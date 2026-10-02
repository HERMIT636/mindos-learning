"""Only course-level ordering; all actual repair uses the existing P0 service."""
from .final_assessment import FINAL_POLICY,criticality
from .decision import PrerequisiteRepairEngine

class FinalRemediationPlanner:
    def plan(self,course,graph,states,misconceptions,final_results=None):
        atoms,_,critical=criticality(course,graph);atoms=[{**a,'unlocked':True} for a in atoms];ids={a['id'] for a in atoms};targets=[]
        def add(origin,target,code,priority,verification,depth=0):
            existing=next((t for t in targets if t['atom_id']==target and t['origin_atom_id']==origin),None)
            if existing:
                existing['required_verification']=list(dict.fromkeys(existing['required_verification']+verification))
                if priority<existing['priority']:existing.update(reason_code=code,priority=priority,depth=depth)
                return
            targets.append({'atom_id':target,'origin_atom_id':origin,'reason_code':code,'priority':priority,'required_verification':verification,'depth':depth,'status':'pending'})
        latest={}
        for result in final_results or []:
            if not result['hint_used'] and not result.get('reused_question'):
                latest[(result['atom_ids'][0],result['kind'])]=result
        for (origin,kind),result in latest.items():
            if origin in ids and kind=='final_transfer' and not result['correct']:
                add(origin,origin,'TRANSFER_WEAK',3,['transfer'])
        mis={m['atom_id'] for m in misconceptions if m['status']=='confirmed' and m['atom_id'] in ids}
        for a in sorted(mis):add(a,a,'MISCONCEPTION_DETECTED',0,['concept','application'])
        for a in atoms:
            origin=a['id'];s=states[origin]
            if origin in critical and s['mastery'] is not None and s['mastery']<FINAL_POLICY['critical_atom_floor']:
                path=PrerequisiteRepairEngine().trace(origin,atoms,graph.get('edges',[]),states)
                if path['weak']:
                    parent,depth=path['weak'][0];add(origin,parent,'PREREQUISITE_GAP',1,['concept','application'],depth)
                else:add(origin,origin,'CRITICAL_ATOM_WEAK',2,['concept','application'])
            elif origin in critical and s['transfer'] is not None and s['transfer']<FINAL_POLICY['critical_atom_floor']:add(origin,origin,'TRANSFER_WEAK',3,['transfer'])
            elif origin in critical and s['transfer'] is None:add(origin,origin,'TRANSFER_UNVERIFIED',3,['transfer'])
            elif origin in critical and s['retention'] is not None and s['retention']<FINAL_POLICY['critical_atom_floor']:add(origin,origin,'RETENTION_WEAK',4,['retention'])
            elif origin in critical and s['confidence']<FINAL_POLICY['confidence_threshold']:add(origin,origin,'LOW_CONFIDENCE',5,['concept','application'])
        return sorted(targets,key=lambda t:(t['priority'],t['atom_id']))[:FINAL_POLICY['max_final_remediation_targets']]
