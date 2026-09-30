# WebRTC boundary

The browser implementation lives in `frontend/src/realtime/live.ts` so Vite builds a self-contained frontend. This directory documents the transport boundary; it is not a second service.

Audio flows directly between the browser and GPT-Live. FastAPI exchanges SDP and owns server control. The React component mounts one transport controller and releases it when unmounted, including mode switches. A generation counter rejects stale microphone permission and SDP results. Captions are capped at 6,000 characters per speaker; displayed timing history at 20 rows. Stop disables microphone tracks immediately, then requests upstream finalization before releasing the peer. Page exit sends best-effort keepalive cleanup; server heartbeat and absolute deadlines remain authoritative.

`RTCPeerConnection` and the microphone need a secure context: localhost during development, HTTPS when deployed. The free demo is a deterministic browser recording, not a fake WebRTC connection or model-quality evaluation.

`frontend/src/realtime/vad.ts` supplies a lightweight microphone-energy onset detector that calls the owned `/interrupt` route only while delegated work is running. It suppresses local onset during measurable remote playback to reduce echo-induced cancellation. The Realtime provider's `input_audio_buffer.speech_started` signal is the interruption authority; untimed transcripts do not cancel work. An explicit Cancel task button is also available.
