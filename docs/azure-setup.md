# Configure Azure fallback

Azure is the second voice provider for M3. It is not needed to use the primary Live
provider or the free simulated demo. An Azure subscription and usage billing are separate
from the primary provider account.

1. Open https://ai.azure.com and select an Azure subscription. Create a Microsoft Foundry
   resource/project in a region supporting your chosen Realtime model and deployment type.
2. In Foundry, open Build → Models → Deploy a base model. Select `gpt-realtime` (or another
   supported GA Realtime model). If it is unavailable, check subscription quota, region
   and model availability before proceeding. Record the deployment name you choose.
3. From the resource's Keys and Endpoint settings in Azure, obtain an API key and the
   Azure OpenAI resource endpoint, e.g. `https://RESOURCE.openai.azure.com`.
   This adapter expects that resource origin, not a project URL or a `/realtime` path.
4. Set the following in the repository root `.env`, preserving existing OpenAI settings:

```dotenv
VOICE_FALLBACK_ENABLED=true
VOICE_AZURE_ENDPOINT=https://RESOURCE.openai.azure.com
VOICE_AZURE_API_KEY=YOUR_RESOURCE_KEY
VOICE_AZURE_DEPLOYMENT=YOUR_DEPLOYMENT_NAME
VOICE_AZURE_VOICE=marin
```

5. Restart FastAPI. Test primary voice first, then the controlled recovery scenario in
   [M3](milestones/m3.md). Setting the variables does not itself verify a real Azure call.

`VOICE_AZURE_DEPLOYMENT` is the deployment name you created; it need not equal the model
name. Keep keys in the backend `.env`, never in `VITE_*` variables or committed files.
Leave `VOICE_FALLBACK_ENABLED=false` while Azure is not configured.

Official setup and current availability:
- https://learn.microsoft.com/en-us/azure/foundry/openai/how-to/realtime-audio-webrtc
- https://learn.microsoft.com/en-us/azure/foundry/openai/how-to/realtime-audio

Reviewed 2026-09-20. Portal labels and subscription availability can differ.
