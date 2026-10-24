"""Synthetic fixtures: no redistributed exam content or network dependency."""

import hashlib
import json
import zipfile

import pytest

from scripts import import_jlpt_test as importer
from scripts.jlpt_test_parser import Block, answer_claims, blocks, choice_lines, numeric_table, parse_questions


def paper(word="言葉", *, month=7, year=2023, method="text"):
    return dict(
        level="N1",
        year=year,
        month=month,
        method=method,
        source_file="questions.pdf",
        output_file="extracted_text/questions.txt",
        text="問題2\n次の文の( )に入れるものを選びなさい。\n"
        + "\n".join(f"{n} {word}{n}は( )です。\n1 甲\n2 乙\n3 丙\n4 丁" for n in (7, 8, 9)),
    )


def answer(text="問題2 234", **kwargs):
    return dict(paper(**kwargs), source_file="答案.pdf", output_file="extracted_text/answers.txt", text=text)


def test_answer_and_exam_numbers_align_and_convert_to_zero_based(tmp_path):
    rows, report = importer.convert([paper(), answer()])
    assert report["imported"] == 3
    assert [r["answer"] for r in rows] == [1, 2, 3]
    for row in rows:
        q = importer.Question.from_dict(row, tmp_path)
        assert q.ai_generated is False
        assert q.question_type == "vocab_context"
        assert q.source_url.startswith(f"https://github.com/eulerex/jlpt-test/blob/{importer.REVISION}/")
        assert "暂无可靠" in q.explanation


def test_numeric_table_requires_whole_unambiguous_number_answer_pairs():
    assert numeric_table("26\n27\n28\n2\n1\n4\n29\n30\n3\n2") == {26: 2, 27: 1, 28: 4, 29: 3, 30: 2}
    assert numeric_table("7\n8\n9\n1\n2") is None
    assert numeric_table("7\n8\n9\n1\n2\n3\n解析") is None


def test_entries_are_not_misidentified_as_answer_sequence():
    claims = list(answer_claims("問題2\n1、2\n2、3\n3、4", "N1"))
    assert [(number, value) for _, number, value, _ in claims] == [(1, 2), (2, 3), (3, 4)]
    assert not list(answer_claims("問題2\n正解:1", "N1"))


def test_answer_appendix_is_separate_from_listening_cycle():
    text = "問題1\n読み方\n問題2\n試験\n聴解\n問題1\n音声\n問題2\n音声\n文字・語彙\n問題1\n4 3 2"
    found = list(blocks(text, "N1"))
    assert [b.phase for b in found] == ["vocabulary", "vocabulary", "listening", "listening", "vocabulary"]


def test_lower_levels_and_roman_group_headings_have_separate_numbering():
    found = list(blocks("言語知識\n問題Ⅰ 1 2 3\n問題Ⅲ 2 3 4\n文法・読解\n問題Ⅰ 3 4 1", "N3"))
    assert [(b.phase, b.number, b.kind) for b in found] == [
        ("vocabulary", 1, "vocab_reading"),
        ("vocabulary", 3, "vocab_context"),
        ("grammar", 1, "grammar_fill"),
    ]


@pytest.mark.parametrize(
    "bad",
    [
        "問題2 231",  # Disagrees with the other answer sheet.
        "問題2 2344",  # Extra answer cannot be silently discarded.
        "問題2 23",  # Insufficient answers.
    ],
)
def test_conflicting_or_incomplete_answer_groups_rejected(bad):
    rows, _ = importer.convert([paper(), answer(), answer(bad)])
    if bad.endswith("23"):
        # The malformed claim is ignored; the complete independent sheet remains.
        assert len(rows) == 3
    else:
        assert rows == []


@pytest.mark.parametrize(
    "mutation",
    [
        lambda text: text.replace("8 言葉", "10 言葉"),
        lambda text: text.replace("4 丁", ""),
        lambda text: text.replace("( )", "答え", 2),
        lambda text: text.replace("2 乙", "2 甲"),
        lambda text: text + "\n新浪微博:advertisement",
    ],
)
def test_missing_layout_options_or_contaminated_text_rejected(mutation):
    source = paper()
    source["text"] = mutation(source["text"])
    assert importer.convert([source, answer()])[0] == []


def test_time_values_are_not_misread_as_extra_option_labels():
    assert choice_lines("1 3時    2 3時に    3 3時間    4 3時間に") == [
        (1, "3時"),
        (2, "3時に"),
        (3, "3時間"),
        (4, "3時間に"),
    ]
    assert choice_lines("1 赤    2 白    3青    4黄") == [(1, "赤"), (2, "白"), (3, "青"), (4, "黄")]


def test_numbered_entries_must_match_complete_question_range():
    group = list(blocks(paper()["text"], "N1"))[0]
    answers = {n: (value, "source", "") for n, value in ((7, 2), (8, 3), (9, 4))}
    assert len(parse_questions(group, answers)) == 3
    with pytest.raises(ValueError):
        parse_questions(group, {**answers, 10: (1, "source", "")})
    with pytest.raises(ValueError):
        parse_questions(group, {**answers, "sequence": [1, 2, 3]})


def test_missing_underlines_and_star_positions_are_not_reconstructed():
    assert not ({"vocab_reading", "vocab_synonym", "grammar_order"} & importer.SUPPORTED)
    group = Block("grammar", 5, "grammar_fill", "1 文は★です。\n1 甲\n2 乙\n3 丙\n4 丁")
    with pytest.raises(ValueError):
        parse_questions(group, {1: (1, "source", "")})


def test_old_undated_and_ocr_question_papers_not_imported():
    assert importer.session(paper(month=None)) is None
    assert importer.convert([paper(month=None), answer()])[0] == []
    assert importer.convert([paper(method="ocr"), answer()])[0] == []
    assert importer.convert([paper(year=2009), answer(year=2009)])[0] == []


def test_duplicate_questions_and_conflicting_versions():
    rows, _ = importer.convert([paper(), paper(), answer()])
    assert len(rows) == 3
    assert importer.convert([paper(), answer()], {importer.fingerprint(r) for r in rows})[0] == []
    assert importer.convert([paper(), paper(word="別の言葉"), answer()])[0] == []


def test_identical_content_with_different_answers_is_not_kept_arbitrarily():
    source = paper()
    for number in (7, 8, 9):
        source["text"] = source["text"].replace(f"言葉{number}", "同じ言葉")
    rows, report = importer.convert([source, answer()])
    assert rows == []
    assert any(item["reason"] == "identical_question_conflicting_answers" for item in report["skipped"])


def test_archive_reads_unicode_names_but_excludes_old_system(tmp_path):
    archive = tmp_path / "source.zip"
    source = paper()
    source["output_file"] = "extracted_text/cafe\u0301.txt"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr(importer.PREFIX + "extracted_text/manifest.json", json.dumps([source, paper(year=2009)]))
        zf.writestr(importer.PREFIX + "extracted_text/caf\u00e9.txt", source["text"])
    assert len(importer.load_sources(archive)) == 1


def test_cached_archive_checksum_failure_preserves_file(tmp_path):
    path = tmp_path / f"jlpt-test-{importer.REVISION[:8]}.zip"
    path.write_bytes(b"broken")
    assert hashlib.sha256(path.read_bytes()).hexdigest() != importer.SHA256
    with pytest.raises(ValueError, match="checksum"):
        importer.fetch_archive(tmp_path)
    assert path.read_bytes() == b"broken"


def test_empty_import_does_not_overwrite_installed_bank(tmp_path, monkeypatch):
    output = tmp_path / "local_data" / "jlpt-test.jsonl"
    output.parent.mkdir()
    output.write_text("previous bank", encoding="utf-8")
    monkeypatch.setattr(importer, "ROOT", tmp_path)
    monkeypatch.setattr(importer, "fetch_archive", lambda _: None)
    monkeypatch.setattr(importer, "load_sources", lambda _: [])
    monkeypatch.setattr(importer, "existing_fingerprints", lambda _: set())
    with pytest.raises(ValueError, match="existing bank preserved"):
        importer.main()
    assert output.read_text(encoding="utf-8") == "previous bank"
