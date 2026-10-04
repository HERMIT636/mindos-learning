"""Disposable mission UI fixture; synthetic model, real browser/HTTP/file handling."""
import json,sys,time,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from test_prototype import PrototypeTests
from mindos.server import MindOSHandler
from mindos.learning.growth import GrowthService
from mission_fixture import protected
captured=[]
from mission_fixture import MissionModel
original=MissionModel.mission_tutor_json
def record(self,payload,repair_reason=''):
 c=payload['context']['practice_context'];captured.append({'mission_id':c['current_mission']['id'],'task_id':c['current_mission_task']['id'],'mode':c['mode'],'artifact_ids':[a['artifact_id'] for a in c['artifacts']],'texts':[a['text'] for a in c['artifacts']],'recent_runs':c['latest_experiment_summary'],'quality_guidance':'quality_guidance' in payload});return original(self,payload,repair_reason)
MissionModel.mission_tutor_json=record
if __name__=='__main__':
 PrototypeTests.setUpClass();t=PrototypeTests();t.setUp()
 try:
  t.configure();store=t.server.storage;user=t.session_id();d=store.save_draft(user,'CUDA实践课程','理解独立实验与性能观测','',{'sections':[{'title':'实验与比较','objective':'理解可靠测量、参数与实际指标'}]},[]);c=store.confirm_draft(user,d['id'],1);cid=c['id'];store.save_graph(user,cid,{'atoms':[{'id':'measurement','title':'性能测量','section':1,'summary':'控制环境与输入，用重复观测比较延迟，不把数字差异等同于因果。','why':'支持可靠实验','type':'mechanism','depth':2}],'edges':[]});store.save_lesson(user,cid,c['sections'][0]['id'],'本节学习可靠测量与性能比较，缓存只是可能的解释，需要测量支持。')
  g=GrowthService(store).create(user,{'title':'完成CUDA实践','description':'独立开展优化实验，交付可复现结果和局限说明','goal_type':'competition','target_level':'practical_understanding','priority':1})
  original_get=MindOSHandler._get
  def fixture_get(h):
   if h.path=='/api/p9-fixture':
    with store.connect() as db:counts={table:db.execute('SELECT count(*) FROM '+table).fetchone()[0] for table in ['learning_missions','mission_tasks','mission_artifacts','mission_experiment_runs','mission_reflections','project_evidence_candidates','knowledge_resources','study_sessions','authentic_tasks']}
    h._json(200,{'digest':hashlib.sha256(json.dumps(protected(store),sort_keys=True).encode()).hexdigest(),'counts':counts,'calls':captured,'course_id':cid,'goal_id':g['id']});return
   return original_get(h)
  MindOSHandler._get=fixture_get;print(json.dumps({'url':t.url,'cookie':user}),flush=True);time.sleep(600)
 except KeyboardInterrupt:pass
 finally:PrototypeTests.tearDownClass()
