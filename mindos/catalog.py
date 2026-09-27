"""Read public course packs while keeping answer keys on the server."""

from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
COURSES = ROOT / "course-packs"
EXTERNAL_GUIDES = ROOT / "external-resources/curated/concept-guides.json"
EXTERNAL_MANIFESTS = ROOT / "external-resources/manifests"
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
        self.external_guides = self._load_external_guides()

    def _load_external_guides(self) -> list[dict]:
        """Only curated, attributed summaries may enter model retrieval."""
        if not EXTERNAL_GUIDES.is_file():
            return []
        data = json.loads(EXTERNAL_GUIDES.read_text(encoding="utf-8"))
        manifests = {}
        for path in EXTERNAL_MANIFESTS.glob("*-manifest.json"):
            for resource in json.loads(path.read_text(encoding="utf-8"))["resources"]:
                manifests[resource["id"]] = resource
        guides = []
        seen = set()
        for guide in data["guides"]:
            course_id = guide["course_id"]
            if course_id not in self.packs or guide["id"] in seen:
                raise ValueError("外部导读的课程或编号无效")
            seen.add(guide["id"])
            concepts = {item["id"] for item in self.packs[course_id]["concepts"]}
            if not guide["concept_ids"] or not set(guide["concept_ids"]) <= concepts:
                raise ValueError("外部导读的知识点无效")
            if not guide["source_resource_ids"] or any(
                source_id not in manifests or
                manifests[source_id]["rag_index_status"] != "candidate_after_teacher_review" or
                manifests[source_id]["local_path"] == "NOT_DOWNLOADED"
                for source_id in guide["source_resource_ids"]
            ):
                raise ValueError("外部导读引用了未通过初审的来源")
            if not guide["url"].startswith("https://") or not guide["content"].strip():
                raise ValueError("外部导读内容或原文链接无效")
            guides.append(guide)
        return guides

    def external_chunks(self, pack: dict, concept_id: str | None = None) -> list[dict]:
        """Attributed editorial drafts for AI grounding, never raw downloaded files."""
        return [
            {"id": guide["id"], "course_id": pack["id"], "course_version": pack["version"],
             "resource_id": guide["id"], "title": guide["title"],
             "content": guide["content"], "concept_ids": guide["concept_ids"],
             "provenance": guide["provenance"], "url": guide["url"]}
            for guide in self.external_guides
            if guide["course_id"] == pack["id"] and
            (concept_id is None or concept_id in guide["concept_ids"])
        ]

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
            for key in ("id", "version", "title", "audience", "learning_goals", "review_status", "dimensions", "concepts", "chapters", "relations")
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

    def lesson_materials(self, pack: dict, concept_id: str) -> list[dict]:
        """Return complete authored lessons, without the retrieval chunk length cap."""
        pack_dir = (COURSES / pack["id"]).resolve()
        materials = []
        for resource in pack["resources"]:
            if concept_id not in resource["concept_ids"]:
                continue
            path = (pack_dir / resource["path"]).resolve()
            if not path.is_relative_to(pack_dir) or path.suffix != ".md":
                raise ValueError("课程资料路径无效")
            relative = path.relative_to(ROOT).as_posix()
            materials.append({
                "title": resource["title"],
                "content": path.read_text(encoding="utf-8").strip(),
                "url": "https://github.com/HERMIT636/mindos-learning/blob/main/" + quote(relative),
                "provenance": resource["provenance"],
            })
        return materials
