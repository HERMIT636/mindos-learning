"""Identity and visual mappings only. Never assesses or updates a learner."""
import base64,json,math
from pathlib import Path
from ..learning.policy import POLICY as LEARNING_POLICY
from ..learning.state import empty,ForgettingService

POLICY=json.loads(Path(__file__).with_name('universe_policy.json').read_text())
LABELS={'unknown':'尚未独立验证','learning':'正在学习','unstable':'建议补强或回忆','stable':'已测内容较稳定','mastered':'已有完整掌握证据'}
RELATIONS={'prerequisite':'前置知识','related':'相关知识','extends':'进一步展开','application':'应用关系','contrast':'对照关系','part_of':'组成关系','causes':'因果关系','similar':'相似关系','implements':'实现关系'}
ALIASES={'applied_in':'application','contrasts':'contrast'}

def star_id(cid,aid):
    return 's-'+base64.urlsafe_b64encode(json.dumps([cid,aid],ensure_ascii=False,separators=(',',':')).encode()).decode().rstrip('=')

def decode_star(value):
    try:
        if not isinstance(value,str) or not value.startswith('s-') or len(value)>500:raise ValueError()
        raw=value[2:];ids=json.loads(base64.b64decode(raw+'='*(-len(raw)%4),altchars=b'-_',validate=True))
        if not isinstance(ids,list) or len(ids)!=2 or any(not isinstance(v,str) or not 1<=len(v)<=100 for v in ids):raise ValueError()
        if star_id(*ids)!=value:raise ValueError()
        return ids
    except (ValueError,UnicodeError,TypeError):raise ValueError('知识星辰编号无效') from None

def visual_state(raw,at,misconceptions=(),read=False):
    state=ForgettingService().project({**empty(''),**(raw or {})},at)
    graded=state['graded_evidence_count'] or 0
    confirmed=any(m.get('status')=='confirmed' for m in misconceptions)
    risks=[]
    if graded and state.get('state')=='review_due':risks.append({'code':'review_due','label':'已到建议回忆时间','estimated':True})
    if confirmed:risks.append({'code':'repeated_confusion','label':'独立检测显示重复混淆，建议换个例子','estimated':False})
    if graded and state.get('transfer') is not None and state['transfer']<LEARNING_POLICY['weak_threshold']:
        risks.append({'code':'transfer_gap','label':'迁移场景需要继续练习','estimated':False})
    if not graded:
        display='learning' if read or state.get('evidence_count') or state.get('state')=='introduced' else 'unknown'
    elif confirmed or state.get('state') in {'unstable','misconception','prerequisite_gap','review_due'}:display='unstable'
    elif state.get('state')=='mastered':display='mastered'
    elif state.get('state')=='stable' or (state.get('successful_reviews',0)>0 and state.get('retention') is not None and state['retention']>=LEARNING_POLICY['weak_threshold'] and (state.get('mastery') or 0)>=LEARNING_POLICY['weak_threshold']):display='stable'
    else:display='learning'
    # These are opacity tokens, never a copy of mastery or a new knowledge score.
    brightness={'unknown':.23,'learning':.48,'unstable':.58,'stable':.78,'mastered':1.0}[display]
    return {'mastery_state':display,'state_label':LABELS[display],'brightness':brightness,
            'knowledge_gap':bool(graded and (state.get('state')=='unstable' or confirmed or any(r['code']=='transfer_gap' for r in risks))),
            'risk_flags':risks,'last_review':state.get('last_reviewed_at'),
            'measured_dimensions':[d for d in LEARNING_POLICY['dimensions'] if state.get(d) is not None],
            'state_basis':'P0 独立答题证据' if graded else '仅有接触记录，未确认掌握' if display=='learning' else '暂无独立答题依据'}

def edge(cid,item):
    original=item['type'];kind=ALIASES.get(original,original)
    weight=item.get('weight',1)
    if not isinstance(weight,(float,int)) or isinstance(weight,bool) or not math.isfinite(weight):weight=1
    return {'source':star_id(cid,item['from']),'target':star_id(cid,item['to']),'relation_type':kind,
            'original_relation_type':original,'label':RELATIONS.get(kind,'已存知识关系'),'weight':weight,
            'boundary':'来自现有课程图谱，关系本身不代表已独立核验。'}
