"""Explicitly export timing-only trace evidence from an existing Grafana Tempo data source."""

import argparse
import asyncio
import json
import os
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx

ALLOWED_NAMES = {
    "provider.connect",
    "provider.failover",
    "provider.close",
    "provider.transcript",
    "delegate_task",
    "session.close",
}
MAX_BYTES = 2_000_000
REQUEST_SECONDS = 5.0


async def export_trace(
    client: httpx.AsyncClient, origin: str, uid: str, trace_id: str
) -> dict[str, object]:
    """Keep timings and known operation names; discard attributes, events and resource data."""
    url = urlsplit(origin)
    if (
        url.scheme not in {"https", "http"}
        or not url.hostname
        or url.username
        or url.password
        or url.query
        or url.fragment
        or url.path
        or (url.scheme == "http" and url.hostname not in {"localhost", "127.0.0.1"})
        or re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", uid) is None
        or re.fullmatch(r"[a-f0-9]{32}", trace_id) is None
    ):
        message = "Expected a canonical Grafana origin, data source UID and hexadecimal trace ID"
        raise ValueError(message)
    endpoint = f"{origin}/api/datasources/proxy/uid/{uid}/api/traces/{trace_id}"
    raw = bytearray()
    async with asyncio.timeout(REQUEST_SECONDS):
        async with client.stream("GET", endpoint, timeout=5, follow_redirects=False) as response:
            response.raise_for_status()
            async for chunk in response.aiter_bytes():
                raw.extend(chunk)
                if len(raw) > MAX_BYTES:
                    message = "Trace exceeds the export size limit"
                    raise ValueError(message)
    data: Any = json.loads(raw)
    if not isinstance(data, dict):
        message = "Expected a Tempo JSON object"
        raise TypeError(message)
    spans = []
    for resource in data.get("batches", data.get("resourceSpans", [])) or []:
        for scope in resource.get("scopeSpans", resource.get("instrumentationLibrarySpans", [])):
            for span in scope.get("spans", []):
                start, end = int(span["startTimeUnixNano"]), int(span["endTimeUnixNano"])
                if start < 0 or end < start:
                    message = "Invalid trace timing"
                    raise ValueError(message)
                spans.append(
                    {
                        "operation": span["name"] if span.get("name") in ALLOWED_NAMES else "other",
                        "start_ns": start,
                        "end_ns": end,
                    }
                )
    if not spans:
        message = "No OTLP spans found; the data source must expose Tempo JSON"
        raise ValueError(message)
    return {"schema_version": 1, "trace_id": trace_id, "spans": spans}


async def fetch_trace(origin: str, uid: str, trace_id: str, token: str) -> dict[str, object]:
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    async with httpx.AsyncClient(headers=headers, trust_env=False) as client:
        return await export_trace(client, origin, uid, trace_id)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--origin", required=True)
    parser.add_argument("--datasource", required=True)
    parser.add_argument("--trace-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    token = os.environ.get("GRAFANA_TOKEN", "")
    try:
        report = asyncio.run(fetch_trace(args.origin, args.datasource, args.trace_id, token))
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + "\n")
    except (
        httpx.HTTPError,
        TimeoutError,
        ValueError,
        KeyError,
        TypeError,
        AttributeError,
        RecursionError,
    ):
        parser.exit(1, "Trace export failed; check access, data source, format and size.\n")


if __name__ == "__main__":
    main()
