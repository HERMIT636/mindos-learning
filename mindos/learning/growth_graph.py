"""Goal-specific capability requirements, never estimates of learner ability."""
import json, secrets
from pathlib import Path
from difflib import SequenceMatcher
from jsonschema import Draft202012Validator,ValidationError
from .canonical import KnowledgeMappingEngine, names, normalized, domain
from .final import fingerprint

POLICY = json.loads(Path(__file__).with_name('growth_policy.json').read_text())
TYPES = ['knowledge','application','transfer','tool','practice','meta_skill']
LEVELS = ['understanding','application','transfer']
TEXT = {'type':'string','minLength':1,'maxLength':1200}
CAP_SCHEMA = {'type':'object','additionalProperties':False,'required':['name','type','required_level','importance','description'], 'properties':{
    'name':{**TEXT,'maxLength':120},'type':{'enum':TYPES},'required_level':{'enum':LEVELS},'importance':{'enum':['critical','supporting','optional']},'description':TEXT,
    'concept_type':{'enum':['concept','mechanism','reason','skill']}}}
GRAPH_SCHEMA = {'type':'object','additionalProperties':False,'required':['goal_summary','capabilities','dependencies'],'properties':{
    'goal_summary':TEXT,'capabilities':{'type':'array','minItems':1,'maxItems':32,'items':CAP_SCHEMA},
    'dependencies':{'type':'array','maxItems':96,'items':{'type':'object','additionalProperties':False,'required':['from','to','relation'],'properties':{'from':TEXT,'to':TEXT,'relation':{'enum':['prerequisite','recommended_before','supports']}}}}}}
STAGE_SCHEMA = {'type':'object','additionalProperties':False,'required':['stages'],'properties':{'stages':{'type':'array','minItems':1,'maxItems':16,'items':{'type':'object','additionalProperties':False,'required':['title','objective','capability_ids'],'properties':{'title':{**TEXT,'maxLength':120},'objective':TEXT,'capability_ids':{'type':'array','minItems':1,'maxItems':8,'uniqueItems':True,'items':TEXT}}}}}}

def order(graph, rank=None):
    caps={c['id']:c for c in graph['capabilities']}; edges=[e for e in graph['dependencies'] if e['relation']=='prerequisite']
    incoming={cid:set() for cid in caps}
    for e in edges:
        if e['from'] not in caps or e['to'] not in caps or e['from']==e['to']:raise ValueError('能力依赖引用不存在或指向自身')
        incoming[e['to']].add(e['from'])
    result=[]
    while incoming:
        ready=[cid for cid,p in incoming.items() if not p]
        if not ready:raise ValueError('关键前置能力存在循环，不能保存')
        ready.sort(key=lambda cid:(rank(cid) if rank else 0,list(caps).index(cid)))
        cid=ready[0];result.append(cid);incoming.pop(cid)
        for parents in incoming.values():parents.discard(cid)
    return result

def validate(raw, practice_required=False, allow_no_critical=False):
    try:Draft202012Validator(GRAPH_SCHEMA).validate(raw)
    except ValidationError as exc:raise ValueError("能力结构不符合格式要求："+exc.message[:300]) from exc
    names_seen=[normalized(c['name']) for c in raw['capabilities']]
    if any(not n for n in names_seen) or len(set(names_seen))!=len(names_seen):raise ValueError('能力名称不能为空或重复')
    if not allow_no_critical and not any(c['importance']=='critical' for c in raw['capabilities']):raise ValueError('至少保留一项关键能力')
    if practice_required and not any(c['type']=='practice' and c['importance']=='critical' for c in raw['capabilities']):raise ValueError('项目或比赛目标需要明确的关键实践能力')
    caps=[dict(c,id=secrets.token_urlsafe(12),source='requirement',user_override=False) for c in raw['capabilities']]
    lookup={c['name']:c['id'] for c in caps};edges=[]
    for e in raw['dependencies']:
        if e['from'] not in lookup or e['to'] not in lookup:raise ValueError('依赖必须引用本目标中的能力名称')
        edge={**e,'from':lookup[e['from']],'to':lookup[e['to']]}
        if edge['from']==edge['to']:
            if edge['relation']=='prerequisite':raise ValueError('能力不能依赖自己')
            continue
        if edge not in edges:edges.append(edge)
    graph={'goal_summary':raw['goal_summary'],'capabilities':caps,'dependencies':edges,'ignored_soft_edges':[]}
    hard_order=order(graph);positions={cid:i for i,cid in enumerate(hard_order)}
    # Soft preferences never overturn hard prerequisites; reverse/cyclic soft edges are ignored visibly.
    kept=[]
    for e in edges:
        if e['relation']=='recommended_before' and positions[e['from']]>=positions[e['to']]:graph['ignored_soft_edges'].append(e)
        else:kept.append(e)
    graph['dependencies']=kept;return graph

class TargetCapabilityGenerator:
    def generate(self,goal,model=None):
        failure='';practice=goal['goal_type'] in {'project','competition'}
        if model:
            for attempt in range(2):
                try:
                    payload={'goal':{k:goal.get(k) for k in ['title','description','goal_type','target_level']},'schema':GRAPH_SCHEMA,'repair_reason':failure}
                    raw=model.growth_capabilities(payload) if hasattr(model,'growth_capabilities') else model._json('你是学习目标需求分解助手。只说明实现目标需要什么能力，绝不推测用户现状或输出掌握率。最多12项，区分critical/supporting/optional；项目和比赛需关键practice。依赖从前置指向后续，不得循环。知识能力名称具体，concept_type可选。返回给定schema的JSON。',json.dumps(payload,ensure_ascii=False),max_tokens=4200,diagnostic_stage='growth_capabilities')
                    graph=validate(raw,practice);graph['source']='model_requirement';return graph
                except Exception as exc:
                    failure=str(exc)
                    if hasattr(model,'_diagnostic'):model._diagnostic({'stage':'growth_capability_validation','attempt':attempt+1,'failure_reason':failure})
        # Conservative editable fallback; no invented domain curriculum or learner scores.
        name=goal['title'][:100];level='understanding' if goal['target_level'] in {'overview','understanding'} else 'transfer' if goal['target_level']=='transfer' else 'application'
        caps=[{'name':name+'基础','type':'knowledge','required_level':level,'importance':'critical','description':goal['description'] or goal['title']}]
        if practice:caps.append({'name':name+'实践验证','type':'practice','required_level':'transfer','importance':'critical','description':'围绕目标完成一次独立实践，并保留可审查的结果。'})
        graph=validate({'goal_summary':'保守草稿，请审查并补充具体能力。','capabilities':caps,'dependencies':[]},practice);graph.update(source='editable_rule_fallback',failure_reason=failure[:1000]);return graph

class GoalCapabilityMatcher:
    """P3 recall vocabulary and schema-checked judge, plus conservative program gates."""
    def __init__(self,store):self.store=store
    def match(self,user,goal,graph,model=None):
        with self.store.connect() as db:
            candidates=[dict(r) for r in db.execute("SELECT * FROM canonical_knowledge_atoms WHERE user_id=? AND status='active'",(user,))]
        result=[];calls=0;goal_domain=domain({'title':goal['title'],'goal':goal['description']})
        engine=KnowledgeMappingEngine(self.store)
        for cap in graph['capabilities']:
            if cap['type'] not in {'knowledge','application','transfer'}:continue
            recalled=[]
            for c in candidates:
                strong=bool(names(cap['name'])&({c['normalized_name']}|{normalized(a) for a in json.loads(c['aliases_json'])}))
                similarity=SequenceMatcher(None,normalized(cap['description']),normalized(c['description'])).ratio()
                if strong or c['domain']==goal_domain and similarity>=.7:recalled.append((int(strong)*2+similarity,c,strong,similarity))
            for _,c,strong,similarity in sorted(recalled,key=lambda r:r[0],reverse=True)[:3]:
                ctx={'title':cap['name'],'type':cap.get('concept_type','unspecified'),'summary':cap['description'],'why':goal['description'],'depth':LEVELS.index(cap['required_level'])+1,'domain':goal_domain,'chapter':goal['title'],'objective':graph['goal_summary'],'neighbors':[],'goal':goal['description']}
                judgment=None
                if model and calls<8:
                    calls+=1;judgment=engine.judge(model,ctx,{k:c[k] for k in ['canonical_name','description','concept_type','domain']})
                compatible=c['domain']==goal_domain and cap.get('concept_type')==c['concept_type']
                same=judgment is not None and judgment['relationship']=='same' and not judgment['conflicts']
                exact=strong and compatible and similarity>=.97
                status='verified' if strong and compatible and similarity>=.7 and (same and judgment['confidence']>=.9 or judgment is None and exact) else 'rejected' if judgment and judgment['relationship'] in {'different','broader','narrower','related'} else 'candidate'
                result.append({'id':secrets.token_urlsafe(12),'capability_id':cap['id'],'canonical_atom_id':c['id'],'canonical_fingerprint':c['semantic_fingerprint'],'status':status,'confidence':judgment['confidence'] if judgment else .95 if exact else .65,'source':'p3_semantic_matcher','relationship':judgment['relationship'] if judgment else 'same' if exact else 'ambiguous','reasons':judgment['reasons'] if judgment else ['名称仅用于召回；定义、领域和类型需同时一致。']})
                if status=='verified':break
        return result
