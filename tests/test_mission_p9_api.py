import base64,json,unittest,urllib.request,urllib.error
from resource_fixture import make_course
from mindos.mission.service import MissionService
from mindos.mission.planner import MissionPlanner
from mindos.mission.artifacts import ArtifactService
from mission_fixture import MissionModel,definition,protected
class MissionAPITests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  from test_prototype import PrototypeTests
  cls.fixture=PrototypeTests;cls.fixture.setUpClass();t=cls.fixture();t.setUp();t.configure();cls.profile=t.server.storage.selected_model_profile(t.session_id())
 @classmethod
 def tearDownClass(cls):cls.fixture.tearDownClass()
 def setUp(self):
  self.t=self.fixture();self.t.setUp();self.t.call('/api/models/select',{'id':self.profile});self.user=self.t.session_id();self.store=self.t.server.storage;self.c=make_course(self.store,self.user);self.s=MissionService(self.store);self.p=MissionPlanner(self.store);self.m=self.s.create(self.user,{'title':'实践项目','confirmed':True});self.mid=self.m['id'];self.path='/api/missions/'+self.mid;self.model=MissionModel(definition(self.c['id'],'a0'))
 def request(self,path,method='GET',body=None,other=False,origin=None,raw=False):
  data=json.dumps(body).encode() if body is not None else None;req=urllib.request.Request(self.t.url+path,data=data,method=method,headers={**({'Content-Type':'application/json'} if data else {}),**({'Origin':origin} if origin else {})});client=urllib.request.build_opener() if other else self.t.client
  try:
   with client.open(req,timeout=20) as r:return r.status,r.read() if raw else json.loads(r.read())
  except urllib.error.HTTPError as e:return e.code,json.loads(e.read())
 def confirm(self):m=self.p.generate(self.user,self.mid,self.model);return self.p.confirm(self.user,self.mid,{'confirm':True,'draft_version':m['draft_version']})
 def test_create_api(self):status,r=self.request('/api/missions','POST',{'title':'新实践','confirmed':True});self.assertEqual(status,200);self.assertEqual(r['mission']['status'],'draft')
 def test_create_requires_confirm(self):self.assertEqual(self.request('/api/missions','POST',{'title':'新实践'})[0],400)
 def test_foreign_detail_denied(self):self.assertEqual(self.request(self.path,other=True)[0],400)
 def test_foreign_mutation_denied(self):self.assertEqual(self.request(self.path,'PATCH',{'title':'偷改'},other=True)[0],400)
 def test_foreign_origin_denied(self):self.assertEqual(self.request(self.path,'PATCH',{'title':'偷改'},origin='https://attacker.example')[0],400)
 def test_list_only_owned(self):status,r=self.request('/api/missions',other=True);self.assertEqual(status,200);self.assertEqual(r['missions'],[])
 def test_metadata_update(self):status,r=self.request(self.path,'PATCH',{'title':'新版','outcome':'failed'});self.assertEqual(status,200);self.assertEqual(r['mission']['title'],'新版')
 def test_status_no_mastery(self):status,r=self.request(self.path+'/status');self.assertEqual(status,200);self.assertTrue(r['completion_gates']);self.assertNotIn('mastery',r['mission'])
 def test_unknown_state_fields_rejected(self):self.assertEqual(self.request(self.path,'PATCH',{'knowledge_state':1})[0],400)
 def test_generate_via_gateway_draft_only(self):status,r=self.request(self.path+'/plan/generate','POST',{});self.assertEqual(status,200);self.assertEqual(r['mission']['draft']['source'],'model');self.assertEqual(r['mission']['tasks'],[])
 def test_plan_confirm_api(self):r=self.request(self.path+'/plan/generate','POST',{})[1];status,r=self.request(self.path+'/plan/confirm','POST',{'confirm':True,'draft_version':r['mission']['draft_version']});self.assertEqual(status,200);self.assertEqual(len(r['mission']['tasks']),3)
 def test_replan_stale_confirm_denied(self):r=self.request(self.path+'/plan/generate','POST',{})[1];self.request(self.path+'/replan','POST',{});self.assertEqual(self.request(self.path+'/plan/confirm','POST',{'confirm':True,'draft_version':r['mission']['draft_version']})[0],400)
 def test_task_start_api(self):m=self.confirm();status,r=self.request(self.path+'/tasks/'+m['tasks'][0]['id']+'/start','POST',{});self.assertEqual(status,200);self.assertEqual(r['mission']['tasks'][0]['status'],'active')
 def test_blocked_start_api(self):m=self.confirm();self.assertEqual(self.request(self.path+'/tasks/'+m['tasks'][1]['id']+'/start','POST',{})[0],400)
 def test_study_uses_existing_session_api(self):m=self.confirm();tid=m['tasks'][0]['id'];self.s.task_action(self.user,self.mid,tid,'start');status,r=self.request(self.path+'/tasks/'+tid+'/study/start','POST',{'planned_minutes':20});self.assertEqual(status,200);self.assertEqual(r['session']['activity_type'],'goal_task')
 def test_upload_file_owned(self):
  before=protected(self.store);status,r=self.request(self.path+'/artifacts/upload','POST',{'filename':'measure.csv','artifact_type':'benchmark','content_base64':base64.b64encode(b'tile,ms\n32,1.3').decode()});self.assertEqual(status,200);status,data=self.request(r['artifact']['file_url'],raw=True);self.assertEqual(status,200);self.assertEqual(data,b'tile,ms\n32,1.3');self.assertEqual(protected(self.store),before)
 def test_foreign_file_denied(self):a=ArtifactService(self.store).upload(self.user,self.mid,{'filename':'x.py','artifact_type':'code'},b'print(1)');self.assertEqual(self.request(a['file_url'],other=True)[0],400)
 def test_bad_base64_rejected(self):self.assertEqual(self.request(self.path+'/artifacts/upload','POST',{'filename':'x.txt','content_base64':'???'})[0],400)
 def test_upload_does_not_accept_mastery(self):self.assertEqual(self.request(self.path+'/artifacts/upload','POST',{'filename':'x.txt','content_base64':'eA==','mastery':1})[0],400)
 def test_preview_text_safe(self):a=ArtifactService(self.store).upload(self.user,self.mid,{'filename':'x.js','artifact_type':'code'},b'<script>window.attack=true</script>');status,r=self.request(self.path+'/artifacts/'+a['id']+'/preview');self.assertEqual(status,200);self.assertIn('<script>',r['text'])
 def test_reflection_confirmation_api(self):self.assertEqual(self.request(self.path+'/reflections','POST',{'content':'真实复盘'})[0],400)
 def test_save_reflection_api(self):status,r=self.request(self.path+'/reflections','POST',{'content':'真实复盘','confirmed':True});self.assertEqual(status,200);self.assertEqual(r['mission']['reflections'][0]['content'],'真实复盘')
 def test_required_skip_not_mission_complete(self):m=self.confirm();self.request(self.path+'/tasks/'+m['tasks'][0]['id']+'/skip','POST',{});self.assertEqual(self.request(self.path,'PATCH',{'status':'completed'})[0],400)
 def test_tutor_api_original_quality(self):m=self.confirm();a=ArtifactService(self.store).upload(self.user,self.mid,{'filename':'baseline.csv','task_id':m['tasks'][0]['id'],'artifact_type':'benchmark'},b'tile,ms\n32,1.3');status,r=self.request(self.path+'/tutor/chat','POST',{'task_id':m['tasks'][0]['id'],'message':'解释这份实验记录','request_id':'api-p9-question','focused_artifact_id':a['id'],'artifact_grounded':True});self.assertEqual(status,200);self.assertTrue(r['saved']);self.assertLessEqual(r['attempts'],2);self.assertEqual(r['artifact_citations'][0]['artifact_id'],a['id'])
 def test_tutor_foreign_task_api(self):self.assertEqual(self.request(self.path+'/tutor/chat','POST',{'task_id':'foreign','message':'解释','request_id':'bad-p9-question'})[0],400)
 def test_unknown_route_404(self):self.assertEqual(self.request(self.path+'/invented')[0],404)
 def test_p8_material_delete_guard_preserves_mission_reference(self):
  from mindos.resources.service import ResourceService
  m=self.confirm();r=ResourceService(self.store).create(self.user,'text','资料',{'text':'背景'});self.s.edit_task(self.user,self.mid,m['tasks'][0]['id'],{'resource_ids':[r['id']]});self.assertEqual(self.request('/api/resources/'+r['id'],'DELETE',{'confirm':True})[0],400);self.s.edit_task(self.user,self.mid,m['tasks'][0]['id'],{'resource_ids':[]});self.assertEqual(self.request('/api/resources/'+r['id'],'DELETE',{'confirm':True})[0],200)
 def test_api_identifier_type_rejected(self):self.assertEqual(self.request(self.path,'PATCH',{'goal_id':{}})[0],400)
