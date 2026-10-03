"""Strict tutor output contract. Observations are hypotheses, never knowledge state."""
from pathlib import Path
import json
from jsonschema import Draft202012Validator

TYPES = ['paragraph','steps','table','comparison','formula','example','code','question','diagram']
STRATEGIES = ['direct_explanation','step_by_step','analogy','comparison','socratic','debugging','example','summary']
MESSAGE_TYPES = ['question','explanation','hint','diagnosis','reflection','summary','verification']
OBSERVATIONS = ['possible_misconception','possible_gap','strong_understanding','preferred_style','confusion_signal']
def string(n=2000):return {'type':'string','minLength':1,'maxLength':n}
def obj(properties,required=None):return {'type':'object','additionalProperties':False,'properties':properties,'required':required or list(properties)}
def arr(items,n=12,minimum=0):return {'type':'array','items':items,'maxItems':n,'minItems':minimum}
branches=[]
for kind in TYPES:
    props={'type':{'const':kind},'title':{'type':'string','maxLength':100}}
    required=['type']
    if kind=='diagram':
        props['data']=obj({'nodes':arr(obj({'id':string(60),'label':string(100)}),12,1),'edges':arr(obj({'from':string(60),'to':string(60),'label':{'type':'string','maxLength':120}} ,['from','to']),16)})
        required+=['data']
    elif kind=='steps':props['steps']=arr(string(600),10,2);required+=['steps']
    elif kind in {'table','comparison'}:
        props.update(columns=arr(string(100),4,2),rows=arr(arr(string(600),4,2),10,1));required+=['columns','rows']
    else:props['content']=string(4000);required+=['content']
    if kind=='code':props['language']={'enum':['text','python','javascript','sql','json','bash','cpp']}
    branches.append(obj(props,required))
SCHEMA=obj({'learning_relevant':{'type':'boolean'},'strategy':{'enum':STRATEGIES},'message_type':{'enum':MESSAGE_TYPES},'blocks':arr({'oneOf':branches},12,1),
 'related_atom_ids':arr(string(100),6),
 'observations':arr(obj({'atom_id':string(100),'observation_type':{'enum':OBSERVATIONS},'description':string(400),
 'supporting_quote':string(400),'confidence':{'type':'number','minimum':0,'maximum':1}}),3),
 'memories':arr(obj({'memory_type':{'enum':['preference','explanation_style','learning_habit','important_insight']},'content':string(400),'supporting_quote':string(400)}),3)})
VALIDATOR=Draft202012Validator(SCHEMA)
def validate(value,payload):
    import math,re
    VALIDATOR.validate(value)
    if len(json.dumps(value,ensure_ascii=False))>24000:raise ValueError('讲解过长')
    if value['strategy']!=payload['strategy']['name']:raise ValueError('回答策略与本次教学决策不一致')
    forms=[b['type'] for b in value['blocks']]
    required=payload['strategy']['required_blocks']
    if any(t not in forms for t in required):raise ValueError('缺少当前问题需要的讲解形式')
    for b in value['blocks']:
        if b['type'] in {'table','comparison'} and any(len(row)!=len(b['columns']) for row in b['rows']):raise ValueError('表格列数不一致')
        if b['type']=='diagram':
            ids=[n['id'] for n in b['data']['nodes']]
            if len(ids)!=len(set(ids)) or any(e['from'] not in ids or e['to'] not in ids for e in b['data']['edges']):raise ValueError('图示节点或连接无效')
        if b['type']=='formula' and not payload['teaching_action']['allow_formulas']:raise ValueError('当前教学阶段先解释直觉，不直接展开公式')
        if b['type']=='code' and payload['teaching_action']['allowed_depth'] in {'concept','conceptual','introductory'}:raise ValueError('当前教学阶段不展开实现代码')
    if value['strategy']=='socratic' and sum(b['type']=='question' for b in value['blocks'])!=1:raise ValueError('苏格拉底引导每次只问一个问题')
    if value['strategy']=='socratic':
        supporting=[b for b in value['blocks'] if b['type']!='question']
        if len(supporting)>2 or any(b['type'] not in {'paragraph'} for b in supporting) or sum(len(b['content']) for b in supporting)>500:raise ValueError('引导模式只给少量提示，不提前展开完整解答或计算示例')
    if not value['learning_relevant'] and (value['observations'] or value['memories']):raise ValueError('普通闲聊不能生成学习记忆')
    for item in value['observations']:
        if not math.isfinite(item['confidence']):raise ValueError('观察置信度无效')
    for item in value['observations']+value['memories']:
        if item['supporting_quote'] not in payload['message']:raise ValueError('观察和记忆必须引用用户本次原话')
    allowed={a['id'] for a in payload['context']['knowledge_atoms']}
    if any(v not in allowed for v in value['related_atom_ids']) or any(v['atom_id'] not in allowed for v in value['observations']):raise ValueError('关联知识点不在本次上下文中')
    # Reuse the existing scope guard without changing the frozen teaching rules.
    from ..teaching import ContentValidator
    text='\n\n'.join(flatten(b) for b in value['blocks'])
    result=ContentValidator().check(text,payload['context']['teaching_context'])
    if not result['passed']:raise ValueError('讲解超出当前小节范围')
    return value

def flatten(block):
    if block['type']=='diagram':return '\n'.join(n['label'] for n in block['data']['nodes'])+'\n'+'\n'.join(e.get('label','') for e in block['data']['edges'])
    if block['type']=='steps':return '\n'.join(block['steps'])
    if block['type'] in {'table','comparison'}:return '\n'.join([' | '.join(block['columns']),*[' | '.join(row) for row in block['rows']]])
    return block['content']

def prompt(name):return (Path(__file__).resolve().parents[2]/'prompts'/'tutor'/f'{name}.md').read_text(encoding='utf-8')

class ExplanationComposer:
    def compose(self,value):return {'blocks':value['blocks'],'answer':'\n\n'.join(flatten(b) for b in value['blocks'])}
