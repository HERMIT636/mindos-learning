"""Explainable demo scoring, evidence states and next-task selection."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from graphlib import TopologicalSorter

from .storage import Storage

OBJECTIVE_TYPES = {"numeric", "single_choice"}
STATE_LABELS = {
    "unassessed": "未评估",
    "needs_work": "需补强",
    "provisional": "初步达标",
    "recheck": "待复核",
    "retested": "复测通过",
}


def assess(task: dict, answer: str) -> bool | None:
    if task["task_type"] == "single_choice":
        if answer not in {choice["id"] for choice in task["choices"]}:
            raise ValueError("请选择题目提供的选项")
        return answer == task["reference_answer"]
    if task["task_type"] == "numeric":
        try:
            submitted = Decimal(answer.strip())
            expected = Decimal(str(task["reference_answer"]))
        except InvalidOperation as exc:
            raise ValueError("请输入有效数字") from exc
        if not submitted.is_finite():
            raise ValueError("请输入有限数字")
        return submitted == expected
    return None


def progress(pack: dict, submissions: list[dict], diagnostic: dict[str, bool] | None = None) -> list[dict]:
    tasks = {task["id"]: task for task in pack["tasks"]}
    latest_by_task = {
        row["task_id"]: row for row in submissions
        if row["counts_for_state"] and row["correct"] is not None and row["task_id"] in tasks
    }
    result = []
    dimensions = {item["id"]: item for item in pack["dimensions"]}
    for concept in pack["concepts"]:
        for dimension_id in concept["dimension_ids"]:
            evidence = [
                row for task_id, row in latest_by_task.items()
                if concept["id"] in tasks[task_id]["concept_ids"]
                and dimension_id in tasks[task_id]["dimension_ids"]
            ]
            passed = sum(row["correct"] == 1 for row in evidence)
            failed = sum(row["correct"] == 0 for row in evidence)
            if passed and failed:
                state = "recheck"
            elif passed >= 2:
                state = "retested"
            elif passed:
                state = "provisional"
            elif failed:
                state = "needs_work"
            else:
                state = "unassessed"
            diagnostic_result = (diagnostic or {}).get((concept["id"], dimension_id))
            if state == "unassessed" and diagnostic_result is not None:
                state = "diagnostic_ready" if diagnostic_result else "needs_work"
            result.append({
                "concept_id": concept["id"], "concept_title": concept["title"],
                "dimension_id": dimension_id, "dimension_label": dimensions[dimension_id]["label"],
                "state": state, "state_label": ("诊断通过·待复测" if state == "diagnostic_ready" else
                    "诊断薄弱·待补强" if state == "needs_work" and not evidence and diagnostic_result is False else STATE_LABELS[state]),
                "passed_tasks": passed, "failed_tasks": failed,
                "evidence_count": len(evidence), "diagnostic_result": diagnostic_result,
            })
    return result


def recommendation(pack: dict, states: list[dict], submissions: list[dict], helped: set[str],
                   allowed_concepts: set[str] | None = None) -> dict | None:
    prerequisites = {concept["id"]: set() for concept in pack["concepts"]}
    for relation in pack["relations"]:
        if relation["type"] == "prerequisite":
            prerequisites[relation["to"]].add(relation["from"])
    order = tuple(TopologicalSorter(prerequisites).static_order())
    seen = {row["task_id"] for row in submissions} | helped
    for concept_id in order:
        if allowed_concepts is not None and concept_id not in allowed_concepts:
            continue
        for item in states:
            if item["concept_id"] != concept_id or item["state"] == "retested":
                continue
            candidates = [task for task in pack["tasks"]
                          if task["task_type"] in OBJECTIVE_TYPES
                          and concept_id in task["concept_ids"]
                          and item["dimension_id"] in task["dimension_ids"]
                          and task["id"] not in seen]
            if not candidates:
                continue
            task = candidates[0]
            reason = (
                f"{item['concept_title']} · {item['dimension_label']}：{item['state_label']}。"
                + ("先完成这一先修知识点。" if any(
                    relation["from"] == concept_id and relation["type"] == "prerequisite"
                    for relation in pack["relations"]) else "用一道新的独立题检查掌握情况。")
            )
            return {"task_id": task["id"], "reason": reason}
    return None


def submit(storage: Storage, session_id: str, pack: dict, task: dict,
           answer: str, requested_mode: str) -> dict:
    if requested_mode not in {"practice", "independent"}:
        raise ValueError("作答模式无效")
    if not isinstance(answer, str) or not answer.strip() or len(answer) > 2000:
        raise ValueError("请提交 1 至 2000 字的答案")
    correct = assess(task, answer)
    mode = requested_mode if correct is not None else "practice"
    previous = storage.submissions(session_id, pack["id"], pack["version"])
    practiced_before = any(row["task_id"] == task["id"] and row["mode"] == "practice" for row in previous)
    helped_before = task["id"] in storage.helped_tasks(session_id, pack)
    counts = mode == "independent" and not practiced_before and not helped_before
    storage.add_submission(session_id, pack, task["id"], mode, answer, correct, counts)
    if correct is None:
        message = "作答已保存。这类题目尚需人工审核或隔离测试，本次不更新掌握状态。"
    elif mode == "practice":
        message = "练习结果已记录；练习不计入独立掌握证据。"
    elif not counts:
        message = "这道题之前已练习或查看过资料，本次结果不计入独立掌握证据。"
    elif correct:
        message = "独立作答正确；已记录为一份证据。复测需另一道不同的题。"
    else:
        message = "独立作答未通过；已记录待补强证据。可查看课程材料后再练习。"
    return {"task_id": task["id"], "mode": mode, "correct": correct,
            "counts_for_state": counts, "message": message}
