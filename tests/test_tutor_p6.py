"""P6 contracts, context limits, memories, observation gates and frozen algorithms."""
import copy,hashlib,json,tempfile,unittest
from pathlib import Path
from mindos.storage import Storage
from mindos.tutor.service import TutorService
from mindos.tutor.context import TutorContextBuilder
from mindos.tutor.observations import TutorObservationService
from mindos.tutor.storage import TutorMemoryStore
from mindos.tutor.protocol import validate
import test_course_tutor as legacy
from tutor_fixture import packet

class Model:
    def __init__(self):self.calls=[];self.logs=[];self.transform=lambda p,v:v
    def tutor_json(self,payload,repair_reason=''):
        self.calls.append(copy.deepcopy(payload));return self.transform(payload,packet(payload))
    def _diagnostic(self,event):self.logs.append(event)
    def learning_check(self,course,section,atom,purpose,mis):
        return ([{'prompt':'独立判断这个定义是否正确？','choices':{'a':'正确','b':'不正确'},'atom_ids':[atom['id']],'assessment_type':'concept'}], [{'answer':'a','explanation':'根据课程定义判断。'}])

class P6Tests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.store=Storage(Path(self.temp.name)/'test.db')
        self.course=legacy.TutorTests.create(self,'Transformer原理');self.second=legacy.TutorTests.create(self,'隔离课程')
        self.svc=TutorService(self.store);self.model=Model();self.search=legacy.Search();self.cid=self.course['id']
    def tearDown(self):self.temp.cleanup()
    def chat(self,message='什么是基础概念？',**kwargs):return self.svc.chat('owner',{'message':message,'context_id':self.cid,**kwargs},self.model,lambda mode:self.search)
    def snapshot(self):
        with self.store.connect() as db:return {t:[tuple(r) for r in db.execute('SELECT * FROM '+t)] for t in ['knowledge_states','learning_evidence','knowledge_state_history','learning_misconceptions','teaching_actions','teaching_feedback','inherited_knowledge_priors','study_sessions','task_execution_events','pace_snapshots','growth_tasks','growth_roadmaps','personal_knowledge_profiles']}
    def test_simple_definition_and_no_learning_writes(self):
        before=self.snapshot();r=self.chat();self.assertFalse(r['fallback']);self.assertEqual(r['strategy'],'direct_explanation');self.assertEqual(before,self.snapshot());self.assertTrue(r['saved'])
    def test_question_specific_strategies(self):
        for msg,strategy in [('为什么Q和K相乘','step_by_step'),('Q和K一样吗','comparison'),('我不理解softmax','socratic'),('帮我调试报错','debugging'),('举个例子','example'),('请总结','summary'),('用类比讲','analogy')]:
            with self.subTest(msg=msg):self.assertEqual(self.chat(msg)['strategy'],strategy)
    def test_socratic_continues_without_grading(self):
        self.chat('我不理解softmax');r=self.chat('我觉得它是在筛选信息');self.assertEqual(r['strategy'],'socratic');self.assertEqual(self.model.calls[-1]['strategy']['stage'],'respond_then_guide');self.assertFalse(self.model.calls[-1]['strategy']['grade_user_answer'])
    def test_social_not_saved_or_sent_to_model(self):
        for m in ['你好','谢谢！','哈哈','好的','ok']:self.assertFalse(self.chat(m)['saved'])
        self.assertEqual(self.model.calls,[]);self.assertEqual(TutorMemoryStore(self.store).history('owner',self.cid)['messages'],[])
    def test_context_uses_actual_lesson_and_state(self):
        sid=self.course['sections'][0]['id'];self.store.save_lesson('owner',self.cid,sid,'真实页面教学片段')
        self.chat(current_context={'section_ordinal':1,'knowledge_atom_id':'a1'});c=self.model.calls[-1]['context']
        self.assertIn('真实页面教学片段',c['current_content']);self.assertEqual(c['current_context']['knowledge_atom_id'],'a1');self.assertEqual(c['knowledge_atoms'][0]['knowledge_state']['graded_evidence_count'],0)
    def test_context_no_future_atoms_whole_course_history_or_answers(self):
        self.chat();c=self.model.calls[-1]['context'];self.assertNotIn('sections',c);self.assertNotIn('curriculum',c['teaching_context']);self.assertNotIn('future',[a['id'] for a in c['knowledge_atoms']]);self.assertIsNone(c['study_session']);self.assertLess(len(json.dumps(c)),20000)
    def test_history_bounded_and_course_isolated(self):
        for i in range(6):self.chat('解释概念'+str(i))
        self.assertLessEqual(len(self.model.calls[-1]['context']['recent_dialogue']),6)
        self.cid=self.second['id'];self.chat();self.assertEqual(self.model.calls[-1]['context']['recent_dialogue'],[])
    def test_reject_forged_context(self):
        for ctx in [{'section_ordinal':2},{'knowledge_atom_id':'future'},{'knowledge_atom_id':'foreign'},{'mastery':1},{'page_content':'fake'}]:
            with self.subTest(ctx=ctx),self.assertRaises(ValueError):self.chat(current_context=ctx)
    def test_foreign_owner_cannot_chat(self):
        with self.assertRaises(ValueError):self.svc.chat('stranger',{'context_id':self.cid,'message':'解释'},self.model,lambda m:self.search)
    def test_invalid_schema_retries_then_safe_unsaved_fallback(self):
        before=self.snapshot();self.model.transform=lambda p,v:{'answer':'invalid'};r=self.chat();self.assertTrue(r['fallback']);self.assertFalse(r['saved']);self.assertEqual(len(self.model.calls),2);self.assertEqual(before,self.snapshot());self.assertEqual(self.history(),[])
    def history(self):return TutorMemoryStore(self.store).history('owner',self.cid)['messages']
    def test_retry_repairs_once(self):
        self.model.transform=lambda p,v:{'bad':True} if len(self.model.calls)==1 else v
        r=self.chat();self.assertFalse(r['fallback']);self.assertEqual(r['attempts'],2);self.assertEqual(len(self.history()),2)
    def test_model_exception_not_swallowed_without_fallback(self):
        def fail(p,v):raise TimeoutError('timeout')
        self.model.transform=fail;r=self.chat();self.assertTrue(r['fallback']);self.assertEqual(len(self.model.logs),2)
    def test_no_unquoted_memory_or_observation(self):
        self.model.transform=lambda p,v:{**v,'memories':[{'memory_type':'preference','content':'喜欢公式','supporting_quote':'用户没说过'}]};self.assertTrue(self.chat()['fallback'])
    def test_real_preference_separate_from_knowledge(self):
        self.model.transform=lambda p,v:{**v,'memories':[{'memory_type':'explanation_style','content':'先直觉后公式','supporting_quote':p['message']}]}
        before=self.snapshot();self.chat('我喜欢先讲直觉，再看公式');self.assertEqual(before,self.snapshot())
        with self.store.connect() as db:self.assertEqual(db.execute('SELECT count(*) FROM tutor_memories').fetchone()[0],1)
        self.chat('解释基础概念');self.assertTrue(self.model.calls[-1]['context']['memories'])
    def test_unstated_habit_not_saved(self):
        self.model.transform=lambda p,v:{**v,'memories':[{'memory_type':'learning_habit','content':'学习效率高','supporting_quote':p['message']}]};self.chat('我做得很快')
        with self.store.connect() as db:self.assertEqual(db.execute('SELECT count(*) FROM tutor_memories').fetchone()[0],0)
    def observation(self,kind='possible_gap'):
        self.model.transform=lambda p,v:{**v,'observations':[{'atom_id':'a1','observation_type':kind,'description':'可能需要再检查这个定义','supporting_quote':p['message'],'confidence':.7}]}
        r=self.chat('我不理解这个基础概念');return r['observations'][0]
    def test_observations_candidate_do_not_affect_knowledge(self):
        before=self.snapshot();o=self.observation();self.assertEqual(o['status'],'candidate');self.assertNotIn('confidence',o);self.assertEqual(before,self.snapshot())
    def test_verification_only_creates_real_p0_quiz(self):
        o=self.observation();before=self.snapshot();r=TutorObservationService(self.store).verify('owner',o['id'],self.model);self.assertIn('quiz',r);self.assertNotIn('answers',r['quiz']);self.assertEqual(before,self.snapshot())
    def test_unsubmitted_quiz_never_verifies(self):
        o=self.observation();service=TutorObservationService(self.store);service.verify('owner',o['id'],self.model);self.assertEqual(service.list('owner',self.cid)['observations'][0]['status'],'candidate')
    def test_foreign_observation_and_dismissal(self):
        o=self.observation();service=TutorObservationService(self.store)
        with self.assertRaises(ValueError):service.verify('other',o['id'],self.model)
        service.dismiss('owner',o['id']);self.assertEqual(service.list('owner',self.cid)['observations'][0]['status'],'dismissed')
    def test_dynamic_search_real_sources_and_failure_boundary(self):
        r=self.chat('最新软件版本？');self.assertEqual(r['search']['status'],'ok');self.assertIn('不是全网搜索',r['search']['note']);self.assertTrue(self.search.calls)
        r=self.svc.chat('owner',{'context_id':self.cid,'message':'最新软件接口'},self.model,None);self.assertEqual(r['search']['status'],'failed');self.assertEqual(r['search']['sources'],[]);self.assertIn('无法确认最新信息',r['answer'])
    def test_pending_answers_not_in_prompt_and_help_before_call(self):
        sid=self.course['sections'][0]['id'];self.store.save_lesson('owner',self.cid,sid,'基础讲解');q=self.store.create_quiz('owner',self.cid,sid,[{'prompt':'独立答题','choices':{'a':'甲','b':'乙'}}],[{'answer':'a','explanation':'secret-answer-marker'}]);self.chat();self.assertNotIn('secret-answer-marker',json.dumps(self.model.calls))
        with self.store.connect() as db:self.assertEqual(json.loads(db.execute('SELECT hint_flags_json FROM quizzes WHERE id=?',(q['id'],)).fetchone()[0]),[True])
    def test_duplicate_requests_no_extra_call_or_memory(self):
        r=self.chat(request_id='same');s=self.chat(request_id='same');self.assertEqual(r['messages'],s['messages']);self.assertEqual(len(self.model.calls),1)
        with self.assertRaises(ValueError):self.chat('不一样的问题',request_id='same')
    def test_deleted_course_and_purge_cascade(self):
        self.observation();self.store.recycle_course('owner',self.cid)
        with self.assertRaises(ValueError):self.chat()
        self.store.restore_course('owner',self.cid);self.assertEqual(len(self.history()),2);self.store.recycle_course('owner',self.cid);self.store.purge_course('owner',self.cid,self.course['title'])
        with self.store.connect() as db:
            for t in ['tutor_conversations','tutor_messages','tutor_memories','tutor_observations']:self.assertEqual(db.execute('SELECT count(*) FROM '+t).fetchone()[0],0)
    def test_formula_and_table_validation(self):
        for blocks in [[{'type':'formula','content':'QK=1'}],[{'type':'comparison','columns':['a','b'],'rows':[['only']]}]]:
            self.model.transform=lambda p,v:{**v,'blocks':blocks};self.assertTrue(self.chat()['fallback'])
    def test_frozen_algorithms(self):
        root=Path(__file__).resolve().parents[1];manifest=json.loads((root/'docs/learning-loop-p6-frozen.json').read_text())
        for name,expected in manifest['files'].items():self.assertEqual(hashlib.sha256((root/name).read_bytes()).hexdigest(),expected,name)

    def test_wrong_independent_check_confirms_gap_only_via_p0_results(self):
        o=self.observation();svc=TutorObservationService(self.store);r=svc.verify('owner',o['id'],self.model)
        self.store.submit_quiz('owner',self.cid,r['quiz']['id'],['b'],['high'])
        before=self.snapshot();o=svc.list('owner',self.cid)['observations'][0];self.assertEqual(o['status'],'verified');self.assertEqual(before,self.snapshot())
    def test_correct_independent_check_dismisses_possible_gap(self):
        o=self.observation();svc=TutorObservationService(self.store);r=svc.verify('owner',o['id'],self.model)
        self.store.submit_quiz('owner',self.cid,r['quiz']['id'],['a'],['high']);self.assertEqual(svc.list('owner',self.cid)['observations'][0]['status'],'dismissed')
    def test_hinted_check_is_only_practice_and_not_verified(self):
        o=self.observation();svc=TutorObservationService(self.store);r=svc.verify('owner',o['id'],self.model);self.chat('请解释这个定义')
        self.store.submit_quiz('owner',self.cid,r['quiz']['id'],['b'],['high']);o=next(x for x in svc.list('owner',self.cid)['observations'] if x['id']==o['id']);self.assertEqual(o['status'],'candidate');self.assertEqual(o['verification']['outcome'],'practice_only')
    def test_wrong_check_cannot_certify_specific_misconception_guess(self):
        o=self.observation('possible_misconception');svc=TutorObservationService(self.store);r=svc.verify('owner',o['id'],self.model)
        self.store.submit_quiz('owner',self.cid,r['quiz']['id'],['b'],['high']);self.assertEqual(svc.list('owner',self.cid)['observations'][0]['status'],'candidate')
    def test_read_p5_session_without_timing_or_recovery(self):
        from mindos.learning.execution import StudySessionService
        s=StudySessionService(self.store).start('owner',{'course_id':self.cid})['session']
        before=self.snapshot();self.chat();self.assertEqual(self.model.calls[-1]['context']['study_session']['id'],s['id']);self.assertEqual(before,self.snapshot())
    def test_unrelated_session_excluded(self):
        from mindos.learning.execution import StudySessionService
        StudySessionService(self.store).start('owner',{'course_id':self.second['id']});self.chat();self.assertIsNone(self.model.calls[-1]['context']['study_session'])
    def test_unrelated_chat_classified_not_persisted(self):
        self.model.transform=lambda p,v:{**v,'learning_relevant':False};self.assertFalse(self.chat('今天天气如何？')['saved']);self.assertEqual(self.history(),[])
    def test_visual_request_uses_real_diagram(self):
        r=self.chat('请用图示解释当前知识');self.assertFalse(r['fallback']);self.assertTrue(any(b['type']=='diagram' for b in r['blocks']))
    def test_no_multiple_socratic_questions(self):
        self.model.transform=lambda p,v:{**v,'blocks':v['blocks']+[{'type':'question','content':'另一个问题'}]};self.assertTrue(self.chat('引导我理解这个知识')['fallback'])
    def test_future_scope_rejects_expanded_formula(self):
        self.model.transform=lambda p,v:{**v,'blocks':[{'type':'paragraph','content':'未来知识计算过程：QK=1。逐步展开未来知识。'}]};self.assertTrue(self.chat()['fallback'])
    def test_tutor_does_not_save_entire_context(self):
        self.chat()
        with self.store.connect() as db:raw=db.execute("SELECT payload_json FROM tutor_messages WHERE role='assistant'").fetchone()[0]
        for k in ['recent_dialogue','recent_learning','user_state','study_session','pending_questions']:self.assertNotIn(k,raw)
    def test_concurrent_duplicate_single_exchange(self):
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(lambda _:self.chat(request_id='concurrent'),range(2)))
        self.assertEqual(len(self.model.calls),1);self.assertEqual(len(self.history()),2);self.assertEqual(results[0]['messages'],results[1]['messages'])
    def test_authentic_help_marks_before_failed_model_and_no_knowledge_write(self):
        from mindos.learning.authentic import AuthenticAssessmentService
        from authentic_fixture import AuthenticModel
        sid=self.course['sections'][0]['id'];self.store.save_lesson('owner',self.cid,sid,'查询表示需求，键用于匹配，值提供内容。')
        task=AuthenticAssessmentService(self.store).start('owner',self.cid,'a1','explanation',AuthenticModel())['task']
        before=self.snapshot();self.model.transform=lambda p,v:{'bad':True};r=self.chat(current_context={'authentic_task_id':task['id']})
        self.assertTrue(r['fallback']);self.assertEqual(before,self.snapshot());self.assertEqual(self.model.calls[-1]['context']['assessment_mode'],'authentic')
        with self.store.connect() as db:self.assertEqual(db.execute('SELECT hint_used FROM authentic_tasks WHERE id=?',(task['id'],)).fetchone()[0],1)
    def test_final_help_uses_true_target_and_cannot_replace_final(self):
        from final_fixture import seed,FinalModel
        from mindos.learning.final import FinalAssessmentService
        c=seed(self.store,title='P6终局范围',count=2);cid=c['id'];svc=FinalAssessmentService(self.store);svc.complete_content('owner',cid);svc.start('owner',cid);final=svc.assessment('owner',cid,FinalModel());self.cid=cid
        before=self.snapshot();self.chat(current_context={'section_ordinal':2})
        ctx=self.model.calls[-1]['context'];self.assertEqual(ctx['assessment_mode'],'final');self.assertEqual(ctx['current_context']['knowledge_atom_id'],final['current_quiz']['item']['atom_id']);self.assertEqual(before,self.snapshot())
    def test_observation_application_recommends_p2_without_creating_task(self):
        self.model.transform=lambda p,v:{**v,'observations':[{'atom_id':'a1','observation_type':'possible_gap','description':'可能需要应用练习','supporting_quote':p['message'],'confidence':.7}]}
        before=self.snapshot();r=self.chat('我不会把知识用于应用题');o=r['observations'][0];self.assertEqual(o['recommendations'][0]['kind'],'authentic_assessment');self.assertEqual(before,self.snapshot())
        with self.store.connect() as db:self.assertEqual(db.execute('SELECT count(*) FROM authentic_tasks').fetchone()[0],0)
    def test_important_insight_requires_user_own_interpretation(self):
        self.model.transform=lambda p,v:{**v,'memories':[{'memory_type':'important_insight','content':'理解分工','supporting_quote':p['message']}]}
        self.chat('再解释一遍')
        with self.store.connect() as db:self.assertEqual(db.execute('SELECT count(*) FROM tutor_memories').fetchone()[0],0)
        self.chat('原来查询和键是不同角色')
        with self.store.connect() as db:self.assertEqual(db.execute('SELECT count(*) FROM tutor_memories').fetchone()[0],1)
    def test_course_copy_does_not_copy_tutor_memory(self):
        self.observation();clone=self.store.copy_course('owner',self.cid);self.assertEqual(TutorMemoryStore(self.store).history('owner',clone['id'])['messages'],[]);self.assertEqual(TutorObservationService(self.store).list('owner',clone['id'])['observations'],[])
    def test_small_history_limit_and_no_cross_section_recent_dialogue(self):
        for i in range(7):self.chat('解释概念 '+str(i))
        self.store.advance('owner',self.cid,1);self.chat(current_context={'section_ordinal':2,'knowledge_atom_id':'future'});self.assertEqual(self.model.calls[-1]['context']['recent_dialogue'],[])
    def test_active_authentic_scope_cannot_be_bypassed_by_omitting_selector(self):
        from mindos.learning.authentic import AuthenticAssessmentService
        from authentic_fixture import AuthenticModel
        self.store.save_lesson('owner',self.cid,self.course['sections'][0]['id'],'查询表示需求，键用于匹配，值提供内容。')
        task=AuthenticAssessmentService(self.store).start('owner',self.cid,'a1','explanation',AuthenticModel())['task'];self.chat(current_context={})
        self.assertEqual(self.model.calls[-1]['context']['assessment_mode'],'authentic')
        with self.store.connect() as db:self.assertEqual(db.execute('SELECT hint_used FROM authentic_tasks WHERE id=?',(task['id'],)).fetchone()[0],1)
    def test_invalid_raw_model_output_not_persisted_in_diagnostics(self):
        from unittest.mock import patch
        from mindos.model import ModelGateway
        log=Path(self.temp.name)/'diagnostics.jsonl';gateway=ModelGateway({'diagnostic_path':str(log)})
        with patch.object(gateway,'_chat',return_value='{"invalid_payload_secret":"must-not-save"}'):
            r=self.svc.chat('owner',{'context_id':self.cid,'message':'解释当前知识'},gateway,None)
        self.assertTrue(r['fallback']);self.assertNotIn('must-not-save',log.read_text());self.assertNotIn('invalid_payload_secret',log.read_text());self.assertEqual(self.history(),[])

    def test_current_growth_task_and_goal_read_without_starting_timer(self):
        from growth_fixture import GrowthModel,browser_seed
        c=browser_seed(self.store,'owner');svc,gid=GrowthModel().growth_goal(self.store);plan=svc.generate('owner',gid)['roadmap'];task=next(t for t in plan['tasks'] if t['target_id']==c['id'] and t['status'] in {'ready','active'});svc.task_action('owner',gid,task['id'],'start');self.cid=c['id']
        before=self.snapshot();self.chat('请解释当前知识');ctx=self.model.calls[-1]['context'];self.assertEqual(ctx['growth_task']['id'],task['id']);self.assertEqual(ctx['learning_goal']['id'],gid);self.assertIsNone(ctx['study_session']);self.assertEqual(before,self.snapshot())
