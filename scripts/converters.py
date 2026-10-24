"""Source-specific normalization. Never execute upstream JavaScript."""

import itertools
import json
import re
import unicodedata


def compact(value):
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", value))


def js_groups(text):
    start = text.index(".push(") + len(".push(")
    text = text[start : text.rfind(")")]
    # Remove trailing commas outside quoted JSON strings only.
    output, quoted, escaped = [], False, False
    for i, char in enumerate(text):
        if char == '"' and not escaped:
            quoted = not quoted
        if not quoted and char == "," and re.match(r"\s*[}\]]", text[i + 1 :]):
            continue
        output.append(char)
        escaped = char == "\\" and not escaped
    text = "".join(output).strip().rstrip(",")
    return json.loads("[" + text + "]")


def explanations(row):
    if isinstance(row.get("explain"), list):
        return "\n".join(f"「{option}」：{explain}" for option, explain in zip(row["options"], row["explain"]))
    return row.get("explanation") or "原题来源仅提供答案，暂无详细解析。"


def normalize_extra_drill(row, level, kind):
    if row.get("verified") is False:
        raise ValueError("upstream_rejected")
    base = dict(
        id=row.get("id", ""),
        level=level,
        question_type=kind,
        options=row.get("options", []),
        answer=row.get("answer"),
        explanation=explanations(row),
    )
    if kind.startswith("vocab_"):
        prompt = row.get("sentence") or row.get("question") or f"请选择「{row.get('target', '')}」用法正确的一句。"
        if row.get("target") and row["target"] not in prompt:
            prompt += f"\n目标词：{row['target']}"
        base.update(category="vocabulary", prompt=prompt)
        return [base]
    if kind == "grammar_order":
        options = row.get("options", [])
        sentence, completed = row.get("sentence", ""), row.get("complete_sentence", "")
        blanks = list(re.finditer(r"[＿_]*[★＊][＿_]*|＿{2,}|_{2,}", sentence))
        star = next((i for i, m in enumerate(blanks) if "★" in m[0] or "＊" in m[0]), None)
        if len(options) != 4 or len(blanks) != 4 or star is None or not completed:
            raise ValueError("incomplete_order_question")
        candidates = []
        for order in itertools.permutations(range(4)):
            parts, pos = [], 0
            for match, choice in zip(blanks, order):
                parts.extend([sentence[pos : match.start()], options[choice]])
                pos = match.end()
            parts.append(sentence[pos:])
            if compact("".join(parts)) == compact(completed):
                candidates.append(order[star])
        if not candidates or set(candidates) != {row.get("answer")}:
            raise ValueError("order_reconstruction_mismatch")
        base.update(
            category="grammar",
            prompt=sentence + "\n请选择 ★ 位置的片段。",
            explanation=explanations(row) + "\n完整句：" + completed,
        )
        return [base]
    if kind == "grammar_passage":
        passage = row.get("passage", "")
        if not passage or not row.get("blanks"):
            raise ValueError("missing_passage_blanks")
        result = []
        for index, blank in enumerate(row["blanks"], 1):
            if not blank.get("explanation"):
                raise ValueError("missing_passage_explanations")
            result.append(
                dict(
                    base,
                    id=f"{base['id']}-blank{index}",
                    category="grammar",
                    passage=passage,
                    prompt=f"请选择文章第 {blank.get('num', index)} 空的正确表达。",
                    options=blank.get("options", []),
                    answer=blank.get("answer"),
                    explanation=explanations(blank),
                )
            )
        return result
    raise ValueError("unsupported_source_type")


def normalize_js_group(group, level, kind, prefix):
    result = []
    for index, row in enumerate(group.get("questions", []), 1):
        passage = group.get("passage", "")
        if not passage and group.get("passageA") and group.get("passageB"):
            passage = "【文章 A】\n" + group["passageA"] + "\n\n【文章 B】\n" + group["passageB"]
        if isinstance(passage, list):
            passage = "\n\n".join(str(p) for p in passage)
        if isinstance(passage, dict):
            passage = "\n\n".join(f"{k}\n{v}" for k, v in passage.items())
        result.append(
            dict(
                id=f"{prefix}-{group['id']}-{index}",
                level=level,
                category="reading" if kind.startswith("reading_") else "grammar",
                question_type=kind,
                prompt=row.get("q", ""),
                passage=passage,
                options=row.get("options", []),
                answer=row.get("answer"),
                explanation=explanations(row),
            )
        )
    return result


def normalize_success(row, level, category):
    entries = row.get("questions", []) if category == "reading" else [row]
    result = []
    for entry in entries:
        choices = entry.get("choices", [])
        answer = entry.get("correctAnswer")
        if answer not in choices:
            raise ValueError("answer_not_in_choices")
        kind = (
            "reading_short"
            if category == "reading"
            else {
                "task_understanding": "listening_task",
                "task": "listening_task",
                "point_understanding": "listening_point",
                "point": "listening_point",
                "utterance_expression": "listening_expression",
                "expression": "listening_expression",
                "quick_response": "listening_response",
                "response": "listening_response",
            }.get(row.get("format_type", row.get("format")), "listening_task")
        )
        result.append(
            dict(
                id="success-" + entry["id"],
                level=level,
                category=category,
                question_type=kind,
                prompt=entry.get("prompt_ja", ""),
                options=choices,
                answer=choices.index(answer),
                explanation=entry.get("explanation_en", "") or "原题来源仅提供答案，暂无详细解析。",
                passage=row.get("ja", "") if category == "reading" else "",
                transcript=row.get("script_ja", "").replace("\\n", "\n") if category == "listening" else "",
                translation=row.get("translation_natural", "") if category == "reading" else "",
            )
        )
    return result
