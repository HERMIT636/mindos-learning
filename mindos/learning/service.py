"""Course-scoped orchestration over existing courses, graph, quizzes and gateway."""
import json,secrets,os
from datetime import timedelta
from .policy import POLICY,clock,date,iso
from .state import KnowledgeStateEngine,ForgettingService,ReviewScheduler,empty
from .evidence import append,event,quiz_evidence
from .misconception import MisconceptionEngine
from .decision import LearningDecisionEngine

class LearningLoopService:
 def __init__(self,store):self.store=store
 def snapshot(self,user,cid,at=None):
  course=self.store._knowledge_course(user,cid);graph=self.store.graph(user,cid) or {'atoms':[],'edges':[]};at=at or clock()
  atoms=[{**a,'unlocked':a['section']<=course['current_ordinal']} for a in graph['atoms'] if a.get('quality_status')!='deprecated']
  with self.store.connect() as db:
   rows=db.execute('SELECT atom_id,state_json FROM knowledge_states WHERE user_id=? AND course_id=?',(user,cid)).fetchall()
   mis=[dict(r) for r in db.execute("SELECT * FROM learning_misconceptions WHERE user_id=? AND course_id=? AND status!='resolved'",(user,cid))]
   repairs=[dict(r) for r in db.execute("SELECT * FROM repair_sessions WHERE user_id=? AND course_id=? AND status IN ('diagnostic','teaching','checking')",(user,cid))]
   pending=[self.store._quiz_public(dict(r))|{'atom_id':r['target_atom_id'],'session_id':r['loop_session_id']} for r in db.execute("""SELECT * FROM quizzes q WHERE course_id=? AND assessment_kind NOT IN ('chapter_quiz','final_concept','final_application','final_transfer','final_retention') AND submitted_at IS NULL
    AND (loop_session_id='' OR EXISTS(SELECT 1 FROM repair_sessions s WHERE s.id=q.loop_session_id AND s.status IN ('diagnostic','teaching','checking'))
    OR EXISTS(SELECT 1 FROM returning_sessions s WHERE s.id=q.loop_session_id AND s.status='pending')) ORDER BY rowid DESC""",(cid,))]
   returns=[dict(r) for r in db.execute("SELECT * FROM returning_sessions WHERE user_id=? AND course_id=? AND status='pending'",(user,cid))]
   completed={}
   for q in db.execute("SELECT loop_session_id,target_atom_id FROM quizzes WHERE course_id=? AND loop_session_id!='' AND submitted_at IS NOT NULL",(cid,)):
    completed.setdefault(q['loop_session_id'],set()).add(q['target_atom_id'])
   repair_history=[dict(r) for r in db.execute('SELECT origin_atom_id,target_atom_id,started_at FROM repair_sessions WHERE user_id=? AND course_id=? ORDER BY started_at DESC',(user,cid))]
  raw={r['atom_id']:json.loads(r['state_json']) for r in rows};states={a['id']:ForgettingService().project(raw.get(a['id'],empty(a['id'])),at) for a in atoms}
  for m in mis:
   m['metadata']=json.loads(m.pop('metadata_json'))
   if m['status']=='confirmed' and m['atom_id'] in states:states[m['atom_id']]['state']='misconception'
  for repair in repairs:
   if repair['origin_atom_id'] in states and repair['trigger_reason']=='PREREQUISITE_GAP':states[repair['origin_atom_id']]['state']='prerequisite_gap'
  for r in repairs:r['return_context']=json.loads(r.pop('return_context_json'));r['content']=json.loads(r.pop('content_json'))
  for r in returns:r['targets']=json.loads(r.pop('targets_json'));r['completed_targets']=sorted(completed.get(r['id'],set()));r['return_context']=json.loads(r.pop('return_context_json'));r['decision']=json.loads(r.pop('decision_json'))
  unlocked=[a for a in atoms if a['unlocked']];reviews=ReviewScheduler().queue(atoms,states,at)
  decisions=[LearningDecisionEngine().decide(a['id'],atoms,graph['edges'],states,mis,reviews) for a in unlocked]
  for d in decisions:
   if d['action']!='remediate':continue
   past=[r for r in repair_history if r['origin_atom_id']==d['metadata']['origin_atom_id'] and r['target_atom_id']==d['target_atom_id']]
   limited=len(past)>=POLICY['max_repair_attempts'];cooling=bool(past and (at-date(past[0]['started_at'])).total_seconds()<POLICY['repair_cooldown_minutes']*60)
   d['metadata']['repair_available']=not (limited or cooling)
   if limited or cooling:d['metadata']['repair_note']='已多次尝试短时补强，建议回看基础小节或向导师提问。' if limited else '刚进行过补强，请先回看解释，再稍后检测。'
  decisions.sort(key=lambda d:(d['priority'],next(a['section']!=course['current_ordinal'] for a in atoms if a['id']==d.get('metadata',{}).get('origin_atom_id',d['target_atom_id']))))
  return {'states':states,'misconceptions':[m for m in mis if m['atom_id'] in {a['id'] for a in unlocked}], 'review_queue':reviews,
   'decisions':decisions,'active_repair':repairs[0] if repairs else None,'returning_session':returns[0] if returns else None,
   'pending_assessments':pending,'debug_enabled':os.getenv('MINDOS_DEBUG_LEARNING')=='1','policy_version':POLICY['version'],
   'boundary':'多维状态是依据独立题目的规则估计，不是能力认证。未知维度保留未测；聊天、自查和阅读不增加掌握度。记忆风险是时间估计，不会扣改历史成绩。'}

 def explain(self,user,cid,atom):
  self.store.atom(user,cid,atom,unlocked=True);loop=self.snapshot(user,cid)
  with self.store.connect() as db:rows=db.execute('SELECT * FROM learning_evidence WHERE user_id=? AND course_id=? AND atom_id=? ORDER BY created_at DESC,rowid DESC LIMIT 12',(user,cid,atom)).fetchall()
  evidence=[{**dict(r),'metadata':json.loads(r['metadata_json'])} for r in rows]
  for e in evidence:e.pop('metadata_json')
  s=loop['states'][atom];reasons=[]
  if not s['graded_evidence_count']:reasons.append('还没有关联到这个知识点的独立答题记录。')
  else:
   reasons.append(f"已记录 {s['graded_evidence_count']} 条已提交答题证据；有提示的题降低权重，单次答对不能确认已经掌握。")
   if s['application'] is not None and s['application']<POLICY['weak_threshold']:reasons.append('应用或计算题仍需要练习。')
   if s['transfer'] is None:reasons.append('还没有独立迁移题，迁移能力未测。')
   if s['retention'] is None:reasons.append('还没有有效的延迟回忆结果，记忆稳定性未测。')
   if s['forgetting_risk'] is not None and s['forgetting_risk']>=POLICY['forgetting_risk_threshold']:reasons.append('距上次独立回忆已有一段时间，建议复习检测。')
  return {'knowledge_state':s,'evidence':evidence,'reasons':reasons,'misconceptions':[m for m in loop['misconceptions'] if m['atom_id']==atom],'decision':next((d for d in loop['decisions'] if d['target_atom_id']==atom),None),'boundary':loop['boundary']}

 def signal(self,db,user,cid,section,atoms,kind,key,metadata=None):
  for atom in atoms or ['']:
   inserted=append(db,user,cid,section,atom,kind,'ai_tutor' if kind=='tutor_interaction' else 'lesson','introduced' if kind=='lesson_check' else 'signal',key,metadata=metadata)
   if inserted and atom:KnowledgeStateEngine().update(db,user,cid,atom)
  db.execute('INSERT INTO loop_activity VALUES(?,?,?) ON CONFLICT(user_id,course_id) DO UPDATE SET last_active_at=excluded.last_active_at',(user,cid,iso(clock())))

 def section_signal(self,db,user,cid,section,kind,key):
  row=db.execute('SELECT graph_json FROM course_graphs WHERE course_id=?',(cid,)).fetchone()
  ordinal=db.execute('SELECT ordinal FROM sections WHERE id=? AND course_id=?',(section,cid)).fetchone()
  atoms=[a['id'] for a in json.loads(row[0])['atoms'] if ordinal and a['section']==ordinal[0] and a.get('quality_status')!='deprecated'] if row else []
  self.signal(db,user,cid,section,atoms,kind,key)

 def submitted(self,db,row,confidence,hints,times):
  user,cid,touched=quiz_evidence(db,row,confidence,hints,times)
  for atom in touched:
   MisconceptionEngine().update(db,user,cid,atom);KnowledgeStateEngine().update(db,user,cid,atom)
  event(db,user,cid,'review_completed' if row['assessment_kind']=='review' else 'assessment_completed',{'quiz_id':row['id'],'score':row['score']})
  db.execute('INSERT INTO loop_activity VALUES(?,?,?) ON CONFLICT(user_id,course_id) DO UPDATE SET last_active_at=excluded.last_active_at',(user,cid,row['submitted_at']))
  self._finish_session(db,user,cid,row)

 def _finish_session(self,db,user,cid,quiz):
  sid=quiz['loop_session_id']
  if not sid:return
  hints=json.loads(quiz['hint_flags_json']);passed=quiz['score']==len(json.loads(quiz['answers_json'])) and not any(hints)
  repair=db.execute('SELECT * FROM repair_sessions WHERE id=? AND user_id=? AND course_id=?',(sid,user,cid)).fetchone()
  if repair:
   if repair['status']=='diagnostic':
    status='completed' if passed else 'teaching'
   elif repair['status'] in {'teaching','checking'}:status='completed' if passed else 'needs_review'
   else:return
   db.execute('UPDATE repair_sessions SET status=?,completed_at=? WHERE id=?',(status,iso(clock()) if status in {'completed','needs_review'} else None,sid))
   event(db,user,cid,'repair_completed' if status=='completed' else 'repair_checkpoint',{'session_id':sid,'status':status,'return_context':json.loads(repair['return_context_json'])})
  returning=db.execute('SELECT * FROM returning_sessions WHERE id=? AND user_id=? AND course_id=?',(sid,user,cid)).fetchone()
  if returning and returning['status']=='pending':
   targets=json.loads(returning['targets_json']);done=db.execute('SELECT target_atom_id,score,questions_json,hint_flags_json FROM quizzes WHERE loop_session_id=? AND submitted_at IS NOT NULL',(sid,)).fetchall()
   if set(targets)<=set(r['target_atom_id'] for r in done):
    all_passed=all(r['score']==len(json.loads(r['questions_json'])) and not any(json.loads(r['hint_flags_json'])) for r in done)
    needs_repair=any(json.loads(r['state_json']).get('failed_sessions',0)>=POLICY['repair_failure_sessions'] for r in db.execute('SELECT atom_id,state_json FROM knowledge_states WHERE user_id=? AND course_id=?',(user,cid)) if r['atom_id'] in targets)
    decision={'action':'continue' if all_passed else 'remediate' if needs_repair else 'review','reason_code':'RETURNING_AFTER_GAP','target_atom_id':None if all_passed else next((r['target_atom_id'] for r in done if r['score']<len(json.loads(r['questions_json']))),targets[0])}
    db.execute('UPDATE returning_sessions SET status=?,completed_at=?,decision_json=? WHERE id=?',('completed',iso(clock()),json.dumps(decision),sid))
    event(db,user,cid,'returning_completed',{'session_id':sid,'decision':decision})

 def enter(self,user,cid,context=None,at=None):
  course=self.store._knowledge_course(user,cid);at=at or clock();loop=self.snapshot(user,cid,at)
  if loop['returning_session']:return loop['returning_session']
  context=self.return_context(course,context,user)
  with self.store.connect() as db:
   db.execute('BEGIN IMMEDIATE');self.store._manage_owned(db,user,cid)
   active=db.execute("SELECT id FROM returning_sessions WHERE user_id=? AND course_id=? AND status='pending'",(user,cid)).fetchone()
   if active:return self.session(user,cid,'returning',active[0])
   last=db.execute('SELECT last_active_at FROM loop_activity WHERE user_id=? AND course_id=?',(user,cid)).fetchone()
   if not last:last=db.execute("SELECT MAX(at) FROM (SELECT submitted_at AS at FROM quizzes WHERE course_id=? UNION ALL SELECT created_at AS at FROM learning_events WHERE course_id=?)",(cid,cid)).fetchone()
   session=None
   if last and last[0] and (at-date(last[0])).total_seconds()>=POLICY['return_threshold_days']*86400:
    graph=self.store.graph(user,cid) or {'atoms':[],'edges':[]}
    available=[a for a in graph['atoms'] if a['section']<=course['current_ordinal'] and a.get('quality_status')!='deprecated']
    prereqs={e['from'] for e in graph['edges'] if e['type']=='prerequisite' and any(a['id']==e['to'] and a['section']==context['section_ordinal'] for a in available)}
    targets=[a['id'] for a in sorted(available,key=lambda a:(a['id'] not in prereqs,a['section']!=context['section_ordinal']))][:POLICY['return_atom_limit']]
    sid=secrets.token_urlsafe(16);status='pending' if targets else 'unavailable'
    db.execute('INSERT INTO returning_sessions VALUES(?,?,?,?,?,?,?,?,?)',(sid,user,cid,status,iso(at),None,json.dumps(targets),json.dumps(context),'{}'))
    event(db,user,cid,'returning_started',{'session_id':sid,'targets':targets},at)
    session={'id':sid,'status':status,'targets':targets,'return_context':context,'note':'先做几个短回忆检测，再决定继续还是复习。' if targets else '尚无知识索引，建议先回看当前小节；不推断已掌握。'}
   db.execute('INSERT INTO loop_activity VALUES(?,?,?) ON CONFLICT(user_id,course_id) DO UPDATE SET last_active_at=excluded.last_active_at',(user,cid,iso(at)))
  return session

 def return_context(self,course,context=None,user=None):
  context=context or {};ordinal=context.get('section_ordinal',course['current_ordinal']);scroll=context.get('scroll_y',0)
  if type(ordinal) is not int or not 1<=ordinal<=course['current_ordinal'] or type(scroll) not in (int,float) or not 0<=scroll<=100000:raise ValueError('返回学习位置无效')
  atom=context.get('knowledge_atom_id')
  if atom is not None:
   referenced=self.store.atom(user,course['id'],atom,unlocked=True)
   if referenced['section']!=ordinal:raise ValueError('返回知识点与小节不一致')
  return {'course_id':course['id'],'section_ordinal':ordinal,'knowledge_atom_id':atom,'atom_mode':context.get('atom_mode','quick') if context.get('atom_mode','quick') in {'quick','deep'} else 'quick','view':context.get('view','learn') if context.get('view','learn') in {'learn','stars'} else 'learn','scroll_y':scroll}

 def repair_start(self,user,cid,origin,context=None,at=None,*,course_decision=None):
  atom=self.store.atom(user,cid,origin,unlocked=True);loop=self.snapshot(user,cid,at);at=at or clock()
  decision=next((d for d in loop['decisions'] if d.get('metadata',{}).get('origin_atom_id')==origin and d['action']=='remediate'),None)
  if course_decision is not None:decision=course_decision
  if not decision:raise ValueError('当前证据不足以启动补强，先做一次独立检测。')
  if loop['active_repair']:return loop['active_repair']
  course=self.store._knowledge_course(user,cid);context=self.return_context(course,context,user)
  target=decision['target_atom_id'];self.store.atom(user,cid,target,unlocked=True)
  with self.store.connect() as db:
   db.execute('BEGIN IMMEDIATE');self.store._manage_owned(db,user,cid)
   if course_decision is not None:
    row=db.execute("SELECT id,targets_json FROM course_repair_plans WHERE user_id=? AND course_id=? AND status='active'",(user,cid)).fetchone()
    if not row or row['id']!=course_decision['metadata']['course_repair_plan_id'] or not any(t['origin_atom_id']==origin and t['atom_id']==target and t['status']!='completed' for t in json.loads(row['targets_json'])):raise ValueError('终局补强计划已变化，请刷新')
   active=db.execute("SELECT id FROM repair_sessions WHERE user_id=? AND course_id=? AND status IN ('diagnostic','teaching','checking')",(user,cid)).fetchone()
   if active:return self.session(user,cid,'repair',active[0])
   past=db.execute('SELECT started_at FROM repair_sessions WHERE user_id=? AND course_id=? AND origin_atom_id=? AND target_atom_id=? ORDER BY started_at DESC',(user,cid,origin,target)).fetchall()
   if len(past)>=POLICY['max_repair_attempts']:raise ValueError('已多次尝试短时补强，建议回看基础小节或向导师提问。')
   if past and (at-date(past[0][0])).total_seconds()<POLICY['repair_cooldown_minutes']*60:raise ValueError('刚进行过补强，请先回看解释，再稍后检测。')
   sid=secrets.token_urlsafe(16)
   db.execute('INSERT INTO repair_sessions(id,user_id,course_id,origin_atom_id,target_atom_id,trigger_reason,status,depth,started_at,return_context_json) VALUES(?,?,?,?,?,?,?,?,?,?)',(sid,user,cid,origin,target,decision['reason_code'],'diagnostic',decision['metadata']['depth'],iso(at),json.dumps(context)))
   if course_decision is not None:
    targets=json.loads(row['targets_json'])
    for entry in targets:
     if entry['atom_id']==target and entry['origin_atom_id']==origin:entry['repair_session_id']=sid
    db.execute('UPDATE course_repair_plans SET targets_json=? WHERE id=?',(json.dumps(targets),row['id']))
   event(db,user,cid,'repair_started',{'session_id':sid,'decision':decision},at)
  return self.snapshot(user,cid,at)['active_repair']

 def assessment(self,user,cid,atom_id,purpose,model=None,session_id=''):
  if purpose not in {'review','remediation','returning','diagnostic','transfer','lesson_check'}:raise ValueError('检测用途无效')
  atom=self.store.atom(user,cid,atom_id,unlocked=True);course=self.store._knowledge_course(user,cid);section=course['sections'][atom['section']-1];loop=self.snapshot(user,cid)
  if purpose=='remediation':
   session=loop['active_repair']
   if not session or session['id']!=session_id or session['target_atom_id']!=atom_id:raise ValueError('补强检测与当前补强任务不一致')
  if purpose=='returning':
   session=loop['returning_session']
   if not session or session['id']!=session_id or atom_id not in session['targets']:raise ValueError('回忆检测与恢复任务不一致')
   if atom_id in session.get('completed_targets',[]):raise ValueError('这个知识点已完成回忆检测，请检测下一个知识点')
  if purpose not in {'remediation','returning'} and session_id:raise ValueError('检测不能绑定其他任务')
  with self.store.connect() as db:
   pending=db.execute('SELECT * FROM quizzes WHERE course_id=? AND target_atom_id=? AND assessment_kind=? AND loop_session_id=? AND submitted_at IS NULL',(cid,atom_id,purpose,session_id)).fetchone()
   historical=db.execute('SELECT * FROM quizzes WHERE course_id=? AND submitted_at IS NOT NULL ORDER BY submitted_at DESC LIMIT 20',(cid,)).fetchall()
  if pending:return self.store._quiz_public(dict(pending))
  questions=answers=None;fallback=False
  try:
   if not model:raise ValueError('未配置对话模型')
   questions,answers=model.learning_check(course,section,atom,purpose,[m for m in loop['misconceptions'] if m['atom_id']==atom_id])
  except Exception as exc:
   if model and hasattr(model,'_diagnostic'):model._diagnostic({'stage':'learning_check_fallback','purpose':purpose,'failure':str(exc),'fallback':'validated_history_or_unavailable'})
   # Reuse only validated same-course questions already tagged for this atom.
   candidates=[]
   for row in historical:
    for q,a in zip(json.loads(row['questions_json']),json.loads(row['answers_json'])):
     if q.get('atom_ids')==[atom_id] and q.get('assessment_type')!='transfer':candidates.append(({**q,'reused_question':True},a))
   if not candidates or purpose=='transfer':return {'available':False,'note':'暂时无法生成检测题。可以回看解释或返回原小节，稍后再试。'}
   questions,answers=map(list,zip(*candidates[:2]));fallback=True
  sid=secrets.token_urlsafe(16)
  with self.store.connect() as db:
   db.execute('BEGIN IMMEDIATE');self.store._manage_owned(db,user,cid);self.store.atom(user,cid,atom_id,unlocked=True)
   # Serialize concurrent generation and recheck the active task after model latency.
   pending=db.execute('SELECT * FROM quizzes WHERE course_id=? AND target_atom_id=? AND assessment_kind=? AND loop_session_id=? AND submitted_at IS NULL',(cid,atom_id,purpose,session_id)).fetchone()
   if pending:return self.store._quiz_public(dict(pending))
   if session_id:
    table='repair_sessions' if purpose=='remediation' else 'returning_sessions'
    active=db.execute(f'SELECT status FROM {table} WHERE id=? AND user_id=? AND course_id=?',(session_id,user,cid)).fetchone()
    if not active or active[0] not in {'diagnostic','teaching','checking','pending'}:raise ValueError('学习任务已结束，请刷新')
    if purpose=='returning' and db.execute('SELECT 1 FROM quizzes WHERE loop_session_id=? AND target_atom_id=? AND submitted_at IS NOT NULL',(session_id,atom_id)).fetchone():raise ValueError('这个知识点已完成回忆检测，请检测下一个知识点')
   db.execute('INSERT INTO quizzes(id,course_id,section_id,questions_json,answers_json,created_at,scope,target_atom_id,assessment_kind,loop_session_id) VALUES(?,?,?,?,?,?,?,?,?,?)',(sid,cid,section['id'],json.dumps(questions,ensure_ascii=False),json.dumps(answers,ensure_ascii=False),iso(clock()),'atom',atom_id,purpose,session_id))
   row=db.execute('SELECT * FROM quizzes WHERE id=?',(sid,)).fetchone()
  return {**self.store._quiz_public(dict(row)),'available':True,'fallback':fallback,'note':'使用已有题目检查回忆；即时重复不会算作新的延迟记忆证据。' if fallback else ''}

 def repair_content(self,user,cid,sid,model=None):
  loop=self.snapshot(user,cid);session=loop['active_repair']
  if not session or session['id']!=sid:raise ValueError('补强任务不存在')
  if session['status']=='diagnostic':raise ValueError('请先完成短诊断，再按结果补强')
  if session['content']:return session['content']
  course=self.store._knowledge_course(user,cid);atom=self.store.atom(user,cid,session['target_atom_id'],unlocked=True);section=course['sections'][atom['section']-1]
  mis=[m for m in loop['misconceptions'] if m['atom_id']==atom['id']]
  blocks=[{'type':'concept','title':'先补这一个关键点','content':atom['summary']},{'type':'text','content':'请回看这个知识点的一个例子，再做短检测。已有索引内容仅作课程参考，不代表事实认证。'}];package={'blocks':blocks,'fallback':True,'note':'本次使用课程知识索引回顾；暂未取得新的模型讲解。'}
  if model:
   try:
    from ..adaptive.content_generator import ContentGenerator,flatten_blocks
    gen=ContentGenerator(self.store);state,knowledge,scope,action=gen.prepare(user,cid,section,'请用一个简短例子补强当前知识，不展开其他知识',atom['id'],'followup','example')
    scope={**scope,'purpose':'3—10分钟内补强一个知识点','core_atoms':[atom['title']],'related_atoms':[],
     'future_atoms':list(dict.fromkeys(scope['future_atoms']+[a['title'] for a in knowledge['atoms'] if a['id']!=atom['id']]))}
    scope['exposure']=[{'knowledge':atom['title'],'level':3}]+[{'knowledge':name,'level':0} for name in scope['future_atoms']]
    knowledge={**knowledge,'atoms':[atom]}
    action={**action,'core_atoms':[atom['title']],'related_atoms':[],'backtrack_targets':[]}
    payload={'mode':'remediation','course':course['title'],'section_title':section['title'],'knowledge_context':knowledge,'learning_state':state,'teaching_action':action,'teaching_context':scope,'misconceptions':mis,'instruction':'只针对目标的一处误区或缺口，简短解释、一个例子和一个自查，总文字不超过1200字；不生成整章。展示计划forms必须与实际blocks的type一致；以案例文字解释为主时intent=explanation，讲关系或流程时必须提供相应diagram或flow。'}
    generated=gen.execute(model,payload,action,scope,lambda:model.generate_teaching_blocks(payload))
    if len(flatten_blocks(generated['blocks']))>POLICY['micro_max_characters']:raise ValueError('补强内容过长')
    package=generated
   except Exception as exc:
    if hasattr(model,'_diagnostic'):model._diagnostic({'stage':'micro_remediation','failure':str(exc),'fallback':'course_index'})
  with self.store.connect() as db:
   db.execute('BEGIN IMMEDIATE');self.store._manage_owned(db,user,cid)
   changed=db.execute("UPDATE repair_sessions SET content_json=?,status='checking' WHERE id=? AND user_id=? AND course_id=? AND status IN ('teaching','checking')",(json.dumps(package,ensure_ascii=False),sid,user,cid)).rowcount
   if not changed:raise ValueError('补强任务已变化，请刷新')
  return package

 def session(self,user,cid,kind,sid):
  self.store._knowledge_course(user,cid);table='repair_sessions' if kind=='repair' else 'returning_sessions'
  with self.store.connect() as db:row=db.execute(f'SELECT * FROM {table} WHERE id=? AND user_id=? AND course_id=?',(sid,user,cid)).fetchone()
  if not row:raise ValueError('学习任务不存在')
  r=dict(row);r['return_context']=json.loads(r.pop('return_context_json'))
  for field in ('content','targets','decision'):
   if field+'_json' in r:r[field]=json.loads(r.pop(field+'_json'))
  return r

 def defer(self,user,cid,kind,sid):
  self.session(user,cid,kind,sid);table='repair_sessions' if kind=='repair' else 'returning_sessions'
  with self.store.connect() as db:
   db.execute('BEGIN IMMEDIATE');self.store._manage_owned(db,user,cid)
   db.execute(f"UPDATE {table} SET status='deferred',completed_at=? WHERE id=? AND user_id=? AND course_id=? AND status IN ('pending','diagnostic','teaching','checking')",(iso(clock()),sid,user,cid))
   event(db,user,cid,'session_deferred',{'kind':kind,'session_id':sid})
  return self.session(user,cid,kind,sid)

 def hint(self,user,cid,quiz_id,index):
  self.store._knowledge_course(user,cid)
  with self.store.connect() as db:
   db.execute('BEGIN IMMEDIATE');self.store._manage_owned(db,user,cid)
   row=db.execute('SELECT * FROM quizzes WHERE id=? AND course_id=? AND submitted_at IS NULL',(quiz_id,cid)).fetchone()
   if not row:raise ValueError('测试不存在或已提交')
   if row['scope']=='final':
    from .final import validate_submission
    validate_submission(db,user,cid,row)
   answers=json.loads(row['answers_json'])
   if type(index) is not int or not 0<=index<len(answers):raise ValueError('题号无效')
   hints=json.loads(row['hint_flags_json']) or [False]*len(answers);hints[index]=True
   db.execute('UPDATE quizzes SET hint_flags_json=? WHERE id=?',(json.dumps(hints),quiz_id))
   return {'hint':answers[index]['explanation'],'hint_used':True,'note':'已查看解释，这道题会作为有提示的练习记录，不当作独立掌握证明。'}
