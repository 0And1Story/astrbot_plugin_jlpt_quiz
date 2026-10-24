"""Download pinned sources, validate, deduplicate and emit portable JSONL.

Only Python's standard library is needed. This script never executes upstream code.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
import unicodedata
import urllib.request
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from quiz.bank import Question  # noqa: E402
from scripts.converters import js_groups, normalize_extra_drill, normalize_js_group, normalize_success  # noqa: E402

BLANK = re.compile(r"[（(][\s　]*[）)]|_{2,}|＿{2,}")
LABEL = re.compile(r"^(?:[A-Da-d][.．、:：)]|选项\s*[A-Da-d]\s*[:：])\s*")


def compact(text: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text))


def download(url: str, target: Path, sha256: str) -> bytes:
    if target.exists():
        data = target.read_bytes()
        if hashlib.sha256(data).hexdigest() == sha256:
            return data
    for attempt in range(3):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "astrbot-jlpt-quiz/0.1"})
            with urllib.request.urlopen(request, timeout=45) as response:
                data = response.read()
            if hashlib.sha256(data).hexdigest() != sha256:
                raise ValueError(f"SHA256 不匹配：{url}")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            return data
        except (OSError, ValueError):
            if attempt == 2:
                raise
            time.sleep(attempt + 1)
    raise RuntimeError("unreachable")


def parse_kumitaku(text: str) -> list[dict]:
    """The bank uses JSON objects in a JS wrapper with trailing group commas."""
    # Strip comments, then use a JSON decoder for each question object. Do not eval JS.
    question_start = re.compile(r'\{\s*"label"\s*:')
    decoder = json.JSONDecoder()
    result = []
    for match in question_start.finditer(text):
        row, _ = decoder.raw_decode(text[match.start() :])
        result.append(row)
    return result


def normalize_drill(row: dict, level: str, category: str) -> list[dict]:
    if row.get("verified") is False:
        raise ValueError("upstream_rejected")
    if category == "grammar":
        # Skip unreviewed seed items (including ambiguous copula/particle questions).
        if row.get("verified") is not True:
            raise ValueError("unreviewed_grammar")
        prompt = row.get("sentence", "")
        if len(BLANK.findall(prompt)) != 1:
            raise ValueError("not_single_blank")
        options, answer = row.get("options", []), row.get("answer")
        if len(options) == 4 and type(answer) is int and 0 <= answer < 4:
            completed = row.get("complete_sentence")
            if completed and compact(BLANK.sub(lambda _: options[answer], prompt)) != compact(completed):
                raise ValueError("completed_sentence_mismatch")
        explanation = row.get("explanation", "")
        if row.get("complete_sentence"):
            explanation += "\n完整句：" + row["complete_sentence"]
        if row.get("translation"):
            explanation += "\n译文：" + row["translation"]
        return [
            dict(
                id=row.get("id", ""),
                level=level,
                category=category,
                prompt=prompt,
                options=options,
                answer=answer,
                explanation=explanation,
            )
        ]
    passage = row.get("passage", "")
    # Prefer the explicitly written top-level question. Nested questions in this
    # source sometimes contain editor placeholders or contradictory replacements.
    if not row.get("question"):
        raise ValueError("missing_reading_prompt")
    return [
        dict(
            id=row.get("id", ""),
            level=level,
            category=category,
            prompt=row["question"],
            passage=passage,
            options=[LABEL.sub("", o).strip() for o in row.get("options", [])],
            answer=row.get("answer"),
            explanation=row.get("explanation", ""),
            translation=row.get("translation", ""),
        )
    ]


def build(lock: dict, cache: Path) -> tuple[list[dict], dict]:
    result, rejected, seen, ids, fingerprints = [], [], {}, set(), {}
    for source in lock["sources"]:
        for file in source["files"]:
            path = file["path"]
            url = f"https://raw.githubusercontent.com/{source['repo']}/{source['revision']}/{path}"
            data = download(url, cache / source["key"] / path, file["sha256"])
            if file.get("role") == "notice":
                continue
            seen[path] = 0
            text = data.decode("utf-8-sig")
            if source["key"] in {"kumitaku", "yomitaku"}:
                rows = js_groups(text)
            elif source["key"].startswith("success"):
                content = json.loads(text)
                rows = content if isinstance(content, list) else content["passages"]
            else:
                rows = json.loads(text)["questions"]
            for index, row in enumerate(rows):
                seen[path] += 1
                identifier = row.get("id", f"{source['key']}-{index + 1:04}")
                try:
                    if source["key"] in {"kumitaku", "yomitaku"}:
                        invalid_questions = []
                        candidates = normalize_js_group(
                            row,
                            file.get("level", "N1"),
                            file["question_type"],
                            source["key"],
                            rejected=invalid_questions,
                        )
                        rejected.extend(dict(file=path, **item) for item in invalid_questions)
                    elif source["key"].startswith("success"):
                        candidates = normalize_success(row, file["level"], file["category"])
                    elif file.get("question_type", "").startswith("vocab_") or file.get("question_type") in {
                        "grammar_order",
                        "grammar_passage",
                    }:
                        candidates = normalize_extra_drill(row, file["level"], file["question_type"])
                    else:
                        candidates = normalize_drill(row, file["level"], file["category"])
                    for candidate in candidates:
                        candidate.setdefault("question_type", file.get("question_type", "grammar_fill"))
                        if not candidate.get("id"):
                            signature = json.dumps(candidate, ensure_ascii=False, sort_keys=True)
                            candidate["id"] = f"{source['key']}-{hashlib.sha256(signature.encode()).hexdigest()[:16]}"
                        candidate.update(source=source["name"], source_url=url, ai_generated=source["ai_generated"])
                        candidate["license"] = source["license"]
                        if source["license"].startswith("CC "):
                            candidate["credit"] = f"{source['name']} · {source['license']}；已转换题库格式。"
                        question = Question.from_dict(candidate, ROOT / "data")
                        if any(
                            marker in question.prompt + question.passage + question.explanation
                            for marker in ("中文详细解析", "TODO", "待补充", "[解析]", "…省略")
                        ):
                            raise ValueError("placeholder")
                        # Some source entries say "correct is B" but store answer=0.
                        explicit = re.findall(
                            r"(?:正解|正确答案|正しい答え)(?:は|为|為|是|[:：])?\s*([A-D1-4])(?:[。．、\s]|$)",
                            question.explanation,
                        )
                        for label in explicit:
                            stated = int(label) - 1 if label.isdigit() else ord(label) - ord("A")
                            if stated != question.answer:
                                raise ValueError("answer_explanation_conflict")
                        # Sort the distractors for duplicate detection; retain the correct option.
                        fingerprint = (
                            question.level,
                            question.category,
                            compact(question.prompt),
                            compact(question.passage),
                            tuple(sorted(compact(o) for o in question.options)),
                        )
                        if fingerprint in fingerprints:
                            if fingerprints[fingerprint] != compact(question.options[question.answer]):
                                raise ValueError("conflicting_duplicate")
                            raise ValueError("duplicate")
                        if question.id in ids:
                            raise ValueError("duplicate_id")
                        fingerprints[fingerprint] = compact(question.options[question.answer])
                        ids.add(question.id)
                        result.append(candidate)
                except (ValueError, TypeError, KeyError) as exc:
                    rejected.append(dict(file=path, id=identifier, reason=str(exc)))
    counts = Counter(f"{r['level']}/{r['category']}" for r in result)
    report = dict(
        schema_version=1,
        accepted=len(result),
        counts=dict(sorted(counts.items())),
        input_counts=seen,
        rejected=len(rejected),
        rejected_reasons=dict(Counter(r["reason"] for r in rejected)),
        rejected_items=rejected,
        sources=[{k: v for k, v in s.items() if k != "files"} for s in lock["sources"]],
        question_types=dict(sorted(Counter(r["question_type"] for r in result).items())),
        limitations=[
            "自动校验仅检查结构、重复及可核对的完整句，不等于人工语言审核。",
            "AI 练习题不是 JLPT 真题，等级和解析可能存在偏差。",
            "排序题须通过完整句重建校验；缺少详细解析的题目明确标注，不生成解析冒充原文。",
            "完整句重建只核对星号位置与来源答案是否一致，不能证明其他语序在语言上不成立。",
        ],
    )
    return result, report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, default=ROOT / ".cache" / "sources")
    parser.add_argument("--output", type=Path, default=ROOT / "data" / "questions.jsonl")
    parser.add_argument("--report", type=Path, default=ROOT / "tmp" / "docs" / "build_report.json")
    args = parser.parse_args()
    lock = json.loads((ROOT / "scripts" / "sources.lock.json").read_text(encoding="utf-8"))
    questions, report = build(lock, args.cache)
    if not questions:
        raise SystemExit("没有通过校验的题目，保留现有题库。")
    for level in (f"N{i}" for i in range(1, 6)):
        if not any(q["level"] == level and q["category"] == "grammar" for q in questions):
            raise SystemExit(f"{level} 文法题为空，保留现有题库。")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix(".jsonl.tmp")
    temporary.write_text("".join(json.dumps(q, ensure_ascii=False) + "\n" for q in questions), encoding="utf-8")
    temporary.replace(args.output)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("accepted", "counts", "rejected_reasons")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
