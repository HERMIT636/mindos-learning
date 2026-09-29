"""End-to-end checks for custom course persistence and per-course learning state."""

from __future__ import annotations

import http.cookiejar
import json
import sqlite3
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from mindos.secrets import SecretStore
from mindos.server import MindOSServer
from mindos.storage import Storage


class FakeModelHandler(BaseHTTPRequestHandler):
    lesson_payloads: list[dict] = []

    def do_POST(self) -> None:
        payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if self.path != "/chat/completions":
            self.send_error(404)
            return
        system = payload["messages"][0]["content"]
        if "课程规划教师" in system:
            content = json.dumps({"sections": [{"title": f"第 {i} 节基础", "objective": f"理解第 {i} 步的核心概念"}
                                                for i in range(1, 5)]}, ensure_ascii=False)
        elif "独立小测出题教师" in system:
            previous_count = len(json.loads(payload["messages"][-1]["content"])["previous_questions"])
            content = json.dumps({"questions": [{"prompt": f"第 {previous_count // 4 + 1} 次测试：关于本节概念 {i}，哪种解释正确？",
                  "choices": {"a": "错误解释", "b": "正确解释", "c": "另一错误解释", "d": "无关解释"},
                  "answer": "b", "explanation": "选项 b 符合本节讲解。"} for i in range(1, 5)]}, ensure_ascii=False)
        elif "连接测试助手" in system:
            content = "OK"
        elif "现在只讲当前这一小节" in system:
            self.lesson_payloads.append(json.loads(payload["messages"][-1]["content"]))
            content = "## 从零开始\n本节详细讲解：先建立直觉，再看例子与误区。\n\n## 例子\n一步一步说明。"
        else:
            content = "继续解释当前小节，并回答你的困惑。"
        body = json.dumps({"choices": [{"message": {"content": content}, "finish_reason": "stop"}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args) -> None:
        pass


class PrototypeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.directory = tempfile.TemporaryDirectory()
        cls.model = ThreadingHTTPServer(("127.0.0.1", 0), FakeModelHandler)
        cls.model_thread = threading.Thread(target=cls.model.serve_forever, daemon=True)
        cls.model_thread.start()
        cls.data_path = Path(cls.directory.name) / "mindos.sqlite3"
        cls.server = MindOSServer(0, cls.data_path)
        cls.server.secrets = SecretStore(Path(cls.directory.name) / "master.key")
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown(); cls.server.server_close(); cls.thread.join(timeout=2)
        cls.model.shutdown(); cls.model.server_close(); cls.model_thread.join(timeout=2)
        cls.directory.cleanup()

    def setUp(self) -> None:
        self.cookies = http.cookiejar.CookieJar()
        self.client = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cookies))

    def call(self, path: str, payload: dict | None = None, client=None) -> tuple[int, dict]:
        data = json.dumps(payload).encode() if payload is not None else None
        request = urllib.request.Request(self.url + path, data=data,
                                         headers={"Content-Type": "application/json"} if data else {})
        try:
            with (client or self.client).open(request, timeout=5) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as exc:
            with exc:
                return exc.code, json.loads(exc.read())

    def configure(self) -> None:
        status, result = self.call("/api/models/save", {"name": "测试模型",
            "base_url": f"http://127.0.0.1:{self.model.server_port}",
            "chat_model": "fake", "api_key": "test-private-key"})
        self.assertEqual(status, 200)
        self.assertTrue(result["model_ready"])
        self.assertNotIn("test-private-key", json.dumps(result))

    def test_course_flow_persists_lessons_quizzes_and_isolates_memory(self) -> None:
        self.configure()
        status, created = self.call("/api/courses/create", {"title": "课程甲", "goal": "从零开始"})
        self.assertEqual(status, 200)
        course_id = created["course_id"]
        self.assertEqual(len(created["course"]["course"]["sections"]), 4)
        self.assertEqual(created["course"]["course"]["current_ordinal"], 1)
        self.assertIsNone(created["course"]["section"]["lesson"])
        status, forbidden = self.call("/api/sections/quiz", {"course_id": course_id, "ordinal": 2})
        self.assertEqual(status, 400)
        status, advance = self.call("/api/sections/advance", {"course_id": course_id, "expected_ordinal": 1})
        self.assertEqual(status, 400)
        status, lesson = self.call("/api/sections/lesson", {"course_id": course_id, "ordinal": 1})
        self.assertEqual(status, 200)
        self.assertIn("从零开始", lesson["section"]["lesson"])
        status, repeat = self.call("/api/sections/lesson", {"course_id": course_id, "ordinal": 1})
        self.assertEqual(repeat["section"]["lesson"], lesson["section"]["lesson"])
        self.assertEqual(len(repeat["turns"]), 1)
        status, asked = self.call("/api/sections/ask", {"course_id": course_id, "ordinal": 1,
                                                        "question": "请再解释一遍"})
        self.assertEqual(status, 200)
        self.assertEqual(len(asked["turns"]), 3)
        status, quiz = self.call("/api/sections/quiz", {"course_id": course_id, "ordinal": 1})
        self.assertEqual(status, 200)
        self.assertEqual(len(quiz["quizzes"][0]["questions"]), 4)
        self.assertNotIn("answer", json.dumps(quiz["quizzes"][0]))
        quiz_id = quiz["quizzes"][0]["id"]
        status, submitted = self.call("/api/quizzes/submit", {"course_id": course_id,
            "quiz_id": quiz_id, "answers": ["b", "b", "a", "a"]})
        self.assertEqual(status, 200)
        self.assertEqual(submitted["result"]["score"], 2)
        self.assertEqual(submitted["mastery"]["sections"][0]["rate"], 50)
        self.assertEqual(submitted["mastery"]["sections"][0]["label"], "需补强")
        status, retest = self.call("/api/sections/quiz", {"course_id": course_id, "ordinal": 1})
        self.assertEqual(status, 200)
        self.assertEqual(len(retest["quizzes"]), 2)
        self.assertIsNone(retest["quizzes"][-1]["score"])
        status, improved = self.call("/api/quizzes/submit", {"course_id": course_id,
            "quiz_id": retest["quizzes"][-1]["id"], "answers": ["b"] * 4})
        self.assertEqual(status, 200)
        self.assertEqual(improved["mastery"]["sections"][0]["rate"], 75)
        status, third = self.call("/api/sections/quiz", {"course_id": course_id, "ordinal": 1})
        self.assertEqual(status, 200)
        status, stable = self.call("/api/quizzes/submit", {"course_id": course_id,
            "quiz_id": third["quizzes"][-1]["id"], "answers": ["b"] * 4})
        self.assertEqual(status, 200)
        self.assertEqual(stable["mastery"]["sections"][0]["label"], "较稳固")
        status, created_b = self.call("/api/courses/create", {"title": "课程乙", "goal": "独立目标"})
        self.assertEqual(status, 200)
        self.assertEqual(created_b["course"]["mastery"]["tested_sections"], 0)
        self.assertIsNone(created_b["course"]["mastery"]["overall_rate"])
        self.assertEqual(self.server.storage.weak_points(self._session_id(), created_b["course_id"]), [])
        status, lesson_b = self.call("/api/sections/lesson", {"course_id": created_b["course_id"], "ordinal": 1})
        self.assertEqual(status, 200)
        self.assertEqual(FakeModelHandler.lesson_payloads[-1]["earlier_missed_questions"], [])
        status, advanced = self.call("/api/sections/advance", {"course_id": course_id, "expected_ordinal": 1})
        self.assertEqual(status, 200)
        self.assertEqual(advanced["course"]["current_ordinal"], 2)
        self.assertIsNone(advanced["section"]["lesson"])
        status, lesson_two = self.call("/api/sections/lesson", {"course_id": course_id, "ordinal": 2})
        self.assertEqual(status, 200)
        self.assertTrue(FakeModelHandler.lesson_payloads[-1]["earlier_missed_questions"])
        self.assertEqual(FakeModelHandler.lesson_payloads[-1]["course"], "课程甲")
        status, duplicate = self.call("/api/sections/advance", {"course_id": course_id, "expected_ordinal": 1})
        self.assertEqual(status, 400)
        status, back = self.call(f"/api/course?course_id={course_id}&ordinal=1")
        self.assertEqual(status, 200)
        self.assertEqual(back["section"]["lesson"], lesson["section"]["lesson"])
        self.assertEqual(len(back["quizzes"]), 3)
        reopened = Storage(self.data_path)
        self.assertEqual(reopened.course(self._session_id(), course_id)["current_ordinal"], 2)

    def _session_id(self) -> str:
        for cookie in self.cookies:
            if cookie.name == "mindos_session":
                return cookie.value
        raise AssertionError("session cookie missing")

    def test_other_browser_cannot_read_or_change_course(self) -> None:
        self.configure()
        _, created = self.call("/api/courses/create", {"title": "私有课程"})
        course_id = created["course_id"]
        other = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        status, data = self.call("/api/bootstrap", client=other)
        self.assertEqual(status, 200)
        self.assertEqual(data["courses"], [])
        status, _ = self.call(f"/api/course?course_id={course_id}", client=other)
        self.assertEqual(status, 400)
        status, _ = self.call("/api/sections/lesson", {"course_id": course_id, "ordinal": 1}, client=other)
        self.assertEqual(status, 400)

    def test_old_data_migrates_with_local_backup_and_preserves_model_profile(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "old.sqlite3"
            with sqlite3.connect(path) as db:
                db.execute("CREATE TABLE learning_targets (session_id TEXT)")
                db.execute("CREATE TABLE model_profiles (id TEXT PRIMARY KEY,name TEXT,base_url TEXT,chat_model TEXT,embedding_model TEXT,encrypted_api_key TEXT)")
                db.execute("INSERT INTO model_profiles VALUES('p','name','https://example.com','model','','ciphertext')")
            store = Storage(path)
            self.assertEqual(len(store.model_profiles()), 1)
            with sqlite3.connect(path) as db:
                self.assertIsNone(db.execute("SELECT name FROM sqlite_master WHERE name='learning_targets'").fetchone())
            backup = path.with_name(path.name + ".before-custom-courses.sqlite3")
            self.assertTrue(backup.exists())
            with sqlite3.connect(backup) as db:
                self.assertIsNotNone(db.execute("SELECT name FROM sqlite_master WHERE name='learning_targets'").fetchone())
