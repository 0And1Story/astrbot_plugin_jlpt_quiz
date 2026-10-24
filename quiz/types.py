"""JLPT question families; not every level contains every family."""

CATEGORIES = {"vocabulary": "词汇", "grammar": "文法", "reading": "阅读", "listening": "听力"}
TYPES = {
    "vocab_reading": ("vocabulary", "汉字读音"),
    "vocab_kanji": ("vocabulary", "汉字表记"),
    "vocab_compound": ("vocabulary", "词语构成"),
    "vocab_context": ("vocabulary", "词汇填空"),
    "vocab_synonym": ("vocabulary", "近义替换"),
    "vocab_usage": ("vocabulary", "词语用法"),
    "grammar_fill": ("grammar", "文法选择"),
    "grammar_order": ("grammar", "文法排序"),
    "grammar_passage": ("grammar", "篇章文法"),
    "reading_short": ("reading", "短文理解"),
    "reading_medium": ("reading", "中文理解"),
    "reading_long": ("reading", "长文理解"),
    "reading_integrated": ("reading", "统合理解"),
    "reading_thematic": ("reading", "主张理解"),
    "reading_search": ("reading", "信息检索"),
    "listening_task": ("listening", "课题理解"),
    "listening_point": ("listening", "要点理解"),
    "listening_summary": ("listening", "概要理解"),
    "listening_expression": ("listening", "语言表达"),
    "listening_response": ("listening", "即时应答"),
    "listening_integrated": ("listening", "综合听力"),
}
DEFAULT_TYPES = {
    "vocabulary": "vocab_context",
    "grammar": "grammar_fill",
    "reading": "reading_short",
    "listening": "listening_task",
}


def resolve_type(value: str) -> tuple[str, str | None] | None:
    value = value.lower()
    if value in {"all", "全部", "综合"}:
        return "all", None
    for key, name in CATEGORIES.items():
        if value in {key, name}:
            return key, None
    for key, (category, name) in TYPES.items():
        if value in {key, name}:
            return category, key
    return None


def parse_filters(text: str) -> tuple[str | None, str, str | None]:
    """Combine optional level, category and subtype filters in any order."""
    level = None
    category = "all"
    question_type = None
    for token in text.split():
        normalized = token.upper()
        if normalized in {"N1", "N2", "N3", "N4", "N5"}:
            if level is not None and level != normalized:
                raise ValueError("一次只能指定一个等级。")
            level = normalized
            continue
        selected = resolve_type(token)
        if selected is None:
            raise ValueError(f"无法识别筛选条件「{token}」。等级为 N1–N5，题型见 /jlpt题型。")
        selected_category, selected_type = selected
        if selected_category == "all":
            continue
        if category != "all" and category != selected_category:
            raise ValueError("大类与具体题型不匹配，或指定了多个大类。")
        if question_type and selected_type and question_type != selected_type:
            raise ValueError("一次只能指定一个具体题型。")
        category = selected_category
        question_type = selected_type or question_type
    return level, category, question_type
