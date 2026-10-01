"""Regressions for the architecture audit: trust, versioning and module cooperation."""
import copy,json,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
import test_prototype as prototype
from test_knowledge import graph
from test_production import TEXT,candidate
from test_discovery import create
from mindos.storage import Storage
from mindos.acquisition import DirectInputProvider,UploadProvider
from mindos.production import normalize_candidate_result
from mindos.discovery import DiscoveryEngine
from mindos.context import course_materials
from mindos.adaptive import ContentGenerator,ATIEEngine
from mindos.teaching import ContentValidator

class ArchitectureStorageTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.store=Storage(Path(self.temp.name)/'db.sqlite3')
        draft=self.store.save_draft('owner','课程基础','从零学习','',{'sections':[{'title':'概念基础','objective':'建立直觉'},{'title':'应用方法','objective':'练习应用'}]},[])
        self.course=self.store.confirm_draft('owner',draft['id'],1);self.cid=self.course['id'];self.section=self.course['sections'][0]
    def tearDown(self):self.temp.cleanup()
    def duplicate(self):
        self.store.save_graph('owner',self.cid,graph())
        source=self.store.save_source('owner',self.cid,DirectInputProvider().acquire(title='新定义',text=TEXT))
        result=normalize_candidate_result(candidate(source,'概念 1'),source,1,source['metadata']['blocks'],{'a1','a2'})
        return self.store.save_batch('owner',self.cid,source['id'],1,result)
    def test_different_definition_requires_explicit_review(self):
        batch=self.duplicate();before=self.store.graph('owner',self.cid)
        with self.assertRaisesRegex(ValueError,'同名'):self.store.review_batch('owner',self.cid,batch['id'],'verify',['c1'],'')
        self.assertEqual(self.store.graph('owner',self.cid),before)
        self.assertEqual(self.store.batch('owner',self.cid,batch['id'])['status'],'candidate')
    def test_keep_definition_does_not_attach_new_quote_or_verification(self):
        batch=self.duplicate();old=self.store.graph('owner',self.cid)['atoms'][0]
        result=self.store.review_batch('owner',self.cid,batch['id'],'verify',['c1'],'',{'c1':'keep'})
        self.assertEqual(self.store.graph('owner',self.cid)['atoms'][0],old)
        self.assertEqual(result['result']['candidates'][0]['quality_status'],'deprecated')
    def test_replace_definition_keeps_history_mastery_and_marks_content_stale(self):
        batch=self.duplicate();self.store.save_atom_content('owner',self.cid,'a1','quick','旧讲解')
        self.store.learning_event('owner',self.cid,['a1'],'read')
        before=self.store.knowledge_state('owner',self.cid)['overall_rate']
        self.store.review_batch('owner',self.cid,batch['id'],'verify',['c1'],'',{'c1':'replace'})
        atom=self.store.graph('owner',self.cid)['atoms'][0]
        self.assertEqual(atom['summary'],batch['result']['candidates'][0]['summary']);self.assertEqual(atom['quality_status'],'verified')
        detail=self.store.atom_detail('owner',self.cid,'a1');self.assertEqual(detail['content']['quick'],'旧讲解');self.assertTrue(detail['content_metadata']['quick']['stale'])
        self.assertTrue(self.store.knowledge_state('owner',self.cid)['atoms'][0]['read']);self.assertEqual(self.store.knowledge_state('owner',self.cid)['overall_rate'],before)
        with self.store.connect() as db:self.assertEqual(db.execute("SELECT COUNT(*) FROM content_history WHERE object_type='knowledge'").fetchone()[0],1)
    def test_teacher_and_tutor_select_same_upload_with_newer_web_documents(self):
        self.store.policy('owner',self.cid,'user_material_first')
        source=self.store.save_source('owner',self.cid,UploadProvider().acquire(filename='笔记.md',data=TEXT.encode()))
        for n in range(5):
            document=DirectInputProvider().acquire(title=f'网页{n}',text=TEXT);document.origin='web_search';self.store.save_source('owner',self.cid,document)
        course=self.store.course('owner',self.cid)
        selected=course_materials(self.store,'owner',course,self.section['title'])
        self.assertEqual(selected[0]['id'],source['id']);self.assertEqual(len(selected),4)
        from mindos.course_tutor import CourseTutorService
        tutor=CourseTutorService(self.store)
        _,context,_=tutor.context('owner',self.cid,{},'解释基础')
        self.assertEqual([d['id'] for d in selected],[d['id'] for d in context['course_materials']])
    def test_conceptual_scope_overrides_high_math_and_deepen(self):
        state={'learner_level':'基础','cognitive_state':{'status':'partial_understanding','source':'test'},'preferences':{'math_level':'advanced'},'assessment_dimensions':{},'previous_strategy':[]}
        knowledge={'name':'Attention','type':'mechanism','weak_prerequisite':[]}
        scope={'purpose':'建立直觉','teaching_depth':'conceptual','core_atoms':['Attention'],'related_atoms':[],'future_atoms':[]}
        action=ATIEEngine().decide(state,knowledge,scope,'请深入推导',mode='assistant',feedback='deepen')
        self.assertFalse(action['allow_formulas']);self.assertNotIn('formula',action['presentation']);self.assertEqual(action['allowed_depth'],'conceptual')
    def test_backtrack_prerequisite_becomes_core_for_prompt_and_validation(self):
        self.store.save_graph('owner',self.cid,graph());self.store.advance('owner',self.cid,1)
        generator=ContentGenerator(self.store)
        state={'cognitive_state':{'status':'weak','source':'test'},'learner_level':'零基础','preferences':{},'assessment_dimensions':{},'previous_strategy':[]}
        knowledge={'name':'应用方法','type':'concept','weak_prerequisite':['概念 1']}
        section=self.store.course('owner',self.cid)['sections'][1]
        with patch.object(generator.states,'read',return_value=(state,knowledge)):
            _,_,scope,action=generator.prepare('owner',self.cid,section,'补充前置知识',feedback='backtrack')
        self.assertEqual(action['action'],'BACKTRACK');self.assertIn('概念 1',scope['core_atoms']);self.assertNotIn('概念 1',scope['related_atoms'])
        self.assertTrue(ContentValidator().check('概念 1：'+('用生活中的水果帮助理解。'*70),scope)['passed'])
    def test_edit_invalidates_content_without_erasing_history_or_advancing(self):
        self.store.save_lesson('owner',self.cid,self.section['id'],'旧讲解');original=self.store.course('owner',self.cid)
        self.store.update_course('owner',self.cid,{'goal':'掌握考试技巧','level':'高级'})
        updated=self.store.course('owner',self.cid)
        self.assertTrue(updated['sections'][0]['lesson_stale']);self.assertEqual(updated['sections'][0]['difficulty'],'advanced')
        self.assertEqual(updated['current_ordinal'],1)
        with self.assertRaisesRegex(ValueError,'依据已更新'):
            self.store.save_lesson('owner',self.cid,self.section['id'],'过期生成',expected_revision=original['content_revision'],regenerate=True)
        self.store.save_lesson('owner',self.cid,self.section['id'],'新讲解',expected_revision=updated['content_revision'],regenerate=True)
        self.assertFalse(self.store.course('owner',self.cid)['sections'][0]['lesson_stale']);self.assertEqual(len(self.store.tutor_turns('owner',self.cid,self.section['id'])),2)
        with self.store.connect() as db:self.assertIn('旧讲解',db.execute("SELECT snapshot_json FROM content_history WHERE object_type='lesson'").fetchone()[0])
    def test_goal_edit_with_unchanged_level_preserves_progressive_section_difficulty(self):
        with self.store.connect() as db:db.execute("UPDATE sections SET difficulty='advanced' WHERE course_id=? AND ordinal=2",(self.cid,))
        self.store.update_course('owner',self.cid,{'goal':'更新学习目标','level':'入门'})
        sections=self.store.course('owner',self.cid)['sections']
        self.assertEqual(sections[0]['difficulty'],'beginner');self.assertEqual(sections[1]['difficulty'],'advanced')

    def test_atom_regeneration_keeps_old_version(self):
        self.store.save_graph('owner',self.cid,graph());self.store.save_atom_content('owner',self.cid,'a1','quick','旧讲解')
        old=self.store.course('owner',self.cid)['content_revision'];self.store.policy('owner',self.cid,'user_material_first')
        with self.assertRaises(ValueError):self.store.save_atom_content('owner',self.cid,'a1','quick','过期',expected_revision=old,regenerate=True)
        self.store.save_atom_content('owner',self.cid,'a1','quick','新讲解',regenerate=True)
        self.assertFalse(self.store.atom_detail('owner',self.cid,'a1')['content_metadata']['quick']['stale'])
        with self.store.connect() as db:self.assertIn('旧讲解',db.execute('SELECT snapshot_json FROM content_history').fetchone()[0])
    def test_partial_reviewed_graph_is_completed_without_replacing_verified_atom(self):
        initial=graph();atom=initial['atoms'][0];atom['quality_status']='verified';atom['source_reference']=[{'quote':'实际资料原文内容引用','document_id':'real'}]
        with self.store.connect() as db:db.execute('INSERT INTO course_graphs VALUES(?,?,?)',(self.cid,json.dumps({'atoms':[atom],'edges':[]}),''))
        old=self.store.graph('owner',self.cid)
        self.assertFalse(self.store.knowledge_state('owner',self.cid)['structure_complete'])
        self.store.complete_index('owner',self.cid,graph(),old)
        updated=self.store.graph('owner',self.cid);self.assertEqual(updated['atoms'][0]['summary'],atom['summary']);self.assertEqual(updated['atoms'][0]['source_reference'],atom['source_reference'])
        knowledge=self.store.knowledge_state('owner',self.cid);self.assertTrue(knowledge['structure_complete']);self.assertEqual(knowledge['reviewed_count'],1);self.assertEqual(knowledge['index_count'],1)
        self.assertEqual(updated['atoms'][1]['quality_status'],'candidate');self.assertFalse(updated['atoms'][1]['source_reference'])
    def test_live_discovery_survives_reopen_and_new_engine(self):
        identifier=self.store.begin_discovery('owner',self.cid,'worker')
        reopened=Storage(self.store.path);DiscoveryEngine(reopened)
        self.assertEqual(reopened.discovery('owner',self.cid)['status'],'running');self.assertIsNone(reopened.begin_discovery('owner',self.cid))
        self.assertTrue(reopened.discovery_heartbeat(identifier,'worker'));self.assertFalse(reopened.discovery_heartbeat(identifier,'other'))
    def test_expired_discovery_recovered_and_late_worker_cannot_restart_it(self):
        identifier=self.store.begin_discovery('owner',self.cid,'worker')
        with self.store.connect() as db:db.execute('UPDATE discovery_runs SET heartbeat_at=? WHERE id=?',(time.time()-301,identifier))
        DiscoveryEngine(self.store);self.assertEqual(self.store.discovery('owner',self.cid)['status'],'interrupted')
        self.assertFalse(self.store.discovery_update(identifier,{'stage':'late'}));self.assertIsNotNone(self.store.begin_discovery('owner',self.cid,'new'))

class ArchitectureApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):prototype.PrototypeTests.setUpClass()
    @classmethod
    def tearDownClass(cls):prototype.PrototypeTests.tearDownClass()
    def setUp(self):self.fixture=prototype.PrototypeTests();self.fixture.setUp();self.fixture.configure()
    def test_changed_model_url_cannot_reuse_old_key(self):
        x=self.fixture;profile=x.call('/api/bootstrap')[1]['profiles'][0]
        old=prototype.PrototypeTests.server.storage.model_profile(profile['id'])
        body={'id':profile['id'],'name':'新地址','base_url':'https://other.example/v1','chat_model':'test','api_key':''}
        status,result=x.call('/api/models/save',body);self.assertEqual(status,400);self.assertIn('地址已改变',result['error'])
        self.assertEqual(prototype.PrototypeTests.server.storage.model_profile(profile['id']),old)
        status,result=x.call('/api/models/save',{**body,'clear_key':True});self.assertEqual(status,200)
        self.assertEqual(prototype.PrototypeTests.server.storage.model_profile(profile['id'])['encrypted_api_key'],'')
    def test_same_model_url_preserves_key_and_explicit_new_key_allows_new_address(self):
        x=self.fixture;profile=x.call('/api/bootstrap')[1]['profiles'][0];store=prototype.PrototypeTests.server.storage
        old=store.model_profile(profile['id'])
        body={'id':profile['id'],'name':'保持','base_url':old['base_url'],'chat_model':'test','api_key':''}
        self.assertEqual(x.call('/api/models/save',body)[0],200);self.assertEqual(store.model_profile(profile['id'])['encrypted_api_key'],old['encrypted_api_key'])
        self.assertEqual(x.call('/api/models/save',{**body,'base_url':'https://other.example','api_key':'new-test-key'})[0],200)
        self.assertNotEqual(store.model_profile(profile['id'])['encrypted_api_key'],old['encrypted_api_key'])
    def test_manual_search_accepts_short_keywords_and_rejects_noise(self):
        x=self.fixture;cid=x.draft_and_confirm('短词测试课程','理解基础')
        for worker in prototype.PrototypeTests.server.discovery_engine.threads:worker.join(3)
        with patch('mindos.server.WebSearchProvider.search',return_value=[]) as search:
            for query in ('AI','ML','RL','图论'):
                status,result=x.call('/api/sources/search',{'course_id':cid,'search_mode':'public','query':query});self.assertEqual(status,200,result)
            for query in ('  ','!!!','---'):
                self.assertEqual(x.call('/api/sources/search',{'course_id':cid,'search_mode':'public','query':query})[0],400)
            self.assertEqual(search.call_count,4)
