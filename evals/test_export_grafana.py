"""Trace exports retain bounded timing evidence, never arbitrary attributes or events."""

import asyncio
import json
from collections.abc import AsyncIterator

import httpx
import pytest

from evals import export_grafana
from evals.export_grafana import MAX_BYTES, export_trace, fetch_trace


async def test_total_deadline_cancels_a_drip_response_and_closes_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Drip(httpx.AsyncByteStream):
        closed = False

        async def __aiter__(self) -> AsyncIterator[bytes]:
            for _ in range(3):
                yield b" "
                await asyncio.sleep(0)
            await asyncio.Event().wait()

        async def aclose(self) -> None:
            self.closed = True

    stream = Drip()
    monkeypatch.setattr(export_grafana, "REQUEST_SECONDS", 0.01)
    async with (
        httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: httpx.Response(200, stream=stream))
        ) as client,
        asyncio.timeout(1),
    ):
        with pytest.raises(TimeoutError):
            await export_trace(client, "http://localhost:3000", "tempo", "a" * 32)
    assert stream.closed


async def test_environment_proxy_configuration_cannot_receive_the_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
        monkeypatch.setenv(name, "http://localhost:invalid-port")
    monkeypatch.setenv("NO_PROXY", "")
    # Ignoring the environment must also ignore an invalid environment CA path.
    monkeypatch.setenv("SSL_CERT_FILE", "/nonexistent/benchmark-test-ca.pem")
    async with httpx.AsyncClient(trust_env=False):
        pass
    # Exercise the actual factory with the real HTTPX constructor and no network request.
    with pytest.raises(ValueError, match="canonical"):
        await fetch_trace("http://remote.invalid", "tempo", "a" * 32, "fixture-token")


async def test_grafana_export_discards_content_and_unknown_operation_names() -> None:
    payload = {
        "resourceSpans": [
            {
                "scopeSpans": [
                    {
                        "spans": [
                            {
                                "name": "delegate_task",
                                "startTimeUnixNano": "100",
                                "endTimeUnixNano": "200",
                                "attributes": [
                                    {"key": "text", "value": {"stringValue": "private content"}}
                                ],
                                "events": [{"name": "private event"}],
                            },
                            {
                                "name": "untrusted name",
                                "startTimeUnixNano": "200",
                                "endTimeUnixNano": "300",
                            },
                        ]
                    }
                ]
            }
        ]
    }
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload))
    ) as c:
        result = await export_trace(c, "http://localhost:3000", "tempo", "a" * 32)
    assert result["spans"] == [
        {"operation": "delegate_task", "start_ns": 100, "end_ns": 200},
        {"operation": "other", "start_ns": 200, "end_ns": 300},
    ]
    assert "private" not in json.dumps(result)


async def test_trace_export_rejects_oversized_response_redirects_and_bad_targets() -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, content=b" " * (MAX_BYTES + 1)))
    ) as client:
        with pytest.raises(ValueError, match="size limit"):
            await export_trace(client, "http://localhost:3000", "tempo", "a" * 32)
        with pytest.raises(ValueError, match="canonical"):
            await export_trace(client, "http://remote.invalid", "tempo", "a" * 32)
    async with (
        httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(302, headers={"Location": "https://other.invalid"})
            )
        ) as client,
    ):
        with pytest.raises(httpx.HTTPStatusError):
            await export_trace(client, "http://localhost:3000", "tempo", "a" * 32)
