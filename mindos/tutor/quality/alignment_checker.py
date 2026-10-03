"""Conservative lexical drift guard; P6 remains the authority for lesson scope."""
import re
from .common import text

class AlignmentChecker:
    def check(self,response,context,strategy,message=''):
        content = text(response).casefold()
        cur = context.get('current_context',{})
        target = cur.get('knowledge_title')
        anchors = [target,cur.get('section_title'),context.get('course',{}).get('title')]
        anchors += [a['title'] for a in context.get('knowledge_atoms',[])]
        anchors += re.findall(r'[A-Za-z][A-Za-z0-9_ -]{1,35}',message)
        anchors = [a.strip().casefold() for a in anchors if a and a.strip()]
        drift = len(content) >= 180 and bool(anchors) and not any(a in content for a in anchors)
        # A long detour into a neighbouring topic must return to the selected target.
        detour = bool(target and target.casefold() not in message.casefold()
                      and len(content) >= 650 and target.casefold() not in content
                      and any(a['title'].casefold() in content for a in context.get('knowledge_atoms',[]) if a['title'] != target))
        return {'aligned':not (drift or detour), 'suggest':'answer_question_then_return_to_current_goal' if drift or detour else ''}
