"""ATIE returns a Teaching Action; it never generates a lesson or changes mastery."""
from .difficulty_controller import difficulty
from .teaching_strategy import choose
from .presentation_controller import presentation, presentation_policy
from .intervention_manager import feedback_from_message
import re

class ATIEEngine:
    def decide(self,state,knowledge,scope,message='',mode='lesson',feedback=None):
        feedback=feedback or feedback_from_message(message)
        if not feedback and re.fullmatch(r'(?:请)?继续(?:讲|解释)?[。！!\s]*',message) and state.get('user_feedback'):
            last=state['user_feedback'][-1]
            if last in ('confused','formula_confusing','rephrase'):feedback=last
        action,reason=choose(state,knowledge,feedback,mode)
        limits=difficulty(state,scope,message,feedback)
        if action=='BACKTRACK':limits.update(depth='beginner',allow_formulas=False,allowed_depth='conceptual')
        if limits['allowed_depth'] in ('concept','conceptual','introductory') and action in ('DEEPEN','CHALLENGE'):
            action='EXPLAIN';reason='先在当前阶段建立直觉，详细推导留到对应小节'
        forms,structure,check=presentation(action,knowledge,limits,state,mode)
        compact=mode!='lesson' and 'text' in state.get('preferences',{}).get('preferred_style',[])
        if mode!='lesson' and not feedback:
            if re.search(r'一句话|简短',message):
                forms,structure,check=['text'],0,False;compact=True
            elif re.search(r'什么是|是什么意思|定义是什么',message):
                forms,structure,check=['concept','example'],1,False;compact=True
            elif re.search(r'区别|比较|\bvs\b',message,re.I):forms,structure,check=['comparison','concept'],2,False
        return {'action':action,'goal':scope['purpose'],'depth':limits['depth'],'presentation':forms,'need_check':check,
                'structure_level':structure,'allow_formulas':limits['allow_formulas'],'allowed_depth':limits['allowed_depth'],
                'forbidden_topics':scope['future_atoms'],'core_atoms':scope['core_atoms'],'related_atoms':scope['related_atoms'],
                'backtrack_targets':knowledge.get('weak_prerequisite',[]) if action=='BACKTRACK' else [],
                'reason':reason,'exploring_future':limits['exploring_future'],'policy_version':'atie_rules_v1',
                'evidence_source':state['cognitive_state']['source'],
                'presentation_policy':presentation_policy(action,forms,structure,check,mode,compact)}
