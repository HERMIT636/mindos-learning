"""Rebuild a bounded server-owned context; never persists whole model input."""
import json
from datetime import datetime
from zoneinfo import ZoneInfo
from ..adaptive.teaching_state import LearningStateManager
from ..adaptive.atie_engine import ATIEEngine
from ..teaching import TeachingOrchestrator

class TutorContextBuilder:
    def __init__(self,store):self.store=store
    def build(self,user,cid,selector,message):
        course=self.store._knowledge_course(user,cid)
        if not isinstance(selector,dict) or set(selector)-{'section_ordinal','knowledge_atom_id','authentic_task_id','atom_mode'}:raise ValueError('只能选择当前课程、小节和知识点，不能提供能力状态')
        mode='learning';task=None
        with self.store.connect() as db:
            task_id=selector.get('authentic_task_id')
            row=db.execute('SELECT * FROM authentic_tasks WHERE user_id=? AND course_id=? AND id=?',(user,cid,task_id)).fetchone() if task_id else db.execute("SELECT * FROM authentic_tasks WHERE user_id=? AND course_id=? AND status='created' ORDER BY rowid DESC LIMIT 1",(user,cid)).fetchone()
        if task_id and not row:raise ValueError('开放检测不属于当前课程')
        if row:
            task={**dict(row),**json.loads(row['task_json'])}
            if task['status']!='created':raise ValueError('开放检测已经结束')
            atom=self.store.atom(user,cid,task['atom_id'],unlocked=True)
            selector={**selector,'section_ordinal':atom['section'],'knowledge_atom_id':atom['id']};mode='authentic'
        else:
            # Read active final scope directly; status() can refresh unrelated reports.
            with self.store.connect() as db:
                row=db.execute("SELECT q.questions_json FROM quizzes q JOIN final_assessment_plans p ON p.id=q.loop_session_id WHERE q.course_id=? AND q.submitted_at IS NULL AND q.scope='final' AND p.status='active' AND p.content_revision=? ORDER BY q.rowid DESC LIMIT 1",(cid,course['content_revision'])).fetchone()
            if row:
                qs=json.loads(row[0]);ids=[i for q in qs for i in q.get('atom_ids',[])]
                if ids:
                    atom=self.store.atom(user,cid,ids[0],unlocked=True);selector={**selector,'section_ordinal':atom['section'],'knowledge_atom_id':atom['id']};mode='final'
        ordinal=selector.get('section_ordinal',course['current_ordinal']);aid=selector.get('knowledge_atom_id')
        state,knowledge=LearningStateManager(self.store).read(user,cid,ordinal,aid)
        section=course['sections'][ordinal-1]
        scope=TeachingOrchestrator(self.store).context(user,cid,section['id'])
        scope={k:v for k,v in scope.items() if k not in {'curriculum','previous_teaching','exposure'}}
        for k in ['core_atoms','related_atoms','future_atoms']:
            scope[k]=([v for v in scope[k] if v.casefold() in message.casefold()]+[v for v in scope[k] if v.casefold() not in message.casefold()])[:12]
        action=ATIEEngine().decide(state,knowledge,scope,message,mode='assistant')
        all_atoms=[a for a in self.store.knowledge_state(user,cid)['atoms'] if a['unlocked'] and a.get('quality_status')!='deprecated']
        target=[a for a in all_atoms if a['id']==aid] if aid else [a for a in all_atoms if a['title'].casefold() in message.casefold()]
        if not target:target=[a for a in all_atoms if a['section']==ordinal][:3]
        target=target[:3];ids={a['id'] for a in target}
        edges=(self.store.graph(user,cid) or {}).get('edges',[])
        prereqs={e['from'] for e in edges if e['type']=='prerequisite' and e['to'] in ids}
        selected=target+[a for a in all_atoms if a['id'] in prereqs and a['id'] not in ids][:3];ids={a['id'] for a in selected}
        def brief(a):
            s=a.get('knowledge_state') or {}
            return {'id':a['id'],'title':a['title'],'summary':a['summary'][:600],'type':a['type'],'section':a['section'],
                    'knowledge_state':{k:s.get(k) for k in ['state','mastery','confidence','understanding','application','transfer','graded_evidence_count']}}
        with self.store.connect() as db:
            conflicts=[{'source_a':r['source_a'],'source_b':r['source_b'],'conflict':r['content_json'][:700],'teaching_expression':r['teaching_expression'][:400],'user_confirmed':bool(r['confirmed'])} for r in db.execute('SELECT * FROM source_conflicts WHERE course_id=? ORDER BY created_at DESC LIMIT 2',(cid,))]
            recent=[dict(r) for r in db.execute('SELECT kind,atom_id,created_at FROM learning_events WHERE course_id=? ORDER BY id DESC LIMIT 3',(cid,))]
            misconceptions=[{'atom_id':r['atom_id'],'description':r['description'][:250],'status':r['status']} for r in db.execute('SELECT * FROM learning_misconceptions WHERE user_id=? AND course_id=? ORDER BY last_detected_at DESC LIMIT 20',(user,cid)) if r['atom_id'] in ids][:4]
            memories=[{'type':r['memory_type'],'content':r['content'],'source':'user_quote'} for r in db.execute('SELECT * FROM tutor_memories WHERE user_id=? AND course_id=? AND active=1 ORDER BY id DESC LIMIT 20',(user,cid)) if r['atom_id'] in (None,'',*ids)][:4]
            dialogue=[json.loads(r['payload_json'])|{'role':r['role'],'content':r['content'][:600]} for r in db.execute('SELECT m.* FROM tutor_messages m JOIN tutor_conversations c ON c.id=m.conversation_id WHERE c.user_id=? AND c.course_id=? AND m.section_id=? AND (m.atom_id IS NULL OR m.atom_id=?) ORDER BY m.id DESC LIMIT 6',(user,cid,section['id'],aid))]
            study=db.execute("SELECT id,goal_id,growth_task_id,title,activity_type,status,planned_minutes FROM study_sessions WHERE user_id=? AND course_id=? AND status IN ('active','paused','interrupted') ORDER BY started_at DESC LIMIT 1",(user,cid)).fetchone()
            study=dict(study) if study else None;growth_task=None;goal=None
            if study and study['growth_task_id']:
                t=db.execute('SELECT id,title,goal_id,status,reason_code FROM growth_tasks WHERE id=? AND user_id=?',(study['growth_task_id'],user)).fetchone()
                if t:growth_task=dict(t)
            if not growth_task:
                t=db.execute("SELECT t.id,t.title,t.goal_id,t.status,t.reason_code FROM growth_tasks t JOIN learning_goals g ON g.id=t.goal_id JOIN growth_roadmaps r ON r.id=t.roadmap_id WHERE t.user_id=? AND g.user_id=? AND r.user_id=? AND (t.target_id=? OR json_extract(t.metadata_json,'$.linked_course_id')=?) AND t.status='active' AND g.status='active' AND r.status='active' ORDER BY t.updated_at DESC LIMIT 1",(user,user,user,cid,cid)).fetchone()
                if t:growth_task=dict(t)
            if growth_task:
                g=db.execute('SELECT id,title,target_level FROM learning_goals WHERE id=? AND user_id=?',(growth_task['goal_id'],user)).fetchone()
                if g:goal=dict(g)
            pending=[q for r in db.execute('SELECT questions_json FROM quizzes WHERE course_id=? AND section_id=? AND submitted_at IS NULL ORDER BY rowid DESC LIMIT 1',(cid,section['id'])) for q in json.loads(r[0])][:3]
        # Only relevant messages, not their entire stored response metadata/search/history.
        history=[{k:m.get(k) for k in ['role','content','strategy']} for m in reversed(dialogue)]
        atom=next((a for a in target if a['id']==aid),None)
        current={'section_id':section['id'],'section_ordinal':ordinal,'section_title':section['title'],'knowledge_atom_id':aid,'knowledge_title':atom['title'] if atom else None,'authentic_task_id':task['id'] if task else None}
        from ..learning.growth import GrowthService
        goal_hint=GrowthService(self.store).context(user,cid,list(ids)) or GrowthService(self.store).context(user,cid)
        context={'growth_context':goal_hint,'today':datetime.now(ZoneInfo('Asia/Shanghai')).date().isoformat(),'course':{k:course[k] for k in ['id','title','goal','learner_level','source_policy','content_revision']},
            'current_context':current,'source_conflicts':conflicts,'current_content':(section['lesson'] or '')[:1600] if not section['lesson_stale'] else '',
            'knowledge_atoms':[brief(a) for a in selected], 'knowledge_relations':[e for e in edges if e['from'] in ids and e['to'] in ids][:8],
            'user_state':{'cognitive_state':state['cognitive_state'],'preferences':state['preferences'],'relevant_personal_prior':state.get('relevant_personal_prior',[])[:3]},
            'misconceptions':misconceptions,'recent_learning':[r for r in recent if r['atom_id'] in ids],'teaching_context':scope,'recent_dialogue':history,
            'memories':memories,'growth_task':growth_task,'learning_goal':goal,'study_session':study,'assessment_mode':mode,
            'pending_questions':[{k:q[k] for k in ['prompt','choices','atom_ids'] if k in q} for q in pending],
            'authentic_task':{'prompt':task['prompt'][:1600],'task_type':task['task_type']} if task else None}
        # Enforce one total ceiling even for very large user-authored course titles/goals.
        for k in ['title','goal','learner_level']:context['course'][k]=str(context['course'][k])[:600]
        action={k:v for k,v in action.items() if k not in {'relevant_personal_prior','presentation_policy'}}
        action['core_atoms']=scope['core_atoms'];action['related_atoms']=scope['related_atoms'];action['forbidden_topics']=scope['future_atoms']
        return course,context,action
