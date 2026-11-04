"""Production logs are one JSON object per line with the real level, without poll noise."""

import io
import json
import logging
import logging.config
from pathlib import Path

import pytest
from voice_delegate.logs import JsonFormatter, QuietAccessFilter

ROOT = Path(__file__).resolve().parents[2]


def access(method: str, path: str, status: int) -> logging.LogRecord:
    return logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        __file__,
        1,
        '%s - "%s %s HTTP/%s" %d',
        ("100.64.0.1:1234", method, path, "1.1", status),
        None,
    )


def test_lines_are_json_with_the_real_level_and_access_fields() -> None:
    formatter = JsonFormatter()
    startup = logging.LogRecord(
        "uvicorn.error", logging.INFO, __file__, 1, "Application startup complete.", (), None
    )
    entry = json.loads(formatter.format(startup))
    assert entry["level"] == "info"  # was labelled "error" because it went to stderr
    assert entry["message"] == "Application startup complete."
    line = json.loads(formatter.format(access("POST", "/api/sessions", 201)))
    assert (line["method"], line["path"], line["status"]) == ("POST", "/api/sessions", 201)
    try:
        raise ValueError("boom")
    except ValueError:
        import sys

        failure = logging.LogRecord(
            "voice_delegate", logging.ERROR, __file__, 1, "failed", (), sys.exc_info()
        )
    assert "ValueError: boom" in json.loads(formatter.format(failure))["exception"]


@pytest.mark.parametrize(
    ("method", "path", "status", "kept"),
    [
        ("POST", "/api/sessions/abc/heartbeat", 200, False),
        ("POST", "/api/sessions/abc/elevenlabs/events", 200, False),
        ("POST", "/api/sessions/abc/activity", 200, False),
        ("OPTIONS", "/api/sessions/abc/close", 200, False),
        ("POST", "/api/sessions/abc/heartbeat", 404, True),
        ("POST", "/api/sessions", 201, True),
        ("POST", "/api/sessions/abc/close", 200, True),
        ("GET", "/healthz", 200, True),
    ],
)
def test_successful_polling_is_dropped_but_failures_and_lifecycle_stay(
    method: str, path: str, status: int, kept: bool
) -> None:
    assert QuietAccessFilter().filter(access(method, path, status)) is kept


def test_shipped_configuration_routes_uvicorn_and_app_logs_to_stdout_as_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = json.loads((ROOT / "backend/logging.json").read_text())
    stream = io.StringIO()
    monkeypatch.setattr("sys.stdout", stream)
    logging.config.dictConfig(config)
    try:
        logging.getLogger("uvicorn.error").info("Started server process [1]")
        logging.getLogger("voice_delegate.session").warning("Provider rejected a command")
        lines = [json.loads(line) for line in stream.getvalue().splitlines()]
        levels = {line["logger"]: line["level"] for line in lines}
        assert levels["uvicorn.error"] == "info"
        assert levels["voice_delegate.session"] == "warning"
    finally:
        logging.config.dictConfig({"version": 1, "disable_existing_loggers": False})
    dockerfile = (ROOT / "deployment/Dockerfile.backend").read_text()
    assert "--log-config /app/logging.json" in dockerfile
    assert "COPY --from=builder /app/backend/logging.json /app/logging.json" in dockerfile
