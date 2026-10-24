import json
from pathlib import Path

import pytest

from scripts.prepare_data import normalize_drill, parse_kumitaku, write_banks
from scripts.converters import js_groups, normalize_extra_drill, normalize_js_group, normalize_success, validate_order


def test_json_in_js_is_decoded_without_executing_wrapper():
    text = 'window.BANK.push({"id":"x","questions":[{"label":"题型","q":"x","options":[],"answer":0,"explain":[]},]},);'
    assert parse_kumitaku(text)[0]["q"] == "x"
    assert parse_kumitaku("require('malicious');") == []


def test_prepare_data_writes_banks_by_source(tmp_path):
    rows = [
        {"id": "drill-1", "source_url": "https://raw.githubusercontent.com/iamcheyan/jlpt-drill/main/q.json", "level": "N1"},
        {"id": "success-1", "source_url": "https://raw.githubusercontent.com/gauravhq/JLPTSuccess/main/q.json", "level": "N4"},
    ]
    write_banks(rows, tmp_path)
    assert json.loads((tmp_path / "drill.jsonl").read_text(encoding="utf-8")) == rows[0]
    assert json.loads((tmp_path / "success.jsonl").read_text(encoding="utf-8")) == rows[1]


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
    rows = [
        json.loads(line)
        for path in (root / "data").rglob("*.jsonl")
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
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


def furniture_order_question(answer=1):
    explanations = ["错误选项。"] * 4
    explanations[answer] = "正解。「彼らは新居に合わせて、家具の配置を考えた」"
    return dict(
        q="彼らは　＿＿・＿＿　＊＿＿・＿＿　。",
        options=["新居に合わせて", "家具の", "配置を", "考えた"],
        answer=answer,
        explain=explanations,
    )


def test_reported_kumitaku_answer_conflicts_with_third_star_slot():
    group = dict(id="km-51", questions=[furniture_order_question()])
    with pytest.raises(ValueError, match="order_reconstruction_mismatch"):
        normalize_js_group(group, "N1", "grammar_order", "kumitaku")


def test_bad_order_question_does_not_discard_valid_siblings():
    group = dict(id="test", questions=[furniture_order_question(answer=2), furniture_order_question()])
    rejected = []
    rows = normalize_js_group(group, "N1", "grammar_order", "test", rejected=rejected)
    assert [r["id"] for r in rows] == ["test-test-1"]
    assert rows[0]["options"][rows[0]["answer"]] == "配置を"
    assert "请选择 ★ 位置的片段" in rows[0]["prompt"]
    assert "完整句：彼らは新居に合わせて、家具の配置を考えた" in rows[0]["explanation"]
    assert rejected == [{"id": "test-test-2", "reason": "order_reconstruction_mismatch"}]


def test_order_without_a_verifiable_complete_sentence_is_rejected():
    row = furniture_order_question(answer=2)
    row["explain"][2] = "正解，但未提供完整句。"
    with pytest.raises(ValueError, match="missing_order_complete_sentence"):
        normalize_js_group(dict(id="test", questions=[row]), "N1", "grammar_order", "test")


def test_adjacent_prefix_star_blanks_are_not_merged():
    sentence = "彼らは　＿＿＊＿＿　＿＿・＿＿　。"
    validate_order(
        sentence,
        ["新居に合わせて", "家具の", "配置を", "考えた"],
        1,
        "彼らは新居に合わせて、家具の配置を考えた",
        prefix_star=True,
    )
    with pytest.raises(ValueError, match="order_reconstruction_mismatch"):
        validate_order(
            sentence,
            ["新居に合わせて", "家具の", "配置を", "考えた"],
            2,
            "彼らは新居に合わせて、家具の配置を考えた",
            prefix_star=True,
        )


def test_middle_dots_inside_words_are_preserved_during_order_validation():
    validate_order(
        "ジョン・スミスは　＿＿・＿＿　＊＿＿・＿＿　。",
        ["ワーク・ライフの", "バランスを", "職場で", "考えた"],
        1,
        "ジョン・スミスは職場でワーク・ライフのバランスを考えた",
        prefix_star=True,
    )


@pytest.mark.parametrize("meaning", ["possession, owning", "year", "４"])
def test_gloss_templates_are_not_imported_as_context_questions(meaning):
    row = dict(
        sentence=f"{meaning}を（　）する。",
        target="所持",
        verified=True,
        options=["観覧", "貶す", "購買", "所持"],
        answer=3,
        explanation=f"意味：{meaning}",
    )
    with pytest.raises(ValueError, match="definition_template_not_context"):
        normalize_extra_drill(row, "N1", "vocab_context")


@pytest.mark.parametrize(
    "kind,sentence,target",
    [
        ("vocab_context", "彼は免許証を（　）している。", "所持"),
        ("vocab_kanji", "（しょじ）に適当な漢字を選んでください。", "所持"),
    ],
)
def test_vocabulary_prompts_do_not_append_the_answer(kind, sentence, target):
    row = dict(
        sentence=sentence,
        target=target,
        options=["観覧", "貶す", "購買", "所持"],
        answer=3,
        explanation="「所持」は持っていること。",
    )
    converted = normalize_extra_drill(row, "N1", kind)[0]
    assert converted["prompt"] == sentence
    assert target not in converted["prompt"]


def test_legitimate_acronym_in_context_question_is_preserved():
    row = dict(
        sentence="IT企業は（　）を採用した。",
        target="技術者",
        options=["技術者", "工場", "機械", "資金"],
        answer=0,
        explanation="採用する对象是人，因此选「技術者」。",
    )
    assert normalize_extra_drill(row, "N2", "vocab_context")[0]["prompt"] == row["sentence"]


@pytest.mark.parametrize("kind", ["vocab_context", "vocab_kanji"])
def test_missing_vocabulary_prompt_does_not_fall_back_to_showing_the_answer(kind):
    row = dict(target="所持", options=["所持", "観覧", "購買", "譲渡"], answer=0, explanation="原题解析。")
    with pytest.raises(ValueError, match="missing_vocabulary_prompt"):
        normalize_extra_drill(row, "N1", kind)


def test_usage_questions_can_still_show_the_word_to_be_tested():
    row = dict(
        target="所持",
        options=["免許証を所持している。", "所持な人だ。", "所持に帰る。", "所持を飲む。"],
        answer=0,
        explanation="所持表示持有。",
    )
    assert normalize_extra_drill(row, "N1", "vocab_usage")[0]["prompt"] == "请选择「所持」用法正确的一句。"


def test_synonym_question_cannot_offer_the_target_itself():
    row = dict(
        sentence="（所持）の類義語を選びなさい。",
        target="所持",
        options=["所持", "観覧", "購買", "譲渡"],
        answer=0,
        explanation="所持的意思是持有。",
    )
    with pytest.raises(ValueError, match="synonym_repeats_target"):
        normalize_extra_drill(row, "N1", "vocab_synonym")
    row["options"][0] = "持っていること"
    assert normalize_extra_drill(row, "N1", "vocab_synonym")[0]["answer"] == 0


def test_reported_invalid_questions_are_excluded_from_default_bank():
    root = Path(__file__).resolve().parents[1]
    rows = [
        json.loads(line)
        for path in (root / "data").rglob("*.jsonl")
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    ids = {row["id"] for row in rows}
    assert {"kumitaku-km-51-2", "n1-vocab_context-1580", "n1-vocab_synonym-011", "n2-vocab_reading-0790"}.isdisjoint(
        ids
    )
    assert all("目标词：" not in r["prompt"] for r in rows if r["question_type"] in {"vocab_context", "vocab_kanji"})


def test_reading_explanation_cannot_explain_a_different_target():
    row = dict(
        sentence="自分の実力を《証明》するために試験を受ける。",
        target="証明",
        verified=True,
        options=["かつぶ", "しょうぶ", "しょうぶう", "きづく"],
        answer=1,
        explanation="1. 正确答案“しょうぶ”是《勝負》的正确读音。例句描述了一场紧张激烈的比赛。",
    )
    with pytest.raises(ValueError, match="reading_target_explanation_conflict"):
        normalize_extra_drill(row, "N2", "vocab_reading")
    row["options"][1] = "しょうめい"
    row["explanation"] = "正确答案“しょうめい”是《証明》的正确读音。"
    assert normalize_extra_drill(row, "N2", "vocab_reading")[0]["answer"] == 1


def test_reading_explanation_can_discuss_distractors_and_individual_characters():
    row = dict(
        sentence="自分の実力を《証明》する。",
        target="証明",
        options=["しょうぶ", "しょうめい", "しょめい", "めいしょう"],
        answer=1,
        explanation="正确读音是「しょうめい」。「明」の読みに注意。干扰项“しょうぶ”是《勝負》的正确读音。",
    )
    assert normalize_extra_drill(row, "N2", "vocab_reading")[0]["answer"] == 1


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
