import json
from pathlib import Path

import pytest

from scripts.prepare_data import normalize_drill, parse_kumitaku
from scripts.converters import js_groups, normalize_extra_drill, normalize_js_group, normalize_success


def test_json_in_js_is_decoded_without_executing_wrapper():
    text = 'window.BANK.push({"id":"x","questions":[{"label":"题型","q":"x","options":[],"answer":0,"explain":[]},]},);'
    assert parse_kumitaku(text)[0]["q"] == "x"
    assert parse_kumitaku("require('malicious');") == []


def test_wrong_completed_sentence_rejected():
    row = dict(
        id="x",
        verified=True,
        sentence="ご飯（　）食べます。",
        options=["を", "に", "で", "が"],
        answer=1,
        complete_sentence="ご飯を食べます。",
        explanation="例",
    )
    with pytest.raises(ValueError, match="completed_sentence_mismatch"):
        normalize_drill(row, "N5", "grammar")
    row["answer"] = 0
    assert normalize_drill(row, "N5", "grammar")[0]["answer"] == 0


def test_bundled_report_excludes_known_bad_upstream_question():
    root = Path(__file__).resolve().parents[1]
    rows = [json.loads(line) for line in (root / "data/questions.jsonl").read_text(encoding="utf-8").splitlines()]
    assert "n2-reading_short-001" not in {row["id"] for row in rows}
    assert not any("練習用文章です" in row.get("passage", "") for row in rows)


def test_js_trailing_comma_and_integrated_passages():
    groups = js_groups(
        'window.BANK.push({"id":"x","passageA":"文章A","passageB":"文章B",'
        '"questions":[{"q":"共通点は？","options":["a","b","c","d"],'
        '"answer":0,"explain":["A","B","C","D"]},]},);'
    )
    row = normalize_js_group(groups[0], "N1", "reading_integrated", "test")[0]
    assert "文章A" in row["passage"] and "文章B" in row["passage"]
    assert row["question_type"] == "reading_integrated"


def test_order_requires_matching_star_fragment_and_complete_sentence():
    row = dict(
        id="order",
        sentence="私は ＿＿ ＿＿ ＿★＿ ＿＿。",
        options=["毎日", "学校で", "日本語を", "勉強します"],
        answer=2,
        complete_sentence="私は毎日学校で日本語を勉強します。",
        explanation="例",
    )
    assert normalize_extra_drill(row, "N5", "grammar_order")[0]["answer"] == 2
    row["answer"] = 1
    with pytest.raises(ValueError, match="order_reconstruction"):
        normalize_extra_drill(row, "N5", "grammar_order")


def test_success_correct_answer_text_is_mapped_to_index():
    row = dict(
        id="n4.listen.001",
        prompt_ja="何ですか",
        choices=["甲", "乙", "丙"],
        correctAnswer="乙",
        explanation_en="Because ...",
        script_ja="原文",
        format="response",
    )
    result = normalize_success(row, "N4", "listening")[0]
    assert result["answer"] == 1
    assert result["question_type"] == "listening_response"
