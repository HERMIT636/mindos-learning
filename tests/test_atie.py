"""Evidence-driven teaching choices, typed content and state isolation."""
import copy
import json
import tempfile
import unittest
import urllib.request
import urllib.error
from pathlib import Path
from unittest.mock import patch
import test_prototype as prototype
from mindos.storage import Storage
from mindos.adaptive import ATIEEngine,ContentGenerator,LearningStateManager
from mindos.adaptive.content_generator import validate_blocks,flatten_blocks
from mindos.model import ModelUnavailable,ModelGateway,ModelStructuredOutputError
from block_fixture import make_blocks

class TeachingModel:
    def __init__(self):self.payloads=[]
    def generate_teaching_blocks(self,payload):
        self.payloads.append(copy.deepcopy(payload));return {'blocks':make_blocks(payload['teaching_action'],'本节Attention帮助我们判断哪些信息更重要。')}
    def repair_teaching_blocks(self,*args):raise ModelUnavailable('修订服务不可用')

class ATIETests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.store=Storage(Path(self.temp.name)/'db.sqlite3')
        self.course=self.create('Attention课程');self.cid=self.course['id'];self.section=self.course['sections'][0]
        self.generator=ContentGenerator(self.store);self.model=TeachingModel()
    def tearDown(self):self.temp.cleanup()
    def create(self,title):
        draft=self.store.save_draft('owner',title,'从零理解QKV的角色与计算','',{'sections':[{'title':'Attention机制','objective':'建立注意力直觉','core_atoms':['Attention','QKV'],'teaching_depth':'detailed'},
                         {'title':'编码器','objective':'理解模型结构','core_atoms':['Encoder'],'teaching_depth':'detailed'}]},[])
        course=self.store.confirm_draft('owner',draft['id'],1)
        self.store.save_graph('owner',course['id'],{'atoms':[{'id':'a1','section':1,'title':'Attention','type':'mechanism','summary':'根据信息的重要程度分配权重','why':'理解序列关系','depth':2},
                     {'id':'a2','section':2,'title':'Encoder','type':'mechanism','summary':'模型中的编码结构','why':'理解模型结构','depth':3}],'edges':[{'from':'a1','to':'a2','type':'prerequisite'}]})
        return course
    def prepare(self,message='',**kwargs):return self.generator.prepare('owner',self.cid,self.section,message,**kwargs)

    def test_novice_mechanism_plan_and_blocks_are_not_a_markdown_article(self):
        package,scope=self.generator.lesson('owner',self.course,self.section,self.model,self.store.mastery('owner',self.cid),[])
        self.assertEqual([b['type'] for b in package['blocks']],['question','analogy','diagram','concept','checkpoint'])
        decision=package['teaching_action'];self.assertEqual(decision['action'],'INTRODUCE');self.assertEqual(decision['structure_level'],3)
        self.assertFalse(decision['allow_formulas']);self.assertIsNone(package['learning_state']['cognitive_state']['confidence'])
        self.assertIsNone(package['learning_state']['cognitive_state']['knowledge_level'])
        self.store.save_lesson('owner',self.cid,self.section['id'],package['content'],scope,package['validation'],package)
        saved=self.store.course('owner',self.cid)['sections'][0]
        self.assertEqual(saved['lesson_blocks'],package['blocks']);self.assertEqual(saved['teaching_action'],decision)
        self.assertEqual(self.store.tutor_turns('owner',self.cid,self.section['id'])[0]['blocks'],package['blocks'])
        self.assertEqual(self.store.mastery('owner',self.cid)['sections'][0]['test_count'],0)

    def test_confusion_changes_presentation_without_mastery_or_formula(self):
        package,scope=self.generator.lesson('owner',self.course,self.section,self.model,self.store.mastery('owner',self.cid),[])
        self.store.save_lesson('owner',self.cid,self.section['id'],package['content'],scope,package['validation'],package)
        before=self.store.knowledge_state('owner',self.cid)
        state,_,_,decision=self.prepare('我不理解QKV',mode='assistant')
        self.assertEqual(decision['action'],'REPHRASE');self.assertEqual(decision['presentation'][0],'example')
        self.assertIn('diagram',decision['presentation']);self.assertFalse(decision['allow_formulas'])
        self.assertIn('confused',state['user_feedback']);self.assertEqual(self.store.knowledge_state('owner',self.cid),before)

    def test_high_math_allows_formula_but_confusion_and_lesson_scope_take_priority(self):
        self.store.save_teaching_preferences('owner',self.cid,{'math_level':'advanced'})
        state,knowledge,scope,decision=self.prepare('请深入解释Attention',mode='assistant')
        self.assertTrue(decision['allow_formulas']);self.assertIn('formula',decision['presentation'])
        blocks=validate_blocks({'blocks':make_blocks(decision)},decision);self.assertIn('y = 2x',flatten_blocks(blocks))
        confused=self.prepare('公式我看不懂',mode='assistant')[3]
        self.assertEqual(confused['action'],'SIMPLIFY');self.assertFalse(confused['allow_formulas'])
        introductory={**scope,'teaching_depth':'introductory'}
        bounded=ATIEEngine().decide(state,knowledge,introductory,'请推导Attention公式',mode='assistant')
        self.assertFalse(bounded['allow_formulas']);self.assertNotIn('formula',bounded['presentation'])
        future=ATIEEngine().decide(state,knowledge,scope,'请推导Encoder',mode='assistant')
        self.assertTrue(future['exploring_future']);self.assertFalse(future['allow_formulas'])

    def test_assessment_dimensions_and_next_section_strategy_from_actual_results(self):
        self.store.save_lesson('owner',self.cid,self.section['id'],'Attention基础讲解')
        quiz=self.store.create_quiz('owner',self.cid,self.section['id'],
            [{'prompt':'解释定义','assessment_type':'concept'},{'prompt':'应用情境','assessment_type':'application'}],
            [{'answer':'a','explanation':'概念依据'},{'answer':'b','explanation':'应用依据'}])
        self.store.submit_quiz('owner',self.cid,quiz['id'],['a','a'])
        self.store.advance('owner',self.cid,1);second=self.store.course('owner',self.cid)['sections'][1]
        state,_,_,decision=self.generator.prepare('owner',self.cid,second)
        self.assertEqual(state['assessment_dimensions']['concept']['rate'],1)
        self.assertEqual(state['assessment_dimensions']['application']['rate'],0)
        self.assertIn(decision['action'],['EXAMPLE','BACKTRACK'])
        self.assertIn('example',decision['presentation']);self.assertEqual(state['recent_assessment']['rate'],.5)
        self.assertEqual(self.store.course('owner',self.cid)['current_ordinal'],2)

    def test_untagged_old_questions_do_not_invent_dimension_scores(self):
        self.store.save_lesson('owner',self.cid,self.section['id'],'Attention基础讲解')
        quiz=self.store.create_quiz('owner',self.cid,self.section['id'],[{'prompt':'旧题'}],[{'answer':'a','explanation':'旧解释'}])
        self.store.submit_quiz('owner',self.cid,quiz['id'],['a'])
        state,_=LearningStateManager(self.store).read('owner',self.cid,1)
        self.assertEqual(state['assessment_dimensions']['unknown']['attempts'],1)
        self.assertIsNone(state['assessment_dimensions']['concept']['rate']);self.assertIsNone(state['assessment_dimensions']['math']['rate'])

    def test_actions_and_structure_levels(self):
        mapping={'rephrase':'REPHRASE','formula_confusing':'SIMPLIFY','visual':'VISUALIZE','example':'EXAMPLE','deepen':'DEEPEN',
                 'backtrack':'BACKTRACK','check':'CHECK','challenge':'CHALLENGE','review':'REVIEW'}
        for feedback,expected in mapping.items():
            self.assertEqual(self.prepare(mode='assistant',feedback=feedback)[3]['action'],expected)
        self.assertEqual(self.prepare(mode='assistant')[3]['action'],'EXPLAIN')
        self.assertEqual(self.prepare('什么是Attention？',mode='assistant')[3]['structure_level'],1)
        self.assertEqual(self.prepare('请用一句话解释Attention',mode='assistant')[3]['structure_level'],0)
        self.assertEqual(self.prepare('Attention和RNN有什么区别？',mode='assistant')[3]['presentation'][0],'comparison')
        state,knowledge,scope,_=self.prepare()
        operation=ATIEEngine().decide(state,{**knowledge,'type':'operation','name':'读文件步骤'},scope)
        self.assertIn('flow',operation['presentation'])

    def test_malformed_diagrams_missing_blocks_and_hidden_formulas_fail_closed(self):
        decision=self.prepare()[3];packet={'blocks':make_blocks(decision)}
        packet['blocks'][2]['data']['edges'][0]['to']='foreign'
        with self.assertRaises(ValueError):validate_blocks(packet,decision)
        with self.assertRaises(ValueError):validate_blocks({'blocks':[{'type':'text','content':'一整篇文章'}]},decision)
        with self.assertRaises(ValueError):validate_blocks({'blocks':make_blocks(decision,'Q = XWq')},decision)
        with self.assertRaises(ValueError):validate_blocks({'blocks':make_blocks(decision,'## 一整篇Markdown文章')},decision)
        class Broken(TeachingModel):
            def generate_teaching_blocks(_,p):return {'blocks':[]}
            def repair_teaching_blocks(_,p,*args):return {'blocks':[]}
        with self.assertRaises(ModelUnavailable):self.generator.lesson('owner',self.course,self.section,Broken(),{},[])
        self.assertIsNone(self.store.course('owner',self.cid)['sections'][0]['lesson'])
        with self.store.connect() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM teaching_actions').fetchone()[0],0)

    def test_settings_feedback_and_state_are_owned_isolated_and_do_not_copy(self):
        self.store.save_teaching_preferences('owner',self.cid,{'math_level':'advanced','preferred_style':['visual']})
        self.store.save_teaching_feedback('owner',self.cid,self.section['id'],'confused',request_id='same')
        self.store.save_teaching_feedback('owner',self.cid,self.section['id'],'confused',request_id='same')
        with self.store.connect() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM teaching_feedback').fetchone()[0],1)
        with self.assertRaises(ValueError):self.store.save_teaching_preferences('other',self.cid,{'math_level':'advanced'})
        with self.assertRaises(ValueError):self.store.save_teaching_preferences('owner',self.cid,{'knowledge_level':1})
        with self.assertRaises(ValueError):self.store.save_teaching_feedback('owner',self.cid,self.course['sections'][1]['id'],'confused')
        with self.assertRaises(ValueError):self.prepare(atom_id='a2')
        clone=self.store.copy_course('owner',self.cid)
        self.assertEqual(self.store.teaching_preferences('owner',clone['id'])['math_level'],'unknown')
        self.store.recycle_course('owner',self.cid)
        with self.assertRaises(ValueError):self.prepare()
        self.store.restore_course('owner',self.cid);self.assertEqual(self.store.teaching_preferences('owner',self.cid)['math_level'],'advanced')
        self.store.recycle_course('owner',self.cid);self.store.purge_course('owner',self.cid,self.course['title'])
        with self.store.connect() as db:self.assertEqual(list(db.execute('PRAGMA foreign_key_check')),[])

    def test_invalid_json_enters_one_repair_and_keeps_original_reply(self):
        # Same missing block-closing brace as the real algebra/graph course reply.
        malformed='{"blocks":[{"type":"flow","data":{"steps":[{"label":"集合"},{"label":"图论"}]},{"type":"concept","content":"预备知识"}]}'
        gateway=ModelGateway({'base_url':'http://localhost','chat_model':'test'})
        events=[];gateway._diagnostic=events.append
        _,_,scope,action=self.prepare()
        with patch.object(gateway,'_chat',return_value=malformed):
            with self.assertRaises(ModelStructuredOutputError) as caught:
                gateway.generate_teaching_blocks({})
        self.assertEqual(caught.exception.raw,malformed)
        self.assertIn('Expecting property name',caught.exception.reason)
        self.assertEqual(events[-1]['failure_type'],'JSONDecodeError')
        payload={'learning_state':{}}
        repaired={'blocks':make_blocks(action)}
        with patch.object(gateway,'_chat',side_effect=[malformed,json.dumps(repaired)] ) as chat:
            package=self.generator.execute(gateway,payload,action,scope,lambda:gateway.generate_teaching_blocks(payload))
        self.assertEqual(chat.call_count,2)
        repair_request=json.loads(chat.call_args_list[1].args[1])
        self.assertEqual(repair_request['original']['unparsed_model_output'],malformed)
        self.assertIn('JSON语法',repair_request['failure'])
        self.assertEqual(package['validation']['repair_attempts'],1)
        self.assertEqual(package['blocks'],validate_blocks(repaired,action))

    def test_parse_and_schema_errors_share_one_repair_budget_and_never_save_failure(self):
        for repaired_reply in ['not JSON','{"blocks":[]}']:
            gateway=ModelGateway({'base_url':'http://localhost','chat_model':'test'});gateway._diagnostic=lambda e:None
            with patch.object(gateway,'_chat',side_effect=['{"blocks":[',repaired_reply]) as chat:
                with self.assertRaisesRegex(ModelUnavailable,'已停止保存'):
                    self.generator.lesson('owner',self.course,self.section,gateway,{},[])
            self.assertEqual(chat.call_count,2)
        self.assertIsNone(self.store.course('owner',self.cid)['sections'][0]['lesson'])
        with self.store.connect() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM teaching_actions').fetchone()[0],0)

    def test_connection_and_truncation_errors_do_not_enter_json_repair(self):
        for message in ['API 密钥无效','模型输出被截断，请重试或换用支持更长输出的模型']:
            gateway=ModelGateway({'base_url':'http://localhost','chat_model':'test'});gateway._diagnostic=lambda e:None
            with patch.object(gateway,'_chat',side_effect=ModelUnavailable(message)) as chat:
                with self.assertRaisesRegex(ModelUnavailable,message):
                    self.generator.lesson('owner',self.course,self.section,gateway,{},[])
            self.assertEqual(chat.call_count,1)

class ATIEApiTests(unittest.TestCase):
    setUpClass=classmethod(prototype.PrototypeTests.setUpClass.__func__)
    tearDownClass=classmethod(prototype.PrototypeTests.tearDownClass.__func__)
    setUp=prototype.PrototypeTests.setUp;call=prototype.PrototypeTests.call;configure=prototype.PrototypeTests.configure
    session_id=prototype.PrototypeTests.session_id;draft_and_confirm=prototype.PrototypeTests.draft_and_confirm
    def test_lesson_api_recovers_parse_failure_before_saving(self):
        self.configure();cid=self.draft_and_confirm('JSON修订接口课程')
        def repair(model,payload,packet,reason):
            self.assertEqual(packet['unparsed_model_output'],'{"blocks":[')
            return {'blocks':make_blocks(payload['teaching_action'])}
        with patch.object(ModelGateway,'generate_teaching_blocks',side_effect=ModelStructuredOutputError('{"blocks":[','未闭合数组')),patch.object(ModelGateway,'repair_teaching_blocks',repair):
            status,data=self.call('/api/sections/lesson',{'course_id':cid,'ordinal':1})
        self.assertEqual(status,200,data)
        self.assertTrue(data['section']['lesson_blocks'])
        with self.server.storage.connect() as db:
            validation=json.loads(db.execute('SELECT validation_json FROM lesson_teaching_records WHERE course_id=?',(cid,)).fetchone()[0])
            self.assertEqual(validation['repair_attempts'],1)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM teaching_actions WHERE course_id=?',(cid,)).fetchone()[0],1)
    def test_preferences_cannot_write_scores_and_future_state_is_blocked(self):
        self.configure();cid=self.draft_and_confirm('ATIE偏好与隔离课程')
        def put(body,client=None):
            request=urllib.request.Request(self.url+f'/api/courses/{cid}/teaching-preferences',method='PUT',
                data=json.dumps(body).encode(),headers={'Content-Type':'application/json'})
            try:
                with (client or self.client).open(request) as response:return response.status,json.loads(response.read())
            except urllib.error.HTTPError as error:
                with error:return error.code,json.loads(error.read())
        self.assertEqual(put({'math_level':'advanced','preferred_style':['visual']})[0],200)
        state=self.call(f'/api/courses/{cid}/learning-state')[1]['learning_state']
        self.assertEqual(state['preferences']['source'],'user_reported');self.assertIsNone(state['cognitive_state']['knowledge_level'])
        self.assertEqual(put({'knowledge_level':1,'confidence':1})[0],400)
        self.assertEqual(put({'math_level':'advanced'},urllib.request.build_opener())[0],400)
        self.assertEqual(self.call(f'/api/courses/{cid}/learning-state?ordinal=2')[0],400)
    def test_lesson_and_assistant_share_actions_blocks_and_persistent_history(self):
        self.configure();cid=self.draft_and_confirm('ATIE接口课程')
        status,data=self.call('/api/sections/lesson',{'course_id':cid,'ordinal':1});self.assertEqual(status,200)
        self.assertTrue(data['section']['lesson_blocks']);self.assertIn('next_teaching_action',data)
        before=data['mastery']
        status,reply=self.call(f'/api/courses/{cid}/assistant/chat',{'message':'我不理解当前知识','request_id':'atie-question'})
        self.assertEqual(status,200,reply);self.assertEqual(reply['teaching_action']['action'],'REPHRASE');self.assertTrue(reply['blocks'])
        self.assertEqual(self.call(f'/api/courses/{cid}/assistant/history')[1]['messages'][-1]['blocks'],reply['blocks'])
        self.assertEqual(self.call(f'/api/courses/{cid}/assistant/chat',{'message':'我不理解当前知识','request_id':'atie-question'})[1]['blocks'],reply['blocks'])
        status,state=self.call(f'/api/courses/{cid}/learning-state');self.assertEqual(status,200)
        self.assertIn('confused',state['learning_state']['user_feedback'])
        self.assertEqual(self.call('/api/course?course_id='+cid)[1]['mastery'],before)
        with self.server.storage.connect() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM teaching_actions WHERE course_id=?',(cid,)).fetchone()[0],2)
