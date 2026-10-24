from __future__ import annotations

import json
import math
import random
from collections import Counter, OrderedDict, defaultdict
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .types import CATEGORIES, DEFAULT_TYPES, TYPES


def discover_question_files(*roots: Path) -> list[Path]:
    """Find JSONL banks recursively and return each resolved path only once."""
    paths = {path.resolve() for root in roots if root.is_dir() for path in root.rglob("*.jsonl") if path.is_file()}
    return sorted(paths, key=lambda path: str(path).casefold())


def media_path(value: str, base_dir: Path) -> str:
    parsed = urlparse(value)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return value
    if parsed.scheme or Path(value).is_absolute():
        raise ValueError("本地媒体必须为相对路径")
    root = base_dir.resolve()
    path = (root / value).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError("媒体文件不存在或超出题库目录")
    return str(path)


@dataclass(frozen=True)
class Question:
    id: str
    level: str
    category: str
    prompt: str
    options: tuple[str, ...]
    answer: int  # Always zero-based in files and in memory.
    explanation: str
    passage: str = ""
    audio: str = ""
    transcript: str = ""
    translation: str = ""
    source: str = ""
    source_url: str = ""
    ai_generated: bool = False
    provenance: str = ""
    original_options: tuple[str, ...] = ()
    question_type: str = ""
    images: tuple[str, ...] = ()
    passage_images: tuple[str, ...] = ()
    shuffle_options: bool = True
    credit: str = ""
    license: str = ""
    audio_duration_seconds: float = 0
    past_paper: bool = False
    ocr_warning: bool = False

    @classmethod
    def from_dict(cls, row: dict[str, Any], base_dir: Path) -> Question:
        if not isinstance(row, dict):
            raise ValueError("题目必须是 JSON 对象")
        required = ("id", "level", "category", "prompt", "explanation")
        for name in required:
            if not isinstance(row.get(name), str) or not row[name].strip():
                raise ValueError(f"{name} 必须是非空字符串")
        if row["level"] not in {f"N{i}" for i in range(1, 6)}:
            raise ValueError("level 必须为 N1–N5")
        if row["category"] not in CATEGORIES:
            raise ValueError("不支持的 category")
        question_type = row.get("question_type", DEFAULT_TYPES[row["category"]])
        if question_type not in TYPES or TYPES[question_type][0] != row["category"]:
            raise ValueError("question_type 与 category 不匹配")
        options = row.get("options")
        if not isinstance(options, list) or len(options) not in {3, 4}:
            raise ValueError("必须有三个或四个选项")
        if any(not isinstance(o, str) or not o.strip() for o in options):
            raise ValueError("选项必须是非空字符串")
        options = tuple(o.strip() for o in options)
        if len(set(options)) != len(options):
            raise ValueError("选项重复")
        answer = row.get("answer")
        if type(answer) is not int or not 0 <= answer < len(options):
            raise ValueError("answer 必须为选项范围内的整数（从 0 开始）")
        if "ai_generated" in row and type(row["ai_generated"]) is not bool:
            raise ValueError("ai_generated 必须为布尔值")
        for name in ("past_paper", "ocr_warning"):
            if name in row and type(row[name]) is not bool:
                raise ValueError(f"{name} 必须为布尔值")
        for name in (
            "passage",
            "audio",
            "transcript",
            "translation",
            "source",
            "source_url",
            "credit",
            "license",
            "provenance",
        ):
            if name in row and not isinstance(row[name], str):
                raise ValueError(f"{name} 必须是字符串")
        audio = row.get("audio", "").strip()
        duration = row.get("audio_duration_seconds", 0)
        if type(duration) not in {int, float} or not math.isfinite(duration) or not 0 <= duration <= 3600:
            raise ValueError("audio_duration_seconds 必须为 0–3600 的有限数值")
        if audio:
            audio = media_path(audio, base_dir)
        images = {}
        for name in ("images", "passage_images"):
            values = row.get(name, [])
            if not isinstance(values, list) or any(not isinstance(v, str) or not v.strip() for v in values):
                raise ValueError(f"{name} 必须为媒体路径数组")
            images[name] = tuple(media_path(v, base_dir) for v in values)
        if row["category"] == "listening" and not audio:
            raise ValueError("听力题缺少音频")
        if row["category"] == "reading" and not row.get("passage", "").strip() and not images["passage_images"]:
            raise ValueError("阅读题缺少文章")
        fields = {k: row[k].strip() for k in required}
        fields.update(
            {
                k: row.get(k, "").strip()
                for k in (
                    "passage",
                    "transcript",
                    "translation",
                    "source",
                    "source_url",
                    "credit",
                    "license",
                    "provenance",
                )
            }
        )
        return cls(
            **fields,
            **images,
            options=options,
            answer=answer,
            audio=audio,
            question_type=question_type,
            shuffle_options=row.get("shuffle_options", True) is True,
            ai_generated=row.get("ai_generated") is True,
            audio_duration_seconds=duration,
            past_paper=row.get("past_paper", False),
            ocr_warning=row.get("ocr_warning", False),
        )

    def shuffled(self, rng: random.Random) -> Question:
        if not self.shuffle_options or self.images:
            return self
        indices = list(range(len(self.options)))
        rng.shuffle(indices)
        return replace(
            self,
            options=tuple(self.options[i] for i in indices),
            answer=indices.index(self.answer),
            original_options=self.options,
        )


class QuestionBank:
    def __init__(self, questions: list[Question]):
        if len({q.id for q in questions}) != len(questions):
            raise ValueError("题目 ID 重复")
        self.questions = questions
        self.pools: dict[tuple[str, str], list[Question]] = defaultdict(list)
        for question in questions:
            self.pools[question.level, question.category].append(question)
        self.recent: OrderedDict[tuple, list[str]] = OrderedDict()

    @classmethod
    def load(cls, paths: list[Path]) -> QuestionBank:
        questions = []
        for path in paths:
            with path.open(encoding="utf-8-sig") as stream:
                for line_number, line in enumerate(stream, 1):
                    if not line.strip():
                        continue
                    try:
                        questions.append(Question.from_dict(json.loads(line), path.parent))
                    except (ValueError, TypeError) as exc:
                        raise ValueError(f"{path.name}:{line_number}: {exc}") from exc
        if not questions:
            raise ValueError("题库为空")
        return cls(questions)

    def draw(
        self,
        level: str | None,
        category: str,
        session_key: tuple,
        recent_count: int = 20,
        shuffle: bool = True,
        question_type: str | None = None,
        ai_generated: bool | None = None,
        past_paper: bool = False,
    ) -> Question | None:
        if level is not None and category != "all":
            pool = self.pools.get((level, category), [])
        else:
            pool = [
                q
                for q in self.questions
                if (level is None or q.level == level) and (category == "all" or q.category == category)
            ]
        if question_type:
            pool = [q for q in pool if q.question_type == question_type]
        if ai_generated is not None:
            pool = [q for q in pool if q.ai_generated == ai_generated]
        if past_paper:
            pool = [q for q in pool if q.past_paper]
        if not pool:
            return None
        key = (*session_key, level, category, question_type, ai_generated, past_paper)
        recent = self.recent.pop(key, [])
        # Small pools still rotate through all available questions.
        recent = recent[-min(max(0, recent_count), max(0, len(pool) - 1)) :] if recent_count and len(pool) > 1 else []
        available = [q for q in pool if q.id not in recent]
        question = random.choice(available)
        self.recent[key] = [*recent, question.id]
        while len(self.recent) > 2048:
            self.recent.popitem(last=False)
        return question.shuffled(random) if shuffle else question

    def counts(self, ai_generated: bool | None = None, past_paper: bool = False) -> Counter:
        return Counter(
            (q.level, q.category)
            for q in self.questions
            if (ai_generated is None or q.ai_generated == ai_generated) and (not past_paper or q.past_paper)
        )
