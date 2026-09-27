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
from .flow import diagnostic_tasks, learning_plan, public_diagnostics
from .learning import progress, recommendation, submit
from .model import ModelGateway, ModelUnavailable
from .retrieval import retrieve, terms
from .secrets import SecretStore
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

    def _selected_profile(self) -> dict | None:
        selected = self.server.storage.selected_model_profile(self._session())
        return self.server.storage.model_profile(selected) if selected else None

    def _model_ready(self) -> bool:
        profile = self._selected_profile()
        return bool(profile["base_url"] and profile["chat_model"]) if profile else self.server.model.chat_ready

    def _embedding_ready(self) -> bool:
        profile = self._selected_profile()
        return bool(profile["base_url"] and profile["embedding_model"]) if profile else self.server.model.embedding_ready

    def _model(self) -> ModelGateway:
        profile = self._selected_profile()
        if profile is None:
            return self.server.model
        return ModelGateway({"base_url": profile["base_url"], "chat_model": profile["chat_model"],
                             "embedding_model": profile["embedding_model"],
                             "api_key": self.server.secrets.decrypt(profile["encrypted_api_key"])})

    def _models_public(self) -> dict:
        selected = self.server.storage.selected_model_profile(self._session())
        return {"profiles": [
            {key: profile[key] for key in ("id", "name", "base_url", "chat_model", "embedding_model")}
            | {"has_key": bool(profile["encrypted_api_key"])}
            for profile in self.server.storage.model_profiles()
        ], "selected_id": selected or ("env" if self.server.model.chat_ready else None),
            "env_available": self.server.model.chat_ready}

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
                      for task in diagnostic_tasks(pack) if task["id"] in answers}
        states = progress(pack, rows, by_concept)
        goal = self.server.storage.goal(self._session(), pack)
        target = self.server.storage.target(self._session(), pack)
        plan = learning_plan(pack, states, answers, goal, target["concept_id"] if target else None) if goal or target else []
        return {
            "course": self.server.catalog.public_course(course_id),
            "goal": goal,
            "target": target,
            "diagnostic_skipped": bool(target and self.server.storage.diagnostics_skipped(
                self._session(), pack, target["concept_id"])),
            "learning_mode": self.server.storage.mode(self._session()),
            "diagnostic": public_diagnostics(pack, answers, target["concept_id"] if target else None),
            "progress": states,
            "plan": plan,
            "recommendation": recommendation(pack, states, rows, self.server.storage.helped_tasks(self._session(), pack),
                                             {item["concept_id"] for item in plan} if goal or target else None),
            "valid_evidence_count": sum(row["counts_for_state"] for row in rows),
            "recent": list(reversed(rows[-8:])),
        }

    def _concept_source(self, pack: dict, concept: dict) -> dict:
        chunks = [item for item in self.server.catalog.teaching_chunks(pack)
                  if concept["id"] in item["concept_ids"]]
        if not chunks:
            raise ValueError("该知识点暂无课程资料")
        sections = [item for item in chunks if " · " in item["title"]] or chunks
        concept_terms = terms(concept["title"])

        def score(item: dict) -> tuple[int, int]:
            section_terms = terms(item["title"].split(" · ")[-1])
            return (sum(min(weight, section_terms[token]) for token, weight in concept_terms.items()),
                    len(item["content"]))

        return max(sections, key=score)

    def _learner_hint(self, pack: dict, concept_id: str | None) -> str:
        if not concept_id:
            return "尚未指定当前知识点；不要推断学习者水平"
        prerequisite_ids = {edge["from"] for edge in pack["relations"]
                            if edge["type"] == "prerequisite" and edge["to"] == concept_id}
        rows = [item for item in self._dashboard(pack["id"])["progress"]
                if item["concept_id"] in prerequisite_ids | {concept_id}]
        if not rows:
            return "当前知识点暂无学习证据"
        return "；".join(
            f"{item['concept_title']}／{item['dimension_label']}：{item['state_label']}，"
            f"短诊断{'未做' if item['diagnostic_result'] is None else '通过' if item['diagnostic_result'] else '待补强'}，"
            f"独立作答证据{item['evidence_count']}份"
            for item in rows
        )

    def _tutor_concept(self, pack: dict, concept_id: str) -> dict:
        if self.server.storage.mode(self._session()) != "ai" or not self._model_ready():
            raise ValueError("逐节讲解需要先配置并启用大模型")
        target = self.server.storage.target(self._session(), pack)
        if target is None:
            raise ValueError("请先确认目标知识点")
        answers = self.server.storage.diagnostics(self._session(), pack)
        if (not self.server.storage.diagnostics_skipped(self._session(), pack, target["concept_id"])
                and any(task["id"] not in answers for task in diagnostic_tasks(pack, target["concept_id"]))):
            raise ValueError("请先完成或跳过学前小测")
        route = {item["concept_id"] for item in self._dashboard(pack["id"])["plan"]}
        if concept_id not in route:
            raise ValueError("请选择当前目标路线中的知识点")
        return next(item for item in pack["concepts"] if item["id"] == concept_id)

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
                "chat_ready": self._model_ready(),
                "embedding_ready": self._embedding_ready(),
                "learning_mode": self.server.storage.mode(self._session()),
            })
        elif parsed.path == "/api/models":
            self._json(HTTPStatus.OK, self._models_public())
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
        elif parsed.path == "/api/mode":
            mode = payload.get("mode")
            if not isinstance(mode, str) or mode not in {"materials", "ai"}:
                raise ValueError("请选择资料模式或大模型模式")
            if mode == "ai" and not self._model_ready():
                raise ValueError("服务端尚未配置大模型；请先在本机 .env 中配置并重启，或选择资料模式")
            self.server.storage.set_mode(self._session(), mode)
            self._json(HTTPStatus.OK, {"mode": mode})
        elif parsed.path == "/api/models/save":
            profile_id = payload.get("id")
            old = None
            if profile_id is not None:
                if not isinstance(profile_id, str) or len(profile_id) > 64:
                    raise ValueError("模型配置编号无效")
                old = self.server.storage.model_profile(profile_id)
                if old is None:
                    raise ValueError("模型配置不存在")
            elif len(self.server.storage.model_profiles()) >= 20:
                raise ValueError("最多保存 20 个模型配置")
            fields = {}
            for key, limit in (("name", 60), ("base_url", 500),
                               ("chat_model", 120), ("embedding_model", 120)):
                value = payload.get(key, "")
                if not isinstance(value, str) or len(value) > limit or "\n" in value or "\r" in value:
                    raise ValueError("模型名称或地址格式无效")
                fields[key] = value.strip()
            if not fields["name"] or not fields["base_url"] or not fields["chat_model"]:
                raise ValueError("请填写配置名称、API 地址和对话模型名称")
            api_key = payload.get("api_key", "")
            clear_key = payload.get("clear_key", False)
            if (not isinstance(api_key, str) or len(api_key) > 4096 or
                    "\n" in api_key or "\r" in api_key or not isinstance(clear_key, bool) or
                    (clear_key and api_key)):
                raise ValueError("API 密钥格式无效")
            key_for_validation = api_key or (self.server.secrets.decrypt(old["encrypted_api_key"])
                                             if old and not clear_key else "")
            ModelGateway({"base_url": fields["base_url"], "chat_model": fields["chat_model"],
                          "embedding_model": fields["embedding_model"], "api_key": key_for_validation})
            encrypted = (self.server.secrets.encrypt(api_key) if api_key else
                         "" if clear_key else old["encrypted_api_key"] if old else "")
            profile = {"id": profile_id or secrets.token_urlsafe(12), **fields,
                       "encrypted_api_key": encrypted}
            self.server.storage.save_model_profile(profile)
            self.server.storage.select_model_profile(self._session(), profile["id"])
            self._json(HTTPStatus.OK, self._models_public())
        elif parsed.path == "/api/models/select":
            profile_id = payload.get("id")
            if profile_id == "env":
                if not self.server.model.chat_ready:
                    raise ValueError("没有可用的环境变量模型配置")
                self.server.storage.select_model_profile(self._session(), None)
            elif isinstance(profile_id, str) and self.server.storage.model_profile(profile_id):
                self.server.storage.select_model_profile(self._session(), profile_id)
            else:
                raise ValueError("请选择已保存的模型配置")
            self._json(HTTPStatus.OK, self._models_public())
        elif parsed.path == "/api/models/delete":
            profile_id = payload.get("id")
            if not isinstance(profile_id, str) or not self.server.storage.model_profile(profile_id):
                raise ValueError("模型配置不存在")
            self.server.storage.delete_model_profile(profile_id)
            self._json(HTTPStatus.OK, self._models_public())
        elif parsed.path == "/api/models/test":
            if not self._model_ready():
                raise ValueError("请先选择模型配置")
            result = self._model()._post("/chat/completions", {
                "model": self._model().chat_model, "max_tokens": 12,
                "messages": [{"role": "user", "content": "请回复 OK"}],
            }, timeout=15)
            if (not isinstance(result.get("choices"), list) or not result["choices"] or
                    not isinstance(result["choices"][0].get("message", {}).get("content"), str) or
                    not result["choices"][0]["message"]["content"].strip()):
                raise ModelUnavailable("模型连接成功，但返回格式不符合预期")
            self._json(HTTPStatus.OK, {"ok": True})
        elif parsed.path == "/api/target":
            pack = self.server.catalog.get(payload.get("course_id", ""))
            if not self.server.storage.mode(self._session()):
                raise ValueError("请先选择学习方式")
            chapter_id, concept_id = payload.get("chapter_id"), payload.get("concept_id")
            chapter = next((item for item in pack["chapters"] if item["id"] == chapter_id), None)
            if chapter is None or concept_id not in chapter["concept_ids"]:
                raise ValueError("请选择当前课程章节内的知识点")
            custom = payload.get("custom_text", "")
            if not isinstance(custom, str) or len(custom) > 200:
                raise ValueError("自定义目标不能超过 200 字")
            if custom and self.server.storage.mode(self._session()) != "ai":
                raise ValueError("自定义目标分析需要大模型模式")
            self.server.storage.set_target(self._session(), pack, chapter_id, concept_id, custom.strip())
            self._json(HTTPStatus.OK, {"dashboard": self._dashboard(pack["id"])})
        elif parsed.path == "/api/analyze-goal":
            pack = self.server.catalog.get(payload.get("course_id", ""))
            if self.server.storage.mode(self._session()) != "ai" or not self._model_ready():
                raise ValueError("请先启用已配置的大模型模式")
            custom = payload.get("custom_text")
            if not isinstance(custom, str) or not 4 <= len(custom.strip()) <= 200:
                raise ValueError("请用 4 至 200 字描述想达到的学习目标")
            states = self._dashboard(pack["id"])["progress"]
            learner_hint = "；".join(f"{item['concept_title']}·{item['dimension_label']}：{item['state_label']}" for item in states)
            analysis = self._model().analyze_goal(pack, custom.strip(), learner_hint)
            concept_id = analysis.get("concept_id")
            rationale = analysis.get("rationale")
            if concept_id is not None and concept_id not in {item["id"] for item in pack["concepts"]}:
                raise ModelUnavailable("模型返回了课程之外的知识点，请重试")
            if not isinstance(rationale, str) or not rationale.strip():
                raise ModelUnavailable("模型没有给出目标分析理由，请重试")
            chapter = next((item for item in pack["chapters"] if concept_id in item["concept_ids"]), None)
            self._json(HTTPStatus.OK, {"concept_id": concept_id,
                                       "chapter_id": chapter["id"] if chapter else None,
                                       "rationale": rationale.strip()[:300]})
        elif parsed.path == "/api/goal":
            pack = self.server.catalog.get(payload.get("course_id", ""))
            goal = payload.get("goal")
            if not isinstance(goal, str) or goal not in pack["learning_goals"]:
                raise ValueError("请选择当前课程提供的学习目标")
            self.server.storage.set_goal(self._session(), pack, goal)
            self._json(HTTPStatus.OK, {"dashboard": self._dashboard(pack["id"])})
        elif parsed.path == "/api/diagnose":
            pack = self.server.catalog.get(payload.get("course_id", ""))
            if not self.server.storage.goal(self._session(), pack) and not self.server.storage.target(self._session(), pack):
                raise ValueError("请先选择学习目标")
            target = self.server.storage.target(self._session(), pack)
            task = next((item for item in diagnostic_tasks(pack, target["concept_id"] if target else None)
                         if item["id"] == payload.get("task_id")), None)
            if task is None:
                raise ValueError("诊断题不存在")
            if task["id"] in self.server.storage.diagnostics(self._session(), pack):
                raise ValueError("这道诊断题已完成")
            answer = payload.get("answer")
            if not isinstance(answer, str) or answer not in {item["id"] for item in task["choices"]}:
                raise ValueError("请选择诊断题提供的选项")
            correct = answer == task["answer"]
            self.server.storage.add_diagnostic(self._session(), pack, task["id"], answer, correct)
            self._json(HTTPStatus.OK, {"result": {"correct": correct}, "dashboard": self._dashboard(pack["id"])})
        elif parsed.path == "/api/skip-diagnostics":
            pack = self.server.catalog.get(payload.get("course_id", ""))
            target = self.server.storage.target(self._session(), pack)
            if target is None:
                raise ValueError("请先确认目标知识点")
            self.server.storage.skip_diagnostics(self._session(), pack, target["concept_id"])
            self._json(HTTPStatus.OK, {"dashboard": self._dashboard(pack["id"])})
        elif parsed.path == "/api/tutor/start":
            pack = self.server.catalog.get(payload.get("course_id", ""))
            concept = self._tutor_concept(pack, payload.get("concept_id", ""))
            reset = payload.get("reset", False)
            if not isinstance(reset, bool):
                raise ValueError("重新讲解参数无效")
            history = self.server.storage.tutor_turns(self._session(), pack, concept["id"])
            if not history or reset:
                prerequisites = [item["title"] for item in pack["concepts"]
                                 if any(edge["type"] == "prerequisite" and edge["from"] == item["id"]
                                        and edge["to"] == concept["id"] for edge in pack["relations"])]
                answer = self._model().tutor(
                    pack["title"], concept["title"], prerequisites,
                    self._learner_hint(pack, concept["id"]),
                    "请从零开始深入讲解这一节，像一对一教学那样逐步说明，并允许我随时打断提问。",
                    [], new_lesson=True)
                self.server.storage.save_tutor_turns(
                    self._session(), pack, concept["id"], [("assistant", "lesson", answer)], reset=True)
                history = [{"role": "assistant", "kind": "lesson", "content": answer}]
            self._json(HTTPStatus.OK, {"title": concept["title"], "answer": history[0]["content"],
                                       "turns": history[1:], "generated": True})
        elif parsed.path == "/api/tutor/ask":
            pack = self.server.catalog.get(payload.get("course_id", ""))
            concept = self._tutor_concept(pack, payload.get("concept_id", ""))
            question = payload.get("question", "")
            if not isinstance(question, str) or not 2 <= len(question.strip()) <= 500:
                raise ValueError("请输入 2 至 500 字的问题")
            history = self.server.storage.tutor_turns(self._session(), pack, concept["id"])
            if not history or history[0]["kind"] != "lesson":
                raise ValueError("请先开始本节讲解")
            prerequisites = [item["title"] for item in pack["concepts"]
                             if any(edge["type"] == "prerequisite" and edge["from"] == item["id"]
                                    and edge["to"] == concept["id"] for edge in pack["relations"])]
            answer = self._model().tutor(
                pack["title"], concept["title"], prerequisites,
                self._learner_hint(pack, concept["id"]), question.strip(), history)
            self.server.storage.save_tutor_turns(self._session(), pack, concept["id"],
                                                 [("user", "question", question.strip()),
                                                  ("assistant", "answer", answer)])
            self._json(HTTPStatus.OK, {"answer": answer, "generated": True})
        elif parsed.path == "/api/ask":
            course_id = payload.get("course_id", "")
            pack = self.server.catalog.get(course_id)
            question = payload.get("question", "")
            concept_id = payload.get("concept_id")
            task_id = payload.get("task_id")
            if payload.get("mode", "practice") == "independent":
                raise ValueError("独立作答期间不提供讲解")
            if not isinstance(question, str) or not 2 <= len(question.strip()) <= 500:
                raise ValueError("请输入 2 至 500 字的问题")
            if concept_id and concept_id not in {item["id"] for item in pack["concepts"]}:
                raise ValueError("知识点不存在")
            if task_id:
                self.server.catalog.task(pack, task_id)
                self.server.storage.mark_help(self._session(), pack, task_id)
            ai_mode = self.server.storage.mode(self._session()) == "ai"
            chunks = self.server.catalog.teaching_chunks(pack)
            if concept_id:
                chunks = [item for item in chunks if concept_id in item["concept_ids"]]
            chunks += self.server.catalog.external_chunks(pack, concept_id)
            sources, retrieval_mode, notice = retrieve(
                question.strip(), chunks, concept_id, self._model(), self.server.storage,
                use_vectors=ai_mode)
            generated = False
            if not sources:
                answer = "当前课程资料中未找到足够相关的内容。请补充更具体的术语或问题。"
            elif ai_mode and self._model_ready():
                hint = self._learner_hint(pack, concept_id)
                try:
                    answer = self._model().explain(question.strip(), sources, hint)
                    generated = True
                    citations = {int(number) for number in re.findall(r"\[(\d+)\]", answer)}
                    if citations - set(range(1, len(sources) + 1)):
                        answer = re.sub(r"\[(\d+)\]", lambda match: match.group(0)
                                        if int(match.group(1)) <= len(sources) else "", answer)
                        notice = "模型引用了本次检索之外的编号，已移除无效编号；请核对原文。"
                except ModelUnavailable:
                    answer = self._source_hint(sources[0])
                    notice = "模型连接失败；作答记录未受影响。"
            else:
                answer = self._source_hint(sources[0])
            self._json(HTTPStatus.OK, {
                "answer": answer, "retrieval_mode": retrieval_mode,
                "sources": [{key: item[key] for key in ("id", "title", "content", "url", "provenance")}
                            for item in sources],
                "notice": notice,
                "generated": generated,
            })
        elif parsed.path == "/api/lesson":
            pack = self.server.catalog.get(payload.get("course_id", ""))
            target = self.server.storage.target(self._session(), pack)
            if target is None:
                raise ValueError("请先确认目标知识点")
            answers = self.server.storage.diagnostics(self._session(), pack)
            if (not self.server.storage.diagnostics_skipped(self._session(), pack, target["concept_id"])
                    and any(task["id"] not in answers for task in diagnostic_tasks(pack, target["concept_id"]))):
                raise ValueError("请先完成或跳过基础测试")
            route = {item["concept_id"] for item in self._dashboard(pack["id"])["plan"]}
            concept_id = payload.get("concept_id", target["concept_id"])
            if concept_id not in route:
                raise ValueError("请选择当前目标路线中的知识点")
            concept = next(item for item in pack["concepts"] if item["id"] == concept_id)
            materials = self.server.catalog.lesson_materials(pack, concept["id"])
            if not materials:
                raise ValueError("该知识点暂无课程资料")
            sources = [item for item in self.server.catalog.teaching_chunks(pack)
                       if concept["id"] in item["concept_ids"]]
            if self.server.storage.mode(self._session()) == "ai":
                sources += self.server.catalog.external_chunks(pack, concept["id"])
            learner_hint = self._learner_hint(pack, concept["id"])
            generated, notice = False, None
            authored_lesson = "\n\n".join(item["content"] for item in materials)
            if self.server.storage.mode(self._session()) == "ai" and self._model_ready():
                try:
                    answer = self._model().explain(
                        f"请从零基础逐步讲解知识点「{concept['title']}」，先解释术语和学习目的，"
                        "再分步骤展示例子，每一步说明为什么这样做，最后用一道不泄露独立测评的小检查帮助理解。"
                        "根据学习者状态调整起点和难度，但不要解答当前独立题。",
                        sources, learner_hint, deep_lesson=True)
                    generated = True
                    citations = {int(number) for number in re.findall(r"\[(\d+)\]", answer)}
                    if citations - set(range(1, len(sources) + 1)):
                        answer = re.sub(r"\[(\d+)\]", lambda match: match.group(0)
                                        if int(match.group(1)) <= len(sources) else "", answer)
                        notice = "模型引用了本次课程资料之外的编号，已移除无效编号；请核对原文。"
                except ModelUnavailable:
                    answer = authored_lesson
                    notice = "模型暂不可用，已展示完整课程讲义。"
            else:
                answer = authored_lesson
            self._json(HTTPStatus.OK, {"title": concept["title"], "answer": answer,
                                       "generated": generated, "notice": notice,
                                       "base_lesson": authored_lesson,
                                       "sources": sources if generated else materials,
                                       "source": materials[0]})
        elif parsed.path == "/api/quiz":
            pack = self.server.catalog.get(payload.get("course_id", ""))
            if self.server.storage.mode(self._session()) != "ai" or not self._model_ready():
                raise ValueError("按需生成小测验需要已配置的大模型模式")
            concept_id = payload.get("concept_id")
            concept = next((item for item in pack["concepts"] if item["id"] == concept_id), None)
            if concept is None:
                raise ValueError("请选择当前课程知识点")
            if payload.get("tutor") is True:
                self._tutor_concept(pack, concept_id)
                history = self.server.storage.tutor_turns(self._session(), pack, concept_id)
                if not history or history[0]["kind"] != "lesson":
                    raise ValueError("请先开始本节讲解")
                source = {"title": f"本节 AI 讲解：{concept['title']}",
                          "content": history[0]["content"], "url": ""}
            else:
                source = self._concept_source(pack, concept)
            states = [item for item in self._dashboard(pack["id"])["progress"] if item["concept_id"] == concept_id]
            learner_hint = "；".join(f"{item['dimension_label']}：{item['state_label']}" for item in states)
            generated = self._model().generate_quiz(concept["title"], source, learner_hint)
            prompt, choices, answer, explanation = (generated.get(key) for key in
                                                     ("prompt", "choices", "answer", "explanation"))
            if (not isinstance(prompt, str) or not 10 <= len(prompt.strip()) <= 400
                    or not isinstance(choices, list) or len(choices) != 3
                    or not all(isinstance(item, dict) and item.get("id") in ("a", "b", "c")
                               and isinstance(item.get("text"), str) and 1 <= len(item["text"]) <= 200
                               for item in choices)
                    or [item["id"] for item in choices] != ["a", "b", "c"]
                    or answer not in ("a", "b", "c")
                    or not isinstance(explanation, str) or not 5 <= len(explanation.strip()) <= 800
                    or prompt in {task["prompt"] for task in pack["tasks"]}):
                raise ModelUnavailable("模型生成的小测验格式不合格，请重试")
            quiz = {"id": secrets.token_urlsafe(16), "concept_id": concept_id,
                    "prompt": prompt.strip(), "choices": choices, "answer": answer,
                    "explanation": explanation.strip(), "source_title": source["title"],
                    "source_url": source["url"]}
            self.server.storage.save_quiz(self._session(), pack, quiz)
            self._json(HTTPStatus.OK, {key: quiz[key] for key in
                                       ("id", "concept_id", "prompt", "choices", "source_title", "source_url")})
        elif parsed.path == "/api/quiz-answer":
            pack = self.server.catalog.get(payload.get("course_id", ""))
            quiz_id = payload.get("quiz_id", "")
            if not isinstance(quiz_id, str) or len(quiz_id) > 100:
                raise ValueError("小测验编号无效")
            quiz = self.server.storage.quiz(self._session(), pack, quiz_id)
            if quiz is None:
                raise ValueError("小测验不存在或不属于当前会话")
            answer = payload.get("answer")
            if answer not in ("a", "b", "c"):
                raise ValueError("请选择一个选项")
            self._json(HTTPStatus.OK, {"correct": answer == quiz["answer"],
                                       "answer": quiz["answer"], "explanation": quiz["explanation"],
                                       "counts_for_state": False})
        else:
            self._json(HTTPStatus.NOT_FOUND, {"error": "接口不存在"})

    @staticmethod
    def _source_hint(source: dict) -> str:
        content = source["content"].strip()
        return f"课程资料 [1]：\n{content[:1800]}"

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
        except ModelUnavailable as exc:
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
