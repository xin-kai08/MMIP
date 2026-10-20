"""SQLite v1. All operations open their own connection; no shared thread cursor."""
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
import uuid

def now():return datetime.now(timezone.utc).isoformat()
def uid():return str(uuid.uuid4())

SCHEMA = '''
CREATE TABLE IF NOT EXISTS schema_versions(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY COLLATE NOCASE, nickname TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS batches(
 id TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id), mode TEXT NOT NULL CHECK(mode IN ('general','evaluation')),
 status TEXT NOT NULL CHECK(status IN ('queued','processing','completed','failed')),
 request_key TEXT NOT NULL, request_hash TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 UNIQUE(user_id,request_key));
CREATE TABLE IF NOT EXISTS images(
 id TEXT PRIMARY KEY, batch_id TEXT NOT NULL REFERENCES batches(id) ON DELETE CASCADE,
 original_name TEXT NOT NULL, storage_path TEXT UNIQUE, sha256 TEXT, format TEXT, width INTEGER, height INTEGER,
 status TEXT NOT NULL CHECK(status IN ('queued','processing','completed','failed')), error TEXT,
 created_at TEXT NOT NULL, started_at TEXT, finished_at TEXT, attempts INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS predictions(
 image_id TEXT PRIMARY KEY REFERENCES images(id) ON DELETE CASCADE,
 waste_label TEXT NOT NULL, residual_label TEXT NOT NULL,
 waste_probabilities TEXT NOT NULL, residual_probabilities TEXT NOT NULL,
 waste_confidence REAL NOT NULL, residual_confidence REAL NOT NULL,
 waste_low INTEGER NOT NULL, residual_low INTEGER NOT NULL, threshold REAL NOT NULL,
 model_version TEXT NOT NULL, elapsed_ms REAL NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS annotations(
 id INTEGER PRIMARY KEY AUTOINCREMENT, image_id TEXT NOT NULL REFERENCES images(id) ON DELETE CASCADE,
 source TEXT NOT NULL CHECK(source IN ('pre_ground_truth','post_feedback')),
 waste_label TEXT, residual_label TEXT, waste_confirmed INTEGER NOT NULL, residual_confirmed INTEGER NOT NULL,
 annotator_id TEXT NOT NULL REFERENCES users(id), created_at TEXT NOT NULL, previous_id INTEGER REFERENCES annotations(id) ON DELETE SET NULL);
CREATE UNIQUE INDEX IF NOT EXISTS one_pre_truth ON annotations(image_id) WHERE source='pre_ground_truth';
CREATE INDEX IF NOT EXISTS images_queue ON images(status,created_at);
CREATE INDEX IF NOT EXISTS batch_history ON batches(user_id,created_at);
CREATE INDEX IF NOT EXISTS annotation_history ON annotations(image_id,id);
CREATE TABLE IF NOT EXISTS file_gc(storage_path TEXT PRIMARY KEY, created_at TEXT NOT NULL);
CREATE TRIGGER IF NOT EXISTS immutable_pre_truth BEFORE UPDATE ON annotations WHEN OLD.source='pre_ground_truth'
 BEGIN SELECT RAISE(ABORT,'Pre-prediction Ground Truth is immutable'); END;
'''

class Store:
    def __init__(self,path):self.path=Path(path)

    @contextmanager
    def connect(self,write=False):
        c=sqlite3.connect(self.path,timeout=15)
        c.row_factory=sqlite3.Row
        c.execute('PRAGMA foreign_keys=ON')
        try:
            if write:c.execute('BEGIN IMMEDIATE')
            yield c
            c.commit()
        except BaseException:
            c.rollback();raise
        finally:c.close()

    def init(self):
        self.path.parent.mkdir(parents=True,exist_ok=True)
        with self.connect() as c:
            version=c.execute('PRAGMA user_version').fetchone()[0]
            if version not in (0,1):raise RuntimeError(f'Unsupported database schema {version}')
            c.execute('PRAGMA journal_mode=WAL')
            c.executescript(SCHEMA)
            c.execute('INSERT OR IGNORE INTO schema_versions VALUES(1,?)',(now(),))
            c.execute('PRAGMA user_version=1')

    @staticmethod
    def update_batch(c,batch):
        states=[r[0] for r in c.execute('SELECT status FROM images WHERE batch_id=?',(batch,))]
        status=('processing' if 'processing' in states else 'queued' if 'queued' in states
                else 'completed' if 'completed' in states else 'failed')
        c.execute('UPDATE batches SET status=?,updated_at=? WHERE id=?',(status,now(),batch))
