import { afterEach, expect, test, vi } from 'vitest';
import { wakeVoiceOptions, type WakeState } from './wake';

afterEach(() => vi.unstubAllGlobals());

const config = { session_ui: true, adapter: 'openai', available_adapters: ['openai'] };

function harness() {
  let clock = 0;
  const states: WakeState[] = [];
  const delays: number[] = [];
  return {
    states,
    delays,
    run: (deadlineMs = 30000) =>
      wakeVoiceOptions(new AbortController().signal, 'platform', false, (s) => states.push(s), {
        deadlineMs,
        now: () => clock,
        sleep: async (ms) => {
          delays.push(ms);
          clock += ms;
        },
      }),
  };
}

test('a sleeping server is retried with backoff until it answers', async () => {
  const fetch = vi
    .fn()
    .mockRejectedValueOnce(new TypeError('network'))
    .mockResolvedValueOnce(new Response('', { status: 503 }))
    .mockResolvedValueOnce(Response.json(config));
  vi.stubGlobal('fetch', fetch);
  const h = harness();
  expect((await h.run())?.adapter).toBe('openai');
  expect(h.delays).toEqual([1000, 2000]);
  expect(h.states).toEqual(['waking', 'waking', 'ready']);
});

test('an answering server with unusable configuration is not retried', async () => {
  const fetch = vi.fn().mockResolvedValue(Response.json({ session_ui: false }));
  vi.stubGlobal('fetch', fetch);
  const h = harness();
  expect(await h.run()).toBeUndefined();
  expect(fetch).toHaveBeenCalledTimes(1);
  expect(h.states).toEqual(['ready']);
});

test('retries stop at the deadline and report the server as unavailable', async () => {
  vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('network')));
  const h = harness();
  expect(await h.run(10000)).toBeUndefined();
  expect(h.delays).toEqual([1000, 2000, 4000]);
  expect(h.states.at(-1)).toBe('unavailable');
});

test('an aborted discovery stops without reporting a state', async () => {
  const abort = new AbortController();
  vi.stubGlobal(
    'fetch',
    vi.fn().mockImplementation(() => {
      abort.abort();
      return Promise.reject(new DOMException('aborted', 'AbortError'));
    }),
  );
  const states: WakeState[] = [];
  expect(await wakeVoiceOptions(abort.signal, 'platform', false, (s) => states.push(s))).toBe(
    undefined,
  );
  expect(states).toEqual([]);
});
