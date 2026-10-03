"""P6.5 quality guards and shared retry budget, with actual persisted P0–P6 snapshots."""
import copy,hashlib,json,unittest
from pathlib import Path
from mindos.tutor.quality import TutorQualityController,QualityTutorService
from mindos.tutor.quality.depth_checker import DepthChecker
from mindos.tutor.quality.repetition_checker import RepetitionChecker
from mindos.tutor.quality.alignment_checker import AlignmentChecker
from mindos.tutor.quality.confidence_checker import ConfidenceChecker
from mindos.tutor.quality.integration import QualityControlledModel
from mindos.tutor.quality.quality_controller import POLICY
from mindos.tutor.storage import TutorMemoryStore
import test_tutor_p6 as fixture


def context():
 return {'course':{'title':'Transformer原理','learner_level':'零基础'},'current_context':{'knowledge_title':'KV Cache','section_title':'Attention机制'},
         'knowledge_atoms':[{'id':'qkv','title':'QKV','knowledge_state':{'understanding':.9,'graded_evidence_count':3}},
                            {'id':'matrix','title':'矩阵','knowledge_state':{'understanding':.9,'graded_evidence_count':4}}]}
def response(content='Attention先匹配需求，再汇总有用的信息。',kind='paragraph'):
 return {'blocks':[{'type':kind,'content':content}]}

class QualityChecks(unittest.TestCase):
 def setUp(self):self.ctx=context();self.s={'name':'direct_explanation'};self.a={'allow_formulas':False,'allowed_depth':'conceptual'}
 def depth(self,r,**kw):return DepthChecker().check(r,self.ctx,self.s,kw.get('message','解释Attention机制'),kw.get('action',self.a))
 def repetition(self,r,history=None,message='解释新的机制',**kw):return RepetitionChecker().check(r,self.ctx,kw.get('strategy',self.s),history or [],message,kw.get('limit',5))
 def confidence(self,r,message='基础概念',search=None):return ConfidenceChecker().check(r,self.ctx,self.s,message,search)
 def alignment(self,r,message='为什么Attention快'):return AlignmentChecker().check(r,self.ctx,self.s,message)
 def test_beginner_intuition_allowed(self):self.assertFalse(self.depth(response())['too_deep'])
 def test_beginner_formula_rejected(self):self.assertTrue(self.depth(response('Q × K = score','formula'))['too_deep'])
 def test_formula_hidden_in_paragraph_rejected(self):self.assertTrue(self.depth(response(r'先算 \frac{QK}{d}'))['too_deep'])
 def test_intermediate_example_level_two(self):self.assertEqual(self.depth(response('用检索书籍解释需求匹配。','example'))['response_depth'],'level_2')
 def test_advanced_formula_allowed_by_atie(self):self.assertFalse(self.depth(response('QK/d','formula'),action={'allow_formulas':True,'allowed_depth':'detailed'})['too_deep'])
 def test_advanced_code_allowed_by_atie(self):self.assertFalse(self.depth(response('score = q @ k.T','code'),action={'allow_formulas':True,'allowed_depth':'detailed'})['too_deep'])
 def test_introductory_ceiling_even_high_math(self):self.assertTrue(self.depth(response('QK/d','formula'),action={'allow_formulas':True,'allowed_depth':'introductory'})['too_deep'])
 def test_no_formula_from_advanced_course_title(self):self.ctx['course']['learner_level']='高级';self.assertTrue(self.depth(response('QK/d','formula'))['too_deep'])
 def test_known_matrix_definition_too_basic(self):self.assertTrue(self.depth(response('矩阵是指按行列排列的数。'*20),message='为什么Attention要做匹配')['too_basic'])
 def test_explicit_definition_can_be_short(self):self.assertFalse(self.depth(response('矩阵是指按行列排列的数。'*20),message='矩阵是什么')['too_basic'])
 def test_review_known_basics_allowed(self):self.assertFalse(self.depth(response('矩阵是指按行列排列的数。'*20),message='再解释一下矩阵为什么有用')['too_basic'])
 def test_unknown_basics_not_skipped(self):self.ctx['knowledge_atoms'][1]['knowledge_state']['graded_evidence_count']=0;self.assertFalse(self.depth(response('矩阵是指按行列排列的数。'*20),message='为什么Attention需要矩阵')['too_basic'])
 def test_model_confidence_not_mastery(self):self.ctx['knowledge_atoms'][1]['knowledge_state']={'confidence':1,'understanding':.99,'graded_evidence_count':0};self.assertFalse(self.depth(response('矩阵是指按行列排列的数。'*20),message='为什么矩阵有用')['too_basic'])
 def test_reason_after_brief_recap_allowed(self):self.assertFalse(self.depth(response('矩阵是指数的排列。因为Attention需要同时匹配多个需求，所以用矩阵表示。'),message='为什么Attention用矩阵')['too_basic'])
 def test_duplicate_recent_answer_rejected(self):r=response('Attention通过查询匹配键，再按权重汇总值。'*15);self.assertTrue(self.repetition(r,[{'role':'assistant','content':r['blocks'][0]['content']}])['duplicate'])
 def test_near_duplicate_rejected(self):r=response('Attention通过查询匹配键，再按权重汇总值。'*15);self.assertTrue(self.repetition(r,[{'role':'assistant','content':r['blocks'][0]['content']+'。'}])['duplicate'])
 def test_short_recap_not_duplicate(self):self.assertFalse(self.repetition(response(),[{'role':'assistant','content':response()['blocks'][0]['content']}])['duplicate'])
 def test_user_message_not_history_answer(self):r=response('Attention通过查询匹配键，再按权重汇总值。'*15);self.assertFalse(self.repetition(r,[{'role':'user','content':r['blocks'][0]['content']}])['duplicate'])
 def test_only_recent_five_rounds(self):r=response('Attention通过查询匹配键，再按权重汇总值。'*15);h=[{'role':'assistant','content':r['blocks'][0]['content']}]+[{'role':'assistant','content':'完全不同的例子'+str(i)} for i in range(5)];self.assertFalse(self.repetition(r,h)['duplicate'])
 def test_explicit_review_not_blocked(self):r=response('Attention通过查询匹配键，再按权重汇总值。'*15);self.assertFalse(self.repetition(r,[{'role':'assistant','content':r['blocks'][0]['content']}],message='请复习这个机制')['duplicate'])
 def test_rephrase_not_blocked(self):r=response('Attention通过查询匹配键，再按权重汇总值。'*15);self.assertFalse(self.repetition(r,[{'role':'assistant','content':r['blocks'][0]['content']}],message='换一种说法')['duplicate'])
 def test_remediation_not_blocked(self):r=response('Attention通过查询匹配键，再按权重汇总值。'*15);self.assertFalse(self.repetition(r,[{'role':'assistant','content':r['blocks'][0]['content']}],message='我不理解Attention')['duplicate'])
 def test_known_qkv_long_definition_not_repeated(self):self.assertTrue(self.repetition(response('QKV表示查询键和值，各自有不同作用。'*20),message='为什么Attention需要QK匹配')['duplicate'])
 def test_socratic_necessary_prompt_not_duplicate(self):r=response('Attention通过查询匹配键，再按权重汇总值。'*15);self.assertFalse(self.repetition(r,[{'role':'assistant','content':r['blocks'][0]['content']}],strategy={'name':'socratic'})['duplicate'])
 def test_goal_related_answer_allowed(self):self.assertTrue(self.alignment(response('KV Cache保存已有键和值，避免重复计算。'*20))['aligned'])
 def test_brief_related_detour_allowed(self):self.assertTrue(self.alignment(response('Transformer可以并行处理训练中的多个位置，RNN按序处理。KV Cache则与逐步生成时避免重复计算有关。'))['aligned'])
 def test_long_irrelevant_answer_rejected(self):self.assertFalse(self.alignment(response('今天我们讲烘焙蛋糕，要先准备面粉与糖，然后放入烤箱。'*20))['aligned'])
 def test_long_adjacent_topic_must_return_to_target(self):self.assertFalse(self.alignment(response('Attention研究历史与模型发展的背景介绍。'*50),message='Transformer的发展有哪些阶段')['aligned'])
 def test_return_to_target_resolves_detour(self):self.assertTrue(self.alignment(response('Attention研究历史与模型发展的背景介绍。'*50+'回到KV Cache，它用于避免重复计算。'),message='Transformer的发展有哪些阶段')['aligned'])
 def test_question_named_topic_can_be_answered(self):self.assertTrue(self.alignment(response('RNN按序处理时间步，适合流式的状态更新。'*20),message='RNN有哪些特点')['aligned'])
 def test_stable_math_no_search_needed(self):self.assertTrue(self.confidence(response('点积用于比较两个向量的方向关系。'))['approved'])
 def test_unknown_paper_requires_uncertainty(self):self.assertFalse(self.confidence(response('一切细节都已经确认。'),message='未知论文ABC有哪些实验')['approved'])
 def test_unknown_paper_conservative_answer_allowed(self):self.assertTrue(self.confidence(response('我无法确认这篇论文的细节。基于稳定知识，Attention通过匹配来加权信息。'),message='论文ABC有哪些实验')['approved'])
 def test_disclaimer_does_not_license_fake_result(self):self.assertFalse(self.confidence(response('我无法确认，但这篇论文证明效率提升98%。'),message='论文ABC有哪些实验')['approved'])
 def test_fabricated_link_rejected(self):self.assertFalse(self.confidence(response('参考 https://fake.example/paper'))['approved'])
 def test_actual_returned_link_allowed(self):search={'status':'ok','sources':[{'url':'https://example.org/paper','description':'公开摘要'}]};self.assertTrue(self.confidence(response('来源 https://example.org/paper'),search=search)['approved'])
 def test_failed_search_not_source(self):search={'status':'failed','sources':[{'url':'https://example.org/paper'}]};self.assertFalse(self.confidence(response('来源 https://example.org/paper'),search=search)['approved'])
 def test_title_snippet_not_fulltext(self):self.assertFalse(self.confidence(response('我已经阅读全文并核验这篇论文。'),message='解释论文')['approved'])
 def test_actual_snippet_can_be_reported_as_snippet(self):self.assertTrue(self.confidence(response('这里只取得标题和摘要，未阅读全文。'),message='最新论文',search={'status':'ok','sources':[{'url':'https://example.org','description':'摘要'}]})['approved'])
 def test_no_numeric_fact_score(self):self.assertNotIsInstance(self.confidence(response())['confidence'],(int,float))
 def test_uncertain_caveat_does_not_license_percent_number(self):self.assertFalse(self.confidence(response('我无法确认，但第三个实验提高97%。'),message='未知论文的实验结果')['approved'])
 def test_returned_snippet_claim_preserved(self):self.assertTrue(self.confidence(response('这篇论文提出匹配方法。这里只取得短摘要。'),message='最新论文',search={'status':'ok','sources':[{'description':'这篇论文提出匹配方法。','url':'https://example.org'}]})['approved'])
 def test_snippet_does_not_license_new_version_number(self):self.assertFalse(self.confidence(response('当前软件版本是99.3。'),message='最新软件版本',search={'status':'ok','sources':[{'description':'介绍软件功能。','url':'https://example.org'}]})['approved'])
 def test_user_link_can_be_repeated_without_claiming_read(self):self.assertTrue(self.confidence(response('你给的链接是 https://example.org/page'),message='解释这个链接 https://example.org/page')['approved'])
 def test_user_link_not_fact_authority(self):self.assertFalse(self.confidence(response('该论文证明准确率提高99%。'),message='论文 https://example.org/page 的结果')['approved'])
 def test_controller_returns_original_only_if_approved(self):r=response();d=TutorQualityController().evaluate(r,self.ctx,self.s,[],action=self.a);self.assertTrue(d['approved']);self.assertIs(d['final_response'],r)
 def test_controller_orders_adjustments(self):d=TutorQualityController().evaluate(response('Q × K = score','formula'),self.ctx,self.s,[],action=self.a);self.assertEqual(d['quality_flags'],['too_deep']);self.assertIsNone(d['final_response'])
 def test_disabled_checker_only_policy(self):policy=copy.deepcopy(POLICY);policy['confidence']['enabled']=False;d=TutorQualityController(policy).evaluate(response('https://fake.example'),self.ctx,self.s,[],action=self.a);self.assertTrue(d['approved'])
 def test_policy_cannot_increase_retry_budget(self):policy=copy.deepcopy(POLICY);policy['max_retry']=2;self.assertRaises(ValueError,TutorQualityController,policy)
 def test_policy_history_bounded(self):policy=copy.deepcopy(POLICY);policy['max_history_context']=100;self.assertRaises(ValueError,TutorQualityController,policy)
 def test_no_mutations_of_context_strategy_history(self):r=response();h=[];before=copy.deepcopy((r,self.ctx,self.s,h,self.a));TutorQualityController().evaluate(r,self.ctx,self.s,h,action=self.a);self.assertEqual(before,(r,self.ctx,self.s,h,self.a))

class QualityIntegration(unittest.TestCase):
 setUp=fixture.P6Tests.setUp
 tearDown=fixture.P6Tests.tearDown
 snapshot=fixture.P6Tests.snapshot
 def chat(self,message='什么是基础概念？',**kw):return QualityTutorService(self.store).chat('owner',{'message':message,'context_id':self.cid,**kw},self.model,lambda mode:self.search)
 def meta(self):return QualityTutorService(self.store).debug('owner',self.cid)['responses']
 def test_approved_saved_with_minimal_meta(self):r=self.chat();self.assertTrue(r['saved']);m=self.meta()[0];self.assertTrue(m['approved']);self.assertEqual(set(m),{'strategy','quality_flags','retry_count','approved','created_at'})
 def test_learning_state_unchanged_by_approved_quality(self):before=self.snapshot();self.chat();self.assertEqual(before,self.snapshot())
 def bad(self,p,v):return {**v,'blocks':[{'type':'paragraph','content':'今天我们讲烘焙蛋糕，准备面粉与糖，放入烤箱。'*20}]}
 def test_quality_fails_once_then_repairs(self):self.model.transform=lambda p,v:self.bad(p,v) if len(self.model.calls)==1 else v;r=self.chat();self.assertTrue(r['saved']);self.assertEqual(len(self.model.calls),2);self.assertEqual(self.meta()[0]['quality_flags'],['goal_drift']);self.assertEqual(self.meta()[0]['retry_count'],1)
 def test_repair_guidance_preserves_original_question(self):self.model.transform=lambda p,v:self.bad(p,v) if len(self.model.calls)==1 else v;self.chat('什么是基础概念？');self.assertEqual(self.model.calls[0]['message'],self.model.calls[1]['message']);self.assertEqual(self.model.calls[0]['context'],self.model.calls[1]['context']);self.assertIn('goal_drift',self.model.calls[1]['quality_guidance']['repair_flags'])
 def test_second_failure_unsaved_conservative(self):self.model.transform=self.bad;r=self.chat();self.assertTrue(r['fallback']);self.assertFalse(r['saved']);self.assertIn('无法确认',r['answer']);self.assertEqual(len(self.model.calls),2);self.assertFalse(self.meta()[0]['approved']);self.assertEqual(TutorMemoryStore(self.store).history('owner',self.cid)['messages'],[])
 def test_failed_quality_never_changes_learning(self):before=self.snapshot();self.model.transform=self.bad;self.chat();self.assertEqual(before,self.snapshot())
 def test_schema_and_quality_share_retry_budget(self):self.model.transform=lambda p,v:{'invalid':True} if len(self.model.calls)==1 else self.bad(p,v);r=self.chat();self.assertTrue(r['fallback']);self.assertEqual(len(self.model.calls),2);self.assertEqual(self.meta()[0]['quality_flags'],['schema_or_scope','goal_drift'])
 def test_exception_shares_budget_and_no_private_error_saved(self):self.model.transform=lambda p,v:(_ for _ in ()).throw(TimeoutError('PRIVATE_SENTINEL'));r=self.chat();self.assertEqual(len(self.model.calls),2);self.assertNotIn('PRIVATE_SENTINEL',json.dumps(self.meta()));self.assertNotIn('PRIVATE_SENTINEL',json.dumps(self.model.logs));self.assertTrue(r['fallback'])
 def test_quality_rejected_memory_not_written(self):self.model.transform=lambda p,v:{**self.bad(p,v),'memories':[{'memory_type':'preference','content':'讲例子','supporting_quote':p['message']}]};self.chat('我喜欢先讲例子');self.assertEqual(self.store_count('tutor_memories'),0)
 def store_count(self,t):
  with self.store.connect() as db:return db.execute('SELECT count(*) FROM '+t).fetchone()[0]
 def test_no_quality_observation_inference(self):self.model.transform=self.bad;self.chat();self.assertEqual(self.store_count('tutor_observations'),0)
 def test_duplicate_request_no_extra_model_or_meta(self):self.chat(request_id='duplicate');m=self.meta();self.chat(request_id='duplicate');self.assertEqual(len(self.model.calls),1);self.assertEqual(m,self.meta())
 def test_social_no_quality_or_meta(self):self.chat('谢谢！');self.assertEqual(self.model.calls,[]);self.assertEqual(self.meta(),[])
 def test_foreign_owner_cannot_read_quality(self):self.chat();self.assertRaises(ValueError,QualityTutorService(self.store).debug,'stranger',self.cid)
 def test_cross_course_quality_isolated(self):self.chat();self.assertEqual(QualityTutorService(self.store).debug('owner',self.second['id'])['responses'],[])
 def test_deleted_course_debug_denied(self):self.chat();self.store.recycle_course('owner',self.cid);self.assertRaises(ValueError,QualityTutorService(self.store).debug,'owner',self.cid)
 def test_purge_cascades_quality_records(self):self.chat();self.store.recycle_course('owner',self.cid);self.store.purge_course('owner',self.cid,self.course['title']);self.assertEqual(self.store_count('tutor_response_meta'),0)
 def test_copied_course_no_quality_history(self):self.chat();c=self.store.copy_course('owner',self.cid);self.assertEqual(QualityTutorService(self.store).debug('owner',c['id'])['responses'],[])
 def test_safe_metadata_no_raw_output_context_or_thought(self):self.chat();m=json.dumps(self.meta());self.assertNotIn('knowledge_atoms',m);self.assertNotIn('chain_of_thought',m);self.assertNotIn('这是',m);self.assertNotIn('confidence',m)
 def test_history_fetch_same_atom_course_bounded(self):self.chat();adapter=QualityControlledModel(self.store,'owner',self.model);ctx=self.model.calls[-1]['context'];self.assertEqual(len(adapter.history(ctx)),1);ctx['current_context']['knowledge_atom_id']='other';self.assertEqual(len(adapter.history(ctx)),1);ctx['course']['id']=self.second['id'];self.assertEqual(adapter.history(ctx),[])
 def test_no_quality_fields_public_response(self):r=self.chat();self.assertNotIn('quality_flags',r);self.assertNotIn('quality_meta',r);self.assertNotIn('quality_guidance',r)
 def test_no_extra_judge_calls(self):self.chat();self.assertEqual(len(self.model.calls),1)
 def test_adapter_refuses_third_generation(self):
  self.chat();p=self.model.calls[0];adapter=QualityControlledModel(self.store,'owner',self.model);adapter.attempts=2
  with self.assertRaisesRegex(ValueError,'RETRY_BUDGET_EXHAUSTED'):adapter.tutor_json(p)
 def test_all_p0_p6_files_frozen(self):
  root=Path(__file__).resolve().parents[1];manifest=json.loads((root/'docs/learning-loop-p65-frozen.json').read_text());self.assertGreater(len(manifest['files']),41)
  for name,expected in manifest['files'].items():self.assertEqual(hashlib.sha256((root/name).read_bytes()).hexdigest(),expected,name)
