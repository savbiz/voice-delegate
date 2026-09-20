# WebRTC boundary

The browser implementation lives in `frontend/src/realtime/live.ts` so Vite builds a self-contained frontend. This directory documents the transport boundary; it is not a second service.

Audio flows directly between the browser and GPT-Live. FastAPI exchanges SDP and owns server control. The React component mounts one transport controller and releases it when unmounted, including mode switches. A generation counter rejects stale microphone permission and SDP results. Captions are capped at 6,000 characters per speaker; displayed timing history at 20 rows. Stop disables microphone tracks immediately, then requests upstream finalization before releasing the peer. Page exit sends best-effort keepalive cleanup; server heartbeat and absolute deadlines remain authoritative.

`RTCPeerConnection` and the microphone need a secure context: localhost during development, HTTPS when deployed. The free demo is a deterministic browser recording, not a fake WebRTC connection or model-quality evaluation.

M2 adds `frontend/src/realtime/vad.ts`: a lightweight microphone-energy onset detector that calls the owned `/interrupt` route. It is heuristic, with timestamped transcript cancellation as a second signal. It cancels delegated work; GPT-Live remains responsible for full-duplex speech behavior. An explicit Cancel task button is also available.
