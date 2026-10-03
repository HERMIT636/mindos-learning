"""Real HTTP ownership, debug gating, new routes and P0 verification integration."""
import json,os,unittest,urllib.request,urllib.error
from unittest.mock import patch
from mindos.server import MindOSHandler
from personal_fixture import course
import test_tutor_p6 as fixture

class TutorAPITests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  import test_prototype
  cls.base=test_prototype.PrototypeTests;cls.base.setUpClass()
 @classmethod
 def tearDownClass(cls):cls.base.tearDownClass()
 def setUp(self):
  self.client=self.base();self.client.setUp();self.client.configure();self.user=self.client.session_id();self.store=self.base.server.storage;self.c=course(self.store,user=self.user);self.model=fixture.Model();p=patch.object(MindOSHandler,'_model',return_value=self.model);p.start();self.addCleanup(p.stop)
 def req(self,path,payload=None,method=None,client=None,headers=None):
  r=urllib.request.Request(self.base.url+path,data=json.dumps(payload).encode() if payload is not None else None,method=method,headers=headers or {'Content-Type':'application/json'})
  try:
   with (client or self.client.client).open(r) as response:return response.status,json.loads(response.read())
  except urllib.error.HTTPError as e:return e.code,json.loads(e.read())
 def chat(self,**extra):return self.req('/api/tutor/chat',{'message':'什么是QKV','context_id':self.c['id'],**extra})
 def test_routes_and_legacy_position_compatibility(self):
  self.assertEqual(self.req('/api/tutor/context?course_id='+self.c['id'])[1]['context_id'],self.c['id']);s,r=self.chat();self.assertEqual(s,200);self.assertTrue(r['saved'])
  self.assertEqual(len(self.req('/api/tutor/conversations?course_id='+self.c['id'])[1]['messages']),2);self.assertEqual(len(self.req('/api/tutor/conversations')[1]['conversations']),1)
  self.assertEqual(self.req('/api/courses/'+self.c['id']+'/assistant/position',{'x':80,'y':400},'PUT')[0],200);self.assertEqual(self.req('/api/tutor/conversations?course_id='+self.c['id'])[1]['position']['x'],80)
 def test_debug_memory_disabled_and_owned(self):
  with patch.dict(os.environ,{'MINDOS_DEBUG_LEARNING':'0'}):self.assertEqual(self.req('/api/tutor/memory?course_id='+self.c['id'])[0],404)
  with patch.dict(os.environ,{'MINDOS_DEBUG_LEARNING':'1'}):self.assertEqual(self.req('/api/tutor/memory?course_id='+self.c['id'])[0],200);self.assertEqual(self.req('/api/tutor/memory?course_id='+self.c['id'],client=urllib.request.build_opener())[0],400)
 def test_ownership_for_conversation_observation_context(self):
  for p in ['context','conversations','observations']:
   self.assertEqual(self.req('/api/tutor/'+p+'?course_id='+self.c['id'],client=urllib.request.build_opener())[0],400)
  self.assertEqual(self.req('/api/tutor/chat',{'context_id':self.c['id'],'message':'解释'},client=urllib.request.build_opener())[0],400)
 def test_schema_fallback_is_usable_and_not_saved(self):
  self.model.transform=lambda p,v:{'invalid':'reply'};s,r=self.chat();self.assertEqual(s,200);self.assertTrue(r['fallback']);self.assertFalse(r['saved']);self.assertEqual(self.req('/api/tutor/conversations?course_id='+self.c['id'])[1]['messages'],[])
 def test_reject_scores_context_forgery_and_foreign_origin(self):
  self.assertEqual(self.chat(mastery=1)[0],400);self.assertEqual(self.chat(current_context={'user_state':{'mastery':1}})[0],400)
  self.assertEqual(self.req('/api/tutor/chat',{'context_id':self.c['id'],'message':'解释'},headers={'Content-Type':'application/json','Origin':'https://evil.example'})[0],400)
 def observed(self):
  self.model.transform=lambda p,v:{**v,'observations':[{'atom_id':'same-local-id','observation_type':'possible_gap','description':'可能需要检查匹配职责','confidence':.7,'supporting_quote':p['message']}]};return self.chat(message='我不理解匹配职责')[1]['observations'][0]
 def test_verification_uses_original_submission_and_no_client_verification(self):
  o=self.observed();path='/api/tutor/observations/'+o['id']+'/verify';self.assertEqual(self.req(path,{'verified':True})[0],400);s,r=self.req(path,{});self.assertEqual(s,200);self.assertEqual(r['verification_task']['type'],'concept_check');self.assertNotIn('answers',r['quiz'])
  s,graded=self.req('/api/quizzes/submit',{'course_id':self.c['id'],'quiz_id':r['quiz']['id'],'answers':['b'],'confidence':['high']});self.assertEqual(s,200)
  o=self.req('/api/tutor/observations?course_id='+self.c['id'])[1]['observations'][0];self.assertEqual(o['status'],'verified');self.assertEqual(o['verification']['outcome'],'needs_review')
 def test_observation_dismiss_and_clear_memory_keep_learning_evidence(self):
  o=self.observed();self.assertEqual(self.req('/api/tutor/observations/'+o['id']+'/dismiss',{})[0],200)
  with self.store.connect() as db:before=[tuple(r) for r in db.execute('SELECT * FROM learning_evidence')]
  self.assertEqual(self.req('/api/tutor/conversations',{'context_id':self.c['id']},'DELETE')[0],200);self.assertEqual(self.req('/api/tutor/conversations?course_id='+self.c['id'])[1]['messages'],[])
  with self.store.connect() as db:self.assertEqual(before,[tuple(r) for r in db.execute('SELECT * FROM learning_evidence')])
 def test_unavailable_model_is_clear_safe_response(self):
  with patch.object(MindOSHandler,'_model',side_effect=ValueError('未配置模型')):
   s,r=self.chat();self.assertEqual(s,200);self.assertTrue(r['fallback']);self.assertEqual(r['attempts'],2)
