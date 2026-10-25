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

    def observe(self, event: Transcript, goal: str, reply: str | None = None) -> None:
        if event.speaker == "user":
            self.latest_request = truncate(goal, 128, max_bytes=600)
            self.latest_reply = ""
            self.revision += 1
        elif not self.interrupted:
            if reply is not None:
                self.latest_reply = truncate(reply, 128, max_bytes=600)
                return
            if event.committed or not self.latest_reply.endswith("…"):
                text = event.text if event.committed else self.latest_reply + event.text
                self.latest_reply = truncate(text, 128, max_bytes=600)

    def interrupt(self) -> None:
        self.interrupted = True
        self.latest_reply = ""
        self.revision += 1

    def resume(self) -> None:
        self.interrupted = False
        self.latest_reply = ""
