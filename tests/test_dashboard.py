"""Dashboard projections must preserve evidence, ownership and manual progression."""
import json
import tempfile
import unittest
from pathlib import Path
from mindos.storage import Storage
from mindos.dashboard import DashboardService
from mindos.adaptive.teaching_state import LearningStateManager


class DashboardTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.store=Storage(Path(self.temp.name)/'db.sqlite3');self.service=DashboardService(self.store)
    def tearDown(self):self.temp.cleanup()
    def create(self,title='Attention',user='owner'):
        draft=self.store.save_draft(user,title,'理解基本机制','',{'sections':[{'title':'基础','objective':'建立直觉'},{'title':'进阶','objective':'理解方法'}]},[])
        return self.store.confirm_draft(user,draft['id'],1)
    def quiz(self,course,answers=('a','b'),user='owner'):
        cid=course['id'];sid=course['sections'][0]['id'];self.store.save_lesson(user,cid,sid,'本节讲解')
        questions=[{'prompt':'private prompt','assessment_type':kind,'choices':{'a':'正确','b':'错误','c':'另一项','d':'其他'}} for kind in ('concept','application')]
        quiz=self.store.create_quiz(user,cid,sid,questions,[{'answer':'a','explanation':'private explanation'}]*2)
        self.store.submit_quiz(user,cid,quiz['id'],list(answers))
        return quiz
    def snapshot(self):
        with self.store.connect() as db:return list(db.iterdump())
    def test_empty_and_inactive_courses_do_not_invent_state(self):
        empty=self.service.read('owner');self.assertIsNone(empty['current']);self.assertIsNone(empty['learning_state']);self.assertEqual(empty['recommendations'],[])
        c=self.create();self.store.update_course('owner',c['id'],{'status':'paused'})
        self.assertIsNone(self.service.read('owner')['current'])
        self.assertEqual(self.service.read('owner',c['id'])['current']['course_id'],c['id'])
    def test_default_selects_recent_active_course_and_excludes_archived(self):
        a=self.create('A');b=self.create('B');self.quiz(b)
        self.assertEqual(self.service.read('owner')['current']['course_id'],b['id'])
        self.store.update_course('owner',b['id'],{'status':'archived'})
        self.assertEqual(self.service.read('owner')['current']['course_id'],a['id'])
    def test_dimensions_use_existing_evidence_without_cross_course_merging(self):
        a=self.create('A');b=self.create('B');self.quiz(a);self.quiz(b,('a','a'))
        result=self.service.read('owner',a['id']);expected,_=LearningStateManager(self.store).read('owner',a['id'],1)
        self.assertEqual(result['learning_state'],expected)
        dims=result['learning_state']['assessment_dimensions'];self.assertEqual(dims['concept']['rate'],1);self.assertEqual(dims['application']['rate'],0);self.assertNotIn('transfer',dims)
        self.assertEqual(self.service.read('owner',b['id'])['learning_state']['assessment_dimensions']['application']['rate'],1)
    def test_timeline_scoped_redacted_and_excludes_pending_tests(self):
        a=self.create('A');b=self.create('B');foreign=self.create('PRIVATE','other');self.quiz(a);self.quiz(b);self.quiz(foreign,user='other')
        self.store.save_assistant_exchange('owner',a['id'],'exchange','private question','private answer',None,{},[],{})
        self.store.create_quiz('owner',a['id'],a['sections'][0]['id'],[{'prompt':'pending secret'}],[{'answer':'a'}])
        result=self.service.read('owner',a['id']);self.assertTrue(result['timeline']);self.assertTrue(all(t['course_id']==a['id'] for t in result['timeline']))
        self.assertEqual(sum(t['kind']=='quiz' for t in result['timeline']),1);self.assertEqual(sum(t['kind']=='tutor' for t in result['timeline']),1)
        self.assertNotIn('private',json.dumps(result['timeline']));self.assertNotIn('PRIVATE',json.dumps(self.service.read('owner')))
        self.store.recycle_course('owner',b['id']);self.assertNotIn(b['id'],json.dumps(self.service.read('owner')))
    def test_foreign_and_deleted_course_selection_rejected(self):
        c=self.create()
        with self.assertRaises(ValueError):self.service.read('other',c['id'])
        self.store.recycle_course('owner',c['id'])
        with self.assertRaises(ValueError):self.service.read('owner',c['id'])
    def test_read_only_no_model_calls_or_progress_updates(self):
        c=self.create();self.quiz(c);before=self.snapshot()
        for _ in range(2):self.service.read('owner',c['id'])
        self.assertEqual(self.snapshot(),before);self.assertEqual(self.store.course('owner',c['id'])['current_ordinal'],1)
        self.assertTrue(all(r['source'] in {'course_state','knowledge_state_rules'} for r in self.service.read('owner')['recommendations']))


class DashboardAPITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from test_prototype import PrototypeTests
        cls.fixture=PrototypeTests;cls.fixture.setUpClass()
    @classmethod
    def tearDownClass(cls):cls.fixture.tearDownClass()
    def setUp(self):self.client=self.fixture();self.client.setUp();self.client.call('/api/bootstrap')
    def test_endpoint_context_matches_selection_and_static_components_served(self):
        store=self.fixture.server.storage;user=self.client.session_id()
        draft=store.save_draft(user,'API课程','','',{'sections':[{'title':'基础','objective':'理解'}]},[]);course=store.confirm_draft(user,draft['id'],1)
        status,data=self.client.call('/api/dashboard?course_id='+course['id']);self.assertEqual(status,200);self.assertEqual(data['context']['course']['id'],data['current']['course_id'])
        for path in ['/universe.css','/components/mindos/state.js','/components/mindos/universe.js']:
            with self.client.client.open(self.fixture.url+path) as response:self.assertEqual(response.status,200)
        import urllib.request,http.cookiejar
        other=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self.assertEqual(self.client.call('/api/dashboard?course_id='+course['id'],client=other)[0],400)
