"""Gap-first planning, keyword normalization, fallback and local diagnostics."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from mindos.model import ModelGateway, ModelUnavailable
from mindos.search_planning import build_search_plan, course_context, normalize_queries, fallback_queries
from mindos.acquisition import DirectInputProvider
from mindos.web_search import PublicSourceSearch, WebSearch

class Planner:
    def __init__(self,path,requirements):self.diagnostic_path=path;self.requirements=requirements;self.calls=[]
    def plan_discovery(self,*args):self.calls.append('requirements');return {'requirements':self.requirements}
    def generate_search_tasks(self,course,gaps):
        self.calls.append(('tasks',[g['title'] for g in gaps]))
        return {'tasks':[{'requirement_index':i,'queries':[g['title'],g['title'].lower(),' !!! '],
            'priority':i+1,'preferred_sources':['公开教材']} for i,g in enumerate(gaps)]}

def requirement(title='图论',evidence=None,aspect='definition'):
    return {'title':title,'section':1,'aspect':aspect,'reason':'需要理解基础与解题方法','evidence':evidence or []}

class PlanningTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)/'diagnostic.jsonl'
        self.course=course_context('代数结构与图论','学会基础，能掌握解题技巧通过期末考试')
    def tearDown(self):self.temp.cleanup()
    def plan(self,model,documents=None,graph=None,batches=None):
        documents=documents or [];selections={d['id']:[b['id'] for b in d['metadata']['blocks']] for d in documents}
        return build_search_plan(model,self.course,documents,selections,graph or {'atoms':[]},batches or [])

    def test_normalization_short_unicode_duplicates_empty_and_long_keywords(self):
        values=[' AI ','ai','ＭＬ','RL','图论','','!!!','\u200b','线性\n代数','x'*300,1]
        self.assertEqual(normalize_queries(values),['AI','ML','RL','图论','线性 代数','x'*300])

    def test_requirement_gap_task_query_order_and_context_expansion(self):
        model=Planner(self.path,[requirement('图论'),requirement('AI')]);plan=self.plan(model)
        self.assertEqual(model.calls,['requirements',('tasks',['图论','AI'])])
        for task in plan['search_tasks']:
            self.assertTrue(all(key in task for key in ['knowledge_target','purpose','search_intent','queries','preferred_sources','priority']))
            self.assertIn(self.course['title'],task['queries'][0])
        self.assertEqual(len(plan['queries']),2)
        logs=[json.loads(line) for line in self.path.read_text().splitlines()]
        self.assertEqual([e['stage'] for e in logs],['requirement_planner','gap_analysis','search_task_generator','query_enhancement'])
        self.assertEqual(len({e['trace_id'] for e in logs}),1)

    def test_covered_requirement_never_generates_search_task(self):
        doc=DirectInputProvider().acquire(title='公开摘录',text='图论研究由顶点和边组成的图，以及它们之间的关系。').to_dict()
        doc['origin']='web_search';block=doc['metadata']['blocks'][0]
        ref={'document_id':doc['id'],'block_id':block['id'],'quote':block['text']}
        model=Planner(self.path,[requirement(evidence=[ref])]);plan=self.plan(model,[doc])
        self.assertEqual(model.calls,['requirements']);self.assertEqual(plan['search_tasks'],[])
        self.assertEqual(plan['queries'],[])

    def test_existing_cited_atom_suppresses_omitted_model_coverage(self):
        doc=DirectInputProvider().acquire(title='图论摘录',text='图论研究由顶点和边组成的图，以及它们之间的关系。').to_dict()
        doc['origin']='web_search';block=doc['metadata']['blocks'][0]
        ref={'document_id':doc['id'],'block_id':block['id'],'quote':block['text']}
        graph={'atoms':[{'title':'图论','source_reference':[ref],'quality_status':'verified'}]}
        plan=self.plan(Planner(self.path,[requirement()]),[doc],graph)
        self.assertEqual(plan['queries'],[])
        plan=self.plan(Planner(self.path,[requirement(aspect='example')]),[doc],graph)
        self.assertTrue(plan['queries']) # Definition is not an example.

    def test_task_failure_falls_back_to_requirements_with_reason(self):
        model=Planner(self.path,[requirement('RL')])
        with patch.object(model,'generate_search_tasks',side_effect=ModelUnavailable('模型超时')):
            plan=self.plan(model)
        self.assertEqual(plan['search_tasks'][0]['generation_origin'],'knowledge_requirement')
        self.assertIn('RL',plan['queries'][0]['query'])
        self.assertEqual(plan['diagnostics']['generation_failure'],'模型超时')

    def test_planner_failure_and_invalid_json_fall_back_without_fabricated_coverage(self):
        for failed in [ModelUnavailable('连接失败'),{'unexpected':[]}]:
            model=Planner(self.path,[])
            with patch.object(model,'plan_discovery',**({'side_effect':failed} if isinstance(failed,Exception) else {'return_value':failed})):
                plan=self.plan(model)
            self.assertEqual(plan['diagnostics']['requirement_origin'],'course_information')
            self.assertTrue(plan['queries']);self.assertFalse(plan['requirements'][0]['covered'])

    def test_three_fallback_levels_are_ordered(self):
        self.assertEqual(fallback_queries(requirement('AI'),self.course)[1],'knowledge_requirement')
        self.assertEqual(fallback_queries(requirement('!!!'),self.course)[1],'course_information')
        course=dict(self.course,goal='')
        self.assertEqual(fallback_queries(requirement('!!!'),course),([course['title']],'course_title'))

    def test_raw_invalid_output_truncation_and_auth_errors_saved_without_key(self):
        model=ModelGateway({'base_url':'https://example.org','chat_model':'fake','api_key':'private-key','diagnostic_path':str(self.path)})
        for body in [('not JSON','stop'),('{"requirements":[]}', 'length')]:
            with patch.object(model,'_post',return_value={'choices':[{'message':{'content':body[0]},'finish_reason':body[1]}]}):
                with self.assertRaises(ModelUnavailable):model.plan_discovery(self.course,[],{}, {'atoms':[]},[])
        with patch.object(model,'_post',side_effect=ModelUnavailable('API 密钥无效')):
            with self.assertRaises(ModelUnavailable):model.plan_discovery(self.course,[],{}, {'atoms':[]},[])
        text=self.path.read_text();self.assertNotIn('private-key',text)
        logs=[json.loads(line) for line in text.splitlines()]
        self.assertTrue(any(e.get('raw')=='not JSON' for e in logs))
        self.assertTrue(any(e.get('finish_reason')=='length' for e in logs))
        self.assertTrue(any(e.get('failure_reason')=='API 密钥无效' for e in logs))

    def test_real_adapter_parsed_output_and_trace_persisted_locally(self):
        model=ModelGateway({'base_url':'https://example.org','chat_model':'fake','diagnostic_path':str(self.path)})
        bodies=[{'requirements':[requirement('AI')]},{'tasks':[{'requirement_index':0,'queries':['AI']}]}]
        with patch.object(model,'_post',side_effect=[{'choices':[{'message':{'content':json.dumps(b)},'finish_reason':'stop'}]} for b in bodies]):
            plan=self.plan(model)
        self.assertTrue(plan['queries'])
        events=[json.loads(line) for line in self.path.read_text().splitlines()]
        self.assertEqual(len([e for e in events if 'raw' in e]),2)
        self.assertEqual({e['trace_id'] for e in events},{plan['diagnostics']['trace_id']})
        self.assertNotIn('raw',json.dumps(plan['diagnostics']))

    def test_provider_transports_accept_short_terms(self):
        from test_web_search import SearchTests
        opener=SearchTests().search_with({'results':[{'title':'图论','url':'https://example.org/graph','content':'定义摘要'}]})
        with patch('mindos.web_search.urllib.request.build_opener',return_value=opener):
            self.assertTrue(WebSearch('key','tavily').search(['图论']))
        with patch.object(PublicSourceSearch,'_source',return_value=([{'title':'AI','url':'https://example.org/ai','description':'人工智能入门摘要','provider':'Wikipedia'}],{'provider':'Wikipedia','queries':['AI'],'count':1,'status':'ok','issues':[]})):
            self.assertTrue(PublicSourceSearch().search(['AI']))
