"""Execution load and deadline rules. Read-only with respect to P0–P4."""
import json, math, statistics
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from .policy import clock, iso, date as parse_time
from .execution import POLICY, activity, StudySessionService
from .pace import DurationEstimator, PersonalPaceModel

TZ=ZoneInfo('Asia/Shanghai')
def week_start(at):
    local=at.astimezone(TZ).replace(hour=0,minute=0,second=0,microsecond=0)
    return local-timedelta(days=local.weekday())
def observed_seconds(s,at):
    seconds=s['active_seconds']
    if s['status']=='active':
        gap=(at-parse_time(s['last_checkpoint_at'])).total_seconds()
        if gap<=POLICY['session']['stale_active_minutes']*60:seconds+=max(0,(at-parse_time(s['segment_started_at'])).total_seconds())
    return seconds

def execution_minutes(store,user,start,end,at,goal_id=None):
    """Split actual active intervals at day/week boundaries; corrected records use their declared start day."""
    total=0
    with store.connect() as db:
        scope=' AND s.goal_id=?' if goal_id else ''
        args=(user,iso(start),*([goal_id] if goal_id else []))
        intervals=db.execute("SELECT e.payload_json FROM task_execution_events e JOIN study_sessions s ON s.id=e.session_id AND s.user_id=e.user_id WHERE e.user_id=? AND e.event_type='interval' AND e.created_at>=? AND s.adjusted_by_user=0"+scope,args)
        for row in intervals:
            p=json.loads(row[0])
            if p['kind']!='active':continue
            a=max(start,parse_time(p['from']));b=min(end,parse_time(p['until']))
            total+=max(0,(b-a).total_seconds())
        corrected=db.execute('SELECT active_seconds FROM study_sessions s WHERE s.user_id=? AND s.adjusted_by_user=1 AND s.started_at>=? AND s.started_at<?'+scope,(user,iso(start),iso(end),*([goal_id] if goal_id else [])))
        total+=sum(r[0] for r in corrected)
        active=db.execute("SELECT s.* FROM study_sessions s WHERE s.user_id=? AND s.status='active' AND s.adjusted_by_user=0"+scope,(user,*([goal_id] if goal_id else [])))
        for row in active:
            if (at-parse_time(row['last_checkpoint_at'])).total_seconds()>POLICY['session']['stale_active_minutes']*60:continue
            total+=max(0,(min(end,at)-max(start,parse_time(row['segment_started_at']))).total_seconds())
    return total/60

class AdaptiveDailyLoadPlanner:
    def __init__(self,store,now=None):self.store=store;self.now=now or clock
    def build(self,user,goals,items):
        at=self.now();estimate=DurationEstimator(self.store,user);start=week_start(at);day=at.astimezone(TZ).replace(hour=0,minute=0,second=0,microsecond=0)
        # Reads include carried active records; stale records only count settled time.
        with self.store.connect() as db:
            rows=[dict(r) for r in db.execute('SELECT * FROM study_sessions WHERE user_id=? AND (started_at>=? OR status IN (\'active\',\'paused\',\'interrupted\'))',(user,iso(start)))]
        spent_week=execution_minutes(self.store,user,start,at,at)
        spent_day=execution_minutes(self.store,user,day,at,at)
        budgets=[g['weekly_time_budget_minutes'] for g in goals if g.get('weekly_time_budget_minutes') is not None]
        weekly_budget=min(budgets) if budgets else None
        week_remaining=max(0,weekly_budget-spent_week) if weekly_budget is not None else None
        daily_budget=math.ceil(weekly_budget/POLICY['daily']['default_active_days_per_week']) if weekly_budget is not None else None
        daily_remaining=min(max(0,daily_budget-spent_day),week_remaining) if daily_budget is not None else None
        prepared=[];seen=set();goal_index={g['id']:g for g in goals};active=next((s for s in rows if s['status'] in {'active','paused','interrupted'}),None)
        # Restore the exact in-flight context even if it no longer appears in today's P4 list.
        if active and not any(t.get('task_id')==active['growth_task_id'] and active['growth_task_id'] or not active['growth_task_id'] and t.get('course_id')==active['course_id'] and t.get('task_type')==active['activity_type'] for t in items):
            items=[{'title':active['title'],'reason':'继续或结束尚未结束的学习记录。','course_id':active['course_id'],'atom_id':active['atom_id'],'goal_id':active['goal_id'],'task_id':active['growth_task_id'],'task_type':active['activity_type'],'estimated_minutes':active['base_minutes'],'status':'active'},*items]
        for item in items:
            key=('growth',item['task_id']) if item.get('task_id') else ('course',item.get('course_id'),item.get('atom_id'),item['task_type'])
            if key in seen:continue
            seen.add(key);kind=activity(item['task_type']) if item['task_type'] not in {'course_learning','free_study'} else item['task_type']
            prediction=estimate.predict(item['estimated_minutes'],kind)
            unfinished=bool(active and ((item.get('task_id')==active['growth_task_id'] and active['growth_task_id']) or (not active['growth_task_id'] and item.get('course_id')==active['course_id'] and item.get('atom_id')==active['atom_id'] and kind==active['activity_type'])))
            urgency=0 if kind=='review' else 1 if unfinished else 2 if item.get('critical') else 3 if item.get('prerequisite') else 4 if kind in {'cross_course_verify','final_assessment'} else 5 if kind in {'authentic_assessment','micro_practice'} else 6
            g=goal_index.get(item.get('goal_id'),{});deadline=g.get('deadline') or '9999-12-31'
            prepared.append({**{k:v for k,v in item.items() if k!='priority'},**prediction,'source_type':'growth' if item.get('task_id') else 'review' if kind=='review' else 'course','source_id':item.get('task_id') or item.get('atom_id') or item.get('course_id'),'activity_type':kind,'can_split':kind in {'course_learning','micro_practice'},'urgency':urgency,'session_id':active['id'] if unfinished else None,'status':'active' if unfinished else item.get('status','ready'),'_rank':(urgency,g.get('priority',5),deadline,0 if item.get('pinned') else 1,item.get('priority',(9,)))})
        prepared.sort(key=lambda t:t['_rank']);ordered=[];remaining=list(prepared)
        # Round-robin critical tasks across goals after urgent reviews and the in-flight task.
        while remaining:
            t=remaining.pop(0);ordered.append(t)
            if POLICY['daily']['multi_goal_fairness'] and t.get('goal_id') and t['urgency']>=2:
                other=next((o for o in remaining if o.get('goal_id') and o['goal_id'] not in {x.get('goal_id') for x in ordered} and o['urgency']<=3),None)
                if other:remaining.remove(other);ordered.append(other)
        def select(limit,budget):
            selected=[];left=budget
            for task in ordered:
                if len(selected)>=limit:break
                t={k:v for k,v in task.items() if k!='_rank'}
                wanted=t['predicted_minutes']
                if left is not None and left<=0:break
                if left is not None and wanted>left:
                    if not t['can_split']:continue
                    t['planned_minutes']=round(left,1);t['split']=True;t['reason']+=' 今天先进行一段学习，结束计时不表示任务完成。'
                else:t['planned_minutes']=wanted;t['split']=False
                if t['planned_minutes']<=0:continue
                selected.append(t)
                if left is not None:left-=t['planned_minutes']
            return selected
        return {'goals':goals[:3],'today':select(POLICY['daily']['max_today_tasks'],daily_remaining),'weekly':select(POLICY['daily']['max_week_tasks'],week_remaining),'weekly_budget':weekly_budget,'today_budget':daily_budget,'weekly_actual_minutes':round(spent_week,1),'today_actual_minutes':round(spent_day,1),'today_remaining_minutes':round(daily_remaining,1) if daily_remaining is not None else None,'weekly_remaining_minutes':round(week_remaining,1) if week_remaining is not None else None,'current_session_id':active['id'] if active else None,'boundary':'只建议1～3个重点；短时段学习不代表任务完成。完整检测不拆分。预算按每周5个学习日参考，计时不判断掌握或专注。'}

class DeadlineFeasibilityAnalyzer:
    def analyze(self,remaining_minutes,deadline,actual_capacity,budget,observed_weeks,at=None):
        at=at or clock();insufficient=observed_weeks<POLICY['deadline']['minimum_observed_weeks']
        capacity=budget if insufficient else actual_capacity
        weeks=max(0,((datetime.fromisoformat(deadline).replace(tzinfo=TZ)+timedelta(days=1))-at).total_seconds()/604800) if deadline else None
        available=weeks*capacity if weeks is not None and capacity is not None else None
        if insufficient or available is None:status='insufficient_data'
        elif remaining_minutes>available:status='unlikely'
        elif remaining_minutes*POLICY['deadline']['risk_buffer']>available:status='at_risk'
        else:status='on_track'
        return {'status':status,'remaining_minutes':math.ceil(remaining_minutes),'capacity_minutes_per_week':round(capacity) if capacity is not None else None,'actual_capacity_minutes_per_week':round(actual_capacity) if actual_capacity is not None else None,'budget_minutes_per_week':budget,'capacity_source':'budget_fallback' if insufficient else 'observed','reference_available_minutes':round(available) if available is not None else None,'summary':{'insufficient_data':'记录不足，暂按计划预算作参考，不能确认截止日期可行。','unlikely':'按最近记录的节奏，剩余时间可能不足。','at_risk':'时间余量较小，建议调整预算或路线安排。','on_track':'按最近记录的节奏，时间暂有余量。'}[status],'boundary':'工程规则参考，不是完成概率或日期承诺；记录时长也可能不完整。'}

class PlanRealityAnalyzer:
    def __init__(self,store,now=None):self.store=store;self.now=now or clock
    def analyze(self,user,gid):
        from .growth import GrowthService
        svc=GrowthService(self.store);g=svc.goal(user,gid);roadmap=svc.roadmap(user,gid)['roadmap'];at=self.now();start=week_start(at);oldest=start-timedelta(weeks=POLICY['reality']['lookback_weeks'])
        with self.store.connect() as db:
            rows=[dict(r) for r in db.execute('SELECT * FROM study_sessions WHERE user_id=? AND goal_id=? AND started_at>=? ORDER BY started_at,rowid',(user,gid,iso(oldest)))]
            pauses=db.execute("SELECT COUNT(*) FROM task_execution_events WHERE user_id=? AND event_type='paused' AND created_at>=? AND session_id IN (SELECT id FROM study_sessions WHERE user_id=? AND goal_id=?)",(user,iso(oldest),user,gid)).fetchone()[0]
        weeks=[];budget=g['weekly_time_budget_minutes'];first=min((parse_time(s['started_at']) for s in rows),default=None)
        for i in range(POLICY['reality']['lookback_weeks'], -1, -1):
            a=start-timedelta(weeks=i);b=a+timedelta(weeks=1);sessions=[s for s in rows if iso(a)<=s['started_at']<iso(b)];actual=execution_minutes(self.store,user,a,min(b,at),at,gid)
            weeks.append({'week_start':a.date().isoformat(),'planned_minutes':budget,'actual_minutes':round(actual,1),'session_planned_minutes':round(sum(s['planned_minutes'] for s in sessions),1),'weekly_execution_ratio':actual/budget if budget else None,'complete_week':b<=at and first is not None and first<=a})
        complete=[w for w in weeks if w['complete_week']];capacity=statistics.median([w['actual_minutes'] for w in complete[-2:]]) if complete else None
        estimator=DurationEstimator(self.store,user)
        tasks=[t for t in (roadmap or {}).get('tasks',[]) if t['status'] not in {'completed','obsolete'} and not t['metadata'].get('deadline_deferred_optional')]
        remaining=sum(estimator.predict(t['estimated_minutes'],activity(t['task_type']))['predicted_minutes'] for t in tasks)
        deadline=DeadlineFeasibilityAnalyzer().analyze(remaining,g['deadline'],capacity,budget,len(complete),at)
        if not roadmap or roadmap['status']!='active':
            deadline['status']='insufficient_data';deadline['summary']='当前没有有效路线，先确认路线后再判断截止时间。'
        ended=[s for s in rows if s['status'] in {'completed','abandoned'}];completed=[s for s in ended if s['status']=='completed'];partial=[s for s in ended if s['completion_ratio']<1]
        friction=[];codes=[]
        bytask={}
        for s in ended:
            if s['growth_task_id']:bytask.setdefault(s['growth_task_id'],[]).append(s)
        if any(len(v)>=3 and all(s['status']=='abandoned' for s in v[-3:]) for v in bytask.values()):friction.append('repeated_abandonment');codes.append('REPEATED_ABANDONMENT')
        if any(len(v)>=3 and all(s['completion_ratio']<1 for s in v[-3:]) for v in bytask.values()):friction.append('repeated_carryover');codes.append('EXECUTION_CARRYOVER')
        if pauses>=POLICY['reality']['frequent_pause_count']:friction.append('frequent_pause')
        debug=PersonalPaceModel(self.store).profiles(user,True)
        if any(p['task_bucket']=='all' and p['reliability']!='low' and p['median_ratio']>1.4 for p in debug['profiles']):friction.append('large_duration_overrun');codes.append('TASK_DURATION_OVERRUN')
        if len(complete)>=2 and budget and capacity < budget*POLICY['reality']['below_plan_ratio']:codes.append('WEEKLY_CAPACITY_BELOW_PLAN')
        if deadline['status'] in {'at_risk','unlikely'}:codes.append('DEADLINE_AT_RISK' if deadline['status']=='at_risk' else 'DEADLINE_UNLIKELY')
        recommended=bool(codes)
        tasks_all=(roadmap or {}).get('tasks',[])
        return {'goal_id':gid,'weeks':weeks,'weekly_planned_minutes':budget,'weekly_actual_minutes':weeks[-1]['actual_minutes'],'completion_rate':sum(s['completion_ratio'] for s in ended)/len(ended) if ended else None,'session_completion_rate':len(completed)/len(ended) if ended else None,'task_carryover_rate':sum(v[-1]['completion_ratio']<1 for v in bytask.values())/len(bytask) if bytask else None,'session_partial_rate':len(partial)/len(ended) if ended else None,'growth_task_completion_rate':sum(t['status']=='completed' for t in tasks_all)/len(tasks_all) if tasks_all else None,'deadline':deadline,'execution_friction':friction,'reason_codes':codes+(['REPLAN_RECOMMENDED'] if recommended else []),'replan_recommended':recommended,'pace_summary':PersonalPaceModel(self.store).profiles(user)['summary'],'adjustment_options':['保留完整路线，调整截止日期','调整每周可用时间','审查辅助与可选能力，再使用现有成长路线重新规划'] if recommended else [],'boundary':'只描述主动记录的执行差异；不评价自律或学习效率，不改变目标、路线、知识缺口或掌握状态。'}
    def context(self,user,gid):
        report=self.analyze(user,gid)
        actual=report['deadline']['actual_capacity_minutes_per_week']
        return {'planned_weekly_minutes':report['weekly_planned_minutes'],'observed_weekly_capacity_range_minutes':[math.floor(actual/15)*15,math.ceil(actual/15)*15] if actual is not None else None,'deadline_risk':report['deadline']['status'],'boundary':'执行数据只用于时间与负载规划，不用于人格、自律或能力判断；不得据此判断掌握、生成能力缺口、删减必需能力或更改程序顺序。'}
