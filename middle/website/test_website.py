import csv
from contextlib import closing
import io
import json
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
        self.settings=Settings(root=self.root,values=dict(database='data/db.sqlite3',uploads='uploads/images',model_path='model.pt',device='cpu',max_file_bytes=100000,max_pixels=100000))

    def tearDown(self):self.tmp.cleanup()

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
                feedback=dict(waste='general',residual=label,waste_confirmed=True,residual_confirmed=True)
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

class RealModelTests(unittest.TestCase):
    def test_real_checkpoint_e2e_and_direct_predictor_agree(self):
        # One real original photo only, copied as a web upload. Never runs formal test evaluation.
        source=ROOT/'dataset/paper_cups/Image_30.png'
        with tempfile.TemporaryDirectory(dir=ROOT/'website') as temp:
            settings=Settings(root=Path(temp),values=dict(database='data/db.sqlite3',uploads='uploads/images',model_path=str(ROOT/'training/runs/experiment_v3/stage2_best.pt'),device='cuda'))
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
