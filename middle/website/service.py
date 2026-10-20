"""One durable SQLite queue and one model thread, shared by all HTTP requests."""
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import threading
import time
from .store import Store, now

log=logging.getLogger(__name__)
MANAGED=re.compile(r'^[0-9a-f-]{36}\.(png|jpg|webp)$')

class Service:
    def __init__(self,settings,predictor_factory=None):
        self.settings=settings;self.store=Store(settings.path('database'));self.factory=predictor_factory
        self.ready=False;self.error=None;self.model_version=None;self.model_metadata={}
        self.stop=threading.Event();self.wake=threading.Event();self.thread=None;self.lock_file=None

    def start(self):
        self.settings.path('uploads').mkdir(parents=True,exist_ok=True)
        self.store.init()
        # OS lock is automatically released on process crash; refuse multi-process GPU servers.
        self.lock_file=open(self.store.path.with_suffix('.worker.lock'),'a+b')
        self.lock_file.seek(0);self.lock_file.write(b'0');self.lock_file.flush();self.lock_file.seek(0)
        try:
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(self.lock_file.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(self.lock_file.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError:
            self.lock_file.close();raise RuntimeError('已有服務使用這個資料庫；請使用單一 backend process／worker')
        self.recover()
        self.thread=threading.Thread(target=self.guarded_run,name='single-model-worker',daemon=True);self.thread.start()

    def guarded_run(self):
        try:self.run()
        except Exception as e:
            self.ready=False;self.error=f'推論 worker 停止，請重新啟動服務：{e}';log.exception('Worker stopped')

    def close(self):
        self.stop.set();self.wake.set()
        if self.thread:self.thread.join()
        if self.lock_file:self.lock_file.close()

    def file(self,relative):
        if not relative or not MANAGED.fullmatch(relative):raise ValueError('Invalid managed image path')
        return self.settings.path('uploads')/relative

    def cleanup(self):
        with self.store.connect() as c:pending=[r[0] for r in c.execute('SELECT storage_path FROM file_gc')]
        for relative in pending:
            try:self.file(relative).unlink(missing_ok=True)
            except OSError:log.exception('File cleanup deferred');continue
            with self.store.connect(True) as c:c.execute('DELETE FROM file_gc WHERE storage_path=?',(relative,))

    def recover(self):
        self.cleanup()
        with self.store.connect(True) as c:
            c.execute("UPDATE images SET status='queued',error=NULL,started_at=NULL WHERE status='processing'")
            known={r[0] for r in c.execute('SELECT storage_path FROM images WHERE storage_path IS NOT NULL')}
            for relative in known:
                if not self.file(relative).exists():c.execute("UPDATE images SET status='failed',error='圖片檔案遺失',finished_at=? WHERE storage_path=?",(now(),relative))
            for b in c.execute('SELECT id FROM batches').fetchall():Store.update_batch(c,b[0])
        # Only this application's UUID files, at startup before requests are accepted.
        for p in self.settings.path('uploads').iterdir():
            if p.is_file() and MANAGED.fullmatch(p.name) and p.name not in known:p.unlink()

    def run(self):
        try:
            model=self.settings.path('model_path')
            expected_hash=hashlib.sha256(model.read_bytes()).hexdigest()
            if self.factory:self.predictor=self.factory()
            else:
                from training.engine import Predictor
                self.predictor=Predictor(self.settings.path('model_path'),self.settings.device)
            if self.predictor.stage!='stage2':raise RuntimeError('網站需要已訓練的 stage2 checkpoint')
            actual_hash=hashlib.sha256(model.read_bytes()).hexdigest()
            if actual_hash!=expected_hash:raise RuntimeError('載入期間 checkpoint 發生變動，請確認檔案後重新啟動')
            self.model_version=model.name+':sha256:'+actual_hash
            self.model_metadata=dict(waste_classes=self.predictor.config['waste_classes'],residual_classes=self.predictor.config['residual_classes'],
                                     preprocessing=self.predictor.config['preprocessing'],threshold=self.predictor.threshold)
            self.ready=True
        except Exception as e:
            self.error=f'模型無法載入：{e}';log.exception('Model startup failed')
            with self.store.connect(True) as c:
                c.execute("UPDATE images SET status='failed',error=?,finished_at=? WHERE status='queued'",(self.error,now()))
                for b in c.execute('SELECT id FROM batches').fetchall():Store.update_batch(c,b[0])
            return
        while not self.stop.is_set():
            self.cleanup()
            with self.store.connect(True) as c:
                row=c.execute("SELECT * FROM images WHERE status='queued' ORDER BY created_at,id LIMIT 1").fetchone()
                if row:
                    c.execute("UPDATE images SET status='processing',started_at=?,attempts=attempts+1 WHERE id=?",(now(),row['id']))
                    Store.update_batch(c,row['batch_id'])
            if not row:
                self.wake.wait(.4);self.wake.clear();continue
            try:
                start=time.perf_counter();result=self.predictor.predict([self.file(row['storage_path'])])[0]
                elapsed=(time.perf_counter()-start)*1000
                if 'error' in result:raise ValueError(result['error'])
                a,b=result['waste'],result['residual']
                with self.store.connect(True) as c:
                    c.execute('INSERT INTO predictions VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
                        (row['id'],a['label'],b['label'],json.dumps(a['probabilities']),json.dumps(b['probabilities']),
                         a['confidence'],b['confidence'],int(a['low_confidence']),int(b['low_confidence']),self.predictor.threshold,self.model_version,elapsed,now()))
                    c.execute("UPDATE images SET status='completed',finished_at=?,error=NULL WHERE id=?",(now(),row['id']))
                    Store.update_batch(c,row['batch_id'])
            except Exception as e:
                log.exception('Image inference failed')
                with self.store.connect(True) as c:
                    c.execute("UPDATE images SET status='failed',error=?,finished_at=? WHERE id=?",(f'辨識失敗：{e}',now(),row['id']))
                    Store.update_batch(c,row['batch_id'])
        self.ready=False
