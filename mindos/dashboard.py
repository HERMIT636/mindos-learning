"""Read-only cockpit projections. Recommendations never unlock chapters or alter evidence."""
from .adaptive.teaching_state import LearningStateManager


class DashboardService:
    def __init__(self,store):self.store=store

    def read(self,user,course_id=None):
        courses=self.store.managed_courses(user)
        if course_id is not None and not any(c['id']==course_id for c in courses):raise ValueError('课程不存在')
        active=[c for c in courses if c['status']=='active']
        selected=next((c for c in courses if c['id']==course_id),None) if course_id else max(active,key=lambda c:(bool(c['last_study_at']),c['last_study_at'] or '',-c['sort_order']),default=None)
        state=None;recommendations=[];current=None
        if selected:
            cid=selected['id'];course=self.store.course(user,cid);section=course['sections'][course['current_ordinal']-1]
            state,_=LearningStateManager(self.store).read(user,cid,section['ordinal'])
            knowledge=self.store.knowledge_state(user,cid)
            current={'course_id':cid,'course_title':course['title'],'section_ordinal':section['ordinal'],'section_title':section['title'],'section_count':len(course['sections']),'progress':selected['progress'],'goal':course['goal']}
            recommendations=[{**r,'course_id':cid,'source':'knowledge_state_rules'} for r in knowledge['queue'][:3]]
            if not recommendations:recommendations=[{'course_id':cid,'title':section['title'],'reason':'当前小节尚未生成讲解，先建立基础。' if not section['lesson'] else '继续当前小节；独立小测后再判断需要补强的内容。','source':'course_state','atom_id':None}]
        timeline=self.timeline(user,course_id)
        return {'courses':courses,'current':current,'learning_state':state,'recommendations':recommendations,'timeline':timeline,
                'boundary':'能力维度只统计当前课程近期独立题目表现；不是能力认证，不跨课程合并学习记忆。迁移能力尚无独立测量。建议来自已有课程与复习规则，不是新调用模型生成的推荐。'}

    def timeline(self,user,cid=None):
        events=[]
        queries=[('lesson',"SELECT t.id,c.id AS course_id,c.title AS course_title,s.title AS section_title,t.created_time AS at FROM lesson_teaching_records t JOIN courses c ON c.id=t.course_id JOIN sections s ON s.id=t.lesson_id"),
                 ('quiz',"SELECT t.id,c.id AS course_id,c.title AS course_title,s.title AS section_title,t.submitted_at AS at,t.score,t.questions_json,t.scope FROM quizzes t JOIN courses c ON c.id=t.course_id JOIN sections s ON s.id=t.section_id"),
                 ('reading',"SELECT t.id,c.id AS course_id,c.title AS course_title,'' AS section_title,t.created_at AS at,t.kind FROM learning_events t JOIN courses c ON c.id=t.course_id"),
                 ('tutor',"SELECT t.id,c.id AS course_id,c.title AS course_title,'' AS section_title,t.created_time AS at FROM assistant_message t JOIN courses c ON c.id=t.course_id")]
        with self.store.connect() as db:
            for kind,sql in queries:
                where=" WHERE c.session_id=? AND c.deleted_at IS NULL";args=[user]
                if cid:where+=' AND c.id=?';args.append(cid)
                if kind=='quiz':where+=' AND t.submitted_at IS NOT NULL'
                if kind=='tutor':where+=" AND t.role='user'"
                rows=db.execute(sql+where+' ORDER BY at DESC,t.id DESC LIMIT 36',args).fetchall()
                for row in rows:
                    item=dict(row);item['kind']=kind;item['id']=f"{kind}:{item['id']}"
                    if kind=='quiz':
                        import json
                        item['question_count']=len(json.loads(item.pop('questions_json')))
                    events.append(item)
        return sorted(events,key=lambda e:(e['at'],e['id']),reverse=True)[:36]
