"""Recent same-course teaching only; explicit reviews and remediation stay available."""
from difflib import SequenceMatcher
from .common import text, normalize, known, definition_sections, REVIEW, COMPLEX

class RepetitionChecker:
    def check(self, response, context, strategy, history, message='', limit=5):
        if REVIEW.search(message) or strategy.get('name') in {'summary','socratic','example'}:
            return {'duplicate':False, 'repeated_topic':''}
        current = normalize(text(response))
        previous = [h for h in history if h.get('role') == 'assistant'][-limit:]
        for h in previous:
            before = normalize(h.get('content',''))
            if len(current) >= 80 and len(before) >= 80 and SequenceMatcher(None,current[:6000],before[:6000],autojunk=False).ratio() >= .92:
                return {'duplicate':True, 'repeated_topic':context.get('current_context',{}).get('knowledge_title') or '当前问题'}
        if COMPLEX.search(message):
            for atom in known(context):
                chunks = definition_sections(response,atom['title'])
                if sum(map(len,chunks)) >= 180:
                    return {'duplicate':True, 'repeated_topic':atom['title']}
        return {'duplicate':False, 'repeated_topic':''}
