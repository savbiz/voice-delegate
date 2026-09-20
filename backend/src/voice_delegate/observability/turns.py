"""Approximate transcript-defined turns with explicit span ownership."""

from dataclasses import dataclass
from time import monotonic

from opentelemetry import trace
from opentelemetry.context import Context

from voice_delegate.providers.models import Transcript

from .metrics import Metrics


@dataclass
class Turn:
    span: trace.Span
    started: float
    user_end: float
    replied: bool = False

    @property
    def context(self) -> Context:
        return trace.set_span_in_context(self.span)


def observe(
    turn: Turn | None, event: Transcript, tracer: trace.Tracer, metrics: Metrics
) -> Turn | None:
    now = monotonic()
    if event.speaker == "user":
        if turn is None or turn.replied or event.start_ms - turn.user_end > 800:
            if turn is not None:
                turn.span.end()
            turn = Turn(
                tracer.start_span(
                    "conversation.turn", attributes={"turn.boundary": "transcript_heuristic"}
                ),
                now,
                event.end_ms,
            )
        else:
            turn.user_end = max(turn.user_end, event.end_ms)
    elif turn is not None and not turn.replied:
        turn.replied = True
        metrics.turn_gap.record(now - turn.started)
        turn.span.add_event("assistant.transcript.first")
    if turn is not None:
        with tracer.start_as_current_span(
            "provider.transcript", context=turn.context, attributes={"speaker": event.speaker}
        ):
            pass
    return turn
