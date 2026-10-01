"""Use only as much structure as the teaching task needs."""
def presentation(action,knowledge,difficulty,state,mode):
    complex_topic=knowledge['type'] in ('mechanism','operation','relation','reason','skill')
    diagram='flow' if knowledge['type']=='operation' or any(word in knowledge['name'] for word in ('流程','步骤','计算过程')) else 'diagram'
    previous=state['previous_strategy'][0].get('presentation',[]) if state['previous_strategy'] else []
    if action=='CHECK':return ['checkpoint'],1,True
    if action=='CHALLENGE':return ['example','checkpoint'],2,True
    if action=='REVIEW':return ['concept','example','checkpoint'],2,True
    if action=='BACKTRACK':return ['concept','analogy','example','checkpoint'],2,True
    if action=='VISUALIZE':return [diagram,'concept','checkpoint'],3,True
    if action=='EXAMPLE':return ['question','example','concept','checkpoint'],2,True
    if action in ('SIMPLIFY','REPHRASE'):
        return (['example','diagram','concept','checkpoint'] if 'analogy' in previous else ['analogy','example','concept','checkpoint']),3 if 'analogy' in previous else 2,True
    if difficulty['allow_formulas'] and (complex_topic or action=='DEEPEN'):return ['question','concept','formula','example','checkpoint'],4,True
    if 'text' in state.get('preferences',{}).get('preferred_style',[]) and mode!='lesson':return ['text'],0,False
    if mode!='lesson' and not complex_topic:return ['concept','example'],1,False
    if complex_topic:return ['question','analogy',diagram,'concept','checkpoint'],3,True
    return ['question','concept','example','checkpoint'],2,True


def presentation_policy(action,forms,structure,check,mode,compact=False):
    """ATIE sets hard teaching constraints; the model selects representations."""
    required=[];groups=[]
    if mode=='lesson':
        required.append('question');groups.append(['example','analogy'])
    if check:required.append('checkpoint')
    if action not in ('CHECK','CHALLENGE'):groups.append(['concept','text'])
    if action in ('EXAMPLE','REVIEW','CHALLENGE'):required.append('example')
    if action in ('SIMPLIFY','REPHRASE','BACKTRACK'):groups.append(['analogy','example'])
    if action=='VISUALIZE':groups.append(['diagram','flow'])
    if 'formula' in forms:required.append('formula')
    if 'comparison' in forms:required.append('comparison')
    # A one-sentence or simple definition request remains deliberately compact.
    compact=compact or action=='CHECK'
    if compact:required=list(dict.fromkeys(required+forms))
    return {'selection':'model','required_types':list(dict.fromkeys(required)),
            'required_any':groups,'max_structure_level':structure if compact else 4 if 'formula' in forms else 3,
            'fallback':forms,'rule':'按知识内容选表达形式，不改变教学动作、难度、公式许可、来源与小节范围'}


def resolve_presentation(packet,action):
    """Apply a model plan only when its block choices respect the ATIE policy."""
    plan=packet.get('presentation_plan') if isinstance(packet,dict) else None
    if plan is None:return {**action,'presentation_source':'rule_fallback'}
    policy=action.get('presentation_policy')
    if not isinstance(plan,dict) or not isinstance(policy,dict):raise ValueError('展示计划格式无效')
    forms=plan.get('forms');intent=plan.get('intent');reason=plan.get('reason')
    kinds={'text','question','analogy','concept','flow','diagram','comparison','formula','example','checkpoint'}
    if (not isinstance(forms,list) or not 1<=len(forms)<=10 or any(not isinstance(f,str) or f not in kinds for f in forms)
            or len(forms)!=len(set(forms))):raise ValueError('展示计划需提供不重复的有效内容块类型')
    if intent not in ('definition','relationship','process','comparison','formula','explanation','mixed'):raise ValueError('展示计划的知识表达意图无效')
    if not isinstance(reason,str) or not reason.strip() or len(reason)>400:raise ValueError('展示计划需简短说明选择理由')
    blocks=packet.get('blocks')
    if not isinstance(blocks,list):raise ValueError('展示计划缺少教学内容块')
    actual=[b.get('type') for b in blocks if isinstance(b,dict)]
    if set(actual)!=set(forms):raise ValueError('展示计划与实际内容块类型不一致')
    if any(k not in forms for k in policy['required_types']):raise ValueError('展示计划缺少当前教学任务要求的引入、案例或自查')
    if any(not any(k in forms for k in group) for group in policy['required_any']):raise ValueError('展示计划没有满足当前解释、例子或图示要求')
    visual={'relationship':['diagram'],'process':['flow'],'comparison':['comparison'],'formula':['formula']}
    if intent in visual and not any(k in forms for k in visual[intent]):raise ValueError('关系、流程、比较或推导需使用对应的展示组件')
    if 'formula' in forms and not action['allow_formulas']:raise ValueError('展示计划不能覆盖当前公式限制')
    structure=4 if 'formula' in forms else 3 if any(k in forms for k in ('diagram','flow')) else 2 if 'comparison' in forms else min(2,action['structure_level'])
    if structure>policy['max_structure_level']:raise ValueError('展示计划超出了当前问题需要的结构程度')
    return {**action,'presentation':forms,'structure_level':structure,'presentation_source':'model_content_plan',
            'presentation_intent':intent,'presentation_reason':reason.strip()}
