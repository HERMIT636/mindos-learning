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
