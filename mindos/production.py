"""Traceable source storage, candidate validation and reviewed graph integration."""
from __future__ import annotations
import copy
import json
import re
import secrets
from datetime import datetime, timezone
from .knowledge import ATOM_TYPES, RELATIONS, validate_graph
from .quality import evaluate_quality

SCHEMA = """
CREATE TABLE IF NOT EXISTS source_documents (
 id TEXT PRIMARY KEY, course_id TEXT NOT NULL REFERENCES courses(id), title TEXT NOT NULL,
 source_type TEXT NOT NULL, origin TEXT NOT NULL, content TEXT NOT NULL, metadata_json TEXT NOT NULL,
 created_time TEXT NOT NULL, processing_status TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS production_batches (
 id TEXT PRIMARY KEY, course_id TEXT NOT NULL REFERENCES courses(id), source_id TEXT NOT NULL REFERENCES source_documents(id),
 section INTEGER NOT NULL, result_json TEXT NOT NULL, status TEXT NOT NULL, feedback TEXT NOT NULL, created_time TEXT NOT NULL
);
"""
RELATION_MAP = {'requires':'prerequisite','related_to':'related','contrast':'contrasts'}


def normalize_candidate_result(raw: dict, source: dict, section: int, blocks: list[dict], existing_ids: set[str]) -> dict:
    if not isinstance(raw,dict) or not isinstance(raw.get('candidates'),list) or not 1 <= len(raw['candidates']) <= 6:
        raise ValueError('模型需返回 1—6 个知识候选')
    understanding=raw.get('understanding')
    if not isinstance(understanding,str) or not 10 <= len(understanding.strip()) <= 1500:
        raise ValueError('资料结构理解不完整')
    by_id={b['id']:b for b in blocks}
    candidates=[]; ids=set()
    for item in raw['candidates']:
        if not isinstance(item,dict):raise ValueError('知识候选格式无效')
        identifier=item.get('id')
        if not isinstance(identifier,str) or not re.fullmatch(r'c[1-6]',identifier) or identifier in ids:
            raise ValueError('候选编号需唯一且为 c1—c6')
        ids.add(identifier)
        fields={}
        for key,limit in [('title',80),('summary',240),('why',240)]:
            text=item.get(key)
            if not isinstance(text,str) or not 2 <= len(text.strip()) <= limit:raise ValueError('候选的名称、定义或用途无效')
            fields[key]=text.strip()
        if not isinstance(item.get('type'),str) or item['type'] not in ATOM_TYPES:raise ValueError('候选类型无效')
        depth=item.get('depth',2)
        if not isinstance(depth,int) or isinstance(depth,bool) or not 1<=depth<=5:raise ValueError('候选深度无效')
        evidence=item.get('evidence')
        references=[];issues=[]
        if not isinstance(evidence,list) or not 1 <= len(evidence) <= 4:
            issues.append('缺少可追踪的原文证据')
        else:
            for entry in evidence:
                if not isinstance(entry,dict) or not isinstance(entry.get('block_id'),str):
                    issues.append('来源位置无效');continue
                block=by_id.get(entry['block_id']);quote=entry.get('quote')
                if not block or not isinstance(quote,str) or not 12 <= len(quote) <= 500 or quote not in block['text']:
                    issues.append('引用不在选定原文中，或长度不足');continue
                references.append({'document_id':source['id'],'document':source['title'],'type':source['source_type'],
                    'origin':source['origin'],'block_id':block['id'],'quote':quote,
                    **{k:block[k] for k in ('page','slide','paragraph','line','table','section_path') if k in block},
                    **({'url':source['metadata']['url']} if source['metadata'].get('url') else {})})
        if not references and not issues:issues.append('没有有效来源')
        quality=evaluate_quality(source,blocks,references,issues)
        candidates.append({'id':identifier,'section':section,'type':item['type'],'depth':depth,**fields,
                           'source_reference':references,'quality_status':'candidate','quality':quality})
    edges=[]
    relations=raw.get('relations',[])
    if not isinstance(relations,list) or len(relations)>60:raise ValueError('候选关系数量或格式无效')
    for link in relations:
        if not isinstance(link,dict):raise ValueError('候选关系格式无效')
        kind=link.get('type');a,b=link.get('from'),link.get('to')
        if not all(isinstance(v,str) for v in (kind,a,b)):raise ValueError('候选关系格式无效')
        if a not in ids|existing_ids or b not in ids|existing_ids or a==b:raise ValueError('关系指向未知原子')
        if kind=='requires':a,b=b,a
        kind=RELATION_MAP.get(kind,kind)
        if kind not in RELATIONS:raise ValueError('候选关系类型不支持')
        edges.append({'from':a,'to':b,'type':kind})
    return {'understanding':understanding.strip(),'selected_blocks':[b['id'] for b in blocks],
            'candidates':candidates,'relations':edges}


class ProductionStorage:
    def save_source(self, session_id, course_id, document):
        self._knowledge_course(session_id,course_id)
        value=document.to_dict()
        with self.connect() as db:
            count=db.execute('SELECT COUNT(*) FROM source_documents WHERE course_id=?',(course_id,)).fetchone()[0]
            if count>=50:raise ValueError('每门课程最多保存 50 份资料')
            db.execute('INSERT INTO source_documents VALUES(?,?,?,?,?,?,?,?,?)',
                       (value['id'],course_id,value['title'],value['source_type'],value['origin'],value['content'],
                        json.dumps(value['metadata'],ensure_ascii=False),value['created_time'],value['processing_status']))
            from .revisions import bump_revision
            bump_revision(db,course_id)
        return self.source(session_id,course_id,value['id'])

    def source(self, session_id, course_id, source_id):
        self._knowledge_course(session_id,course_id)
        if not isinstance(source_id,str):raise ValueError('资料编号无效')
        with self.connect() as db:
            row=db.execute('SELECT * FROM source_documents WHERE course_id=? AND id=?',(course_id,source_id)).fetchone()
        if not row:raise ValueError('本课程资料不存在')
        value=dict(row);value['metadata']=json.loads(value.pop('metadata_json'));return value

    def sources(self, session_id, course_id):
        self._knowledge_course(session_id,course_id)
        with self.connect() as db:
            rows=db.execute('SELECT id,title,source_type,origin,created_time,processing_status FROM source_documents WHERE course_id=? ORDER BY rowid DESC',
                            (course_id,)).fetchall()
        return [dict(row) for row in rows]

    def source_status(self, session_id, course_id, source_id, status):
        self.source(session_id,course_id,source_id)
        with self.connect() as db:db.execute('UPDATE source_documents SET processing_status=? WHERE id=?',(status,source_id))

    def save_batch(self, session_id, course_id, source_id, section, result):
        self.source(session_id,course_id,source_id)
        identifier=secrets.token_urlsafe(16)
        with self.connect() as db:
            db.execute('INSERT INTO production_batches VALUES(?,?,?,?,?,?,?,?)',
                       (identifier,course_id,source_id,section,json.dumps(result,ensure_ascii=False),'candidate','',
                        datetime.now(timezone.utc).isoformat(timespec='seconds')))
            db.execute("UPDATE source_documents SET processing_status='candidate' WHERE id=?",(source_id,))
        return self.batch(session_id,course_id,identifier)

    def batch(self, session_id, course_id, batch_id):
        self._knowledge_course(session_id,course_id)
        if not isinstance(batch_id,str):raise ValueError('候选批次编号无效')
        with self.connect() as db:
            row=db.execute('SELECT * FROM production_batches WHERE course_id=? AND id=?',(course_id,batch_id)).fetchone()
        if not row:raise ValueError('候选批次不存在')
        value=dict(row);value['result']=json.loads(value.pop('result_json'));return value

    def batches(self, session_id, course_id):
        self._knowledge_course(session_id,course_id)
        with self.connect() as db:
            ids=db.execute('SELECT id FROM production_batches WHERE course_id=? ORDER BY rowid DESC',(course_id,)).fetchall()
        return [self.batch(session_id,course_id,row[0]) for row in ids]

    def review_batch(self, session_id, course_id, batch_id, action, selected, feedback, merge_choices=None):
        course=self._knowledge_course(session_id,course_id)
        batch=self.batch(session_id,course_id,batch_id)
        if not isinstance(feedback,str) or len(feedback)>500:raise ValueError('审查备注最多 500 字')
        if batch['status']!='candidate':raise ValueError('该批次已经审查，不能重复写入图谱')
        if action not in ('verify','deprecate'):raise ValueError('请选择确认导入或弃用')
        result=copy.deepcopy(batch['result'])
        original_graph=self.graph(session_id,course_id)
        graph=copy.deepcopy(original_graph)
        merge_choices=merge_choices or {}
        if not isinstance(merge_choices,dict):raise ValueError("同名定义处理选项无效")
        if action=='verify':
            if not graph:graph={'atoms':[],'edges':[]}
            if not isinstance(selected,list) or not selected or any(not isinstance(x,str) for x in selected):
                raise ValueError('请选择要导入的知识候选')
            candidates=[c for c in result['candidates'] if c['id'] in selected]
            if len(candidates)!=len(set(selected)):raise ValueError('候选编号无效')
            if any(not c['quality']['grounded'] for c in candidates):raise ValueError('来源或质量检查未通过，不能进入正式图谱')
            referenced_docs={r['document_id'] for c in candidates for r in c['source_reference']}
            unresolved={c['id'] for c in self.conflicts(session_id,course_id) if not c['confirmed'] and (referenced_docs.intersection((c['source_a'],c['source_b'])) or c['id'] in result.get('conflict_ids',[]))}
            if unresolved:raise ValueError('外部资料存在不同表述/事实冲突，请先确认冲突记录中的教学表达')
            mapping={a['id']:a['id'] for a in graph['atoms']};existing={a['title'].casefold():a for a in graph['atoms']}
            for candidate in candidates:
                if candidate['title'].casefold() in existing:
                    atom=existing[candidate['title'].casefold()]
                    mapping[candidate['id']]=atom['id']
                    if atom['summary'].strip()!=candidate['summary'].strip():
                        choice=merge_choices.get(candidate['id'])
                        if choice not in ('replace','keep'):
                            raise ValueError('同名知识点的定义不同，请对照新旧定义后选择替换或保留')
                        candidate['merge_choice']=choice
                        if choice=='keep':
                            # A rejected new definition cannot certify the retained definition.
                            candidate['quality_status']='deprecated'
                            mapping.pop(candidate['id'],None)
                            continue
                        for key in ('summary','why','type','depth','source_reference'):
                            atom[key]=copy.deepcopy(candidate[key])
                    else:
                        references=atom.setdefault('source_reference',[])
                        for reference in candidate['source_reference']:
                            if reference not in references:references.append(reference)
                else:
                    identifier='p_'+secrets.token_hex(8);mapping[candidate['id']]=identifier
                    atom={k:v for k,v in candidate.items() if k!='quality'};atom['id']=identifier
                    graph['atoms'].append(atom);existing[atom['title'].casefold()]=atom
                atom['quality_status']='verified'
                atom['quality_review']={'meaning':'用户审查通过，非独立事实认证','feedback':feedback,
                                        'reviewed_at':datetime.now(timezone.utc).isoformat(timespec='seconds'),
                                        'quality_factors':candidate['quality']}
            for edge in result['relations']:
                if edge['from'] in mapping and edge['to'] in mapping and mapping[edge['from']]!=mapping[edge['to']]:
                    graph['edges'].append({**edge,'from':mapping[edge['from']],'to':mapping[edge['to']]})
            graph=validate_graph(graph,len(course['sections']),require_coverage=False)
        for candidate in result['candidates']:
            candidate['quality_status']='verified' if action=='verify' and candidate['id'] in selected and candidate.get('merge_choice')!='keep' else 'deprecated'
            candidate['quality']['user_feedback']=feedback or ('用户审查通过' if candidate['quality_status']=='verified' else '用户未采纳')
        result['imported_count']=sum(c['quality_status']=='verified' for c in result['candidates'])
        result['retained_count']=sum(c.get('merge_choice')=='keep' for c in result['candidates'])
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            current=db.execute('SELECT status FROM production_batches WHERE id=?',(batch_id,)).fetchone()
            if current[0]!='candidate':raise ValueError('批次已变化，请刷新')
            # Serialize read/modify/write against another import; stale snapshots must not overwrite.
            if action=='verify':
                pending=db.execute('SELECT source_a,source_b FROM source_conflicts WHERE course_id=? AND confirmed=0',(course_id,)).fetchall()
                if any(referenced_docs.intersection((r[0],r[1])) for r in pending):raise ValueError('存在尚未确认的来源冲突，请先核对双方原文')
                latest=db.execute('SELECT graph_json FROM course_graphs WHERE course_id=?',(course_id,)).fetchone()
                if (json.loads(latest[0]) if latest else None)!=original_graph:raise ValueError('图谱已变化，请重新审查')
                from .revisions import bump_revision,archive
                if original_graph and graph!=original_graph:
                    archive(db,course_id,'knowledge',course_id,course['content_revision'],original_graph)
                if graph!=original_graph:bump_revision(db,course_id)
                db.execute('INSERT INTO course_graphs VALUES(?,?,?) ON CONFLICT(course_id) DO UPDATE SET graph_json=excluded.graph_json',
                           (course_id,json.dumps(graph,ensure_ascii=False),datetime.now(timezone.utc).isoformat(timespec='seconds')))
            status='verified' if action=='verify' else 'deprecated'
            db.execute('UPDATE production_batches SET status=?,feedback=?,result_json=? WHERE id=?',
                       (status,feedback,json.dumps(result,ensure_ascii=False),batch_id))
            db.execute('UPDATE source_documents SET processing_status=? WHERE id=?',(status,batch['source_id']))
        return self.batch(session_id,course_id,batch_id)
