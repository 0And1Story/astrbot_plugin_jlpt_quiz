"""Conservative extraction of text-only questions from the jlpt-test corpus.

Do not infer missing options, answers, underlines, figures or star positions.
"""

import re
import unicodedata
from dataclasses import dataclass

HEADER = re.compile(r"(?m)^[ \t]*(?:問[ \t]*題|もんだい)[ \t]*([0-9]{1,2}|VIII|VII|VI|IV|III|II|IX|V|I)(?![0-9I])")
ROMAN = {s: i for i, s in enumerate(("I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX"), 1)}
NUMBER = re.compile(r"^([0-9]{1,3})(?:[.、:)][ \t]*|[ \t]+|$)(.*)$")
QUESTION_LINE = re.compile(
    r"^\s*(?:\[(?P<bracket>\d{1,3})[|｜]?\]?|\((?P<paren>\d{1,3})\)|"
    r"(?P<bare>\d{1,3})(?:句子|[、.．:/／)）]|\s+|$))(?:\s*)(?P<text>.*)$"
)
CHOICE = re.compile(r"(?:^|(?<=\s))([1-4])(?:[.、)][ \t]*|[ \t]+)(?=\S|$)")
BLANK = re.compile(r"\(\s*\)|_{2,}")
WATERMARKS = {"多肉", "公众", "Tôi Yêu Ngoại Ngữ Group", "Tôi yêu Ngoại ngữ Group", "Yuuki Bùi"}
VOCAB = {
    "N1": ["vocab_reading", "vocab_context", "vocab_synonym", "vocab_usage"],
    "N2": ["vocab_reading", "vocab_kanji", "vocab_compound", "vocab_context", "vocab_synonym", "vocab_usage"],
    "N3": ["vocab_reading", "vocab_kanji", "vocab_context", "vocab_synonym", "vocab_usage"],
    "N4": ["vocab_reading", "vocab_kanji", "vocab_context", "vocab_synonym", "vocab_usage"],
    "N5": ["vocab_reading", "vocab_kanji", "vocab_context", "vocab_synonym"],
}
GRAMMAR = ["grammar_fill", "grammar_order", "grammar_passage"]
SUPPORTED = {"vocab_context", "vocab_compound", "vocab_usage", "grammar_fill"}
READING = {
    "N1": ["reading_short", "reading_medium", "reading_long", "reading_integrated", "reading_thematic", "reading_search"],
    "N2": ["reading_short", "reading_medium", "reading_integrated", "reading_thematic", "reading_search"],
    "N3": ["reading_short", "reading_medium", "reading_long", "reading_search"],
    "N4": ["reading_short", "reading_medium", "reading_search"],
    "N5": ["reading_short", "reading_medium", "reading_search"],
}

# Only explicit section titles move lower-level blocks into a phase. In
# particular, an unlabelled section must remain unknown rather than defaulting
# to vocabulary.
PHASE_TITLE = re.compile(
    r"聴解|听力|聽力|ちょうかい|文字・語彙|文字語彙|文字词汇|文字詞彙|"
    r"もじ・ごい|言語知識|文法|ぶんぽう|语法|語法"
)
LISTENING_TITLES = {"聴解", "听力", "聽力", "ちょうかい"}
GRAMMAR_TITLES = {"文法", "ぶんぽう", "语法", "語法"}


def _explicit_phase(prefix):
    """Return the phase of the latest explicit title in nearby source text."""
    matches = list(PHASE_TITLE.finditer(prefix[-100:]))
    if not matches:
        return "unknown"
    title = matches[-1].group()
    if title in LISTENING_TITLES:
        return "listening"
    if title in GRAMMAR_TITLES:
        return "grammar"
    return "vocabulary"


def normalize(text):
    return unicodedata.normalize("NFKC", text).replace("\r\n", "\n").replace("\r", "\n")


def clean(text):
    lines = [line.strip() for line in text.splitlines() if line.strip() not in WATERMARKS]
    return "\n".join(lines).strip()


@dataclass
class Block:
    phase: str
    number: int
    kind: str
    body: str


def blocks(text, level):
    text = clean(normalize(text))
    headers = list(HEADER.finditer(text))
    phase = "unknown"
    for index, match in enumerate(headers):
        number = ROMAN[match[1]] if match[1] in ROMAN else int(match[1])
        end = headers[index + 1].start() if index + 1 < len(headers) else len(text)
        body = text[match.end() : end].strip()
        prefix = re.sub(r"\s", "", text[max(0, match.start() - 250) : match.start()])
        rubric = re.sub(r"\s", "", body[:250])
        if level in {"N1", "N2"}:
            if number == 1:
                phase = "listening" if _explicit_phase(prefix) == "listening" else "vocabulary"
            if phase == "listening":
                yield Block(phase, number, "unsupported", body)
                continue
            if 1 <= number <= len(VOCAB[level]):
                kind = VOCAB[level][number - 1]
                phase = "vocabulary"
            elif number <= len(VOCAB[level]) + len(GRAMMAR):
                kind = GRAMMAR[number - len(VOCAB[level]) - 1]
                phase = "grammar"
            else:
                reading_index = number - len(VOCAB[level]) - len(GRAMMAR) - 1
                phase = "reading"
                kind = READING[level][reading_index] if 0 <= reading_index < len(READING[level]) else "unsupported"
        else:
            if number == 1:
                explicit_phase = _explicit_phase(prefix)
                if explicit_phase == "listening":
                    phase = "listening"
                elif any(word in rubric for word in ("読み方", "どうよみ", "ひらがなでどう")):
                    phase = "vocabulary"
                elif any(word in rubric for word in ("次の文の", "つぎの文の")) and any(
                    word in rubric for word in ("入れる", "いれ", "入ります", "はいり")
                ):
                    phase = "grammar"
                elif explicit_phase == "grammar":
                    phase = "grammar"
                elif explicit_phase == "vocabulary":
                    phase = "vocabulary"
                else:
                    phase = "unknown"
            if phase == "listening":
                kind = "unsupported"
            elif phase == "vocabulary":
                kind = VOCAB[level][number - 1] if 1 <= number <= len(VOCAB[level]) else "unsupported"
            elif phase == "grammar":
                if 1 <= number <= len(GRAMMAR):
                    kind = GRAMMAR[number - 1]
                else:
                    reading_index = number - len(GRAMMAR) - 1
                    phase = "reading"
                    kind = READING[level][reading_index] if 0 <= reading_index < len(READING[level]) else "unsupported"
            elif phase == "reading":
                reading_index = number - len(GRAMMAR) - 1
                kind = READING[level][reading_index] if 0 <= reading_index < len(READING[level]) else "unsupported"
            else:
                kind = "unsupported"
        yield Block(phase, number, kind, body)


def answer_claims(text, level):
    """Read only explicit answer headings and numbered answer entries."""
    for block in blocks(text, level):
        if block.phase == "unknown":
            continue
        first = block.body.splitlines()[0].strip() if block.body else ""
        if re.fullmatch(r"[1-4\s]+", first) and len(re.sub(r"\s", "", first)) >= 3:
            yield block, "sequence", [int(c) for c in first if c in "1234"], first
        for line in block.body.splitlines():
            sequence = re.fullmatch(r"(?:答案|正解|答え)\s*[:：]\s*([1-4\s、,・]+)", line.strip())
            if sequence and len(re.sub(r"[^1-4]", "", sequence[1])) >= 3:
                yield block, "sequence", [int(c) for c in sequence[1] if c in "1234"], line
        entry = re.compile(r"(?m)^\s*([0-9]{1,3})[、.:]\s*([1-4])(?=\s|$)([^\n]*)")
        for match in entry.finditer(block.body):
            yield block, int(match[1]), int(match[2]), match[3].strip()
        explicit = re.compile(r"(?m)^\s*\(?([0-9]{1,3})\)?[.、:\s]*(?:正解|答案)\s*[:：]\s*([1-4])([^\n]*)")
        for match in explicit.finditer(block.body):
            yield block, int(match[1]), int(match[2]), match[3].strip()
        table = numeric_table(block.body)
        if table:
            for number, value in table.items():
                yield block, number, value, "原始正答表"


def numeric_table(body):
    """Accept only complete, unambiguous runs of question numbers then answers."""
    lines = [line.strip() for line in body.splitlines() if line.strip()]
    while lines and re.fullmatch(r"(?:言語知識.*|文字・語彙|文法|読解|聴解)", lines[-1]):
        lines.pop()
    if not lines or any(not re.fullmatch(r"[0-9\s]+", line) for line in lines):
        return None
    tokens = [int(t) for line in lines for t in line.split()]

    def partitions(offset):
        if offset == len(tokens):
            return [{}]
        found = []
        for size in range(2, min(20, (len(tokens) - offset) // 2) + 1):
            numbers = tokens[offset : offset + size]
            answers = tokens[offset + size : offset + size * 2]
            if numbers != list(range(numbers[0], numbers[0] + size)) or not all(1 <= a <= 4 for a in answers):
                continue
            for remaining in partitions(offset + size * 2):
                if set(numbers) & remaining.keys():
                    continue
                found.append(dict(zip(numbers, answers)) | remaining)
                if len(found) > 1:
                    return found
        return found

    results = partitions(0)
    return results[0] if len(results) == 1 else None


def choice_lines(line):
    # Missing spaces after labels are recoverable only at column boundaries.
    # A single space in "1 3時" separates label and content, not two labels.
    line = re.sub(r"^([1-4])(?=[ぁ-ヺ一-鿿])", r"\1 ", line)
    line = re.sub(r"(?<=\s\s)([1-4])(?=[ぁ-ヺ一-鿿])", r"\1 ", line)
    matches = list(CHOICE.finditer(line))
    if not matches or matches[0].start() != 0:
        # Some extracted options omit the space after their leading digit.
        tight = re.match(r"^([1-4])(?=[ぁ-ヺ一-鿿])(.*)$", line)
        return [(int(tight[1]), tight[2])] if tight else []
    return [
        (int(m[1]), line[m.end() : matches[i + 1].start() if i + 1 < len(matches) else len(line)].strip())
        for i, m in enumerate(matches)
    ]


def question_line(line):
    """Return (number, text, strong-marker) for a printed question-number line."""
    match = QUESTION_LINE.fullmatch(line)
    if not match:
        return None
    if match["bracket"] is not None:
        return int(match["bracket"]), match["text"], True
    if match["paren"] is not None:
        return int(match["paren"]), match["text"], True
    number = int(match["bare"])
    text = match["text"]
    # 「7句子...」 is a common OCR layout; preserve the suffix as source text.
    if "句子" in line[: match.start("text")]:
        text = "句子" + text
    if text.startswith(("/", "／")):
        text = text[1:].lstrip()
    strong = bool(re.match(r"^\s*\d{1,3}(?:句子|[、.．:/／)）])", line))
    return number, text, strong


def split_inline_choices(text):
    """Split a stem followed by four explicit inline options, when fully labeled."""
    for match in CHOICE.finditer(text):
        if int(match[1]) != 1:
            continue
        choices = choice_lines(text[match.start() :])
        if [label for label, _ in choices] == [1, 2, 3, 4] and all(value for _, value in choices):
            return text[: match.start()].strip(), [value for _, value in choices]
    return text.strip(), []


def _is_answer_or_explanation(text):
    return bool(
        re.match(
            r"^[\s\W_]*(?:正解|正答|正确答案|参考答案|答案|解析|解说|解説)\s*[:：]",
            text.strip(),
        )
    )


def _is_complete_choice_row(line):
    choices = choice_lines(line)
    return [label for label, _ in choices] == [1, 2, 3, 4] and all(value for _, value in choices)


def _has_embedded_choice_group(text):
    labels = [
        int(match[1])
        for match in re.finditer(
            r"(?<!\d)([1-4])(?:[.、)][ \t]*|[ \t]+|(?=[ぁ-ヺ一-鿿]))(?=\S|$)", text
        )
    ]
    return any(labels[index : index + 4] == [1, 2, 3, 4] for index in range(len(labels) - 3))


def _is_source_footer_or_new_section(text):
    return bool(
        re.search(
            r"百利天下|下载地址|網址|网址\s*[:：]|電話\s*[:：]|电话\s*[:：]|"
            r"传真\s*[:：]|郵編\s*[:：]|邮编\s*[:：]|地址\s*[:：]|"
            r"(?:聴解|听力|聽力)\s*(?:問題|第)|問題\s*[0-9一二三四五六七八九IVX]+",
            text,
        )
    )


def _is_document_title(text):
    return bool(re.search(r"ご利用案内|お知らせ|料金表|旅行会社の案内|読書会のお知らせ", text))


def _is_rubric_only_passage(text):
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return True
    # References to a right-hand page indicate that the actual source is an
    # image/layout region that this text extraction cannot recover reliably.
    if re.search(r"右のページ|右ページ|このページは", text):
        return True
    rubric = re.compile(
        r"右のページ|このページは|下の質問|下の問い|これを読んで|答えは|一つ選び|一つえらび|"
        r"から最もよいもの|いちばんいいもの|最もよいものを一つ|質問に答えて|質問に答えなさい"
    )
    return any(rubric.search(line) for line in lines) and all(
        rubric.search(line) or re.fullmatch(r"[1-4・\-\sから]+", line) for line in lines
    )


def _max_option_length(kind):
    if kind.startswith("reading_") or kind == "reading":
        return 280
    return {
        "vocab_reading": 140,
        "vocab_kanji": 140,
        "vocab_synonym": 160,
        "vocab_compound": 160,
        "vocab_context": 180,
        "vocab_usage": 200,
        "grammar_fill": 180,
        "grammar_order": 160,
        "grammar_passage": 160,
    }.get(kind, 180)


def parse_candidate_segment(text, passage="", kind=""):
    """Parse recoverable candidates independently; one damaged item never hides its neighbors."""
    rows = []
    current = None

    def finish():
        nonlocal current
        if current and not current["invalid"] and len(current["options"]) == 4:
            prompt = "\n".join(current["prompt"]).strip()
            if kind != "grammar_order":
                prompt = BLANK.sub("（　）", prompt)
            options = ["\n".join(option).strip() for option in current["options"]]
            if any(
                len(option) > _max_option_length(kind)
                or _has_embedded_choice_group(option)
                or _is_source_footer_or_new_section(option)
                for option in options
            ):
                current = None
                return
            if kind == "grammar_passage" and len(prompt) > 160:
                current = None
                return
            if kind == "grammar_passage" and re.search(r"\(注\s*\d|（注\s*\d", prompt):
                current = None
                return
            if kind == "grammar_passage" and not (
                BLANK.search(normalize(prompt)) or re.search(r"入る|入れる|選び|えらび", prompt)
            ):
                # A number inside the article is not a separate question stem.
                current = None
                return
            if _is_source_footer_or_new_section(passage):
                current = None
                return
            if kind == "grammar_order":
                slots = re.findall(r"(?:_{2,}|＿{2,}|（　）|\(\s*\))", prompt)
                if prompt.count("★") != 1 or len(slots) != 3:
                    current = None
                    return
            if prompt and all(options) and len(set(options)) == 4:
                rows.append(dict(number=current["number"], prompt=prompt, options=options, passage=passage))
        current = None

    def begin(number, prompt_lines):
        prompt_lines = list(prompt_lines)
        prompt = "\n".join(prompt_lines)
        if _is_answer_or_explanation(prompt):
            return None
        clean_prompt, inline_options = split_inline_choices(prompt)
        return {
            "number": number,
            "prompt": [clean_prompt] if clean_prompt else [],
            "options": [[option] for option in inline_options],
            "invalid": False,
        }

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if _is_answer_or_explanation(line):
            finish()
            continue
        marker = question_line(line)
        if current is None:
            # A four-choice row is an answer set, never a question heading.
            # OCR sections whose actual stem is absent remain unimported.
            if _is_complete_choice_row(line):
                continue
            if marker:
                current = begin(marker[0], [marker[1]] if marker[1] else [])
            continue

        if len(current["options"]) == 4:
            # A second complete option row cannot be a continuation of option 4.
            if _is_complete_choice_row(line) or _has_embedded_choice_group(line):
                finish()
                continue
            if _is_source_footer_or_new_section(line) or _is_document_title(line):
                finish()
                continue
            wrapped_choice = choice_lines(line)
            if wrapped_choice and wrapped_choice[0][0] == 1:
                finish()
                continue
            # Keep wrapped fourth choices intact. Strong markers, larger exam
            # item numbers, and sequential weak numbers start the next question.
            if marker and (
                marker[2]
                or marker[0] > 4
                or marker[0] == current["number"] + 1
            ):
                finish()
                current = begin(marker[0], [marker[1]] if marker[1] else [])
            else:
                current["options"][-1].append(line)
            continue

        choices = choice_lines(line)
        expected = len(current["options"]) + 1
        # Option labels take precedence over plain numeric question-number layouts.
        if choices and choices[0][0] == expected:
            for label, value in choices:
                if label != len(current["options"]) + 1 or label > 4:
                    current["invalid"] = True
                    break
                current["options"].append([value])
            continue

        if marker and (marker[2] or marker[0] > 4 or marker[0] != expected):
            finish()
            current = begin(marker[0], [marker[1]] if marker[1] else [])
            continue

        if current["options"]:
            current["options"][-1].append(line)
        else:
            current["prompt"].append(line)

    finish()
    return rows


def parse_candidates(block):
    """Extract four-choice question candidates without requiring an answer key.

    Returns dictionaries with the printed question number, literal prompt and choices,
    and a shared passage when its boundary is structurally clear. Incomplete candidates
    are skipped independently.
    """
    body = clean(normalize(block.body))
    if not body:
        return []

    is_reading = block.phase == "reading" or block.kind.startswith("reading_") or block.kind == "reading"
    # Reading groups often label separate texts as (1), (2), etc. Keep those boundaries
    # so one article can never leak into the next candidate group.
    if is_reading:
        lines = body.splitlines()
        sections = []
        label = ""
        chunk = []
        for line in lines:
            article_marker = re.fullmatch(r"\s*\(\s*([1-9])\s*\)\s*(.*)", line)
            if article_marker:
                if chunk:
                    sections.append((label, "\n".join(chunk).strip()))
                label = f"({article_marker[1]})"
                chunk = [article_marker[2]] if article_marker[2] else []
            else:
                chunk.append(line)
        if chunk:
            sections.append((label, "\n".join(chunk).strip()))
        if not sections:
            sections = [("", body)]
    else:
        sections = [("", body)]

    result = []
    for label, section in sections:
        # Separate the shared article from the first numbered question. An article is
        # returned only when a nonempty prefix precedes the question in reading groups.
        first_question = None
        for index, line in enumerate(section.splitlines()):
            marker = question_line(line.strip())
            if marker:
                first_question = index
                break
        if first_question is None:
            continue
        lines = section.splitlines()
        prefix = "\n".join(lines[:first_question]).strip()
        if is_reading and (not prefix or _is_rubric_only_passage(prefix)):
            continue
        passage = (label + "\n" if label else "") + prefix if is_reading or block.kind == "grammar_passage" else ""
        question_text = "\n".join(lines[first_question:])
        if block.kind == "grammar_passage" and not passage:
            # Paragraph grammar is only safe when the group has a distinct shared article.
            continue
        result.extend(parse_candidate_segment(question_text, passage, block.kind))
    return result


def parse_from(lines, start):
    first = NUMBER.fullmatch(lines[start])
    if not first:
        raise ValueError("missing_question_number")
    number = int(first[1])
    prompt, options, result = [first[2]], [], []
    for line in lines[start + 1 :]:
        numbered = NUMBER.fullmatch(line)
        if len(options) == 4 and numbered:
            if int(numbered[1]) != number + 1:
                raise ValueError("nonconsecutive_question_number")
            result.append((number, "\n".join(prompt).strip(), options))
            number += 1
            prompt, options = [numbered[2]], []
            continue
        choices = choice_lines(line)
        if choices and (options or choices[0][0] == 1):
            for label, value in choices:
                if label != len(options) + 1:
                    raise ValueError("unordered_or_missing_options")
                options.append(value)
        elif options:
            options[-1] += "\n" + line
        else:
            prompt.append(line)
    if len(options) != 4:
        raise ValueError("incomplete_options")
    result.append((number, "\n".join(prompt).strip(), options))
    return result


def parse_questions(block, answers):
    """Require exactly one parse matching a complete numbered answer group."""
    lines = [line.strip() for line in block.body.splitlines() if line.strip()]
    # The next paper's title sometimes precedes its first 問題 header.
    while lines and re.fullmatch(r"言語知識\s*\((?:文字・語彙|文法)\)(?:・読解)?", lines[-1]):
        lines.pop()
    attempts = {}
    sequence = answers.get("sequence")
    entries = {k: v for k, v in answers.items() if isinstance(k, int)}
    for start, line in enumerate(lines):
        first = NUMBER.fullmatch(line)
        if not first or (entries and int(first[1]) != min(entries)):
            continue
        try:
            questions = parse_from(lines, start)
            numbers = [q[0] for q in questions]
            if sequence is not None and len(sequence) != len(questions):
                continue
            if entries and set(numbers) != set(entries):
                continue
            normalized = []
            for index, (number, prompt, options) in enumerate(questions):
                value = entries[number][0] if entries else sequence[index]
                if sequence is not None and value != sequence[index]:
                    raise ValueError("answer_sources_conflict")
                prompt = BLANK.sub("（　）", prompt)
                if any(
                    marker in prompt + "".join(options)
                    for marker in (
                        "解析",
                        "正解",
                        "www.",
                        "http",
                        "選びなさい",
                        "淘宝",
                        "新浪微博",
                        "公众号",
                        "考试成功",
                        "Group",
                        "Yuuki",
                    )
                ):
                    raise ValueError("instructions_or_analysis_in_question")
                if block.kind in {"vocab_context", "vocab_compound", "grammar_fill"}:
                    if prompt.count("（　）") != 1:
                        raise ValueError("missing_or_multiple_blanks")
                elif block.kind == "vocab_usage":
                    if not 1 <= len(prompt) <= 40:
                        raise ValueError("missing_usage_target")
                    prompt = f"「{prompt}」の使い方として最もよいものを選んでください。"
                if any(not o or len(o) > 1000 for o in options) or len(set(options)) != 4:
                    raise ValueError("invalid_options")
                normalized.append(dict(number=number, prompt=prompt, options=options, answer=value - 1))
            key = tuple((q["number"], q["prompt"], tuple(q["options"]), q["answer"]) for q in normalized)
            attempts[key] = normalized
        except (ValueError, KeyError, IndexError):
            continue
    if len(attempts) != 1:
        raise ValueError("no_unique_complete_question_alignment")
    return next(iter(attempts.values()))
