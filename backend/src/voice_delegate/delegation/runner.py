"""Own finite worker tasks and suppress results invalidated by interruption or close."""

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from time import monotonic

from opentelemetry import trace
from opentelemetry.context import Context
from voice_delegate_agent.reference import GroundedAnswer, Source

from voice_delegate.limits.tokens import truncate
from voice_delegate.observability.metrics import Metrics
from voice_delegate.providers.base import RealtimeConnection
from voice_delegate.providers.models import COMMENTARY_MAX_BYTES, Commentary, ProviderError

from .contracts import DelegationInput, Worker, WorkerBusy

logger = logging.getLogger(__name__)


@dataclass
class DelegationState:
    """Per-session generation, deduplication and UI status without storing results."""

    generation: int = 0
    task: asyncio.Task[None] | None = None
    seen: set[str] = field(default_factory=set)
    status: str = "idle"
    offset_ms: float = -1
    sources: tuple[Source, ...] = ()


class DelegationRunner:
    """Bound active worker invocations globally, even during cancellation cleanup."""

    def __init__(
        self,
        worker: Worker,
        *,
        timeout: float = 15,
        budget: int = 120,
        capacity: int = 4,
        request_limit: int = 64,
        tracer: trace.Tracer | None = None,
        metrics: Metrics | None = None,
    ) -> None:
        self.metrics = metrics or Metrics()
        self.worker = worker
        self.timeout = timeout
        self.budget = budget
        self.capacity = capacity
        self.request_limit = request_limit
        self.tracer = tracer or trace.NoOpTracerProvider().get_tracer(__name__)
        self.work: set[asyncio.Task[str]] = set()

    def cancel(self, state: DelegationState) -> None:
        """Invalidate before canceling so a late return can never be narrated."""
        state.generation += 1
        state.sources = ()
        if state.task is not None and not state.task.done():
            state.status = "cancelled"
            self.metrics.interruptions.add(1)
            state.task.cancel()

    def start(
        self,
        state: DelegationState,
        request_id: str,
        request: DelegationInput,
        connection: RealtimeConnection,
        is_connected: Callable[[], bool],
        context: Context | None = None,
    ) -> None:
        """Dispatch without blocking the provider event reader; duplicates are ignored."""
        if request_id in state.seen:
            return
        self.cancel(state)
        if len(state.seen) >= self.request_limit:
            state.status = "request_limit"
            return
        state.seen.add(request_id)
        state.status = "running"
        generation = state.generation
        state.task = asyncio.create_task(
            self._run(state, generation, request_id, request, connection, is_connected, context),
            name="delegated-task",
        )

    def _finished(self, task: asyncio.Task[str]) -> None:
        self.work.discard(task)
        if not task.cancelled() and (error := task.exception()) is not None:
            logger.debug("Delegated worker failed", exc_info=error)

    async def _run(
        self,
        state: DelegationState,
        generation: int,
        request_id: str,
        request: DelegationInput,
        connection: RealtimeConnection,
        is_connected: Callable[[], bool],
        context: Context | None = None,
    ) -> None:
        started = monotonic()
        child: asyncio.Task[str] | None = None
        try:
            with self.tracer.start_as_current_span(
                "delegate_task", record_exception=False, context=context
            ):
                if len(self.work) >= self.capacity:
                    result, status = "Worker busy; task was not started.", "busy"
                elif not request.goal.strip():
                    result, status = (
                        "Please repeat the task; no usable transcript is available.",
                        "failed",
                    )
                else:
                    child = asyncio.create_task(
                        self.worker.delegate_task(request.goal, request.context)
                    )
                    self.work.add(child)
                    child.add_done_callback(self._finished)
                    done, _ = await asyncio.wait({child}, timeout=self.timeout)
                    if not done:
                        child.cancel()
                        result, status = "Worker timed out; task incomplete.", "timeout"
                    else:
                        try:
                            result, status = child.result(), "completed"
                        except WorkerBusy:
                            result, status = "Worker busy; task was not started.", "busy"
                        except Exception:
                            result, status = "Worker failed; task incomplete.", "failed"
                if generation == state.generation and is_connected():
                    # 500 UTF-8 bytes also conservatively bound the provider's 500-token limit.
                    await connection.send(
                        Commentary(
                            request_id,
                            truncate(result, self.budget, max_bytes=COMMENTARY_MAX_BYTES),
                        )
                    )
                    if generation == state.generation:
                        state.status = status
                        state.sources = result.sources if isinstance(result, GroundedAnswer) else ()
        except asyncio.CancelledError:
            if generation == state.generation:
                state.status = "cancelled"
            if child is not None:
                child.cancel()
            raise
        except ProviderError:
            if generation == state.generation:
                state.status = "delivery_failed"
        except Exception:
            if generation == state.generation:
                state.status = "failed"

        finally:
            self.metrics.operations.record(
                monotonic() - started,
                {
                    "operation": "delegate_task",
                    "outcome": state.status if generation == state.generation else "cancelled",
                },
            )

    async def aclose(self) -> None:
        """Cancel cooperative workers and bound shutdown if an extension misbehaves."""
        for task in self.work:
            task.cancel()
        if self.work:
            await asyncio.wait(self.work, timeout=1)
