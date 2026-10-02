"""HTTP contracts: server-owned state, preserved scores, isolated tasks and fallback."""
import json,unittest,urllib.request
from unittest.mock import patch
import test_prototype as p
from mindos.model import ModelGateway,ModelUnavailable

class LoopAPI(unittest.TestCase):
 setUpClass=classmethod(p.PrototypeTests.setUpClass.__func__);tearDownClass=classmethod(p.PrototypeTests.tearDownClass.__func__)
 setUp=p.PrototypeTests.setUp;call=p.PrototypeTests.call;configure=p.PrototypeTests.configure;session_id=p.PrototypeTests.session_id;draft_and_confirm=p.PrototypeTests.draft_and_confirm
 def ready(self):
  self.configure();cid=self.draft_and_confirm('闭环API课程');self.call('/api/knowledge/build',{'course_id':cid});self.call('/api/sections/lesson',{'course_id':cid,'ordinal':1});return cid
 def test_loop_enter_api_and_untrusted_state_writes_rejected(self):
  cid=self.ready();status,r=self.call(f'/api/courses/{cid}/loop/enter',{});self.assertEqual(status,200,r);self.assertEqual(r['status'],'not_needed')
  for field in ['mastery','understanding','state','score','retention']:
   self.assertEqual(self.call(f'/api/courses/{cid}/loop/enter',{field:1})[0],400)
  self.assertEqual(self.call(f'/api/courses/{cid}/loop/enter',{'return_context':{'section_ordinal':99}})[0],400)
  self.assertEqual(self.call(f'/api/courses/{cid}/loop')[0],200)
 def test_small_assessment_validated_saved_and_scored_with_confidence(self):
  cid=self.ready();status,quiz=self.call(f'/api/courses/{cid}/loop/assessment',{'atom_id':'a1','purpose':'review'});self.assertEqual(status,200,quiz);self.assertEqual(len(quiz['questions']),2)
  self.assertNotIn('answer',json.dumps(quiz['questions']));self.assertNotIn('QK_ROLE_CONFUSION',json.dumps(quiz['questions']))
  self.assertEqual(self.call(f'/api/courses/{cid}/loop/assessment',{'atom_id':'a1','purpose':'review'})[1]['id'],quiz['id'])
  status,r=self.call('/api/quizzes/submit',{'course_id':cid,'quiz_id':quiz['id'],'answers':['a','a'],'confidence':['high','low']});self.assertEqual(status,200,r);self.assertEqual(r['result']['score'],2);self.assertEqual(r['course']['current_ordinal'],1)
  state=self.call(f'/api/courses/{cid}/loop/state?atom_id=a1')[1];self.assertIsNotNone(state['knowledge_state']['understanding']);self.assertIsNone(state['knowledge_state']['retention']);self.assertEqual(state['evidence'][0]['confidence'],'low')
 def test_choice_misconception_uses_mapping_and_never_calls_diagnosis(self):
  cid=self.ready()
  with patch.object(ModelGateway,'analyze_misconception',side_effect=AssertionError('choice must not call LLM')):
   for _ in range(2):
    quiz=self.call(f'/api/courses/{cid}/loop/assessment',{'atom_id':'a1','purpose':'diagnostic'})[1]
    self.assertEqual(self.call('/api/quizzes/submit',{'course_id':cid,'quiz_id':quiz['id'],'answers':['b','b'],'confidence':['high','high']})[0],200)
  loop=self.call(f'/api/courses/{cid}/loop')[1];self.assertEqual(loop['misconceptions'][0]['status'],'confirmed');self.assertEqual(loop['decisions'][0]['action'],'remediate')
 def test_diagnosis_failure_returns_signal_does_not_break_later_scoring(self):
  cid=self.ready()
  with patch.object(ModelGateway,'analyze_misconception',return_value={'mastery':1}) as diagnose:
   status,r=self.call(f'/api/courses/{cid}/loop/self-explanation',{'atom_id':'a1','answer':'我还不确定这些角色'});self.assertEqual(status,200,r);self.assertFalse(r['affects_mastery']);self.assertIsNone(r['candidate']);self.assertEqual(diagnose.call_count,2)
  quiz=self.call(f'/api/courses/{cid}/loop/assessment',{'atom_id':'a1','purpose':'diagnostic'})[1]
  self.assertEqual(self.call('/api/quizzes/submit',{'course_id':cid,'quiz_id':quiz['id'],'answers':['a','a']})[0],200)
 def test_model_failure_no_invented_question_and_valid_history_fallback(self):
  cid=self.ready()
  with patch.object(ModelGateway,'learning_check',side_effect=ModelUnavailable('offline')):
   r=self.call(f'/api/courses/{cid}/loop/assessment',{'atom_id':'a1','purpose':'review'})[1];self.assertFalse(r['available'])
  quiz=self.call(f'/api/courses/{cid}/loop/assessment',{'atom_id':'a1','purpose':'diagnostic'})[1];self.call('/api/quizzes/submit',{'course_id':cid,'quiz_id':quiz['id'],'answers':['a','a']})
  with patch.object(ModelGateway,'learning_check',side_effect=ModelUnavailable('offline')):
   r=self.call(f'/api/courses/{cid}/loop/assessment',{'atom_id':'a1','purpose':'review'})[1];self.assertTrue(r['fallback']);self.assertTrue(all(q['reused_question'] for q in r['questions']))
 def test_short_question_schema_retries_once_and_then_fails_closed(self):
  model=ModelGateway({'base_url':'http://127.0.0.1','chat_model':'test'})
  valid={'questions':[{'prompt':f'第{i+1}题：请选择符合查询角色的正确表述。','choices':dict(a='表示需求',b='提供内容',c='忽略条件',d='替代所有角色'),'answer':'a','explanation':'查询表达需要查找什么。','atom_ids':['a1'],'assessment_type':'concept'} for i in range(2)]}
  with patch.object(model,'_diagnostic'),patch.object(model,'_json',side_effect=[{'mastery':1},valid]) as call:
   questions,answers=model.learning_check({'title':'基础'}, {'title':'查询'}, {'id':'a1'},'diagnostic',[]);self.assertEqual(len(questions),2);self.assertEqual(call.call_count,2)
  with patch.object(model,'_diagnostic'),patch.object(model,'_json',return_value={'mastery':1}) as call:
   with self.assertRaises(ModelUnavailable):model.learning_check({'title':'基础'}, {'title':'查询'}, {'id':'a1'},'diagnostic',[])
   self.assertEqual(call.call_count,2)
 def test_course_owner_future_atom_and_debug_gates(self):
  cid=self.ready();stranger=urllib.request.build_opener(urllib.request.HTTPCookieProcessor())
  self.assertEqual(self.call(f'/api/courses/{cid}/loop',client=stranger)[0],400)
  self.assertEqual(self.call(f'/api/courses/{cid}/loop/assessment',{'atom_id':'a2','purpose':'review'})[0],400)
  self.assertEqual(self.call(f'/api/courses/{cid}/loop/debug')[0],404)
  with patch.dict('os.environ',{'MINDOS_DEBUG_LEARNING':'1'}):
   r=self.call(f'/api/courses/{cid}/loop/debug')[1];self.assertIn('state_history',r);self.assertNotIn('encrypted_api_key',json.dumps(r))
 def test_teacher_help_is_recorded_without_changing_mastery(self):
  cid=self.ready();quiz=self.call(f'/api/courses/{cid}/loop/assessment',{'atom_id':'a1','purpose':'diagnostic'})[1]
  before=self.call('/api/course?course_id='+cid)[1]['mastery'];self.call('/api/sections/ask',{'course_id':cid,'ordinal':1,'question':'请换一个例子解释这个知识点'})
  with self.server.storage.connect() as db:flags=json.loads(db.execute('SELECT hint_flags_json FROM quizzes WHERE id=?',(quiz['id'],)).fetchone()[0])
  self.assertTrue(all(flags));self.assertEqual(self.call('/api/course?course_id='+cid)[1]['mastery'],before)
  self.assertEqual(self.call('/api/quizzes/submit',{'course_id':cid,'quiz_id':quiz['id'],'answers':['a','a'],'hint_used':[False,False]})[0],200)
