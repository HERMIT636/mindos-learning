"""End-to-end checks for the local demo without real student data or model keys."""

from __future__ import annotations

import http.cookiejar
import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from mindos.catalog import Catalog
from mindos.model import ModelGateway
from mindos.retrieval import retrieve
from mindos.server import MindOSServer


class FakeModelHandler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        length = int(self.headers["Content-Length"])
        payload = json.loads(self.rfile.read(length))
        if self.path == "/v1/embeddings":
            result = {"data": [
                {"index": index, "embedding": [1.0 if "return" in text else 0.2, 0.5]}
                for index, text in enumerate(payload["input"])
            ]}
        elif self.path == "/v1/chat/completions":
            system = payload["messages"][0]["content"]
            if "课程目标匹配助手" in system:
                content = json.dumps({"concept_id": "return-value", "rationale": "目标涉及函数返回值。"}, ensure_ascii=False)
            elif "课程练习出题助手" in system:
                content = json.dumps({"prompt": "调用一个只执行 print(3) 的函数时，调用结果是什么？",
                                      "choices": [{"id": "a", "text": "3"}, {"id": "b", "text": "None"},
                                                  {"id": "c", "text": "字符串 3"}], "answer": "b",
                                      "explanation": "print 显示内容，但函数没有 return，调用结果为 None。"}, ensure_ascii=False)
            else:
                assert "参考答案" not in payload["messages"][1]["content"]
                assert "不是你讲解时唯一能用的知识" in system
                assert "扩展说明" in system
                if "请深入讲解知识点" in payload["messages"][1]["content"]:
                    assert "不要只给定义或简短摘要" in system
                    assert "函数定义与调用" in payload["messages"][1]["content"]
                    assert "独立作答证据" in payload["messages"][1]["content"]
                content = "根据课程资料，return 会交回值。[1]"
            result = {"choices": [{"message": {"content": content}}]}
        else:
            self.send_error(404)
            return
        body = json.dumps(result).encode("utf-8")
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
        cls.server = MindOSServer(0, Path(cls.directory.name) / "demo.sqlite3")
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2)
        cls.directory.cleanup()

    def setUp(self) -> None:
        self.client = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def call(self, path: str, payload: dict | None = None) -> tuple[int, dict]:
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = urllib.request.Request(self.url + path, data=data,
                                         headers={"Content-Type": "application/json"} if data else {})
        try:
            with self.client.open(request, timeout=5) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as exc:
            try:
                return exc.code, json.loads(exc.read())
            finally:
                exc.close()

    def test_course_isolation_and_distinct_independent_evidence(self) -> None:
        status, courses = self.call("/api/courses")
        self.assertEqual(status, 200)
        self.assertEqual(len(courses["courses"]), 5)
        self.assertEqual([item["id"] for item in courses["courses"][:3]],
                         ["machine-learning", "hpc-foundations", "ascend-c-operators"])
        _, dashboard = self.call("/api/dashboard?course_id=python-foundations")
        self.assertNotIn("reference_answer", json.dumps(dashboard))
        self.assertEqual(dashboard["recommendation"]["task_id"], "identify-call")
        for task_id, answer in (("identify-call", "b"), ("identify-call-with-argument", "b")):
            status, result = self.call("/api/submit", {"course_id": "python-foundations", "task_id": task_id,
                                                       "answer": answer, "mode": "independent"})
            self.assertEqual(status, 200)
            self.assertTrue(result["result"]["counts_for_state"])
        _, dashboard = self.call("/api/dashboard?course_id=python-foundations")
        functions = next(row for row in dashboard["progress"] if row["concept_id"] == "functions" and row["dimension_id"] == "understanding")
        self.assertEqual(functions["state"], "retested")
        self.assertEqual(functions["evidence_count"], 2)
        self.assertEqual(dashboard["valid_evidence_count"], 2)
        self.assertEqual(dashboard["recommendation"]["task_id"], "return-vs-print")
        _, other = self.call("/api/dashboard?course_id=linear-algebra")
        self.assertEqual(other["valid_evidence_count"], 0)
        self.assertTrue(all(row["state"] == "unassessed" for row in other["progress"]))

    def test_every_demo_concept_has_complete_authored_lesson(self) -> None:
        catalog = Catalog()
        for pack in catalog.packs.values():
            for concept in pack["concepts"]:
                with self.subTest(course=pack["id"], concept=concept["id"]):
                    materials = catalog.lesson_materials(pack, concept["id"])
                    self.assertEqual(len(materials), 1)
                    lesson = materials[0]["content"]
                    minimum = 1500 if pack["id"] in {"python-foundations", "linear-algebra"} else 650
                    self.assertGreater(len(lesson), minimum)
                    self.assertIn("## 常见", lesson)
                    self.assertNotIn("reference_answer", lesson)

    def test_curated_guides_are_retrievable_for_each_concept(self) -> None:
        catalog = Catalog()
        questions = [
            ("python-foundations", "functions", "函数定义和调用有什么区别？", "python-functions-official-guide"),
            ("python-foundations", "return-value", "return 和 print 有什么区别？", "python-return-official-guide"),
            ("linear-algebra", "vectors", "二维向量的分量是什么意思？", "linear-vectors-hefferon-guide"),
            ("linear-algebra", "dot-product", "点积为零为什么说明垂直？", "linear-dot-hefferon-guide"),
        ]
        for course_id, concept_id, question, guide_id in questions:
            with self.subTest(course=course_id, concept=concept_id):
                pack = catalog.get(course_id)
                chunks = [chunk for chunk in catalog.teaching_chunks(pack)
                          if concept_id in chunk["concept_ids"]]
                chunks += catalog.external_chunks(pack, concept_id)
                sources, _, _ = retrieve(question, chunks, concept_id, ModelGateway(),
                                         self.server.storage, use_vectors=False)
                self.assertIn(guide_id, [source["id"] for source in sources])
                self.assertTrue(all(concept_id in source["concept_ids"] for source in sources))

    def test_new_course_diagnoses_only_target_and_direct_prerequisite(self) -> None:
        self.call("/api/mode", {"mode": "materials"})
        status, result = self.call("/api/target", {"course_id": "machine-learning",
                                               "chapter_id": "evaluation", "concept_id": "evaluation"})
        self.assertEqual(status, 200)
        self.assertEqual([item["id"] for item in result["dashboard"]["diagnostic"]],
                         ["diagnose-problem-framing", "diagnose-data-splits", "diagnose-evaluation"])
        status, blocked = self.call("/api/lesson", {"course_id": "machine-learning"})
        self.assertEqual(status, 400)
        self.assertIn("基础测试", blocked["error"])
        for task_id in ("diagnose-problem-framing", "diagnose-data-splits", "diagnose-evaluation"):
            status, _ = self.call("/api/diagnose", {"course_id": "machine-learning",
                                                        "task_id": task_id, "answer": "a"})
            self.assertEqual(status, 200)
        status, lesson = self.call("/api/lesson", {"course_id": "machine-learning"})
        self.assertEqual(status, 200)
        self.assertIn("分类与回归评价指标", lesson["title"])
        self.assertIn("混淆矩阵", lesson["answer"])

    def test_priority_courses_open_their_first_lessons(self) -> None:
        self.call("/api/mode", {"mode": "materials"})
        catalog = Catalog()
        for course_id in ("machine-learning", "hpc-foundations", "ascend-c-operators"):
            with self.subTest(course=course_id):
                pack = catalog.get(course_id)
                first = pack["concepts"][0]["id"]
                chapter = pack["chapters"][0]["id"]
                self.assertEqual(len(pack["diagnostics"]), len(pack["concepts"]))
                self.assertTrue(all(sum(task["concept_ids"] == [concept["id"]]
                                        for task in pack["tasks"]) == 2 for concept in pack["concepts"]))
                status, result = self.call("/api/target", {"course_id": course_id,
                                                      "chapter_id": chapter, "concept_id": first})
                self.assertEqual(status, 200)
                self.assertEqual(len(result["dashboard"]["diagnostic"]), 1)
                diagnostic = pack["diagnostics"][0]
                self.call("/api/diagnose", {"course_id": course_id,
                                            "task_id": diagnostic["id"], "answer": diagnostic["answer"]})
                status, lesson = self.call("/api/lesson", {"course_id": course_id})
                self.assertEqual(status, 200)
                self.assertEqual(lesson["title"], pack["concepts"][0]["title"])
                self.assertFalse(lesson["generated"])

    def test_help_and_practice_never_count_as_independent(self) -> None:
        self.call("/api/dashboard?course_id=linear-algebra")
        status, answer = self.call("/api/ask", {"course_id": "linear-algebra", "task_id": "vector-component",
                                                   "concept_id": "vectors", "question": "二维向量的分量是什么？", "mode": "practice"})
        self.assertEqual(status, 200)
        self.assertTrue(answer["sources"])
        self.assertTrue(all("linear-algebra" in item["url"] for item in answer["sources"]))
        status, response = self.call("/api/submit", {"course_id": "linear-algebra", "task_id": "vector-component",
                                                     "answer": "b", "mode": "independent"})
        self.assertEqual(status, 200)
        self.assertFalse(response["result"]["counts_for_state"])
        _, dashboard = self.call("/api/dashboard?course_id=linear-algebra")
        self.assertEqual(dashboard["valid_evidence_count"], 0)
        self.assertEqual(dashboard["recommendation"]["task_id"], "zero-vector")

    def test_goal_diagnosis_plan_and_local_tiered_hints(self) -> None:
        _, dashboard = self.call("/api/dashboard?course_id=python-foundations")
        self.assertIsNone(dashboard["goal"])
        self.assertNotIn("answer", json.dumps(dashboard["diagnostic"]))
        status, error = self.call("/api/diagnose", {"course_id": "python-foundations", "task_id": "diagnose-function", "answer": "a"})
        self.assertEqual(status, 400)
        self.assertIn("目标", error["error"])
        goal = dashboard["course"]["learning_goals"][1]
        _, response = self.call("/api/goal", {"course_id": "python-foundations", "goal": goal})
        self.assertEqual(response["dashboard"]["goal"], goal)
        self.assertEqual(len(response["dashboard"]["plan"]), 2)
        status, blocked = self.call("/api/lesson", {"course_id": "python-foundations"})
        self.assertEqual(status, 400)
        self.assertIn("目标", blocked["error"])
        for task_id, answer in (("diagnose-function", "a"), ("diagnose-return", "c")):
            status, response = self.call("/api/diagnose", {"course_id": "python-foundations", "task_id": task_id, "answer": answer})
            self.assertEqual(status, 200)
        dashboard = response["dashboard"]
        self.assertEqual(dashboard["valid_evidence_count"], 0)
        self.assertEqual(dashboard["plan"][0]["status"], "优先补强")
        understanding = next(row for row in dashboard["progress"] if row["concept_id"] == "functions" and row["dimension_id"] == "understanding")
        implementation = next(row for row in dashboard["progress"] if row["concept_id"] == "functions" and row["dimension_id"] == "implementation")
        self.assertEqual(understanding["state"], "needs_work")
        self.assertEqual(implementation["state"], "unassessed")
        self.call("/api/mode", {"mode": "materials"})
        self.call("/api/target", {"course_id": "python-foundations",
                                  "chapter_id": "function-results", "concept_id": "return-value"})
        status, lesson = self.call("/api/lesson", {"course_id": "python-foundations"})
        self.assertEqual(status, 200)
        self.assertFalse(lesson["generated"])
        self.assertIn("返回与显示", lesson["source"]["title"])
        self.assertIn("## return 还会结束本次调用", lesson["answer"])
        self.assertIn("## 常见误区与自查方法", lesson["answer"])
        self.assertGreater(len(lesson["answer"]), 1500)
        self.assertEqual(lesson["answer"], lesson["base_lesson"])
        self.assertNotIn("reference_answer", json.dumps(lesson))
        for level in (1, 2, 3):
            status, hint = self.call("/api/ask", {"course_id": "python-foundations", "question": "return 和 print 有什么区别？", "hint_level": level})
            self.assertEqual(status, 200)
            self.assertFalse(hint["generated"])
            self.assertIn(f"{level}", hint["answer"] if level < 3 else "3")
            self.assertTrue(hint["sources"])
        other_client = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        with other_client.open(self.url + "/api/dashboard?course_id=python-foundations") as result:
            other = json.loads(result.read())
        self.assertIsNone(other["goal"])
        self.assertTrue(all(item["result"] is None for item in other["diagnostic"]))

    def test_first_goal_limits_plan_and_next_task(self) -> None:
        _, dashboard = self.call("/api/dashboard?course_id=python-foundations")
        goal = dashboard["course"]["learning_goals"][0]
        _, response = self.call("/api/goal", {"course_id": "python-foundations", "goal": goal})
        self.assertEqual([item["concept_id"] for item in response["dashboard"]["plan"]], ["functions"])
        for task_id, answer in (("identify-call", "b"), ("identify-call-with-argument", "b")):
            self.call("/api/submit", {"course_id": "python-foundations", "task_id": task_id,
                                      "answer": answer, "mode": "independent"})
        _, dashboard = self.call("/api/dashboard?course_id=python-foundations")
        self.assertIsNone(dashboard["recommendation"])
        self.assertEqual(dashboard["plan"][0]["status"], "已复测")

    def test_mode_and_chapter_target_validation(self) -> None:
        status, result = self.call("/api/mode", {"mode": "ai"})
        self.assertEqual(status, 400)
        self.assertIn("配置", result["error"])
        status, result = self.call("/api/mode", {"mode": "materials"})
        self.assertEqual(status, 200)
        status, result = self.call("/api/target", {"course_id": "python-foundations",
                                                   "chapter_id": "function-basics", "concept_id": "return-value"})
        self.assertEqual(status, 400)
        status, result = self.call("/api/target", {"course_id": "python-foundations",
                                                   "chapter_id": "function-results", "concept_id": "return-value"})
        self.assertEqual(status, 200)
        self.assertEqual([item["concept_id"] for item in result["dashboard"]["plan"]],
                         ["functions", "return-value"])
        status, result = self.call("/api/quiz", {"course_id": "python-foundations", "concept_id": "return-value"})
        self.assertEqual(status, 400)

    def test_numeric_grading_and_no_answer_query(self) -> None:
        status, invalid = self.call("/api/submit", {"course_id": "linear-algebra", "task_id": "calculate-dot-product",
                                                  "answer": "NaN", "mode": "independent"})
        self.assertEqual(status, 400)
        self.assertIn("数字", invalid["error"])
        status, response = self.call("/api/submit", {"course_id": "linear-algebra", "task_id": "calculate-dot-product",
                                                   "answer": "11", "mode": "independent"})
        self.assertEqual(status, 200)
        self.assertTrue(response["result"]["correct"])
        status, response = self.call("/api/ask", {"course_id": "linear-algebra", "question": "外星生命为什么存在？"})
        self.assertEqual(status, 200)
        self.assertEqual(response["sources"], [])
        self.assertFalse(response["generated"])

    def test_configured_model_and_vectors_with_fake_local_service(self) -> None:
        fake = ThreadingHTTPServer(("127.0.0.1", 0), FakeModelHandler)
        thread = threading.Thread(target=fake.serve_forever, daemon=True)
        thread.start()
        keys = ("MINDOS_MODEL_BASE_URL", "MINDOS_CHAT_MODEL", "MINDOS_EMBEDDING_MODEL", "MINDOS_MODEL_API_KEY")
        old = {key: os.environ.get(key) for key in keys}
        previous_model = self.server.model
        try:
            os.environ.update({"MINDOS_MODEL_BASE_URL": f"http://127.0.0.1:{fake.server_port}/v1",
                               "MINDOS_CHAT_MODEL": "fake-chat", "MINDOS_EMBEDDING_MODEL": "fake-embedding",
                               "MINDOS_MODEL_API_KEY": ""})
            self.server.model = ModelGateway()
            status, result = self.call("/api/mode", {"mode": "ai"})
            self.assertEqual(status, 200)
            status, analysis = self.call("/api/analyze-goal", {"course_id": "python-foundations",
                                                                  "custom_text": "我想理解 print 和 return 的区别"})
            self.assertEqual(status, 200)
            self.assertEqual(analysis["concept_id"], "return-value")
            self.call("/api/target", {"course_id": "python-foundations", "chapter_id": "function-results",
                                      "concept_id": "return-value", "custom_text": "我想理解 print 和 return 的区别"})
            for task_id, answer in (("diagnose-function", "b"), ("diagnose-return", "c")):
                self.call("/api/diagnose", {"course_id": "python-foundations", "task_id": task_id, "answer": answer})
            status, lesson = self.call("/api/lesson", {"course_id": "python-foundations"})
            self.assertEqual(status, 200)
            self.assertTrue(lesson["generated"])
            self.assertGreater(len(lesson["base_lesson"]), 1500)
            self.assertGreater(len(lesson["sources"]), 1)
            self.assertTrue(any(source["id"] == "python-return-official-guide"
                                and source["url"] == "https://docs.python.org/3/library/functions.html#print"
                                for source in lesson["sources"]))
            self.assertIn("课程资料", lesson["answer"])
            status, quiz = self.call("/api/quiz", {"course_id": "python-foundations", "concept_id": "return-value"})
            self.assertEqual(status, 200)
            self.assertNotIn("answer", quiz)
            self.assertIn("返回", quiz["source_title"])
            status, scored = self.call("/api/quiz-answer", {"course_id": "python-foundations",
                                                            "quiz_id": quiz["id"], "answer": "b"})
            self.assertEqual(status, 200)
            self.assertTrue(scored["correct"])
            self.assertFalse(scored["counts_for_state"])
            status, response = self.call("/api/ask", {"course_id": "python-foundations", "question": "return 和 print 有什么区别？",
                                                       "concept_id": "return-value"})
            self.assertEqual(status, 200)
            self.assertTrue(response["generated"])
            self.assertEqual(response["retrieval_mode"], "关键词＋向量")
            self.assertTrue(response["sources"])
            self.assertTrue(any(source["id"] == "python-return-official-guide" for source in response["sources"]))
            self.call("/api/mode", {"mode": "materials"})
            status, offline = self.call("/api/ask", {"course_id": "python-foundations", "question": "return 和 print 有什么区别？",
                                                      "concept_id": "return-value"})
            self.assertEqual(status, 200)
            self.assertFalse(offline["generated"])
            self.assertEqual(offline["retrieval_mode"], "关键词")
            self.assertTrue(all(not source["id"].endswith("-official-guide") for source in offline["sources"]))
        finally:
            self.server.model = previous_model
            for key, value in old.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
            fake.shutdown()
            fake.server_close()
            thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
