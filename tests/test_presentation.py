"""Content-based representation selection stays inside ATIE teaching constraints."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import test_prototype as prototype
from mindos.storage import Storage
from mindos.adaptive.content_generator import ContentGenerator
from mindos.adaptive.presentation_controller import resolve_presentation
from mindos.model import ModelGateway,ModelUnavailable
from block_fixture import make_blocks

class PresentationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.store=Storage(Path(self.temp.name)/'db.sqlite3')
        draft=self.store.save_draft('owner','集合与关系','从零理解集合、关系与有序对','',{'sections':[
            {'title':'集合与关系','objective':'理解有序对的关系','core_atoms':['集合','关系']},
            {'title':'矩阵表示','objective':'后续再学矩阵计算','core_atoms':['矩阵']} ]},[])
        self.course=self.store.confirm_draft('owner',draft['id'],1);self.section=self.course['sections'][0];self.generator=ContentGenerator(self.store)
    def tearDown(self):self.temp.cleanup()
    def action(self,message='',mode='lesson',feedback=None):return self.generator.prepare('owner',self.course['id'],self.section,message,mode=mode,feedback=feedback)[3]
    def packet(self,action,intent='relationship',forms=None):
        forms=forms or ['question','diagram','concept','example','checkpoint']
        return {'presentation_plan':{'intent':intent,'reason':'用元素连线直观看出关系，不需要用户手动选图示','forms':forms},'blocks':make_blocks({**action,'presentation':forms},'集合里的元素可以组成有序对。')}
    def test_concept_topic_can_choose_diagram_without_visual_feedback(self):
        action=self.action();self.assertNotIn('diagram',action['presentation']);before=copy.deepcopy(action)
        model=ModelGateway({'base_url':'http://localhost','chat_model':'test'});model._diagnostic=lambda e:None
        _,_,scope,_=self.generator.prepare('owner',self.course['id'],self.section)
        packet=self.packet(action)
        with patch.object(model,'_chat',return_value=json.dumps(packet,ensure_ascii=False)) as chat:
            package,_=self.generator.lesson('owner',self.course,self.section,model,{},[])
        self.assertEqual(chat.call_count,1);self.assertEqual(action,before)
        selected=package['teaching_action'];self.assertEqual(selected['presentation_source'],'model_content_plan');self.assertIn('diagram',selected['presentation'])
        self.assertEqual(selected['action'],'INTRODUCE');self.assertFalse(selected['allow_formulas']);self.assertEqual(selected['forbidden_topics'],action['forbidden_topics'])
        self.store.save_lesson('owner',self.course['id'],self.section['id'],package['content'],scope,package['validation'],package)
        saved=self.store.course('owner',self.course['id'])
        self.assertEqual(saved['sections'][0]['teaching_action']['presentation_source'],'model_content_plan');self.assertEqual(saved['current_ordinal'],1)
        self.assertIsNone(self.store.mastery('owner',self.course['id'])['overall_rate'])
    def test_model_can_select_process_or_comparison_without_changing_action(self):
        action=self.action('为什么这些元素之间可以建立关系',mode='assistant')
        self.assertEqual(action['structure_level'],1)
        for intent,kind in [('process','flow'),('comparison','comparison')]:
            selected=resolve_presentation(self.packet(action,intent,['question','concept',kind,'example','checkpoint']),action)
            self.assertIn(kind,selected['presentation']);self.assertEqual(selected['action'],action['action'])
    def test_referenced_explanation_does_not_request_future_topics(self):
        model=ModelGateway({'base_url':'http://localhost','chat_model':'test'});model._diagnostic=lambda e:None
        reference='矩阵将在后续小节讲，当前先理解集合和关系。'
        def generate(payload):
            self.assertEqual(payload['reference_explanation'],reference)
            self.assertFalse(payload['teaching_action']['exploring_future'])
            return {'blocks':make_blocks(payload['teaching_action'])}
        with patch.object(model,'generate_teaching_blocks',side_effect=generate):
            self.generator.followup('owner',self.course,self.section,model,[],'请看个例子','example',reference)
    def test_one_sentence_request_does_not_become_an_unnecessary_diagram(self):
        action=self.action('请用一句话解释集合',mode='assistant');packet=self.packet(action,'definition',['text'])
        selected=resolve_presentation(packet,action);self.assertEqual(selected['structure_level'],0)
        with self.assertRaises(ValueError):resolve_presentation(self.packet(action),action)
    def test_model_cannot_drop_explicit_visual_example_or_confusion_requirements(self):
        for feedback in ['visual','example','formula_confusing']:
            action=self.action(mode='assistant',feedback=feedback)
            with self.assertRaises(ValueError):resolve_presentation(self.packet(action,'definition',['concept','checkpoint']),action)
    def test_fake_plan_inconsistent_blocks_and_hidden_future_details_still_fail(self):
        action=self.action();base=self.packet(action)
        for mutate in [lambda p:p['presentation_plan'].update(forms=['text']),lambda p:p['presentation_plan'].update(intent='executable'),
                       lambda p:p['presentation_plan'].update(forms=['question','formula','concept','example','checkpoint']),
                       lambda p:p['presentation_plan'].update(reason='')]:
            p=copy.deepcopy(base);mutate(p)
            with self.assertRaises(ValueError):resolve_presentation(p,action)
        _,_,scope,_=self.generator.prepare('owner',self.course['id'],self.section)
        packet=self.packet(action);packet['blocks'][2]['content']='矩阵逐项相乘，第1步计算，第二步求和。'
        with self.assertRaises(ValueError):self.generator.validate(packet,resolve_presentation(packet,action),scope)
        packet=self.packet(action);packet['blocks'][2]['content']='Q = XWq'
        with self.assertRaises(ValueError):self.generator.validate(packet,resolve_presentation(packet,action),scope)
    def test_legacy_packets_keep_the_fallback_and_invalid_plans_share_repair_budget(self):
        action=self.action();packet={'blocks':make_blocks(action)}
        self.assertEqual(resolve_presentation(packet,action)['presentation_source'],'rule_fallback')
        model=ModelGateway({'base_url':'http://localhost','chat_model':'test'});model._diagnostic=lambda e:None
        broken=self.packet(action);broken['presentation_plan']['intent']='relationship';broken['blocks'][1]['data']['edges'][0]['to']='missing'
        with patch.object(model,'generate_teaching_blocks',return_value=broken),patch.object(model,'repair_teaching_blocks',return_value=broken) as repair:
            with self.assertRaises(ModelUnavailable):self.generator.lesson('owner',self.course,self.section,model,{},[])
        self.assertEqual(repair.call_count,1);self.assertIsNone(self.store.course('owner',self.course['id'])['sections'][0]['lesson'])

class PresentationAPITests(unittest.TestCase):
    setUpClass=classmethod(prototype.PrototypeTests.setUpClass.__func__);tearDownClass=classmethod(prototype.PrototypeTests.tearDownClass.__func__)
    setUp=prototype.PrototypeTests.setUp;call=prototype.PrototypeTests.call;configure=prototype.PrototypeTests.configure
    session_id=prototype.PrototypeTests.session_id;draft_and_confirm=prototype.PrototypeTests.draft_and_confirm
    def test_assistant_content_plan_is_saved_and_does_not_change_learning_progress(self):
        self.configure();cid=self.draft_and_confirm('展示策略助教课程');self.call('/api/sections/lesson',{'course_id':cid,'ordinal':1})
        def answer(model,context,*args):
            action=context['teaching_action'];forms=['question','diagram','concept','example','checkpoint']
            return {'presentation_plan':{'intent':'relationship','reason':'根据当前疑问用案例与结构图说明','forms':forms},'blocks':make_blocks({**action,'presentation':forms}),'related_atom_ids':[]}
        with patch.object(ModelGateway,'answer_course_tutor',answer):status,data=self.call(f'/api/courses/{cid}/assistant/chat',{'message':'为什么这些对象之间可以建立关系','request_id':'model-select'})
        self.assertEqual(status,200,data);self.assertEqual(data['teaching_action']['presentation_source'],'model_content_plan')
        history=self.call(f'/api/courses/{cid}/assistant/history')[1];self.assertEqual(history['messages'][-1]['teaching_action'],data['teaching_action'])
        course=self.call('/api/course?course_id='+cid)[1];self.assertEqual(course['course']['current_ordinal'],1);self.assertIsNone(course['mastery']['overall_rate'])

    def test_reference_turn_is_resolved_only_inside_owned_section(self):
        self.configure();cid=self.draft_and_confirm('引用讲解课程');self.call('/api/sections/lesson',{'course_id':cid,'ordinal':1})
        captured=[]
        def generate(model,payload):
            captured.append(payload)
            return {'blocks':make_blocks(payload['teaching_action'])}
        with patch.object(ModelGateway,'generate_teaching_blocks',generate):
            status,data=self.call('/api/sections/ask',{'course_id':cid,'ordinal':1,'question':'请看个例子','feedback':'example','reference_turn':0})
            self.assertEqual(status,200,data)
            for invalid in [True,-1,1,999,'0']:
                status,data=self.call('/api/sections/ask',{'course_id':cid,'ordinal':1,'question':'请看个例子','reference_turn':invalid})
                self.assertEqual(status,400,data)
        self.assertEqual(len(captured),1);self.assertTrue(captured[0]['reference_explanation']);self.assertEqual(captured[0]['question'],'请看个例子')
