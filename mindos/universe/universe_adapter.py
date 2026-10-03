"""Query-only consistent SQLite snapshots. Bounded graph windows, no cache rebuilds."""
import json,sqlite3
from contextlib import contextmanager
from datetime import datetime,timezone
from .universe_graph import POLICY,visual_state,star_id,decode_star,edge
from ..learning.canonical import atom_context
from ..learning.final import fingerprint

BOUNDARY='星光只映射已有学习记录；阅读、探索和聊天不证明掌握。关系来自课程图谱，历史知识档案不替代本课程检测。'

def integer(value,maximum=1000000):
    if type(value) is not int or not 0<=value<=maximum:raise ValueError('分页位置无效')
    return value

class KnowledgeUniverseAdapter:
    def __init__(self,store):self.store=store
    @contextmanager
    def read(self):
        # Separate read-only connection: an accidental INSERT cannot reach the user's DB.
        db=sqlite3.connect(self.store.path.resolve().as_uri()+'?mode=ro',uri=True,timeout=10)
        db.row_factory=sqlite3.Row
        try:
            db.execute('PRAGMA query_only=ON');db.execute('BEGIN');yield db
        finally:db.rollback();db.close()
    def owned(self,db,user,cid):
        row=db.execute('SELECT * FROM courses WHERE id=? AND session_id=? AND deleted_at IS NULL',(cid,user)).fetchone()
        if not row:raise ValueError('课程不存在或不属于当前学习空间')
        return dict(row)
    def sections(self,db,cid):
        return [dict(r) for r in db.execute('SELECT * FROM sections WHERE course_id=? ORDER BY ordinal',(cid,))]
    def progress(self,db,c):
        # The existing CourseManagement progress rules, expressed as bounded SQL reads.
        completed=db.execute('SELECT 1 FROM course_final_completion WHERE user_id=? AND course_id=? AND content_revision=?',(c['session_id'],c['id'],c['content_revision'])).fetchone()
        sections=db.execute('SELECT id,ordinal FROM sections WHERE course_id=?',(c['id'],)).fetchall();done=set()
        submitted={r[0] for r in db.execute("SELECT section_id FROM quizzes WHERE course_id=? AND scope='section' AND submitted_at IS NOT NULL",(c['id'],))}
        counts={r['ordinal']:r for r in db.execute("SELECT json_extract(a.value,'$.section') AS ordinal,COUNT(*) AS amount,SUM(EXISTS(SELECT 1 FROM learning_events e WHERE e.course_id=g.course_id AND e.atom_id=json_extract(a.value,'$.id') AND e.kind IN ('read','review'))) AS read_count FROM course_graphs g,json_each(g.graph_json,'$.atoms') a WHERE g.course_id=? AND COALESCE(json_extract(a.value,'$.quality_status'),'candidate')!='deprecated' GROUP BY json_extract(a.value,'$.section')",(c['id'],))}
        for section in sections:
            count=counts.get(section['ordinal'])
            if completed or section['ordinal']<c['current_ordinal'] or section['id'] in submitted or count and count['amount'] and count['read_count']==count['amount']:done.add(section['id'])
        return sections,done
    def galaxy(self,db,c,progress=None):
        sections,done=progress or self.progress(db,c)
        stars=db.execute("SELECT COUNT(*) FROM course_graphs g,json_each(g.graph_json,'$.atoms') a WHERE g.course_id=? AND COALESCE(json_extract(a.value,'$.quality_status'),'candidate')!='deprecated'",(c['id'],)).fetchone()[0]
        last=db.execute('SELECT MAX(created_at) FROM learning_events WHERE course_id=?',(c['id'],)).fetchone()[0]
        return {'id':'g-'+c['id'],'course_id':c['id'],'name':c['title'],'description':c['description'] or c['goal'],
                'progress':round(100*len(done)/len(sections)) if sections else 0,
                'chapter_count':len(sections),'star_count':stars,'created_at':c['created_at'],'status':c['status'],
                'current_ordinal':c['current_ordinal'],'last_learning':last,'progress_basis':'既有课程进度规则，不是掌握率'}
    def nebula(self,db,c,s,progress=None):
        amount=db.execute("SELECT COUNT(*) FROM course_graphs g,json_each(g.graph_json,'$.atoms') a WHERE g.course_id=? AND json_extract(a.value,'$.section')=? AND COALESCE(json_extract(a.value,'$.quality_status'),'candidate')!='deprecated'",(c['id'],s['ordinal'])).fetchone()[0]
        return {'id':'n-'+s['id'],'chapter_id':s['id'],'galaxy_id':'g-'+c['id'],'course_id':c['id'],'name':s['title'],
                'order':s['ordinal'],'progress':100 if s['id'] in (progress or self.progress(db,c))[1] else 0,'star_count':amount,'unlocked':s['ordinal']<=c['current_ordinal'],
                'current':s['ordinal']==c['current_ordinal'],'progress_basis':'既有课程进度规则，不是掌握率'}
    def base(self,view):
        return {'galaxies':[],'nebulae':[],'stars':[],'edges':[],'clusters':[],'view':view,'policy':POLICY,
                'boundary':BOUNDARY,'generated_at':datetime.now(timezone.utc).isoformat(),'has_more':False,'next_offset':None}
    def all(self,user,offset=0):
        integer(offset);result=self.base('galaxy')
        with self.read() as db:
            rows=[dict(r) for r in db.execute('SELECT * FROM courses WHERE session_id=? AND deleted_at IS NULL ORDER BY sort_order,created_at,id LIMIT ? OFFSET ?',(user,POLICY['max_visible_galaxies']+1,offset))]
            result['galaxies']=[self.galaxy(db,c) for c in rows[:POLICY['max_visible_galaxies']]]
            result['has_more']=len(rows)>POLICY['max_visible_galaxies'];result['next_offset']=offset+POLICY['max_visible_galaxies'] if result['has_more'] else None
            current=db.execute("SELECT c.id,c.current_ordinal FROM courses c LEFT JOIN (SELECT course_id,MAX(created_at) AS last FROM learning_events GROUP BY course_id) e ON e.course_id=c.id WHERE c.session_id=? AND c.deleted_at IS NULL AND c.status='active' ORDER BY e.last DESC,c.sort_order,c.id LIMIT 1",(user,)).fetchone()
            result['current_exploration']=None
            if current:
                section=db.execute('SELECT id,title FROM sections WHERE course_id=? AND ordinal=?',(current['id'],current['current_ordinal'])).fetchone()
                latest=db.execute("SELECT json_extract(a.value,'$.id') AS aid,json_extract(a.value,'$.title') AS title FROM (SELECT atom_id,created_at FROM learning_events WHERE course_id=? UNION ALL SELECT atom_id,created_at FROM learning_evidence WHERE user_id=? AND course_id=? AND result IN ('correct','wrong')) e JOIN course_graphs g ON g.course_id=? JOIN json_each(g.graph_json,'$.atoms') a ON json_extract(a.value,'$.id')=e.atom_id WHERE json_extract(a.value,'$.section')=? AND COALESCE(json_extract(a.value,'$.quality_status'),'candidate')!='deprecated' ORDER BY e.created_at DESC LIMIT 1",(current['id'],user,current['id'],current['id'],current['current_ordinal'])).fetchone()
                name=db.execute('SELECT title FROM courses WHERE id=?',(current['id'],)).fetchone()[0]
                result['current_exploration']={'course_id':current['id'],'course_name':name,'chapter_ordinal':current['current_ordinal'],'chapter_id':section['id'] if section else None,'chapter_name':section['title'] if section else None,'star_id':star_id(current['id'],latest['aid']) if latest else None,'star_name':latest['title'] if latest else None,'basis':'课程当前小节与已有学习记录；探索点击不改位置'}
        return result
    def course(self,user,cid,chapter_id=None,offset=0):
        integer(offset);result=self.base('star' if chapter_id else 'nebula')
        with self.read() as db:
            c=self.owned(db,user,cid);sections=self.sections(db,cid);progress=self.progress(db,c);result['galaxies']=[self.galaxy(db,c,progress)]
            if chapter_id:
                section=next((s for s in sections if s['id']==chapter_id),None)
                if not section:raise ValueError('章节不属于当前课程')
                visible_sections=[section]
            else:visible_sections=sections[offset:offset+POLICY['max_visible_nebulae']]
            result['nebulae']=[self.nebula(db,c,s,progress) for s in visible_sections]
            result['goal_context']=self.goals(db,user,cid)
            result['explored_path']=self.path(db,user,cid)
            if not chapter_id:
                result['has_more']=len(sections)>offset+len(visible_sections);result['next_offset']=offset+len(visible_sections) if result['has_more'] else None
                result['clusters']=[{'id':n['id'],'nebula_id':n['id'],'name':n['name'],'star_count':n['star_count'],'basis':'已有章节聚合，不新增知识关系'} for n in result['nebulae'] if n['star_count']>POLICY['max_visible_stars']]
                return result
            rows=db.execute("SELECT a.value FROM course_graphs g,json_each(g.graph_json,'$.atoms') a WHERE g.course_id=? AND json_extract(a.value,'$.section')=? AND COALESCE(json_extract(a.value,'$.quality_status'),'candidate')!='deprecated' ORDER BY CAST(a.key AS INTEGER) LIMIT ? OFFSET ?",(cid,section['ordinal'],POLICY['max_visible_stars']+1,offset)).fetchall()
            atoms=[json.loads(r[0]) for r in rows[:POLICY['max_visible_stars']]]
            ids={a['id'] for a in atoms}
            importance={r['aid']:r['amount'] for r in db.execute("SELECT json_extract(e.value,'$.from') AS aid,COUNT(*) AS amount FROM course_graphs g,json_each(g.graph_json,'$.edges') e WHERE g.course_id=? AND json_extract(e.value,'$.type')='prerequisite' AND EXISTS(SELECT 1 FROM json_each(?) ids WHERE ids.value=json_extract(e.value,'$.from')) GROUP BY json_extract(e.value,'$.from')",(cid,json.dumps(list(ids))))}
            result['stars']=[self.star(db,user,c,section,a,importance.get(a['id'],0)) for a in atoms]
            links=db.execute("SELECT e.value FROM course_graphs g,json_each(g.graph_json,'$.edges') e WHERE g.course_id=? AND EXISTS(SELECT 1 FROM json_each(?) ids WHERE ids.value=json_extract(e.value,'$.from')) AND EXISTS(SELECT 1 FROM json_each(?) ids WHERE ids.value=json_extract(e.value,'$.to')) LIMIT ?",(cid,json.dumps(list(ids)),json.dumps(list(ids)),POLICY['max_visible_edges']+1)).fetchall()
            result['edges']=[edge(cid,json.loads(r[0])) for r in links[:POLICY['max_visible_edges']]]
            result['edges_truncated']=len(links)>POLICY['max_visible_edges'];result['has_more']=len(rows)>POLICY['max_visible_stars']
            result['next_offset']=offset+len(atoms) if result['has_more'] else None
            total=result['nebulae'][0]['star_count']
            if total>POLICY['max_visible_stars']:result['clusters']=[{'id':'n-'+section['id'],'nebula_id':'n-'+section['id'],'name':section['title'],'star_count':total,'basis':'按已有章节聚合，分页探索星辰'}]
        return result
    def star(self,db,user,c,s,a,importance=None):
        cid=c['id'];aid=a['id']
        row=db.execute('SELECT state_json FROM knowledge_states WHERE user_id=? AND course_id=? AND atom_id=?',(user,cid,aid)).fetchone()
        raw=json.loads(row[0]) if row else None
        mis=[dict(r) for r in db.execute("SELECT status,description FROM learning_misconceptions WHERE user_id=? AND course_id=? AND atom_id=? AND status='confirmed' LIMIT 4",(user,cid,aid))]
        read=bool(db.execute('SELECT 1 FROM learning_events WHERE course_id=? AND atom_id=? LIMIT 1',(cid,aid)).fetchone())
        if importance is None:importance=db.execute("SELECT COUNT(*) FROM course_graphs g,json_each(g.graph_json,'$.edges') e WHERE g.course_id=? AND json_extract(e.value,'$.from')=? AND json_extract(e.value,'$.type')='prerequisite'",(cid,aid)).fetchone()[0]
        return {'id':star_id(cid,aid),'atom_id':aid,'course_id':cid,'nebula_id':'n-'+s['id'],'chapter_id':s['id'],'section_ordinal':s['ordinal'],
                'name':a['title'],'description':a['summary'],'importance':1+min(3,importance),'importance_basis':'已有前置关系连接数，大小不代表掌握度',
                'difficulty':{1:'概念入门',2:'基础理解',3:'机制应用',4:'深入推导',5:'综合实现'}.get(a.get('depth',2),'基础理解'),
                'quality_status':a.get('quality_status','candidate'),'unlocked':s['ordinal']<=c['current_ordinal'],
                **visual_state(raw,datetime.now(timezone.utc),mis,read)}
    def detail(self,user,sid,relation_offset=0):
        integer(relation_offset);cid,aid=decode_star(sid)
        with self.read() as db:
            c=self.owned(db,user,cid)
            row=db.execute("SELECT a.value,a.key AS position FROM course_graphs g,json_each(g.graph_json,'$.atoms') a WHERE g.course_id=? AND json_extract(a.value,'$.id')=? AND COALESCE(json_extract(a.value,'$.quality_status'),'candidate')!='deprecated' LIMIT 1",(cid,aid)).fetchone()
            if not row:raise ValueError('知识星辰不存在')
            a=json.loads(row[0]);sections=self.sections(db,cid);section=next((s for s in sections if s['ordinal']==a['section']),None)
            if not section:raise ValueError('星辰所属章节不存在')
            star=self.star(db,user,c,section,a)
            position=db.execute("SELECT COUNT(*) FROM course_graphs g,json_each(g.graph_json,'$.atoms') a WHERE g.course_id=? AND json_extract(a.value,'$.section')=? AND CAST(a.key AS INTEGER)<? AND COALESCE(json_extract(a.value,'$.quality_status'),'candidate')!='deprecated'",(cid,a['section'],row['position'])).fetchone()[0]
            rows=db.execute("SELECT e.value FROM course_graphs g,json_each(g.graph_json,'$.edges') e WHERE g.course_id=? AND (json_extract(e.value,'$.from')=? OR json_extract(e.value,'$.to')=?) LIMIT 41 OFFSET ?",(cid,aid,aid,relation_offset)).fetchall()
            relations=[];neighbors=[]
            for r in rows[:40]:
                link=json.loads(r[0]);other=link['to'] if link['from']==aid else link['from']
                neighbor=db.execute("SELECT a.value FROM course_graphs g,json_each(g.graph_json,'$.atoms') a WHERE g.course_id=? AND json_extract(a.value,'$.id')=? AND COALESCE(json_extract(a.value,'$.quality_status'),'candidate')!='deprecated' LIMIT 1",(cid,other)).fetchone()
                if not neighbor:continue
                neighbor=json.loads(neighbor[0]);ns=next((s for s in sections if s['ordinal']==neighbor['section']),None)
                if not ns:continue
                neighbor_star=self.star(db,user,c,ns,neighbor);relations.append({**edge(cid,link),'other_star':neighbor_star});neighbors.append(neighbor)
            history=[{'kind':r['kind'],'created_at':r['created_at']} for r in db.execute('SELECT kind,created_at FROM learning_events WHERE course_id=? AND atom_id=? ORDER BY id DESC LIMIT 8',(cid,aid))]
            evidence=[{'evidence_type':r['evidence_type'],'label':'独立答题通过' if r['result']=='correct' else '建议回看后再独立检测','created_at':r['created_at']} for r in db.execute("SELECT evidence_type,result,created_at FROM learning_evidence WHERE user_id=? AND course_id=? AND atom_id=? AND result IN ('correct','wrong') AND hint_used=0 AND COALESCE(json_extract(metadata_json,'$.reused_question'),0)=0 ORDER BY rowid DESC LIMIT 8",(user,cid,aid))]
            return {'atom':star,'window_offset':position//POLICY['max_visible_stars']*POLICY['max_visible_stars'],'relations':relations,'history':history,'independent_history':evidence,'mastery_state':star['mastery_state'],
                    'galaxy':self.galaxy(db,c),'nebula':self.nebula(db,c,section),'goal_context':self.goals(db,user,cid),
                    'personal_reference':self.profile(db,user,c,sections,a),'calibration_reference':self.calibration(db,user,cid,aid),
                    'has_more_relations':len(rows)>40,'next_relation_offset':relation_offset+40 if len(rows)>40 else None,
                    'tutor_context':{'context_id':cid,'current_context':{'section_ordinal':a['section'],'knowledge_atom_id':aid}},
                    'boundary':BOUNDARY}
    def profile(self,db,user,c,sections,a):
        row=db.execute("SELECT m.atom_hash,m.canonical_atom_id,p.profile_json,p.updated_at FROM course_atom_mappings m JOIN canonical_knowledge_atoms k ON k.id=m.canonical_atom_id AND k.user_id=m.user_id AND k.status='active' LEFT JOIN personal_knowledge_profiles p ON p.user_id=m.user_id AND p.canonical_atom_id=m.canonical_atom_id WHERE m.user_id=? AND m.course_id=? AND m.course_atom_id=? AND m.status='verified'",(user,c['id'],a['id'])).fetchone()
        if not row or not row['profile_json']:return None
        # Validate the original mapping fingerprint without loading an entire graph into Python.
        links=[json.loads(r[0]) for r in db.execute("SELECT e.value FROM course_graphs g,json_each(g.graph_json,'$.edges') e WHERE g.course_id=? AND (json_extract(e.value,'$.from')=? OR json_extract(e.value,'$.to')=?) LIMIT ?",(c['id'],a['id'],a['id'],POLICY['max_visible_edges']+1))]
        if len(links)>POLICY['max_visible_edges']:return None
        ids={v for e in links for v in [e['from'],e['to']]}
        neighbors=[json.loads(r[0]) for r in db.execute("SELECT a.value FROM course_graphs g,json_each(g.graph_json,'$.atoms') a WHERE g.course_id=? AND EXISTS(SELECT 1 FROM json_each(?) ids WHERE ids.value=json_extract(a.value,'$.id'))",(c['id'],json.dumps(list(ids))))]
        g={'atoms':neighbors or [a],'edges':links};course={**c,'sections':sections}
        if fingerprint(atom_context(course,g,a))!=row['atom_hash']:return None
        p=json.loads(row['profile_json'])
        return {'canonical_atom_id':row['canonical_atom_id'],'name':p['name'],'label':p['label'],
                'cross_course_conflict':p['cross_course_conflict'],'updated_at':row['updated_at'],
                'snapshot':True,'boundary':'这是已存的个人知识档案快照，不自动重建，也不作为本课程掌握证明。'}
    def calibration(self,db,user,cid,aid):
        row=db.execute("SELECT result_json,created_at FROM calibration_snapshots WHERE user_id=? AND scope_type='course' AND scope_id=? AND policy_version='all-separated' AND calibration_policy_version='calibration-v1'",(user,cid)).fetchone()
        if not row:return None
        data=json.loads(row['result_json']);state=db.execute('SELECT state_json FROM knowledge_states WHERE user_id=? AND course_id=? AND atom_id=?',(user,cid,aid)).fetchone()
        policy=json.loads(state[0]).get('policy_version','weighted-evidence-v1') if state else 'weighted-evidence-v1'
        atomic=data.get('versions',{}).get(policy,{}).get('atoms',{}).get(aid,{})
        labels=[v.get('independent_mcq',{}).get('classification') for v in atomic.values()]
        valid=[v for v in labels if v in {'state_overestimation','state_underestimation','well_aligned'}]
        if not valid:return None
        category='state_overestimation' if 'state_overestimation' in valid else 'state_underestimation' if 'state_underestimation' in valid else 'well_aligned'
        return {'classification':category,'label':'历史估计与后续独立测验存在差异，建议主动验证' if category!='well_aligned' else '已有历史估计与后续独立测验的对照记录',
                'updated_at':row['created_at'],'snapshot':True,'boundary':'仅引用已有 P2 独立题校准快照，不把模型开放评分当事实，不改掌握状态。'}
    def goals(self,db,user,cid):
        rows=db.execute("SELECT g.id,g.title,t.id AS task_id,t.title AS task_title,t.reason_code,t.metadata_json FROM growth_tasks t JOIN learning_goals g ON g.id=t.goal_id AND g.user_id=t.user_id JOIN growth_roadmaps r ON r.id=t.roadmap_id AND r.user_id=t.user_id WHERE t.user_id=? AND g.status='active' AND r.status='active' AND t.status IN ('active','ready') AND (t.target_id=? OR json_extract(t.metadata_json,'$.linked_course_id')=?) ORDER BY t.priority,t.stage_ordinal LIMIT 4",(user,cid,cid)).fetchall()
        return [{'goal_id':r['id'],'goal':r['title'],'task_id':r['task_id'],'task':r['task_title'],'reason_code':r['reason_code'],'atom_id':json.loads(r['metadata_json']).get('atom_id'),'boundary':'读取已有成长任务，不自动规划或推进。'} for r in rows]
    def path(self,db,user,cid):
        # Chronology is a separate list, not invented graph edges.
        rows=db.execute("SELECT atom_id,MAX(created_at) AS last FROM (SELECT atom_id,created_at FROM learning_events WHERE course_id=? UNION ALL SELECT atom_id,created_at FROM learning_evidence WHERE user_id=? AND course_id=? AND result IN ('correct','wrong')) GROUP BY atom_id ORDER BY last DESC LIMIT 12",(cid,user,cid)).fetchall()
        result=[]
        for r in reversed(rows):
            exists=db.execute("SELECT json_extract(a.value,'$.title') FROM course_graphs g,json_each(g.graph_json,'$.atoms') a WHERE g.course_id=? AND json_extract(a.value,'$.id')=? AND COALESCE(json_extract(a.value,'$.quality_status'),'candidate')!='deprecated' LIMIT 1",(cid,r['atom_id'])).fetchone()
            if exists:result.append({'star_id':star_id(cid,r['atom_id']),'created_at':r['last'],'name':exists[0]})
        return result
    def search(self,user,q):
        if not isinstance(q,str) or not 1<=len(q.strip())<=100:raise ValueError('请输入1到100字的搜索词')
        # instr is literal: %/_ are not SQL wildcard syntax. Search only owned, visible records.
        q=q.strip().casefold();result=[]
        with self.read() as db:
            for r in db.execute('SELECT id,title FROM courses WHERE session_id=? AND deleted_at IS NULL AND instr(lower(title),?)>0 ORDER BY sort_order LIMIT 20',(user,q)):
                result.append({'type':'galaxy','name':r['title'],'course_id':r['id']})
            for r in db.execute('SELECT s.id,s.title,s.course_id FROM sections s JOIN courses c ON c.id=s.course_id WHERE c.session_id=? AND c.deleted_at IS NULL AND instr(lower(s.title),?)>0 ORDER BY c.sort_order,s.ordinal LIMIT 20',(user,q)):
                result.append({'type':'nebula','name':r['title'],'course_id':r['course_id'],'chapter_id':r['id']})
            for r in db.execute("SELECT c.id,json_extract(a.value,'$.id') AS aid,json_extract(a.value,'$.title') AS title,s.id AS chapter_id FROM courses c JOIN course_graphs g ON g.course_id=c.id JOIN json_each(g.graph_json,'$.atoms') a JOIN sections s ON s.course_id=c.id AND s.ordinal=json_extract(a.value,'$.section') WHERE c.session_id=? AND c.deleted_at IS NULL AND COALESCE(json_extract(a.value,'$.quality_status'),'candidate')!='deprecated' AND instr(lower(json_extract(a.value,'$.title')),?)>0 LIMIT 20",(user,q)):
                result.append({'type':'star','name':r['title'],'course_id':r['id'],'chapter_id':r['chapter_id'],'star_id':star_id(r['id'],r['aid'])})
        return {'results':result,'boundary':'只搜索已有课程、章节与知识原子，不生成知识或改变学习状态。'}
