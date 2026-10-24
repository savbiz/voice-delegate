/** Deterministic, offline scenario: timings are illustrative, never measured audio. */
export const scenario = [
  { speaker: 'You', text: 'Hi! What can you help me with?', gap: null },
  {
    speaker: 'Assistant',
    text: 'We can talk naturally. Calculations and project questions go to a separate worker.',
    gap: 240,
  },
  { speaker: 'You', text: 'Calculate (120 + 80) * 1.22.', gap: null },
  {
    speaker: 'Assistant',
    text: 'Simulated worker result: 244. The real offline worker is available from the command line.',
    gap: 310,
  },
] as const;
export function visibleScenario(step: number): (typeof scenario)[number][] {
  return scenario.slice(0, Math.max(0, Math.min(step, scenario.length)));
}

/** Exercise the isolated stack; the public static demo never calls this by default. */
export async function runStackDemo(signal: AbortSignal): Promise<string> {
  signal = AbortSignal.any([signal, AbortSignal.timeout(15000)]);
  let owner: { id: string; key: string } | undefined;
  const post = async (path: string, body: unknown = {}, closing = false) => {
    const response = await fetch(`/api${path}`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(owner ? { 'X-Session-Key': owner.key } : {}),
      },
      body: JSON.stringify(body),
      signal: closing
        ? AbortSignal.timeout(3000)
        : AbortSignal.any([signal, AbortSignal.timeout(2000)]),
    });
    if (!response.ok) throw new Error('Offline stack unavailable. Check docker compose logs.');
    const reader = response.body?.getReader();
    if (!reader) throw new Error('Offline stack returned an empty response.');
    const decoder = new TextDecoder();
    let text = '';
    let bytes = 0;
    try {
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        bytes += value.byteLength;
        if (bytes > 8192) throw new Error('Offline stack returned too much data.');
        text += decoder.decode(value, { stream: true });
      }
      return JSON.parse(text + decoder.decode());
    } finally {
      await reader.cancel().catch(() => undefined);
      reader.releaseLock();
    }
  };
  try {
    // Complete creation even after Stop, so its ownership key can be used for cleanup.
    owner = (await post('/sessions', {}, true)) as { id: string; key: string };
    signal.throwIfAborted();
    await post(`/sessions/${owner.id}/offer`, { sdp: 'v=0\r\n' });
    for (let attempt = 0; attempt < 60; attempt += 1) {
      const status = (await post(`/sessions/${owner.id}/heartbeat`)) as {
        delegation: string;
        recap?: { latest_reply: string };
      };
      if (status.delegation === 'completed' && status.recap?.latest_reply)
        return status.recap.latest_reply.slice(0, 500);
      if (['failed', 'timeout', 'delivery_failed'].includes(status.delegation))
        throw new Error('Offline worker failed. Check docker compose logs.');
      await new Promise<void>((resolve) => setTimeout(resolve, 200));
      signal.throwIfAborted();
    }
    throw new Error('Offline worker timed out. Check docker compose logs.');
  } finally {
    if (owner) await post(`/sessions/${owner.id}/close`, {}, true).catch(() => undefined);
  }
}
