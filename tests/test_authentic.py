import unittest,tempfile,json
from pathlib import Path
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime,timezone,timedelta
from mindos.storage import Storage
from mindos.learning.authentic import AuthenticAssessmentService,AuthenticEvaluator,AuthenticAssessmentGenerator
from mindos.learning.calibration import CalibrationService,CalibrationAnalyzer,capture_prediction,agreement,state_policy
from mindos.learning.final import FinalAssessmentService
from mindos.learning.evidence import append
from mindos.learning.state import empty
from final_fixture import seed,grade
from authentic_fixture import AuthenticModel

class AuthenticTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.store=Storage(Path(self.tmp.name)/'p2.sqlite');self.course=seed(self.store);self.cid=self.course['id'];self.service=AuthenticAssessmentService(self.store);self.model=AuthenticModel()
 def tearDown(self):self.tmp.cleanup()
 def start(self,type_='explanation'):return self.service.start('owner',self.cid,'a1',type_,self.model)['task']
 def frozen(self):
  with self.store.connect() as db:return {t:[tuple(r) for r in db.execute('SELECT * FROM '+t)] for t in ['knowledge_states','knowledge_state_history','course_mastery_reports','course_mastery_states']}
 def test_all_modes_and_no_private_expected_answers(self):
  for mode in ['explanation','analysis','design','open_transfer']:
   task=self.start(mode);self.assertEqual(task['task_type'],mode);self.assertNotIn('expected_concepts',task);self.assertEqual(len(task['rubric']['criteria']),2);self.service.defer('owner',self.cid,task['id'])
 def test_server_recomputes_weighted_score_and_shadow_state_unchanged(self):
  before=self.frozen();h=FinalAssessmentService(self.store)._context('owner',self.cid)['state_hash'];task=self.start()
  result=self.service.submit('owner',self.cid,task['id'],'需求先和条件匹配，再读取相关的内容。',self.model)['task']['result']
  self.assertAlmostEqual(result['score'],.82);self.assertTrue(result['valid_for_calibration']);self.assertEqual(result['evaluation']['model_overall_score'],.123)
  self.assertEqual(before,self.frozen());self.assertEqual(h,FinalAssessmentService(self.store)._context('owner',self.cid)['state_hash'])
  with self.store.connect() as db:r=db.execute("SELECT * FROM learning_evidence WHERE evidence_type='project_evidence'").fetchone();self.assertEqual(json.loads(r['metadata_json'])['shadow'],True)
 def test_invalid_quotes_repaired_once_unavailable_not_zero(self):
  task=self.start();self.model.invalid_quote=True
  result=self.service.submit('owner',self.cid,task['id'],'这里是我的真实回答内容。',self.model)['task']['result']
  self.assertIsNone(result['score']);self.assertFalse(result['valid_for_calibration']);self.assertEqual(result['answer'],'这里是我的真实回答内容。');self.assertEqual(len([c for c in self.model.calls if c[0]=='authentic_evaluation']),2)
  with self.store.connect() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM learning_prediction_outcomes').fetchone()[0],0)
 def test_failure_not_zero_answer_persisted(self):
  task=self.start();self.model.bad=True;r=self.service.submit('owner',self.cid,task['id'],'我认为需求决定选择内容。',self.model)['task']['result'];self.assertIsNone(r['score']);self.assertFalse(r['valid_for_calibration'])
 def test_hints_sticky_no_state_change(self):
  task=self.start();before=self.frozen();self.service.hint('owner',self.cid,task['id']);r=self.service.submit('owner',self.cid,task['id'],'比较需求后选择并读取内容。',self.model)['task'];self.assertEqual(r['hint_used'],1);self.assertFalse(r['result']['valid_for_calibration']);self.assertEqual(before,self.frozen());self.assertEqual(r['result']['agreement']['classification'],'insufficient_future_evidence')
 def test_draft_refresh_and_submit_idempotence(self):
  t=self.start();self.service.draft('owner',self.cid,t['id'],'第一行\n第二行');self.assertEqual(self.service.get('owner',self.cid)['task']['draft'],'第一行\n第二行')
  self.service.submit('owner',self.cid,t['id'],'保存的独立回答。',self.model);n=len(self.model.calls);r=self.service.submit('owner',self.cid,t['id'],'再次提交不同回答。',self.model);self.assertEqual(len(self.model.calls),n);self.assertEqual(r['task']['result']['answer'],'保存的独立回答。')
 def test_owner_and_atom_bounds(self):
  with self.assertRaises(ValueError):self.service.start('stranger',self.cid,'a1','explanation',self.model)
  with self.assertRaises(ValueError):self.service.start('owner',self.cid,'outside','explanation',self.model)
  with self.store.connect() as db:db.execute('UPDATE courses SET current_ordinal=1 WHERE id=?',(self.cid,))
  with self.assertRaises(ValueError):self.service.start('owner',self.cid,'a2','explanation',self.model)
  graph=self.store.graph('owner',self.cid);graph['atoms'][0]['quality_status']='deprecated'
  with self.store.connect() as db:db.execute('UPDATE course_graphs SET graph_json=? WHERE course_id=?',(json.dumps(graph),self.cid))
  with self.assertRaises(ValueError):self.start()
 def test_bad_weights_repair_once_and_generation_failure(self):
  self.model.bad_weights=True
  with self.assertRaises(ValueError):self.start()
  self.assertEqual(len(self.model.calls),2);self.assertEqual(self.service.get('owner',self.cid)['task']['status'],'unavailable')
 def test_duplicate_signature_and_lexical_duplicate_rejected(self):
  t=self.start('open_transfer');self.service.defer('owner',self.cid,t['id'])
  with self.assertRaises(ValueError):self.start('open_transfer')
  self.model.domain='物流运输';self.model.structure='另外的结构，先比较仓储位置再分配运输任务'
  with self.assertRaises(ValueError):self.start('open_transfer')
 def test_application_not_open_transfer(self):
  self.model.force_type='design'
  with self.assertRaises(ValueError):self.start('open_transfer')
 def test_parallel_generation_only_one_call(self):
  with ThreadPoolExecutor(2) as pool:results=list(pool.map(lambda _:self.start(),range(2)))
  self.assertEqual(results[0]['id'],results[1]['id']);self.assertEqual(len(self.model.calls),1)
 def test_parallel_submit_only_one_evaluation(self):
  t=self.start()
  def submit(_):
   try:return self.service.submit('owner',self.cid,t['id'],'需求与条件匹配后取得内容。',self.model)
   except ValueError:return None
  with ThreadPoolExecutor(2) as pool:list(pool.map(submit,range(2)))
  self.assertEqual(len([c for c in self.model.calls if c[0]=='authentic_evaluation']),1)
 def test_recover_interrupted_evaluation_retains_answer_without_rescoring(self):
  t=self.start()
  with self.store.connect() as db:db.execute("UPDATE authentic_tasks SET status='evaluating',draft='保留回答',lease_at=? WHERE id=?",((datetime.now(timezone.utc)-timedelta(minutes=20)).isoformat(),t['id']))
  n=len(self.model.calls);r=self.service.get('owner',self.cid)['task'];self.assertEqual(r['status'],'submitted');self.assertEqual(r['result']['answer'],'保留回答');self.assertIsNone(r['result']['score']);self.assertEqual(n,len(self.model.calls))
 def test_rubric_ids_must_match(self):
  task=self.start();raw=self.model.authentic_json
  def invalid(stage,p):
   r=raw(stage,p)
   if stage=='authentic_evaluation':r['criteria'][0]['id']='wrong_id'
   return r
  self.model.authentic_json=invalid;r=self.service.submit('owner',self.cid,task['id'],'真实的用户回答。',self.model)['task']['result'];self.assertIsNone(r['score'])
 def test_open_score_does_not_change_official_transfer(self):
  grade(self.store,self.course,'a1');before=self.frozen();t=self.start('open_transfer');self.service.submit('owner',self.cid,t['id'],'按需求与条件匹配，取得对应内容而非简单平均。',self.model);self.assertEqual(before,self.frozen())
 def test_permanent_delete_and_copy_no_p2_results(self):
  t=self.start();self.service.submit('owner',self.cid,t['id'],'真实的用户回答。',self.model);CalibrationService(self.store).course('owner',self.cid)
  copy=self.store.copy_course('owner',self.cid);self.assertIsNone(self.service.get('owner',copy['id'])['task']);self.store.recycle_course('owner',self.cid);self.store.purge_course('owner',self.cid,self.course['title'])
 def test_generation_minimal_context_no_full_answers(self):
  self.start();payload=self.model.calls[0][1];self.assertNotIn('answer',json.dumps(payload));self.assertNotIn('learner_state',payload['context'])

 def test_structural_repeat_cannot_bypass_by_changing_domain(self):
  t=self.start('open_transfer');self.service.defer('owner',self.cid,t['id']);self.model.domain='空间站维修调度'
  original=self.model.authentic_json
  def different_text(stage,payload):
   value=original(stage,payload)
   if stage=='authentic_generation':value['prompt']='空间站维修员面对多个紧急检修申请。请说明怎样利用需求和设备特征选择维护操作，在太空环境中自行建立知识角色的对应关系。'
   return value
  self.model.authentic_json=different_text
  with self.assertRaises(ValueError):self.start('open_transfer')
 def test_original_domain_transfer_rejected(self):
  self.model.domain=self.course['title']
  with self.assertRaises(ValueError):self.start('open_transfer')
 def test_open_shadow_future_outcomes_use_earlier_snapshot_and_separate_source(self):
  now=datetime.now(timezone.utc)
  with self.store.connect() as db:
   state=empty('a1');state['mastery']=.86;state['confidence']=.81
   capture_prediction(db,'owner',self.cid,'a1',state,at=now-timedelta(days=7),salt='future-open')
  t=self.start('open_transfer');before=self.frozen();self.service.submit('owner',self.cid,t['id'],'先按条件匹配，再读取内容。',self.model)
  result=CalibrationService(self.store).course('owner',self.cid,True)['versions']['weighted-evidence-v1']['windows']['7']
  self.assertEqual(result['llm_rubric']['samples'],1);self.assertAlmostEqual(result['llm_rubric']['observed'],.82);self.assertEqual(result['independent_mcq']['samples'],0);self.assertEqual(before,self.frozen())
 def test_generation_provider_failure_no_fake_task(self):
  self.model.bad=True
  with self.assertRaises(ValueError):self.start()
  self.assertEqual(self.service.get('owner',self.cid)['task']['status'],'unavailable')
 def test_policy_and_course_cache_invalidate_when_prediction_added(self):
  svc=CalibrationService(self.store);first=svc.course('owner',self.cid,True);self.start();second=svc.course('owner',self.cid,True);self.assertGreater(second['prediction_count'],first['prediction_count'])
  policy=svc.policy('owner')
  with patch('mindos.learning.calibration.CalibrationAnalyzer.analyze',side_effect=AssertionError('cached dashboard recomputed')):self.assertEqual(policy,svc.policy('owner'))

 def test_non_finite_evaluation_rejected(self):
  self.model.score=float('nan');task=self.start();result=self.service.submit('owner',self.cid,task['id'],'真实的回答内容。',self.model)['task']['result'];self.assertIsNone(result['score']);self.assertFalse(result['valid_for_calibration'])

class CalibrationTests(unittest.TestCase):
 def samples(self,p,success,n=100,confidence=.8):return [{'prediction':p,'confidence':confidence,'observed':int(i<n*success)} for i in range(n)]
 def test_ece_aligned(self):r=CalibrationAnalyzer().analyze(self.samples(.8,.8));self.assertAlmostEqual(r['calibration_error'],0);self.assertEqual(r['classification'],'well_aligned')
 def test_overestimate(self):self.assertEqual(CalibrationAnalyzer().analyze(self.samples(.9,.5))['classification'],'state_overestimation')
 def test_underestimate(self):self.assertEqual(CalibrationAnalyzer().analyze(self.samples(.4,.8))['classification'],'state_underestimation')
 def test_low_sample(self):self.assertEqual(CalibrationAnalyzer().analyze(self.samples(.9,0,2))['classification'],'insufficient_future_evidence')
 def test_confidence_is_not_success_probability(self):r=CalibrationAnalyzer().analyze(self.samples(.8,.8,confidence=.2));self.assertIn('mean_prediction_error',r['confidence_buckets'][1]);self.assertAlmostEqual(r['brier_score'],.16)
 def test_individual_agreement_and_conflict(self):self.assertEqual(agreement(.86,.82)['classification'],'well_aligned');self.assertEqual(agreement(.91,.35)['reason_code'],'AUTHENTIC_STATE_MISMATCH')
 def test_legacy_version_from_state_payload(self):self.assertEqual(state_policy({'policy_version':'course-final-v1','state_json':json.dumps({'mastery_state':{'state_policy_version':'weighted-evidence-v1'}})}),'weighted-evidence-v1')
 def test_future_windows_policy_separation_independence_and_cached_reads(self):
  with tempfile.TemporaryDirectory() as tmp:
   store=Storage(Path(tmp)/'db');course=seed(store);cid=course['id'];now=datetime.now(timezone.utc);ids={}
   with store.connect() as db:
    for days in [1,7,14,30]:
     s=empty('a1');s['mastery']=.82;s['confidence']=.8;s['policy_version']='weighted-evidence-v1' if days!=14 else 'weighted-evidence-v2';ids[days]=capture_prediction(db,'owner',cid,'a1',s,at=now-timedelta(days=days),salt=str(days))
   grade(store,course,'a1',answer='b',purpose='review',at=now)
   svc=CalibrationService(store);r=svc.course('owner',cid,True)
   self.assertEqual(r['versions']['weighted-evidence-v1']['windows']['7']['independent_mcq']['samples'],1);self.assertEqual(r['versions']['weighted-evidence-v1']['windows']['7']['independent_mcq']['observed'],0)
   self.assertEqual(r['versions']['weighted-evidence-v2']['windows']['14']['independent_mcq']['samples'],1);self.assertEqual(r['versions']['weighted-evidence-v1']['windows']['14']['independent_mcq']['samples'],0)
   with patch.object(svc,'_increment',side_effect=AssertionError('replayed history')):self.assertEqual(r,svc.course('owner',cid,True))
 def test_hint_reuse_immediate_and_before_prediction_excluded(self):
  for flag in ['hint','reuse','immediate','before']:
   with self.subTest(flag=flag),tempfile.TemporaryDirectory() as tmp:
    store=Storage(Path(tmp)/'db');course=seed(store);cid=course['id'];now=datetime.now(timezone.utc)
    with store.connect() as db:
     s=empty('a1');s['mastery']=.8;pid=capture_prediction(db,'owner',cid,'a1',s,at=now+timedelta(days=1) if flag=='before' else now-timedelta(days=7),salt=flag)
    if flag=='immediate':grade(store,course,'a1',at=now-timedelta(hours=1))
    q=grade(store,course,'a1',at=now)
    with store.connect() as db:
     if flag=='hint':db.execute("UPDATE learning_evidence SET hint_used=1 WHERE event_key LIKE ?",('quiz:'+q['id']+':%',))
     if flag=='reuse':
      row=db.execute("SELECT id,metadata_json FROM learning_evidence WHERE event_key LIKE ?",('quiz:'+q['id']+':%',)).fetchone();m=json.loads(row[1]);m['reused_question']=True;db.execute('UPDATE learning_evidence SET metadata_json=? WHERE id=?',(json.dumps(m),row[0]))
    r=CalibrationService(store).course('owner',cid,True)
    samples=r['versions']['weighted-evidence-v1']['windows']['7']['independent_mcq']['samples'];self.assertEqual(samples,0 if flag!='immediate' else 1)
 def test_nearest_outcome_one_sample_per_window(self):
  with tempfile.TemporaryDirectory() as tmp:
   store=Storage(Path(tmp)/'db');course=seed(store);cid=course['id'];now=datetime.now(timezone.utc)
   with store.connect() as db:
    s=empty('a1');s['mastery']=.8;capture_prediction(db,'owner',cid,'a1',s,at=now-timedelta(days=7),salt='nearest')
   grade(store,course,'a1',answer='a',at=now-timedelta(days=1));grade(store,course,'a1',answer='b',at=now)
   r=CalibrationService(store).course('owner',cid,True)['versions']['weighted-evidence-v1']['windows']['7']['independent_mcq'];self.assertEqual(r['samples'],1);self.assertEqual(r['observed'],0)

 def test_same_outcome_does_not_inflate_sample_count(self):
  rows=[{'prediction':.8,'confidence':.8,'observed':0,'outcome_reference':'one-independent-review','atom_id':'a1','window_days':7,'policy_version':'v1','scoring_source':'independent_mcq','delay_days':7+i*.01} for i in range(30)]
  r=CalibrationAnalyzer().analyze(rows);self.assertEqual(r['samples'],1);self.assertEqual(r['classification'],'insufficient_future_evidence')

 def test_shadow_continuous_score_not_reported_as_binary_brier(self):
  r=CalibrationAnalyzer().analyze([{'prediction':.8,'confidence':.9,'observed':.6,'scoring_source':'llm_rubric'}]);self.assertIsNone(r['brier_score']);self.assertAlmostEqual(r['score_mean_squared_error'],.04)
 def test_grouped_mcq_brier_uses_success_and_failure_losses(self):
  r=CalibrationAnalyzer().analyze([{'prediction':.8,'confidence':.9,'observed':.5,'scoring_source':'independent_mcq'}]);self.assertAlmostEqual(r['brier_score'],.34)
