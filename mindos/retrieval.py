"""Course-scoped teaching retrieval with optional cached dense vectors."""

from __future__ import annotations

import hashlib
import math
import re
from collections import Counter

from .model import ModelGateway, ModelUnavailable
from .storage import Storage

STOP_TERMS = {"什么", "怎么", "如何", "请问", "一下", "是否", "哪个", "哪些", "问题", "解释"}


def terms(text: str) -> Counter[str]:
    result: Counter[str] = Counter()
    for match in re.findall(r"[\u4e00-\u9fff]+|[a-zA-Z_][a-zA-Z_0-9]*|[0-9]+", text.casefold()):
        if re.fullmatch(r"[\u4e00-\u9fff]+", match):
            if len(match) > 1:
                for index in range(len(match) - 1):
                    token = match[index:index + 2]
                    if token not in STOP_TERMS:
                        result[token] += 1
        elif len(match) > 1:
            result[match] += 2
    return result


def cosine(left: list[float], right: list[float]) -> float:
    if len(left) != len(right):
        return 0.0
    norm = math.sqrt(sum(value * value for value in left) * sum(value * value for value in right))
    return sum(a * b for a, b in zip(left, right)) / norm if norm else 0.0


def retrieve(question: str, chunks: list[dict], concept_id: str | None,
             model: ModelGateway, storage: Storage) -> tuple[list[dict], str, str | None]:
    query = terms(question)
    lexical = []
    for chunk in chunks:
        document = terms(chunk["title"] + "\n" + chunk["content"])
        overlap = sum(min(weight, document[token]) for token, weight in query.items())
        lexical.append(float(overlap))
    semantic = [0.0] * len(chunks)
    notice = None
    mode = "关键词"
    if model.embedding_ready and chunks:
        try:
            keys = [hashlib.sha256((model.base_url + "\0" + model.embedding_model + "\0" +
                    chunk["course_id"] + "\0" + chunk["course_version"] + "\0" +
                    chunk["title"] + "\0" + chunk["content"]).encode("utf-8")).hexdigest() for chunk in chunks]
            vectors = [storage.get_vector(key) for key in keys]
            missing = [index for index, vector in enumerate(vectors) if vector is None]
            inputs = [chunks[index]["title"] + "\n" + chunks[index]["content"] for index in missing]
            inputs.append(question)
            embedded = model.embed(inputs)
            for position, index in enumerate(missing):
                vectors[index] = embedded[position]
                storage.put_vector(keys[index], embedded[position])
            query_vector = embedded[-1]
            semantic = [cosine(query_vector, vector) for vector in vectors]
            mode = "关键词＋向量"
        except ModelUnavailable:
            notice = "向量检索暂不可用，已改用课程关键词检索。"
    ranked = []
    for index, chunk in enumerate(chunks):
        if lexical[index] <= 0 and semantic[index] < 0.22:
            continue
        keyword_score = lexical[index] / max(1, sum(query.values()))
        semantic_score = max(0.0, semantic[index])
        concept_boost = 0.08 if concept_id and concept_id in chunk["concept_ids"] else 0.0
        score = keyword_score + (0.6 * semantic_score if mode != "关键词" else 0.0) + concept_boost
        ranked.append((score, chunk["id"], chunk))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    return [item[2] for item in ranked[:3]], mode, notice
