"""Course source policy, bounded gap discovery and evidence-backed conflict records."""
from __future__ import annotations
import json
import secrets
import threading
import time
from datetime import datetime, timezone
from .production import normalize_candidate_result
from .acquisition import SourceDocument, WebSearchProvider

POLICIES={'balanced','user_material_first'}
def stamp():return datetime.now(timezone.utc).isoformat(timespec='seconds')
SCHEMA='''
CREATE TABLE IF NOT EXISTS draft_documents (
 draft_id TEXT NOT NULL REFERENCES course_drafts(id), id TEXT NOT NULL, document_json TEXT NOT NULL,
 PRIMARY KEY(draft_id,id)
);
CREATE TABLE IF NOT EXISTS discovery_runs (
 id TEXT PRIMARY KEY, course_id TEXT NOT NULL REFERENCES courses(id), status TEXT NOT NULL,
 report_json TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS discovery_active ON discovery_runs(course_id) WHERE status='running';
CREATE TABLE IF NOT EXISTS source_conflicts (
 id TEXT PRIMARY KEY, course_id TEXT NOT NULL REFERENCES courses(id), source_a TEXT NOT NULL,
 source_b TEXT NOT NULL, content_json TEXT NOT NULL, teaching_expression TEXT NOT NULL,
 confirmed INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, confirmed_at TEXT
);
'''

def migrate_discovery(db):
    columns={r[1] for r in db.execute('PRAGMA table_info(discovery_runs)')}
    if 'owner_id' not in columns:db.execute("ALTER TABLE discovery_runs ADD COLUMN owner_id TEXT NOT NULL DEFAULT ''")
    if 'heartbeat_at' not in columns:
        db.execute('ALTER TABLE discovery_runs ADD COLUMN heartbeat_at REAL NOT NULL DEFAULT 0')
        db.execute("UPDATE discovery_runs SET heartbeat_at=COALESCE(strftime('%s',updated_at),0)")


def selected_blocks(source, limit=24000):
    """Select complete blocks; disclose the range rather than truncate inside a block."""
    selected=[];size=0
    for block in source['metadata']['blocks']:
        if size+len(block['text'])<=limit:selected.append(block);size+=len(block['text'])
    return selected


def teaching_blocks(source, title, limit=4000):
    matching=[b for b in source['metadata']['blocks'] if title in [str(h)[:80] for h in b.get('section_path',[])] or b['kind']=='heading' and b['text'][:80]==title]
    if not matching:return selected_blocks(source,limit)
    selected=[];size=0
    for block in matching:
        if size+len(block['text'])<=limit:selected.append(block);size+=len(block['text'])
    return selected


def reference(doc, entry, allowed=None):
    if not isinstance(entry,dict):raise ValueError('来源证据格式无效')
    block=next((b for b in doc['metadata']['blocks'] if b['id']==entry.get('block_id') and (allowed is None or b['id'] in allowed)),None)
    quote=entry.get('quote')
    if not block or not isinstance(quote,str) or not 12<=len(quote)<=500 or quote not in block['text']:
        raise ValueError('覆盖或冲突证据不在实际选定原文中')
    return {'document_id':doc['id'],'document':doc['title'],'type':doc['source_type'],'origin':doc['origin'],
            'block_id':block['id'],'quote':quote,**{k:block[k] for k in ('page','slide','paragraph','line','section_path') if k in block},
            **({'url':doc['metadata']['url']} if doc['metadata'].get('url') else {})}


def normalize_plan(raw, course, documents, selections):
    units=raw.get('requirements') if isinstance(raw,dict) else None
    if not isinstance(units,list) or not 1<=len(units)<=16:raise ValueError('知识需求分析需返回 1—16 项')
    by_id={d['id']:d for d in documents};result=[];queries=[];seen=set()
    for unit in units:
        if not isinstance(unit,dict):raise ValueError('知识需求格式无效')
        title,section,aspect=unit.get('title'),unit.get('section'),unit.get('aspect')
        if not isinstance(title,str) or not 2<=len(title)<=100 or not isinstance(section,int) or isinstance(section,bool) or not 1<=section<=len(course['sections']):raise ValueError('知识需求名称或章节无效')
        if aspect not in ('definition','prerequisite','example','current','verification','relation'):raise ValueError('知识需求类型无效')
        evidence=unit.get('evidence',[]);refs=[]
        if not isinstance(evidence,list) or len(evidence)>4:raise ValueError('覆盖证据格式无效')
        for entry in evidence:
            if not isinstance(entry,dict) or not isinstance(entry.get('document_id'),str) or entry.get('document_id') not in by_id:raise ValueError('覆盖分析使用了未知资料')
            refs.append(reference(by_id[entry['document_id']],entry,selections[entry['document_id']]))
        query=unit.get('query','');reason=unit.get('reason','')
        if not isinstance(reason,str) or len(reason)>400:raise ValueError('知识缺口理由无效')
        if refs and aspect not in ('verification','current'):
            query='' # Never re-search a covered definition merely because a model suggested it.
        elif query and (not isinstance(query,str) or query.strip().casefold()==course['title'].strip().casefold()):
            raise ValueError('缺口检索词应具体，不能只重复整个课程主题')
        if query:
            key=query.strip().casefold()
            if key not in seen:
                queries.append({'query':query.strip(),'section':section,'requirement':title,'aspect':aspect,'reason':reason});seen.add(key)
        result.append({'title':title,'section':section,'aspect':aspect,'covered':bool(refs),'evidence':refs,'reason':reason,'query':query})
    # A course supplied only by user material still lacks an external fact comparison.
    if not queries and any(d['origin']=='user_upload' for d in documents) and not any(d['origin']=='web_search' for d in documents):
        covered=next((r for r in result if r['evidence']),None)
        if covered:
            query=covered['title']+' 官方资料 定义核对'
            check={'title':covered['title'],'section':covered['section'],'aspect':'verification','covered':True,
                'evidence':covered['evidence'],'reason':'用户资料不是事实认证，目前缺少公开资料对照核验','query':query}
            result.append(check)
            queries.append({k:check[k] for k in ('query','section','aspect','reason')}|{'requirement':check['title']})
    return {'requirements':result,'queries':queries[:3],'remaining_queries':queries[3:],
            'source_policy':course['source_policy'],'learner_level':course['learner_level'],
            'scope':[{'source_id':d['id'],'selected_blocks':list(selections[d['id']]),'total_blocks':len(d['metadata']['blocks'])} for d in documents]}


class DiscoveryStorage:
    def draft_documents(self, session, draft_id):
        if not self.draft(session,draft_id):raise ValueError('审查稿不存在')
        with self.connect() as db:rows=db.execute('SELECT document_json FROM draft_documents WHERE draft_id=? ORDER BY rowid',(draft_id,)).fetchall()
        return [json.loads(r[0]) for r in rows]

    def discovery(self,session,cid):
        self._knowledge_course(session,cid)
        with self.connect() as db:row=db.execute('SELECT * FROM discovery_runs WHERE course_id=? ORDER BY rowid DESC LIMIT 1',(cid,)).fetchone()
        if not row:return None
        value=dict(row);value['report']=json.loads(value.pop('report_json'));return value

    def begin_discovery(self,session,cid,owner_id=''):

        self._knowledge_course(session,cid)
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute("SELECT 1 FROM discovery_runs WHERE course_id=? AND status='running'",(cid,)).fetchone():return None
            identifier=secrets.token_urlsafe(16)
            db.execute('INSERT INTO discovery_runs(id,course_id,status,report_json,created_at,updated_at,owner_id,heartbeat_at) VALUES(?,?,?,?,?,?,?,?)',(identifier,cid,'running','{}',stamp(),stamp(),owner_id,time.time()))
        return identifier

    def recover_discovery(self,lease_seconds=300):
        with self.connect() as db:
            return db.execute("UPDATE discovery_runs SET status='interrupted',updated_at=? WHERE status='running' AND heartbeat_at<?",(stamp(),time.time()-lease_seconds)).rowcount

    def discovery_heartbeat(self,identifier,owner_id):
        with self.connect() as db:
            return bool(db.execute("UPDATE discovery_runs SET heartbeat_at=? WHERE id=? AND owner_id=? AND status='running'",(time.time(),identifier,owner_id)).rowcount)

    def discovery_update(self,identifier,report,status='running'):
        # Terminal or expired jobs never return to running through a late worker.
        with self.connect() as db:
            return bool(db.execute("UPDATE discovery_runs SET status=?,report_json=?,updated_at=?,heartbeat_at=? WHERE id=? AND status='running'",(status,json.dumps(report,ensure_ascii=False),stamp(),time.time(),identifier)).rowcount)

    def conflicts(self,session,cid):
        self._knowledge_course(session,cid)
        with self.connect() as db:rows=db.execute('SELECT * FROM source_conflicts WHERE course_id=? ORDER BY rowid DESC',(cid,)).fetchall()
        result=[]
        for row in rows:
            item=dict(row);item['content']=json.loads(item.pop('content_json'));item['confirmed']=bool(item['confirmed']);result.append(item)
        return result

    def save_conflicts(self,session,cid,raw,documents,selections):
        self._knowledge_course(session,cid)
        entries=raw.get('conflicts') if isinstance(raw,dict) else None
        if not isinstance(entries,list) or len(entries)>6:raise ValueError('冲突分析格式无效')
        by_id={d['id']:self.source(session,cid,d['id']) for d in documents};normalized=[]
        for entry in entries:
            if not isinstance(entry,dict):raise ValueError('冲突格式无效')
            a,b=entry.get('source_a'),entry.get('source_b')
            if not isinstance(a,dict) or not isinstance(b,dict) or not isinstance(a.get('document_id'),str) or not isinstance(b.get('document_id'),str) or a.get('document_id') not in by_id or b.get('document_id') not in by_id or a['document_id']==b['document_id']:raise ValueError('冲突必须对应本课程不同真实资料')
            topic,description=entry.get('topic'),entry.get('description')
            if not isinstance(topic,str) or not 2<=len(topic)<=100 or not isinstance(description,str) or not 10<=len(description)<=600:raise ValueError('冲突内容不完整')
            ra=reference(by_id[a['document_id']],a,selections[a['document_id']]);rb=reference(by_id[b['document_id']],b,selections[b['document_id']])
            # Expression is a proposal, never a silent modification to lessons or atoms.
            course=self.course(session,cid)
            preferred=ra if ra['origin']=='user_upload' else rb if rb['origin']=='user_upload' else ra
            expression=preferred['quote'] if course['source_policy']=='user_material_first' else '暂不选择，等待用户核对双方原文'
            normalized.append((ra,rb,{'topic':topic,'description':description,'source_a':ra,'source_b':rb,'meaning':'模型发现的待核对差异，非事实认证'},expression))
        with self.connect() as db:
            for a,b,content,expression in normalized:
                existing=db.execute('SELECT content_json FROM source_conflicts WHERE course_id=? AND ((source_a=? AND source_b=?) OR (source_a=? AND source_b=?))',
                    (cid,a['document_id'],b['document_id'],b['document_id'],a['document_id'])).fetchall()
                if any(json.loads(r[0])['topic']==content['topic'] for r in existing):continue
                db.execute('INSERT INTO source_conflicts VALUES(?,?,?,?,?,?,0,?,NULL)',(secrets.token_urlsafe(16),cid,a['document_id'],b['document_id'],json.dumps(content,ensure_ascii=False),expression,stamp()))
                from .revisions import bump_revision
                bump_revision(db,cid)
        return self.conflicts(session,cid)

    def confirm_conflict(self,session,cid,identifier,expression):
        self._knowledge_course(session,cid)
        if not isinstance(identifier,str) or not isinstance(expression,str) or not 2<=len(expression.strip())<=600:raise ValueError('请填写本课程采用的教学表达或保留分歧的说明')
        with self.connect() as db:
            if not db.execute('UPDATE source_conflicts SET teaching_expression=?,confirmed=1,confirmed_at=? WHERE id=? AND course_id=?',
                (expression.strip(),stamp(),identifier,cid)).rowcount:raise ValueError('本课程冲突记录不存在')
            from .revisions import bump_revision
            bump_revision(db,cid)
        return self.conflicts(session,cid)

    def policy(self,session,cid,policy):
        self._knowledge_course(session,cid)
        if not isinstance(policy,str) or policy not in POLICIES:raise ValueError('知识来源偏好无效')
        with self.connect() as db:
            if db.execute("SELECT 1 FROM discovery_runs WHERE course_id=? AND status='running'",(cid,)).fetchone():raise ValueError('自动发现正在进行，请完成后再更换来源偏好')
            old=db.execute('SELECT source_policy FROM courses WHERE id=?',(cid,)).fetchone()[0]
            db.execute('UPDATE courses SET source_policy=? WHERE id=?',(policy,cid))
            if old!=policy:
                from .revisions import bump_revision
                bump_revision(db,cid)


def analyze_conflicts(store,session,course,model,source,blocks):
    summaries=[s for s in store.sources(session,course['id']) if s['id']!=source['id']]
    summaries.sort(key=lambda d:d['origin']!='user_upload')
    others=[store.source(session,course['id'],s['id']) for s in summaries[:5]]
    if not others:return []
    documents=[source]+others
    selections={d['id']:[b['id'] for b in (blocks if d['id']==source['id'] else selected_blocks(d,8000))] for d in documents}
    raw=model.find_source_conflicts(course,documents,selections)
    all_conflicts=store.save_conflicts(session,course['id'],raw,documents,selections)
    return [c['id'] for c in all_conflicts if source['id'] in (c['source_a'],c['source_b'])]


def produce_source(store,session,course,model,source,section,blocks):
    store.source_status(session,course['id'],source['id'],'processing')
    try:
        graph=store.graph(session,course['id']) or {'atoms':[],'edges':[]}
        production_course=dict(course)
        production_course['source_context']=[{'title':d['title'],'origin':d['origin'],'blocks':selected_blocks(d,3000)}
            for d in [store.source(session,course['id'],s['id']) for s in store.sources(session,course['id']) if s['id']!=source['id']][:4]]
        raw=model.produce_knowledge(production_course,source,section,blocks,graph['atoms'])
        result=normalize_candidate_result(raw,source,section,blocks,{a['id'] for a in graph['atoms']})
        conflict_ids=analyze_conflicts(store,session,course,model,source,blocks)
        result['source_policy']=course.get('source_policy','balanced')
        result['learner_level']=course.get('learner_level','零基础')
        result['conflict_ids']=conflict_ids
        if conflict_ids:
            for c in result['candidates']:c['quality']['multi_source_consistency']='外部资料存在不同表述/事实冲突，请先审查冲突记录'
        return store.save_batch(session,course['id'],source['id'],section,result)
    except Exception:
        store.source_status(session,course['id'],source['id'],'failed');raise


class DiscoveryEngine:
    """One course job at a time, no graph or mastery writes; transports are injected."""
    def __init__(self,store):
        self.store=store;self.threads=[];self.owner_id=secrets.token_urlsafe(16)
        self.store.recover_discovery()
    def start(self,session,cid,model,provider):
        self.store.recover_discovery()
        identifier=self.store.begin_discovery(session,cid,self.owner_id)
        if not identifier:return self.store.discovery(session,cid)
        thread=threading.Thread(target=self.run,args=(session,cid,identifier,model,provider),daemon=True)
        self.threads=[t for t in self.threads if t.is_alive()]+[thread];thread.start()
        return self.store.discovery(session,cid)
    def run(self,session,cid,identifier,model,provider):
        stop=threading.Event()
        with self.store.connect() as db:
            owner=db.execute('SELECT owner_id FROM discovery_runs WHERE id=?',(identifier,)).fetchone()[0]
        def heartbeat():
            while not stop.wait(15):
                if not self.store.discovery_heartbeat(identifier,owner):return
        pulse=threading.Thread(target=heartbeat,daemon=True);pulse.start()
        try:self._run(session,cid,identifier,model,provider)
        finally:stop.set();pulse.join(timeout=1)

    def _run(self,session,cid,identifier,model,provider):
        report={'stage':'读取课程与已有资料','errors':[],'acquisitions':[],'batches':[]}
        try:
            course=self.store.course(session,cid)
            summaries=self.store.sources(session,cid)
            summaries.sort(key=lambda d:d['origin']!='user_upload')
            docs=[self.store.source(session,cid,s['id']) for s in summaries[:10]]
            report['unexamined_documents']=[s['id'] for s in summaries[10:]]
            # Uploads drive the body of material-first courses; process them before planning external gaps.
            pending=[d for d in docs if d['origin']=='user_upload']
            done={(b['source_id'],b['section']) for b in self.store.batches(session,cid)}
            if pending:
                report['stage']='理解用户资料并生成课程主体候选';self.store.discovery_update(identifier,report)
                for doc in pending[:3]:
                    blocks=selected_blocks(doc)
                    report.setdefault('material_scope',[]).append({'source_id':doc['id'],'selected_blocks':[b['id'] for b in blocks],'total_blocks':len(doc['metadata']['blocks'])})
                    groups={};current=1
                    for block in blocks:
                        if block['kind']=='heading':
                            match=next((s['ordinal'] for s in course['sections'] if s['title']==block['text'][:80]),None)
                            if match:current=match
                        groups.setdefault(current,[]).append(block)
                    for section,chosen in groups.items():
                        if (doc['id'],section) in done:continue
                        if not any(len(b['text'])>=12 for b in chosen):continue
                        try:report['batches'].append(produce_source(self.store,session,course,model,doc,section,chosen)['id'])
                        except Exception as exc:report['errors'].append({'stage':'用户资料抽取','source_id':doc['id'],'message':str(exc)})
            done={(b['source_id'],b['section']) for b in self.store.batches(session,cid)}
            for doc in docs:
                context=doc['metadata'].get('discovery')
                if doc['origin']=='web_search' and context and (doc['id'],context['section']) not in done:
                    try:
                        batch=produce_source(self.store,session,course,model,doc,context['section'],selected_blocks(doc))
                        report['batches'].append(batch['id']);report['acquisitions'].append({**context,'source_id':doc['id'],'url':doc['metadata'].get('url'),'status':'complete'})
                    except Exception as exc:report['errors'].append({'stage':'重试已有公开正文','source_id':doc['id'],'message':str(exc)})
            graph=self.store.graph(session,cid) or {'atoms':[],'edges':[]}
            selections={d['id']:[b['id'] for b in selected_blocks(d,8000)] for d in docs}
            report['stage']='知识需求与缺口分析';self.store.discovery_update(identifier,report)
            from .search_planning import build_search_plan
            plan=build_search_plan(model,course,docs,selections,graph,self.store.batches(session,cid))
            report['plan']=plan;report['stage']='按缺口获取公开正文';self.store.discovery_update(identifier,report)
            known_urls={d['metadata'].get('url') for d in docs};seen_urls=set()
            with self.store.connect() as db:previous=db.execute("SELECT report_json FROM discovery_runs WHERE course_id=? AND id!=?",(cid,identifier)).fetchall()
            completed={x['query'].casefold() for r in previous for x in json.loads(r[0]).get('acquisitions',[]) if x.get('status')=='complete'}
            completed.update(x['query'].casefold() for x in report['acquisitions'] if x.get('status')=='complete')
            all_queries=plan['queries']+plan['remaining_queries']
            already=[q for q in all_queries if q['query'].casefold() in completed]
            new=[q for q in all_queries if q['query'].casefold() not in completed]
            plan['queries']=new[:3];plan['remaining_queries']=new[3:]
            for query in already+plan['queries']:
                if query['query'].casefold() in completed:
                    report['acquisitions'].append({**query,'status':'already_done'});continue
                try:results=provider.search(query['query'])
                except Exception as exc:
                    report['errors'].append({'stage':'搜索缺口','query':query['query'],'message':str(exc)});continue
                acquired=False
                for result in results[:3]:
                    url=result['url']
                    if url in known_urls or url in seen_urls:continue
                    seen_urls.add(url)
                    try:
                        source=provider.acquire(url=url,title=result['title'][:150])
                        source.metadata['discovery']=dict(query)
                        saved=self.store.save_source(session,cid,source);known_urls.add(url)
                        batch=produce_source(self.store,session,course,model,saved,query['section'],selected_blocks(saved))
                        report['batches'].append(batch['id']);report['acquisitions'].append({**query,'url':url,'source_id':saved['id'],'status':'complete'});acquired=True;break
                    except Exception as exc:report['errors'].append({'stage':'正文获取或候选生产','url':url,'message':str(exc)})
                if not acquired:
                    report['acquisitions'].append({**query,'status':'no_new_body'})
                    report['errors'].append({'stage':'缺口补充','query':query['query'],'message':'未能取得新的可用正文，缺口仍需核对或重试'})
                self.store.discovery_update(identifier,report)
            report['stage']='候选等待用户审查'
            self.store.discovery_update(identifier,report,'partial' if report['errors'] or plan['remaining_queries'] or report['unexamined_documents'] else 'complete')
        except Exception as exc:
            report['errors'].append({'stage':report['stage'],'message':str(exc)})
            self.store.discovery_update(identifier,report,'failed')
