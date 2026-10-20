"""Stop the server, then back up SQLite and referenced upload files together."""
import argparse
from datetime import datetime, timezone
from pathlib import Path
import shutil
import sqlite3
from .settings import Settings
from .service import MANAGED

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path);a=p.parse_args()
    settings=Settings();db=settings.path('database')
    if not db.exists():raise SystemExit('Database does not exist')
    lock=open(db.with_suffix('.worker.lock'),'a+b');lock.seek(0)
    try:
        if __import__('os').name=='nt':
            import msvcrt
            try:msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
            except OSError:raise SystemExit('請先 Ctrl+C 停止後端，再備份資料庫與圖片')
        else:
            import fcntl
            try:fcntl.flock(lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
            except OSError:raise SystemExit('Stop the server before backup')
        out=a.output or settings.root/'website/data/backups'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        out.mkdir(parents=True,exist_ok=False);(out/'images').mkdir()
        src=sqlite3.connect(db);dest=sqlite3.connect(out/'app.sqlite3')
        try:
            src.backup(dest)
            for (relative,) in src.execute('SELECT storage_path FROM images WHERE storage_path IS NOT NULL'):
                if not MANAGED.fullmatch(relative):raise ValueError('Invalid upload path in database')
                shutil.copy2(settings.path('uploads')/relative,out/'images'/relative)
        finally:dest.close();src.close()
        shutil.copy2(settings.root/'website/config.json',out/'config.json')
        print(out)
    finally:lock.close()

if __name__=='__main__':main()
