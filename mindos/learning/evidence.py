"""Append-only server evidence; replayable and idempotent within course scope."""
import json,secrets
from .policy import TYPES,SOURCES,iso,clock
SCHEMA='''
CREATE TABLE IF NOT EXISTS learning_evidence (
 id TEXT PRIMARY KEY,user_id TEXT NOT NULL,course_id TEXT NOT NULL REFERENCES courses(id),
 section_id TEXT,atom_id TEXT NOT NULL DEFAULT '',evidence_type TEXT NOT NULL,source TEXT NOT NULL,
 result TEXT NOT NULL,score REAL,confidence TEXT,difficulty TEXT NOT NULL,hint_used INTEGER NOT NULL,
 response_time_ms INTEGER,misconception_code TEXT,metadata_json TEXT NOT NULL,created_at TEXT NOT NULL,
 event_key TEXT NOT NULL,UNIQUE(course_id,event_key,atom_id)
);
CREATE INDEX IF NOT EXISTS evidence_scope ON learning_evidence(user_id,course_id,atom_id,created_at);
CREATE TABLE IF NOT EXISTS knowledge_states (
 user_id TEXT NOT NULL,course_id TEXT NOT NULL REFERENCES courses(id),atom_id TEXT NOT NULL,
 state_json TEXT NOT NULL,version INTEGER NOT NULL,updated_at TEXT NOT NULL,
 PRIMARY KEY(user_id,course_id,atom_id)
);
CREATE TABLE IF NOT EXISTS learning_misconceptions (
 id TEXT PRIMARY KEY,user_id TEXT NOT NULL,course_id TEXT NOT NULL REFERENCES courses(id),atom_id TEXT NOT NULL,
 code TEXT NOT NULL,description TEXT NOT NULL,confidence REAL NOT NULL,status TEXT NOT NULL,
 first_detected_at TEXT NOT NULL,last_detected_at TEXT NOT NULL,evidence_count INTEGER NOT NULL,
 resolved_at TEXT,metadata_json TEXT NOT NULL,UNIQUE(user_id,course_id,atom_id,code)
);
CREATE TABLE IF NOT EXISTS knowledge_state_history (
 id INTEGER PRIMARY KEY,user_id TEXT NOT NULL,course_id TEXT NOT NULL REFERENCES courses(id),atom_id TEXT NOT NULL,
 old_json TEXT NOT NULL,new_json TEXT NOT NULL,evidence_ids_json TEXT NOT NULL,reason_code TEXT NOT NULL,created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS loop_events (
 id INTEGER PRIMARY KEY,user_id TEXT NOT NULL,course_id TEXT NOT NULL REFERENCES courses(id),
 kind TEXT NOT NULL,metadata_json TEXT NOT NULL,created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS repair_sessions (
 id TEXT PRIMARY KEY,user_id TEXT NOT NULL,course_id TEXT NOT NULL REFERENCES courses(id),origin_atom_id TEXT NOT NULL,
 target_atom_id TEXT NOT NULL,trigger_reason TEXT NOT NULL,status TEXT NOT NULL,depth INTEGER NOT NULL,
 started_at TEXT NOT NULL,completed_at TEXT,return_context_json TEXT NOT NULL,content_json TEXT NOT NULL DEFAULT '{}'
);
CREATE UNIQUE INDEX IF NOT EXISTS one_active_repair ON repair_sessions(user_id,course_id) WHERE status IN ('diagnostic','teaching','checking');
CREATE TABLE IF NOT EXISTS returning_sessions (
 id TEXT PRIMARY KEY,user_id TEXT NOT NULL,course_id TEXT NOT NULL REFERENCES courses(id),status TEXT NOT NULL,
 started_at TEXT NOT NULL,completed_at TEXT,targets_json TEXT NOT NULL,return_context_json TEXT NOT NULL,decision_json TEXT NOT NULL DEFAULT '{}'
);
CREATE UNIQUE INDEX IF NOT EXISTS one_active_return ON returning_sessions(user_id,course_id) WHERE status='pending';
CREATE TABLE IF NOT EXISTS loop_activity (
 user_id TEXT NOT NULL,course_id TEXT NOT NULL REFERENCES courses(id),last_active_at TEXT NOT NULL,
 PRIMARY KEY(user_id,course_id)
);
CREATE TABLE IF NOT EXISTS learning_migrations (name TEXT PRIMARY KEY,applied_at TEXT NOT NULL);
'''

def event(db,user,cid,kind,metadata,at=None):
 db.execute('INSERT INTO loop_events(user_id,course_id,kind,metadata_json,created_at) VALUES(?,?,?,?,?)',(user,cid,kind,json.dumps(metadata,ensure_ascii=False),iso(at or clock())))

def append(db,user,cid,section,atom,kind,source,result,key,*,score=None,confidence=None,difficulty='standard',hint=False,response_time_ms=None,code=None,metadata=None,at=None):
 if kind not in TYPES or source not in SOURCES or result not in {'correct','wrong','signal','introduced'}:raise ValueError('学习证据类型无效')
 if confidence not in {None,'low','medium','high'}:raise ValueError('答题信心无效')
 if type(hint) is not bool:raise ValueError('提示使用标记无效')
 if response_time_ms is not None and (type(response_time_ms) is not int or not 0<=response_time_ms<=3600000):raise ValueError('答题用时无效')
 owner=db.execute('SELECT session_id FROM courses WHERE id=?',(cid,)).fetchone()
 if not owner or owner[0]!=user:raise ValueError('课程不存在')
 if atom:
  row=db.execute('SELECT graph_json FROM course_graphs WHERE course_id=?',(cid,)).fetchone()
  if not row or atom not in {a['id'] for a in json.loads(row[0])['atoms']}:raise ValueError('证据知识点不属于课程')
 identifier=secrets.token_urlsafe(16)
 inserted=db.execute('INSERT OR IGNORE INTO learning_evidence VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
  (identifier,user,cid,section,atom or '',kind,source,result,score,confidence,difficulty,int(hint),response_time_ms,code,json.dumps(metadata or {},ensure_ascii=False),iso(at or clock()),key)).rowcount
 if inserted:event(db,user,cid,'question_answered' if result in {'correct','wrong'} else kind,{'evidence_id':identifier,'atom_id':atom,'result':result},at)
 return identifier if inserted else None

def quiz_evidence(db,row,confidence=None,hints=None,times=None):
 """Only server-scored submitted answers produce independent evidence."""
 cid=row['course_id'];user=db.execute('SELECT session_id FROM courses WHERE id=?',(cid,)).fetchone()[0]
 questions=json.loads(row['questions_json']);answers=json.loads(row['answers_json']);given=json.loads(row['user_answers_json'])
 graph=db.execute('SELECT graph_json FROM course_graphs WHERE course_id=?',(cid,)).fetchone()
 atoms={a['id'] for a in json.loads(graph[0])['atoms']} if graph else set()
 kind=row['assessment_kind'] if 'assessment_kind' in row.keys() else 'chapter_quiz'
 typ={'final_retention':'review_answer','final_transfer':'transfer_test','review':'review_answer','returning':'review_answer','remediation':'remediation_check','diagnostic':'diagnostic_test','transfer':'transfer_test','lesson_check':'lesson_check'}.get(kind,'quiz_answer')
 if row['scope']=='diagnostic':typ='diagnostic_test'
 confidence=confidence or [None]*len(questions);hints=hints or [False]*len(questions);times=times or [None]*len(questions)
 touched=set()
 for i,(q,a,g) in enumerate(zip(questions,answers,given)):
  targets=[v for v in q.get('atom_ids',[]) if v in atoms] or ['']
  mappings=a.get('misconceptions',{});mis=mappings.get(g) if g!=a['answer'] else None
  for atom in targets:
   if append(db,user,cid,row['section_id'],atom,typ,'review' if typ=='review_answer' else 'remediation' if typ=='remediation_check' else 'assessment' if typ=='diagnostic_test' else 'quiz',
      'correct' if g==a['answer'] else 'wrong',f"quiz:{row['id']}:{i}",score=int(g==a['answer']),confidence=confidence[i],hint=hints[i],response_time_ms=times[i],
      code=mis['code'] if mis else None,difficulty=q.get('difficulty','standard'),at=__import__('datetime').datetime.fromisoformat(row['submitted_at']),
      metadata={'quiz_id':row['id'],'question_index':i,'assessment_type':q.get('assessment_type','unknown'),'question':q['prompt'],'selected':g,
       'misconception_description':mis['description'] if mis else None,'checked_codes':[v['code'] for v in mappings.values()],
       **({'cross_course_verification':True,'inherited_prior_id':q['cross_course_verification']['prior_id'],'canonical_atom_id':q['cross_course_verification']['canonical_atom_id']} if q.get('cross_course_verification') else {}),
       'reused_question':bool(q.get('reused_question')),'legacy':bool(row.get('legacy',False)) if isinstance(row,dict) else False}):
    if atom:touched.add(atom)
 return user,cid,touched

def migrate(db):
 db.executescript(SCHEMA)
 columns={r[1] for r in db.execute('PRAGMA table_info(quizzes)')}
 for name,definition in {'assessment_kind':"TEXT NOT NULL DEFAULT 'chapter_quiz'",'confidence_json':"TEXT NOT NULL DEFAULT '[]'",'hint_flags_json':"TEXT NOT NULL DEFAULT '[]'",'response_times_json':"TEXT NOT NULL DEFAULT '[]'",'loop_session_id':"TEXT NOT NULL DEFAULT ''"}.items():
  if name not in columns:db.execute(f'ALTER TABLE quizzes ADD COLUMN {name} {definition}')
 if db.execute("SELECT 1 FROM learning_migrations WHERE name='evidence-v1'").fetchone():return
 from .state import KnowledgeStateEngine
 for row in db.execute('SELECT * FROM quizzes WHERE submitted_at IS NOT NULL ORDER BY submitted_at,rowid').fetchall():
  row=dict(row);row['legacy']=True
  user,cid,touched=quiz_evidence(db,row)
  for atom in touched:KnowledgeStateEngine().update(db,user,cid,atom)
 db.execute('INSERT INTO learning_migrations VALUES(?,?)',('evidence-v1',iso(clock())))

def mark_help(db,cid,section=None,atom=None):
 """Persist help before submission; a client cannot undo it with false flags."""
 # Final detection can target an earlier lesson; mark the active final question too.
 final=db.execute("SELECT q.id,q.questions_json,q.hint_flags_json FROM quizzes q JOIN final_assessment_plans p ON p.id=q.loop_session_id WHERE q.course_id=? AND q.scope='final' AND q.submitted_at IS NULL AND p.status='active'",(cid,)).fetchall()
 for r in final:
  db.execute('UPDATE quizzes SET hint_flags_json=? WHERE id=?',(json.dumps([True]*len(json.loads(r['questions_json']))),r['id']))
 if not section and not atom:return
 rows=db.execute('SELECT id,questions_json,hint_flags_json FROM quizzes WHERE course_id=? AND submitted_at IS NULL'+(' AND section_id=?' if section else ''),(cid,section) if section else (cid,)).fetchall()
 for r in rows:
  qs=json.loads(r['questions_json']);flags=json.loads(r['hint_flags_json']) or [False]*len(qs)
  for i,q in enumerate(qs):
   if atom is None or atom in q.get('atom_ids',[]):flags[i]=True
  db.execute('UPDATE quizzes SET hint_flags_json=? WHERE id=?',(json.dumps(flags),r['id']))
