"""Short current-course diagnosis; priors never become evidence themselves."""
import json
from .personal import InheritedKnowledgePrior,PersonalKnowledgeProfileBuilder
from .canonical import KnowledgeMappingEngine
from .policy import iso,clock
from .final_assessment import novelty
from .calibration import capture_prediction
from .state import empty

class CrossCourseVerification:
 def __init__(self,store):self.store=store
 def start(self,user,cid,pid,model):
  priors=InheritedKnowledgePrior(self.store).list(user,cid)['priors'];prior=next((p for p in priors if p['id']==pid),None)
  if not prior:raise ValueError('历史基础提示已失效，请刷新')
  self.store.atom(user,cid,prior['course_atom_id'],unlocked=True)
  with self.store.connect() as db:
   row=db.execute('SELECT * FROM inherited_knowledge_priors WHERE id=? AND user_id=? AND course_id=?',(pid,user,cid)).fetchone()
   if row['quiz_id']:
    q=db.execute('SELECT * FROM quizzes WHERE id=? AND course_id=?',(row['quiz_id'],cid)).fetchone()
    if q:return {'quiz':self.store._quiz_public(dict(q)),'prior':prior}
  from .service import LearningLoopService
  quiz=LearningLoopService(self.store).assessment(user,cid,prior['course_atom_id'],'diagnostic',model)
  if quiz.get('available') is False:return {'quiz':quiz,'prior':prior}
  with self.store.connect() as db:
   db.execute('BEGIN IMMEDIATE');self.store._manage_owned(db,user,cid)
   active=db.execute("SELECT * FROM inherited_knowledge_priors WHERE id=? AND user_id=? AND course_id=? AND status!='invalidated'",(pid,user,cid)).fetchone()
   if not active:raise ValueError('关联已变化，请刷新')
   other=db.execute("SELECT id FROM inherited_knowledge_priors WHERE user_id=? AND course_id=? AND quiz_id=? AND id!=?",(user,cid,quiz['id'],pid)).fetchone()
   if other:raise ValueError('已有另一份快速验证，请先完成并刷新')
   state=db.execute('SELECT state_json FROM knowledge_states WHERE user_id=? AND course_id=? AND atom_id=?',(user,cid,prior['course_atom_id'])).fetchone()
   capture_prediction(db,user,cid,prior['course_atom_id'],json.loads(state[0]) if state else empty(prior['course_atom_id']),salt=pid)
   # Check both courses' earlier quizzes. Reused text is practice, not strong proof.
   source=json.loads(active['source_courses_json']);earlier=[]
   for r in db.execute('SELECT course_id,questions_json FROM quizzes WHERE course_id IN (SELECT id FROM courses WHERE session_id=?) AND id!=? AND submitted_at IS NOT NULL',(user,quiz['id'])):
    if r['course_id'] in source+[cid]:earlier += [q['prompt'] for q in json.loads(r['questions_json'])]
   raw=db.execute('SELECT * FROM quizzes WHERE id=? AND course_id=? AND submitted_at IS NULL',(quiz['id'],cid)).fetchone()
   if not raw:raise ValueError('检测已提交，请刷新')
   questions=json.loads(raw['questions_json'])
   for q in questions:
    q['cross_course_verification']={'prior_id':pid,'canonical_atom_id':prior['canonical_atom_id']}
    if not novelty('',q['prompt'],earlier)['passed']:q['reused_question']=True
   db.execute('UPDATE quizzes SET questions_json=? WHERE id=?',(json.dumps(questions,ensure_ascii=False),quiz['id']))
   db.execute('UPDATE inherited_knowledge_priors SET quiz_id=? WHERE id=?',(quiz['id'],pid));raw=db.execute('SELECT * FROM quizzes WHERE id=?',(quiz['id'],)).fetchone()
  return {'quiz':self.store._quiz_public(dict(raw)),'prior':prior}
 @staticmethod
 def on_submit(db,user,cid,row):
  priors=db.execute("SELECT * FROM inherited_knowledge_priors WHERE user_id=? AND course_id=? AND quiz_id=? AND status!='invalidated'",(user,cid,row['id'])).fetchall()
  for p in priors:
   verified=db.execute("SELECT 1 FROM course_atom_mappings WHERE id=? AND user_id=? AND status='verified'",(p['mapping_id'],user)).fetchone()
   if not verified:continue
   qs=json.loads(row['questions_json']);hints=json.loads(row['hint_flags_json'])
   independent=not any(hints) and not any(q.get('reused_question') for q in qs)
   passed=independent and row['score']==len(qs)
   failed=independent and row['score']<len(qs)
   status='verified_in_course' if passed else 'conflicted' if failed else 'needs_verification'
   db.execute('UPDATE inherited_knowledge_priors SET status=?,verified_at=?,reason_codes_json=? WHERE id=?',(status,iso(clock()) if passed else None,json.dumps(['PRIOR_VERIFIED' if passed else 'CROSS_COURSE_MISMATCH' if failed else 'PRIOR_NEEDS_VERIFICATION']),p['id']))
