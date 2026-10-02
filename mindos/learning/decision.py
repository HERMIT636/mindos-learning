"""Course graph drives suggestions; decisions never advance a lesson."""
from .policy import POLICY

class PrerequisiteRepairEngine:
 def trace(self,origin,atoms,edges,states):
  allowed={a['id'] for a in atoms if a.get('unlocked',True) and a.get('quality_status')!='deprecated'}
  parents={a:[] for a in allowed}
  for e in edges:
   if e['type']=='prerequisite' and e['from'] in allowed and e['to'] in allowed:parents[e['to']].append(e['from'])
  seen={origin};front=[(origin,0)];weak=[];unknown=[];truncated=False
  while front:
   target,depth=front.pop(0)
   if depth>=POLICY['max_repair_depth']:
    truncated=truncated or bool(parents.get(target));continue
   for parent in parents.get(target,[]):
    if parent in seen:continue
    seen.add(parent);s=states[parent];front.append((parent,depth+1))
    if not s['graded_evidence_count']:unknown.append((parent,depth+1))
    elif s['mastery'] is not None and s['mastery']<POLICY['weak_threshold']:weak.append((parent,depth+1))
  weak.sort(key=lambda v:(states[v[0]]['mastery'],v[1]))
  return {'weak':weak,'unknown':unknown,'depth_limit_reached':truncated,'visited':list(seen)}

class LearningDecisionEngine:
 def decide(self,origin,atoms,edges,states,misconceptions,review_queue):
  s=states[origin];mis=[m for m in misconceptions if m['atom_id']==origin and m['status']=='confirmed']
  if mis:return self.result('remediate',origin,'MISCONCEPTION_DETECTED',0,origin_atom_id=origin,depth=0,codes=[m['code'] for m in mis])
  if s['failed_sessions']>=POLICY['repair_failure_sessions']:
   path=PrerequisiteRepairEngine().trace(origin,atoms,edges,states)
   if path['weak']:
    target,depth=path['weak'][0]
    return self.result('remediate',target,'PREREQUISITE_GAP',0,origin_atom_id=origin,depth=depth,trace=path)
   if path['depth_limit_reached'] and not path['weak']:return self.result('reassess',origin,'REPAIR_DEPTH_LIMIT',1,origin_atom_id=origin,trace=path)
   if path['unknown']:return self.result('reassess',path['unknown'][0][0],'LOW_CONFIDENCE',1,origin_atom_id=origin,trace=path)
   return self.result('remediate',origin,'REPEATED_FAILURE',1,origin_atom_id=origin,depth=0,trace=path)
  queued=next((r for r in review_queue if r['atom_id']==origin),None)
  if queued:return self.result('review',origin,queued['reason_code'],2)
  if s['graded_evidence_count'] and s['confidence']<POLICY['mastered_confidence']:return self.result('reassess',origin,'LOW_CONFIDENCE',3)
  return self.result('continue',origin,'CURRENT_LESSON',4)
 @staticmethod
 def result(action,target,reason,priority,**metadata):return {'action':action,'target_atom_id':target,'reason_code':reason,'priority':priority,'metadata':metadata}
