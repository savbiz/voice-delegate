"""Trace exports retain bounded timing evidence, never arbitrary attributes or events."""

import json

import httpx
import pytest

from evals.export_grafana import MAX_BYTES, export_trace


def test_grafana_export_discards_content_and_unknown_operation_names() -> None:
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
    with httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload))
    ) as c:
        result = export_trace(c, "http://localhost:3000", "tempo", "a" * 32)
    assert result["spans"] == [
        {"operation": "delegate_task", "start_ns": 100, "end_ns": 200},
        {"operation": "other", "start_ns": 200, "end_ns": 300},
    ]
    assert "private" not in json.dumps(result)


def test_trace_export_rejects_oversized_response_redirects_and_bad_targets() -> None:
    with httpx.Client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, content=b" " * (MAX_BYTES + 1)))
    ) as client:
        with pytest.raises(ValueError, match="size limit"):
            export_trace(client, "http://localhost:3000", "tempo", "a" * 32)
        with pytest.raises(ValueError, match="canonical"):
            export_trace(client, "http://remote.invalid", "tempo", "a" * 32)
    with (
        httpx.Client(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(302, headers={"Location": "https://other.invalid"})
            )
        ) as client,
        pytest.raises(httpx.HTTPStatusError),
    ):
        export_trace(client, "http://localhost:3000", "tempo", "a" * 32)
