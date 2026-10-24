"""Conservative extraction of text-only questions from the jlpt-test corpus.

Do not infer missing options, answers, underlines, figures or star positions.
"""

import re
import unicodedata
from dataclasses import dataclass

HEADER = re.compile(r"(?m)^[ \t]*(?:問[ \t]*題|もんだい)[ \t]*([0-9]{1,2}|VIII|VII|VI|IV|III|II|IX|V|I)(?![0-9I])")
ROMAN = {s: i for i, s in enumerate(("I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX"), 1)}
NUMBER = re.compile(r"^([0-9]{1,3})(?:[.、:)][ \t]*|[ \t]+|$)(.*)$")
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
                headings = re.findall(r"聴解|听力|ちょうかい|文字・語彙|文法|読解", prefix[-100:])
                phase = "listening" if headings and headings[-1] in {"聴解", "听力", "ちょうかい"} else "vocabulary"
            if phase == "listening":
                yield Block(phase, number, "unsupported", body)
                continue
            kind = (VOCAB[level] + GRAMMAR)[number - 1] if 1 <= number <= len(VOCAB[level]) + 3 else "reading"
            phase = "vocabulary" if number <= len(VOCAB[level]) else "grammar"
        else:
            if number == 1:
                if any(word in rubric for word in ("読み方", "どうよみ", "ひらがなでどう")):
                    phase = "vocabulary"
                elif any(word in rubric for word in ("次の文の", "つぎの文の")) and any(
                    word in rubric for word in ("入れる", "いれ", "入ります", "はいり")
                ):
                    phase = "grammar"
                elif "文法" in prefix[-100:] or "ぶんぽう" in prefix[-100:]:
                    phase = "grammar"
                elif any(word in prefix[-100:] for word in ("もじ・ごい", "文字・語彙", "言語知識")):
                    phase = "vocabulary"
                else:
                    phase = "unknown"
            if phase == "vocabulary":
                kind = VOCAB[level][number - 1] if 1 <= number <= len(VOCAB[level]) else "unsupported"
            elif phase == "grammar":
                kind = GRAMMAR[number - 1] if 1 <= number <= 3 else "reading"
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
