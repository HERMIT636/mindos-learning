"""Course-scoped knowledge structure, evidence and review recommendations."""
from __future__ import annotations

import json
import re
import secrets
from datetime import datetime, timezone

ATOM_TYPES = {'concept', 'mechanism', 'operation', 'relation', 'reason', 'rule', 'skill'}
RELATIONS = {'prerequisite', 'part_of', 'related', 'causes', 'similar', 'contrasts', 'applied_in', 'implements', 'extends'}

SCHEMA = """
CREATE TABLE IF NOT EXISTS course_graphs (
 course_id TEXT PRIMARY KEY REFERENCES courses(id), graph_json TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS atom_content (
 course_id TEXT NOT NULL REFERENCES courses(id), atom_id TEXT NOT NULL, mode TEXT NOT NULL,
 content TEXT NOT NULL, created_at TEXT NOT NULL, PRIMARY KEY(course_id,atom_id,mode)
);
CREATE TABLE IF NOT EXISTS atom_turns (
 id INTEGER PRIMARY KEY, course_id TEXT NOT NULL REFERENCES courses(id), atom_id TEXT NOT NULL,
 role TEXT NOT NULL, content TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS learning_events (
 id INTEGER PRIMARY KEY, course_id TEXT NOT NULL REFERENCES courses(id), atom_id TEXT NOT NULL,
 kind TEXT NOT NULL, created_at TEXT NOT NULL
);
"""

def timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def validate_graph(value: dict, section_count: int, *, require_coverage=True) -> dict:
    if not isinstance(value, dict) or not isinstance(value.get('atoms'), list):
        raise ValueError('知识地图结构无效')
    atoms, edges = value['atoms'], value.get('edges', [])
    if not (section_count if require_coverage else 1) <= len(atoms) <= min(96, section_count * 6) or not isinstance(edges, list) or len(edges) > 240:
        raise ValueError('每节需要 1—6 个知识原子，整门课程最多 96 个')
    ids, titles, covered = set(), set(), set()
    clean = []
    for atom in atoms:
        if not isinstance(atom, dict):
            raise ValueError('知识原子格式无效')
        identifier, ordinal = atom.get('id'), atom.get('section')
        if (not isinstance(identifier, str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,60}', identifier)
                or identifier in ids or not isinstance(ordinal, int) or isinstance(ordinal, bool)
                or not 1 <= ordinal <= section_count or not isinstance(atom.get('type'), str)
                or atom['type'] not in ATOM_TYPES):
            raise ValueError('知识原子编号、类型或所属小节无效')
        fields = {}
        for key, limit in [('title', 80), ('summary', 240), ('why', 240)]:
            content = atom.get(key)
            if not isinstance(content, str) or not 2 <= len(content.strip()) <= limit:
                raise ValueError('知识原子的名称、定义与用途不完整')
            fields[key] = content.strip()
        if fields['title'].casefold() in titles:
            raise ValueError('同一课程不要重复拆分相同知识原子')
        depth = atom.get('depth', 2)
        if not isinstance(depth, int) or isinstance(depth, bool) or not 1 <= depth <= 5:
            raise ValueError('学习深度应为 1—5')
        extras = {}
        references = atom.get('source_reference', [])
        if not isinstance(references, list) or len(references) > 40 or any(not isinstance(r, dict) for r in references):
            raise ValueError('原子来源引用格式无效')
        extras['source_reference'] = references
        status = atom.get('quality_status', 'candidate')
        if status not in ('candidate', 'verified', 'deprecated'):
            raise ValueError('知识质量状态无效')
        extras['quality_status'] = status
        extras['knowledge_role']='reviewed_knowledge' if status=='verified' and references else 'planning_index'
        if isinstance(atom.get('quality_review'), dict): extras['quality_review'] = atom['quality_review']
        ids.add(identifier); titles.add(fields['title'].casefold()); covered.add(ordinal)
        clean.append({'id': identifier, 'section': ordinal, 'type': atom['type'],
                      'depth': depth, **fields, **extras})
    if require_coverage and covered != set(range(1, section_count + 1)):
        raise ValueError('知识地图必须覆盖每个小节')
    if any(sum(a['section'] == n for a in clean) > 6 for n in covered):
        raise ValueError('单个小节拆分过细，请控制在 6 个原子以内')
    links, seen = [], set()
    dependency = {identifier: [] for identifier in ids}
    for edge in edges:
        if not isinstance(edge, dict):
            raise ValueError('知识关系格式无效')
        source, target, kind = edge.get('from'), edge.get('to'), edge.get('type')
        if (not isinstance(source, str) or not isinstance(target, str) or source not in ids
                or target not in ids or source == target or not isinstance(kind, str) or kind not in RELATIONS):
            raise ValueError('知识关系必须连接本课程不同的原子')
        key = (source, target, kind)
        if key in seen:
            continue
        seen.add(key); links.append({'from': source, 'to': target, 'type': kind})
        if kind == 'prerequisite':
            dependency[source].append(target)
    visited, active = set(), set()
    def visit(node):
        if node in active:
            raise ValueError('前置知识关系存在循环，请重新生成')
        if node in visited:
            return
        active.add(node)
        for target in dependency[node]:
            visit(target)
        active.remove(node); visited.add(node)
    for identifier in ids:
        visit(identifier)
    return {'atoms': clean, 'edges': links, 'version': 1}


class KnowledgeStorage:
    def _knowledge_course(self, session_id, course_id):
        course = self.course(session_id, course_id)
        if not course:
            raise ValueError('课程不存在')
        return course

    def graph(self, session_id, course_id):
        self._knowledge_course(session_id, course_id)
        with self.connect() as db:
            row = db.execute('SELECT graph_json FROM course_graphs WHERE course_id=?', (course_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def save_graph(self, session_id, course_id, value):
        course = self._knowledge_course(session_id, course_id)
        graph = validate_graph(value, len(course['sections']))
        with self.connect() as db:
            db.execute('INSERT OR IGNORE INTO course_graphs VALUES(?,?,?)',
                       (course_id, json.dumps(graph, ensure_ascii=False), timestamp()))
        return self.graph(session_id, course_id)

    def complete_index(self,session_id,course_id,value,expected_graph):
        """Fill missing sections with unreviewed index nodes; never replace reviewed atoms."""
        import copy,secrets
        course=self._knowledge_course(session_id,course_id)
        incoming=validate_graph(value,len(course['sections']))
        graph=copy.deepcopy(expected_graph or {'atoms':[],'edges':[]})
        covered={a['section'] for a in graph['atoms'] if a.get('quality_status')!='deprecated'}
        missing=set(range(1,len(course['sections'])+1))-covered
        titles={a['title'].casefold() for a in graph['atoms']};mapping={}
        for atom in incoming['atoms']:
            if atom['section'] not in missing or atom['title'].casefold() in titles:continue
            identifier=atom['id'] if not any(a['id']==atom['id'] for a in graph['atoms']) else 'i_'+secrets.token_hex(8);mapping[atom['id']]=identifier
            graph['atoms'].append({**atom,'id':identifier,'source_reference':[],'quality_status':'candidate'})
            titles.add(atom['title'].casefold())
        for section in course['sections']:
            if section['ordinal'] in missing and not any(a['section']==section['ordinal'] for a in graph['atoms']):
                label=(section['title']+' · 小节索引')[:80]
                graph['atoms'].append({'id':'i_'+secrets.token_hex(8),'section':section['ordinal'],'title':label,'summary':section['objective'][:240] or '本节学习目标','why':'用于规划本节学习，待资料审查','type':'concept','depth':2,'quality_status':'candidate','source_reference':[]})
        graph['edges'] += [{**e,'from':mapping[e['from']],'to':mapping[e['to']]} for e in incoming['edges'] if e['from'] in mapping and e['to'] in mapping]
        graph=validate_graph(graph,len(course['sections']))
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            latest=db.execute('SELECT graph_json FROM course_graphs WHERE course_id=?',(course_id,)).fetchone()
            if (json.loads(latest[0]) if latest else None)!=expected_graph:raise ValueError('知识地图已变化，请重新补全索引')
            db.execute('INSERT INTO course_graphs VALUES(?,?,?) ON CONFLICT(course_id) DO UPDATE SET graph_json=excluded.graph_json',(course_id,json.dumps(graph,ensure_ascii=False),timestamp()))
            from .revisions import bump_revision
            bump_revision(db,course_id)
        return graph

    def atom(self, session_id, course_id, atom_id, *, unlocked=False):
        if not isinstance(atom_id, str):
            raise ValueError('知识原子编号无效')
        course = self._knowledge_course(session_id, course_id)
        graph = self.graph(session_id, course_id)
        atom = next((a for a in (graph or {}).get('atoms', []) if a['id'] == atom_id), None)
        if not atom:
            raise ValueError('本课程没有这个知识原子，请先生成知识地图')
        if unlocked and atom['section'] > course['current_ordinal']:
            raise ValueError('该原子属于未来小节，请在章节模式中主动进入对应小节')
        return atom

    def learning_event(self, session_id, course_id, atom_ids, kind):
        if kind not in ('read', 'review'):
            raise ValueError('学习事件无效')
        for identifier in atom_ids:
            self.atom(session_id, course_id, identifier, unlocked=True)
        with self.connect() as db:
            db.executemany('INSERT INTO learning_events(course_id,atom_id,kind,created_at) VALUES(?,?,?,?)',
                           [(course_id, a, kind, timestamp()) for a in dict.fromkeys(atom_ids)])
            from .learning.service import LearningLoopService
            LearningLoopService(self).signal(db,session_id,course_id,None,list(dict.fromkeys(atom_ids)),'self_explanation','read:'+str(db.execute('SELECT MAX(id) FROM learning_events').fetchone()[0]),{'activity':kind})

    def atom_detail(self, session_id, course_id, atom_id):
        atom = self.atom(session_id, course_id, atom_id, unlocked=True)
        with self.connect() as db:
            content = db.execute('SELECT mode,content,content_revision FROM atom_content WHERE course_id=? AND atom_id=?',
                                 (course_id, atom_id)).fetchall()
            turns = db.execute('SELECT role,content,created_at FROM atom_turns WHERE course_id=? AND atom_id=? ORDER BY id',
                               (course_id, atom_id)).fetchall()
            quizzes = db.execute("SELECT * FROM quizzes WHERE course_id=? AND target_atom_id=? AND scope='atom' ORDER BY rowid",
                                 (course_id, atom_id)).fetchall()
        revision=self._knowledge_course(session_id,course_id)['content_revision']
        return {'content_history':{mode:self.content_versions(session_id,course_id,'atom_'+mode,atom_id) for mode in ('quick','deep')},'content_metadata':{r['mode']:{'revision':r['content_revision'],'stale':r['content_revision']!=revision} for r in content},'atom': atom, 'content': {row['mode']: row['content'] for row in content},
                'turns': [dict(row) for row in turns], 'quizzes': [self._quiz_public(dict(row)) for row in quizzes]}

    def save_atom_content(self, session_id, course_id, atom_id, mode, content, *, expected_revision=None, regenerate=False):
        self.atom(session_id, course_id, atom_id, unlocked=True)
        if mode not in ('quick', 'deep') or not isinstance(content, str) or not content.strip():
            raise ValueError('原子讲解格式无效')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            revision=db.execute('SELECT content_revision FROM courses WHERE id=?',(course_id,)).fetchone()[0]
            if expected_revision is not None and expected_revision!=revision:raise ValueError('课程依据已更新，请重新生成知识点讲解')
            if regenerate:
                old=db.execute('SELECT * FROM atom_content WHERE course_id=? AND atom_id=? AND mode=?',(course_id,atom_id,mode)).fetchone()
                if old:
                    from .revisions import archive
                    archive(db,course_id,'atom_'+mode,atom_id,old['content_revision'],dict(old))
                    db.execute('DELETE FROM atom_content WHERE course_id=? AND atom_id=? AND mode=?',(course_id,atom_id,mode))
            db.execute('INSERT OR IGNORE INTO atom_content(course_id,atom_id,mode,content,created_at,content_revision) VALUES(?,?,?,?,?,?)',
                       (course_id, atom_id, mode, content, timestamp(),revision))

    def atom_exchange(self, session_id, course_id, atom_id, question, answer):
        self.atom(session_id, course_id, atom_id, unlocked=True)
        with self.connect() as db:
            db.executemany('INSERT INTO atom_turns(course_id,atom_id,role,content,created_at) VALUES(?,?,?,?,?)',
                           [(course_id, atom_id, role, text, timestamp()) for role, text in
                            [('user', question), ('assistant', answer)]])
            from .learning.evidence import mark_help
            from .learning.service import LearningLoopService
            mark_help(db,course_id,atom=atom_id)
            LearningLoopService(self).signal(db,session_id,course_id,None,[atom_id],'tutor_interaction','atom-turn:'+str(db.execute('SELECT MAX(id) FROM atom_turns').fetchone()[0]))

    def knowledge_state(self, session_id, course_id):
        course = self._knowledge_course(session_id, course_id)
        graph = self.graph(session_id, course_id)
        if not graph:
            return {'ready': False, 'atoms': [], 'edges': [], 'queue': [], 'diagnostics': []}
        with self.connect() as db:
            events = db.execute('SELECT atom_id,MAX(created_at) AS recent FROM learning_events WHERE course_id=? GROUP BY atom_id',
                                (course_id,)).fetchall()
            tests = db.execute('SELECT * FROM quizzes WHERE course_id=? AND submitted_at IS NOT NULL ORDER BY submitted_at,rowid',
                               (course_id,)).fetchall()
            diagnostics = db.execute("SELECT * FROM quizzes WHERE course_id=? AND scope='diagnostic' ORDER BY rowid",
                                     (course_id,)).fetchall()
        read = {r['atom_id']: r['recent'] for r in events}
        evidence = {a['id']: [] for a in graph['atoms']}
        for row in tests:
            scores = {}
            for question, answer, given in zip(json.loads(row['questions_json']), json.loads(row['answers_json']),
                                                json.loads(row['user_answers_json'])):
                for identifier in question.get('atom_ids', []):
                    if identifier in evidence:
                        scores.setdefault(identifier, []).append(given == answer['answer'])
            for identifier, answers in scores.items():
                evidence[identifier].append({'rate': sum(answers) / len(answers), 'count': len(answers),
                                             'date': row['submitted_at'], 'scope': row['scope']})
        from .learning.service import LearningLoopService
        loop=LearningLoopService(self).snapshot(session_id,course_id)
        states=loop['states']
        atoms = []
        queue = []
        for atom in graph['atoms']:
            trials = evidence[atom['id']]
            recent = trials[-2:]
            rate = round(sum(t['rate'] * t['count'] for t in recent) / sum(t['count'] for t in recent) * 100) if recent else None
            status = ('未测' if rate is None else '需补强' if rate < 60 else
                      '正在掌握' if rate < 85 or len(trials) < 2 else '较稳固')
            last = max([t['date'] for t in trials] + [read.get(atom['id'], '')])
            overdue = any(r['atom_id']==atom['id'] for r in loop['review_queue'])
            public = {**atom, 'read': atom['id'] in read, 'rate': rate, 'status': status,
                      'test_count': len(trials), 'evidence_count': sum(t['count'] for t in trials),
                      'last_activity': last or None, 'knowledge_state':states.get(atom['id']), 'unlocked': atom['section'] <= course['current_ordinal']}
            atoms.append(public)
            if public['unlocked']:
                if rate is not None and rate < 60:
                    reason, priority = '最近测试有错题，建议定点补强', 0
                elif overdue:
                    reason, priority = '到了回忆检测时间，建议先回忆再复习', 1
                elif public['read'] and rate is None:
                    reason, priority = '已阅读但未测试，建议检查理解', 2
                elif not public['read']:
                    reason, priority = '尚未记录阅读，可随本节系统学习', 3
                else:
                    continue
                queue.append({'atom_id': atom['id'], 'title': atom['title'], 'reason': reason, 'priority': priority})
        queue.sort(key=lambda item: item['priority'])
        tested = [a for a in atoms if a['rate'] is not None]
        return {'ready': True, 'structure_complete':{a['section'] for a in atoms}==set(range(1,len(course['sections'])+1)),
                'reviewed_count':sum(a.get('quality_status')=='verified' and bool(a.get('source_reference')) for a in atoms),
                'index_count':sum(not(a.get('quality_status')=='verified' and a.get('source_reference')) for a in atoms),
                'atoms': atoms, 'edges': graph['edges'], 'queue': queue[:8],
                'read_count': sum(a['read'] for a in atoms), 'tested_count': len(tested), 'total': len(atoms),
                'overall_rate': round(sum(a['rate'] for a in tested) / len(tested)) if tested else None,
                'diagnostics': [self._quiz_public(dict(row)) for row in diagnostics],
                'rule': 'recent-two-tests-v1', 'review_rule': loop['policy_version'], 'learning_loop':loop}

    def create_knowledge_quiz(self, session_id, course_id, section_id, questions, answers, scope, target=''):
        course = self._knowledge_course(session_id, course_id)
        if scope not in ('atom', 'diagnostic'):
            raise ValueError('测试类型无效')
        if scope == 'atom':
            atom = self.atom(session_id, course_id, target, unlocked=True)
            if course['sections'][atom['section'] - 1]['id'] != section_id:
                raise ValueError('原子测试所属章节不一致')
        allowed = {a['id'] for a in (self.graph(session_id, course_id) or {}).get('atoms', [])
                   if a['section'] <= course['current_ordinal']}
        if scope == 'atom':
            allowed &= {target}
        else:
            allowed &= {a['id'] for a in self.graph(session_id, course_id)['atoms'] if a['section'] == 1}
        if not questions or len(questions) != len(answers) or any(
            not isinstance(q.get('atom_ids'), list) or not q['atom_ids'] or
            any(not isinstance(a, str) or a not in allowed for a in q['atom_ids']) for q in questions):
            raise ValueError('测试题必须关联本课程已开放的知识原子')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            pending = db.execute('SELECT * FROM quizzes WHERE course_id=? AND scope=? AND target_atom_id=? '
                                 'AND submitted_at IS NULL LIMIT 1', (course_id, scope, target)).fetchone()
            if pending:
                return self._quiz_public(dict(pending))
            identifier = secrets.token_urlsafe(16)
            db.execute('INSERT INTO quizzes(id,course_id,section_id,questions_json,answers_json,created_at,scope,target_atom_id) '
                       'VALUES(?,?,?,?,?,?,?,?)', (identifier, course_id, section_id, json.dumps(questions, ensure_ascii=False),
                        json.dumps(answers, ensure_ascii=False), timestamp(), scope, target))
            row = db.execute('SELECT * FROM quizzes WHERE id=?', (identifier,)).fetchone()
        return self._quiz_public(dict(row))
