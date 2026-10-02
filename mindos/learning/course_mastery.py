"""Program-owned course judgments; completion and unknown dimensions stay distinct."""
from .final_assessment import FINAL_POLICY,criticality
from .policy import POLICY

def label(status,retention=None):
    return {'not_ready':'学习中','ready_for_final':'内容已完成 · 待掌握检测','assessing':'正在进行掌握检测','needs_reinforcement':'还有几个知识点值得巩固','mastered':'当前能力较稳定'+(' · 长期记忆待验证' if retention is None else ''),'completed_with_gaps':'内容已完成 · 仍有待巩固知识','content_completed':'内容已完成 · 暂未检测'}[status]

class CourseMasteryAnalyzer:
    def analyze(self,course,graph,states,misconceptions,completion,plan=None,results=None):
        atoms,scores,critical=criticality(course,graph);weights={a['id']:FINAL_POLICY['critical_atom_weight'] if a['id'] in critical else FINAL_POLICY['normal_atom_weight'] for a in atoms};total=sum(weights.values())
        def average(field):
            pairs=[(states[a['id']].get(field),weights[a['id']]) for a in atoms if states[a['id']].get(field) is not None]
            return round(sum(v*w for v,w in pairs)/sum(w for v,w in pairs),4) if pairs else None
        dims={d:average(d) for d in ['understanding','application','transfer','retention']};mastery=average('mastery')
        confidence=round(sum(states[a['id']]['confidence']*weights[a['id']] for a in atoms)/total,4) if total else 0.
        coverage={d:round(sum(states[a]['confidence']>0 and states[a][d] is not None for a in critical)/len(critical),4) if critical else 0. for d in dims}
        active_mis=[m for m in misconceptions if m['atom_id'] in weights and m['status']=='confirmed']
        weak=[a for a in atoms if states[a['id']]['mastery'] is not None and states[a['id']]['mastery']<FINAL_POLICY['critical_atom_floor']]
        unknown=[a for a in atoms if states[a['id']]['mastery'] is None or states[a['id']]['confidence']<FINAL_POLICY['confidence_threshold'] or any(states[a['id']][d] is None for d in ['understanding','application','transfer'])]
        stable=[a for a in atoms if states[a['id']]['mastery'] is not None and states[a['id']]['mastery']>=FINAL_POLICY['course_mastery_threshold'] and states[a['id']]['confidence']>=FINAL_POLICY['confidence_threshold'] and all(states[a['id']][d] is not None and states[a['id']][d]>=FINAL_POLICY['critical_atom_floor'] for d in ['understanding','application','transfer'])]
        reviews=[a for a in atoms if states[a['id']].get('state')=='review_due' or states[a['id']].get('forgetting_risk',0) is not None and states[a['id']].get('forgetting_risk',0)>=POLICY['forgetting_risk_threshold']]
        final=results or [];independent=[r for r in final if not r['hint_used'] and not r.get('reused_question')];transfer=[r for r in independent if r['kind']=='final_transfer']
        accuracy=sum(r['correct'] for r in independent)/len(independent) if independent else None
        guards={
         'CONTENT_COMPLETE':completion['eligible'],
         'FINAL_COMPLETED':bool(plan and plan['status']=='completed' and not plan.get('stale',False)),
         'OVERALL_SCORE':mastery is not None and mastery>=FINAL_POLICY['course_mastery_threshold'],
         'CRITICAL_FLOOR':bool(critical) and all(states[a]['mastery'] is not None and states[a]['mastery']>=FINAL_POLICY['critical_atom_floor'] for a in critical),
         'STATE_CONFIDENCE':confidence>=FINAL_POLICY['confidence_threshold'],
         'UNDERSTANDING_COVERAGE':coverage['understanding']>=FINAL_POLICY['minimum_understanding_coverage'],
         'APPLICATION_COVERAGE':coverage['application']>=FINAL_POLICY['minimum_application_coverage'],
         'TRANSFER_COVERAGE':coverage['transfer']>=FINAL_POLICY['minimum_transfer_coverage'],
         'RETENTION_IF_MEASURED':all(states[a]['retention'] is None or states[a]['retention']>=FINAL_POLICY['critical_atom_floor'] for a in critical),
         'NO_CONFIRMED_MISCONCEPTION':not active_mis,
         'INDEPENDENT_FINAL':len(independent)>=FINAL_POLICY['minimum_final_independent_answers'] and accuracy is not None and accuracy>=FINAL_POLICY['minimum_final_accuracy'] and all(any(r['kind']==kind for r in independent) for kind in ['final_concept','final_application','final_transfer']),
         'FINAL_TRANSFER':bool(transfer) and sum(r['correct'] for r in transfer)/len(transfer)>=FINAL_POLICY['minimum_final_accuracy']}
        messages={'CONTENT_COMPLETE':'课程内容还未全部完成。','FINAL_COMPLETED':'还没有完成有效的终局检测。','OVERALL_SCORE':'综合答题证据仍需要巩固。','CRITICAL_FLOOR':'关键知识存在薄弱或未充分验证的情况。','STATE_CONFIDENCE':'系统判断所依据的证据量或维度覆盖不足。','UNDERSTANDING_COVERAGE':'部分核心概念还没有理解题证据。','APPLICATION_COVERAGE':'部分核心知识还缺少应用题证据。','TRANSFER_COVERAGE':'迁移能力尚未充分验证。','RETENTION_IF_MEASURED':'已有延迟回忆显示部分关键知识仍需要巩固；未测的记忆不按零分处理。','NO_CONFIRMED_MISCONCEPTION':'存在重复答题支持的混淆，需要定点巩固。','INDEPENDENT_FINAL':'本次独立理解、应用和迁移证据尚不充分；求助题仍作为练习。','FINAL_TRANSFER':'本次陌生情境迁移还需要验证或练习。'}
        if not completion['eligible']:status='not_ready'
        elif plan and plan['status']=='active' and not plan.get('stale'):status='assessing'
        elif all(guards.values()):status='mastered'
        elif plan and plan['status'] in {'completed','deferred'}:status='needs_reinforcement'
        else:status='ready_for_final'
        if course.get('final_disposition')=='completed_with_gaps' and status!='mastered':status='completed_with_gaps'
        elif course.get('final_disposition')=='content_completed' and status=='ready_for_final':status='content_completed'
        compact=lambda a:{'id':a['id'],'title':a['title'],'section':a['section'],'critical':a['id'] in critical,'knowledge_state':states[a['id']]}
        return {'status':status,'label':label(status,None if coverage['retention']<1 else dims['retention']),'completion_ratio':completion['ratio'],'mastery_score':mastery,'mastery_confidence':confidence,**dims,
          'dimension_coverage':coverage,'critical_atoms_total':len(critical),'critical_atoms_mastered':sum(a['id'] in critical for a in stable),'critical_atoms_weak':sum(a['id'] in critical for a in weak),'critical_atoms_unknown':sum(a['id'] in critical for a in unknown),
          'stable_atoms':[compact(a) for a in stable],'weak_atoms':[compact(a) for a in weak],'unknown_atoms':[compact(a) for a in unknown],'misconception_atoms':[m for m in active_mis],'review_due_atoms':[compact(a) for a in reviews],
          'guards':guards,'reasons':[{'code':k,'message':messages[k]} for k,v in guards.items() if not v],
          'final_independent_answers':len(independent),'final_accuracy':round(accuracy,4) if accuracy is not None else None,'retention_pending':coverage['retention']<1,
          'policy_version':FINAL_POLICY['version'],'state_policy_version':POLICY['version'],
          'boundary':'课程进度不是掌握证明。结论来自规则与答题证据；未知维度不补分，长期记忆未测时不能声称全面掌握。题目未经教师认证。'}

    def recommendations(self,result):
        actions=[]
        if result['status']!='mastered':actions.append({'action':'reinforce','reason':'只补当前关键缺口，再用新题验证，不重学整门课程。'})
        if result['retention_pending'] or result['review_due_atoms']:actions.append({'action':'review','reason':'长期记忆仍需延迟回忆验证，沿用现有复习建议与间隔。'})
        if result['status']=='mastered':actions.append({'action':'continue_learning','reason':'可以考虑新的学习方向；不跨课程转移掌握记录。'})
        return actions
