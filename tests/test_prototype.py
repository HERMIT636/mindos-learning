"""End-to-end checks for reviewed custom courses and isolated learning state."""

from __future__ import annotations

import http.cookiejar
import json
import sqlite3
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from mindos.secrets import SecretStore
from mindos.server import MindOSServer
from mindos.storage import Storage
from mindos.web_search import PublicSourceSearch, WebSearch


class FakeProvider(BaseHTTPRequestHandler):
    lesson_payloads: list[dict] = []
    search_queries: list[str] = []

    def do_GET(self) -> None:
        parsed = urllib.parse.urlsplit(self.path)
        if parsed.path == "/w/api.php":
            self.send_json({"query": {"search": [{"title": "机器学习", "snippet": "从基础概念开始"}]}})
            return
        if parsed.path == "/search/repositories":
            self.send_json({"items": [{"full_name": "example/course", "html_url": "https://github.com/example/course",
                                       "description": "公开教程与实例"}]})
            return
        if parsed.path != "/res/v1/web/search":
            self.send_error(404); return
        if self.headers.get("X-Subscription-Token") != "search-test-private-key":
            self.send_error(401); return
        query = urllib.parse.parse_qs(parsed.query)["q"][0]
        self.search_queries.append(query)
        result = {"web": {"results": [{"title": "公开入门课程大纲", "url": "https://example.edu/syllabus",
                                        "description": "从基础概念到应用的学习顺序"},
                                       {"title": "官方学习指南", "url": "https://docs.example.org/guide",
                                        "description": "核心知识点和入门路径"}]}}
        self.send_json(result)

    def do_POST(self) -> None:
        payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if self.path != "/chat/completions":
            self.send_error(404); return
        system = payload["messages"][0]["content"]
        user = json.loads(payload["messages"][-1]["content"]) if len(payload["messages"]) > 1 and \
            payload["messages"][-1]["content"].startswith("{") else {}
        if "课程调研助手" in system:
            content = json.dumps({"queries": ["入门课程 大纲 教程", "核心知识 先修 路线"]}, ensure_ascii=False)
        elif "课程规划教师" in system:
            feedback = user.get("latest_revision_request", "")
            content = json.dumps({
                "overview": "这门课从最常用的基础概念学起，逐步认识核心问题，最后练习把知识用于真实场景。",
                "outcomes": ["能解释这门课的基础概念", "能完成一个简单的应用任务"],
                "directions": ["先建立必要的基础词汇和直觉", "更多实践与动手练习" if "实践" in feedback else "再学习主要方法与应用"],
                "sections": [{"title": f"第 {i} 节基础", "objective": f"理解第 {i} 步的核心概念"} for i in range(1, 5)],
            }, ensure_ascii=False)
        elif "独立小测出题教师" in system:
            previous_count = len(user["previous_questions"])
            content = json.dumps({"questions": [{"prompt": f"第 {previous_count // 4 + 1} 次测试：关于本节概念 {i}，哪种解释正确？",
                  "choices": {"a": "错误解释", "b": "正确解释", "c": "另一错误解释", "d": "无关解释"},
                  "answer": "b", "explanation": "选项 b 符合本节讲解。"} for i in range(1, 5)]}, ensure_ascii=False)
        elif "连接测试助手" in system:
            content = "OK"
        elif "现在只讲当前这一小节" in system:
            self.lesson_payloads.append(user)
            content = "## 从零开始\n本节详细讲解：先建立直觉，再看例子与误区。\n\n## 例子\n一步一步说明。"
        else:
            content = "继续解释当前小节，并回答你的困惑。"
        self.send_json({"choices": [{"message": {"content": content}, "finish_reason": "stop"}]})

    def send_json(self, result: dict) -> None:
        body = json.dumps(result).encode()
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
        cls.provider = ThreadingHTTPServer(("127.0.0.1", 0), FakeProvider)
        cls.provider_thread = threading.Thread(target=cls.provider.serve_forever, daemon=True)
        cls.provider_thread.start()
        cls.original_search_endpoint = WebSearch.ENDPOINT
        cls.original_wikipedia_endpoints = PublicSourceSearch.WIKIPEDIA_ENDPOINTS
        cls.original_github_endpoint = PublicSourceSearch.GITHUB_ENDPOINT
        WebSearch.ENDPOINT = f"http://127.0.0.1:{cls.provider.server_port}/res/v1/web/search"
        PublicSourceSearch.WIKIPEDIA_ENDPOINTS = {
            "zh": f"http://127.0.0.1:{cls.provider.server_port}/w/api.php",
            "en": f"http://127.0.0.1:{cls.provider.server_port}/w/api.php",
        }
        PublicSourceSearch.GITHUB_ENDPOINT = f"http://127.0.0.1:{cls.provider.server_port}/search/repositories"
        cls.data_path = Path(cls.directory.name) / "mindos.sqlite3"
        cls.server = MindOSServer(0, cls.data_path)
        cls.server.secrets = SecretStore(Path(cls.directory.name) / "master.key")
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown(); cls.server.server_close(); cls.thread.join(timeout=2)
        cls.provider.shutdown(); cls.provider.server_close(); cls.provider_thread.join(timeout=2)
        WebSearch.ENDPOINT = cls.original_search_endpoint
        PublicSourceSearch.WIKIPEDIA_ENDPOINTS = cls.original_wikipedia_endpoints
        PublicSourceSearch.GITHUB_ENDPOINT = cls.original_github_endpoint
        cls.directory.cleanup()

    def setUp(self) -> None:
        self.cookies = http.cookiejar.CookieJar()
        self.client = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cookies))

    def call(self, path: str, payload: dict | None = None, client=None) -> tuple[int, dict]:
        data = json.dumps(payload).encode() if payload is not None else None
        request = urllib.request.Request(self.url + path, data=data,
                                         headers={"Content-Type": "application/json"} if data else {})
        try:
            with (client or self.client).open(request, timeout=8) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as exc:
            with exc:
                return exc.code, json.loads(exc.read())

    def configure(self) -> None:
        status, result = self.call("/api/models/save", {"name": "测试模型",
            "base_url": f"http://127.0.0.1:{self.provider.server_port}",
            "chat_model": "fake", "api_key": "model-test-private-key"})
        self.assertEqual(status, 200)
        self.assertTrue(result["model_ready"])
        self.assertNotIn("model-test-private-key", json.dumps(result))
        status, result = self.call("/api/search/save", {"api_key": "search-test-private-key"})
        self.assertEqual(status, 200)
        self.assertTrue(result["search_ready"])
        self.assertNotIn("search-test-private-key", json.dumps(result))
        with sqlite3.connect(self.data_path) as db:
            encrypted = db.execute("SELECT encrypted_api_key FROM search_settings WHERE session_id=?",
                                   (self.session_id(),)).fetchone()[0]
        self.assertNotIn("search-test-private-key", encrypted)
        self.assertEqual(self.server.secrets.decrypt(encrypted), "search-test-private-key")

    def session_id(self) -> str:
        return next(cookie.value for cookie in self.cookies if cookie.name == "mindos_session")

    def draft_and_confirm(self, title: str, goal: str = "") -> str:
        before = len(self.call("/api/bootstrap")[1]["courses"])
        status, drafted = self.call("/api/courses/draft", {"title": title, "goal": goal,
                                                             "search_mode": "brave"})
        self.assertEqual(status, 200)
        draft = drafted["draft"]
        self.assertEqual(draft["revision"], 1)
        self.assertEqual(len(draft["sources"]), 2)
        self.assertIn("学起", draft["plan"]["overview"])
        self.assertEqual(len(self.call("/api/bootstrap")[1]["courses"]), before)
        status, confirmed = self.call("/api/courses/confirm", {"draft_id": draft["id"], "revision": 1})
        self.assertEqual(status, 200)
        return confirmed["course_id"]

    def test_review_revision_confirmation_and_refresh(self) -> None:
        self.configure()
        status, drafted = self.call("/api/courses/draft", {"title": "课程甲", "goal": "从零开始",
                                                         "search_mode": "brave"})
        self.assertEqual(status, 200)
        first = drafted["draft"]
        self.assertEqual(first["revision"], 1)
        self.assertEqual(len(first["sources"]), 2)
        self.assertEqual(len(first["plan"]["sections"]), 4)
        self.assertEqual(self.call("/api/bootstrap")[1]["courses"], [])
        status, old_endpoint = self.call("/api/courses/create", {"title": "绕过审查"})
        self.assertEqual(status, 404)
        status, revised = self.call("/api/courses/draft", {"draft_id": first["id"], "revision": 1,
            "title": "课程甲", "goal": "从零开始", "feedback": "增加更多实践",
            "search_mode": "brave"})
        self.assertEqual(status, 200)
        latest = revised["draft"]
        self.assertEqual(latest["revision"], 2)
        self.assertIn("实践", latest["plan"]["directions"][1])
        self.assertEqual(self.call(f"/api/draft?draft_id={first['id']}")[1]["draft"]["revision"], 2)
        self.assertEqual(len(self.call("/api/bootstrap")[1]["drafts"]), 1)
        status, stale = self.call("/api/courses/confirm", {"draft_id": first["id"], "revision": 1})
        self.assertEqual(status, 400)
        status, confirmed = self.call("/api/courses/confirm", {"draft_id": latest["id"], "revision": 2})
        self.assertEqual(status, 200)
        course_id = confirmed["course_id"]
        self.assertEqual(confirmed["course"]["course"]["current_ordinal"], 1)
        self.assertIsNone(confirmed["course"]["section"]["lesson"])
        self.assertEqual(confirmed["course"]["review"]["revision"], 2)
        status, repeated = self.call("/api/courses/confirm", {"draft_id": latest["id"], "revision": 2})
        self.assertEqual(repeated["course_id"], course_id)
        self.assertEqual(len(self.call("/api/bootstrap")[1]["courses"]), 1)
        self.assertEqual(self.call("/api/bootstrap")[1]["drafts"], [])
        self.assertGreaterEqual(len(FakeProvider.search_queries), 4)

    def test_course_flow_persists_quizzes_and_isolates_memory(self) -> None:
        self.configure()
        course_id = self.draft_and_confirm("课程乙", "从零开始")
        status, blocked = self.call("/api/sections/quiz", {"course_id": course_id, "ordinal": 2})
        self.assertEqual(status, 400)
        status, lesson = self.call("/api/sections/lesson", {"course_id": course_id, "ordinal": 1})
        self.assertEqual(status, 200)
        self.assertIn("从零开始", lesson["section"]["lesson"])
        self.assertEqual(len(self.call("/api/sections/lesson", {"course_id": course_id, "ordinal": 1})[1]["turns"]), 1)
        status, quiz = self.call("/api/sections/quiz", {"course_id": course_id, "ordinal": 1})
        self.assertEqual(status, 200)
        self.assertNotIn("answer", json.dumps(quiz["quizzes"][0]))
        status, submitted = self.call("/api/quizzes/submit", {"course_id": course_id,
            "quiz_id": quiz["quizzes"][0]["id"], "answers": ["b", "b", "a", "a"]})
        self.assertEqual(status, 200)
        self.assertEqual(submitted["mastery"]["sections"][0]["rate"], 50)
        status, retest = self.call("/api/sections/quiz", {"course_id": course_id, "ordinal": 1})
        self.assertEqual(status, 200)
        status, improved = self.call("/api/quizzes/submit", {"course_id": course_id,
            "quiz_id": retest["quizzes"][-1]["id"], "answers": ["b"] * 4})
        self.assertEqual(improved["mastery"]["sections"][0]["rate"], 75)
        other_id = self.draft_and_confirm("课程丙", "独立目标")
        self.assertEqual(self.server.storage.weak_points(self.session_id(), other_id), [])
        self.call("/api/sections/lesson", {"course_id": other_id, "ordinal": 1})
        self.assertEqual(FakeProvider.lesson_payloads[-1]["earlier_missed_questions"], [])
        status, advanced = self.call("/api/sections/advance", {"course_id": course_id, "expected_ordinal": 1})
        self.assertEqual(status, 200)
        self.assertEqual(advanced["course"]["current_ordinal"], 2)
        self.assertEqual(self.call("/api/sections/advance", {"course_id": course_id,
            "expected_ordinal": 1})[0], 400)
        self.call("/api/sections/lesson", {"course_id": course_id, "ordinal": 2})
        self.assertTrue(FakeProvider.lesson_payloads[-1]["earlier_missed_questions"])
        self.assertEqual(FakeProvider.lesson_payloads[-1]["course"], "课程乙")
        self.assertEqual(len(self.call(f"/api/course?course_id={course_id}&ordinal=1")[1]["quizzes"]), 2)
        self.assertEqual(Storage(self.data_path).course(self.session_id(), course_id)["current_ordinal"], 2)

    def test_other_browser_cannot_read_or_confirm_draft(self) -> None:
        self.configure()
        _, drafted = self.call("/api/courses/draft", {"title": "私有课程", "search_mode": "brave"})
        draft_id = drafted["draft"]["id"]
        other = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self.assertEqual(self.call("/api/bootstrap", client=other)[1]["drafts"], [])
        self.assertEqual(self.call(f"/api/draft?draft_id={draft_id}", client=other)[0], 400)
        self.assertEqual(self.call("/api/courses/confirm", {"draft_id": draft_id, "revision": 1}, other)[0], 400)

    def test_keyless_sources_work_and_brave_is_optional(self) -> None:
        status, saved = self.call("/api/models/save", {"name": "仅模型",
            "base_url": f"http://127.0.0.1:{self.provider.server_port}",
            "chat_model": "fake", "api_key": "model-only"})
        self.assertEqual(status, 200)
        status, result = self.call("/api/courses/draft", {"title": "只有模型的课程"})
        self.assertEqual(status, 200)
        self.assertTrue(result["draft"]["sources"])
        self.assertTrue({source["provider"] for source in result["draft"]["sources"]} &
                        {"Wikipedia zh", "Wikipedia en", "GitHub"})
        self.assertFalse(self.call("/api/bootstrap")[1]["search_ready"])
        status, missing = self.call("/api/courses/draft", {"title": "需要 Brave 的课程",
                                                             "search_mode": "brave"})
        self.assertEqual(status, 503)
        self.assertIn("搜索密钥", missing["error"])
        self.call("/api/search/save", {"api_key": "wrong-search-key"})
        status, invalid = self.call("/api/courses/draft", {"title": "密钥错误的课程",
                                                             "search_mode": "brave"})
        self.assertEqual(status, 503)
        self.assertIn("搜索密钥无效", invalid["error"])
        self.assertEqual(len(self.call("/api/bootstrap")[1]["drafts"]), 1)
        self.call("/api/search/save", {"api_key": "search-test-private-key"})
        first = result["draft"]
        status, revised = self.call("/api/courses/draft", {
            "draft_id": first["id"], "revision": first["revision"], "title": first["title"],
            "goal": first["goal"], "search_mode": "brave"})
        self.assertEqual(status, 200)
        self.assertEqual({source["provider"] for source in revised["draft"]["sources"]}, {"Brave"})

    def test_keyless_search_failure_does_not_invent_sources(self) -> None:
        self.call("/api/models/save", {"name": "测试模型", "base_url": f"http://127.0.0.1:{self.provider.server_port}",
                                       "chat_model": "fake", "api_key": "model-only"})
        old_wiki = PublicSourceSearch.WIKIPEDIA_ENDPOINTS
        old_github = PublicSourceSearch.GITHUB_ENDPOINT
        try:
            PublicSourceSearch.WIKIPEDIA_ENDPOINTS = {"zh": "http://127.0.0.1:1/w/api.php"}
            PublicSourceSearch.GITHUB_ENDPOINT = "http://127.0.0.1:1/search/repositories"
            status, failed = self.call("/api/courses/draft", {"title": "无法检索的课程"})
        finally:
            PublicSourceSearch.WIKIPEDIA_ENDPOINTS = old_wiki
            PublicSourceSearch.GITHUB_ENDPOINT = old_github
        self.assertEqual(status, 503)
        self.assertIn("检索暂时不可用", failed["error"])
        self.assertEqual(self.call("/api/bootstrap")[1]["drafts"], [])

    def test_old_data_migrates_with_backup_and_preserves_model_profile(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "old.sqlite3"
            with sqlite3.connect(path) as db:
                db.execute("CREATE TABLE learning_targets (session_id TEXT)")
                db.execute("CREATE TABLE model_profiles (id TEXT PRIMARY KEY,name TEXT,base_url TEXT,chat_model TEXT,embedding_model TEXT,encrypted_api_key TEXT)")
                db.execute("INSERT INTO model_profiles VALUES('p','name','https://example.com','model','','ciphertext')")
            store = Storage(path)
            self.assertEqual(len(store.model_profiles()), 1)
            self.assertTrue(path.with_name(path.name + ".before-custom-courses.sqlite3").exists())
