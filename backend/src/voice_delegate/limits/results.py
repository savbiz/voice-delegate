"""Apply narration budgets without silently turning cited web evidence into plain claims."""

import re
from dataclasses import replace

from voice_delegate_agent.reference import WorkerResult

from voice_delegate.limits.tokens import truncate
from voice_delegate.providers.models import COMMENTARY_MAX_BYTES


def clip_worker_result(
    result: WorkerResult,
    budget: int,
    *,
    max_bytes: int = COMMENTARY_MAX_BYTES,
    prefix: str = "",
) -> WorkerResult:
    """Fail closed when clipping removes every citation to attached web evidence."""
    text = truncate(prefix + result.text, budget, max_bytes=max_bytes)
    web_indices = {
        index for index, source in enumerate(result.sources, 1) if source.section == "Web search"
    }
    # A request reminder can itself contain citation-like text; it is not answer evidence.
    answer = text[len(prefix) :] if text.startswith(prefix) else ""
    retained = {int(index) for index in re.findall(r"\[(\d+)\]", answer)}
    if result.status == "completed" and web_indices and not (web_indices & retained):
        return WorkerResult(
            truncate(
                "Web result lost its citations; task incomplete.", budget, max_bytes=max_bytes
            ),
            status="failed",
        )
    return replace(result, text=text)
