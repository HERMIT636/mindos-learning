"""Program-owned tasks and dependency gates; models may only organize stages."""
import json,secrets
from datetime import datetime
from zoneinfo import ZoneInfo
from jsonschema import Draft202012Validator
from .growth_graph import POLICY,STAGE_SCHEMA,order
from .final import fingerprint

TRIGGERS={'COURSE_MASTERED','COURSE_COMPLETED_WITH_GAPS','CAPABILITY_VERIFIED','CAPABILITY_CONFLICT','MAJOR_MISCONCEPTION','PROFILE_CHANGED','DEADLINE_CHANGED','GOAL_CHANGED','USER_REQUESTED_REPLAN'}
REASONS={'GOAL_GAP_MISSING':'目标要求这项能力，目前还缺少相关依据。','GOAL_GAP_PARTIAL':'已有部分基础，继续补齐目标要求的应用或理解。','GOAL_GAP_STALE':'这项前置能力需要先检查是否还记得。','GOAL_GAP_CONFLICT':'历史表现有冲突，先独立验证再决定下一步。','GOAL_GAP_TRANSFER_UNVERIFIED':'迁移能力还未测，优先使用陌生情境验证。','GOAL_GAP_PRACTICE_MISSING':'知识学习不能替代实践，需要独立完成并检查结果。','VERIFY_EXISTING_KNOWLEDGE':'已有相关基础，先用短测确认，避免完整重学。','REUSE_EXISTING_COURSE':'已有课程覆盖相关能力，优先继续当前课程。','CREATE_COURSE_REQUIRED':'现有课程尚未明确覆盖这项能力，建议审查一门范围较小的新课程。','FINAL_REQUIRED':'课程内容已完成，但掌握检测仍未满足，先完成现有终局检测。','MAPPING_REVIEW_REQUIRED':'可能关联到已有知识，请先审查关联，暂不当作确定覆盖。','CAPABILITY_VERIFIED':'已有结果支持当前能力要求，无需重复安排基础学习。','MAJOR_MISCONCEPTION':'关键能力仍有已确认误区，先回到课程中的补强流程。'}

class GrowthPlanner:
    def stages(self,goal,graph,sequence,model=None,pace_context=None):
        if model:
            failure=''
            for attempt in range(2):
                try:
                    payload={'goal':goal['title'],'capabilities':graph['capabilities'],'program_order':sequence,'hard_dependencies':[e for e in graph['dependencies'] if e['relation']=='prerequisite'],'schema':STAGE_SCHEMA,'repair_reason':failure,'pace_context':pace_context}
                    raw=model.growth_stages(payload) if hasattr(model,'growth_stages') else model._json('只把目标能力组织成简明阶段，不判断用户现状，不生成任务或完成状态。严格按program_order顺序分组，每项能力恰好出现一次，不得自行重排。前置不得位于后续阶段。每阶段最多4项能力。执行数据只用于时间与负载规划，不用于人格、自律或能力判断。不得据此判断掌握、改变能力或顺序。返回schema的JSON。',json.dumps(payload,ensure_ascii=False),max_tokens=2600,diagnostic_stage='growth_stages')
                    Draft202012Validator(STAGE_SCHEMA).validate(raw)
                    flat=[cid for s in raw['stages'] for cid in s['capability_ids']]
                    if len(flat)!=len(sequence) or set(flat)!=set(sequence):raise ValueError('阶段必须完整覆盖且不能重复能力')
                    positions={cid:i for i,s in enumerate(raw['stages']) for cid in s['capability_ids']}
                    if any(positions[e['from']]>positions[e['to']] for e in graph['dependencies'] if e['relation']=='prerequisite'):raise ValueError('阶段违反关键前置顺序')
                    if any(len(s['capability_ids'])>4 for s in raw['stages']):raise ValueError('请缩小阶段范围')
                    for s in raw['stages']:s['capability_ids']=sorted(s['capability_ids'],key=sequence.index)
                    if [cid for s in raw['stages'] for cid in s['capability_ids']]!=sequence:raise ValueError('阶段不得改变程序确定的任务顺序')
                    return raw['stages'],'model_organization'
                except Exception as exc:
                    failure=str(exc)
                    if hasattr(model,'_diagnostic'):model._diagnostic({'stage':'growth_stage_validation','attempt':attempt+1,'failure_reason':failure})
        return [{'title':'补齐与验证 · '+str(i//4+1),'objective':'依次满足这部分目标要求，再进入后续阶段。','capability_ids':sequence[i:i+4]} for i in range(0,len(sequence),4)],'rule_organization'

    def build(self,goal,graph,analysis,inputs,model=None,previous=None,pace_context=None):
        gaps={g['capability_id']:g for g in analysis['gaps']};caps={c['id']:c for c in graph['capabilities']}
        inherited={t['key']:t for t in (previous or {}).get('tasks',[])}
        ancestors=set();stack=[c['id'] for c in caps.values() if c['importance']=='critical']
        while stack:
            cid=stack.pop()
            for e in graph['dependencies']:
                if e['relation']=='prerequisite' and e['to']==cid and e['from'] not in ancestors:ancestors.add(e['from']);stack.append(e['from'])
        def rank(cid):
            g=gaps[cid];base=0 if cid in ancestors or g['importance']=='critical' else 1 if g['importance']=='supporting' else 2
            return base*10+{'conflicted':0,'stale':1,'missing':2,'partial':3,'unknown':4,'ready_to_verify':4,'practice_missing':5,'sufficient':6}[g['status']]
        sequence=order(graph,rank);stages,organization=self.stages(goal,graph,sequence,model,pace_context)
        tasklist=[];new_courses=0;verifications=0
        deadline_short=False
        if goal.get('deadline'):deadline_short=(datetime.fromisoformat(goal['deadline']).date()-datetime.now(ZoneInfo('Asia/Shanghai')).date()).days<=14
        selected_courses={g['coverage'][0]['course_id'] for g in analysis['gaps'] if g['coverage']}
        final_needed={cid for cid,v in inputs['finals'].items() if cid in selected_courses and v['completion']['eligible'] and v['mastery_state']['status']!='mastered'}
        final_seen=set()
        for i,stage in enumerate(stages,1):
            stage.update(id=secrets.token_urlsafe(12),ordinal=i,status='planned')
            stage['gate']={'type':'capability_gate','requirements':[{'capability_id':cid,'minimum':caps[cid]['required_level']} for cid in stage['capability_ids']]}
            for cid in stage['capability_ids']:
                cap=caps[cid];g=gaps[cid];related=g['coverage'];r=related[0] if related else None;kind='goal_checkpoint';reason=g['reason_code'];target=None;meta={'capability_id':cid,'required_level':cap['required_level'],'gap_status':g['status'],'planning_confidence':g['planning_confidence'],'why_after':'完成后可更可靠地学习依赖它的后续能力。'}
                if r:target=r['course_id'];meta.update(course_id=target,atom_id=r['atom_id'],section=r['section'])
                if g['status']=='sufficient':
                    if r and target in final_needed and target not in final_seen:kind='final_assessment';reason='FINAL_REQUIRED';final_seen.add(target)
                elif r and target in final_needed and target not in final_seen and g['status'] not in {'stale','conflicted','practice_missing'}:
                    kind='final_assessment';reason='FINAL_REQUIRED';final_seen.add(target)
                elif g['possible_coverage'] and not g['canonical_atom_id']:reason='MAPPING_REVIEW_REQUIRED'
                elif r and r['deleted']:kind='continue_course';reason='COURSE_RECYCLED'
                elif r and not r['unlocked']:kind='continue_course';reason='REUSE_EXISTING_COURSE';meta['future_topic']=True
                elif g['status']=='stale' and r:kind='review';reason='GOAL_GAP_STALE'
                elif g['status'] in {'conflicted','ready_to_verify','unknown'} and r:
                    kind='cross_course_verify';reason='VERIFY_EXISTING_KNOWLEDGE' if g['status']!='conflicted' else 'GOAL_GAP_CONFLICT';verifications+=1
                    prior=next((p for p in inputs['priors'] if p['course_id']==target and p['course_atom_id']==r['atom_id'] and p['status']!='verified_in_course'),None)
                    meta['prior_id']=prior['id'] if prior else None;meta['assessment']='diagnostic'
                elif cap['type'] in {'practice','tool','meta_skill'} and r:kind='authentic_assessment';reason='GOAL_GAP_PRACTICE_MISSING';meta['assessment']='design'
                elif cap['required_level']=='transfer' and r and g['reason_code']=='GOAL_GAP_TRANSFER_UNVERIFIED':kind='authentic_assessment';meta['assessment']='open_transfer'
                elif r:kind='continue_course';reason='REUSE_EXISTING_COURSE'
                elif g['all_coverage']:
                    r=g['all_coverage'][0];kind='start_course';target=r['course_id'];meta.update(course_id=target,atom_id=r['atom_id'],section=r['section']);reason='REUSE_EXISTING_COURSE'
                elif cap['type'] in {'practice','tool','meta_skill'}:kind='goal_checkpoint';reason='GOAL_GAP_PRACTICE_MISSING';meta['needs_related_course']=True
                else:
                    kind='create_course';new_courses+=1;reason='CREATE_COURSE_REQUIRED';meta['course_title']=cap['name']+' · 目标专题';meta['course_goal']=cap['description'];meta['target_capabilities']=[{'name':cap['name'],'required_level':cap['required_level']}]
                linked=next((t for t in inherited.values() if t['capability_id']==cid and t['metadata'].get('linked_course_id') in inputs['courses'] and not inputs['courses'][t['metadata']['linked_course_id']]['deleted_at']),None)
                if kind=='create_course' and linked:
                    kind='continue_course';target=linked['metadata']['linked_course_id'];reason='REUSE_EXISTING_COURSE';meta.update(course_id=target,linked_course_id=target,coverage_not_confirmed=True)
                    new_courses-=1
                key=fingerprint([cid,kind,target,meta.get('atom_id')]);old=inherited.get(key,linked or {})
                status='completed' if g['status']=='sufficient' and kind=='goal_checkpoint' else 'ready'
                dependencies=[e['from'] for e in graph['dependencies'] if e['to']==cid and e['relation']=='prerequisite']
                if any(gaps[p]['status']!='sufficient' or any(x['course_id'] in final_needed for x in gaps[p]['coverage']) for p in dependencies):status='blocked';meta['blocked_by']=[caps[p]['name'] for p in dependencies if gaps[p]['status']!='sufficient' or any(x['course_id'] in final_needed for x in gaps[p]['coverage'])]
                if g['prerequisite_misconception']:meta['remediation_first']=True
                if new_courses>POLICY['planning']['max_new_course_recommendations'] and kind=='create_course' or verifications>POLICY['planning']['max_verification_tasks'] and kind=='cross_course_verify':status='planned';meta['deferred_to_later_batch']=True
                if deadline_short and cap['importance']=='optional' and cid not in ancestors:status='planned';meta['deadline_deferred_optional']=True
                if old.get('status') in {'skipped','paused'}:status=old['status']
                task={'id':secrets.token_urlsafe(12),'key':key,'stage_ordinal':i,'capability_id':cid,'task_type':kind,'target_id':target,'title':cap['name'],'reason_code':reason,'reason':REASONS.get(reason,'先检查相关课程与能力要求，再决定行动。'),'priority':rank(cid),'estimated_minutes':POLICY['minutes'][kind],'status':status,'locked':bool(old.get('locked')),'pinned':bool(old.get('pinned')),'metadata':meta}
                tasklist.append(task)
        # Keep user locks, even when scope or gap changes. They do not satisfy any new gate.
        existing_keys={t['key'] for t in tasklist}
        for t in (previous or {}).get('tasks',[]):
            if t.get('locked') and t['key'] not in existing_keys:
                t=json.loads(json.dumps(t));t.update(id=secrets.token_urlsafe(12),stage_ordinal=len(stages)+1,status='ready' if t['status']!='completed' else 'completed');t['metadata']['retained_user_lock']=True;tasklist.append(t)
        if any(t['stage_ordinal']>len(stages) for t in tasklist):stages.append({'id':secrets.token_urlsafe(12),'ordinal':len(stages)+1,'title':'你固定的学习任务','objective':'保留用户选择，不作为新目标能力已经满足的证明。','capability_ids':[],'gate':{'type':'user_choices','requirements':[]},'status':'planned'})
        for s in stages:
            tasks=[t for t in tasklist if t['stage_ordinal']==s['ordinal']];s['estimated_minutes']=sum(t['estimated_minutes'] for t in tasks if t['status']!='completed')
        if any(sum(t['stage_ordinal']==s['ordinal'] for t in tasklist)>8 for s in stages):raise ValueError('阶段任务过多，请缩小能力范围')
        return {'stages':stages,'tasks':tasklist,'organization':organization,'inputs_hash':analysis['inputs_hash'],'goal_model_version':goal['goal_model_version'],'rationale':{'policy_version':POLICY['version'],'dependency_order':sequence,'time_basis':'规则估算，不是模型预测或严格排程','deadline_optional_deferred':deadline_short,'weekly_time_budget_minutes':goal.get('weekly_time_budget_minutes')}}

class GrowthReplanningEngine:
    def triggers(self,old,new_analysis,inputs):
        before=old.get('gap_snapshot',{});after={g['capability_id']:g['status'] for g in new_analysis['gaps']};codes=[]
        for cid,status in after.items():
            if status!=before.get(cid):
                if status=='sufficient':codes.append('CAPABILITY_VERIFIED')
                elif status=='conflicted':codes.append('CAPABILITY_CONFLICT')
                elif status=='stale':codes.append('PROFILE_CHANGED')
                elif before.get(cid)=='sufficient':codes.append('PROFILE_CHANGED')
        previous_final=old.get('final_snapshot',{})
        for cid,final in inputs['finals'].items():
            state=final['mastery_state']['status']
            if previous_final.get(cid)!=state and state in {'mastered','completed_with_gaps'}:codes.append('COURSE_MASTERED' if state=='mastered' else 'COURSE_COMPLETED_WITH_GAPS')
        if any(g['prerequisite_misconception'] and before.get(g['capability_id'])!='conflicted' for g in new_analysis['gaps']):codes.append('MAJOR_MISCONCEPTION')
        return list(dict.fromkeys(codes))
