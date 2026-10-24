from itertools import permutations

import pytest

from quiz.types import parse_filters


@pytest.mark.parametrize(
    "text,expected",
    [
        ("", (None, "all", None)),
        ("文法", (None, "grammar", None)),
        ("n1", ("N1", "all", None)),
        ("文法排序", (None, "grammar", "grammar_order")),
        ("  文法排序\tn1  ", ("N1", "grammar", "grammar_order")),
        ("GRAMMAR_ORDER N1", ("N1", "grammar", "grammar_order")),
        ("综合 n5", ("N5", "all", None)),
        ("n1 N1 文法 文法排序 文法排序", ("N1", "grammar", "grammar_order")),
    ],
)
def test_optional_filters(text, expected):
    assert parse_filters(text) == expected


def test_filter_order_does_not_change_selection():
    for tokens in permutations(["文法排序", "n1", "文法"]):
        assert parse_filters(" ".join(tokens)) == ("N1", "grammar", "grammar_order")


@pytest.mark.parametrize(
    "tokens",
    [
        ("n1", "n5"),
        ("阅读", "文法排序"),
        ("文法", "词汇"),
        ("文法选择", "文法排序"),
        ("N6",),
        ("文法排序", "n1", "未知条件"),
    ],
)
def test_invalid_filters_are_rejected_regardless_of_order(tokens):
    for order in permutations(tokens):
        with pytest.raises(ValueError):
            parse_filters(" ".join(order))
