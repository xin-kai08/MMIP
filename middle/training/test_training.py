"""Data/metrics tests run without torch; model tests require an installed stack."""
import copy
import importlib.util
import random
import unittest
import tempfile
import shutil
from pathlib import Path
from unittest.mock import patch
from collections import defaultdict
import data as d
from metrics import classification_metrics

def row(path='paper_cups/a.png',**kwargs):
    r=dict(image_path=path,folder='paper_cups',origin='original',source_id='paper_cups:'+path,group_id=path,
           split='train',waste_class='other_recycling',review_status='approved',residual_applicable='unknown',residual='',notes='')
    r.update(kwargs);return r

class DataTests(unittest.TestCase):
    def test_frozen_manifest_reuses_partition_and_never_changes_labels(self):
        from PIL import Image
        root=Path(tempfile.mkdtemp(dir=d.ROOT))
        try:
            labels=root/'dataset/labels.csv';labels.parent.mkdir()
            rows=[row(f'paper_cups/{i}.png',group_id=f'g{i}',split=('train','val','test')[i%3],residual_applicable='yes',residual='none') for i in range(9)]
            for r in rows:
                path=labels.parent/r['image_path'];path.parent.mkdir(exist_ok=True)
                Image.new('RGB',(16,16),'white').save(path)
            d.write_csv(labels,rows);original=labels.read_bytes()
            with patch.object(d,'ROOT',root),patch.object(d,'LABELS',labels),patch.object(d,'DATA',labels.parent),patch.object(d,'STATE',root/'state'):
                a=d.prepare('v1');partition=(a/'partition.json').read_bytes();manifest=(a/'manifest.csv').read_bytes()
                self.assertEqual(d.prepare('v1'),a)
                self.assertEqual((a/'manifest.csv').read_bytes(),manifest)
                b=d.prepare('v2',a/'partition.json')
                self.assertEqual((b/'partition.json').read_bytes(),partition)
                self.assertEqual(labels.read_bytes(),original)
                rows[0]['notes']='human changed';d.write_csv(labels,rows)
                with self.assertRaises(ValueError):d.verify(a)
                with self.assertRaises(ValueError):d.prepare('v1')
        finally:
            assert root.resolve().is_relative_to(d.ROOT.resolve())
            shutil.rmtree(root)

    def test_explicit_label_mapping(self):
        for i,label in enumerate(d.RESIDUAL[:3]):self.assertEqual(d.residual_target(row(residual_applicable='yes',residual=label))[0],i)
        self.assertEqual(d.residual_target(row(residual_applicable='no'))[0],3)
        self.assertEqual(d.residual_target(row(residual_applicable='no',residual='food'))[0],-1)
        self.assertEqual(d.residual_target(row(residual_applicable='yes',residual=''))[0],-1)

    def test_unknown_needs_confirmed_structured_reason_not_free_text(self):
        r=row(notes='interior not visible; cannot assess')
        self.assertEqual(d.residual_target(r)[0],-1)
        q=dict(decision='confirmed',reason='interior_not_visible',reviewer='human',evidence='existing review entry 23',label_fingerprint=d.fingerprint(r))
        self.assertEqual(d.residual_target(r,q)[0],3)
        for key,value in [('decision','pending'),('reason','mixed'),('reviewer',''),('evidence',''),('label_fingerprint','old')]:
            bad=q.copy();bad[key]=value;self.assertEqual(d.residual_target(r,bad)[0],-1)

    def test_pending_generated_prompt_never_becomes_a_label(self):
        for status in ('pending','excluded'):
            r=row(origin='generated',review_status=status,residual_applicable='yes',residual='food')
            self.assertEqual(d.residual_target(r)[0],-1)

    def test_group_integrity_and_no_eval_stage(self):
        a=row(group_id='g');b=row('paper_cups/b.png',group_id='g',split='test')
        with self.assertRaises(ValueError):d.check_groups([a,b])
        with self.assertRaises(ValueError):d.check_groups([row(split='val',stage='stage1')])
        a['stage']='stage1';b.update(split='train',stage='stage2')
        with self.assertRaises(ValueError):d.check_groups([a,b])
        with self.assertRaises(ValueError):d.check_groups([row(origin='generated')])
        with patch.object(d,'read_csv',return_value=[{'a':a['image_path'],'b':b['image_path']}]),patch.object(Path,'exists',return_value=True),patch.object(d,'read_json',return_value=[]):
            a['group_id']='a';b['group_id']='b'
            with self.assertRaises(ValueError):d.check_confirmed_duplicates([a,b])

    def test_stages_deterministic_balanced_and_keep_source_versions(self):
        rows=[row(f'paper_cups/{i}.png',group_id=f'g{i}',residual_applicable='yes',residual=('none','food','liquid')[i%3]) for i in range(80)]
        rows += [row(f'paper_cups/gen{i}.png',group_id=f'g{i}',origin='generated') for i in range(0,30,3)]
        a=d.assign_stages(rows);random.Random(99).shuffle(rows);b=d.assign_stages(rows)
        self.assertEqual(a,b)
        counts=defaultdict(int)
        for r in rows:r['stage']=a[r['group_id']];counts[r['stage']]+=1
        self.assertLessEqual(abs(counts['stage1']-counts['stage2']),4)
        self.assertEqual(len(a),80)

    def test_metrics_zero_support_and_separate_food_waste(self):
        m=classification_metrics([0,0,1],[0,1,1],d.WASTE,3.)
        self.assertEqual(m['n'],3);self.assertAlmostEqual(m['accuracy'],2/3)
        self.assertAlmostEqual(m['macro_f1'],1/3)
        self.assertEqual(m['per_class'][2]['support'],0)
        self.assertNotEqual(d.WASTE[2],d.RESIDUAL[1])

HAS_TORCH=all(importlib.util.find_spec(n) for n in ('torch','torchvision'))
@unittest.skipUnless(HAS_TORCH,'PyTorch/TorchVision not installed; no model/GPU validation claimed')
class ModelTests(unittest.TestCase):
    def test_epoch_resume_reproduces_uninterrupted_optimizer_and_weights(self):
        import torch
        import engine
        from model import WasteModel
        from PIL import Image
        torch.set_num_threads(2)
        root=Path(tempfile.mkdtemp(dir=d.ROOT))
        class Tiny(torch.nn.Module):
            # Test checkpoint/loop behavior cheaply, independent of architecture test.
            def __init__(self,dropout=.2,**kwargs):
                super().__init__();self.features=torch.nn.Sequential(torch.nn.Conv2d(3,4,1),torch.nn.AdaptiveAvgPool2d(1))
                self.waste_head=torch.nn.Sequential(torch.nn.Dropout(dropout),torch.nn.Linear(4,4))
                self.residual_head=torch.nn.Sequential(torch.nn.Dropout(dropout),torch.nn.Linear(4,4))
            def forward(self,x):
                f=self.features(x).flatten(1);return self.waste_head(f),self.residual_head(f)
            stage=WasteModel.stage
        try:
            folder=root/'manifest';folder.mkdir();dataset=root/'dataset';dataset.mkdir()
            config=d.read_json(d.ROOT/'config.json');config.update(device='cpu',batch_size=4,max_epochs=2)
            rows=[]
            for i in range(16):
                name=f'{i}.png';Image.new('RGB',(24,24),(i*17,90,200)).save(dataset/name)
                rows.append(dict(image_path=name,origin='original',group_id=f'g{i}',split='test' if i>=12 else 'val' if i>=8 else 'train',stage='' if i>=8 else 'stage2' if i>=4 else 'stage1',waste_target=i%4,residual_target=i%4))
            d.write_csv(folder/'manifest.csv',rows);d.write_json(folder/'metadata.json',{'manifest_sha256':d.sha((folder/'manifest.csv').read_bytes())})
            d.write_json(folder/'smoke.json',dict(status='passed',device='cuda',config_sha256=engine.config_hash(config),manifest_sha256=d.sha((folder/'manifest.csv').read_bytes()),test_fixture_only=True))
            with patch.object(d,'DATA',dataset),patch.object(d,'verify',return_value={'ready':True}),patch.object(engine,'WasteModel',Tiny):
                engine.train(folder,root/'continuous','stage1',config)
                original_save=engine.save_torch
                def interrupt_after_epoch(path,payload):
                    original_save(path,payload)
                    if Path(path).name=='stage1_last.pt' and payload['epoch']==1:raise KeyboardInterrupt()
                with patch.object(engine,'save_torch',side_effect=interrupt_after_epoch):
                    with self.assertRaises(KeyboardInterrupt):engine.train(folder,root/'resumed','stage1',config)
                engine.train(folder,root/'resumed','stage1',config,resume=root/'resumed/stage1_last.pt')
                a=engine.load_checkpoint(root/'continuous/stage1_last.pt');b=engine.load_checkpoint(root/'resumed/stage1_last.pt')
                self.assertEqual(a['epoch'],b['epoch']);self.assertEqual(a['bad_epochs'],b['bad_epochs'])
                self.assertTrue(all(torch.equal(a['model'][k],b['model'][k]) for k in a['model']))
                for key in ('training_loss','selection_metric','waste_drop_percentage_points','bad_epochs','learning_rates'):
                    self.assertEqual(a['history'][-1][key],b['history'][-1][key])
                for k,state in a['optimizer']['state'].items():
                    for key,value in state.items():self.assertTrue(torch.equal(value,b['optimizer']['state'][k][key]))
                # A constant validation score stops after first improvement + 5 misses.
                config['max_epochs']=10
                d.write_json(folder/'smoke.json',dict(status='passed',device='cuda',config_sha256=engine.config_hash(config),manifest_sha256=d.sha((folder/'manifest.csv').read_bytes()),test_fixture_only=True))
                fixed_metrics={origin:{task:dict(macro_f1=.25) for task in ('waste','residual')} for origin in ('all','original','generated')}
                with patch.object(engine,'evaluate_rows',return_value=(fixed_metrics,[])):
                    engine.train(folder,root/'early','stage1',config)
                    first_hash=d.sha((root/'early/stage1_best.pt').read_bytes())
                    first=engine.load_checkpoint(root/'early/stage1_best.pt')
                    engine.train(folder,root/'early','stage2',config,from_stage1=root/'early/stage1_best.pt')
                    self.assertEqual(first_hash,d.sha((root/'early/stage1_best.pt').read_bytes()))
                    for stage in ('stage1','stage2'):
                        last=engine.load_checkpoint(root/f'early/{stage}_last.pt')
                        self.assertEqual(last['epoch'],6);self.assertEqual(last['bad_epochs'],5)
                        self.assertEqual(engine.load_checkpoint(root/f'early/{stage}_best.pt')['epoch'],1)
                    second=engine.load_checkpoint(root/'early/stage2_last.pt')
                    self.assertTrue(all(torch.equal(v,second['model'][k]) for k,v in first['model'].items() if k.startswith('waste_head')))
                    self.assertTrue(all(float(v['step'])==6 for v in second['optimizer']['state'].values()))
                engine.final_evaluation(folder,root/'early',device='cpu')
                with self.assertRaises(RuntimeError):engine.final_evaluation(folder,root/'early',device='cpu')
                pred=engine.Predictor(root/'early/stage2_best.pt',device='cpu',confidence_threshold=1.)
                images=[dataset/'12.png',dataset/'13.png'];self.assertEqual(pred.predict(images),pred.predict(images))
                self.assertTrue(all(r['waste']['low_confidence'] for r in pred.predict(images)))
        finally:
            assert root.resolve().is_relative_to(d.ROOT.resolve());shutil.rmtree(root)

    def test_dimensions_mask_freezing_and_checkpoint_roundtrip(self):
        import torch
        from model import WasteModel,masked_loss,seed_all
        import engine
        seed_all(42);torch.set_num_threads(2)
        model=WasteModel();x=torch.rand(2,3,224,224)
        targets=torch.tensor([1,-1])
        logits=torch.tensor([[1.,2.,3.,4.],[4.,3.,2.,1.]],requires_grad=True)
        loss=masked_loss(logits,targets);loss.backward()
        self.assertTrue(torch.equal(logits.grad[1],torch.zeros(4)))
        self.assertIsNone(masked_loss(logits,torch.tensor([-1,-1])))
        for stage in ('stage1','stage2'):
            config=dict(backbone_lr=1e-5,head_lr=1e-4,weight_decay=0.,amp=False)
            op,sc=engine.optimizer_for(model,stage,config)
            before={n:p.detach().clone() for n,p in model.named_parameters()}
            out=model(x);self.assertEqual(tuple(out[0].shape),(2,4));self.assertEqual(tuple(out[1].shape),(2,4))
            engine.step(model,x,torch.tensor([0,1]),targets,stage,op,torch.amp.GradScaler('cuda',enabled=False),config)
            frozen='residual_head' if stage=='stage1' else 'waste_head'
            active='waste_head' if stage=='stage1' else 'residual_head'
            changed=[n for n,p in model.named_parameters() if not torch.equal(p,before[n])]
            self.assertFalse(any(n.startswith(frozen) for n in changed))
            self.assertTrue(any(n.startswith(active) for n in changed));self.assertTrue(any(n.startswith('features') for n in changed))
        model.eval();restored=WasteModel();restored.load_state_dict(copy.deepcopy(model.state_dict()));restored.eval()
        with torch.no_grad():self.assertTrue(all(torch.equal(a,b) for a,b in zip(model(x),restored(x))))

if __name__=='__main__':unittest.main()
