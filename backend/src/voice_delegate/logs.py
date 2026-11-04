"""One JSON object per log line for hosted platforms, with the real level as a field.

Railway (and similar hosts) label a line by its output stream unless it is JSON with a
`level` field. Uvicorn's default configuration writes its lifecycle messages to stderr,
so a normal restart showed up as a burst of errors. The production image passes
`backend/logging.json` (copied to `/app/logging.json`) to Uvicorn, which routes every
logger through this formatter to stdout. Local development keeps Uvicorn's readable text.

Records carry only what the code already logs: no transcripts, credentials or bodies.
"""

import json
import logging
import re
from datetime import UTC, datetime

# Polled every few hundred milliseconds by a live browser; successful calls are noise.
QUIET_PATHS = re.compile(
    r"^/api/sessions/[^/]+/(heartbeat|activity|audio-timing|debug|elevenlabs/events)$"
)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, object] = {
            "time": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname.lower(),
            "logger": record.name,
            "message": record.getMessage(),
        }
        access = access_fields(record)
        if access:
            entry.update(access)
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry, ensure_ascii=False)


def access_fields(record: logging.LogRecord) -> dict[str, object] | None:
    """Uvicorn access records pass (client, method, path, version, status) as arguments."""
    if record.name != "uvicorn.access" or not isinstance(record.args, tuple):
        return None
    if len(record.args) != 5:
        return None
    _, method, path, _, status = record.args
    return {"method": method, "path": path, "status": status}


class QuietAccessFilter(logging.Filter):
    """Drop successful access lines for high-frequency session endpoints and preflights."""

    def filter(self, record: logging.LogRecord) -> bool:
        fields = access_fields(record)
        if fields is None:
            return True
        status = fields["status"]
        if not isinstance(status, int) or status >= 400:
            return True
        path = str(fields["path"]).split("?", 1)[0]
        return fields["method"] != "OPTIONS" and QUIET_PATHS.match(path) is None
