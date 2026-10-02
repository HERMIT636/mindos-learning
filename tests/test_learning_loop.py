"""Actual scored evidence, targeted misconceptions, graph repair, time and return."""
import json,tempfile,unittest
from pathlib import Path
from datetime import datetime,timezone,timedelta
from unittest.mock import patch
from mindos.storage import Storage
from mindos.learning.service import LearningLoopService
from mindos.learning.state import KnowledgeStateEngine,ForgettingService
from mindos.learning.evidence import append
from mindos.learning.misconception import MisconceptionEngine
from mindos.learning.decision import PrerequisiteRepairEngine
from mindos.learning.policy import POLICY,iso

class LoopTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.path=Path(self.temp.name)/'db.sqlite3';self.store=Storage(self.path)
  draft=self.store.save_draft('owner','Transformer','逐步理解','',{'sections':[{'title':'Attention与QKV','objective':'理解三者角色'},{'title':'Multi Head','objective':'理解多头结构'},{'title':'位置编码','objective':'理解位置'}]},[])
  self.course=self.store.confirm_draft('owner',draft['id'],1);self.cid=self.course['id'];self.loop=LearningLoopService(self.store);self.at=datetime(2026,10,2,1,tzinfo=timezone.utc)
  atoms=[{'id':a,'section':s,'title':name,'type':'mechanism','summary':'用查询与键比较，再按相关程度取值。','why':'建立直觉','depth':2} for a,s,name in [('attention',1,'Attention'),('qkv',1,'QKV'),('matrix',1,'Matrix'),('multi',2,'Multi Head'),('position',3,'位置编码')]]
  self.store.save_graph('owner',self.cid,{'atoms':atoms,'edges':[{'from':a,'to':'multi','type':'prerequisite'} for a in ['attention','qkv','matrix']]})
  for n in [1,2,3]:
   self.store.save_lesson('owner',self.cid,self.course['sections'][n-1]['id'],'本节基础讲解')
   if n<3:self.store.advance('owner',self.cid,n)
 def tearDown(self):self.temp.cleanup()
 def grade(self,atom,answer='a',kind='application',at=None,purpose='chapter_quiz',confidence='high',hint=False,code=False,session=''):
  section=self.store.atom('owner',self.cid,atom)['section'];q={'prompt':'请选择符合这个知识点的正确表述。','choices':{'a':'正确角色','b':'交换角色','c':'另一表述','d':'其他条件'},'atom_ids':[atom],'assessment_type':kind}
  a={'answer':'a','explanation':'查询代表需要查找的信息；键用于匹配信息。'}
  if code:a['misconceptions']={'b':{'code':'QK_ROLE_CONFUSION','description':'把查询和键的角色反过来了'}}
  quiz=self.store.create_quiz('owner',self.cid,self.course['sections'][section-1]['id'],[q],[a])
  with self.store.connect() as db:db.execute('UPDATE quizzes SET assessment_kind=?,scope=?,target_atom_id=?,loop_session_id=? WHERE id=?',(purpose,'atom',atom,session,quiz['id']))
  with patch('mindos.storage.now',return_value=iso(at or self.at)):
   self.store.submit_quiz('owner',self.cid,quiz['id'],[answer],[confidence],[hint])
  return quiz['id']
 def state(self,atom,at=None):return self.loop.snapshot('owner',self.cid,at or self.at)['states'][atom]
 def test_once_correct_and_chat_do_not_confirm_mastery(self):
  self.grade('qkv',kind='concept');s=self.state('qkv');self.assertNotEqual(s['state'],'mastered');self.assertLess(s['confidence'],.3);self.assertIsNone(s['transfer']);self.assertIsNone(s['retention'])
  with self.store.connect() as db:self.loop.signal(db,'owner',self.cid,None,['qkv'],'tutor_interaction','chat:1');self.loop.signal(db,'owner',self.cid,None,['qkv'],'self_explanation','chat:2')
  after=self.state('qkv');self.assertEqual(s['mastery'],after['mastery']);self.assertEqual(s['confidence'],after['confidence'])
 def test_hint_and_reported_confidence_are_recorded_and_cannot_be_cleared(self):
  q={'prompt':'提示使用的检测题目是什么？','choices':dict(a='正确',b='错误',c='其它',d='无关'),'atom_ids':['qkv'],'assessment_type':'concept'}
  quiz=self.store.create_quiz('owner',self.cid,self.course['sections'][0]['id'],[q],[{'answer':'a','explanation':'已显示解释'}]);self.loop.hint('owner',self.cid,quiz['id'],0)
  self.store.submit_quiz('owner',self.cid,quiz['id'],['a'],['low'],[False],[12000])
  with self.store.connect() as db:e=db.execute("SELECT * FROM learning_evidence WHERE evidence_type='quiz_answer'").fetchone()
  self.assertEqual((e['hint_used'],e['confidence'],e['response_time_ms']),(1,'low',12000));self.assertLess(self.state('qkv')['confidence'],.1)
 def test_confidence_grows_with_independent_evidence_transfer_is_separate(self):
  self.grade('qkv',kind='concept');low=self.state('qkv')['confidence']
  for kind in ['concept','application','transfer','concept','application']:self.grade('qkv',kind=kind,purpose='transfer' if kind=='transfer' else 'chapter_quiz')
  s=self.state('qkv');self.assertGreater(s['confidence'],low);self.assertGreater(s['transfer'],.5);self.assertIsNone(s['retention'])
 def test_misconception_suspected_confirmed_weakening_resolved(self):
  self.grade('qkv','b',code=True);m=self.loop.snapshot('owner',self.cid,self.at)['misconceptions'][0];self.assertEqual(m['status'],'suspected')
  self.grade('qkv','b',code=True);self.assertEqual(self.loop.snapshot('owner',self.cid,self.at)['misconceptions'][0]['status'],'confirmed');self.assertLess(self.state('qkv')['application'],.5)
  decision=next(d for d in self.loop.snapshot('owner',self.cid,self.at)['decisions'] if d['reason_code']=='MISCONCEPTION_DETECTED');self.assertEqual(decision['target_atom_id'],'qkv')
  self.grade('qkv','a',code=True);self.assertEqual(self.loop.snapshot('owner',self.cid,self.at)['misconceptions'][0]['status'],'weakening')
  self.grade('qkv','a',code=True);self.assertFalse(self.loop.snapshot('owner',self.cid,self.at)['misconceptions'])
  with self.store.connect() as db:
   append(db,'owner',self.cid,None,'qkv','self_explanation','ai_tutor','signal','new-ai-candidate',code='QK_ROLE_CONFUSION')
   MisconceptionEngine().update(db,'owner',self.cid,'qkv')
  self.assertFalse(self.loop.snapshot('owner',self.cid,self.at)['misconceptions'])
 def test_prerequisite_gap_short_repair_and_return(self):
  for atom,answer in [('attention','a'),('attention','a'),('matrix','a'),('matrix','a'),('qkv','b'),('qkv','b'),('multi','b'),('multi','b')]:self.grade(atom,answer)
  decision=next(d for d in self.loop.snapshot('owner',self.cid,self.at)['decisions'] if d['reason_code']=='PREREQUISITE_GAP');self.assertEqual(decision['target_atom_id'],'qkv')
  session=self.loop.repair_start('owner',self.cid,'multi',{'section_ordinal':2,'scroll_y':420},self.at);self.assertEqual(session['target_atom_id'],'qkv')
  self.grade('qkv','b',purpose='remediation',session=session['id']);self.assertEqual(self.loop.session('owner',self.cid,'repair',session['id'])['status'],'teaching')
  explanation=self.loop.repair_content('owner',self.cid,session['id']);self.assertTrue(explanation['blocks']);self.assertLess(sum(len(b.get('content','')) for b in explanation['blocks']),POLICY['micro_max_characters'])
  self.grade('qkv','a',purpose='remediation',session=session['id']);finished=self.loop.session('owner',self.cid,'repair',session['id']);self.assertEqual(finished['status'],'completed');self.assertEqual(finished['return_context']['section_ordinal'],2);self.assertEqual(finished['return_context']['scroll_y'],420);self.assertEqual(self.store.course('owner',self.cid)['current_ordinal'],3)
  with self.assertRaises(ValueError):self.loop.repair_start('owner',self.cid,'multi',at=self.at)
 def test_graph_depth_unknown_and_cycle_are_bounded(self):
  atoms=[{'id':str(i),'unlocked':True} for i in range(7)];edges=[{'from':str(i+1),'to':str(i),'type':'prerequisite'} for i in range(6)]+[{'from':'0','to':'6','type':'prerequisite'}]
  states={a['id']:{'graded_evidence_count':0,'mastery':None} for a in atoms}
  result=PrerequisiteRepairEngine().trace('0',atoms,edges,states);self.assertTrue(result['depth_limit_reached']);self.assertFalse(result['weak']);self.assertLessEqual(len(result['visited']),POLICY['max_repair_depth']+1)
 def test_hinted_review_and_wrong_answer_do_not_confirm_independent_memory_or_misconception(self):
  self.grade('qkv','b',code=True,hint=True);self.grade('qkv','b',code=True,hint=True)
  self.assertEqual(self.loop.snapshot('owner',self.cid,self.at)['misconceptions'][0]['status'],'suspected')
  self.grade('qkv',at=self.at+timedelta(days=8),purpose='review',hint=True)
  s=self.state('qkv',self.at+timedelta(days=8));self.assertIsNone(s['retention']);self.assertEqual(s['successful_reviews'],0);self.assertIsNone(s['last_reviewed_at'])
  before=s['next_review_at']
  with self.store.connect() as db:self.loop.signal(db,'owner',self.cid,None,['qkv'],'self_explanation','read-with-no-mastery')
  self.assertEqual(self.state('qkv')['next_review_at'],before)
 def test_deferred_task_does_not_restore_quiz_or_accept_stale_submission(self):
  for _ in range(2):self.grade('qkv','b')
  session=self.loop.repair_start('owner',self.cid,'qkv',at=self.at)
  quiz=self.loop.assessment('owner',self.cid,'qkv','remediation',session_id=session['id'])
  self.assertTrue(self.loop.snapshot('owner',self.cid)['pending_assessments'])
  self.loop.defer('owner',self.cid,'repair',session['id'])
  self.assertFalse(self.loop.snapshot('owner',self.cid)['pending_assessments'])
  with self.assertRaises(ValueError):self.store.submit_quiz('owner',self.cid,quiz['id'],['a']*len(quiz['questions']))
 def test_repair_attempt_limit_and_oversized_content_fallback(self):
  from mindos.adaptive.content_generator import ContentGenerator
  for _ in range(2):self.grade('qkv','b')
  session=self.loop.repair_start('owner',self.cid,'qkv',at=self.at)
  self.grade('qkv','b',purpose='remediation',session=session['id'])
  with patch.object(ContentGenerator,'execute',return_value={'blocks':[{'type':'text','content':'x'*(POLICY['micro_max_characters']+1)}]}):
   content=self.loop.repair_content('owner',self.cid,session['id'],object())
  self.assertTrue(content['fallback']);self.assertLess(len(json.dumps(content)),POLICY['micro_max_characters'])
  self.loop.defer('owner',self.cid,'repair',session['id'])
  for n in range(1,POLICY['max_repair_attempts']):
   s=self.loop.repair_start('owner',self.cid,'qkv',at=self.at+timedelta(minutes=31*n));self.loop.defer('owner',self.cid,'repair',s['id'])
  with self.assertRaises(ValueError):self.loop.repair_start('owner',self.cid,'qkv',at=self.at+timedelta(hours=4))
 def test_returning_targets_complete_once_and_preserve_original_atom_mode(self):
  self.grade('qkv',at=self.at);at=self.at+timedelta(days=8)
  session=self.loop.enter('owner',self.cid,{'section_ordinal':1,'knowledge_atom_id':'qkv','atom_mode':'deep','view':'stars','scroll_y':900},at)
  target=session['targets'][0];self.grade(target,at=at,purpose='returning',session=session['id'])
  pending=self.loop.snapshot('owner',self.cid,at)['returning_session'];self.assertIn(target,pending['completed_targets'])
  with self.assertRaises(ValueError):self.loop.assessment('owner',self.cid,target,'returning',session_id=session['id'])
  self.assertEqual(pending['return_context']['knowledge_atom_id'],'qkv');self.assertEqual(pending['return_context']['atom_mode'],'deep')
 def test_time_projection_does_not_change_stored_state_review_improves_stability(self):
  self.grade('position',kind='concept');s=self.state('position');later=self.at+timedelta(days=14);projected=self.state('position',later)
  self.assertLess(projected['effective_mastery'],s['mastery']);self.assertEqual(projected['mastery'],s['mastery']);self.assertIn('position',[r['atom_id'] for r in self.loop.snapshot('owner',self.cid,later)['review_queue']])
  self.grade('position',kind='concept',at=later,purpose='review');after=self.state('position',later);self.assertIsNotNone(after['retention']);self.assertGreater(after['stability'],s['stability']);self.assertGreater(after['next_review_at'],s['next_review_at'])
  self.grade('position',kind='concept',at=later,purpose='review');self.assertEqual(self.state('position',later)['successful_reviews'],1)
 def test_return_after_eight_days_and_no_duplicate_on_refresh(self):
  self.grade('attention',at=self.at);session=self.loop.enter('owner',self.cid,{'section_ordinal':2},self.at+timedelta(days=8));self.assertEqual(session['status'],'pending');self.assertTrue(2<=len(session['targets'])<=4)
  duplicate=self.loop.enter('owner',self.cid,at=self.at+timedelta(days=8));self.assertEqual(session['id'],duplicate['id'])
  for atom in session['targets']:self.grade(atom,purpose='returning',at=self.at+timedelta(days=8),session=session['id'])
  finished=self.loop.session('owner',self.cid,'returning',session['id']);self.assertEqual(finished['status'],'completed');self.assertEqual(finished['decision']['action'],'continue')
 def test_engine_failure_rolls_back_score_and_evidence_duplicate_submit_rejected(self):
  q={'prompt':'事务测试问题是什么？','choices':dict(a='正确',b='错误',c='其它',d='无关'),'atom_ids':['qkv'],'assessment_type':'concept'}
  quiz=self.store.create_quiz('owner',self.cid,self.course['sections'][0]['id'],[q],[{'answer':'a','explanation':'解释'}])
  with patch.object(KnowledgeStateEngine,'update',side_effect=RuntimeError('simulated storage failure')):
   with self.assertRaises(RuntimeError):self.store.submit_quiz('owner',self.cid,quiz['id'],['a'])
  with self.store.connect() as db:self.assertIsNone(db.execute('SELECT submitted_at FROM quizzes WHERE id=?',(quiz['id'],)).fetchone()[0]);self.assertEqual(db.execute("SELECT COUNT(*) FROM learning_evidence WHERE evidence_type='quiz_answer'").fetchone()[0],0)
  self.store.submit_quiz('owner',self.cid,quiz['id'],['a'])
  with self.assertRaises(ValueError):self.store.submit_quiz('owner',self.cid,quiz['id'],['a'])
 def test_migration_replays_without_inventing_unknown_dimensions_and_only_once(self):
  self.grade('qkv',kind='unknown')
  with self.store.connect() as db:db.execute('DELETE FROM learning_evidence');db.execute('DELETE FROM knowledge_states');db.execute('DELETE FROM learning_migrations')
  migrated=Storage(self.path);state=LearningLoopService(migrated).snapshot('owner',self.cid,self.at)['states']['qkv'];self.assertIsNotNone(state['mastery']);self.assertIsNone(state['understanding']);self.assertIsNone(state['transfer']);self.assertLess(state['confidence'],.3)
  Storage(self.path)
  with migrated.connect() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM learning_evidence').fetchone()[0],1)
 def test_diagnosis_schema_retry_skip_and_actual_quote(self):
  class Broken:
   calls=0
   def analyze_misconception(self,*a,**k):self.calls+=1;return {'confidence':1,'mastery':1}
  broken=Broken();self.assertIsNone(MisconceptionEngine().analyze(broken,{'answer':'我把Q和K搞反了'}));self.assertEqual(broken.calls,2)
  class Good:
   def analyze_misconception(self,*a,**k):return {'misconception_detected':True,'code':'QK_ROLE_CONFUSION','confidence':.99,'reason':'可能反转角色','supporting_evidence':['Q和K搞反了']}
  candidate=MisconceptionEngine().analyze(Good(),{'answer':'我把Q和K搞反了'});self.assertTrue(candidate)
  self.assertIsNone(MisconceptionEngine().analyze(Good(),{'answer':'没有这段话，不能伪造引用'}))
  with self.store.connect() as db:
   for i in range(2):append(db,'owner',self.cid,None,'qkv','self_explanation','ai_tutor','signal',f'ai:{i}',code=candidate['code'],metadata={'misconception_description':candidate['reason']})
   MisconceptionEngine().update(db,'owner',self.cid,'qkv');KnowledgeStateEngine().update(db,'owner',self.cid,'qkv')
  m=self.loop.snapshot('owner',self.cid,self.at)['misconceptions'][0];self.assertEqual(m['status'],'suspected');self.assertIsNone(self.state('qkv')['mastery'])
 def test_cross_course_ownership_soft_delete_restore_copy_and_purge(self):
  self.grade('qkv')
  with self.assertRaises(ValueError):self.loop.snapshot('stranger',self.cid)
  copied=self.store.copy_course('owner',self.cid);self.assertIsNone(LearningLoopService(self.store).snapshot('owner',copied['id'])['states']['qkv']['mastery'])
  self.store.recycle_course('owner',self.cid)
  with self.assertRaises(ValueError):self.loop.snapshot('owner',self.cid)
  self.store.restore_course('owner',self.cid);self.assertIsNotNone(self.state('qkv')['mastery'])
  self.store.recycle_course('owner',self.cid);self.store.purge_course('owner',self.cid,'Transformer')
  with self.store.connect() as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM learning_evidence WHERE course_id=?',(self.cid,)).fetchone()[0],0)
