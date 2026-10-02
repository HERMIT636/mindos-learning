"""Sole writer of multidimensional state; unknown dimensions stay unknown."""
import json,math
from .policy import POLICY,DIMENSION,clock,date,iso
from .evidence import event

def empty(atom):
 return {'knowledge_atom_id':atom,'mastery':None,**{d:None for d in POLICY['dimensions']},'confidence':0.0,'stability':None,
  'evidence_count':0,'graded_evidence_count':0,'last_evidence_at':None,'last_graded_evidence_at':None,'last_independent_success_at':None,'last_success_at':None,'last_reviewed_at':None,
  'next_review_at':None,'successful_reviews':0,'consecutive_errors':0,'failed_sessions':0,'state':'unknown','version':0,'policy_version':POLICY['version']}

class KnowledgeStateEngine:
 def update(self,db,user,cid,atom):
  rows=db.execute('SELECT * FROM learning_evidence WHERE user_id=? AND course_id=? AND atom_id=? ORDER BY created_at,rowid',(user,cid,atom)).fetchall()
  old=db.execute('SELECT state_json,version FROM knowledge_states WHERE user_id=? AND course_id=? AND atom_id=?',(user,cid,atom)).fetchone()
  state=empty(atom);state['evidence_count']=len(rows);sums={d:[0.,0.] for d in POLICY['dimensions']};total=0.;correct=0.;last_test=None;last_session=None;delayed=False;reviews={};sessions={}
  for r in rows:
   state['last_evidence_at']=r['created_at'];meta=json.loads(r['metadata_json']);weight=POLICY['weights'][r['evidence_type']]
   if not weight or r['result'] not in {'correct','wrong'}:continue
   weight*=POLICY['answer_confidence'][r['confidence'] or 'unknown']
   if r['hint_used']:weight*=POLICY['hint_multiplier']
   if meta.get('reused_question') and r['evidence_type']!='review_answer':weight*=POLICY['hint_multiplier']
   ok=r['result']=='correct';sessions.setdefault(meta.get('quiz_id',r['event_key']),[]).append(ok);state['graded_evidence_count']+=1;state['last_graded_evidence_at']=r['created_at'];total+=weight;correct+=weight*ok
   dim='transfer' if r['evidence_type']=='transfer_test' else DIMENSION.get(meta.get('assessment_type'))
   if dim:sums[dim][0]+=weight*ok;sums[dim][1]+=weight
   session=meta.get('quiz_id',r['event_key'])
   if session!=last_session:
    delayed=bool(last_test and (date(r['created_at'])-last_test).total_seconds()>=POLICY['minimum_delay_hours']*3600)
    last_test=date(r['created_at']);last_session=session
   if r['evidence_type']=='review_answer' and delayed:
    reviews.setdefault(session,[]).append((ok,bool(r['hint_used'])))
    if not r['hint_used']:
     sums['retention'][0]+=weight*ok;sums['retention'][1]+=weight;state['last_reviewed_at']=r['created_at']
   if ok:
    state['last_success_at']=r['created_at'];state['consecutive_errors']=0
    if not r['hint_used']:state['last_independent_success_at']=r['created_at']
   else:
    state['consecutive_errors']+=1
  for results in reviews.values():
   if all(ok and not hinted for ok,hinted in results):
    state['successful_reviews']+=1;state['stability']=POLICY['review_intervals_days'][min(state['successful_reviews'],len(POLICY['review_intervals_days'])-1)]
   elif any(not ok for ok,hinted in results):state['stability']=max(POLICY['stability_floor_days'],(state['stability'] or POLICY['review_intervals_days'][0])/2)
  for dim,(success,mass) in sums.items():
   if mass:state[dim]=round((success+POLICY['prior_weight']*POLICY['neutral_prior'])/(mass+POLICY['prior_weight']),4)
  measured={d:state[d] for d in POLICY['dimensions'] if state[d] is not None}
  if total:
   state['mastery']=round(sum(v*POLICY['dimensions'][d] for d,v in measured.items())/sum(POLICY['dimensions'][d] for d in measured),4) if measured else round(correct/total,4)
   coverage=POLICY['confidence_coverage_floor']+(1-POLICY['confidence_coverage_floor'])*len(measured)/len(POLICY['dimensions'])
   state['confidence']=round(total/(total+POLICY['confidence_prior'])*coverage,4)
   state['stability']=state['stability'] or POLICY['review_intervals_days'][0]
   from datetime import timedelta
   basis=state['last_reviewed_at'] or state['last_independent_success_at'] or state['last_graded_evidence_at']
   state['next_review_at']=iso(date(basis)+timedelta(days=state['stability']))
   state['state']='unstable' if state['mastery']<POLICY['weak_threshold'] else 'learning'
   if len(measured)==len(POLICY['dimensions']) and state['graded_evidence_count']>=POLICY['mastered_min_evidence'] and state['confidence']>=POLICY['mastered_confidence'] and min(measured.values())>=POLICY['mastered_threshold']:state['state']='mastered'
  elif rows:state['state']='introduced'
  state['failed_sessions']=0
  for answers in reversed(list(sessions.values())):
   if sum(answers)/len(answers)>=POLICY['weak_threshold']:break
   state['failed_sessions']+=1
  state['version']=(old['version'] if old else 0)+1;state['updated_at']=iso(clock())
  db.execute('INSERT INTO knowledge_states VALUES(?,?,?,?,?,?) ON CONFLICT(user_id,course_id,atom_id) DO UPDATE SET state_json=excluded.state_json,version=excluded.version,updated_at=excluded.updated_at',(user,cid,atom,json.dumps(state,ensure_ascii=False),state['version'],state['updated_at']))
  ids=[r['id'] for r in rows]
  db.execute('INSERT INTO knowledge_state_history(user_id,course_id,atom_id,old_json,new_json,evidence_ids_json,reason_code,created_at) VALUES(?,?,?,?,?,?,?,?)',
   (user,cid,atom,old['state_json'] if old else '{}',json.dumps(state),json.dumps(ids),'EVIDENCE_UPDATED',state['updated_at']))
  event(db,user,cid,'state_changed',{'atom_id':atom,'version':state['version'],'reason_code':'EVIDENCE_UPDATED'})
  if state['next_review_at']:event(db,user,cid,'review_scheduled',{'atom_id':atom,'next_review_at':state['next_review_at']})
  return state

class ForgettingService:
 def project(self,state,at=None):
  at=at or clock();s=dict(state);basis=date(s['last_reviewed_at'] or s.get('last_independent_success_at') or s.get('last_graded_evidence_at') or s['last_success_at'])
  s.update(effective_mastery=s['mastery'],effective_retention=None,forgetting_risk=None)
  if basis and s['stability'] and s['mastery'] is not None:
   elapsed=max(0,(at-basis).total_seconds()/86400);factor=math.exp(-elapsed/s['stability'])
   s['effective_retention']=round((s['retention'] if s['retention'] is not None else s['mastery'])*factor,4)
   s['forgetting_risk']=round(1-factor,4);s['effective_mastery']=round(s['mastery']*factor,4)
   if s['next_review_at'] and date(s['next_review_at'])<=at:s['state']='review_due'
  s['retention_is_estimate']=s['retention'] is None
  return s

class ReviewScheduler:
 def queue(self,atoms,states,at=None):
  at=at or clock();items=[]
  for a in atoms:
   s=states[a['id']]
   if not a.get('unlocked',True) or a.get('quality_status')=='deprecated' or not s['graded_evidence_count']:continue
   due=s['next_review_at'] and date(s['next_review_at'])<=at;risk=s['forgetting_risk']
   if due or (risk is not None and risk>=POLICY['forgetting_risk_threshold']):
    items.append({'atom_id':a['id'],'title':a['title'],'reason_code':'REVIEW_DUE' if due else 'FORGETTING_RISK','reason':'到了回忆检测时间，先试着回答，再按结果复习。' if due else '距上次独立答题已有一段时间，建议检查是否还记得。','priority':0 if due else 1,'minutes':POLICY['review_minutes_per_atom'],'next_review_at':s['next_review_at'],'forgetting_risk':risk})
  return sorted(items,key=lambda x:(x['priority'],x['next_review_at'] or ''))[:POLICY['review_daily_minutes']//POLICY['review_minutes_per_atom']]
