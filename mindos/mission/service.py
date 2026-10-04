"""Owned practice execution. No imports of knowledge-state/evidence writers."""
import json,secrets
from ..tutor.storage import now
from ..learning.growth import GrowthService
from ..learning.execution import StudySessionService
from ..learning.pace import DurationEstimator
from ..resources.service import ResourceService
from .protocol import *

SCHEMA='''
CREATE TABLE IF NOT EXISTS learning_missions (
 id TEXT PRIMARY KEY,user_id TEXT NOT NULL,goal_id TEXT,title TEXT NOT NULL,description TEXT NOT NULL,
 mission_type TEXT NOT NULL,target_outcome TEXT NOT NULL,status TEXT NOT NULL,priority INTEGER NOT NULL,
 deadline TEXT,plan_version INTEGER NOT NULL DEFAULT 0,draft_version INTEGER NOT NULL DEFAULT 0,
 draft_json TEXT NOT NULL DEFAULT '{}',history_json TEXT NOT NULL DEFAULT '[]',outcome TEXT,
 created_at TEXT NOT NULL,updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS mission_owner ON learning_missions(user_id,status);
CREATE TABLE IF NOT EXISTS mission_milestones (
 id TEXT PRIMARY KEY,mission_id TEXT NOT NULL REFERENCES learning_missions(id),milestone_key TEXT NOT NULL,
 ordinal INTEGER NOT NULL,title TEXT NOT NULL,objective TEXT NOT NULL,status TEXT NOT NULL,
 planned_minutes REAL,due_date TEXT,gate_json TEXT NOT NULL,metadata_json TEXT NOT NULL,
 created_at TEXT NOT NULL,updated_at TEXT NOT NULL,UNIQUE(mission_id,milestone_key)
);
CREATE TABLE IF NOT EXISTS mission_tasks (
 id TEXT PRIMARY KEY,mission_id TEXT NOT NULL REFERENCES learning_missions(id),
 milestone_id TEXT NOT NULL REFERENCES mission_milestones(id),task_key TEXT NOT NULL,
 title TEXT NOT NULL,task_type TEXT NOT NULL,description TEXT NOT NULL,status TEXT NOT NULL,
 priority INTEGER NOT NULL,estimated_minutes REAL NOT NULL,linked_course_id TEXT,linked_atom_id TEXT,
 linked_growth_task_id TEXT,metadata_json TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,
 UNIQUE(mission_id,task_key)
);
CREATE TABLE IF NOT EXISTS mission_experiment_runs (
 id TEXT PRIMARY KEY,mission_id TEXT NOT NULL REFERENCES learning_missions(id),
 task_id TEXT NOT NULL REFERENCES mission_tasks(id),run_index INTEGER NOT NULL,
 parameters_json TEXT NOT NULL,metrics_json TEXT NOT NULL,notes TEXT NOT NULL,
 artifact_ids_json TEXT NOT NULL,created_at TEXT NOT NULL,UNIQUE(task_id,run_index)
);
CREATE TABLE IF NOT EXISTS mission_artifacts (
 id TEXT PRIMARY KEY,user_id TEXT NOT NULL,mission_id TEXT NOT NULL REFERENCES learning_missions(id),
 task_id TEXT REFERENCES mission_tasks(id),run_id TEXT REFERENCES mission_experiment_runs(id),
 artifact_type TEXT NOT NULL,title TEXT NOT NULL,local_path TEXT NOT NULL,mime_type TEXT NOT NULL,
 content_hash TEXT NOT NULL,version INTEGER NOT NULL,parent_artifact_id TEXT REFERENCES mission_artifacts(id),
 metadata_json TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS artifact_owner ON mission_artifacts(user_id,mission_id);
CREATE TABLE IF NOT EXISTS mission_reflections (
 id TEXT PRIMARY KEY,user_id TEXT NOT NULL,mission_id TEXT NOT NULL REFERENCES learning_missions(id),
 milestone_id TEXT REFERENCES mission_milestones(id),task_id TEXT REFERENCES mission_tasks(id),
 reflection_type TEXT NOT NULL,content TEXT NOT NULL,artifact_ids_json TEXT NOT NULL,created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS project_evidence_candidates (
 id TEXT PRIMARY KEY,user_id TEXT NOT NULL,mission_id TEXT NOT NULL REFERENCES learning_missions(id),
 capability_id TEXT,canonical_atom_id TEXT,artifact_ids_json TEXT NOT NULL,claim_type TEXT NOT NULL,
 claim TEXT NOT NULL,source TEXT NOT NULL,status TEXT NOT NULL,review_json TEXT NOT NULL,
 verification_json TEXT NOT NULL,created_at TEXT NOT NULL
);
'''
def migrate(db):db.executescript(SCHEMA)
def uid():return secrets.token_urlsafe(18)
def encode(v):return json.dumps(v,ensure_ascii=False,allow_nan=False)
def row_json(row):
 r=dict(row)
 for k in list(r):
  if k.endswith('_json'):r[k[:-5]]=json.loads(r.pop(k))
 r.pop('user_id',None);return r

class MissionService:
 def __init__(self,store):self.store=store
 def _owned(self,db,user,mid):
  r=db.execute('SELECT * FROM learning_missions WHERE id=? AND user_id=?',(mid,user)).fetchone()
  if not r:raise ValueError('实践项目不存在或不属于你')
  return r
 def goal(self,user,gid):
  if gid is not None and (not isinstance(gid,str) or not 1<=len(gid)<=100):raise ValueError('成长目标编号无效')
  return GrowthService(self.store).goal(user,gid) if gid else None
 def _touch(self,db,mid):
  db.execute("UPDATE learning_missions SET updated_at=?,draft_version=draft_version+1,draft_json='{}' WHERE id=?",(now(),mid))
 def _task(self,db,user,mid,tid):
  self._owned(db,user,mid);r=db.execute('SELECT * FROM mission_tasks WHERE id=? AND mission_id=?',(tid,mid)).fetchone()
  if not r:raise ValueError('实践任务不存在')
  return r
 def _milestone(self,db,user,mid,sid):
  self._owned(db,user,mid);r=db.execute('SELECT * FROM mission_milestones WHERE id=? AND mission_id=?',(sid,mid)).fetchone()
  if not r:raise ValueError('里程碑不存在')
  return r
 def links(self,user,t):
  cid=t.get('linked_course_id');aid=t.get('linked_atom_id');gtid=t.get('linked_growth_task_id')
  for v in [cid,aid,gtid]:
   if v is not None and (not isinstance(v,str) or not 1<=len(v)<=100):raise ValueError('课程、知识点或成长任务编号无效')
  if cid:
   if not isinstance(cid,str):raise ValueError('课程编号无效')
   self.store._knowledge_course(user,cid)
   if aid:ResourceService(self.store).atom(user,cid,aid)
  elif aid:raise ValueError('请先关联知识点所属课程')
  if gtid:
   with self.store.connect() as db:r=db.execute('SELECT t.id FROM growth_tasks t JOIN learning_goals g ON g.id=t.goal_id WHERE t.id=? AND t.user_id=? AND g.user_id=?',(gtid,user,user)).fetchone()
   if not r:raise ValueError('成长任务不存在或不属于你')
  for rid in t.get('resource_ids',[]):ResourceService(self.store).get(user,rid)
 def create(self,user,p):
  fields(p,{'goal_id','title','description','mission_type','target_outcome','priority','deadline','confirmed'})
  if p.get('confirmed') is not True:raise ValueError('请明确确认创建实践项目')
  gid=p.get('goal_id');self.goal(user,gid);ts=now();mid=uid()
  values=(mid,user,gid,text(p.get('title'),150),text(p.get('description',''),5000,True),enum(p.get('mission_type','project'),MISSION_TYPES,'项目类型'),text(p.get('target_outcome',''),3000,True),'draft',integer(p.get('priority',2)),deadline(p.get('deadline')),ts,ts)
  with self.store.connect() as db:db.execute('INSERT INTO learning_missions(id,user_id,goal_id,title,description,mission_type,target_outcome,status,priority,deadline,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',values)
  return self.get(user,mid)
 def list(self,user):
  with self.store.connect() as db:ids=[r[0] for r in db.execute('SELECT id FROM learning_missions WHERE user_id=? ORDER BY priority,updated_at DESC LIMIT 100',(user,))]
  return {'missions':[self.get(user,mid,False) for mid in ids],'boundary':BOUNDARY}
 def get(self,user,mid,detail=True):
  with self.store.connect() as db:
   m=row_json(self._owned(db,user,mid));milestones=[row_json(r) for r in db.execute('SELECT * FROM mission_milestones WHERE mission_id=? ORDER BY ordinal,created_at',(mid,))];tasks=[row_json(r) for r in db.execute('SELECT * FROM mission_tasks WHERE mission_id=? ORDER BY rowid',(mid,))]
   runs=[row_json(r) for r in db.execute('SELECT * FROM mission_experiment_runs WHERE mission_id=? ORDER BY created_at',(mid,))]
   reflections=[row_json(r) for r in db.execute('SELECT * FROM mission_reflections WHERE mission_id=? ORDER BY created_at DESC LIMIT 40',(mid,))]
   candidates=[row_json(r) for r in db.execute('SELECT * FROM project_evidence_candidates WHERE mission_id=? ORDER BY created_at DESC LIMIT 40',(mid,))]
  active_ms=[s for s in milestones if s['metadata'].get('current',True)];current_tasks=[t for t in tasks if t['metadata'].get('current',True)]
  conflict=False
  if m.get('goal_id'):
   try:conflict=any(g['status']=='conflicted' and g.get('importance')=='critical' for g in GrowthService(self.store).gaps(user,m['goal_id'])['gaps'])
   except ValueError:pass
  estimator=DurationEstimator(self.store,user)
  for t in current_tasks:
   t['blocked_reasons']=self.blocked(user,m,active_ms,current_tasks,t,conflict)
   if t['status'] in {'planned','ready','blocked'}:t['status']='blocked' if t['blocked_reasons'] else 'ready'
   t['duration']=estimator.predict(t['estimated_minutes'],'goal_task')
  minutes=0
  with self.store.connect() as db:
   for t in tasks:
    for sid in t['metadata'].get('study_session_ids',[]):
     r=db.execute('SELECT active_seconds FROM study_sessions WHERE id=? AND user_id=?',(sid,user)).fetchone()
     if r:minutes+=r[0]/60
  with self.store.connect() as db:artifact_count=db.execute('SELECT count(*) FROM mission_artifacts WHERE mission_id=?',(mid,)).fetchone()[0]
  m.update(boundary=BOUNDARY,progress={'tasks_completed':sum(t['status']=='completed' for t in current_tasks),'tasks_total':len(current_tasks),'milestones_completed':sum(s['status']=='completed' for s in active_ms),'milestones_total':len(active_ms),'experiments':sum(t['task_type']=='experiment' for t in current_tasks),'runs':len(runs),'artifacts':artifact_count,'actual_minutes':round(minutes,2)})
  if detail:
   from .artifacts import ArtifactService
   m.update(milestones=active_ms,tasks=current_tasks,runs=runs,reflections=reflections,evidence_candidates=candidates,artifacts=ArtifactService(self.store).list(user,mid)['artifacts'],past_task_count=len(tasks)-len(current_tasks))
  try:m['goal']=self.goal(user,m['goal_id'])
  except ValueError:m['goal']=None;m['goal_note']='原目标已删除，实践历史仍保留。'
  return m
 def update(self,user,mid,p):
  fields(p,{'title','description','target_outcome','mission_type','priority','deadline','status','outcome','goal_id'})
  if not p:raise ValueError('请提供需要修改的项目字段')
  if 'goal_id' in p:self.goal(user,p['goal_id'])
  clean={}
  for k,v in p.items():
   if k in {'title','description','target_outcome'}:clean[k]=text(v,150 if k=='title' else 5000,k!='title')
   elif k=='status':clean[k]=enum(v,STATUSES,'项目状态')
   elif k=='mission_type':clean[k]=enum(v,MISSION_TYPES,'项目类型')
   elif k=='outcome':clean[k]=enum(v,{'success','partial','failed','withdrawn'},'项目结果')
   elif k=='priority':clean[k]=integer(v)
   elif k=='deadline':clean[k]=deadline(v)
   else:clean[k]=v
  with self.store.connect() as db:
   db.execute('BEGIN IMMEDIATE');m=self._owned(db,user,mid)
   if clean.get('status')=='completed':
    problems=self._completion(db,user,mid)
    if problems:raise ValueError('项目尚未满足完成要求：'+'；'.join(problems))
   if clean.get('status')=='active' and not m['plan_version']:raise ValueError('请先确认实践计划')
   clean['updated_at']=now();self._touch(db,mid);db.execute('UPDATE learning_missions SET '+','.join(k+'=?' for k in clean)+' WHERE id=?',(*clean.values(),mid))
  return self.get(user,mid)
 def _completion(self,db,user,mid):
  self._owned(db,user,mid);reasons=[]
  milestones=[row_json(r) for r in db.execute('SELECT * FROM mission_milestones WHERE mission_id=?',(mid,))];tasks=[row_json(r) for r in db.execute('SELECT * FROM mission_tasks WHERE mission_id=?',(mid,))]
  if not any(s['metadata'].get('current',True) for s in milestones):reasons.append('没有确认计划')
  for s in milestones:
   if not s['metadata'].get('current',True) or not s['metadata'].get('required',True):continue
   if s['status']!='completed':reasons.append('里程碑未完成：'+s['title'])
   kinds={r[0] for r in db.execute('SELECT a.artifact_type FROM mission_artifacts a JOIN mission_tasks t ON t.id=a.task_id WHERE t.milestone_id=?',(s['id'],))}
   if set(s['gate'].get('artifact_types',[]))-kinds:reasons.append('里程碑必要产出缺失：'+s['title'])
   if s['gate'].get('require_run') and not db.execute('SELECT 1 FROM mission_experiment_runs r JOIN mission_tasks t ON r.task_id=t.id WHERE t.milestone_id=?',(s['id'],)).fetchone():reasons.append('里程碑实验记录缺失：'+s['title'])
  for t in tasks:
   if not t['metadata'].get('current',True) or not t['metadata'].get('required',True):continue
   if t['status']!='completed':reasons.append('必需任务未完成：'+t['title'])
   kinds={r[0] for r in db.execute('SELECT artifact_type FROM mission_artifacts WHERE task_id=?',(t['id'],))}
   if set(t['metadata'].get('artifact_types',[]))-kinds:reasons.append('任务必要产出缺失：'+t['title'])
   if t['task_type']=='experiment' and not db.execute('SELECT 1 FROM mission_experiment_runs WHERE task_id=?',(t['id'],)).fetchone():reasons.append('实验记录缺失：'+t['title'])
  return reasons
 def blocked(self,user,m,milestones,tasks,t,conflict=False):
  reasons=[];meta=t['metadata'];keys={x['task_key']:x for x in tasks};ms=next((s for s in milestones if s['id']==t['milestone_id']),None)
  for dep in meta.get('dependencies',[]):
   if dep not in keys or keys[dep]['status']!='completed':reasons.append('前置任务未完成：'+(keys[dep]['title'] if dep in keys else dep))
  if not ms:reasons.append('任务属于历史计划')
  else:
   if any(s['id']!=ms['id'] and s['status']=='active' for s in milestones):reasons.append('请先完成当前进行中的里程碑')
   reasons += ['前一必需里程碑未完成：'+s['title'] for s in milestones if s['ordinal']<ms['ordinal'] and s['metadata'].get('required',True) and s['status']!='completed']
  try:self.links(user,{**t,'resource_ids':meta.get('resource_ids',[])})
  except ValueError:reasons.append('关联课程、知识点或材料已不可用，请编辑关联')
  # Actual conflict is computed once from the unchanged P4 reader.
  if conflict:reasons.append('目标关键能力有实际来源冲突，请先独立验证')
  return reasons
 def task_action(self,user,mid,tid,op,p=None):
  p=p or {};fields(p,{'enabled'} if op=='lock' else set())
  m=self.get(user,mid);t=next((t for t in m['tasks'] if t['id']==tid),None)
  if not t:raise ValueError('当前计划没有这个任务')
  if m['status']!='active' and op not in {'lock'}:raise ValueError('请先启用实践项目')
  if op in {'start','complete'} and t['blocked_reasons']:raise ValueError('；'.join(t['blocked_reasons']))
  with self.store.connect() as db:
   db.execute('BEGIN IMMEDIATE');raw=self._task(db,user,mid,tid);meta=json.loads(raw['metadata_json'])
   if not meta.get('current',True):raise ValueError('任务已不属于当前计划，请重新读取')
   if op!='lock' and self._owned(db,user,mid)['status']!='active':raise ValueError('请先启用实践项目')
   if op in {'start','complete'}:
    rows=[row_json(r) for r in db.execute('SELECT * FROM mission_tasks WHERE mission_id=?',(mid,))];keys={x['task_key']:x for x in rows if x['metadata'].get('current',True)}
    if any(dep not in keys or keys[dep]['status']!='completed' for dep in meta.get('dependencies',[])):raise ValueError('前置任务状态已改变，请重新读取')
    stage=self._milestone(db,user,mid,raw['milestone_id'])
    for other in db.execute('SELECT * FROM mission_milestones WHERE mission_id=?',(mid,)):
     om=json.loads(other['metadata_json'])
     if om.get('current',True) and other['id']!=stage['id'] and (other['status']=='active' or other['ordinal']<stage['ordinal'] and om.get('required',True) and other['status']!='completed'):raise ValueError('请先完成当前必需里程碑')
   if op=='lock':meta['locked']=boolean(p.get('enabled'));db.execute('UPDATE mission_tasks SET metadata_json=?,updated_at=? WHERE id=?',(encode(meta),now(),tid))
   elif op in {'start','complete','skip','resume'}:
    if raw['status']=='completed' and op!='complete':raise ValueError('已完成任务保留历史记录，请重规划新增任务')
    if op=='complete':
     if raw['status']!='active':raise ValueError('请先开始任务，再明确确认完成')
     kinds={r[0] for r in db.execute('SELECT artifact_type FROM mission_artifacts WHERE task_id=?',(tid,))}
     if set(meta.get('artifact_types',[]))-kinds:raise ValueError('请先上传任务要求的产出：'+','.join(set(meta['artifact_types'])-kinds))
     if raw['task_type']=='experiment' and not db.execute('SELECT 1 FROM mission_experiment_runs WHERE task_id=?',(tid,)).fetchone():raise ValueError('实验任务需要至少一条实际运行记录')
    state={'start':'active','complete':'completed','skip':'skipped','resume':'planned'}[op]
    db.execute('UPDATE mission_tasks SET status=?,updated_at=? WHERE id=?',(state,now(),tid))
    if op=='start':db.execute("UPDATE mission_milestones SET status='active',updated_at=? WHERE id=? AND status!='completed'",(now(),raw['milestone_id']))
    self._settle_milestone(db,mid,raw['milestone_id'])
   else:raise ValueError('任务操作无效')
   self._touch(db,mid)
  return self.get(user,mid)
 def _settle_milestone(self,db,mid,sid):
  s=row_json(db.execute('SELECT * FROM mission_milestones WHERE id=?',(sid,)).fetchone());tasks=[row_json(r) for r in db.execute('SELECT * FROM mission_tasks WHERE milestone_id=?',(sid,)) if json.loads(r['metadata_json']).get('current',True)]
  required=[t for t in tasks if t['metadata'].get('required',True)]
  kinds={r[0] for r in db.execute('SELECT a.artifact_type FROM mission_artifacts a JOIN mission_tasks t ON a.task_id=t.id WHERE t.milestone_id=?',(sid,))}
  has_run=bool(db.execute('SELECT 1 FROM mission_experiment_runs r JOIN mission_tasks t ON t.id=r.task_id WHERE t.milestone_id=?',(sid,)).fetchone())
  done=bool(tasks) and all(t['status']=='completed' for t in required) and not (set(s['gate'].get('artifact_types',[]))-kinds) and (not s['gate'].get('require_run') or has_run)
  if done:db.execute("UPDATE mission_milestones SET status='completed',updated_at=? WHERE id=?",(now(),sid))
 def lock_milestone(self,user,mid,sid,p):
  fields(p,{'enabled'})
  with self.store.connect() as db:
   r=self._milestone(db,user,mid,sid);meta=json.loads(r['metadata_json']);meta['locked']=boolean(p.get('enabled'));self._touch(db,mid);db.execute('UPDATE mission_milestones SET metadata_json=?,updated_at=? WHERE id=?',(encode(meta),now(),sid))
  return self.get(user,mid)
 def edit_task(self,user,mid,tid,p):
  fields(p,{'title','description','required','locked','estimated_minutes','linked_course_id','linked_atom_id','linked_growth_task_id','resource_ids','experiment','artifact_types'})
  with self.store.connect() as db:
   r=row_json(self._task(db,user,mid,tid))
  if r['status']=='completed':raise ValueError('已完成任务不能覆写，请新增任务')
  definition={k:r[k] for k in ['title','description','task_type','priority','estimated_minutes','linked_course_id','linked_atom_id','linked_growth_task_id']};definition.update({k:r['metadata'].get(k,[]) if k in {'dependencies','artifact_types','resource_ids'} else r['metadata'].get(k,False if k=='locked' else True) for k in ['required','locked','dependencies','artifact_types','resource_ids']});definition['experiment']=r['metadata'].get('experiment',{});definition.update(p);definition['key']=r['task_key']
  # Validate within a local synthetic prefix for existing dependencies.
  for k in ['title','description']:definition[k]=text(definition[k],150 if k=='title' else 3000,k!='title')
  for k in ['required','locked']:definition[k]=boolean(definition[k])
  definition['estimated_minutes']=number(definition['estimated_minutes'],1,1440)
  for k in ['resource_ids','artifact_types']:definition[k]=strings(definition[k])
  if set(definition['artifact_types'])-ARTIFACT_TYPES:raise ValueError('产出类型无效')
  if definition['experiment'] and definition['task_type']!='experiment':raise ValueError('仅实验任务可设置实验说明')
  fields(definition['experiment'],{'hypothesis','setup','variables','expected_result'})
  definition['experiment']={k:object_values(v) if k=='variables' else text(v,1500,True) for k,v in definition['experiment'].items()}
  self.links(user,definition);meta={**r['metadata'],**{k:definition[k] for k in ['required','locked','resource_ids','artifact_types','experiment']}}
  with self.store.connect() as db:
   self._touch(db,mid);db.execute('UPDATE mission_tasks SET title=?,description=?,estimated_minutes=?,linked_course_id=?,linked_atom_id=?,linked_growth_task_id=?,metadata_json=?,updated_at=? WHERE id=?',(definition['title'],definition['description'],definition['estimated_minutes'],definition['linked_course_id'],definition['linked_atom_id'],definition['linked_growth_task_id'],encode(meta),now(),tid))
  return self.get(user,mid)
 def start_session(self,user,mid,tid,p):
  fields(p,{'planned_minutes'});m=self.get(user,mid);t=next((t for t in m['tasks'] if t['id']==tid),None)
  if not t or t['status']!='active' or t['blocked_reasons']:raise ValueError('请先开始当前可执行任务')
  payload={'activity_type':'goal_task','source':'free','planned_minutes':number(p.get('planned_minutes',t['duration']['personalized_minutes']),1,1440),'course_id':t['linked_course_id'],'atom_id':t['linked_atom_id']}
  result=StudySessionService(self.store).start(user,payload)
  with self.store.connect() as db:
   r=self._task(db,user,mid,tid);meta=json.loads(r['metadata_json']);meta.setdefault('study_session_ids',[]).append(result['session']['id']);self._touch(db,mid);db.execute('UPDATE mission_tasks SET metadata_json=? WHERE id=?',(encode(meta),tid))
  return result
 def reflection(self,user,mid,p):
  fields(p,{'milestone_id','task_id','experiment_id','reflection_type','content','artifact_ids','confirmed'})
  if p.get('confirmed') is not True:raise ValueError('复盘内容需由你确认后保存')
  ids=strings(p.get('artifact_ids',[]));self.validate_artifacts(user,mid,ids)
  with self.store.connect() as db:
   self._owned(db,user,mid)
   if p.get('milestone_id'):self._milestone(db,user,mid,p['milestone_id'])
   tid=p.get('task_id') or p.get('experiment_id')
   if tid:self._task(db,user,mid,tid)
   self._touch(db,mid);db.execute('INSERT INTO mission_reflections VALUES(?,?,?,?,?,?,?,?,?)',(uid(),user,mid,p.get('milestone_id'),tid,enum(p.get('reflection_type','retrospective'),REFLECTION_TYPES,'复盘类型'),text(p.get('content'),10000),encode(ids),now()))
  return self.get(user,mid)
 def validate_artifacts(self,user,mid,ids):
  from .artifacts import ArtifactService
  for aid in ids:ArtifactService(self.store).get(user,mid,aid)
 def run(self,user,mid,tid,p):
  fields(p,{'parameters','metrics','notes','artifact_ids'});ids=strings(p.get('artifact_ids',[]));self.validate_artifacts(user,mid,ids)
  parameters=object_values(p.get('parameters',{}));metrics=object_values(p.get('metrics',{}),True)
  if not metrics:raise ValueError('请填写至少一项实际实验指标')
  with self.store.connect() as db:
   db.execute('BEGIN IMMEDIATE');t=self._task(db,user,mid,tid)
   if t['task_type']!='experiment' or t['status']!='active':raise ValueError('请先开始实验任务')
   index=db.execute('SELECT COALESCE(MAX(run_index),0)+1 FROM mission_experiment_runs WHERE task_id=?',(tid,)).fetchone()[0]
   self._touch(db,mid);db.execute('INSERT INTO mission_experiment_runs VALUES(?,?,?,?,?,?,?,?,?)',(uid(),mid,tid,index,encode(parameters),encode(metrics),text(p.get('notes',''),5000,True),encode(ids),now()))
  return self.get(user,mid)
 def compare(self,user,mid,tid,p):
  fields(p,{'run_ids'});ids=strings(p.get('run_ids',[]),POLICY['experiments']['max_compare_runs'])
  if len(ids)<2:raise ValueError('请选择 2–5 次实验记录')
  with self.store.connect() as db:
   self._task(db,user,mid,tid);runs=[row_json(r) for r in db.execute('SELECT * FROM mission_experiment_runs WHERE task_id=?',(tid,)) if r['id'] in ids]
  if len(runs)!=len(ids):raise ValueError('实验记录不属于当前任务')
  names=set.intersection(*(set(r['metrics']) for r in runs));comparison=[{'metric':k,'values':[{'run_id':r['id'],'run_index':r['run_index'],'value':r['metrics'][k],'parameters':r['parameters']} for r in runs],'minimum':min(r['metrics'][k] for r in runs),'maximum':max(r['metrics'][k] for r in runs)} for k in sorted(names)]
  return {'runs':runs,'comparison':comparison,'boundary':'仅比较用户记录的同名指标；数值大小是否更好由指标含义决定，不能据此确定因果。'}
 def recommendations(self,user,gid=None):
  goals=[self.goal(user,gid)] if gid else GrowthService(self.store).goals(user)['goals'];items=[]
  for g in goals:
   with self.store.connect() as db:existing=db.execute("SELECT id,title FROM learning_missions WHERE user_id=? AND goal_id=? AND status IN ('active','paused','draft') ORDER BY created_at LIMIT 1",(user,g['id'])).fetchone()
   try:missing=[x for x in GrowthService(self.store).gaps(user,g['id'])['gaps'] if x['status']=='practice_missing']
   except ValueError:missing=[]
   if existing:items.append({'goal_id':g['id'],'mission_id':existing['id'],'title':existing['title'],'reason':'继续已有实践项目，避免重复创建。'})
   elif missing or g['goal_type'] in {'project','competition'}:items.append({'goal_id':g['id'],'mission_id':None,'title':g['title']+' · 实践','reason':'目标需要实践验证；先明确要交付的产出，再由你确认创建。','gaps':[x['name'] for x in missing]})
  return {'recommendations':items[:3],'boundary':BOUNDARY}
