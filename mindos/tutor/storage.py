"""Selective course-scoped dialogue and separate personal teaching memory."""
import json,re,secrets
from datetime import datetime,timezone
def now():return datetime.now(timezone.utc).isoformat(timespec="microseconds")

SCHEMA='''
CREATE TABLE IF NOT EXISTS tutor_conversations (
 id TEXT PRIMARY KEY,user_id TEXT NOT NULL,course_id TEXT NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
 goal_id TEXT,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,UNIQUE(user_id,course_id)
);
CREATE TABLE IF NOT EXISTS tutor_messages (
 id INTEGER PRIMARY KEY AUTOINCREMENT,conversation_id TEXT NOT NULL REFERENCES tutor_conversations(id) ON DELETE CASCADE,
 role TEXT NOT NULL,content TEXT NOT NULL,message_type TEXT NOT NULL,section_id TEXT NOT NULL,atom_id TEXT,
 request_id TEXT NOT NULL,payload_json TEXT NOT NULL,created_at TEXT NOT NULL,
 UNIQUE(conversation_id,request_id,role)
);
CREATE INDEX IF NOT EXISTS tutor_message_scope ON tutor_messages(conversation_id,section_id,id);
CREATE TABLE IF NOT EXISTS tutor_memories (
 id INTEGER PRIMARY KEY AUTOINCREMENT,user_id TEXT NOT NULL,course_id TEXT NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
 atom_id TEXT,memory_type TEXT NOT NULL,content TEXT NOT NULL,quote TEXT NOT NULL,active INTEGER NOT NULL DEFAULT 1,
 created_at TEXT NOT NULL,UNIQUE(user_id,course_id,memory_type,quote)
);
CREATE TABLE IF NOT EXISTS tutor_observations (
 id TEXT PRIMARY KEY,user_id TEXT NOT NULL,course_id TEXT NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
 atom_id TEXT NOT NULL,observation_type TEXT NOT NULL,description TEXT NOT NULL,confidence REAL NOT NULL,
 status TEXT NOT NULL DEFAULT 'candidate',quote TEXT NOT NULL,created_at TEXT NOT NULL,quiz_id TEXT,
 verification_json TEXT NOT NULL DEFAULT '{}',UNIQUE(user_id,course_id,atom_id,observation_type,quote)
);
CREATE INDEX IF NOT EXISTS tutor_observation_owner ON tutor_observations(user_id,course_id,created_at);
'''
def migrate(db):db.executescript(SCHEMA)
def social(message):return bool(re.fullmatch(r'(?:你好|您好|hi|hello|谢谢|感谢|好的|收到|明白了|哈哈|嗯|再见|ok|早上好|晚上好)[\s！!。.,，~～]*',message,re.I))
def public(row):
    result=json.loads(row['payload_json']);result.update(id=row['id'],role=row['role'],content=row['content'],message_type=row['message_type'],created_time=row['created_at']);return result

class TutorMemoryStore:
    def __init__(self,store):self.store=store
    def history(self,user,cid,before=None):
        self.store._knowledge_course(user,cid)
        if before is not None and (type(before) is not int or before<1):raise ValueError('历史页码无效')
        with self.store.connect() as db:
            position=db.execute('SELECT position_x,position_y,updated_time FROM assistant_position WHERE user_id=? AND course_id=?',(user,cid)).fetchone()
            rows=db.execute('SELECT m.* FROM tutor_messages m JOIN tutor_conversations c ON c.id=m.conversation_id WHERE c.user_id=? AND c.course_id=?'+(' AND m.id<?' if before else '')+' ORDER BY m.id DESC LIMIT 81',(user,cid,*([before] if before else []))).fetchall()
        return {'messages':[public(r) for r in reversed(rows[:80])],'has_more':len(rows)>80,'position':{'x':position['position_x'],'y':position['position_y'],'updated_time':position['updated_time']} if position else None}
    def exchange(self,user,cid,rid):
        with self.store.connect() as db:return [public(r) for r in db.execute('SELECT m.* FROM tutor_messages m JOIN tutor_conversations c ON c.id=m.conversation_id WHERE c.user_id=? AND c.course_id=? AND m.request_id=? ORDER BY m.id',(user,cid,rid))]
    def remember(self,db,user,cid,aid,items,message):
        for item in items:
            kind=item['memory_type'];quote=item['supporting_quote']
            # Model inference alone never creates a preference, habit or "insight".
            if kind in {'preference','explanation_style'} and not re.search(r'喜欢|希望|偏好|习惯|请先|先.*再|想要',quote):continue
            if kind=='learning_habit' and not re.search(r'我(?:平时|通常|每天|习惯|一般)',quote):continue
            if kind=='important_insight' and not re.search(r'我理解|我明白|原来|也就是说|我的理解',quote):continue
            db.execute('INSERT OR IGNORE INTO tutor_memories(user_id,course_id,atom_id,memory_type,content,quote,created_at) VALUES(?,?,?,?,?,?,?)',(user,cid,aid,kind,item['content'],quote,now()))
        db.execute('DELETE FROM tutor_memories WHERE user_id=? AND course_id=? AND id NOT IN (SELECT id FROM tutor_memories WHERE user_id=? AND course_id=? ORDER BY id DESC LIMIT 40)',(user,cid,user,cid))
    def save(self,user,cid,rid,message,result,context,value,revision):
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE');owned=self.store._manage_owned(db,user,cid)
            if owned['content_revision']!=revision:raise ValueError('课程内容已经改变，请刷新后提问')
            db.execute('INSERT OR IGNORE INTO tutor_conversations VALUES(?,?,?,?,?,?)',(secrets.token_urlsafe(16),user,cid,context['learning_goal']['id'] if context['learning_goal'] else None,now(),now()))
            conv=db.execute('SELECT id FROM tutor_conversations WHERE user_id=? AND course_id=?',(user,cid)).fetchone()[0]
            cur=context['current_context'];base={'context':cur,'strategy':value['strategy'],'search':{},'related_knowledge':[],'blocks':[],'teaching_action':{}}
            for role,content,kind,payload in [('user',message,'reflection' if value['strategy']=='socratic' and context['recent_dialogue'] else 'question',base),('assistant',result['answer'],value['message_type'],{**base,**{k:result[k] for k in ['blocks','search','related_knowledge','teaching_action','strategy','fallback']}})]:
                db.execute('INSERT INTO tutor_messages(conversation_id,role,content,message_type,section_id,atom_id,request_id,payload_json,created_at) VALUES(?,?,?,?,?,?,?,?,?)',(conv,role,content,kind,cur['section_id'],cur['knowledge_atom_id'],rid,json.dumps(payload,ensure_ascii=False),now()))
            db.execute('UPDATE tutor_conversations SET updated_at=? WHERE id=?',(now(),conv))
            self.remember(db,user,cid,cur['knowledge_atom_id'],value['memories'],message)
            for item in value['observations']:
                db.execute('INSERT OR IGNORE INTO tutor_observations(id,user_id,course_id,atom_id,observation_type,description,confidence,quote,created_at) VALUES(?,?,?,?,?,?,?,?,?)',(secrets.token_urlsafe(16),user,cid,item['atom_id'],item['observation_type'],item['description'],item['confidence'],item['supporting_quote'],now()))
            db.execute('DELETE FROM tutor_messages WHERE conversation_id=? AND id NOT IN (SELECT id FROM tutor_messages WHERE conversation_id=? ORDER BY id DESC LIMIT 200)',(conv,conv))
            db.execute("DELETE FROM tutor_observations WHERE user_id=? AND course_id=? AND status='candidate' AND quiz_id IS NULL AND id NOT IN (SELECT id FROM tutor_observations WHERE user_id=? AND course_id=? ORDER BY created_at DESC,rowid DESC LIMIT 80)",(user,cid,user,cid))
        return self.exchange(user,cid,rid)
