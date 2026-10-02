import unittest,json,os,urllib.request,urllib.error
from unittest.mock import patch
from mindos.server import MindOSHandler
from personal_fixture import course
from growth_fixture import GrowthModel

class ExecutionAPITests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  from test_prototype import PrototypeTests
  cls.fixture=PrototypeTests;cls.fixture.setUpClass()
 @classmethod
 def tearDownClass(cls):cls.fixture.tearDownClass()
 def setUp(self):
  self.client=self.fixture();self.client.setUp();self.client.configure();self.user=self.client.session_id();self.store=self.fixture.server.storage;self.c=course(self.store,user=self.user);self.model=GrowthModel();p=patch.object(MindOSHandler,'_model',return_value=self.model);p.start();self.addCleanup(p.stop)
 def request(self,path,payload=None,method=None,client=None,headers=None):
  req=urllib.request.Request(self.fixture.url+path,data=json.dumps(payload).encode() if payload is not None else None,headers=headers or {'Content-Type':'application/json'},method=method)
  try:
   with (client or self.client.client).open(req) as r:return r.status,json.loads(r.read())
  except urllib.error.HTTPError as e:return e.code,json.loads(e.read())
 def start(self):
  status,r=self.request('/api/study/sessions/start',{'course_id':self.c['id']});self.assertEqual(status,200);return r['session']['id']
 def test_http_lifecycle_restore_adjust_delete(self):
  self.assertIsNone(self.request('/api/study/sessions/current')[1]['session']);sid=self.start();base='/api/study/sessions/'+sid
  self.assertEqual(self.request('/api/study/sessions/current')[1]['session']['id'],sid);self.assertEqual(self.request(base+'/pause',{})[1]['session']['status'],'paused');self.assertEqual(self.request(base+'/resume',{})[1]['session']['status'],'active');self.assertEqual(self.request(base+'/checkpoint',{})[0],200);self.assertEqual(self.request(base+'/end',{'completion':'done','adjusted_active_minutes':28})[1]['session']['status'],'completed');self.assertEqual(self.request(base,{'adjusted_active_minutes':20},'PATCH')[1]['session']['active_seconds'],1200);self.assertEqual(self.request('/api/study/sessions?course_id='+self.c['id'])[1]['sessions'][0]['id'],sid);self.assertTrue(self.request(base,{},'DELETE')[1]['deleted'])
 def test_http_ownership_and_debug_redaction(self):
  sid=self.start();other=urllib.request.build_opener();self.assertNotEqual(self.request('/api/study/sessions/'+sid+'/pause',{},client=other)[0],200);self.assertIsNone(self.request('/api/study/sessions/current',client=other)[1]['session']);r=self.request('/api/study/pace')[1];self.assertNotIn('profiles',r);self.assertNotIn('median_ratio',str(r));self.assertNotIn('user_id',self.request('/api/study/sessions/current')[1]['session'])
  with patch.dict(os.environ,{'MINDOS_DEBUG_LEARNING':'0'}):self.assertEqual(self.request('/api/debug/learning/pace')[0],404)
  with patch.dict(os.environ,{'MINDOS_DEBUG_LEARNING':'1'}):self.assertIn('profiles',self.request('/api/debug/learning/pace')[1])
 def test_http_origin_and_invalid_fields(self):
  self.assertEqual(self.request('/api/study/sessions/start',{'course_id':self.c['id']},headers={'Content-Type':'application/json','Origin':'https://evil.example'})[0],400)
  for data in [{'course_id':[]},{'course_id':self.c['id'],'mastery':1},{'course_id':self.c['id'],'activity_type':[]},{'course_id':self.c['id'],'planned_minutes':-1}]:self.assertEqual(self.request('/api/study/sessions/start',data)[0],400)
  sid=self.start();self.assertEqual(self.request('/api/study/sessions/start',{'course_id':self.c['id']})[0],400);self.assertEqual(self.request('/api/study/sessions/'+sid+'/end',{'completion':{}})[0],400)
 def test_growth_start_suggestion_never_auto_timing(self):
  svc,gid=self.model.growth_goal(self.store,self.user);plan=svc.generate(self.user,gid)['roadmap'];tid=plan['tasks'][0]['id'];status,r=self.request(f'/api/goals/{gid}/tasks/{tid}/start',{});self.assertEqual(status,200);self.assertIn('study_session_suggestion',r);self.assertIsNone(self.request('/api/study/sessions/current')[1]['session']);status,r=self.request('/api/study/sessions/start',{'growth_task_id':tid});self.assertEqual(status,200);self.assertEqual(r['session']['goal_id'],gid)
 def test_execution_feedback_api_does_not_replan(self):
  svc,gid=self.model.growth_goal(self.store,self.user,deadline='2026-10-30',weekly_time_budget_minutes=300);svc.generate(self.user,gid);status,r=self.request(f'/api/goals/{gid}/execution');self.assertEqual(status,200);self.assertEqual(r['deadline']['status'],'insufficient_data');self.assertEqual(svc.roadmap(self.user,gid)['roadmap']['version'],1);self.assertEqual(self.request('/api/growth/today')[0],200)
