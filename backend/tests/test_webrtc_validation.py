"""Malformed creation responses never attach or hang up an unknown provider call."""

import httpx
import pytest
from voice_delegate.providers.base import SidebandSocket
from voice_delegate.providers.models import ProviderError, SessionConfig
from voice_delegate.providers.realtime import OpenAIRealtimeProvider
from voice_delegate.providers.webrtc import call_identity, validate_answer


@pytest.mark.parametrize(
    "location", [None, "", "/calls/", "/calls/invalid%20id", "/calls/" + "x" * 257]
)
async def test_invalid_call_identity_never_triggers_hangup(location: str | None) -> None:
    headers = {} if location is None else {"Location": location}
    response = httpx.Response(201, text="v=0\r\n", headers=headers)
    with pytest.raises(ProviderError, match="invalid call identity"):
        call_identity(response, "Realtime")
    requests: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request.url.path)
        return httpx.Response(201, text="v=0\r\n", headers=headers)

    class FixtureProvider(OpenAIRealtimeProvider):
        async def _attach(self, call_id: str) -> SidebandSocket:
            raise AssertionError("Invalid identity must not attach")

    provider = FixtureProvider("fixture", httpx.AsyncClient(transport=httpx.MockTransport(respond)))
    try:
        with pytest.raises(ProviderError, match="connection failed"):
            await provider.connect(
                config=SessionConfig("model", "voice", "hello"), offer_sdp="v=0\r\n"
            )
        assert requests == ["/v1/realtime/calls"]
    finally:
        await provider.aclose()


@pytest.mark.parametrize("body", ["not SDP", "v=0\r\n" + "x" * 65536])
async def test_invalid_sdp_closes_only_the_validated_call(body: str) -> None:
    with pytest.raises(ProviderError, match="invalid SDP answer"):
        validate_answer(httpx.Response(201, text=body), "Realtime")
    requests: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request.url.path)
        if request.url.path.endswith("/hangup"):
            return httpx.Response(200)
        return httpx.Response(201, text=body, headers={"Location": "/calls/known_call"})

    class FixtureProvider(OpenAIRealtimeProvider):
        async def _attach(self, call_id: str) -> SidebandSocket:
            raise AssertionError("Invalid SDP must not attach")

    provider = FixtureProvider("fixture", httpx.AsyncClient(transport=httpx.MockTransport(respond)))
    try:
        with pytest.raises(ProviderError, match="connection failed"):
            await provider.connect(
                config=SessionConfig("model", "voice", "hello"), offer_sdp="v=0\r\n"
            )
        assert requests == ["/v1/realtime/calls", "/v1/realtime/calls/known_call/hangup"]
    finally:
        await provider.aclose()
