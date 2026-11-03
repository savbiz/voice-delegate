/** Bounded configuration discovery; failure preserves the existing fixed-provider UI. */
export const adapterNames = {
  live: 'OpenAI · GPT-Live',
  realtime: 'OpenAI · Realtime',
  azure: 'Azure · Realtime',
  elevenlabs: 'ElevenLabs · Agents',
} as const;
export type Adapter = keyof typeof adapterNames;
export type VoiceOptions = {
  adapter: Adapter;
  available_adapters: Adapter[];
  session_ui: true;
  elevenlabs_webhook_url?: string;
};
export async function voiceOptions(
  signal: AbortSignal,
  source: 'platform' | 'personal' = 'platform',
  native = false,
): Promise<VoiceOptions | undefined> {
  try {
    const response = await fetch(
      `${import.meta.env.VITE_API_BASE_URL ?? ''}/api/${source === 'personal' ? 'personal/' : ''}config`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: '{}',
        signal: AbortSignal.any([signal, AbortSignal.timeout(3000)]),
      },
    );
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
    return {
      adapter: adapters.includes(data.adapter) ? data.adapter : adapters[0]!,
      available_adapters: adapters,
      session_ui: true,
      elevenlabs_webhook_url:
        typeof data.elevenlabs_webhook_url === 'string' && data.elevenlabs_webhook_url.length <= 512
          ? data.elevenlabs_webhook_url
          : undefined,
    };
  } catch {
    return;
  }
}
