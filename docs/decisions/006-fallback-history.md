# ADR 006: One fallback attempt with clamped text history

Status: accepted 2026-09-30

Context: losing a provider sideband must not leave a hidden active connection or duplicate worker execution. Audio and server state cannot be transparently migrated across providers.

Decision: retain application ownership in `reconnecting`, close the failed connection immediately, cancel active delegation and accept one generation-checked fallback SDP offer under the session lock. Seal every unsealed trailing transcript entry before building the fallback configuration. Replay at most twelve text segments within 2048 tokens; exclude audio, tool calls and tool results. Keep instructions separate from replayed conversation data.

Consequences: the browser creates a new peer and preserves visible conversation context. Setup consumes the attempt even if it times out. Absolute lifetime and quota reservation persist. Finalization is unconfirmed if either provider cannot confirm cleanup. Partial text can lack context; replay does not imply identical provider behavior or permission to repeat external effects. Real Azure and voice acceptance remain separate gates.

See [architecture](../architecture.md) and [API](../api.md).
