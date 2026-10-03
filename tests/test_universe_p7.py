"""P7 projections are read-only, scoped and bounded; assertions use actual stored records."""
import copy,hashlib,json,sqlite3,tempfile,unittest
from pathlib import Path
from datetime import datetime,timedelta,timezone
from unittest.mock import patch
from mindos.storage import Storage
from mindos.universe import KnowledgeUniverseAdapter
from mindos.universe.universe_graph import visual_state,star_id,decode_star,edge,POLICY
from mindos.learning.state import empty
from mindos.learning.canonical import KnowledgeMappingEngine
from mindos.learning.personal import PersonalKnowledgeProfileBuilder
from personal_fixture import course as personal_course,train
from final_fixture import grade
NOW=datetime.now(timezone.utc)

def make_course(store,user='owner',title='Transformer知识宇宙',count=3):
 d=store.save_draft(user,title,'理解基础并练习应用','',{'sections':[{'title':n,'objective':'理解本节的基础与应用'} for n in ['导引','Attention机制','应用实践'][:count]]},[]);c=store.confirm_draft(user,d['id'],1)
 atoms=[{'id':'a'+str(i),'section':i+1,'title':['矩阵','Attention','KV Cache'][i],'summary':'这个知识点用于理解信息表示与处理。','why':'支撑下一步理解与应用','type':'mechanism','depth':i+1} for i in range(count)]
 edges=[{'from':'a'+str(i),'to':'a'+str(i+1),'type':'prerequisite'} for i in range(count-1)]
 store.save_graph(user,c['id'],{'atoms':atoms,'edges':edges});store.save_lesson(user,c['id'],c['sections'][0]['id'],'用生活中的信息匹配解释当前基础，不展开未来小节。');return c

def snapshot(store):
 with store.connect() as db:
  names=[r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
  return {n:[tuple(r) for r in db.execute('SELECT * FROM "'+n+'" ORDER BY rowid')] for n in names}

class UniverseTests(unittest.TestCase):
 def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.store=Storage(Path(self.tmp.name)/'db');self.c=make_course(self.store);self.cid=self.c['id'];self.adapter=KnowledgeUniverseAdapter(self.store)
 def tearDown(self):self.tmp.cleanup()
 def graph(self,i=0,offset=0):return self.adapter.course('owner',self.cid,self.c['sections'][i]['id'],offset)
 def detail(self,aid='a0'):return self.adapter.detail('owner',star_id(self.cid,aid))
 def test_course_maps_to_galaxy(self):r=self.adapter.all('owner');self.assertEqual(r['galaxies'][0]['course_id'],self.cid);self.assertEqual(r['galaxies'][0]['star_count'],3)
 def test_chapters_map_to_nebula(self):r=self.adapter.course('owner',self.cid);self.assertEqual([n['order'] for n in r['nebulae']],[1,2,3]);self.assertEqual([n['chapter_id'] for n in r['nebulae']],[s['id'] for s in self.c['sections']])
 def test_atoms_map_to_star(self):a=self.graph()['stars'][0];self.assertEqual(a['atom_id'],'a0');self.assertEqual(a['name'],'矩阵');self.assertEqual(a['nebula_id'],'n-'+self.c['sections'][0]['id'])
 def test_nebula_does_not_load_all_stars(self):r=self.adapter.course('owner',self.cid);self.assertEqual(r['stars'],[]);self.assertEqual(r['edges'],[])
 def test_global_does_not_load_all_atoms(self):r=self.adapter.all('owner');self.assertEqual(r['stars'],[]);self.assertEqual(r['nebulae'],[])
 def test_empty_user(self):r=self.adapter.all('empty');self.assertEqual(r['galaxies'],[]);self.assertIsNone(r['current_exploration'])
 def test_course_without_graph(self):
  with self.store.connect() as db:db.execute('DELETE FROM course_graphs WHERE course_id=?',(self.cid,))
  self.assertEqual(self.graph()['stars'],[])
 def test_global_read_no_database_changes(self):before=snapshot(self.store);self.adapter.all('owner');self.assertEqual(before,snapshot(self.store))
 def test_course_read_no_database_changes(self):before=snapshot(self.store);self.adapter.course('owner',self.cid);self.graph();self.assertEqual(before,snapshot(self.store))
 def test_star_selection_no_database_changes(self):before=snapshot(self.store);self.detail();self.assertEqual(before,snapshot(self.store))
 def test_search_no_database_changes(self):before=snapshot(self.store);self.adapter.search('owner','Attention');self.assertEqual(before,snapshot(self.store))
 def test_readonly_connection_blocks_write(self):
  with self.adapter.read() as db:
   with self.assertRaises(sqlite3.OperationalError):db.execute('UPDATE courses SET current_ordinal=2')
 def test_foreign_course_denied(self):self.assertRaises(ValueError,self.adapter.course,'other',self.cid)
 def test_foreign_star_denied(self):self.assertRaises(ValueError,self.adapter.detail,'other',star_id(self.cid,'a0'))
 def test_foreign_course_search_hidden(self):self.assertEqual(self.adapter.search('other','Attention')['results'],[])
 def test_foreign_chapter_denied(self):other=make_course(self.store,title='隔离课程');self.assertRaises(ValueError,self.adapter.course,'owner',self.cid,other['sections'][0]['id'])
 def test_deleted_course_hidden(self):self.store.recycle_course('owner',self.cid);self.assertEqual(self.adapter.all('owner')['galaxies'],[]);self.assertRaises(ValueError,self.adapter.course,'owner',self.cid)
 def test_deleted_star_denied(self):self.store.recycle_course('owner',self.cid);self.assertRaises(ValueError,self.adapter.detail,'owner',star_id(self.cid,'a0'))
 def test_archived_course_visible(self):self.store.update_course('owner',self.cid,{'status':'archived'});self.assertEqual(self.adapter.all('owner')['galaxies'][0]['status'],'archived')
 def test_restored_course_visible(self):self.store.recycle_course('owner',self.cid);self.store.restore_course('owner',self.cid);self.assertEqual(len(self.adapter.all('owner')['galaxies']),1)
 def test_same_local_atom_ids_isolated(self):other=make_course(self.store,title='独立图论');self.assertNotEqual(star_id(self.cid,'a0'),star_id(other['id'],'a0'));self.assertEqual(self.adapter.detail('owner',star_id(other['id'],'a0'))['galaxy']['name'],'独立图论')
 def test_deprecated_atom_hidden(self):
  with self.store.connect() as db:db.execute("UPDATE course_graphs SET graph_json=json_set(graph_json,'$.atoms[0].quality_status','deprecated') WHERE course_id=?",(self.cid,))
  self.assertEqual(self.graph()['stars'],[]);self.assertRaises(ValueError,self.adapter.detail,'owner',star_id(self.cid,'a0'))
 def test_future_star_structure_only(self):a=self.detail('a1')['atom'];self.assertFalse(a['unlocked']);self.assertEqual(a['mastery_state'],'unknown');self.assertNotIn('lesson',self.detail('a1'))
 def test_tutor_context_only_selectors(self):ctx=self.detail()['tutor_context'];self.assertEqual(ctx['context_id'],self.cid);self.assertEqual(ctx['current_context'],{'section_ordinal':1,'knowledge_atom_id':'a0'});self.assertNotIn('mastery',ctx)
 def test_actual_edges_only(self):r=self.detail();self.assertEqual(len(r['relations']),1);self.assertEqual(r['relations'][0]['original_relation_type'],'prerequisite');self.assertEqual(r['relations'][0]['target'],star_id(self.cid,'a1'))
 def test_no_synthetic_cross_course_edge(self):make_course(self.store,title='另一课程');self.assertEqual(self.adapter.all('owner')['edges'],[])
 def test_no_missing_endpoint_graph_edge(self):r=self.graph();self.assertEqual(r['edges'],[])
 def test_reading_progress_not_mastery(self):sid=self.c['sections'][0]['id'];self.store.learning_event('owner',self.cid,['a0'],'read');g=self.adapter.all('owner')['galaxies'][0];self.assertEqual(g['progress'],33);self.assertIn('不是掌握率',g['progress_basis'])
 def test_true_p0_submission_refreshes_visual_state(self):before=self.detail()['atom']['measured_dimensions'];grade(self.store,self.c,'a0');after=self.detail()['atom']['measured_dimensions'];self.assertEqual(before,[]);self.assertIn('understanding',after)
 def test_chat_and_self_report_not_mastered(self):
  with self.store.connect() as db:db.execute('UPDATE knowledge_states SET state_json=json_set(state_json,\'$.mastery\',1,\'$.confidence\',1) WHERE course_id=?',(self.cid,))
  self.assertNotEqual(self.detail()['mastery_state'],'mastered')
 def test_no_internal_mastery_or_confidence_fields(self):r=json.dumps(self.detail());self.assertNotIn('"mastery":',r);self.assertNotIn('"confidence":',r);self.assertNotIn('effective_mastery',r)
 def test_no_hidden_quiz_answers(self):grade(self.store,self.c,'a0');r=json.dumps(self.detail());self.assertNotIn('answers_json',r);self.assertNotIn('selected',r);self.assertNotIn('questions_json',r)
 def test_learning_history_uses_real_records(self):grade(self.store,self.c,'a0');self.assertTrue(self.detail()['independent_history']);self.assertTrue(self.adapter.course('owner',self.cid)['explored_path'])
 def test_exploration_does_not_create_history(self):self.detail();self.assertEqual(self.detail()['history'],[])
 def test_no_model_calls_for_projection(self):
  with patch('mindos.model.ModelGateway._chat',side_effect=AssertionError('not allowed')):self.adapter.all('owner');self.graph();self.detail()
 def test_importance_from_relationship_not_mastery(self):before=self.detail()['atom']['importance'];grade(self.store,self.c,'a0');self.assertEqual(self.detail()['atom']['importance'],before)
 def test_difficulty_from_existing_atom_depth(self):self.assertEqual(self.detail()['atom']['difficulty'],'概念入门')
 def test_last_review_not_invented(self):self.assertIsNone(self.detail()['atom']['last_review'])
 def test_search_course(self):self.assertTrue(any(r['type']=='galaxy' for r in self.adapter.search('owner','Transformer')['results']))
 def test_search_chapter(self):self.assertTrue(any(r['type']=='nebula' for r in self.adapter.search('owner','导引')['results']))
 def test_search_atom(self):self.assertEqual(next(r['star_id'] for r in self.adapter.search('owner','KV Cache')['results'] if r['type']=='star'),star_id(self.cid,'a2'))
 def test_search_case_insensitive(self):self.assertTrue(self.adapter.search('owner','attention')['results'])
 def test_search_percent_literal(self):self.assertEqual(self.adapter.search('owner','%')['results'],[])
 def test_search_injection_literal(self):self.assertEqual(self.adapter.search('owner',"' OR 1=1 --")['results'],[])
 def test_empty_search_rejected(self):self.assertRaises(ValueError,self.adapter.search,'owner',' ')
 def test_long_search_rejected(self):self.assertRaises(ValueError,self.adapter.search,'owner','x'*101)
 def test_invalid_negative_offset(self):self.assertRaises(ValueError,self.adapter.all,'owner',-1)
 def test_invalid_bool_offset(self):self.assertRaises(ValueError,self.adapter.all,'owner',True)
 def test_invalid_huge_offset(self):self.assertRaises(ValueError,self.adapter.all,'owner',1000001)
 def test_invalid_star_encoding(self):self.assertRaises(ValueError,self.adapter.detail,'owner','s-malformed')
 def test_atom_not_found(self):self.assertRaises(ValueError,self.adapter.detail,'owner',star_id(self.cid,'missing'))
 def large(self,count=405):
  with self.store.connect() as db:
   g={'atoms':[{'id':'big'+str(i),'section':1,'title':'知识'+str(i),'summary':'已有知识索引','why':'学习用途','depth':2,'type':'concept'} for i in range(count)],'edges':[{'from':'big'+str(i),'to':'big'+str(i+1),'type':'prerequisite'} for i in range(count-1)]};db.execute('UPDATE course_graphs SET graph_json=? WHERE course_id=?',(json.dumps(g),self.cid))
 def test_big_chapter_cluster(self):self.large();r=self.adapter.course('owner',self.cid);self.assertEqual(r['clusters'][0]['star_count'],405);self.assertEqual(r['stars'],[])
 def test_big_star_window_max_200(self):self.large();r=self.graph();self.assertEqual(len(r['stars']),200);self.assertTrue(r['has_more']);self.assertEqual(r['next_offset'],200)
 def test_big_star_pages_no_duplicate(self):self.large();one=self.graph();two=self.graph(offset=200);self.assertFalse({s['id'] for s in one['stars']}&{s['id'] for s in two['stars']})
 def test_big_last_page(self):self.large();r=self.graph(offset=400);self.assertEqual(len(r['stars']),5);self.assertFalse(r['has_more'])
 def test_search_outside_visible_window(self):self.large();r=self.adapter.search('owner','知识404');self.assertEqual(r['results'][0]['star_id'],star_id(self.cid,'big404'))
 def test_big_detail_outside_window(self):self.large();self.assertEqual(self.adapter.detail('owner',star_id(self.cid,'big404'))['atom']['name'],'知识404')
 def test_p3_snapshot_not_rebuilt(self):
  c=personal_course(self.store);train(self.store,c,n=6);PersonalKnowledgeProfileBuilder(self.store).rebuild('owner');before=snapshot(self.store);r=self.adapter.detail('owner',star_id(c['id'],'same-local-id'));self.assertTrue(r['personal_reference']['snapshot']);self.assertEqual(before,snapshot(self.store))
 def test_invalid_p3_mapping_not_displayed(self):
  c=personal_course(self.store);train(self.store,c,n=6);PersonalKnowledgeProfileBuilder(self.store).rebuild('owner')
  with self.store.connect() as db:db.execute('UPDATE courses SET goal=? WHERE id=?',('完全不同的目标',c['id']))
  self.assertIsNone(self.adapter.detail('owner',star_id(c['id'],'same-local-id'))['personal_reference'])
 def test_missing_profile_not_auto_created(self):before=snapshot(self.store);self.detail();self.assertEqual(before,snapshot(self.store))
 def test_p4_no_auto_tasks(self):before=snapshot(self.store);self.adapter.course('owner',self.cid);self.assertEqual(before,snapshot(self.store))
 def test_frozen_p0_p65_algorithms(self):
  root=Path(__file__).resolve().parents[1];manifest=json.loads((root/'docs/learning-loop-p7-frozen.json').read_text())
  for n,h in manifest['files'].items():self.assertEqual(hashlib.sha256((root/n).read_bytes()).hexdigest(),h,n)

class VisualTests(unittest.TestCase):
 def test_star_identity_roundtrip(self):self.assertEqual(decode_star(star_id('course','中文原子')),['course','中文原子'])
 def test_noncanonical_id_rejected(self):self.assertRaises(ValueError,decode_star,star_id('course','atom')+'=')
 def test_wrong_identity_shape_rejected(self):self.assertRaises(ValueError,decode_star,'s-e30')
 def test_numeric_identity_rejected(self):self.assertRaises(ValueError,decode_star,'s-WzEsMl0')
 def test_existing_edge_aliases_preserved(self):r=edge('c',{'from':'a','to':'b','type':'contrasts'});self.assertEqual(r['relation_type'],'contrast');self.assertEqual(r['original_relation_type'],'contrasts')
 def test_existing_application_alias(self):self.assertEqual(edge('c',{'from':'a','to':'b','type':'applied_in'})['relation_type'],'application')
 def test_relation_default_weight_not_truth(self):r=edge('c',{'from':'a','to':'b','type':'related'});self.assertIn('不代表',r['boundary']);self.assertEqual(r['weight'],1)
 def test_invalid_edge_weight_safe(self):self.assertEqual(edge('c',{'from':'a','to':'b','type':'related','weight':float('nan')})['weight'],1)
 def test_project_does_not_mutate_p0_state(self):s=empty('a');before=copy.deepcopy(s);visual_state(s,NOW);self.assertEqual(before,s)
 def test_no_grade_raw_mastery_not_enough(self):s={**empty('a'),'mastery':1,'confidence':1,'state':'mastered'};self.assertEqual(visual_state(s,NOW)['mastery_state'],'unknown')
 def test_brightness_is_category_token_not_mastery(self):s={**empty('a'),'graded_evidence_count':3,'mastery':.81,'state':'learning'};self.assertNotEqual(visual_state(s,NOW)['brightness'],.81)
 def test_confirmed_confusion_is_reminder(self):s={**empty('a'),'graded_evidence_count':3,'state':'learning'};v=visual_state(s,NOW,[{'status':'confirmed'}]);self.assertTrue(v['knowledge_gap']);self.assertEqual(v['risk_flags'][0]['code'],'repeated_confusion')
 def test_model_suspected_confusion_not_gap(self):s=empty('a');self.assertFalse(visual_state(s,NOW,[{'status':'suspected'}])['knowledge_gap'])
 def test_transfer_gap_only_from_measured_p0(self):s={**empty('a'),'graded_evidence_count':3,'state':'learning','transfer':.4};self.assertTrue(visual_state(s,NOW)['knowledge_gap'])
 def test_unknown_transfer_not_gap(self):self.assertFalse(visual_state(empty('a'),NOW)['knowledge_gap'])
 def test_review_due_is_estimate_not_failure(self):s={**empty('a'),'graded_evidence_count':3,'state':'learning','mastery':.8,'stability':1,'last_success_at':(NOW-timedelta(days=7)).isoformat(),'next_review_at':(NOW-timedelta(days=6)).isoformat()};v=visual_state(s,NOW);self.assertTrue(v['risk_flags'][0]['estimated']);self.assertNotIn('失败',v['state_label'])

for name,raw,read,expected in [
 ('unknown',{},False,'unknown'),('reading_only',{},True,'learning'),('introduced',{'state':'introduced'},False,'learning'),
 ('chat_evidence',{'evidence_count':4},False,'learning'),('p0_learning',{'state':'learning','graded_evidence_count':3},False,'learning'),
 ('p0_unstable',{'state':'unstable','graded_evidence_count':3},False,'unstable'),('p0_mastered',{'state':'mastered','graded_evidence_count':8},False,'mastered'),
 ('delayed_stable',{'state':'learning','graded_evidence_count':8,'successful_reviews':1,'retention':.8,'mastery':.8},False,'stable'),
 ('review_not_measured',{'state':'learning','graded_evidence_count':8,'successful_reviews':1,'mastery':.8},False,'learning'),
 ('review_still_weak',{'state':'learning','graded_evidence_count':8,'successful_reviews':1,'retention':.3,'mastery':.8},False,'learning')]:
 def test(self,raw=raw,read=read,expected=expected):self.assertEqual(visual_state({**empty('a'),**raw},NOW,read=read)['mastery_state'],expected)
 setattr(VisualTests,'test_visual_'+name,test)

class ExistingInputTests(UniverseTests):
 # Only this class's distinct methods are collected; inherited tests stay in their original suite.
 def calibration_snapshot(self,kind='independent_mcq',label='state_overestimation',policy='weighted-evidence-v1'):
  payload={'versions':{policy:{'atoms':{'a0':{'3':{kind:{'classification':label}}}}}}}
  with self.store.connect() as db:db.execute('INSERT INTO calibration_snapshots VALUES(?,?,?,?,?,?,?,?,?)',('p7-calibration','owner','course',self.cid,'all-separated','calibration-v1',json.dumps(payload),0,NOW.isoformat()))
 def test_existing_calibration_snapshot_readonly(self):self.calibration_snapshot();before=snapshot(self.store);r=self.detail();self.assertEqual(r['calibration_reference']['classification'],'state_overestimation');self.assertEqual(before,snapshot(self.store))
 def test_llm_calibration_not_used_for_star(self):self.calibration_snapshot('llm_rubric');self.assertIsNone(self.detail()['calibration_reference'])
 def test_calibration_different_policy_not_mixed(self):self.calibration_snapshot(policy='foreign-policy');self.assertIsNone(self.detail()['calibration_reference'])
 def test_insufficient_calibration_not_inferred(self):self.calibration_snapshot(label='insufficient_future_evidence');self.assertIsNone(self.detail()['calibration_reference'])
 def test_unknown_calibration_label_not_claimed_aligned(self):self.calibration_snapshot(label='unexpected');self.assertIsNone(self.detail()['calibration_reference'])
 def test_actual_current_learning_position(self):grade(self.store,self.c,'a0');r=self.adapter.all('owner')['current_exploration'];self.assertEqual(r['star_name'],'矩阵');self.assertEqual(r['chapter_id'],self.c['sections'][0]['id'])
 def test_exploration_does_not_become_current_learning_position(self):before=self.adapter.all('owner')['current_exploration'];self.detail('a2');self.assertEqual(before,self.adapter.all('owner')['current_exploration'])
 def test_large_search_star_returns_its_window(self):self.large();self.assertEqual(self.adapter.detail('owner',star_id(self.cid,'big404'))['window_offset'],400)
 def test_course_progress_matches_existing_course_card(self):grade(self.store,self.c,'a0');self.store.learning_event('owner',self.cid,['a0'],'read');r=self.adapter.all('owner')['galaxies'][0];self.assertEqual(r['progress'],next(c['progress'] for c in self.store.managed_courses('owner') if c['id']==self.cid))
 def test_path_contains_actual_names(self):grade(self.store,self.c,'a0');self.assertEqual(self.adapter.course('owner',self.cid)['explored_path'][0]['name'],'矩阵')
 def test_real_growth_goal_context_is_readonly(self):
  from growth_fixture import GrowthModel
  c=personal_course(self.store);model=GrowthModel();svc,gid=model.growth_goal(self.store);svc.generate('owner',gid,model);task=svc.roadmap('owner',gid)['roadmap']['tasks'][0];svc.task_action('owner',gid,task['id'],'start');before=snapshot(self.store);r=self.adapter.course('owner',c['id']);self.assertTrue(r['goal_context']);self.assertEqual(r['goal_context'][0]['goal_id'],gid);self.assertEqual(before,snapshot(self.store))
# Reuse setup/helpers without re-running the original test cases.
for _name in list(UniverseTests.__dict__):
 if _name.startswith('test_'):setattr(ExistingInputTests,_name,None)
