"""Run the local MindOS learning prototype with Python's standard library."""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import secrets
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from .catalog import Catalog, ROOT
from .flow import DIAGNOSTICS, learning_plan, public_diagnostics
from .learning import progress, recommendation, submit
from .model import ModelGateway, ModelUnavailable
from .retrieval import retrieve
from .storage import Storage

LOGGER = logging.getLogger("mindos")
WEB = ROOT / "web"
ENV_KEYS = {"MINDOS_MODEL_BASE_URL", "MINDOS_CHAT_MODEL", "MINDOS_EMBEDDING_MODEL", "MINDOS_MODEL_API_KEY", "MINDOS_DATA_PATH"}
STATIC = {
    "/": (WEB / "index.html", "text/html; charset=utf-8"),
    "/app.js": (WEB / "app.js", "text/javascript; charset=utf-8"),
    "/style.css": (WEB / "style.css", "text/css; charset=utf-8"),
}


class MindOSServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, port: int, data_path: Path) -> None:
        self.catalog = Catalog()
        self.storage = Storage(data_path)
        self.model = ModelGateway()
        super().__init__(("127.0.0.1", port), MindOSHandler)


class MindOSHandler(BaseHTTPRequestHandler):
    server: MindOSServer

    def _session(self) -> str:
        if not hasattr(self, "_session_value"):
            cookie = SimpleCookie()
            try:
                cookie.load(self.headers.get("Cookie", ""))
                value = cookie["mindos_session"].value if "mindos_session" in cookie else ""
            except Exception:
                value = ""
            self._new_session = not bool(re.fullmatch(r"[0-9a-f]{32}", value))
            self._session_value = secrets.token_hex(16) if self._new_session else value
        return self._session_value

    def _send(self, status: HTTPStatus, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'")
        self._session()
        if self._new_session:
            self.send_header("Set-Cookie", f"mindos_session={self._session_value}; HttpOnly; SameSite=Strict; Path=/; Max-Age=2592000")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: HTTPStatus, payload: dict | list) -> None:
        self._send(status, json.dumps(payload, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def _request_json(self) -> dict:
        if self.headers.get_content_type() != "application/json":
            raise ValueError("请使用 JSON 请求")
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise ValueError("请求长度无效") from exc
        if not 0 < length <= 8192:
            raise ValueError("请求内容过大或为空")
        try:
            payload = json.loads(self.rfile.read(length))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("JSON 格式无效") from exc
        if not isinstance(payload, dict):
            raise ValueError("请求格式无效")
        return payload

    def _check_local_request(self) -> None:
        valid_hosts = {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}
        host = self.headers.get("Host", "")
        origin = self.headers.get("Origin")
        if host not in valid_hosts or (origin and origin not in {f"http://{item}" for item in valid_hosts}):
            raise ValueError("仅接受本机页面提交")

    def _dashboard(self, course_id: str) -> dict:
        pack = self.server.catalog.get(course_id)
        rows = self.server.storage.submissions(self._session(), course_id, pack["version"])
        answers = self.server.storage.diagnostics(self._session(), pack)
        by_concept = {(task["concept_id"], task["dimension_id"]): answers[task["id"]]
                      for task in DIAGNOSTICS.get(course_id, []) if task["id"] in answers}
        states = progress(pack, rows, by_concept)
        goal = self.server.storage.goal(self._session(), pack)
        plan = learning_plan(pack, states, answers, goal) if goal else []
        return {
            "course": self.server.catalog.public_course(course_id),
            "goal": goal,
            "diagnostic": public_diagnostics(pack, answers),
            "progress": states,
            "plan": plan,
            "recommendation": recommendation(pack, states, rows, self.server.storage.helped_tasks(self._session(), pack),
                                             {item["concept_id"] for item in plan} if goal else None),
            "valid_evidence_count": sum(row["counts_for_state"] for row in rows),
            "recent": list(reversed(rows[-8:])),
        }

    def _get(self) -> None:
        self._check_local_request()
        parsed = urlsplit(self.path)
        if parsed.path in STATIC:
            path, content_type = STATIC[parsed.path]
            self._send(HTTPStatus.OK, path.read_bytes(), content_type)
        elif parsed.path == "/api/health":
            self._json(HTTPStatus.OK, {"status": "ok", "courses": len(self.server.catalog.packs)})
        elif parsed.path == "/api/courses":
            self._json(HTTPStatus.OK, {
                "courses": self.server.catalog.courses(),
                "chat_ready": self.server.model.chat_ready,
                "embedding_ready": self.server.model.embedding_ready,
            })
        elif parsed.path == "/api/dashboard":
            course_id = parse_qs(parsed.query).get("course_id", [""])[0]
            self._json(HTTPStatus.OK, self._dashboard(course_id))
        else:
            self._json(HTTPStatus.NOT_FOUND, {"error": "页面不存在"})

    def _post(self) -> None:
        self._check_local_request()
        payload = self._request_json()
        parsed = urlsplit(self.path)
        if parsed.path == "/api/submit":
            course_id = payload.get("course_id", "")
            task_id = payload.get("task_id", "")
            pack = self.server.catalog.get(course_id)
            task = self.server.catalog.task(pack, task_id)
            result = submit(self.server.storage, self._session(), pack, task,
                            payload.get("answer"), payload.get("mode", "practice"))
            self._json(HTTPStatus.OK, {"result": result, "dashboard": self._dashboard(course_id)})
        elif parsed.path == "/api/goal":
            pack = self.server.catalog.get(payload.get("course_id", ""))
            goal = payload.get("goal")
            if not isinstance(goal, str) or goal not in pack["learning_goals"]:
                raise ValueError("请选择当前课程提供的学习目标")
            self.server.storage.set_goal(self._session(), pack, goal)
            self._json(HTTPStatus.OK, {"dashboard": self._dashboard(pack["id"])})
        elif parsed.path == "/api/diagnose":
            pack = self.server.catalog.get(payload.get("course_id", ""))
            if not self.server.storage.goal(self._session(), pack):
                raise ValueError("请先选择学习目标")
            task = next((item for item in DIAGNOSTICS.get(pack["id"], [])
                         if item["id"] == payload.get("task_id")), None)
            if task is None:
                raise ValueError("诊断题不存在")
            if task["id"] in self.server.storage.diagnostics(self._session(), pack):
                raise ValueError("这道诊断题已完成")
            answer = payload.get("answer")
            if answer not in {item["id"] for item in task["choices"]}:
                raise ValueError("请选择诊断题提供的选项")
            correct = answer == task["answer"]
            self.server.storage.add_diagnostic(self._session(), pack, task["id"], answer, correct)
            self._json(HTTPStatus.OK, {"result": {"correct": correct}, "dashboard": self._dashboard(pack["id"])})
        elif parsed.path == "/api/ask":
            course_id = payload.get("course_id", "")
            pack = self.server.catalog.get(course_id)
            question = payload.get("question", "")
            concept_id = payload.get("concept_id")
            task_id = payload.get("task_id")
            level = payload.get("hint_level", 3)
            if type(level) is not int or level not in (1, 2, 3):
                raise ValueError("提示级别无效")
            if payload.get("mode", "practice") == "independent":
                raise ValueError("独立作答期间不提供讲解")
            if not isinstance(question, str) or not 2 <= len(question.strip()) <= 500:
                raise ValueError("请输入 2 至 500 字的问题")
            if concept_id and concept_id not in {item["id"] for item in pack["concepts"]}:
                raise ValueError("知识点不存在")
            if task_id:
                self.server.catalog.task(pack, task_id)
                self.server.storage.mark_help(self._session(), pack, task_id)
            chunks = self.server.catalog.teaching_chunks(pack)
            sources, retrieval_mode, notice = retrieve(
                question.strip(), chunks, concept_id, self.server.model, self.server.storage)
            generated = False
            if not sources:
                answer = "当前课程资料中未找到足够相关的内容。请补充更具体的术语或问题。"
            elif self.server.model.chat_ready:
                states = self._dashboard(course_id)["progress"]
                relevant = [item for item in states if item["concept_id"] == concept_id]
                hint = "；".join(f"{item['dimension_label']}：{item['state_label']}" for item in relevant) or "暂无独立测评证据"
                try:
                    answer = self.server.model.explain(question.strip(), sources, hint, level)
                    generated = True
                    citations = {int(number) for number in re.findall(r"\[(\d+)\]", answer)}
                    if citations - set(range(1, len(sources) + 1)):
                        answer = re.sub(r"\[(\d+)\]", lambda match: match.group(0)
                                        if int(match.group(1)) <= len(sources) else "", answer)
                        notice = "模型引用了本次检索之外的编号，已移除无效编号；请核对原文。"
                except ModelUnavailable:
                    answer = self._source_hint(sources[0], level)
                    notice = "模型连接失败；作答记录未受影响。"
            else:
                answer = self._source_hint(sources[0], level)
            self._json(HTTPStatus.OK, {
                "answer": answer, "retrieval_mode": retrieval_mode,
                "sources": [{key: item[key] for key in ("id", "title", "content", "url", "provenance")}
                            for item in sources],
                "notice": notice,
                "generated": generated,
            })
        else:
            self._json(HTTPStatus.NOT_FOUND, {"error": "接口不存在"})

    @staticmethod
    def _source_hint(source: dict, level: int) -> str:
        content = source["content"].strip()
        if level == 1:
            return f"提示 1：先回想「{source['title']}」中的核心概念，再自己尝试说出解题步骤。可核对下方原文 [1]。"
        if level == 2:
            return f"提示 2：课程资料 [1] 给出的线索是：\n{content[:320]}"
        return f"资料讲解：请对照课程原文 [1] 梳理概念、例子和本题条件：\n{content[:1100]}"

    def do_GET(self) -> None:
        self._safe_call(self._get)

    def do_POST(self) -> None:
        self._safe_call(self._post)

    def _safe_call(self, handler) -> None:
        try:
            handler()
        except KeyError as exc:
            self._json(HTTPStatus.NOT_FOUND, {"error": str(exc.args[0])})
        except ValueError as exc:
            self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
        except Exception:
            LOGGER.exception("请求处理失败")
            self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "服务暂不可用，请查看终端日志"})

    def log_message(self, format: str, *args) -> None:
        LOGGER.info("%s %s", self.address_string(), format % args)


def main() -> None:
    parser = argparse.ArgumentParser(description="MindOS local learning prototype")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    local_env = ROOT / ".env"
    if local_env.is_file():
        for line in local_env.read_text(encoding="utf-8").splitlines():
            key, separator, value = line.partition("=")
            if separator and key.strip() in ENV_KEYS:
                os.environ.setdefault(key.strip(), value.strip().strip('"'))
    path = Path(os.getenv("MINDOS_DATA_PATH", str(ROOT / "data/mindos-demo.sqlite3"))).resolve()
    server = MindOSServer(args.port, path)
    print(f"MindOS 已启动：http://127.0.0.1:{server.server_port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
