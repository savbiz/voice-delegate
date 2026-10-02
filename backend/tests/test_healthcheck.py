"""Container readiness checks honor deployment ports and Host validation."""

from email.message import Message
from unittest.mock import MagicMock
from urllib.error import HTTPError, URLError

import pytest
from voice_delegate import healthcheck


@pytest.mark.parametrize(("status", "expected"), [(200, 0), (503, 1)])
def test_healthcheck_uses_local_port_and_allowed_host(
    monkeypatch: pytest.MonkeyPatch, status: int, expected: int
) -> None:
    monkeypatch.setenv("PORT", "9000")
    monkeypatch.setenv("VOICE_ALLOWED_HOSTS", '["demo.onrender.com"]')
    response = MagicMock()
    response.__enter__.return_value.status = status
    opener = MagicMock(return_value=response)
    monkeypatch.setattr(healthcheck, "urlopen", opener)
    assert healthcheck.main() == expected
    request = opener.call_args.args[0]
    assert request.full_url == "http://127.0.0.1:9000/healthz"
    assert request.get_header("Host") == "demo.onrender.com"
    assert opener.call_args.kwargs["timeout"] == 3


def test_healthcheck_reports_unreachable_server(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(healthcheck, "urlopen", MagicMock(side_effect=URLError("offline")))
    assert healthcheck.main() == 1


@pytest.mark.parametrize(("status", "expected"), [(401, 0), (404, 1), (503, 1)])
def test_worker_healthcheck_requires_authentication_boundary(
    monkeypatch: pytest.MonkeyPatch, status: int, expected: int
) -> None:
    opener = MagicMock(side_effect=HTTPError("http://local/jobs", status, "probe", Message(), None))
    monkeypatch.setattr(healthcheck, "urlopen", opener)
    assert healthcheck.main(worker=True) == expected
    assert opener.call_args.args[0].full_url == "http://127.0.0.1:8001/jobs"
    assert opener.call_args.args[0].get_method() == "POST"


@pytest.mark.parametrize("ready_after", [21, None])
def test_container_smoke_readiness_honors_startup_grace(ready_after: int | None) -> None:
    import runpy
    from pathlib import Path
    from types import SimpleNamespace

    import httpx

    smoke = SimpleNamespace(
        **runpy.run_path(str(Path(__file__).resolve().parents[2] / "scripts/smoke_container.py"))
    )
    now = [0.0]
    calls = []

    def sleep(delay: float) -> None:
        now[0] += delay

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if now[0] < 1:
            raise httpx.ConnectError("starting")
        return httpx.Response(200 if ready_after is not None and now[0] >= ready_after else 503)

    with httpx.Client(
        transport=httpx.MockTransport(handler), base_url="http://container"
    ) as client:
        if ready_after is None:
            with pytest.raises(SystemExit, match="readiness budget"):
                smoke.wait_ready(client, clock=lambda: now[0], sleep=sleep)
            assert 25 <= now[0] < 25.3
        else:
            smoke.wait_ready(client, clock=lambda: now[0], sleep=sleep)
            assert ready_after <= now[0] < ready_after + 0.3
    assert set(calls) == {"/healthz"}
    assert len(calls) > 100
