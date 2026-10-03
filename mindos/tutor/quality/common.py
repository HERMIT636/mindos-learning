"""Bounded text helpers. Levels describe presentation, never learner ability."""
import re
from ..protocol import flatten

REVIEW = re.compile(r'回顾|复习|再讲|再解释|换.*说法|重说|不懂|没理解|不理解|不明白|confus|review|rephrase', re.I)
COMPLEX = re.compile(r'为什么|原理|机制|推导|证明|设计|实现|复杂度|why|derive|mechanism', re.I)

def text(response):
    return '\n\n'.join(flatten(b) for b in response['blocks'])

def normalize(value):
    return re.sub(r'[\W_]+', '', value.casefold())

def known(context):
    # Same conservative gate as P6. A prior, self-report or model confidence is not evidence.
    return [a for a in context.get('knowledge_atoms', [])
            if (a.get('knowledge_state', {}).get('graded_evidence_count') or 0) >= 3
            and (a.get('knowledge_state', {}).get('understanding') or 0) >= .8]

def definition_sections(response, term):
    return [flatten(b) for b in response['blocks'] if b['type'] in {'paragraph', 'example'}
            and term.casefold() in flatten(b).casefold()
            and re.search(r'是指|是什么|定义|表示|指的是|means|defined', flatten(b), re.I)]
