"""Safety/continuation regression tests using disposable synthetic fixtures."""
import contextlib
import csv
import hashlib
import io
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from PIL import Image
import waste_workflow as w

class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.workspace=w.ROOT.resolve()
        self.tmp=tempfile.TemporaryDirectory(dir=w.ROOT)
        self.root=Path(self.tmp.name)
        self.ps=[patch.object(w,'ROOT',self.root),patch.object(w,'DATA',self.root/'dataset'),
                 patch.object(w,'WORK',self.root/'state'),patch.object(w,'LABELS',self.root/'labels.csv')]
        for p in self.ps:p.start()
        w.DATA.mkdir();w.WORK.mkdir()
    def tearDown(self):
        for p in reversed(self.ps):p.stop()
        assert self.root.resolve().is_relative_to(self.workspace)
        for attempt in range(10):
            try:self.tmp.cleanup();break
            except OSError as e:
                if getattr(e,'winerror',None) not in (32,145) or attempt==9:raise
                time.sleep(.05)
    def pic(self,rel,color='white'):
        p=w.DATA/rel;p.parent.mkdir(parents=True,exist_ok=True)
        Image.new('RGB',(32,24),color).save(p);return p
    def quiet(self,fn,*a,**kw):
        with contextlib.redirect_stdout(io.StringIO()):return fn(*a,**kw)
    def test_rescan_preserves_manual_labels_bom_and_unknown_folder(self):
        original=self.pic('paper_cups/a.png');before=original.read_bytes()
        self.pic('unknown_category/b.png','blue');(w.DATA/'paper_cups'/'bad.png').write_bytes(b'not an image')
        self.quiet(w.scan)
        self.quiet(w.annotate,[{'image_path':'paper_cups/a.png','residual':'liquid','residual_applicable':'yes','review_status':'approved','notes':'human label'}])
        first=w.read_labels();self.quiet(w.scan);second=w.read_labels()
        self.assertEqual(first,second);self.assertEqual(original.read_bytes(),before)
        self.assertTrue(w.LABELS.read_bytes().startswith(b'\xef\xbb\xbf'))
        unknown=next(r for r in second if r['folder']=='unknown_category')
        self.assertEqual(unknown['waste_class'],'');self.assertEqual(unknown['residual'],'')
        self.assertEqual(next(r for r in second if r['filename']=='bad.png')['review_status'],'excluded')
    def test_exact_duplicates_and_seed_reproducible(self):
        a=self.pic('paper_cups/a.png');b=w.DATA/'paper_cups'/'b.png';b.write_bytes(a.read_bytes())
        self.pic('glass_beverage_bottles/c.png','blue');self.pic('plastic_food_containers/d.png','green')
        self.quiet(w.scan);rows=w.read_labels();by={r['image_path']:r for r in rows}
        self.assertEqual(by['paper_cups/a.png']['group_id'],by['paper_cups/b.png']['group_id'])
        self.assertEqual(by['paper_cups/a.png']['split'],by['paper_cups/b.png']['split'])
        inv=w.read_json(w.WORK/'inventory.json',{});w.regroup(rows,inv,reset=True);result={r['image_path']:r['split'] for r in rows}
        for r in rows:r['split']=''
        w.regroup(rows,inv,reset=True);self.assertEqual(result,{r['image_path']:r['split'] for r in rows})
        self.quiet(w.decide,'paper_cups/a.png','glass_beverage_bottles/c.png','same')
        by={r['image_path']:r for r in w.read_labels()}
        self.assertEqual(by['paper_cups/b.png']['group_id'],by['glass_beverage_bottles/c.png']['group_id'])
    def test_reservation_collision_exclusive_copy_and_resume(self):
        source=self.pic('paper_cups/source.png');existing=self.pic('paper_cups/Image_251.png','blue');before=existing.read_bytes()
        self.quiet(w.scan)
        self.quiet(w.annotate,[{'image_path':'paper_cups/source.png','residual':'none','residual_applicable':'yes','review_status':'approved','generation_candidate':'eligible'}])
        self.quiet(w.plan);tasks=w.read_json(w.WORK/'generation_tasks.json',[]);tid=tasks[0]['task_id']
        self.quiet(w.reserve,tid);tasks,t=w.get_task(tid);self.assertEqual(t['output_path'],'paper_cups/Image_252.png')
        with self.assertRaises(ValueError):self.quiet(w.reserve,tid)
        output=self.root/'output.png';Image.new('RGB',(50,50),'red').save(output)
        self.quiet(w.complete,tid,str(output));out=w.image_path(t['output_path']);saved=out.read_bytes()
        self.quiet(w.complete,tid,str(output));self.assertEqual(out.read_bytes(),saved);self.assertEqual(existing.read_bytes(),before)
        rows={r['image_path']:r for r in w.read_labels()};gen=rows[t['output_path']];orig=rows['paper_cups/source.png']
        self.assertEqual(gen['origin'],'generated');self.assertEqual(gen['source_id'],orig['source_id'])
        self.assertEqual(gen['group_id'],orig['group_id']);self.assertEqual(gen['split'],orig['split'])
        self.assertEqual(gen['residual'],'');self.assertEqual(gen['review_status'],'pending')
    def test_recover_copy_completed_before_success_log(self):
        source=self.pic('glass_beverage_bottles/source.png');self.quiet(w.scan)
        self.quiet(w.annotate,[{'image_path':'glass_beverage_bottles/source.png','residual':'none','residual_applicable':'yes','review_status':'approved','generation_candidate':'eligible'}])
        self.quiet(w.plan);tid=w.read_json(w.WORK/'generation_tasks.json',[])[0]['task_id'];self.quiet(w.reserve,tid)
        tasks,t=w.get_task(tid);out=self.pic(t['output_path'],'orange');t['output_sha256']=hashlib.sha256(out.read_bytes()).hexdigest()
        w.atomic_json(w.WORK/'generation_tasks.json',tasks);self.quiet(w.recover)
        self.assertEqual(w.get_task(tid)[1]['status'],'success')
        self.assertEqual(next(r for r in w.read_labels() if r['image_path']==t['output_path'])['origin'],'generated')
    def test_balance_counts_only_approved_canonical_originals(self):
        a=self.pic('paper_cups/a.png');(a.parent/'b.png').write_bytes(a.read_bytes());self.pic('paper_cups/c.png','blue')
        self.quiet(w.scan)
        self.quiet(w.annotate,[{'image_path':'paper_cups/'+n+'.png','residual':'none','residual_applicable':'yes','review_status':'approved'} for n in ('a','b')])
        import csv
        with (w.WORK/'reports'/'balance.csv').open(encoding='utf-8-sig') as f:b=next(r for r in csv.DictReader(f) if r['folder']=='paper_cups')
        self.assertEqual(b['original_none'],'1');self.assertEqual(b['final_add_residual'],'')

    def test_reviewed_unknown_no_and_mixed_are_not_residual_training(self):
        for name,color in [('unknown','white'),('na','blue'),('mixed','green'),('food','red')]:self.pic('paper_cups/'+name+'.png',color)
        self.quiet(w.scan)
        self.quiet(w.annotate,[
            {'image_path':'paper_cups/unknown.png','review_status':'approved','residual_applicable':'unknown','residual':'','notes':'inside hidden'},
            {'image_path':'paper_cups/na.png','review_status':'approved','residual_applicable':'no','residual':'','notes':'non-container'},
            {'image_path':'paper_cups/mixed.png','review_status':'approved','residual_applicable':'yes','residual':'','notes':'mixed food and liquid'},
            {'image_path':'paper_cups/food.png','review_status':'approved','residual_applicable':'yes','residual':'food'},
        ])
        rows=w.read_labels();self.assertTrue(all(r['review_status']=='approved' for r in rows))
        self.assertEqual(sum(w.residual_usable(r) for r in rows),1)
        with (w.WORK/'reports'/'residual_training_manifest.csv').open(encoding='utf-8-sig') as f:usable=list(csv.DictReader(f))
        self.assertEqual([r['filename'] for r in usable],['food.png'])
        with (w.WORK/'reports'/'balance.csv').open(encoding='utf-8-sig') as f:b=next(r for r in csv.DictReader(f) if r['folder']=='paper_cups')
        self.assertEqual(b['original_none'],'0');self.assertEqual(b['original_residual'],'1')

    def test_eligible_requires_confirmed_empty_and_approved_before_queue(self):
        self.pic('paper_cups/a.png');self.quiet(w.scan)
        with self.assertRaises(ValueError):self.quiet(w.annotate,[{'image_path':'paper_cups/a.png','generation_candidate':'eligible'}])
        self.quiet(w.annotate,[{'image_path':'paper_cups/a.png','residual_applicable':'yes','residual':'none','generation_candidate':'eligible'}])
        self.quiet(w.plan);self.assertEqual(w.read_json(w.WORK/'generation_tasks.json',[]),[])
        self.quiet(w.annotate,[{'image_path':'paper_cups/a.png','review_status':'approved'}]);self.quiet(w.plan)
        tid=w.read_json(w.WORK/'generation_tasks.json',[])[0]['task_id']
        self.quiet(w.annotate,[{'image_path':'paper_cups/a.png','residual':'liquid','generation_candidate':'exclude'}])
        with self.assertRaises(ValueError):self.quiet(w.reserve,tid)

    def test_unjustified_blank_yes_not_forced_to_none(self):
        self.pic('paper_cups/a.png');self.quiet(w.scan)
        with self.assertRaises(ValueError):self.quiet(w.annotate,[{'image_path':'paper_cups/a.png','review_status':'approved','residual_applicable':'yes','residual':'','notes':'unsure'}])
        self.quiet(w.annotate,[{'image_path':'paper_cups/a.png','review_status':'approved','residual_applicable':'unknown','residual':''}])
        self.assertEqual(w.read_labels()[0]['residual'],'')

    def test_balance_deduplicates_sources_and_waits_for_saved_pending_outputs(self):
        self.pic('styrofoam_food_containers/Image_9.png')
        self.pic('styrofoam_food_containers/duplicate.png')
        self.pic('styrofoam_food_containers/other.png','blue')
        self.quiet(w.scan)
        self.quiet(w.annotate,[dict(image_path=r['image_path'],residual='none',residual_applicable='yes',review_status='approved',generation_candidate='eligible') for r in w.read_labels()])
        before={r['image_path']:r['group_id'] for r in w.read_labels()}
        self.quiet(w.plan,'balance')
        tasks=w.read_json(w.WORK/'generation_tasks.json',[])
        self.assertEqual(len(tasks),2)
        self.assertEqual(len({before[t['source_path']] for t in tasks}),2)
        for t in tasks:
            self.quiet(w.reserve,t['task_id'])
            output=self.root/(t['task_id']+'.png')
            Image.new('RGB',(50,50),'red' if t==tasks[0] else 'orange').save(output)
            self.quiet(w.complete,t['task_id'],str(output))
        for r in w.read_labels():
            if r['origin']=='original':self.assertEqual(r['group_id'],before[r['image_path']])
        self.quiet(w.plan,'balance')
        self.assertEqual(len(w.read_json(w.WORK/'generation_tasks.json',[])),2)

if __name__=='__main__':unittest.main()
