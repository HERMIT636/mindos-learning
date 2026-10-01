"""Respect lesson scope and reported difficulty; never infer math ability from title."""
from ..teaching import contains

def difficulty(state,scope,message,feedback):
    beginner='零基础' in state.get('learner_level','') or state['cognitive_state']['status'] in ('unknown','weak')
    math=state.get('preferences',{}).get('math_level','unknown')
    high_math=math=='advanced' or (isinstance(math,(int,float)) and not isinstance(math,bool) and math>=.75)
    math_evidence=state.get('assessment_dimensions',{}).get('math',{})
    high_math=high_math or (math_evidence.get('attempts',0)>=4 and (math_evidence.get('rate') or 0)>=.8)
    future=any(contains(message,term) for term in scope.get('future_atoms',[])) if message else False
    introductory=scope.get('teaching_depth') in ('introductory','concept','conceptual') or future
    simplify=feedback in ('confused','formula_confusing','backtrack','rephrase')
    return {'depth':'beginner' if introductory or simplify else 'advanced' if high_math else 'beginner' if beginner else 'intermediate',
            'allow_formulas':bool((high_math or feedback=='deepen') and not introductory and not simplify),
            'allowed_depth':'conceptual' if introductory or simplify else scope.get('teaching_depth','detailed'),
            'exploring_future':future}
