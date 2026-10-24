"""Import recoverable modern exam questions for local personal use.

The upstream PDF transcription corpus has no redistribution license. Only this
importer is distributed; downloads, reports and question banks stay gitignored.
Never use upstream __flat__/__inline__ answer arrays, or invent missing layout.
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
from scripts.jlpt_test_parser import SUPPORTED, answer_claims, blocks, normalize, parse_questions  # noqa: E402

REVISION = "215b7ffd509824388541ab826b82053c7b185cd3"
SHA256 = "70f948edb1af951f85b9164295dc6f493a1d5290b6c516dc9740854c48091f53"
ARCHIVE_URL = f"https://codeload.github.com/eulerex/jlpt-test/zip/{REVISION}"
PREFIX = f"jlpt-test-{REVISION}/"
ANSWER_FILE = re.compile(r"答案|正解|参考答|解析|answers?|đáp", re.I)
# These transcriptions passed structural checks but contain visible corruption.
# Preserve the source and skip them instead of guessing repairs without the PDF.
EXCLUDED = {
    "jlpt-test-n1-201612-grammar-m5-q28": "始めて/初めて transcription error",
    **{
        f"jlpt-test-n1-202112-grammar-m5-q{n}": "missing particles or corrupted kana in transcription"
        for n in (27, 28, 29, 32, 33, 34, 35)
    },
    **{
        f"jlpt-test-n1-202112-vocabulary-m{group}-q{n}": "corrupted words in transcription"
        for group, n in ((2, 8), (2, 12), (4, 20), (4, 21), (4, 22), (4, 25))
    },
    "jlpt-test-n4-202307-vocabulary-m3-q17": "人がす少ない transcription error",
    "jlpt-test-n4-202307-vocabulary-m3-q20": "さんぼ transcription error",
}


def fetch_archive(cache):
    archive = cache / f"jlpt-test-{REVISION[:8]}.zip"
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
    """Read members directly: no extraction, code execution or path traversal."""
    with zipfile.ZipFile(archive) as zf:
        members = {unicodedata.normalize("NFC", name): name for name in zf.namelist()}

        def read(path):
            path = unicodedata.normalize("NFC", path)
            if PurePosixPath(path).is_absolute() or ".." in PurePosixPath(path).parts:
                raise ValueError("Unexpected upstream member path")
            return zf.read(members[PREFIX + path]).decode("utf-8-sig")

        manifest = json.loads(read("extracted_text/manifest.json"))
        sources = []
        for row in manifest:
            if row["level"] not in {"N1", "N2", "N3", "N4", "N5"} or row["year"] < 2010:
                continue
            sources.append(dict(row, text=read(row["output_file"])))
        return sources


def session(source):
    # A year-only file cannot safely be paired with either July or December.
    if source.get("month") not in {7, 12} or source["year"] < 2010:
        return None
    return source["level"], source["year"], source["month"]


def collect_answers(sources):
    claims = defaultdict(lambda: defaultdict(list))
    for source in sources:
        date = session(source)
        if date is None or not ANSWER_FILE.search(source["source_file"]):
            continue
        for block, number, value, note in answer_claims(source["text"], source["level"]):
            if block.kind in SUPPORTED:
                claims[date + (block.phase, block.number)][number].append((value, source["output_file"], note))
    answers, conflicts = {}, []
    for key, group in claims.items():
        result = {}
        for number, values in group.items():
            unique = {tuple(v[0]) if isinstance(v[0], list) else v[0] for v in values}
            if len(unique) != 1:
                conflicts.append(dict(group=key, number=number, claims=values))
                break
            result[number] = values[0][0] if number == "sequence" else values[0]
        else:
            result["sources"] = sorted({value[1] for values in group.values() for value in values})
            answers[key] = result
    return answers, conflicts


def fingerprint(row):
    compact = lambda text: re.sub(r"\s+", "", normalize(text))  # noqa: E731
    return row["level"], compact(row["prompt"]), tuple(sorted(compact(o) for o in row["options"]))


def existing_fingerprints(output):
    found = set()
    for directory in (ROOT / "data", ROOT / "local_data"):
        for path in directory.glob("*.jsonl"):
            if path.resolve() == output.resolve():
                continue
            for line in path.read_text(encoding="utf-8-sig").splitlines():
                if line.strip():
                    found.add(fingerprint(json.loads(line)))
    return found


def convert(sources, existing=()):
    answers, conflicts = collect_answers(sources)
    rejected, candidates = [], defaultdict(list)
    answer_sources_by_id = {}
    for source in sources:
        date = session(source)
        if date is None:
            rejected.append(dict(file=source["output_file"], reason="unknown_exam_month"))
            continue
        if source["method"] != "text":
            rejected.append(dict(file=source["output_file"], reason="ocr_requires_original_page_verification"))
            continue
        for block in blocks(source["text"], source["level"]):
            if block.kind not in SUPPORTED:
                continue
            key = date + (block.phase, block.number)
            if key not in answers:
                rejected.append(dict(file=source["output_file"], group=key, reason="no_unambiguous_answer_group"))
                continue
            try:
                questions = parse_questions(block, answers[key])
            except ValueError as exc:
                rejected.append(dict(file=source["output_file"], group=key, reason=str(exc)))
                continue
            for question in questions:
                number = question.pop("number")
                level, year, month = date
                row = dict(
                    question,
                    id=f"jlpt-test-{level.lower()}-{year}{month:02}-{block.phase}-m{block.number}-q{number}",
                    level=level,
                    category="grammar" if block.kind.startswith("grammar_") else "vocabulary",
                    question_type=block.kind,
                    explanation="来源正答表提供答案；暂无可靠的逐题解析。",
                    source=f"jlpt-test 收录 {year} 年 {month} 月 {level} 真题文本（本地自用）",
                    source_url=f"https://github.com/eulerex/jlpt-test/blob/{REVISION}/"
                    + quote(source["output_file"], safe="/"),
                    ai_generated=False,
                    provenance="上游标记为新制历年真题；文本提取，未逐题人工校对，可能存在转录或 OCR 错误。",
                    license="Local personal-use import; original rights retained. No redistribution license provided.",
                )
                Question.from_dict(row, ROOT / "local_data")
                candidates[row["id"]].append((source, row))
                answer_sources_by_id[row["id"]] = answers[key]["sources"]
    seen, records, duplicates = set(existing), [], []
    for identity, variants in sorted(candidates.items()):
        # Conflicting text versions are not silently resolved.
        versions = [row for _, row in variants]
        signatures = {(fingerprint(r), normalize(r["options"][r["answer"]])) for r in versions}
        if len(signatures) != 1:
            rejected.append(dict(id=identity, reason="conflicting_question_versions"))
            continue
        row = versions[0]
        if identity in EXCLUDED:
            rejected.append(dict(id=identity, reason="known_transcription_error", detail=EXCLUDED[identity]))
            continue
        signature = fingerprint(row)
        if signature in seen:
            duplicates.append(identity)
            continue
        seen.add(signature)
        records.append(row)
    by_content = defaultdict(list)
    for row in records:
        by_content[fingerprint(row)].append(row)
    # Detect contradictory answers even when the session / source ID differs.
    for variants in candidates.values():
        for _, row in variants:
            if fingerprint(row) in by_content:
                by_content[fingerprint(row)].append(row)
    contradictory = {
        key
        for key, group in by_content.items()
        if len({re.sub(r"\s+", "", normalize(r["options"][r["answer"]])) for r in group}) > 1
    }
    for row in records:
        if fingerprint(row) in contradictory:
            rejected.append(dict(id=row["id"], reason="identical_question_conflicting_answers"))
    records = [r for r in records if fingerprint(r) not in contradictory]
    report = dict(
        revision=REVISION,
        archive_sha256=SHA256,
        modern_source_files=len(sources),
        answer_groups=len(answers),
        imported=len(records),
        by_level=dict(sorted(Counter(r["level"] for r in records).items())),
        by_type=dict(sorted(Counter(r["question_type"] for r in records).items())),
        accepted=[
            dict(
                id=row["id"],
                question_source=row["source_url"],
                answer_files=answer_sources_by_id[row["id"]],
            )
            for row in records
        ],
        answer_conflicts=conflicts,
        duplicates=duplicates,
        skipped=rejected,
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
        raise ValueError(f"No safe questions recovered; existing bank preserved. See {report_path}")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(".jsonl.tmp")
    temporary.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records), encoding="utf-8")
    temporary.replace(output)
    print(json.dumps({k: report[k] for k in ("imported", "by_level", "by_type")}, ensure_ascii=False))
    print(f"Local bank: {output}\nAudit report: {report_path}")


if __name__ == "__main__":
    main()
