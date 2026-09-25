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
