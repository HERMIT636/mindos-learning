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

from mindos.model import ModelGateway
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
            assert "参考答案" not in payload["messages"][1]["content"]
            result = {"choices": [{"message": {"content": "根据课程资料，return 会交回值。[1]"}}]}
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
        self.assertEqual(len(courses["courses"]), 2)
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
            status, response = self.call("/api/ask", {"course_id": "python-foundations", "question": "return 和 print 有什么区别？",
                                                       "concept_id": "return-value"})
            self.assertEqual(status, 200)
            self.assertTrue(response["generated"])
            self.assertEqual(response["retrieval_mode"], "关键词＋向量")
            self.assertTrue(response["sources"])
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
