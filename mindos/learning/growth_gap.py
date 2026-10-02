"""Batch, read-only adapters over P0–P3 and rule-owned goal gaps."""
import json
from .canonical import atom_context
from .personal import PersonalKnowledgeProfileBuilder
from .state import ForgettingService, ReviewScheduler, empty
from .final import FinalAssessmentService, fingerprint
from .policy import clock
from .growth_graph import POLICY, LEVELS

LABELS={'unknown':'待验证','missing':'需要补齐','partial':'需要巩固','ready_to_verify':'已有基础，先验证','sufficient':'当前要求已有依据','stale':'建议复习','conflicted':'存在冲突，先验证','practice_missing':'需要实践验证'}

class GrowthInputReader:
    def __init__(self,store):self.store=store
    def read(self,user):
        builder=PersonalKnowledgeProfileBuilder(self.store)
        with self.store.connect() as db:
            identities,courses,graphs,mappings,evidence,calibration=builder._inputs(db,user)
            raw={(r['course_id'],r['atom_id']):json.loads(r['state_json']) for r in db.execute('SELECT * FROM knowledge_states WHERE user_id=?',(user,))}
            mis=[dict(r) for r in db.execute("SELECT * FROM learning_misconceptions WHERE user_id=? AND status='confirmed'",(user,))]
            priors=[dict(r) for r in db.execute("SELECT * FROM inherited_knowledge_priors WHERE user_id=? AND status!='invalidated'",(user,))]
            authentic=[dict(r) for r in db.execute('SELECT r.*,t.atom_id,t.task_type,t.task_json FROM authentic_results r JOIN authentic_tasks t ON t.id=r.task_id WHERE r.user_id=? AND t.user_id=?',(user,user))]
        groups={i['id']:[] for i in identities};coverage={};valid=[];states={};reviews=[]
        for cid,c in courses.items():
            graph=graphs.get(cid,{'atoms':[],'edges':[]});atoms=[a for a in graph['atoms'] if a.get('quality_status')!='deprecated']
            states[cid]={a['id']:ForgettingService().project(raw.get((cid,a['id']),empty(a['id']))) for a in atoms}
            if not c['deleted_at'] and c['status'] in {'active','completed'}:
                reviews += [dict(r,course_id=cid,course_title=c['title']) for r in ReviewScheduler().queue([dict(a,unlocked=a['section']<=c['current_ordinal']) for a in atoms],states[cid])]
        for m in mappings:
            c=courses.get(m['course_id']);g=graphs.get(m['course_id'],{'atoms':[],'edges':[]});a=next((a for a in g['atoms'] if a['id']==m['course_atom_id'] and a.get('quality_status')!='deprecated'),None)
            if not c or not a or fingerprint(atom_context(c,g,a))!=m['atom_hash']:continue
            valid.append(m);coverage.setdefault(m['canonical_atom_id'],[]).append({'course_id':c['id'],'atom_id':a['id'],'section':a['section'],'title':c['title'],'course_status':c['status'],'deleted':bool(c['deleted_at']),'unlocked':a['section']<=c['current_ordinal']})
            if m['canonical_atom_id'] not in groups or not m['state_json']:continue
            groups[m['canonical_atom_id']].append({'course_id':c['id'],'course_title':c['title'],'course_atom_id':a['id'],'depth':a['depth'],'source_course_deleted':bool(c['deleted_at']),'mapping_id':m['id'],'mapping_confidence':m['mapping_confidence'],'state':json.loads(m['state_json']),'independent_evidence':evidence.get((c['id'],a['id']),0)})
        # Invoke unchanged P3 aggregation purely in memory; never persist P3 profiles.
        profiles={i['id']:builder.compute(i,groups[i['id']],calibration) for i in identities}
        # P1 is read once per course, not once per capability; use its exact completion semantics.
        finals={cid:FinalAssessmentService(self.store).status(user,cid) for cid,c in courses.items() if not c['deleted_at']}
        return {'canonical':{i['id']:i for i in identities},'profiles':profiles,'courses':courses,'graphs':graphs,'states':states,'coverage':coverage,'misconceptions':mis,'priors':priors,'authentic':authentic,'reviews':reviews,'finals':finals,'mappings':valid}

class GapAnalysisEngine:
    def analyze(self,goal,graph,mappings,inputs,artifacts=None):
        cfg=POLICY['gap'];gaps=[];artifacts=artifacts or {}
        canonical=inputs['canonical'];verified={m['capability_id']:m for m in mappings if m['status']=='verified' and m['canonical_atom_id'] in canonical and m['canonical_fingerprint']==canonical[m['canonical_atom_id']]['semantic_fingerprint']}
        by_id={c['id']:c for c in graph['capabilities']}
        required_ancestors=set();stack=[c['id'] for c in graph['capabilities'] if c['importance']=='critical']
        while stack:
            cid=stack.pop()
            for e in graph['dependencies']:
                if e['relation']=='prerequisite' and e['to']==cid and e['from'] not in required_ancestors:required_ancestors.add(e['from']);stack.append(e['from'])
        for cap in graph['capabilities']:
            m=verified.get(cap['id']);cid=m['canonical_atom_id'] if m else None;p=inputs['profiles'].get(cid)
            if p and (not p['sources'] or not p['course_count']):p=None
            coverage=inputs['coverage'].get(cid,[]);live=[r for r in coverage if not r['deleted'] and r['course_status'] in {'active','completed','paused'}]
            required_depth=LEVELS.index(cap['required_level'])+1
            def target_depth(r):return next(a['depth'] for a in inputs['graphs'][r['course_id']]['atoms'] if a['id']==r['atom_id'])
            live.sort(key=lambda r:(not r['unlocked'],target_depth(r)<required_depth,r['course_status']=='paused',inputs['courses'][r['course_id']]['sort_order']))
            possible=any(x['capability_id']==cap['id'] and x['status']=='candidate' for x in mappings)
            current=[inputs['states'][r['course_id']][r['atom_id']] for r in live if r['unlocked'] and target_depth(r)>=required_depth]
            dim=cap['required_level'];field=dim+'_estimate';value=p.get(field) if p else None
            reason='GOAL_GAP_MISSING';status='missing';practice_record=None
            relevant_mis=[x for x in inputs['misconceptions'] if any(r['course_id']==x['course_id'] and r['atom_id']==x['atom_id'] for r in live)]
            due=[r for r in inputs['reviews'] if any(r['course_id']==c['course_id'] and r['atom_id']==c['atom_id'] for c in live)]
            if cap['type'] in {'practice','tool','meta_skill'}:
                reference=artifacts.get(cap['id'])
                requirement_hash=fingerprint({k:cap[k] for k in ['id','name','description','type','required_level']})
                practice_record=next((r for r in inputs['authentic'] if r['task_id']==reference and json.loads(r['task_json']).get('growth_scope',{}).get('requirement_hash')==requirement_hash and json.loads(r['task_json']).get('growth_scope',{}).get('goal_id')==goal['id'] and r['valid_for_calibration'] and r['score'] is not None and r['score']>=cfg['practice_score'] and r['evaluator_confidence']>=cfg['practice_confidence']),None)
                status='sufficient' if practice_record else 'practice_missing';reason='PRACTICE_RESULT_OBSERVED' if practice_record else 'GOAL_GAP_PRACTICE_MISSING'
                # Route practical work through a verified prerequisite's course where possible.
                ancestors=set();stack=[cap['id']]
                while stack:
                    node=stack.pop()
                    for e in graph['dependencies']:
                        if e['to']==node and e['relation']=='prerequisite' and e['from'] not in ancestors:ancestors.add(e['from']);stack.append(e['from'])
                if not live:
                    live=[r for a in ancestors if a in verified for r in inputs['coverage'].get(verified[a]['canonical_atom_id'],[]) if not r['deleted']]
            elif p:
                if p['cross_course_conflict'] or relevant_mis:status='conflicted';reason='MAJOR_MISCONCEPTION' if relevant_mis else 'GOAL_GAP_CONFLICT'
                elif p['support_level']=='stale' or due or p['retention_estimate'] is not None and p['retention_estimate']<.6:status='stale';reason='GOAL_GAP_STALE'
                elif value is None:
                    status='partial' if p['understanding_estimate'] is not None else 'unknown';reason='GOAL_GAP_TRANSFER_UNVERIFIED' if dim=='transfer' else 'GOAL_GAP_PARTIAL'
                elif value<cfg['sufficient_dimension']:status='partial';reason='GOAL_GAP_PARTIAL'
                elif p['confidence']<cfg['minimum_confidence'] or p['calibration_status']=='state_overestimation':status='ready_to_verify';reason='VERIFY_EXISTING_KNOWLEDGE'
                elif current and any(s.get(dim) is not None and s[dim]>=cfg['sufficient_dimension'] and s['confidence']>=cfg['minimum_confidence'] for s in current):status='sufficient';reason='CAPABILITY_VERIFIED'
                else:status='ready_to_verify';reason='VERIFY_EXISTING_KNOWLEDGE'
            elif possible:status='unknown';reason='MAPPING_REVIEW_REQUIRED'
            higher=bool(p and p['sources'] and LEVELS.index(dim)+1>max(s['depth'] for s in p['sources']))
            if status=='sufficient' and higher:status='ready_to_verify';reason='VERIFY_DEEPER_REQUIREMENT'
            gaps.append({'capability_id':cap['id'],'name':cap['name'],'type':cap['type'],'required_level':dim,'importance':cap['importance'],'required_for_critical':cap['id'] in required_ancestors,'status':status,'label':LABELS[status],'reason_code':reason,'canonical_atom_id':cid,'coverage':live,'all_coverage':coverage,'possible_coverage':possible,'planning_confidence':'建议先验证' if status in {'unknown','conflicted','ready_to_verify'} else '推荐依据充分' if status=='sufficient' else '推荐依据一般','practice_task_id':practice_record['task_id'] if practice_record else None,'profile_support':p['support_level'] if p else 'absent','prerequisite_misconception':bool(relevant_mis),'review_due':bool(due),'debug':{'dimension_value':value,'profile_confidence':p['confidence'] if p else None,'calibration_status':p['calibration_status'] if p else 'insufficient_future_evidence','source_state_versions':p['state_versions'] if p else []}})
        summary={s:sum(g['status']==s for g in gaps) for s in LABELS};critical=[g for g in gaps if (g['importance']=='critical' or g.get('required_for_critical')) and g['status']!='sufficient']
        return {'gaps':gaps,'summary':summary,'critical_gaps':critical,'inputs_hash':fingerprint({'goal_version':goal['goal_model_version'],'graph':graph,'mapping':mappings,'gaps':gaps,'course_revisions':[(c['id'],c['content_revision'],c['current_ordinal'],c['deleted_at']) for c in inputs['courses'].values()],'policy':POLICY}), 'boundary':'缺口是对目标要求的比较，不是答题错误或掌握状态。未测维度保持未知。实践依据中的开放评分仍是模型辅助观察。'}

class GoalCompletionAnalyzer:
    def analyze(self,goal,graph,analysis,inputs):
        critical=[g for g in analysis['gaps'] if g['importance']=='critical' or g.get('required_for_critical')];pending_final=[]
        for g in critical:
            # Gate the course selected for this requirement, not every historical source.
            for r in g['coverage'][:1]:
                final=inputs['finals'].get(r['course_id'])
                if final and final['completion']['eligible'] and final['mastery_state']['status']!='mastered':pending_final.append(r['course_id'])
        practice=any(g['type']=='practice' and g['status']=='sufficient' for g in analysis['gaps'])
        achieved=not goal.get('requirements_stale',False) and bool(critical) and all(g['status']=='sufficient' for g in critical) and not pending_final and (goal['goal_type'] not in {'project','competition'} or practice)
        return {'achieved':achieved,'label':'目标已变化，请重新确认能力要求' if goal.get('requirements_stale') else '当前目标要求已基本满足' if achieved else '仍有目标要求待补齐或验证','critical_remaining':len(analysis['critical_gaps']),'final_pending_courses':sorted(set(pending_final)),'practice_requirement_met':practice,'boundary':'程序对当前目标要求的检查，不是职业或教育认证。用户跳过任务不会改变这些条件。'}
