"""Owned tutor API. context_id selects a course; all facts are rebuilt server-side."""
import os,re
from urllib.parse import urlsplit,parse_qs
from .service import TutorService,_LOCKS
from .storage import TutorMemoryStore
from .observations import TutorObservationService

def dispatch(handler):
    parsed=urlsplit(handler.path);path=parsed.path;method=handler.command
    if not path.startswith('/api/tutor/'):return False
    user=handler._session();store=handler.server.storage;result=None;query=parse_qs(parsed.query)
    if method!='GET':handler._check_local_request()
    def model():
        from ..model import ModelUnavailable
        try:return handler._model()
        except (ValueError,ModelUnavailable):return None
    cid=query.get('context_id',query.get('course_id',['']))[0]
    if path=='/api/tutor/chat' and method=='POST':
        result=TutorService(store).chat(user,handler._request_json(15000),model(),handler.server.assistant_search_factory or handler._search)
    elif path=='/api/tutor/context' and method=='GET':
        course=store._knowledge_course(user,cid);result={'context_id':course['id'],'course_title':course['title'],'boundary':'仅为课程选择编号；知识状态由服务器每次重新读取。'}
    elif path=='/api/tutor/conversations' and method=='GET':
        if cid:
            before=query.get('before',[None])[0]
            if before is not None and not before.isdigit():raise ValueError('历史页码无效')
            result=TutorMemoryStore(store).history(user,cid,int(before) if before else None)
        else:
            with store.connect() as db:result={'conversations':[dict(r) for r in db.execute('SELECT t.id,t.course_id,t.goal_id,t.created_at,t.updated_at FROM tutor_conversations t JOIN courses c ON c.id=t.course_id WHERE t.user_id=? AND c.session_id=? AND c.deleted_at IS NULL ORDER BY t.updated_at DESC LIMIT 40',(user,user))]}
    elif path=='/api/tutor/observations' and method=='GET':result=TutorObservationService(store).list(user,cid)
    elif path=='/api/tutor/memory' and method=='GET':
        if os.getenv('MINDOS_DEBUG_LEARNING')!='1':handler._json(404,{'error':'接口不存在'});return True
        store._knowledge_course(user,cid)
        with store.connect() as db:result={'memories':[dict(r) for r in db.execute('SELECT id,memory_type,content,quote,created_at FROM tutor_memories WHERE user_id=? AND course_id=? AND active=1 ORDER BY id DESC LIMIT 40',(user,cid))]}
    else:
        m=re.fullmatch(r'/api/tutor/observations/([A-Za-z0-9_-]+)/(verify|dismiss)',path)
        if m and method=='POST':
            payload=handler._request_json()
            if payload:raise ValueError('检测结果只能由原有独立答题流程产生')
            service=TutorObservationService(store);result=service.verify(user,m[1],model()) if m[2]=='verify' else service.dismiss(user,m[1])
        elif path=='/api/tutor/conversations' and method=='DELETE':
            payload=handler._request_json();cid=payload.get('context_id');store._knowledge_course(user,cid)
            if set(payload)!={'context_id'}:raise ValueError('请提供课程编号')
            with _LOCKS[hash((user,cid))%len(_LOCKS)],store.connect() as db:
                db.execute('BEGIN IMMEDIATE');store._manage_owned(db,user,cid)
                for table in ['tutor_conversations','tutor_memories','tutor_observations']:db.execute('DELETE FROM '+table+' WHERE user_id=? AND course_id=?',(user,cid))
            result={'deleted':True,'note':'只清除导师对话、教学偏好和候选观察，保留真实学习证据。'}
    handler._json(200 if result is not None else 404,result if result is not None else {'error':'导师接口不存在'})
    return True
