"""Structural validation and evidence attribution safeguards."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from mindos.knowledge import validate_graph
from mindos.model import ModelGateway, ModelUnavailable
from mindos.storage import Storage


def graph():
    return {'atoms': [{'id':f'a{i}', 'title':f'概念 {i}', 'section':i, 'type':'concept',
                       'summary':'一句话定义', 'why':'这是学习基础', 'depth':2} for i in (1,2)],
            'edges':[{'from':'a1','to':'a2','type':'prerequisite'}]}


class KnowledgeTests(unittest.TestCase):
    def test_reject_cycles_unknown_ids_and_over_fragmentation(self):
        cases = []
        cycle=graph();cycle['edges'].append({'from':'a2','to':'a1','type':'prerequisite'});cases.append(cycle)
        unknown=graph();unknown['edges'][0]['to']='other-course';cases.append(unknown)
        missing=graph();missing['atoms'][1]['section']=1;cases.append(missing)
        invalid=graph();invalid['atoms'][0]['type']=[];cases.append(invalid)
        duplicate=graph();duplicate['atoms'][1]['title']=duplicate['atoms'][0]['title'];cases.append(duplicate)
        depth=graph();depth['atoms'][0]['depth']=True;cases.append(depth)
        for candidate in cases:
            with self.subTest(candidate=candidate), self.assertRaises(ValueError):
                validate_graph(candidate, 2)
        self.assertEqual(len(validate_graph(graph(),2)['edges']),1)

    def test_no_evidence_is_inferred_from_untagged_section_score(self):
        with tempfile.TemporaryDirectory() as directory:
            store=Storage(Path(directory)/'db.sqlite3')
            draft=store.save_draft('owner','课程','','', {'sections':[{'title':'第一节','objective':'基础学习'},
                                 {'title':'第二节','objective':'后续学习'}]},[])
            course=store.confirm_draft('owner',draft['id'],1)
            store.save_graph('owner',course['id'],graph())
            section=course['sections'][0]
            store.save_lesson('owner',course['id'],section['id'],'讲解内容')
            questions=[{'prompt':'这是一个测试问题', 'choices':{'a':'正确','b':'错误','c':'另一项','d':'其他'}}]
            quiz=store.create_quiz('owner',course['id'],section['id'],questions,[{'answer':'a','explanation':'解释'}])
            store.submit_quiz('owner',course['id'],quiz['id'],['a'])
            state=store.knowledge_state('owner',course['id'])
            self.assertIsNone(state['atoms'][0]['rate'])
            self.assertEqual(store.mastery('owner',course['id'])['overall_rate'],100)
            store.learning_event('owner',course['id'],['a1'],'read')
            self.assertEqual(store.knowledge_state('owner',course['id'])['read_count'],1)
            self.assertEqual(store.knowledge_state('owner',course['id'])['tested_count'],0)
            with self.assertRaises(ValueError): store.learning_event('owner',course['id'],['a2'],'read')
            self.assertEqual(store.course('owner',course['id'])['current_ordinal'],1)

    def test_generated_question_cannot_tag_foreign_atom_or_leak_answers(self):
        model=ModelGateway()
        raw={'questions':[{'prompt':f'第{i}个知识点的含义是什么？','choices':{'a':'一','b':'二','c':'三','d':'四'},
                           'answer':'b','explanation':'因为它满足定义','atom_ids':['foreign']} for i in range(4)]}
        with self.assertRaises(ModelUnavailable): model._validated_questions(raw,[],{'a1'},required=True)
        for q in raw['questions']: q['atom_ids']=['a1']
        questions, answers=model._validated_questions(raw,[],{'a1'},required=True)
        self.assertNotIn('answer',json.dumps(questions))
        self.assertEqual(answers[0]['answer'],'b')
