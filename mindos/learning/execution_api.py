"""Small owned HTTP surface for explicitly started study sessions."""
import os,re
from urllib.parse import urlsplit,parse_qs
from .execution import StudySessionService
from .pace import PersonalPaceModel
from .execution_planner import PlanRealityAnalyzer

def dispatch(handler):
    parsed=urlsplit(handler.path);path=parsed.path;method=handler.command
    goal=re.fullmatch(r'/api/goals/([A-Za-z0-9_-]+)/execution',path)
    if not (path.startswith('/api/study/') or path=='/api/debug/learning/pace' or goal):return False
    user=handler._session();service=StudySessionService(handler.server.storage);result=None
    if method!='GET':handler._check_local_request()
    if path=='/api/debug/learning/pace':
        if os.getenv('MINDOS_DEBUG_LEARNING')!='1':handler._json(404,{'error':'接口不存在'});return True
        if method=='GET':result=PersonalPaceModel(handler.server.storage).profiles(user,True)
    elif goal and method=='GET':result=PlanRealityAnalyzer(handler.server.storage).analyze(user,goal[1])
    elif path=='/api/study/pace' and method=='GET':result=PersonalPaceModel(handler.server.storage).profiles(user)
    elif path=='/api/study/sessions/current' and method=='GET':result=service.current(user)
    elif path=='/api/study/sessions' and method=='GET':result=service.history(user,{k:v[0] for k,v in parse_qs(parsed.query).items()})
    elif path=='/api/study/sessions/start' and method=='POST':result=service.start(user,handler._request_json())
    else:
        m=re.fullmatch(r'/api/study/sessions/([A-Za-z0-9_-]+)(?:/(pause|resume|end|checkpoint))?',path)
        if m:
            sid,op=m.groups()
            if method=='POST' and op:result=service.action(user,sid,op,handler._request_json())
            elif method=='PATCH' and op is None:result=service.action(user,sid,'adjust',handler._request_json())
            elif method=='DELETE' and op is None:result=service.action(user,sid,'delete',handler._request_json())
    handler._json(200 if result is not None else 404,result if result is not None else {'error':'学习执行接口不存在'})
    return True
