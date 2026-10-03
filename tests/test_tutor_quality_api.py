"""Quality metadata ownership, server debug gate, and unchanged public chat contract."""
import os,unittest,urllib.request
from unittest.mock import patch
import test_tutor_p6_api as fixture

class QualityAPITests(unittest.TestCase):
 setUpClass=classmethod(fixture.TutorAPITests.setUpClass.__func__)
 tearDownClass=classmethod(fixture.TutorAPITests.tearDownClass.__func__)
 setUp=fixture.TutorAPITests.setUp
 req=fixture.TutorAPITests.req
 chat=fixture.TutorAPITests.chat
 def path(self):return '/api/tutor/quality-debug?context_id='+self.c['id']
 def test_debug_disabled_even_query_requests_it(self):
  with patch.dict(os.environ,{'MINDOS_DEBUG_LEARNING':'0'}):self.assertEqual(self.req(self.path()+'&debug=1')[0],404)
 def test_debug_enabled_returns_only_small_meta(self):
  self.chat()
  with patch.dict(os.environ,{'MINDOS_DEBUG_LEARNING':'1'}):
   s,r=self.req(self.path());self.assertEqual(s,200);self.assertEqual(len(r['responses']),1);self.assertEqual(set(r['responses'][0]),{'strategy','quality_flags','retry_count','approved','created_at'})
 def test_foreign_owner_cannot_read_debug(self):
  with patch.dict(os.environ,{'MINDOS_DEBUG_LEARNING':'1'}):self.assertEqual(self.req(self.path(),client=urllib.request.build_opener())[0],400)
 def test_bootstrap_debug_disabled(self):
  with patch.dict(os.environ,{'MINDOS_DEBUG_LEARNING':'0'}):self.assertFalse(self.req('/api/bootstrap')[1]['tutor_quality_debug_enabled'])
 def test_bootstrap_debug_enabled(self):
  with patch.dict(os.environ,{'MINDOS_DEBUG_LEARNING':'1'}):self.assertTrue(self.req('/api/bootstrap')[1]['tutor_quality_debug_enabled'])
 def test_public_answer_has_no_quality_scores_or_analysis(self):
  r=self.chat()[1];self.assertTrue(r['saved']);self.assertNotIn('quality_flags',r);self.assertNotIn('model_confidence',r);self.assertNotIn('analysis',r)
 def test_quality_failure_fallback_no_saved_messages(self):
  self.model.transform=lambda p,v:{**v,'blocks':[{'type':'paragraph','content':'今天讲蛋糕做法，和知识学习无关的配料、烤箱温度与装饰。'*20}]}
  s,r=self.chat();self.assertEqual(s,200);self.assertTrue(r['fallback']);self.assertFalse(r['saved']);self.assertIn('无法确认',r['answer']);self.assertEqual(len(self.model.calls),2)
 def test_clear_also_removes_failed_quality_meta(self):
  self.model.transform=lambda p,v:{'bad':True};self.chat();self.assertEqual(self.req('/api/tutor/conversations',{'context_id':self.c['id']},'DELETE')[0],200)
  with patch.dict(os.environ,{'MINDOS_DEBUG_LEARNING':'1'}):self.assertEqual(self.req(self.path())[1]['responses'],[])
 def test_invalid_payload_not_server_error(self):self.assertEqual(self.req('/api/tutor/chat',[])[0],400)
 def test_clear_invalid_payload_not_server_error(self):self.assertEqual(self.req('/api/tutor/conversations',[],'DELETE')[0],400)
 def test_cannot_request_more_retries_or_fake_quality(self):self.assertEqual(self.chat(max_retry=20,approved=True)[0],400)
 def test_static_debug_script_exists(self):
  with self.client.client.open(self.base.url+'/components/mindos/tutor-quality.js') as r:self.assertEqual(r.status,200)
