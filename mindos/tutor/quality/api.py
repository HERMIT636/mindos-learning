"""Boundary hook; public P6 contracts and all frozen P6 algorithms remain unchanged."""
import os
from urllib.parse import urlsplit,parse_qs
from .integration import QualityTutorService
from ..service import _LOCKS

def dispatch(handler):
    path=urlsplit(handler.path).path;method=handler.command
    if path=='/api/tutor/quality-debug' and method=='GET':
        if os.getenv('MINDOS_DEBUG_LEARNING')!='1':
            handler._json(404,{'error':'接口不存在'});return True
        cid=parse_qs(urlsplit(handler.path).query).get('context_id',[''])[0]
        handler._json(200,QualityTutorService(handler.server.storage).debug(handler._session(),cid));return True
    if path not in {'/api/tutor/chat','/api/tutor/conversations'} or method not in {'POST','DELETE'}:return False
    if not ((path.endswith('/chat') and method=='POST') or (path.endswith('/conversations') and method=='DELETE')):return False
    handler._check_local_request();user=handler._session();store=handler.server.storage
    payload=handler._request_json(15000)
    if not isinstance(payload,dict):raise ValueError('导师请求字段无效')
    if method=='POST':
        from ...model import ModelUnavailable
        try:model=handler._model()
        except (ValueError,ModelUnavailable):model=None
        result=QualityTutorService(store).chat(user,payload,model,handler.server.assistant_search_factory or handler._search)
    else:
        cid=payload.get('context_id');store._knowledge_course(user,cid)
        if set(payload)!={'context_id'}:raise ValueError('请提供课程编号')
        with _LOCKS[hash((user,cid))%len(_LOCKS)],store.connect() as db:
            db.execute('BEGIN IMMEDIATE');store._manage_owned(db,user,cid)
            for table in ['tutor_response_meta','tutor_conversations','tutor_memories','tutor_observations']:
                db.execute('DELETE FROM '+table+' WHERE user_id=? AND course_id=?',(user,cid))
        result={'deleted':True,'note':'只清除导师对话、教学偏好、候选观察和回答质量记录，保留真实学习证据。'}
    handler._json(200,result);return True
