import unittest,json,os,urllib.request,urllib.error
from unittest.mock import patch
from growth_fixture import GrowthModel,browser_seed
from mindos.server import MindOSHandler
class GrowthAPITests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  from test_prototype import PrototypeTests
  cls.fixture=PrototypeTests;cls.fixture.setUpClass()
 @classmethod
 def tearDownClass(cls):cls.fixture.tearDownClass()
 def setUp(self):
  self.client=self.fixture();self.client.setUp();self.client.configure();self.user=self.client.session_id();self.store=self.fixture.server.storage;self.model=GrowthModel();self.mock=patch.object(MindOSHandler,'_model',return_value=self.model);self.mock.start();self.addCleanup(self.mock.stop)
 def request(self,path,payload=None,method=None,client=None):
  req=urllib.request.Request(self.fixture.url+path,data=json.dumps(payload).encode() if payload is not None else None,headers={'Content-Type':'application/json'},method=method)
  try:
   with (client or self.client.client).open(req) as r:return r.status,json.loads(r.read())
  except urllib.error.HTTPError as e:return e.code,json.loads(e.read())
 def goal(self):
  status,r=self.request('/api/goals',{'title':'LLM目标','description':'独立理解信息匹配并能应用'});self.assertEqual(status,200);gid=r['goal']['id'];status,r=self.request(f'/api/goals/{gid}/analyze',{});self.assertEqual(status,200);status,r=self.request(f'/api/goals/{gid}/analyze',{'confirm':True,'draft_version':r['goal']['draft_version']});self.assertEqual(status,200);return gid
 def test_http_full_lifecycle_and_versioned_routes(self):
  current=browser_seed(self.store,self.user);gid=self.goal();status,r=self.request(f'/api/goals/{gid}/roadmap/generate',{});self.assertEqual(status,200);t=r['roadmap']['tasks'][0];self.assertEqual(t['target_id'],current['id']);self.assertEqual(self.request(f'/api/goals/{gid}/tasks/{t["id"]}/start',{})[1]['route']['destination'],'atom');self.assertEqual(self.request(f'/api/goals/{gid}/replan',{})[1]['roadmap']['version'],2);self.assertEqual(self.request(f'/api/goals/{gid}/roadmap?version=1')[1]['roadmap']['status'],'superseded')
  self.assertEqual(self.request(f'/api/goals/{gid}',{'status':'paused'},'PATCH')[0],200);self.assertFalse(self.request('/api/growth/today')[1]['goals']);self.assertEqual(self.request(f'/api/goals/{gid}',{'status':'active'},'PATCH')[0],200);self.assertEqual(self.request(f'/api/goals/{gid}',{'title':'更深入的LLM目标'},'PATCH')[0],200);self.assertEqual(self.request(f'/api/goals/{gid}/roadmap')[1]['roadmap']['status'],'stale');self.assertEqual(self.request(f'/api/goals/{gid}',{},'DELETE')[0],200);self.assertTrue(self.store.course(self.user,current['id']))
 def test_owner_redaction_and_debug_gate(self):
  gid=self.goal();status,r=self.request(f'/api/goals/{gid}/gaps');self.assertEqual(status,200);self.assertNotIn('debug',r['gaps'][0]);self.assertNotIn('inputs_hash',r)
  with patch.dict(os.environ,{'MINDOS_DEBUG_LEARNING':'0'}):self.assertEqual(self.request(f'/api/debug/learning/growth/{gid}/gaps')[0],404)
  with patch.dict(os.environ,{'MINDOS_DEBUG_LEARNING':'1'}):self.assertIn('debug',self.request(f'/api/debug/learning/growth/{gid}/gaps')[1]['gaps'][0])
  self.assertNotEqual(self.request(f'/api/goals/{gid}',client=urllib.request.build_opener())[0],200)
 def test_untrusted_scores_and_operations_rejected(self):
  gid=self.goal();self.assertEqual(self.request(f'/api/goals/{gid}',{'status':'achieved'},'PATCH')[0],400);self.assertEqual(self.request(f'/api/goals/{gid}/replan',{'mastery':1})[0],400);self.assertEqual(self.request(f'/api/goals/{gid}/roadmap?version=bad')[0],400);self.assertEqual(self.request(f'/api/goals/{gid}/anything')[0],404)
