"""Lesson scope planning and conservative content checks; no mastery writes."""
from __future__ import annotations

import json
import re

FIELDS = ('purpose', 'core_atoms', 'related_atoms', 'future_atoms', 'difficulty', 'teaching_depth')
RULES = (
    '当前核心知识详细解释（Level 3）；相关知识只作简短辅助说明（Level 1）；'
    '后续知识不主动展开（Level 0），必要时只提名称和作用。不要一次讲完整课程。'
    '导引课使用背景、直觉和学习路线，不强行加入后续公式、完整推导或实现代码。'
    '已讲知识只按本节需要回顾，不能把生成过讲解当成学生已经理解或掌握。'
    '用户主动问后续知识时可以回答：先标明属于后续小节，再给直观解释；'
    '详细计算留在相应小节。用户要求继续时仍只继续当前小节，不自动推进课程。'
)


def names(value):
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            value = []
    if not isinstance(value, list):
        return []
    return list(dict.fromkeys(s.strip() for s in value if isinstance(s, str) and 0 < len(s.strip()) <= 100))[:64]


def metadata(section, course=None):
    introductory = bool(re.search(r'导引|导论|概览|学习路线|课程介绍|课程背景|预备知识|入门介绍', section['title']))
    return {
        'purpose': section['purpose'].strip()[:500] if isinstance(section.get('purpose'), str) and section['purpose'].strip()
        else section.get('objective', ''),
        **{key: names(section.get(key, [])) for key in ('core_atoms', 'related_atoms', 'future_atoms')},
        'difficulty': section.get('difficulty') if section.get('difficulty') in ('beginner', 'basic', 'intermediate', 'advanced')
        else {'入门': 'beginner', '基础': 'basic', '进阶': 'intermediate', '高级': 'advanced'}.get((course or {}).get('level'), 'beginner'),
        'teaching_depth': 'conceptual' if section.get('teaching_depth')=='concept' else section.get('teaching_depth') if section.get('teaching_depth') in ('introductory', 'conceptual', 'detailed')
        else ('introductory' if introductory else 'detailed'),
    }


def migrate_teaching(db):
    columns = {r[1] for r in db.execute('PRAGMA table_info(sections)')}
    for key in FIELDS:
        if key not in columns:
            default = '[]' if key.endswith('_atoms') else ''
            db.execute(f"ALTER TABLE sections ADD COLUMN {key} TEXT NOT NULL DEFAULT '{default}'")
    db.execute("UPDATE sections SET purpose=objective WHERE purpose=''")
    db.executescript('''
        CREATE TABLE IF NOT EXISTS lesson_teaching_records (
          id INTEGER PRIMARY KEY, user_id TEXT NOT NULL,
          course_id TEXT NOT NULL REFERENCES courses(id), lesson_id TEXT NOT NULL REFERENCES sections(id),
          covered_atoms TEXT NOT NULL, created_time TEXT NOT NULL,
          context_json TEXT NOT NULL, validation_json TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS teaching_scope ON lesson_teaching_records(user_id,course_id,lesson_id,id);
    ''')


class TeachingOrchestrator:
    def __init__(self, store):
        self.store = store

    def context(self, session, course_id, lesson_id):
        course = self.store.course(session, course_id)
        if not course:
            raise ValueError('课程不存在')
        section = next((s for s in course['sections'] if s['id'] == lesson_id), None)
        if not section or section['ordinal'] > course['current_ordinal']:
            raise ValueError('小节尚未开放或不属于当前课程')
        graph = self.store.graph(session, course_id) or {}
        atoms = [a for a in graph.get('atoms', []) if a.get('quality_status') != 'deprecated']
        data = metadata(section, course)
        current_atoms = [a for a in atoms if a['section'] == section['ordinal']]
        core = names(data['core_atoms'] + [a['title'] for a in current_atoms]) or [section['title']]
        core_ids = {a['id'] for a in current_atoms}
        earlier = {a['id']: a for a in atoms if a['section'] < section['ordinal']}
        related = names(data['related_atoms'] + [earlier[e['from']]['title'] for e in graph.get('edges', [])
                        if e['type'] == 'prerequisite' and e['to'] in core_ids and e['from'] in earlier])
        future = names(data['future_atoms'] + [a['title'] for a in atoms if a['section'] > section['ordinal']]
                       + [name for s in course['sections'] if s['ordinal'] > section['ordinal'] for name in names(s.get('core_atoms', []))]
                       + [s['title'] for s in course['sections'] if s['ordinal'] > section['ordinal']])
        # A future topic explicitly allowed as a brief introduction stays Level 1.
        core_keys = {s.casefold() for s in core}
        related = [s for s in related if s.casefold() not in core_keys]
        future = [s for s in future if s.casefold() not in core_keys | {s.casefold() for s in related}]
        with self.store.connect() as db:
            records = [dict(r) for r in db.execute(
                'SELECT covered_atoms,created_time FROM lesson_teaching_records WHERE user_id=? AND course_id=? AND lesson_id=? ORDER BY id DESC LIMIT 8',
                (session, course_id, lesson_id))]
        return {
            'course_id': course_id, 'course': course['title'], 'course_goal': course['goal'],
            'lesson_id': lesson_id, 'lesson': section['title'], 'ordinal': section['ordinal'],
            'purpose': data['purpose'], 'learner_level': course.get('learner_level', '零基础'),
            'difficulty': data['difficulty'], 'teaching_depth': data['teaching_depth'],
            'course_revision':course['content_revision'],
            'knowledge_boundary':'课程索引用于教学规划；只有有效原文引用且用户确认的知识才标为已审查，均不代表独立事实认证',
            'core_atoms': core, 'related_atoms': related, 'future_atoms': future,
            'exposure': [{'knowledge': s, 'level': level} for level, group in ((3, core), (1, related), (0, future)) for s in group],
            'curriculum': [{'ordinal': s['ordinal'], 'title': s['title'], 'objective': s['objective']} for s in course['sections']],
            'previous_teaching': [{'covered_atoms': names(r['covered_atoms']), 'created_time': r['created_time']} for r in records],
            'rules': RULES, 'scope_version': 1,
        }


def contains(text, term):
    if re.fullmatch(r'[A-Za-z0-9 _-]+', term):
        return bool(re.search(r'(?<![A-Za-z0-9])' + re.escape(term) + r'(?![A-Za-z0-9])', text, re.I))
    return term.casefold() in text.casefold()


class ContentValidator:
    """Signals of obvious overreach, not a semantic or factual certification."""
    def check(self, content, context):
        issues = []
        blocks = re.split(r'\n\s*\n', content)
        detail = r'=|∑|Σ|softmax\s*\(|```|第[一二三四1234]步|步骤\s*[1234]|逐项.{0,20}(?:相乘|求和)|(?:点积|矩阵乘法).{0,20}(?:逐步|计算过程|展开)'
        def detailed(window):
            if re.search(detail, window, re.I):
                return True
            # Naming components is a brief overview, not an explanation of their structure.
            return bool(re.search(r'残差连接|前馈网络|LayerNorm', window, re.I) and
                        re.search(r'逐层|子层|输入.{0,30}输出|线性变换|非线性|激活函数|两层|相加', window))
        for term in context['future_atoms'] + context['related_atoms']:
            for i, block in enumerate(blocks):
                if not contains(block, term):
                    continue
                target_sentences = [s for s in re.split(r'[。！？]|\n', block) if contains(s, term)]
                if target_sentences and all(re.search(r'后续|以后|后面|留待|稍后', s) and not detailed(s)
                                            for s in target_sentences):
                    continue
                # Headings followed by a calculation must not evade the check.
                window = block
                if len(block.strip()) <= 100 and re.search(r'(?m)^\s*#{1,6}\s', block):
                    window += '\n' + (blocks[i + 1] if i + 1 < len(blocks) else '')
                if detailed(window) or len(window) > 650:
                    issues.append({'code': 'overexposure', 'knowledge': term,
                                   'message': f'对「{term}」的讲解包含详细步骤、公式或过长段落，应缩为简短介绍'})
                    break
        if context['teaching_depth'] == 'introductory':
            equations = len(re.findall(r'(?m)^.*(?:=|∑|Σ).*$', content))
            if equations >= 4 or '```' in content:
                issues.append({'code': 'introductory_depth', 'message': '导引课出现多行公式或代码，请改用背景、直觉与学习路线'})
        return {'passed': not issues, 'score': max(0, 100 - 25 * len(issues)), 'issues': issues,
                'method': 'heuristic_scope_v1', 'boundary': '仅检测明显超纲信号，不代表完整语义检查或事实认证'}


def generate_lesson(model, course, section, mastery, weak_points, context):
    from .model import ModelUnavailable
    section = {**section, 'teaching_context': context}
    validator = ContentValidator()
    lesson = model.teach_section(course, section, mastery, weak_points)
    initial = validator.check(lesson, context)
    if hasattr(model, '_diagnostic'):
        model._diagnostic({'stage': 'teaching_validation', 'lesson_id': section['id'], 'attempt': 1, 'result': initial})
    validation = initial
    if not initial['passed']:
        lesson = model.repair_section(course, section, lesson, initial['issues'])
        validation = validator.check(lesson, context)
        if hasattr(model, '_diagnostic'):
            model._diagnostic({'stage': 'teaching_validation', 'lesson_id': section['id'], 'attempt': 2, 'result': validation})
        if not validation['passed']:
            raise ModelUnavailable('本节讲解仍包含过多后续内容，已停止保存。请重试生成或更换模型。')
    return lesson, {**validation, 'repair_attempts': int(not initial['passed']), 'initial_issues': initial['issues']}
