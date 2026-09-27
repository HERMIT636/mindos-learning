"""Small public demo diagnostics and an explainable learning path."""

from __future__ import annotations

from graphlib import TopologicalSorter


DIAGNOSTICS = {
    "python-foundations": [
        {"id": "diagnose-function", "concept_id": "functions", "dimension_id": "understanding", "prompt": "已定义 def greet(name): return 'Hi ' + name。哪项会把 'Lin' 传入函数并调用它？", "choices": [
            {"id": "a", "text": "greet"}, {"id": "b", "text": "greet('Lin')"}, {"id": "c", "text": "def greet('Lin'):"}], "answer": "b"},
        {"id": "diagnose-return", "concept_id": "return-value", "dimension_id": "understanding", "prompt": "函数内只执行 print(8)，没有 return。调用该函数得到的值是什么？", "choices": [
            {"id": "a", "text": "8"}, {"id": "b", "text": "字符串 '8'"}, {"id": "c", "text": "None"}], "answer": "c"},
    ],
    "linear-algebra": [
        {"id": "diagnose-vector", "concept_id": "vectors", "dimension_id": "understanding", "prompt": "二维向量 (5, -2) 的第一个分量是什么？", "choices": [
            {"id": "a", "text": "5"}, {"id": "b", "text": "-2"}, {"id": "c", "text": "3"}], "answer": "a"},
        {"id": "diagnose-dot", "concept_id": "dot-product", "dimension_id": "calculation", "prompt": "二维向量 (1, 3) 与 (2, 1) 的标准点积是多少？", "choices": [
            {"id": "a", "text": "3"}, {"id": "b", "text": "5"}, {"id": "c", "text": "6"}], "answer": "b"},
    ],
}


def public_diagnostics(pack: dict, answers: dict[str, bool]) -> list[dict]:
    return [
        {key: task[key] for key in ("id", "concept_id", "dimension_id", "prompt", "choices")}
        | {"result": answers.get(task["id"])}
        for task in DIAGNOSTICS.get(pack["id"], [])
    ]


def learning_plan(pack: dict, states: list[dict], answers: dict[str, bool], goal: str | None) -> list[dict]:
    prerequisites = {item["id"]: set() for item in pack["concepts"]}
    for relation in pack["relations"]:
        if relation["type"] == "prerequisite":
            prerequisites[relation["to"]].add(relation["from"])
    order = tuple(TopologicalSorter(prerequisites).static_order())
    concept_by_id = {item["id"]: item for item in pack["concepts"]}
    diagnosed = {task["concept_id"]: answers[task["id"]]
                 for task in DIAGNOSTICS.get(pack["id"], []) if task["id"] in answers}
    target = pack["concepts"][0]["id"] if goal == pack["learning_goals"][0] else pack["concepts"][-1]["id"]
    included = {target}
    while any(prerequisites[item] - included for item in included):
        included.update(*(prerequisites[item] for item in tuple(included)))
    result = []
    for concept_id in order:
        if concept_id not in included:
            continue
        related = [item for item in states if item["concept_id"] == concept_id]
        assessable = [item for item in related if any(
            task["task_type"] in {"single_choice", "numeric"}
            and concept_id in task["concept_ids"] and item["dimension_id"] in task["dimension_ids"]
            for task in pack["tasks"])]
        if assessable and all(item["state"] == "retested" for item in assessable):
            status, reason = "已复测", "不同公开练习形成了复测证据，可继续后续知识点。"
        elif any(item["state"] == "recheck" for item in related):
            status, reason = "待复核", "独立题出现相互矛盾的证据，先回看资料并换题确认。"
        elif any(item["evidence_count"] and item["state"] == "needs_work" for item in related):
            status, reason = "优先补强", "独立作答仍未通过，先回看相关资料并补练。"
        elif any(item["evidence_count"] for item in related):
            status, reason = "继续验证", "已有独立作答证据，还需另一道不同题复测。"
        elif diagnosed.get(concept_id) is False:
            status, reason = "优先补强", "短诊断未通过，先读资料并练习，再做另一道独立题。"
        elif diagnosed.get(concept_id) is True:
            status, reason = "继续验证", "短诊断通过，但仍需新的独立变式题验证。"
        else:
            status, reason = "待诊断", "完成短诊断后再确定这一知识点的起点。"
        prior = [concept_by_id[item]["title"] for item in order if item in prerequisites[concept_id]]
        result.append({"concept_id": concept_id, "title": concept_by_id[concept_id]["title"],
                       "status": status, "reason": reason, "prerequisites": prior})
    return result
