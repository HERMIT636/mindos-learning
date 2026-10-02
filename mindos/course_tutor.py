"""Independent course assistant: read-only learning context, optional search and own history."""
from __future__ import annotations
import json
import math
import re
import secrets
from datetime import datetime, timezone, timedelta
from urllib.parse import urlsplit
from .discovery import teaching_blocks
from .search_planning import normalize_queries
from .model import ModelUnavailable
from .adaptive.content_generator import ContentGenerator, flatten_blocks

SCHEMA='''
CREATE TABLE IF NOT EXISTS assistant_message (
 id INTEGER PRIMARY KEY, user_id TEXT NOT NULL, course_id TEXT NOT NULL REFERENCES courses(id),
 role TEXT NOT NULL CHECK(role IN ('user','assistant')), content TEXT NOT NULL,
 knowledge_atom_id TEXT, created_time TEXT NOT NULL, exchange_id TEXT NOT NULL,
 context_json TEXT NOT NULL, related_json TEXT NOT NULL, search_json TEXT NOT NULL,
 UNIQUE(user_id,course_id,exchange_id,role)
);
CREATE INDEX IF NOT EXISTS assistant_history ON assistant_message(user_id,course_id,id);
CREATE TABLE IF NOT EXISTS assistant_position (
 id TEXT PRIMARY KEY, user_id TEXT NOT NULL, course_id TEXT NOT NULL REFERENCES courses(id),
 position_x INTEGER NOT NULL, position_y INTEGER NOT NULL, updated_time TEXT NOT NULL,
 UNIQUE(user_id,course_id)
);
'''

def stamp():return datetime.now(timezone.utc).isoformat(timespec='seconds')

def public_message(row):
    value=dict(row)
    for key in ['context','related','search']:value[key if key!='related' else 'related_knowledge']=json.loads(value.pop(key+'_json'))
    value['blocks']=json.loads(value.pop('blocks_json','[]'));value['teaching_action']=json.loads(value.pop('action_json','{}'))
    value.pop('user_id',None);return value

class CourseTutorStorage:
    def assistant_history(self,session,cid,before=None):
        self._knowledge_course(session,cid)
        if before is not None and (type(before) is not int or before<1):raise ValueError('历史记录页码无效')
        with self.connect() as db:
            rows=db.execute('SELECT * FROM assistant_message WHERE user_id=? AND course_id=?'+(' AND id<?' if before else '')+' ORDER BY id DESC LIMIT 81',
                            (session,cid,before) if before else (session,cid)).fetchall()
            position=db.execute('SELECT position_x,position_y,updated_time FROM assistant_position WHERE user_id=? AND course_id=?',(session,cid)).fetchone()
        return {'messages':[public_message(r) for r in reversed(rows[:80])],'has_more':len(rows)>80,
                'position':({'x':position['position_x'],'y':position['position_y'],'updated_time':position['updated_time']} if position else None)}

    def assistant_exchange(self,session,cid,exchange_id):
        self._knowledge_course(session,cid)
        with self.connect() as db:
            rows=db.execute('SELECT * FROM assistant_message WHERE user_id=? AND course_id=? AND exchange_id=? ORDER BY id',(session,cid,exchange_id)).fetchall()
        return [public_message(r) for r in rows]

    def save_assistant_exchange(self,session,cid,exchange_id,question,answer,atom_id,context,related,search,teaching_package=None):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE');self._manage_owned(db,session,cid)
            old=db.execute('SELECT * FROM assistant_message WHERE user_id=? AND course_id=? AND exchange_id=? ORDER BY id',(session,cid,exchange_id)).fetchall()
            if old:
                if old[0]['content']!=question:raise ValueError('重复请求编号对应了不同问题')
                return [public_message(r) for r in old]
            for role,content in [('user',question),('assistant',answer)]:
                db.execute('INSERT INTO assistant_message(user_id,course_id,role,content,knowledge_atom_id,created_time,exchange_id,context_json,related_json,search_json) VALUES(?,?,?,?,?,?,?,?,?,?)',
                           (session,cid,role,content,atom_id,stamp(),exchange_id,json.dumps(context,ensure_ascii=False),json.dumps(related if role=='assistant' else [],ensure_ascii=False),json.dumps(search if role=='assistant' else {},ensure_ascii=False)))
                if role=='assistant' and teaching_package:
                    db.execute('UPDATE assistant_message SET blocks_json=?,action_json=? WHERE id=last_insert_rowid()',
                               (json.dumps(teaching_package['blocks'],ensure_ascii=False),json.dumps(teaching_package['teaching_action'],ensure_ascii=False)))
                    self.record_teaching_action(db,session,cid,context['section_id'],atom_id,teaching_package)
            from .learning.service import LearningLoopService
            from .learning.evidence import mark_help
            if context.get('authentic_task_id'):
                task=db.execute("SELECT status FROM authentic_tasks WHERE id=? AND user_id=? AND course_id=?",(context['authentic_task_id'],session,cid)).fetchone()
                if not task or task[0]!='created':raise ValueError('开放任务已提交或暂缓，请刷新')
                db.execute('UPDATE authentic_tasks SET hint_used=1 WHERE id=?',(context['authentic_task_id'],))
            else:
                mark_help(db,cid,context.get('section_id'),atom_id)
                LearningLoopService(self).signal(db,session,cid,context.get('section_id'),[atom_id] if atom_id else [],'tutor_interaction','assistant:'+exchange_id)
        return self.assistant_exchange(session,cid,exchange_id)

    def save_assistant_position(self,session,cid,x,y):
        for value in [x,y]:
            if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or not 0<=value<=100000:raise ValueError('助手位置无效')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE');self._manage_owned(db,session,cid)
            db.execute('INSERT INTO assistant_position VALUES(?,?,?,?,?,?) ON CONFLICT(user_id,course_id) DO UPDATE SET position_x=excluded.position_x,position_y=excluded.position_y,updated_time=excluded.updated_time',
                       (secrets.token_urlsafe(16),session,cid,round(x),round(y),stamp()))
        return {'x':round(x),'y':round(y)}


DYNAMIC=re.compile(r'最新|近期|新闻|版本|发布|更新|API.*(?:变化|接口)|20[2-9][0-9]|\b(?:latest|recent|version|release|news)\b',re.I)
class CourseTutorService:
    def __init__(self,store):self.store=store;self.generator=ContentGenerator(store)

    def context(self,session,cid,current,message):
        course=self.store._knowledge_course(session,cid)
        if not isinstance(current,dict):raise ValueError('当前学习上下文格式无效')
        task_id=current.get('authentic_task_id')
        if task_id:
            from .learning.authentic import AuthenticAssessmentService
            task=AuthenticAssessmentService(self.store).get(session,cid,task_id)['task']
            if task['status']!='created':raise ValueError('开放任务当前不可求助')
            atom=self.store.atom(session,cid,task['atom_id'],unlocked=True);section=course['sections'][atom['section']-1]
            from .teaching import TeachingOrchestrator
            context={'today':stamp()[:10],'course':{k:course[k] for k in ['id','title','goal','learner_level','level','source_policy','content_revision']},
                'current_context':{'section_ordinal':atom['section'],'section_title':section['title'],'knowledge_atom_id':atom['id'],'knowledge_title':atom['title'],'authentic_task_id':task_id},
                'assessment_mode':'authentic','authentic_task':{'id':task_id,'task_type':task['task_type'],'prompt':task['prompt'],'guidance':'默认帮助理解任务并提出引导问题；仅用户明确要求直接答案时可以解答。所有求助都留下提示标记，本次任务不用于校准。'},
                'knowledge_atoms':[atom],'knowledge_relations':[],'pending_quiz_questions':[], 'teaching_context':TeachingOrchestrator(self.store).context(session,cid,section['id'])}
            # Mark before the model call; failed help requests cannot erase independence.
            AuthenticAssessmentService(self.store).hint(session,cid,task_id)
            return course,context,[atom]
        from .learning.final import FinalAssessmentService
        final=FinalAssessmentService(self.store).status(session,cid)
        final_quiz=final['current_quiz'] if final['plan'] and final['plan']['status']=='active' and not final['plan']['stale'] else None
        if final_quiz:
            target=self.store.atom(session,cid,final_quiz['item']['atom_id'],unlocked=True)
            current={**current,'section_ordinal':target['section'],'knowledge_atom_id':target['id']}
        ordinal=current.get('section_ordinal',course['current_ordinal'])
        if type(ordinal) is not int or not 1<=ordinal<=course['current_ordinal']:raise ValueError('当前小节尚未开放')
        section=course['sections'][ordinal-1];atom_id=current.get('knowledge_atom_id');atom=None
        if atom_id is not None:
            if not isinstance(atom_id,str):raise ValueError('当前知识点格式无效')
            atom=self.store.atom(session,cid,atom_id,unlocked=True)
            if atom['section']!=ordinal:raise ValueError('当前知识点与小节不一致')
        mode=current.get('atom_mode','quick')
        if mode not in ('quick','deep'):raise ValueError('知识点阅读方式无效')
        learning=self.store.knowledge_state(session,cid)
        atoms=[a for a in learning['atoms'] if a['unlocked'] and a.get('quality_status')!='deprecated']
        graph=self.store.graph(session,cid) or {'atoms':[],'edges':[]}
        selected=[a for a in atoms if a['id']==atom_id or a['section']==ordinal or a['title'].casefold() in message.casefold()][:16]
        ids={a['id'] for a in selected}
        related_edges=[e for e in graph['edges'] if e['from'] in ids or e['to'] in ids]
        prerequisite_ids={e['from'] for e in related_edges if e['type']=='prerequisite'}
        selected+= [a for a in atoms if a['id'] in prerequisite_ids and a['id'] not in ids][:8]
        available_ids={a['id'] for a in atoms}
        from .context import course_materials
        materials=course_materials(self.store,session,course,section['title'])
        atom_content=self.store.atom_detail(session,cid,atom_id)['content'].get(mode,'') if atom_id else ''
        with self.store.connect() as db:
            recent=[dict(r) for r in db.execute('SELECT kind,atom_id,created_at FROM learning_events WHERE course_id=? ORDER BY id DESC LIMIT 12',(cid,))]
            recent_content=[dict(r) for r in db.execute('SELECT role,substr(content,1,1500) AS content,created_at FROM tutor_turns WHERE course_id=? ORDER BY id DESC LIMIT 6',(cid,))]
            pending=[json.loads(r[0]) for r in db.execute('SELECT questions_json FROM quizzes WHERE course_id=? AND section_id=? AND submitted_at IS NULL ORDER BY rowid DESC LIMIT 1',(cid,section['id']))]
        pending=[[{k:q[k] for k in ('prompt','choices','atom_ids') if k in q} for q in questions if isinstance(q,dict)] for questions in pending]
        context={'today':datetime.now(timezone(timedelta(hours=8))).date().isoformat(),
                 'course':{k:course[k] for k in ['id','title','goal','learner_level','level','source_policy','content_revision']},
                 'current_context':{'section_ordinal':ordinal,'section_title':section['title'],'section_objective':section['objective'],
                                    'knowledge_atom_id':atom_id,'knowledge_title':atom['title'] if atom else None,
                                    'page_content':{'chapter_lesson_stale':section['lesson_stale'],'basis_revision':section['lesson_revision'],'chapter_lesson':(section['lesson'] or '')[:10000],'atom_explanation':atom_content[:6000]}},
                 'sections':[{'ordinal':s['ordinal'],'title':s['title'],'objective':s['objective'],'unlocked':s['ordinal']<=course['current_ordinal']} for s in course['sections']],
                 'knowledge_atoms':selected,'knowledge_relations':[e for e in related_edges if e['from'] in available_ids and e['to'] in available_ids],
                 'learner_state':{'mastery':self.store.mastery(session,cid),'read_knowledge':[a['title'] for a in atoms if a['read']],
                                  'mastered_knowledge':[a['title'] for a in atoms if (a.get('knowledge_state') or {}).get('state')=='mastered'],
                                  'weak_knowledge':[a['title'] for a in atoms if a['rate'] is not None and a['rate']<60],
                                  'recent_learning_events':recent,'recent_learning_content':recent_content,'rule':'阅读和聊天不是掌握证据；正确率只来自独立测试'},
                 'course_materials':materials,'source_conflicts':self.store.conflicts(session,cid),
                 'pending_quiz_questions':pending, 'learning_loop':learning.get('learning_loop',{})}
        if final_quiz:
            context['assessment_mode']='final'
            context['pending_quiz_questions']=[final_quiz['questions']]
            context['final_assessment']={'dimension':final_quiz['item']['dimension'],'course_state':final['mastery_state'],'guidance':'先引导独立思考，只给方向或问题；只有用户明确要求标准答案才可以直接解答。任何求助均保存 hint_used，不作为独立终局证据。'}
        from .teaching import TeachingOrchestrator
        context['teaching_context'] = TeachingOrchestrator(self.store).context(session,cid,section['id'])
        from .learning.personal import InheritedKnowledgePrior
        from .learning.growth import GrowthService
        context['growth_context']=GrowthService(self.store).context(session,cid,ids)
        context['relevant_personal_prior']=InheritedKnowledgePrior(self.store).relevant(session,cid,ids)
        return course,context,atoms

    def chat(self,session,cid,payload,model,search_factory):
        question=payload.get('message')
        if not isinstance(question,str) or not 1<=len(question.strip())<=2000:raise ValueError('问题请填写1—2000字')
        question=question.strip();exchange_id=payload.get('request_id') or secrets.token_urlsafe(16)
        if not isinstance(exchange_id,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}',exchange_id):raise ValueError('问题请求编号无效')
        old=self.store.assistant_exchange(session,cid,exchange_id)
        if old:
            if old[0]['content']!=question:raise ValueError('重复请求编号对应了不同问题')
            return self._response(old)
        course,context,atoms=self.context(session,cid,payload.get('current_context',{}),question)
        history=[] if context.get('assessment_mode')=='authentic' else self.store.assistant_history(session,cid)['messages'][-12:]
        route_error=None
        try:
            route=model.plan_course_tutor(context,question,[{'id':a['id'],'title':a['title'],'section':a['section']} for a in atoms])
            if not isinstance(route,dict) or type(route.get('need_search')) is not bool:raise ModelUnavailable('助教回答规划格式无效')
        except Exception as exc:
            route_error=str(exc);route={'need_search':bool(DYNAMIC.search(question)),'strategy':'先建立直觉，再解释原因与当前课程联系','queries':[],'related_atom_ids':[]}
        routed=route.get('related_atom_ids',[])
        if not isinstance(routed,list):routed=[]
        selected_ids={a['id'] for a in context['knowledge_atoms']}
        context['knowledge_atoms'] += [a for a in atoms if a['id'] in routed and a['id'] not in selected_ids][:8]
        graph=self.store.graph(session,cid) or {'edges':[]}
        selected_ids={a['id'] for a in context['knowledge_atoms']};available={a['id'] for a in atoms}
        edges=[e for e in graph['edges'] if e['from'] in available and e['to'] in available and (e['from'] in selected_ids or e['to'] in selected_ids)]
        prereqs={e['from'] for e in edges if e['type']=='prerequisite'}
        context['knowledge_atoms'] += [a for a in atoms if a['id'] in prereqs and a['id'] not in selected_ids][:8]
        context['knowledge_relations']=edges
        need_search=route['need_search'] or bool(DYNAMIC.search(question))
        search={'needed':need_search,'status':'not_needed','mode':course['search_mode'],'sources':[],'note':'本次直接结合课程与模型知识回答；模型知识不等于资料核验'}
        if route_error:search['planning_warning']=route_error
        if need_search:
            queries=normalize_queries(route.get('queries'))[:3] or normalize_queries([course['title']+' '+question])
            search.update(status='failed',queries=queries)
            try:
                provider=search_factory(course['search_mode'])
                results=provider.search(queries,topic=course['title']) if course['search_mode']=='public' else provider.search(queries)
                for result in results[:8]:
                    url=result.get('url','');parsed=urlsplit(url)
                    if parsed.scheme not in ('https','http') or not parsed.hostname or parsed.username or parsed.password:continue
                    search['sources'].append({'title':str(result.get('title',''))[:180],'url':url,'description':str(result.get('description',''))[:400],'provider':result.get('provider',course['search_mode'])})
                if not search['sources']:raise ValueError('检索没有返回可用的公开来源')
                search.update(status='ok',note='检索入口：'+({'public':'免密钥 Wikipedia / GitHub','brave':'Brave / 兼容接口','tavily':'Tavily / 兼容接口'}.get(course['search_mode'],course['search_mode']))+'。以下仅为实际检索到的标题和短摘要，未阅读全文；不能据此保证最新或准确。'+('免密钥入口仅覆盖 Wikipedia 与 GitHub，不是全网搜索。' if course['search_mode']=='public' else ''))
            except Exception as exc:
                search.update(status='failed',note='联网检索未成功，无法核实当前版本或最新事实；本次只能解释稳定知识，并明确保留不确定性。',error=str(exc),sources=[])
        section=course['sections'][context['current_context']['section_ordinal']-1]
        result=self.generator.assistant(session,course,section,model,context,question,history,route,search,payload.get('feedback'),exchange_id)
        if search['status']=='failed':
            result['blocks'].insert(0,{'type':'text','content':'联网资料暂未取得，以下无法确认最新信息。'})
        answer=flatten_blocks(result['blocks'])
        requested=result.get('related_atom_ids',[])
        if not isinstance(requested,list):requested=[]
        related=[{'id':a['id'],'title':a['title'],'section':a['section']} for a in atoms if a['id'] in requested][:6]
        if not related:related=[{'id':a['id'],'title':a['title'],'section':a['section']} for a in atoms if a['id']==context['current_context']['knowledge_atom_id'] or a['title'].casefold() in question.casefold()][:4]
        current=context['current_context'];saved_context={k:current[k] for k in ['section_ordinal','section_title','knowledge_atom_id','knowledge_title']}|{'course_title':course['title'],'section_id':section['id'],'validation':result['validation']}
        if current.get('authentic_task_id'):saved_context['authentic_task_id']=current['authentic_task_id']
        messages=self.store.save_assistant_exchange(session,cid,exchange_id,question,answer,current['knowledge_atom_id'],saved_context,related,search,result)
        return self._response(messages)

    @staticmethod
    def _response(messages):
        answer=next(m for m in messages if m['role']=='assistant')
        return {'answer':answer['content'],'blocks':answer['blocks'],'teaching_action':answer['teaching_action'],'validation':answer['context'].get('validation'),'related_knowledge':answer['related_knowledge'],'search':answer['search'],'messages':messages,'request_id':answer['exchange_id']}
