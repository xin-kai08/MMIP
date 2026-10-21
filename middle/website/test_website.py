import csv
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
import io
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import threading
import time
import unittest
import uuid
from unittest.mock import patch
from PIL import Image
from fastapi.testclient import TestClient
from website.app import create_app
from website.settings import Settings, ROOT
from website.store import Store
from website.service import Service

def png():
    data=io.BytesIO();Image.new('RGB',(50,40),'white').save(data,'PNG');return data.getvalue()

class TestPredictor:
    """Isolated test double only; production never calls this class."""
    stage='stage2';threshold=.6
    config=dict(waste_classes=['general','glass','food_waste','other_recycling'],residual_classes=['none','food','liquid','not_assessable'],preprocessing='test_fixture_only')
    def __init__(self,gate=None):self.gate=gate
    def predict(self,paths):
        if self.gate:self.gate.wait(15)
        return [dict(waste=dict(label='glass',confidence=.8,low_confidence=False,probabilities=dict(general=.05,glass=.8,food_waste=.05,other_recycling=.1)),
                     residual=dict(label='liquid',confidence=.55,low_confidence=True,probabilities=dict(none=.15,food=.15,liquid=.55,not_assessable=.15)))]

class WebsiteTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=ROOT/'website');self.root=Path(self.tmp.name)
        (self.root/'model.pt').write_bytes(b'test_fixture_only')
        # Explicit overrides keep even a shell with production WASTE_* settings
        # from directing tests into real user data.
        environment=patch.dict(os.environ,{'WASTE_DATABASE':str(self.root/'data/db.sqlite3'),
                              'WASTE_UPLOADS':str(self.root/'uploads/images'),
                              'WASTE_MODEL_PATH':str(self.root/'model.pt'),'WASTE_DEVICE':'cpu'})
        environment.start();self.addCleanup(environment.stop)
        self.settings=Settings(root=self.root,values=dict(database='data/db.sqlite3',uploads='uploads/images',model_path='model.pt',device='cpu',max_file_bytes=100000,max_pixels=100000))
        assert self.settings.path('database').is_relative_to(self.root.resolve())
        assert self.settings.path('uploads').is_relative_to(self.root.resolve())

    def tearDown(self):
        if not self.root.resolve().is_relative_to((ROOT/'website').resolve()):
            raise RuntimeError('Test cleanup outside website workspace')
        # Windows may finish removing SQLite WAL/SHM a moment after connections
        # close. Retry only transient sharing/nonempty errors; never force locks.
        for attempt in range(20):
            try:self.tmp.cleanup();return
            except OSError as e:
                if getattr(e,'winerror',None) not in (32,145) or attempt==19:raise
                time.sleep(.05)

    def client(self,factory=TestPredictor):return TestClient(create_app(self.settings,factory))

    def wait_ready(self,c):
        for _ in range(100):
            r=c.get('/api/health').json()
            if r['model_ready']:return r
            if r['model_error']:raise AssertionError(r)
            time.sleep(.03)
        self.fail('Worker not ready')

    def user(self,c,id='Test2026',nickname='測試者'):
        r=c.post('/api/users',json=dict(id=id,nickname=nickname));self.assertEqual(r.status_code,201,r.text)

    def upload(self,c,files=None,mode='general',annotations=None,key=None):
        metadata=dict(user_id='TEST2026',mode=mode,request_key=key or str(uuid.uuid4()),annotations=annotations or [])
        return c.post('/api/batches',data={'metadata':json.dumps(metadata)},files=files or [('files',('sample.png',png(),'image/png'))])

    def done(self,c,batch):
        for _ in range(200):
            r=c.get(f'/api/batches/{batch}?user_id=test2026').json()
            if r['status'] in ('completed','failed'):return r
            time.sleep(.02)
        self.fail('Batch not completed')

    def test_id_rules_canonical_and_duplicate_nickname(self):
        with self.client() as c:
            for id in ('abc','abcdefghijklmnopqrstu','中文1234','abc def','abcd!',' abcd','abcd\n','ＡＢＣＤ'):
                self.assertEqual(c.get('/api/users/'+id.replace('\n','%0A')).status_code,422,id)
            self.user(c);self.user(c,'Other2026')
            self.assertEqual(c.get('/api/users/TEST2026').json()['user']['id'],'test2026')
            self.assertEqual(c.post('/api/users',json=dict(id='test2026',nickname='別名')).status_code,409)
            self.assertEqual(c.get('/api/users/Missing123').json()['exists'],False)

    def test_mixed_upload_idempotency_history_export_and_delete(self):
        with self.client() as c:
            self.wait_ready(c);self.user(c,nickname='=2+2');key=str(uuid.uuid4())
            files=[('files',('../../escape.png',png(),'image/png')),('files',('=malicious.png',b'not an image','image/png'))]
            created=self.upload(c,files=files,key=key);self.assertEqual(created.status_code,201,created.text)
            b=created.json()['batch_id'];result=self.done(c,b)
            self.assertEqual(sorted(i['status'] for i in result['images']),['completed','failed'])
            self.assertEqual(self.upload(c,files=files,key=key).json()['batch_id'],b)
            self.assertEqual(self.upload(c,key=key).status_code,409)
            self.assertEqual(c.get('/api/batches?user_id=TeSt2026').json()['total'],1)
            good=next(i for i in result['images'] if i['status']=='completed')
            self.assertEqual(c.get(f'/api/images/{good["id"]}/file?user_id=test2026').status_code,200)
            self.assertEqual(c.get(f'/api/images/{good["id"]}/file?user_id=other2026').status_code,404)
            self.assertEqual(len(list(self.settings.path('uploads').glob('*.png'))),1)
            exported=c.get('/api/export.csv?user_id=test2026')
            self.assertTrue(exported.content.startswith(b'\xef\xbb\xbf'))
            parsed=list(csv.DictReader(io.StringIO(exported.content.decode('utf-8-sig'))))
            self.assertTrue(all(r['nickname'].startswith("'") for r in parsed))
            self.assertTrue(next(r for r in parsed if r['filename'].endswith('malicious.png'))['filename'].startswith("'"))
            self.assertEqual(c.delete(f'/api/batches/{b}?user_id=test2026').status_code,400)
            self.assertEqual(c.delete(f'/api/batches/{b}?user_id=test2026&confirm=true').status_code,200)
            self.assertEqual(c.get(f'/api/batches/{b}?user_id=test2026').status_code,404)
            self.assertEqual(list(self.settings.path('uploads').glob('*.png')),[])
            with closing(sqlite3.connect(self.settings.path('database'))) as db:
                for table in ('images','predictions','annotations','file_gc'):self.assertEqual(db.execute(f'SELECT count(*) FROM {table}').fetchone()[0],0)

    def test_pre_truth_immutable_feedback_separate_and_unknown_is_not_label(self):
        with self.client() as c:
            self.wait_ready(c);self.user(c)
            a=dict(waste='glass',residual=None,waste_confirmed=True,residual_confirmed=False)
            response=self.upload(c,mode='evaluation',annotations=[a]);self.assertEqual(response.status_code,201,response.text)
            b=response.json()['batch_id'];r=self.done(c,b);image=r['images'][0];image_id=image['id']
            original=image['annotations'][0];prediction=image['prediction']
            self.assertLessEqual(original['created_at'],image['started_at'] if 'started_at' in image else original['created_at'])
            gt=c.get('/api/stats?user_id=test2026').json()['versions'][0]['tasks']
            self.assertEqual(gt['waste']['accuracy'],1.);self.assertIsNone(gt['residual']['accuracy']);self.assertEqual(gt['residual']['n'],0)
            for label in ('food','liquid'):
                feedback=dict(waste='other_recycling',residual=label,waste_confirmed=True,residual_confirmed=True)
                self.assertEqual(c.post(f'/api/images/{image_id}/annotations?user_id=test2026',json=feedback).status_code,201)
            current=c.get(f'/api/batches/{b}?user_id=test2026').json()['images'][0]
            self.assertEqual(current['prediction'],prediction);self.assertEqual(current['annotations'][0],original)
            self.assertEqual(len(current['annotations']),3)
            self.assertEqual(c.get('/api/stats?user_id=test2026').json()['versions'][0]['tasks']['residual']['n'],0)
            post=c.get('/api/stats?user_id=test2026&source=post_feedback').json()['versions'][0]['tasks']
            self.assertEqual(post['residual']['accuracy'],1.);self.assertEqual(post['waste']['accuracy'],0.)
            with closing(sqlite3.connect(self.settings.path('database'))) as db:
                with self.assertRaises(sqlite3.IntegrityError):db.execute("UPDATE annotations SET waste_label='food_waste' WHERE source='pre_ground_truth'")

    def test_processing_delete_rejected_and_restart_recovers(self):
        gate=threading.Event()
        with self.client(lambda:TestPredictor(gate)) as c:
            self.wait_ready(c);self.user(c)
            response=self.upload(c);b=response.json()['batch_id']
            try:
                for _ in range(100):
                    row=c.get(f'/api/batches/{b}?user_id=test2026').json()['images'][0]
                    if row['status']=='processing':break
                    time.sleep(.01)
                self.assertEqual(c.delete(f'/api/images/{row["id"]}?user_id=test2026&confirm=true').status_code,409)
                self.assertEqual(c.get('/api/health').status_code,200)
            finally:gate.set()
            self.done(c,b)
        with closing(sqlite3.connect(self.settings.path('database'))) as db:
            db.execute('DELETE FROM predictions');db.execute("UPDATE images SET status='processing'");db.execute("UPDATE batches SET status='processing'")
            db.commit()
        orphan=self.settings.path('uploads')/(str(uuid.uuid4())+'.png');orphan.write_bytes(png())
        with self.client() as c:
            self.wait_ready(c);recovered=self.done(c,b)
            self.assertEqual(recovered['images'][0]['status'],'completed');self.assertFalse(orphan.exists())

    def test_feedback_noop_revisions_confirmation_and_retry(self):
        with self.client() as c:
            self.wait_ready(c);self.user(c)
            batch=self.upload(c).json()['batch_id'];image=self.done(c,batch)['images'][0]
            url=f'/api/images/{image["id"]}/annotations?user_id=test2026'
            a=dict(waste='glass',residual='none',waste_confirmed=True,residual_confirmed=True)
            # A failed write must roll back, retain the draft client-side, and allow retry.
            with patch('website.app.annotation_insert',side_effect=sqlite3.OperationalError('temporary write failure')):
                with self.assertRaises(sqlite3.OperationalError):c.post(url,json=a)
            self.assertEqual(c.get(f'/api/batches/{batch}?user_id=test2026').json()['images'][0]['annotations'],[])
            first=c.post(url,json=a);self.assertEqual(first.status_code,201)
            previous=first.json();self.assertTrue(previous['changed'])
            for _ in range(3):
                duplicate=c.post(url,json=a);self.assertEqual(duplicate.status_code,200)
                self.assertEqual(duplicate.json(),dict(previous,changed=False))
            changes=[dict(a,residual='food'),a,dict(a,waste_confirmed=False),
                     dict(a,waste_confirmed=False,residual_confirmed=False),a]
            for content in changes:
                result=c.post(url,json=content);self.assertEqual(result.status_code,201)
                current=result.json();self.assertTrue(current['changed'])
                self.assertEqual(current['previous_id'],previous['id']);previous=current
            current=c.get(f'/api/batches/{batch}?user_id=test2026').json()['images'][0]
            self.assertEqual(len(current['annotations']),6)
            self.assertEqual(current['prediction'],image['prediction'])
            self.assertEqual(c.get('/api/stats?user_id=test2026&source=post_feedback').json()['versions'][0]['tasks']['waste']['n'],1)

    def test_concurrent_duplicate_feedback_has_one_revision(self):
        with self.client() as c:
            self.wait_ready(c);self.user(c)
            batch=self.upload(c).json()['batch_id'];image=self.done(c,batch)['images'][0]
            url=f'/api/images/{image["id"]}/annotations?user_id=test2026'
            answer=dict(waste='glass',residual='liquid',waste_confirmed=True,residual_confirmed=True)
            for content in (answer,dict(answer,residual='food')):
                barrier=threading.Barrier(12)
                def submit(_):
                    barrier.wait(timeout=10)
                    return c.post(url,json=content)
                with ThreadPoolExecutor(max_workers=12) as pool:responses=list(pool.map(submit,range(12)))
                self.assertEqual(sum(r.status_code==201 for r in responses),1)
                self.assertEqual(sum(r.status_code==200 for r in responses),11)
                self.assertEqual(sum(r.json()['changed'] for r in responses),1)
                self.assertEqual(len({r.json()['id'] for r in responses}),1)
                self.assertEqual(len({r.json()['created_at'] for r in responses}),1)
            current=c.get(f'/api/batches/{batch}?user_id=test2026').json()['images'][0]
            self.assertEqual(len(current['annotations']),2)

    def test_legacy_duplicates_count_once_sources_locked_and_csv_versions(self):
        with self.client() as c:
            self.wait_ready(c);self.user(c)
            pre=dict(waste='glass',residual=None,waste_confirmed=True,residual_confirmed=False)
            batch=self.upload(c,mode='evaluation',annotations=[pre]).json()['batch_id']
            image=self.done(c,batch)['images'][0];image_id=image['id']
            url=f'/api/images/{image_id}/annotations?user_id=test2026'
            answer=dict(waste='other_recycling',residual='food',waste_confirmed=True,residual_confirmed=True)
            first=c.post(url,json=answer).json()
            # Preserve an identical legacy row, as if it had been saved by the old API.
            from website.app import annotation_insert
            from website.schemas import Annotation
            with Store(self.settings.path('database')).connect(True) as db:
                annotation_insert(db,image_id,Annotation(**answer),'post_feedback','test2026',first['id'])
                legacy_id=db.execute('SELECT last_insert_rowid()').fetchone()[0]
            noop=c.post(url,json=answer).json();self.assertFalse(noop['changed']);self.assertEqual(noop['id'],legacy_id)
            self.assertEqual(c.post(url+'&source=pre_ground_truth',json=answer).status_code,422)
            self.assertEqual(c.post(url,json=dict(answer,source='pre_ground_truth')).status_code,422)
            self.assertEqual(c.put(url,json=answer).status_code,405)
            def tasks(source):return c.get('/api/stats?user_id=test2026&source='+source).json()['versions'][0]['tasks']
            gt=tasks('pre_ground_truth');post=tasks('post_feedback')
            self.assertEqual((gt['waste']['n'],gt['residual']['n']),(1,0))
            self.assertEqual((post['waste']['n'],post['residual']['n']),(1,1))
            # The latest snapshot withdrawing confirmation must not resurrect an older answer.
            self.assertTrue(c.post(url,json=dict(answer,waste_confirmed=False)).json()['changed'])
            self.assertEqual((tasks('post_feedback')['waste']['n'],tasks('post_feedback')['residual']['n']),(0,1))
            self.assertEqual(tasks('pre_ground_truth'),gt)
            current=c.get(f'/api/batches/{batch}?user_id=test2026').json()['images'][0]
            self.assertEqual(current['annotations'][0],image['annotations'][0])
            self.assertEqual(current['prediction'],image['prediction'])
            self.assertEqual(len(current['annotations']),4)
            export=c.get('/api/export.csv?user_id=test2026&batch_id='+batch)
            self.assertTrue(export.content.startswith(b'\xef\xbb\xbf'))
            rows=list(csv.DictReader(io.StringIO(export.content.decode('utf-8-sig'))))
            self.assertEqual(len(rows),4)
            self.assertEqual([r['annotation_source'] for r in rows],['pre_ground_truth']+['post_feedback']*3)
            self.assertEqual(rows[-1]['previous_annotation_id'],str(legacy_id))

    def test_invalid_metadata_limits_empty_statistics_and_missing_model(self):
        with self.client() as c:
            self.wait_ready(c);self.user(c)
            self.assertEqual(c.get('/api/stats?user_id=test2026').json()['versions'],[])
            self.assertEqual(self.upload(c,mode='evaluation').status_code,422)
            self.assertEqual(self.upload(c,files=[('files',('big.png',b'a'*100001,'image/png'))]).status_code,201)
            body=self.done(c,c.get('/api/batches?user_id=test2026').json()['items'][0]['id']);self.assertEqual(body['status'],'failed')
            self.assertEqual(c.post('/api/users',json=dict(id='badID',nickname=' ')).status_code,422)
        def fail():raise RuntimeError('missing checkpoint fixture')
        with self.client(fail) as c:
            for _ in range(100):
                h=c.get('/api/health').json()
                if h['model_error']:break
                time.sleep(.01)
            self.assertFalse(h['model_ready']);self.assertEqual(self.upload(c).status_code,503)

    def test_linked_residual_validation_for_both_annotation_sources(self):
        with self.client() as c:
            self.wait_ready(c);self.user(c)
            batch=self.upload(c).json()['batch_id'];image=self.done(c,batch)['images'][0]
            url=f'/api/images/{image["id"]}/annotations?user_id=test2026'
            for waste in ('general','food_waste'):
                for residual in ('none','food','liquid'):
                    for confirmed in (False,True):
                        answer=dict(waste=waste,residual=residual,waste_confirmed=False,residual_confirmed=confirmed)
                        self.assertEqual(c.post(url,json=answer).status_code,422)
                        self.assertEqual(self.upload(c,mode='evaluation',annotations=[answer]).status_code,422)
                for residual,confirmed in ((None,False),('not_assessable',False),('not_assessable',True)):
                    answer=dict(waste=waste,residual=residual,waste_confirmed=False,residual_confirmed=confirmed)
                    self.assertEqual(c.post(url,json=answer).status_code,201)
                    response=self.upload(c,mode='evaluation',annotations=[answer]);self.assertEqual(response.status_code,201)
                    saved=self.done(c,response.json()['batch_id'])['images'][0]['annotations'][0]
                    self.assertEqual(saved['residual_label'],residual);self.assertEqual(bool(saved['residual_confirmed']),confirmed)
                    tasks=c.get('/api/stats?user_id=test2026&batch_id='+response.json()['batch_id']).json()['versions'][0]['tasks']
                    self.assertEqual(tasks['residual']['n'],int(confirmed))
                    self.assertEqual(tasks['waste']['n'],0)
            for waste in ('glass','other_recycling'):
                for residual in ('none','food','liquid','not_assessable',None):
                    answer=dict(waste=waste,residual=residual,waste_confirmed=True,residual_confirmed=False)
                    self.assertEqual(c.post(url,json=answer).status_code,201)
            # Either task can remain unknown/unconfirmed, independently.
            for answer in (dict(waste=None,residual='liquid',residual_confirmed=True),
                           dict(waste='glass',residual=None,waste_confirmed=True)):
                self.assertEqual(c.post(url,json=answer).status_code,201)
            for answer in (dict(waste='general',residual=None,residual_confirmed=True),
                           dict(waste='glass',residual=None,residual_confirmed=True),
                           dict(waste=None,residual='none',waste_confirmed=True)):
                self.assertEqual(c.post(url,json=answer).status_code,422)

    def test_legacy_incompatible_records_readable_and_gt_remains_locked(self):
        with self.client() as c:
            self.wait_ready(c);self.user(c)
            batch=self.upload(c).json()['batch_id'];image=self.done(c,batch)['images'][0]
            from website.app import annotation_insert
            from website.schemas import Annotation
            # Construct historical fixtures directly; validation applies only to new submissions.
            old=Annotation.model_construct(waste='general',residual='food',waste_confirmed=True,residual_confirmed=True)
            with Store(self.settings.path('database')).connect(True) as db:
                db.execute("UPDATE batches SET mode='evaluation' WHERE id=?",(batch,))
                annotation_insert(db,image['id'],old,'pre_ground_truth','test2026')
                annotation_insert(db,image['id'],old,'post_feedback','test2026')
            original=c.get(f'/api/batches/{batch}?user_id=test2026').json()['images'][0]
            self.assertEqual([a['residual_label'] for a in original['annotations']],['food','food'])
            url=f'/api/images/{image["id"]}/annotations?user_id=test2026'
            self.assertEqual(c.post(url,json=old.model_dump()).status_code,422)
            corrected=dict(waste='general',residual='not_assessable',waste_confirmed=True,residual_confirmed=False)
            saved=c.post(url,json=corrected);self.assertEqual(saved.status_code,201)
            self.assertFalse(c.post(url,json=corrected).json()['changed'])
            result=c.get(f'/api/batches/{batch}?user_id=test2026').json()['images'][0]
            self.assertEqual(result['annotations'][:2],original['annotations'])
            self.assertEqual(result['prediction'],image['prediction'])
            with Store(self.settings.path('database')).connect(True) as db:
                with self.assertRaises(sqlite3.IntegrityError):
                    db.execute("UPDATE annotations SET residual_label='not_assessable' WHERE source='pre_ground_truth'")

class RealModelTests(unittest.TestCase):
    def test_real_checkpoint_e2e_and_direct_predictor_agree(self):
        # One real original photo only, copied as a web upload. Never runs formal test evaluation.
        source=ROOT/'dataset/paper_cups/Image_30.png'
        with tempfile.TemporaryDirectory(dir=ROOT/'website') as temp:
            with patch.dict(os.environ,{'WASTE_DATABASE':str(Path(temp)/'data/db.sqlite3'),
                            'WASTE_UPLOADS':str(Path(temp)/'uploads/images'),
                            'WASTE_MODEL_PATH':str(ROOT/'training/runs/experiment_v3/stage2_best.pt'),'WASTE_DEVICE':'cuda'}):
                settings=Settings(root=Path(temp))
            app=create_app(settings)
            with TestClient(app) as c:
                for _ in range(500):
                    health=c.get('/api/health').json()
                    if health['model_ready']:break
                    if health['model_error']:self.fail(health['model_error'])
                    time.sleep(.05)
                self.assertTrue(health['model_ready']);c.post('/api/users',json={'id':'Real2026','nickname':'真實模型驗證'})
                meta=dict(user_id='real2026',mode='evaluation',request_key=str(uuid.uuid4()),annotations=[dict(waste=None,residual=None)])
                response=c.post('/api/batches',data={'metadata':json.dumps(meta)},files=[('files',(source.name,source.read_bytes(),'image/png'))]);self.assertEqual(response.status_code,201,response.text)
                batch=response.json()['batch_id']
                for _ in range(500):
                    result=c.get(f'/api/batches/{batch}?user_id=real2026').json()
                    if result['status'] in ('completed','failed'):break
                    time.sleep(.02)
                self.assertEqual(result['status'],'completed',result)
                p=result['images'][0]['prediction']
                direct=app.state.service.predictor.predict([source])[0]
                self.assertEqual(p['waste_label'],direct['waste']['label']);self.assertEqual(p['residual_label'],direct['residual']['label'])
                self.assertAlmostEqual(p['waste_confidence'],direct['waste']['confidence'],places=6)
                self.assertAlmostEqual(p['residual_confidence'],direct['residual']['confidence'],places=6)

if __name__=='__main__':unittest.main()
