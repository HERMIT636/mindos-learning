"""P8 isolation, ownership, real parsers and shared quality path."""
import base64,copy,hashlib,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from mindos.storage import Storage
from mindos.resources import ResourceService
from mindos.resources.context import MultimodalTutorContextBuilder
from mindos.resources.generation import ResourceGenerator
from mindos.resources.tutor import ResourceTutorService
from mindos.resources.protocol import POLICY,content,resource_text
from resource_fixture import png,pdf,PAYLOADS,ResourceModel,make_course
from test_universe_p7 import snapshot
from final_fixture import grade

class ResourceTests(unittest.TestCase):
 def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.store=Storage(Path(self.tmp.name)/'db');self.c=make_course(self.store);self.cid=self.c['id'];self.s=ResourceService(self.store);self.model=ResourceModel()
 def tearDown(self):self.tmp.cleanup()
 def create(self,kind='text',role=None,source='manual'):
  r=self.s.create('owner',kind,kind+'材料',PAYLOADS[kind],source);self.s.link('owner',self.cid,'a0',r['id'],role);return r
 def protected(self):return {k:v for k,v in snapshot(self.store).items() if k not in {'knowledge_resources','atom_resource_mappings','sqlite_sequence','tutor_response_meta','tutor_messages','tutor_conversations','tutor_observations','tutor_memories'}}
 def chat(self,r,question='请解释当前材料的直观含义',grounded=False,rid='chat-1',model=None):return ResourceTutorService(self.store).chat('owner',{'context_id':self.cid,'current_context':{'section_ordinal':1,'knowledge_atom_id':'a0'},'message':question,'focused_resource_id':r['id'] if r else None,'resource_grounded':grounded,'request_id':rid},model or self.model,None)
 def test_multiple_resources_on_one_atom(self):a=self.create();b=self.create('formula');self.assertEqual({r['id'] for r in self.s.list('owner',self.cid,'a0')['resources']},{a['id'],b['id']})
 def test_foreign_resource_detail_denied(self):r=self.create();self.assertRaises(ValueError,self.s.get,'other',r['id'])
 def test_foreign_resource_file_denied(self):r=self.s.upload('owner','x.png',png());self.assertRaises(ValueError,self.s.file,'other',r['id'])
 def test_foreign_course_link_denied(self):r=self.create();self.assertRaises(ValueError,self.s.link,'other',self.cid,'a0',r['id'])
 def test_cross_owner_resource_link_denied(self):r=self.s.create('other','text',' чужой',{'text':'private'});self.assertRaises(ValueError,self.s.link,'owner',self.cid,'a0',r['id'])
 def test_future_atom_link_denied(self):r=self.create();self.assertRaises(ValueError,self.s.link,'owner',self.cid,'a1',r['id'])
 def test_deprecated_atom_link_denied(self):
  r=self.create()
  with self.store.connect() as db:g=json.loads(db.execute('SELECT graph_json FROM course_graphs WHERE course_id=?',(self.cid,)).fetchone()[0]);g['atoms'][0]['quality_status']='deprecated';db.execute('UPDATE course_graphs SET graph_json=? WHERE course_id=?',(json.dumps(g),self.cid))
  self.assertRaises(ValueError,self.s.link,'owner',self.cid,'a0',r['id'])
 def test_invalid_role_denied(self):r=self.create();self.assertRaises(ValueError,self.s.link,'owner',self.cid,'a0',r['id'],'mastered')
 def test_mapping_repeat_does_not_duplicate(self):r=self.create();self.s.link('owner',self.cid,'a0',r['id']);self.assertEqual(len(self.s.list('owner',self.cid,'a0')['resources']),1)
 def test_mapping_unlink_does_not_delete_file(self):r=self.s.upload('owner','x.png',png());self.s.link('owner',self.cid,'a0',r['id']);self.s.unlink('owner',self.cid,'a0',r['id']);self.assertEqual(self.s.file('owner',r['id'])[0].read_bytes(),png())
 def test_many_to_many_across_owned_courses(self):r=self.create();other=make_course(self.store,title='另一门课程');self.s.link('owner',other['id'],'a0',r['id']);self.s.unlink('owner',self.cid,'a0',r['id']);self.assertEqual(self.s.list('owner',other['id'],'a0')['resources'][0]['id'],r['id'])
 def test_upload_name_not_used_as_path(self):r=self.s.upload('owner','很安全.png',png());p,_=self.s.file('owner',r['id']);self.assertEqual(p.name,r['id']+'.png')
 def test_upload_actual_content_hash(self):r=self.s.upload('owner','x.png',png());self.assertEqual(r['content_hash'],hashlib.sha256(png()).hexdigest())
 def test_duplicate_bytes_keep_distinct_owned_resources(self):a=self.s.upload('owner','x.png',png());b=self.s.upload('owner','y.png',png());self.assertNotEqual(a['id'],b['id']);self.assertEqual(a['content_hash'],b['content_hash'])
 def test_png_crc_damage_rejected(self):self.assertRaises(ValueError,self.s.upload,'owner','x.png',png()[:-5]+b'badxx')
 def test_actual_jpeg_upload_and_decode(self):
  from PIL import Image
  import io
  b=io.BytesIO();Image.new('RGB',(4,4),'blue').save(b,format='JPEG');r=self.s.upload('owner','test.jpg',b.getvalue());self.assertEqual(r['mime_type'],'image/jpeg');self.assertEqual(self.s.file('owner',r['id'])[0].read_bytes(),b.getvalue())
 def test_jpeg_incomplete_rejected(self):self.assertRaises(ValueError,self.s.upload,'owner','x.jpg',b'\xff\xd8\xff\xda\x00\x02bad')
 def test_extension_spoof_rejected(self):self.assertRaises(ValueError,self.s.upload,'owner','x.pdf',b'plain text')
 def test_executable_upload_rejected(self):self.assertRaises(ValueError,self.s.upload,'owner','x.exe',b'MZ binary')
 def test_svg_upload_rejected(self):self.assertRaises(ValueError,self.s.upload,'owner','x.svg',b'<svg onload="bad()"/>')
 def test_filename_traversal_rejected(self):self.assertRaises(ValueError,self.s.upload,'owner','../x.txt',b'hello')
 def test_windows_filename_traversal_rejected(self):self.assertRaises(ValueError,self.s.upload,'owner',r'..\x.txt',b'hello')
 def test_symlink_file_denied(self):
  r=self.s.upload('owner','x.png',png());p,_=self.s.file('owner',r['id']);outside=Path(self.tmp.name)/'outside';outside.write_bytes(png());p.unlink();p.symlink_to(outside);self.assertRaises(ValueError,self.s.file,'owner',r['id'])
 def test_database_path_tampering_denied(self):
  r=self.s.upload('owner','x.png',png())
  with self.store.connect() as db:db.execute('UPDATE knowledge_resources SET local_path=? WHERE id=?',('../outside',r['id']))
  self.assertRaises(ValueError,self.s.file,'owner',r['id'])
 def test_text_binary_control_rejected(self):self.assertRaises(ValueError,self.s.upload,'owner','x.txt',b'a\x00b')
 def test_empty_upload_rejected(self):self.assertRaises(ValueError,self.s.upload,'owner','x.txt',b'')
 def test_text_limit_enforced(self):
  with patch.dict(POLICY['uploads'],max_text_bytes=3):self.assertRaises(ValueError,self.s.upload,'owner','x.txt',b'four')
 def test_image_limit_enforced(self):
  with patch.dict(POLICY['uploads'],max_image_bytes=3):self.assertRaises(ValueError,self.s.upload,'owner','x.png',png())
 def test_pdf_limit_enforced(self):
  with patch.dict(POLICY['uploads'],max_pdf_bytes=3):self.assertRaises(ValueError,self.s.upload,'owner','x.pdf',pdf())
 def test_markdown_headings_extracted(self):r=self.s.upload('owner','x.md','# Heading\n\nParagraph'.encode());self.assertEqual(r['metadata']['headings'],['Heading'])
 def test_pdf_initial_container_has_no_body(self):r=self.s.upload('owner','x.pdf',pdf());self.assertEqual(r['status'],'pending');self.assertEqual(r['metadata']['page_count'],3);self.assertEqual(resource_text(r),'')
 def test_pdf_selected_pages_only(self):r=self.s.upload('owner','x.pdf',pdf());child=self.s.extract('owner',r['id'],[2]);self.assertIn('SECOND',child['payload']['text']);self.assertNotIn('FIRST',child['payload']['text']);self.assertEqual(child['metadata']['pages'],[2]);self.assertEqual(child['metadata']['derived_from_resource_id'],r['id'])
 def test_pdf_bad_range_has_no_excerpt(self):r=self.s.upload('owner','x.pdf',pdf());self.assertRaises(ValueError,self.s.extract,'owner',r['id'],[4]);self.assertEqual(self.s.get('owner',r['id'])['status'],'failed')
 def test_pdf_duplicate_pages_denied(self):r=self.s.upload('owner','x.pdf',pdf());self.assertRaises(ValueError,self.s.extract,'owner',r['id'],[1,1])
 def test_pdf_boolean_pages_denied(self):r=self.s.upload('owner','x.pdf',pdf());self.assertRaises(ValueError,self.s.extract,'owner',r['id'],[True])
 def test_pdf_parser_failure_keeps_original(self):r=self.s.upload('owner','Attention秘密答案.pdf',b'%PDF-broken');self.assertEqual(r['status'],'failed');self.assertEqual(self.s.file('owner',r['id'])[0].read_bytes(),b'%PDF-broken');self.assertNotIn('答案',resource_text(r))
 def test_pdf_retry_after_wrong_range(self):r=self.s.upload('owner','x.pdf',pdf());self.assertRaises(ValueError,self.s.extract,'owner',r['id'],[9]);c=self.s.extract('owner',r['id'],[1]);self.assertEqual(c['status'],'ready');self.assertEqual(self.s.get('owner',r['id'])['status'],'pending')
 def test_pdf_scanned_has_clear_failure(self):
  from pypdf import PdfWriter
  import io
  w=PdfWriter();w.add_blank_page(width=100,height=100);b=io.BytesIO();w.write(b);r=self.s.upload('owner','scan.pdf',b.getvalue());self.assertRaisesRegex(ValueError,'OCR',self.s.extract,'owner',r['id'],[1])
 def test_delete_requires_exact_confirmation(self):r=self.create();self.assertRaises(ValueError,self.s.delete,'owner',r['id']);self.assertRaises(ValueError,self.s.delete,'owner',r['id'],'yes')
 def test_parent_delete_blocked_by_excerpt(self):r=self.s.upload('owner','x.pdf',pdf());child=self.s.extract('owner',r['id'],[1]);self.assertRaises(ValueError,self.s.delete,'owner',r['id'],True);self.s.delete('owner',child['id'],True);self.assertTrue(self.s.delete('owner',r['id'],True)['deleted'])
 def test_resource_delete_removes_mappings(self):r=self.create();self.s.delete('owner',r['id'],True);self.assertEqual(self.s.list('owner',self.cid,'a0')['resources'],[])
 def test_resource_delete_removes_local_file(self):r=self.s.upload('owner','x.png',png());p,_=self.s.file('owner',r['id']);self.s.delete('owner',r['id'],True);self.assertFalse(p.exists())
 def test_soft_delete_restore_keeps_resources(self):r=self.create();self.store.recycle_course('owner',self.cid);self.assertRaises(ValueError,self.s.list,'owner',self.cid,'a0');self.store.restore_course('owner',self.cid);self.assertEqual(self.s.list('owner',self.cid,'a0')['resources'][0]['id'],r['id'])
 def test_purge_keeps_personal_upload(self):r=self.s.upload('owner','x.png',png());self.s.link('owner',self.cid,'a0',r['id']);self.store.recycle_course('owner',self.cid);self.store.purge_course('owner',self.cid,self.c['title']);self.s.cleanup('owner');self.assertTrue(self.s.file('owner',r['id'])[0].exists())
 def test_purge_keeps_shared_generated(self):r=self.create(source='generated');other=make_course(self.store,title='复制目的');self.s.link('owner',other['id'],'a0',r['id']);self.store.recycle_course('owner',self.cid);self.store.purge_course('owner',self.cid,self.c['title']);self.s.cleanup('owner');self.assertEqual(self.s.get('owner',r['id'])['id'],r['id'])
 def test_purge_cleans_unshared_generated(self):r=self.create(source='generated');self.store.recycle_course('owner',self.cid);self.store.purge_course('owner',self.cid,self.c['title']);self.s.cleanup('owner');self.assertRaises(ValueError,self.s.get,'owner',r['id'])
 def test_copy_excludes_personal(self):self.create(role='personal_note');self.create('image');new=self.store.copy_course('owner',self.cid,'副本');self.s.copy_links('owner',self.cid,new['id']);self.assertEqual(self.s.list('owner',new['id'],'a0')['resources'],[])
 def test_copy_shares_generated_and_resets_progress(self):r=self.create('diagram',source='generated');new=self.store.copy_course('owner',self.cid,'副本');self.s.copy_links('owner',self.cid,new['id']);self.assertEqual(self.s.list('owner',new['id'],'a0')['resources'][0]['id'],r['id']);self.assertEqual(new['current_ordinal'],1)
 def test_list_and_detail_are_read_only(self):r=self.create();before=snapshot(self.store);self.s.list('owner',self.cid,'a0');self.s.inspect('owner',r['id']);self.assertEqual(before,snapshot(self.store))
 def test_resource_changes_preserve_all_learning_tables(self):before=self.protected();r=self.create();self.s.unlink('owner',self.cid,'a0',r['id']);self.s.delete('owner',r['id'],True);self.assertEqual(before,self.protected())
 def test_mapping_does_not_modify_prerequisites(self):before=self.store.graph('owner',self.cid);self.create();self.assertEqual(before,self.store.graph('owner',self.cid))
 def test_context_only_atom_materials(self):r=self.create();other=make_course(self.store,title='另课');x=self.s.create('owner','text','不相关',{'text':'PRIVATE_OTHER_COURSE'});self.s.link('owner',other['id'],'a0',x['id']);context=MultimodalTutorContextBuilder(self.store).build('owner',self.cid,'a0','解释');self.assertEqual([a['resource_id'] for a in context['resources']],[r['id']])
 def test_context_max_four_and_budget(self):
  for i in range(8):r=self.s.create('owner','text',str(i),{'text':'a'*20000});self.s.link('owner',self.cid,'a0',r['id'])
  c=MultimodalTutorContextBuilder(self.store).build('owner',self.cid,'a0','解释');self.assertLessEqual(len(c['resources']),4);self.assertLessEqual(sum(len(r['text']) for r in c['resources']),8000)
 def test_focus_priority(self):r=self.create();self.create('formula');ctx=MultimodalTutorContextBuilder(self.store).build('owner',self.cid,'a0','公式',r['id']);self.assertEqual(ctx['resources'][0]['resource_id'],r['id'])
 def test_grounding_requires_selected_resource(self):self.assertRaises(ValueError,MultimodalTutorContextBuilder(self.store).build,'owner',self.cid,'a0','解释',None,True)
 def test_grounding_sends_only_selected_material(self):a=self.create();self.create('formula');ctx=MultimodalTutorContextBuilder(self.store).build('owner',self.cid,'a0','解释',a['id'],True);self.assertEqual(len(ctx['resources']),1)
 def test_failed_pdf_excluded_from_context(self):r=self.s.upload('owner','x.pdf',b'%PDF-broken');self.s.link('owner',self.cid,'a0',r['id']);ctx=MultimodalTutorContextBuilder(self.store).build('owner',self.cid,'a0','解释',r['id']);self.assertEqual(ctx['resources'],[]);self.assertTrue(ctx['excluded'])
 def test_foreign_unmapped_focus_denied(self):r=self.s.create('owner','text','未关联',{'text':'secret'});self.assertRaises(ValueError,MultimodalTutorContextBuilder(self.store).build,'owner',self.cid,'a0','解释',r['id'])
 def test_image_context_explicitly_no_vision(self):r=self.create('image');c=MultimodalTutorContextBuilder(self.store).build('owner',self.cid,'a0','图',r['id']);self.assertIn('未看到图片',c['resources'][0]['text'])
 def test_reference_does_not_claim_full_text(self):r=self.create('reference');self.assertIn('未获取正文',resource_text(r))
 def test_generated_resource_through_gateway_adapter(self):v=ResourceGenerator(self.store).generate('owner',self.cid,'a0','diagram',self.model);self.assertTrue(v['available']);self.assertEqual(v['resource']['source_type'],'generated');self.assertTrue(v['resource']['metadata']['model_generated'])
 def test_generated_invalid_twice_not_saved(self):
  class Invalid:
   def resource_json(self,p):return {'title':'bad','payload':{'nodes':[],'edges':[]}}
  before=snapshot(self.store);v=ResourceGenerator(self.store).generate('owner',self.cid,'a0','diagram',Invalid());self.assertFalse(v['available']);self.assertEqual(v['attempts'],2);self.assertEqual(before,snapshot(self.store))
 def test_generated_retry_once(self):
  class Retry(ResourceModel):
   n=0
   def resource_json(self,p):self.n+=1;return {'bad':True} if self.n==1 else super().resource_json(p)
  v=ResourceGenerator(self.store).generate('owner',self.cid,'a0','diagram',Retry());self.assertTrue(v['available']);self.assertEqual(v['attempts'],2)
 def test_summary_preserves_original(self):r=self.create();before=self.s.get('owner',r['id']);v=ResourceGenerator(self.store).generate('owner',self.cid,'a0','summary',self.model,r['id']);self.assertEqual(before,self.s.get('owner',r['id']));self.assertEqual(v['resource']['metadata']['derived_from_resource_id'],r['id'])
 def test_summary_failed_pdf_denied(self):r=self.s.upload('owner','x.pdf',b'%PDF-bad');self.s.link('owner',self.cid,'a0',r['id']);self.assertRaises(ValueError,ResourceGenerator(self.store).generate,'owner',self.cid,'a0','summary',self.model,r['id'])
 def test_revision_fingerprint_changes(self):before=self.s.fingerprint('owner',self.cid,'a0');self.store.update_course('owner',self.cid,{'goal':'新目标'});self.assertNotEqual(before,self.s.fingerprint('owner',self.cid,'a0'))
 def test_grading_does_not_change_resource_fingerprint(self):before=self.s.fingerprint('owner',self.cid,'a0');grade(self.store,self.c,'a0');self.assertEqual(before,self.s.fingerprint('owner',self.cid,'a0'))
 def test_user_upload_never_autoexpires(self):r=self.create();self.store.update_course('owner',self.cid,{'goal':'更新目标'});self.assertFalse(self.s.list('owner',self.cid,'a0')['resources'][0]['needs_review']);self.assertEqual(self.s.get('owner',r['id'])['status'],'ready')
 def test_grounded_chat_no_external_fetch(self):r=self.create();v=self.chat(r,'这份材料为什么这样说',True);self.assertFalse(v['fallback']);self.assertEqual(v['search']['status'],'not_needed');self.assertTrue(v['resource_citations'])
 def test_chat_citations_saved_in_history(self):from mindos.tutor.storage import TutorMemoryStore;r=self.create();v=self.chat(r);self.assertEqual(TutorMemoryStore(self.store).history('owner',self.cid)['messages'][-1]['resource_citations'],v['resource_citations'])
 def test_chat_does_not_change_knowledge_state(self):r=self.create();before=self.protected();self.chat(r);self.assertEqual(before,self.protected())
 def test_chat_idempotent_same_material(self):r=self.create();first=self.chat(r);second=self.chat(r);self.assertEqual(first['answer'],second['answer']);self.assertEqual(len(self.model.calls),1)
 def test_chat_idempotent_changed_material_denied(self):r=self.create();other=self.create('formula');self.chat(r);self.assertRaises(ValueError,self.chat,other)
 def test_invalid_citation_fails_no_answer_saved(self):
  class Forged(ResourceModel):
   def resource_tutor_json(self,payload,repair_reason=''):
    v=super().resource_tutor_json(payload,repair_reason);v['resource_citations'][0]['quote']='fabricated unavailable quote';return v
  r=self.create();model=Forged();v=self.chat(r,model=model);self.assertTrue(v['fallback']);self.assertFalse(v['saved']);self.assertEqual(len(model.calls),2)
 def test_failed_resource_clear_no_guessing(self):r=self.s.upload('owner','矩阵秘密.pdf',b'%PDF-bad');self.s.link('owner',self.cid,'a0',r['id']);v=self.chat(r,grounded=True);self.assertIn('无法读取',v['answer']);self.assertEqual(v['resource_citations'],[])
 def test_quality_rejection_not_bypassed(self):
  class TooDeep(ResourceModel):
   def resource_tutor_json(self,payload,repair_reason=''):
    v=super().resource_tutor_json(payload,repair_reason);v['response']['blocks'].append({'type':'code','content':'code','language':'python'});return v
  r=self.create();v=self.chat(r,model=TooDeep());self.assertTrue(v['fallback']);self.assertEqual(v['attempts'],2)
 def test_unknown_client_state_denied(self):r=self.create();self.assertRaises(ValueError,ResourceTutorService(self.store).chat,'owner',{'context_id':self.cid,'message':'讲解','mastery':1},self.model,None)
 def test_resources_directory_symlink_denied(self):
  outside=Path(self.tmp.name)/'outside';outside.mkdir();self.s.directory.symlink_to(outside,target_is_directory=True);self.assertRaises(ValueError,self.s.upload,'owner','x.png',png());self.assertEqual(list(outside.iterdir()),[])
 def test_generation_link_failure_leaves_no_resource(self):
  before=snapshot(self.store)
  with patch.object(ResourceService,'link',side_effect=ValueError('changed atom')):v=ResourceGenerator(self.store).generate('owner',self.cid,'a0','diagram',self.model)
  self.assertFalse(v['available']);self.assertEqual(before['knowledge_resources'],snapshot(self.store)['knowledge_resources'])
 def test_course_cleanup_does_not_sweep_another_course(self):
  r=self.create(source='generated');other=make_course(self.store,title='另一课');x=self.s.create('owner','text','留存材料',PAYLOADS['text'],'generated');self.s.link('owner',other['id'],'a0',x['id']);self.s.unlink('owner',other['id'],'a0',x['id']);candidates=self.s.course_resource_ids('owner',self.cid);self.store.recycle_course('owner',self.cid);self.store.purge_course('owner',self.cid,self.c['title']);self.s.cleanup('owner',candidates);self.assertEqual(self.s.get('owner',x['id'])['id'],x['id']);self.assertRaises(ValueError,self.s.get,'owner',r['id'])
 def test_failed_resource_model_down_has_clear_unsaved_fallback(self):
  r=self.s.upload('owner','x.pdf',b'%PDF-bad');self.s.link('owner',self.cid,'a0',r['id'])
  class Down:
   def resource_tutor_json(self,payload,repair_reason=''):raise RuntimeError('offline')
  v=self.chat(r,grounded=True,model=Down());self.assertFalse(v['saved']);self.assertIn('无法读取',v['answer']);self.assertEqual(v['attempts'],2)
 def test_missing_observation_metadata_defaults_to_no_claims(self):
  class Minimal(ResourceModel):
   def resource_tutor_json(self,payload,repair_reason=''):
    v=super().resource_tutor_json(payload,repair_reason);v['response'].pop('observations');v['response'].pop('memories');v['response'].pop('related_atom_ids');return v
  r=self.create();v=self.chat(r,model=Minimal());self.assertFalse(v['fallback']);self.assertEqual(v['observations'],[])
 def test_grounded_request_strips_other_content_sources(self):
  r=self.create();v=self.chat(r,grounded=True);context=self.model.calls[0]['context'];self.assertEqual(context['current_content'],'');self.assertEqual(context['recent_dialogue'],[]);self.assertEqual(len(context['resource_context']['resources']),1)
 def test_policy_and_core_frozen(self):m=json.loads(Path('docs/learning-loop-p8-frozen.json').read_text());self.assertTrue(all(hashlib.sha256(Path(p).read_bytes()).hexdigest()==h for p,h in m['files'].items()));self.assertEqual(POLICY['generation']['max_retry'],1)
 def test_list_pagination_and_literal_search(self):
  for i in range(10):r=self.s.create('owner','text','title '+str(i),{'text':'hello'});self.s.link('owner',self.cid,'a0',r['id'])
  a=self.s.list('owner',self.cid,'a0');b=self.s.list('owner',self.cid,'a0',8);self.assertEqual(len(a['resources']),8);self.assertTrue(a['has_more']);self.assertEqual(len(b['resources']),2);self.assertEqual(self.s.list('owner',self.cid,'a0',search="' OR 1=1")['resources'],[])

for kind in PAYLOADS:
 def check(self,kind=kind):
  before=self.protected();r=self.create(kind);self.assertEqual(self.s.list('owner',self.cid,'a0')['resources'][0]['resource_type'],kind);self.assertEqual(before,self.protected())
 setattr(ResourceTests,'test_type_'+kind+'_does_not_create_evidence',check)
