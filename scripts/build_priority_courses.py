"""Build the three draft priority course packs from editable authoring files."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
COURSES = ROOT / "course-packs"
IDS = ("machine-learning", "hpc-foundations", "ascend-c-operators")


def question(raw: dict, topic_id: str, suffix: str, diagnostic: bool = False) -> dict:
    choices = [{"id": key, "text": text} for key, text in zip("abc", raw["choices"], strict=True)]
    base = {"id": f"{suffix}-{topic_id}", "prompt": raw["prompt"], "choices": choices}
    if diagnostic:
        return base | {"concept_id": topic_id, "dimension_id": "understanding",
                       "answer": "abc"[raw["answer"]]}
    return base | {"task_type": "single_choice", "purpose": "practice",
                   "concept_ids": [topic_id], "dimension_ids": ["understanding"],
                   "rubric": [{"dimension_id": "understanding",
                               "criterion": "根据概念与例子的条件选择唯一正确项；正确得 1 分，否则 0 分",
                               "max_score": 1}],
                   "reference_answer": "abc"[raw["answer"]]}


def lesson(topic: dict) -> str:
    return (f"# {topic['title']}\n\n"
            "本讲义为 MindOS 原创课程草稿，尚待教师审核。先理解现象与条件，再尝试完整例子。\n\n"
            f"## 为什么要学\n\n{topic['motivation']}\n\n"
            f"## 核心原理\n\n{topic['principle']}\n\n"
            f"## 逐步例子\n\n{topic['example']}\n\n"
            f"## 常见误区与自查\n\n{topic['pitfall']}\n\n"
            "## 学完后的检验\n\n先合上讲义，自己复述：这个方法解决什么问题、前提是什么、"
            "例子中的每一步为何成立、换一组输入时哪些判断必须重做。再完成两道不同的公开练习；"
            "练习表现只是初步证据，不能代替真实项目中的实现与复核。\n\n"
            f"延伸阅读：[原始官方资料]({topic['source']})。本讲义为原创概述，不复制原站正文；"
            "不同软件版本的接口以对应版本官方文档为准。\n")


def build(course_id: str) -> None:
    folder = COURSES / course_id
    authoring = json.loads((folder / "authoring.json").read_text(encoding="utf-8"))
    topics = authoring["topics"]
    ids = [item["id"] for item in topics]
    if len(ids) != len(set(ids)) or not ids:
        raise ValueError(f"{course_id}: 知识点编号重复或为空")
    if any(prior not in ids or prior == topic["id"]
           for topic in topics for prior in topic.get("prerequisites", [])):
        raise ValueError(f"{course_id}: 先修知识点无效")
    chapters = [{"id": item["id"], "title": item["title"],
                 "concept_ids": [topic["id"] for topic in topics if topic["chapter"] == item["id"]]}
                for item in authoring["chapters"]]
    if sorted(sum((item["concept_ids"] for item in chapters), [])) != sorted(ids):
        raise ValueError(f"{course_id}: 章节必须覆盖每个知识点")

    materials = folder / "materials"
    materials.mkdir(exist_ok=True)
    for topic in topics:
        if len(topic["questions"]) != 3 or any(len(item["choices"]) != 3 or item["answer"] not in (0, 1, 2)
                                               for item in topic["questions"]):
            raise ValueError(f"{course_id}/{topic['id']}: 需三道三选一题")
        (materials / f"{topic['id']}.md").write_text(lesson(topic), encoding="utf-8")

    manifest = {
        "$schema": "../../schemas/course-pack.schema.json", "schema_version": "0.1.0",
        "id": course_id, "version": "0.1.0", "title": authoring["title"],
        "language": "zh-CN", "level": authoring["level"], "audience": authoring["audience"],
        "license": "MIT", "review_status": "draft", "learning_goals": authoring["learning_goals"],
        "dimensions": [{"id": "understanding", "label": "概念理解与判断",
                        "description": "能解释适用前提、关键步骤与常见错误；公开单选题仅提供初步证据"}],
        "concepts": [{"id": topic["id"], "title": topic["title"], "dimension_ids": ["understanding"]}
                     for topic in topics],
        "chapters": chapters,
        "relations": [{"from": prior, "to": topic["id"], "type": "prerequisite"}
                      for topic in topics for prior in topic.get("prerequisites", [])],
        "diagnostics": [question(topic["questions"][0], topic["id"], "diagnose", True)
                        for topic in topics],
        "resources": [{"id": f"{topic['id']}-note", "title": f"{topic['title']}讲义",
                       "path": f"materials/{topic['id']}.md", "concept_ids": [topic["id"]],
                       "license": "MIT", "provenance": "MindOS 原创课程草稿；末尾列出官方延伸阅读；待教师审核"}
                      for topic in topics],
        "tasks": [question(raw, topic["id"], f"practice-{index}")
                  for topic in topics for index, raw in enumerate(topic["questions"][1:], start=1)],
    }
    (folder / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{course_id}: {len(topics)} 个知识点，{len(chapters)} 章，{len(manifest['tasks'])} 道公开练习")


if __name__ == "__main__":
    for name in IDS:
        build(name)
