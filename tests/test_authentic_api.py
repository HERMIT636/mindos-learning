import unittest,json,os,http.cookiejar,urllib.request
from unittest.mock import patch
import test_prototype
from final_fixture import seed
from authentic_fixture import AuthenticModel

class AuthenticApiTests(unittest.TestCase):
 setUpClass=classmethod(test_prototype.PrototypeTests.setUpClass.__func__)
 tearDownClass=classmethod(test_prototype.PrototypeTests.tearDownClass.__func__)
 call=test_prototype.PrototypeTests.call
 session_id=test_prototype.PrototypeTests.session_id
 configure=test_prototype.PrototypeTests.configure
 def setUp(self):
  test_prototype.PrototypeTests.setUp(self);self.configure();self.user=self.session_id();self.course=seed(self.server.storage,self.user);self.cid=self.course['id'];self.base=f'/api/courses/{self.cid}/authentic/';test_prototype.FakeProvider.authentic_model=AuthenticModel()
 def start(self,mode='explanation'):
  status,r=self.call(self.base+'start',{'atom_id':'a1','task_type':mode});self.assertEqual(status,200,r);return r['task']
 def frozen(self):
  with self.server.storage.connect() as db:return [tuple(r) for r in db.execute('SELECT * FROM knowledge_states')],[tuple(r) for r in db.execute('SELECT * FROM knowledge_state_history')]
 def test_api_draft_submit_and_no_client_scoring(self):
  task=self.start('open_transfer');tid=task['id'];before=self.frozen()
  self.assertEqual(self.call(self.base+tid+'/draft',{'answer':'我的多行\n回答'})[0],200)
  self.assertEqual(self.call(self.base+tid)[1]['task']['draft'],'我的多行\n回答')
  self.assertEqual(self.call(self.base+tid+'/submit',{'answer':'真实回答','score':1})[0],400)
  status,r=self.call(self.base+tid+'/submit',{'answer':'需求与条件匹配后，读取对应内容。'});self.assertEqual(status,200,r);self.assertEqual(r['task']['result']['score'],.82);self.assertEqual(before,self.frozen())
  status,r=self.call(f'/api/courses/{self.cid}/calibration');self.assertEqual(status,200,r);self.assertNotIn('brier_score',json.dumps(r))
 def test_tutor_help_marks_task_and_never_updates_state(self):
  task=self.start();before=self.frozen();status,r=self.call(f'/api/courses/{self.cid}/assistant/chat',{'message':'直接告诉我答案','request_id':'p2-direct','current_context':{'authentic_task_id':task['id']}});self.assertEqual(status,200,r);self.assertEqual(before,self.frozen())
  status,r=self.call(self.base+task['id']+'/submit',{'answer':'比较需求和匹配条件，再读取相关内容。'});self.assertEqual(status,200,r);self.assertFalse(r['task']['result']['valid_for_calibration']);self.assertEqual(before,self.frozen())
 def test_owner_and_debug_guard_and_static(self):
  task=self.start();other=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()));self.assertEqual(self.call(self.base+task['id'],client=other)[0],400)
  with patch.dict(os.environ,{'MINDOS_DEBUG_LEARNING':'0'}):self.assertEqual(self.call('/api/debug/learning/calibration')[0],404)
  with patch.dict(os.environ,{'MINDOS_DEBUG_LEARNING':'1'}):status,r=self.call('/api/debug/learning/calibration');self.assertEqual(status,200,r);self.assertIn('courses',r)
  with self.client.open(self.url+'/components/mindos/authentic.js') as r:self.assertIn(b'MindOSAuthentic',r.read())
