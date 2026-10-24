from __future__ import annotations

import asyncio
import re
import time
import unicodedata
from dataclasses import dataclass

from .bank import Question


def parse_answer(text: str) -> int | None:
    """Accept only an entire explicit answer; never interpret ordinary chat."""
    text = unicodedata.normalize("NFKC", text).strip()
    match = re.fullmatch(r"(?:答案\s*[:：]?\s*)?([1-4a-dA-D])", text)
    if not match:
        return None
    value = match[1].upper()
    return int(value) - 1 if value.isdigit() else ord(value) - ord("A")


def is_reveal_request(text: str) -> bool:
    return text.strip() in {"查看答案", "放弃作答"}


def session_key(event) -> tuple[str, str, str, str]:
    # Do not use UMO alone: group sessions can be configured per sender in AstrBot.
    group = event.get_group_id()
    return (
        str(event.get_platform_id()),
        str(event.get_self_id()),
        "group" if group else "private",
        str(group or event.get_sender_id()),
    )


@dataclass(eq=False)
class Round:
    key: tuple
    question: Question
    owner_id: str
    origin: str
    group: bool
    state: str = "preparing"
    deadline: float | None = None
    timer: asyncio.Task | None = None


class QuizSessions:
    """Mutations are synchronous on the event loop: no await between check and claim."""

    def __init__(self):
        self.rounds: dict[tuple, Round] = {}

    def reserve(self, key: tuple, question: Question, owner: str, origin: str, group: bool) -> Round | None:
        if key in self.rounds:
            return None
        round_ = Round(key, question, owner, origin, group)
        self.rounds[key] = round_
        return round_

    def activate(self, round_: Round, timeout: float) -> bool:
        if self.rounds.get(round_.key) is not round_ or round_.state != "preparing":
            return False
        round_.deadline = time.monotonic() + timeout if timeout > 0 else None
        round_.state = "active"
        return True

    def active(self, key: tuple) -> Round | None:
        round_ = self.rounds.get(key)
        return round_ if round_ and round_.state == "active" else None

    def claim(self, round_: Round) -> bool:
        if self.active(round_.key) is not round_:
            return False
        round_.state = "settling"
        if round_.timer and round_.timer is not asyncio.current_task():
            round_.timer.cancel()
        return True

    def release(self, round_: Round) -> None:
        if self.rounds.get(round_.key) is round_:
            self.rounds.pop(round_.key)
        if round_.timer and round_.timer is not asyncio.current_task():
            round_.timer.cancel()
        round_.state = "closed"
