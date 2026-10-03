"""Actual HTTP ownership, query guards, projection refresh and frozen tutor integration."""
import unittest,urllib.request
from unittest.mock import patch
from mindos.server import MindOSHandler
from mindos.universe.universe_graph import star_id
from mindos.tutor.quality import QualityTutorService
from mindos.learning.state import empty
from final_fixture import grade
import test_tutor_p6_api as http
import test_universe_p7 as fixture

class UniverseAPITests(unittest.TestCase):
 setUpClass=classmethod(http.TutorAPITests.setUpClass.__func__)
 tearDownClass=classmethod(http.TutorAPITests.tearDownClass.__func__)
 req=http.TutorAPITests.req
 def setUp(self):
  http.TutorAPITests.setUp(self);self.c=fixture.make_course(self.store,user=self.user);self.cid=self.c['id'];self.sid=star_id(self.cid,'a0')
 def test_global_route(self):s,r=self.req('/api/universe');self.assertEqual(s,200);self.assertTrue(r['galaxies']);self.assertEqual(r['stars'],[])
 def test_course_route(self):s,r=self.req('/api/universe/course/'+self.cid);self.assertEqual(s,200);self.assertEqual(len(r['nebulae']),3)
 def test_chapter_route(self):s,r=self.req('/api/universe/course/'+self.cid+'?chapter_id='+self.c['sections'][0]['id']);self.assertEqual(s,200);self.assertEqual(r['stars'][0]['atom_id'],'a0')
 def test_star_route(self):s,r=self.req('/api/universe/star/'+self.sid);self.assertEqual(s,200);self.assertEqual(r['mastery_state'],'learning')
 def test_route_ownership(self):self.assertEqual(self.req('/api/universe/course/'+self.cid,client=urllib.request.build_opener())[0],400)
 def test_star_ownership(self):self.assertEqual(self.req('/api/universe/star/'+self.sid,client=urllib.request.build_opener())[0],400)
 def test_no_mutation_post(self):before=fixture.snapshot(self.store);self.assertEqual(self.req('/api/universe',{},'POST')[0],405);self.assertEqual(before,fixture.snapshot(self.store))
 def test_no_mutation_put(self):self.assertEqual(self.req('/api/universe/course/'+self.cid,{'mastery':1},'PUT')[0],405)
 def test_no_mutation_delete(self):self.assertEqual(self.req('/api/universe/star/'+self.sid,{},'DELETE')[0],405)
 def test_reject_mastery_in_query(self):self.assertEqual(self.req('/api/universe?mastery=1')[0],400)
 def test_reject_duplicate_pagination(self):self.assertEqual(self.req('/api/universe?offset=0&offset=1')[0],400)
 def test_reject_invalid_pagination(self):self.assertEqual(self.req('/api/universe?offset=-1')[0],400)
 def test_search_route(self):self.assertTrue(self.req('/api/universe?search=Attention')[1]['results'])
 def test_unknown_path(self):self.assertEqual(self.req('/api/universe/no-such-route')[0],404)
 def test_gets_do_not_change_any_table(self):before=fixture.snapshot(self.store);self.req('/api/universe');self.req('/api/universe/course/'+self.cid);self.req('/api/universe/star/'+self.sid);self.assertEqual(before,fixture.snapshot(self.store))
 def test_star_tutor_context_accepted_and_actual(self):
  ctx=self.req('/api/universe/star/'+self.sid)[1]['tutor_context']
  s,r=self.req('/api/tutor/chat',{**ctx,'message':'什么是矩阵？'});self.assertEqual(s,200);self.assertTrue(r['saved']);self.assertEqual(self.model.calls[-1]['context']['current_context']['knowledge_atom_id'],'a0');self.assertEqual(self.model.calls[-1]['context']['course']['id'],self.cid)
 def test_wrong_future_tutor_context_cannot_unlock(self):ctx=self.req('/api/universe/star/'+star_id(self.cid,'a1'))[1]['tutor_context'];self.assertEqual(self.req('/api/tutor/chat',{**ctx,'message':'解释'} )[0],400)
 def test_p0_actual_submit_then_universe_refresh(self):
  self.assertEqual(self.req('/api/universe/star/'+self.sid)[1]['atom']['measured_dimensions'],[]);grade(self.store,self.c,'a0',user=self.user);self.assertIn('understanding',self.req('/api/universe/star/'+self.sid)[1]['atom']['measured_dimensions'])
 def test_static_assets(self):
  for path in ['/knowledge-universe.css','/components/mindos/knowledge-universe.js','/components/mindos/universe-renderer.js']:
   with self.client.client.open(self.base.url+path) as r:self.assertEqual(r.status,200)
