"""Local MindOS server for user-created, section-by-section AI courses."""

from __future__ import annotations

import argparse
import base64
import binascii
import json
import logging
import os
import re
import secrets
import threading
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from .search_planning import build_search_plan, course_context
from .course_tutor import CourseTutorService
from .teaching import TeachingOrchestrator, generate_lesson
from .adaptive import ContentGenerator, LearningStateManager
from .course_management import validate_fields
from .model import ModelGateway, ModelUnavailable
from .acquisition import DirectInputProvider, UploadProvider, WebSearchProvider, fetch_public_document
from .production import normalize_candidate_result
from .discovery import DiscoveryEngine, POLICIES, produce_source, selected_blocks, teaching_blocks
from .secrets import SecretStore
from .storage import Storage
from .web_search import PublicSourceSearch, SearchUnavailable, WebSearch

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
LOGGER = logging.getLogger("mindos")
STATIC = {"/components/mindos/mission.js": ("components/mindos/mission.js", "text/javascript; charset=utf-8"), "/mission.css": ("mission.css", "text/css; charset=utf-8"),"/knowledge-space.css": ("knowledge-space.css", "text/css; charset=utf-8"),"/components/mindos/knowledge-space.js": ("components/mindos/knowledge-space.js", "text/javascript; charset=utf-8"),"/components/mindos/resource-renderer.js": ("components/mindos/resource-renderer.js", "text/javascript; charset=utf-8"),"/vendor/katex.min.js": ("vendor/katex.min.js", "text/javascript; charset=utf-8"),"/knowledge-universe.css": ("knowledge-universe.css", "text/css; charset=utf-8"),"/components/mindos/universe-renderer.js": ("components/mindos/universe-renderer.js", "text/javascript; charset=utf-8"),"/components/mindos/knowledge-universe.js": ("components/mindos/knowledge-universe.js", "text/javascript; charset=utf-8"),"/components/mindos/tutor-quality.js": ("components/mindos/tutor-quality.js", "text/javascript; charset=utf-8"),"/components/mindos/tutor.js": ("components/mindos/tutor.js", "text/javascript; charset=utf-8"),"/components/mindos/study.js": ("components/mindos/study.js", "text/javascript; charset=utf-8"),"/components/mindos/growth.js": ("components/mindos/growth.js", "text/javascript; charset=utf-8"),"/components/mindos/personal.js": ("components/mindos/personal.js", "text/javascript; charset=utf-8"),"/components/mindos/authentic.js": ("components/mindos/authentic.js", "text/javascript; charset=utf-8"),"/components/mindos/course-final.js": ("components/mindos/course-final.js", "text/javascript; charset=utf-8"),"/components/mindos/learning-loop.js": ("components/mindos/learning-loop.js", "text/javascript; charset=utf-8"),"/": ("index.html", "text/html; charset=utf-8"),
          "/components/teaching/teaching-blocks.js": ("components/teaching/teaching-blocks.js", "text/javascript; charset=utf-8"),
          "/app.js": ("app.js", "text/javascript; charset=utf-8"),
          "/components/CourseManager/course-manager.js": ("components/CourseManager/course-manager.js", "text/javascript; charset=utf-8"),
          "/components/CourseAssistant/course-assistant.js": ("components/CourseAssistant/course-assistant.js", "text/javascript; charset=utf-8"),
          "/production.js": ("production.js", "text/javascript; charset=utf-8"),
          "/components/mindos/state.js": ("components/mindos/state.js", "text/javascript; charset=utf-8"),
          "/components/mindos/universe.js": ("components/mindos/universe.js", "text/javascript; charset=utf-8"),
          "/universe.css": ("universe.css", "text/css; charset=utf-8"),
          "/style.css": ("style.css", "text/css; charset=utf-8")}
ENV_KEYS = {"MINDOS_MODEL_BASE_URL", "MINDOS_CHAT_MODEL", "MINDOS_MODEL_API_KEY",
            "MINDOS_BRAVE_SEARCH_API_KEY", "MINDOS_DATA_PATH", "MINDOS_DEBUG_LEARNING"}


class MindOSServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, port: int, data_path: Path) -> None:
        self.storage = Storage(data_path)
        self.model = ModelGateway()
        self.discovery_engine = DiscoveryEngine(self.storage)
        self.course_tutor = CourseTutorService(self.storage)
        self.teaching = TeachingOrchestrator(self.storage)
        self.content_generator = ContentGenerator(self.storage)
        self.canonical_slots=threading.BoundedSemaphore(2)
        self.assistant_search_factory = None
        self.discovery_provider_factory = None
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
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' https:; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'")
        self._session()
        if self._new_session:
            self.send_header("Set-Cookie", f"mindos_session={self._session_value}; HttpOnly; SameSite=Strict; Path=/; Max-Age=2592000")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: HTTPStatus, payload: dict) -> None:
        self._send(status, json.dumps(payload, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def _request_json(self, limit: int = 8192, *, array=False) -> dict:
        if self.headers.get_content_type() != "application/json":
            raise ValueError("请使用 JSON 请求")
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise ValueError("请求长度无效") from exc
        if not 0 < length <= limit:
            raise ValueError("请求内容过大或为空")
        try:
            payload = json.loads(self.rfile.read(length))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("JSON 格式无效") from exc
        if not isinstance(payload, list if array else dict):
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
        search_profiles = []
        for provider in WebSearch.PROVIDERS:
            config = self._search_config(provider)
            encrypted = config["encrypted_api_key"]
            has_key = bool(encrypted or config["env_key"])
            try:
                usable = bool(self.server.secrets.decrypt(encrypted) if encrypted else config["env_key"])
            except ValueError:
                usable = False
            search_profiles.append({"provider": provider, "api_url": config["api_url"],
                                    "has_key": has_key, "key_usable": usable})
        return {"profiles": profiles, "selected_id": selected or ("env" if self.server.model.chat_ready else None),
                "env_available": self.server.model.chat_ready,
                "model_ready": bool(active and active["key_usable"] or not selected and self.server.model.chat_ready),
                "search_has_key": search_profiles[0]["has_key"],
                "search_ready": search_profiles[0]["key_usable"], "search_profiles": search_profiles}

    def _search_config(self, provider: str) -> dict:
        WebSearch.endpoint(provider)
        saved = self.server.storage.search_profile(self._session(), provider)
        api_url = WebSearch.endpoint(provider, saved["api_url"])
        # Never forward a legacy environment key to a custom address.
        env_key = os.getenv("MINDOS_BRAVE_SEARCH_API_KEY", "") if (
            provider == "brave" and not saved["saved"] and api_url == WebSearch.endpoint("brave")) else ""
        return {**saved, "api_url": api_url, "env_key": env_key}

    def _search(self, mode: str) -> PublicSourceSearch | WebSearch:
        if mode == "public":
            return PublicSourceSearch()
        config = self._search_config(mode)
        encrypted = config["encrypted_api_key"]
        api_key = self.server.secrets.decrypt(encrypted) if encrypted else config["env_key"]
        return WebSearch(api_key, mode, config["api_url"])

    def _owned_course(self, course_id: str) -> dict:
        if not isinstance(course_id, str) or len(course_id) > 80:
            raise ValueError("课程编号无效")
        course = self.server.storage.course(self._session(), course_id)
        if not course:
            raise ValueError("课程不存在")
        review = self.server.storage.confirmed_review(self._session(), course_id)
        course["review_plan"] = review["plan"] if review else None
        course["source_conflicts"] = self.server.storage.conflicts(self._session(),course_id)
        from .context import course_materials
        course['teaching_materials']=course_materials(self.server.storage,self._session(),course)
        return course

    def _start_discovery(self,course):
        model=self._model()
        factory=self.server.discovery_provider_factory
        try:provider=factory(course) if factory else WebSearchProvider(self._search(course['search_mode']),course['search_mode'])
        except (ValueError,SearchUnavailable) as exc:
            message=str(exc)
            class UnavailableProvider:
                def search(self,query):raise SearchUnavailable(message)
            provider=UnavailableProvider()
        return self.server.discovery_engine.start(self._session(),course['id'],model,provider)

    def _section_materials(self,course,section):
        from .context import course_materials
        course['teaching_materials']=course_materials(self.server.storage,self._session(),course,section['title'])
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
        learning_state,knowledge_context=LearningStateManager(self.server.storage).read(self._session(),course_id,viewed['ordinal'])
        scope=self.server.teaching.context(self._session(),course_id,viewed['id'])
        from .learning.final import FinalAssessmentService
        return {'course_final':FinalAssessmentService(self.server.storage).status(self._session(),course_id),"course": {key: value for key, value in course.items() if key not in ("review_plan","teaching_materials")},
                "mastery": self.server.storage.mastery(self._session(), course_id),
                "current_section": current, "section": viewed,
                "lesson_history":self.server.storage.content_versions(self._session(),course_id,'lesson',viewed["id"]),
                "review": self.server.storage.confirmed_review(self._session(), course_id),
                "turns": self.server.storage.tutor_turns(self._session(), course_id, viewed["id"]),
                "quizzes": self.server.storage.section_quizzes(self._session(), course_id, viewed["id"]),
                "knowledge": self.server.storage.knowledge_state(self._session(), course_id),
                "learning_state":learning_state,
                "next_teaching_action":self.server.content_generator.engine.decide(learning_state,knowledge_context,scope)}

    def do_GET(self) -> None:
        self._safe_call(self._get)

    def do_POST(self) -> None:
        self._safe_call(self._post)

    def do_PUT(self) -> None:
        self._safe_call(self._manage_mutation)

    def do_PATCH(self) -> None:
        self._safe_call(self._manage_mutation)

    def do_DELETE(self) -> None:
        self._safe_call(self._manage_mutation)

    def _manage_mutation(self) -> None:
        from .mission.api import dispatch as mission_dispatch
        if mission_dispatch(self):return
        from .resources.api import dispatch as resource_dispatch
        if resource_dispatch(self):return
        from .universe.api import dispatch as universe_dispatch
        if universe_dispatch(self):return
        from .tutor.quality.api import dispatch as quality_dispatch
        if quality_dispatch(self):return
        from .tutor.api import dispatch as tutor_dispatch
        if tutor_dispatch(self):return
        from .learning.execution_api import dispatch as execution_dispatch
        if execution_dispatch(self):return
        from .learning.growth_api import dispatch
        if dispatch(self):return
        self._check_local_request()
        path=urlsplit(self.path).path;session=self._session();store=self.server.storage
        assistant=re.fullmatch(r'/api/courses/([A-Za-z0-9_-]+)/assistant/position',path)
        preferences=re.fullmatch(r'/api/courses/([A-Za-z0-9_-]+)/teaching-preferences',path)
        if preferences and self.command=='PUT':
            self._json(HTTPStatus.OK,{'preferences':store.save_teaching_preferences(session,preferences[1],self._request_json())});return
        if assistant and self.command=='PUT':
            payload=self._request_json()
            self._json(HTTPStatus.OK,{'position':store.save_assistant_position(session,assistant[1],payload.get('x'),payload.get('y'))});return
        if path=='/api/courses/order' and self.command=='PUT':
            self._json(HTTPStatus.OK,{'courses':store.order_courses(session,self._request_json(100000,array=True))});return
        match=re.fullmatch(r'/api/courses/([A-Za-z0-9_-]+)(?:/(status|restore|copy|permanent))?',path)
        if not match:self._json(HTTPStatus.NOT_FOUND,{'error':'课程接口不存在'});return
        cid,operation=match.groups()
        if self.command=='PUT' and operation in (None,'status'):
            payload=self._request_json()
            if operation=='status':payload={'status':payload.get('status')}
            result=store.update_course(session,cid,payload)
        elif self.command=='DELETE' and operation is None:result=store.recycle_course(session,cid)
        elif self.command=='DELETE' and operation=='permanent':
            from .resources.service import ResourceService
            resources=ResourceService(store);resource_ids=resources.course_resource_ids(session,cid)
            store.purge_course(session,cid,self._request_json().get('confirm_title'))
            resources.cleanup(session,resource_ids)
            self._json(HTTPStatus.OK,{'deleted':True});return
        elif self.command=='POST' and operation=='restore':result=store.restore_course(session,cid)
        elif self.command=='POST' and operation=='copy':
            payload=self._request_json();result=store.copy_course(session,cid,payload.get('title',payload.get('name')))
            from .resources.service import ResourceService
            ResourceService(store).copy_links(session,cid,result['id'])
        else:self._json(HTTPStatus.NOT_FOUND,{'error':'课程接口不存在'});return
        self._json(HTTPStatus.OK,{'course':result})

    def _get(self) -> None:
        from .mission.api import dispatch as mission_dispatch
        if mission_dispatch(self):return
        from .resources.api import dispatch as resource_dispatch
        if resource_dispatch(self):return
        from .universe.api import dispatch as universe_dispatch
        if universe_dispatch(self):return
        from .tutor.quality.api import dispatch as quality_dispatch
        if quality_dispatch(self):return
        from .tutor.api import dispatch as tutor_dispatch
        if tutor_dispatch(self):return
        from .learning.execution_api import dispatch as execution_dispatch
        if execution_dispatch(self):return
        from .learning.growth_api import dispatch
        if dispatch(self):return
        parsed = urlsplit(self.path)
        if parsed.path in STATIC:
            name, content_type = STATIC[parsed.path]
            self._send(HTTPStatus.OK, (WEB / name).read_bytes(), content_type)
        elif parsed.path=='/api/debug/learning/personal':
            if os.getenv('MINDOS_DEBUG_LEARNING')!='1':self._json(HTTPStatus.NOT_FOUND,{'error':'接口不存在'});return
            from .learning.personal import PersonalKnowledgeProfileBuilder
            user=self._session();result=PersonalKnowledgeProfileBuilder(self.server.storage).profiles(user,debug=True)
            with self.server.storage.connect() as db:
                result['canonical_atoms']=[dict(r) for r in db.execute('SELECT * FROM canonical_knowledge_atoms WHERE user_id=?',(user,))]
                result['mapping_history']=[dict(r) for r in db.execute('SELECT * FROM canonical_mapping_history WHERE user_id=?',(user,))]
                result['mappings']=[dict(r) for r in db.execute('SELECT * FROM course_atom_mappings WHERE user_id=?',(user,))]
                result['priors']=[dict(r) for r in db.execute('SELECT * FROM inherited_knowledge_priors WHERE user_id=?',(user,))]
            self._json(HTTPStatus.OK,result)
        elif parsed.path=='/api/knowledge/profile' or re.fullmatch(r'/api/knowledge/profile/[A-Za-z0-9_-]+',parsed.path):
            from .learning.personal import PersonalKnowledgeProfileBuilder
            query=parse_qs(parsed.query);service=PersonalKnowledgeProfileBuilder(self.server.storage)
            result=service.profiles(self._session(),query.get('search',[''])[0],query.get('domain',[''])[0],query.get('status',[''])[0])
            if parsed.path!='/api/knowledge/profile':
                p=next((p for p in result['profiles'] if p['canonical_atom_id']==parsed.path.rsplit('/',1)[1]),None)
                identifier=parsed.path.rsplit('/',1)[1];original=identifier;seen=set()
                with self.server.storage.connect() as db:
                    while not p and identifier not in seen:
                        seen.add(identifier);row=db.execute("SELECT redirect_id FROM canonical_knowledge_atoms WHERE id=? AND user_id=? AND status='redirect'",(identifier,self._session())).fetchone()
                        if not row:break
                        identifier=row[0];p=next((item for item in result['profiles'] if item['canonical_atom_id']==identifier),None)
                if not p:raise ValueError('个人知识不存在')
                result={'profile':p,'boundary':result['boundary'],'redirected_from':original if original!=identifier else None}
            self._json(HTTPStatus.OK,result)
        elif re.fullmatch(r'/api/courses/[A-Za-z0-9_-]+/knowledge/(mappings|priors)',parsed.path):
            from .learning.canonical import KnowledgeMappingEngine
            from .learning.personal import InheritedKnowledgePrior
            cid=parsed.path.split('/')[3]
            result=KnowledgeMappingEngine(self.server.storage).list(self._session(),cid) if parsed.path.endswith('mappings') else InheritedKnowledgePrior(self.server.storage).list(self._session(),cid)
            self._json(HTTPStatus.OK,result)
        elif parsed.path=='/api/debug/learning/calibration':
            if os.getenv('MINDOS_DEBUG_LEARNING')!='1':self._json(HTTPStatus.NOT_FOUND,{'error':'页面或接口不存在'});return
            from .learning.calibration import CalibrationService
            self._json(HTTPStatus.OK,CalibrationService(self.server.storage).policy(self._session()))
        elif re.fullmatch(r'/api/courses/[A-Za-z0-9_-]+/calibration',parsed.path):
            from .learning.calibration import CalibrationService
            self._json(HTTPStatus.OK,CalibrationService(self.server.storage).course(self._session(),parsed.path.split('/')[3]))
        elif re.fullmatch(r'/api/courses/[A-Za-z0-9_-]+/authentic/[A-Za-z0-9_-]+',parsed.path):
            from .learning.authentic import AuthenticAssessmentService
            parts=parsed.path.split('/')
            self._json(HTTPStatus.OK,AuthenticAssessmentService(self.server.storage).get(self._session(),parts[3],parts[5]))
        elif re.fullmatch(r'/api/lessons/[A-Za-z0-9_-]+/teaching-context',parsed.path):
            lesson_id = parsed.path.split('/')[3]
            with self.server.storage.connect() as db:
                row = db.execute('SELECT s.course_id FROM sections s JOIN courses c ON c.id=s.course_id WHERE s.id=? AND c.session_id=? AND c.deleted_at IS NULL',
                                 (lesson_id,self._session())).fetchone()
            if not row:raise ValueError('小节不存在')
            self._json(HTTPStatus.OK,self.server.teaching.context(self._session(),row['course_id'],lesson_id))
        elif re.fullmatch(r'/api/courses/[A-Za-z0-9_-]+/final/(status|report|remediation)',parsed.path):
            from .learning.final import FinalAssessmentService
            cid=parsed.path.split('/')[3];op=parsed.path.rsplit('/',1)[1];service=FinalAssessmentService(self.server.storage)
            result=service.report(self._session(),cid) if op=='report' else service.status(self._session(),cid)
            self._json(HTTPStatus.OK,result)
        elif re.fullmatch(r'/api/courses/[A-Za-z0-9_-]+/loop(?:/[a-z-]+)?',parsed.path):
            from .learning.service import LearningLoopService
            cid=parsed.path.split('/')[3];op=parsed.path.split('/')[-1];service=LearningLoopService(self.server.storage);query=parse_qs(parsed.query)
            if op=='state':result=service.explain(self._session(),cid,query.get('atom_id',[''])[0])
            elif op in {'repair','returning'} and query.get('id'):result=service.session(self._session(),cid,op,query['id'][0])
            elif op=='debug':
                if os.getenv('MINDOS_DEBUG_LEARNING')!='1':self._json(HTTPStatus.NOT_FOUND,{'error':'页面或接口不存在'});return
                result=service.snapshot(self._session(),cid)
                with self.server.storage.connect() as db:
                    result['recent_evidence']=[dict(r) for r in db.execute('SELECT * FROM learning_evidence WHERE user_id=? AND course_id=? ORDER BY created_at DESC LIMIT 30',(self._session(),cid))]
                    result['state_history']=[dict(r) for r in db.execute('SELECT * FROM knowledge_state_history WHERE user_id=? AND course_id=? ORDER BY id DESC LIMIT 20',(self._session(),cid))]
            else:result=service.snapshot(self._session(),cid)
            self._json(HTTPStatus.OK,result)
        elif re.fullmatch(r'/api/courses/[A-Za-z0-9_-]+/learning-state',parsed.path):
            cid=parsed.path.split('/')[3];course=self._owned_course(cid);query=parse_qs(parsed.query)
            value=query.get('ordinal',[str(course['current_ordinal'])])[0]
            if not value.isdigit():raise ValueError('小节编号无效')
            state,knowledge=LearningStateManager(self.server.storage).read(self._session(),cid,int(value),query.get('atom_id',[None])[0])
            self._json(HTTPStatus.OK,{'learning_state':state,'knowledge_context':knowledge})
        elif parsed.path == "/api/health":
            self._json(HTTPStatus.OK, {"status": "ok"})
        elif parsed.path == '/api/dashboard':
            from .dashboard import DashboardService
            cid=parse_qs(parsed.query).get('course_id',[None])[0]
            data=DashboardService(self.server.storage).read(self._session(),cid)
            from .learning.growth import GrowthService
            data['growth']=GrowthService(self.server.storage).dashboard(self._session())
            data['context']=self._course_public(data['current']['course_id']) if data['current'] else None
            self._json(HTTPStatus.OK,data)
        elif parsed.path == "/api/bootstrap":
            self._json(HTTPStatus.OK, {**self._models_public(),
                "tutor_quality_debug_enabled": os.getenv("MINDOS_DEBUG_LEARNING")=="1",
                "courses": self.server.storage.courses(self._session()),
                "drafts": self.server.storage.drafts(self._session())})
        elif parsed.path == '/api/courses':
            query=parse_qs(parsed.query)
            self._json(HTTPStatus.OK,{'courses':self.server.storage.managed_courses(self._session(),query.get('status',[None])[0],query.get('deleted',['false'])[0]=='true')})
        elif re.fullmatch(r'/api/courses/[A-Za-z0-9_-]+',parsed.path):
            self._json(HTTPStatus.OK,{'course':self.server.storage.managed_course(self._session(),parsed.path.rsplit('/',1)[1])})
        elif re.fullmatch(r'/api/courses/[A-Za-z0-9_-]+/assistant/history',parsed.path):
            before=parse_qs(parsed.query).get('before',[None])[0]
            if before is not None and not before.isdigit():raise ValueError('历史记录页码无效')
            self._json(HTTPStatus.OK,self.server.storage.assistant_history(self._session(),parsed.path.split('/')[3],int(before) if before else None))
        elif parsed.path == "/api/draft":
            draft_id = parse_qs(parsed.query).get("draft_id", [""])[0]
            draft = self.server.storage.draft(self._session(), draft_id)
            if not draft:
                raise ValueError("课程审查稿不存在")
            self._json(HTTPStatus.OK, {"draft": draft})
        elif parsed.path == "/api/sources":
            course_id = parse_qs(parsed.query).get("course_id", [""])[0]
            self._json(HTTPStatus.OK, {"sources": self.server.storage.sources(self._session(),course_id),
                                      "batches": self.server.storage.batches(self._session(),course_id),
                                      "conflicts":self.server.storage.conflicts(self._session(),course_id),
                                      "discovery":self.server.storage.discovery(self._session(),course_id)})
        elif parsed.path == "/api/source":
            course_id = parse_qs(parsed.query).get("course_id", [""])[0]
            source_id = parse_qs(parsed.query).get("source_id", [""])[0]
            self._json(HTTPStatus.OK, {"source": self.server.storage.source(self._session(),course_id,source_id)})
        elif parsed.path == "/api/knowledge":
            course_id = parse_qs(parsed.query).get("course_id", [""])[0]
            self._owned_course(course_id)
            self._json(HTTPStatus.OK, self.server.storage.knowledge_state(self._session(), course_id))
        elif parsed.path == "/api/atom":
            course_id = parse_qs(parsed.query).get("course_id", [""])[0]
            atom_id = parse_qs(parsed.query).get("atom_id", [""])[0]
            self._json(HTTPStatus.OK, self.server.storage.atom_detail(self._session(), course_id, atom_id))
        elif parsed.path == "/api/course":
            course_id = parse_qs(parsed.query).get("course_id", [""])[0]
            ordinal = parse_qs(parsed.query).get("ordinal", [""])[0]
            self._json(HTTPStatus.OK, self._course_public(course_id, int(ordinal) if ordinal.isdigit() else None))
        else:
            self._json(HTTPStatus.NOT_FOUND, {"error": "页面或接口不存在"})

    def _post(self) -> None:
        from .mission.api import dispatch as mission_dispatch
        if mission_dispatch(self):return
        from .resources.api import dispatch as resource_dispatch
        if resource_dispatch(self):return
        from .universe.api import dispatch as universe_dispatch
        if universe_dispatch(self):return
        from .tutor.quality.api import dispatch as quality_dispatch
        if quality_dispatch(self):return
        from .tutor.api import dispatch as tutor_dispatch
        if tutor_dispatch(self):return
        from .learning.execution_api import dispatch as execution_dispatch
        if execution_dispatch(self):return
        from .learning.growth_api import dispatch
        if dispatch(self):return
        self._check_local_request()
        path = urlsplit(self.path).path
        personal=re.fullmatch(r'/api/courses/([A-Za-z0-9_-]+)/knowledge/(mappings/scan|mappings/[A-Za-z0-9_-]+/(?:verify|reject|split)|priors/[A-Za-z0-9_-]+/verify)',path)
        if personal:
            from .learning.canonical import KnowledgeMappingEngine
            from .learning.personal import InheritedKnowledgePrior
            from .learning.cross_course import CrossCourseVerification
            cid,op=personal.groups();user=self._session();self._owned_course(cid);payload=self._request_json()
            if payload:raise ValueError('此操作不接受客户端评分、置信度或知识状态')
            engine=KnowledgeMappingEngine(self.server.storage)
            try:model=self._model()
            except (ValueError,ModelUnavailable):model=None
            if op=='mappings/scan':result=engine.scan(user,cid,model)
            elif op.startswith('priors/'):result=CrossCourseVerification(self.server.storage).start(user,cid,op.split('/')[1],model)
            elif op.endswith('/split'):result=engine.split(user,cid,op.split('/')[1])
            else:result=engine.review(user,cid,op.split('/')[1],op.endswith('/verify'))
            self._json(HTTPStatus.OK,result);return
        if path=='/api/knowledge/canonical/merge':
            from .learning.canonical import KnowledgeMappingEngine
            payload=self._request_json()
            if payload.get('confirm') is not True:raise ValueError('请明确确认这两个知识身份表达同一概念')
            self._json(HTTPStatus.OK,KnowledgeMappingEngine(self.server.storage).merge(self._session(),payload.get('source_id'),payload.get('target_id')));return
        authentic=re.fullmatch(r'/api/courses/([A-Za-z0-9_-]+)/authentic/(start|[A-Za-z0-9_-]+/(?:submit|draft|defer|hint))',path)
        if authentic:
            from .learning.authentic import AuthenticAssessmentService
            cid,op=authentic.groups();payload=self._request_json(90000);user=self._session();self._owned_course(cid);service=AuthenticAssessmentService(self.server.storage)
            if set(payload)&{'score','valid_for_calibration','hint_used','mastery','evaluation'}:raise ValueError('评分与独立性只能由服务器确定')
            if op=='start':
                growth_context=None
                if payload.get('growth_goal_id') or payload.get('growth_task_id'):
                    from .learning.growth import GrowthService
                    growth_context=GrowthService(self.server.storage).practice_context(user,payload.get('growth_goal_id'),payload.get('growth_task_id'),cid,payload.get('atom_id'))
                result=service.start(user,cid,payload.get('atom_id'),payload.get('task_type'),self._model(),payload.get('difficulty','standard'),growth_context)
            else:
                tid,operation=op.split('/')
                if operation=='submit':
                    try:model=self._model()
                    except (ValueError,ModelUnavailable):model=None
                    result=service.submit(user,cid,tid,payload.get('answer'),model)
                elif operation=='draft':result=service.draft(user,cid,tid,payload.get('answer'))
                elif operation=='hint':result=service.hint(user,cid,tid)
                else:result=service.defer(user,cid,tid)
            self._json(HTTPStatus.OK,result);return
        final=re.fullmatch(r'/api/courses/([A-Za-z0-9_-]+)/final/([a-z-]+|remediation/(?:start|target))',path)
        if final:
            from .learning.final import FinalAssessmentService
            cid,op=final.groups();op=op.replace('remediation/','remediation-');payload=self._request_json(15000);user=self._session();service=FinalAssessmentService(self.server.storage)
            self._owned_course(cid)
            if set(payload)&{'mastery','understanding','application','transfer','retention','score','state','report','targets','blueprint'}:raise ValueError('掌握结论与检测范围只能由服务器生成')
            def optional_final_model():
                try:return self._model()
                except (ValueError,ModelUnavailable):return None
            if op=='complete-content':result=service.complete_content(user,cid)
            elif op=='start':
                if type(payload.get('reassessment',False)) is not bool:raise ValueError('重新检测标记无效')
                result=service.start(user,cid,payload.get('reassessment',False))
            elif op=='assessment':result=service.assessment(user,cid,optional_final_model())
            elif op=='report':
                if type(payload.get('summary',False)) is not bool:raise ValueError('报告说明选项无效')
                result=service.refresh_report(user,cid,optional_final_model() if payload.get('summary') else None,payload.get('summary',False))
            elif op=='defer':
                if type(payload.get('end_with_gaps',False)) is not bool:raise ValueError('暂时结束选项无效')
                result=service.defer(user,cid,payload.get('end_with_gaps',False))
            elif op=='remediation-start':result=service.remediation_start(user,cid)
            elif op=='remediation-target':result=service.remediation_target(user,cid,payload.get('atom_id'),payload.get('return_context'))
            else:self._json(HTTPStatus.NOT_FOUND,{'error':'课程终局接口不存在'});return
            self._json(HTTPStatus.OK,result);return
        learning=re.fullmatch(r'/api/courses/([A-Za-z0-9_-]+)/loop/([a-z-]+)',path)
        if learning:
            from .learning.service import LearningLoopService
            cid,op=learning.groups();payload=self._request_json(15000);service=LearningLoopService(self.server.storage);user=self._session()
            self._owned_course(cid)
            if set(payload)&{'mastery','understanding','application','transfer','retention','score','state'}:raise ValueError('学习状态只能由服务器根据实际答题更新')
            def optional_model():
                try:return self._model()
                except (ValueError,ModelUnavailable):return None
            if op=='enter':result=service.enter(user,cid,payload.get('return_context')) or {'status':'not_needed'}
            elif op=='repair-start':result=service.repair_start(user,cid,payload.get('origin_atom_id'),payload.get('return_context'))
            elif op=='assessment':result=service.assessment(user,cid,payload.get('atom_id'),payload.get('purpose'),optional_model(),payload.get('session_id',''))
            elif op=='repair-content':result=service.repair_content(user,cid,payload.get('session_id'),optional_model())
            elif op=='hint':result=service.hint(user,cid,payload.get('quiz_id'),payload.get('question_index'))
            elif op=='defer':
                if payload.get('kind') not in {'repair','returning'}:raise ValueError('学习任务类型无效')
                result=service.defer(user,cid,payload['kind'],payload.get('session_id'))
            elif op=='self-explanation':
                atom=self.server.storage.atom(user,cid,payload.get('atom_id'),unlocked=True);answer=payload.get('answer')
                if not isinstance(answer,str) or not 1<=len(answer)<=2000:raise ValueError('请填写简短解释')
                from .learning.misconception import MisconceptionEngine
                candidate=MisconceptionEngine().analyze(optional_model(),{'answer':answer,'atom':atom,'standard_concept':atom['summary'],'goal':atom['why']}) if optional_model() else None
                from .learning.evidence import append
                from .learning.state import KnowledgeStateEngine
                with self.server.storage.connect() as db:
                    db.execute('BEGIN IMMEDIATE');self.server.storage._manage_owned(db,user,cid)
                    append(db,user,cid,None,atom['id'],'self_explanation','ai_tutor','signal','self:'+secrets.token_urlsafe(16),code=candidate['code'] if candidate else None,metadata={'answer':answer,'misconception_description':candidate['reason'] if candidate else None,'ai_candidate':candidate})
                    MisconceptionEngine().update(db,user,cid,atom['id']);KnowledgeStateEngine().update(db,user,cid,atom['id'])
                result={'candidate':candidate,'affects_mastery':False,'note':'这只是可能误区的提示，不确认掌握，也不替代独立检测。'}
            else:self._json(HTTPStatus.NOT_FOUND,{'error':'学习接口不存在'});return
            self._json(HTTPStatus.OK,result);return
        assistant=re.fullmatch(r'/api/courses/([A-Za-z0-9_-]+)/assistant/chat',path)
        if assistant:
            payload=self._request_json(15000)
            factory=self.server.assistant_search_factory or self._search
            self._json(HTTPStatus.OK,self.server.course_tutor.chat(self._session(),assistant[1],payload,self._model(),factory));return
        if re.fullmatch(r'/api/courses/[A-Za-z0-9_-]+/(restore|copy)',path):
            self._manage_mutation();return
        payload = self._request_json(9_000_000 if path in ("/api/sources/upload","/api/courses/draft","/api/courses") else
                                     450_000 if path == "/api/sources/text" else 8192)
        if path=='/api/courses':
            payload={**payload,'title':payload.get('title',payload.get('name',''))}
            path='/api/courses/confirm' if payload.get('confirm') is True else '/api/courses/draft'
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
            clear_key=payload.get("clear_key",False)
            if type(clear_key) is not bool:raise ValueError("清除密钥选项无效")
            if old and old["encrypted_api_key"] and not api_key and not clear_key and fields["base_url"].rstrip("/")!=old["base_url"].rstrip("/"):
                raise ValueError("API 地址已改变，请重新输入该地址的密钥，或明确清除旧密钥")
            if not api_key and not clear_key and old and old["encrypted_api_key"] and not self._profile_key_usable(old):
                raise ValueError("旧密钥无法解密，请重新输入密钥后保存")
            ModelGateway({"base_url": fields["base_url"], "chat_model": fields["chat_model"], "api_key": api_key})
            encrypted = self.server.secrets.encrypt(api_key) if api_key else "" if clear_key else old["encrypted_api_key"] if old else ""
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
            provider = payload.get("provider", "brave")
            old = self._search_config(provider)
            api_url = WebSearch.endpoint(provider, payload.get("api_url", old["api_url"]))
            if not api_key and not clear and api_url != old["api_url"] and (old["encrypted_api_key"] or old["env_key"]):
                raise ValueError("更换 API 地址时请重新填写密钥，避免将旧密钥发送到新地址")
            encrypted = (self.server.secrets.encrypt(api_key) if api_key else
                         "" if clear else old["encrypted_api_key"] or self.server.secrets.encrypt(old["env_key"]))
            if not encrypted and not clear and not old["env_key"]:
                raise ValueError("请输入网页搜索密钥")
            self.server.storage.save_search_profile(self._session(), provider, api_url, encrypted)
            self._json(HTTPStatus.OK, self._models_public())
        elif path == "/api/courses/draft":
            title, goal = payload.get("title"), payload.get("goal", "")
            search_mode = payload.get("search_mode", "public")
            source_policy=payload.get('source_policy','balanced')
            learner_level=payload.get('learner_level','零基础')
            if not isinstance(source_policy,str) or source_policy not in POLICIES:raise ValueError('知识来源偏好无效')
            if not isinstance(learner_level,str) or not 1<=len(learner_level)<=200:raise ValueError('请填写当前水平，最多200字')
            if search_mode not in ("public", "brave", "tavily"):
                raise ValueError("请选择有效的资料检索方式")
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
                previous_mode = next((source.get("provider", "Brave").lower() for source in previous["sources"]
                                      if source.get("provider", "Brave") in WebSearch.PROVIDERS.values()), "public")
                if (not feedback.strip() and title.strip() == previous["title"] and
                        goal.strip() == previous["goal"] and search_mode == previous_mode):
                    raise ValueError("请填写想修改的学习方向")
            elif len(self.server.storage.drafts(self._session())) >= 20:
                raise ValueError("最多保留 20 份未确认审查稿")
            documents=self.server.storage.draft_documents(self._session(),draft_id) if previous else []
            uploads=payload.get('uploads')
            if uploads is not None:
                if not isinstance(uploads,list) or len(uploads)>3:raise ValueError('创建课程最多上传3份资料，总计6 MB')
                documents=[];total=0
                for upload in uploads:
                    if not isinstance(upload,dict) or not isinstance(upload.get('content_base64'),str):raise ValueError('上传格式无效')
                    try:data=base64.b64decode(upload['content_base64'],validate=True)
                    except (ValueError,binascii.Error) as exc:raise ValueError('上传编码无效') from exc
                    total+=len(data)
                    if total>6*1024*1024:raise ValueError('创建课程上传资料总计最多6 MB')
                    documents.append(UploadProvider().acquire(filename=upload.get('filename'),data=data).to_dict())
            if previous:
                source_policy=payload.get('source_policy',previous['source_policy'])
                learner_level=payload.get('learner_level',previous['learner_level'])
            if not documents:source_policy='balanced'
            model = self._model()
            planning_course=course_context(title.strip(),goal.strip(),learner_level,source_policy,
                previous['plan'] if previous else None,feedback.strip())
            selections={d['id']:[b['id'] for b in selected_blocks(d,8000)] for d in documents}
            discovery_plan=build_search_plan(model,planning_course,documents,selections,{'atoms':[],'edges':[]},[])
            queries=[q['query'] for q in discovery_plan['queries']]
            sources=[];search_report={}
            if queries:
                search=self._search(search_mode)
                sources=search.search(queries,topic=title.strip()) if search_mode=='public' else search.search(queries)
                search_report=search.report if search_mode=='public' else {}
            search_report={**search_report,'discovery_plan':discovery_plan}
            context={'source_policy':source_policy,'learner_level':learner_level,
                'documents':[{'title':d['title'],'blocks':selected_blocks(d,8000)} for d in documents]}
            from .learning.personal import PersonalKnowledgeProfileBuilder
            from .learning.canonical import normalized,names
            topic=normalized(title+' '+goal)
            relevant=[p for p in PersonalKnowledgeProfileBuilder(self.server.storage).profiles(self._session())['profiles'] if any(n and n in topic for n in names(p['name']))][:6]
            context['relevant_personal_knowledge']=[{'name':p['name'],'label':p['label'],'guidance':'历史基础仅作提示；大纲保持完整，不自动删章节'} for p in relevant]
            if payload.get('growth_goal_id') or payload.get('growth_task_id'):
                from .learning.growth import GrowthService
                context['growth_goal_context']=GrowthService(self.server.storage).course_context(self._session(),payload.get('growth_goal_id'),payload.get('growth_task_id'))
            plan=model.plan_course_review(title.strip(),goal.strip(),feedback.strip(),previous['plan'] if previous else None,sources,context)
            if source_policy=='user_material_first':
                headings=[]
                for doc in documents:
                    for block in doc['metadata']['blocks']:
                        if block['kind']=='heading' and block.get('level',1)<=2 and len(block['text'])>=2:
                            value=block['text'][:80]
                            if value not in headings:headings.append(value)
                if headings:
                    plan['sections']=[{'title':h,'objective':'按照上传资料理解本节概念、术语与重点，并补充必要前置与实例。'} for h in headings[:16]]
                    plan['material_structure_note']='沿用上传资料的标题顺序；最多16节，完整原文保存在课程资料中。'
            draft=self.server.storage.save_draft(self._session(),title.strip(),goal.strip(),feedback.strip(),plan,sources,draft_id,revision,search_report,
                source_policy=source_policy,learner_level=learner_level,search_mode=search_mode,documents=documents,
                course_info={k:v for k,v in payload.items() if k in ('description','cover','tags','level','status')} or None)
            self._json(HTTPStatus.OK, {"draft": draft})
        elif path == "/api/courses/confirm":
            draft_id, revision = payload.get("draft_id"), payload.get("revision")
            if (not isinstance(draft_id, str) or not isinstance(revision, int) or
                    isinstance(revision, bool)):
                raise ValueError("课程审查稿编号无效")
            course = self.server.storage.confirm_draft(self._session(), draft_id, revision)
            if not self.server.storage.discovery(self._session(),course['id']):
                self._start_discovery(course)
            self._json(HTTPStatus.OK, {"course_id": course["id"], "course": self._course_public(course["id"])})
        elif path in ("/api/sources/text", "/api/sources/upload", "/api/sources/url"):
            course = self._owned_course(payload.get("course_id"))
            if path == "/api/sources/text":
                source = DirectInputProvider().acquire(title=payload.get("title"),text=payload.get("text"))
            elif path == "/api/sources/upload":
                encoded = payload.get("content_base64")
                if not isinstance(encoded,str):
                    raise ValueError("文件内容格式无效")
                try:
                    data = base64.b64decode(encoded,validate=True)
                except (ValueError,binascii.Error) as exc:
                    raise ValueError("文件传输编码无效") from exc
                source = UploadProvider().acquire(filename=payload.get("filename"),data=data)
            else:
                mode = payload.get("search_mode", "direct")
                title = payload.get("title", "")
                if not isinstance(title,str) or len(title)>150:
                    raise ValueError("资料名称最多 150 字")
                if mode == "direct":
                    source = fetch_public_document(payload.get("url"),title)
                elif mode in ("public", "brave", "tavily"):
                    source = WebSearchProvider(self._search(mode),mode).acquire(url=payload.get("url"),title=title)
                else:
                    raise ValueError("网页获取方式无效")
            saved = self.server.storage.save_source(self._session(),course["id"],source)
            self._json(HTTPStatus.OK, {"source":saved})
        elif path == "/api/sources/search":
            course = self._owned_course(payload.get("course_id"))
            mode = payload.get("search_mode", "tavily")
            if mode not in ("public", "brave", "tavily"):
                raise ValueError("检索方式无效")
            query = payload.get("query")
            from .search_planning import normalize_queries
            if not isinstance(query,str) or len(query)>250 or not normalize_queries([query]):
                raise ValueError("请输入有效的资料检索词，最多250字")
            query=normalize_queries([query])[0]
            provider = WebSearchProvider(self._search(mode),mode)
            results = provider.search(query.strip())
            self._json(HTTPStatus.OK, {"results":results,"search_mode":mode,
                "note":"以下是索引标题与摘要；选择获取正文后，才进入资料理解与抽取流程"})
        elif path == "/api/sources/process":
            course = self._owned_course(payload.get("course_id"))
            source = self.server.storage.source(self._session(),course["id"],payload.get("source_id"))
            section = payload.get("section")
            if not isinstance(section,int) or isinstance(section,bool) or not 1 <= section <= len(course["sections"]):
                raise ValueError("请选择本课程的目标章节")
            selected = payload.get("block_ids")
            blocks = source["metadata"]["blocks"]
            if selected is not None:
                if not isinstance(selected,list) or not selected or any(not isinstance(i,str) for i in selected):
                    raise ValueError("请选择资料结构块")
                blocks = [b for b in blocks if b["id"] in selected]
                if len(blocks)!=len(set(selected)):
                    raise ValueError("资料结构块编号无效")
            if sum(len(b["text"]) for b in blocks)>24_000:
                raise ValueError("本次理解最多 2.4 万字；请按章节、页码或幻灯片选择需要处理的结构块，不会截断全文")
            batch=produce_source(self.server.storage,self._session(),course,self._model(),source,section,blocks)
            self._json(HTTPStatus.OK, {"batch":batch})
        elif path == "/api/sources/review":
            course = self._owned_course(payload.get("course_id"))
            batch = self.server.storage.review_batch(self._session(),course["id"],payload.get("batch_id"),
                payload.get("action"),payload.get("selected",[]),payload.get("feedback",""),payload.get("merge_choices"))
            self._json(HTTPStatus.OK, {"batch":batch,"knowledge":self.server.storage.knowledge_state(self._session(),course["id"])})
        elif path == '/api/discovery/start':
            course=self._owned_course(payload.get('course_id'))
            self._start_discovery(course)
            self._json(HTTPStatus.OK,{'discovery':self.server.storage.discovery(self._session(),course['id'])})
        elif path == '/api/courses/source-policy':
            course=self._owned_course(payload.get('course_id'))
            self.server.storage.policy(self._session(),course['id'],payload.get('source_policy'))
            self._json(HTTPStatus.OK,self._course_public(course['id']))
        elif path == '/api/conflicts/confirm':
            course=self._owned_course(payload.get('course_id'))
            conflicts=self.server.storage.confirm_conflict(self._session(),course['id'],payload.get('conflict_id'),payload.get('teaching_expression'))
            self._json(HTTPStatus.OK,{'conflicts':conflicts})
        elif path == "/api/knowledge/build":
            course = self._owned_course(payload.get("course_id"))
            existing=self.server.storage.graph(self._session(),course["id"])
            covered={a["section"] for a in (existing or {}).get("atoms",[]) if a.get("quality_status")!="deprecated"}
            if covered!=set(range(1,len(course["sections"])+1)):
                graph = self._model().build_knowledge_graph(course)
                self.server.storage.complete_index(self._session(), course["id"], graph,existing)
            from .learning.canonical import KnowledgeMappingEngine
            # The stored index is ready independently of optional semantic refinement.
            # Bound model work and keep it outside the request's course transaction.
            try:
                store=self.server.storage;user=self._session();cid=course['id'];model=self._model()
                slots=self.server.canonical_slots
                def refine():
                    try:KnowledgeMappingEngine(store).scan(user,cid,model)
                    except Exception as exc:LOGGER.warning('语义关联补充待重试：%s',type(exc).__name__)
                    finally:slots.release()
                if slots.acquire(blocking=False):threading.Thread(target=refine,daemon=True,name='canonical-refinement').start()
            except (ValueError,ModelUnavailable):pass
            self._json(HTTPStatus.OK, self._course_public(course["id"]))
        elif path == "/api/sections/read":
            course = self._owned_course(payload.get("course_id"))
            section = self._unlocked_section(course, payload.get("ordinal"))
            self._section_materials(course,section)
            if not section["lesson"]:
                raise ValueError("请先生成并阅读本节讲解")
            graph = self.server.storage.graph(self._session(), course["id"])
            if not graph:
                raise ValueError("请先生成课程知识地图")
            ids = [a["id"] for a in graph["atoms"] if a["section"] == section["ordinal"]]
            self.server.storage.learning_event(self._session(), course["id"], ids, "read")
            self._json(HTTPStatus.OK, self._course_public(course["id"], section["ordinal"]))
        elif path in ("/api/atoms/lesson", "/api/atoms/ask", "/api/atoms/quiz", "/api/atoms/read"):
            course = self._owned_course(payload.get("course_id"))
            atom_id = payload.get("atom_id")
            detail = self.server.storage.atom_detail(self._session(), course["id"], atom_id)
            atom = detail["atom"]
            section = course["sections"][atom["section"] - 1]
            self._section_materials(course,section)
            if path == "/api/atoms/lesson":
                mode = payload.get("mode", "quick")
                if mode not in ("quick", "deep"):
                    raise ValueError("请选择快速复习或深入理解")
                if mode not in detail["content"] or payload.get("regenerate") is True:
                    state = self.server.storage.knowledge_state(self._session(), course["id"])
                    context = {key: state[key] for key in ("atoms", "edges", "queue", "rule")}
                    content = self._model().teach_atom(course, atom, context, mode)
                    self.server.storage.save_atom_content(self._session(), course["id"], atom_id, mode, content,expected_revision=course["content_revision"],regenerate=payload.get("regenerate") is True)
            elif path == "/api/atoms/ask":
                question = payload.get("question")
                if not isinstance(question, str) or not 2 <= len(question.strip()) <= 500:
                    raise ValueError("请输入 2 至 500 字的问题")
                if not detail["content"] and not section["lesson"]:
                    raise ValueError("请先阅读章节讲解或原子讲解")
                content = detail["content"] or {"section": section["lesson"]}
                answer = self._model().answer_atom(course, atom, detail["turns"], content, question.strip())
                self.server.storage.atom_exchange(self._session(), course["id"], atom_id, question.strip(), answer)
            elif path == "/api/atoms/read":
                if not detail["content"] and not section["lesson"]:
                    raise ValueError("请先阅读章节讲解或原子讲解")
                self.server.storage.learning_event(self._session(), course["id"], [atom_id], "review")
            else:
                previous = detail["quizzes"]
                if not any(q["submitted_at"] is None for q in previous):
                    if not detail["content"] and not section["lesson"]:
                        raise ValueError("请先阅读章节或原子讲解；首次学习前可以使用基础摸底")
                    prompts = [q["prompt"] for test in previous for q in test["questions"]]
                    target_section = {**section, "lesson": "\n".join(detail["content"].values()) or section["lesson"]}
                    questions, answers = self._model().knowledge_quiz(course, target_section, [atom], prompts)
                    self.server.storage.create_knowledge_quiz(self._session(), course["id"], section["id"],
                                                              questions, answers, "atom", atom_id)
            self._json(HTTPStatus.OK, self.server.storage.atom_detail(self._session(), course["id"], atom_id))
        elif path == "/api/knowledge/diagnostic":
            course = self._owned_course(payload.get("course_id"))
            state = self.server.storage.knowledge_state(self._session(), course["id"])
            candidates = [a for a in state["atoms"] if a["section"] == 1]
            if not candidates:
                raise ValueError("请先生成课程知识地图")
            if not any(q["submitted_at"] is None for q in state["diagnostics"]):
                prompts = [q["prompt"] for quiz in state["diagnostics"] for q in quiz["questions"]]
                section = course["sections"][0]
                questions, answers = self._model().knowledge_quiz(course, section, candidates, prompts, diagnostic=True)
                self.server.storage.create_knowledge_quiz(self._session(), course["id"], section["id"],
                                                          questions, answers, "diagnostic")
            self._json(HTTPStatus.OK, self._course_public(course["id"]))
        elif path == "/api/sections/lesson":
            course = self._owned_course(payload.get("course_id"))
            section = self._unlocked_section(course, payload.get("ordinal"))
            self._section_materials(course,section)
            if not section["lesson"] or payload.get("regenerate") is True:
                state = self.server.storage.knowledge_state(self._session(), course["id"])
                section["knowledge_atoms"] = [a for a in state["atoms"] if a["section"] == section["ordinal"] and a.get('quality_status')!='deprecated']
                section["atom_evidence"] = [a for a in state["atoms"] if a["section"] <= section["ordinal"] and a.get('quality_status')!='deprecated']
                package,context = self.server.content_generator.lesson(self._session(),course,section,self._model(),
                    self.server.storage.mastery(self._session(),course['id']),self.server.storage.weak_points(self._session(),course['id']))
                self.server.storage.save_lesson(self._session(),course['id'],section['id'],package['content'],context,package['validation'],package,expected_revision=course['content_revision'],regenerate=payload.get('regenerate') is True)
            self._json(HTTPStatus.OK, self._course_public(course["id"], section["ordinal"]))
        elif path == "/api/sections/ask":
            course = self._owned_course(payload.get("course_id"))
            section = self._unlocked_section(course, payload.get("ordinal"))
            self._section_materials(course,section)
            question = payload.get("question")
            if not section["lesson"]:
                raise ValueError("请先生成本节讲解")
            if not isinstance(question, str) or not 2 <= len(question.strip()) <= 500:
                raise ValueError("请输入 2 至 500 字的问题")
            section["atom_evidence"] = [a for a in self.server.storage.knowledge_state(self._session(), course["id"])["atoms"]
                                        if a["section"] <= section["ordinal"]]
            turns = self.server.storage.tutor_turns(self._session(), course["id"], section["id"])
            reference=''
            reference_turn=payload.get('reference_turn')
            if reference_turn is not None:
                if (not isinstance(reference_turn,int) or isinstance(reference_turn,bool) or not 0<=reference_turn<len(turns)
                        or turns[reference_turn]['role']!='assistant'):
                    raise ValueError('引用的讲解不存在，请刷新后重试')
                reference=turns[reference_turn]['content'][:6000]
            package=self.server.content_generator.followup(self._session(),course,section,self._model(),turns,question.strip(),payload.get('feedback'),reference)
            self.server.storage.add_tutor_exchange(self._session(),course['id'],section['id'],question.strip(),package['content'],package)
            self._json(HTTPStatus.OK, self._course_public(course["id"], section["ordinal"]))
        elif path == "/api/sections/quiz":
            course = self._owned_course(payload.get("course_id"))
            section = self._unlocked_section(course, payload.get("ordinal"))
            self._section_materials(course,section)
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
            questions, answers = self._model().generate_quiz(course, section, prompts, weak_prompts,
                [a for a in self.server.storage.knowledge_state(self._session(), course["id"])["atoms"]
                 if a["section"] == section["ordinal"]])
            self.server.storage.create_quiz(self._session(), course["id"], section["id"], questions, answers)
            self._json(HTTPStatus.OK, self._course_public(course["id"], section["ordinal"]))
        elif path == "/api/quizzes/submit":
            course = self._owned_course(payload.get("course_id"))
            answers = payload.get("answers")
            if not isinstance(answers, list) or any(not isinstance(a, str) for a in answers):
                raise ValueError("请完成全部题目")
            result = self.server.storage.submit_quiz(self._session(), course["id"], payload.get("quiz_id"), answers,payload.get("confidence"),payload.get("hint_used"),payload.get("response_time_ms"))
            self._json(HTTPStatus.OK, {"result": result, **self._course_public(course["id"])})
        elif path == "/api/sections/advance":
            course = self._owned_course(payload.get("course_id"))
            from .learning.service import LearningLoopService
            if LearningLoopService(self.server.storage).snapshot(self._session(),course['id'])['returning_session']:raise ValueError('离开较久，请先完成回忆检测，或明确选择先回看当前小节。')
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
        except (BrokenPipeError, ConnectionResetError):
            # A closed browser cannot receive another error response.
            return
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
