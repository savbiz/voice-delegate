"""OpenAI GA Realtime: fixed endpoint plus bearer auth on the shared contract."""

import httpx

from .webrtc import RealtimeWebRTCProvider


class OpenAIRealtimeProvider(RealtimeWebRTCProvider):
    name = "OpenAI Realtime"

    def __init__(self, api_key: str, http: httpx.AsyncClient | None = None) -> None:
        super().__init__(
            "https://api.openai.com/v1/realtime", {"Authorization": f"Bearer {api_key}"}, http
        )
