"""P1 verifies completion, evidence, private rubrics, bounded repair and isolation."""
import json,tempfile,unittest,threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from datetime import datetime,timezone,timedelta
from unittest.mock import patch
from mindos.storage import Storage
from mindos.learning.final import FinalAssessmentService,validate_explanation
from mindos.learning.final_assessment import FinalAssessmentPlanner,TransferAssessmentGenerator,FINAL_POLICY,novelty
from mindos.learning.course_mastery import CourseMasteryAnalyzer
from mindos.learning.final_remediation import FinalRemediationPlanner
from mindos.learning.state import empty
from mindos.learning.service import LearningLoopService
from mindos.learning.evidence import mark_help
from mindos.course_tutor import CourseTutorService
from final_fixture import FinalModel,seed,grade

class FinalTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.store=Storage(Path(self.temp.name)/'db.sqlite3');self.course=seed(self.store);self.cid=self.course['id'];self.service=FinalAssessmentService(self.store);self.model=FinalModel()
 def tearDown(self):self.temp.cleanup()
 def complete(self):return self.service.complete_content('owner',self.cid)
 def start(self):self.complete();return self.service.start('owner',self.cid)
 def finish(self,choice='a',hint=False):
  self.start()
  for _ in range(FINAL_POLICY['max_questions']+2):
   status=self.service.status('owner',self.cid)
   if status['plan']['status']!='active':break
   result=self.service.assessment('owner',self.cid,self.model)
   quiz=result['current_quiz']
   if quiz:self.store.submit_quiz('owner',self.cid,quiz['id'],[choice],['high'],[hint])
  else:self.fail('检测未在总题量上限内结束')
  return self.service.status('owner',self.cid)
 def strong(self):
  for atom in ['a1','a2','a3']:
   for _ in range(8):
    for kind in ['concept','application','transfer']:grade(self.store,self.course,atom,kind,purpose='transfer' if kind=='transfer' else 'chapter_quiz')
 def test_complete_content_is_not_mastery_and_management_status_not_evidence(self):
  self.store.update_course('owner',self.cid,{'status':'completed'})
  before=self.service.status('owner',self.cid);self.assertFalse(before['eligible_for_final']);self.assertIsNone(before['mastery_state']['mastery_score'])
  after=self.complete();self.assertTrue(after['eligible_for_final']);self.assertEqual(after['mastery_state']['status'],'ready_for_final');self.assertIsNone(after['mastery_state']['transfer'])
  with self.store.connect() as db:self.assertEqual(db.execute("SELECT COUNT(*) FROM learning_evidence WHERE result IN ('correct','wrong')").fetchone()[0],0)
  self.assertEqual(self.store.managed_course('owner',self.cid)['progress'],100)
 def test_content_completion_requires_all_lessons_and_explicit_last_position(self):
  with self.store.connect() as db:db.execute('UPDATE sections SET lesson=NULL WHERE id=?',(self.course['sections'][0]['id'],))
  with self.assertRaises(ValueError):self.complete()
  with self.assertRaises(ValueError):self.service.start('owner',self.cid)
 def test_one_active_plan_and_resume_same_question_without_model(self):
  self.start()
  with ThreadPoolExecutor(max_workers=2) as pool:ids=list(pool.map(lambda _:self.service.start('owner',self.cid)['plan']['id'],range(2)))
  self.assertEqual(len(set(ids)),1);first=self.service.assessment('owner',self.cid,self.model);next_=self.service.assessment('owner',self.cid,None)
  self.assertEqual(first['current_quiz']['id'],next_['current_quiz']['id']);self.assertEqual(self.model.questions,1)
  raw=json.dumps(next_['current_quiz']);self.assertNotIn('"answer":',raw);self.assertNotIn('explanation',raw)
  self.store.submit_quiz('owner',self.cid,first['current_quiz']['id'],['a']);self.assertEqual(self.service.status('owner',self.cid)['plan']['blueprint'][0]['status'],'completed')
 def test_concurrent_generation_keeps_only_one_quiz(self):
  self.start();barrier=threading.Barrier(2);outer=self.model
  class Blocking(FinalModel):
   def final_question(self,*a,**kw):barrier.wait(timeout=3);return super().final_question(*a,**kw)
  with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(lambda _:self.service.assessment('owner',self.cid,Blocking()),range(2)))
  self.assertEqual(len({r['current_quiz']['id'] for r in results}),1)
  with self.store.connect() as db:self.assertEqual(db.execute("SELECT COUNT(*) FROM quizzes WHERE scope='final'").fetchone()[0],1)
 def test_defer_invalidates_old_submission_hint_and_preserves_unknown(self):
  self.start();q=self.service.assessment('owner',self.cid,self.model)['current_quiz'];self.service.defer('owner',self.cid,True)
  with self.assertRaises(ValueError):self.store.submit_quiz('owner',self.cid,q['id'],['a'])
  with self.assertRaises(ValueError):LearningLoopService(self.store).hint('owner',self.cid,q['id'],0)
  r=self.service.report('owner',self.cid);self.assertEqual(r['mastery_state']['status'],'completed_with_gaps');self.assertIsNone(r['mastery_state']['mastery_score']);self.assertEqual(self.store.course('owner',self.cid)['status'],'completed')
 def test_revision_stales_plan_report_and_rejects_old_question(self):
  self.start();q=self.service.assessment('owner',self.cid,self.model)['current_quiz'];self.store.update_course('owner',self.cid,{'goal':'新目标：强调真实应用'})
  with self.assertRaises(ValueError):self.store.submit_quiz('owner',self.cid,q['id'],['a'])
  self.assertTrue(self.service.status('owner',self.cid)['plan']['stale']);self.assertFalse(self.service.status('owner',self.cid)['eligible_for_final']);self.complete();new=self.service.start('owner',self.cid);self.assertNotEqual(new['plan']['id'],q['plan_id'])
 def test_hint_is_sticky_final_and_earlier_lesson_tutor_context(self):
  self.start();q=self.service.assessment('owner',self.cid,self.model)['current_quiz'];course,context,_=CourseTutorService(self.store).context('owner',self.cid,{},'能给一个思路吗')
  self.assertEqual(context['assessment_mode'],'final');self.assertEqual(context['current_context']['section_ordinal'],1);self.assertNotIn('rubric',json.dumps(context['pending_quiz_questions']))
  with self.store.connect() as db:mark_help(db,self.cid,self.course['sections'][-1]['id'])
  self.store.submit_quiz('owner',self.cid,q['id'],['a'],['high'],[False])
  with self.store.connect() as db:
   row=db.execute('SELECT hint_used FROM learning_evidence WHERE event_key LIKE ?',('quiz:'+q['id']+':%',)).fetchone();self.assertEqual(row[0],1)
 def test_transfer_schema_private_rubric_and_independent_evidence_mapping(self):
  self.start()
  for _ in range(8):
   r=self.service.assessment('owner',self.cid,self.model);q=r['current_quiz'];self.assertIsNotNone(q)
   if q['assessment_kind']=='final_transfer':break
   self.store.submit_quiz('owner',self.cid,q['id'],['a'])
  self.assertIn('scenario',q['questions'][0]);self.assertNotIn('rubric',json.dumps(q));self.assertNotIn('expected_concepts',json.dumps(q))
  self.store.submit_quiz('owner',self.cid,q['id'],['a'],['high'])
  with self.store.connect() as db:
   e=db.execute('SELECT evidence_type FROM learning_evidence WHERE event_key LIKE ?',('quiz:'+q['id']+':%',)).fetchone();private=json.loads(db.execute('SELECT answers_json FROM quizzes WHERE id=?',(q['id'],)).fetchone()[0])[0]
  self.assertEqual(e[0],'transfer_test');self.assertTrue(private['novelty_check']['passed']);self.assertEqual(len(private['rubric']),2)
 def test_no_provider_falls_back_only_ordinary_history_and_missing_is_not_zero(self):
  grade(self.store,self.course,'a1');self.start()
  for _ in range(12):
   r=self.service.assessment('owner',self.cid,None)
   if r['current_quiz']:self.store.submit_quiz('owner',self.cid,r['current_quiz']['id'],['a'])
   if self.service.status('owner',self.cid)['plan']['status']=='completed':break
  r=self.service.status('owner',self.cid)
  self.assertEqual(r['plan']['status'],'completed');report=self.service.report('owner',self.cid)['mastery_state'];self.assertIsNone(report['transfer']);self.assertFalse(report['guards']['FINAL_TRANSFER']);self.assertNotEqual(report['status'],'mastered')
  with self.store.connect() as db:self.assertFalse(db.execute("SELECT 1 FROM learning_evidence WHERE evidence_type='transfer_test'").fetchone())
 def test_transfer_clone_numeric_and_variable_replacement_is_rejected(self):
  old='一个仓库有20个零件，使用向量x计算每种零件与订单需求的匹配程度，再读取匹配结果。为什么这样组织数据？'
  new=old.replace('20','35').replace('x','y');self.assertFalse(novelty(new,'为什么这样组织数据？',[old])['passed'])
  model=FinalModel();raw=model.final_transfer(self.course,{'id':'a1'},[]);previous=[raw['scenario']+' '+raw['question']]
  with patch.object(model,'final_transfer',return_value=raw):
   with self.assertRaises(ValueError):TransferAssessmentGenerator().generate(model,self.course,{'id':'a1'},previous)
  self.assertEqual(len(model.logs),2)
 def test_invalid_transfer_schema_retries_once_and_does_not_import(self):
  model=FinalModel()
  with patch.object(model,'final_transfer',return_value={'scenario':'不足'}) as mocked:
   with self.assertRaises(ValueError):TransferAssessmentGenerator().generate(model,self.course,{'id':'a1'},[])
  self.assertEqual(mocked.call_count,2);self.assertIn('failure',model.logs[0])
 def test_all_correct_but_sparse_evidence_is_not_mastered_and_no_instant_retention(self):
  r=self.finish();m=r['mastery_state'];self.assertEqual(r['plan']['status'],'completed');self.assertNotEqual(m['status'],'mastered');self.assertIsNone(m['retention']);self.assertTrue(m['retention_pending']);self.assertFalse(m['guards']['STATE_CONFIDENCE'])
  self.assertLessEqual(len(r['plan']['blueprint']),FINAL_POLICY['max_questions']);self.assertLessEqual(max(q['stage'] for q in r['plan']['blueprint']),2)
 def test_sufficient_evidence_and_final_correct_can_pass_current_ability_only(self):
  self.strong();r=self.finish();m=r['mastery_state'];self.assertEqual(m['status'],'mastered',m['reasons']);self.assertIn('长期记忆待验证',m['label']);self.assertIsNone(m['retention'])
 def test_reports_readonly_cached_summary_snapshots_future_outcomes_only(self):
  self.finish();r=self.service.report('owner',self.cid);before=json.dumps(r['mastery_state'],sort_keys=True)
  self.service.refresh_report('owner',self.cid,self.model,True);self.service.refresh_report('owner',self.cid,self.model,True);self.assertEqual(self.model.summaries,1)
  with self.store.connect() as db:prediction=db.execute('SELECT id FROM learning_prediction_snapshots ORDER BY rowid DESC LIMIT 1').fetchone()[0];count=db.execute('SELECT COUNT(*) FROM knowledge_state_history').fetchone()[0]
  self.service.report('owner',self.cid);self.service.status('owner',self.cid)
  with self.store.connect() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM knowledge_state_history').fetchone()[0],count);self.assertEqual(db.execute('SELECT COUNT(*) FROM learning_prediction_outcomes WHERE prediction_id=?',(prediction,)).fetchone()[0],0)
  grade(self.store,self.course,'a1');after=self.service.report('owner',self.cid);self.assertGreater(after['version'],r['version'])
  with self.store.connect() as db:old=json.loads(db.execute('SELECT result_json FROM course_mastery_reports WHERE id=?',(r['id'],)).fetchone()[0]);links=db.execute('SELECT COUNT(*) FROM learning_prediction_outcomes WHERE prediction_id=?',(prediction,)).fetchone()[0]
  self.assertEqual(json.dumps(old['mastery_state'],sort_keys=True),before);self.assertEqual(links,1)
 def test_summary_invalid_scores_never_change_program_report(self):
  self.finish();r=self.service.report('owner',self.cid)
  with patch.object(self.model,'final_report_summary',return_value={'status':'mastered','summary':'已掌握100%，这是认证结论'}) as call:
   newer=self.service.refresh_report('owner',self.cid,self.model,True)
  self.assertEqual(call.call_count,2);self.assertEqual(newer['mastery_state'],r['mastery_state']);self.assertEqual(newer['summary']['source'],'rule_fallback')
 def test_final_remediation_uses_p0_and_requires_target_reassessment(self):
  self.finish('b');repair=self.service.remediation_start('owner',self.cid);target=repair['targets'][0];session=self.service.remediation_target('owner',self.cid,target['atom_id'],{'section_ordinal':3,'scroll_y':240})
  grade(self.store,self.course,target['atom_id'],'concept','b',purpose='remediation',session=session['id']);loop=LearningLoopService(self.store);content=loop.repair_content('owner',self.cid,session['id']);self.assertTrue(content['blocks'])
  self.assertNotEqual(self.service.status('owner',self.cid)['mastery_state']['status'],'mastered')
  grade(self.store,self.course,target['atom_id'],'application','a',purpose='remediation',session=session['id']);self.assertEqual(loop.session('owner',self.cid,'repair',session['id'])['return_context']['section_ordinal'],3)
  self.assertEqual(self.service.status('owner',self.cid)['repair_plan']['targets'][0]['status'],'completed');self.assertEqual(self.store.course('owner',self.cid)['current_ordinal'],3)
  with self.assertRaises(ValueError):self.service.start('owner',self.cid,True)
 def test_defer_course_repair_stops_linked_p0_submission(self):
  self.finish('b');repair=self.service.remediation_start('owner',self.cid);t=repair['targets'][0];s=self.service.remediation_target('owner',self.cid,t['atom_id']);q=LearningLoopService(self.store).assessment('owner',self.cid,t['atom_id'],'remediation',self.model,s['id']);self.service.defer('owner',self.cid,True)
  with self.assertRaises(ValueError):self.store.submit_quiz('owner',self.cid,q['id'],['a','a'])
 def test_complete_course_repair_then_targeted_reassessment_does_not_skip_grading(self):
  self.finish('b');repair=self.service.remediation_start('owner',self.cid)
  for target in repair['targets']:
   session=self.service.remediation_target('owner',self.cid,target['atom_id'])
   quiz=LearningLoopService(self.store).assessment('owner',self.cid,target['atom_id'],'remediation',self.model,session['id'])
   self.store.submit_quiz('owner',self.cid,quiz['id'],['a','a'],['high','high'])
  ready=self.service.status('owner',self.cid);self.assertEqual(ready['repair_plan']['status'],'needs_verification');self.assertNotEqual(ready['mastery_state']['status'],'mastered')
  before=ready['plan']['id'];plan=self.service.start('owner',self.cid,True)['plan'];self.assertNotEqual(plan['id'],before)
  for _ in range(12):
   if self.service.status('owner',self.cid)['plan']['status']!='active':break
   quiz=self.service.assessment('owner',self.cid,self.model)['current_quiz']
   if quiz:self.store.submit_quiz('owner',self.cid,quiz['id'],['a'],['high'])
  self.assertEqual(self.service.status('owner',self.cid)['plan']['status'],'completed');self.assertIsNone(self.service.status('owner',self.cid)['repair_plan']);self.assertNotEqual(self.service.status('owner',self.cid)['mastery_state']['status'],'mastered')
 def test_confirmed_misconception_blocks_otherwise_strong_state(self):
  self.strong()
  for _ in range(2):grade(self.store,self.course,'a1',answer='b')
  self.finish('b');m=self.service.report('owner',self.cid)['mastery_state']
  self.assertGreater(m['mastery_score'],.78);self.assertTrue(m['misconception_atoms']);self.assertFalse(m['guards']['NO_CONFIRMED_MISCONCEPTION']);self.assertNotEqual(m['status'],'mastered')
 def test_final_repair_binding_is_atomic_and_defer_during_start_cannot_leave_orphan(self):
  self.finish('b');repair=self.service.remediation_start('owner',self.cid);target=repair['targets'][0]
  original=LearningLoopService.repair_start
  def deferred(loop,user,cid,origin,context=None,**kwargs):
   self.service.defer(user,cid,True)
   return original(loop,user,cid,origin,context,**kwargs)
  with patch.object(LearningLoopService,'repair_start',deferred):self.assertRaises(ValueError,self.service.remediation_target,'owner',self.cid,target['atom_id'])
  self.assertIsNone(LearningLoopService(self.store).snapshot('owner',self.cid)['active_repair'])
 def test_context_query_count_stays_bounded_with_many_old_final_plans(self):
  self.start()
  with self.store.connect() as db:
   plan=dict(db.execute('SELECT * FROM final_assessment_plans WHERE course_id=?',(self.cid,)).fetchone())
   for index in range(2,42):db.execute('INSERT INTO final_assessment_plans VALUES(?,?,?,?,?,?,?,?,?,?)',(f'history-{index}','owner',self.cid,index,'completed',plan['content_revision'],plan['scope_hash'],plan['plan_json'],plan['created_at'],plan['created_at']))
   statements=[];db.set_trace_callback(statements.append);self.service._context('owner',self.cid,db);self.assertLess(len(statements),20)
 def test_existing_state_history_growth_is_measured_without_rewriting_old_rows(self):
  for _ in range(12):grade(self.store,self.course,'a1')
  with self.store.connect() as db:
   old=db.execute('SELECT id,new_json,evidence_ids_json FROM knowledge_state_history ORDER BY id LIMIT 1').fetchone();count=db.execute('SELECT COUNT(*) FROM knowledge_state_history').fetchone()[0];size=db.execute('SELECT SUM(LENGTH(new_json)+LENGTH(old_json)+LENGTH(evidence_ids_json)) FROM knowledge_state_history').fetchone()[0]
  self.assertGreater(size,0)
  grade(self.store,self.course,'a1')
  with self.store.connect() as db:
   self.assertEqual(db.execute('SELECT COUNT(*) FROM knowledge_state_history').fetchone()[0],count+1);new=db.execute('SELECT new_json,evidence_ids_json FROM knowledge_state_history WHERE id=?',(old['id'],)).fetchone();self.assertEqual(tuple(new),tuple(old)[1:])
 def test_cross_owner_soft_delete_restore_copy_purge_and_read_batching(self):
  self.finish();self.assertRaises(ValueError,self.service.report,'other',self.cid);self.assertRaises(ValueError,self.service.start,'other',self.cid)
  copy=self.store.copy_course('owner',self.cid);self.assertIsNone(self.service.status('owner',copy['id'])['plan']);self.assertIsNone(self.service.status('owner',copy['id'])['mastery_state']['mastery_score'])
  self.store.recycle_course('owner',self.cid);self.assertRaises(ValueError,self.service.status,'owner',self.cid);self.store.restore_course('owner',self.cid);self.assertTrue(self.service.report('owner',self.cid)['version'])
  with self.store.connect() as db:
   statements=[];db.set_trace_callback(statements.append);self.service._context('owner',self.cid,db);self.assertLess(len(statements),20)
  self.store.recycle_course('owner',self.cid);self.store.purge_course('owner',self.cid,self.course['title'])
  with self.store.connect() as db:
   for table in ['course_final_completion','final_assessment_plans','course_mastery_reports','course_repair_plans','learning_prediction_snapshots','learning_prediction_outcomes']:self.assertFalse(db.execute(f'SELECT 1 FROM {table} WHERE course_id=?',(self.cid,)).fetchone())

class PlannerAnalyzerTests(unittest.TestCase):
 def setUp(self):
  self.course={'current_ordinal':3,'sections':[{'core_atoms':['Core'+str(i)]} for i in range(3)]};self.graph={'atoms':[{'id':str(i),'title':'Core'+str(i),'section':1+i%3,'depth':2} for i in range(6)],'edges':[{'from':'0','to':str(i),'type':'prerequisite'} for i in range(1,6)]};self.states={a['id']:empty(a['id']) for a in self.graph['atoms']};self.at=datetime.now(timezone.utc)
 def analyze(self):return CourseMasteryAnalyzer().analyze(self.course,self.graph,self.states,[],{'eligible':True,'ratio':1},{'status':'completed'},[{'kind':k,'correct':True,'hint_used':False} for k in ['final_concept','final_application','final_transfer']])
 def test_planner_targets_mis_stable_unknown_transfer_ignores_future_deprecated(self):
  self.states['2'].update(mastery=.95,confidence=.75,understanding=.95,application=.95,transfer=.95);self.states['1'].update(mastery=.3,confidence=.5);self.graph['atoms']+=[{'id':'future','title':'Future','section':4},{'id':'deprecated','title':'Old','section':1,'quality_status':'deprecated'}]
  p=FinalAssessmentPlanner().plan(self.course,self.graph,self.states,[{'atom_id':'1','status':'confirmed'}],self.at)
  self.assertIn('1',p['targets']);self.assertIn('2',p['targets']);self.assertNotIn('future',p['targets']);self.assertNotIn('deprecated',p['targets']);self.assertGreaterEqual(len(p['blueprint']),6);self.assertLessEqual(len(p['blueprint']),10)
 def test_retention_requires_elapsed_day_and_precedes_other_tests(self):
  self.states['0']['last_graded_evidence_at']=(self.at-timedelta(hours=23)).isoformat();p=FinalAssessmentPlanner().plan(self.course,self.graph,self.states,[],self.at);self.assertFalse(any(q['dimension']=='retention' for q in p['blueprint']))
  self.states['0']['last_graded_evidence_at']=(self.at-timedelta(hours=25)).isoformat();p=FinalAssessmentPlanner().plan(self.course,self.graph,self.states,[],self.at);self.assertEqual(p['blueprint'][0]['dimension'],'retention')
 def test_high_mean_critical_weak_or_low_confidence_or_unknown_transfer_blocks_mastery(self):
  for s in self.states.values():s.update(mastery=.95,confidence=.9,understanding=.95,application=.95,transfer=.95)
  self.assertEqual(self.analyze()['status'],'mastered')
  self.states['0']['mastery']=.3;r=self.analyze();self.assertGreater(r['mastery_score'],.78);self.assertFalse(r['guards']['CRITICAL_FLOOR'])
  self.states['0']['mastery']=.95
  for s in self.states.values():s['confidence']=.2
  self.assertFalse(self.analyze()['guards']['STATE_CONFIDENCE'])
  for s in self.states.values():s.update(confidence=.9,transfer=None)
  r=self.analyze();self.assertIsNone(r['transfer']);self.assertFalse(r['guards']['TRANSFER_COVERAGE']);self.assertNotEqual(r['status'],'mastered')
 def test_known_weak_delayed_memory_blocks_mastery_even_with_high_mean(self):
  for s in self.states.values():s.update(mastery=.9,confidence=.9,understanding=.95,application=.95,transfer=.95,retention=.3)
  result=self.analyze();self.assertFalse(result['guards']['RETENTION_IF_MEASURED']);self.assertNotEqual(result['status'],'mastered')
 def test_single_atom_course_still_plans_two_trials_of_three_abilities(self):
  graph={'atoms':[self.graph['atoms'][0]],'edges':[]};p=FinalAssessmentPlanner().plan(self.course,graph,self.states,[],self.at)
  self.assertEqual(len(p['blueprint']),6);self.assertEqual({dim:sum(q['dimension']==dim for q in p['blueprint']) for dim in ('concept','application','transfer')},{'concept':2,'application':2,'transfer':2})
 def test_targeted_reassessment_rechecks_advanced_origin_and_not_instant_retention(self):
  targets=[{'atom_id':'0','origin_atom_id':'2','required_verification':['concept','application']},{'atom_id':'1','origin_atom_id':'1','required_verification':['retention']}]
  self.states['1']['last_graded_evidence_at']=self.at.isoformat();p=FinalAssessmentPlanner().plan(self.course,self.graph,self.states,[],self.at,targets)
  self.assertTrue(any(q['atom_id']=='2' and q['dimension']=='application' for q in p['blueprint']));self.assertFalse(any(q['dimension']=='retention' for q in p['blueprint']))
 def test_recent_transfer_failure_not_hidden_by_past_high_average(self):
  for s in self.states.values():s.update(mastery=.95,confidence=.9,understanding=.95,application=.95,transfer=.95)
  p=FinalRemediationPlanner().plan(self.course,self.graph,self.states,[],[{'atom_ids':['0'],'kind':'final_transfer','correct':False,'hint_used':False}]);self.assertEqual(p[0]['reason_code'],'TRANSFER_WEAK');self.assertIn('transfer',p[0]['required_verification'])
 def test_report_uncertainty_negations_are_allowed_but_positive_claims_rejected(self):
  validate_explanation('长期记忆尚未测过，不能据此说已经全面掌握或拿到了某种认证。')
  validate_explanation('证据不足，所以也不宜说已经全面掌握、获得认证或完全没有缺口。')
  self.assertRaises(ValueError,validate_explanation,'已经全面掌握，获得认证。')
  self.assertRaises(ValueError,validate_explanation,'还没有测过，但已经全面掌握。')
 def test_empty_index_cannot_confirm_and_large_course_is_bounded(self):
  self.assertFalse(FinalAssessmentPlanner().plan(self.course,{'atoms':[]},self.states,[],self.at)['available'])
  atoms=[{'id':str(i),'title':'K'+str(i),'section':1,'depth':2} for i in range(1000)];states={a['id']:empty(a['id']) for a in atoms};p=FinalAssessmentPlanner().plan(self.course,{'atoms':atoms,'edges':[]},states,[],self.at);self.assertLessEqual(len(p['blueprint']),10)
