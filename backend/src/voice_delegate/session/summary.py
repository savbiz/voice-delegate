"""Bounded extractive recap: user words and task state, never inferred completion."""

from dataclasses import dataclass

from voice_delegate.limits.tokens import truncate
from voice_delegate.providers.models import Transcript


@dataclass
class Recap:
    latest_request: str = ""
    latest_reply: str = ""
    interrupted: bool = False
    revision: int = 0

    def observe(self, event: Transcript, goal: str) -> None:
        if event.speaker == "user":
            self.latest_request = truncate(goal, 128, max_bytes=600)
            self.latest_reply = ""
            self.revision += 1
        elif not self.interrupted:
            self.latest_reply = truncate(event.text, 128, max_bytes=600)

    def interrupt(self) -> None:
        self.interrupted = True
        self.latest_reply = ""
        self.revision += 1

    def resume(self) -> None:
        self.interrupted = False
        self.latest_reply = ""
