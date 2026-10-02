"""P1 orchestration over P0 evidence, quizzes, repair and model gateway."""
import json,secrets,hashlib
from .policy import POLICY,clock,date,iso
from .state import empty,ForgettingService
from .evidence import event
from .final_assessment import FINAL_POLICY,FINAL_KINDS,FinalAssessmentPlanner,TransferAssessmentGenerator,QUESTION_SCHEMA
from .course_mastery import CourseMasteryAnalyzer
from .final_remediation import FinalRemediationPlanner

SCHEMA='''
CREATE TABLE IF NOT EXISTS course_final_completion (
 user_id TEXT NOT NULL,course_id TEXT NOT NULL REFERENCES courses(id),content_revision INTEGER NOT NULL,completed_at TEXT NOT NULL,
 PRIMARY KEY(user_id,course_id)
);
CREATE TABLE IF NOT EXISTS final_assessment_plans (
 id TEXT PRIMARY KEY,user_id TEXT NOT NULL,course_id TEXT NOT NULL REFERENCES courses(id),version INTEGER NOT NULL,
 status TEXT NOT NULL,content_revision INTEGER NOT NULL,scope_hash TEXT NOT NULL,plan_json TEXT NOT NULL,
 created_at TEXT NOT NULL,completed_at TEXT,UNIQUE(course_id,version)
);
CREATE INDEX IF NOT EXISTS final_history_scope ON final_assessment_plans(user_id,course_id,scope_hash,status,version);
CREATE INDEX IF NOT EXISTS quiz_final_scope ON quizzes(course_id,scope,loop_session_id,target_atom_id,assessment_kind);
CREATE UNIQUE INDEX IF NOT EXISTS one_active_final ON final_assessment_plans(user_id,course_id) WHERE status='active';
CREATE TABLE IF NOT EXISTS course_mastery_states (
 user_id TEXT NOT NULL,course_id TEXT NOT NULL REFERENCES courses(id),state_json TEXT NOT NULL DEFAULT '{}',
 disposition TEXT NOT NULL DEFAULT '',updated_at TEXT NOT NULL,PRIMARY KEY(user_id,course_id)
);
CREATE TABLE IF NOT EXISTS course_mastery_reports (
 id TEXT PRIMARY KEY,user_id TEXT NOT NULL,course_id TEXT NOT NULL REFERENCES courses(id),version INTEGER NOT NULL,
 state_hash TEXT NOT NULL,result_json TEXT NOT NULL,summary_json TEXT NOT NULL DEFAULT '{}',created_at TEXT NOT NULL,policy_version TEXT NOT NULL,
 UNIQUE(course_id,version),UNIQUE(course_id,state_hash)
);
CREATE TABLE IF NOT EXISTS course_repair_plans (
 id TEXT PRIMARY KEY,user_id TEXT NOT NULL,course_id TEXT NOT NULL REFERENCES courses(id),report_id TEXT,
 status TEXT NOT NULL,targets_json TEXT NOT NULL,created_at TEXT NOT NULL,completed_at TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS one_active_course_repair ON course_repair_plans(user_id,course_id) WHERE status IN ('active','needs_verification');
CREATE TABLE IF NOT EXISTS learning_prediction_snapshots (
 id TEXT PRIMARY KEY,user_id TEXT NOT NULL,course_id TEXT NOT NULL REFERENCES courses(id),atom_id TEXT,
 prediction_type TEXT NOT NULL,predicted_mastery REAL,predicted_confidence REAL NOT NULL,state_json TEXT NOT NULL,
 policy_version TEXT NOT NULL,created_at TEXT NOT NULL,evidence_cursor INTEGER NOT NULL,state_hash TEXT NOT NULL,
 UNIQUE(course_id,prediction_type,state_hash)
);
CREATE TABLE IF NOT EXISTS learning_prediction_outcomes (
 id INTEGER PRIMARY KEY,user_id TEXT NOT NULL,course_id TEXT NOT NULL REFERENCES courses(id),
 prediction_id TEXT NOT NULL REFERENCES learning_prediction_snapshots(id),quiz_id TEXT NOT NULL,
 evidence_ids_json TEXT NOT NULL,score INTEGER NOT NULL,total INTEGER NOT NULL,created_at TEXT NOT NULL,
 UNIQUE(prediction_id,quiz_id)
);
'''

def migrate(db):db.executescript(SCHEMA)
def fingerprint(value):return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def validate_explanation(text):
    """Reject new score/certification claims, allow explicit uncertainty statements."""
    import re
    if re.search(r'\d|百分之',text):raise ValueError('报告说明不得新增数字或分数')
    for clause in re.split(r'[，。；！？\n]',text):
        for claim in re.finditer(r'认证|全部掌握|全面掌握|没有任何缺口',clause):
            prefix=clause[:claim.start()]
            # Negation applies only within this clause, before any contrast.
            tail=re.split(r'但是|但|然而|却',prefix)[-1]
            if not re.search(r'不能|不应|不宜|不可|不代表|不是|并非|不等于|无法|尚未|未达到|还没有|不属于|并没有',tail):
                raise ValueError('报告说明不能声称全面掌握、认证或没有缺口')

def load_plan(row):
    if not row:return None
    r=dict(row);r.update(json.loads(r.pop('plan_json')));return r

def validate_submission(db,user,cid,row):
    plan=load_plan(db.execute('SELECT * FROM final_assessment_plans WHERE id=? AND user_id=? AND course_id=?',(row['loop_session_id'],user,cid)).fetchone())
    context=FinalAssessmentService(None)._context(user,cid,db)
    if not plan or plan['status']!='active' or plan['scope_hash']!=context['scope_hash']:raise ValueError('终局检测已暂缓或课程结构有变化，请刷新')
    item=next((q for q in plan['blueprint'] if q['status'] in {'pending','generated'}),None)
    if not item or item.get('quiz_id')!=row['id']:raise ValueError('这道题已完成或不是当前检测题，请刷新')

class FinalAssessmentService:
    def __init__(self,store):self.store=store

    def _context(self,user,cid,db=None,at=None):
        if db is None:
            with self.store.connect() as connection:return self._context(user,cid,connection,at)
        at=at or clock();row=db.execute('SELECT * FROM courses WHERE id=? AND session_id=? AND deleted_at IS NULL',(cid,user)).fetchone()
        if not row:raise ValueError('课程不存在')
        course=dict(row);course['sections']=[dict(s) for s in db.execute('SELECT * FROM sections WHERE course_id=? ORDER BY ordinal',(cid,))]
        graphrow=db.execute('SELECT graph_json FROM course_graphs WHERE course_id=?',(cid,)).fetchone();graph=json.loads(graphrow[0]) if graphrow else {'atoms':[],'edges':[]}
        valid=[a for a in graph['atoms'] if a['section']<=course['current_ordinal'] and a.get('quality_status')!='deprecated']
        raw={r['atom_id']:json.loads(r['state_json']) for r in db.execute('SELECT atom_id,state_json FROM knowledge_states WHERE user_id=? AND course_id=?',(user,cid))}
        states={a['id']:ForgettingService().project(raw.get(a['id'],empty(a['id'])),at) for a in valid}
        mis=[dict(r) for r in db.execute("SELECT * FROM learning_misconceptions WHERE user_id=? AND course_id=? AND status!='resolved'",(user,cid))]
        count=len(course['sections']);done={s['ordinal'] for s in course['sections'] if s['ordinal']<course['current_ordinal']}
        submitted={r[0] for r in db.execute("SELECT section_id FROM quizzes WHERE course_id=? AND scope='section' AND submitted_at IS NOT NULL",(cid,))};read={r[0] for r in db.execute("SELECT atom_id FROM learning_events WHERE course_id=? AND kind IN ('read','review')",(cid,))}
        for s in course['sections']:
            ids={a['id'] for a in valid if a['section']==s['ordinal']}
            if s['id'] in submitted or ids and ids<=read:done.add(s['ordinal'])
        completion=db.execute('SELECT * FROM course_final_completion WHERE user_id=? AND course_id=?',(user,cid)).fetchone()
        if completion and completion['content_revision']==course['content_revision']:done.update(s['ordinal'] for s in course['sections'])
        eligible=bool(count and len(done)==count and course['current_ordinal']==count and all(s['lesson'] for s in course['sections']))
        masteryrow=db.execute('SELECT disposition FROM course_mastery_states WHERE user_id=? AND course_id=?',(user,cid)).fetchone();course['final_disposition']=masteryrow[0] if masteryrow else ''
        scope_hash=fingerprint({'revision':course['content_revision'],'graph':graph,'sections':[{k:s[k] for k in ['id','title','objective','core_atoms']} for s in course['sections']]})
        plan=load_plan(db.execute('SELECT * FROM final_assessment_plans WHERE user_id=? AND course_id=? ORDER BY version DESC LIMIT 1',(user,cid)).fetchone())
        if plan:plan['stale']=plan['scope_hash']!=scope_hash
        results=self._results(db,cid,plan['id']) if plan else []
        # Fetch the latest independent final trial per atom/dimension in one
        # indexed query. Older plans remain immutable and are not replayed here.
        final_rows=db.execute("""SELECT * FROM (
            SELECT q.*,ROW_NUMBER() OVER (PARTITION BY q.target_atom_id,q.assessment_kind ORDER BY q.rowid DESC) AS latest_trial
            FROM quizzes q JOIN final_assessment_plans p ON p.id=q.loop_session_id
            WHERE p.user_id=? AND p.course_id=? AND p.scope_hash=? AND p.status='completed'
            AND q.course_id=p.course_id AND q.scope='final' AND q.submitted_at IS NOT NULL
            AND COALESCE(json_extract(q.hint_flags_json,'$[0]'),0)=0
            AND COALESCE(json_extract(q.questions_json,'$[0].reused_question'),0)=0
        ) WHERE latest_trial=1""",(user,cid,scope_hash)).fetchall()
        valid_final_results=self._results_from_rows(final_rows)
        state_hash=fingerprint({'scope':scope_hash,'course_title':course['title'],'versions':{a:s['version'] for a,s in states.items()},'mis':[(m['id'],m['status'],m['evidence_count']) for m in mis],'day':at.date().isoformat(),'review_due':[a for a,s in states.items() if s['state']=='review_due' or s['forgetting_risk'] is not None and s['forgetting_risk']>=POLICY['forgetting_risk_threshold']],'plan':(plan['id'],plan['status']) if plan else None,'disposition':course['final_disposition'],'eligible':eligible})
        return {'course':course,'graph':graph,'states':states,'misconceptions':mis,'completion':{'eligible':eligible,'ratio':len(done)/count if count else 0.,'completed_sections':len(done),'total_sections':count},'plan':plan,'results':results,'valid_final_results':valid_final_results,'scope_hash':scope_hash,'state_hash':state_hash,'at':at}

    def _results(self,db,cid,pid):
        return self._results_from_rows(db.execute("SELECT * FROM quizzes WHERE course_id=? AND loop_session_id=? AND scope='final' AND submitted_at IS NOT NULL ORDER BY rowid",(cid,pid)))

    @staticmethod
    def _results_from_rows(rows):
        result=[]
        for row in rows:
            qs,answers,given=json.loads(row['questions_json']),json.loads(row['answers_json']),json.loads(row['user_answers_json']);hints=json.loads(row['hint_flags_json']) or [False]*len(qs)
            for i,(q,a,g) in enumerate(zip(qs,answers,given)):result.append({'quiz_id':row['id'],'atom_ids':q['atom_ids'],'kind':row['assessment_kind'],'correct':g==a['answer'],'hint_used':hints[i],'reused_question':q.get('reused_question',False)})
        return result

    def _analyze(self,c):return CourseMasteryAnalyzer().analyze(c['course'],c['graph'],c['states'],c['misconceptions'],c['completion'],c['plan'],c['valid_final_results'])

    def status(self,user,cid):
        c=self._context(user,cid);plan=c['plan'];result=self._analyze(c)
        with self.store.connect() as db:
            report=db.execute('SELECT id,version,state_hash FROM course_mastery_reports WHERE user_id=? AND course_id=? ORDER BY version DESC LIMIT 1',(user,cid)).fetchone()
            repair=self._repair_row(db,user,cid)
            quiz=None
            if plan and not plan['stale']:
                item=next((i for i in plan['blueprint'] if i['status'] in {'pending','generated'}),None)
                if item and item.get('quiz_id'):
                    row=db.execute('SELECT * FROM quizzes WHERE id=? AND course_id=?',(item['quiz_id'],cid)).fetchone()
                    if row:quiz=self.store._quiz_public(dict(row))|{'item':item,'plan_id':plan['id']}
        public_plan={k:v for k,v in plan.items() if k not in {'user_id','scope_hash'}} if plan else None
        return {'completion':c['completion'],'eligible_for_final':c['completion']['eligible'],'knowledge_index_available':bool(c['states']),'plan':public_plan,'current_quiz':quiz,'mastery_state':result,'repair_plan':repair,
          'latest_report':{'id':report['id'],'version':report['version'],'is_stale':report['state_hash']!=c['state_hash']} if report else None,'policy_version':FINAL_POLICY['version']}

    def complete_content(self,user,cid):
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE');c=self._context(user,cid,db);course=c['course']
            if course['current_ordinal']!=len(course['sections']) or not all(s['lesson'] for s in course['sections']):raise ValueError('请先逐节学习并生成最后一节讲解，再确认内容已学完')
            db.execute('INSERT INTO course_final_completion VALUES(?,?,?,?) ON CONFLICT(user_id,course_id) DO UPDATE SET content_revision=excluded.content_revision,completed_at=excluded.completed_at',(user,cid,course['content_revision'],iso(clock())))
            event(db,user,cid,'content_completed',{'revision':course['content_revision'],'affects_mastery':False})
        return self.status(user,cid)

    def start(self,user,cid,reassessment=False):
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE');c=self._context(user,cid,db)
            if not c['completion']['eligible']:raise ValueError('课程内容尚未全部完成；最后一节可明确确认内容已学完')
            plan=c['plan']
            if plan and plan['status']=='active' and not plan['stale']:return self.status(user,cid)
            if plan and plan['status']=='active':db.execute("UPDATE final_assessment_plans SET status='outdated' WHERE id=?",(plan['id'],))
            if db.execute("SELECT 1 FROM repair_sessions WHERE user_id=? AND course_id=? AND status IN ('diagnostic','teaching','checking') UNION ALL SELECT 1 FROM returning_sessions WHERE user_id=? AND course_id=? AND status='pending'",(user,cid,user,cid)).fetchone():raise ValueError('请先完成或明确暂缓当前补强／回忆检测')
            repair=self._repair_row(db,user,cid);targets=None
            if reassessment:
                if not repair or repair['status']!='needs_verification':raise ValueError('请先完成当前补强目标，再重新检测')
                targets=repair['targets']
            prepared=FinalAssessmentPlanner().plan(c['course'],c['graph'],c['states'],c['misconceptions'],c['at'],targets)
            if not prepared['available']:return prepared
            version=db.execute('SELECT COALESCE(MAX(version),0)+1 FROM final_assessment_plans WHERE course_id=?',(cid,)).fetchone()[0];pid=secrets.token_urlsafe(16)
            if repair:prepared['repair_plan_id']=repair['id']
            db.execute('INSERT INTO final_assessment_plans VALUES(?,?,?,?,?,?,?,?,?,?)',(pid,user,cid,version,'active',c['course']['content_revision'],c['scope_hash'],json.dumps(prepared,ensure_ascii=False),iso(clock()),None))
            db.execute("INSERT INTO course_mastery_states VALUES(?,?,'{}','',?) ON CONFLICT(user_id,course_id) DO UPDATE SET disposition=''",(user,cid,iso(clock())))
            baseline=self._context(user,cid,db);estimate=self._analyze(baseline)
            cursor=db.execute('SELECT COALESCE(MAX(rowid),0) FROM learning_evidence WHERE course_id=?',(cid,)).fetchone()[0]
            db.execute('INSERT OR IGNORE INTO learning_prediction_snapshots VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(secrets.token_urlsafe(16),user,cid,None,'final_start',estimate['mastery_score'],estimate['mastery_confidence'],json.dumps({'mastery_state':estimate,'content_revision':c['course']['content_revision'],'scope_hash':c['scope_hash']},ensure_ascii=False),FINAL_POLICY['version'],iso(clock()),cursor,baseline['state_hash']))
            event(db,user,cid,'final_started',{'plan_id':pid,'version':version,'reassessment':reassessment})
        return self.status(user,cid)

    def _save_plan(self,db,plan):
        data={k:v for k,v in plan.items() if k not in {'id','user_id','course_id','version','status','content_revision','scope_hash','created_at','completed_at','stale'}}
        db.execute('UPDATE final_assessment_plans SET plan_json=?,status=?,completed_at=? WHERE id=?',(json.dumps(data,ensure_ascii=False),plan['status'],plan.get('completed_at'),plan['id']))

    def assessment(self,user,cid,model=None):
        c=self._context(user,cid);plan=c['plan']
        if not plan or plan['status']!='active' or plan['stale']:raise ValueError('请先开始当前课程的掌握检测')
        item=next((i for i in plan['blueprint'] if i['status'] in {'pending','generated'}),None)
        if not item:return self.status(user,cid)
        if item.get('quiz_id'):return self.status(user,cid)
        atom=next(a for a in c['graph']['atoms'] if a['id']==item['atom_id']);section=c['course']['sections'][atom['section']-1]
        with self.store.connect() as db:
            historical=[dict(r) for r in db.execute('SELECT * FROM quizzes WHERE course_id=? ORDER BY rowid DESC LIMIT ?',(cid,FINAL_POLICY['history_question_limit']))]
        previous=[]
        for r in historical:
            for q in json.loads(r['questions_json']):previous.append(q.get('scenario','')+' '+q['prompt'])
        for s in c['course']['sections']:
            if s['lesson']:previous.extend(s['lesson'].split('\n\n'))
        questions=answers=None;fallback=False
        try:
            if not model:raise ValueError('未配置模型')
            if item['dimension']=='transfer':questions,answers=TransferAssessmentGenerator().generate(model,c['course'],atom,previous)
            else:questions,answers=self._question(model,c['course'],section,atom,item,previous)
        except Exception as exc:
            if model and hasattr(model,'_diagnostic'):model._diagnostic({'stage':'final_generation_fallback','kind':item['kind'],'failure':str(exc)})
            if item['dimension']!='transfer':
                for row in historical:
                    if not row['submitted_at']:continue
                    for q,a in zip(json.loads(row['questions_json']),json.loads(row['answers_json'])):
                        if q.get('atom_ids')==[atom['id']] and q.get('assessment_type')==('concept' if item['dimension']=='retention' else item['dimension']) and set(q.get('choices',{}))==set('abcd'):
                            questions=[{**q,'reused_question':True}];answers=[a];fallback=True;break
                    if questions:break
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE');fresh=self._context(user,cid,db);active=fresh['plan']
            if not active or active['id']!=plan['id'] or active['status']!='active' or active['stale']:raise ValueError('检测任务或课程结构已变化，请刷新')
            current=next((q for q in active['blueprint'] if q['status'] in {'pending','generated'}),None)
            if not current or current['id']!=item['id'] or current.get('quiz_id'):return self.status(user,cid)
            if questions:
                qid=secrets.token_urlsafe(16)
                db.execute('INSERT INTO quizzes(id,course_id,section_id,questions_json,answers_json,created_at,scope,target_atom_id,assessment_kind,loop_session_id) VALUES(?,?,?,?,?,?,?,?,?,?)',(qid,cid,section['id'],json.dumps(questions,ensure_ascii=False),json.dumps(answers,ensure_ascii=False),iso(clock()),'final',atom['id'],item['kind'],plan['id']))
                current.update(status='generated',quiz_id=qid,fallback=fallback)
            else:
                current.update(status='unavailable',note='当前无法完成迁移能力检测，保留未测。' if item['dimension']=='transfer' else '暂时没有可用题源，可以稍后重新检测；不按答错处理。')
            self._save_plan(db,active)
            if not questions:self._advance(db,user,cid)
        result=self.status(user,cid)
        if not questions:result.update(available=False,note=current['note'])
        return result

    def _question(self,model,course,section,atom,item,previous):
        from jsonschema import Draft202012Validator
        failure=''
        for attempt in range(2):
            try:
                raw=model.final_question(course,section,atom,item['dimension'],previous,failure);Draft202012Validator(QUESTION_SCHEMA).validate(raw)
                questions,answers=model._validated_questions(raw,[],{atom['id']},required=True,count=1)
                expected='concept' if item['dimension']=='retention' else item['dimension']
                if questions[0]['assessment_type']!=expected or questions[0]['atom_ids']!=[atom['id']]:raise ValueError('检测题能力或知识归属与规划不一致')
                if any(questions[0]['prompt'].strip()==p.strip() for p in previous):raise ValueError('新题与已有题目重复')
                return questions,answers
            except Exception as exc:
                failure=str(exc)
                if hasattr(model,'_diagnostic'):model._diagnostic({'stage':'final_question_validation','attempt':attempt+1,'failure':failure})
        raise ValueError('题目修订后仍不可用')

    def on_submit(self,db,user,cid,row):
        # Link only previous predictions before saving this result's prediction.
        evidence=[r[0] for r in db.execute('SELECT id FROM learning_evidence WHERE course_id=? AND event_key LIKE ?',(cid,'quiz:'+row['id']+':%'))]
        result_cursor=db.execute('SELECT MAX(rowid) FROM learning_evidence WHERE course_id=? AND event_key LIKE ?',(cid,'quiz:'+row['id']+':%')).fetchone()[0]
        for prediction in db.execute('SELECT id,evidence_cursor FROM learning_prediction_snapshots WHERE user_id=? AND course_id=? ORDER BY created_at DESC,rowid DESC LIMIT 5',(user,cid)).fetchall():
            if result_cursor is None or prediction['evidence_cursor']>=result_cursor:continue
            db.execute('INSERT OR IGNORE INTO learning_prediction_outcomes(user_id,course_id,prediction_id,quiz_id,evidence_ids_json,score,total,created_at) VALUES(?,?,?,?,?,?,?,?)',(user,cid,prediction[0],row['id'],json.dumps(evidence),row['score'],len(json.loads(row['answers_json'])),row['submitted_at']))
        if row['assessment_kind'].startswith('final_'):
            plan=load_plan(db.execute('SELECT * FROM final_assessment_plans WHERE id=?',(row['loop_session_id'],)).fetchone())
            item=next(i for i in plan['blueprint'] if i.get('quiz_id')==row['id']);item['status']='completed';self._save_plan(db,plan);self._advance(db,user,cid)
        else:
            repair=self._repair_row(db,user,cid)
            if repair and row['loop_session_id']:
                for target in repair['targets']:
                    if target.get('repair_session_id')==row['loop_session_id']:
                        r=db.execute('SELECT status FROM repair_sessions WHERE id=?',(row['loop_session_id'],)).fetchone()
                        if r and r[0]=='completed':target['status']='completed'
                status='needs_verification' if all(t['status']=='completed' for t in repair['targets']) else 'active'
                db.execute('UPDATE course_repair_plans SET status=?,targets_json=? WHERE id=?',(status,json.dumps(repair['targets']),repair['id']))
            if db.execute('SELECT 1 FROM course_mastery_reports WHERE user_id=? AND course_id=?',(user,cid)).fetchone():self._save_report(db,user,cid)

    def _advance(self,db,user,cid):
        c=self._context(user,cid,db);plan=c['plan']
        if any(i['status'] in {'pending','generated'} for i in plan['blueprint']):return
        if FINAL_POLICY['max_stages']>=2 and not any(i['stage']==2 for i in plan['blueprint']) and c['results'] and len(plan['blueprint'])<FINAL_POLICY['max_questions']:
            candidates=[r for r in c['results'] if not r['correct'] and not r['hint_used']]
            if not candidates:
                candidates=[r for r in c['results'] if c['states'][r['atom_ids'][0]]['confidence']<FINAL_POLICY['confidence_threshold']]
            added=[]
            for r in candidates:
                dimension=next(k for k,v in FINAL_KINDS.items() if v==r['kind'])
                if dimension=='retention':continue
                if any(i['atom_id']==r['atom_ids'][0] and i['dimension']==dimension for i in added):continue
                if dimension=='transfer' and sum(i['dimension']=='transfer' for i in plan['blueprint']+added)>=FINAL_POLICY['max_transfer_questions']:continue
                added.append({'id':'verify-'+str(len(added)+1),'atom_id':r['atom_ids'][0],'dimension':dimension,'kind':r['kind'],'stage':2,'status':'pending','reason':'TARGETED_VERIFICATION：当前结果边界不确定，用新题复核'})
                if len(added)>=FINAL_POLICY['targeted_questions'] or len(plan['blueprint'])+len(added)>=FINAL_POLICY['max_questions']:break
            if added:
                plan['blueprint']+=added;plan['estimated_minutes']=len(plan['blueprint'])*FINAL_POLICY['estimated_minutes_per_question'];self._save_plan(db,plan);return
        plan['status']='completed';plan['completed_at']=iso(clock());self._save_plan(db,plan)
        if plan.get('repair_plan_id'):db.execute("UPDATE course_repair_plans SET status='completed',completed_at=? WHERE id=? AND status='needs_verification'",(plan['completed_at'],plan['repair_plan_id']))
        self._save_report(db,user,cid);event(db,user,cid,'final_completed',{'plan_id':plan['id']})

    def _save_report(self,db,user,cid):
        c=self._context(user,cid,db);result=self._analyze(c);time=iso(clock())
        db.execute("INSERT INTO course_mastery_states VALUES(?,?,?,'',?) ON CONFLICT(user_id,course_id) DO UPDATE SET state_json=excluded.state_json,updated_at=excluded.updated_at",(user,cid,json.dumps(result,ensure_ascii=False),time))
        old=db.execute('SELECT id FROM course_mastery_reports WHERE user_id=? AND course_id=? AND state_hash=?',(user,cid,c['state_hash'])).fetchone()
        if old:return old[0]
        rid=secrets.token_urlsafe(16);version=db.execute('SELECT COALESCE(MAX(version),0)+1 FROM course_mastery_reports WHERE course_id=?',(cid,)).fetchone()[0]
        snapshot={'course_title':c['course']['title'],'mastery_state':result,'recommendations':CourseMasteryAnalyzer().recommendations(result),'source_state_versions':{a:s['version'] for a,s in c['states'].items()},'assessment_plan_id':c['plan']['id'] if c['plan'] else None,'content_revision':c['course']['content_revision'],'scope_hash':c['scope_hash'],'assessment_version':c['plan']['version'] if c['plan'] else None,'last_assessed_at':c['plan']['completed_at'] if c['plan'] else None,'evidence_rule':'同一课程结构的已完成终局检测可用于定点复测；每个知识点与维度保留最新独立结果。'}
        db.execute('INSERT INTO course_mastery_reports VALUES(?,?,?,?,?,?,?,?,?)',(rid,user,cid,version,c['state_hash'],json.dumps(snapshot,ensure_ascii=False),'{}',time,FINAL_POLICY['version']))
        cursor=db.execute('SELECT COALESCE(MAX(rowid),0) FROM learning_evidence WHERE course_id=?',(cid,)).fetchone()[0]
        db.execute('INSERT OR IGNORE INTO learning_prediction_snapshots VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(secrets.token_urlsafe(16),user,cid,None,'course_'+result['status'],result['mastery_score'],result['mastery_confidence'],json.dumps(snapshot,ensure_ascii=False),FINAL_POLICY['version'],time,cursor,c['state_hash']))
        return rid

    def report(self,user,cid):
        c=self._context(user,cid)
        with self.store.connect() as db:
            row=db.execute('SELECT * FROM course_mastery_reports WHERE user_id=? AND course_id=? ORDER BY version DESC LIMIT 1',(user,cid)).fetchone()
            history=[dict(r) for r in db.execute('SELECT id,version,created_at FROM course_mastery_reports WHERE user_id=? AND course_id=? ORDER BY version DESC LIMIT 5',(user,cid))]
        if not row:return {'available':False,'note':'完成掌握检测或明确暂时结束课程后，再生成掌握报告。'}
        r=dict(row);r.update(json.loads(r.pop('result_json')));r['summary']=json.loads(r.pop('summary_json'));r.pop('user_id');r['is_stale']=r['state_hash']!=c['state_hash'];r['history']=history;return r

    def refresh_report(self,user,cid,model=None,summary=False):
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE');c=self._context(user,cid,db)
            if not c['completion']['eligible'] or not c['plan'] and c['course']['final_disposition'] not in {'content_completed','completed_with_gaps'}:raise ValueError('请先完成或明确暂缓终局检测')
            if c['plan'] and c['plan']['status']=='active':raise ValueError('请先完成或暂缓当前掌握检测')
            self._save_report(db,user,cid)
        report=self.report(user,cid)
        if summary and not report['summary']:
            package={'status':report['mastery_state']['status'],'summary':report['mastery_state']['label'],'source':'rule_fallback'}
            if model:
                from jsonschema import Draft202012Validator
                schema={'type':'object','additionalProperties':False,'required':['status','summary'],'properties':{'status':{'const':package['status']},'summary':{'type':'string','minLength':10,'maxLength':FINAL_POLICY['summary_max_characters']}}};failure=''
                for attempt in range(2):
                    try:
                        value=model.final_report_summary(report,failure);Draft202012Validator(schema).validate(value)
                        validate_explanation(value['summary'])
                        package={**value,'source':'model_explanation'};break
                    except Exception as exc:
                        failure=str(exc)
                        if hasattr(model,'_diagnostic'):model._diagnostic({'stage':'final_report_summary_validation','attempt':attempt+1,'failure':failure})
            with self.store.connect() as db:
                db.execute('BEGIN IMMEDIATE');self.store._manage_owned(db,user,cid)
                if self._context(user,cid,db)['state_hash']!=report['state_hash']:raise ValueError('学习证据已更新，请刷新报告后生成说明')
                db.execute("UPDATE course_mastery_reports SET summary_json=? WHERE id=? AND summary_json='{}'",(json.dumps(package,ensure_ascii=False),report['id']))
        return self.report(user,cid)

    def defer(self,user,cid,end_with_gaps=False):
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE');c=self._context(user,cid,db)
            if not c['completion']['eligible']:raise ValueError('请先完成课程内容，再选择暂时结束')
            db.execute("UPDATE final_assessment_plans SET status='deferred',completed_at=? WHERE user_id=? AND course_id=? AND status='active'",(iso(clock()),user,cid))
            disposition='completed_with_gaps' if end_with_gaps else 'content_completed'
            db.execute("INSERT INTO course_mastery_states VALUES(?,?,'{}',?,?) ON CONFLICT(user_id,course_id) DO UPDATE SET disposition=excluded.disposition",(user,cid,disposition,iso(clock())))
            repair=self._repair_row(db,user,cid)
            if repair:
                for target in repair['targets']:
                    db.execute("UPDATE repair_sessions SET status='deferred',completed_at=? WHERE id=? AND user_id=? AND course_id=? AND status IN ('diagnostic','teaching','checking')",(iso(clock()),target.get('repair_session_id',''),user,cid))
            db.execute("UPDATE course_repair_plans SET status='deferred',completed_at=? WHERE user_id=? AND course_id=? AND status IN ('active','needs_verification')",(iso(clock()),user,cid))
            if end_with_gaps:db.execute("UPDATE courses SET status='completed',updated_at=? WHERE id=?",(iso(clock()),cid))
            self._save_report(db,user,cid);event(db,user,cid,'final_deferred',{'disposition':disposition})
        return self.status(user,cid)

    def _repair_row(self,db,user,cid):
        row=db.execute("SELECT * FROM course_repair_plans WHERE user_id=? AND course_id=? AND status IN ('active','needs_verification') ORDER BY created_at DESC LIMIT 1",(user,cid)).fetchone()
        if not row:return None
        r=dict(row);r['targets']=json.loads(r.pop('targets_json'));r.pop('user_id');return r

    def remediation_start(self,user,cid):
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE');c=self._context(user,cid,db);old=self._repair_row(db,user,cid)
            if old:return old
            if not c['completion']['eligible'] or not c['plan'] or c['plan']['status'] not in {'completed','deferred'}:raise ValueError('请先完成或暂缓掌握检测，再选择终局补强')
            targets=FinalRemediationPlanner().plan(c['course'],c['graph'],c['states'],c['misconceptions'],c['results'])
            if not targets:return {'available':False,'note':'当前没有需要短时补强的明确目标；长期记忆可按已有复习建议检查。'}
            rid=self._save_report(db,user,cid);pid=secrets.token_urlsafe(16)
            db.execute('INSERT INTO course_repair_plans VALUES(?,?,?,?,?,?,?,?)',(pid,user,cid,rid,'active',json.dumps(targets),iso(clock()),None));event(db,user,cid,'course_repair_started',{'plan_id':pid})
        return self.status(user,cid)['repair_plan']

    def remediation_target(self,user,cid,atom_id,context=None):
        from .service import LearningLoopService
        with self.store.connect() as db:
            c=self._context(user,cid,db);repair=self._repair_row(db,user,cid)
        if not repair or repair['status']!='active':raise ValueError('请先开始当前课程的终局补强')
        target=next((t for t in repair['targets'] if t['atom_id']==atom_id and t['status']!='completed'),None)
        if not target:raise ValueError('该知识点不是当前未完成补强目标')
        if context is None:context={'section_ordinal':c['course']['current_ordinal'],'view':'learn','scroll_y':0}
        loop=LearningLoopService(self.store);active=loop.snapshot(user,cid)['active_repair']
        if active and active['id']!=target.get('repair_session_id'):raise ValueError('请先完成或暂缓当前短时补强任务')
        decision={'action':'remediate','target_atom_id':target['atom_id'],'reason_code':target['reason_code'],'priority':target['priority'],'metadata':{'origin_atom_id':target['origin_atom_id'],'depth':target['depth'],'course_repair_plan_id':repair['id']}}
        return loop.repair_start(user,cid,target['origin_atom_id'],context,course_decision=decision)
