"""Requirement-driven search tasks; conservative coverage and explicit fallbacks."""
from __future__ import annotations
import copy
import json
from contextvars import ContextVar
import os
import re
import secrets
import threading
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

_LOCK = threading.Lock()
_DIAGNOSTIC_CONTEXT = ContextVar("discovery_diagnostic", default={})

def log_event(event, path=None):
    # Local diagnostic data only: never returned by model/settings APIs.
    destination = Path(path) if path else Path(__file__).resolve().parents[1]/'data'/'discovery-diagnostics.jsonl'
    entry = {'time':datetime.now(timezone.utc).isoformat(), **_DIAGNOSTIC_CONTEXT.get(), **event}
    destination.parent.mkdir(parents=True, exist_ok=True)
    with _LOCK:
        fd = os.open(destination, os.O_WRONLY|os.O_CREAT|os.O_APPEND, 0o600)
        with os.fdopen(fd, 'a', encoding='utf-8') as stream:
            stream.write(json.dumps(entry, ensure_ascii=False)+'\n')

def normalize_queries(values, course=None, target='', intent='', enhance=False):
    """No keyword length threshold; keep letters/numbers, normalize spaces and duplicates."""
    if not isinstance(values, list):return []
    result=[];seen=set()
    for value in values:
        if not isinstance(value,str):continue
        value=unicodedata.normalize('NFKC', value)
        value=''.join(' ' if c.isspace() else c for c in value if c.isspace() or not unicodedata.category(c).startswith('C'))
        value=re.sub(r'\s+', ' ',value).strip()
        if not any(c.isalnum() for c in value):continue
        if enhance and (value.casefold()==target.casefold() or value.casefold()==str((course or {}).get('title','')).casefold()):
            context=(course or {}).get('title','')
            value=' '.join(dict.fromkeys(v for v in [context,target,intent] if v))
        key=value.casefold()
        if key not in seen:result.append(value);seen.add(key)
    return result

def course_context(title, goal, level='零基础', policy='balanced', previous=None, feedback=''):
    sections=(previous or {}).get('sections') or [{'title':title,'objective':goal}]
    return {'title':title,'goal':goal,'learner_level':level,'source_policy':policy,
            'revision_request':feedback,'sections':[dict(s,ordinal=i+1) for i,s in enumerate(sections)]}

def local_requirements(course, documents, selections):
    """Fallback coverage is conservative: a real block mentioning the target, no mastery inference."""
    result=[]
    for i, section in enumerate(course['sections'][:16]):
        target=section['title']; evidence=[]
        for doc in documents:
            for block in doc['metadata']['blocks']:
                if block['id'] not in selections[doc['id']]:continue
                # Heading alone is not a definition; short Latin terms must be whole words.
                match=re.search(r'(?<![A-Za-z0-9])'+re.escape(target)+r'(?![A-Za-z0-9])',block['text'],re.I)
                if match and block.get('kind')!='heading' and len(block['text'])>=12:
                    start=max(0,match.start()-100);quote=block['text'][start:start+500]
                    evidence=[{'document_id':doc['id'],'block_id':block['id'],'quote':quote}];break
            if evidence:break
        result.append({'title':target,'section':i+1,'aspect':'definition','reason':'本地回退：按课程小节检查原文提及，覆盖程度仍需审查',
                       'evidence':evidence,'query':''})
    return {'requirements':result}

INTENTS={'definition':'基础定义 教材','prerequisite':'前置知识 直观解释','example':'例题 解题方法',
         'current':'最新官方说明','verification':'官方资料 定义核对','relation':'概念关系 教材'}

def attach_known_coverage(raw, documents, selections, graph, batches):
    """Reuse only matching, cited definitions; graph/candidate presence alone proves nothing."""
    from .discovery import reference
    result=copy.deepcopy(raw)
    if not isinstance(result,dict) or not isinstance(result.get('requirements'),list):return result
    by_id={d['id']:d for d in documents}
    atoms=list(graph.get('atoms',[]))+[c for b in batches for c in b.get('result',{}).get('candidates',[])]
    for unit in result['requirements']:
        if not isinstance(unit,dict) or unit.get('evidence') or unit.get('aspect')!='definition':continue
        title=str(unit.get('title','')).strip().casefold()
        for atom in atoms:
            if str(atom.get('title','')).strip().casefold()!=title or atom.get('quality_status')=='deprecated':continue
            refs=[]
            for ref in atom.get('source_reference',[]):
                doc=by_id.get(ref.get('document_id'))
                if doc is None:continue
                try:refs.append(reference(doc,ref,selections[doc['id']]))
                except ValueError:continue
            if refs:
                unit['evidence']=refs[:4];break
    return result


def fallback_queries(requirement, course):
    """Three ordered tiers, independent of the LLM and query schema."""
    target=requirement.get('title','');intent=INTENTS.get(requirement.get('aspect'),'基础教材')
    if normalize_queries([target]):
        values=normalize_queries([requirement.get('query')],course,target,intent,True)
        if not values:values=normalize_queries([f"{target} {intent}"],course,target,intent,True)
        if values:return values,'knowledge_requirement'
    if normalize_queries([course.get('goal','')]):
        values=normalize_queries([f"{course['title']} {course['goal']} {course['learner_level']} {intent}"])
        if values:return values,'course_information'
    return normalize_queries([course['title']]),'course_title'


def build_search_plan(model, course, documents, selections, graph, batches):
    context={'trace_id':secrets.token_urlsafe(12),'course_id':course.get('id'),'course_title':course['title']}
    token=_DIAGNOSTIC_CONTEXT.set(context)
    try:return _build_search_plan(model,course,documents,selections,graph,batches)
    finally:_DIAGNOSTIC_CONTEXT.reset(token)


def _build_search_plan(model, course, documents, selections, graph, batches):
    # Import locally to avoid the production/discovery/planner import cycle.
    from .discovery import normalize_plan
    identifier=_DIAGNOSTIC_CONTEXT.get()['trace_id'];events=[]
    def record(stage, **data):
        entry={'trace_id':identifier,'course_id':course.get('id'),'course_title':course['title'],'stage':stage,**data}
        events.append({k:v for k,v in entry.items() if k not in ('raw','parsed')})
        if hasattr(model,'_diagnostic'):model._diagnostic(entry)
        else:log_event(entry, getattr(model,'diagnostic_path',None))
    try:
        raw=model.plan_discovery(course,documents,selections,graph,batches)
        record('requirement_planner',parsed=raw)
        plan=normalize_plan(attach_known_coverage(raw,documents,selections,graph,batches),course,documents,selections)
        requirement_origin='llm'
    except Exception as exc:
        record('requirement_planner',failure_type=type(exc).__name__,failure_reason=str(exc))
        raw=local_requirements(course,documents,selections)
        plan=normalize_plan(attach_known_coverage(raw,documents,selections,graph,batches),course,documents,selections)
        requirement_origin='course_information'
    gaps=[r for r in plan['requirements'] if not r['covered'] or r['aspect'] in ('verification','current')]
    record('gap_analysis',parsed=plan['requirements'],gap_count=len(gaps),requirement_origin=requirement_origin)
    # An empty gap list is success, never an excuse to search the entire course.
    generated=[];generation_failure=None
    if gaps:
        try:
            generated=model.generate_search_tasks(course,gaps)
            record('search_task_generator',parsed=generated)
            generated=generated.get('tasks') if isinstance(generated,dict) else None
            if not isinstance(generated,list):raise ValueError('搜索任务缺少 tasks 数组')
        except Exception as exc:
            generation_failure=str(exc);generated=[]
            record('search_task_generator',failure_type=type(exc).__name__,failure_reason=str(exc))
    tasks=[];flat=[];seen=set()
    for index,gap in enumerate(gaps):
        proposed=next((t for t in generated if isinstance(t,dict) and t.get('requirement_index')==index),{})
        intent=INTENTS[gap['aspect']]
        proposed_intent=proposed.get('search_intent')
        if isinstance(proposed_intent,str) and normalize_queries([proposed_intent]):intent=proposed_intent.strip()
        values=normalize_queries(proposed.get('queries'),course,gap['title'],intent,True)
        origin='llm'
        if not values:
            values,origin=fallback_queries(gap,course)
            record('query_fallback',requirement_index=index,fallback_level=origin,
                   failure_reason=generation_failure or '任务未提供有效搜索词')
        preferred=proposed.get('preferred_sources')
        if not isinstance(preferred,list) or not all(isinstance(s,str) and s.strip() for s in preferred):preferred=['官方文档','公开教材','教育机构公开资料']
        priority=proposed.get('priority',index+1)
        if isinstance(priority,bool) or not isinstance(priority,int) or priority<1:priority=index+1
        task={'knowledge_target':gap['title'],'purpose':gap['reason'],'search_intent':intent,
              'queries':values[:3],'preferred_sources':preferred[:6],'priority':priority,
              'section':gap['section'],'aspect':gap['aspect'],'generation_origin':origin,'requirement_index':index}
        tasks.append(task)
    tasks.sort(key=lambda t:t['priority'])
    for task in tasks:
        for query in task['queries']:
            if query.casefold() in seen:continue
            seen.add(query.casefold())
            flat.append({'query':query,'section':task['section'],'requirement':task['knowledge_target'],
                         'aspect':task['aspect'],'reason':task['purpose'],'task_index':tasks.index(task)})
    plan.update(search_tasks=tasks,queries=flat[:3],remaining_queries=flat[3:],
                diagnostics={'trace_id':identifier,'events':events,'requirement_origin':requirement_origin,
                             'generation_failure':generation_failure})
    record('query_enhancement',parsed={'tasks':tasks,'queries':flat})
    return plan
