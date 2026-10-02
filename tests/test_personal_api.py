import unittest,json,os,http.cookiejar,urllib.request
from unittest.mock import patch
from personal_fixture import course,train,PersonalModel
from mindos.learning.canonical import KnowledgeMappingEngine
class PersonalAPITests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  from test_prototype import PrototypeTests
  cls.fixture=PrototypeTests;cls.fixture.setUpClass()
 @classmethod
 def tearDownClass(cls):cls.fixture.tearDownClass()
 def setUp(self):
  self.client=self.fixture();self.client.setUp();self.client.configure();self.user=self.client.session_id();self.store=self.fixture.server.storage
 def pair(self):
  a=course(self.store,user=self.user);train(self.store,a,user=self.user);b=course(self.store,'LLM API','Query-Key-Value',user=self.user);KnowledgeMappingEngine(self.store).scan(self.user,b['id'],PersonalModel());return a,b
 def test_real_http_full_verification_and_redaction(self):
  a,b=self.pair();cid=b['id'];status,data=self.client.call(f'/api/courses/{cid}/knowledge/priors');self.assertEqual(status,200);p=data['priors'][0];self.assertNotIn('profile_snapshot',p)
  status,r=self.client.call(f"/api/courses/{cid}/knowledge/priors/{p['id']}/verify",{});self.assertEqual(status,200);q=r['quiz'];self.assertNotIn('answer',q['questions'][0]);self.assertEqual(self.client.call('/api/quizzes/submit',{'course_id':cid,'quiz_id':q['id'],'answers':['a','a']})[0],200)
  self.assertEqual(self.client.call(f'/api/courses/{cid}/knowledge/priors')[1]['priors'][0]['status'],'verified_in_course')
  data=self.client.call('/api/knowledge/profile')[1];self.assertNotIn('mastery_estimate',json.dumps(data));self.assertTrue(data['profiles']);identifier=data['profiles'][0]['canonical_atom_id'];self.assertEqual(self.client.call('/api/knowledge/profile/'+identifier)[0],200)
  with self.store.connect() as db:rows=db.execute("SELECT metadata_json FROM learning_evidence WHERE course_id=? AND result IN ('correct','wrong')",(cid,)).fetchall();self.assertTrue(all(json.loads(r[0])['cross_course_verification'] for r in rows))
 def test_foreign_owner_and_debug_gate(self):
  a,b=self.pair();other=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()));self.assertEqual(self.client.call(f"/api/courses/{b['id']}/knowledge/mappings",client=other)[0],400)
  with patch.dict(os.environ,{'MINDOS_DEBUG_LEARNING':'0'}):self.assertEqual(self.client.call('/api/debug/learning/personal')[0],404)
  with patch.dict(os.environ,{'MINDOS_DEBUG_LEARNING':'1'}):self.assertIn('mapping_history',self.client.call('/api/debug/learning/personal')[1])
 def test_client_cannot_supply_evidence_and_filters(self):
  a,b=self.pair();before=self.store.knowledge_state(self.user,b['id']);self.assertEqual(self.client.call(f"/api/courses/{b['id']}/knowledge/mappings/scan",{'mastery':1,'mapping_confidence':1,'score':2})[0],400);self.assertEqual(before,self.store.knowledge_state(self.user,b['id']));self.assertFalse(self.client.call('/api/knowledge/profile?domain=cognitive_psychology')[1]['profiles'])
