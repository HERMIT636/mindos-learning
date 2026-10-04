"""Disposable P8 material browser fixture; actual HTTP and parsers, synthetic model."""
import base64,hashlib,json,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from test_prototype import PrototypeTests
from mindos.server import MindOSHandler
from mindos.resources.service import ResourceService
from resource_fixture import PAYLOADS,png,pdf,ResourceModel
from mindos.universe.universe_graph import star_id
captured=[];original=ResourceModel.resource_tutor_json
def record(self,payload,repair_reason=''):
 rc=payload['context']['resource_context'];captured.append({'course':payload['context']['course']['id'],'atom':payload['context']['current_context']['knowledge_atom_id'],'focus':rc['focused_resource_id'],'resource_ids':[r['resource_id'] for r in rc['resources']],'texts':[r['text'] for r in rc['resources']],'mode':rc['mode']});return original(self,payload,repair_reason)
ResourceModel.resource_tutor_json=record
if __name__=='__main__':
 PrototypeTests.setUpClass();t=PrototypeTests();t.setUp()
 try:
  t.configure();store=t.server.storage;owner=t.session_id();d=store.save_draft(owner,'Transformer多模态课程','理解匹配的直觉与应用','',{'sections':[{'title':'Attention机制','objective':'理解QKV职责与匹配原因'}]},[]);c=store.confirm_draft(owner,d['id'],1);cid=c['id'];store.save_graph(owner,cid,{'atoms':[{'id':'qkv','section':1,'title':'QKV','summary':'查询、键、值分别承担需求、匹配和内容角色。','why':'帮助理解匹配与汇总','type':'mechanism','depth':2},{'id':'attention','section':1,'title':'Attention','summary':'匹配相关内容再加权汇总。','why':'理解信息选择','type':'mechanism','depth':2}],'edges':[{'from':'qkv','to':'attention','type':'prerequisite'}]});store.save_lesson(owner,cid,c['sections'][0]['id'],'从图书馆检索需求与书籍标签理解QKV职责。');s=ResourceService(store);ids={}
  for kind in ['formula','diagram','code','practice']:
   r=s.create(owner,kind,{'formula':'Attention缩放公式','diagram':'QKV职责图','code':'匹配示例代码','practice':'独立解释任务'}[kind],PAYLOADS[kind]);s.link(owner,cid,'qkv',r['id']);ids[kind]=r['id']
  get=MindOSHandler._get
  def fixture_get(h):
   if h.path=='/api/p8-fixture':
    with store.connect() as db:
     protected={table:[tuple(r) for r in db.execute('SELECT * FROM '+table)] for table in ['knowledge_states','learning_evidence','personal_knowledge_profiles','learning_events','course_graphs']};sessions=db.execute('SELECT count(*) FROM study_sessions').fetchone()[0];tasks=db.execute('SELECT count(*) FROM authentic_tasks').fetchone()[0]
    h._json(200,{'digest':hashlib.sha256(json.dumps(protected,sort_keys=True).encode()).hexdigest(),'calls':captured,'course_id':cid,'star_id':star_id(cid,'qkv'),'resources':ids,'image_base64':base64.b64encode(png()).decode(),'pdf_base64':base64.b64encode(pdf()).decode(),'sessions':sessions,'tasks':tasks});return
   return get(h)
  MindOSHandler._get=fixture_get;print(json.dumps({'url':t.url,'cookie':owner}),flush=True);time.sleep(600)
 except KeyboardInterrupt:pass
 finally:PrototypeTests.tearDownClass()
