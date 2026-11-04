/** Bounded configuration discovery; failure preserves the existing fixed-provider UI. */
export const adapterNames = {
  openai: 'OpenAI · GPT-Live',
  azure: 'Azure',
  elevenlabs: 'ElevenLabs · Agents',
} as const;
export type Adapter = keyof typeof adapterNames;
export type VoiceOptions = {
  adapter: Adapter;
  available_adapters: Adapter[];
  session_ui: true;
  azure_recovery_available?: boolean;
  access_request_available?: boolean;
  access_request_email?: boolean;
  elevenlabs_webhook_url?: string;
};
export async function voiceOptions(
  signal: AbortSignal,
  source: 'platform' | 'personal' = 'platform',
  native = false,
): Promise<VoiceOptions | undefined> {
  return (await discoverVoiceOptions(signal, source, native)).options;
}

/** `reachable` is false when no usable HTTP answer arrived, e.g. while a sleeping host starts. */
export async function discoverVoiceOptions(
  signal: AbortSignal,
  source: 'platform' | 'personal' = 'platform',
  native = false,
  timeoutMs = 3000,
): Promise<{ options?: VoiceOptions; reachable: boolean }> {
  let reachable = false;
  const options = await (async (): Promise<VoiceOptions | undefined> => {
    try {
      const response = await fetch(
        `${import.meta.env.VITE_API_BASE_URL ?? ''}/api/${source === 'personal' ? 'personal/' : ''}config`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: '{}',
          signal: AbortSignal.any([signal, AbortSignal.timeout(timeoutMs)]),
        },
      );
      reachable = ![502, 503, 504].includes(response.status);
      if (!response.ok || !response.body) return;
      const reader = response.body.getReader();
      let raw = '';
      let bytes = 0;
      const decoder = new TextDecoder();
      try {
        for (;;) {
          const { done, value } = await reader.read();
          if (done) break;
          bytes += value.byteLength;
          if (bytes > 8192) return;
          raw += decoder.decode(value, { stream: true });
        }
      } finally {
        await reader.cancel().catch(() => undefined);
        reader.releaseLock();
      }
      const data = JSON.parse(raw + decoder.decode());
      const valid = (value: unknown): value is Adapter =>
        typeof value === 'string' && Object.hasOwn(adapterNames, value);
      if (
        data.session_ui !== true ||
        !valid(data.adapter) ||
        !Array.isArray(data.available_adapters) ||
        !data.available_adapters.length ||
        data.available_adapters.length > 4 ||
        !data.available_adapters.every(valid) ||
        !data.available_adapters.includes(data.adapter)
      )
        return;
      const adapters = [...new Set<Adapter>(data.available_adapters)].filter(
        (adapter) => !native || adapter !== 'elevenlabs',
      );
      if (!adapters.length) return;
      const configured =
        data.voice_available === false
          ? adapters.filter((adapter) => adapter !== data.adapter)
          : adapters;
      return {
        adapter: configured.includes(data.adapter) ? data.adapter : (configured[0] ?? adapters[0]!),
        available_adapters: configured,
        session_ui: true,
        azure_recovery_available: data.azure_recovery_available === true,
        access_request_available: data.access_request_available === true,
        access_request_email: data.access_request_email === true,
        elevenlabs_webhook_url:
          typeof data.elevenlabs_webhook_url === 'string' &&
          data.elevenlabs_webhook_url.length <= 512
            ? data.elevenlabs_webhook_url
            : undefined,
      };
    } catch {
      return;
    }
  })();
  return { options, reachable };
}
