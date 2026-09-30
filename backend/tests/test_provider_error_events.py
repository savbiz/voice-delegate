"""Rejected provider commands do not consume fallback or cancel unrelated work."""

from collections.abc import Callable

import pytest
from conftest import BlockingWorker
from voice_delegate.config import Settings
from voice_delegate.providers.fake import FakeProvider
from voice_delegate.providers.models import (
    DelegationRequested,
    ProviderCommandError,
    ProviderEvent,
    ProviderFailure,
    Transcript,
)
from voice_delegate.providers.openai import normalize_event as live_event
from voice_delegate.providers.webrtc import normalize_event as realtime_event
from voice_delegate.session.manager import SessionManager

from test_support import eventually


@pytest.mark.parametrize("normalize", [live_event, realtime_event])
async def test_command_error_preserves_session_and_running_worker(
    normalize: Callable[[str | bytes], ProviderEvent | None],
    blocking_worker: BlockingWorker,
    caplog: pytest.LogCaptureFixture,
) -> None:
    provider = FakeProvider()
    manager = SessionManager(provider, Settings(), worker=blocking_worker, fallback=FakeProvider())
    session = manager.create()
    await manager.connect(session, "v=0\r\n")
    connection = provider.connections[0]
    connection.queue.put_nowait(DelegationRequested("job", goal="calculate 2+2"))
    await blocking_worker.started.wait()
    event = normalize(
        '{"type":"error","error":{"type":"invalid_request_error","message":"private data"}}'
    )
    assert isinstance(event, ProviderCommandError)
    connection.queue.put_nowait(event)
    connection.queue.put_nowait(Transcript("assistant", "Still connected", 0, 0))
    await eventually(lambda: bool(session.history.entries))
    assert session.state == "connected"
    assert session.delegation.status == "running"
    assert not session.fallback_used
    assert not connection.closed
    assert "private data" not in caplog.text
    failure = normalize('{"type":"error","error":{"type":"server_error"}}')
    assert isinstance(failure, ProviderFailure)
    connection.queue.put_nowait(failure)
    await eventually(lambda: session.state == "reconnecting")
    await manager.aclose()


@pytest.mark.parametrize(
    "arguments", ["{bad json", "{}", '{"goal": 42}', '{"goal":""}', "x" * 8193, {}]
)
async def test_bad_realtime_tool_arguments_keep_reader_alive_and_request_repetition(
    arguments: object,
) -> None:
    import json

    import httpx
    from test_provider import MemorySocket
    from voice_delegate.providers.models import WebRTCAnswer
    from voice_delegate.providers.realtime import OpenAIRealtimeProvider
    from voice_delegate.providers.webrtc import RealtimeWebRTCConnection

    socket = MemorySocket()
    provider = OpenAIRealtimeProvider(
        "fixture", httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200)))
    )
    connection = RealtimeWebRTCConnection(WebRTCAnswer("call", "sdp"), socket, provider)
    manager = SessionManager(FakeProvider(), Settings())
    session = manager.create()
    session.connection, session.state = connection, "connected"
    session.history.append(Transcript("user", "calculate 9+9", 0, 0))
    import asyncio

    session.watcher = asyncio.create_task(manager._watch(session))
    socket.incoming.put_nowait(
        json.dumps(
            {
                "type": "response.function_call_arguments.done",
                "name": "delegate_task",
                "call_id": "invalid-task",
                "arguments": arguments,
            }
        )
    )
    await eventually(lambda: len(socket.sent) == 2)
    result = json.loads(socket.sent[0])["item"]
    assert result["call_id"] == "invalid-task"
    assert "Please repeat" in result["output"]
    assert "18" not in result["output"]
    assert not connection._failed and not connection._reader.done()
    assert session.state == "connected"
    await manager.aclose()
    await provider.aclose()


async def test_unknown_realtime_tool_returns_error_and_continues_reading() -> None:
    import json

    import httpx
    from test_provider import MemorySocket
    from voice_delegate.providers.models import WebRTCAnswer
    from voice_delegate.providers.realtime import OpenAIRealtimeProvider
    from voice_delegate.providers.webrtc import RealtimeWebRTCConnection

    socket = MemorySocket()
    provider = OpenAIRealtimeProvider(
        "fixture", httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200)))
    )
    connection = RealtimeWebRTCConnection(WebRTCAnswer("call", "sdp"), socket, provider)
    socket.incoming.put_nowait(
        json.dumps(
            {
                "type": "response.function_call_arguments.done",
                "name": "unknown",
                "call_id": "unknown-task",
                "arguments": "{}",
            }
        )
    )
    events = connection.events()
    event = await anext(events)
    assert isinstance(event, ProviderCommandError)
    result = json.loads(socket.sent[0])["item"]
    assert result == {
        "type": "function_call_output",
        "call_id": "unknown-task",
        "output": "Unknown tool; no action taken.",
    }
    socket.incoming.put_nowait(
        '{"type":"conversation.item.input_audio_transcription.completed","transcript":"still here"}'
    )
    assert isinstance(await anext(events), Transcript)
    assert not connection._failed and not connection._reader.done()
    await events.aclose()
    await connection.aclose()
    await provider.aclose()


def test_documented_tool_schema_matches_realtime_registration() -> None:
    import json
    from pathlib import Path

    from voice_delegate.providers.webrtc import DELEGATE_TASK_TOOL

    schema = Path(__file__).resolve().parents[2] / "docs/delegate_task.schema.json"
    assert json.loads(schema.read_text()) == DELEGATE_TASK_TOOL


async def test_unknown_tool_response_during_teardown_does_not_fail_stream() -> None:
    import httpx
    from test_provider import MemorySocket
    from voice_delegate.providers.models import WebRTCAnswer
    from voice_delegate.providers.realtime import OpenAIRealtimeProvider
    from voice_delegate.providers.webrtc import RealtimeWebRTCConnection

    socket = MemorySocket()
    provider = OpenAIRealtimeProvider(
        "fixture", httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200)))
    )
    connection = RealtimeWebRTCConnection(WebRTCAnswer("call", "sdp"), socket, provider)
    socket.incoming.put_nowait(
        '{"type":"response.function_call_arguments.done","name":"unknown",'
        '"call_id":"closing-task","arguments":"{}"}'
    )
    await eventually(lambda: not connection._queue.empty())
    await connection.aclose()
    events = connection.events()
    event = await anext(events)
    assert isinstance(event, ProviderCommandError)
    assert event.call_id == "closing-task"
    with pytest.raises(StopAsyncIteration):
        await anext(events)
    assert not connection._failed
    assert not socket.sent
    await events.aclose()
    await provider.aclose()


async def test_realtime_hangup_respects_configured_close_timeout() -> None:
    import asyncio

    import httpx
    from voice_delegate.providers.realtime import OpenAIRealtimeProvider

    cancelled = asyncio.Event()

    async def blocked(request: httpx.Request) -> httpx.Response:
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()
        return httpx.Response(200)

    provider = OpenAIRealtimeProvider(
        "fixture", httpx.AsyncClient(transport=httpx.MockTransport(blocked))
    )
    provider.close_timeout = 0.01
    assert not await provider.hangup("call")
    assert cancelled.is_set()
    await provider.aclose()
