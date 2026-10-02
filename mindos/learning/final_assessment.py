"""Bounded, deterministic whole-course plans and validated novel scenarios."""
import json,re,unicodedata
from pathlib import Path
from difflib import SequenceMatcher
from .policy import POLICY,date
FINAL_POLICY=json.loads(Path(__file__).with_name('final_policy.json').read_text())
FINAL_KINDS={'concept':'final_concept','application':'final_application','transfer':'final_transfer','retention':'final_retention'}

def criticality(course,graph):
    atoms=[a for a in graph.get('atoms',[]) if a['section']<=course['current_ordinal'] and a.get('quality_status')!='deprecated']
    ids={a['id'] for a in atoms};dependents={a:set() for a in ids}
    for e in graph.get('edges',[]):
        if e['type']=='prerequisite' and e['from'] in ids and e['to'] in ids:dependents[e['from']].add(e['to'])
    max_degree=max((len(v) for v in dependents.values()),default=1) or 1;cores=set()
    for section in course['sections']:
        names=section.get('core_atoms',[]);names=json.loads(names) if isinstance(names,str) else names
        cores.update(str(n).casefold() for n in names)
    scores={a['id']:round(FINAL_POLICY['core_score']*(a['title'].casefold() in cores)+FINAL_POLICY['dependency_score']*len(dependents[a['id']])/max_degree+FINAL_POLICY['depth_score']*a.get('depth',1)/5,4) for a in atoms}
    critical={k for k,v in scores.items() if v>=FINAL_POLICY['criticality_threshold']}
    # Sparse old metadata still has a representative core in each section.
    for ordinal in {a['section'] for a in atoms}:
        group=[a for a in atoms if a['section']==ordinal]
        if not any(a['id'] in critical for a in group):critical.add(max(group,key=lambda a:(scores[a['id']],-atoms.index(a)))['id'])
    return atoms,scores,critical

class FinalAssessmentPlanner:
    def plan(self,course,graph,states,misconceptions,at,reassessment=None):
        atoms,scores,critical=criticality(course,graph)
        if not atoms:return {'available':False,'targets':[],'blueprint':[],'rationale':['当前没有可检测的课程知识索引。可先生成索引，章节成绩继续保留。']}
        mis={m['atom_id'] for m in misconceptions if m['status']=='confirmed'}
        def rank(a):
            s=states[a['id']]
            return (a['id'] not in mis,a['id'] not in critical,not(s['mastery'] is not None and s['mastery']<FINAL_POLICY['critical_atom_floor']),s['transfer'] is not None,s['confidence']>=FINAL_POLICY['confidence_threshold'],-scores[a['id']],a['section'],a['id'])
        ranked=sorted(atoms,key=rank);selected=ranked[:max(FINAL_POLICY['concept_questions'],FINAL_POLICY['application_questions'],FINAL_POLICY['transfer_questions'])+1]
        stable=[a for a in atoms if a['id'] in critical and states[a['id']]['mastery'] is not None and states[a['id']]['mastery']>=FINAL_POLICY['course_mastery_threshold'] and states[a['id']]['confidence']>=FINAL_POLICY['confidence_threshold'] and all(states[a['id']][d] is not None and states[a['id']][d]>=FINAL_POLICY['critical_atom_floor'] for d in ('understanding','application','transfer'))]
        if stable and not any(a['id']==stable[0]['id'] for a in selected):selected[-1]=stable[0]
        blueprint=[];seen=set()
        def add(atom,dimension,reason,stage=1,repeat=False):
            if not repeat and (atom,dimension) in seen or len(blueprint)>=FINAL_POLICY['max_questions']:return
            seen.add((atom,dimension));blueprint.append({'id':f'{dimension}-{len(blueprint)+1}','atom_id':atom,'dimension':dimension,'kind':FINAL_KINDS[dimension],'stage':stage,'status':'pending','reason':reason})
        # Delayed recall must precede same-session teaching or another test of it.
        due=[a for a in ranked if states[a['id']]['last_graded_evidence_at'] and (at-date(states[a['id']]['last_graded_evidence_at'])).total_seconds()>=POLICY['minimum_delay_hours']*3600 and (states[a['id']]['retention'] is None or states[a['id']].get('state')=='review_due')]
        for a in due[:FINAL_POLICY['retention_questions']]:add(a['id'],'retention','独立延迟回忆；若期间学习或求助，仍按 P0 规则处理')
        if reassessment:
            for target in reassessment:
                for dimension in target['required_verification']:
                    if dimension=='retention':
                        s=states[target['atom_id']]
                        if not s['last_graded_evidence_at'] or (at-date(s['last_graded_evidence_at'])).total_seconds()<POLICY['minimum_delay_hours']*3600:continue
                    add(target['origin_atom_id'] if dimension=='transfer' else target['atom_id'],dimension,'补强后重新验证，不能以看完讲解代替答题')
                if target['origin_atom_id']!=target['atom_id']:
                    add(target['origin_atom_id'],'application','前置知识补强后，重新验证原来的高级目标')
        else:
            for dimension,count in [('concept',FINAL_POLICY['concept_questions']),('application',FINAL_POLICY['application_questions']),('transfer',FINAL_POLICY['transfer_questions'])]:
                for index in range(count):
                    a=selected[(index+(1 if dimension=='application' else 0))%len(selected)]
                    add(a['id'],dimension,'重复混淆优先复核' if a['id'] in mis else '稳定核心也需要代表性验证' if a in stable else '关键结构、证据覆盖与薄弱情况共同决定',repeat=True)
        if not reassessment:
            index=0
            while len(blueprint)<min(FINAL_POLICY['min_questions'],FINAL_POLICY['max_questions']):
                add(selected[index%len(selected)]['id'],('concept','application')[index%2],'按最低代表性题量，用另一道新题复核',repeat=True);index+=1
        if not blueprint:return {'available':False,'targets':[],'blueprint':[],'rationale':['本次只需要延迟记忆验证，但刚有答题或补强。请按已有复习建议间隔后再试，不作即时长期记忆测试。']}
        targets=list(dict.fromkeys(q['atom_id'] for q in blueprint))
        return {'available':True,'targets':targets,'blueprint':blueprint,'critical_atoms':sorted(critical),'criticality':scores,
                'estimated_minutes':len(blueprint)*FINAL_POLICY['estimated_minutes_per_question'],
                'rationale':['按关键依赖、核心知识、薄弱与证据覆盖抽样，不逐个重考全部原子。','同时抽取已有稳定表现的核心；最多两个阶段，第二阶段只补边界证据。']}

QUESTION_SCHEMA={'type':'object','additionalProperties':False,'required':['questions'],'properties':{'questions':{'type':'array','minItems':1,'maxItems':1,'items':{'type':'object','additionalProperties':False,
 'required':['prompt','choices','answer','explanation','atom_ids','assessment_type'],
 'properties':{'prompt':{'type':'string','minLength':8,'maxLength':800},'choices':{'type':'object','required':list('abcd'),'additionalProperties':False,'properties':{k:{'type':'string','minLength':1,'maxLength':1000} for k in 'abcd'}},'answer':{'enum':list('abcd')},'explanation':{'type':'string','minLength':10,'maxLength':2000},'atom_ids':{'type':'array','minItems':1,'maxItems':1,'items':{'type':'string'}},'assessment_type':{'enum':['concept','application']},'misconceptions':{'type':'object','maxProperties':3}}}}}}
TRANSFER_SCHEMA={'type':'object','additionalProperties':False,'required':['scenario','question','target_atom_ids','rubric','expected_concepts','difficulty','novelty_reason','choices','answer','explanation'],
 'properties':{'scenario':{'type':'string','minLength':20,'maxLength':1600},'question':{'type':'string','minLength':8,'maxLength':800},'target_atom_ids':{'type':'array','minItems':1,'maxItems':3,'uniqueItems':True,'items':{'type':'string'}},
 'rubric':{'type':'array','minItems':2,'maxItems':5,'items':{'type':'object','additionalProperties':False,'required':['id','criterion'],'properties':{'id':{'type':'string','pattern':'^[a-z][a-z0-9_]{1,40}$'},'criterion':{'type':'string','minLength':4,'maxLength':400}}}},
 'expected_concepts':{'type':'array','minItems':1,'maxItems':5,'items':{'type':'string','minLength':1,'maxLength':200}},'difficulty':{'enum':['basic','standard','advanced']},'novelty_reason':{'type':'string','minLength':12,'maxLength':500},
 'choices':{'type':'object','required':list('abcd'),'additionalProperties':False,'properties':{k:{'type':'string','minLength':1,'maxLength':1000} for k in 'abcd'}},'answer':{'enum':list('abcd')},'explanation':{'type':'string','minLength':10,'maxLength':2000}}}

def normalized(value):
    value=unicodedata.normalize('NFKC',value).casefold();value=re.sub(r'\b[a-z]\b','v',value);value=re.sub(r'\d+(?:\.\d+)?','n',value)
    return ''.join(c for c in value if c.isalnum())

def novelty(scenario,question,previous):
    candidate=normalized(scenario+' '+question);grams={candidate[i:i+2] for i in range(max(0,len(candidate)-1))};maximum=0.;keyword=0.
    for old in previous:
        old=normalized(old)
        if not old:continue
        similarity=SequenceMatcher(None,candidate,old,autojunk=False).ratio();maximum=max(maximum,similarity)
        oldgrams={old[i:i+2] for i in range(max(0,len(old)-1))};overlap=len(grams&oldgrams)/len(grams|oldgrams) if grams|oldgrams else 0;keyword=max(keyword,overlap)
        if len(candidate)>=20 and candidate in old:maximum=1.
    return {'passed':maximum<FINAL_POLICY['novelty_similarity_threshold'] and keyword<FINAL_POLICY['novelty_keyword_threshold'],'normalized_similarity':round(maximum,4),'keyword_overlap':round(keyword,4),'rule':'lexical-novelty-v1','boundary':'文本重复防护不能独立证明语义陌生或题目事实正确。'}

class TransferAssessmentGenerator:
    def generate(self,model,course,atom,previous):
        from jsonschema import Draft202012Validator
        failure=''
        for attempt in range(2):
            try:
                raw=model.final_transfer(course,atom,previous,failure);Draft202012Validator(TRANSFER_SCHEMA).validate(raw)
                if raw['target_atom_ids']!=[atom['id']]:raise ValueError('迁移场景关联了本次目标之外的知识点')
                if len({r['id'] for r in raw['rubric']})!=len(raw['rubric']):raise ValueError('迁移标准编号重复')
                check=novelty(raw['scenario'],raw['question'],previous)
                if not check['passed']:raise ValueError('迁移场景与课程题目或讲解高度重复，不能只改数字或变量')
                questions,answers=model._validated_questions({'questions':[{'prompt':raw['question'],'choices':raw['choices'],'answer':raw['answer'],'explanation':raw['explanation'],'atom_ids':raw['target_atom_ids'],'assessment_type':'transfer'}]},[],{atom['id']},required=True,count=1)
                questions[0].update(scenario=raw['scenario'],difficulty=raw['difficulty'])
                answers[0].update(rubric=raw['rubric'],expected_concepts=raw['expected_concepts'],novelty_reason=raw['novelty_reason'],novelty_check=check)
                return questions,answers
            except Exception as exc:
                failure=str(exc)
                if hasattr(model,'_diagnostic'):model._diagnostic({'stage':'final_transfer_validation','attempt':attempt+1,'failure':failure})
        raise ValueError('当前无法完成迁移能力检测，仍保留未测：'+failure)
