"""Read-only knowledge calibration; incremental matching, versioned cached statistics."""
import json,secrets
from pathlib import Path
from datetime import timedelta
from .policy import POLICY,clock,date,iso
from .final import fingerprint
from .final_assessment import criticality

CALIBRATION_POLICY=json.loads(Path(__file__).with_name('calibration_policy.json').read_text())
SCHEMA='''
CREATE INDEX IF NOT EXISTS prediction_calibration_scope ON learning_prediction_snapshots(user_id,course_id,created_at,policy_version,atom_id);
CREATE INDEX IF NOT EXISTS outcome_calibration_scope ON learning_prediction_outcomes(user_id,course_id,created_at,prediction_id);
CREATE INDEX IF NOT EXISTS evidence_calibration_event ON learning_evidence(course_id,event_key);
CREATE TABLE IF NOT EXISTS calibration_matches (
 user_id TEXT NOT NULL,course_id TEXT NOT NULL REFERENCES courses(id),prediction_id TEXT NOT NULL REFERENCES learning_prediction_snapshots(id),
 window_days INTEGER NOT NULL,scoring_source TEXT NOT NULL,outcome_id INTEGER NOT NULL REFERENCES learning_prediction_outcomes(id),
 distance REAL NOT NULL,sample_json TEXT NOT NULL,PRIMARY KEY(prediction_id,window_days,scoring_source)
);
CREATE TABLE IF NOT EXISTS calibration_snapshots (
 id TEXT PRIMARY KEY,user_id TEXT NOT NULL,scope_type TEXT NOT NULL,scope_id TEXT NOT NULL,policy_version TEXT NOT NULL,
 calibration_policy_version TEXT NOT NULL,result_json TEXT NOT NULL,source_cursor INTEGER NOT NULL,created_at TEXT NOT NULL,
 UNIQUE(user_id,scope_type,scope_id,policy_version,calibration_policy_version)
);
'''

def migrate(db):
    columns={r[1] for r in db.execute('PRAGMA table_info(learning_prediction_outcomes)')}
    for name,definition in {'outcome_type':"TEXT NOT NULL DEFAULT 'quiz'",'outcome_score':'REAL','delay_hours':'REAL','scoring_source':"TEXT NOT NULL DEFAULT 'independent_mcq'",'valid_for_calibration':'INTEGER NOT NULL DEFAULT 0','evidence_cursor':'INTEGER NOT NULL DEFAULT 0','atom_id':'TEXT','result_id':'TEXT'}.items():
        if name not in columns:db.execute(f'ALTER TABLE learning_prediction_outcomes ADD COLUMN {name} {definition}')
    db.executescript(SCHEMA)

def state_policy(prediction):
    # P1 stored report policy in its outer field; read the actual state policy.
    if prediction['policy_version'].startswith('weighted-evidence-'):return prediction['policy_version']
    payload=json.loads(prediction['state_json']);state=payload.get('mastery_state',payload)
    return state.get('state_policy_version',state.get('policy_version',prediction['policy_version']))

def capture_prediction(db,user,cid,atom,state,at=None,salt=''):
    at=at or clock();cursor=db.execute('SELECT COALESCE(MAX(rowid),0) FROM learning_evidence WHERE user_id=? AND course_id=?',(user,cid)).fetchone()[0]
    digest=fingerprint([atom,state['version'],cursor,iso(at),salt]);pid=secrets.token_urlsafe(16)
    db.execute('INSERT OR IGNORE INTO learning_prediction_snapshots VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(pid,user,cid,atom,'atom_assessment',state['mastery'],state['confidence'],json.dumps(state,ensure_ascii=False),state['policy_version'],iso(at),cursor,digest))
    return db.execute("SELECT id FROM learning_prediction_snapshots WHERE course_id=? AND prediction_type='atom_assessment' AND state_hash=?",(cid,digest)).fetchone()[0]

def agreement(predicted,observed):
    if predicted is None or observed is None:return {'classification':'insufficient_future_evidence','message':'尚无可比较的有效开放评估；课程掌握状态不变。'}
    gap=predicted-observed
    if predicted>.8 and observed<.5 or gap>=CALIBRATION_POLICY['authentic_disagreement_gap']:
        return {'classification':'high_state_low_authentic','reason_code':'AUTHENTIC_STATE_MISMATCH','action':'reassess','message':'检测到能力证据之间存在明显差异。建议主动进行一次新的独立应用或迁移检测；不会自动降低掌握状态。'}
    if predicted<.5 and observed>.8 or -gap>=CALIBRATION_POLICY['authentic_disagreement_gap']:
        return {'classification':'low_state_high_authentic','message':'本次开放回答比已有状态估计更好，可用新的独立题进一步验证；不会自动提高掌握状态。'}
    return {'classification':'well_aligned','message':'本次开放表现与已有掌握估计基本一致；单次模型评分不能验证整体状态策略。'}

def _predictions(db,user,cid,at):
    earliest=iso(date(at)-timedelta(days=max(CALIBRATION_POLICY['windows_days'])*(1+CALIBRATION_POLICY['window_tolerance_ratio'])))
    return db.execute('SELECT * FROM learning_prediction_snapshots WHERE user_id=? AND course_id=? AND created_at>=? AND created_at<?',(user,cid,earliest,at)).fetchall()

def _match(db,prediction,outcome):
    if not outcome['valid_for_calibration'] or prediction['predicted_mastery'] is None:return
    delay=(date(outcome['created_at'])-date(prediction['created_at'])).total_seconds()/86400
    if delay<=0 or outcome['evidence_cursor']<=prediction['evidence_cursor']:return
    if prediction['atom_id'] and prediction['atom_id']!=outcome['atom_id']:return
    for window in CALIBRATION_POLICY['windows_days']:
        distance=abs(delay-window)
        if distance>window*CALIBRATION_POLICY['window_tolerance_ratio']:continue
        # A single outcome contributes once per prediction/window/source, nearest wins.
        sample={'prediction_id':prediction['id'],'outcome_reference':outcome['quiz_id'],'course_id':prediction['course_id'],'atom_id':prediction['atom_id'],'policy_version':state_policy(prediction),'prediction':prediction['predicted_mastery'],'confidence':prediction['predicted_confidence'],'observed':outcome['outcome_score'],'delay_days':delay,'window_days':window,'scoring_source':outcome['scoring_source']}
        db.execute('''INSERT INTO calibration_matches VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(prediction_id,window_days,scoring_source) DO UPDATE SET outcome_id=excluded.outcome_id,distance=excluded.distance,sample_json=excluded.sample_json WHERE excluded.distance<calibration_matches.distance''',(prediction['user_id'],prediction['course_id'],prediction['id'],window,outcome['scoring_source'],outcome['id'],distance,json.dumps(sample)))

def _outcome(db,prediction,user,cid,reference,ids,score,total,at,kind,observed,source,cursor,atom,valid,result_id=None):
    delay=(date(at)-date(prediction['created_at'])).total_seconds()/3600
    if delay<=0 or cursor<=prediction['evidence_cursor']:return
    db.execute('''INSERT INTO learning_prediction_outcomes(user_id,course_id,prediction_id,quiz_id,evidence_ids_json,score,total,created_at,outcome_type,outcome_score,delay_hours,scoring_source,valid_for_calibration,evidence_cursor,atom_id,result_id)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(prediction_id,quiz_id) DO UPDATE SET outcome_type=excluded.outcome_type,outcome_score=excluded.outcome_score,delay_hours=excluded.delay_hours,scoring_source=excluded.scoring_source,valid_for_calibration=excluded.valid_for_calibration,evidence_cursor=excluded.evidence_cursor,atom_id=excluded.atom_id,result_id=excluded.result_id''',
        (user,cid,prediction['id'],reference,json.dumps(ids),score,total,at,kind,observed,delay,source,int(valid),cursor,atom,result_id))
    row=db.execute('SELECT * FROM learning_prediction_outcomes WHERE prediction_id=? AND quiz_id=?',(prediction['id'],reference)).fetchone();_match(db,prediction,row)

def link_authentic(db,user,cid,task,rid,score,evidence,at):
    cursor=db.execute('SELECT rowid FROM learning_evidence WHERE id=?',(evidence,)).fetchone()[0]
    for p in _predictions(db,user,cid,at):
        if p['atom_id'] and p['atom_id']!=task['atom_id']:continue
        # Legacy NOT NULL score/total remain counts only. Open score lives exclusively
        # in outcome_score; 0/0 is not a graded zero or a quiz and is never displayed.
        _outcome(db,p,user,cid,'authentic:'+task['id'],[evidence],0,0,at,'open_transfer' if task['task_type']=='open_transfer' else 'authentic',score,'llm_rubric',cursor,task['atom_id'],True,rid)

class CalibrationAnalyzer:
    def analyze(self,samples):
        # One observed trial must not inflate n by validating many predictions
        # in the same window. Different windows and atom units stay separate.
        distinct={};unlinked=[]
        for s in samples:
            if not s.get('outcome_reference'):unlinked.append(s);continue
            key=(s['outcome_reference'],s.get('atom_id'),s.get('window_days'),s.get('policy_version'),s.get('scoring_source'))
            distance=abs(s['delay_days']-s['window_days'])
            if key not in distinct or distance<abs(distinct[key]['delay_days']-distinct[key]['window_days']):distinct[key]=s
        samples=unlinked+list(distinct.values())
        n=len(samples);mass=sum(s.get('weight',1) for s in samples)
        def avg(key,rows):
            weight=sum(s.get('weight',1) for s in rows)
            return sum(s[key]*s.get('weight',1) for s in rows)/weight if weight else None
        buckets=[];confidence=[];ece=0
        for low,high in CALIBRATION_POLICY['mastery_buckets']:
            rows=[s for s in samples if low<=s['prediction']<high or high==1 and s['prediction']==1]
            w=sum(s.get('weight',1) for s in rows);p=avg('prediction',rows);observed=avg('observed',rows)
            if w:ece+=w/mass*abs(p-observed)
            buckets.append({'range':[low,high],'samples':len(rows),'predicted':p,'observed':observed,'sufficient':len(rows)>=CALIBRATION_POLICY['minimum_bucket_samples']})
            cs=[s for s in samples if low<=s['confidence']<high or high==1 and s['confidence']==1]
            errors=[dict(s,error=abs(s['prediction']-s['observed'])) for s in cs]
            confidence.append({'range':[low,high],'samples':len(cs),'mean_prediction_error':avg('error',errors),'sufficient':len(cs)>=CALIBRATION_POLICY['minimum_bucket_samples']})
        predicted=avg('prediction',samples);observed=avg('observed',samples)
        classification='insufficient_future_evidence'
        if n>=CALIBRATION_POLICY['minimum_calibration_samples']:
            gap=predicted-observed
            classification='state_overestimation' if gap>=CALIBRATION_POLICY['authentic_disagreement_gap'] else 'state_underestimation' if -gap>=CALIBRATION_POLICY['authentic_disagreement_gap'] else 'well_aligned'
        return {'samples':n,'predicted':predicted,'observed':observed,'brier_score':sum(s.get('weight',1)*(s['observed']*(1-s['prediction'])**2+(1-s['observed'])*s['prediction']**2) for s in samples)/mass if mass and all(s.get('scoring_source','independent_mcq')=='independent_mcq' for s in samples) else None,'score_mean_squared_error':sum(s.get('weight',1)*(s['prediction']-s['observed'])**2 for s in samples)/mass if mass else None,'calibration_error':ece if n else None,'classification':classification,'mastery_buckets':buckets,'confidence_buckets':confidence,'confidence_boundary':'confidence表示证据充分程度，不是答对概率；按信心分组比较掌握预测误差，不把confidence当mastery计算Brier。','overestimate_rate':sum(s['prediction']-s['observed']>=.3 for s in samples)/n if n else None,'underestimate_rate':sum(s['observed']-s['prediction']>=.3 for s in samples)/n if n else None}

class CalibrationService:
    def __init__(self,store):self.store=store
    def _increment(self,db,user,cid,cursor):
        rows=db.execute('SELECT rowid AS cursor,* FROM learning_evidence WHERE user_id=? AND course_id=? AND rowid>? ORDER BY rowid',(user,cid,cursor)).fetchall()
        seen=set()
        for r in rows:
            meta=json.loads(r['metadata_json'])
            if r['result'] not in {'correct','wrong'} or not meta.get('quiz_id'):continue
            key=(meta['quiz_id'],r['atom_id'])
            if key in seen:continue
            seen.add(key)
            answers=db.execute('SELECT rowid AS cursor,* FROM learning_evidence WHERE user_id=? AND course_id=? AND atom_id=? AND event_key LIKE ?',(user,cid,r['atom_id'],'quiz:'+meta['quiz_id']+':%')).fetchall()
            answers=[a for a in answers if a['result'] in {'correct','wrong'}]
            if not answers:continue
            previous=db.execute("SELECT created_at FROM learning_evidence WHERE user_id=? AND course_id=? AND atom_id=? AND result IN ('correct','wrong') AND rowid<? AND event_key NOT LIKE ? ORDER BY rowid DESC LIMIT 1",(user,cid,r['atom_id'],min(a['cursor'] for a in answers),'quiz:'+meta['quiz_id']+':%')).fetchone()
            immediate=bool(previous and (date(r['created_at'])-date(previous[0])).total_seconds()<CALIBRATION_POLICY['immediate_repeat_hours']*3600)
            valid=not immediate and all(not a['hint_used'] and not json.loads(a['metadata_json']).get('reused_question') and not json.loads(a['metadata_json']).get('legacy') and not json.loads(a['metadata_json']).get('immediate_repeat') for a in answers)
            score=sum(a['result']=='correct' for a in answers);total=len(answers);last=max(a['cursor'] for a in answers)
            quiz=db.execute('SELECT assessment_kind FROM quizzes WHERE id=?',(meta['quiz_id'],)).fetchone();kind=quiz[0] if quiz else 'quiz'
            typ='review' if kind in {'review','returning','final_retention'} else 'final' if kind.startswith('final_') else 'quiz'
            for p in _predictions(db,user,cid,r['created_at']):
                if p['atom_id'] and p['atom_id']!=r['atom_id']:continue
                # Atom-level outcomes must not overwrite an aggregate course trial
                # with the last atom's score. Course snapshots use the full quiz.
                selected=answers
                if not p['atom_id']:
                    selected=db.execute('SELECT rowid AS cursor,* FROM learning_evidence WHERE user_id=? AND course_id=? AND event_key LIKE ?',(user,cid,'quiz:'+meta['quiz_id']+':%')).fetchall()
                    # One question mapped to several atoms still counts once.
                    selected=list({a['event_key']:a for a in selected}.values())
                s=sum(a['result']=='correct' for a in selected);count=len(selected)
                allvalid=valid and all(not a['hint_used'] and not json.loads(a['metadata_json']).get('reused_question') for a in selected)
                _outcome(db,p,user,cid,meta['quiz_id'],[a['id'] for a in selected],s,count,r['created_at'],typ,s/count,'independent_mcq',last,p['atom_id'],allvalid)
        return max([cursor]+[r['cursor'] for r in rows])
    def course(self,user,cid,debug=False):
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE');course=self.store._manage_owned(db,user,cid)
            revision=(course['content_revision'],course['current_ordinal'])
            existing=db.execute("SELECT * FROM calibration_snapshots WHERE user_id=? AND scope_type='course' AND scope_id=? AND policy_version='all-separated' AND calibration_policy_version=?",(user,cid,CALIBRATION_POLICY['version'])).fetchone()
            cursor=existing['source_cursor'] if existing else 0
            newest=db.execute('SELECT COALESCE(MAX(rowid),0) FROM learning_evidence WHERE user_id=? AND course_id=?',(user,cid)).fetchone()[0]
            prediction_cursor=db.execute('SELECT COALESCE(MAX(rowid),0) FROM learning_prediction_snapshots WHERE user_id=? AND course_id=?',(user,cid)).fetchone()[0]
            if existing and newest==cursor and json.loads(existing['result_json']).get('prediction_cursor')==prediction_cursor and json.loads(existing['result_json']).get('course_revision')==list(revision):result=json.loads(existing['result_json'])
            else:
                cursor=self._increment(db,user,cid,cursor)
                graphrow=db.execute('SELECT graph_json FROM course_graphs WHERE course_id=?',(cid,)).fetchone();graph=json.loads(graphrow[0]) if graphrow else {'atoms':[],'edges':[]}
                sections=[dict(r) for r in db.execute('SELECT * FROM sections WHERE course_id=? ORDER BY ordinal',(cid,))]
                _,weights,_=criticality({'sections':sections,'current_ordinal':db.execute('SELECT current_ordinal FROM courses WHERE id=?',(cid,)).fetchone()[0]},graph)
                samples=[json.loads(r[0]) for r in db.execute('SELECT sample_json FROM calibration_matches WHERE user_id=? AND course_id=?',(user,cid))]
                versions={s['policy_version'] for s in samples}
                predictions=db.execute('SELECT * FROM learning_prediction_snapshots WHERE user_id=? AND course_id=?',(user,cid)).fetchall()
                versions.update(state_policy(p) for p in predictions)
                result={'calibration_policy':CALIBRATION_POLICY['version'],'versions':{},'prediction_count':len(predictions),'prediction_cursor':prediction_cursor,'source_cursor':cursor,'course_revision':list(revision),'course_id':cid,'boundary':'独立选择题结果与模型辅助开放评分分开统计。样本不足不判断策略偏差；校准不会自动调整掌握状态、权重或阈值。'}
                analyzer=CalibrationAnalyzer()
                for version in sorted(versions):
                    atomic_trials={(s.get('outcome_reference'),s['window_days'],s['scoring_source']) for s in samples if s['policy_version']==version and s['atom_id']}
                    scoped=[dict(s,weight=weights.get(s['atom_id'],1)) for s in samples if s['policy_version']==version and (s['atom_id'] or (s.get('outcome_reference'),s['window_days'],s['scoring_source']) not in atomic_trials)]
                    windows={str(w):{source:analyzer.analyze([s for s in scoped if s['window_days']==w and s['scoring_source']==source]) for source in ['independent_mcq','llm_rubric']} for w in CALIBRATION_POLICY['windows_days']}
                    atoms={atom:{str(w):{source:analyzer.analyze([s for s in scoped if s['atom_id']==atom and s['window_days']==w and s['scoring_source']==source]) for source in ['independent_mcq','llm_rubric']} for w in CALIBRATION_POLICY['windows_days']} for atom in {s['atom_id'] for s in scoped if s['atom_id']}}
                    result['versions'][version]={'windows':windows,'atoms':atoms}
                # Immediate shadow comparisons are not future-window calibration.
                latest=db.execute('''SELECT r.score,p.predicted_mastery,t.task_type FROM authentic_results r JOIN authentic_tasks t ON t.id=r.task_id LEFT JOIN learning_prediction_snapshots p ON p.id=t.prediction_id WHERE r.user_id=? AND r.course_id=? AND r.valid_for_calibration=1 ORDER BY r.rowid DESC LIMIT 20''',(user,cid)).fetchall()
                result['authentic_agreement']=[{'task_type':r['task_type'],**agreement(r['predicted_mastery'],r['score'])} for r in latest]
                db.execute('''INSERT INTO calibration_snapshots VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(user_id,scope_type,scope_id,policy_version,calibration_policy_version) DO UPDATE SET result_json=excluded.result_json,source_cursor=excluded.source_cursor,created_at=excluded.created_at''',(secrets.token_urlsafe(16),user,'course',cid,'all-separated',CALIBRATION_POLICY['version'],json.dumps(result),cursor,iso(clock())))
        if debug:return result
        return {'prediction_count':result['prediction_count'],'authentic_agreement':result.get('authentic_agreement',[]),'windows':{version:{w:{source:{k:v[k] for k in ['samples','classification']} for source,v in sources.items()} for w,sources in data['windows'].items()} for version,data in result['versions'].items()},'boundary':result['boundary']}
    def policy(self,user):
        with self.store.connect() as db:courses=[r[0] for r in db.execute('SELECT id FROM courses WHERE session_id=? AND deleted_at IS NULL',(user,))]
        summaries=[self.course(user,cid,True) for cid in courses]
        signature=fingerprint([(r['course_id'],r['source_cursor'],r['prediction_cursor'],r['course_revision']) for r in summaries])
        with self.store.connect() as db:
            cached=db.execute("SELECT result_json FROM calibration_snapshots WHERE user_id=? AND scope_type='policy' AND scope_id='owned' AND policy_version='all-separated' AND calibration_policy_version=?",(user,CALIBRATION_POLICY['version'])).fetchone()
            if cached and json.loads(cached[0]).get('source_signature')==signature:return json.loads(cached[0])
            samples=[json.loads(r[0]) for r in db.execute('SELECT m.sample_json FROM calibration_matches m JOIN courses c ON c.id=m.course_id WHERE m.user_id=? AND c.session_id=? AND c.deleted_at IS NULL',(user,user))]
            analyzer=CalibrationAnalyzer();versions={s['policy_version'] for s in samples}
            result={'source_signature':signature,'courses':summaries,'policies':{v:{str(w):{source:analyzer.analyze([s for s in samples if s['policy_version']==v and s['window_days']==w and s['scoring_source']==source]) for source in ['independent_mcq','llm_rubric']} for w in CALIBRATION_POLICY['windows_days']} for v in versions},'boundary':'仅汇总当前用户的策略统计，不合并课程知识或继承掌握状态。'}
            db.execute("INSERT INTO calibration_snapshots VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(user_id,scope_type,scope_id,policy_version,calibration_policy_version) DO UPDATE SET result_json=excluded.result_json,source_cursor=excluded.source_cursor,created_at=excluded.created_at",(secrets.token_urlsafe(16),user,'policy','owned','all-separated',CALIBRATION_POLICY['version'],json.dumps(result),sum(r['source_cursor'] for r in summaries),iso(clock())))
        return result
