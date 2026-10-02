"""HTTP P1 checks use the same configured local gateway and existing quiz endpoint."""
import unittest,json,urllib.request,http.cookiejar
import test_prototype
from final_fixture import seed,FinalModel

class FinalApiTests(unittest.TestCase):
 setUpClass=classmethod(test_prototype.PrototypeTests.setUpClass.__func__)
 tearDownClass=classmethod(test_prototype.PrototypeTests.tearDownClass.__func__)
 call=test_prototype.PrototypeTests.call
 session_id=test_prototype.PrototypeTests.session_id
 configure=test_prototype.PrototypeTests.configure
 def setUp(self):
  test_prototype.PrototypeTests.setUp(self);self.configure();self.user=self.session_id();self.course=seed(self.server.storage,self.user);self.cid=self.course['id'];self.base=f'/api/courses/{self.cid}/final/'
  test_prototype.FakeProvider.final_model=FinalModel()
 def post(self,op,body={}):return self.call(self.base+op,body)
 def test_http_flow_private_schema_final_report_cached_reads_and_defer(self):
  self.assertEqual(self.post('start')[0],400);self.assertEqual(self.post('complete-content')[0],200);self.assertEqual(self.post('start')[0],200)
  ids=[];kinds=set()
  for _ in range(12):
   status,r=self.post('assessment');self.assertEqual(status,200,r)
   quiz=r['current_quiz']
   if quiz:
    self.assertNotIn('"answer":',json.dumps(quiz));self.assertNotIn('rubric',json.dumps(quiz));ids.append(quiz['id']);kinds.add(quiz['assessment_kind'])
    status,result=self.call('/api/quizzes/submit',{'course_id':self.cid,'quiz_id':quiz['id'],'answers':['a'],'confidence':['high']});self.assertEqual(status,200,result)
   if self.call(self.base+'status')[1]['plan']['status']=='completed':break
  self.assertTrue({'final_concept','final_application','final_transfer'}<=kinds);self.assertEqual(len(ids),len(set(ids)))
  status,r=self.call(self.base+'report');self.assertEqual(status,200,r);self.assertEqual(r['mastery_state']['status'],'needs_reinforcement');self.assertIsNone(r['mastery_state']['retention'])
  version=r['version'];self.assertEqual(self.call(self.base+'report')[1]['version'],version);self.assertEqual(self.post('report',{'summary':True})[0],200)
  self.assertEqual(self.post('defer',{'end_with_gaps':True})[1]['mastery_state']['status'],'completed_with_gaps')
 def test_write_fields_are_rejected_owner_scope_and_new_static_script(self):
  self.assertEqual(self.post('start',{'mastery':1})[0],400)
  other=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
  self.assertEqual(self.call(self.base+'status',client=other)[0],400)
  with self.client.open(self.url+'/components/mindos/course-final.js') as response:self.assertEqual(response.status,200);self.assertIn(b'MindOSCourseFinal',response.read())
 def test_tutor_help_is_recorded_for_actual_final_target_and_can_not_clear(self):
  self.post('complete-content');self.post('start');quiz=self.post('assessment')[1]['current_quiz']
  status,result=self.call(f'/api/courses/{self.cid}/assistant/chat',{'message':'先引导我思考，不要给答案','request_id':'final-api-hint'});self.assertEqual(status,200,result)
  status,r=self.call('/api/quizzes/submit',{'course_id':self.cid,'quiz_id':quiz['id'],'answers':['a'],'hint_used':[False]});self.assertEqual(status,200,r)
  with self.server.storage.connect() as db:e=db.execute('SELECT hint_used FROM learning_evidence WHERE event_key LIKE ?',('quiz:'+quiz['id']+':%',)).fetchone()
  self.assertEqual(e[0],1)
 def test_nested_remediation_route_alias_reuses_p0(self):
  self.post('complete-content');self.post('start');self.post('defer')
  status,r=self.post('remediation/start');self.assertEqual(status,200,r);self.assertEqual(r['status'],'active');self.assertTrue(r['targets'])
  target=r['targets'][0];status,result=self.post('remediation/target',{'atom_id':target['atom_id']});self.assertEqual(status,200,result);self.assertEqual(result['status'],'diagnostic')
