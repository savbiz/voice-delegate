"""Bounded transcript context for client delegation, not a durable conversation log."""

import json
from dataclasses import dataclass, field

from voice_delegate.limits.defaults import TRANSCRIPT_GAP_MS
from voice_delegate.limits.tokens import count_tokens, truncate
from voice_delegate.providers.models import Transcript


@dataclass
class History:
    """Merge same-speaker fragments and preserve only recent bounded context."""

    budget: int = 2048
    entries: list[Transcript] = field(default_factory=list)
    first_index: int = 0
    turns: list[Transcript] = field(default_factory=list)

    def append(self, event: Transcript) -> None:
        """Retain a Unicode-safe suffix; never keep a full oversized wire fragment."""
        event = Transcript(
            event.speaker, event.text[-8192:], event.start_ms, event.end_ms, event.committed
        )
        self._append_turn(event)
        if (
            self.entries
            and not event.committed
            and self.entries[-1].speaker == event.speaker
            and (event.start_ms - self.entries[-1].end_ms <= TRANSCRIPT_GAP_MS)
        ):
            previous = self.entries.pop()
            event = Transcript(
                event.speaker,
                (previous.text + event.text)[-8192:],
                previous.start_ms,
                max(previous.end_ms, event.end_ms),
            )
        self.entries.append(event)
        self.first_index += max(0, len(self.entries) - 12)
        self.entries = self.entries[-12:]
        while len(self.entries) > 1 and count_tokens(self._render(self.entries)) > self.budget:
            self.entries.pop(0)
            self.first_index += 1
        if count_tokens(self._render(self.entries)) > self.budget:
            last = self.entries[-1]
            self.entries[-1] = Transcript(
                last.speaker, truncate(last.text, self.budget - 8), last.start_ms, last.end_ms
            )

    def context(self) -> str:
        """Render speaker labels as untrusted user data."""
        return self._render(self.turns or self.entries)

    def delegation_context(self) -> str:
        """Identify the preceding user turn without inferring the intent of a correction."""
        users = [
            item.text
            for item in (self.turns or self.entries)
            if item.speaker == "user" and item.text.strip()
        ]
        return json.dumps(
            {
                "previous_user_turn": truncate(users[-2], 256, max_bytes=2048)
                if len(users) > 1
                else "",
                "conversation": truncate(self.context(), 1536, max_bytes=12000),
            },
            ensure_ascii=False,
        )

    def goal(self) -> str:
        """Use the latest user utterance; never synthesize a task from metadata."""
        return next(
            (
                truncate(item.text.strip(), 512)
                for item in reversed(self.turns or self.entries)
                if item.speaker == "user" and item.text.strip()
            ),
            "",
        )

    @staticmethod
    def _render(entries: list[Transcript]) -> str:
        return "\n".join(f"{item.speaker}: {item.text}" for item in entries)

    def latest_reply(self) -> str:
        return next((item.text for item in reversed(self.turns) if item.speaker == "assistant"), "")

    def _append_turn(self, event: Transcript) -> None:
        # Audio streams overlap: an assistant fragment does not end an ongoing user utterance.
        index = next(
            (
                i
                for i in range(len(self.turns) - 1, -1, -1)
                if self.turns[i].speaker == event.speaker
            ),
            -1,
        )
        previous = self.turns[index] if index >= 0 else None
        if (
            previous is not None
            and not event.committed
            and not previous.committed
            and (
                (
                    index == len(self.turns) - 1
                    and (
                        event.start_ms <= 0 or event.start_ms - previous.end_ms <= TRANSCRIPT_GAP_MS
                    )
                )
                or (
                    event.start_ms > 0
                    and self.turns[-1].start_ms <= previous.end_ms
                    and 0 <= event.start_ms - previous.end_ms <= TRANSCRIPT_GAP_MS
                )
            )
        ):
            self.turns[index] = Transcript(
                event.speaker,
                (previous.text + event.text)[-8192:],
                previous.start_ms,
                max(previous.end_ms, event.end_ms),
            )
        else:
            self.turns.append(event)
        self.turns = self.turns[-12:]
        while len(self.turns) > 1 and count_tokens(self._render(self.turns)) > self.budget:
            self.turns.pop(0)
        if count_tokens(self._render(self.turns)) > self.budget:
            last = self.turns[-1]
            self.turns[-1] = Transcript(
                last.speaker,
                truncate(last.text, self.budget - 8),
                last.start_ms,
                last.end_ms,
                last.committed,
            )
