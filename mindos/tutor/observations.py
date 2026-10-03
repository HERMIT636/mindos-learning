"""Candidate observations link to P0 detection; never writes evidence or mastery."""
import json
from ..learning.service import LearningLoopService

class TutorObservationService:
    def __init__(self,store):self.store=store
    def _owned(self,db,user,oid):
        row=db.execute('SELECT * FROM tutor_observations WHERE id=? AND user_id=?',(oid,user)).fetchone()
        if not row:raise ValueError('观察建议不存在')
        self.store._manage_owned(db,user,row['course_id']);return dict(row)
    def reconcile(self,user,oid):
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE');o=self._owned(db,user,oid)
            q=db.execute('SELECT * FROM quizzes WHERE id=? AND course_id=? AND target_atom_id=?',(o['quiz_id'],o['course_id'],o['atom_id'])).fetchone() if o['quiz_id'] else None
            if q and q['submitted_at'] and o['status']=='candidate':
                ev=db.execute('SELECT result,hint_used,metadata_json FROM learning_evidence WHERE user_id=? AND course_id=? AND atom_id=?',(user,o['course_id'],o['atom_id'])).fetchall()
                ev=[e for e in ev if json.loads(e['metadata_json']).get('quiz_id')==q['id']]
                independent=bool(ev) and all(not e['hint_used'] and not json.loads(e['metadata_json']).get('reused_question') for e in ev)
                outcome='needs_review' if independent and any(e['result']=='wrong' for e in ev) else 'check_passed' if independent else 'practice_only'
                # Generic check errors cannot certify the tutor's specific misconception description.
                status='verified' if independent and outcome=='needs_review' and o['observation_type']=='possible_gap' else 'dismissed' if independent and outcome=='check_passed' and o['observation_type'] in {'possible_gap','possible_misconception'} else 'candidate'
                v={'quiz_id':q['id'],'independent':independent,'outcome':outcome,'note':'检测结果由原有学习闭环产生；导师描述不是事实认证，也不替代终局或开放评估。'}
                db.execute('UPDATE tutor_observations SET status=?,verification_json=? WHERE id=?',(status,json.dumps(v,ensure_ascii=False),oid))
                o.update(status=status,verification_json=json.dumps(v))
        return o
    def list(self,user,cid):
        self.store._knowledge_course(user,cid)
        with self.store.connect() as db:ids=[r[0] for r in db.execute('SELECT id FROM tutor_observations WHERE user_id=? AND course_id=? ORDER BY created_at DESC,rowid DESC LIMIT 20',(user,cid))]
        result=[]
        for oid in ids:
            o=self.reconcile(user,oid)
            recommendations=[]
            if o['status']=='candidate' and o['observation_type']=='possible_gap':
                with self.store.connect() as db:
                    row=db.execute('SELECT state_json FROM knowledge_states WHERE user_id=? AND course_id=? AND atom_id=?',(user,cid,o['atom_id'])).fetchone()
                    task=db.execute("SELECT t.goal_id FROM growth_tasks t JOIN learning_goals g ON g.id=t.goal_id JOIN growth_roadmaps r ON r.id=t.roadmap_id WHERE t.user_id=? AND t.target_id=? AND t.status='active' AND g.status='active' AND r.status='active' LIMIT 1",(user,cid)).fetchone()
                state=json.loads(row[0]) if row else {}
                if ('应用' in o['description'] or (state.get('understanding') or 0)>=.65 and state.get('application') is not None and state['application']<.6):
                    recommendations.append({'kind':'authentic_assessment','course_id':cid,'atom_id':o['atom_id'],'note':'可以用开放练习检查应用能力；导师观察不替代真实评估。'})
                if task:recommendations.append({'kind':'recommend_replan','goal_id':task['goal_id'],'note':'如果这个困难影响当前目标，可以查看成长路线并主动重新规划。'})
            result.append({k:o[k] for k in ['id','course_id','atom_id','observation_type','description','status','created_at','quiz_id']}|{'recommendations':recommendations,'verification':json.loads(o['verification_json']),'boundary':'导师观察，仅作待验证线索；不直接改变掌握状态。'})
        return {'observations':result}
    def verify(self,user,oid,model):
        o=self.reconcile(user,oid)
        if o['status']!='candidate':return {'observation':self.list(user,o['course_id']),'note':'这条建议已处理。'}
        if o['observation_type'] not in {'possible_gap','possible_misconception','confusion_signal','strong_understanding'}:raise ValueError('讲解偏好不需要知识检测')
        with self.store.connect() as db:
            if db.execute("SELECT 1 FROM authentic_tasks WHERE user_id=? AND course_id=? AND status='created'",(user,o['course_id'])).fetchone() or db.execute("SELECT 1 FROM final_assessment_plans WHERE user_id=? AND course_id=? AND status='active'",(user,o['course_id'])).fetchone():raise ValueError('请先完成当前课程检测，再做导师建议的短检测')
        quiz=LearningLoopService(self.store).assessment(user,o['course_id'],o['atom_id'],'diagnostic',model)
        if quiz.get('available') is False:return {'quiz':quiz,'note':quiz['note']}
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE');self._owned(db,user,oid)
            db.execute("UPDATE tutor_observations SET quiz_id=? WHERE id=? AND status='candidate'",(quiz['id'],oid))
        return {'verification_task':{'id':quiz['id'],'type':'concept_check','status':'pending','source':'p0_diagnostic'},'quiz':quiz,'course_id':o['course_id'],'observation_id':oid,'note':'请独立回答；导师观察不会写入答案、评分或掌握记录。'}
    def dismiss(self,user,oid):
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE');self._owned(db,user,oid);db.execute("UPDATE tutor_observations SET status='dismissed' WHERE id=?",(oid,))
        return {'dismissed':True}
