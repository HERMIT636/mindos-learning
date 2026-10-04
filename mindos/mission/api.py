"""Local mission API boundary. All referenced entities are checked server-side."""
import base64,binascii,re
from urllib.parse import urlsplit,parse_qs
from .service import MissionService
from .planner import MissionPlanner
from .artifacts import ArtifactService
from .evidence import ProjectEvidenceBridge
from .tutor import MissionTutorService
from .protocol import POLICY,fields

def dispatch(h):
 parsed=urlsplit(h.path);path=parsed.path
 if not path.startswith('/api/missions'):
  # Integration guard: P8 supporting material references must remain owned and resolvable.
  if h.command=='DELETE' and (resource:=re.fullmatch(r'/api/resources/([A-Za-z0-9_-]+)',path)):
   with h.server.storage.connect() as db:
    for row in db.execute('SELECT t.metadata_json FROM mission_tasks t JOIN learning_missions m ON m.id=t.mission_id WHERE m.user_id=?',(h._session(),)):
     import json
     if resource[1] in json.loads(row[0]).get('resource_ids',[]):raise ValueError('这份学习资料仍被实践任务引用，请先在任务设置中解除关联')
  return False
 user=h._session();store=h.server.storage;svc=MissionService(store);method=h.command
 if method!='GET':h._check_local_request()
 def model():
  try:return h._model()
  except ValueError:return None
 def body():return h._request_json(80000)
 if path=='/api/missions' and method=='GET':result=svc.list(user)
 elif path=='/api/missions' and method=='POST':result={'mission':svc.create(user,body())}
 elif path=='/api/missions/recommendations' and method=='GET':
  q=parse_qs(parsed.query)
  if set(q)-{'goal_id'} or any(len(v)!=1 for v in q.values()):raise ValueError('实践建议筛选无效')
  result=svc.recommendations(user,q.get('goal_id',[None])[0])
 elif m:=re.fullmatch(r'/api/missions/([A-Za-z0-9_-]+)(?:/(.*))?',path):
  mid,op=m.groups();art=ArtifactService(store);svc.get(user,mid,False)
  if not op and method=='GET':result={'mission':svc.get(user,mid)}
  elif not op and method in {'PATCH','PUT'}:result={'mission':svc.update(user,mid,body())}
  elif op=='status' and method=='GET':
   mission=svc.get(user,mid)
   with store.connect() as db:completion=svc._completion(db,user,mid)
   result={'mission':mission,'completion_gates':completion,'goal_completion':mission.get('goal',{}).get('status') if mission.get('goal') else None,'boundary':mission['boundary']}
  elif op in {'plan/generate','replan'} and method=='POST':result={'mission':MissionPlanner(store).generate(user,mid,model(),body(),op=='replan')}
  elif op=='plan/confirm' and method=='POST':result={'mission':MissionPlanner(store).confirm(user,mid,body())}
  elif m2:=re.fullmatch(r'tasks/([A-Za-z0-9_-]+)(?:/(start|complete|skip|resume|lock|runs|compare|study/start))?',op or ''):
   tid,action=m2.groups()
   if action in {'start','complete','skip','resume','lock'} and method=='POST':result={'mission':svc.task_action(user,mid,tid,action,body())}
   elif action=='runs' and method=='POST':result={'mission':svc.run(user,mid,tid,body())}
   elif action=='compare' and method=='POST':result=svc.compare(user,mid,tid,body())
   elif action=='study/start' and method=='POST':result=svc.start_session(user,mid,tid,body())
   elif not action and method=='PATCH':result={'mission':svc.edit_task(user,mid,tid,body())}
   else:h._json(405,{'error':'任务操作不支持此请求'});return True
  elif m2:=re.fullmatch(r'milestones/([A-Za-z0-9_-]+)/lock',op or ''):
   if method!='POST':h._json(405,{'error':'里程碑操作不支持此请求'});return True
   result={'mission':svc.lock_milestone(user,mid,m2[1],body())}
  elif op=='artifacts' and method=='GET':result=art.list(user,mid)
  elif op=='artifacts/upload' and method=='POST':
   p=h._request_json(POLICY['uploads']['max_bytes']*4//3+10000)
   fields(p,{'filename','title','artifact_type','task_id','experiment_id','run_id','parent_artifact_id','caption','repository_url','content_base64'})
   try:data=base64.b64decode(p.pop('content_base64',''),validate=True)
   except (ValueError,binascii.Error):raise ValueError('上传编码无效') from None
   result={'artifact':art.upload(user,mid,p,data)}
  elif m2:=re.fullmatch(r'artifacts/([A-Za-z0-9_-]+)(?:/(file|preview|promote))?',op or ''):
   aid,action=m2.groups()
   if action=='file' and method=='GET':p,mime=art.file(user,mid,aid);h._send(200,p.read_bytes(),mime);return True
   elif action=='preview' and method in {'GET','POST'}:result=art.preview(user,mid,aid,body() if method=='POST' else {})
   elif action=='promote' and method=='POST':result=art.promote(user,mid,aid,body())
   elif not action and method=='GET':result={'artifact':art.get(user,mid,aid)}
   elif not action and method=='DELETE':result=art.delete(user,mid,aid,body())
   else:h._json(405,{'error':'产出操作不支持此请求'});return True
  elif op=='reflections' and method=='POST':result={'mission':svc.reflection(user,mid,body())}
  elif op=='evidence/analyze' and method=='POST':result={'mission':ProjectEvidenceBridge(store).analyze(user,mid,body(),model())}
  elif m2:=re.fullmatch(r'evidence/([A-Za-z0-9_-]+)(?:/(verify))?',op or ''):
   if method=='POST' and m2[2]=='verify':result=ProjectEvidenceBridge(store).verify(user,mid,m2[1],body(),model())
   elif method=='GET' and not m2[2]:result=ProjectEvidenceBridge(store).status(user,mid,m2[1])
   else:h._json(405,{'error':'独立验证操作不支持此请求'});return True
  elif op=='tutor/chat' and method=='POST':result=MissionTutorService(store).chat(user,mid,body(),model(),h.server.assistant_search_factory or h._search)
  else:h._json(404,{'error':'实践入口不存在'});return True
 else:h._json(404,{'error':'实践入口不存在'});return True
 h._json(200,result);return True
