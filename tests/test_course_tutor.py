"""Course assistant context, search boundaries, history and learning-state isolation."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from mindos.storage import Storage
from mindos.course_tutor import CourseTutorService
from mindos.model import ModelUnavailable
from block_fixture import make_blocks

class Model:
    def __init__(self):self.contexts=[];self.histories=[];self.searches=[];self.ids=['a1','invented','future']
    def plan_course_tutor(self,context,question,atoms):return {'need_search':False,'strategy':'直观解释','queries':['AI 最新版本']}
    def answer_course_tutor(self,context,question,history,route,search):
        self.contexts.append(copy.deepcopy(context));self.histories.append(copy.deepcopy(history));self.searches.append(copy.deepcopy(search))
        return {'blocks':make_blocks(context['teaching_action'],f"简单理解：这里是 {context['course']['title']} 的解释。直观解释：用基础例子理解。与当前课程关联：{context['current_context']['section_title']}。"),'related_atom_ids':self.ids}

class Search:
    def __init__(self):self.calls=[]
    def search(self,queries,topic=''):
        self.calls.append((queries,topic));return [{'title':'实际检索的公开页面','url':'https://example.org/source','description':'真实服务返回的短摘要','provider':'测试公开来源'}]

class TutorTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.store=Storage(Path(self.temp.name)/'db.sqlite3');self.service=CourseTutorService(self.store);self.model=Model();self.search=Search()
        self.course=self.create('图论基础');self.second=self.create('独立代数课程')
    def tearDown(self):self.temp.cleanup()
    def create(self,title):
        draft=self.store.save_draft('owner',title,'理解原理和解题技巧','',{'sections':[{'title':'基础定义','objective':'从零理解'},{'title':'后续内容','objective':'深入理解'}]},[])
        course=self.store.confirm_draft('owner',draft['id'],1)
        self.store.save_graph('owner',course['id'],{'atoms':[{'id':'a1','section':1,'title':'基础概念','summary':'基础概念的定义','why':'支持后续理解','type':'concept','depth':2},{'id':'future','section':2,'title':'未来知识','summary':'尚未学习的知识','why':'以后逐步学习','type':'concept','depth':2}], 'edges':[{'from':'a1','to':'future','type':'prerequisite'}]})
        return course
    def send(self,message='什么是基础概念？',cid=None,**kwargs):
        return self.service.chat('owner',cid or self.course['id'],{'message':message,**kwargs},self.model,lambda mode:self.search)
    def learning_snapshot(self,cid):
        with self.store.connect() as db:
            return {table:[tuple(r) for r in db.execute('SELECT * FROM '+table+' WHERE course_id=?',(cid,))] for table in ['sections','course_graphs','learning_events','quizzes','tutor_turns','atom_content','atom_turns','source_documents','production_batches']}

    def test_context_includes_current_atom_page_state_and_structure_without_learning_writes(self):
        cid=self.course['id'];section=self.course['sections'][0]
        self.store.save_lesson('owner',cid,section['id'],'服务端实际课程讲解')
        before=self.learning_snapshot(cid)
        result=self.send(current_context={'section_ordinal':1,'knowledge_atom_id':'a1','atom_mode':'quick','page_content':'伪造页面内容'})
        ctx=self.model.contexts[-1]
        self.assertEqual(ctx['current_context']['page_content']['chapter_lesson'],'服务端实际课程讲解')
        self.assertNotIn('伪造页面内容',json.dumps(ctx,ensure_ascii=False))
        self.assertEqual(ctx['course']['learner_level'],'零基础')
        self.assertTrue(ctx['sections']);self.assertTrue(ctx['knowledge_atoms']);self.assertIn('mastery',ctx['learner_state'])
        self.assertEqual([a['id'] for a in result['related_knowledge']],['a1'])
        self.assertEqual(self.learning_snapshot(cid),before);self.assertEqual(self.search.calls,[])
        self.assertEqual(self.store.course('owner',cid)['current_ordinal'],1)

    def test_course_and_owner_isolation_and_no_future_context(self):
        self.send(request_id='one');self.send(cid=self.second['id'],request_id='two')
        self.assertEqual(self.model.histories[-1],[])
        first=self.store.assistant_history('owner',self.course['id'])['messages']
        self.assertEqual(len(first),2);self.assertNotIn(self.second['title'],first[-1]['content'])
        with self.assertRaises(ValueError):self.store.assistant_history('other',self.course['id'])
        with self.assertRaises(ValueError):self.send(current_context={'section_ordinal':2})
        with self.assertRaises(ValueError):self.send(current_context={'section_ordinal':1,'knowledge_atom_id':'future'})
        with self.assertRaises(ValueError):self.send(current_context={'knowledge_atom_id':'foreign'})

    def test_dynamic_information_forces_real_search_even_when_model_declines(self):
        result=self.send('目前最新软件版本的 API 有什么更新？')
        self.assertTrue(self.search.calls);self.assertEqual(result['search']['status'],'ok')
        self.assertEqual(result['search']['sources'][0]['url'],'https://example.org/source')
        self.assertIn('未阅读全文',result['search']['note']);self.assertIn('不是全网搜索',result['search']['note'])
        self.assertEqual(self.model.searches[-1]['status'],'ok')

    def test_failed_search_still_explains_with_visible_uncertainty_and_no_sources(self):
        def failed(mode):raise ValueError('模拟检索不可用')
        result=self.service.chat('owner',self.course['id'],{'message':'最新模型版本是多少'},self.model,failed)
        self.assertEqual(result['search']['status'],'failed');self.assertEqual(result['search']['sources'],[])
        self.assertIn('无法确认最新信息',result['answer'])
        saved=self.store.assistant_history('owner',self.course['id'])['messages'][-1]
        self.assertEqual(saved['search']['sources'],[])

    def test_planner_failure_fallback_and_answer_failure_keep_history_consistent(self):
        class BrokenPlanner(Model):
            def plan_course_tutor(self,*args):raise ModelUnavailable('模拟规划超时')
        self.model=BrokenPlanner();result=self.send('为什么需要这个定义？')
        self.assertEqual(result['search']['planning_warning'],'模拟规划超时');self.assertEqual(self.search.calls,[])
        class BrokenAnswer(Model):
            def answer_course_tutor(self,*args):raise ModelUnavailable('模拟回答超时')
        before=len(self.store.assistant_history('owner',self.course['id'])['messages']);self.model=BrokenAnswer()
        with self.assertRaises(ModelUnavailable):self.send('继续解释')
        self.assertEqual(len(self.store.assistant_history('owner',self.course['id'])['messages']),before)

    def test_semantic_route_can_select_another_unlocked_atom_and_prerequisites(self):
        cid=self.course['id'];self.store.advance('owner',cid,1)
        class Routed(Model):
            def plan_course_tutor(self,*args):return {'need_search':False,'strategy':'关联已学知识','related_atom_ids':['future']}
        self.model=Routed();self.send('为什么使用另一种表示？',current_context={'section_ordinal':1})
        ids={a['id'] for a in self.model.contexts[-1]['knowledge_atoms']}
        self.assertIn('future',ids);self.assertIn('a1',ids)
        self.assertEqual(self.model.contexts[-1]['knowledge_relations'][0]['type'],'prerequisite')
        self.assertEqual(self.store.course('owner',cid)['current_ordinal'],2)

    def test_pending_quiz_answer_is_not_in_context(self):
        cid=self.course['id'];section=self.course['sections'][0];self.store.save_lesson('owner',cid,section['id'],'先学习当前内容')
        self.store.create_quiz('owner',cid,section['id'],[{'prompt':'未作答问题','choices':{'a':'甲','b':'乙'}}],[{'answer':'a','explanation':'保密答案解析 unique-secret'}])
        self.send();serialized=json.dumps(self.model.contexts[-1],ensure_ascii=False)
        self.assertIn('未作答问题',serialized);self.assertNotIn('unique-secret',serialized);self.assertNotIn('"answer"',serialized)

    def test_idempotent_exchange_and_history_pagination(self):
        one=self.send(request_id='duplicate');two=self.send(request_id='duplicate')
        self.assertEqual(one['messages'],two['messages']);self.assertEqual(len(self.model.contexts),1)
        with self.assertRaises(ValueError):self.send('不同问题',request_id='duplicate')
        for i in range(41):self.send('解释定义',request_id='history-'+str(i))
        page=self.store.assistant_history('owner',self.course['id']);self.assertEqual(len(page['messages']),80);self.assertTrue(page['has_more'])
        previous=self.store.assistant_history('owner',self.course['id'],page['messages'][0]['id'])
        self.assertEqual(len(previous['messages']),4);self.assertFalse(previous['has_more'])

    def test_positions_persist_per_course_and_deleted_course_lifecycle(self):
        cid=self.course['id'];self.send();self.store.save_assistant_position('owner',cid,80,700)
        reopened=Storage(self.store.path);self.assertEqual(reopened.assistant_history('owner',cid)['position']['x'],80)
        self.assertIsNone(reopened.assistant_history('owner',self.second['id'])['position'])
        for x,y in [(True,2),(-1,1),(float('nan'),2),(float('inf'),2)]:
            with self.assertRaises(ValueError):self.store.save_assistant_position('owner',cid,x,y)
        with self.assertRaises(ValueError):self.store.save_assistant_position('other',cid,80,700)
        clone=self.store.copy_course('owner',cid);self.assertEqual(self.store.assistant_history('owner',clone['id'])['messages'],[])
        self.assertIsNone(self.store.assistant_history('owner',clone['id'])['position'])
        self.store.recycle_course('owner',cid)
        with self.assertRaises(ValueError):self.send()
        self.store.restore_course('owner',cid);self.assertEqual(len(self.store.assistant_history('owner',cid)['messages']),2)
        self.store.recycle_course('owner',cid);self.store.purge_course('owner',cid,self.course['title'])
        with self.store.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM assistant_message WHERE course_id=?',(cid,)).fetchone()[0],0)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM assistant_position WHERE course_id=?',(cid,)).fetchone()[0],0)

class TutorApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from test_prototype import PrototypeTests
        cls.fixture=PrototypeTests;cls.fixture.setUpClass();cls.search=Search();cls.fixture.server.assistant_search_factory=lambda mode:cls.search
    @classmethod
    def tearDownClass(cls):cls.fixture.tearDownClass()
    def setUp(self):
        self.bridge=self.fixture();self.bridge.setUp();self.bridge.configure();self.search.calls.clear()
        draft=self.fixture.server.storage.save_draft(self.bridge.session_id(),'专属助教课程','理解基础','',{'sections':[{'title':'基础章节','objective':'从零理解'}]},[])
        self.cid=self.fixture.server.storage.confirm_draft(self.bridge.session_id(),draft['id'],1)['id']
    def call(self,suffix,method='GET',body=None,other=False,origin=None):
        import urllib.request,urllib.error
        data=json.dumps(body).encode() if body is not None else None
        req=urllib.request.Request(self.bridge.url+f'/api/courses/{self.cid}/assistant/'+suffix,data=data,method=method,headers={**({'Content-Type':'application/json'} if data else {}),**({'Origin':origin} if origin else {})})
        try:
            with (urllib.request.build_opener() if other else self.bridge.client).open(req,timeout=10) as response:return response.status,json.loads(response.read())
        except urllib.error.HTTPError as exc:return exc.code,json.loads(exc.read())
    def test_gateway_history_position_and_current_context(self):
        status,result=self.call('chat','POST',{'message':'为什么要这样学习？','request_id':'test-question','current_context':{'section_ordinal':1}})
        self.assertEqual(status,200,result);self.assertIn('专属助教课程',result['answer']);self.assertEqual(len(result['messages']),2)
        self.assertEqual(self.call('position','PUT',{'x':80,'y':700})[0],200)
        status,history=self.call('history');self.assertEqual(status,200)
        self.assertEqual(history['position']['x'],80);self.assertEqual(len(history['messages']),2)
        self.assertNotIn('model-test-private-key',json.dumps(history));self.assertNotIn('user_id',history['messages'][0])
        self.assertEqual(self.fixture.server.storage.mastery(self.bridge.session_id(),self.cid)['overall_rate'],None)
    def test_dynamic_search_and_http_failure_guards(self):
        status,result=self.call('chat','POST',{'message':'最新模型版本是什么？'})
        self.assertEqual(status,200,result);self.assertEqual(result['search']['status'],'ok');self.assertTrue(self.search.calls)
        self.assertEqual(self.call('history',other=True)[0],400)
        self.assertEqual(self.call('position','PUT',{'x':1,'y':2},other=True)[0],400)
        self.assertEqual(self.call('position','PUT',{'x':1,'y':2},origin='https://outside.example')[0],400)
        self.assertEqual(self.call('chat','POST',{'message':'问题','current_context':{'section_ordinal':2}})[0],400)
        self.assertEqual(self.call('history?before=invalid')[0],400)
