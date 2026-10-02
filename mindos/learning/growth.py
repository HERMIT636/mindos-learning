"""Goal lifecycle, immutable roadmap versions, and routes into existing learning modules."""
import json,secrets,math
from datetime import date,datetime
from zoneinfo import ZoneInfo
from .policy import clock,iso
from .final import fingerprint
from .growth_graph import POLICY,TargetCapabilityGenerator,GoalCapabilityMatcher,validate,order
from .growth_gap import GrowthInputReader,GapAnalysisEngine,GoalCompletionAnalyzer
from .growth_planner import GrowthPlanner,GrowthReplanningEngine,TRIGGERS,REASONS
from .canonical import normalized

SCHEMA='''
CREATE TABLE IF NOT EXISTS learning_goals (
 id TEXT PRIMARY KEY,user_id TEXT NOT NULL,title TEXT NOT NULL,description TEXT NOT NULL,
 goal_type TEXT NOT NULL,target_level TEXT NOT NULL,deadline TEXT,weekly_time_budget_minutes INTEGER,
 priority INTEGER NOT NULL,status TEXT NOT NULL,goal_model_version INTEGER NOT NULL,
 graph_json TEXT NOT NULL DEFAULT '{}',draft_json TEXT NOT NULL DEFAULT '{}',draft_version INTEGER NOT NULL DEFAULT 0,
 overrides_json TEXT NOT NULL DEFAULT '[]',created_at TEXT NOT NULL,updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS growth_goal_owner ON learning_goals(user_id,status,priority);
CREATE TABLE IF NOT EXISTS goal_capability_mappings (
 id TEXT PRIMARY KEY,user_id TEXT NOT NULL,goal_id TEXT NOT NULL REFERENCES learning_goals(id) ON DELETE CASCADE,
 capability_id TEXT NOT NULL,canonical_atom_id TEXT NOT NULL,canonical_fingerprint TEXT NOT NULL,
 status TEXT NOT NULL,confidence REAL NOT NULL,source TEXT NOT NULL,relationship TEXT NOT NULL,
 reasons_json TEXT NOT NULL,created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS growth_mapping_owner ON goal_capability_mappings(user_id,goal_id,status);
CREATE TABLE IF NOT EXISTS growth_roadmaps (
 id TEXT PRIMARY KEY,user_id TEXT NOT NULL,goal_id TEXT NOT NULL REFERENCES learning_goals(id) ON DELETE CASCADE,
 version INTEGER NOT NULL,status TEXT NOT NULL,plan_json TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,
 UNIQUE(goal_id,version)
);
CREATE TABLE IF NOT EXISTS growth_tasks (
 id TEXT PRIMARY KEY,user_id TEXT NOT NULL,goal_id TEXT NOT NULL REFERENCES learning_goals(id) ON DELETE CASCADE,
 roadmap_id TEXT NOT NULL REFERENCES growth_roadmaps(id) ON DELETE CASCADE,task_key TEXT NOT NULL,
 stage_ordinal INTEGER NOT NULL,capability_id TEXT NOT NULL,task_type TEXT NOT NULL,target_id TEXT,
 title TEXT NOT NULL,reason_code TEXT NOT NULL,priority INTEGER NOT NULL,estimated_minutes INTEGER NOT NULL,
 status TEXT NOT NULL,locked INTEGER NOT NULL DEFAULT 0,pinned INTEGER NOT NULL DEFAULT 0,
 metadata_json TEXT NOT NULL,updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS growth_tasks_owner ON growth_tasks(user_id,goal_id,roadmap_id,status);
CREATE TABLE IF NOT EXISTS growth_roadmap_changes (
 id TEXT PRIMARY KEY,user_id TEXT NOT NULL,goal_id TEXT NOT NULL REFERENCES learning_goals(id) ON DELETE CASCADE,
 from_version INTEGER,to_version INTEGER NOT NULL,reason_codes_json TEXT NOT NULL,diff_json TEXT NOT NULL,
 inputs_hash TEXT NOT NULL,created_at TEXT NOT NULL
);
'''
def migrate(db):db.executescript(SCHEMA)
def identifier():return secrets.token_urlsafe(16)
def today():return datetime.now(ZoneInfo('Asia/Shanghai')).date()

def fields(payload,partial=False):
    allowed={'title','description','goal_type','target_level','deadline','weekly_time_budget_minutes','priority','status'}
    if not isinstance(payload,dict) or set(payload)-allowed:raise ValueError('目标字段格式不正确；不能由客户端提供掌握或完成状态')
    data={} if partial else {'title':'','description':'','goal_type':'custom','target_level':'practical_understanding','deadline':None,'weekly_time_budget_minutes':None,'priority':1,'status':'active'}
    data.update(payload)
    for key,limit in [('title',120),('description',3000)]:
        if key in data:
            if not isinstance(data[key],str) or len(data[key].strip())>limit or key=='title' and not data[key].strip():raise ValueError('请填写简明目标名称与说明')
            data[key]=data[key].strip()
    if 'goal_type' in data and data['goal_type'] not in {'skill','knowledge_domain','project','competition','certificate','custom'}:raise ValueError('目标类型无效')
    if 'target_level' in data and data['target_level'] not in {'overview','understanding','practical_understanding','application','transfer','advanced'}:raise ValueError('目标深度无效')
    if 'status' in data and data['status'] not in {'active','paused','abandoned'}:raise ValueError('目标满足情况由程序检查，不能直接标为已完成')
    if 'priority' in data and (type(data['priority']) is not int or not 1<=data['priority']<=5):raise ValueError('目标优先级应在1到5之间')
    if data.get('deadline')=='':data['deadline']=None
    if data.get('deadline') is not None:
        try:
            if not isinstance(data['deadline'],str) or len(data['deadline'])!=10:raise ValueError()
            date.fromisoformat(data['deadline'])
        except (ValueError,TypeError):raise ValueError('截止日期请使用年-月-日')
    if 'weekly_time_budget_minutes' in data and data['weekly_time_budget_minutes'] is not None:
        v=data['weekly_time_budget_minutes']
        if type(v) is not int or not 5<=v<=10080:raise ValueError('每周时间请填写5到10080分钟，或留空')
    return data

class GrowthService:
    def __init__(self,store):self.store=store
    def _owned(self,db,user,gid):
        row=db.execute('SELECT * FROM learning_goals WHERE id=? AND user_id=?',(gid,user)).fetchone()
        if not row:raise ValueError('学习目标不存在')
        return dict(row)
    def goal(self,user,gid):
        with self.store.connect() as db:g=self._owned(db,user,gid)
        g['graph']=json.loads(g.pop('graph_json'));g['draft']=json.loads(g.pop('draft_json'));g['user_overrides']=json.loads(g.pop('overrides_json'));g.pop('user_id')
        g['requirements_stale']=bool(g['graph'].get('capabilities') and g['graph'].get('goal_basis')!=fingerprint({k:g[k] for k in ['title','description','goal_type','target_level']}))
        g['clarification']='目标较宽时，可补充希望独立完成什么；未补充时默认以实际理解与应用为目标。' if len(g['description'])<12 else None
        return g
    def goals(self,user):
        with self.store.connect() as db:rows=[dict(r) for r in db.execute('SELECT id,title,description,goal_type,target_level,deadline,weekly_time_budget_minutes,priority,status,goal_model_version,created_at,updated_at FROM learning_goals WHERE user_id=? ORDER BY priority,created_at',(user,))]
        return {'goals':rows}
    def create(self,user,payload):
        d=fields(payload);gid=identifier();now=iso(clock())
        with self.store.connect() as db:
            if db.execute('SELECT COUNT(*) FROM learning_goals WHERE user_id=?',(user,)).fetchone()[0]>=30:raise ValueError('第一版最多保留30个学习目标')
            db.execute('INSERT INTO learning_goals(id,user_id,title,description,goal_type,target_level,deadline,weekly_time_budget_minutes,priority,status,goal_model_version,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',(gid,user,*[d[k] for k in ['title','description','goal_type','target_level','deadline','weekly_time_budget_minutes','priority','status']],1,now,now))
        return self.goal(user,gid)
    def update(self,user,gid,payload):
        d=fields(payload,True)
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE');g=self._owned(db,user,gid);changed={k:v for k,v in d.items() if g[k]!=v};major=set(changed)-{'status','priority'}
            if changed:
                db.execute('UPDATE learning_goals SET '+','.join(k+'=?' for k in changed)+',updated_at=? WHERE id=?',(*changed.values(),iso(clock()),gid))
            if major:
                graph=json.loads(g['graph_json']);graph['pending_reason']='DEADLINE_CHANGED' if set(major)=={'deadline'} else 'GOAL_CHANGED'
                db.execute('UPDATE learning_goals SET graph_json=? WHERE id=?',(json.dumps(graph,ensure_ascii=False),gid))
                db.execute("UPDATE learning_goals SET goal_model_version=goal_model_version+1,draft_json='{}',draft_version=draft_version+1,status=CASE WHEN status='achieved' THEN 'active' ELSE status END WHERE id=?",(gid,))
                db.execute("UPDATE growth_roadmaps SET status='stale' WHERE goal_id=? AND status='active'",(gid,))
        return self.goal(user,gid)
    def delete(self,user,gid):
        with self.store.connect() as db:self._owned(db,user,gid);db.execute('DELETE FROM learning_goals WHERE id=? AND user_id=?',(gid,user))
        return {'deleted':True,'boundary':'只删除目标及路线，不删除课程、答题或个人知识档案。'}
    def _raw_graph(self,graph):
        lookup={c['id']:c['name'] for c in graph.get('capabilities',[])}
        return {'goal_summary':graph.get('goal_summary','请审查目标能力'),'capabilities':[{k:c[k] for k in ['name','type','required_level','importance','description','concept_type'] if k in c} for c in graph.get('capabilities',[])], 'dependencies':[{**e,'from':lookup[e['from']],'to':lookup[e['to']]} for e in graph.get('dependencies',[]) if e['from'] in lookup and e['to'] in lookup]}
    def analyze(self,user,gid,model=None,payload=None):
        payload=payload or {};g=self.goal(user,gid)
        if set(payload)-{'confirm','draft_version','graph'}:raise ValueError('能力草稿字段无效')
        if payload.get('confirm') is True:
            if type(payload.get('draft_version')) is not int or payload['draft_version']!=g['draft_version'] or not g['draft']:raise ValueError('能力草稿已变化，请刷新审查')
            graph=validate(payload.get('graph') or self._raw_graph(g['draft']),allow_no_critical=True)
            old={normalized(c['name']):c for c in g['graph'].get('capabilities',[])}
            remap={}
            for c in graph['capabilities']:
                previous=old.get(normalized(c['name']));original=c['id'];c['id']=previous['id'] if previous else original
                remap[original]=c['id'];c['user_override']=True;c['source']='user_confirmed_requirement'
            graph['dependencies']=[{**e,'from':remap[e['from']],'to':remap[e['to']]} for e in graph['dependencies']]
            order(graph)
            if g['graph'].get('capabilities'):graph['pending_reason']=g['graph'].get('pending_reason','GOAL_CHANGED')
            graph['goal_basis']=fingerprint({k:g[k] for k in ['title','description','goal_type','target_level']})
            overrides=list(dict.fromkeys(g['user_overrides']+[c['name'] for c in g['graph'].get('capabilities',[]) if normalized(c['name']) not in {normalized(n['name']) for n in graph['capabilities']}]))
            restored={normalized(c['name']) for c in graph['capabilities']};overrides=[name for name in overrides if normalized(name) not in restored]
            mappings=GoalCapabilityMatcher(self.store).match(user,g,graph,model)
            with self.store.connect() as db:
                db.execute('BEGIN IMMEDIATE');current=self._owned(db,user,gid)
                if current['draft_version']!=payload['draft_version'] or current['goal_model_version']!=g['goal_model_version']:raise ValueError('目标已变化，请重新审查')
                db.execute("UPDATE learning_goals SET graph_json=?,draft_json='{}',overrides_json=?,goal_model_version=goal_model_version+1,updated_at=? WHERE id=?",(json.dumps(graph,ensure_ascii=False),json.dumps(overrides),iso(clock()),gid))
                db.execute('DELETE FROM goal_capability_mappings WHERE goal_id=?',(gid,))
                for m in mappings:db.execute('INSERT INTO goal_capability_mappings VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(m['id'],user,gid,m['capability_id'],m['canonical_atom_id'],m['canonical_fingerprint'],m['status'],m['confidence'],m['source'],m['relationship'],json.dumps(m['reasons']),iso(clock())))
                db.execute("UPDATE growth_roadmaps SET status='stale' WHERE goal_id=? AND status='active'",(gid,))
            return {'goal':self.goal(user,gid),'confirmed':True}
        graph=TargetCapabilityGenerator().generate(g,model)
        removed={normalized(n) for n in g['user_overrides']};graph['capabilities']=[c for c in graph['capabilities'] if normalized(c['name']) not in removed];ids={c['id'] for c in graph['capabilities']};graph['dependencies']=[e for e in graph['dependencies'] if e['from'] in ids and e['to'] in ids]
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE');current=self._owned(db,user,gid)
            if current['goal_model_version']!=g['goal_model_version']:raise ValueError('目标已变化，请重试')
            db.execute('UPDATE learning_goals SET draft_json=?,draft_version=draft_version+1,updated_at=? WHERE id=?',(json.dumps(graph,ensure_ascii=False),iso(clock()),gid))
        return {'goal':self.goal(user,gid),'confirmed':False}
    def mappings(self,user,gid,debug=False):
        self.goal(user,gid)
        with self.store.connect() as db:rows=[dict(r) for r in db.execute('SELECT m.*,c.canonical_name,c.description AS canonical_description,c.domain AS canonical_domain,c.concept_type AS canonical_type FROM goal_capability_mappings m LEFT JOIN canonical_knowledge_atoms c ON c.id=m.canonical_atom_id AND c.user_id=m.user_id WHERE m.goal_id=? AND m.user_id=?',(gid,user))]
        if not debug:
            for r in rows:
                for k in ['user_id','confidence','canonical_fingerprint','reasons_json']:r.pop(k,None)
        return rows
    def refresh_mappings(self,user,gid,model=None):
        g=self.goal(user,gid)
        if not g['graph'].get('capabilities') or g['requirements_stale']:raise ValueError('请先确认当前目标能力要求')
        found=GoalCapabilityMatcher(self.store).match(user,g,g['graph'],model);changed=False
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE');current=self._owned(db,user,gid)
            if current['goal_model_version']!=g['goal_model_version']:raise ValueError('目标已变化，请刷新')
            for m in found:
                old=db.execute('SELECT * FROM goal_capability_mappings WHERE user_id=? AND goal_id=? AND capability_id=? AND canonical_atom_id=?',(user,gid,m['capability_id'],m['canonical_atom_id'])).fetchone()
                if old and (old['source']=='user_review' or old['canonical_fingerprint']==m['canonical_fingerprint']):continue
                if old:db.execute('DELETE FROM goal_capability_mappings WHERE id=?',(old['id'],))
                db.execute('INSERT INTO goal_capability_mappings VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(m['id'],user,gid,m['capability_id'],m['canonical_atom_id'],m['canonical_fingerprint'],m['status'],m['confidence'],m['source'],m['relationship'],json.dumps(m['reasons']),iso(clock())))
                changed=True
            if changed:
                db.execute('UPDATE learning_goals SET goal_model_version=goal_model_version+1,updated_at=? WHERE id=?',(iso(clock()),gid))
                db.execute("UPDATE growth_roadmaps SET status='stale' WHERE goal_id=? AND status='active'",(gid,))
        return {'mappings':self.mappings(user,gid),'changed':changed,'boundary':'只更新目标与知识的关联；候选需审查，不修改课程或个人掌握状态。'}
    def review_mapping(self,user,gid,mid,verify):
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE');g=self._owned(db,user,gid);m=db.execute('SELECT * FROM goal_capability_mappings WHERE id=? AND user_id=? AND goal_id=?',(mid,user,gid)).fetchone()
            if not m:raise ValueError('能力关联不存在')
            if verify:
                c=db.execute("SELECT * FROM canonical_knowledge_atoms WHERE id=? AND user_id=? AND status='active'",(m['canonical_atom_id'],user)).fetchone()
                if not c or c['semantic_fingerprint']!=m['canonical_fingerprint'] or m['relationship'] in {'different','broader','narrower','related'}:raise ValueError('该概念关联不适用，请重新审查能力范围')
                db.execute("UPDATE goal_capability_mappings SET status='rejected' WHERE goal_id=? AND capability_id=? AND id!=?",(gid,m['capability_id'],mid))
            db.execute('UPDATE goal_capability_mappings SET status=?,source=? WHERE id=?',('verified' if verify else 'rejected','user_review',mid));db.execute('UPDATE learning_goals SET goal_model_version=goal_model_version+1,updated_at=? WHERE id=?',(iso(clock()),gid));db.execute("UPDATE growth_roadmaps SET status='stale' WHERE goal_id=? AND status='active'",(gid,))
        return {'mappings':self.mappings(user,gid)}
    def _analysis(self,user,gid):
        g=self.goal(user,gid)
        if not g['graph'].get('capabilities'):raise ValueError('请先审查并确认目标能力')
        inputs=GrowthInputReader(self.store).read(user);maps=self.mappings(user,gid,True);old=self.roadmap(user,gid)
        artifacts={t['capability_id']:t['metadata']['authentic_task_id'] for t in (old.get('roadmap') or {}).get('tasks',[]) if t['metadata'].get('authentic_task_id')}
        analysis=GapAnalysisEngine().analyze(g,g['graph'],maps,inputs,artifacts);completion=GoalCompletionAnalyzer().analyze(g,g['graph'],analysis,inputs)
        return g,inputs,analysis,completion
    def gaps(self,user,gid,debug=False):
        _,_,a,c=self._analysis(user,gid)
        if not debug:
            for gap in a['gaps']:gap.pop('debug',None)
            for gap in a['critical_gaps']:gap.pop('debug',None)
            a.pop('inputs_hash',None)
        return {**a,'completion':c}
    def _tasks(self,db,user,rid):
        tasks=[]
        for row in db.execute('SELECT * FROM growth_tasks WHERE user_id=? AND roadmap_id=? ORDER BY stage_ordinal,priority,rowid',(user,rid)):
            t=dict(row);t['key']=t.pop('task_key');t['metadata']=json.loads(t.pop('metadata_json'));t['reason']=REASONS.get(t['reason_code'],'请检查当前课程与能力要求。');t['locked']=bool(t['locked']);t['pinned']=bool(t['pinned']);t.pop('user_id');tasks.append(t)
        return tasks
    def roadmap(self,user,gid,version=None):
        self.goal(user,gid)
        with self.store.connect() as db:
            row=db.execute('SELECT * FROM growth_roadmaps WHERE user_id=? AND goal_id=?'+(' AND version=?' if version is not None else '')+' ORDER BY version DESC LIMIT 1',(user,gid,*([version] if version is not None else []))).fetchone()
            versions=[dict(r) for r in db.execute('SELECT version,status,created_at FROM growth_roadmaps WHERE user_id=? AND goal_id=? ORDER BY version DESC',(user,gid))]
            changes=[{'from_version':r['from_version'],'to_version':r['to_version'],'reason_codes':json.loads(r['reason_codes_json']),'diff':json.loads(r['diff_json']),'created_at':r['created_at']} for r in db.execute('SELECT * FROM growth_roadmap_changes WHERE user_id=? AND goal_id=? ORDER BY rowid DESC',(user,gid))]
            if not row:return {'roadmap':None,'versions':versions,'changes':changes}
            plan=json.loads(row['plan_json']);plan.update(id=row['id'],version=row['version'],status=row['status'],created_at=row['created_at'],tasks=self._tasks(db,user,row['id']))
        return {'roadmap':plan,'versions':versions,'changes':changes}
    def generate(self,user,gid,model=None,reason='USER_REQUESTED_REPLAN',automatic=False):
        if reason not in TRIGGERS:raise ValueError('重规划原因无效')
        g,inputs,a,completion=self._analysis(user,gid)
        if g['requirements_stale']:raise ValueError('目标范围已变化，请先重新分析并确认能力要求')
        previous=self.roadmap(user,gid)['roadmap']
        if previous and previous['status']=='stale':reason=g['graph'].get('pending_reason','PROFILE_CHANGED')
        if g['status'] not in {'active','achieved'}:raise ValueError('请先恢复目标，再生成路线')
        if automatic and previous and previous['status']=='stale':return {'pending_replan':True,'reason':'目标或能力结构已变化，请确认后重新规划。',**self.roadmap(user,gid)}
        if automatic and previous and (clock()-datetime.fromisoformat(previous['created_at'])).total_seconds()<POLICY['replanning']['min_seconds_between_major_replans']:return {'throttled':True,**self.roadmap(user,gid)}
        plan=GrowthPlanner().build(g,g['graph'],a,inputs,model,previous);plan['gap_snapshot']={gap['capability_id']:gap['status'] for gap in a['gaps']};plan['final_snapshot']={cid:v['mastery_state']['status'] for cid,v in inputs['finals'].items()};rid=identifier();now=iso(clock())
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE');current=self._owned(db,user,gid)
            if current['goal_model_version']!=g['goal_model_version']:raise ValueError('目标已变化，请重新生成路线')
            latest=db.execute('SELECT id,version FROM growth_roadmaps WHERE goal_id=? ORDER BY version DESC LIMIT 1',(gid,)).fetchone()
            if previous and (not latest or latest['id']!=previous['id']):raise ValueError('路线已被其他请求更新，请刷新')
            version=(latest['version'] if latest else 0)+1
            db.execute("UPDATE growth_roadmaps SET status='superseded' WHERE goal_id=? AND status IN ('active','stale')",(gid,))
            stored={k:v for k,v in plan.items() if k!='tasks'};db.execute('INSERT INTO growth_roadmaps VALUES(?,?,?,?,?,?,?,?)',(rid,user,gid,version,'active',json.dumps(stored,ensure_ascii=False),now,now))
            old_by_key={t['key']:t for t in (previous or {}).get('tasks',[])}
            for t in plan['tasks']:
                old=old_by_key.get(t['key'],{})
                for key in ['week_reserved','authentic_task_id','started_at','linked_course_id']:
                    if key in old.get('metadata',{}):t['metadata'][key]=old['metadata'][key]
                db.execute('INSERT INTO growth_tasks VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(t['id'],user,gid,rid,t['key'],t['stage_ordinal'],t['capability_id'],t['task_type'],t['target_id'],t['title'],t['reason_code'],t['priority'],t['estimated_minutes'],t['status'],int(t['locked']),int(t['pinned']),json.dumps(t['metadata'],ensure_ascii=False),now))
            diff={'added':[t['title'] for t in plan['tasks'] if t['key'] not in old_by_key], 'no_longer_required':[t['title'] for t in (previous or {}).get('tasks',[]) if t['key'] not in {n['key'] for n in plan['tasks']}],'gap_changes':[{ 'capability_id':k,'before':(previous or {}).get('gap_snapshot',{}).get(k),'after':v} for k,v in plan['gap_snapshot'].items() if (previous or {}).get('gap_snapshot',{}).get(k)!=v]}
            db.execute('INSERT INTO growth_roadmap_changes VALUES(?,?,?,?,?,?,?,?,?)',(identifier(),user,gid,previous['version'] if previous else None,version,json.dumps([reason]),json.dumps(diff,ensure_ascii=False),a['inputs_hash'],now))
        result=self.evaluate(user,gid,auto=False);result['route_updated']=True;return result
    def evaluate(self,user,gid,auto=True):
        g,inputs,a,completion=self._analysis(user,gid);result=self.roadmap(user,gid);plan=result['roadmap']
        if not plan:return {**result,'analysis':self.gaps(user,gid),'completion':completion}
        if plan['status']=='stale':return {**result,'pending_replan':True,'completion':completion}
        if plan['status']!='active':return result
        triggers=GrowthReplanningEngine().triggers(plan,a,inputs)
        if auto and triggers and g['status'] in {'active','achieved'}:
            generated=self.generate(user,gid,None,triggers[0],automatic=True)
            if generated.get('route_updated'):return generated
        gaps={x['capability_id']:x for x in a['gaps']};first=None
        final_pending=set(completion['final_pending_courses'])
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE');current=self._owned(db,user,gid)
            latest=db.execute('SELECT id FROM growth_roadmaps WHERE goal_id=? ORDER BY version DESC LIMIT 1',(gid,)).fetchone()
            if not latest or latest['id']!=plan['id'] or current['goal_model_version']!=g['goal_model_version']:raise ValueError('路线已变化，请刷新')
            for t in plan['tasks']:
                gap=gaps.get(t['capability_id']);status=t['status'];meta=t['metadata']
                course=inputs['courses'].get(t['target_id']) if t['target_id'] else None
                if t['target_id'] and (not course or course['deleted_at']):status='blocked';meta['blocked_note']='课程位于回收站，请恢复后继续。' if course else '课程已永久删除，请重新规划。'
                elif gap and gap['status']=='sufficient' and t['task_type']!='final_assessment':status='completed'
                elif t['task_type']=='final_assessment' and course and inputs['finals'].get(t['target_id'],{}).get('mastery_state',{}).get('status')=='mastered':status='completed'
                elif gap and status not in {'skipped','paused'}:
                    parents=[e['from'] for e in g['graph']['dependencies'] if e['to']==t['capability_id'] and e['relation']=='prerequisite']
                    blocked=any(gaps[p]['status']!='sufficient' or any(r['course_id'] in final_pending for r in gaps[p]['coverage']) for p in parents)
                    if blocked:status='blocked'
                    elif status in {'blocked','completed'}:status='ready'
                db.execute('UPDATE growth_tasks SET status=?,metadata_json=?,updated_at=? WHERE id=? AND user_id=?',(status,json.dumps(meta,ensure_ascii=False),iso(clock()),t['id'],user))
                t['status']=status
            for s in plan['stages']:
                requirements=[cid for cid in s['capability_ids'] if gaps[cid]['importance']!='optional' or any(e['from']==cid and e['relation']=='prerequisite' for e in g['graph']['dependencies'])]
                done=all(gaps[cid]['status']=='sufficient' and not any(r['course_id'] in final_pending for r in gaps[cid]['coverage']) for cid in requirements)
                if s['gate']['type']=='user_choices':done=all(t['status'] in {'completed','skipped'} for t in plan['tasks'] if t['stage_ordinal']==s['ordinal'])
                s['status']='completed' if done else 'active' if first is None else 'planned'
                if not done and first is None:first=s['ordinal']
            stored={k:v for k,v in plan.items() if k not in {'tasks','id','version','status','created_at'}};stored['current_stage']=first
            db.execute('UPDATE growth_roadmaps SET plan_json=?,updated_at=? WHERE id=?',(json.dumps(stored,ensure_ascii=False),iso(clock()),plan['id']))
            if g['status'] in {'active','achieved'}:db.execute('UPDATE learning_goals SET status=? WHERE id=?',('achieved' if completion['achieved'] else 'active',gid))
        result=self.roadmap(user,gid);result.update(completion=completion,replan_recommended=bool(triggers),replan_reason_codes=triggers);return result
    def task_action(self,user,gid,tid,operation,payload=None):
        payload=payload or {};self.evaluate(user,gid,auto=False);g=self.goal(user,gid)
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE');row=db.execute('SELECT t.*,r.status AS roadmap_status FROM growth_tasks t JOIN growth_roadmaps r ON r.id=t.roadmap_id WHERE t.id=? AND t.user_id=? AND t.goal_id=?',(tid,user,gid)).fetchone()
            if not row or row['roadmap_status']!='active':raise ValueError('任务属于旧路线，请刷新或重新规划')
            current=self._owned(db,user,gid)
            t=dict(row);meta=json.loads(t['metadata_json'])
            plan=json.loads(db.execute('SELECT plan_json FROM growth_roadmaps WHERE id=?',(t['roadmap_id'],)).fetchone()[0])
            if operation=='start':
                if t['stage_ordinal']!=plan.get('current_stage') and t['status']!='completed':raise ValueError('请先满足当前阶段要求；固定顺序不能绕过前置条件')
                if meta.get('deferred_to_later_batch') or meta.get('deadline_deferred_optional'):raise ValueError('此任务暂未排入当前批次，请调整能力范围后重新规划')
                if current['status'] not in {'active','achieved'} or t['status'] in {'blocked','skipped','paused','obsolete'}:raise ValueError('请先恢复目标或满足前置条件；跳过不代表完成')
                if t['status']!='completed':db.execute("UPDATE growth_tasks SET status='active',metadata_json=?,updated_at=? WHERE id=?",(json.dumps({**meta,'started_at':iso(clock()),'week_reserved':today().isocalendar()[:2]}),iso(clock()),tid))
            elif operation in {'skip','pause','resume','lock','pin'}:
                if operation in {'lock','pin'}:
                    if set(payload)-{'enabled'} or type(payload.get('enabled')) is not bool:raise ValueError('请明确设置是否固定')
                    db.execute('UPDATE growth_tasks SET '+('locked' if operation=='lock' else 'pinned')+'=?,updated_at=? WHERE id=?',(int(payload['enabled']),iso(clock()),tid))
                else:
                    if t['status']=='completed':raise ValueError('已有能力依据的任务无需跳过')
                    db.execute('UPDATE growth_tasks SET status=?,updated_at=? WHERE id=?',('skipped' if operation=='skip' else 'paused' if operation=='pause' else 'ready',iso(clock()),tid))
                pass
            else:raise ValueError('任务操作无效')
        if operation!='start':return {'roadmap':self.roadmap(user,gid)['roadmap'],'note':'用户选择不会改变能力缺口或掌握状态。'}
        route={'destination':'course','course_id':t['target_id'],'atom_id':meta.get('atom_id'),'task_type':t['task_type'],'goal_context':{'goal_id':gid,'goal_title':g['title'],'task_id':tid,'task_relevance':t['title']}}
        if t['task_type']=='create_course' and meta.get('linked_course_id'):route.update(destination='course',course_id=meta['linked_course_id'],atom_id=None)
        elif t['task_type']=='create_course':route.update(destination='create_course',title=meta['course_title'],goal=meta['course_goal'],target_capabilities=meta['target_capabilities'])
        elif t['task_type']=='goal_checkpoint':route.update(destination='growth',note='请审查知识关联或补充可验证的实践要求。')
        elif t['task_type'] in {'review','cross_course_verify','micro_practice'}:route.update(destination='atom',prior_id=meta.get('prior_id'),assessment='review' if t['task_type']=='review' else 'diagnostic')
        elif t['task_type']=='final_assessment':route['destination']='final'
        elif t['task_type']=='authentic_assessment':route.update(destination='authentic',assessment=meta.get('assessment','design'))
        return {'route':route}
    def link_course(self,user,gid,tid,cid):
        g=self.goal(user,gid);self.store.managed_course(user,cid)
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE');row=db.execute("SELECT t.* FROM growth_tasks t JOIN growth_roadmaps r ON r.id=t.roadmap_id WHERE t.user_id=? AND t.goal_id=? AND t.id=? AND r.status='active'",(user,gid,tid)).fetchone()
            if not row or row['task_type']!='create_course' or row['status']!='active':raise ValueError('请先打开当前路线的新课程建议')
            meta=json.loads(row['metadata_json'])
            if meta.get('linked_course_id') and meta['linked_course_id']!=cid:raise ValueError('此建议已关联课程，请先重新规划')
            meta['linked_course_id']=cid;meta['course_id']=cid
            db.execute('UPDATE growth_tasks SET target_id=?,metadata_json=? WHERE id=?',(cid,json.dumps(meta,ensure_ascii=False),tid))
        return {'linked':True,'boundary':'记录用户确认创建的课程入口，不作为能力覆盖或掌握证明。'}
    def practice_context(self,user,gid,tid,cid,atom_id):
        g=self.goal(user,gid);plan=self.roadmap(user,gid)['roadmap']
        task=next((t for t in (plan or {}).get('tasks',[]) if t['id']==tid),None)
        if not task or plan['status']!='active' or task['status']!='active' or task['task_type']!='authentic_assessment' or task['target_id']!=cid or task['metadata'].get('atom_id')!=atom_id:raise ValueError('目标实践上下文已失效，请重新打开任务')
        cap=next((c for c in g['graph']['capabilities'] if c['id']==task['capability_id']),None)
        if not cap:raise ValueError('目标能力已变化，请重新规划')
        scope={k:cap[k] for k in ['id','name','description','type','required_level']}
        return {'goal_id':gid,'capability_id':cap['id'],'requirement_hash':fingerprint(scope),'goal_title':g['title'],'capability':scope,'boundary':'围绕这项具体能力设计可独立完成的小任务；不能把一次小任务当作整项比赛或职业认证。'}
    def attach_authentic(self,user,gid,tid,aid):
        if not isinstance(aid,str):raise ValueError('开放任务编号无效')
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE');self._owned(db,user,gid)
            task=db.execute("SELECT t.* FROM growth_tasks t JOIN growth_roadmaps r ON r.id=t.roadmap_id WHERE t.user_id=? AND t.goal_id=? AND t.id=? AND r.status='active'",(user,gid,tid)).fetchone()
            if not task or task['task_type']!='authentic_assessment' or task['status']!='active':raise ValueError('请先启动对应实践任务')
            m=json.loads(task['metadata_json']);artifact=db.execute('SELECT * FROM authentic_tasks WHERE id=? AND user_id=? AND course_id=? AND atom_id=?',(aid,user,task['target_id'],m.get('atom_id'))).fetchone()
            if not artifact or artifact['task_type'] not in {'design','open_transfer'} or artifact['created_at']<m.get('started_at',''):raise ValueError('请选择本次路线实践中产生的对应开放任务')
            scope=json.loads(artifact['task_json']).get('growth_scope',{})
            if scope.get('goal_id')!=gid or scope.get('capability_id')!=task['capability_id']:raise ValueError('此开放任务并非为当前目标能力生成，请启动对应目标实践')
            m['authentic_task_id']=aid;db.execute('UPDATE growth_tasks SET metadata_json=? WHERE id=?',(json.dumps(m),tid))
        return {'attached':True,'boundary':'开放评分只作为目标实践的模型辅助观察，不修改课程掌握状态。'}
    def context(self,user,cid,atom_ids=None):
        with self.store.connect() as db:
            rows=db.execute("SELECT t.*,g.title AS goal_title,r.plan_json FROM growth_tasks t JOIN learning_goals g ON g.id=t.goal_id JOIN growth_roadmaps r ON r.id=t.roadmap_id JOIN courses c ON c.id=t.target_id WHERE t.user_id=? AND g.user_id=? AND c.session_id=? AND t.target_id=? AND g.status='active' AND r.status='active' AND t.status='active' ORDER BY t.updated_at DESC LIMIT 4",(user,user,user,cid)).fetchall()
        for r in rows:
            meta=json.loads(r['metadata_json'])
            if atom_ids is not None and meta.get('atom_id') not in atom_ids:continue
            stages=json.loads(r['plan_json'])['stages'];s=next((s for s in stages if s['ordinal']==r['stage_ordinal']),{})
            return {'goal_title':r['goal_title'],'current_stage_objective':s.get('objective',''),'current_task_relevance':r['title']}
        return None
    def course_context(self,user,gid,tid):
        g=self.goal(user,gid);plan=self.roadmap(user,gid)['roadmap'];t=next((t for t in (plan or {}).get('tasks',[]) if t['id']==tid and t['task_type']=='create_course'),None)
        if not t or plan['status']!='active':raise ValueError('课程建议属于旧路线，请重新规划')
        return {'goal_title':g['title'],'target_capabilities':t['metadata']['target_capabilities'],'scope':'优先覆盖所列目标缺口；必要基础保留在完整章节中，通过验证后可简短回顾。'}
    def dashboard(self,user):
        goals=self.goals(user)['goals'];active=[g for g in goals if g['status']=='active'];items=[];budgets=[g['weekly_time_budget_minutes'] for g in active if g['weekly_time_budget_minutes'] is not None]
        for g in active:
            plan=self.roadmap(user,g['id'])['roadmap']
            if not plan or plan['status']!='active':continue
            for t in plan['tasks']:
                if t['status'] not in {'ready','active'} or t['stage_ordinal']!=plan.get('current_stage'):continue
                items.append({'goal_id':g['id'],'goal_title':g['title'],'task_id':t['id'],'title':t['title'],'reason':t.get('reason',REASONS.get(t['reason_code'],'请检查当前任务要求。')),'task_type':t['task_type'],'course_id':t['target_id'],'atom_id':t['metadata'].get('atom_id'),'estimated_minutes':t['estimated_minutes'],'priority':(0 if t['status']=='active' else 1,0 if t['pinned'] else 1,g['priority'],t['priority'])})
        # Read the original scheduler once; no new review policy or evidence writes.
        if active:
            inputs=GrowthInputReader(self.store).read(user)
            for c in sorted(inputs['courses'].values(),key=lambda c:c['sort_order']):
                if c['deleted_at'] or c['status']!='active' or any(i.get('course_id')==c['id'] for i in items):continue
                items.append({'title':c['title'],'reason':'继续你正在学习的课程，章节仍由你手动推进。','task_type':'continue_course','course_id':c['id'],'atom_id':None,'estimated_minutes':POLICY['minutes']['continue_course'],'priority':(3,0,0,c['sort_order'])})
                break
            for r in inputs['reviews']:items.append({'title':r['title'],'reason':r['reason'],'task_type':'review','course_id':r['course_id'],'atom_id':r['atom_id'],'estimated_minutes':r['minutes'],'priority':(-1,r['priority'],0,0)})
        items.sort(key=lambda i:i['priority']);limit=min(budgets) if budgets else None;daily=math.ceil(limit/5) if limit else None;selected=[];remaining=daily;weekly=[];week_left=limit
        seen=set()
        for item in items:
            key=(item.get('course_id'),item.get('atom_id'),item['task_type']) if item.get('course_id') else item.get('task_id')
            if key in seen:continue
            seen.add(key);item={k:v for k,v in item.items() if k!='priority'}
            if week_left is None or week_left>0:
                w={**item,'planned_minutes':item['estimated_minutes'] if week_left is None else min(item['estimated_minutes'],week_left)};weekly.append(w)
                if week_left is not None:week_left-=w['planned_minutes']
            if len(selected)<3 and (remaining is None or remaining>0):
                item['planned_minutes']=item['estimated_minutes'] if remaining is None else min(item['estimated_minutes'],remaining);selected.append(item)
                if remaining is not None:remaining-=item['planned_minutes']
        return {'goals':active[:3],'today':selected,'weekly':weekly,'weekly_budget':limit,'today_budget':daily,'boundary':'时间为规则估计；较长任务可分次进行。不是严格日程或实际用时统计，建议不会自动创建课程或推进章节。'}
