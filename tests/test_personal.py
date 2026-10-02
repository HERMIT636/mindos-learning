import unittest,tempfile,json,sqlite3,copy
from pathlib import Path
from datetime import datetime,timezone,timedelta
from unittest.mock import patch
from mindos.storage import Storage
from mindos.learning.canonical import KnowledgeMappingEngine,POLICY
from mindos.learning.personal import PersonalKnowledgeProfileBuilder,InheritedKnowledgePrior
from mindos.learning.cross_course import CrossCourseVerification
from mindos.learning.state import empty
from mindos.adaptive.teaching_state import LearningStateManager
from mindos.adaptive.atie_engine import ATIEEngine
from personal_fixture import course,train,PersonalModel

class PersonalTests(unittest.TestCase):
 def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.store=Storage(Path(self.tmp.name)/'db');self.model=PersonalModel();self.engine=KnowledgeMappingEngine(self.store)
 def tearDown(self):self.tmp.cleanup()
 def rows(self,cid):return self.engine.list('owner',cid,True)['mappings']
 def states(self,cid):
  with self.store.connect() as db:return [tuple(r) for r in db.execute('SELECT * FROM knowledge_states WHERE course_id=?',(cid,))]
 def pair(self):
  a=course(self.store);train(self.store,a);b=course(self.store,'LLM原理','Query-Key-Value');self.engine.scan('owner',b['id'],self.model);return a,b
 def test_synonym_identity_and_no_new_course_mastery(self):
  a,b=self.pair();self.assertEqual([m for m in self.rows(a['id']) if m['status']=='verified'][0]['canonical_atom_id'],[m for m in self.rows(b['id']) if m['status']=='verified'][0]['canonical_atom_id']);self.assertIsNone(json.loads(self.states(b['id'])[0][3])['mastery'])
  priors=InheritedKnowledgePrior(self.store).list('owner',b['id'])['priors'];self.assertEqual(len(priors),1);self.assertTrue(priors[0]['needs_verification'])
 def test_same_name_different_domain_not_merged(self):
  a=course(self.store,name='Attention');b=course(self.store,'Cognitive Psychology','Attention',summary='人类感觉系统选择感知信息的认知注意机制。');self.engine.scan('owner',b['id'],self.model)
  self.assertNotEqual(next(m for m in self.rows(a['id']) if m['status']=='verified')['canonical_atom_id'],next(m for m in self.rows(b['id']) if m['status']=='verified')['canonical_atom_id']);self.assertFalse(InheritedKnowledgePrior(self.store).list('owner',b['id'])['priors'])
 def test_ambiguous_candidate_excluded_until_user_verifies(self):
  a=course(self.store);b=course(self.store,'LLM新课程',summary='把每个请求写成向量，比较记录索引以寻找匹配，然后取得相关信息。');self.model.confidence=.71;r=self.engine.scan('owner',b['id'],self.model);candidate=next(m for m in r['mappings'] if m['status']=='candidate')
  self.assertFalse(InheritedKnowledgePrior(self.store).list('owner',b['id'])['priors']);self.engine.review('owner',b['id'],candidate['id'],True);self.assertEqual(next(m for m in self.rows(b['id']) if m['id']==candidate['id'])['status'],'verified')
 def test_broader_narrower_related_not_same(self):
  for relation in ['broader','narrower','related']:
   with self.subTest(relation=relation):
    a=course(self.store,'Transformer '+relation);b=course(self.store,'LLM '+relation,summary='比较输入的需求表示和所有条件表示，然后取得需要的结果。');self.model.relationship=relation;r=self.engine.scan('owner',b['id'],self.model);c=next(m for m in r['mappings'] if m['status']=='candidate')
    with self.assertRaises(ValueError):self.engine.review('owner',b['id'],c['id'],True)
 def test_high_confidence_without_consistent_context_stays_candidate(self):
  a=course(self.store);b=course(self.store,'LLM模糊关联')
  with self.store.connect() as db:db.execute('UPDATE sections SET objective=? WHERE course_id=?',('只描述一般的信息选择，缺少具体语义范围',b['id']))
  result=self.engine.scan('owner',b['id'],self.model)
  self.assertFalse(any(m['status']=='verified' for m in result['mappings']));self.assertTrue(any(m['status']=='candidate' for m in result['mappings']))
 def test_mapping_unique_and_revocation_keeps_real_states(self):
  a,b=self.pair();p=InheritedKnowledgePrior(self.store).list('owner',b['id'])['priors'][0];q=CrossCourseVerification(self.store).start('owner',b['id'],p['id'],self.model)['quiz'];self.store.submit_quiz('owner',b['id'],q['id'],['a','a']);before=self.states(b['id']);mid=next(m for m in self.rows(b['id']) if m['status']=='verified')['id'];self.engine.review('owner',b['id'],mid,False)
  self.assertEqual(before,self.states(b['id']));self.assertFalse(InheritedKnowledgePrior(self.store).list('owner',b['id'])['priors'])
  with self.store.connect() as db:self.assertGreater(db.execute('SELECT COUNT(*) FROM canonical_mapping_history WHERE mapping_id=?',(mid,)).fetchone()[0],1)
 def test_verification_actual_diagnostic_evidence_and_old_state_unchanged(self):
  a,b=self.pair();old=self.states(a['id']);p=InheritedKnowledgePrior(self.store).list('owner',b['id'])['priors'][0];q=CrossCourseVerification(self.store).start('owner',b['id'],p['id'],self.model)['quiz'];self.store.submit_quiz('owner',b['id'],q['id'],['a','a']);self.assertEqual(old,self.states(a['id']));self.assertTrue(self.states(b['id']))
  with self.store.connect() as db:
   rows=db.execute('SELECT * FROM learning_evidence WHERE course_id=?',(b['id'],)).fetchall();self.assertEqual({r['evidence_type'] for r in rows if r['result'] in ('correct','wrong')},{'diagnostic_test'});self.assertTrue(all(json.loads(r['metadata_json'])['cross_course_verification'] for r in rows if r['result'] in ('correct','wrong')));self.assertEqual(db.execute('SELECT current_ordinal FROM courses WHERE id=?',(b['id'],)).fetchone()[0],1)
  p=InheritedKnowledgePrior(self.store).list('owner',b['id'])['priors'][0];self.assertEqual(p['status'],'verified_in_course');state,knowledge=LearningStateManager(self.store).read('owner',b['id'],1,'same-local-id');self.assertTrue(state['relevant_personal_prior'])
  from mindos.teaching import TeachingOrchestrator
  scope=TeachingOrchestrator(self.store).context('owner',b['id'],b['sections'][0]['id']);action=ATIEEngine().decide(state,knowledge,scope);self.assertTrue(action['reduce_repeated_basics']);self.assertEqual(action['verified_basics'],['same-local-id'])
 def test_verification_failure_conflict_no_historical_rewrite(self):
  a,b=self.pair();old=self.states(a['id']);p=InheritedKnowledgePrior(self.store).list('owner',b['id'])['priors'][0];q=CrossCourseVerification(self.store).start('owner',b['id'],p['id'],self.model)['quiz'];self.store.submit_quiz('owner',b['id'],q['id'],['b','b']);profile=PersonalKnowledgeProfileBuilder(self.store).profiles('owner',debug=True)['profiles'];self.assertTrue(any(p['cross_course_conflict'] for p in profile));self.assertEqual(old,self.states(a['id']))
 def test_hint_or_reused_not_strong_verification(self):
  a,b=self.pair();p=InheritedKnowledgePrior(self.store).list('owner',b['id'])['priors'][0];q=CrossCourseVerification(self.store).start('owner',b['id'],p['id'],self.model)['quiz'];self.store.submit_quiz('owner',b['id'],q['id'],['a','a'],hint_used=[True,False]);self.assertNotEqual(InheritedKnowledgePrior(self.store).list('owner',b['id'])['priors'][0]['status'],'verified_in_course')
 def test_depth_higher_scope_and_unmeasured_transfer(self):
  a=course(self.store,depth=1);train(self.store,a);b=course(self.store,'Transformer推导','Query-Key-Value',depth=5);self.engine.scan('owner',b['id'],self.model);p=InheritedKnowledgePrior(self.store).list('owner',b['id'])['priors'][0];self.assertNotEqual(p['prior_strength'],'strong');self.assertEqual(p['scope']['covered_dimensions'],['understanding']);self.assertIn('implementation',p['scope']['not_assumed'])
 def test_changed_target_context_invalidates_prior_without_recreating_it(self):
  a,b=self.pair();self.assertTrue(InheritedKnowledgePrior(self.store).list('owner',b['id'])['priors'])
  with self.store.connect() as db:db.execute('UPDATE sections SET objective=? WHERE course_id=?',('新的高级实现目标，与原有语义上下文不同',b['id']))
  self.assertFalse(InheritedKnowledgePrior(self.store).list('owner',b['id'])['priors']);self.assertFalse(InheritedKnowledgePrior(self.store).list('owner',b['id'])['priors'])
 def test_prior_creation_no_evidence_or_state_write(self):
  a,b=self.pair()
  with self.store.connect() as db:count=db.execute('SELECT COUNT(*) FROM learning_evidence').fetchone()[0]
  before=self.states(b['id']);InheritedKnowledgePrior(self.store).list('owner',b['id'])
  with self.store.connect() as db:self.assertEqual(count,db.execute('SELECT COUNT(*) FROM learning_evidence').fetchone()[0])
  self.assertEqual(before,self.states(b['id']))
 def test_owner_isolation(self):
  a=course(self.store);b=course(self.store,user='other');self.assertNotEqual(self.rows(a['id'])[0]['canonical_atom_id'],self.engine.list('other',b['id'])['mappings'][0]['canonical_atom_id'])
  with self.assertRaises(ValueError):self.engine.scan('other',a['id'])
 def test_merge_redirect_split_preserves_identity_history(self):
  a=course(self.store);b=course(self.store,'LLM Different',name='Other Role',summary='用于测试显式用户合并与撤销的独立定义。');ra=next(m for m in self.rows(a['id']) if m['status']=='verified');rb=next(m for m in self.rows(b['id']) if m['status']=='verified');self.engine.merge('owner',rb['canonical_atom_id'],ra['canonical_atom_id']);self.engine.split('owner',b['id'],next(m for m in self.rows(b['id']) if m['status']=='verified')['id']);self.assertNotEqual(next(m for m in self.rows(b['id']) if m['status']=='verified')['canonical_atom_id'],ra['canonical_atom_id'])
 def test_rejected_identity_not_silently_restored_on_rescan(self):
  a,b=self.pair();mid=next(m for m in self.rows(b['id']) if m['status']=='verified');self.engine.review('owner',b['id'],mid['id'],False);self.engine.scan('owner',b['id'],self.model)
  current=next(m for m in self.rows(b['id']) if m['status']=='verified');self.assertNotEqual(current['canonical_atom_id'],mid['canonical_atom_id']);self.assertFalse(InheritedKnowledgePrior(self.store).list('owner',b['id'])['priors'])
 def test_model_schema_failure_retries_then_conservative_fallback(self):
  a=course(self.store);b=course(self.store,'LLM ambiguous',summary='按任务比较索引和需求，读出相关记录。');self.model.invalid=True;self.engine.scan('owner',b['id'],self.model);self.assertEqual(len(self.model.mapping_calls),2);self.assertTrue(any(m['status']=='candidate' for m in self.rows(b['id'])))
 def test_soft_delete_keeps_trace_permanent_delete_removes_source(self):
  a,b=self.pair();self.store.recycle_course('owner',a['id']);p=PersonalKnowledgeProfileBuilder(self.store).profiles('owner',debug=True)['profiles'];self.assertTrue(any(s['source_course_deleted'] for x in p for s in x['sources']));self.store.purge_course('owner',a['id'],a['title']);self.assertFalse(InheritedKnowledgePrior(self.store).list('owner',b['id'])['priors'])
 def test_copy_does_not_copy_mastery_or_prior(self):
  a=course(self.store);train(self.store,a);b=self.store.copy_course('owner',a['id']);self.assertEqual(self.states(b['id']),[])
 def test_scan_idempotent(self):
  a=course(self.store);before=self.rows(a['id']);self.engine.scan('owner',a['id'],self.model);self.assertEqual(before,self.rows(a['id']));self.assertEqual(self.model.mapping_calls,[])

class ProfileRulesTests(unittest.TestCase):
 def source(self,cid='a',mastery=.85,confidence=.9,days=0):
  s=empty('atom');s.update(mastery=mastery,confidence=confidence,understanding=mastery,application=mastery,transfer=mastery,retention=mastery,last_graded_evidence_at=(datetime.now(timezone.utc)-timedelta(days=days)).isoformat());return {'course_id':cid,'course_atom_id':'atom','course_title':cid,'mapping_confidence':1,'independent_evidence':24,'state':s,'depth':2,'source_course_deleted':False}
 def compute(self,sources,cal={}):return PersonalKnowledgeProfileBuilder(None).compute({'id':'canonical','canonical_name':'QKV','domain':'machine_learning'},sources,cal)
 def test_diversity_increases_support(self):a=self.compute([self.source()]);b=self.compute([self.source(),self.source('b')]);self.assertGreater(b['confidence'],a['confidence']);self.assertEqual(b['support_level'],'strong')
 def test_same_course_contribution_capped(self):a=self.compute([self.source()]);b=self.compute([self.source() for i in range(30)]);self.assertAlmostEqual(a['confidence'],b['confidence'])
 def test_cross_course_conflict_explicit(self):p=self.compute([self.source(mastery=.92),self.source('b',mastery=.42)]);self.assertTrue(p['cross_course_conflict']);self.assertEqual(p['support_level'],'conflicted')
 def test_stale_and_unknown(self):self.assertEqual(self.compute([self.source(days=90)])['support_level'],'stale');self.assertEqual(self.compute([])['support_level'],'unknown')
 def test_calibration_reduces_trust_not_estimated_mastery(self):
  a=self.compute([self.source()]);b=self.compute([self.source()],{'a':{'versions':{'weighted-evidence-v1':{'atoms':{'atom':{'7':{'independent_mcq':{'classification':'state_overestimation'}}}}}}}});self.assertEqual(a['mastery_estimate'],b['mastery_estimate']);self.assertLess(b['confidence'],a['confidence'])
