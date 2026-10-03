"""Presentation depth from actual P0 evidence and the existing ATIE ceiling."""
import re
from .common import text, known, definition_sections, REVIEW, COMPLEX

class DepthChecker:
    def check(self, response, context, strategy, message='', action=None):
        action = action or {}
        content = text(response)
        types = {b['type'] for b in response['blocks']}
        symbolic = bool(re.search(r'\\(?:frac|sum|sqrt|partial|begin)|∑|∂|∇|softmax\s*\([^)]*\)\s*=|\b[QK]\s*[×*]\s*[QK]', content, re.I))
        level = 4 if 'code' in types else 3 if 'formula' in types or symbolic else 2 if types & {'steps','example','diagram','comparison'} or len(content) > 180 else 1
        ceiling = 4 if action.get('allow_formulas') and action.get('allowed_depth') not in {'concept','conceptual','introductory'} else 2
        too_deep = level > ceiling
        # Do not force a long answer for a definition, a guide, or an explicit review.
        too_basic = False
        if COMPLEX.search(message) and not REVIEW.search(message) and strategy.get('name') != 'socratic':
            for atom in known(context):
                chunks = definition_sections(response, atom['title'])
                if sum(map(len, chunks)) >= 100 and not re.search(r'因此|因为|所以|原因|为了|由于|because|therefore', content, re.I):
                    too_basic = True
        return {'too_basic':too_basic, 'too_deep':too_deep, 'response_depth':f'level_{level}',
                'allowed_depth':f'level_{ceiling}', 'suggest':'reduce_formula' if too_deep else 'explain_current_reason' if too_basic else ''}
