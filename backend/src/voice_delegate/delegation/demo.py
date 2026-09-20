"""Run the real LangGraph worker offline from the command line, without voice or API keys."""

import argparse
import asyncio
import json

from voice_delegate_agent.graph import LangGraphWorker, OfflinePlanner

from voice_delegate.limits.tokens import count_tokens, truncate


async def run(goal: str) -> str:
    """Execute local read-only tools within the same default time/output budgets."""
    async with asyncio.timeout(15):
        result = await LangGraphWorker(OfflinePlanner()).delegate_task(goal[:8192], "")
    return truncate(result, 120, max_bytes=500)


def main() -> None:
    """Print a bounded result and its application token count."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("goal", nargs="?", default="calculate (120 + 80) * 1.22")
    args = parser.parse_args()
    result = asyncio.run(run(args.goal))
    print(
        json.dumps(
            {"mode": "offline", "result": result, "tokens": count_tokens(result)},
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
