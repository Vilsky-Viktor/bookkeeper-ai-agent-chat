"""The chat eval's types: one eval case and one model run of it."""

from dataclasses import dataclass, field
from typing import Callable


@dataclass
class Run:
    calls: list[tuple[str, dict]]
    text: str
    input_tokens: int = 0
    cached_tokens: int = 0
    output_tokens: int = 0

    def called(self, name: str) -> list[dict]:
        return [a for n, a in self.calls if n == name]


@dataclass
class Case:
    name: str
    message: str
    check: Callable[[Run], str | None]  # None = pass, else the failure reason
    history: list[dict] = field(default_factory=list)
    # Messages added after the user's message by a workflow that ran before the
    # assistant this turn (e.g. the receipt workflow's extract_receipt result).
    workflow_messages: list = field(default_factory=list)
    working_set: dict = field(default_factory=dict)
    summary: str | None = None
    language: str = "en"
