import copy,json,math,tempfile,unittest
from pathlib import Path
from mindos.storage import Storage
from mindos.mission.service import MissionService
from mindos.mission.planner import MissionPlanner
from mindos.mission.artifacts import ArtifactService
from mindos.mission.evidence import ProjectEvidenceBridge
from mindos.mission.tutor import MissionTutorService,MissionContextBuilder
from mindos.mission.protocol import plan
from mindos.learning.execution import StudySessionService
from mindos.learning.growth import GrowthService
from mindos.learning.authentic import AuthenticAssessmentService
from mindos.resources.service import ResourceService
from resource_fixture import make_course,png,pdf
from mission_fixture import MissionModel,definition,protected
class MissionTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.store=Storage(Path(self.tmp.name)/'db');self.c=make_course(self.store,'owner');self.cid=self.c['id'];self.s=MissionService(self.store);self.p=MissionPlanner(self.store);self.a=ArtifactService(self.store);self.b=ProjectEvidenceBridge(self.store);self.model=MissionModel(definition(self.cid,'a0'));self.m=self.s.create('owner',{'title':'CUDA推理优化','mission_type':'project','target_outcome':'实验与报告','confirmed':True});self.mid=self.m['id']
 def tearDown(self):self.tmp.cleanup()
 def confirmed(self):
  m=self.p.generate('owner',self.mid,self.model);return self.p.confirm('owner',self.mid,{'confirm':True,'draft_version':m['draft_version']})
 def get(self):return self.s.get('owner',self.mid)
 def task(self,index=0):return self.get()['tasks'][index]
 def activate_experiment(self):
  self.confirmed();t=self.task();self.s.task_action('owner',self.mid,t['id'],'start');self.s.task_action('owner',self.mid,t['id'],'complete');t=self.task(1);self.s.task_action('owner',self.mid,t['id'],'start');return self.task(1)
 def upload(self,tid=None,kind='benchmark',data=b'tile,latency_ms\n16,1.8\n32,1.3\n64,1.7',filename='benchmark.csv',**extra):return self.a.upload('owner',self.mid,{'filename':filename,'artifact_type':kind,'task_id':tid,**extra},data)
 def test_create_requires_explicit_confirmation(self):self.assertRaises(ValueError,self.s.create,'owner',{'title':'任务'})
 def test_goal_ownership_checked(self):self.assertRaises(ValueError,self.s.create,'owner',{'title':'任务','goal_id':'other','confirmed':True})
 def test_course_not_created(self):
  with self.store.connect() as db:self.assertEqual(db.execute('SELECT count(*) FROM courses').fetchone()[0],1)
 def test_initial_status_draft(self):self.assertEqual(self.get()['status'],'draft')
 def test_no_plan_not_active(self):self.assertRaises(ValueError,self.s.update,'owner',self.mid,{'status':'active'})
 def test_foreign_mission_denied(self):self.assertRaises(ValueError,self.s.get,'other',self.mid)
 def test_unknown_fields_rejected(self):self.assertRaises(ValueError,self.s.update,'owner',self.mid,{'mastery':1})
 def test_mission_edit(self):self.s.update('owner',self.mid,{'title':'新版','deadline':'2026-11-01'});self.assertEqual(self.get()['title'],'新版')
 def test_invalid_date(self):self.assertRaises(ValueError,self.s.update,'owner',self.mid,{'deadline':'明天'})
 def test_invalid_status(self):self.assertRaises(ValueError,self.s.update,'owner',self.mid,{'status':'mastered'})
 def test_outcome_does_not_drop_state(self):
  before=protected(self.store);self.s.update('owner',self.mid,{'outcome':'failed','status':'abandoned'});self.assertEqual(protected(self.store),before)
 def test_plan_draft_does_not_create_tasks(self):m=self.p.generate('owner',self.mid,self.model);self.assertEqual(m['tasks'],[]);self.assertEqual(m['plan_version'],0)
 def test_model_context_actual_courses(self):self.p.generate('owner',self.mid,self.model);self.assertEqual(self.model.calls[0][1]['courses'][0]['id'],self.cid)
 def test_confirmation_version_required(self):m=self.p.generate('owner',self.mid,self.model);self.assertRaises(ValueError,self.p.confirm,'owner',self.mid,{'confirm':True,'draft_version':m['draft_version']+1})
 def test_confirmation_not_truthy(self):m=self.p.generate('owner',self.mid,self.model);self.assertRaises(ValueError,self.p.confirm,'owner',self.mid,{'confirm':1,'draft_version':m['draft_version']})
 def test_confirmed_plan_order(self):m=self.confirmed();self.assertEqual([t['status'] for t in m['tasks']],['ready','blocked','blocked'])
 def test_model_unavailable_editable_fallback(self):m=self.p.generate('owner',self.mid,None);self.assertEqual(m['draft']['source'],'editable_rule_fallback');self.assertEqual(m['tasks'],[])
 def test_plan_rejects_mastery(self):d=definition();d['milestones'][0]['tasks'][0]['mastery']=1;self.assertRaises(ValueError,plan,d)
 def test_plan_cycle_or_forward_dependency_rejected(self):d=definition();d['milestones'][0]['tasks'][0]['dependencies']=['report'];self.assertRaises(ValueError,plan,d)
 def test_plan_duplicate_key(self):d=definition();d['milestones'][1]['tasks'][1]['key']='baseline';self.assertRaises(ValueError,plan,d)
 def test_invalid_link_falls_back_without_foreign_course(self):model=MissionModel(definition('foreign','a0'));m=self.p.generate('owner',self.mid,model);self.assertEqual(m['draft']['source'],'editable_rule_fallback')
 def test_blocked_task_not_startable(self):m=self.confirmed();self.assertRaises(ValueError,self.s.task_action,'owner',self.mid,m['tasks'][1]['id'],'start')
 def test_task_start_no_study_session(self):m=self.confirmed();self.s.task_action('owner',self.mid,m['tasks'][0]['id'],'start');self.assertIsNone(StudySessionService(self.store).current('owner')['session'])
 def test_complete_requires_start(self):m=self.confirmed();self.assertRaises(ValueError,self.s.task_action,'owner',self.mid,m['tasks'][0]['id'],'complete')
 def test_required_skip_blocks_mission(self):m=self.confirmed();self.s.task_action('owner',self.mid,m['tasks'][0]['id'],'skip');self.assertRaises(ValueError,self.s.update,'owner',self.mid,{'status':'completed'})
 def test_skip_can_resume(self):m=self.confirmed();tid=m['tasks'][0]['id'];self.s.task_action('owner',self.mid,tid,'skip');self.s.task_action('owner',self.mid,tid,'resume');self.assertEqual(self.task()['status'],'ready')
 def test_complete_requires_artifact(self):t=self.activate_experiment();self.s.run('owner',self.mid,t['id'],{'metrics':{'ms':1}});self.assertRaises(ValueError,self.s.task_action,'owner',self.mid,t['id'],'complete')
 def test_complete_experiment_requires_run(self):t=self.activate_experiment();self.upload(t['id']);self.assertRaises(ValueError,self.s.task_action,'owner',self.mid,t['id'],'complete')
 def test_complete_flow_no_mastery(self):
  before=protected(self.store);t=self.activate_experiment();self.upload(t['id']);self.s.run('owner',self.mid,t['id'],{'metrics':{'ms':1}});self.s.task_action('owner',self.mid,t['id'],'complete');t=self.task(2);self.s.task_action('owner',self.mid,t['id'],'start');self.upload(t['id'],'report',b'Observations and limitations','report.md');self.s.task_action('owner',self.mid,t['id'],'complete');m=self.s.update('owner',self.mid,{'status':'completed','outcome':'success'});self.assertEqual(m['progress']['milestones_completed'],2);self.assertEqual(protected(self.store),before)
 def test_session_end_not_task_complete(self):
  m=self.confirmed();tid=m['tasks'][0]['id'];self.s.task_action('owner',self.mid,tid,'start');r=self.s.start_session('owner',self.mid,tid,{'planned_minutes':20});StudySessionService(self.store).action('owner',r['session']['id'],'end',{'completion':'done','reason':'finished'});self.assertEqual(self.task()['status'],'active')
 def test_session_explicit_only_active(self):self.confirmed();self.assertRaises(ValueError,self.s.start_session,'owner',self.mid,self.task()['id'],{})
 def test_session_uses_existing_goal_task(self):m=self.confirmed();tid=m['tasks'][0]['id'];self.s.task_action('owner',self.mid,tid,'start');r=self.s.start_session('owner',self.mid,tid,{});self.assertEqual(r['session']['activity_type'],'goal_task')
 def test_lock_task_survives_replan(self):
  m=self.confirmed();t=m['tasks'][0];self.s.task_action('owner',self.mid,t['id'],'lock',{'enabled':True});self.model.plan['milestones'][0]['tasks'][0]['title']='偷改';m=self.p.generate('owner',self.mid,self.model,replan=True);m=self.p.confirm('owner',self.mid,{'confirm':True,'draft_version':m['draft_version']});self.assertEqual(m['tasks'][0]['id'],t['id']);self.assertEqual(m['tasks'][0]['title'],t['title'])
 def test_completed_preserved_replan(self):t=self.activate_experiment();before=self.task();m=self.p.generate('owner',self.mid,MissionModel(definition()),replan=True);self.assertEqual(m['draft']['plan']['milestones'][0]['tasks'][0]['title'],before['title'])
 def test_locked_prefix_cannot_user_overwrite(self):
  m=self.confirmed();self.s.task_action('owner',self.mid,m['tasks'][0]['id'],'lock',{'enabled':True});m=self.p.generate('owner',self.mid,self.model);d=copy.deepcopy(m['draft']['plan']);d['milestones'][0]['tasks'][0]['title']='不同';self.assertRaises(ValueError,self.p.confirm,'owner',self.mid,{'confirm':True,'draft_version':m['draft_version'],'plan':d})
 def test_fixed_milestone_preserved(self):m=self.confirmed();self.s.lock_milestone('owner',self.mid,m['milestones'][0]['id'],{'enabled':True});self.model.plan['milestones'][0]['title']='错误';m=self.p.generate('owner',self.mid,self.model);self.assertEqual(m['draft']['plan']['milestones'][0]['title'],'建立基线')
 def test_replan_history_versions(self):self.confirmed();m=self.p.generate('owner',self.mid,self.model);m=self.p.confirm('owner',self.mid,{'confirm':True,'draft_version':m['draft_version']});self.assertEqual(m['plan_version'],2);self.assertEqual(len(m['history']),2)
 def test_multiple_runs_indices(self):t=self.activate_experiment();self.s.run('owner',self.mid,t['id'],{'metrics':{'ms':1}});m=self.s.run('owner',self.mid,t['id'],{'metrics':{'ms':2}});self.assertEqual([r['run_index'] for r in m['runs']],[1,2])
 def test_metrics_nan_rejected(self):t=self.activate_experiment();self.assertRaises(ValueError,self.s.run,'owner',self.mid,t['id'],{'metrics':{'ms':float('nan')}})
 def test_metrics_infinity_rejected(self):t=self.activate_experiment();self.assertRaises(ValueError,self.s.run,'owner',self.mid,t['id'],{'metrics':{'ms':math.inf}})
 def test_metrics_text_rejected(self):t=self.activate_experiment();self.assertRaises(ValueError,self.s.run,'owner',self.mid,t['id'],{'metrics':{'ms':'fast'}})
 def test_compare_only_same_metric_no_causality(self):
  t=self.activate_experiment()
  for tile,ms in [(16,1.8),(32,1.3),(64,1.7)]:self.s.run('owner',self.mid,t['id'],{'parameters':{'tile':tile},'metrics':{'latency_ms':ms}})
  m=self.get();r=self.s.compare('owner',self.mid,t['id'],{'run_ids':[r['id'] for r in m['runs']]});self.assertEqual(r['comparison'][0]['minimum'],1.3);self.assertIn('不能',r['boundary']);self.assertNotIn('cause',r)
 def test_compare_foreign_run_denied(self):t=self.activate_experiment();self.assertRaises(ValueError,self.s.compare,'owner',self.mid,t['id'],{'run_ids':['foreign','unknown']})
 def test_compare_one_not_enough(self):t=self.activate_experiment();self.assertRaises(ValueError,self.s.compare,'owner',self.mid,t['id'],{'run_ids':['x']})
 def test_run_foreign_artifact_denied(self):t=self.activate_experiment();self.assertRaises(ValueError,self.s.run,'owner',self.mid,t['id'],{'metrics':{'ms':1},'artifact_ids':['foreign']})
 def test_artifact_not_resource(self):self.upload();self.assertEqual(self.count('knowledge_resources'),0)
 def count(self,table):
  with self.store.connect() as db:return db.execute('SELECT count(*) FROM '+table).fetchone()[0]
 def test_upload_twenty_no_evidence(self):
  before=protected(self.store)
  for i in range(20):self.upload(data=('report '+str(i)).encode())
  self.assertEqual(self.count('mission_artifacts'),20);self.assertEqual(protected(self.store),before)
 def test_hash_actual_original_bytes(self):from mindos.resources.protocol import digest;a=self.upload();p,_=self.a.file('owner',self.mid,a['id']);self.assertEqual(a['content_hash'],digest(p.read_bytes()))
 def test_local_path_not_returned(self):self.assertNotIn('local_path',self.upload())
 def test_filename_traversal_denied(self):self.assertRaises(ValueError,self.upload,filename='../key.txt')
 def test_filename_windows_traversal_denied(self):self.assertRaises(ValueError,self.upload,filename='..\\key.txt')
 def test_invalid_utf8_text(self):self.assertRaises(ValueError,self.upload,data=b'\xff\xfe')
 def test_fake_image_denied(self):self.assertRaises(ValueError,self.upload,kind='image',data=b'fake',filename='fake.png')
 def test_svg_active_content_rejected(self):self.assertRaises(ValueError,self.upload,data=b'<svg/>',filename='image.svg')
 def test_code_not_executed_or_material(self):a=self.upload(kind='code',data=b'raise RuntimeError("must never execute")',filename='code.py');self.assertIn('raise',self.a.preview('owner',self.mid,a['id'])['text']);self.assertEqual(self.count('knowledge_resources'),0)
 def test_image_reuses_p8_decoder(self):a=self.upload(kind='image',data=png(),filename='x.png');self.assertEqual(a['mime_type'],'image/png')
 def test_corrupt_image_rejected(self):self.assertRaises(ValueError,self.upload,kind='image',data=png()[:-10],filename='x.png')
 def test_model_binary_no_text(self):a=self.upload(kind='model',data=b'\x00\x01fakeopaque',filename='x.safetensors');p=self.a.preview('owner',self.mid,a['id']);self.assertEqual(p['text'],'');self.assertIn('无法读取',p['note'])
 def test_version_lineage(self):a=self.upload();b=self.upload(parent_artifact_id=a['id']);self.assertEqual(b['version'],2);self.assertEqual(b['parent_artifact_id'],a['id'])
 def test_version_foreign_parent(self):self.assertRaises(ValueError,self.upload,parent_artifact_id='foreign')
 def test_version_type_change_denied(self):a=self.upload();self.assertRaises(ValueError,self.upload,kind='report',parent_artifact_id=a['id'])
 def test_parent_delete_blocked(self):a=self.upload();self.upload(parent_artifact_id=a['id']);self.assertRaises(ValueError,self.a.delete,'owner',self.mid,a['id'],{'confirm':True})
 def test_delete_confirmation(self):a=self.upload();self.assertRaises(ValueError,self.a.delete,'owner',self.mid,a['id'],{})
 def test_delete_unreferenced_removes_file(self):a=self.upload();p,_=self.a.file('owner',self.mid,a['id']);self.a.delete('owner',self.mid,a['id'],{'confirm':True});self.assertFalse(p.exists())
 def test_symlink_directory_rejected(self):self.a.files.directory.symlink_to(Path(self.tmp.name)/'elsewhere',target_is_directory=True);self.assertRaises(ValueError,self.upload)
 def test_symlink_file_rejected(self):a=self.upload();p,_=self.a.file('owner',self.mid,a['id']);p.unlink();p.symlink_to(self.store.path);self.assertRaises(ValueError,self.a.file,'owner',self.mid,a['id'])
 def test_foreign_artifact_denied(self):a=self.upload();self.assertRaises(ValueError,self.a.get,'other',self.mid,a['id'])
 def test_cross_mission_artifact_denied(self):a=self.upload();m=self.s.create('owner',{'title':'第二个','confirmed':True});self.assertRaises(ValueError,self.a.get,'owner',m['id'],a['id'])
 def test_large_preview_bounded(self):a=self.upload(data=b'x'*30000);self.assertEqual(len(self.a.preview('owner',self.mid,a['id'])['text']),12000)
 def test_pdf_not_read_without_pages(self):a=self.upload(data=pdf(),filename='x.pdf',kind='document');self.assertEqual(self.a.preview('owner',self.mid,a['id'])['text'],'')
 def test_pdf_selected_pages_only(self):a=self.upload(data=pdf(),filename='x.pdf',kind='document');p=self.a.preview('owner',self.mid,a['id'],{'pages':[2]});self.assertIn('SECOND',p['text']);self.assertNotIn('FIRST',p['text'])
 def test_pdf_failed_no_filename_guess(self):a=self.upload(data=b'%PDF-bad',filename='definitely_fastest.pdf',kind='document');self.assertRaises(Exception,self.a.preview,'owner',self.mid,a['id'],{'pages':[1]})
 def test_promote_explicit_resource_derived(self):a=self.upload();r=self.a.promote('owner',self.mid,a['id'],{'confirm':True,'course_id':self.cid,'atom_id':'a0'})['resource'];self.assertNotEqual(r['id'],a['id']);self.assertEqual(r['metadata']['derived_from_artifact_id'],a['id']);self.assertEqual(self.count('mission_artifacts'),1)
 def test_promote_requires_confirm(self):a=self.upload();self.assertRaises(ValueError,self.a.promote,'owner',self.mid,a['id'],{'course_id':self.cid,'atom_id':'a0'})
 def test_promoted_artifact_delete_blocked(self):a=self.upload();self.a.promote('owner',self.mid,a['id'],{'confirm':True,'course_id':self.cid,'atom_id':'a0'});self.assertRaises(ValueError,self.a.delete,'owner',self.mid,a['id'],{'confirm':True})
 def test_supporting_resources_stay_p8(self):
  m=self.confirmed();r=ResourceService(self.store).create('owner','text','参考',{'text':'背景解释'});self.s.edit_task('owner',self.mid,m['tasks'][0]['id'],{'resource_ids':[r['id']]});self.assertEqual(self.count('mission_artifacts'),0)
 def test_foreign_resource_denied(self):m=self.confirmed();self.assertRaises(ValueError,self.s.edit_task,'owner',self.mid,m['tasks'][0]['id'],{'resource_ids':['foreign']})
 def test_reflection_confirmation(self):self.assertRaises(ValueError,self.s.reflection,'owner',self.mid,{'content':'这是我的发现'})
 def test_reflection_no_state_change(self):before=protected(self.store);m=self.s.reflection('owner',self.mid,{'content':'实际结果与预期不同，下一步检查计时','confirmed':True});self.assertEqual(len(m['reflections']),1);self.assertEqual(protected(self.store),before)
 def test_reflection_foreign_task(self):self.assertRaises(ValueError,self.s.reflection,'owner',self.mid,{'content':'发现','task_id':'foreign','confirmed':True})
 def test_reflection_ref_blocks_delete(self):a=self.upload();self.s.reflection('owner',self.mid,{'content':'发现','artifact_ids':[a['id']],'confirmed':True});self.assertRaises(ValueError,self.a.delete,'owner',self.mid,a['id'],{'confirm':True})
 def candidate(self,a):return self.b.analyze('owner',self.mid,{'claim':'能够独立实现测量','claim_type':'implementation','artifact_ids':[a['id']],'confirmed':True},self.model)['evidence_candidates'][0]
 def test_candidate_not_learning_evidence(self):before=protected(self.store);c=self.candidate(self.upload());self.assertEqual(c['status'],'candidate');self.assertTrue(c['review']['available']);self.assertEqual(protected(self.store),before)
 def test_candidate_ref_blocks_delete(self):a=self.upload();self.candidate(a);self.assertRaises(ValueError,self.a.delete,'owner',self.mid,a['id'],{'confirm':True})
 def test_verify_creates_original_p2_task(self):c=self.candidate(self.upload());r=self.b.verify('owner',self.mid,c['id'],{'course_id':self.cid,'atom_id':'a0','confirm':True},self.model);self.assertEqual(r['task']['task_type'],'design');self.assertEqual(self.count('authentic_tasks'),1);self.assertNotIn('artifacts',self.model.calls[-1][1]['context'])
 def test_verify_requires_confirmation(self):c=self.candidate(self.upload());self.assertRaises(ValueError,self.b.verify,'owner',self.mid,c['id'],{'course_id':self.cid,'atom_id':'a0'},self.model)
 def test_verify_foreign_course(self):c=self.candidate(self.upload());self.assertRaises(ValueError,self.b.verify,'owner',self.mid,c['id'],{'course_id':'foreign','atom_id':'a0','confirm':True},self.model)
 def test_existing_p2_not_reused_as_new_proof(self):AuthenticAssessmentService(self.store).start('owner',self.cid,'a0','design',self.model);c=self.candidate(self.upload());self.assertRaises(ValueError,self.b.verify,'owner',self.mid,c['id'],{'course_id':self.cid,'atom_id':'a0','confirm':True},self.model)
 def test_original_p2_result_not_new_mastery(self):
  c=self.candidate(self.upload());r=self.b.verify('owner',self.mid,c['id'],{'course_id':self.cid,'atom_id':'a0','confirm':True},self.model);before=protected(self.store);AuthenticAssessmentService(self.store).submit('owner',self.cid,r['task']['id'],'比较需求与工具条件，然后读取对应工具方案，重新设置条件检查匹配。',self.model);status=self.b.status('owner',self.mid,c['id']);self.assertEqual(status['candidate']['status'],'candidate');self.assertTrue(status['task']['result']['valid_for_calibration']);after=protected(self.store);self.assertEqual(after['knowledge_states'],before['knowledge_states']);self.assertEqual(after['personal_knowledge_profiles'],before['personal_knowledge_profiles']);self.assertEqual(len(after['learning_evidence']),len(before['learning_evidence'])+1)
 def test_tutor_requires_real_course(self):self.model.plan=definition();m=self.confirmed();self.assertRaises(ValueError,MissionContextBuilder(self.store).build,'owner',self.mid,m['tasks'][0]['id'])
 def test_tutor_task_and_recent_runs(self):
  t=self.activate_experiment()
  for i in range(5):self.s.run('owner',self.mid,t['id'],{'parameters':{'tile':i},'metrics':{'ms':i}})
  _,_,ctx=MissionContextBuilder(self.store).build('owner',self.mid,t['id']);self.assertEqual(len(ctx['latest_experiment_summary']),3);self.assertEqual(ctx['current_mission_task']['id'],t['id'])
 def test_tutor_only_selected_artifact_context(self):t=self.activate_experiment();a=self.upload(t['id']);self.upload(t['id'],data=b'OTHER SECRET REPORT');_,_,ctx=MissionContextBuilder(self.store).build('owner',self.mid,t['id'],a['id'],True);self.assertEqual(len(ctx['artifacts']),1);self.assertEqual(ctx['latest_experiment_summary'],[]);self.assertNotIn('SECRET',json.dumps(ctx))
 def test_tutor_large_artifact_bounded(self):t=self.activate_experiment();a=self.upload(t['id'],data=b'x'*30000);_,_,ctx=MissionContextBuilder(self.store).build('owner',self.mid,t['id'],a['id']);self.assertEqual(len(ctx['artifacts'][0]['text']),3000)
 def test_tutor_foreign_task_artifact_rejected(self):t=self.activate_experiment();a=self.upload(self.task()['id']);self.assertRaises(ValueError,MissionContextBuilder(self.store).build,'owner',self.mid,t['id'],a['id'])
 def test_tutor_uses_p65_and_original_history(self):
  t=self.activate_experiment();a=self.upload(t['id']);before=protected(self.store);r=MissionTutorService(self.store).chat('owner',self.mid,{'task_id':t['id'],'message':'如何理解这个实验？','request_id':'test-p9-ctx','focused_artifact_id':a['id'],'artifact_grounded':True},self.model,lambda mode:None);self.assertTrue(r['saved']);self.assertEqual(r['attempts'],1);self.assertEqual(r['artifact_citations'][0]['artifact_id'],a['id']);self.assertEqual(protected(self.store),before)
 def test_tutor_binary_reads_no_guessed_body(self):
  t=self.activate_experiment();a=self.upload(t['id'],'model',b'\x00\x01binary','perfect_model.bin');r=MissionTutorService(self.store).chat('owner',self.mid,{'task_id':t['id'],'message':'只根据这个产出，解释模型质量','request_id':'test-p9-binary','focused_artifact_id':a['id'],'artifact_grounded':True},self.model,lambda mode:None);self.assertIn('无法读取',r['answer']);self.assertEqual(r['artifact_citations'],[])
 def test_tutor_idempotency_changed_scope_rejected(self):
  t=self.activate_experiment();a=self.upload(t['id']);svc=MissionTutorService(self.store);p={'task_id':t['id'],'message':'解释实验记录','request_id':'same-p9-request','focused_artifact_id':a['id']};svc.chat('owner',self.mid,p,self.model,lambda mode:None);b=self.upload(t['id']);self.assertRaises(ValueError,svc.chat,'owner',self.mid,{**p,'focused_artifact_id':b['id']},self.model,lambda mode:None)
 def test_tutor_rejects_fabricated_quote(self):
  t=self.activate_experiment();a=self.upload(t['id']);original=self.model.mission_tutor_json
  def bad(p,repair_reason=''):
   r=original(p,repair_reason);r['artifact_citations'][0]['quote']='not present';return r
  self.model.mission_tutor_json=bad;r=MissionTutorService(self.store).chat('owner',self.mid,{'task_id':t['id'],'message':'解释实际记录','request_id':'bad-p9-request','focused_artifact_id':a['id'],'artifact_grounded':True},self.model,lambda mode:None);self.assertFalse(r['saved']);self.assertLessEqual(r['attempts'],2)
 def test_deleted_course_blocks_new_context(self):m=self.confirmed();self.store.recycle_course('owner',self.cid);self.assertRaises(ValueError,MissionContextBuilder(self.store).build,'owner',self.mid,m['tasks'][0]['id'])
 def test_active_mission_recommendation_reused(self):
  g=GrowthService(self.store).create('owner',{'title':'实践目标','description':'独立完成推理优化实验并记录可复现结果','goal_type':'competition','target_level':'practical_understanding','priority':1});self.s.update('owner',self.mid,{'goal_id':g['id']});r=self.s.recommendations('owner',g['id']);self.assertEqual(r['recommendations'][0]['mission_id'],self.mid);self.assertEqual(self.count('learning_missions'),1)
 def test_p4_practice_recommendation_and_existing_bridge(self):
  from growth_fixture import browser_seed,GrowthModel,graph,requirement
  from personal_fixture import train
  current=browser_seed(self.store,'owner');gm=GrowthModel(graph([requirement(),requirement('小型信息匹配设计',kind='practice')],[{'from':'QKV','to':'小型信息匹配设计','relation':'prerequisite'}]));gs,gid=gm.growth_goal(self.store,goal_type='project');train(self.store,current,n=9);route=gs.generate('owner',gid)['roadmap'];gt=next(t for t in route['tasks'] if t['task_type']=='authentic_assessment');self.s.update('owner',self.mid,{'goal_id':gid});a=self.upload();c=self.b.analyze('owner',self.mid,{'artifact_ids':[a['id']],'claim':'独立实现分配方案','claim_type':'implementation','capability_id':gt['capability_id'],'confirmed':True},self.model)['evidence_candidates'][0];r=self.b.verify('owner',self.mid,c['id'],{'course_id':gt['target_id'],'atom_id':'same-local-id','linked_growth_task_id':gt['id'],'confirm':True},self.model);AuthenticAssessmentService(self.store).submit('owner',gt['target_id'],r['task']['id'],'需求用于匹配，比较工具能力后取得借用说明，并检查使用范围。',self.model);self.assertEqual(next(x for x in gs.gaps('owner',gid)['gaps'] if x['type']=='practice')['status'],'sufficient');self.assertEqual(self.b.status('owner',self.mid,c['id'])['candidate']['status'],'candidate')
 def test_task_change_invalidates_pending_plan(self):
  m=self.confirmed();m=self.p.generate('owner',self.mid,self.model);v=m['draft_version'];self.s.edit_task('owner',self.mid,m['tasks'][0]['id'],{'title':'用户修改'});self.assertRaises(ValueError,self.p.confirm,'owner',self.mid,{'confirm':True,'draft_version':v})
 def test_replan_preserves_tasks_with_artifacts(self):
  m=self.confirmed();a=self.upload(m['tasks'][0]['id']);self.model.plan['milestones'][0]['tasks'][0]['title']='覆写历史';m=self.p.generate('owner',self.mid,self.model);self.assertEqual(m['draft']['plan']['milestones'][0]['tasks'][0]['title'],'记录基线')
 def test_code_promote_maps_language_supported_by_p8(self):
  a=self.upload(kind='code',filename='kernel.cu',data=b'void kernel() {}');r=self.a.promote('owner',self.mid,a['id'],{'confirm':True,'course_id':self.cid,'atom_id':'a0'})['resource'];self.assertEqual(r['payload']['language'],'cpp');self.assertFalse(r['payload']['runnable'])
 def test_priority_rejects_fraction(self):self.assertRaises(ValueError,self.s.update,'owner',self.mid,{'priority':2.5})
 def test_plan_version_rejects_boolean(self):m=self.p.generate('owner',self.mid,self.model);self.assertRaises(ValueError,self.p.confirm,'owner',self.mid,{'confirm':True,'draft_version':True})
 def test_identifier_objects_rejected(self):self.assertRaises(ValueError,self.s.create,'owner',{'title':'任务','confirmed':True,'goal_id':{}})
 def test_artifact_preview_cannot_forge_text(self):a=self.upload();self.assertRaises(ValueError,self.a.preview,'owner',self.mid,a['id'],{'text':'伪造正文'})
 def test_context_total_budget_includes_run_notes(self):
  t=self.activate_experiment()
  for i in range(3):self.s.run('owner',self.mid,t['id'],{'parameters':{'tile':i},'metrics':{'ms':i},'notes':'观察'*2000})
  for i in range(4):self.upload(t['id'],data=b'x'*20000)
  _,_,ctx=MissionContextBuilder(self.store).build('owner',self.mid,t['id']);self.assertLessEqual(len(json.dumps(ctx,ensure_ascii=False)),10000)
