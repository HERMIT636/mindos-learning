"""Owned P8 HTTP contracts, no simulated connectivity claims."""
import base64,json,unittest,urllib.request,urllib.error
from resource_fixture import make_course,png,pdf,PAYLOADS
from mindos.resources.service import ResourceService
from test_universe_p7 import snapshot
class ResourceAPITests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  from test_prototype import PrototypeTests
  cls.fixture=PrototypeTests;cls.fixture.setUpClass();t=cls.fixture();t.setUp();t.configure();cls.profile=t.server.storage.selected_model_profile(t.session_id())
 @classmethod
 def tearDownClass(cls):cls.fixture.tearDownClass()
 def setUp(self):self.t=self.fixture();self.t.setUp();self.t.call('/api/models/select', {'id':self.profile});self.user=self.t.session_id();self.c=make_course(self.t.server.storage,self.user);self.cid=self.c['id'];self.s=ResourceService(self.t.server.storage);self.path='/api/courses/'+self.cid+'/atoms/a0/resources'
 def request(self,path,method='GET',body=None,other=False,origin=None):
  data=json.dumps(body).encode() if body is not None else None;req=urllib.request.Request(self.t.url+path,data=data,method=method,headers={**({'Content-Type':'application/json'} if data else {}),**({'Origin':origin} if origin else {})});client=urllib.request.build_opener() if other else self.t.client
  try:
   with client.open(req,timeout=10) as r:return r.status,json.loads(r.read())
  except urllib.error.HTTPError as e:return e.code,json.loads(e.read())
 def create(self,kind='text'):return self.request(self.path,'POST',{'type':kind,'title':'实际资料','payload':PAYLOADS[kind]})[1]['resource']
 def test_create_and_owned_list(self):r=self.create();status,value=self.request(self.path);self.assertEqual(status,200);self.assertEqual(value['resources'][0]['id'],r['id'])
 def test_foreign_list_denied(self):self.assertEqual(self.request(self.path,other=True)[0],400)
 def test_future_atom_list_denied(self):self.assertEqual(self.request(self.path.replace('a0','a1'))[0],400)
 def test_mutation_foreign_origin_denied(self):self.assertEqual(self.request(self.path,'POST',{'type':'text','title':'资料','payload':PAYLOADS['text']},origin='https://attacker.example')[0],400)
 def test_client_mastery_rejected(self):self.assertEqual(self.request(self.path,'POST',{'type':'text','title':'资料','payload':PAYLOADS['text'],'mastery':1})[0],400)
 def test_upload_and_local_file(self):
  status,v=self.request('/api/resources/upload','POST',{'filename':'x.png','content_base64':base64.b64encode(png()).decode()});self.assertEqual(status,200);rid=v['resource_id'];req=urllib.request.Request(self.t.url+'/api/resources/'+rid+'/file')
  with self.t.client.open(req) as r:self.assertEqual(r.headers['Content-Type'],'image/png');self.assertEqual(r.read(),png());self.assertEqual(r.headers['X-Content-Type-Options'],'nosniff')
 def test_invalid_base64_denied(self):self.assertEqual(self.request('/api/resources/upload','POST',{'filename':'x.png','content_base64':'??'})[0],400)
 def test_bad_upload_extension_denied(self):self.assertEqual(self.request('/api/resources/upload','POST',{'filename':'x.svg','content_base64':base64.b64encode(b'<svg/>').decode()})[0],400)
 def test_pdf_selected_excerpt_api(self):r=self.s.upload(self.user,'x.pdf',pdf());status,v=self.request('/api/resources/'+r['id']+'/extract','POST',{'pages':[2]});self.assertEqual(status,200);self.assertIn('SECOND',v['resource']['payload']['text']);self.assertNotIn('FIRST',v['resource']['payload']['text'])
 def test_failed_pdf_api_returns_no_guessed_text(self):r=self.s.upload(self.user,'Answer.pdf',b'%PDF-bad');status,v=self.request('/api/resources/'+r['id']);self.assertEqual(status,200);self.assertEqual(v['resource']['status'],'failed');self.assertNotIn('text',v['resource']['payload'])
 def test_delete_confirmation_and_mapping(self):r=self.create();self.assertEqual(self.request('/api/resources/'+r['id'],'DELETE',{})[0],400);self.assertEqual(self.request('/api/resources/'+r['id'],'DELETE',{'confirm':True})[0],200);self.assertEqual(self.request(self.path)[1]['resources'],[])
 def test_foreign_delete_denied(self):r=self.create();self.assertEqual(self.request('/api/resources/'+r['id'],'DELETE',{'confirm':True},other=True)[0],400)
 def test_mapping_unlink_api_preserves_resource(self):r=self.create();self.assertEqual(self.request(self.path+'/'+r['id']+'/link','DELETE',{})[0],200);self.assertEqual(self.request('/api/resources/'+r['id'])[0],200)
 def test_generation_resource_api(self):status,v=self.request(self.path+'/generate','POST',{'type':'diagram'});self.assertEqual(status,200);self.assertTrue(v['available']);self.assertEqual(v['resource']['resource_type'],'diagram')
 def test_tutor_selected_resource_and_history(self):
  r=self.create();status,v=self.request('/api/resources/tutor/chat','POST',{'context_id':self.cid,'current_context':{'section_ordinal':1,'knowledge_atom_id':'a0'},'focused_resource_id':r['id'],'message':'请解释材料中的矩阵','request_id':'p8-http'});self.assertEqual(status,200);self.assertFalse(v['fallback']);self.assertEqual(v['resource_citations'][0]['resource_id'],r['id']);self.assertEqual(self.request('/api/tutor/conversations?context_id='+self.cid)[1]['messages'][-1]['resource_citations'],v['resource_citations'])
 def test_unmapped_tutor_resource_denied(self):r=self.s.create(self.user,'text','未关联',PAYLOADS['text']);self.assertEqual(self.request('/api/resources/tutor/chat','POST',{'context_id':self.cid,'current_context':{'section_ordinal':1,'knowledge_atom_id':'a0'},'focused_resource_id':r['id'],'message':'解释'})[0],400)
 def test_focused_selection_cannot_override_course_state(self):r=self.create();self.assertEqual(self.request('/api/resources/tutor/chat','POST',{'context_id':self.cid,'current_context':{'section_ordinal':99,'knowledge_atom_id':'a0'},'focused_resource_id':r['id'],'message':'解释'})[0],400)
 def test_debug_endpoint_hidden_by_default(self):r=self.create();self.assertEqual(self.request('/api/resources/'+r['id']+'/inspect')[0],404)
 def test_get_requests_do_not_write_any_table(self):r=self.create();before=snapshot(self.t.server.storage);self.request(self.path);self.request('/api/resources/'+r['id']);self.assertEqual(before,snapshot(self.t.server.storage))
 def test_api_copy_does_not_copy_personal_resources(self):self.create();status,v=self.request('/api/courses/'+self.cid+'/copy','POST',{'title':'副本'});self.assertEqual(status,200);self.assertEqual(self.s.list(self.user,v['course']['id'],'a0')['resources'],[])
 def test_api_purge_keeps_original_uploaded_file(self):r=self.s.upload(self.user,'x.png',png());self.s.link(self.user,self.cid,'a0',r['id']);self.request('/api/courses/'+self.cid,'DELETE',{});self.assertEqual(self.request('/api/courses/'+self.cid+'/permanent','DELETE',{'confirm_title':self.c['title']})[0],200);self.assertTrue(self.s.file(self.user,r['id'])[0].exists())
 def test_static_local_renderer_served(self):
  for path in ['/knowledge-space.css','/vendor/katex.min.js','/components/mindos/resource-renderer.js','/components/mindos/knowledge-space.js']:
   with self.t.client.open(self.t.url+path) as r:self.assertEqual(r.status,200)
