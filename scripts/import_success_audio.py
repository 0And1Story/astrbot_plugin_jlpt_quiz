"""Download supplementary N4/N5 synthetic listening drills for local personal use.

Audio and converted questions are deliberately excluded from the default bank.
The upstream notices contain provider/character-specific output terms.
"""

import concurrent.futures
import hashlib
import json
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from quiz.bank import Question  # noqa: E402
from scripts.converters import normalize_success  # noqa: E402

REVISION = "708a995691dcd0983e2ede47db423281b1cd343a"
BASE = f"https://raw.githubusercontent.com/gauravhq/JLPTSuccess/{REVISION}/"


def main():
    output = ROOT / "local_data"
    cache = ROOT / "tmp" / "private_sources" / "success"
    records, report = [], []
    for level in ("N4", "N5"):

        def fetch(path):
            target = cache / path
            if not target.exists():
                for attempt in range(3):
                    try:
                        with urllib.request.urlopen(BASE + path, timeout=25) as response:
                            data = response.read()
                        break
                    except OSError:
                        if attempt == 2:
                            raise
                        time.sleep(attempt + 1)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
            return target.read_bytes()

        for notice in ("LICENSE", f"{level}/CONTENT-LICENSE.md", f"{level}/NOTICES.md"):
            fetch(notice)
        rows = json.loads(fetch(f"{level}/data/listening.json"))
        if isinstance(rows, dict):
            rows = rows.get("items")
        if not isinstance(rows, list):
            raise ValueError("Upstream listening schema changed")

        def convert(row):
            candidate = normalize_success(row, level, "listening")[0]
            path = row["audio"]
            if path.startswith(("/", "http")) or ".." in Path(path).parts:
                raise ValueError("Unexpected upstream audio path")
            content = fetch(f"{level}/{path}")
            destination = Path("success") / level / path
            target = output / destination
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
            duration = 0
            if shutil.which("ffprobe"):
                result = subprocess.run(
                    [
                        "ffprobe",
                        "-v",
                        "error",
                        "-show_entries",
                        "format=duration",
                        "-of",
                        "default=noprint_wrappers=1:nokey=1",
                        str(target),
                    ],
                    capture_output=True,
                    text=True,
                    check=True,
                )
                duration = float(result.stdout.strip())
            candidate.update(
                audio=destination.as_posix(),
                ai_generated=False,
                provenance=(
                    "原始生成方式未披露；含 Claude AI 审核；音频为合成语音"
                    if level == "N5"
                    else "原始生成方式未披露；音频为合成语音"
                ),
                source=f"JLPTSuccess {level} 合成听力（本地自用）",
                source_url=BASE + f"{level}/data/listening.json",
                shuffle_options=False,
                license="Local personal-use import; see upstream content and audio terms.",
                audio_duration_seconds=duration,
            )
            if level == "N5":
                voices = row.get("audio_render_meta", {}).get("voices_used", [])
                candidate["credit"] = "音声：VOICEVOX / " + "、".join(voices)
            Question.from_dict(candidate, output)
            return candidate, dict(id=candidate["id"], sha256=hashlib.sha256(content).hexdigest())

        def checked_convert(row):
            try:
                return convert(row)
            except (ValueError, KeyError, OSError) as exc:
                return None, dict(id=row.get("id"), rejected=str(exc))

        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            for row, item in executor.map(checked_convert, rows):
                if row is not None:
                    records.append(row)
                report.append(item)
    temporary = output / "success-listening.jsonl.tmp"
    temporary.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in records), encoding="utf-8")
    temporary.replace(output / "success-listening.jsonl")
    docs = ROOT / "tmp" / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "success-audio-import.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"Imported {len(records)} local listening questions; no default bank files changed.")


if __name__ == "__main__":
    main()
