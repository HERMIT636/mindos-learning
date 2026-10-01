"""Version teaching inputs without changing learner evidence or losing old content."""
import json
from datetime import datetime,timezone


def migrate_revisions(db):
    for table,name in [('courses','content_revision'),('sections','lesson_revision'),('atom_content','content_revision')]:
        columns={r[1] for r in db.execute(f'PRAGMA table_info({table})')}
        if name not in columns:
            db.execute(f'ALTER TABLE {table} ADD COLUMN {name} INTEGER NOT NULL DEFAULT 1')
    db.execute('''CREATE TABLE IF NOT EXISTS content_history (
      id INTEGER PRIMARY KEY,course_id TEXT NOT NULL REFERENCES courses(id),
      object_type TEXT NOT NULL,object_id TEXT NOT NULL,revision INTEGER NOT NULL,
      snapshot_json TEXT NOT NULL,created_at TEXT NOT NULL)''')


def bump_revision(db,cid):
    db.execute('UPDATE courses SET content_revision=content_revision+1 WHERE id=?',(cid,))


def archive(db,cid,kind,identifier,revision,snapshot):
    db.execute('INSERT INTO content_history(course_id,object_type,object_id,revision,snapshot_json,created_at) VALUES(?,?,?,?,?,?)',
               (cid,kind,identifier,revision,json.dumps(snapshot,ensure_ascii=False),datetime.now(timezone.utc).isoformat()))
