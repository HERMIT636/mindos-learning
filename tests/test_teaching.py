"""Teaching scope, migration, repair and unchanged learning evidence."""
import json
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
from mindos.model import ModelGateway, ModelUnavailable
from mindos.storage import Storage
from mindos.teaching import TeachingOrchestrator, ContentValidator, generate_lesson
import test_prototype as prototype
from block_fixture import make_blocks


INTRO = {'title': '课程导引与预备知识', 'objective': '理解Transformer背景和学习路线',
         'purpose': '建立整体认知', 'core_atoms': ['Transformer背景', '序列建模问题'],
         'related_atoms': ['Attention'], 'future_atoms': ['QKV', 'Multi-head Attention', 'Encoder'],
         'difficulty': 'beginner', 'teaching_depth': 'introductory'}
ATTENTION = {'title': 'Attention机制', 'objective': '理解QKV计算过程', 'core_atoms': ['Attention', 'QKV'],
             'future_atoms': ['Multi-head Attention', 'Encoder'], 'teaching_depth': 'detailed'}
BAD = '## QKV计算\n\nQKV计算先将输入映射到三个向量。Q = XWq；K = XWk；V = XWv。随后计算 softmax(QK / sqrt(d))V。'
GOOD = '## Transformer背景\n模型需要理解序列中远处信息的联系。RNN逐步处理序列，处理很长的序列时有局限。\n\nAttention可以想成挑选值得关注的信息，本节先建立直觉，具体计算在后续小节学习。'


class TeachingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name)/'db.sqlite3'
        self.store = Storage(self.path)
        draft = self.store.save_draft('owner', 'Transformer原理', '从零理解原理', '',
                                      {'sections': [INTRO, ATTENTION, {'title': '模型结构', 'objective': '深入理解结构', 'core_atoms': ['Multi-head Attention', 'Encoder']}]}, [])
        self.course = self.store.confirm_draft('owner',draft['id'],1)
        self.cid = self.course['id']; self.lesson = self.course['sections'][0]
        self.orchestrator = TeachingOrchestrator(self.store)
        self.ctx = self.orchestrator.context('owner',self.cid,self.lesson['id'])
    def tearDown(self): self.temp.cleanup()

    def test_scope_without_graph_and_short_knowledge_names(self):
        self.assertEqual(self.ctx['core_atoms'],INTRO['core_atoms'])
        self.assertEqual(self.ctx['related_atoms'],['Attention'])
        self.assertIn('QKV',self.ctx['future_atoms'])
        self.assertEqual({e['knowledge']:e['level'] for e in self.ctx['exposure']}['Attention'],1)
        self.assertEqual(self.ctx['teaching_depth'],'introductory')
        self.assertEqual(self.store.mastery('owner',self.cid)['sections'][0]['test_count'],0)
        self.assertEqual(self.store.course('owner',self.cid)['current_ordinal'],1)

    def test_future_unlocking_and_owner_isolation(self):
        with self.assertRaises(ValueError):self.orchestrator.context('other',self.cid,self.lesson['id'])
        second=self.course['sections'][1]
        with self.assertRaises(ValueError):self.orchestrator.context('owner',self.cid,second['id'])
        self.store.advance('owner',self.cid,1)
        ctx=self.orchestrator.context('owner',self.cid,second['id'])
        self.assertIn('QKV',ctx['core_atoms']);self.assertNotIn('QKV',ctx['future_atoms'])
        self.assertTrue(ContentValidator().check(BAD,ctx)['passed'])

    def test_graph_relations_compute_prerequisite_scope_without_mutating_graph(self):
        atoms=[{'id':str(i),'section':n,'title':title,'type':'concept','summary':title+'含义','why':'解释前置概念','depth':2}
               for i,n,title in [(1,1,'序列建模问题'),(2,2,'QKV'),(3,3,'Encoder')]]
        graph=self.store.save_graph('owner',self.cid,{'atoms':atoms,'edges':[{'from':'1','to':'2','type':'prerequisite'}]})
        self.store.advance('owner',self.cid,1)
        ctx=self.orchestrator.context('owner',self.cid,self.course['sections'][1]['id'])
        self.assertIn('序列建模问题',ctx['related_atoms']);self.assertIn('Encoder',ctx['future_atoms'])
        self.assertEqual(self.store.graph('owner',self.cid),graph)

    def test_validator_brief_mentions_allowed_formulas_and_future_headings_flagged(self):
        validator=ContentValidator()
        self.assertTrue(validator.check(GOOD,self.ctx)['passed'])
        self.assertFalse(validator.check(BAD,self.ctx)['passed'])
        self.assertFalse(validator.check('QKV：Q = XWq',self.ctx)['passed'])
        self.assertFalse(validator.check('## Encoder\n\n由残差连接与前馈网络组成，需要逐层处理输入。',self.ctx)['passed'])
        self.assertTrue(validator.check('我们后面将学习QKV、Multi-head Attention和Encoder。',self.ctx)['passed'])
        self.assertTrue(validator.check('背景中的序列可以表示为 x = [1, 2, 3]。QKV计算会在后续小节学习。',self.ctx)['passed'])
        self.assertTrue(validator.check('Transformer不是只有Attention，还包括前馈网络、残差连接和层归一化。这里只提名称，具体作用后续学习。',self.ctx)['passed'])
        self.assertTrue(validator.check('Encoder包含Attention、前馈网络和残差连接。这些结构会在后续章节展开。',self.ctx)['passed'])
        self.assertTrue(validator.check('TR = 1\n例子中只有一个等式。',self.ctx)['passed'])
        self.assertFalse(validator.check('a=1\nb=2\nc=3\nd=4',self.ctx)['passed'])

    def test_actual_model_overview_regression_component_and_prerequisite_names_are_not_details(self):
        validator=ContentValidator()
        overview='**误区：Transformer就是Attention。**\n不准确。Attention是核心机制之一，但Transformer还包括其他部分，比如前馈网络、残差连接、层归一化等。只是本课程重点放在Attention和Encoder上。'
        prerequisites='1. 向量可以理解成一串数字。\n2. 矩阵乘法的基本直觉：一组数变换成另一组数。\n3. 概率和加权平均：Attention里会用到权重的概念。'
        self.assertTrue(validator.check(overview,self.ctx)['passed'])
        self.assertTrue(validator.check(prerequisites,self.ctx)['passed'])
        self.assertFalse(validator.check('Encoder中的前馈网络执行两层线性变换，中间通过激活函数引入非线性。',self.ctx)['passed'])
        self.assertFalse(validator.check('QKV的点积计算过程：将向量逐项相乘后求和。',self.ctx)['passed'])

    def test_one_repair_then_save_only_accepted_content_and_record(self):
        class Model:
            repairs=0
            def teach_section(_, *args):return BAD
            def repair_section(_, *args):_.repairs+=1;return GOOD
        model=Model()
        content,validation=generate_lesson(model,self.course,self.lesson,{},[],self.ctx)
        self.assertEqual(content,GOOD);self.assertEqual(model.repairs,1);self.assertEqual(validation['repair_attempts'],1)
        self.store.save_lesson('owner',self.cid,self.lesson['id'],content,self.ctx,validation)
        self.store.save_lesson('owner',self.cid,self.lesson['id'],'后到请求不覆盖')
        with self.store.connect() as db:
            records=db.execute('SELECT * FROM lesson_teaching_records').fetchall()
            self.assertEqual(len(records),1);self.assertIn('Transformer背景',json.loads(records[0]['covered_atoms']))
            self.assertTrue(json.loads(records[0]['validation_json'])['passed'])
        self.assertEqual(len(self.store.tutor_turns('owner',self.cid,self.lesson['id'])),1)
        self.assertEqual(self.store.mastery('owner',self.cid)['sections'][0]['test_count'],0)
        self.assertEqual(self.store.knowledge_state('owner',self.cid)['atoms'],[])
        self.assertTrue(self.orchestrator.context('owner',self.cid,self.lesson['id'])['previous_teaching'])

    def test_failed_repair_or_model_leaves_no_partial_teaching_history(self):
        class Model:
            def teach_section(_, *args):return BAD
            def repair_section(_, *args):return BAD
        with self.assertRaises(ModelUnavailable):generate_lesson(Model(),self.course,self.lesson,{},[],self.ctx)
        self.assertIsNone(self.store.course('owner',self.cid)['sections'][0]['lesson'])
        self.assertEqual(self.store.tutor_turns('owner',self.cid,self.lesson['id']),[])
        with self.store.connect() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM lesson_teaching_records').fetchone()[0],0)

    def test_existing_schema_migrates_without_overwriting_lesson_or_ids(self):
        old=Path(self.temp.name)/'legacy.sqlite3'
        with sqlite3.connect(old) as db:
            db.executescript("CREATE TABLE courses(id TEXT PRIMARY KEY,session_id TEXT,title TEXT,goal TEXT,current_ordinal INTEGER,created_at TEXT);CREATE TABLE sections(id TEXT PRIMARY KEY,course_id TEXT,ordinal INTEGER,title TEXT,objective TEXT,lesson TEXT,created_at TEXT);")
            db.execute('INSERT INTO courses VALUES(?,?,?,?,?,?)',('c','owner','旧课','目标',1,'old'))
            db.execute('INSERT INTO sections VALUES(?,?,?,?,?,?,?)',('s','c',1,'课程导引','建立直觉','保留原讲义','old'))
        store=Storage(old);Storage(old)
        s=store.course('owner','c')['sections'][0]
        self.assertEqual(s['id'],'s');self.assertEqual(s['lesson'],'保留原讲义');self.assertEqual(s['purpose'],'建立直觉')
        self.assertEqual(s['teaching_depth'],'introductory')

    def test_copy_preserves_metadata_but_drops_teaching_records_restore_and_purge(self):
        self.store.save_lesson('owner',self.cid,self.lesson['id'],GOOD,self.ctx,{'passed':True})
        clone=self.store.copy_course('owner',self.cid)
        self.assertEqual(clone['sections'][0]['core_atoms'],INTRO['core_atoms'])
        clone_context=self.orchestrator.context('owner',clone['id'],clone['sections'][0]['id'])
        self.assertEqual(clone_context['previous_teaching'],[])
        self.store.recycle_course('owner',self.cid)
        with self.assertRaises(ValueError):self.orchestrator.context('owner',self.cid,self.lesson['id'])
        self.store.restore_course('owner',self.cid)
        self.assertTrue(self.orchestrator.context('owner',self.cid,self.lesson['id'])['previous_teaching'])
        self.store.recycle_course('owner',self.cid);self.store.purge_course('owner',self.cid,self.course['title'])
        with self.store.connect() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM lesson_teaching_records WHERE course_id=?',(self.cid,)).fetchone()[0],0)

    def test_model_prompt_includes_scope_and_exploration_rules(self):
        class Capture(ModelGateway):
            def _chat(_,system,user,**kwargs):_.system=system;_.payload=json.loads(user);return GOOD
        model=Capture({})
        section={**self.lesson,'teaching_context':self.ctx}
        model.teach_section(self.course,section,{},[])
        self.assertEqual(model.payload['teaching_context'],self.ctx)
        self.assertIn('Level 0',model.system);self.assertIn('不强行加入公式',model.system)
        model.answer_question(self.course,section,[],'Attention具体怎么算？')
        self.assertIn('用户主动问后续知识',model.system);self.assertEqual(model.payload['question'],'Attention具体怎么算？')


class TeachingApiTests(unittest.TestCase):
    setUpClass=classmethod(prototype.PrototypeTests.setUpClass.__func__)
    tearDownClass=classmethod(prototype.PrototypeTests.tearDownClass.__func__)
    setUp=prototype.PrototypeTests.setUp
    call=prototype.PrototypeTests.call
    configure=prototype.PrototypeTests.configure
    session_id=prototype.PrototypeTests.session_id
    draft_and_confirm=prototype.PrototypeTests.draft_and_confirm

    def test_context_api_and_existing_lesson_generation_route(self):
        self.configure();cid=self.draft_and_confirm('教学范围测试课程')
        course=self.server.storage.course(self.session_id(),cid);first,second=course['sections'][:2]
        path=f"/api/lessons/{first['id']}/teaching-context"
        status,context=self.call(path)
        self.assertEqual(status,200);self.assertEqual(context['lesson_id'],first['id'])
        self.assertEqual(self.call(f"/api/lessons/{second['id']}/teaching-context")[0],400)
        self.assertEqual(self.call('/api/lessons/foreign/teaching-context')[0],400)
        self.assertEqual(self.call('/api/sections/lesson',{'course_id':cid,'ordinal':1})[0],200)
        self.assertEqual(prototype.FakeProvider.lesson_payloads[-1]['teaching_context']['lesson_id'],first['id'])
        self.assertEqual(self.call('/api/sections/ask',{'course_id':cid,'ordinal':1,'question':'后续知识怎么学？'})[0],200)
        self.assertEqual(self.server.storage.course(self.session_id(),cid)['current_ordinal'],1)
        with self.server.storage.connect() as db:
            record=db.execute('SELECT validation_json FROM lesson_teaching_records WHERE lesson_id=?',(first['id'],)).fetchone()
        self.assertTrue(json.loads(record[0])['passed'])

    def test_failed_repair_returns_error_without_saving_then_successful_retry(self):
        self.configure();store=self.server.storage;owner=self.session_id()
        draft=store.save_draft(owner,'Transformer接口验收','建立基础','',{'sections':[INTRO,ATTENTION]},[])
        course=store.confirm_draft(owner,draft['id'],1);cid=course['id'];lesson_id=course['sections'][0]['id']
        def packet(payload,content):return {'blocks':make_blocks(payload['teaching_action'],content.replace('## ',''))}
        with patch.object(ModelGateway,'generate_teaching_blocks',side_effect=lambda p:packet(p,BAD)),patch.object(ModelGateway,'repair_teaching_blocks',side_effect=lambda p,*_:packet(p,BAD)) as repair:
            status,result=self.call('/api/sections/lesson',{'course_id':cid,'ordinal':1})
            self.assertEqual(status,503);self.assertIn('停止保存',result['error']);self.assertEqual(repair.call_count,1)
        self.assertIsNone(store.course(owner,cid)['sections'][0]['lesson']);self.assertEqual(store.tutor_turns(owner,cid,lesson_id),[])
        with store.connect() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM lesson_teaching_records WHERE course_id=?',(cid,)).fetchone()[0],0)
        with patch.object(ModelGateway,'generate_teaching_blocks',side_effect=lambda p:packet(p,BAD)),patch.object(ModelGateway,'repair_teaching_blocks',side_effect=lambda p,*_:packet(p,GOOD)):
            self.assertEqual(self.call('/api/sections/lesson',{'course_id':cid,'ordinal':1})[0],200)
        self.assertIn(GOOD.replace('## ',''),store.course(owner,cid)['sections'][0]['lesson'])
        self.assertTrue(store.course(owner,cid)['sections'][0]['lesson_blocks'])
        self.assertEqual(store.mastery(owner,cid)['sections'][0]['test_count'],0)
        self.assertEqual(store.course(owner,cid)['current_ordinal'],1)


if __name__=='__main__':unittest.main()
