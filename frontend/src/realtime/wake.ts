import { discoverVoiceOptions, type VoiceOptions } from './provider-options';

export type WakeState = 'ready' | 'waking' | 'unavailable';

const pause = (ms: number, signal: AbortSignal) =>
  new Promise<void>((resolve) => {
    const timer = setTimeout(resolve, ms);
    signal.addEventListener(
      'abort',
      () => {
        clearTimeout(timer);
        resolve();
      },
      { once: true },
    );
  });

/**
 * Discover providers, retrying while a sleeping backend host starts.
 * Only unanswered requests (network error, timeout, 502-504) are retried; a server that
 * answers with an unusable configuration is not retried. Retries stop after `deadlineMs`.
 */
export async function wakeVoiceOptions(
  signal: AbortSignal,
  source: 'platform' | 'personal',
  native: boolean,
  onState: (state: WakeState) => void,
  {
    deadlineMs = 30000,
    now = () => Date.now(),
    sleep = pause,
  }: { deadlineMs?: number; now?: () => number; sleep?: typeof pause } = {},
): Promise<VoiceOptions | undefined> {
  const started = now();
  let delay = 1000;
  for (let attempt = 0; ; attempt++) {
    const remaining = deadlineMs - (now() - started);
    const { options, reachable } = await discoverVoiceOptions(
      signal,
      source,
      native,
      attempt === 0 ? 3000 : Math.max(1000, Math.min(10000, remaining)),
    );
    if (signal.aborted) return undefined;
    if (reachable || options) {
      onState('ready');
      return options;
    }
    if (now() - started + delay >= deadlineMs) {
      onState('unavailable');
      return undefined;
    }
    onState('waking');
    await sleep(delay, signal);
    if (signal.aborted) return undefined;
    delay = Math.min(delay * 2, 8000);
  }
}
