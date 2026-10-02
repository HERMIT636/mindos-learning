import unittest,tempfile,json,copy,sqlite3,hashlib,subprocess
from pathlib import Path
from datetime import timedelta
from unittest.mock import patch
from mindos.storage import Storage
from mindos.learning.growth import GrowthService,fields
from mindos.learning.growth_graph import validate,order,GoalCapabilityMatcher,TargetCapabilityGenerator
from mindos.learning.growth_gap import GrowthInputReader,GapAnalysisEngine,GoalCompletionAnalyzer
from mindos.learning.growth_planner import GrowthPlanner
from mindos.learning.policy import clock,iso
from mindos.learning.canonical import KnowledgeMappingEngine
from mindos.learning.personal import PersonalKnowledgeProfileBuilder
from growth_fixture import GrowthModel,graph,requirement,browser_seed
from personal_fixture import PersonalModel,course,train
from final_fixture import grade
from authentic_fixture import AuthenticModel
from mindos.learning.authentic import AuthenticAssessmentService

class GrowthTests(unittest.TestCase):
 def setUp(self):self.temp=tempfile.TemporaryDirectory();self.store=Storage(Path(self.temp.name)/'db');self.service=GrowthService(self.store);self.model=GrowthModel()
 def tearDown(self):self.temp.cleanup()
 def goal(self,raw=None,**kwargs):return (GrowthModel(raw) if raw else self.model).growth_goal(self.store,**kwargs)[1]
 def read_only_snapshot(self):
  with self.store.connect() as db:
   tables=[r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name") if not r[0].startswith(('growth_','learning_goals','goal_capability_'))]
   return {t:[tuple(r) for r in db.execute('SELECT * FROM '+t)] for t in tables}
 def task(self,gid):return self.service.roadmap('owner',gid)['roadmap']['tasks'][0]
 def synthetic(self,status='sufficient',level='application',kind='knowledge'):
  gid=self.goal(graph([requirement(level=level,kind=kind)]));g,inp,a,_=self.service._analysis('owner',gid);cid=g['graph']['capabilities'][0]['id'];gap=a['gaps'][0];gap.update(status=status,reason_code={'stale':'GOAL_GAP_STALE','conflicted':'GOAL_GAP_CONFLICT','partial':'GOAL_GAP_PARTIAL','practice_missing':'GOAL_GAP_PRACTICE_MISSING','ready_to_verify':'VERIFY_EXISTING_KNOWLEDGE'}.get(status,'CAPABILITY_VERIFIED'),canonical_atom_id='canon',coverage=[{'course_id':'c','atom_id':'a','section':1,'unlocked':True,'deleted':False,'course_status':'active'}],all_coverage=[])
  inp.update(courses={'c':{'id':'c','deleted_at':None,'status':'active','sort_order':0}},finals={'c':{'completion':{'eligible':False},'mastery_state':{'status':'not_assessed'}}});return g,inp,a,cid
 def test_goal_lifecycle_default_and_cascade_boundary(self):
  c=course(self.store);gid=self.goal();g=self.service.goal('owner',gid);self.assertEqual(g['target_level'],'practical_understanding');v=g['goal_model_version'];self.service.generate('owner',gid)
  self.service.update('owner',gid,{'status':'paused'});self.assertFalse(self.service.dashboard('owner')['goals']);self.assertEqual(self.service.goal('owner',gid)['goal_model_version'],v)
  self.service.update('owner',gid,{'status':'active'});self.service.update('owner',gid,{'description':'目标范围发生变化'});self.assertEqual(self.service.goal('owner',gid)['goal_model_version'],v+1);self.assertEqual(self.service.roadmap('owner',gid)['roadmap']['status'],'stale');self.service.delete('owner',gid);self.assertTrue(self.store.course('owner',c['id']))
 def test_goal_owner_and_client_cannot_set_achieved(self):
  gid=self.goal()
  for op in [lambda:self.service.goal('other',gid),lambda:self.service.delete('other',gid),lambda:self.service.update('owner',gid,{'status':'achieved'}),lambda:self.service.create('owner',{'title':'a','mastery':1})]:
   with self.assertRaises(ValueError):op()
 def test_goal_field_validation(self):
  for d in [{'title':''},{'title':'x','deadline':'2026-99-01'},{'title':'x','priority':True},{'title':'x','weekly_time_budget_minutes':-1}]:
   with self.assertRaises(ValueError):fields(d)
 def test_hard_cycle_and_unknown_dependency_rejected(self):
  for edges in [[{'from':'A','to':'B','relation':'prerequisite'},{'from':'B','to':'A','relation':'prerequisite'}],[{'from':'A','to':'X','relation':'prerequisite'}]]:
   with self.assertRaises(ValueError):validate(graph([requirement('A'),requirement('B')],edges))
 def test_soft_cycle_ignored_and_hard_order_preserved(self):
  g=validate(graph([requirement('A'),requirement('B')],[{'from':'A','to':'B','relation':'prerequisite'},{'from':'B','to':'A','relation':'recommended_before'}]));self.assertEqual(len(g['ignored_soft_edges']),1);self.assertEqual([next(c['name'] for c in g['capabilities'] if c['id']==cid) for cid in order(g)],['A','B'])
 def test_schema_extra_mastery_repair_and_fallback(self):
  model=GrowthModel();model.raw['capabilities'][0]['mastery']=1;g=TargetCapabilityGenerator().generate({'title':'LLM目标','description':'测试','goal_type':'custom','target_level':'application'},model);self.assertEqual(g['source'],'editable_rule_fallback');self.assertEqual(len(model.capability_calls),2);self.assertNotIn('mastery',g['capabilities'][0]);self.assertTrue(g['failure_reason'])
 def test_requirement_model_never_receives_user_profile(self):
  self.goal();payload=self.model.capability_calls[0];self.assertEqual(set(payload['goal']),{'title','description','goal_type','target_level'});self.assertNotIn('profiles',payload)
 def test_capability_custom_delete_override_and_cas(self):
  gid=self.goal(graph([requirement(),requirement('可选知识',importance='optional')]));g=self.service.analyze('owner',gid,self.model)['goal'];raw=graph([requirement(),requirement('我的能力',importance='supporting')]);self.service.analyze('owner',gid,self.model,{'confirm':True,'draft_version':g['draft_version'],'graph':raw});confirmed=self.service.goal('owner',gid);self.assertIn('可选知识',confirmed['user_overrides']);self.assertTrue(all(c['user_override'] for c in confirmed['graph']['capabilities']))
  with self.assertRaises(ValueError):self.service.analyze('owner',gid,payload={'confirm':True,'draft_version':g['draft_version']})
 def test_candidate_does_not_count_coverage(self):
  c=course(self.store);train(self.store,c);gid=self.goal(graph([dict(requirement(),description='用于信息选择的一种表示方法。')]))
  maps=self.service.mappings('owner',gid);self.assertEqual(maps[0]['status'],'candidate');a=self.service.gaps('owner',gid);self.assertEqual(a['gaps'][0]['status'],'unknown');self.assertFalse(a['gaps'][0]['coverage']);self.service.generate('owner',gid);self.assertEqual(self.task(gid)['reason_code'],'MAPPING_REVIEW_REQUIRED')
 def test_no_profile_missing_and_no_learning_writes(self):
  gid=self.goal();before=self.read_only_snapshot();self.service.gaps('owner',gid);r=self.service.generate('owner',gid);self.assertEqual(self.service.gaps('owner',gid)['gaps'][0]['status'],'missing');self.service.task_action('owner',gid,r['roadmap']['tasks'][0]['id'],'skip');self.service.evaluate('owner',gid);self.service.dashboard('owner');self.assertEqual(before,self.read_only_snapshot())
 def test_matching_reuses_existing_course_and_future_section(self):
  c=course(self.store);gid=self.goal();self.service.generate('owner',gid);self.assertEqual(self.task(gid)['task_type'],'continue_course')
  g,inp,a,_=self.synthetic('partial');a['gaps'][0]['coverage'][0]['unlocked']=False;p=GrowthPlanner().build(g,g['graph'],a,inp);self.assertEqual(p['tasks'][0]['task_type'],'continue_course');self.assertTrue(p['tasks'][0]['metadata']['future_topic'])
 def test_dependency_chain_blocks_successors_and_pin_cannot_bypass(self):
  raw=graph([requirement('A'),requirement('B'),requirement('C')],[{'from':a,'to':b,'relation':'prerequisite'} for a,b in [('A','B'),('B','C')]]);gid=self.goal(raw);r=self.service.generate('owner',gid)['roadmap'];self.assertEqual([t['title'] for t in r['tasks']],['A','B','C']);self.assertEqual([t['status'] for t in r['tasks']],['ready','blocked','blocked']);t=r['tasks'][1];self.service.task_action('owner',gid,t['id'],'pin',{'enabled':True})
  with self.assertRaises(ValueError):self.service.task_action('owner',gid,t['id'],'start')
 def test_gap_classification_and_routing_cases(self):
  for status,expected in [('stale','review'),('conflicted','cross_course_verify'),('ready_to_verify','cross_course_verify'),('partial','continue_course'),('sufficient','goal_checkpoint'),('practice_missing','authentic_assessment')]:
   with self.subTest(status=status):
    g,inp,a,_=self.synthetic(status,kind='practice' if status=='practice_missing' else 'knowledge');plan=GrowthPlanner().build(g,g['graph'],a,inp);self.assertEqual(plan['tasks'][0]['task_type'],expected)
 def test_final_pending_overrides_partial_course_and_stage_gate(self):
  g,inp,a,_=self.synthetic('partial');inp['finals']['c']['completion']['eligible']=True;plan=GrowthPlanner().build(g,g['graph'],a,inp);self.assertEqual(plan['tasks'][0]['task_type'],'final_assessment');a['gaps'][0]['status']='sufficient';self.assertFalse(GoalCompletionAnalyzer().analyze(g,g['graph'],a,inp)['achieved']);inp['finals']['c']['mastery_state']['status']='mastered';self.assertTrue(GoalCompletionAnalyzer().analyze(g,g['graph'],a,inp)['achieved'])
 def test_unmeasured_transfer_uses_open_task(self):
  g,inp,a,_=self.synthetic('partial',level='transfer');a['gaps'][0]['reason_code']='GOAL_GAP_TRANSFER_UNVERIFIED';plan=GrowthPlanner().build(g,g['graph'],a,inp);self.assertEqual(plan['tasks'][0]['task_type'],'authentic_assessment');self.assertEqual(plan['tasks'][0]['metadata']['assessment'],'open_transfer')
 def test_real_p3_conflict_and_stale_adapters(self):
  a=course(self.store);train(self.store,a);b=course(self.store,'LLM第二课程');train(self.store,b);KnowledgeMappingEngine(self.store).scan('owner',b['id'],PersonalModel());gid=self.goal();g,inp,analysis,_=self.service._analysis('owner',gid);identity=analysis['gaps'][0]['canonical_atom_id'];self.assertTrue(identity)
  p=inp['profiles'][identity];p.update(cross_course_conflict=True);self.assertEqual(GapAnalysisEngine().analyze(g,g['graph'],self.service.mappings('owner',gid,True),inp)['gaps'][0]['status'],'conflicted');p.update(cross_course_conflict=False,support_level='stale');self.assertEqual(GapAnalysisEngine().analyze(g,g['graph'],self.service.mappings('owner',gid,True),inp)['gaps'][0]['status'],'stale')
 def test_only_understanding_is_partial_not_invented_application(self):
  c=course(self.store);grade(self.store,c,'same-local-id');gid=self.goal();a=self.service.gaps('owner',gid);self.assertEqual(a['gaps'][0]['status'],'partial');self.assertEqual(a['gaps'][0]['required_level'],'application')
 def test_mixed_partial_missing_conflict_respects_dependency(self):
  raw=graph([requirement('KV Cache'),requirement('GPU Memory'),requirement('Roofline')],[{'from':'GPU Memory','to':'Roofline','relation':'prerequisite'}]);gid=self.goal(raw);g,inp,a,_=self.service._analysis('owner',gid);a['gaps'][0].update(status='partial');a['gaps'][1].update(status='conflicted');p=GrowthPlanner().build(g,g['graph'],a,inp);positions={t['title']:i for i,t in enumerate(p['tasks'])};self.assertLess(positions['GPU Memory'],positions['Roofline']);self.assertEqual(next(t for t in p['tasks'] if t['title']=='Roofline')['status'],'blocked')
 def test_deadline_optional_prerequisite_retained_and_budget(self):
  raw=graph([requirement('A',importance='optional'),requirement('B'),requirement('C',importance='optional')],[{'from':'A','to':'B','relation':'prerequisite'}]);gid=self.goal(raw,deadline=(clock().date()+timedelta(days=2)).isoformat(),weekly_time_budget_minutes=120);r=self.service.generate('owner',gid)['roadmap'];self.assertFalse(r['tasks'][0]['metadata'].get('deadline_deferred_optional'));self.assertTrue(next(t for t in r['tasks'] if t['title']=='C')['metadata']['deadline_deferred_optional']);today=self.service.dashboard('owner');self.assertLessEqual(len(today['today']),3);self.assertLessEqual(sum(t['planned_minutes'] for t in today['weekly']),120);self.assertLessEqual(sum(t['planned_minutes'] for t in today['today']),24)
 def test_version_history_and_user_choices_preserved(self):
  gid=self.goal();first=self.service.generate('owner',gid)['roadmap'];t=first['tasks'][0];self.service.task_action('owner',gid,t['id'],'skip');self.service.task_action('owner',gid,t['id'],'lock',{'enabled':True});second=self.service.generate('owner',gid)['roadmap'];self.assertEqual(second['version'],2);self.assertEqual(second['tasks'][0]['status'],'skipped');self.assertTrue(second['tasks'][0]['locked']);self.assertEqual(self.service.roadmap('owner',gid,1)['roadmap']['status'],'superseded');self.assertFalse(self.service.gaps('owner',gid)['completion']['achieved']);self.assertEqual(self.service.roadmap('owner',gid)['changes'][0]['reason_codes'],['USER_REQUESTED_REPLAN'])
 def test_automatic_replan_throttle_and_goal_change_stale(self):
  gid=self.goal();self.service.generate('owner',gid);self.assertTrue(self.service.generate('owner',gid,automatic=True)['throttled']);self.service.update('owner',gid,{'target_level':'transfer'})
  with self.assertRaises(ValueError):self.service.generate('owner',gid,automatic=True)
 def test_soft_deleted_and_purged_course_task_blocked(self):
  c=course(self.store);gid=self.goal();self.service.generate('owner',gid);t=self.task(gid);self.store.recycle_course('owner',c['id']);self.service.evaluate('owner',gid,False);self.assertEqual(self.task(gid)['status'],'blocked');self.assertIn('回收站',self.task(gid)['metadata']['blocked_note']);self.store.purge_course('owner',c['id'],c['title']);self.service.evaluate('owner',gid,False);self.assertEqual(self.task(gid)['status'],'blocked')
 def test_course_copy_has_no_growth_link(self):
  c=course(self.store);gid=self.goal();self.service.generate('owner',gid);copied=self.store.copy_course('owner',c['id'],'LLM副本');self.assertFalse(self.service.context('owner',copied['id']))
 def test_successful_real_quiz_updates_roadmap_without_advancing_course(self):
  current=browser_seed(self.store,'owner');gid=self.goal();r=self.service.generate('owner',gid)['roadmap'];t=r['tasks'][0];self.assertEqual(t['task_type'],'cross_course_verify');self.assertEqual(t['target_id'],current['id']);self.service.task_action('owner',gid,t['id'],'start');from mindos.learning.service import LearningLoopService
  q=LearningLoopService(self.store).assessment('owner',current['id'],'same-local-id','diagnostic',self.model)
  self.store.submit_quiz('owner',current['id'],q['id'],['a','a'])
  self.assertEqual(self.service.gaps('owner',gid)['gaps'][0]['status'],'sufficient')
  with self.store.connect() as db:db.execute('UPDATE growth_roadmaps SET created_at=? WHERE id=?',(iso(clock()-timedelta(seconds=601)),r['id']))
  v2=self.service.evaluate('owner',gid);self.assertTrue(v2['route_updated']);self.assertEqual(v2['roadmap']['version'],2);self.assertEqual(self.store.course('owner',current['id'])['current_ordinal'],1)
 def test_debug_and_bounded_context_do_not_leak_internal_scores(self):
  c=course(self.store);gid=self.goal();self.service.generate('owner',gid);t=self.task(gid);self.service.task_action('owner',gid,t['id'],'start');context=self.service.context('owner',c['id']);self.assertEqual(set(context),{'goal_title','current_stage_objective','current_task_relevance'});self.assertNotIn('debug',self.service.gaps('owner',gid)['gaps'][0]);self.assertIn('debug',self.service.gaps('owner',gid,True)['gaps'][0])
 def test_goal_practice_requires_own_qualified_artifact(self):
  current=browser_seed(self.store,'owner');raw=graph([requirement(),requirement('小型信息匹配设计',kind='practice')],[{'from':'QKV','to':'小型信息匹配设计','relation':'prerequisite'}]);gid=self.goal(raw,goal_type='project')
  # More independent successes satisfy the application prerequisite in the current depth.
  train(self.store,current,n=9);r=self.service.generate('owner',gid)['roadmap'];t=next(t for t in r['tasks'] if t['task_type']=='authentic_assessment');self.service.task_action('owner',gid,t['id'],'start');context=self.service.practice_context('owner',gid,t['id'],t['target_id'],'same-local-id');am=AuthenticModel(.9);a=AuthenticAssessmentService(self.store).start('owner',t['target_id'],'same-local-id','design',am,growth_context=context)['task'];self.service.attach_authentic('owner',gid,t['id'],a['id']);AuthenticAssessmentService(self.store).submit('owner',t['target_id'],a['id'],'需求用于匹配，比较工具能力后取得借用说明，并检查使用范围。',am);gaps=self.service.gaps('owner',gid);self.assertEqual(next(g for g in gaps['gaps'] if g['type']=='practice')['status'],'sufficient')
 def test_created_course_link_reused_without_claiming_coverage(self):
  gid=self.goal();self.service.generate('owner',gid);t=self.task(gid);self.service.task_action('owner',gid,t['id'],'start');c=course(self.store,'目标新课程');self.service.link_course('owner',gid,t['id'],c['id']);route=self.service.task_action('owner',gid,t['id'],'start')['route'];self.assertEqual(route['course_id'],c['id']);self.assertEqual(route['destination'],'course');self.service.generate('owner',gid);self.assertEqual(self.task(gid)['task_type'],'continue_course');self.assertEqual(self.service.gaps('owner',gid)['gaps'][0]['status'],'missing')
  self.service.refresh_mappings('owner',gid,self.model);self.assertEqual(self.service.roadmap('owner',gid)['roadmap']['status'],'stale');self.service.generate('owner',gid);self.assertEqual(self.task(gid)['target_id'],c['id'])
 def test_requirement_change_needs_confirmation_and_records_cause(self):
  gid=self.goal();self.service.generate('owner',gid);self.service.update('owner',gid,{'description':'改变具体应用要求'});self.assertTrue(self.service.goal('owner',gid)['requirements_stale']);self.assertFalse(self.service.gaps('owner',gid)['completion']['achieved'])
  with self.assertRaises(ValueError):self.service.generate('owner',gid)
  draft=self.service.analyze('owner',gid,self.model)['goal'];self.service.analyze('owner',gid,self.model,{'confirm':True,'draft_version':draft['draft_version']});self.service.generate('owner',gid);self.assertEqual(self.service.roadmap('owner',gid)['changes'][0]['reason_codes'],['GOAL_CHANGED'])
 def test_malformed_manual_capability_is_user_error(self):
  gid=self.goal();g=self.service.analyze('owner',gid,self.model)['goal']
  with self.assertRaises(ValueError):self.service.analyze('owner',gid,payload={'confirm':True,'draft_version':g['draft_version'],'graph':{'capabilities':[]}})
 def test_mapping_refresh_preserves_user_rejection(self):
  c=course(self.store);gid=self.goal(graph([dict(requirement(),description='用于信息选择的表示方法')]))
  mid=self.service.mappings('owner',gid)[0]['id'];self.service.review_mapping('owner',gid,mid,False);self.service.refresh_mappings('owner',gid,self.model);self.assertEqual(self.service.mappings('owner',gid)[0]['status'],'rejected')
 def test_model_cannot_reorder_program_priority_across_stages(self):
  class WrongStages(GrowthModel):
   def growth_stages(self,p):return {'stages':[{'title':'模型私自调整','objective':'不允许','capability_ids':[cid]} for cid in reversed(p['program_order'])]}
  g=validate(graph([requirement('A'),requirement('B')]));sequence=order(g);stages,source=GrowthPlanner().stages({'title':'目标'},g,sequence,WrongStages());self.assertEqual(source,'rule_organization');self.assertEqual([c for s in stages for c in s['capability_ids']],sequence)
 def test_optional_prerequisite_still_required_for_goal_completion(self):
  raw=graph([requirement('A',importance='optional'),requirement('B')],[{'from':'A','to':'B','relation':'prerequisite'}]);gid=self.goal(raw);g,inp,a,_=self.service._analysis('owner',gid);a['gaps'][1]['status']='sufficient';self.assertTrue(a['gaps'][0]['required_for_critical']);self.assertFalse(GoalCompletionAnalyzer().analyze(g,g['graph'],a,inp)['achieved'])
 def test_unselected_historical_course_final_does_not_block_current_goal(self):
  g,inp,a,cid=self.synthetic('sufficient');inp['finals']['c']={'completion':{'eligible':True},'mastery_state':{'status':'mastered'}};inp['finals']['old']={'completion':{'eligible':True},'mastery_state':{'status':'not_assessed'}};a['gaps'][0]['coverage'].append({'course_id':'old','atom_id':'a','section':1,'unlocked':True,'deleted':False,'course_status':'active'});self.assertTrue(GoalCompletionAnalyzer().analyze(g,g['graph'],a,inp)['achieved']);self.assertEqual(GrowthPlanner().build(g,g['graph'],a,inp)['tasks'][0]['task_type'],'goal_checkpoint')
 def test_restored_capability_not_silently_removed_next_analysis(self):
  gid=self.goal(graph([requirement(),requirement('可选知识',importance='optional')]));g=self.service.analyze('owner',gid,self.model)['goal'];self.service.analyze('owner',gid,self.model,{'confirm':True,'draft_version':g['draft_version'],'graph':graph([requirement()])});model=GrowthModel(graph([requirement(),requirement('可选知识',importance='optional')]));draft=self.service.analyze('owner',gid,model)['goal'];self.service.analyze('owner',gid,model,{'confirm':True,'draft_version':draft['draft_version'],'graph':model.raw});again=self.service.analyze('owner',gid,model)['goal'];self.assertIn('可选知识',[c['name'] for c in again['draft']['capabilities']])
 def test_frozen_policies_match_baseline_commit(self):
  root=Path(__file__).resolve().parents[1]
  frozen={'state.py': '4c8fd399d6931ff84f86dbb059c41088e0fe9f067f6bf69b4da05a4dcda87a5c', 'learning_policy.json': '6fadff4ea74d7ffad3fc3be5c323bef1aa24efe02e910eba886d4cb735098fbd', 'course_mastery.py': '299ca4fc2450586882c2f24a76eb76721da0680fbc7496683ffe72a98b2beb51', 'final_policy.json': 'd16ad38855194c0410e0fae45e838ee378fa76bf84bf4fccd93197655cf6cabc', 'calibration.py': '606f85bfb96d7c1d73837db638845f611e18ca05493127de4ae7eb26e3fd50de', 'calibration_policy.json': '6da6412e2226d8cd2225a2a43bbdf8be61ca01660e28369e3c1a7c9326cb837e', 'personal.py': '029aef62de961c0000e7edea4eded01ea2fde0cb10bea3d075383f2a595cadba', 'canonical.py': 'ef347e2b8615369fba2483bc6960727bf3dd67f92c8fbdc9cc6b4e69ea0b3969', 'personal_knowledge_policy.json': '7df6ffc9b17cf50ca211c154dee9ea08c3e06dc16f58ad44bfe9d4625f8010e4'}
  for f,expected in frozen.items():
   path='mindos/learning/'+f;self.assertEqual(hashlib.sha256((root/path).read_bytes()).hexdigest(),expected,path)
