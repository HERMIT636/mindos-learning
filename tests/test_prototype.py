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
    discovery_demo = False
    presentation_demo = False
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
        if self.path == "/search":
            if self.headers.get("Authorization") != "Bearer tavily-test-private-key":
                self.send_error(401); return
            if payload.get("include_raw_content") is not False or payload.get("include_answer") is not False:
                self.send_error(400); return
            self.search_queries.append(payload["query"])
            self.send_json({"results": [{"title": "Tavily 入门资料", "url": "https://example.edu/tavily",
                                         "content": "循序渐进的学习摘要"}]})
            return
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
        elif "课程知识结构设计教师" in system:
            content = json.dumps({"atoms": [{"id": f"a{n}", "section": n, "title": f"知识点 {n}",
                "type": "concept", "summary": f"第 {n} 步核心定义", "why": "用于理解本节核心方法", "depth": 2}
                for n in range(1, len(user["sections"]) + 1)],
                "edges": [{"from": "a1", "to": "a2", "type": "prerequisite"}]}, ensure_ascii=False)
        elif "MindOS课程助教回答规划教师" in system:
            content=json.dumps({'need_search':False,'strategy':'生活例子与数学直觉','queries':['课程 最新版本'],'related_atom_ids':[]})
        elif "MindOS课程智能助教" in system:
            from block_fixture import make_blocks
            ctx=user['learning_context'];current=ctx['current_context'];atoms=ctx['knowledge_atoms']
            content=json.dumps({'blocks':make_blocks(ctx['teaching_action'],f"这是 {ctx['course']['title']} 的问题。可以把它想成按需要挑选信息。先理解定义，再看原因。当前正在学习 {current['section_title']}。"),
                                'related_atom_ids':[a['id'] for a in atoms[:2]]},ensure_ascii=False)
        elif "课程搜索任务规划教师" in system:
            content=json.dumps({'tasks':[{'requirement_index':i,'knowledge_target':gap['title'],
                'purpose':gap['reason'],'search_intent':'补充缺失知识','queries':[gap.get('query') or gap['title']+' 教材'],
                'preferred_sources':['公开教材'],'priority':i+1} for i,gap in enumerate(user['gaps'])]},ensure_ascii=False)
        elif "课程知识需求规划教师" in system:
            documents=user['documents']
            evidence=[]
            if documents:
                document=next((d for d in documents if any(len(b['text'])>=20 for b in d['blocks'])),None)
                if document:
                    block=next(b for b in document['blocks'] if len(b['text'])>=20)
                    evidence=[{'document_id':document['id'],'block_id':block['id'],'quote':block['text'][:100]}]
            requirements=[{'title':'基础概念','section':1,'aspect':'definition','reason':'先检查课程资料是否提供基础定义','evidence':evidence,'query':'基础概念 直观解释 实例'}]
            if self.discovery_demo:
                requirements=([requirements[0]] if evidence else [])+[{'title':'矩阵乘法前置','section':1,'aspect':'prerequisite','reason':'缺少矩阵乘法的直观前置说明','evidence':[],'query':'矩阵乘法 行列 直观说明'}]
            content=json.dumps({'requirements':requirements},ensure_ascii=False)
        elif "资料冲突检查教师" in system:
            conflicts=[]
            if self.discovery_demo:
                uploaded=next((d for d in user['documents'] if d['origin']=='user_upload'),None)
                public=next((d for d in user['documents'] if d['origin']=='web_search'),None)
                if uploaded and public:
                    def ref(doc):
                        block=next(b for b in doc['blocks'] if 'Softmax output' in b['text'])
                        return {'document_id':doc['id'],'block_id':block['id'],'quote':block['text']}
                    conflicts=[{'topic':'Softmax','description':'两个来源对权重的符号与总和存在明显不同表述，需要核对原文。','source_a':ref(uploaded),'source_b':ref(public)}]
            content=json.dumps({'conflicts':conflicts})
        elif "资料理解与知识抽取教师" in system:
            blocks = user["structured_blocks"]
            block = next(b for b in blocks if len(b["text"]) >= 20)
            content = json.dumps({"understanding":"这份资料保留了章节与定义，主要解释一个基础概念的含义。",
                "candidates":[{"id":"c1","title":"资料知识点","type":"concept","summary":"资料中的基础概念定义",
                    "why":"用于理解课程的基础问题","depth":2,"evidence":[{"block_id":block["id"],"quote":block["text"][:100]}]}],
                "relations":[]},ensure_ascii=False)
        elif "独立小测出题教师" in system:
            previous_count = len(user["previous_questions"])
            atoms = user.get("atoms", user.get("knowledge_atoms", []))
            context = ("基础摸底" if user.get("diagnostic") else "原子" if "atoms" in user else "章节")
            content = json.dumps({"questions": [{"prompt": f"{context}第 {previous_count // 4 + 1} 次测试：关于本节概念 {i}，哪种解释正确？",
                  "choices": {"a": "错误解释", "b": "正确解释", "c": "另一错误解释", "d": "无关解释"},
                  "answer": "b", "explanation": "选项 b 符合本节讲解。", "assessment_type":['concept','application','reasoning','math'][i-1],
                  **({"atom_ids": [atoms[(i-1) % len(atoms)]["id"]]} if atoms else {})} for i in range(1, 5)]}, ensure_ascii=False)
        elif "连接测试助手" in system:
            content = "OK"
        elif "MindOS结构化教学内容生成教师" in system:
            from block_fixture import make_blocks
            if user['mode']=='lesson':self.lesson_payloads.append(user)
            content=json.dumps({'blocks':make_blocks(user['teaching_action'],'从零开始：这是 '+user['course']+' 的本节详细讲解，先建立直觉，再看例子与误区。')},ensure_ascii=False)
            if self.presentation_demo:
                from presentation_fixture import presentation_reply
                content=json.dumps(presentation_reply(user),ensure_ascii=False)
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
        cls.server.discovery_provider_factory=lambda course: type('EmptyProvider',(),{'search':lambda self,q: []})()
        cls.server.secrets = SecretStore(Path(cls.directory.name) / "master.key")
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls) -> None:
        for worker in cls.server.discovery_engine.threads:worker.join(timeout=5)
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
            encrypted = db.execute("SELECT encrypted_api_key FROM search_profiles WHERE session_id=? AND provider='brave'",
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
        report = result["draft"]["search_report"]
        self.assertEqual(report["mode"], "public")
        self.assertEqual(len(report["sources"]), 3)
        restored = self.call(f"/api/draft?draft_id={result['draft']['id']}")[1]["draft"]
        self.assertEqual(restored["search_report"], report)
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

    def test_tavily_settings_and_review_flow(self) -> None:
        self.configure()
        address = f"http://127.0.0.1:{self.provider.server_port}"
        status, saved = self.call("/api/search/save", {"provider": "tavily", "api_url": address,
                                                     "api_key": "tavily-test-private-key"})
        self.assertEqual(status, 200)
        self.assertNotIn("tavily-test-private-key", json.dumps(saved))
        config = self.server.storage.search_profile(self.session_id(), "tavily")
        self.assertEqual(config["api_url"], address + "/search")
        self.assertNotIn("tavily-test-private-key", config["encrypted_api_key"])
        self.assertEqual(self.server.secrets.decrypt(config["encrypted_api_key"]), "tavily-test-private-key")
        self.assertEqual(self.call("/api/search/save", {"provider": "tavily", "api_key": ""})[0], 200)
        reloaded = Storage(self.data_path).search_profile(self.session_id(), "tavily")
        self.assertEqual(reloaded, config)
        self.assertEqual(self.call("/api/search/save", {"provider": "tavily",
            "api_url": "https://different.example/search", "api_key": ""})[0], 400)
        status, result = self.call("/api/courses/draft", {"title": "Tavily 课程", "search_mode": "tavily"})
        self.assertEqual(status, 200)
        draft = result["draft"]
        self.assertEqual(draft["sources"][0]["provider"], "Tavily")
        self.assertEqual(draft["sources"][0]["description"], "循序渐进的学习摘要")
        status, revised = self.call("/api/courses/draft", {"draft_id": draft["id"], "revision": 1,
            "title": draft["title"], "goal": draft["goal"], "feedback": "更多实践", "search_mode": "tavily"})
        self.assertEqual(status, 200)
        self.assertEqual(self.call("/api/courses/confirm", {"draft_id": draft["id"], "revision": 2})[0], 200)
        other = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        profiles = self.call("/api/bootstrap", client=other)[1]["search_profiles"]
        self.assertFalse(next(p for p in profiles if p["provider"] == "tavily")["has_key"])
        status, cleared = self.call("/api/search/save", {"provider": "tavily", "clear": True})
        self.assertEqual(status, 200)
        self.assertFalse(cleared["search_profiles"][1]["has_key"])
        self.assertTrue(cleared["search_profiles"][0]["has_key"])
        self.assertEqual(self.call("/api/courses/draft", {"title": "缺少密钥课程", "search_mode": "tavily"})[0], 503)

    def test_legacy_search_key_and_invalid_settings(self) -> None:
        self.call("/api/bootstrap")
        encrypted = self.server.secrets.encrypt("search-test-private-key")
        self.server.storage.save_search_key(self.session_id(), encrypted)
        self.assertTrue(self.call("/api/bootstrap")[1]["search_ready"])
        self.assertEqual(self.call("/api/search/save", {"api_key": ""})[0], 200)
        self.assertEqual(self.server.storage.search_profile(self.session_id(), "brave")["encrypted_api_key"], encrypted)
        for address in ("http://example.com/search", "https://user:secret@example.com/search",
                        "https://example.com/search?api_key=secret", "https://example.com/#secret",
                        "https://example.com:bad/search"):
            self.assertEqual(self.call("/api/search/save", {"provider": "tavily", "api_url": address,
                                                           "api_key": "test"})[0], 400)
        for provider in ("unknown", [], None):
            self.assertEqual(self.call("/api/search/save", {"provider": provider, "api_key": "test"})[0], 400)

    def test_knowledge_modes_share_evidence_and_keep_course_boundaries(self) -> None:
        self.configure()
        course_id = self.draft_and_confirm("知识地图课程", "从零开始")
        self.assertEqual(self.call("/api/knowledge/build", {"course_id": course_id})[0], 200)
        state = self.call(f"/api/course?course_id={course_id}")[1]["knowledge"]
        self.assertEqual(state["total"], 4)
        self.assertEqual(state["tested_count"], 0)
        self.assertTrue(all(a["rate"] is None for a in state["atoms"]))
        self.assertEqual(self.call("/api/atoms/lesson", {"course_id": course_id, "atom_id": "a2"})[0], 400)
        self.assertEqual(self.call("/api/knowledge/diagnostic", {"course_id": course_id})[0], 200)
        data = self.call(f"/api/course?course_id={course_id}")[1]
        diagnostic = data["knowledge"]["diagnostics"][0]
        self.assertNotIn("answer", json.dumps(diagnostic))
        self.assertEqual(self.call("/api/quizzes/submit", {"course_id": course_id,
            "quiz_id": diagnostic["id"], "answers": ["b","b","a","a"]})[0], 200)
        self.call("/api/sections/lesson", {"course_id": course_id, "ordinal": 1})
        self.assertTrue(FakeProvider.lesson_payloads[-1]["knowledge_atoms"])
        before = self.call(f"/api/course?course_id={course_id}")[1]["knowledge"]["atoms"][0]
        self.assertEqual(before["rate"], 50)
        self.assertFalse(before["read"])
        self.call("/api/sections/read", {"course_id": course_id, "ordinal": 1})
        self.call("/api/atoms/lesson", {"course_id": course_id, "atom_id": "a1", "mode": "quick"})
        self.call("/api/atoms/ask", {"course_id": course_id, "atom_id": "a1", "question": "再解释一下"})
        after = self.call(f"/api/course?course_id={course_id}")[1]["knowledge"]["atoms"][0]
        self.assertTrue(after["read"])
        self.assertEqual(after["rate"], 50)
        self.assertEqual(after["evidence_count"], 4)
        detail = self.call("/api/atoms/quiz", {"course_id": course_id, "atom_id": "a1"})[1]
        self.assertIn("quick", detail["content"])
        self.assertEqual(len(detail["turns"]), 2)
        quiz = detail["quizzes"][0]
        self.assertNotIn("answer", json.dumps(quiz))
        self.assertEqual(self.call("/api/atoms/quiz", {"course_id": course_id, "atom_id": "a1"})[1]["quizzes"][0]["id"], quiz["id"])
        self.call("/api/quizzes/submit", {"course_id": course_id, "quiz_id": quiz["id"], "answers": ["b"]*4})
        chapter = self.call("/api/sections/quiz", {"course_id": course_id, "ordinal": 1})[1]
        self.assertEqual(len(chapter["quizzes"]), 1)
        self.assertTrue(chapter["quizzes"][0]["questions"][0]["atom_ids"])
        chapter_quiz = chapter["quizzes"][0]
        self.call("/api/quizzes/submit", {"course_id": course_id, "quiz_id": chapter_quiz["id"], "answers": ["b"]*4})
        updated = self.call(f"/api/course?course_id={course_id}")[1]
        self.assertEqual(updated["knowledge"]["atoms"][0]["rate"], 100)
        self.assertEqual(updated["mastery"]["sections"][0]["test_count"], 1)
        self.assertEqual(updated["course"]["current_ordinal"], 1)
        self.assertEqual(Storage(self.data_path).knowledge_state(self.session_id(), course_id)["atoms"][0]["rate"], 100)
        other_id = self.draft_and_confirm("独立知识课程", "独立目标")
        self.call("/api/knowledge/build", {"course_id": other_id})
        other_state = self.call(f"/api/course?course_id={other_id}")[1]["knowledge"]
        self.assertIsNone(other_state["atoms"][0]["rate"])
        self.assertFalse(other_state["atoms"][0]["read"])
        other = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self.assertEqual(self.call(f"/api/knowledge?course_id={course_id}", client=other)[0], 400)
        self.assertEqual(self.call(f"/api/atom?course_id={course_id}&atom_id=a1", client=other)[0], 400)
        self.assertEqual(self.call("/api/atoms/lesson", {"course_id": course_id, "atom_id": "a1"}, other)[0], 400)
        self.assertEqual(self.call("/api/quizzes/submit", {"course_id": other_id, "quiz_id": quiz["id"], "answers": ["b"]*4})[0], 400)

    def test_create_with_material_policy_preserves_structure_and_starts_discovery(self):
        import base64,time
        self.configure()
        text='# Attention\n\nAttention uses QKV and Softmax to produce weighted representations.\n\n## QKV\n\nQuery, Key and Value are three representations used in attention.'
        status,result=self.call('/api/courses/draft',{'title':'注意力课程','goal':'从零理解','learner_level':'了解一些基础',
            'source_policy':'user_material_first','search_mode':'public','uploads':[{'filename':'讲义.md','content_base64':base64.b64encode(text.encode()).decode()}]})
        self.assertEqual(status,200,result);draft=result['draft']
        self.assertEqual([s['title'] for s in draft['plan']['sections']],['Attention','QKV'])
        status,result=self.call('/api/courses/confirm',{'draft_id':draft['id'],'revision':draft['revision']})
        self.assertEqual(status,200,result);cid=result['course_id']
        self.assertEqual(result['course']['course']['source_policy'],'user_material_first')
        self.assertEqual(result['course']['course']['learner_level'],'了解一些基础')
        for worker in self.server.discovery_engine.threads:worker.join(timeout=5)
        sources=self.call(f'/api/sources?course_id={cid}')[1]
        self.assertIn(sources['discovery']['status'],('complete','partial'),sources)
        self.assertTrue(sources['batches']);self.assertEqual(len(sources['sources']),1)
        self.assertFalse(self.call(f'/api/knowledge?course_id={cid}')[1]['ready'])
        run_id=sources['discovery']['id']
        self.call('/api/courses/confirm',{'draft_id':draft['id'],'revision':draft['revision']})
        self.assertEqual(self.call(f'/api/sources?course_id={cid}')[1]['discovery']['id'],run_id)
        self.assertEqual(self.call('/api/courses/source-policy',{'course_id':cid,'source_policy':'balanced'})[0],200)
        self.assertEqual(self.call('/api/courses/source-policy',{'course_id':cid,'source_policy':[]})[0],400)
        self.assertEqual(self.call('/api/courses/draft',{'title':'错误课程','source_policy':[]})[0],400)
        fresh=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self.assertEqual(self.call('/api/discovery/start',{'course_id':cid},client=fresh)[0],400)

    def test_source_pipeline_review_provenance_and_course_isolation(self):
        import base64
        self.configure()
        course=self.draft_and_confirm("资料课程", "理解概念")
        cid=course
        self.call('/api/knowledge/build', {'course_id':cid})
        original=self.server.storage.graph(self.session_id(),cid)
        status,data=self.call('/api/sources/upload',{'course_id':cid,'filename':'课堂.md',
            'content_base64':base64.b64encode(('# 定义\n\n定义：概念是一类事物的共同属性，使用实例能够帮助初学者逐步理解。\n\n'+ '例子：观察生活中的物品并描述其共同属性。\n\n'*200).encode()).decode()})
        self.assertEqual(status,200)
        source=data['source'];self.assertEqual(source['origin'],'user_upload')
        status,data=self.call('/api/sources/process',{'course_id':cid,'source_id':source['id'],'section':1})
        self.assertEqual(status,200,data)
        batch=data['batch'];self.assertEqual(batch['status'],'candidate')
        self.assertEqual(original,self.server.storage.graph(self.session_id(),cid))
        self.assertTrue(batch['result']['candidates'][0]['quality']['grounded'])
        status,data=self.call('/api/sources/review',{'course_id':cid,'batch_id':batch['id'],'action':'verify','selected':['c1'],'feedback':'已核对原文'})
        self.assertEqual(status,200,data)
        atom=next(a for a in data['knowledge']['atoms'] if a['title']=='资料知识点')
        self.assertEqual(atom['source_reference'][0]['document_id'],source['id'])
        self.assertIsNone(atom['rate'])
        self.assertEqual(data['knowledge']['tested_count'],0)
        self.assertEqual(self.call('/api/sources/review',{'course_id':cid,'batch_id':batch['id'],'action':'verify','selected':['c1']})[0],400)
        other=self.draft_and_confirm('另外课程','分别学习')
        self.assertEqual(self.call(f'/api/sources?course_id={other}')[1]['sources'],[])
        self.assertEqual(self.call(f'/api/source?course_id={other}&source_id={source["id"]}')[0],400)
        fresh=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self.assertEqual(self.call(f'/api/sources?course_id={cid}',client=fresh)[0],400)
        self.assertEqual(self.call('/api/sources/url',{'course_id':cid,'url':'http://127.0.0.1/'})[0],400)

    def test_existing_draft_survives_search_report_migration(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "legacy.sqlite3"
            store = Storage(path)
            draft = store.save_draft("owner", "课程", "", "", {"sections": []}, [])
            with sqlite3.connect(path) as db:
                db.execute("ALTER TABLE course_drafts DROP COLUMN search_report_json")
            restored = Storage(path).draft("owner", draft["id"])
            self.assertEqual(restored["title"], "课程")
            self.assertEqual(restored["search_report"], {})

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
