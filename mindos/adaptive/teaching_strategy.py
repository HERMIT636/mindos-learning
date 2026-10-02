"""Versioned, explainable teaching choices independent of the LLM."""
ACTIONS={'INTRODUCE','EXPLAIN','REPHRASE','VISUALIZE','EXAMPLE','DEEPEN','SIMPLIFY','BACKTRACK','CHECK','CHALLENGE','REVIEW'}

def choose(state,knowledge,feedback,mode):
    if feedback:
        return {'confused':'REPHRASE','formula_confusing':'SIMPLIFY','rephrase':'REPHRASE','visual':'VISUALIZE','example':'EXAMPLE',
                'deepen':'DEEPEN','backtrack':'BACKTRACK','check':'CHECK','challenge':'CHALLENGE','review':'REVIEW'}[feedback], '根据你当前的提问或反馈调整讲法'
    if knowledge.get('weak_prerequisite') and not knowledge.get('repair_managed'):return 'BACKTRACK','先补充已有测试显示薄弱的前置知识'
    application=state['assessment_dimensions']['application']
    if application['attempts'] and application['rate']<.6:return 'EXAMPLE','应用题较薄弱，增加情境与案例练习'
    recent=state.get('recent_assessment')
    if recent and recent['rate']<.6:return 'EXAMPLE','最近一次小测较薄弱，换用具体例子并逐步解释'
    styles=state.get('preferences',{}).get('preferred_style',[])
    if 'example' in styles:return 'EXAMPLE','按你的偏好增加具体例子'
    if 'visual' in styles:return 'VISUALIZE','按你的偏好用图示解释关系'
    if state.get('preferences',{}).get('math_level')=='advanced':return 'DEEPEN','按你声明的数学基础，允许在本节范围内深入'
    if not state['previous_strategy'] and mode=='lesson':return 'INTRODUCE','先建立直觉与本节学习目标'
    return 'EXPLAIN','结合当前目标与已有学习证据解释'
