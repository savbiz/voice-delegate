"""Sanitized scripted controls; these are not measurements of model quality."""

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
from voice_delegate.config import Settings
from voice_delegate.providers.fake import FakeProvider
from voice_delegate.providers.models import DelegationRequested, Transcript
from voice_delegate.session.manager import SessionManager

SCENARIOS = json.loads((Path(__file__).parent / "scenarios/control.json").read_text())


@pytest.mark.parametrize("scenario", SCENARIOS, ids=[s["name"] for s in SCENARIOS])
async def test_scripted_control(scenario: dict[str, Any]) -> None:
    provider = FakeProvider()
    manager = SessionManager(provider, Settings())
    session = manager.create()
    await manager.connect(session, "v=0\r\n")
    connection = provider.connections[0]
    connection.queue.put_nowait(Transcript("user", scenario["text"], 0, 10))
    for request in scenario["requests"]:
        connection.queue.put_nowait(DelegationRequested(request, 20))
    await asyncio.sleep(0)
    if session.delegation.task is not None:
        await session.delegation.task
    assert len(connection.commands) == scenario["expected_results"]
    await manager.aclose()
    assert connection.closed and not manager.sessions
