"""Course policy, bounded automatic discovery, evidence and conflict review."""
import copy
import tempfile
import time
import unittest
from pathlib import Path
from mindos.acquisition import DirectInputProvider, UploadProvider, document, text_blocks
from mindos.discovery import DiscoveryEngine, normalize_plan, produce_source, selected_blocks
from mindos.storage import Storage

USER_TEXT='# Attention\n\nAttention combines input values using attention weights from QKV and Softmax.\n\n## QKV\n\nQKV stands for Query, Key and Value, three representations used in attention.\n\n## Softmax\n\nSoftmax outputs non-negative weights whose sum is one in standard attention.'
PUBLIC_TEXT='# Matrix multiplication\n\nMatrix multiplication combines rows and columns through weighted summation.\n\nSoftmax output may contain negative probabilities whose sum is two.'

def create(store,policy='balanced',upload=False):
    plan={'sections':[{'title':'Attention','objective':'理解机制'},{'title':'QKV','objective':'理解表示'},{'title':'Softmax','objective':'理解归一化'}]}
    docs=[UploadProvider().acquire(filename='课程.md',data=USER_TEXT.encode()).to_dict()] if upload else []
    draft=store.save_draft('owner','注意力课程','从零理解原理','',plan,[],source_policy=policy,learner_level='了解一些基础',documents=docs)
    return store.confirm_draft('owner',draft['id'],1)

class Provider:
    def __init__(self):self.queries=[];self.fetched=[]
    def search(self,query):self.queries.append(query);return [{'title':'矩阵乘法公开说明','url':'https://example.org/matrix'}]
    def acquire(self,**kwargs):
        self.fetched.append(kwargs['url'])
        return document(kwargs['title'],'web','web_search',text_blocks(PUBLIC_TEXT),url=kwargs['url'])

class Model:
    def __init__(self,conflicts=False):self.calls=[];self.want_conflicts=conflicts
    def plan_discovery(self,course,docs,selections,graph,batches):
        self.calls.append(('plan',course['source_policy'],copy.deepcopy(graph),len(batches)))
        requirements=[]
        for doc in docs:
            if doc['origin']=='user_upload':
                for title in ['Attention','QKV','Softmax']:
                    block=next(b for b in doc['metadata']['blocks'] if title in b['text'] and len(b['text'])>=20)
                    requirements.append({'title':title,'section':1,'aspect':'definition','reason':'用户资料已有定义',
                        'evidence':[{'document_id':doc['id'],'block_id':block['id'],'quote':block['text']}],
                        'query':title+' definition'})
        requirements.append({'title':'矩阵乘法前置','section':1,'aspect':'prerequisite','reason':'缺少矩阵乘法的直观前置说明','evidence':[],'query':'矩阵乘法 行列 直观说明'})
        return {'requirements':requirements}
    def produce_knowledge(self,course,source,section,blocks,existing):
        self.calls.append(('produce',source['origin'],course['source_policy']))
        block=next(b for b in blocks if len(b['text'])>=20)
        return {'understanding':'资料按章节组织并解释基础定义，本次保留完整结构与真实引用。','candidates':[{
            'id':'c1','title':'Softmax' if self.want_conflicts else '基础概念 '+str(section) if source['origin']=='user_upload' else '矩阵乘法',
            'type':'concept','summary':'课程基础知识的简明定义','why':'支持后续理解与应用','depth':2,
            'evidence':[{'block_id':block['id'],'quote':block['text']}]}],'relations':[]}
    def find_source_conflicts(self,course,docs,selections):
        if not self.want_conflicts:return {'conflicts':[]}
        uploaded=next((d for d in docs if d['origin']=='user_upload'),None)
        public=next((d for d in docs if d['origin']=='web_search'),None)
        if not uploaded or not public:return {'conflicts':[]}
        def evidence(d):
            b=next(b for b in d['metadata']['blocks'] if 'Softmax output' in b['text']);return {'document_id':d['id'],'block_id':b['id'],'quote':b['text']}
        return {'conflicts':[{'topic':'Softmax','description':'两个来源对权重符号和总和给出了明显不同的事实表述，需要核对。',
            'source_a':evidence(uploaded),'source_b':evidence(public)}]}

class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.store=Storage(Path(self.temp.name)/'db.sqlite3')
    def tearDown(self):self.temp.cleanup()
    def wait(self,engine):
        for thread in engine.threads:thread.join(timeout=8);self.assertFalse(thread.is_alive())

    def test_default_without_upload_auto_discovers_body_but_does_not_import(self):
        course=create(self.store);provider=Provider();engine=DiscoveryEngine(self.store)
        engine.start('owner',course['id'],Model(),provider);self.wait(engine)
        run=self.store.discovery('owner',course['id'])
        self.assertEqual(run['status'],'complete',run)
        self.assertEqual(provider.queries,['矩阵乘法 行列 直观说明'])
        self.assertEqual(len(self.store.sources('owner',course['id'])),1)
        self.assertEqual(len(self.store.batches('owner',course['id'])),1)
        self.assertIsNone(self.store.graph('owner',course['id']))
        batch=self.store.batches('owner',course['id'])[0]
        self.store.review_batch('owner',course['id'],batch['id'],'verify',['c1'],'核对原文')
        graph=self.store.graph('owner',course['id'])
        self.assertEqual(len(graph['atoms']),1)
        self.assertIsNone(self.store.knowledge_state('owner',course['id'])['atoms'][0]['rate'])
        self.assertEqual(self.store.course('owner',course['id'])['current_ordinal'],1)
        with self.assertRaises(ValueError):self.store.discovery('stranger',course['id'])

    def test_material_first_processes_user_structure_before_only_missing_queries(self):
        course=create(self.store,'user_material_first',True);model=Model();provider=Provider();engine=DiscoveryEngine(self.store)
        engine.start('owner',course['id'],model,provider);self.wait(engine)
        run=self.store.discovery('owner',course['id']);self.assertEqual(run['status'],'complete',run)
        self.assertEqual(provider.queries,['矩阵乘法 行列 直观说明'])
        self.assertEqual(model.calls[0][:2],('produce','user_upload'))
        self.assertTrue(any(call[0]=='plan' and call[3]>=1 for call in model.calls))
        self.assertTrue(all(not r['query'] for r in run['report']['plan']['requirements'][:3]))
        self.assertEqual([s['title'] for s in self.store.course('owner',course['id'])['sections']],['Attention','QKV','Softmax'])
        self.assertEqual({b['section'] for b in self.store.batches('owner',course['id']) if self.store.source('owner',course['id'],b['source_id'])['origin']=='user_upload'},{1,2,3})
        self.assertIsNone(self.store.graph('owner',course['id']))

    def test_coverage_cannot_be_forged_or_search_the_entire_course(self):
        course=create(self.store,'balanced',True);docs=[self.store.source('owner',course['id'],s['id']) for s in self.store.sources('owner',course['id'])]
        selections={d['id']:[b['id'] for b in selected_blocks(d)] for d in docs}
        raw=Model().plan_discovery(course,docs,selections,{},[])
        raw['requirements'][0]['evidence'][0]['quote']='This is an invented quotation with no source.'
        with self.assertRaises(ValueError):normalize_plan(raw,course,docs,selections)
        raw=Model().plan_discovery(course,[],{}, {},[]);raw['requirements'][0]['query']=course['title']
        with self.assertRaises(ValueError):normalize_plan(raw,course,[],{})

    def test_new_conflict_blocks_an_earlier_batch_until_user_confirms_expression(self):
        course=create(self.store,'user_material_first',True);cid=course['id'];user=self.store.source('owner',cid,self.store.sources('owner',cid)[0]['id'])
        early=produce_source(self.store,'owner',course,Model(True),user,1,selected_blocks(user))
        web=self.store.save_source('owner',cid,Provider().acquire(url='https://example.org/matrix',title='公开资料'))
        later=produce_source(self.store,'owner',course,Model(True),web,1,selected_blocks(web))
        conflicts=self.store.conflicts('owner',cid);self.assertEqual(len(conflicts),1)
        conflict=conflicts[0];self.assertFalse(conflict['confirmed'])
        self.assertEqual(conflict['content']['source_a']['origin'],'user_upload')
        self.assertEqual(conflict['content']['source_b']['origin'],'web_search')
        for batch in [early,later]:
            with self.assertRaises(ValueError):self.store.review_batch('owner',cid,batch['id'],'verify',['c1'],'')
        self.assertIsNone(self.store.graph('owner',cid))
        self.store.confirm_conflict('owner',cid,conflict['id'],'本课程采用非负且总和为一的定义；保留外部资料错误表述供核对。')
        self.store.review_batch('owner',cid,early['id'],'verify',['c1'],'已确认教学表达')
        self.assertEqual(self.store.conflicts('owner',cid)[0]['confirmed'],True)
        self.assertEqual(self.store.graph('owner',cid)['atoms'][0]['quality_status'],'verified')
        self.assertIsNone(self.store.knowledge_state('owner',cid)['atoms'][0]['rate'])
        with self.assertRaises(ValueError):self.store.confirm_conflict('stranger',cid,conflict['id'],'不能跨用户确认')

    def test_conflict_with_fabricated_quote_or_location_is_rejected(self):
        course=create(self.store,'balanced',True);cid=course['id'];docs=[self.store.source('owner',cid,s['id']) for s in self.store.sources('owner',cid)]
        docs.append(self.store.save_source('owner',cid,Provider().acquire(url='https://example.org/matrix',title='公开资料')))
        selections={d['id']:[b['id'] for b in selected_blocks(d)] for d in docs}
        raw=Model(True).find_source_conflicts(course,docs,selections);raw['conflicts'][0]['source_b']['block_id']='forged'
        with self.assertRaises(ValueError):self.store.save_conflicts('owner',cid,raw,docs,selections)
        self.assertEqual(self.store.conflicts('owner',cid),[])

    def test_repeat_discovery_does_not_repeat_successful_gap_search(self):
        course=create(self.store);cid=course['id'];engine=DiscoveryEngine(self.store);provider=Provider()
        engine.start('owner',cid,Model(),provider);self.wait(engine)
        engine.start('owner',cid,Model(),provider);self.wait(engine)
        self.assertEqual(len(provider.queries),1)
        self.assertEqual(len(self.store.sources('owner',cid)),1)
        self.assertEqual(self.store.discovery('owner',cid)['report']['acquisitions'][0]['status'],'already_done')

    def test_partial_failure_retains_course_and_user_candidates(self):
        class BrokenProvider:
            def search(self,q):raise ValueError('模拟搜索服务不可用')
        course=create(self.store,'balanced',True);engine=DiscoveryEngine(self.store)
        engine.start('owner',course['id'],Model(),BrokenProvider());self.wait(engine)
        run=self.store.discovery('owner',course['id']);self.assertEqual(run['status'],'partial')
        self.assertTrue(run['report']['errors']);self.assertTrue(self.store.batches('owner',course['id']))
        self.assertIsNone(self.store.graph('owner',course['id']))

    def test_old_course_migration_defaults_and_single_active_run(self):
        course=create(self.store);cid=course['id'];self.assertEqual(course['source_policy'],'balanced')
        identifier=self.store.begin_discovery('owner',cid);self.assertIsNotNone(identifier)
        self.assertIsNone(self.store.begin_discovery('owner',cid))
        with self.assertRaises(ValueError):self.store.policy('owner',cid,'user_material_first')
        reopened=Storage(self.store.path);self.assertEqual(reopened.discovery('owner',cid)['status'],'running')
        self.assertEqual(reopened.recover_discovery(),0)
        with reopened.connect() as db:db.execute('UPDATE discovery_runs SET heartbeat_at=0 WHERE id=?',(identifier,))
        self.assertEqual(reopened.recover_discovery(),1)
        self.assertEqual(reopened.discovery('owner',cid)['status'],'interrupted')
        reopened.policy('owner',cid,'user_material_first')
        self.assertEqual(reopened.course('owner',cid)['source_policy'],'user_material_first')

    def test_retry_failed_production_uses_saved_body_without_refetch(self):
        class FailOnce(Model):
            fail=True
            def produce_knowledge(self,*args):
                if self.fail:self.fail=False;raise ValueError('模拟模型超时')
                return super().produce_knowledge(*args)
        course=create(self.store);cid=course['id'];model=FailOnce();provider=Provider();engine=DiscoveryEngine(self.store)
        engine.start('owner',cid,model,provider);self.wait(engine)
        self.assertEqual(self.store.discovery('owner',cid)['status'],'partial')
        source_id=self.store.sources('owner',cid)[0]['id']
        self.assertEqual(self.store.batches('owner',cid),[])
        engine.start('owner',cid,model,provider);self.wait(engine)
        self.assertEqual(len(provider.queries),1)
        self.assertEqual(provider.fetched,['https://example.org/matrix'])
        self.assertEqual(self.store.sources('owner',cid)[0]['id'],source_id)
        self.assertEqual(len(self.store.batches('owner',cid)),1)
        self.assertIsNone(self.store.graph('owner',cid))

    def test_bounded_next_run_advances_to_remaining_gaps(self):
        class MultiModel(Model):
            def plan_discovery(self,*args):return {'requirements':[{'title':f'缺口 {i}','section':1,'aspect':'example','reason':'需要公开实例','evidence':[],'query':f'缺口 {i} 官方实例'} for i in range(4)]}
        class MultiProvider(Provider):
            def search(self,query):self.queries.append(query);return [{'title':'公开例子','url':'https://example.org/example-'+str(query.split()[1])}]
        course=create(self.store);cid=course['id'];provider=MultiProvider();engine=DiscoveryEngine(self.store)
        engine.start('owner',cid,MultiModel(),provider);self.wait(engine)
        self.assertEqual(len(provider.queries),3)
        self.assertEqual(len(self.store.discovery('owner',cid)['report']['plan']['remaining_queries']),1)
        engine.start('owner',cid,MultiModel(),provider);self.wait(engine)
        self.assertEqual(len(provider.queries),4)
        self.assertEqual(len(set(provider.queries)),4)
        self.assertEqual(len(self.store.sources('owner',cid)),4)

    def test_only_user_materials_leave_explicit_external_verification_gap(self):
        course=create(self.store,'user_material_first',True)
        docs=[self.store.source('owner',course['id'],s['id']) for s in self.store.sources('owner',course['id'])]
        selections={d['id']:[b['id'] for b in selected_blocks(d)] for d in docs}
        raw=Model().plan_discovery(course,docs,selections,{},[]);raw['requirements']=raw['requirements'][:3]
        plan=normalize_plan(raw,course,docs,selections)
        self.assertEqual(len(plan['queries']),1)
        self.assertEqual(plan['queries'][0]['aspect'],'verification')
        self.assertIn('核对',plan['queries'][0]['query'])
        self.assertTrue(all(not r['query'] for r in plan['requirements'][:3]))

    def test_actual_old_course_rows_migrate_without_data_loss(self):
        import sqlite3
        path=Path(self.temp.name)/'old.sqlite3'
        with sqlite3.connect(path) as db:
            db.execute('CREATE TABLE courses(id TEXT PRIMARY KEY,session_id TEXT NOT NULL,title TEXT NOT NULL,goal TEXT NOT NULL,current_ordinal INTEGER NOT NULL,created_at TEXT NOT NULL)')
            db.execute("INSERT INTO courses VALUES('old','owner','旧课程','原目标',1,'2026-01-01')")
        store=Storage(path);course=store.course('owner','old')
        self.assertEqual(course['goal'],'原目标')
        self.assertEqual(course['source_policy'],'balanced')
        self.assertEqual(course['learner_level'],'零基础')

    def test_material_first_later_section_uses_its_text_not_file_prefix(self):
        from mindos.discovery import teaching_blocks
        source=UploadProvider().acquire(filename='后续章节.md',data=('# Attention\n\n'+('Earlier chapter text. '*400)+'\n\n## QKV\n\nQuery, Key and Value are the actual contents for this later section.').encode()).to_dict()
        selected=teaching_blocks(source,'QKV')
        self.assertTrue(any('actual contents' in b['text'] for b in selected))
        self.assertFalse(any('Earlier chapter' in b['text'] for b in selected))
        self.assertEqual(selected[0]['section_path'],['Attention','QKV'])
