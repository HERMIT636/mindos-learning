"""Migration, recycle bin, ownership, ordering and copy isolation."""
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from mindos.storage import Storage
from mindos.acquisition import DirectInputProvider

class ManagementTests(unittest.TestCase):
    def setUp(self):self.temp=tempfile.TemporaryDirectory();self.store=Storage(Path(self.temp.name)/'db.sqlite3')
    def tearDown(self):self.temp.cleanup()
    def create(self,title='图论课程',owner='owner',info=None):
        draft=self.store.save_draft(owner,title,'理解定义与解题方法','',{'sections':[{'title':'图论','objective':'理解基础'},{'title':'代数','objective':'建立关系'}]},[],course_info=info)
        return self.store.confirm_draft(owner,draft['id'],1)
    def populate(self,course):
        cid=course['id'];section=course['sections'][0]
        self.store.save_lesson('owner',cid,section['id'],'真实保留的课程讲解')
        source=self.store.save_source('owner',cid,DirectInputProvider().acquire(title='图论原文',text='图论研究由顶点和边组成的图，并讨论图中存在的关系。'))
        block=source['metadata']['blocks'][0]
        graph={'atoms':[{'id':'a1','title':'图论','section':1,'type':'concept','summary':'图论定义','why':'解释基本结构','depth':2,'quality_status':'verified','source_reference':[{'document_id':source['id'],'block_id':block['id'],'quote':block['text']}]},
                        {'id':'a2','title':'代数','section':2,'type':'concept','summary':'代数定义','why':'建立概念关系','depth':2}],
               'edges':[{'from':'a1','to':'a2','type':'prerequisite'}]}
        self.store.save_graph('owner',cid,graph)
        from mindos.production import normalize_candidate_result
        raw={'understanding':'该资料给出了图论的基础定义，保留实际原文引用。','candidates':[{'id':'c1','title':'图论关系','type':'concept','summary':'顶点与边的关系','why':'理解图论基础','depth':2,'evidence':[{'block_id':block['id'],'quote':block['text']}]}],'relations':[]}
        result=normalize_candidate_result(raw,source,1,[block],{'a1','a2'})
        self.store.save_batch('owner',cid,source['id'],1,result)
        self.store.learning_event('owner',cid,['a1'],'read')
        quiz=self.store.create_quiz('owner',cid,section['id'],[{'prompt':'测试'}],[{'answer':'a','explanation':'正确'}])
        self.store.submit_quiz('owner',cid,quiz['id'],['a']);return source
    def counts(self,cid):
        tables=['sections','tutor_turns','quizzes','course_graphs','learning_events','source_documents','source_conflicts','production_batches']
        with self.store.connect() as db:return {t:db.execute(f'SELECT COUNT(*) FROM {t} WHERE course_id=?',(cid,)).fetchone()[0] for t in tables}

    def test_metadata_progress_and_no_automatic_completion(self):
        course=self.create(info={'description':'通俗讲解','level':'基础','tags':['数学'],'cover':'https://example.org/cover.png'})
        self.populate(course);card=self.store.managed_course('owner',course['id'])
        self.assertEqual(card['progress'],50);self.assertEqual(card['status'],'active');self.assertEqual(card['knowledge_count'],2)
        self.assertTrue(card['last_study_at']);self.assertEqual(card['level'],'基础');self.assertEqual(card['tags'],['数学'])
        self.store.update_course('owner',course['id'],{'name':'代数与图论','goal':'新的目标','status':'paused','level':'高级'})
        self.assertEqual(self.store.managed_course('owner',course['id'])['name'],'代数与图论')
        self.assertEqual(self.store.course('owner',course['id'])['sections'][0]['lesson'],'真实保留的课程讲解')

    def test_soft_delete_restores_every_record_and_blocks_learning(self):
        course=self.create();cid=course['id'];self.populate(course);before=self.counts(cid)
        self.store.recycle_course('owner',cid)
        self.assertIsNone(self.store.course('owner',cid));self.assertEqual(self.store.courses('owner'),[])
        self.assertEqual(self.counts(cid),before)
        self.assertEqual(len(self.store.managed_courses('owner',deleted=True)),1)
        self.assertFalse(self.store.save_lesson('owner',cid,course['sections'][0]['id'],'覆盖旧讲解'))
        with self.assertRaises(ValueError):self.store.graph('owner',cid)
        self.store.restore_course('owner',cid);self.assertEqual(self.counts(cid),before)
        self.assertEqual(self.store.managed_course('owner',cid)['progress'],50)

    def test_copy_preserves_structure_and_references_but_not_learning(self):
        course=self.create();cid=course['id'];old_source=self.populate(course)
        cloned=self.store.copy_course('owner',cid);new=cloned['id'];self.assertNotEqual(new,cid)
        self.assertEqual(cloned['current_ordinal'],1);self.assertTrue(all(s['lesson'] is None for s in cloned['sections']))
        self.assertTrue(set(s['id'] for s in course['sections']).isdisjoint(s['id'] for s in cloned['sections']))
        self.assertEqual(self.store.managed_course('owner',new)['progress'],0)
        graph=self.store.graph('owner',new);self.assertEqual(graph['edges'],self.store.graph('owner',cid)['edges'])
        ref=graph['atoms'][0]['source_reference'][0];self.assertNotEqual(ref['document_id'],old_source['id'])
        source=self.store.source('owner',new,ref['document_id']);self.assertIn(ref['quote'],source['content'])
        self.assertEqual(graph['atoms'][0]['quality_status'],'candidate')
        self.assertTrue(all(a['rate'] is None for a in self.store.knowledge_state('owner',new)['atoms']))
        for table in ['quizzes','tutor_turns','learning_events','production_batches']:self.assertEqual(self.counts(new)[table],0)
        self.assertEqual(self.store.mastery('owner',cid)['overall_rate'],100)

    def test_copy_keeps_source_conflicts_unconfirmed_and_owned(self):
        from mindos.acquisition import document,text_blocks
        course=self.create();cid=course['id'];one=self.populate(course)
        two=self.store.save_source('owner',cid,document('外部说明','web','web_search',text_blocks('图论研究的对象有不同的定义表述，需比较顶点和边之间的关系。'),url='https://example.org/graph'))
        docs=[one,two];selections={d['id']:[b['id'] for b in d['metadata']['blocks']] for d in docs}
        def ref(d):
            b=d['metadata']['blocks'][0];return {'document_id':d['id'],'block_id':b['id'],'quote':b['text']}
        conflict=self.store.save_conflicts('owner',cid,{'conflicts':[{'topic':'图论','description':'两个来源对图论定义存在明显不同表述，需要用户保留差异。','source_a':ref(one),'source_b':ref(two)}]},docs,selections)[0]
        self.store.confirm_conflict('owner',cid,conflict['id'],'保留两个来源的不同表述供核对。')
        clone=self.store.copy_course('owner',cid);copied=self.store.conflicts('owner',clone['id'])[0]
        self.assertFalse(copied['confirmed']);self.assertNotEqual(copied['source_a'],one['id'])
        self.assertEqual(copied['content']['source_a']['document_id'],copied['source_a'])
        self.store.recycle_course('owner',cid);self.store.purge_course('owner',cid,course['title'])
        self.assertEqual(len(self.store.conflicts('owner',clone['id'])),1)

    def test_sort_persists_and_rejects_missing_foreign_duplicate_positions(self):
        one,two=self.create('课程一'),self.create('课程二');foreign=self.create('别人的课程','other')
        entries=[{'id':two['id'],'sort_order':1},{'id':one['id'],'sort_order':2}]
        self.store.order_courses('owner',entries);reopened=Storage(self.store.path)
        self.assertEqual([c['id'] for c in reopened.courses('owner')],[two['id'],one['id']])
        for bad in [entries[:1],[entries[0],entries[0]],entries+[{'id':foreign['id'],'sort_order':3}],[{'id':one['id'],'sort_order':True}]]:
            with self.assertRaises(ValueError):self.store.order_courses('owner',bad)
        self.assertEqual([c['id'] for c in self.store.courses('owner')],[two['id'],one['id']])

    def test_purge_requires_owner_recycle_bin_and_name_and_removes_dependencies(self):
        course=self.create();cid=course['id'];self.populate(course)
        with self.assertRaises(ValueError):self.store.purge_course('owner',cid,course['title'])
        self.store.recycle_course('owner',cid)
        with self.assertRaises(ValueError):self.store.purge_course('other',cid,course['title'])
        with self.assertRaises(ValueError):self.store.purge_course('owner',cid,'错误名称')
        self.store.purge_course('owner',cid,course['title'])
        self.assertTrue(all(count==0 for count in self.counts(cid).values()))
        with self.store.connect() as db:self.assertEqual(list(db.execute('PRAGMA foreign_key_check')),[])
        self.assertEqual(self.store.managed_courses('owner',deleted=True),[])

    def test_every_mutation_and_recycle_lookup_are_owned(self):
        course=self.create();cid=course['id']
        for operation in [lambda:self.store.managed_course('other',cid),lambda:self.store.update_course('other',cid,{'title':'抢占'}),lambda:self.store.copy_course('other',cid),lambda:self.store.recycle_course('other',cid)]:
            with self.assertRaises(ValueError):operation()
        self.store.recycle_course('owner',cid)
        with self.assertRaises(ValueError):self.store.restore_course('other',cid)

    def test_discovery_in_progress_blocks_structure_mutations(self):
        course=self.create();cid=course['id'];self.store.begin_discovery('owner',cid)
        for action in [lambda:self.store.recycle_course('owner',cid),lambda:self.store.copy_course('owner',cid),lambda:self.store.update_course('owner',cid,{'title':'修改'})]:
            with self.assertRaises(ValueError):action()
        self.assertIsNotNone(self.store.course('owner',cid))

    def test_invalid_metadata_fails_without_partial_writes(self):
        course=self.create();cid=course['id']
        for fields in [{'status':'fake'},{'level':'零基础'},{'cover':'javascript:alert(1)'},{'tags':['x']*11},{'title':''}]:
            with self.assertRaises(ValueError):self.store.update_course('owner',cid,fields)
        self.assertEqual(self.store.course('owner',cid)['title'],course['title'])

    def test_old_rows_migrate_idempotently_without_losing_data(self):
        path=Path(self.temp.name)/'old.sqlite3'
        with sqlite3.connect(path) as db:
            db.execute('CREATE TABLE courses(id TEXT PRIMARY KEY,session_id TEXT NOT NULL,title TEXT NOT NULL,goal TEXT NOT NULL,current_ordinal INTEGER NOT NULL,created_at TEXT NOT NULL)')
            db.execute("INSERT INTO courses VALUES('old','owner','旧课程','原目标',1,'2026-01-01')")
        migrated=Storage(path);value=migrated.managed_course('owner','old')
        self.assertEqual((value['status'],value['level'],value['goal']),('active','入门','原目标'))
        migrated.update_course('owner','old',{'status':'archived'})
        self.assertEqual(Storage(path).managed_course('owner','old')['status'],'archived')
        self.assertEqual(value['updated_at'],value['created_at'])

class ManagementApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from test_prototype import PrototypeTests
        from test_discovery import Provider
        cls.fixture=PrototypeTests;cls.fixture.setUpClass();cls.fixture.server.discovery_provider_factory=lambda course:Provider()
    @classmethod
    def tearDownClass(cls):cls.fixture.tearDownClass()
    def setUp(self):self.bridge=self.fixture();self.bridge.setUp();self.bridge.configure()
    def request(self,path,method='GET',body=None,other=False,origin=None):
        import urllib.request,urllib.error
        data=json.dumps(body).encode() if body is not None else None
        req=urllib.request.Request(self.bridge.url+path,data=data,method=method,headers={**({'Content-Type':'application/json'} if data else {}),**({'Origin':origin} if origin else {})})
        client=urllib.request.build_opener() if other else self.bridge.client
        try:
            with client.open(req,timeout=10) as response:return response.status,json.loads(response.read())
        except urllib.error.HTTPError as exc:return exc.code,json.loads(exc.read())
    def create(self):
        status,result=self.request('/api/courses','POST',{'name':'管理API课程','goal':'理解基础','description':'简介','tags':['数学'],'level':'进阶'})
        self.assertEqual(status,200,result);draft=result['draft']
        status,result=self.request('/api/courses','POST',{'confirm':True,'draft_id':draft['id'],'revision':1})
        self.assertEqual(status,200,result)
        for thread in self.fixture.server.discovery_engine.threads:thread.join(timeout=8)
        return result['course_id']
    def test_rest_endpoints_metadata_status_order_copy_delete_restore_and_purge(self):
        cid=self.create();status,data=self.request('/api/courses');self.assertEqual(status,200)
        self.assertEqual(data['courses'][0]['level'],'进阶');self.assertEqual(data['courses'][0]['description'],'简介')
        self.assertEqual(self.request(f'/api/courses/{cid}','PUT',{'name':'重新命名'})[0],200)
        self.assertEqual(self.request(f'/api/courses/{cid}/status','PUT',{'status':'archived'})[0],200)
        self.assertEqual(len(self.request('/api/courses?status=archived')[1]['courses']),1)
        status,copied=self.request(f'/api/courses/{cid}/copy','POST',{});self.assertEqual(status,200,copied)
        clone=copied['course']['id']
        self.assertEqual(self.request('/api/courses/order','PUT',[{'id':clone,'sort_order':1},{'id':cid,'sort_order':2}])[0],200)
        self.assertEqual(self.request(f'/api/courses/{cid}','DELETE')[0],200)
        self.assertEqual(self.request('/api/course?course_id='+cid)[0],400)
        self.assertEqual(len(self.request('/api/courses?deleted=true')[1]['courses']),1)
        self.assertEqual(self.request(f'/api/courses/{cid}/restore','POST',{})[0],200)
        self.assertEqual(self.request(f'/api/courses/{cid}','DELETE')[0],200)
        self.assertEqual(self.request(f'/api/courses/{cid}/permanent','DELETE',{'confirm_title':'重新命名'})[0],200)
        self.assertEqual(self.request(f'/api/courses/{cid}')[0],400)
    def test_foreign_browser_and_external_origin_are_rejected(self):
        cid=self.create()
        for method,body in [('GET',None),('PUT',{'name':'冒用'}),('DELETE',None)]:self.assertEqual(self.request(f'/api/courses/{cid}',method,body,other=True)[0],400)
        self.assertEqual(self.request(f'/api/courses/{cid}','DELETE',origin='https://external.example')[0],400)
        self.assertEqual(self.request(f'/api/courses/{cid}/status','PUT',{'status':'nonsense'})[0],400)
