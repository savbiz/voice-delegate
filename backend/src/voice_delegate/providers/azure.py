"""Azure OpenAI GA Realtime: resource endpoint plus api-key header on the shared contract."""

import httpx

from .webrtc import RealtimeWebRTCConnection, RealtimeWebRTCProvider, normalize_event

__all__ = ["AzureRealtimeConnection", "AzureRealtimeProvider", "normalize_event"]

AzureRealtimeConnection = RealtimeWebRTCConnection


class AzureRealtimeProvider(RealtimeWebRTCProvider):
    name = "Azure"

    def __init__(self, endpoint: str, api_key: str, http: httpx.AsyncClient | None = None) -> None:
        super().__init__(endpoint.rstrip("/") + "/openai/v1/realtime", {"api-key": api_key}, http)
