from itertools import permutations

import pytest

from quiz.types import parse_filters


@pytest.mark.parametrize(
    "text,expected",
    [
        ("", (None, "all", None, None, False)),
        ("文法", (None, "grammar", None, None, False)),
        ("n1", ("N1", "all", None, None, False)),
        ("文法排序", (None, "grammar", "grammar_order", None, False)),
        ("  文法排序\tn1  ", ("N1", "grammar", "grammar_order", None, False)),
        ("GRAMMAR_ORDER N1", ("N1", "grammar", "grammar_order", None, False)),
        ("综合 n5", ("N5", "all", None, None, False)),
        ("n1 N1 文法 文法排序 文法排序", ("N1", "grammar", "grammar_order", None, False)),
        ("AI", (None, "all", None, True, False)),
        ("ai生成 n1", ("N1", "all", None, True, False)),
        ("文法 非AI生成", (None, "grammar", None, False, False)),
        ("非ai 文法排序 N1", ("N1", "grammar", "grammar_order", False, False)),
        ("noai n5", ("N5", "all", None, False, False)),
        ("ai AI生成 n1", ("N1", "all", None, True, False)),
        ("真题", (None, "all", None, None, True)),
        ("真题 短文理解 n1", ("N1", "reading", "reading_short", None, True)),
        ("n2 AI 真题 文法排序", ("N2", "grammar", "grammar_order", True, True)),
    ],
)
def test_optional_filters(text, expected):
    assert parse_filters(text) == expected


def test_filter_order_does_not_change_selection():
    for tokens in permutations(["文法排序", "n1", "文法", "非AI"]):
        assert parse_filters(" ".join(tokens)) == ("N1", "grammar", "grammar_order", False, False)


@pytest.mark.parametrize(
    "tokens",
    [
        ("n1", "n5"),
        ("阅读", "文法排序"),
        ("文法", "词汇"),
        ("文法选择", "文法排序"),
        ("N6",),
        ("文法排序", "n1", "未知条件"),
        ("AI", "非AI"),
        ("ai生成", "noai", "n1"),
        ("非真题",),
    ],
)
def test_invalid_filters_are_rejected_regardless_of_order(tokens):
    for order in permutations(tokens):
        with pytest.raises(ValueError):
            parse_filters(" ".join(order))
