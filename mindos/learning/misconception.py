"""Deterministic option maps first; AI produces only a validated candidate."""
import json,re,secrets,math
from .policy import POLICY,clock,iso
from .evidence import event

CANDIDATE_SCHEMA={'type':'object','additionalProperties':False,'required':['misconception_detected','code','confidence','reason','supporting_evidence'],
 'properties':{'misconception_detected':{'type':'boolean'},'code':{'type':'string','pattern':'^[A-Z][A-Z0-9_]{2,60}$'},'confidence':{'type':'number','minimum':0,'maximum':1},'reason':{'type':'string','minLength':1,'maxLength':400},'supporting_evidence':{'type':'array','minItems':1,'maxItems':4,'items':{'type':'string','minLength':1,'maxLength':400}}}}

class MisconceptionEngine:
 def update(self,db,user,cid,atom):
  rows=db.execute('SELECT * FROM learning_evidence WHERE user_id=? AND course_id=? AND atom_id=? ORDER BY created_at,rowid',(user,cid,atom)).fetchall()
  codes={r['misconception_code'] for r in rows if r['misconception_code']}
  for code in codes:
   relevant=[];high=set();successes=set();description='可能混淆了这个知识点的含义';ai_only=True
   for r in rows:
    meta=json.loads(r['metadata_json'])
    if r['misconception_code']==code:
     relevant.append(r['id']);description=meta.get('misconception_description') or description
     if r['evidence_type'] not in {'tutor_interaction','self_explanation'}:
      if len(successes)>=POLICY['misconception_resolve_successes']:high.clear()
      successes.clear()
      ai_only=False
      if r['confidence']=='high' and not r['hint_used'] and not meta.get('reused_question'):high.add(meta.get('quiz_id',r['event_key']))
    elif r['result']=='correct' and code in meta.get('checked_codes',[]) and not r['hint_used']:
     successes.add(meta.get('quiz_id',r['event_key']))
   success=len(successes)
   status='resolved' if success>=POLICY['misconception_resolve_successes'] else 'weakening' if success else 'confirmed' if not ai_only and len(high)>=POLICY['misconception_confirm_errors'] else 'suspected'
   old=db.execute('SELECT * FROM learning_misconceptions WHERE user_id=? AND course_id=? AND atom_id=? AND code=?',(user,cid,atom,code)).fetchone()
   first=old['first_detected_at'] if old else next(r['created_at'] for r in rows if r['id']==relevant[0]);last=next(r['created_at'] for r in reversed(rows) if r['id'] in relevant)
   confidence=min(POLICY['misconception_confidence_cap'],POLICY['misconception_initial_confidence']+POLICY['misconception_confidence_increment']*len(high)) if not ai_only else POLICY['ai_misconception_confidence_cap']
   db.execute('INSERT INTO learning_misconceptions VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(user_id,course_id,atom_id,code) DO UPDATE SET description=excluded.description,confidence=excluded.confidence,status=excluded.status,last_detected_at=excluded.last_detected_at,evidence_count=excluded.evidence_count,resolved_at=excluded.resolved_at,metadata_json=excluded.metadata_json',
    (old['id'] if old else secrets.token_urlsafe(16),user,cid,atom,code,description,confidence,status,first,last,len(relevant),(old['resolved_at'] if old and old['status']=='resolved' else iso(clock())) if status=='resolved' else None,json.dumps({'evidence_ids':relevant,'ai_only':ai_only,'high_confidence_error_sessions':len(high),'subsequent_targeted_successes':success})))
   if not old or old['status']!=status:event(db,user,cid,'misconception_detected',{'atom_id':atom,'code':code,'status':status})

 def analyze(self,model,payload):
  try:from jsonschema import Draft202012Validator
  except ImportError:
   if hasattr(model,'_diagnostic'):model._diagnostic({'stage':'misconception_diagnosis','failure':'JSON Schema依赖未安装','fallback':'skip_diagnosis'})
   return None
  for attempt in range(2):
   try:
    candidate=model.analyze_misconception(payload,attempt=attempt);Draft202012Validator(CANDIDATE_SCHEMA).validate(candidate)
    if not math.isfinite(candidate['confidence']):raise ValueError('诊断置信度必须有限')
    if any(text not in payload['answer'] for text in candidate['supporting_evidence']):raise ValueError('诊断引用不在实际回答中')
    return candidate if candidate['misconception_detected'] else None
   except Exception as exc:
    if hasattr(model,'_diagnostic'):model._diagnostic({'stage':'misconception_diagnosis','attempt':attempt+1,'failure':str(exc),'fallback':'skip_diagnosis'})
  return None
