"""Local MindOS server for user-created, section-by-section AI courses."""

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

from .model import ModelGateway, ModelUnavailable
from .secrets import SecretStore
from .storage import Storage
from .web_search import SearchUnavailable, WebSearch

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
LOGGER = logging.getLogger("mindos")
STATIC = {"/": ("index.html", "text/html; charset=utf-8"),
          "/app.js": ("app.js", "text/javascript; charset=utf-8"),
          "/style.css": ("style.css", "text/css; charset=utf-8")}
ENV_KEYS = {"MINDOS_MODEL_BASE_URL", "MINDOS_CHAT_MODEL", "MINDOS_MODEL_API_KEY",
            "MINDOS_BRAVE_SEARCH_API_KEY", "MINDOS_DATA_PATH"}


class MindOSServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, port: int, data_path: Path) -> None:
        self.storage = Storage(data_path)
        self.model = ModelGateway()
        self.secrets = SecretStore()
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
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'")
        self._session()
        if self._new_session:
            self.send_header("Set-Cookie", f"mindos_session={self._session_value}; HttpOnly; SameSite=Strict; Path=/; Max-Age=2592000")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: HTTPStatus, payload: dict) -> None:
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
        host, origin = self.headers.get("Host", ""), self.headers.get("Origin")
        if host not in valid_hosts or (origin and origin not in {f"http://{item}" for item in valid_hosts}):
            raise ValueError("仅接受本机页面提交")

    def _profile_key_usable(self, profile: dict) -> bool:
        try:
            self.server.secrets.decrypt(profile["encrypted_api_key"])
            return True
        except ValueError:
            return False

    def _selected_profile(self) -> dict | None:
        selected = self.server.storage.selected_model_profile(self._session())
        return self.server.storage.model_profile(selected) if selected else None

    def _model(self) -> ModelGateway:
        profile = self._selected_profile()
        if profile is None:
            model = self.server.model
        else:
            model = ModelGateway({"base_url": profile["base_url"], "chat_model": profile["chat_model"],
                                  "api_key": self.server.secrets.decrypt(profile["encrypted_api_key"])})
        if not model.chat_ready:
            raise ValueError("请先在“管理模型与 API”中配置对话模型")
        return model

    def _models_public(self) -> dict:
        selected = self.server.storage.selected_model_profile(self._session())
        profiles = [{key: p[key] for key in ("id", "name", "base_url", "chat_model")}
                    | {"has_key": bool(p["encrypted_api_key"]), "key_usable": self._profile_key_usable(p)}
                    for p in self.server.storage.model_profiles()]
        active = next((p for p in profiles if p["id"] == selected), None)
        saved_search = self.server.storage.search_key(self._session())
        try:
            search_usable = bool(self.server.secrets.decrypt(saved_search)) if saved_search else bool(
                os.getenv("MINDOS_BRAVE_SEARCH_API_KEY", ""))
        except ValueError:
            search_usable = False
        return {"profiles": profiles, "selected_id": selected or ("env" if self.server.model.chat_ready else None),
                "env_available": self.server.model.chat_ready,
                "model_ready": bool(active and active["key_usable"] or not selected and self.server.model.chat_ready),
                "search_has_key": bool(saved_search or os.getenv("MINDOS_BRAVE_SEARCH_API_KEY", "")),
                "search_ready": search_usable}

    def _search(self) -> WebSearch:
        encrypted = self.server.storage.search_key(self._session())
        api_key = self.server.secrets.decrypt(encrypted) if encrypted else os.getenv("MINDOS_BRAVE_SEARCH_API_KEY", "")
        return WebSearch(api_key)

    def _owned_course(self, course_id: str) -> dict:
        if not isinstance(course_id, str) or len(course_id) > 80:
            raise ValueError("课程编号无效")
        course = self.server.storage.course(self._session(), course_id)
        if not course:
            raise ValueError("课程不存在")
        review = self.server.storage.confirmed_review(self._session(), course_id)
        course["review_plan"] = review["plan"] if review else None
        return course

    def _unlocked_section(self, course: dict, ordinal: object) -> dict:
        if (not isinstance(ordinal, int) or isinstance(ordinal, bool) or
                not 1 <= ordinal <= course["current_ordinal"]):
            raise ValueError("未来小节尚未开放，请先明确选择进入下一小节")
        return course["sections"][ordinal - 1]

    def _course_public(self, course_id: str, ordinal: int | None = None) -> dict:
        course = self._owned_course(course_id)
        current = course["sections"][course["current_ordinal"] - 1]
        viewed = self._unlocked_section(course, ordinal or course["current_ordinal"])
        return {"course": {key: value for key, value in course.items() if key != "review_plan"},
                "mastery": self.server.storage.mastery(self._session(), course_id),
                "current_section": current, "section": viewed,
                "review": self.server.storage.confirmed_review(self._session(), course_id),
                "turns": self.server.storage.tutor_turns(self._session(), course_id, viewed["id"]),
                "quizzes": self.server.storage.section_quizzes(self._session(), course_id, viewed["id"])}

    def do_GET(self) -> None:
        self._safe_call(self._get)

    def do_POST(self) -> None:
        self._safe_call(self._post)

    def _get(self) -> None:
        parsed = urlsplit(self.path)
        if parsed.path in STATIC:
            name, content_type = STATIC[parsed.path]
            self._send(HTTPStatus.OK, (WEB / name).read_bytes(), content_type)
        elif parsed.path == "/api/health":
            self._json(HTTPStatus.OK, {"status": "ok"})
        elif parsed.path == "/api/bootstrap":
            self._json(HTTPStatus.OK, {**self._models_public(),
                "courses": self.server.storage.courses(self._session()),
                "drafts": self.server.storage.drafts(self._session())})
        elif parsed.path == "/api/draft":
            draft_id = parse_qs(parsed.query).get("draft_id", [""])[0]
            draft = self.server.storage.draft(self._session(), draft_id)
            if not draft:
                raise ValueError("课程审查稿不存在")
            self._json(HTTPStatus.OK, {"draft": draft})
        elif parsed.path == "/api/course":
            course_id = parse_qs(parsed.query).get("course_id", [""])[0]
            ordinal = parse_qs(parsed.query).get("ordinal", [""])[0]
            self._json(HTTPStatus.OK, self._course_public(course_id, int(ordinal) if ordinal.isdigit() else None))
        else:
            self._json(HTTPStatus.NOT_FOUND, {"error": "页面或接口不存在"})

    def _post(self) -> None:
        self._check_local_request()
        payload = self._request_json()
        path = urlsplit(self.path).path
        if path == "/api/models/save":
            profile_id = payload.get("id")
            old = None
            if profile_id is not None:
                if not isinstance(profile_id, str) or not (old := self.server.storage.model_profile(profile_id)):
                    raise ValueError("模型配置不存在")
            elif len(self.server.storage.model_profiles()) >= 20:
                raise ValueError("最多保存 20 个模型配置")
            fields = {}
            for key, limit in (("name", 60), ("base_url", 500), ("chat_model", 120)):
                value = payload.get(key, "")
                if not isinstance(value, str) or len(value) > limit or "\n" in value or "\r" in value:
                    raise ValueError("模型配置格式无效")
                fields[key] = value.strip()
            if not all(fields.values()):
                raise ValueError("请填写配置名称、API 地址和模型名称")
            api_key = payload.get("api_key", "")
            if not isinstance(api_key, str) or len(api_key) > 4096 or "\n" in api_key or "\r" in api_key:
                raise ValueError("API 密钥格式无效")
            if not api_key and old and old["encrypted_api_key"] and not self._profile_key_usable(old):
                raise ValueError("旧密钥无法解密，请重新输入密钥后保存")
            ModelGateway({"base_url": fields["base_url"], "chat_model": fields["chat_model"], "api_key": api_key})
            encrypted = self.server.secrets.encrypt(api_key) if api_key else old["encrypted_api_key"] if old else ""
            profile = {"id": profile_id or secrets.token_urlsafe(12), **fields,
                       "embedding_model": "", "encrypted_api_key": encrypted}
            self.server.storage.save_model_profile(profile)
            self.server.storage.select_model_profile(self._session(), profile["id"])
            self._json(HTTPStatus.OK, self._models_public())
        elif path == "/api/models/select":
            profile_id = payload.get("id")
            if profile_id == "env" and self.server.model.chat_ready:
                self.server.storage.select_model_profile(self._session(), None)
            elif isinstance(profile_id, str) and self.server.storage.model_profile(profile_id):
                self.server.storage.select_model_profile(self._session(), profile_id)
            else:
                raise ValueError("请选择已保存的模型配置")
            self._json(HTTPStatus.OK, self._models_public())
        elif path == "/api/models/delete":
            profile_id = payload.get("id")
            if not isinstance(profile_id, str) or not self.server.storage.model_profile(profile_id):
                raise ValueError("模型配置不存在")
            self.server.storage.delete_model_profile(profile_id)
            self._json(HTTPStatus.OK, self._models_public())
        elif path == "/api/models/test":
            self._model().test_connection()
            self._json(HTTPStatus.OK, {"ok": True})
        elif path == "/api/search/save":
            api_key = payload.get("api_key", "")
            clear = payload.get("clear", False)
            if (not isinstance(api_key, str) or len(api_key) > 4096 or "\n" in api_key or
                    "\r" in api_key or not isinstance(clear, bool) or (clear and api_key)):
                raise ValueError("网页搜索密钥格式无效")
            if api_key:
                self.server.storage.save_search_key(self._session(), self.server.secrets.encrypt(api_key))
            elif clear:
                self.server.storage.save_search_key(self._session(), "")
            else:
                raise ValueError("请输入 Brave Search API 密钥")
            self._json(HTTPStatus.OK, self._models_public())
        elif path == "/api/courses/draft":
            title, goal = payload.get("title"), payload.get("goal", "")
            if not isinstance(title, str) or not 2 <= len(title.strip()) <= 100:
                raise ValueError("请输入 2 至 100 字的课程名称")
            if not isinstance(goal, str) or len(goal) > 500:
                raise ValueError("学习目标不能超过 500 字")
            if len(self.server.storage.courses(self._session())) >= 50:
                raise ValueError("最多创建 50 门课程")
            draft_id, revision = payload.get("draft_id"), payload.get("revision")
            feedback = payload.get("feedback", "")
            if not isinstance(feedback, str) or len(feedback) > 500:
                raise ValueError("修改意见不能超过 500 字")
            previous = None
            if draft_id is not None:
                if not isinstance(draft_id, str) or not isinstance(revision, int) or isinstance(revision, bool):
                    raise ValueError("课程审查稿编号无效")
                previous = self.server.storage.draft(self._session(), draft_id)
                if not previous or previous["confirmed_course_id"]:
                    raise ValueError("课程审查稿不存在或已确认")
                if previous["revision"] != revision:
                    raise ValueError("审查稿已经变化，请刷新后重新修改")
                if not feedback.strip() and title.strip() == previous["title"] and goal.strip() == previous["goal"]:
                    raise ValueError("请填写想修改的学习方向")
            elif len(self.server.storage.drafts(self._session())) >= 20:
                raise ValueError("最多保留 20 份未确认审查稿")
            model = self._model()
            search = self._search()
            queries = model.search_queries(title.strip(), goal.strip(), feedback.strip(),
                                           previous["plan"] if previous else None)
            sources = search.search(queries)
            plan = model.plan_course_review(title.strip(), goal.strip(), feedback.strip(),
                                            previous["plan"] if previous else None, sources)
            draft = self.server.storage.save_draft(self._session(), title.strip(), goal.strip(),
                feedback.strip(), plan, sources, draft_id, revision)
            self._json(HTTPStatus.OK, {"draft": draft})
        elif path == "/api/courses/confirm":
            draft_id, revision = payload.get("draft_id"), payload.get("revision")
            if (not isinstance(draft_id, str) or not isinstance(revision, int) or
                    isinstance(revision, bool)):
                raise ValueError("课程审查稿编号无效")
            course = self.server.storage.confirm_draft(self._session(), draft_id, revision)
            self._json(HTTPStatus.OK, {"course_id": course["id"], "course": self._course_public(course["id"])})
        elif path == "/api/sections/lesson":
            course = self._owned_course(payload.get("course_id"))
            section = self._unlocked_section(course, payload.get("ordinal"))
            if not section["lesson"]:
                lesson = self._model().teach_section(
                    course, section, self.server.storage.mastery(self._session(), course["id"]),
                    self.server.storage.weak_points(self._session(), course["id"]))
                self.server.storage.save_lesson(self._session(), course["id"], section["id"], lesson)
            self._json(HTTPStatus.OK, self._course_public(course["id"], section["ordinal"]))
        elif path == "/api/sections/ask":
            course = self._owned_course(payload.get("course_id"))
            section = self._unlocked_section(course, payload.get("ordinal"))
            question = payload.get("question")
            if not section["lesson"]:
                raise ValueError("请先生成本节讲解")
            if not isinstance(question, str) or not 2 <= len(question.strip()) <= 500:
                raise ValueError("请输入 2 至 500 字的问题")
            turns = self.server.storage.tutor_turns(self._session(), course["id"], section["id"])
            answer = self._model().answer_question(course, section, turns, question.strip())
            self.server.storage.add_tutor_exchange(self._session(), course["id"], section["id"], question.strip(), answer)
            self._json(HTTPStatus.OK, self._course_public(course["id"], section["ordinal"]))
        elif path == "/api/sections/quiz":
            course = self._owned_course(payload.get("course_id"))
            section = self._unlocked_section(course, payload.get("ordinal"))
            if not section["lesson"]:
                raise ValueError("请先生成本节讲解")
            previous = self.server.storage.section_quizzes(self._session(), course["id"], section["id"])
            if previous and previous[-1]["submitted_at"] is None:
                self._json(HTTPStatus.OK, self._course_public(course["id"], section["ordinal"]))
                return
            prompts = [q["prompt"] for quiz in previous for q in quiz["questions"]]
            weak_prompts = [question["prompt"] for quiz in previous if quiz["submitted_at"]
                            for question, user_answer, result in zip(
                                quiz["questions"], quiz["user_answers"], quiz["results"])
                            if user_answer != result["answer"]]
            questions, answers = self._model().generate_quiz(course, section, prompts, weak_prompts)
            self.server.storage.create_quiz(self._session(), course["id"], section["id"], questions, answers)
            self._json(HTTPStatus.OK, self._course_public(course["id"], section["ordinal"]))
        elif path == "/api/quizzes/submit":
            course = self._owned_course(payload.get("course_id"))
            answers = payload.get("answers")
            if not isinstance(answers, list) or any(not isinstance(a, str) for a in answers):
                raise ValueError("请完成全部题目")
            result = self.server.storage.submit_quiz(self._session(), course["id"], payload.get("quiz_id"), answers)
            self._json(HTTPStatus.OK, {"result": result, **self._course_public(course["id"])})
        elif path == "/api/sections/advance":
            course = self._owned_course(payload.get("course_id"))
            expected = payload.get("expected_ordinal")
            if not isinstance(expected, int) or isinstance(expected, bool) or expected != course["current_ordinal"]:
                raise ValueError("课程进度已变化，请刷新后再试")
            if not course["sections"][expected - 1]["lesson"]:
                raise ValueError("请先学习当前小节")
            if not self.server.storage.advance(self._session(), course["id"], expected):
                raise ValueError("已经是最后一节，或课程进度已变化")
            self._json(HTTPStatus.OK, self._course_public(course["id"]))
        else:
            self._json(HTTPStatus.NOT_FOUND, {"error": "接口不存在"})

    def _safe_call(self, handler) -> None:
        try:
            handler()
        except ValueError as exc:
            self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
        except ModelUnavailable as exc:
            self._json(HTTPStatus.SERVICE_UNAVAILABLE, {"error": str(exc)})
        except SearchUnavailable as exc:
            self._json(HTTPStatus.SERVICE_UNAVAILABLE, {"error": str(exc)})
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
