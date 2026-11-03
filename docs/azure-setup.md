# Configure Azure Live

Azure can be a primary voice provider or a single recovery attempt from OpenAI Live.
Recovery is off by default and needs the session checkbox; Azure billing is separate.

1. In Microsoft Foundry, deploy **gpt-live-1** in a supported region. A Realtime deployment
   cannot serve the Live protocol. Record the deployment name; it may differ from the model.
2. Obtain the Azure OpenAI resource key and origin, e.g. `https://RESOURCE.openai.azure.com`.
   Supply the origin only, without a project path or `/live` suffix.
3. For Platform API, configure the backend:

```dotenv
VOICE_AZURE_ENDPOINT=https://RESOURCE.openai.azure.com
VOICE_AZURE_API_KEY=YOUR_RESOURCE_KEY
VOICE_AZURE_DEPLOYMENT=YOUR_LIVE_DEPLOYMENT_NAME
VOICE_AZURE_VOICE=marin
```

Restart the backend. Azure becomes selectable; to recover an OpenAI session, check
**Allow one Azure recovery** before starting. Select `VOICE_ADAPTER=azure` only to make
Azure the default primary. No fallback-enable environment flag is needed.

For **Your API keys**, enter your own Azure key, resource origin and deployment in the UI.
The same fields appear for Azure primary and for checked OpenAI recovery. Platform Azure
credentials are never substituted for missing personal keys. Fields clear after submission.

The adapter creates `/openai/v1/live/sessions`, authenticates with Bearer credentials,
and attaches a backend sideband. It sends `delegation.type=client`; work remains owned
by the application. A recovery creates another voice session and may incur both providers'
charges; it does not migrate audio or replay completed tools. Azure prices remain explicitly
unpriced in local estimates until an applicable rate is supplied. Actual billed usage is
reported by your Azure account. No live acceptance is implied by offline tests.

Sources: [WebRTC setup](https://learn.microsoft.com/en-us/azure/foundry/openai/how-to/gpt-live-webrtc),
[event reference](https://learn.microsoft.com/en-us/azure/foundry/openai/gpt-live-reference).
Reviewed 2026-11-03; account access and regional availability must be checked separately.
