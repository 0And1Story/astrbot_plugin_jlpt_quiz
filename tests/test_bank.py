import json
import random
from pathlib import Path

import pytest

from quiz.bank import Question, QuestionBank
from quiz.session import parse_answer

ROOT = Path(__file__).resolve().parents[1]


def row(**overrides):
    result = dict(
        id="test-n5-1",
        level="N5",
        category="grammar",
        prompt="毎日（　）勉強します。",
        options=["に", "を", "で", "から"],
        answer=0,
        explanation="测试解析",
    )
    return {**result, **overrides}


@pytest.mark.parametrize(
    "text,expected",
    [
        ("1", 0),
        (" ４ ", 3),
        ("Ａ", 0),
        ("d", 3),
        ("/答题 2", None),
        ("答案：C", 2),
        ("答题 2", None),
        ("①", 0),
        ("我选1", None),
        ("12", None),
        ("选A吗", None),
        ("1.0", None),
        ("A B", None),
        ("/n1wf", None),
        ("5", None),
        ("", None),
    ],
)
def test_answer_parser(text, expected):
    assert parse_answer(text) == expected


@pytest.mark.parametrize(
    "changes",
    [
        {"answer": True},
        {"answer": -1},
        {"answer": 4},
        {"answer": "1"},
        {"options": ["a", "a", "b", "c"]},
        {"options": ["a", "b"]},
        {"options": ["a", "b", "c", " "]},
        {"level": "N6"},
        {"category": "vocab"},
        {"explanation": ""},
        {"prompt": None},
        {"category": "listening"},
        {"category": "reading"},
        {"audio": "file:///etc/passwd"},
    ],
)
def test_invalid_question_rejected(tmp_path, changes):
    with pytest.raises(ValueError):
        Question.from_dict(row(**changes), tmp_path)


def test_local_audio_confined_and_portable(tmp_path):
    (tmp_path / "clip.wav").write_bytes(b"test")
    q = Question.from_dict(row(category="listening", audio="clip.wav"), tmp_path)
    assert q.audio == str(tmp_path / "clip.wav")
    with pytest.raises(ValueError):
        Question.from_dict(row(category="listening", audio="../clip.wav"), tmp_path)
    q = Question.from_dict(row(category="listening", audio="https://example.com/clip.wav"), tmp_path)
    assert q.audio.startswith("https://")


def test_shuffle_preserves_answer_and_original_labels(tmp_path):
    q = Question.from_dict(row(), tmp_path)
    for seed in range(30):
        shuffled = q.shuffled(random.Random(seed))
        assert shuffled.options[shuffled.answer] == q.options[q.answer]
        assert shuffled.original_options == q.options


def test_three_choices_and_picture_question_numbering(tmp_path):
    question = Question.from_dict(row(options=["甲", "乙", "丙"], answer=2), tmp_path)
    shuffled = question.shuffled(random.Random(1))
    assert shuffled.options[shuffled.answer] == "丙"
    assert len(shuffled.options) == 3
    (tmp_path / "question.png").write_bytes(b"image")
    picture = Question.from_dict(row(images=["question.png"]), tmp_path)
    assert picture.shuffled(random.Random(3)) is picture


def test_subtype_selection_and_mixed_pool(tmp_path):
    questions = [
        Question.from_dict(row(id="vocab", category="vocabulary", question_type="vocab_reading"), tmp_path),
        Question.from_dict(row(id="order", question_type="grammar_order"), tmp_path),
    ]
    bank = QuestionBank(questions)
    assert bank.draw("N5", "vocabulary", (), question_type="vocab_reading").id == "vocab"
    assert bank.draw("N5", "grammar", (), question_type="grammar_order").id == "order"
    assert bank.draw("N5", "grammar", (), question_type="grammar_passage") is None
    assert bank.draw("N5", "all", ()).id in {"vocab", "order"}
    with pytest.raises(ValueError, match="question_type"):
        Question.from_dict(row(category="vocabulary", question_type="grammar_order"), tmp_path)


@pytest.mark.parametrize(
    "level,category,subtype,expected",
    [
        (None, "all", None, {"n1-order", "n5-order", "n1-fill", "n2-vocab"}),
        (None, "grammar", None, {"n1-order", "n5-order", "n1-fill"}),
        (None, "grammar", "grammar_order", {"n1-order", "n5-order"}),
        ("N1", "all", None, {"n1-order", "n1-fill"}),
        ("N1", "grammar", "grammar_order", {"n1-order"}),
    ],
)
def test_filters_cover_all_levels_and_rotate_only_matching_questions(tmp_path, level, category, subtype, expected):
    questions = [
        Question.from_dict(row(id="n1-order", level="N1", question_type="grammar_order"), tmp_path),
        Question.from_dict(row(id="n5-order", level="N5", question_type="grammar_order"), tmp_path),
        Question.from_dict(row(id="n1-fill", level="N1"), tmp_path),
        Question.from_dict(row(id="n2-vocab", level="N2", category="vocabulary"), tmp_path),
    ]
    bank = QuestionBank(questions)
    drawn = {bank.draw(level, category, ("group", "1"), question_type=subtype).id for _ in expected}
    assert drawn == expected


def test_reading_can_use_images_without_text(tmp_path):
    (tmp_path / "passage.png").write_bytes(b"image")
    q = Question.from_dict(row(category="reading", passage_images=["passage.png"]), tmp_path)
    assert q.passage_images


def test_draw_rotates_small_pools_and_separates_levels(tmp_path):
    questions = [Question.from_dict(row(id=str(i)), tmp_path) for i in range(3)]
    bank = QuestionBank(questions)
    for _ in range(20):
        drawn = [bank.draw("N5", "grammar", ("group", "1"), 20).id for _ in range(3)]
        assert len(set(drawn)) == 3
    assert bank.draw("N1", "grammar", ("group", "1")) is None


def test_entire_bundled_bank_is_loadable_and_unique():
    bank = QuestionBank.load([ROOT / "data/questions.jsonl"])
    assert len(bank.questions) > 1000
    assert all(bank.pools[(f"N{i}", "grammar")] for i in range(1, 6))
    assert all(bank.pools[(f"N{i}", "vocabulary")] for i in range(1, 6))
    assert all(q.source_url.startswith("https://raw.githubusercontent.com/") for q in bank.questions)
    assert all(q.explanation for q in bank.questions)


def test_load_reports_file_and_line(tmp_path):
    path = tmp_path / "bad.jsonl"
    path.write_text(json.dumps(row(answer=5)), encoding="utf-8")
    with pytest.raises(ValueError, match="bad.jsonl:1"):
        QuestionBank.load([path])
