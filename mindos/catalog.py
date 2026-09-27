"""Read public course packs while keeping answer keys on the server."""

from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
COURSES = ROOT / "course-packs"
PUBLIC_TASK_FIELDS = ("id", "task_type", "purpose", "prompt", "concept_ids", "dimension_ids", "choices")


class Catalog:
    def __init__(self) -> None:
        self.packs: dict[str, dict] = {}
        for manifest in sorted(COURSES.glob("*/manifest.json")):
            pack = json.loads(manifest.read_text(encoding="utf-8"))
            if pack["id"] != manifest.parent.name or not re.fullmatch(r"[a-z][a-z0-9-]*", pack["id"]):
                raise ValueError(f"课程包编号与目录不一致：{manifest}")
            self.packs[pack["id"]] = pack
        if not self.packs:
            raise ValueError("未找到课程包")

    def get(self, course_id: str) -> dict:
        try:
            return self.packs[course_id]
        except KeyError as exc:
            raise KeyError("课程不存在") from exc

    def courses(self) -> list[dict]:
        return [
            {key: pack[key] for key in ("id", "version", "title", "audience", "learning_goals", "review_status")}
            for pack in self.packs.values()
        ]

    def public_course(self, course_id: str) -> dict:
        pack = self.get(course_id)
        return {
            key: pack[key]
            for key in ("id", "version", "title", "audience", "learning_goals", "review_status", "dimensions", "concepts", "relations")
        } | {
            "tasks": [
                {key: task[key] for key in PUBLIC_TASK_FIELDS if key in task}
                for task in pack["tasks"]
            ]
        }

    def task(self, pack: dict, task_id: str) -> dict:
        for task in pack["tasks"]:
            if task["id"] == task_id:
                return task
        raise KeyError("练习不存在")

    def teaching_chunks(self, pack: dict) -> list[dict]:
        chunks: list[dict] = []
        pack_dir = (COURSES / pack["id"]).resolve()
        for resource in pack["resources"]:
            path = (pack_dir / resource["path"]).resolve()
            if not path.is_relative_to(pack_dir) or path.suffix != ".md":
                raise ValueError("课程资料路径无效")
            text = path.read_text(encoding="utf-8")
            sections: list[tuple[str, list[str]]] = []
            title = resource["title"]
            body: list[str] = []
            for line in text.splitlines():
                if line.startswith("## ") and body:
                    sections.append((title, body))
                    title, body = line[3:].strip(), []
                else:
                    body.append(line)
            if body:
                sections.append((title, body))
            for index, (section_title, lines) in enumerate(sections):
                content = "\n".join(lines).strip()
                if not content:
                    continue
                relative = path.relative_to(ROOT).as_posix()
                chunks.append({
                    "id": f"{resource['id']}:{index}",
                    "course_id": pack["id"],
                    "course_version": pack["version"],
                    "resource_id": resource["id"],
                    "title": f"{resource['title']} · {section_title}" if index else resource["title"],
                    "content": content[:2400],
                    "concept_ids": resource["concept_ids"],
                    "provenance": resource["provenance"],
                    "url": "https://github.com/HERMIT636/mindos-learning/blob/main/" + quote(relative),
                })
        return chunks
