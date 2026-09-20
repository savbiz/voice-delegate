"""Explicit container-test entry point. Never use this factory for real voice."""

from fastapi import FastAPI

from voice_delegate.api.app import create_app
from voice_delegate.config import load_settings
from voice_delegate.providers.fake import FakeConnection, FakeProvider
from voice_delegate.providers.models import DelegationRequested, SessionConfig, Transcript


class ScriptedProvider(FakeProvider):
    async def connect(self, *, config: SessionConfig, offer_sdp: str) -> FakeConnection:
        connection = await super().connect(config=config, offer_sdp=offer_sdp)
        connection.queue.put_nowait(Transcript("user", "2 + 2", 0, 100))
        connection.queue.put_nowait(DelegationRequested("test-job", 101))
        return connection


def create_test_app() -> FastAPI:
    return create_app(load_settings(), ScriptedProvider())
