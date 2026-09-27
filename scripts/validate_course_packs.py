"""Validate public course-pack structure; never execute course submissions."""

from __future__ import annotations

import json
import sys
from collections import Counter
from graphlib import CycleError, TopologicalSorter
from pathlib import Path

try:
    from jsonschema import Draft202012Validator
except ImportError:
    raise SystemExit("请先安装开发依赖：python -m pip install -r requirements-dev.txt")

ROOT = Path(__file__).resolve().parents[1]


def validate_pack(path: Path, validator: Draft202012Validator) -> list[str]:
    errors: list[str] = []
    try:
        pack = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return [f"无法读取 JSON：{exc}"]

    for error in validator.iter_errors(pack):
        location = ".".join(str(part) for part in error.absolute_path) or "root"
        errors.append(f"{location}: {error.message}")
    if errors:
        return errors

    if pack["id"] != path.parent.name:
        errors.append("课程 id 必须与课程目录名一致")

    for field in ("dimensions", "concepts", "resources", "tasks"):
        duplicates = [key for key, count in Counter(item["id"] for item in pack[field]).items() if count > 1]
        if duplicates:
            errors.append(f"{field} 存在重复编号：{', '.join(duplicates)}")

    dimension_ids = {item["id"] for item in pack["dimensions"]}
    concepts = {item["id"]: item for item in pack["concepts"]}
    concept_ids = set(concepts)
    if "chapters" in pack:
        chapter_ids = [item["id"] for item in pack["chapters"]]
        if len(chapter_ids) != len(set(chapter_ids)):
            errors.append("chapters 存在重复编号")
        covered = []
        for chapter in pack["chapters"]:
            covered.extend(chapter["concept_ids"])
            missing = set(chapter["concept_ids"]) - concept_ids
            if missing:
                errors.append(f"chapter {chapter['id']} 引用了未定义知识点：{', '.join(sorted(missing))}")
        if set(covered) != concept_ids or len(covered) != len(set(covered)):
            errors.append("chapters 必须将每个知识点恰好归入一个章节")

    def check_refs(values: list[str], allowed: set[str], location: str) -> None:
        missing = set(values) - allowed
        if missing:
            errors.append(f"{location} 引用了未定义编号：{', '.join(sorted(missing))}")

    for concept in pack["concepts"]:
        check_refs(concept["dimension_ids"], dimension_ids, f"concept {concept['id']}")

    graph = TopologicalSorter()
    for concept_id in concept_ids:
        graph.add(concept_id)
    for edge in pack["relations"]:
        check_refs([edge["from"], edge["to"]], concept_ids, "relation")
        if edge["from"] == edge["to"]:
            errors.append("知识关系不能连接知识点自身")
        if edge["type"] == "prerequisite":
            graph.add(edge["to"], edge["from"])
    try:
        tuple(graph.static_order())
    except CycleError:
        errors.append("先修关系存在循环")

    for resource in pack["resources"]:
        check_refs(resource["concept_ids"], concept_ids, f"resource {resource['id']}")
        relative_path = Path(resource["path"])
        try:
            resolved = (path.parent / relative_path).resolve()
            if relative_path.is_absolute() or not resolved.is_relative_to(path.parent.resolve()):
                errors.append(f"resource {resource['id']} 路径必须位于课程目录内")
            elif resolved.suffix != ".md" or not resolved.is_file():
                errors.append(f"resource {resource['id']} 需要存在的 Markdown 文件")
            else:
                resolved.read_text(encoding="utf-8")
        except (OSError, ValueError, RuntimeError) as exc:
            errors.append(f"resource {resource['id']} 无法读取：{exc}")

    for task in pack["tasks"]:
        label = f"task {task['id']}"
        if task["task_type"] == "single_choice":
            option_ids = [option["id"] for option in task["choices"]]
            if len(option_ids) != len(set(option_ids)):
                errors.append(f"{label} 选项编号重复")
            if task["reference_answer"] not in option_ids:
                errors.append(f"{label} 参考答案不在选项中")
        check_refs(task["concept_ids"], concept_ids, label)
        check_refs(task["dimension_ids"], dimension_ids, label)
        allowed_dimensions = {
            dimension for concept_id in task["concept_ids"] if concept_id in concepts
            for dimension in concepts[concept_id]["dimension_ids"]
        }
        check_refs(task["dimension_ids"], allowed_dimensions, f"{label} 对应知识点维度")
        rubric_dimensions = {item["dimension_id"] for item in task["rubric"]}
        if rubric_dimensions != set(task["dimension_ids"]):
            errors.append(f"{label} 评分维度必须与任务维度一致")

    return errors


def main() -> int:
    schema = json.loads((ROOT / "schemas/course-pack.schema.json").read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    paths = sorted((ROOT / "course-packs").glob("*/manifest.json"))
    if not paths:
        print("未找到课程包。", file=sys.stderr)
        return 1
    failed = False
    for path in paths:
        errors = validate_pack(path, validator)
        print(f"{'FAIL' if errors else 'OK'} {path.relative_to(ROOT)}")
        for error in errors:
            print(f"  {error}")
        failed = failed or bool(errors)
    if not failed:
        print(f"已通过 {len(paths)} 个课程包的结构检查；教学质量和应用功能未在此验证。")
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
