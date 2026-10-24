"""Synthetic candidate parser tests; no private exam passages are included."""

import pytest

from scripts.jlpt_test_parser import Block, blocks, choice_lines, parse_candidates


@pytest.mark.parametrize("question_number", ["7", "7句子", "(7)", "[7]", "[7|", "7、", "7 /"])
def test_candidate_question_number_layouts(question_number):
    block = Block(
        "grammar",
        2,
        "grammar_fill",
        f"{question_number} 文は（　）です。\n1 甲\n2 乙\n3 丙\n4 丁",
    )
    candidates = parse_candidates(block)
    assert candidates == [
        dict(
            number=7,
            prompt=("句子" if question_number == "7句子" else "") + "文は（　）です。",
            options=["甲", "乙", "丙", "丁"],
            passage="",
        )
    ]


def test_inline_and_multiline_options_are_kept_literal():
    inline = Block("grammar", 2, "grammar_fill", "8 文は（　）です。 1 甲 2 乙 3 丙 4 丁")
    assert parse_candidates(inline)[0]["options"] == ["甲", "乙", "丙", "丁"]

    wrapped = Block("grammar", 2, "grammar_fill", "9 文は（　）です。\n1 甲の\n続き\n2 乙\n3 丙\n4 丁")
    assert parse_candidates(wrapped)[0]["options"] == ["甲の\n続き", "乙", "丙", "丁"]


def test_fourth_option_continuation_line_is_preserved():
    block = Block(
        "reading",
        8,
        "reading_short",
        "(1)\n共享文章。\n47 問いは何か。\n1 甲\n2 乙\n3 丙\n4 丁の前半\n丁的续文",
    )
    row = parse_candidates(block)[0]
    assert row["options"][3] == "丁の前半\n丁的续文"


def test_complete_four_choices_split_at_next_question_number():
    block = Block(
        "reading",
        8,
        "reading_short",
        "(1)\n共享文章。\n47 第一問は何か。\n1 甲\n2 乙\n3 丙\n4 丁の续文\n"
        "48 第二問は何か。\n1 戊\n2 己\n3 庚\n4 辛",
    )
    rows = parse_candidates(block)
    assert [row["number"] for row in rows] == [47, 48]
    assert rows[0]["options"][3] == "丁の续文"
    assert rows[1]["options"] == ["戊", "己", "庚", "辛"]


def test_inline_choice_group_cannot_become_question_or_continue_option_four():
    unheaded_choices = Block(
        "vocabulary",
        1,
        "vocab_reading",
        "1 かべ 2 わく 3 みぞ 4 ふち\n従来の桂を超えて新しい分野に進出する企業が増えている。",
    )
    assert parse_candidates(unheaded_choices) == []

    block = Block(
        "vocabulary",
        2,
        "vocab_context",
        "1 第一个问题文。\n1 甲\n2 乙\n3 丙\n4 丁\n"
        "1 第二组甲\n2 第二组乙\n3 第二组丙\n4 第二组丁",
    )
    rows = parse_candidates(block)
    assert len(rows) == 1
    assert rows[0]["options"] == ["甲", "乙", "丙", "丁"]


def test_answer_and_explanation_text_is_not_parsed_as_a_question():
    for text in (
        "(11) 正解:1\n解析 : 解说文本\n1 甲\n2 乙\n3 丙\n4 丁",
        "16 正解: 2<\n解析: 错误识别的解释\n1 甲\n2 乙\n3 丙\n4 丁",
    ):
        assert parse_candidates(Block("vocabulary", 2, "vocab_context", text)) == []


def test_sequential_weak_question_number_splits_after_fourth_option():
    block = Block(
        "vocabulary",
        1,
        "vocab_context",
        "1 第一题题干。\n1 甲\n2 乙\n3 丙\n4 丁续行\n"
        "2 第二题题干。\n1 戊\n2 己\n3 庚\n4 辛",
    )
    rows = parse_candidates(block)
    assert [row["number"] for row in rows] == [1, 2]
    assert rows[0]["options"][3] == "丁续行"
    assert rows[1]["options"] == ["戊", "己", "庚", "辛"]


def test_reading_rubric_without_source_article_is_not_a_passage():
    for rubric in (
        "右のページの旅行会社の案内を見て、下の質問に答えてください。答えは1から4から選んでください。",
        "このページは、観光客のための案内である。1・2・3・4から一つ選びなさい。",
        "右のページのAとBは、図書館にはってある二つのお知らせである。これを読んで、下の質問に答えなさい。",
    ):
        block = Block(
            "reading",
            7,
            "reading_search",
            f"{rubric}\n28 質問は何か。\n1 甲\n2 乙\n3 丙\n4 丁",
        )
        assert parse_candidates(block) == []


def test_reading_with_actual_article_is_retained():
    block = Block(
        "reading",
        7,
        "reading_short",
        "次の文章を読んで答えなさい。\n\n町の図書館は火曜日に休館します。\n"
        "28 いつ休館するか。\n1 月曜日\n2 火曜日\n3 水曜日\n4 木曜日",
    )
    rows = parse_candidates(block)
    assert len(rows) == 1
    assert "町の図書館は火曜日に休館します。" in rows[0]["passage"]


def test_chinese_answer_explanation_heading_is_rejected():
    block = Block(
        "grammar",
        7,
        "grammar_passage",
        "42 正确答案: 1\n有一天，从家里传来母亲身体不好的消息。\n"
        "1 ある日\n2 あの日に\n3 こうして\n4 そうやって",
    )
    assert parse_candidates(block) == []


def test_grammar_passage_with_article_notes_misplaced_in_prompt_is_skipped():
    block = Block(
        "grammar",
        7,
        "grammar_passage",
        "本を閉じた後、45 車を実家に走らせた。\n"
        "(注1) 疎ましい:いやな感じがして避けたい\n1 ではないが\n2 と同じく\n3 とは違って\n4 にとっても",
    )
    assert parse_candidates(block) == []


def test_reading_source_with_advertising_footer_is_skipped():
    block = Block(
        "reading",
        10,
        "reading_long",
        "互いに視線を向ける場面では、人間には独自の作法がある。\n"
        "百利天下日语下载地址:http://jlpt.example/material。\n"
        "60 サルとは違ったこととは何か。\n1 甲\n2 乙\n3 丙\n4 丁",
    )
    assert parse_candidates(block) == []


@pytest.mark.parametrize(
    "continuation,keep_question",
    [
        ("百利天下日语下载地址:http://jlpt.example/material/", True),
        ("聴解 問題1 では、男の人は何をしますか。", True),
        ("あおい市市立図書館のご利用案内", True),
        ("続きの説明文" * 46, False),
    ],
)
def test_fourth_option_ad_footer_section_or_runaway_text_is_rejected(continuation, keep_question):
    block = Block(
        "grammar",
        6,
        "grammar_order",
        "40 文が____ ____ ____ ★です。\n1 甲\n2 乙\n3 丙\n4 丁\n" + continuation,
    )
    rows = parse_candidates(block)
    if keep_question:
        assert len(rows) == 1
        assert rows[0]["options"][3] == "丁"
    else:
        assert rows == []


def test_fourth_option_followed_by_ocr_prefixed_second_choice_group_is_separated():
    block = Block(
        "grammar",
        7,
        "grammar_passage",
        "文章です。\n45 文は（　）。\n1 甲\n2 乙\n3 丙\n4 丁\n"
        "錠| 1ある日 2.あの日に 3.こうして 4.そうやって",
    )
    rows = parse_candidates(block)
    assert len(rows) == 1
    assert rows[0]["options"] == ["甲", "乙", "丙", "丁"]


def test_missing_options_skip_only_the_incomplete_question():
    block = Block(
        "vocabulary",
        2,
        "vocab_context",
        "7 文は（　）です。\n1 甲\n2 乙\n3 丙\n"
        "8 文は（　）です。\n1 丁\n2 戊\n3 己\n4 庚",
    )
    assert [candidate["number"] for candidate in parse_candidates(block)] == [8]


def test_time_digits_are_not_split_as_choice_labels():
    assert choice_lines("1 3時    2 3時に    3 3時間    4 3時間に") == [
        (1, "3時"),
        (2, "3時に"),
        (3, "3時間"),
        (4, "3時間に"),
    ]
    block = Block("grammar", 2, "grammar_fill", "10 時刻は（　）です。\n1 3時    2 3時に    3 3時間    4 3時間に")
    assert parse_candidates(block)[0]["options"] == ["3時", "3時に", "3時間", "3時間に"]
    assert choice_lines("1赤    2白    3青    4黄") == [(1, "赤"), (2, "白"), (3, "青"), (4, "黄")]


def test_reading_article_boundaries_keep_passages_separate_and_repeat_shared_text():
    block = Block(
        "reading",
        8,
        "reading_short",
        "(1)\n第一篇文章。\n47 第一問は何か。\n1 甲\n2 乙\n3 丙\n4 丁\n"
        "48 第二問は何か。\n1 戊\n2 己\n3 庚\n4 辛\n"
        "(2)\n第二篇文章。\n49 問いは何か。\n1 子\n2 丑\n3 寅\n4 卯",
    )
    rows = parse_candidates(block)
    assert [row["number"] for row in rows] == [47, 48, 49]
    assert rows[0]["passage"] == rows[1]["passage"] == "(1)\n第一篇文章。"
    assert rows[2]["passage"] == "(2)\n第二篇文章。"


def test_grammar_passage_requires_and_preserves_shared_article():
    block = Block("grammar", 3, "grammar_passage", "共通文章です。\n41 ここは（　）。\n1 甲\n2 乙\n3 丙\n4 丁")
    assert parse_candidates(block)[0]["passage"] == "共通文章です。"
    no_article = Block("grammar", 3, "grammar_passage", "41 ここは（　）。\n1 甲\n2 乙\n3 丙\n4 丁")
    assert parse_candidates(no_article) == []
    ambiguous_reading = Block("reading", 8, "reading_short", "47 問いは何か。\n1 甲\n2 乙\n3 丙\n4 丁")
    assert parse_candidates(ambiguous_reading) == []


@pytest.mark.parametrize("fragment", ["」", "の特徴は、鉄道を楽しめるという点である。", "1.ゆえに 2.が 3.とはいえ 4.また"])
def test_article_fragments_are_not_paragraph_grammar_question_stems(fragment):
    block = Block("grammar", 7, "grammar_passage", f"共通文章です。\n43 {fragment}\n1 甲\n2 乙\n3 丙\n4 丁")
    assert parse_candidates(block) == []


def test_order_question_requires_four_slots_and_visible_star():
    valid = Block("grammar", 2, "grammar_order", "7 Aは＿＿ ＿＿ ★ ＿＿です。\n1 甲\n2 乙\n3 丙\n4 丁")
    assert parse_candidates(valid)[0]["prompt"] == "Aは__ __ ★ __です。"
    missing_star = Block("grammar", 2, "grammar_order", "7 Aは＿＿ ＿＿ ＿＿ ＿＿です。\n1 甲\n2 乙\n3 丙\n4 丁")
    assert parse_candidates(missing_star) == []


def test_inline_article_labels_keep_each_reading_with_its_own_passage():
    block = Block(
        "reading", 9, "reading_medium",
        "( 1)最初の記事です。\n49 質問です。\n1 甲\n2 乙\n3 丙\n4 丁\n"
        "( 2)次の記事です。\n52 別の質問です。\n1 赤\n2 白\n3 青\n4 黒",
    )
    rows = parse_candidates(block)
    assert [row["number"] for row in rows] == [49, 52]
    assert rows[0]["passage"] == "(1)\n最初の記事です。"
    assert rows[1]["passage"] == "(2)\n次の記事です。"
    assert rows[0]["options"][3] == "丁"


def test_group_mapping_exposes_fine_reading_types():
    n1 = list(
        blocks(
            "文字・語彙\n問題1\n語彙\n問題2\n語彙\n問題3\n語彙\n問題4\n語彙\n"
            "文法\n問題5\n文法\n問題6\n文法\n問題7\n文法\n読解\n"
            "問題8\n短文\n問題9\n中文\n問題10\n長文\n問題11\n統合\n問題12\n主張\n問題13\n検索",
            "N1",
        )
    )
    assert [block.kind for block in n1[-6:]] == [
        "reading_short",
        "reading_medium",
        "reading_long",
        "reading_integrated",
        "reading_thematic",
        "reading_search",
    ]

    n2 = list(
        blocks(
            "文字・語彙\n問題1\n語彙\n問題2\n語彙\n問題3\n語彙\n問題4\n語彙\n問題5\n語彙\n問題6\n語彙\n"
            "文法\n問題7\n文法\n問題8\n文法\n問題9\n文法\n読解\n"
            "問題10\n短文\n問題11\n中文\n問題12\n統合\n問題13\n主張\n問題14\n検索",
            "N2",
        )
    )
    assert [block.kind for block in n2[-5:]] == [
        "reading_short",
        "reading_medium",
        "reading_integrated",
        "reading_thematic",
        "reading_search",
    ]


@pytest.mark.parametrize(
    "level,expected",
    [
        ("N3", ["reading_short", "reading_medium", "reading_long", "reading_search"]),
        ("N4", ["reading_short", "reading_medium", "reading_search"]),
        ("N5", ["reading_short", "reading_medium", "reading_search"]),
    ],
)
def test_lower_level_groups_map_reading_by_phase_and_group_number(level, expected):
    text = (
        "言語知識 文字・語彙\n問題Ⅰ 読み方\n問題Ⅱ 文脈\n問題Ⅲ 文脈\n"
        "文法・読解\n問題Ⅰ 次の文の（　）に入れる\n問題Ⅱ 文法\n問題Ⅲ 文法\n"
        "問題Ⅳ 短文\n問題Ⅴ 中文\n問題Ⅵ 長文"
        + ("\n問題Ⅶ 検索" if level == "N3" else "")
    )
    found = list(blocks(text, level))
    assert [block.kind for block in found if block.phase == "reading"] == expected


@pytest.mark.parametrize(
    "title,expected_phase,expected_kind",
    [
        ("文字词汇", "vocabulary", "vocab_reading"),
        ("文字語彙", "vocabulary", "vocab_reading"),
        ("语法", "grammar", "grammar_fill"),
        ("語法", "grammar", "grammar_fill"),
    ],
)
def test_lower_level_explicit_chinese_titles_split_phases(title, expected_phase, expected_kind):
    body = "読み方" if expected_phase == "vocabulary" else "次の文の（　）に入れる"
    found = list(blocks(f"{title}\n問題Ⅰ {body}\n問題Ⅱ {body}", "N3"))
    assert found[0].phase == expected_phase
    assert found[0].kind == expected_kind


@pytest.mark.parametrize("title", ["听力", "聽力"])
def test_lower_level_listening_title_isolated_from_vocab_and_grammar(title):
    text = (
        "文字词汇\n問題Ⅰ 読み方\n"
        f"{title}\n問題Ⅰ 次の文の（　）に入れる\n問題Ⅱ 次の文の（　）に入れる"
    )
    found = list(blocks(text, "N3"))
    assert found[0].phase == "vocabulary"
    assert [block.phase for block in found[1:]] == ["listening", "listening"]
    assert [block.kind for block in found[1:]] == ["unsupported", "unsupported"]


def test_lower_level_unlabelled_section_does_not_default_to_vocabulary():
    found = list(blocks("問題Ⅰ 読み方", "N3"))
    assert found[0].phase == "vocabulary"  # Explicit rubric remains usable.
    unknown = list(blocks("問題Ⅰ 問題文", "N3"))
    assert unknown[0].phase == "unknown"
