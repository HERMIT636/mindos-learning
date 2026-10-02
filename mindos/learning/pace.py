"""Bounded rolling timing statistics; independent of the learner knowledge model."""
import json, math, statistics
from .execution import POLICY, ACTIVITIES, ACTIVITY_NAMES, bucket
from .policy import clock, iso

class PersonalPaceModel:
    def __init__(self,store):self.store=store
    @staticmethod
    def eligible(s):
        if s['status']!='completed':return 'abandoned_or_unfinished'
        if s['was_interrupted']:return 'interrupted'
        if s['invalid_for_pace']:return 'user_marked_invalid'
        if s['completion_ratio']!=1:return 'partial_execution'
        if s['planned_minutes']<=0:return 'no_plan'
        if not 0<s['active_seconds']<=POLICY['session']['max_reasonable_session_minutes']*60:return 'unreasonable_duration'
        ratio=s['active_seconds']/60/s['planned_minutes']
        if not POLICY['pace']['outlier_ratio_min']<=ratio<=POLICY['pace']['outlier_ratio_max']:return 'outlier'
        return None
    def profiles(self,user,debug=False):
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            cursor=db.execute("SELECT COALESCE(MAX(id),0) FROM task_execution_events WHERE user_id=? AND event_type IN ('completed','abandoned','adjusted','deleted')",(user,)).fetchone()[0]
            cached=db.execute('SELECT * FROM pace_snapshots WHERE user_id=?',(user,)).fetchone()
            if cached and cached['source_cursor']==cursor and cached['policy_version']==POLICY['version']:result=json.loads(cached['profile_json'])
            else:
                profiles=[];excluded={}
                for kind in sorted(ACTIVITIES):
                    rows=[dict(r) for r in db.execute("SELECT * FROM study_sessions WHERE user_id=? AND activity_type=? AND status IN ('completed','abandoned') ORDER BY updated_at DESC,rowid DESC LIMIT ?",(user,kind,POLICY['pace']['rolling_samples']))]
                    groups={'all':[],'short':[],'medium':[],'long':[]}
                    for s in rows:
                        reason=self.eligible(s)
                        if reason:excluded[reason]=excluded.get(reason,0)+1;continue
                        ratio=s['active_seconds']/60/s['planned_minutes'];groups['all'].append(ratio);groups[bucket(s['base_minutes'])].append(ratio)
                    for b,ratios in groups.items():
                        ordered=sorted(ratios);n=len(ordered);trim=math.floor(n*.1);trimmed=ordered[trim:n-trim] if trim else ordered
                        profiles.append({'activity_type':kind,'task_bucket':b,'sample_count':n,'median_ratio':statistics.median(ordered) if n else 1,'trimmed_mean_ratio':statistics.mean(trimmed) if n else 1,'p75_ratio':ordered[max(0,math.ceil(n*.75)-1)] if n else 1,'reliability':'high' if n>=POLICY['pace']['minimum_samples_high'] else 'medium' if n>=POLICY['pace']['minimum_samples_medium'] else 'low'})
                result={'profiles':profiles,'excluded':excluded,'source_cursor':cursor,'policy_version':POLICY['version']}
                if cursor:db.execute('INSERT OR REPLACE INTO pace_snapshots VALUES(?,?,?,?,?)',(user,json.dumps(result),cursor,POLICY['version'],iso(clock())))
        if debug:return result
        summaries=[]
        for p in result['profiles']:
            if p['task_bucket']!='all':continue
            if p['reliability']=='low':text='完整记录还不够，暂用初始规则估时。'
            else:
                percent=round((p['median_ratio']-1)*100)
                text='最近类似任务用时接近初始估计。' if abs(percent)<5 else f'最近类似任务通常比初始估计{"多" if percent>0 else "少"}约 {abs(percent)}% 时间。'
            summaries.append({'activity_type':p['activity_type'],'label':ACTIVITY_NAMES[p['activity_type']],'summary':text,'confidence':p['reliability']})
        return {'summary':summaries,'boundary':'耗时来自主动记录和手动修正，不评价知识能力、专注程度、人格或生产力。'}

class DurationEstimator:
    def __init__(self,store,user):self.profiles=PersonalPaceModel(store).profiles(user,True)['profiles']
    def predict(self,base,kind):
        specific=next((p for p in self.profiles if p['activity_type']==kind and p['task_bucket']==bucket(base)),None)
        general=next((p for p in self.profiles if p['activity_type']==kind and p['task_bucket']=='all'),None)
        p=specific if specific and specific['reliability']!='low' else general
        enough=p and p['reliability']!='low';ratio=p['median_ratio'] if enough else 1
        ratio=max(POLICY['pace']['minimum_multiplier'],min(POLICY['pace']['maximum_multiplier'],ratio))
        return {'base_minutes':base,'base_estimated_minutes':base,'predicted_minutes':math.ceil(base*ratio),'personalized_minutes':math.ceil(base*ratio),'personalized_estimated_minutes':math.ceil(base*ratio),'pace_confidence':p['reliability'] if p else 'low','pace_reason':'PACE_PERSONALIZED' if enough else 'PACE_LOW_SAMPLE','estimate_source':'根据你过去类似任务调整' if enough else '完整记录不足，暂用初始规则估时'}
