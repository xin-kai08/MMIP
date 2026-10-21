"""Run the real model + built SPA in a disposable local server for browser tests."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import threading
import time
import uuid
from urllib.request import urlopen
from fastapi import HTTPException, Request

import uvicorn
from .app import create_app
from .settings import Settings, ROOT


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port',type=int,default=Settings().port+2)
    parser.add_argument('--scenario',choices=('feedback','linkage'),default='feedback')
    args=parser.parse_args()
    cache=ROOT/'website/.cache';cache.mkdir(exist_ok=True)
    node=ROOT/'website/.tools/node-v22.14.0-win-x64/node.exe'
    if not node.is_file():raise SystemExit('Portable Node missing; see website/README.md')
    if not (Settings().dist/'index.html').is_file():raise SystemExit('Build the frontend first')
    temp=tempfile.TemporaryDirectory(prefix='feedback-test-',dir=cache)
    root=Path(temp.name).resolve()
    if not root.is_relative_to(cache.resolve()):raise RuntimeError('Unsafe test directory')
    override={'WASTE_DATABASE':str(root/'data/db.sqlite3'),'WASTE_UPLOADS':str(root/'images'),
              'WASTE_MODEL_PATH':str(ROOT/'training/runs/experiment_v3/stage2_best.pt'),'WASTE_DEVICE':'cpu'}
    original={key:os.environ.get(key) for key in override}
    server=None;thread=None;sock=None
    result_path=ROOT/f'website/verification/{args.scenario}_browser.json'
    result_path.parent.mkdir(exist_ok=True)
    result_path.write_text(json.dumps({'passed':False,'status':'running',
                                      'timestamp_utc':datetime.now(timezone.utc).isoformat()}),encoding='utf-8')
    try:
        os.environ.update(override)
        settings=Settings(root=root)
        app=create_app(settings)
        token=uuid.uuid4().hex
        if args.scenario=='linkage':
            # Fixture-only route on this disposable server. Never registered by
            # website.app/create_app or exposed on the real user's service.
            @app.post('/__test__/legacy_feedback')
            async def seed_legacy(request:Request):
                if request.headers.get('X-Test-Token')!=token:raise HTTPException(403)
                payload=await request.json()
                from .store import now
                with app.state.service.store.connect(True) as c:
                    row=c.execute('SELECT i.id,b.user_id FROM images i JOIN batches b ON b.id=i.batch_id WHERE i.id=?',(payload['image_id'],)).fetchone()
                    if not row:raise HTTPException(404)
                    previous=c.execute("SELECT id FROM annotations WHERE image_id=? AND source='post_feedback' ORDER BY id DESC LIMIT 1",(row['id'],)).fetchone()
                    c.execute("INSERT INTO annotations(image_id,source,waste_label,residual_label,waste_confirmed,residual_confirmed,annotator_id,created_at,previous_id) VALUES(?,'post_feedback','general','food',1,1,?,?,?)",
                              (row['id'],row['user_id'],now(),previous['id'] if previous else None))
                return {'seeded':True}
        # Keep the listening socket alive until Uvicorn has drained its loop.
        # Closing it first produces a Windows Proactor accept cancellation error.
        sock=socket.socket(socket.AF_INET,socket.SOCK_STREAM)
        sock.bind(('127.0.0.1',args.port));sock.listen(128)
        server=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=args.port,workers=1,log_level='warning'))
        thread=threading.Thread(target=server.run,kwargs={'sockets':[sock]},name='isolated-feedback-server')
        thread.start()
        base=f'http://127.0.0.1:{args.port}'
        for _ in range(600):
            if not thread.is_alive():raise RuntimeError('Isolated server stopped')
            try:
                with urlopen(base+'/api/health',timeout=1) as response:health=json.load(response)
                if health['model_error']:raise RuntimeError(health['model_error'])
                if health['model_ready']:break
            except (OSError,TimeoutError):pass
            time.sleep(.1)
        else:raise RuntimeError('Model readiness timeout')
        env=dict(os.environ,WASTE_UI_TEST_URL=base,WASTE_FEEDBACK_TEST_DIR=str(root),WASTE_TEST_TOKEN=token)
        subprocess.run([str(node),str(ROOT/f'website/frontend/verify_{args.scenario}.mjs')],
                       cwd=ROOT/'website/frontend',env=env,check=True,timeout=240)
        result=json.loads(result_path.read_text('utf-8'))
        result.update(device='cpu',model_version=health['model_version'],
                      timestamp_utc=datetime.now(timezone.utc).isoformat(),isolated_database=True,status='completed')
        result_path.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        print(result_path)
    except BaseException as e:
        result_path.write_text(json.dumps({'passed':False,'status':'failed','error':str(e),
                                          'timestamp_utc':datetime.now(timezone.utc).isoformat()},ensure_ascii=False,indent=2),encoding='utf-8')
        raise
    finally:
        if server:server.should_exit=True
        if thread:
            thread.join(timeout=30)
            if thread.is_alive():raise RuntimeError('Test server still exiting; temporary files retained')
        if sock:sock.close()
        for key,value in original.items():
            if value is None:os.environ.pop(key,None)
            else:os.environ[key]=value
        for attempt in range(30):
            try:temp.cleanup();break
            except OSError as e:
                if getattr(e,'winerror',None) not in (32,145) or attempt==29:raise
                time.sleep(.1)


if __name__=='__main__':main()
