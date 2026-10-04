import json,math,re
from pathlib import Path
from ..resources.protocol import text,digest
POLICY=json.loads(Path(__file__).with_name('mission_policy.json').read_text())
MISSION_TYPES={'project','competition','experiment','portfolio','research','custom'}
STATUSES={'draft','active','paused','completed','abandoned'}
TASK_TYPES={'learn','implement','experiment','analyze','document','verify','reflect','submit'}
ARTIFACT_TYPES={'code','report','dataset','benchmark','profile','image','log','model','document','submission','other'}
REFLECTION_TYPES={'what_worked','what_failed','lesson_learned','next_step','retrospective'}
CLAIM_TYPES={'application','transfer','tool_use','problem_solving','implementation','analysis'}
TRIGGERS={'MISSION_SCOPE_CHANGED','MILESTONE_FAILED','EXPERIMENT_RESULT_CHANGED_DIRECTION','DEADLINE_CHANGED','USER_REQUESTED'}
BOUNDARY='项目进度只表示实践完成情况；产出、用时与模型点评不代表知识掌握或独立能力认证。'
def fields(p,allowed):
 if not isinstance(p,dict) or set(p)-set(allowed):raise ValueError('实践请求字段无效；不能提供掌握状态或评分')
 for k,v in p.items():
  if k.endswith('_id') and v is not None and (not isinstance(v,str) or not 1<=len(v)<=100):raise ValueError('关联编号无效')
 return p
def enum(v,allowed,label):
 if not isinstance(v,str) or v not in allowed:raise ValueError(label+'无效')
 return v
def boolean(v):
 if type(v) is not bool:raise ValueError('请明确选择是否确认、固定或必需')
 return v
def number(v,lo=0,hi=1440):
 if type(v) not in {int,float} or not math.isfinite(v) or not lo<=v<=hi:raise ValueError('请输入范围内的有限数值')
 return v
def integer(v,lo=1,hi=5):
 if type(v) is not int or not lo<=v<=hi:raise ValueError('优先级应为 1–5 的整数')
 return v
def deadline(v):
 if v is None or v=='':return None
 from datetime import date
 try:date.fromisoformat(v)
 except (ValueError,TypeError):raise ValueError('日期格式应为 YYYY-MM-DD') from None
 return v
def strings(v,limit=20):
 if not isinstance(v,list) or len(v)>limit:raise ValueError('关联列表无效')
 values=[text(x,100) for x in v]
 if len(set(values))!=len(values):raise ValueError('关联列表不能重复')
 return values
def object_values(v,numeric=False):
 if not isinstance(v,dict) or len(v)>30:raise ValueError('参数或指标最多 30 项')
 result={}
 for k,x in v.items():
  k=text(k,80)
  if numeric:result[k]=number(x,-1e15,1e15)
  elif type(x) in {int,float}:result[k]=number(x,-1e15,1e15)
  elif isinstance(x,str):result[k]=text(x,300,True)
  elif x is None or type(x) is bool:result[k]=x
  else:raise ValueError('参数只能填写文字、数值或布尔值')
 return result
def key(v):
 if not isinstance(v,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}',v):raise ValueError('计划编号无效')
 return v

def plan(value):
 fields(value,{'milestones'});items=value.get('milestones')
 if not isinstance(items,list) or not 1<=len(items)<=POLICY['planning']['max_milestones']:raise ValueError('计划需要 1–12 个里程碑')
 mskeys=set();taskkeys=set();result=[]
 for index,m in enumerate(items,1):
  fields(m,{'key','ordinal','title','objective','required','locked','planned_minutes','due_date','gate','tasks'})
  mk=key(m.get('key'))
  if mk in mskeys:raise ValueError('里程碑编号重复')
  mskeys.add(mk);gate=fields(m.get('gate',{}),{'artifact_types','require_run'})
  kinds=strings(gate.get('artifact_types',[]))
  if set(kinds)-ARTIFACT_TYPES:raise ValueError('里程碑产出类型无效')
  tasks=m.get('tasks')
  if not isinstance(tasks,list) or not 1<=len(tasks)<=POLICY['planning']['max_tasks_per_milestone']:raise ValueError('每个里程碑需要 1–10 个任务')
  normalized=[]
  for t in tasks:
   fields(t,{'key','title','task_type','description','required','locked','priority','estimated_minutes','dependencies','artifact_types','linked_course_id','linked_atom_id','linked_growth_task_id','resource_ids','experiment'})
   tk=key(t.get('key'));deps=strings(t.get('dependencies',[]))
   if tk in taskkeys or set(deps)-taskkeys:raise ValueError('任务编号重复或依赖不是前置任务')
   taskkeys.add(tk);kinds2=strings(t.get('artifact_types',[]))
   if set(kinds2)-ARTIFACT_TYPES:raise ValueError('任务产出类型无效')
   kind=enum(t.get('task_type'),TASK_TYPES,'任务类型');experiment=fields(t.get('experiment',{}),{'hypothesis','setup','variables','expected_result'})
   if experiment and kind!='experiment':raise ValueError('实验元数据只能用于实验任务')
   experiment={k:text(v,1500,True) if k!='variables' else object_values(v) for k,v in experiment.items()}
   normalized.append({'key':tk,'title':text(t.get('title'),150),'task_type':kind,'description':text(t.get('description',''),3000,True),'required':boolean(t.get('required',True)),'locked':boolean(t.get('locked',False)),'priority':integer(t.get('priority',2)),'estimated_minutes':number(t.get('estimated_minutes',25),1,1440),'dependencies':deps,'artifact_types':kinds2,'linked_course_id':t.get('linked_course_id'),'linked_atom_id':t.get('linked_atom_id'),'linked_growth_task_id':t.get('linked_growth_task_id'),'resource_ids':strings(t.get('resource_ids',[])),'experiment':experiment})
  result.append({'key':mk,'ordinal':index,'title':text(m.get('title'),150),'objective':text(m.get('objective',''),3000,True),'required':boolean(m.get('required',True)),'locked':boolean(m.get('locked',False)),'planned_minutes':None if m.get('planned_minutes') is None else number(m['planned_minutes'],1,14400),'due_date':deadline(m.get('due_date')),'gate':{'artifact_types':kinds,'require_run':boolean(gate.get('require_run',False))},'tasks':normalized})
 return {'milestones':result}
