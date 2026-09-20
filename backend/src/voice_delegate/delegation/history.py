"""Bounded transcript context for client delegation, not a durable conversation log."""

from dataclasses import dataclass, field

from voice_delegate.limits.tokens import count_tokens, truncate
from voice_delegate.providers.models import Transcript


@dataclass
class History:
    """Merge same-speaker fragments and preserve only recent bounded context."""

    budget: int = 2048
    entries: list[Transcript] = field(default_factory=list)

    def append(self, event: Transcript) -> None:
        """Retain a Unicode-safe suffix; never keep a full oversized wire fragment."""
        event = Transcript(event.speaker, event.text[-8192:], event.start_ms, event.end_ms)
        if (
            self.entries
            and self.entries[-1].speaker == event.speaker
            and (event.start_ms - self.entries[-1].end_ms <= 800)
        ):
            previous = self.entries.pop()
            event = Transcript(
                event.speaker,
                (previous.text + event.text)[-8192:],
                previous.start_ms,
                max(previous.end_ms, event.end_ms),
            )
        self.entries.append(event)
        self.entries = self.entries[-12:]
        while len(self.entries) > 1 and count_tokens(self.context()) > self.budget:
            self.entries.pop(0)
        if count_tokens(self.context()) > self.budget:
            last = self.entries[-1]
            self.entries[-1] = Transcript(
                last.speaker, truncate(last.text, self.budget - 8), last.start_ms, last.end_ms
            )

    def context(self) -> str:
        """Render speaker labels as untrusted user data."""
        return "\n".join(f"{item.speaker}: {item.text}" for item in self.entries)

    def goal(self) -> str:
        """Use the latest user utterance; never synthesize a task from metadata."""
        return next(
            (
                truncate(item.text.strip(), 512)
                for item in reversed(self.entries)
                if item.speaker == "user" and item.text.strip()
            ),
            "",
        )
