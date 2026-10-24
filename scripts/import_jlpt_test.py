"""Import uncorrected modern exam transcriptions from 5Mcv4He/jlpt-freq.

This only converts structure; it never asks a model to repair text or solve
questions. Downloads and the single source bank stay local and gitignored.
"""

import hashlib
import json
import re
import sys
import unicodedata
import urllib.request
import zipfile
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from quiz.bank import Question  # noqa: E402
from quiz.types import TYPES  # noqa: E402
from scripts.jlpt_test_parser import NUMBER, VOCAB, answer_claims, blocks, normalize, parse_candidates  # noqa: E402

REPOSITORY = "5Mcv4He/jlpt-freq"
REVISION = "215b7ffd509824388541ab826b82053c7b185cd3"
SHA256 = "fc3104e71c1f2c2881c6e1328e9ec513d872321e86feb14dbceb294e2b1a0417"
ARCHIVE_URL = f"https://codeload.github.com/{REPOSITORY}/zip/{REVISION}"
PREFIX = f"jlpt-freq-{REVISION}/"
ANSWER_FILE = re.compile(r"答案|正解|参考答|解析|answers?|đáp", re.I)


def fetch_archive(cache):
    archive = cache / f"jlpt-freq-{REVISION[:8]}.zip"
    cache.mkdir(parents=True, exist_ok=True)
    if not archive.exists():
        with urllib.request.urlopen(ARCHIVE_URL, timeout=45) as response:
            content = response.read()
        if hashlib.sha256(content).hexdigest() != SHA256:
            raise ValueError("Downloaded archive checksum mismatch")
        archive.write_bytes(content)
    if hashlib.sha256(archive.read_bytes()).hexdigest() != SHA256:
        raise ValueError("Cached archive checksum mismatch; remove it and retry")
    return archive


def load_sources(archive):
    """Read pinned ZIP members directly; never execute or extract upstream code."""
    with zipfile.ZipFile(archive) as zf:
        members = {unicodedata.normalize("NFC", name): name for name in zf.namelist()}

        def read(path):
            path = unicodedata.normalize("NFC", path)
            if PurePosixPath(path).is_absolute() or ".." in PurePosixPath(path).parts:
                raise ValueError("Unexpected upstream member path")
            return zf.read(members[PREFIX + path]).decode("utf-8-sig")

        manifest = json.loads(read("extracted_text/manifest.json"))
        return [
            dict(row, text=read(row["output_file"]))
            for row in manifest
            if row["level"] in VOCAB and row["year"] >= 2010
        ]


def session(source):
    if source["year"] < 2010:
        return None
    return source["level"], source["year"], source.get("month") or 0


def group_key(source, block):
    key = session(source) + (block.phase, block.number)
    # A year-only file may use its OWN embedded answers, never another file's.
    return key + (source["source_file"],) if not source.get("month") else key


def sequence_numbers(block, sequence, level):
    """Locate a sequence's question numbers in the answer document itself."""
    found = []
    for line in block.body.splitlines()[1:]:
        match = NUMBER.fullmatch(line.strip())
        if match and match[2] and re.search(r"[ぁ-ヺ一-鿿]", match[2]):
            found.append(int(match[1]))
    if len(found) == len(sequence) and found == list(range(found[0], found[0] + len(found))):
        return found
    # These groups have a fixed printed starting number in modern exams.
    if level == "N1" and block.phase == "vocabulary" and block.number in {1, 2, 3, 4}:
        start = {1: 1, 2: 7, 3: 14, 4: 20}[block.number]
    elif block.phase == "grammar" and block.kind == "grammar_fill":
        start = 26 if level == "N1" else 1 if level in {"N3", "N4", "N5"} else None
    elif block.phase == "vocabulary" and block.number == 1:
        start = 1
    else:
        start = None
    return list(range(start, start + len(sequence))) if start is not None else []


def collect_answers(sources):
    """Keep independently numbered explicit claims; conflicts affect one item."""
    claims = defaultdict(lambda: defaultdict(list))
    for source in sources:
        date = session(source)
        if date is None or not ANSWER_FILE.search(source["source_file"]):
            continue
        for block, number, value, note in answer_claims(source["text"], source["level"]):
            if block.kind not in TYPES or block.phase == "listening":
                continue
            key = group_key(source, block)
            if number == "sequence":
                for n, a in zip(sequence_numbers(block, value, source["level"]), value):
                    claims[key][n].append((a, source["output_file"], note))
            else:
                claims[key][number].append((value, source["output_file"], note))
        # A bare 正解 line following a clearly numbered q > 4 is also explicit.
        for block in blocks(source["text"], source["level"]):
            if block.kind not in TYPES or block.phase == "listening":
                continue
            current = None
            for line in block.body.splitlines():
                match = NUMBER.fullmatch(line.strip())
                if match and int(match[1]) > 4:
                    current = int(match[1])
                value = re.fullmatch(r"正解\s*[:：]\s*([1-4])\s*", line.strip())
                if current is not None and value:
                    claims[group_key(source, block)][current].append(
                        (int(value[1]), source["output_file"], line.strip())
                    )
    answers, conflicts = {}, []
    for key, group in claims.items():
        accepted = {}
        for number, values in group.items():
            if len({v[0] for v in values}) == 1:
                accepted[number] = values[0]
            else:
                conflicts.append(dict(group=key, number=number, claims=values))
        if accepted:
            answers[key] = accepted
    return answers, conflicts


def fingerprint(row):
    compact = lambda text: re.sub(r"\s+", "", normalize(text))  # noqa: E731
    return (
        row["level"],
        compact(row["prompt"]),
        compact(row.get("passage", "")),
        tuple(sorted(compact(o) for o in row["options"])),
    )


def existing_fingerprints(output):
    found = set()
    for directory in (ROOT / "data", ROOT / "local_data"):
        for path in directory.rglob("*.jsonl"):
            if path.resolve() == output.resolve():
                continue
            for line in path.read_text(encoding="utf-8-sig").splitlines():
                if line.strip():
                    found.add(fingerprint(json.loads(line)))
    return found


def convert(sources, existing=()):
    answers, conflicts = collect_answers(sources)
    skipped, variants, candidates_seen = [], defaultdict(list), 0
    for source in sources:
        date = session(source)
        if date is None:
            skipped.append(dict(file=source["output_file"], reason="unknown_or_old_exam_date"))
            continue
        for block in blocks(source["text"], source["level"]):
            if block.kind not in TYPES or block.phase == "listening":
                continue
            group = answers.get(group_key(source, block), {})
            for candidate in parse_candidates(block):
                candidates_seen += 1
                number = candidate["number"]
                if number not in group:
                    skipped.append(
                        dict(
                            file=source["output_file"],
                            group=block.number,
                            number=number,
                            reason="no_unambiguous_numbered_answer",
                        )
                    )
                    continue
                level, year, month = date
                file_tag = "-" + hashlib.sha256(source["source_file"].encode()).hexdigest()[:8] if not month else ""
                exam_label = f"{year}.{month:02}" if month else f"{year}（月份未注明）"
                row = dict(
                    id=f"jlpt-test-{level.lower()}-{year}{month:02}{file_tag}-{block.phase}-m{block.number}-q{number}",
                    level=level,
                    category=TYPES[block.kind][0],
                    question_type=block.kind,
                    prompt=candidate["prompt"],
                    options=candidate["options"],
                    answer=group[number][0] - 1,
                    passage=candidate.get("passage", ""),
                    explanation="正答来自来源答案表；暂无可靠的逐题解析。题面保留上游转录，尚未纠错。",
                    source=f"5Mcv4He/jlpt-freq · {exam_label} {level} 历年真题转录",
                    source_url=f"https://github.com/{REPOSITORY}/blob/{REVISION}/"
                    + quote(source["output_file"], safe="/"),
                    ai_generated=False,
                    past_paper=True,
                    ocr_warning=True,
                    provenance="上游标注为新制历年真题；原始文本/OCR转录，未纠错，未逐题核对官方原卷。",
                    license="Local personal-use import; original rights retained; no redistribution license provided.",
                )
                try:
                    Question.from_dict(row, ROOT / "local_data")
                except (ValueError, TypeError) as exc:
                    skipped.append(dict(id=row["id"], reason=str(exc)))
                    continue
                variants[row["id"]].append((source, row, group[number][1]))
    # Choose a source version, never synthesize a repaired version from copies.
    chosen = []
    for identity, versions in sorted(variants.items()):
        versions.sort(key=lambda item: (item[0]["method"] != "text", item[0]["output_file"]))
        chosen.append(versions[0])
    by_content = defaultdict(list)
    for source, row, answer_file in chosen:
        by_content[fingerprint(row)].append((source, row, answer_file))
    seen, records, audit, duplicates = set(existing), [], [], []
    for key, versions in by_content.items():
        if len({normalize(r["options"][r["answer"]]) for _, r, _ in versions}) != 1:
            skipped.extend(dict(id=r["id"], reason="identical_question_conflicting_answers") for _, r, _ in versions)
            continue
        source, row, answer_file = versions[0]
        if key in seen:
            duplicates.append(row["id"])
            continue
        seen.add(key)
        records.append(row)
        duplicates.extend(r["id"] for _, r, _ in versions[1:])
        audit.append(
            dict(id=row["id"], question_source=row["source_url"], method=source["method"], answer_file=answer_file)
        )
    records.sort(key=lambda row: row["id"])
    report = dict(
        repository=REPOSITORY,
        revision=REVISION,
        archive_sha256=SHA256,
        modern_source_files=len(sources),
        candidates=candidates_seen,
        answer_groups=len(answers),
        imported=len(records),
        by_level=dict(sorted(Counter(r["level"] for r in records).items())),
        by_type=dict(sorted(Counter(r["question_type"] for r in records).items())),
        accepted=audit,
        answer_conflicts=conflicts,
        duplicates=duplicates,
        skipped=skipped,
        text_correction=False,
        warning="OCR 识别可能不准确；未纠错。",
    )
    return records, report


def main():
    output = ROOT / "local_data" / "jlpt-test.jsonl"
    sources = load_sources(fetch_archive(ROOT / "tmp" / "private_sources"))
    records, report = convert(sources, existing_fingerprints(output))
    report_path = ROOT / "tmp" / "docs" / "jlpt-test-import.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if not records:
        raise ValueError(f"No structurally usable questions; existing bank preserved. See {report_path}")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(".jsonl.tmp")
    temporary.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in records), encoding="utf-8")
    temporary.replace(output)
    print(json.dumps({key: report[key] for key in ("imported", "by_level", "by_type")}, ensure_ascii=False))
    print(f"Local bank: {output}\nReport: {report_path}")


if __name__ == "__main__":
    main()
