"""P6 interaction layer: no second model gateway or knowledge-state writer."""
import json,re,secrets,threading
from urllib.parse import urlsplit
from .context import TutorContextBuilder
from .storage import TutorMemoryStore,social
from .strategy import TutorStrategyEngine,SocraticTutor
from .protocol import validate,ExplanationComposer
from .observations import TutorObservationService
from ..course_tutor import DYNAMIC
from ..learning.evidence import mark_help

_LOCKS=[threading.RLock() for _ in range(64)]
class TutorService:
    def __init__(self,store):self.store=store;self.memory=TutorMemoryStore(store)
    def _search(self,course,message,factory):
        result={'status':'not_needed','sources':[],'note':'本次没有联网检索。'}
        if not DYNAMIC.search(message):return result
        try:
            provider=factory(course['search_mode']);sources=provider.search([course['title'][:120]+' '+message[:200]],topic=course['title'])
            for source in sources[:4]:
                url=source.get('url','');parts=urlsplit(url)
                if parts.scheme not in {'https','http'} or not parts.hostname or parts.username or parts.password:continue
                result['sources'].append({'title':str(source.get('title',''))[:180],'url':url,'description':str(source.get('description',''))[:400],'provider':str(source.get('provider',course['search_mode']))[:100]})
            if not result['sources']:raise ValueError('no_sources')
            result.update(status='ok',note='仅使用实际检索到的标题与短摘要，未阅读全文。'+('免密钥入口覆盖 Wikipedia / GitHub，不是全网搜索。' if course['search_mode']=='public' else '检索入口：'+course['search_mode']+'。'))
        except Exception:
            result.update(status='failed',sources=[],note='联网资料暂未取得，无法确认最新信息；下面只解释稳定知识。')
        return result
    def chat(self,user,payload,model,factory):
        if not isinstance(payload,dict) or set(payload)-{'message','context_id','course_id','current_context','request_id','feedback'}:raise ValueError('导师请求字段无效')
        cid=payload.get('context_id',payload.get('course_id'))
        if not isinstance(cid,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}',cid):raise ValueError('请先选择当前课程')
        if payload.get('course_id',cid)!=cid:raise ValueError('上下文与课程不一致')
        message=payload.get('message');rid=payload.get('request_id') or secrets.token_urlsafe(16)
        if not isinstance(message,str) or not 1<=len(message.strip())<=2000:raise ValueError('请填写不超过2000字的问题')
        if not isinstance(rid,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}',rid):raise ValueError('请求编号无效')
        message=message.strip()
        with _LOCKS[hash((user,cid))%len(_LOCKS)]:
            course,context,action=TutorContextBuilder(self.store).build(user,cid,payload.get('current_context',{}),message)
            old=self.memory.exchange(user,cid,rid)
            if old:
                if old[0]['content']!=message or old[0]['context']!=context['current_context']:raise ValueError('重复请求编号对应不同问题或上下文')
                answer=old[-1];return {**answer,'answer':answer['content'],'messages':old,'request_id':rid,'saved':True,'observations':TutorObservationService(self.store).list(user,cid)['observations']}
            strategy=TutorStrategyEngine().choose(message,context,action)
            if social(message):
                return self._transient(rid,message,'你好，告诉我这门课里哪里不理解，我会结合当前小节解释。',context,action,strategy,False)
            # Preserve independence even when model generation fails. No new learning evidence.
            with self.store.connect() as db:
                db.execute('BEGIN IMMEDIATE');self.store._manage_owned(db,user,cid)
                cur=context['current_context']
                if cur.get('authentic_task_id'):
                    db.execute("UPDATE authentic_tasks SET hint_used=1 WHERE id=? AND user_id=? AND course_id=? AND status='created'",(cur['authentic_task_id'],user,cid))
                mark_help(db,cid,cur['section_id'],cur['knowledge_atom_id'])
            search=self._search(course,message,factory)
            request={'message':message,'context':context,'strategy':strategy,'teaching_action':action,'search':search,
                     'socratic_instruction':SocraticTutor.instruction(strategy) if strategy['name']=='socratic' else ''}
            if len(json.dumps(request,ensure_ascii=False))>26000:raise ValueError('当前资料摘要过长，请选择一个具体知识点提问')
            value=None;failure='';attempts=0
            for attempt in range(2):
                attempts+=1
                try:
                    raw=model.tutor_json(request,repair_reason=failure) if model else None
                    value=validate(raw,request)
                    if getattr(model,'diagnostic_path',None):model._diagnostic({'stage':'p6_tutor_answer','parsed':value})
                    break
                except Exception as exc:
                    failure=str(exc)[:500]
                    if model and hasattr(model,'_diagnostic'):model._diagnostic({'stage':'p6_tutor_validation','attempt':attempt+1,'failure_type':type(exc).__name__,'failure_code':'INVALID_OR_UNAVAILABLE_REPLY'})
            if value is None:
                return self._transient(rid,message,'这次没有取得符合要求的导师讲解。可以先回看当前小节，或把问题缩小到一个概念后再问。你的课程位置与掌握记录没有改变。',context,action,strategy,True,search,attempts)
            result={**ExplanationComposer().compose(value),'search':search,'teaching_action':action,'strategy':value['strategy'],'fallback':False,'attempts':attempts}
            if search['status']=='failed':
                result['blocks']=[{'type':'paragraph','content':search['note']},*result['blocks']];result['answer']=search['note']+'\n\n'+result['answer']
            result['related_knowledge']=[{'id':a['id'],'title':a['title'],'section':a['section']} for a in context['knowledge_atoms'] if a['id'] in value['related_atom_ids']]
            if not value['learning_relevant']:
                return self._transient(rid,message,result['answer'],context,action,strategy,False,search,attempts)
            result['messages']=self.memory.save(user,cid,rid,message,result,context,value,course['content_revision'])
            return {**result,'request_id':rid,'saved':True,'observations':TutorObservationService(self.store).list(user,cid)['observations'],'memory_note':'只保留学习相关对话；教学偏好与待验证观察独立于掌握记录。'}
    @staticmethod
    def _transient(rid,message,answer,context,action,strategy,fallback,search=None,attempts=0):
        blocks=[{'type':'paragraph','content':answer}];cur=context['current_context'];search=search or {'status':'not_needed','sources':[],'note':'本次没有联网检索。'}
        return {'answer':answer,'blocks':blocks,'strategy':strategy['name'],'teaching_action':action,'related_knowledge':[],'search':search,
                'messages':[{'id':rid+'-u','role':'user','content':message,'context':cur},{'id':rid+'-a','role':'assistant','content':answer,'blocks':blocks,'context':cur,'search':search,'strategy':strategy['name'],'fallback':fallback}],
                'request_id':rid,'saved':False,'fallback':fallback,'attempts':attempts,'observations':[],'memory_note':'这次对话不保存为学习记忆。'}
