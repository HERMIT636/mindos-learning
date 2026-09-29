"""Persistent user courses, section lessons, quizzes and isolated mastery evidence."""

from __future__ import annotations

import json
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Storage:
    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            old = db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='learning_targets'").fetchone()
            migrated = db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='courses'").fetchone()
            if old and not migrated:
                backup = path.with_name(path.name + ".before-custom-courses.sqlite3")
                if not backup.exists():
                    with sqlite3.connect(backup) as target:
                        db.backup(target)
                for table in ("submissions", "embedding_cache", "help_events", "learning_goals",
                              "diagnostic_answers", "learning_preferences", "learning_targets",
                              "diagnostic_skips", "generated_quizzes", "tutor_turns"):
                    db.execute(f"DROP TABLE IF EXISTS {table}")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS model_profiles (
                  id TEXT PRIMARY KEY, name TEXT NOT NULL, base_url TEXT NOT NULL,
                  chat_model TEXT NOT NULL, embedding_model TEXT NOT NULL,
                  encrypted_api_key TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS model_selection (
                  session_id TEXT PRIMARY KEY, profile_id TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS courses (
                  id TEXT PRIMARY KEY, session_id TEXT NOT NULL, title TEXT NOT NULL,
                  goal TEXT NOT NULL, current_ordinal INTEGER NOT NULL DEFAULT 1,
                  created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS courses_owner ON courses(session_id, created_at);
                CREATE TABLE IF NOT EXISTS sections (
                  id TEXT PRIMARY KEY, course_id TEXT NOT NULL REFERENCES courses(id),
                  ordinal INTEGER NOT NULL, title TEXT NOT NULL, objective TEXT NOT NULL,
                  lesson TEXT, created_at TEXT NOT NULL, UNIQUE(course_id, ordinal)
                );
                CREATE INDEX IF NOT EXISTS sections_course ON sections(course_id, ordinal);
                CREATE TABLE IF NOT EXISTS tutor_turns (
                  id INTEGER PRIMARY KEY, course_id TEXT NOT NULL, section_id TEXT NOT NULL,
                  role TEXT NOT NULL, content TEXT NOT NULL, created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS tutor_scope ON tutor_turns(course_id, section_id, id);
                CREATE TABLE IF NOT EXISTS quizzes (
                  id TEXT PRIMARY KEY, course_id TEXT NOT NULL, section_id TEXT NOT NULL,
                  questions_json TEXT NOT NULL, answers_json TEXT NOT NULL,
                  user_answers_json TEXT, score INTEGER, created_at TEXT NOT NULL,
                  submitted_at TEXT
                );
                CREATE INDEX IF NOT EXISTS quizzes_scope ON quizzes(course_id, section_id, created_at);
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def model_profiles(self) -> list[dict]:
        with self.connect() as db:
            return [dict(r) for r in db.execute("SELECT * FROM model_profiles ORDER BY name,id")]

    def model_profile(self, profile_id: str) -> dict | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM model_profiles WHERE id=?", (profile_id,)).fetchone()
            return dict(row) if row else None

    def save_model_profile(self, profile: dict) -> None:
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO model_profiles VALUES(?,?,?,?,?,?)",
                       (profile["id"], profile["name"], profile["base_url"], profile["chat_model"],
                        profile.get("embedding_model", ""), profile["encrypted_api_key"]))

    def selected_model_profile(self, session_id: str) -> str | None:
        with self.connect() as db:
            row = db.execute("SELECT profile_id FROM model_selection WHERE session_id=?", (session_id,)).fetchone()
            return row[0] if row else None

    def select_model_profile(self, session_id: str, profile_id: str | None) -> None:
        with self.connect() as db:
            if profile_id is None:
                db.execute("DELETE FROM model_selection WHERE session_id=?", (session_id,))
            else:
                db.execute("INSERT OR REPLACE INTO model_selection VALUES(?,?)", (session_id, profile_id))

    def delete_model_profile(self, profile_id: str) -> None:
        with self.connect() as db:
            db.execute("DELETE FROM model_profiles WHERE id=?", (profile_id,))
            db.execute("DELETE FROM model_selection WHERE profile_id=?", (profile_id,))

    def create_course(self, session_id: str, title: str, goal: str, outline: list[dict]) -> dict:
        course_id = secrets.token_urlsafe(16)
        with self.connect() as db:
            db.execute("INSERT INTO courses VALUES(?,?,?,?,?,?)", (course_id, session_id, title, goal, 1, now()))
            for ordinal, item in enumerate(outline, 1):
                db.execute("INSERT INTO sections VALUES(?,?,?,?,?,?,?)",
                           (secrets.token_urlsafe(16), course_id, ordinal,
                            item["title"], item["objective"], None, now()))
        return self.course(session_id, course_id)

    def courses(self, session_id: str) -> list[dict]:
        with self.connect() as db:
            rows = db.execute("SELECT id,title,goal,current_ordinal,created_at FROM courses "
                              "WHERE session_id=? ORDER BY created_at DESC,id DESC", (session_id,)).fetchall()
        return [dict(row) for row in rows]

    def course(self, session_id: str, course_id: str) -> dict | None:
        with self.connect() as db:
            course = db.execute("SELECT * FROM courses WHERE id=? AND session_id=?",
                                (course_id, session_id)).fetchone()
            if not course:
                return None
            sections = db.execute("SELECT * FROM sections WHERE course_id=? ORDER BY ordinal", (course_id,)).fetchall()
        return {**dict(course), "sections": [dict(s) for s in sections]}

    def section(self, session_id: str, course_id: str, ordinal: int) -> dict | None:
        course = self.course(session_id, course_id)
        if not course or not 1 <= ordinal <= course["current_ordinal"]:
            return None
        return course["sections"][ordinal - 1]

    def save_lesson(self, session_id: str, course_id: str, section_id: str, lesson: str) -> bool:
        with self.connect() as db:
            row = db.execute("SELECT 1 FROM sections s JOIN courses c ON c.id=s.course_id "
                             "WHERE s.id=? AND s.course_id=? AND c.session_id=? AND s.ordinal<=c.current_ordinal",
                             (section_id, course_id, session_id)).fetchone()
            if not row:
                return False
            # First successful generation wins; repeat requests never overwrite the learner's history.
            changed = db.execute("UPDATE sections SET lesson=? WHERE id=? AND lesson IS NULL",
                                 (lesson, section_id)).rowcount
            if changed:
                db.execute("INSERT INTO tutor_turns(course_id,section_id,role,content,created_at) "
                           "VALUES(?,?,?,?,?)", (course_id, section_id, "assistant", lesson, now()))
        return True

    def tutor_turns(self, session_id: str, course_id: str, section_id: str) -> list[dict]:
        with self.connect() as db:
            owned = db.execute("SELECT 1 FROM courses WHERE id=? AND session_id=?", (course_id, session_id)).fetchone()
            if not owned:
                return []
            rows = db.execute("SELECT role,content,created_at FROM tutor_turns "
                              "WHERE course_id=? AND section_id=? ORDER BY id", (course_id, section_id)).fetchall()
        return [dict(r) for r in rows]

    def add_tutor_exchange(self, session_id: str, course_id: str, section_id: str,
                           question: str, answer: str) -> None:
        with self.connect() as db:
            owned = db.execute("SELECT 1 FROM sections s JOIN courses c ON c.id=s.course_id "
                               "WHERE s.id=? AND s.course_id=? AND c.session_id=?",
                               (section_id, course_id, session_id)).fetchone()
            if not owned:
                raise ValueError("小节不存在")
            db.executemany("INSERT INTO tutor_turns(course_id,section_id,role,content,created_at) "
                           "VALUES(?,?,?,?,?)", [(course_id, section_id, role, content, now())
                                               for role, content in (("user", question), ("assistant", answer))])

    def advance(self, session_id: str, course_id: str, expected: int) -> bool:
        with self.connect() as db:
            changed = db.execute("UPDATE courses SET current_ordinal=current_ordinal+1 "
                                 "WHERE id=? AND session_id=? AND current_ordinal=? "
                                 "AND current_ordinal<(SELECT COUNT(*) FROM sections WHERE course_id=?)",
                                 (course_id, session_id, expected, course_id)).rowcount
        return bool(changed)

    def section_quizzes(self, session_id: str, course_id: str, section_id: str) -> list[dict]:
        with self.connect() as db:
            owned = db.execute("SELECT 1 FROM courses WHERE id=? AND session_id=?", (course_id, session_id)).fetchone()
            if not owned:
                return []
            rows = db.execute("SELECT * FROM quizzes WHERE course_id=? AND section_id=? ORDER BY rowid",
                              (course_id, section_id)).fetchall()
        return [self._quiz_public(dict(r)) for r in rows]

    @staticmethod
    def _quiz_public(row: dict) -> dict:
        questions = json.loads(row["questions_json"])
        public = {"id": row["id"], "questions": questions, "score": row["score"],
                  "submitted_at": row["submitted_at"], "created_at": row["created_at"]}
        if row["submitted_at"]:
            public["user_answers"] = json.loads(row["user_answers_json"])
            public["results"] = json.loads(row["answers_json"])
        return public

    def create_quiz(self, session_id: str, course_id: str, section_id: str,
                    questions: list[dict], answers: list[dict]) -> dict:
        quiz_id = secrets.token_urlsafe(16)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            owned = db.execute("SELECT 1 FROM sections s JOIN courses c ON c.id=s.course_id "
                               "WHERE s.id=? AND s.course_id=? AND c.session_id=? AND s.lesson IS NOT NULL "
                               "AND s.ordinal<=c.current_ordinal", (section_id, course_id, session_id)).fetchone()
            if not owned:
                raise ValueError("请先完成当前小节讲解")
            pending = db.execute("SELECT * FROM quizzes WHERE course_id=? AND section_id=? "
                                 "AND submitted_at IS NULL ORDER BY rowid DESC LIMIT 1",
                                 (course_id, section_id)).fetchone()
            if pending:
                return self._quiz_public(dict(pending))
            db.execute("INSERT INTO quizzes VALUES(?,?,?,?,?,?,?,?,?)",
                       (quiz_id, course_id, section_id, json.dumps(questions, ensure_ascii=False),
                        json.dumps(answers, ensure_ascii=False), None, None, now(), None))
        return {"id": quiz_id, "questions": questions, "score": None}

    def submit_quiz(self, session_id: str, course_id: str, quiz_id: str,
                    user_answers: list[str]) -> dict:
        with self.connect() as db:
            row = db.execute("SELECT q.* FROM quizzes q JOIN courses c ON c.id=q.course_id "
                             "WHERE q.id=? AND q.course_id=? AND c.session_id=?",
                             (quiz_id, course_id, session_id)).fetchone()
            if not row:
                raise ValueError("测试不存在")
            if row["submitted_at"]:
                raise ValueError("这次测试已经提交，请生成新测试继续复测")
            answers = json.loads(row["answers_json"])
            if len(user_answers) != len(answers) or any(a not in {"a", "b", "c", "d"} for a in user_answers):
                raise ValueError("请完成全部题目后提交")
            score = sum(a == item["answer"] for a, item in zip(user_answers, answers))
            changed = db.execute("UPDATE quizzes SET user_answers_json=?,score=?,submitted_at=? "
                                 "WHERE id=? AND submitted_at IS NULL",
                                 (json.dumps(user_answers), score, now(), quiz_id)).rowcount
            if not changed:
                raise ValueError("这次测试已经提交，请生成新测试继续复测")
        return {"id": quiz_id, "score": score, "total": len(answers),
                "results": [{"correct": a == item["answer"], **item}
                            for a, item in zip(user_answers, answers)]}

    def mastery(self, session_id: str, course_id: str) -> dict:
        course = self.course(session_id, course_id)
        if not course:
            raise ValueError("课程不存在")
        with self.connect() as db:
            rows = db.execute("SELECT section_id,score,answers_json FROM quizzes "
                              "WHERE course_id=? AND submitted_at IS NOT NULL ORDER BY rowid",
                              (course_id,)).fetchall()
        by_section: dict[str, list[float]] = {}
        for row in rows:
            by_section.setdefault(row["section_id"], []).append(row["score"] / len(json.loads(row["answers_json"])))
        sections = []
        for section in course["sections"]:
            scores = by_section.get(section["id"], [])
            recent = scores[-2:]
            rate = round(sum(recent) / len(recent) * 100) if recent else None
            label = ("未测" if rate is None else "需补强" if rate < 60 else
                     "正在掌握" if rate < 85 or len(scores) < 2 else "较稳固")
            sections.append({"ordinal": section["ordinal"], "title": section["title"],
                             "rate": rate, "label": label, "test_count": len(scores)})
        tested = [s["rate"] for s in sections if s["rate"] is not None]
        return {"sections": sections, "tested_sections": len(tested),
                "overall_rate": round(sum(tested) / len(tested)) if tested else None,
                "coverage": f"{len(tested)}/{len(sections)}"}

    def weak_points(self, session_id: str, course_id: str) -> list[dict]:
        course = self.course(session_id, course_id)
        if not course:
            raise ValueError("课程不存在")
        titles = {section["id"]: section["title"] for section in course["sections"]}
        with self.connect() as db:
            rows = db.execute("SELECT section_id,questions_json,answers_json,user_answers_json "
                              "FROM quizzes WHERE course_id=? AND submitted_at IS NOT NULL "
                              "ORDER BY rowid DESC LIMIT 10", (course_id,)).fetchall()
        missed = []
        for row in rows:
            for question, correct, given in zip(json.loads(row["questions_json"]),
                                                json.loads(row["answers_json"]),
                                                json.loads(row["user_answers_json"])):
                if given != correct["answer"]:
                    missed.append({"section": titles[row["section_id"]], "question": question["prompt"]})
        return missed[:8]
