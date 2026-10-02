"""Course metadata, ordering, recycle bin and independent structural copies."""
from __future__ import annotations
import json
import secrets
from datetime import datetime, timezone
from urllib.parse import urlsplit

STATUSES={'active','paused','completed','archived'}
LEVELS={'入门','基础','进阶','高级'}

def stamp():return datetime.now(timezone.utc).isoformat(timespec='seconds')

def validate_fields(payload):
    if not isinstance(payload,dict):raise ValueError('课程信息格式无效')
    result={}
    if 'name' in payload and 'title' not in payload:payload={**payload,'title':payload['name']}
    for key,limit in [('title',100),('description',1000),('goal',500),('cover',1000)]:
        if key not in payload:continue
        value=payload[key]
        if not isinstance(value,str) or len(value.strip())>limit or any(ord(c)<32 and c not in '\n\t' for c in value):raise ValueError('课程名称、简介、目标或封面格式无效')
        if key=='title' and not value.strip():raise ValueError('请填写课程名称')
        if key=='cover' and value:
            url=urlsplit(value)
            if url.scheme!='https' or not url.hostname or url.username or url.password:raise ValueError('封面请填写 HTTPS 图片地址，或留空')
        result[key]=value.strip()
    for key,choices in [('status',STATUSES),('level',LEVELS)]:
        if key in payload:
            if not isinstance(payload[key],str) or payload[key] not in choices:raise ValueError('课程状态或难度无效')
            result[key]=payload[key]
    if 'tags' in payload:
        tags=payload['tags']
        if not isinstance(tags,list) or len(tags)>10 or any(not isinstance(t,str) or not 1<=len(t.strip())<=30 for t in tags):raise ValueError('标签最多10个，每个1—30字')
        result['tags_json']=json.dumps(list(dict.fromkeys(t.strip() for t in tags)),ensure_ascii=False)
    return result


def migrate_courses(db):
    columns={r[1] for r in db.execute('PRAGMA table_info(courses)')}
    additions={'description':"TEXT NOT NULL DEFAULT ''",'cover':"TEXT NOT NULL DEFAULT ''",
               'tags_json':"TEXT NOT NULL DEFAULT '[]'",'status':"TEXT NOT NULL DEFAULT 'active'",
               'sort_order':"INTEGER NOT NULL DEFAULT 0",'level':"TEXT NOT NULL DEFAULT '入门'",
               'updated_at':"TEXT NOT NULL DEFAULT ''",'deleted_at':'TEXT'}
    for name,definition in additions.items():
        if name not in columns:db.execute(f'ALTER TABLE courses ADD COLUMN {name} {definition}')
    if 'sort_order' not in columns:
        rows=db.execute('SELECT id,session_id FROM courses ORDER BY created_at DESC,id DESC').fetchall();positions={}
        for row in rows:
            positions[row['session_id']]=positions.get(row['session_id'],0)+1
            db.execute('UPDATE courses SET sort_order=? WHERE id=?',(positions[row['session_id']],row['id']))
    db.execute("UPDATE courses SET updated_at=created_at WHERE updated_at=''")


class CourseManagementStorage:
    def _manage_owned(self,db,session,cid,deleted=False):
        row=db.execute('SELECT * FROM courses WHERE id=? AND session_id=?',(cid,session)).fetchone()
        if not row or (row['deleted_at'] and not deleted):raise ValueError('课程不存在或已进入回收站')
        return dict(row)

    @staticmethod
    def _idle_course(db,cid):
        if db.execute("SELECT 1 FROM discovery_runs WHERE course_id=? AND status='running'",(cid,)).fetchone():raise ValueError('课程正在自动发现资料，请完成后再编辑、复制或删除')

    def _course_card(self,db,row):
        value=dict(row);value.pop('session_id',None)
        value['name']=value['title'];value['tags']=json.loads(value.pop('tags_json'))
        sections=db.execute('SELECT id,ordinal FROM sections WHERE course_id=?',(value['id'],)).fetchall()
        graph=db.execute('SELECT graph_json FROM course_graphs WHERE course_id=?',(value['id'],)).fetchone()
        atoms=json.loads(graph[0])['atoms'] if graph else []
        atoms=[a for a in atoms if a.get('quality_status')!='deprecated']
        value['knowledge_count']=len(atoms);value['section_count']=len(sections)
        done={s['ordinal'] for s in sections if s['ordinal']<value['current_ordinal']}
        submitted={r[0] for r in db.execute("SELECT section_id FROM quizzes WHERE course_id=? AND scope='section' AND submitted_at IS NOT NULL",(value['id'],))}
        done.update(s['ordinal'] for s in sections if s['id'] in submitted)
        read={r[0] for r in db.execute("SELECT atom_id FROM learning_events WHERE course_id=? AND kind IN ('read','review')",(value['id'],))}
        for s in sections:
            ids={a['id'] for a in atoms if a['section']==s['ordinal']}
            if ids and ids<=read:done.add(s['ordinal'])
        value['progress']=round(len(done)/len(sections)*100) if sections else 0
        value['progress_note']='按已进入后续小节、完成章节小测或读完本节全部知识点计算；不代表掌握率'
        times=[]
        for table,column in [('tutor_turns','created_at'),('atom_turns','created_at'),('atom_content','created_at'),('learning_events','created_at'),('quizzes','submitted_at')]:
            time=db.execute(f'SELECT MAX({column}) FROM {table} WHERE course_id=?',(value['id'],)).fetchone()[0]
            if time:times.append(time)
        value['last_study_at']=max(times) if times else None
        return value

    def managed_courses(self,session,status=None,deleted=False):
        if status is not None and status not in STATUSES:raise ValueError('课程状态无效')
        with self.connect() as db:
            rows=db.execute('SELECT * FROM courses WHERE session_id=? AND deleted_at IS '+('NOT NULL' if deleted else 'NULL')+' ORDER BY sort_order,created_at,id',(session,)).fetchall()
            return [self._course_card(db,r) for r in rows if status is None or r['status']==status]

    def managed_course(self,session,cid):
        with self.connect() as db:return self._course_card(db,self._manage_owned(db,session,cid,True))

    def update_course(self,session,cid,payload):
        fields=validate_fields(payload)
        if not fields:raise ValueError('没有可更新的课程信息')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE');old=self._manage_owned(db,session,cid);self._idle_course(db,cid)
            if any(k in fields and fields[k]!=old[k] for k in ('goal','level')):
                from .revisions import bump_revision
                bump_revision(db,cid)
                if 'level' in fields and fields['level']!=old['level']:
                    difficulty={'入门':'beginner','基础':'basic','进阶':'intermediate','高级':'advanced'}[fields['level']]
                    db.execute('UPDATE sections SET difficulty=? WHERE course_id=?',(difficulty,cid))
            fields['updated_at']=stamp()
            db.execute('UPDATE courses SET '+','.join(k+'=?' for k in fields)+' WHERE id=?',(*fields.values(),cid))
        return self.managed_course(session,cid)

    def order_courses(self,session,entries):
        if not isinstance(entries,list):raise ValueError('排序需提交课程列表')
        ids=[];orders=[]
        for item in entries:
            if not isinstance(item,dict) or not isinstance(item.get('id'),str) or type(item.get('sort_order')) is not int or item['sort_order']<0:raise ValueError('课程排序格式无效')
            ids.append(item['id']);orders.append(item['sort_order'])
        if len(set(ids))!=len(ids) or len(set(orders))!=len(orders):raise ValueError('课程或排序位置不能重复')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            expected={r[0] for r in db.execute('SELECT id FROM courses WHERE session_id=? AND deleted_at IS NULL',(session,))}
            if set(ids)!=expected:raise ValueError('课程列表已变化，请刷新后重新排序')
            db.executemany('UPDATE courses SET sort_order=?,updated_at=? WHERE id=? AND session_id=?',[(o,stamp(),i,session) for i,o in zip(ids,orders)])
        return self.managed_courses(session)

    def recycle_course(self,session,cid):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE');row=self._manage_owned(db,session,cid,True);self._idle_course(db,cid)
            if not row['deleted_at']:db.execute('UPDATE courses SET deleted_at=?,updated_at=? WHERE id=?',(stamp(),stamp(),cid))
        return self.managed_course(session,cid)

    def restore_course(self,session,cid):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE');row=self._manage_owned(db,session,cid,True)
            if not row['deleted_at']:raise ValueError('该课程不在回收站')
            order=db.execute('SELECT COALESCE(MAX(sort_order),0)+1 FROM courses WHERE session_id=? AND deleted_at IS NULL',(session,)).fetchone()[0]
            db.execute('UPDATE courses SET deleted_at=NULL,sort_order=?,updated_at=? WHERE id=?',(order,stamp(),cid))
        return self.managed_course(session,cid)

    def purge_course(self,session,cid,confirm_title):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE');row=self._manage_owned(db,session,cid,True);self._idle_course(db,cid)
            if not row['deleted_at']:raise ValueError('请先将课程移入回收站')
            if confirm_title!=row['title']:raise ValueError('请填写完整课程名称确认永久删除')
            drafts=[r[0] for r in db.execute('SELECT id FROM course_drafts WHERE confirmed_course_id=?',(cid,))]
            for draft in drafts:db.execute('DELETE FROM draft_documents WHERE draft_id=?',(draft,))
            db.execute('DELETE FROM course_drafts WHERE confirmed_course_id=?',(cid,))
            for table in ['loop_events','knowledge_state_history','learning_misconceptions','knowledge_states','learning_evidence','repair_sessions','returning_sessions','loop_activity','content_history','teaching_actions','teaching_feedback','teaching_preferences','lesson_teaching_records','assistant_message','assistant_position','production_batches','source_conflicts','discovery_runs','course_graphs','atom_content','atom_turns','learning_events','quizzes','tutor_turns','sections','source_documents']:
                db.execute(f'DELETE FROM {table} WHERE course_id=?',(cid,))
            db.execute('DELETE FROM courses WHERE id=? AND session_id=?',(cid,session))

    def copy_course(self,session,cid,title=None):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE');row=self._manage_owned(db,session,cid);self._idle_course(db,cid)
            fields=validate_fields({'title':title if title is not None else row['title'][:96]+'（副本）'})
            new=secrets.token_urlsafe(16);time=stamp()
            order=db.execute('SELECT COALESCE(MAX(sort_order),0)+1 FROM courses WHERE session_id=? AND deleted_at IS NULL',(session,)).fetchone()[0]
            db.execute('INSERT INTO courses(id,session_id,title,goal,current_ordinal,created_at,source_policy,learner_level,search_mode,description,cover,tags_json,status,sort_order,level,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                       (new,session,fields['title'],row['goal'],1,time,row['source_policy'],row['learner_level'],row['search_mode'],row['description'],row['cover'],row['tags_json'],'active',order,row['level'],time))
            for section in db.execute('SELECT * FROM sections WHERE course_id=? ORDER BY ordinal',(cid,)).fetchall():
                db.execute('INSERT INTO sections(id,course_id,ordinal,title,objective,lesson,created_at,purpose,core_atoms,related_atoms,future_atoms,difficulty,teaching_depth) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
                           (secrets.token_urlsafe(16),new,section['ordinal'],section['title'],section['objective'],None,time,
                            *[section[k] for k in ('purpose','core_atoms','related_atoms','future_atoms','difficulty','teaching_depth')]))
            sources=db.execute('SELECT * FROM source_documents WHERE course_id=?',(cid,)).fetchall()
            mapping={s['id']:secrets.token_urlsafe(16) for s in sources}
            def remap(value):
                if isinstance(value,str):return mapping.get(value,value)
                if isinstance(value,list):return [remap(v) for v in value]
                if isinstance(value,dict):return {k:remap(v) for k,v in value.items()}
                return value
            for source in sources:
                metadata=remap(json.loads(source['metadata_json']));metadata.pop('discovery',None)
                db.execute('INSERT INTO source_documents VALUES(?,?,?,?,?,?,?,?,?)',(mapping[source['id']],new,source['title'],source['source_type'],source['origin'],source['content'],json.dumps(metadata,ensure_ascii=False),time,'ready'))
            graph=db.execute('SELECT graph_json FROM course_graphs WHERE course_id=?',(cid,)).fetchone()
            if graph:
                structure=remap(json.loads(graph[0]))
                for atom in structure['atoms']:
                    if atom.get('quality_status')!='deprecated':atom['quality_status']='candidate'
                    atom.pop('quality_review',None)
                db.execute('INSERT INTO course_graphs VALUES(?,?,?)',(new,json.dumps(structure,ensure_ascii=False),time))
            for conflict in db.execute('SELECT * FROM source_conflicts WHERE course_id=?',(cid,)).fetchall():
                db.execute('INSERT INTO source_conflicts VALUES(?,?,?,?,?,?,0,?,NULL)',(secrets.token_urlsafe(16),new,mapping[conflict['source_a']],mapping[conflict['source_b']],json.dumps(remap(json.loads(conflict['content_json'])),ensure_ascii=False),conflict['teaching_expression'],time))
        return self.course(session,new)
