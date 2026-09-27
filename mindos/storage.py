"""Local demo evidence and embedding cache, isolated by browser session."""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


class Storage:
    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS submissions (
                  id INTEGER PRIMARY KEY,
                  session_id TEXT NOT NULL,
                  course_id TEXT NOT NULL,
                  course_version TEXT NOT NULL,
                  task_id TEXT NOT NULL,
                  mode TEXT NOT NULL,
                  answer TEXT NOT NULL,
                  correct INTEGER,
                  counts_for_state INTEGER NOT NULL,
                  created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS submissions_scope
                  ON submissions(session_id, course_id, course_version, id);
                CREATE TABLE IF NOT EXISTS embedding_cache (
                  cache_key TEXT PRIMARY KEY,
                  vector TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS help_events (
                  session_id TEXT NOT NULL,
                  course_id TEXT NOT NULL,
                  course_version TEXT NOT NULL,
                  task_id TEXT NOT NULL,
                  PRIMARY KEY(session_id, course_id, course_version, task_id)
                );
                CREATE TABLE IF NOT EXISTS learning_goals (
                  session_id TEXT NOT NULL, course_id TEXT NOT NULL, course_version TEXT NOT NULL,
                  goal TEXT NOT NULL, PRIMARY KEY(session_id,course_id,course_version)
                );
                CREATE TABLE IF NOT EXISTS diagnostic_answers (
                  session_id TEXT NOT NULL, course_id TEXT NOT NULL, course_version TEXT NOT NULL,
                  task_id TEXT NOT NULL, answer TEXT NOT NULL, correct INTEGER NOT NULL,
                  PRIMARY KEY(session_id,course_id,course_version,task_id)
                );
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def submissions(self, session_id: str, course_id: str, version: str) -> list[dict]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT id, task_id, mode, answer, correct, counts_for_state, created_at "
                "FROM submissions WHERE session_id=? AND course_id=? AND course_version=? ORDER BY id",
                (session_id, course_id, version),
            ).fetchall()
        return [dict(row) for row in rows]

    def add_submission(self, session_id: str, pack: dict, task_id: str, mode: str,
                       answer: str, correct: bool | None, counts: bool) -> None:
        with self.connect() as db:
            db.execute(
                "INSERT INTO submissions(session_id,course_id,course_version,task_id,mode,answer,correct,counts_for_state,created_at) "
                "VALUES(?,?,?,?,?,?,?,?,?)",
                (session_id, pack["id"], pack["version"], task_id, mode, answer,
                 None if correct is None else int(correct), int(counts),
                 datetime.now(timezone.utc).isoformat(timespec="seconds")),
            )

    def get_vector(self, key: str) -> list[float] | None:
        with self.connect() as db:
            row = db.execute("SELECT vector FROM embedding_cache WHERE cache_key=?", (key,)).fetchone()
        return json.loads(row["vector"]) if row else None

    def mark_help(self, session_id: str, pack: dict, task_id: str) -> None:
        with self.connect() as db:
            db.execute("INSERT OR IGNORE INTO help_events(session_id,course_id,course_version,task_id) VALUES(?,?,?,?)",
                       (session_id, pack["id"], pack["version"], task_id))

    def helped_tasks(self, session_id: str, pack: dict) -> set[str]:
        with self.connect() as db:
            rows = db.execute("SELECT task_id FROM help_events WHERE session_id=? AND course_id=? AND course_version=?",
                              (session_id, pack["id"], pack["version"])).fetchall()
        return {row["task_id"] for row in rows}

    def put_vector(self, key: str, vector: list[float]) -> None:
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO embedding_cache(cache_key,vector) VALUES(?,?)",
                       (key, json.dumps(vector, separators=(",", ":"))))

    def goal(self, session_id: str, pack: dict) -> str | None:
        with self.connect() as db:
            row = db.execute("SELECT goal FROM learning_goals WHERE session_id=? AND course_id=? AND course_version=?",
                             (session_id, pack["id"], pack["version"])).fetchone()
        return row["goal"] if row else None

    def set_goal(self, session_id: str, pack: dict, goal: str) -> None:
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO learning_goals VALUES(?,?,?,?)",
                       (session_id, pack["id"], pack["version"], goal))

    def diagnostics(self, session_id: str, pack: dict) -> dict[str, bool]:
        with self.connect() as db:
            rows = db.execute("SELECT task_id,correct FROM diagnostic_answers WHERE session_id=? AND course_id=? AND course_version=?",
                              (session_id, pack["id"], pack["version"])).fetchall()
        return {row["task_id"]: bool(row["correct"]) for row in rows}

    def add_diagnostic(self, session_id: str, pack: dict, task_id: str, answer: str, correct: bool) -> None:
        with self.connect() as db:
            db.execute("INSERT INTO diagnostic_answers VALUES(?,?,?,?,?,?)",
                       (session_id, pack["id"], pack["version"], task_id, answer, int(correct)))
