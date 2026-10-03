"""Adapter inside P6's existing two-attempt loop. No independent regeneration loop."""
import json
from pathlib import Path
from ..service import TutorService, _LOCKS
from ..protocol import validate, prompt, SCHEMA
from ..storage import now
from .quality_controller import TutorQualityController, ADJUSTMENTS

SCHEMA_SQL = '''
CREATE TABLE IF NOT EXISTS tutor_response_meta (
 id INTEGER PRIMARY KEY AUTOINCREMENT,
 user_id TEXT NOT NULL,
 course_id TEXT NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
 request_id TEXT NOT NULL,
 message_id INTEGER REFERENCES tutor_messages(id) ON DELETE CASCADE,
 strategy TEXT NOT NULL,quality_flags TEXT NOT NULL,retry_count INTEGER NOT NULL,
 approved INTEGER NOT NULL,created_at TEXT NOT NULL,
 UNIQUE(user_id,course_id,request_id)
);
CREATE INDEX IF NOT EXISTS tutor_quality_owner ON tutor_response_meta(user_id,course_id,id);
'''

def migrate(db):
    db.executescript(SCHEMA_SQL)

def quality_prompt(name):
    return (Path(__file__).resolve().parents[3]/'prompts'/'tutor'/'quality'/f'{name}.md').read_text(encoding='utf-8')

class QualityControlledModel:
    def __init__(self,store,user,model):
        self.store,self.user,self.model=store,user,model
        self.controller=TutorQualityController()
        self.flags=[];self.attempts=0;self.last_decision=None
    def _diagnostic(self,event):
        # Forward P6's already validated packets / failure codes only.
        try:
            if self.model and hasattr(self.model,'_diagnostic'):self.model._diagnostic(event)
        except Exception:
            pass  # A logging outage must not make P6 save a previous rejected generation.
    @property
    def diagnostic_path(self):
        return getattr(self.model,'diagnostic_path',None)
    def history(self,context):
        cur=context['current_context'];cid=context['course']['id']
        with self.store.connect() as db:
            rows=db.execute("SELECT m.content FROM tutor_messages m JOIN tutor_conversations c ON c.id=m.conversation_id WHERE c.user_id=? AND c.course_id=? AND m.section_id=? AND (m.atom_id IS NULL OR m.atom_id=?) AND m.role='assistant' ORDER BY m.id DESC LIMIT ?",
                (self.user,cid,cur['section_id'],cur['knowledge_atom_id'],self.controller.policy['max_history_context'])).fetchall()
        return [{'role':'assistant','content':r['content'][:6000]} for r in reversed(rows)]
    def tutor_json(self,payload,repair_reason=''):
        self.attempts+=1
        if self.attempts>2:raise ValueError('RETRY_BUDGET_EXHAUSTED')
        guidance={'policy_version':self.controller.policy['version'],
                  'rules':[ADJUSTMENTS[k] for k in ADJUSTMENTS],
                  'repair_flags':list(dict.fromkeys(self.flags)),
                  'known_concepts':payload['strategy']['known_concepts'],
                  'preserve_question_and_goal':True}
        request={**payload,'quality_guidance':guidance}
        from ...model import ModelGateway
        try:
            if isinstance(self.model,ModelGateway):
                # Reuse the original transport, credentials, timeout and strict schema.
                system='\n'.join(prompt(n) for n in ['context_builder','strategy_selector','explanation','socratic','observation'])
                system+='\n'+quality_prompt('depth_check')+'\n'+quality_prompt('alignment_check')
                if self.attempts==2:system+='\n'+quality_prompt('rewrite_request')+'\n检查提示：'+','.join(guidance['repair_flags'])+' '+repair_reason[:100]
                system+='\n严格符合以下 JSON Schema：'+json.dumps(SCHEMA,ensure_ascii=False)
                raw=self.model._json(system,json.dumps(request,ensure_ascii=False),max_tokens=4500)
            else:
                raw=self.model.tutor_json(request,repair_reason=repair_reason) if self.model else None
        except Exception:
            self.flags.append('model_unavailable')
            raise ValueError('MODEL_UNAVAILABLE') from None
        try:
            value=validate(raw,payload)
        except Exception:
            # JSON schema exceptions can contain the entire rejected packet. Do not forward it.
            self.flags.append('schema_or_scope')
            raise ValueError('P6_SCHEMA_OR_SCOPE') from None
        decision=self.controller.evaluate(value,payload['context'],payload['strategy'],self.history(payload['context']),
            payload['message'],payload['teaching_action'],payload['search'])
        self.last_decision=decision
        if not decision['approved']:
            self.flags.extend(decision['quality_flags'])
            raise ValueError('QUALITY_REWRITE_REQUIRED: '+','.join(decision['quality_flags']))
        return decision['final_response']

class QualityTutorService:
    def __init__(self,store):self.store=store
    def chat(self,user,payload,model,factory):
        # P6 remains the authority for validating the request, ownership and course revision.
        cid=payload.get('context_id',payload.get('course_id')) if isinstance(payload,dict) else None
        if not isinstance(cid,str):return TutorService(self.store).chat(user,payload,model,factory)
        with _LOCKS[hash((user,cid))%len(_LOCKS)]:
            adapter=QualityControlledModel(self.store,user,model)
            result=TutorService(self.store).chat(user,payload,adapter,factory)
            if not result.get('attempts') and adapter.attempts==0:
                # Idempotent saved exchange (or social greeting) must not re-run quality checks.
                return result
            flags=list(dict.fromkeys(adapter.flags))
            if result['fallback'] and any(f in ADJUSTMENTS for f in flags):
                answer='这次讲解仍未通过教学质量检查，我无法确认其中的具体细节。可以先回看当前小节，或把问题缩小到一个概念后再问；未保存这次回答，也没有改变课程进度或掌握记录。'
                result['answer']=answer;result['blocks']=[{'type':'paragraph','content':answer}]
                result['messages'][-1].update(content=answer,blocks=result['blocks'])
            meta={'strategy':result['strategy'],'quality_flags':flags,'retry_count':min(1,max(0,adapter.attempts-1)),
                  'approved':not result['fallback'],'created_at':now()}
            mid=result['messages'][-1]['id'] if result['saved'] else None
            with self.store.connect() as db:
                db.execute('BEGIN IMMEDIATE');self.store._manage_owned(db,user,cid)
                db.execute('INSERT INTO tutor_response_meta(user_id,course_id,request_id,message_id,strategy,quality_flags,retry_count,approved,created_at) VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(user_id,course_id,request_id) DO UPDATE SET message_id=excluded.message_id,strategy=excluded.strategy,quality_flags=excluded.quality_flags,retry_count=excluded.retry_count,approved=excluded.approved,created_at=excluded.created_at',
                    (user,cid,result['request_id'],mid,meta['strategy'],json.dumps(flags),meta['retry_count'],int(meta['approved']),meta['created_at']))
                db.execute('DELETE FROM tutor_response_meta WHERE user_id=? AND course_id=? AND id NOT IN (SELECT id FROM tutor_response_meta WHERE user_id=? AND course_id=? ORDER BY id DESC LIMIT 100)',(user,cid,user,cid))
            return result
    def debug(self,user,cid):
        self.store._knowledge_course(user,cid)
        with self.store.connect() as db:
            rows=db.execute('SELECT strategy,quality_flags,retry_count,approved,created_at FROM tutor_response_meta WHERE user_id=? AND course_id=? ORDER BY id DESC LIMIT 20',(user,cid)).fetchall()
        return {'policy_version':'quality-v1','responses':[{**dict(r),'quality_flags':json.loads(r['quality_flags']),'approved':bool(r['approved'])} for r in rows]}
