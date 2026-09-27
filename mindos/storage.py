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
                CREATE TABLE IF NOT EXISTS learning_preferences (
                  session_id TEXT PRIMARY KEY, mode TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS learning_targets (
                  session_id TEXT NOT NULL, course_id TEXT NOT NULL, course_version TEXT NOT NULL,
                  chapter_id TEXT NOT NULL, concept_id TEXT NOT NULL, custom_text TEXT NOT NULL,
                  PRIMARY KEY(session_id,course_id,course_version)
                );
                CREATE TABLE IF NOT EXISTS diagnostic_skips (
                  session_id TEXT NOT NULL, course_id TEXT NOT NULL, course_version TEXT NOT NULL,
                  concept_id TEXT NOT NULL,
                  PRIMARY KEY(session_id,course_id,course_version,concept_id)
                );
                CREATE TABLE IF NOT EXISTS generated_quizzes (
                  quiz_id TEXT PRIMARY KEY, session_id TEXT NOT NULL, course_id TEXT NOT NULL,
                  course_version TEXT NOT NULL, concept_id TEXT NOT NULL, prompt TEXT NOT NULL,
                  choices TEXT NOT NULL, answer TEXT NOT NULL, explanation TEXT NOT NULL,
                  source_title TEXT NOT NULL, source_url TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS tutor_turns (
                  id INTEGER PRIMARY KEY, session_id TEXT NOT NULL, course_id TEXT NOT NULL,
                  course_version TEXT NOT NULL, concept_id TEXT NOT NULL,
                  role TEXT NOT NULL, kind TEXT NOT NULL, content TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS tutor_turns_scope ON tutor_turns
                  (session_id, course_id, course_version, concept_id, id);
                CREATE TABLE IF NOT EXISTS model_profiles (
                  id TEXT PRIMARY KEY, name TEXT NOT NULL, base_url TEXT NOT NULL,
                  chat_model TEXT NOT NULL, embedding_model TEXT NOT NULL,
                  encrypted_api_key TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS model_selection (
                  session_id TEXT PRIMARY KEY, profile_id TEXT NOT NULL
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

    def skip_diagnostics(self, session_id: str, pack: dict, concept_id: str) -> None:
        with self.connect() as db:
            db.execute("INSERT OR IGNORE INTO diagnostic_skips VALUES(?,?,?,?)",
                       (session_id, pack["id"], pack["version"], concept_id))

    def diagnostics_skipped(self, session_id: str, pack: dict, concept_id: str) -> bool:
        with self.connect() as db:
            row = db.execute("SELECT 1 FROM diagnostic_skips WHERE session_id=? AND course_id=? "
                             "AND course_version=? AND concept_id=?",
                             (session_id, pack["id"], pack["version"], concept_id)).fetchone()
        return row is not None

    def mode(self, session_id: str) -> str | None:
        with self.connect() as db:
            row = db.execute("SELECT mode FROM learning_preferences WHERE session_id=?", (session_id,)).fetchone()
        return row["mode"] if row else None

    def model_profiles(self) -> list[dict]:
        with self.connect() as db:
            rows = db.execute("SELECT id,name,base_url,chat_model,embedding_model,"
                              "encrypted_api_key FROM model_profiles ORDER BY name,id").fetchall()
        return [dict(row) for row in rows]

    def model_profile(self, profile_id: str) -> dict | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM model_profiles WHERE id=?", (profile_id,)).fetchone()
        return dict(row) if row else None

    def save_model_profile(self, profile: dict) -> None:
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO model_profiles VALUES(?,?,?,?,?,?)",
                       (profile["id"], profile["name"], profile["base_url"],
                        profile["chat_model"], profile["embedding_model"],
                        profile["encrypted_api_key"]))

    def selected_model_profile(self, session_id: str) -> str | None:
        with self.connect() as db:
            row = db.execute("SELECT profile_id FROM model_selection WHERE session_id=?",
                             (session_id,)).fetchone()
        return row["profile_id"] if row else None

    def select_model_profile(self, session_id: str, profile_id: str | None) -> None:
        with self.connect() as db:
            if profile_id is None:
                db.execute("DELETE FROM model_selection WHERE session_id=?", (session_id,))
            else:
                db.execute("INSERT OR REPLACE INTO model_selection VALUES(?,?)",
                           (session_id, profile_id))

    def delete_model_profile(self, profile_id: str) -> None:
        with self.connect() as db:
            db.execute("DELETE FROM model_profiles WHERE id=?", (profile_id,))
            db.execute("DELETE FROM model_selection WHERE profile_id=?", (profile_id,))

    def set_mode(self, session_id: str, mode: str) -> None:
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO learning_preferences VALUES(?,?)", (session_id, mode))

    def target(self, session_id: str, pack: dict) -> dict | None:
        with self.connect() as db:
            row = db.execute("SELECT chapter_id,concept_id,custom_text FROM learning_targets "
                             "WHERE session_id=? AND course_id=? AND course_version=?",
                             (session_id, pack["id"], pack["version"])).fetchone()
        return dict(row) if row else None

    def set_target(self, session_id: str, pack: dict, chapter_id: str,
                   concept_id: str, custom_text: str) -> None:
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO learning_targets VALUES(?,?,?,?,?,?)",
                       (session_id, pack["id"], pack["version"], chapter_id, concept_id, custom_text))

    def save_quiz(self, session_id: str, pack: dict, quiz: dict) -> None:
        with self.connect() as db:
            db.execute("INSERT INTO generated_quizzes VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                       (quiz["id"], session_id, pack["id"], pack["version"], quiz["concept_id"],
                        quiz["prompt"], json.dumps(quiz["choices"], ensure_ascii=False), quiz["answer"],
                        quiz["explanation"], quiz["source_title"], quiz["source_url"]))

    def tutor_turns(self, session_id: str, pack: dict, concept_id: str) -> list[dict]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT role,kind,content FROM tutor_turns WHERE session_id=? AND course_id=? "
                "AND course_version=? AND concept_id=? ORDER BY id",
                (session_id, pack["id"], pack["version"], concept_id),
            ).fetchall()
        return [dict(row) for row in rows]

    def save_tutor_turns(self, session_id: str, pack: dict, concept_id: str,
                         turns: list[tuple[str, str, str]], reset: bool = False) -> None:
        with self.connect() as db:
            scope = (session_id, pack["id"], pack["version"], concept_id)
            if reset:
                db.execute("DELETE FROM tutor_turns WHERE session_id=? AND course_id=? "
                           "AND course_version=? AND concept_id=?", scope)
            db.executemany(
                "INSERT INTO tutor_turns(session_id,course_id,course_version,concept_id,role,kind,content) "
                "VALUES(?,?,?,?,?,?,?)",
                [(*scope, role, kind, content) for role, kind, content in turns],
            )

    def quiz(self, session_id: str, pack: dict, quiz_id: str) -> dict | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM generated_quizzes WHERE quiz_id=? AND session_id=? "
                             "AND course_id=? AND course_version=?",
                             (quiz_id, session_id, pack["id"], pack["version"])).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["choices"] = json.loads(result["choices"])
        return result
