"""OpenAI GA Realtime: same wire contract as Azure, fixed endpoint and bearer auth."""

import httpx

from .azure import AzureRealtimeConnection, AzureRealtimeProvider
from .models import ProviderError, SessionConfig


class OpenAIRealtimeProvider(AzureRealtimeProvider):
    def __init__(self, api_key: str, http: httpx.AsyncClient | None = None) -> None:
        super().__init__("https://api.openai.com", api_key, http)
        self._endpoint = "https://api.openai.com/v1/realtime"
        self._headers = {"Authorization": f"Bearer {api_key}"}

    async def connect(self, *, config: SessionConfig, offer_sdp: str) -> AzureRealtimeConnection:
        try:
            return await super().connect(config=config, offer_sdp=offer_sdp)
        except ProviderError as exc:
            raise ProviderError(
                "OpenAI Realtime connection failed; check server configuration"
            ) from exc
