"""Explicit development-only recording, separate from content-free feedback."""

import json
import logging
import os
import time
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

logger = logging.getLogger(__name__)
MAX_BYTES = 2 * 1024 * 1024
MAX_RECORDINGS = 20
RETENTION_SECONDS = 86400


class DebugSample(BaseModel):
    """An allowlist excludes SDP, candidate addresses, device IDs and headers."""

    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    event: Literal["stats", "local_onset", "client_stop", "peer_state", "channel_closed"]
    peer_state: (
        Literal["new", "connecting", "connected", "disconnected", "failed", "closed"] | None
    ) = None
    packets_lost: int | None = Field(default=None, ge=0)
    packets_received: int | None = Field(default=None, ge=0)
    jitter_seconds: float | None = Field(default=None, ge=0, le=3600)
    concealed_samples: int | None = Field(default=None, ge=0)
    audio_level: float | None = Field(default=None, ge=0, le=1)


def purge_recordings(directory: Path) -> None:
    if directory.exists():
        for path in directory.glob("*.jsonl"):
            if path.stat().st_mtime < time.time() - RETENTION_SECONDS:
                path.unlink()


class DebugRecording:
    """Bounded local JSONL file; callers explicitly select each recorded field."""

    def __init__(self, directory: Path, identity: str) -> None:
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        directory.chmod(0o700)
        purge_recordings(directory)
        if len(list(directory.glob("*.jsonl"))) >= MAX_RECORDINGS:
            message = "Debug recording capacity reached; remove old recordings"
            raise OSError(message)
        self.path = directory / f"{identity}.jsonl"
        self.size = 0
        self.stopped = False
        descriptor = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        os.close(descriptor)

    def write(self, event: str, **fields: str | int | float | bool | None) -> None:
        if self.stopped:
            return
        data = (
            json.dumps({"at": time.time(), "event": event, **fields}, ensure_ascii=False) + "\n"
        ).encode()
        if self.size + len(data) > MAX_BYTES:
            self.stopped = True
            logger.warning("Debug recording size limit reached; recording stopped")
            return
        try:
            descriptor = os.open(
                self.path, os.O_WRONLY | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0)
            )
            with os.fdopen(descriptor, "ab") as target:
                target.write(data)
            self.size += len(data)
        except OSError:
            self.stopped = True
            logger.warning("Debug recording unavailable; recording stopped")

    def delegation_finished(self, status: str, text: str) -> None:
        """Record only the bounded narration and outcome for an opted-in session."""
        self.write("delegation_finished", status=status, text=text)

    def close(self, finalized: bool) -> None:
        self.write("closed", finalized=finalized)
        self.stopped = True
