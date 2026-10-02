"""P5 synthetic clocks and owned records; execution never stands in for learning evidence."""
import unittest,tempfile,json,hashlib,math
from pathlib import Path
from datetime import datetime,timedelta,timezone
from concurrent.futures import ThreadPoolExecutor
from mindos.storage import Storage
from mindos.learning.execution import StudySessionService,POLICY
from mindos.learning.pace import PersonalPaceModel,DurationEstimator
from mindos.learning.execution_planner import AdaptiveDailyLoadPlanner,PlanRealityAnalyzer,DeadlineFeasibilityAnalyzer
from mindos.learning.growth import GrowthService
from personal_fixture import course,train
from growth_fixture import GrowthModel,browser_seed

class ExecutionTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.store=Storage(Path(self.temp.name)/'test.sqlite3');self.at=datetime(2026,10,2,0,0,tzinfo=timezone.utc);self.svc=StudySessionService(self.store,lambda:self.at);self.c=course(self.store);self.pace=PersonalPaceModel(self.store)
 def start(self,**kw):return self.svc.start('owner',{'course_id':self.c['id'],**kw})['session']
 def advance(self,minutes):self.at+=timedelta(minutes=minutes)
 def end(self,s,minutes=20,**kwargs):
  self.advance(minutes);return self.svc.action('owner',s['id'],'end',{'completion':'done','reason':'finished',**kwargs})['session']
 def sample(self,planned=20,actual=28,kind='course_learning',**kwargs):
  s=self.start(planned_minutes=planned,activity_type=kind);return self.end(s,actual,**kwargs)
 def frozen(self):
  with self.store.connect() as db:
   names=[r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'") if r[0] not in {'study_sessions','task_execution_events','pace_snapshots'}]
   return {n:[tuple(r) for r in db.execute('SELECT * FROM '+n)] for n in names}
 def task(self,**kwargs):
  current=browser_seed(self.store,'owner');model=GrowthModel();svc,gid=model.growth_goal(self.store,'owner',**kwargs);plan=svc.generate('owner',gid)['roadmap'];t=plan['tasks'][0];svc.task_action('owner',gid,t['id'],'start');return svc,gid,t,current
 def item(self,kind='continue_course',base=20,**kwargs):return {'title':'KV Cache','reason':'补齐当前能力','task_type':kind,'course_id':self.c['id'],'estimated_minutes':base,**kwargs}
 def goal(self,gid='g1',budget=300,priority=1):return {'id':gid,'weekly_time_budget_minutes':budget,'priority':priority,'deadline':None}
 def plan(self,items,goals=None):return AdaptiveDailyLoadPlanner(self.store,lambda:self.at).build('owner',goals or [],items)
 def test_open_page_does_not_start(self):
  self.assertIsNone(self.svc.current('owner')['session']);self.store.course('owner',self.c['id']);self.assertEqual(self.svc.history('owner')['sessions'],[])
 def test_pause_resume_time_scenario_27_and_10(self):
  s=self.start(planned_minutes=20);self.advance(15);self.svc.action('owner',s['id'],'pause');self.advance(10);self.svc.action('owner',s['id'],'resume');r=self.end(s,12);self.assertEqual(r['active_seconds'],27*60);self.assertEqual(r['paused_seconds'],10*60)
 def test_only_one_active_concurrent(self):
  def start():
   try:return self.start()['id']
   except ValueError:return None
  with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(lambda _:start(),range(2)))
  self.assertEqual(sum(r is not None for r in results),1)
 def test_paused_session_not_stranded(self):
  s=self.start();self.svc.action('owner',s['id'],'pause')
  with self.assertRaises(ValueError):self.start()
  self.assertEqual(self.svc.current('owner')['session']['status'],'paused')
 def test_database_unique_active_constraint(self):
  s=self.start()
  import sqlite3
  with self.store.connect() as db:
   names=[r[1] for r in db.execute('PRAGMA table_info(study_sessions)')];values=[db.execute('SELECT '+n+' FROM study_sessions WHERE id=?',(s['id'],)).fetchone()[0] for n in names];values[0]='second'
   with self.assertRaises(sqlite3.IntegrityError):db.execute('INSERT INTO study_sessions VALUES('+','.join('?' for _ in names)+')',values)
 def test_refresh_restores_without_duplicate_start(self):
  s=self.start();self.advance(8);r=StudySessionService(self.store,lambda:self.at).current('owner')['session'];self.assertEqual(r['id'],s['id']);self.assertEqual(r['active_seconds'],480)
 def test_stale_session_offline_time_not_added(self):
  s=self.start();self.advance(15);self.svc.action('owner',s['id'],'checkpoint');self.advance(181);r=self.svc.current('owner')['session'];self.assertEqual(r['status'],'interrupted');self.assertEqual(r['active_seconds'],900);self.svc.action('owner',s['id'],'resume');r=self.end(s,12);self.assertEqual(r['active_seconds'],1620);self.assertEqual(r['was_interrupted'],1);self.assertEqual(self.pace.eligible(r),'interrupted')
 def test_end_stale_direct_cannot_count_offline(self):
  s=self.start();self.advance(500);r=self.svc.action('owner',s['id'],'end',{'completion':'done'});self.assertEqual(r['session']['active_seconds'],0);self.assertEqual(r['session']['was_interrupted'],1)
 def test_user_adjustment_and_events(self):
  s=self.start();r=self.end(s,40,adjusted_active_minutes=20);self.assertEqual(r['active_seconds'],1200);self.assertTrue(r['adjusted_by_user']);self.assertIsNone(self.pace.eligible(r))
  with self.store.connect() as db:events=[r[0] for r in db.execute('SELECT event_type FROM task_execution_events WHERE session_id=?',(s['id'],))]
  self.assertIn('started',events);self.assertIn('completed',events);self.assertIn('adjusted',events)
 def test_invalid_duration_and_scores_rejected_atomically(self):
  s=self.start()
  for v in [-1,float('nan'),float('inf'),1441,'20',True]:
   with self.assertRaises(ValueError):self.svc.action('owner',s['id'],'end',{'adjusted_active_minutes':v})
  with self.assertRaises(ValueError):self.svc.action('owner',s['id'],'end',{'mastery':1})
  self.assertEqual(self.svc.current('owner')['session']['status'],'active')
 def test_long_session_needs_confirmation_and_excluded(self):
  s=self.start()
  for _ in range(5):self.advance(60);self.svc.action('owner',s['id'],'checkpoint')
  with self.assertRaises(ValueError):self.svc.action('owner',s['id'],'end',{'completion':'done'})
  r=self.svc.action('owner',s['id'],'end',{'completion':'done','confirm_long_duration':True})['session'];self.assertEqual(self.pace.eligible(r),'unreasonable_duration')
 def test_interrupted_can_end_and_adjust(self):
  s=self.start();self.advance(190);self.svc.current('owner');r=self.svc.action('owner',s['id'],'end',{'completion':'partial','adjusted_active_minutes':7})['session'];self.assertEqual(r['active_seconds'],420)
 def test_idempotent_pause_resume_and_end(self):
  s=self.start();self.svc.action('owner',s['id'],'pause');self.svc.action('owner',s['id'],'pause');self.svc.action('owner',s['id'],'resume');self.svc.action('owner',s['id'],'resume');a=self.end(s,20);b=self.svc.action('owner',s['id'],'end')['session'];self.assertEqual(a['active_seconds'],b['active_seconds'])
 def test_owner_course_atom_isolation(self):
  with self.assertRaises(ValueError):self.svc.start('other',{'course_id':self.c['id']})
  with self.assertRaises(ValueError):self.start(atom_id='fake')
  s=self.start()
  with self.assertRaises(ValueError):self.svc.action('other',s['id'],'pause')
  self.assertEqual(self.svc.history('other')['sessions'],[]);self.assertIsNone(self.svc.current('other')['session'])
 def test_session_end_never_completes_task(self):
  growth,gid,t,c=self.task();before=growth.gaps('owner',gid);s=self.svc.start('owner',{'growth_task_id':t['id']})['session'];self.end(s,27);after=growth.gaps('owner',gid);self.assertEqual(before,after);self.assertEqual(growth.roadmap('owner',gid)['roadmap']['tasks'][0]['status'],'active')
 def test_task_scope_from_server_and_old_version_blocked(self):
  growth,gid,t,c=self.task()
  with self.assertRaises(ValueError):self.svc.start('owner',{'growth_task_id':t['id'],'course_id':c['id'] if c['id']!=t['target_id'] else self.c['id']})
  growth.generate('owner',gid)
  with self.assertRaises(ValueError):self.svc.start('owner',{'growth_task_id':t['id']})
 def test_mastery_isolation_many_actions(self):
  train(self.store,self.c,n=4);before=self.frozen();s=self.start()
  for _ in range(6):self.advance(5);self.svc.action('owner',s['id'],'pause');self.advance(4);self.svc.action('owner',s['id'],'resume')
  self.end(s,20);self.sample(actual=1);s=self.start();self.end(s,5,completion='not_started',reason='blocked');self.pace.profiles('owner');self.assertEqual(before,self.frozen())
 def test_learning_outcome_observation_does_not_add_evidence(self):
  s=self.start();train(self.store,self.c,n=2);before=self.frozen();r=self.end(s,5);self.assertEqual(r['outcome']['quiz_count'],2);self.assertTrue(r['outcome']['knowledge_state_changed']);self.assertEqual(before,self.frozen())
 def test_pace_insufficient_samples_rule_fallback(self):
  self.sample();self.sample();r=DurationEstimator(self.store,'owner').predict(20,'course_learning');self.assertEqual(r['predicted_minutes'],20);self.assertEqual(r['pace_reason'],'PACE_LOW_SAMPLE')
 def test_pace_median_scenario_28(self):
  for actual in [26,28,30]:self.sample(actual=actual)
  r=DurationEstimator(self.store,'owner').predict(20,'course_learning');self.assertEqual(r['predicted_minutes'],28)
 def test_outlier_abandoned_interrupted_partial_excluded(self):
  self.sample(actual=1);self.sample(actual=100);self.sample(completion='partial');self.sample(completion='not_started',reason='blocked');s=self.start();self.advance(181);self.svc.current('owner');self.svc.action('owner',s['id'],'end',{'completion':'done','adjusted_active_minutes':20});r=self.pace.profiles('owner',True);self.assertEqual(sum(p['sample_count'] for p in r['profiles'] if p['task_bucket']=='all'),0);self.assertEqual(r['excluded']['outlier'],2)
 def test_activities_separate_and_multiplier_clamp(self):
  for _ in range(3):self.sample(actual=60);self.sample(planned=5,actual=2,kind='review')
  estimate=DurationEstimator(self.store,'owner');self.assertEqual(estimate.predict(20,'course_learning')['predicted_minutes'],40);self.assertEqual(estimate.predict(5,'review')['predicted_minutes'],3)
 def test_edit_delete_rebuild_cursor(self):
  records=[self.sample(actual=a) for a in [20,40,60]];self.assertEqual(DurationEstimator(self.store,'owner').predict(20,'course_learning')['predicted_minutes'],40)
  self.svc.action('owner',records[1]['id'],'adjust',{'adjusted_active_minutes':28});self.assertEqual(DurationEstimator(self.store,'owner').predict(20,'course_learning')['predicted_minutes'],28)
  self.svc.action('owner',records[1]['id'],'delete');self.assertEqual(DurationEstimator(self.store,'owner').predict(20,'course_learning')['pace_reason'],'PACE_LOW_SAMPLE')
 def test_eight_hour_record_invalid_and_deletable(self):
  records=[self.sample() for _ in range(3)];s=self.start();r=self.end(s,1,adjusted_active_minutes=480);self.assertEqual(self.pace.eligible(r),'unreasonable_duration');self.assertEqual(DurationEstimator(self.store,'owner').predict(20,'course_learning')['predicted_minutes'],28);self.svc.action('owner',r['id'],'delete');self.assertEqual(DurationEstimator(self.store,'owner').predict(20,'course_learning')['predicted_minutes'],28)
 def test_snapshot_cached_and_rolling_window_bounded(self):
  self.sample();a=self.pace.profiles('owner',True);b=self.pace.profiles('owner',True);self.assertEqual(a,b)
  with self.store.connect() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM pace_snapshots').fetchone()[0],1)
 def test_user_marked_invalid_excluded(self):self.assertEqual(self.pace.eligible(self.sample(invalid_for_pace=True)),'user_marked_invalid')
 def test_history_filters_and_pagination(self):
  for _ in range(4):self.sample()
  r=self.svc.history('owner',{'limit':'2','course_id':self.c['id'],'date_from':'2026-10-02','date_to':'2026-10-02'});self.assertEqual(len(r['sessions']),2);self.assertTrue(r['next_cursor']);self.assertEqual(len(self.svc.history('owner',{'limit':2,'before':r['next_cursor']})['sessions']),2)
  with self.assertRaises(ValueError):self.svc.history('owner',{'date_from':'bad'})
 def test_today_max3_and_week_max8_no_budget(self):
  items=[self.item(course_id=str(i)) for i in range(12)];p=self.plan(items);self.assertEqual(len(p['today']),3);self.assertEqual(len(p['weekly']),8)
 def test_urgent_review_then_active_then_critical(self):
  s=self.start();p=self.plan([self.item(course_id='other',task_id='critical',critical=True),self.item('review',5,atom_id='due')]);self.assertEqual([t['activity_type'] for t in p['today']],['review','course_learning','course_learning']);self.assertEqual(p['today'][1]['session_id'],s['id'])
 def test_multigoal_fairness_scenario(self):
  items=[self.item(task_id='a'+str(i),goal_id='a',critical=True) for i in range(3)]+[self.item(task_id='b',goal_id='b',critical=True)];p=self.plan(items,[self.goal('a'),self.goal('b')]);self.assertEqual([t['goal_id'] for t in p['today'][:2]],['a','b'])
 def test_personalized_minutes_used(self):
  for _ in range(3):self.sample()
  p=self.plan([self.item()]);self.assertEqual(p['today'][0]['predicted_minutes'],28);self.assertEqual(p['today'][0]['base_minutes'],20)
 def test_budget_deducts_today_and_week_actual(self):
  self.sample(actual=10);p=self.plan([self.item()],[self.goal(budget=100)]);self.assertEqual(p['today_remaining_minutes'],10);self.assertEqual(sum(t['planned_minutes'] for t in p['today']),10);self.assertTrue(p['today'][0]['split'])
 def test_assessment_not_split(self):
  p=self.plan([self.item('final_assessment',20),self.item('continue_course',20)],[self.goal(budget=50)]);self.assertEqual(len(p['today']),1);self.assertEqual(p['today'][0]['activity_type'],'course_learning');self.assertEqual(p['today'][0]['planned_minutes'],10)
 def test_zero_week_budget_no_negative_allocation(self):
  self.sample(actual=40);p=self.plan([self.item()],[self.goal(budget=25)]);self.assertEqual(p['today'],[]);self.assertEqual(p['weekly'],[])
 def test_deadline_states_no_probabilities(self):
  analyzer=DeadlineFeasibilityAnalyzer();deadline='2026-10-23'
  for remaining,state in [(100,'on_track'),(500,'at_risk'),(800,'unlikely')]:
   r=analyzer.analyze(remaining,deadline,180,300,2,self.at);self.assertEqual(r['status'],state);self.assertNotIn('probability',r)
  r=analyzer.analyze(800,deadline,None,300,0,self.at);self.assertEqual(r['status'],'insufficient_data');self.assertEqual(r['capacity_source'],'budget_fallback')
 def test_reality_two_weeks_150_vs300_deadline_800(self):
  growth,gid,t,c=self.task(weekly_time_budget_minutes=300,deadline='2026-10-23');self.at=datetime(2026,9,13,16,tzinfo=timezone.utc)
  for _ in range(2):
   s=self.svc.start('owner',{'growth_task_id':t['id'],'planned_minutes':150})['session'];self.end(s,150);self.at+=timedelta(days=7)-timedelta(minutes=150)
  self.at=datetime(2026,10,2,0,tzinfo=timezone.utc)
  with self.store.connect() as db:db.execute('UPDATE growth_tasks SET estimated_minutes=800 WHERE id=?',(t['id'],))
  before=self.frozen();r=PlanRealityAnalyzer(self.store,lambda:self.at).analyze('owner',gid);self.assertEqual(r['deadline']['actual_capacity_minutes_per_week'],150);self.assertEqual(r['deadline']['status'],'unlikely');self.assertIn('WEEKLY_CAPACITY_BELOW_PLAN',r['reason_codes']);self.assertEqual(before,self.frozen())
 def test_repeated_abandonment_only_recommends(self):
  growth,gid,t,c=self.task();before=growth.gaps('owner',gid)
  for _ in range(3):s=self.svc.start('owner',{'growth_task_id':t['id']})['session'];self.end(s,5,completion='not_started',reason='blocked')
  r=PlanRealityAnalyzer(self.store,lambda:self.at).analyze('owner',gid);self.assertIn('REPEATED_ABANDONMENT',r['reason_codes']);self.assertEqual(before,growth.gaps('owner',gid));self.assertEqual(growth.roadmap('owner',gid)['roadmap']['version'],1)
 def test_model_receives_bounded_pace_context_only(self):
  growth,gid,t,c=self.task();model=GrowthModel();s=self.svc.start('owner',{'growth_task_id':t['id']})['session'];self.end(s,30);before=growth.gaps('owner',gid);growth.generate('owner',gid,model);payload=model.stage_calls[0];self.assertEqual(set(payload['pace_context']),{'planned_weekly_minutes','observed_weekly_capacity_range_minutes','deadline_risk','boundary'});self.assertNotIn('sessions',str(payload));self.assertEqual(before,growth.gaps('owner',gid))
 def test_actual_time_split_across_midnight(self):
  self.at=datetime(2026,10,1,15,50,tzinfo=timezone.utc);s=self.start();self.end(s,20);p=self.plan([self.item()],[self.goal(budget=300)]);self.assertEqual(p['today_actual_minutes'],10);self.assertEqual(p['weekly_actual_minutes'],20)
 def test_actual_time_split_across_week_boundary_with_pause(self):
  self.at=datetime(2026,10,4,15,40,tzinfo=timezone.utc);s=self.start();self.advance(10);self.svc.action('owner',s['id'],'pause');self.advance(20);self.svc.action('owner',s['id'],'resume');self.end(s,10);p=self.plan([self.item()],[self.goal(budget=300)]);self.assertEqual(p['weekly_actual_minutes'],10);self.assertEqual(p['today_actual_minutes'],10)
 def test_skipped_critical_task_still_deadline_work(self):
  growth,gid,t,c=self.task(weekly_time_budget_minutes=300,deadline='2026-10-23');growth.task_action('owner',gid,t['id'],'skip');r=PlanRealityAnalyzer(self.store,lambda:self.at).analyze('owner',gid);self.assertGreater(r['deadline']['remaining_minutes'],0)
 def test_policy_migration_idempotent_no_user_data_loss(self):
  s=self.start();self.end(s,20);Storage(self.store.path);Storage(self.store.path);self.assertEqual(len(self.svc.history('owner')['sessions']),1)
 def test_session_survives_goal_deletion_and_course_recycle(self):
  growth,gid,t,c=self.task();s=self.svc.start('owner',{'growth_task_id':t['id']})['session'];self.end(s,20);growth.delete('owner',gid);self.store.recycle_course('owner',t['target_id']);self.assertEqual(self.svc.history('owner')['sessions'][0]['goal_id'],gid)
 def test_frozen_modules_sha(self):
  root=Path(__file__).resolve().parents[1];expected=json.loads((root/'docs/validation/learning-loop-p5-frozen.json').read_text());self.assertEqual({name:hashlib.sha256((root/'mindos/learning'/name).read_bytes()).hexdigest() for name in expected},expected)
