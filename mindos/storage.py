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


from .course_management import CourseManagementStorage, migrate_courses, validate_fields
from .course_tutor import CourseTutorStorage, SCHEMA as ASSISTANT_SCHEMA
from .teaching import migrate_teaching, metadata, TeachingOrchestrator, contains
from .adaptive.teaching_state import AdaptiveStorage, migrate_adaptive
from .knowledge import KnowledgeStorage, SCHEMA
from .production import ProductionStorage, SCHEMA as PRODUCTION_SCHEMA
from .discovery import DiscoveryStorage, SCHEMA as DISCOVERY_SCHEMA, POLICIES


class Storage(KnowledgeStorage, ProductionStorage, DiscoveryStorage, CourseManagementStorage, CourseTutorStorage, AdaptiveStorage):
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
                CREATE TABLE IF NOT EXISTS search_settings (
                  session_id TEXT PRIMARY KEY, encrypted_api_key TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS search_profiles (
                  session_id TEXT NOT NULL, provider TEXT NOT NULL, api_url TEXT NOT NULL,
                  encrypted_api_key TEXT NOT NULL, PRIMARY KEY(session_id, provider)
                );
                CREATE TABLE IF NOT EXISTS course_drafts (
                  id TEXT PRIMARY KEY, session_id TEXT NOT NULL, title TEXT NOT NULL,
                  goal TEXT NOT NULL, feedback TEXT NOT NULL, revision INTEGER NOT NULL,
                  plan_json TEXT NOT NULL, sources_json TEXT NOT NULL,
                  confirmed_course_id TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS drafts_owner ON course_drafts(session_id, updated_at);
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

            columns = {row[1] for row in db.execute("PRAGMA table_info(course_drafts)")}
            if "search_report_json" not in columns:
                db.execute("ALTER TABLE course_drafts ADD COLUMN search_report_json TEXT NOT NULL DEFAULT '{}'")

            if 'management_json' not in columns:
                db.execute("ALTER TABLE course_drafts ADD COLUMN management_json TEXT NOT NULL DEFAULT '{}'")

            for table in ('courses','course_drafts'):
                columns={r[1] for r in db.execute(f'PRAGMA table_info({table})')}
                for name,default in [('source_policy','balanced'),('learner_level','零基础'),('search_mode','public')]:
                    if name not in columns:db.execute(f"ALTER TABLE {table} ADD COLUMN {name} TEXT NOT NULL DEFAULT '{default}'")
            migrate_courses(db)
            db.executescript(DISCOVERY_SCHEMA)
            from .discovery import migrate_discovery
            migrate_discovery(db)

            db.executescript(SCHEMA)
            db.executescript(PRODUCTION_SCHEMA)
            db.executescript(ASSISTANT_SCHEMA)
            migrate_teaching(db)
            migrate_adaptive(db)
            from .revisions import migrate_revisions
            migrate_revisions(db)
            columns = {row[1] for row in db.execute("PRAGMA table_info(quizzes)")}
            if "scope" not in columns:
                db.execute("ALTER TABLE quizzes ADD COLUMN scope TEXT NOT NULL DEFAULT 'section'")
            if "target_atom_id" not in columns:
                db.execute("ALTER TABLE quizzes ADD COLUMN target_atom_id TEXT NOT NULL DEFAULT ''")
            from .learning.evidence import migrate
            migrate(db)
            from .learning.final import migrate as migrate_final
            migrate_final(db)
            from .learning.authentic import migrate as migrate_authentic
            from .learning.calibration import migrate as migrate_calibration
            migrate_authentic(db)
            migrate_calibration(db)
            from .learning.canonical import migrate as migrate_canonical
            from .learning.personal import migrate as migrate_personal
            migrate_canonical(db)
            migrate_personal(db)
            from .learning.growth import migrate as migrate_growth
            migrate_growth(db)
            from .learning.execution import migrate as migrate_execution
            migrate_execution(db)
            from .tutor.storage import migrate as migrate_tutor
            migrate_tutor(db)

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

    def search_key(self, session_id: str) -> str:
        with self.connect() as db:
            row = db.execute("SELECT encrypted_api_key FROM search_settings WHERE session_id=?",
                             (session_id,)).fetchone()
        return row[0] if row else ""

    def save_search_key(self, session_id: str, encrypted_api_key: str) -> None:
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO search_settings VALUES(?,?)",
                       (session_id, encrypted_api_key))

    def search_profile(self, session_id: str, provider: str) -> dict:
        with self.connect() as db:
            row = db.execute("SELECT api_url, encrypted_api_key FROM search_profiles "
                             "WHERE session_id=? AND provider=?", (session_id, provider)).fetchone()
        if row:
            return {**dict(row), "saved": True}
        return {"saved": False, "api_url": "", "encrypted_api_key": self.search_key(session_id) if provider == "brave" else ""}

    def save_search_profile(self, session_id: str, provider: str, api_url: str, encrypted_api_key: str) -> None:
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO search_profiles VALUES(?,?,?,?)",
                       (session_id, provider, api_url, encrypted_api_key))
            if provider == "brave":
                db.execute("DELETE FROM search_settings WHERE session_id=?", (session_id,))

    @staticmethod
    def _draft_public(row: dict) -> dict:
        return {key: row[key] for key in ("id", "title", "goal", "feedback", "revision",
                                          "confirmed_course_id", "created_at", "updated_at")} | {
            "plan": json.loads(row["plan_json"]), "sources": json.loads(row["sources_json"]),
            "search_report": json.loads(row.get("search_report_json", "{}")),
            "course_info":json.loads(row.get("management_json","{}")),
            "source_policy":row.get("source_policy","balanced"),"learner_level":row.get("learner_level","零基础"),"search_mode":row.get("search_mode","public")}

    def drafts(self, session_id: str) -> list[dict]:
        with self.connect() as db:
            rows = db.execute("SELECT * FROM course_drafts WHERE session_id=? "
                              "AND confirmed_course_id IS NULL ORDER BY updated_at DESC,id DESC",
                              (session_id,)).fetchall()
        return [self._draft_public(dict(row)) for row in rows]

    def draft(self, session_id: str, draft_id: str) -> dict | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM course_drafts WHERE id=? AND session_id=?",
                             (draft_id, session_id)).fetchone()
        return self._draft_public(dict(row)) if row else None

    def save_draft(self, session_id: str, title: str, goal: str, feedback: str,
                   plan: dict, sources: list[dict], draft_id: str | None = None,
                   expected_revision: int | None = None, search_report: dict | None = None, *,
                   source_policy='balanced', learner_level='零基础', search_mode='public', documents=None, course_info=None) -> dict:
        if not isinstance(source_policy,str) or source_policy not in POLICIES:raise ValueError('知识来源偏好无效')
        manager_fields=validate_fields(course_info) if course_info is not None else None
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if draft_id is None:
                draft_id=secrets.token_urlsafe(16)
                db.execute('INSERT INTO course_drafts(id,session_id,title,goal,feedback,revision,plan_json,sources_json,confirmed_course_id,created_at,updated_at,search_report_json,source_policy,learner_level,search_mode) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                    (draft_id,session_id,title,goal,feedback,1,json.dumps(plan,ensure_ascii=False),json.dumps(sources,ensure_ascii=False),None,now(),now(),json.dumps(search_report or {},ensure_ascii=False),source_policy,learner_level,search_mode))
            else:
                changed=db.execute('UPDATE course_drafts SET title=?,goal=?,feedback=?,revision=revision+1,plan_json=?,sources_json=?,search_report_json=?,updated_at=?,source_policy=?,learner_level=?,search_mode=? WHERE id=? AND session_id=? AND revision=? AND confirmed_course_id IS NULL',
                    (title,goal,feedback,json.dumps(plan,ensure_ascii=False),json.dumps(sources,ensure_ascii=False),json.dumps(search_report or {},ensure_ascii=False),now(),source_policy,learner_level,search_mode,draft_id,session_id,expected_revision)).rowcount
                if not changed:raise ValueError('审查稿已经变化，请刷新后重新修改')
            if manager_fields is not None:
                db.execute('UPDATE course_drafts SET management_json=? WHERE id=?',(json.dumps(manager_fields,ensure_ascii=False),draft_id))
            if documents is not None:
                db.execute('DELETE FROM draft_documents WHERE draft_id=?',(draft_id,))
                for doc in documents:db.execute('INSERT INTO draft_documents VALUES(?,?,?)',(draft_id,doc['id'],json.dumps(doc,ensure_ascii=False)))
        return self.draft(session_id,draft_id)

    def confirm_draft(self, session_id: str, draft_id: str, expected_revision: int) -> dict:
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM course_drafts WHERE id=? AND session_id=?",
                             (draft_id, session_id)).fetchone()
            if not row:
                raise ValueError("课程审查稿不存在")
            if row["confirmed_course_id"]:
                course_id = row["confirmed_course_id"]
            else:
                if row["revision"] != expected_revision:
                    raise ValueError("审查稿已经变化，请先查看最新版再确认")
                course_id = secrets.token_urlsafe(16)
                db.execute("INSERT INTO courses(id,session_id,title,goal,current_ordinal,created_at,source_policy,learner_level,search_mode) VALUES(?,?,?,?,?,?,?,?,?)",
                           (course_id, session_id, row["title"], row["goal"], 1, now(),row["source_policy"],row["learner_level"],row["search_mode"]))
                order=db.execute('SELECT COALESCE(MAX(sort_order),0)+1 FROM courses WHERE session_id=? AND id!=? AND deleted_at IS NULL',(session_id,course_id)).fetchone()[0]
                db.execute('UPDATE courses SET sort_order=?,updated_at=? WHERE id=?',(order,now(),course_id))
                info=json.loads(row['management_json'])
                if info:db.execute('UPDATE courses SET '+','.join(k+'=?' for k in info)+' WHERE id=?',(*info.values(),course_id))
                documents=db.execute("SELECT document_json FROM draft_documents WHERE draft_id=?",(draft_id,)).fetchall()
                for document in documents:
                    d=json.loads(document[0])
                    db.execute("INSERT INTO source_documents VALUES(?,?,?,?,?,?,?,?,?)",(d["id"],course_id,d["title"],d["source_type"],d["origin"],d["content"],json.dumps(d["metadata"],ensure_ascii=False),d["created_time"],d["processing_status"]))
                for ordinal, item in enumerate(json.loads(row["plan_json"])["sections"], 1):
                    db.execute("INSERT INTO sections(id,course_id,ordinal,title,objective,lesson,created_at) VALUES(?,?,?,?,?,?,?)",
                               (secrets.token_urlsafe(16), course_id, ordinal,
                                item["title"], item["objective"], None, now()))
                    meta = metadata(item, info)
                    db.execute('UPDATE sections SET ' + ','.join(k+'=?' for k in meta) + ' WHERE course_id=? AND ordinal=?',
                               (*[json.dumps(v,ensure_ascii=False) if isinstance(v,list) else v for v in meta.values()],course_id,ordinal))
                db.execute("UPDATE course_drafts SET confirmed_course_id=?,updated_at=? WHERE id=?",
                           (course_id, now(), draft_id))
        course=self.course(session_id,course_id)
        if not course:raise ValueError('课程已进入回收站，请先恢复课程')
        return course

    def confirmed_review(self, session_id: str, course_id: str) -> dict | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM course_drafts WHERE session_id=? AND confirmed_course_id=?",
                             (session_id, course_id)).fetchone()
        return self._draft_public(dict(row)) if row else None

    def courses(self, session_id: str) -> list[dict]:
        return self.managed_courses(session_id)

    def course(self, session_id: str, course_id: str) -> dict | None:
        with self.connect() as db:
            course = db.execute("SELECT * FROM courses WHERE id=? AND session_id=? AND deleted_at IS NULL",
                                (course_id, session_id)).fetchone()
            if not course:
                return None
            sections = db.execute("SELECT * FROM sections WHERE course_id=? ORDER BY ordinal", (course_id,)).fetchall()
        return {**dict(course), "sections": [{**dict(s), **metadata(dict(s), dict(course)),
                 'lesson_stale':bool(s['lesson'] and s['lesson_revision']!=course['content_revision']),
                 'lesson_blocks':json.loads(s['lesson_blocks_json']),'teaching_action':json.loads(s['teaching_action_json'])} for s in sections]}

    def content_versions(self,session_id,course_id,kind,identifier):
        self._knowledge_course(session_id,course_id)
        with self.connect() as db:
            rows=db.execute('SELECT revision,snapshot_json,created_at FROM content_history WHERE course_id=? AND object_type=? AND object_id=? ORDER BY id DESC LIMIT 5',(course_id,kind,identifier)).fetchall()
        return [{'revision':r['revision'],'snapshot':json.loads(r['snapshot_json']),'created_at':r['created_at']} for r in rows]

    def section(self, session_id: str, course_id: str, ordinal: int) -> dict | None:
        course = self.course(session_id, course_id)
        if not course or not 1 <= ordinal <= course["current_ordinal"]:
            return None
        return course["sections"][ordinal - 1]

    def save_lesson(self, session_id: str, course_id: str, section_id: str, lesson: str,
                    teaching_context: dict | None = None, validation: dict | None = None, teaching_package: dict | None = None, *, expected_revision=None, regenerate=False) -> bool:
        course = self.course(session_id, course_id)
        if not course or not any(s['id'] == section_id and s['ordinal'] <= course['current_ordinal'] for s in course['sections']):
            return False
        teaching_context = teaching_context or TeachingOrchestrator(self).context(session_id,course_id,section_id)
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            revision=db.execute('SELECT content_revision FROM courses WHERE id=?',(course_id,)).fetchone()[0]
            if expected_revision is not None and revision!=expected_revision:raise ValueError('课程依据已更新，请重新生成本节讲解')
            if regenerate:
                old=db.execute('SELECT * FROM sections WHERE id=? AND course_id=?',(section_id,course_id)).fetchone()
                if old and old['lesson']:
                    from .revisions import archive
                    archive(db,course_id,'lesson',section_id,old['lesson_revision'],dict(old))
            row = db.execute("SELECT 1 FROM sections s JOIN courses c ON c.id=s.course_id "
                             "WHERE s.id=? AND s.course_id=? AND c.session_id=? AND c.deleted_at IS NULL AND s.ordinal<=c.current_ordinal",
                             (section_id, course_id, session_id)).fetchone()
            if not row:
                return False
            # First successful generation wins; repeat requests never overwrite the learner's history.
            changed = db.execute("UPDATE sections SET lesson=?,lesson_revision=? WHERE id=?"+("" if regenerate else " AND lesson IS NULL"),
                                 (lesson, revision, section_id)).rowcount
            if changed:
                from .learning.service import LearningLoopService
                LearningLoopService(self).section_signal(db,session_id,course_id,section_id,'lesson_check','lesson:'+section_id+':'+str(revision))
                if teaching_package:
                    blocks=json.dumps(teaching_package['blocks'],ensure_ascii=False);decision=json.dumps(teaching_package['teaching_action'],ensure_ascii=False)
                    db.execute('UPDATE sections SET lesson_blocks_json=?,teaching_action_json=? WHERE id=?',(blocks,decision,section_id))
                    self.record_teaching_action(db,session_id,course_id,section_id,None,teaching_package)
                db.execute("INSERT INTO tutor_turns(course_id,section_id,role,content,created_at) "
                           "VALUES(?,?,?,?,?)", (course_id, section_id, "assistant", lesson, now()))
                if teaching_package:db.execute('UPDATE tutor_turns SET blocks_json=?,action_json=? WHERE id=last_insert_rowid()',(blocks,decision))
                covered = [name for name in teaching_context['core_atoms'] if contains(lesson, name)]
                db.execute('INSERT INTO lesson_teaching_records(user_id,course_id,lesson_id,covered_atoms,created_time,context_json,validation_json) VALUES(?,?,?,?,?,?,?)',
                           (session_id,course_id,section_id,json.dumps(covered,ensure_ascii=False),now(),
                            json.dumps(teaching_context,ensure_ascii=False),json.dumps(validation or {'method':'not_checked'},ensure_ascii=False)))
        return True

    def tutor_turns(self, session_id: str, course_id: str, section_id: str) -> list[dict]:
        with self.connect() as db:
            owned = db.execute("SELECT 1 FROM courses WHERE id=? AND session_id=? AND deleted_at IS NULL", (course_id, session_id)).fetchone()
            if not owned:
                return []
            rows = db.execute("SELECT role,content,created_at,blocks_json,action_json FROM tutor_turns "
                              "WHERE course_id=? AND section_id=? ORDER BY id", (course_id, section_id)).fetchall()
        return [{**dict(r),'blocks':json.loads(r['blocks_json']),'teaching_action':json.loads(r['action_json'])} for r in rows]

    def add_tutor_exchange(self, session_id: str, course_id: str, section_id: str,
                           question: str, answer: str, teaching_package: dict | None = None) -> None:
        with self.connect() as db:
            owned = db.execute("SELECT 1 FROM sections s JOIN courses c ON c.id=s.course_id "
                               "WHERE s.id=? AND s.course_id=? AND c.session_id=? AND c.deleted_at IS NULL",
                               (section_id, course_id, session_id)).fetchone()
            if not owned:
                raise ValueError("小节不存在")
            db.executemany("INSERT INTO tutor_turns(course_id,section_id,role,content,created_at) "
                           "VALUES(?,?,?,?,?)", [(course_id, section_id, role, content, now())
                                               for role, content in (("user", question), ("assistant", answer))])
            if teaching_package:
                db.execute('UPDATE tutor_turns SET blocks_json=?,action_json=? WHERE id=(SELECT MAX(id) FROM tutor_turns WHERE course_id=? AND section_id=?)',
                           (json.dumps(teaching_package['blocks'],ensure_ascii=False),json.dumps(teaching_package['teaching_action'],ensure_ascii=False),course_id,section_id))
                self.record_teaching_action(db,session_id,course_id,section_id,None,teaching_package)
            from .learning.service import LearningLoopService
            from .learning.evidence import mark_help
            mark_help(db,course_id,section_id)
            LearningLoopService(self).section_signal(db,session_id,course_id,section_id,'tutor_interaction','turn:'+str(db.execute('SELECT MAX(id) FROM tutor_turns').fetchone()[0]))

    def advance(self, session_id: str, course_id: str, expected: int) -> bool:
        with self.connect() as db:
            changed = db.execute("UPDATE courses SET current_ordinal=current_ordinal+1 "
                                 "WHERE id=? AND session_id=? AND deleted_at IS NULL AND current_ordinal=? "
                                 "AND current_ordinal<(SELECT COUNT(*) FROM sections WHERE course_id=?)",
                                 (course_id, session_id, expected, course_id)).rowcount
        return bool(changed)

    def section_quizzes(self, session_id: str, course_id: str, section_id: str) -> list[dict]:
        with self.connect() as db:
            owned = db.execute("SELECT 1 FROM courses WHERE id=? AND session_id=? AND deleted_at IS NULL", (course_id, session_id)).fetchone()
            if not owned:
                return []
            rows = db.execute("SELECT * FROM quizzes WHERE course_id=? AND section_id=? AND scope='section' ORDER BY rowid",
                              (course_id, section_id)).fetchall()
        return [self._quiz_public(dict(r)) for r in rows]

    @staticmethod
    def _quiz_public(row: dict) -> dict:
        questions = json.loads(row["questions_json"])
        public = {"id": row["id"], "questions": questions, "score": row["score"],
                  "submitted_at": row["submitted_at"], "created_at": row["created_at"],
                  "assessment_kind":row.get('assessment_kind','chapter_quiz'),"hint_used":json.loads(row.get('hint_flags_json','[]')),
                  "confidence":json.loads(row.get('confidence_json','[]'))}
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
                               "WHERE s.id=? AND s.course_id=? AND c.session_id=? AND c.deleted_at IS NULL AND s.lesson IS NOT NULL "
                               "AND s.ordinal<=c.current_ordinal", (section_id, course_id, session_id)).fetchone()
            if not owned:
                raise ValueError("请先完成当前小节讲解")
            pending = db.execute("SELECT * FROM quizzes WHERE course_id=? AND section_id=? "
                                 "AND scope='section' AND submitted_at IS NULL ORDER BY rowid DESC LIMIT 1",
                                 (course_id, section_id)).fetchone()
            if pending:
                return self._quiz_public(dict(pending))
            from .learning.calibration import capture_prediction
            from .learning.state import empty
            for atom in {a for q in questions for a in q.get('atom_ids',[])}:
                raw=db.execute('SELECT state_json FROM knowledge_states WHERE user_id=? AND course_id=? AND atom_id=?',(session_id,course_id,atom)).fetchone()
                capture_prediction(db,session_id,course_id,atom,json.loads(raw[0]) if raw else empty(atom),salt=quiz_id)
            db.execute("INSERT INTO quizzes(id,course_id,section_id,questions_json,answers_json,user_answers_json,score,created_at,submitted_at) VALUES(?,?,?,?,?,?,?,?,?)",
                       (quiz_id, course_id, section_id, json.dumps(questions, ensure_ascii=False),
                        json.dumps(answers, ensure_ascii=False), None, None, now(), None))
        return {"id": quiz_id, "questions": questions, "score": None}

    def submit_quiz(self, session_id: str, course_id: str, quiz_id: str,
                    user_answers: list[str], confidence=None, hint_used=None, response_time_ms=None) -> dict:
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute("SELECT q.* FROM quizzes q JOIN courses c ON c.id=q.course_id "
                             "WHERE q.id=? AND q.course_id=? AND c.session_id=? AND c.deleted_at IS NULL",
                             (quiz_id, course_id, session_id)).fetchone()
            if not row:
                raise ValueError("测试不存在")
            if row["submitted_at"]:
                raise ValueError("这次测试已经提交，请生成新测试继续复测")
            if row['assessment_kind'].startswith('final_'):
                from .learning.final import validate_submission
                validate_submission(db,session_id,course_id,row)
            elif row['loop_session_id']:
                table='repair_sessions' if row['assessment_kind']=='remediation' else 'returning_sessions'
                task=db.execute(f'SELECT status FROM {table} WHERE id=? AND user_id=? AND course_id=?',(row['loop_session_id'],session_id,course_id)).fetchone()
                if not task or task[0] not in {'diagnostic','teaching','checking','pending'}:
                    raise ValueError('学习任务已结束，请刷新后重新选择检测')
            answers = json.loads(row["answers_json"])
            if len(user_answers) != len(answers) or any(a not in {"a", "b", "c", "d"} for a in user_answers):
                raise ValueError("请完成全部题目后提交")
            count=len(answers)
            confidence=confidence if confidence is not None else [None]*count
            times=response_time_ms if response_time_ms is not None else [None]*count
            reported=hint_used if hint_used is not None else [False]*count
            if (not isinstance(confidence,list) or len(confidence)!=count or any(v not in (None,'low','medium','high') for v in confidence)
                    or not isinstance(reported,list) or len(reported)!=count or any(type(v) is not bool for v in reported)
                    or not isinstance(times,list) or len(times)!=count or any(v is not None and (type(v) is not int or not 0<=v<=3600000) for v in times)):
                raise ValueError('答题信心、提示或用时记录无效')
            hints=json.loads(row['hint_flags_json']) or [False]*count
            hints=[saved or offered for saved,offered in zip(hints,reported)]
            score = sum(a == item["answer"] for a, item in zip(user_answers, answers))
            changed = db.execute("UPDATE quizzes SET user_answers_json=?,score=?,submitted_at=? "
                                 "WHERE id=? AND submitted_at IS NULL",
                                 (json.dumps(user_answers), score, now(), quiz_id)).rowcount
            if not changed:
                raise ValueError("这次测试已经提交，请生成新测试继续复测")
            db.execute('UPDATE quizzes SET confidence_json=?,hint_flags_json=?,response_times_json=? WHERE id=?',(json.dumps(confidence),json.dumps(hints),json.dumps(times),quiz_id))
            graded=db.execute('SELECT * FROM quizzes WHERE id=?',(quiz_id,)).fetchone()
            from .learning.service import LearningLoopService
            LearningLoopService(self).submitted(db,graded,confidence,hints,times)
            from .learning.final import FinalAssessmentService
            FinalAssessmentService(self).on_submit(db,session_id,course_id,graded)
            from .learning.cross_course import CrossCourseVerification
            CrossCourseVerification.on_submit(db,session_id,course_id,graded)
        return {"id": quiz_id, "score": score, "total": len(answers),
                "results": [{"correct": a == item["answer"], **item}
                            for a, item in zip(user_answers, answers)]}

    def mastery(self, session_id: str, course_id: str) -> dict:
        course = self.course(session_id, course_id)
        if not course:
            raise ValueError("课程不存在")
        with self.connect() as db:
            rows = db.execute("SELECT section_id,score,answers_json FROM quizzes "
                              "WHERE course_id=? AND scope='section' AND submitted_at IS NOT NULL ORDER BY rowid",
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
