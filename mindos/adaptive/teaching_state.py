"""Read actual quiz evidence; keep preferences/feedback distinct from mastery."""
import json
import secrets
from ..learning.policy import POLICY
from datetime import datetime, timezone

FEEDBACK = {'confused','formula_confusing','rephrase','visual','example','deepen','backtrack','check','review','challenge'}
STYLES = {'visual','example','text','formula'}

def stamp():return datetime.now(timezone.utc).isoformat(timespec='seconds')

def migrate_adaptive(db):
    for table, fields in {
        'sections': {'lesson_blocks_json':'[]','teaching_action_json':'{}'},
        'tutor_turns': {'blocks_json':'[]','action_json':'{}'},
        'assistant_message': {'blocks_json':'[]','action_json':'{}'},
    }.items():
        columns={r[1] for r in db.execute(f'PRAGMA table_info({table})')}
        for key,default in fields.items():
            if key not in columns:db.execute(f"ALTER TABLE {table} ADD COLUMN {key} TEXT NOT NULL DEFAULT '{default}'")
    db.executescript('''
        CREATE TABLE IF NOT EXISTS teaching_preferences (
          user_id TEXT NOT NULL, course_id TEXT NOT NULL REFERENCES courses(id),
          math_level TEXT NOT NULL, styles_json TEXT NOT NULL, updated_at TEXT NOT NULL,
          PRIMARY KEY(user_id,course_id)
        );
        CREATE TABLE IF NOT EXISTS teaching_feedback (
          id TEXT PRIMARY KEY, user_id TEXT NOT NULL, course_id TEXT NOT NULL REFERENCES courses(id),
          section_id TEXT NOT NULL REFERENCES sections(id), atom_id TEXT, kind TEXT NOT NULL,
          created_at TEXT NOT NULL, request_id TEXT NOT NULL,
          UNIQUE(user_id,course_id,request_id)
        );
        CREATE TABLE IF NOT EXISTS teaching_actions (
          id INTEGER PRIMARY KEY, user_id TEXT NOT NULL, course_id TEXT NOT NULL REFERENCES courses(id),
          section_id TEXT NOT NULL REFERENCES sections(id), atom_id TEXT, action_json TEXT NOT NULL,
          state_json TEXT NOT NULL, created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS adaptive_history ON teaching_actions(user_id,course_id,section_id,id);
    ''')

class AdaptiveStorage:
    def teaching_preferences(self,user,cid):
        self._knowledge_course(user,cid)
        with self.connect() as db:row=db.execute('SELECT * FROM teaching_preferences WHERE user_id=? AND course_id=?',(user,cid)).fetchone()
        return {'math_level':row['math_level'] if row else 'unknown',
                'preferred_style':json.loads(row['styles_json']) if row else [],'source':'user_reported'}

    def save_teaching_preferences(self,user,cid,payload):
        if not isinstance(payload,dict) or set(payload)-{'math_level','preferred_style'}:raise ValueError('只能设置数学基础与讲解偏好')
        old=self.teaching_preferences(user,cid)
        level=payload.get('math_level',old['math_level']);styles=payload.get('preferred_style',old['preferred_style'])
        if not isinstance(level,str) or level not in {'unknown','basic','advanced'}:raise ValueError('请选择合适的数学基础')
        if not isinstance(styles,list) or len(styles)>4 or any(not isinstance(v,str) or v not in STYLES for v in styles):raise ValueError('讲解偏好无效')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE');self._manage_owned(db,user,cid)
            db.execute('INSERT INTO teaching_preferences VALUES(?,?,?,?,?) ON CONFLICT(user_id,course_id) DO UPDATE SET math_level=excluded.math_level,styles_json=excluded.styles_json,updated_at=excluded.updated_at',
                       (user,cid,level,json.dumps(list(dict.fromkeys(styles))),stamp()))
        return self.teaching_preferences(user,cid)

    def save_teaching_feedback(self,user,cid,section_id,kind,atom_id=None,request_id=None):
        if not isinstance(kind,str) or kind not in FEEDBACK:raise ValueError('学习反馈无效')
        course=self._knowledge_course(user,cid)
        section=next((s for s in course['sections'] if s['id']==section_id and s['ordinal']<=course['current_ordinal']),None)
        if not section:raise ValueError('当前小节尚未开放')
        if atom_id:
            atom=self.atom(user,cid,atom_id,unlocked=True)
            if atom['section']!=section['ordinal']:raise ValueError('知识点不属于当前小节')
        request_id=request_id or secrets.token_urlsafe(20)
        if not isinstance(request_id,str) or not 1<=len(request_id)<=100:raise ValueError('反馈请求编号无效')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE');self._manage_owned(db,user,cid)
            old=db.execute('SELECT section_id,atom_id,kind FROM teaching_feedback WHERE user_id=? AND course_id=? AND request_id=?',(user,cid,request_id)).fetchone()
            if old:
                if (old['section_id'],old['atom_id'],old['kind'])!=(section_id,atom_id,kind):raise ValueError('反馈请求编号已用于其他内容')
            else:db.execute('INSERT INTO teaching_feedback VALUES(?,?,?,?,?,?,?,?)',(secrets.token_urlsafe(16),user,cid,section_id,atom_id,kind,stamp(),request_id))
        return {'kind':kind,'source':'user_reported','affects_mastery':False}

    @staticmethod
    def record_teaching_action(db,user,cid,section_id,atom_id,package):
        if package and package.get('teaching_action'):
            db.execute('INSERT INTO teaching_actions(user_id,course_id,section_id,atom_id,action_json,state_json,created_at) VALUES(?,?,?,?,?,?,?)',
                       (user,cid,section_id,atom_id,json.dumps(package['teaching_action'],ensure_ascii=False),json.dumps(package.get('learning_state',{}),ensure_ascii=False),stamp()))

class LearningStateManager:
    def __init__(self,store):self.store=store

    def read(self,user,cid,ordinal,atom_id=None):
        course=self.store._knowledge_course(user,cid)
        if type(ordinal) is not int or not 1<=ordinal<=course['current_ordinal']:raise ValueError('小节尚未开放')
        section=course['sections'][ordinal-1]
        if atom_id:
            atom=self.store.atom(user,cid,atom_id,unlocked=True)
            if atom['section']!=ordinal:raise ValueError('知识点不属于当前小节')
        else:atom=None
        knowledge=self.store.knowledge_state(user,cid)
        all_atoms=[a for a in knowledge['atoms'] if a.get('quality_status')!='deprecated']
        current=[a for a in all_atoms if (a['id']==atom_id if atom_id else a['section']==ordinal)]
        graph=self.store.graph(user,cid) or {'edges':[]}
        ids={a['id'] for a in current};before={a['id']:a for a in all_atoms if a['section']<=ordinal}
        prereqs=[before[e['from']] for e in graph['edges'] if e['type']=='prerequisite' and e['to'] in ids and e['from'] in before]
        with self.store.connect() as db:
            quizzes=[dict(r) for r in db.execute('SELECT q.* FROM quizzes q JOIN sections s ON s.id=q.section_id WHERE q.course_id=? AND s.ordinal<=? AND q.submitted_at IS NOT NULL ORDER BY q.submitted_at DESC,q.rowid DESC LIMIT 8',(cid,ordinal))]
            feedback=[r[0] for r in db.execute('SELECT kind FROM teaching_feedback WHERE user_id=? AND course_id=? AND section_id=? AND (atom_id IS NULL OR atom_id=?) ORDER BY rowid DESC LIMIT 8',(user,cid,section['id'],atom_id))]
            actions=[json.loads(r[0]) for r in db.execute('SELECT action_json FROM teaching_actions WHERE user_id=? AND course_id=? AND section_id=? AND (atom_id IS NULL OR atom_id=?) ORDER BY id DESC LIMIT 6',(user,cid,section['id'],atom_id))]
        dimensions={k:{'correct':0,'attempts':0,'rate':None} for k in ['concept','application','reasoning','math','transfer','unknown']}
        for q in quizzes:
            for item,answer,given in zip(json.loads(q['questions_json']),json.loads(q['answers_json']),json.loads(q['user_answers_json'])):
                kind=item.get('assessment_type','unknown');kind=kind if kind in dimensions else 'unknown'
                dimensions[kind]['attempts']+=1;dimensions[kind]['correct']+=int(answer['answer']==given)
        for d in dimensions.values():
            if d['attempts']:d['rate']=round(d['correct']/d['attempts'],3)
        latest=quizzes[0] if quizzes else None
        assessment={'rate':latest['score']/len(json.loads(latest['answers_json'])),'section_id':latest['section_id'],'scope':latest['scope'],'submitted_at':latest['submitted_at']} if latest else None
        measured=[a['rate']/100 for a in current if a.get('rate') is not None]
        rate=sum(measured)/len(measured) if measured else (assessment['rate'] if assessment and assessment['section_id']==section['id'] else None)
        estimates=[a.get('knowledge_state') for a in current if a.get('knowledge_state',{}).get('mastery') is not None]
        certainty=None
        if estimates:
            rate=sum(s['mastery'] for s in estimates)/len(estimates)
            certainty=sum(s['confidence'] for s in estimates)/len(estimates)
        preferences=self.store.teaching_preferences(user,cid)
        state={'course':course['title'],'chapter':section['title'],'knowledge_atom':atom['title'] if atom else None,
               'learning_goal':course['goal'],'learner_level':course.get('learner_level','零基础'),
               'cognitive_state':{'status':'unknown' if rate is None else 'weak' if rate<.6 else 'partial_understanding' if rate<.85 else 'strong' if certainty is not None and certainty>=POLICY['mastered_confidence'] else 'partial_understanding',
                                  'knowledge_level':rate,'confidence':certainty,'source':'weighted_evidence' if estimates else 'independent_quiz' if rate is not None else 'no_evidence'},
               'assessment_dimensions':dimensions,'recent_assessment':assessment,'previous_strategy':actions,
               'user_feedback':list(reversed(feedback)),'preferences':preferences,
               'next_target':course['sections'][ordinal]['title'] if ordinal<len(course['sections']) else None,
               'learning_loop':knowledge.get('learning_loop',{}),
               'rule':'反馈和教学策略不写入掌握记录；正确率不是置信度，未知能力不填虚构分数'}
        fallback_type='operation' if any(t in section['title'] for t in ['步骤','流程','操作','算法']) else 'mechanism' if any(t in section['title'].lower() for t in ['机制','原理','attention','过程']) else 'concept'
        topic_type=atom['type'] if atom else next((kind for kind in ['operation','mechanism','relation','reason','skill'] if any(a['type']==kind for a in current)),fallback_type)
        context={'name':atom['title'] if atom else section['title'],'type':topic_type,
                 'atoms':current,'prerequisite':[a['title'] for a in prereqs],
                 'weak_prerequisite':[a['title'] for a in prereqs if a.get('rate') is not None and a['rate']<60],
                 'common_mistakes':[m['description'] for m in knowledge.get('learning_loop',{}).get('misconceptions',[]) if m['atom_id'] in ids],
                 'repair_managed':True}
        return state,context
