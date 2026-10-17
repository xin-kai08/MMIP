"""Commands for immutable manifests, GPU smoke, two-stage training and inference."""
from __future__ import annotations
import argparse
import importlib.util
import json
import os
import subprocess
from pathlib import Path
if __package__:
    from . import data as d
else:
    import data as d

def configuration(path, args):
    config=d.read_json(path)
    for name in ('batch_size','num_workers','device','amp','allow_weight_download'):
        if hasattr(args,name) and getattr(args,name) is not None:config[name]=getattr(args,name)
    if config['waste_classes']!=d.WASTE or config['residual_classes']!=d.RESIDUAL:raise ValueError('Class order mismatch')
    if config['seed']!=42 or config['split_ratios']!=[.7,.2,.1]:raise ValueError('This fixed experiment uses seed 42 and 70/20/10')
    if not 1<=config['max_epochs']<=30 or config['patience']!=5:raise ValueError('Use <=30 epochs and patience=5')
    if config['batch_size'] not in (4,8,16) or config['num_workers'] not in (0,2):raise ValueError('Unsupported initial batch/workers setting')
    if config['weights']!='IMAGENET1K_V1' or config['model']!='efficientnet_b0':raise ValueError('Model/weights mismatch')
    if config['input_size']<=0 or config['min_delta']<0:raise ValueError('Invalid configuration')
    return config

def environment():
    missing=[name for name in ('torch','torchvision','PIL') if importlib.util.find_spec(name) is None]
    result=dict(missing_dependencies=missing,cuda_verified=False)
    try:
        r=subprocess.run(['nvidia-smi','--query-gpu=name,memory.total,driver_version','--format=csv,noheader'],capture_output=True,text=True,timeout=15)
        result['driver_gpu_inventory']=r.stdout.strip() if r.returncode==0 else r.stderr.strip()
    except (OSError,subprocess.TimeoutExpired) as e:result['driver_gpu_inventory']=str(e)
    if not missing:
        try:
            import torch,torchvision
            result.update(torch=str(torch.__version__),torchvision=str(torchvision.__version__),cuda_available=torch.cuda.is_available(),cuda_build=torch.version.cuda)
            # cuda_available is not a numerical training verification.
        except (ImportError,OSError,RuntimeError) as e:result['import_error']=str(e)
    d.write_json(d.ROOT/'environment.json',result);return result

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--config',type=Path,default=d.ROOT/'config.json')
    commands=p.add_subparsers(dest='command',required=True)
    prepare=commands.add_parser('prepare');prepare.add_argument('--version',default='v1');prepare.add_argument('--reuse-partition',type=Path)
    commands.add_parser('environment')
    verify=commands.add_parser('verify');verify.add_argument('--manifest-dir',type=Path,default=d.ROOT/'artifacts/v2')
    for name in ('smoke','train','run'):
        q=commands.add_parser(name)
        q.add_argument('--manifest-dir',type=Path,default=d.ROOT/'artifacts/v2')
        q.add_argument('--batch-size',type=int,choices=[4,8,16]);q.add_argument('--num-workers',type=int,choices=[0,2])
        q.add_argument('--device',choices=['cuda','cpu']);q.add_argument('--amp',action=argparse.BooleanOptionalAction,default=None)
        q.add_argument('--allow-weight-download',action=argparse.BooleanOptionalAction,default=None)
        if name!='smoke':
            q.add_argument('--run-dir',type=Path,default=d.ROOT/'runs/experiment_v2')
        if name=='train':
            q.add_argument('--stage',choices=['stage1','stage2'],required=True)
            q.add_argument('--from-stage1',type=Path);q.add_argument('--resume',type=Path)
    e=commands.add_parser('evaluate');e.add_argument('--checkpoint',type=Path,required=True)
    e.add_argument('--manifest-dir',type=Path,default=d.ROOT/'artifacts/v2');e.add_argument('--output',type=Path,required=True);e.add_argument('--device',default='cuda',choices=['cpu','cuda'])
    e=commands.add_parser('final-test');e.add_argument('--manifest-dir',type=Path,default=d.ROOT/'artifacts/v2')
    e.add_argument('--run-dir',type=Path,default=d.ROOT/'runs/experiment_v2');e.add_argument('--device',default='cuda',choices=['cpu','cuda'])
    q=commands.add_parser('predict');q.add_argument('--checkpoint',type=Path,required=True);q.add_argument('--images',nargs='+',type=Path,required=True)
    q.add_argument('--device',default='cpu',choices=['cpu','cuda']);q.add_argument('--threshold',type=float);q.add_argument('--output',type=Path)
    args=p.parse_args();config=configuration(args.config,args)
    if args.command=='environment':print(json.dumps(environment(),ensure_ascii=False,indent=2));return
    if args.command=='prepare':
        folder=d.prepare(args.version,args.reuse_partition);print(json.dumps(d.read_json(folder/'readiness.json'),ensure_ascii=False,indent=2));return
    if args.command=='verify':print(json.dumps(d.verify(args.manifest_dir),ensure_ascii=False,indent=2));return
    if args.command in ('train','run'):
        readiness=d.verify(args.manifest_dir)
        if not readiness['ready']:raise RuntimeError('Formal training blocked: '+'; '.join(readiness['blockers']))
    status=environment()
    if status['missing_dependencies'] or status.get('import_error'):
        if args.command=='smoke':
            report=dict(status='blocked',reason='Missing or unusable PyTorch/TorchVision dependencies',environment=status,
                        gpu_training_verified=False,oom=None,peak_memory_mb=None,seconds=None)
            d.write_json(args.manifest_dir/('smoke_amp.json' if config['amp'] else 'smoke.json'),report)
        raise RuntimeError('Dependencies unavailable; no package download was started. See training/environment.json')
    # Import only after manifest-only commands, so data preparation needs no torch.
    if __package__:
        from . import engine
    else:
        import engine
    if args.command=='smoke':
        try:result=engine.smoke(args.manifest_dir,config)
        except (RuntimeError,AssertionError,FloatingPointError) as exc:
            report=dict(status='failed',reason=str(exc),oom='out of memory' in str(exc).lower(),gpu_training_verified=False)
            d.write_json(args.manifest_dir/('smoke_amp.json' if config['amp'] else 'smoke.json'),report);raise
        print(json.dumps(result,ensure_ascii=False,indent=2))
    elif args.command=='train':engine.train(args.manifest_dir,args.run_dir,args.stage,config,args.from_stage1,args.resume)
    elif args.command=='run':
        proof=engine.smoke(args.manifest_dir,config)
        if proof['device']!='cuda':raise RuntimeError('Formal experiment requires passing CUDA smoke')
        ck=engine.train(args.manifest_dir,args.run_dir,'stage1',config)
        engine.train(args.manifest_dir,args.run_dir,'stage2',config,from_stage1=ck)
        engine.final_evaluation(args.manifest_dir,args.run_dir,config['device'])
    elif args.command=='evaluate':engine.evaluate_validation(args.checkpoint,args.manifest_dir,args.output,args.device)
    elif args.command=='final-test':engine.final_evaluation(args.manifest_dir,args.run_dir,args.device)
    elif args.command=='predict':
        result=engine.Predictor(args.checkpoint,args.device,args.threshold).predict(args.images)
        if args.output:d.write_json(args.output,result)
        print(json.dumps(result,ensure_ascii=False,indent=2))

if __name__=='__main__':
    try:main()
    except (RuntimeError,ValueError,FileNotFoundError) as e:
        raise SystemExit(str(e))
