"""Execute Teaching Actions through a model; validate typed blocks before saving."""
import json
import re
from ..model import ModelUnavailable, ModelStructuredOutputError
from ..teaching import TeachingOrchestrator, ContentValidator
from .atie_engine import ATIEEngine
from .teaching_state import LearningStateManager
from .intervention_manager import feedback_from_message
from .presentation_controller import resolve_presentation

BLOCK_TYPES={'text','question','analogy','concept','flow','diagram','comparison','formula','example','checkpoint'}
ROW_HEADERS={'性质','比较方面','比较项','对比项','方面','项目','维度','指标','特征','特点','属性','条目','名称','类型','术语','知识点','字段',
             'aspect','property','properties','feature','features','criterion','criteria','item','dimension','metric','name','type'}

def normalize_blocks(packet):
    """Unambiguous layout conversions only: never invent missing table cells."""
    if not isinstance(packet,dict) or not isinstance(packet.get('blocks'),list):return packet,[]
    import copy
    result=copy.deepcopy(packet);changes=[]
    for index,block in enumerate(result['blocks']):
        if not isinstance(block,dict) or block.get('type')!='comparison':continue
        data=block.get('data')
        if not isinstance(data,dict):continue
        columns=data.get('columns');rows=data.get('rows')
        if (not isinstance(columns,list) or not 3<=len(columns)<=5 or not isinstance(columns[0],str)
                or columns[0].strip().casefold() not in ROW_HEADERS or not isinstance(rows,list) or not rows):continue
        if data.get('label_header') not in (None,columns[0]):continue
        if all(isinstance(row,dict) and isinstance(row.get('label'),str) and row['label'].strip()
               and isinstance(row.get('values'),list) and len(row['values'])==len(columns)-1 for row in rows):
            data['label_header']=columns[0];data['columns']=columns[1:]
            changes.append({'block_index':index,'conversion':'comparison_row_header','original_column_count':len(columns),
                            'value_column_count':len(columns)-1})
    return result,changes

def text(value,limit=8000):
    if not isinstance(value,str) or not value.strip() or len(value)>limit:raise ValueError('内容块文字为空或过长')
    return value.strip()

def validate_blocks(packet,action):
    if not isinstance(packet,dict) or not isinstance(packet.get('blocks'),list) or not 1<=len(packet['blocks'])<=24:raise ValueError('请返回1—24个教学内容块')
    blocks=[]
    for raw in packet['blocks']:
        if not isinstance(raw,dict) or raw.get('type') not in BLOCK_TYPES:raise ValueError('内容块类型无效')
        kind=raw['type'];block={'type':kind}
        if 'title' in raw:block['title']=text(raw['title'],100)
        if 'content' in raw:block['content']=text(raw['content'])
        if re.search(r'(?m)^\s*#{1,6}\s|```',block.get('content','')):raise ValueError('教学块应使用普通文字，不要输出Markdown文章或代码围栏')
        data=raw.get('data',{})
        if not isinstance(data,dict):raise ValueError('内容块数据格式无效')
        if kind=='flow':
            steps=data.get('steps')
            if not isinstance(steps,list) or not 2<=len(steps)<=12:raise ValueError('流程图需要2—12个步骤')
            block['data']={'steps':[{'label':text(s.get('label'),100),**({'description':text(s['description'],1000)} if 'description' in s else {})} if isinstance(s,dict) else {'label':text(s,100)} for s in steps]}
        elif kind=='diagram':
            nodes=data.get('nodes');edges=data.get('edges',[])
            if not isinstance(nodes,list) or not 1<=len(nodes)<=16 or not isinstance(edges,list) or len(edges)>24:raise ValueError('结构图节点或关系过多')
            normalized=[]
            for n in nodes:
                if not isinstance(n,dict):raise ValueError('结构图节点无效')
                identifier=text(n.get('id'),40)
                if not re.fullmatch(r'[A-Za-z0-9_-]+',identifier):raise ValueError('结构图节点编号无效')
                normalized.append({'id':identifier,'label':text(n.get('label'),160)})
            ids={n['id'] for n in normalized}
            if len(ids)!=len(normalized):raise ValueError('结构图节点编号重复')
            links=[]
            for e in edges:
                if not isinstance(e,dict) or not isinstance(e.get('from'),str) or not isinstance(e.get('to'),str) or e['from'] not in ids or e['to'] not in ids:raise ValueError('结构图关联了不存在的节点')
                links.append({'from':e['from'],'to':e['to'],**({'label':text(e['label'],160)} if e.get('label') else {})})
            block['data']={'nodes':normalized,'edges':links}
        elif kind=='comparison':
            columns=data.get('columns');rows=data.get('rows')
            if not isinstance(columns,list) or not 2<=len(columns)<=4 or not isinstance(rows,list) or not 1<=len(rows)<=10:raise ValueError('比较表结构无效')
            result=[]
            for row_index,row in enumerate(rows):
                if not isinstance(row,dict) or not isinstance(row.get('values'),list):raise ValueError('比较表行数据无效')
                if len(row['values'])!=len(columns):raise ValueError(f'比较表第{row_index+1}行有{len(row["values"])}个值，但columns有{len(columns)}列；columns只包含值列，行标签由label单独提供，不要把行标签表头放进columns')
                result.append({'label':text(row.get('label'),100),'values':[text(v,500) for v in row['values']]})
            block['data']={'columns':[text(v,100) for v in columns],'rows':result}
            if 'label_header' in data:block['data']['label_header']=text(data['label_header'],100)
        elif kind=='formula':
            if not action['allow_formulas']:raise ValueError('当前教学策略要求先建立直觉，不允许公式块')
            symbols=data.get('symbols',[]);steps=data.get('steps',[])
            if not isinstance(symbols,list) or not 1<=len(symbols)<=16 or any(not isinstance(s,dict) for s in symbols) or not isinstance(steps,list) or len(steps)>12:raise ValueError('公式需要有效的符号说明')
            block['data']={'symbols':[{'symbol':text(s.get('symbol'),80),'meaning':text(s.get('meaning'),300)} for s in symbols],'steps':[text(s,1000) for s in steps]}
            block['content']=text(raw.get('content'))
        else:block['content']=text(raw.get('content'))
        blocks.append(block)
    if len(json.dumps(blocks,ensure_ascii=False))>40000:raise ValueError('教学内容过长')
    types=[b['type'] for b in blocks];cursor=0
    for required in action['presentation']:
        try:cursor=types.index(required,cursor)+1
        except ValueError as exc:raise ValueError('内容没有按教学策略组织：缺少或顺序不符 '+required) from exc
    if action['structure_level']<=1 and (len(blocks)>4 or any(t in types for t in ['diagram','flow','comparison','formula'])):raise ValueError('简单问题不应生成复杂教学流程')
    flat=flatten_blocks(blocks)
    if not action['allow_formulas'] and re.search(r'softmax\s*\(|∑|\\(?:frac|sum)|\b[A-Za-z][A-Za-z0-9_]*\s*=\s*[A-Za-z0-9]',flat,re.I):raise ValueError('当前策略不允许直接给出推导，请改用类比或例子')
    return blocks

def flatten_blocks(blocks):
    parts=[]
    for b in blocks:
        values=[b.get('title',''),b.get('content','')];data=b.get('data',{})
        if b['type']=='flow':values += [s['label']+'：'+s.get('description','') for s in data['steps']]
        if b['type']=='diagram':
            labels={n['id']:n['label'] for n in data['nodes']};values+=list(labels.values())
            values += [labels[e['from']]+' → '+labels[e['to']]+('：'+e['label'] if e.get('label') else '') for e in data['edges']]
        if b['type']=='comparison':values += [' / '.join(data['columns'])]+[r['label']+'：'+' / '.join(r['values']) for r in data['rows']]
        if b['type']=='formula':values += [s['symbol']+'：'+s['meaning'] for s in data['symbols']]+data['steps']
        parts.append('\n'.join(v for v in values if v))
    return '\n\n'.join(parts)

class ContentGenerator:
    def __init__(self,store):self.store=store;self.states=LearningStateManager(store);self.engine=ATIEEngine();self.scope=TeachingOrchestrator(store)

    def prepare(self,user,cid,section,question='',atom_id=None,mode='lesson',feedback=None,request_id=None):
        kind=feedback or feedback_from_message(question)
        if kind:self.store.save_teaching_feedback(user,cid,section['id'],kind,atom_id,request_id)
        from ..learning.personal import InheritedKnowledgePrior
        InheritedKnowledgePrior(self.store).refresh(user,cid)
        state,knowledge=self.states.read(user,cid,section['ordinal'],atom_id)
        scope=self.scope.context(user,cid,section['id'])
        action=self.engine.decide(state,knowledge,scope,question,mode,kind)
        # A backtrack deliberately teaches prerequisites in detail; validation must
        # use the same scope that is sent to the content generator.
        if action['action']=='BACKTRACK':
            scope={**scope,'core_atoms':list(dict.fromkeys(scope['core_atoms']+action['backtrack_targets']))}
            scope['related_atoms']=[x for x in scope['related_atoms'] if x not in scope['core_atoms']]
            scope['exposure']=[{'knowledge':x,'level':level} for level,group in ((3,scope['core_atoms']),(1,scope['related_atoms']),(0,scope['future_atoms'])) for x in group]
            action={**action,'core_atoms':scope['core_atoms'],'related_atoms':scope['related_atoms']}
        return state,knowledge,scope,action

    def validate(self,packet,action,scope):
        blocks=validate_blocks(packet,action)
        result=ContentValidator().check(flatten_blocks(blocks),scope)
        if not result['passed']:raise ValueError('; '.join(i['message'] for i in result['issues']))
        return blocks,result

    def execute(self,model,payload,action,scope,request):
        packet=None;failures=[];repair_reason='';normalizations=[]
        for attempt in range(2):
            try:
                packet=request() if attempt==0 else model.repair_teaching_blocks(payload,packet,repair_reason)
            except ModelStructuredOutputError as exc:
                packet={'unparsed_model_output':exc.raw}
                repair_reason='JSON语法或对象格式无效：'+exc.reason
                failure=exc
            else:
                packet,changes=normalize_blocks(packet)
                normalizations.extend(changes)
                if changes and hasattr(model,'_diagnostic'):model._diagnostic({'stage':'atie_normalization','attempt':attempt+1,'changes':changes})
                try:
                    effective_action=resolve_presentation(packet,action)
                    blocks,validation=self.validate(packet,effective_action,scope);break
                except (ValueError,TypeError,KeyError,AttributeError) as exc:
                    repair_reason=str(exc);failure=exc
            failures.append(repair_reason)
            if hasattr(model,'_diagnostic'):model._diagnostic({'stage':'atie_validation','attempt':attempt+1,'failure':repair_reason,'action':action})
            if attempt==1:raise ModelUnavailable('教学内容未通过检查，自动修订后仍有问题：'+repair_reason[:300]+'。已停止保存，请重试。') from failure
        related=packet.get('related_atom_ids',[])
        content=flatten_blocks(blocks)
        if len(content)>30000:raise ModelUnavailable('教学内容过长，请重试生成')
        if hasattr(model,'_diagnostic'):model._diagnostic({'stage':'atie_presentation','source':effective_action['presentation_source'],
            'forms':effective_action['presentation'],'intent':effective_action.get('presentation_intent'),
            'reason':effective_action.get('presentation_reason')})
        return {'blocks':blocks,'content':content,'teaching_action':effective_action,
                'learning_state':payload['learning_state'],'related_atom_ids':related,
                'validation':{**validation,'repair_attempts':len(failures),'initial_issues':failures,'normalizations':normalizations}}

    def lesson(self,user,course,section,model,mastery,weak):
        state,knowledge,scope,decision=self.prepare(user,course['id'],section)
        scope['material_scope']=[{'source_id':d['id'],'block_ids':[b['id'] for b in d['blocks']],'total_blocks':d.get('total_blocks')} for d in course.get('teaching_materials',[])]
        payload={'mode':'lesson','course':course['title'],'goal':course['goal'],'section_title':section['title'],
                 'section_objective':section['objective'],'section_number':section['ordinal'],'learner_level':course['learner_level'],
                 'teaching_context':scope,'teaching_action':decision,'learning_state':state,'knowledge_context':knowledge,
                 'learning_loop':state.get('learning_loop',{}),'knowledge_atoms':section.get('knowledge_atoms',[]),'atom_evidence':section.get('atom_evidence',[]),
                 'earlier_missed_questions':weak,'mastery':mastery,'source_policy':course['source_policy'],
                 'source_conflicts':course.get('source_conflicts',[]),'course_materials':course.get('teaching_materials',[])}
        package=self.execute(model,payload,decision,scope,lambda:model.generate_teaching_blocks(payload))
        return package,scope

    def followup(self,user,course,section,model,turns,question,feedback=None,reference=""):
        state,knowledge,scope,decision=self.prepare(user,course['id'],section,question,mode='followup',feedback=feedback)
        payload={'mode':'followup','course':course['title'],'section_title':section['title'],'question':question,
                 'reference_explanation':reference,'history':turns[-8:],'teaching_action':decision,'teaching_context':scope,'learning_state':state,'knowledge_context':knowledge,
                 'source_policy':course['source_policy'],'source_conflicts':course.get('source_conflicts',[]),
                 'course_materials':course.get('teaching_materials',[])}
        return self.execute(model,payload,decision,scope,lambda:model.generate_teaching_blocks(payload))

    def assistant(self,user,course,section,model,context,question,history,route,search,feedback=None,request_id=None):
        atom=context['current_context']['knowledge_atom_id']
        state,knowledge,scope,decision=self.prepare(user,course['id'],section,question,atom,'assistant',feedback,request_id)
        context.update(learning_state=state,knowledge_context=knowledge,teaching_action=decision)
        payload={'mode':'assistant','learning_context':context,'question':question,'learning_state':state,
                 'teaching_action':decision,'teaching_context':scope,'history':history,'search':search}
        return self.execute(model,payload,decision,scope,lambda:model.answer_course_tutor(context,question,history,route,search))
