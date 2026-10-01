"""Table schema interoperability without relaxing lesson or evidence safeguards."""
import copy
import json
import unittest
from unittest.mock import patch
import test_prototype as prototype
from mindos.adaptive.content_generator import normalize_blocks,validate_blocks,ContentGenerator
from mindos.model import ModelGateway,ModelUnavailable
from block_fixture import make_blocks

ACTION={'presentation':['question','concept','example','checkpoint'],'structure_level':2,'allow_formulas':False}
SCOPE={'future_atoms':['QKV'],'related_atoms':[],'teaching_depth':'introductory'}

def table_packet():
    blocks=make_blocks(ACTION,'使用集合和运算理解基本性质。')
    blocks.insert(-1,{'type':'comparison','data':{'columns':['性质','核心问题','整数加法','整数减法'],
        'rows':[{'label':'交换律','values':['交换顺序是否改变结果','满足','不满足']},
                {'label':'结合律','values':['改变分组是否改变结果','满足','不满足']}]}})
    return {'blocks':blocks}

class TableTests(unittest.TestCase):
    def test_full_headers_are_converted_losslessly_and_input_is_not_changed(self):
        original=table_packet();before=copy.deepcopy(original);result,changes=normalize_blocks(original)
        self.assertEqual(original,before);data=validate_blocks(result,ACTION)[-2]['data']
        self.assertEqual(data['label_header'],'性质');self.assertEqual(data['columns'],['核心问题','整数加法','整数减法'])
        self.assertEqual(data['rows'],before['blocks'][-2]['data']['rows']);self.assertEqual(changes[0]['conversion'],'comparison_row_header')
        self.assertEqual(normalize_blocks(result),(result,[]))
    def test_canonical_headers_and_optional_label_header_remain_compatible(self):
        packet=table_packet();data=packet['blocks'][-2]['data'];data['columns']=data['columns'][1:]
        self.assertEqual(normalize_blocks(packet),(packet,[]));self.assertNotIn('label_header',validate_blocks(packet,ACTION)[-2]['data'])
        data['label_header']='性质';self.assertEqual(validate_blocks(packet,ACTION)[-2]['data']['label_header'],'性质')
    def test_missing_inconsistent_or_ambiguous_values_are_not_fabricated(self):
        for case in ('mixed_width','missing_values','ambiguous_header','missing_label'):
            packet=table_packet();data=packet['blocks'][-2]['data']
            if case=='mixed_width':data['rows'][0]['values'].pop()
            if case=='missing_values':data['rows'][0].pop('values')
            if case=='ambiguous_header':data['columns'][0]='整数乘法'
            if case=='missing_label':data['rows'][0].pop('label')
            result,changes=normalize_blocks(packet);self.assertEqual(changes,[])
            with self.assertRaises(ValueError):validate_blocks(result,ACTION)
    def test_conversion_does_not_bypass_formula_order_or_future_scope_checks(self):
        generator=ContentGenerator(None)
        for case in ('formula','order','scope'):
            packet=table_packet()
            if case=='formula':packet['blocks'][1]['content']='Q = XWq'
            if case=='order':packet['blocks'].pop(0)
            if case=='scope':packet['blocks'][1]['content']='QKV计算：Q = XWq'
            normalized,_=normalize_blocks(packet)
            with self.assertRaises(ValueError):generator.validate(normalized,ACTION,SCOPE)
        packet=table_packet();packet['blocks'][1]['content']='QKV逐项相乘求和，第1步计算查询。'
        with self.assertRaisesRegex(ValueError,'QKV'):generator.validate(normalize_blocks(packet)[0],ACTION,SCOPE)
    def test_execute_normalizes_before_model_repair_and_records_conversion(self):
        model=ModelGateway({'base_url':'http://localhost','chat_model':'test'});events=[];model._diagnostic=events.append
        with patch.object(model,'repair_teaching_blocks',side_effect=AssertionError('不应调用模型修订')):
            package=ContentGenerator(None).execute(model,{'learning_state':{}},ACTION,SCOPE,table_packet)
        self.assertEqual(package['validation']['repair_attempts'],0);self.assertEqual(len(package['validation']['normalizations']),1)
        self.assertEqual(events[0]['stage'],'atie_normalization')
    def test_failed_repair_reports_actual_column_error_and_retains_budget(self):
        packet=table_packet();packet['blocks'][-2]['data']['rows'][0]['values'].pop()
        model=ModelGateway({'base_url':'http://localhost','chat_model':'test'});model._diagnostic=lambda e:None
        with patch.object(model,'repair_teaching_blocks',return_value=packet) as repair:
            with self.assertRaisesRegex(ModelUnavailable,'第1行有2个值，但columns有4列'):
                ContentGenerator(None).execute(model,{'learning_state':{}},ACTION,SCOPE,lambda:packet)
        self.assertEqual(repair.call_count,1)

class TableAPITests(unittest.TestCase):
    setUpClass=classmethod(prototype.PrototypeTests.setUpClass.__func__)
    tearDownClass=classmethod(prototype.PrototypeTests.tearDownClass.__func__)
    setUp=prototype.PrototypeTests.setUp;call=prototype.PrototypeTests.call;configure=prototype.PrototypeTests.configure
    session_id=prototype.PrototypeTests.session_id;draft_and_confirm=prototype.PrototypeTests.draft_and_confirm
    def test_lesson_saves_normalized_table_once_without_mastery_or_advance(self):
        self.configure();cid=self.draft_and_confirm('比较表课程')
        def generate(model,payload):
            packet=table_packet();packet['blocks']=make_blocks(payload['teaching_action'])[:-1]+[packet['blocks'][-2]]+make_blocks(payload['teaching_action'])[-1:]
            return packet
        with patch.object(ModelGateway,'generate_teaching_blocks',generate),patch.object(ModelGateway,'repair_teaching_blocks',side_effect=AssertionError('无损表格无需模型修订')):
            status,data=self.call('/api/sections/lesson',{'course_id':cid,'ordinal':1})
        self.assertEqual(status,200,data);self.assertEqual(data['section']['lesson_blocks'][-2]['data']['label_header'],'性质')
        self.assertIsNone(data['mastery']['overall_rate']);self.assertEqual(data['course']['current_ordinal'],1)
        with self.server.storage.connect() as db:
            row=db.execute('SELECT validation_json FROM lesson_teaching_records WHERE course_id=?',(cid,)).fetchone()
            self.assertEqual(json.loads(row[0])['normalizations'][0]['conversion'],'comparison_row_header')
            self.assertEqual(db.execute('SELECT COUNT(*) FROM teaching_actions WHERE course_id=?',(cid,)).fetchone()[0],1)
