"""Training, short GPU verification, checkpointing, evaluation and inference."""
from __future__ import annotations
import os
os.environ.setdefault('CUBLAS_WORKSPACE_CONFIG', ':4096:8')
import copy
import json
import random
import time
from pathlib import Path
import torch
import torchvision
from PIL import Image
from torch.utils.data import Dataset, DataLoader
if __package__:
    from . import data as d
    from .metrics import classification_metrics
    from .model import WasteModel, preprocessing, seed_all, masked_loss, WEIGHTS_ID
else:
    import data as d
    from metrics import classification_metrics
    from model import WasteModel, preprocessing, seed_all, masked_loss, WEIGHTS_ID

class Images(Dataset):
    def __init__(self, rows, config, train=False):
        self.rows = rows; self.transform = preprocessing(config,train)
    def __len__(self):return len(self.rows)
    def __getitem__(self,index):
        r=self.rows[index]
        with Image.open(d.image_path(r['image_path'])) as im:x=self.transform(im)
        return x,int(r['waste_target']),int(r['residual_target']),index

def worker_seed(_):random.seed(torch.initial_seed() % (2**32))
def loader(rows, config, train=False, generator=None):
    return DataLoader(Images(rows,config,train),batch_size=config['batch_size'],shuffle=train,
                      num_workers=config['num_workers'],pin_memory=config['device']=='cuda',
                      worker_init_fn=worker_seed,generator=generator,drop_last=False)
def device_for(config):
    if config['device']=='cuda' and not torch.cuda.is_available():raise RuntimeError('CUDA unavailable; no automatic CPU fallback')
    return torch.device(config['device'])
def amp_check(config,device):
    if config['amp'] and (device.type!='cuda' or torch.cuda.get_device_capability(device)[0]<7):
        raise RuntimeError('Requested AMP is not supported by this smoke-test policy')
def optimizer_for(model,stage,config):
    model.stage(stage)
    head=model.waste_head if stage=='stage1' else model.residual_head
    optimizer=torch.optim.AdamW([{'params':model.features.parameters(),'lr':config['backbone_lr']},
                                {'params':head.parameters(),'lr':config['head_lr']}],weight_decay=config['weight_decay'])
    scheduler=torch.optim.lr_scheduler.ReduceLROnPlateau(optimizer,mode='max',factor=.5,patience=2,min_lr=1e-7)
    return optimizer,scheduler
def save_torch(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True);tmp=path.with_suffix('.tmp')
    with tmp.open('wb') as f:torch.save(value,f);f.flush();os.fsync(f.fileno())
    os.replace(tmp,path)
def load_checkpoint(path):
    return torch.load(path,map_location='cpu',weights_only=True)
def rng_state(generator):
    return dict(python=random.getstate(),torch=torch.get_rng_state(),
                cuda=torch.cuda.get_rng_state_all() if torch.cuda.is_available() else [],loader=generator.get_state())
def restore_rng(state,generator):
    random.setstate(state['python']);torch.set_rng_state(state['torch']);generator.set_state(state['loader'])
    if state['cuda']:torch.cuda.set_rng_state_all(state['cuda'])
def config_hash(config):return d.sha(json.dumps(config,sort_keys=True).encode())

@torch.inference_mode()
def evaluate_rows(model,rows,config):
    model.eval();device=device_for(config);details=[]
    accum={origin:{task:dict(targets=[],predictions=[],loss_sum=0.) for task in ('waste','residual')}
           for origin in ('all','original','generated')}
    for x,w,r,indices in loader(rows,config):
        outputs=model(x.to(device))
        for j,index in enumerate(indices.tolist()):
            row=rows[index];detail={k:row[k] for k in ('image_path','origin','group_id','split','stage')}
            for task,target,logits,classes in [('waste',int(w[j]),outputs[0][j],d.WASTE),('residual',int(r[j]),outputs[1][j],d.RESIDUAL)]:
                probs=logits.softmax(0);pred=int(probs.argmax());confidence=float(probs[pred])
                detail.update({task+'_true':classes[target] if target>=0 else '',task+'_predicted':classes[pred],task+'_confidence':confidence,
                               task+'_valid':int(target>=0)})
                if target>=0:
                    loss=float(torch.nn.functional.cross_entropy(logits.unsqueeze(0),torch.tensor([target],device=device)))
                    for origin in ('all',row['origin']):
                        a=accum[origin][task];a['targets'].append(target);a['predictions'].append(pred);a['loss_sum']+=loss
            details.append(detail)
    metrics={origin:{task:classification_metrics(**a,classes=d.WASTE if task=='waste' else d.RESIDUAL)
                     for task,a in tasks.items()} for origin,tasks in accum.items()}
    return metrics,details

def step(model,x,w,r,stage,optimizer,scaler,config):
    optimizer.zero_grad(set_to_none=True)
    with torch.autocast(device_type=x.device.type,dtype=torch.float16,enabled=config['amp']):
        out=model(x)
        loss=masked_loss(out[0] if stage=='stage1' else out[1],w if stage=='stage1' else r)
    if loss is None:return None
    if not torch.isfinite(loss):raise FloatingPointError('Non-finite loss')
    scaler.scale(loss).backward();scaler.unscale_(optimizer)
    if any(p.grad is not None and not torch.isfinite(p.grad).all() for p in model.parameters()):
        raise FloatingPointError('Non-finite gradient; no silent AMP continuation')
    scaler.step(optimizer);scaler.update()
    if any(not torch.isfinite(p).all() for p in model.parameters()):raise FloatingPointError('Non-finite parameters')
    return float(loss.detach())

def smoke(folder,config):
    """No weights download or full training; isolated checkpoints under smoke/."""
    readiness=d.verify(folder);device=device_for(config);amp_check(config,device);seed_all(config['seed'])
    rows=[r for r in d.read_csv(Path(folder)/'manifest.csv') if r['split']=='train' and int(r['residual_target'])>=0]
    if len(rows)<config['batch_size']:raise RuntimeError('Not enough valid train samples for configured smoke batch')
    x,w,r,_=next(iter(loader(rows[:config['batch_size']],config)))
    x,w,r=x.to(device),w.to(device),r.to(device)
    model=WasteModel(config['dropout']).to(device)
    report=dict(status='running',device=str(device),torch=str(torch.__version__),torchvision=str(torchvision.__version__),
                cuda_build=torch.version.cuda,batch_size=config['batch_size'],input_size=config['input_size'],amp=config['amp'],
                pretrained=False,oom=False,full_training_started=False,stages=[])
    if device.type=='cuda':
        report['gpu']=torch.cuda.get_device_name(device);report['capability']=list(torch.cuda.get_device_capability(device))
        torch.cuda.reset_peak_memory_stats(device);torch.cuda.synchronize(device)
    started=time.perf_counter()
    model.eval()
    with torch.no_grad():out=model(x)
    assert out[0].shape==out[1].shape==(config['batch_size'],4)
    if config['amp']:
        with torch.no_grad(),torch.autocast(device_type='cuda',dtype=torch.float16):amp_out=model(x)
        gap=max(float((a.softmax(1)-b.float().softmax(1)).abs().max()) for a,b in zip(out,amp_out))
        report['amp_probability_max_difference_vs_fp32']=gap
        if gap>.03:raise FloatingPointError('AMP vs FP32 difference exceeds smoke tolerance')
    for stage in ('stage1','stage2'):
        optimizer,scheduler=optimizer_for(model,stage,config);scaler=torch.amp.GradScaler('cuda',enabled=config['amp'])
        before={n:p.detach().clone() for n,p in model.named_parameters()}
        losses=[]
        for _ in range(3):losses.append(step(model,x,w,r,stage,optimizer,scaler,config))
        changed=[n for n,p in model.named_parameters() if not torch.equal(before[n],p)]
        frozen='residual_head' if stage=='stage1' else 'waste_head';active='waste_head' if stage=='stage1' else 'residual_head'
        assert not any(n.startswith(frozen) for n in changed)
        assert any(n.startswith('features') for n in changed) and any(n.startswith(active) for n in changed)
        generator=torch.Generator().manual_seed(config['seed'])
        checkpoint=dict(model=model.state_dict(),optimizer=optimizer.state_dict(),scheduler=scheduler.state_dict(),
                        scaler=scaler.state_dict(),rng=rng_state(generator),stage=stage,epoch=0,config=config)
        smoke_dir=Path(folder)/'smoke'/('amp' if config['amp'] else 'fp32');smoke_dir.mkdir(parents=True,exist_ok=True)
        save_torch(smoke_dir/(stage+'.pt'),checkpoint)
        model.eval()
        with torch.no_grad():prediction=model(x)
        restored=WasteModel(config['dropout']).to(device);restored.load_state_dict(load_checkpoint(smoke_dir/(stage+'.pt'))['model']);restored.eval()
        with torch.no_grad():reproduced=restored(x)
        assert all(torch.equal(a,b) for a,b in zip(prediction,reproduced))
        # Verify optimizer/scaler/scheduler and RNG restoration, not just weights.
        op,sc=optimizer_for(restored,stage,config);ck=load_checkpoint(smoke_dir/(stage+'.pt'))
        op.load_state_dict(ck['optimizer']);sc.load_state_dict(ck['scheduler']);scaler.load_state_dict(ck['scaler']);restore_rng(ck['rng'],generator)
        report['stages'].append(dict(stage=stage,steps=3,losses=losses,changed_parameters=len(changed),frozen_head_unchanged=True,checkpoint_reload_reproducible=True))
    report['seconds']=time.perf_counter()-started
    report['peak_memory_mb']=torch.cuda.max_memory_allocated(device)/1024**2 if device.type=='cuda' else None
    report.update(status='passed',config_sha256=config_hash(config),manifest_sha256=d.sha((Path(folder)/'manifest.csv').read_bytes()))
    d.write_json(Path(folder)/('smoke_amp.json' if config['amp'] else 'smoke.json'),report);return report

def checkpoint_payload(model,optimizer,scheduler,scaler,stage,epoch,best,bad,config,metadata,generator,history,baseline,stage1_hash):
    return dict(format_version=1,model=model.state_dict(),optimizer=optimizer.state_dict(),scheduler=scheduler.state_dict(),
                scaler=scaler.state_dict(),stage=stage,epoch=epoch,best_metric=best,bad_epochs=bad,config=config,
                preprocessing=config['preprocessing'],weights=WEIGHTS_ID,waste_classes=d.WASTE,residual_classes=d.RESIDUAL,
                seed=config['seed'],data_metadata=metadata,rng=rng_state(generator),history=history,
                stage1_waste_baseline=baseline,stage1_checkpoint_sha256=stage1_hash,
                torch_version=str(torch.__version__),torchvision_version=str(torchvision.__version__))

def train(folder,run_dir,stage,config,from_stage1=None,resume=None):
    folder,run_dir=Path(folder),Path(run_dir)
    if (run_dir/'final_test').exists():raise RuntimeError('Final test is locked; do not resume or retrain this evaluated run')
    readiness=d.verify(folder)
    if not readiness['ready']:raise RuntimeError('Data not ready: '+'; '.join(readiness['blockers']))
    smoke_path=folder/('smoke_amp.json' if config['amp'] else 'smoke.json')
    if not smoke_path.exists():raise RuntimeError('Run and pass GPU smoke first')
    proof=d.read_json(smoke_path)
    if (proof.get('status')!='passed' or proof.get('device')!='cuda' or proof.get('config_sha256')!=config_hash(config)
        or proof.get('manifest_sha256')!=d.sha((folder/'manifest.csv').read_bytes())):
        raise RuntimeError('GPU smoke proof does not match current configuration and manifest')
    device=device_for(config);amp_check(config,device);seed_all(config['seed'])
    metadata=d.read_json(folder/'metadata.json');run_dir.mkdir(parents=True,exist_ok=True)
    best_path=run_dir/(stage+'_best.pt');last_path=run_dir/(stage+'_last.pt')
    if not resume and (best_path.exists() or last_path.exists()):raise RuntimeError('Existing run; use --resume or a new run directory')
    rows=d.read_csv(folder/'manifest.csv');training=[r for r in rows if r['stage']==stage]
    # Stage2 never trains on a waste-only image; masks still guard invalid targets.
    if stage=='stage2':training=[r for r in training if int(r['residual_target'])>=0]
    validation=[r for r in rows if r['split']=='val']
    if not training or not validation:raise RuntimeError('Empty training or validation subset')
    generator=torch.Generator().manual_seed(config['seed'])
    model=WasteModel(config['dropout'],pretrained=(not resume and stage=='stage1'),allow_download=config['allow_weight_download']).to(device)
    baseline=None;stage1_hash=None;history=[];start_epoch=1;best=-1.;bad=0
    if stage=='stage2' and not resume:
        if not from_stage1:raise ValueError('--from-stage1 is required')
        c=load_checkpoint(from_stage1)
        if not (Path(from_stage1).parent/'stage1_completed.json').exists():raise ValueError('Stage1 model selection must be complete before stage2')
        if c['stage']!='stage1' or c['data_metadata']!=metadata:raise ValueError('Stage1 checkpoint/data mismatch')
        if Path(from_stage1).name!='stage1_best.pt':raise ValueError('Stage2 starts from independently saved stage1_best.pt')
        if c['config']!=config:raise ValueError('Stage1 and stage2 configuration mismatch')
        model.load_state_dict(c['model']);baseline=c['best_metric'];stage1_hash=d.sha(Path(from_stage1).read_bytes())
        # No stage1 optimizer/scheduler states are reused here.
    optimizer,scheduler=optimizer_for(model,stage,config)
    scaler=torch.amp.GradScaler('cuda',enabled=config['amp'])
    if resume:
        c=load_checkpoint(resume)
        if c['stage']!=stage or c['data_metadata']!=metadata or c['config']!=config:raise ValueError('Resume stage/data/config mismatch')
        if Path(resume).resolve()!=last_path.resolve():raise ValueError('Resume the matching run/stage last checkpoint')
        model.load_state_dict(c['model']);optimizer.load_state_dict(c['optimizer']);scheduler.load_state_dict(c['scheduler']);scaler.load_state_dict(c['scaler'])
        restore_rng(c['rng'],generator);start_epoch=c['epoch']+1;best=c['best_metric'];bad=c['bad_epochs'];history=c['history']
        baseline=c['stage1_waste_baseline'] if stage=='stage2' else None;stage1_hash=c['stage1_checkpoint_sha256']
    else:
        save_torch(last_path,checkpoint_payload(model,optimizer,scheduler,scaler,stage,0,best,bad,config,metadata,generator,history,baseline,stage1_hash))
    if bad>=config['patience']:raise RuntimeError('Run already stopped by early stopping; no silent restart')
    train_loader=loader(training,config,True,generator)
    for epoch in range(start_epoch,config['max_epochs']+1):
        model.stage(stage)
        if device.type=='cuda':torch.cuda.reset_peak_memory_stats(device);torch.cuda.synchronize(device)
        started=time.perf_counter();loss_total=0.;samples=0;lrs=[g['lr'] for g in optimizer.param_groups]
        for x,w,r,_ in train_loader:
            x,w,r=x.to(device),w.to(device),r.to(device)
            loss=step(model,x,w,r,stage,optimizer,scaler,config)
            if loss is not None:
                n=int((w>=0).sum() if stage=='stage1' else (r>=0).sum());samples+=n;loss_total+=loss*n
        metrics,details=evaluate_rows(model,validation,config)
        task='waste' if stage=='stage1' else 'residual'
        score=metrics['original'][task]['macro_f1']
        if score is None:raise RuntimeError('No real validation examples for selection')
        improved=score>best+config['min_delta']
        if improved:best=score;bad=0
        else:bad+=1
        scheduler.step(score)
        if device.type=='cuda':torch.cuda.synchronize(device)
        waste_f1=metrics['original']['waste']['macro_f1']
        entry=dict(epoch=epoch,training_loss=loss_total/samples if samples else None,training_samples=samples,
                   selection_metric=score,validation_waste_macro_f1=waste_f1,validation_residual_macro_f1=metrics['original']['residual']['macro_f1'],
                   waste_drop_percentage_points=(baseline-waste_f1)*100 if baseline is not None else None,
                   seconds=time.perf_counter()-started,learning_rates=lrs,learning_rates_next=[g['lr'] for g in optimizer.param_groups],
                   peak_memory_mb=torch.cuda.max_memory_allocated(device)/1024**2 if device.type=='cuda' else None,bad_epochs=bad,metrics=metrics)
        history.append(entry)
        baseline_to_save=best if stage=='stage1' else baseline
        payload=checkpoint_payload(model,optimizer,scheduler,scaler,stage,epoch,best,bad,config,metadata,generator,history,baseline_to_save,stage1_hash)
        if improved:
            save_torch(best_path,payload);d.write_json(run_dir/(stage+'_best_validation.json'),metrics)
            d.write_csv(run_dir/(stage+'_best_validation_predictions.csv'),details)
        save_torch(last_path,payload)
        d.write_json(run_dir/(stage+'_history.json'),history)
        d.write_csv(run_dir/(stage+'_history.csv'),[{k:v for k,v in h.items() if k!='metrics'} for h in history])
        print(json.dumps({k:v for k,v in entry.items() if k!='metrics'},ensure_ascii=False),flush=True)
        if bad>=config['patience']:break
    d.write_json(run_dir/(stage+'_completed.json'),dict(stage=stage,best_checkpoint=str(best_path),last_checkpoint=str(last_path),best_validation_macro_f1=best,
                 completed_epochs=len(history),early_stopped=bad>=config['patience'],manifest_sha256=metadata['manifest_sha256'],config_sha256=config_hash(config)))
    return best_path

def final_evaluation(folder,run_dir,device='cuda'):
    """One predeclared comparison, after both stages complete. No test selection."""
    folder,run_dir=Path(folder),Path(run_dir);d.verify(folder)
    dest=run_dir/'final_test'
    if dest.exists():raise RuntimeError('Final test already started/completed; do not retune or repeatedly select on test')
    checkpoints={stage:run_dir/(stage+'_best.pt') for stage in ('stage1','stage2')}
    for stage in checkpoints:
        if not (run_dir/(stage+'_completed.json')).exists():raise RuntimeError('Both training stages must complete before final test')
    stage2=load_checkpoint(checkpoints['stage2'])
    if stage2['stage1_checkpoint_sha256']!=d.sha(checkpoints['stage1'].read_bytes()):raise ValueError('Stage2 was not initialized from this locked stage1_best')
    rows=[r for r in d.read_csv(folder/'manifest.csv') if r['split']=='test']
    if not rows:raise RuntimeError('No qualified test samples')
    dest.mkdir()
    d.write_json(dest/'selection_locked.json',{k:d.sha(p.read_bytes()) for k,p in checkpoints.items()})
    result={}
    for stage,path in checkpoints.items():
        ck=load_checkpoint(path)
        if ck['data_metadata']!=d.read_json(folder/'metadata.json'):raise ValueError('Checkpoint manifest mismatch')
        config=ck['config'].copy();config['device']=device;seed_all(config['seed']);model=WasteModel(config['dropout']).to(device_for(config));model.load_state_dict(ck['model'])
        result[stage],details=evaluate_rows(model,rows,config)
        d.write_json(dest/(stage+'_metrics.json'),result[stage]);d.write_csv(dest/(stage+'_predictions.csv'),details)
    f1a=result['stage1']['original']['waste']['macro_f1'];f1b=result['stage2']['original']['waste']['macro_f1']
    d.write_json(dest/'comparison.json',dict(waste_drop_percentage_points=(f1a-f1b)*100 if f1a is not None and f1b is not None else None,
                                           test_used_for_model_selection=False,metrics=result))
    return result

def evaluate_validation(checkpoint,folder,output,device='cuda'):
    d.verify(folder);ck=load_checkpoint(checkpoint)
    if ck['data_metadata']!=d.read_json(Path(folder)/'metadata.json'):raise ValueError('Checkpoint manifest mismatch')
    config=ck['config'].copy();config['device']=device;seed_all(config['seed'])
    model=WasteModel(config['dropout']).to(device_for(config));model.load_state_dict(ck['model'])
    rows=[r for r in d.read_csv(Path(folder)/'manifest.csv') if r['split']=='val']
    metrics,details=evaluate_rows(model,rows,config);output=Path(output);output.mkdir(parents=True,exist_ok=True)
    d.write_json(output/'metrics.json',metrics);d.write_csv(output/'predictions.csv',details)
    return metrics

class Predictor:
    """Reusable future web API: one primary object per image; no web server."""
    def __init__(self,checkpoint,device='cpu',confidence_threshold=None):
        ck=load_checkpoint(checkpoint);self.config=ck['config'].copy();self.config['device']=device
        if ck['waste_classes']!=d.WASTE or ck['residual_classes']!=d.RESIDUAL:raise ValueError('Checkpoint class order mismatch')
        seed_all(self.config['seed']);self.device=device_for(self.config)
        self.model=WasteModel(self.config['dropout']).to(self.device);self.model.load_state_dict(ck['model']);self.model.eval()
        self.transform=preprocessing(self.config);self.threshold=confidence_threshold if confidence_threshold is not None else self.config['confidence_threshold']
        if not 0<=self.threshold<=1:raise ValueError('Invalid confidence threshold')
        self.stage=ck['stage']

    @torch.inference_mode()
    def predict(self,paths):
        results=[]
        for path in paths:
            try:
                with Image.open(path) as im:x=self.transform(im).unsqueeze(0).to(self.device)
                outputs=self.model(x);result=dict(image_path=str(path),checkpoint_stage=self.stage)
                for task,logits,classes in [('waste',outputs[0][0],d.WASTE),('residual',outputs[1][0],d.RESIDUAL)]:
                    probs=logits.softmax(0);i=int(probs.argmax());label=classes[i];confidence=float(probs[i])
                    result[task]=dict(label=label,display='不適用／無法判斷' if label=='not_assessable' else label,
                        confidence=confidence,low_confidence=confidence<self.threshold,probabilities={c:float(v) for c,v in zip(classes,probs)})
                result['residual_head_trained']=self.stage=='stage2';results.append(result)
            except (OSError,ValueError) as e:results.append(dict(image_path=str(path),error=str(e)))
        return results
