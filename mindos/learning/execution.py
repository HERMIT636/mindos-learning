"""Voluntary local execution records. Never writes knowledge, evidence or task completion."""
import json, math, secrets
from pathlib import Path
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from .policy import clock, date as parse_time

def iso(at):return at.isoformat(timespec="microseconds")

POLICY = json.loads(Path(__file__).with_name('execution_policy.json').read_text())
ACTIVITIES = {'course_learning', 'review', 'cross_course_verify', 'final_assessment',
              'authentic_assessment', 'micro_practice', 'goal_task', 'free_study'}
ACTIVITY_NAMES = {'authentic_assessment':'开放实践','course_learning':'课程学习','cross_course_verify':'跨课程验证','final_assessment':'课程检测','free_study':'自主学习','goal_task':'目标任务','micro_practice':'小练习','review':'复习'}
TASK_ACTIVITY = {'continue_course':'course_learning', 'start_course':'course_learning',
                 'create_course':'goal_task', 'goal_checkpoint':'goal_task',
                 **{v:v for v in ACTIVITIES if v not in {'course_learning','free_study','goal_task'}}}
UNFINISHED = ('active', 'paused', 'interrupted')
REASONS = {'finished','time_box_end','user_stopped','blocked','too_difficult','interrupted','route_changed'}
SCHEMA = '''
CREATE TABLE IF NOT EXISTS study_sessions (
 id TEXT PRIMARY KEY,user_id TEXT NOT NULL,goal_id TEXT,roadmap_id TEXT,growth_task_id TEXT,
 course_id TEXT,atom_id TEXT,title TEXT NOT NULL,activity_type TEXT NOT NULL,status TEXT NOT NULL,
 planned_minutes REAL NOT NULL,base_minutes REAL NOT NULL,started_at TEXT NOT NULL,ended_at TEXT,
 active_seconds REAL NOT NULL DEFAULT 0,paused_seconds REAL NOT NULL DEFAULT 0,
 segment_started_at TEXT NOT NULL,last_checkpoint_at TEXT NOT NULL,
 completion_ratio REAL NOT NULL DEFAULT 0,completion_reason TEXT,source TEXT NOT NULL,
 adjusted_by_user INTEGER NOT NULL DEFAULT 0,invalid_for_pace INTEGER NOT NULL DEFAULT 0,
 was_interrupted INTEGER NOT NULL DEFAULT 0,outcome_json TEXT NOT NULL DEFAULT '{}',
 created_at TEXT NOT NULL,updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS one_active_study_session ON study_sessions(user_id) WHERE status='active';
CREATE INDEX IF NOT EXISTS study_session_owner_time ON study_sessions(user_id,started_at);
CREATE INDEX IF NOT EXISTS study_session_owner_status ON study_sessions(user_id,status);
CREATE INDEX IF NOT EXISTS study_session_task ON study_sessions(user_id,growth_task_id);
CREATE INDEX IF NOT EXISTS study_session_course ON study_sessions(user_id,course_id);
CREATE INDEX IF NOT EXISTS study_session_pace ON study_sessions(user_id,activity_type,status,updated_at);
CREATE TABLE IF NOT EXISTS task_execution_events (
 id INTEGER PRIMARY KEY AUTOINCREMENT,user_id TEXT NOT NULL,session_id TEXT NOT NULL,event_type TEXT NOT NULL,
 payload_json TEXT NOT NULL,created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS execution_event_owner ON task_execution_events(user_id,id);
CREATE TABLE IF NOT EXISTS pace_snapshots (
 user_id TEXT PRIMARY KEY,profile_json TEXT NOT NULL,source_cursor INTEGER NOT NULL,
 policy_version TEXT NOT NULL,updated_at TEXT NOT NULL
);
'''
def migrate(db): db.executescript(SCHEMA)
def activity(task_type): return TASK_ACTIVITY.get(task_type,'goal_task')
def bucket(minutes): return 'short' if minutes <= 10 else 'medium' if minutes <= 30 else 'long'
def number(value,minimum=0,maximum=1440):
    if type(value) not in {int,float} or not math.isfinite(value) or not minimum <= value <= maximum:
        raise ValueError('时间应为范围内的有效分钟数')
    return float(value)
def event(db,user,sid,kind,payload,at):
    db.execute('INSERT INTO task_execution_events(user_id,session_id,event_type,payload_json,created_at) VALUES(?,?,?,?,?)',
               (user,sid,kind,json.dumps(payload,ensure_ascii=False),iso(at)))

class StudySessionService:
    def __init__(self,store,now=None): self.store=store; self.now=now or clock
    def _owned(self,db,user,sid):
        row=db.execute('SELECT * FROM study_sessions WHERE id=? AND user_id=?',(sid,user)).fetchone()
        if not row: raise ValueError('学习记录不存在')
        return dict(row)
    def _course(self,db,user,cid,atom=None):
        row=db.execute('SELECT * FROM courses WHERE id=? AND session_id=? AND deleted_at IS NULL',(cid,user)).fetchone()
        if not row: raise ValueError('课程不存在或位于回收站')
        if atom:
            graph=db.execute('SELECT graph_json FROM course_graphs WHERE course_id=?',(cid,)).fetchone()
            if not graph or atom not in {a['id'] for a in json.loads(graph[0])['atoms']}: raise ValueError('知识点不属于课程')
        return row['title']
    def _recover(self,db,user,at):
        for row in db.execute("SELECT * FROM study_sessions WHERE user_id=? AND status='active'",(user,)).fetchall():
            if (at-parse_time(row['last_checkpoint_at'])).total_seconds() > POLICY['session']['stale_active_minutes']*60:
                # All time up to the last live checkpoint was already settled. No offline interval is added.
                db.execute("UPDATE study_sessions SET status='interrupted',was_interrupted=1,segment_started_at=?,updated_at=? WHERE id=?",(iso(at),iso(at),row['id']))
                event(db,user,row['id'],'interrupted',{'reason':'stale_checkpoint','stopped_at':row['last_checkpoint_at']},at)
    def _settle(self,db,s,at):
        seconds=max(0,(at-parse_time(s['segment_started_at'])).total_seconds())
        field='active_seconds' if s['status']=='active' else 'paused_seconds' if s['status']=='paused' else None
        if field:
            s[field]+=seconds
            if seconds:event(db,s['user_id'],s['id'],'interval',{'kind':s['status'],'from':s['segment_started_at'],'until':iso(at),'seconds':seconds},at)
        s['segment_started_at']=iso(at);s['last_checkpoint_at']=iso(at)
        db.execute('UPDATE study_sessions SET active_seconds=?,paused_seconds=?,segment_started_at=?,last_checkpoint_at=?,updated_at=? WHERE id=?',
                   (s['active_seconds'],s['paused_seconds'],iso(at),iso(at),iso(at),s['id']))
    def _snapshot(self,db,user,cid,atom,tid):
        states=[dict(r) for r in db.execute('SELECT atom_id,state_json FROM knowledge_states WHERE user_id=? AND course_id=?'+(' AND atom_id=?' if atom else '')+' ORDER BY atom_id',(user,cid,*([atom] if atom else [])))] if cid else []
        task=db.execute('SELECT status FROM growth_tasks WHERE id=? AND user_id=?',(tid,user)).fetchone() if tid else None
        maximum=db.execute('SELECT COALESCE(MAX(rowid),0) FROM learning_evidence WHERE user_id=?',(user,)).fetchone()[0]
        return {'states':states,'evidence_cursor':maximum,'task_state':task[0] if task else None}
    def _public(self,s,at=None):
        result={k:v for k,v in s.items() if k not in {'user_id','outcome_json','segment_started_at','last_checkpoint_at'}}
        result['outcome']=json.loads(s['outcome_json']);result['server_time']=iso(at or self.now())
        result['segment_started_at']=s['segment_started_at']
        result['needs_duration_confirmation']=s['active_seconds']>POLICY['session']['max_reasonable_session_minutes']*60
        result['checkpoint_seconds']=POLICY['session']['checkpoint_seconds']
        result['boundary']='仅记录你主动开始的学习时段，不监测专注程度；时长不代表掌握程度。'
        return result
    def start(self,user,payload):
        allowed={'growth_task_id','course_id','atom_id','activity_type','source','planned_minutes'}
        if not isinstance(payload,dict) or set(payload)-allowed: raise ValueError('学习记录字段无效；不能提供掌握状态')
        for key in ['growth_task_id','course_id','atom_id']:
            if payload.get(key) is not None and (not isinstance(payload[key],str) or not 1<=len(payload[key])<=100):raise ValueError('课程或任务编号格式无效')
        at=self.now();sid=secrets.token_urlsafe(16)
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE');self._recover(db,user,at)
            if db.execute("SELECT 1 FROM study_sessions WHERE user_id=? AND status IN ('active','paused','interrupted')",(user,)).fetchone(): raise ValueError('请先继续或结束当前学习记录')
            tid=payload.get('growth_task_id');cid=payload.get('course_id');atom=payload.get('atom_id');gid=rid=None
            kind=payload.get('activity_type','course_learning');base=25;title='自主学习'
            if not isinstance(kind,str):raise ValueError('学习活动类型无效')
            base=POLICY['activity_minutes'].get(kind,25)
            if tid:
                t=db.execute("SELECT t.*,g.status AS goal_status,r.status AS route_status,r.plan_json FROM growth_tasks t JOIN learning_goals g ON g.id=t.goal_id AND g.user_id=t.user_id JOIN growth_roadmaps r ON r.id=t.roadmap_id AND r.user_id=t.user_id WHERE t.id=? AND t.user_id=?",(tid,user)).fetchone()
                if not t or t['route_status']!='active' or t['goal_status'] not in {'active','achieved'} or t['status'] not in {'ready','active'}: raise ValueError('请选择当前路线中可执行的任务')
                meta=json.loads(t['metadata_json']);plan=json.loads(t['plan_json'])
                if t['stage_ordinal']!=plan.get('current_stage') or meta.get('deferred_to_later_batch') or meta.get('deadline_deferred_optional'): raise ValueError('请先满足当前阶段前置要求')
                target=t['target_id'] or meta.get('linked_course_id');target_atom=meta.get('atom_id')
                if cid and cid!=target or atom and atom!=target_atom:raise ValueError('学习记录与任务课程不一致')
                cid=target;atom=target_atom;gid=t['goal_id'];rid=t['roadmap_id'];kind=activity(t['task_type']);base=t['estimated_minutes'];title=t['title']
                if payload.get('activity_type',kind)!=kind:raise ValueError('任务类型由当前路线确定')
            if kind not in ACTIVITIES: raise ValueError('学习活动类型无效')
            if cid:
                course_title=self._course(db,user,cid,atom)
                if not tid:title=course_title
            elif atom:raise ValueError('请先选择知识点所属课程')
            elif kind not in {'goal_task','free_study'}:raise ValueError('此学习活动需要课程上下文')
            source=payload.get('source','growth' if tid else 'course' if cid else 'free')
            if not isinstance(source,str) or source not in {'growth','course','review','assessment','free','today'}:raise ValueError('学习入口无效')
            planned=number(payload.get('planned_minutes',base))
            outcome={'before':self._snapshot(db,user,cid,atom,tid)}
            values={'id':sid,'user_id':user,'goal_id':gid,'roadmap_id':rid,'growth_task_id':tid,'course_id':cid,'atom_id':atom,'title':title,'activity_type':kind,'status':'active','planned_minutes':planned,'base_minutes':base,'started_at':iso(at),'segment_started_at':iso(at),'last_checkpoint_at':iso(at),'source':source,'outcome_json':json.dumps(outcome),'created_at':iso(at),'updated_at':iso(at)}
            db.execute('INSERT INTO study_sessions('+','.join(values)+') VALUES('+','.join('?' for _ in values)+')',tuple(values.values()))
            event(db,user,sid,'started',{'activity_type':kind,'planned_minutes':planned},at)
            s=self._owned(db,user,sid)
        return {'session':self._public(s,at)}
    def current(self,user):
        at=self.now()
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE');self._recover(db,user,at)
            row=db.execute("SELECT * FROM study_sessions WHERE user_id=? AND status IN ('active','paused','interrupted') ORDER BY started_at DESC LIMIT 1",(user,)).fetchone()
            s=dict(row) if row else None
        if s and s['status'] in {'active','paused'}:
            field='active_seconds' if s['status']=='active' else 'paused_seconds'
            s[field]+=max(0,(at-parse_time(s['segment_started_at'])).total_seconds());s['segment_started_at']=iso(at)
        return {'session':self._public(s,at) if s else None,'activity_defaults':POLICY['activity_minutes']}
    def action(self,user,sid,op,payload=None):
        payload=payload or {};at=self.now()
        allowed={'end':{'completion','reason','adjusted_active_minutes','confirm_long_duration','invalid_for_pace'},'adjust':{'adjusted_active_minutes','invalid_for_pace'}}.get(op,set())
        if not isinstance(payload,dict) or set(payload)-allowed:raise ValueError('学习记录操作字段无效')
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE');self._recover(db,user,at);s=self._owned(db,user,sid)
            if op=='delete':
                if s['status'] in UNFINISHED:raise ValueError('请先结束记录，再删除')
                db.execute('DELETE FROM pace_snapshots WHERE user_id=?',(user,))
                db.execute('DELETE FROM task_execution_events WHERE session_id=? AND user_id=?',(sid,user));db.execute('DELETE FROM study_sessions WHERE id=? AND user_id=?',(sid,user))
                event(db,user,sid,'deleted',{},at);return {'deleted':True}
            if op=='adjust':
                if s['status'] in UNFINISHED:raise ValueError('请在结束时修正时间')
                if 'adjusted_active_minutes' not in payload:raise ValueError('请填写实际学习分钟数')
            elif op not in {'pause','resume','checkpoint','end'}:raise ValueError('学习操作无效')
            elif s['status'] not in UNFINISHED:
                if op=='end':return {'session':self._public(s,at)}
                raise ValueError('学习记录已经结束')
            if op in {'pause','resume'} and s['status']==('paused' if op=='pause' else 'active'):return {'session':self._public(s,at)}
            if op=='pause' and s['status']!='active':raise ValueError('请先继续中断的学习记录')
            if op!='adjust':self._settle(db,s,at)
            if op in {'pause','resume'}:
                status='paused' if op=='pause' else 'active'
                if status=='active' and db.execute("SELECT 1 FROM study_sessions WHERE user_id=? AND status='active' AND id!=?",(user,sid)).fetchone():raise ValueError('已有正在计时的学习记录')
                db.execute('UPDATE study_sessions SET status=? WHERE id=?',(status,sid));event(db,user,sid,'paused' if op=='pause' else 'resumed',{},at)
            elif op=='checkpoint':
                # One checkpoint per minute is enough for an audit trail; the time ledger still settles.
                last=db.execute("SELECT created_at FROM task_execution_events WHERE session_id=? AND event_type='checkpoint' ORDER BY id DESC LIMIT 1",(sid,)).fetchone()
                if s['status']=='active' and (not last or (at-parse_time(last[0])).total_seconds()>=60):event(db,user,sid,'checkpoint',{},at)
            else:
                adjusted=payload.get('adjusted_active_minutes')
                seconds=number(adjusted,maximum=POLICY['session']['max_adjusted_minutes'])*60 if adjusted is not None else s['active_seconds']
                for flag in ['invalid_for_pace','confirm_long_duration']:
                    if flag in payload and type(payload[flag]) is not bool:raise ValueError('请明确确认时间与无效记录标记')
                if seconds>POLICY['session']['max_reasonable_session_minutes']*60 and not payload.get('confirm_long_duration') and adjusted is None:raise ValueError('这条记录时长较长，请确认或修正实际学习时间')
                if op=='end':
                    completion=payload.get('completion','partial');ratios={'not_started':0,'partial':.5,'mostly_done':.75,'done':1}
                    if not isinstance(completion,str) or completion not in ratios:raise ValueError('请选择本次完成情况')
                    reason=payload.get('reason','user_stopped')
                    if not isinstance(reason,str) or reason not in REASONS:raise ValueError('学习结束原因无效')
                    status='abandoned' if reason in {'blocked','too_difficult','route_changed'} or ratios[completion]==0 else 'completed'
                    before=json.loads(s['outcome_json']).get('before',{});after=self._snapshot(db,user,s['course_id'],s['atom_id'],s['growth_task_id'])
                    evidence=[dict(r) for r in db.execute('SELECT score,metadata_json FROM learning_evidence WHERE user_id=? AND course_id=? AND rowid>?'+(' AND atom_id=?' if s['atom_id'] else ''),(user,s['course_id'],before.get('evidence_cursor',0),*([s['atom_id']] if s['atom_id'] else [])))] if s['course_id'] else []
                    outcome={'evidence_count':len(evidence),'graded_evidence_count':sum(e['score'] is not None for e in evidence),'quiz_count':len({json.loads(e['metadata_json']).get('quiz_id') for e in evidence if json.loads(e['metadata_json']).get('quiz_id')}),'task_state_before':before.get('task_state'),'task_state_after':after['task_state'],'knowledge_state_changed':before.get('states',[])!=after['states'],'boundary':'只是已有学习结果的观察，不生成证据或学习效率评分。'}
                    db.execute('UPDATE study_sessions SET status=?,ended_at=?,completion_ratio=?,completion_reason=?,outcome_json=? WHERE id=?',(status,iso(at),ratios[completion],reason,json.dumps(outcome,ensure_ascii=False),sid))
                    event(db,user,sid,status,{'completion':completion,'reason':reason},at)
                if adjusted is not None or 'invalid_for_pace' in payload:
                    db.execute('UPDATE study_sessions SET active_seconds=?,adjusted_by_user=?,invalid_for_pace=? WHERE id=?',(seconds,int(adjusted is not None or s['adjusted_by_user']),int(payload.get('invalid_for_pace',bool(s['invalid_for_pace']))),sid))
                    event(db,user,sid,'adjusted',{'active_minutes':seconds/60,'adjusted_by_user':adjusted is not None},at)
            s=self._owned(db,user,sid)
        return {'session':self._public(s,at)}
    def history(self,user,filters=None):
        filters=filters or {};where=['user_id=?'];values=[user]
        if set(filters)-{'date_from','date_to','course_id','goal_id','before','limit'}:raise ValueError('记录筛选字段无效')
        for k in ['course_id','goal_id']:
            if filters.get(k):where.append(k+'=?');values.append(filters[k])
        for key,op in [('date_from','>='),('date_to','<')]:
            if filters.get(key):
                try:d=datetime.strptime(filters[key],'%Y-%m-%d').replace(tzinfo=ZoneInfo('Asia/Shanghai'))
                except (TypeError,ValueError):raise ValueError('记录日期格式无效')
                if key=='date_to':d+=timedelta(days=1)
                where.append('started_at'+op+'?');values.append(iso(d))
        if filters.get('before'):
            try:cursor=int(filters['before'])
            except (ValueError,TypeError):raise ValueError('分页位置无效')
            where.append('rowid<?');values.append(cursor)
        try:limit=max(1,min(100,int(filters.get('limit',50))))
        except (TypeError,ValueError):raise ValueError('记录条数无效')
        with self.store.connect() as db:rows=[dict(r) for r in db.execute('SELECT rowid AS cursor,* FROM study_sessions WHERE '+' AND '.join(where)+' ORDER BY rowid DESC LIMIT ?',(*values,limit+1))]
        return {'sessions':[self._public(s) for s in rows[:limit]],'next_cursor':rows[limit-1]['cursor'] if len(rows)>limit else None}
