"""HTTP adapter kept separate from the classroom and evidence routes."""
import os,re
from urllib.parse import urlsplit,parse_qs
from .growth import GrowthService

def dispatch(handler):
    parsed=urlsplit(handler.path);path=parsed.path;method=handler.command
    debug=path.startswith('/api/debug/learning/growth/')
    if debug:
        if os.getenv('MINDOS_DEBUG_LEARNING')!='1':handler._json(404,{'error':'接口不存在'});return True
        path=path.replace('/api/debug/learning/growth/','/api/goals/')
    if not (path=='/api/goals' or path.startswith('/api/goals/') or path=='/api/growth/today'):return False
    service=GrowthService(handler.server.storage);user=handler._session()
    if method!='GET':handler._check_local_request()
    def model():
        from ..model import ModelUnavailable
        try:return handler._model()
        except (ValueError,ModelUnavailable):return None
    result=None
    if path=='/api/growth/today' and method=='GET':result=service.dashboard(user)
    elif path=='/api/goals':
        if method=='GET':result=service.goals(user)
        elif method=='POST':result={'goal':service.create(user,handler._request_json())}
    else:
        match=re.fullmatch(r'/api/goals/([A-Za-z0-9_-]+)(?:/(.*))?',path)
        if match:
            gid,op=match.groups()
            if method=='GET':
                if op is None:result={'goal':service.goal(user,gid)}
                elif op=='capabilities':result={'goal':service.goal(user,gid),'mappings':service.mappings(user,gid,debug)}
                elif op=='gaps':result=service.gaps(user,gid,debug)
                elif op=='roadmap':
                    version=parse_qs(parsed.query).get('version',[None])[0]
                    if version is not None and not version.isdigit():raise ValueError('路线版本无效')
                    result=service.roadmap(user,gid,int(version) if version else None)
                elif op=='status':result={'goal':service.goal(user,gid),'completion':service.gaps(user,gid)['completion']}
            elif method in {'PATCH','PUT'} and op is None:result={'goal':service.update(user,gid,handler._request_json())}
            elif method=='DELETE' and op is None:result=service.delete(user,gid)
            elif method=='POST':
                payload=handler._request_json()
                if op=='capabilities/scan':
                    if payload:raise ValueError('知识关联检查不接受客户端评分')
                    result=service.refresh_mappings(user,gid,model())
                elif op=='analyze':result=service.analyze(user,gid,model(),payload)
                elif op in {'roadmap/generate','replan'}:
                    if payload:raise ValueError('路线状态与调整原因由服务器确定')
                    result=service.generate(user,gid,model())
                elif op=='evaluate':
                    if payload:raise ValueError('能力结果由现有学习模块提供')
                    result=service.evaluate(user,gid)
                elif re.fullmatch(r'mappings/[A-Za-z0-9_-]+/(verify|reject)',op or ''):
                    if payload:raise ValueError('知识关联操作不接受客户端评分')
                    _,mid,action=op.split('/');result=service.review_mapping(user,gid,mid,action=='verify')
                elif re.fullmatch(r'tasks/[A-Za-z0-9_-]+/(start|skip|pause|resume|lock|pin|artifact|link-course)',op or ''):
                    _,tid,action=op.split('/')
                    if action=='link-course':
                        if set(payload)!={'course_id'}:raise ValueError('请提供用户确认创建的课程编号')
                        result=service.link_course(user,gid,tid,payload['course_id'])
                    elif action=='artifact':
                        if set(payload)!={'authentic_task_id'}:raise ValueError('请提供本次开放任务编号')
                        result=service.attach_authentic(user,gid,tid,payload['authentic_task_id'])
                    else:
                        if action not in {'lock','pin'} and payload:raise ValueError('任务操作不接受能力状态')
                        result=service.task_action(user,gid,tid,action,payload)
    handler._json(200 if result is not None else 404,result if result is not None else {'error':'成长路线接口不存在'})
    return True
