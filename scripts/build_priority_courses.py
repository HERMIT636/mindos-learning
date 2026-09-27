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
    terms = "\n".join(f"- **{item['name']}**：{item['meaning']}" for item in topic["beginner_terms"])
    worked_steps = "\n\n".join(f"### {index}. {item['title']}\n\n{item['text']}"
                               for index, item in enumerate(topic.get("worked_steps", []), 1))
    return (f"# {topic['title']}\n\n"
            "这是从零开始的 MindOS 课程草稿，尚待教师审核。读不懂某个词时，先看下面的术语，再按步骤阅读；无需先会做题。\n\n"
            f"## 第 0 步：先认清本讲的词\n\n{terms}\n\n"
            f"## 第 1 步：从一个问题出发\n\n{topic['motivation']}\n\n"
            f"## 第 2 步：理解它怎样工作\n\n{topic['principle']}\n\n"
            f"## 第 3 步：跟着例子做\n\n{topic['example']}\n\n"
            + (f"{worked_steps}\n\n" if worked_steps else "") +
            f"## 常见误区与自查\n\n{topic['pitfall']}\n\n"
            f"## 自己试一试\n\n{topic['check']}\n\n"
            "先不用急着做正式练习。能用自己的话说清这道小检查，才进入下一讲；答不出来就回到第 2、3 步。"
            "后面的公开练习只提供初步证据，不能代替真实项目中的实现与复核。\n\n"
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
        if not topic.get("beginner_terms") or not topic.get("check"):
            raise ValueError(f"{course_id}/{topic['id']}: 缺少零基础术语或自查题")
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
