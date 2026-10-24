"""Explicit container-test entry point. Never use this factory for real voice."""

import os

from fastapi import FastAPI

from voice_delegate.api.app import create_app
from voice_delegate.config import load_settings
from voice_delegate.providers.fake import FakeConnection, FakeProvider
from voice_delegate.providers.models import (
    DelegationRequested,
    ProviderCommand,
    SessionConfig,
    Transcript,
)


class ScriptedConnection(FakeConnection):
    """Echo worker commentary as a synthetic transcript, never generated audio."""

    async def send(self, command: ProviderCommand) -> None:
        await super().send(command)
        self.queue.put_nowait(Transcript("assistant", command.content, 200, 300, committed=True))


class ScriptedProvider(FakeProvider):
    async def connect(self, *, config: SessionConfig, offer_sdp: str) -> FakeConnection:  # noqa: ARG002 - provider contract
        connection = ScriptedConnection()
        self.connections.append(connection)
        connection.queue.put_nowait(Transcript("user", "2 + 2", 0, 100))
        connection.queue.put_nowait(DelegationRequested("test-job", 101))
        return connection


def create_test_app() -> FastAPI:
    if os.environ.get("VOICE_SCRIPTED_PROVIDER") != "1":
        message = "Scripted provider requires VOICE_SCRIPTED_PROVIDER=1"
        raise ValueError(message)
    return create_app(load_settings(), ScriptedProvider())


def create_demo_app() -> FastAPI:
    """Isolated offline entry point: refuse configuration that could incur provider usage."""
    if os.environ.get("VOICE_OFFLINE_DEMO") != "1":
        message = "Offline demo requires VOICE_OFFLINE_DEMO=1"
        raise ValueError(message)
    settings = load_settings()
    if (
        settings.worker_mode != "offline"
        or settings.fallback_enabled
        or settings.openai_api_key.get_secret_value()
        or settings.azure_api_key.get_secret_value()
        or settings.debug_recording
    ):
        message = "Offline demo requires offline worker, no provider keys, no fallback or recording"
        raise ValueError(message)
    return create_app(settings, ScriptedProvider())
