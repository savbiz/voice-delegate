import { afterEach, expect, test, vi } from 'vitest';
import { voiceOptions } from './provider-options';
import { renderToStaticMarkup } from 'react-dom/server';
import { createElement } from 'react';
import { SpeakingStatus, CostPanel } from '../components/SessionPanels';

afterEach(() => vi.unstubAllGlobals());

test('provider discovery validates the complete allowlist and deduplicates', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue(
      Response.json({
        session_ui: true,
        adapter: 'openai',
        available_adapters: ['openai', 'azure', 'openai'],
      }),
    ),
  );
  expect((await voiceOptions(new AbortController().signal))?.available_adapters).toEqual([
    'openai',
    'azure',
  ]);
});

test.each([
  { session_ui: false },
  { session_ui: true, adapter: 'openai', available_adapters: ['unknown'] },
  { session_ui: true, adapter: 'openai', available_adapters: ['azure'] },
])('invalid or disabled discovery preserves the existing fixed provider UI', async (json) => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(Response.json(json)));
  expect(await voiceOptions(new AbortController().signal)).toBeUndefined();
});

test('discovery failures and oversized responses fall back without leaking payloads', async () => {
  vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('private body')));
  expect(await voiceOptions(new AbortController().signal)).toBeUndefined();
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('x'.repeat(9000))));
  expect(await voiceOptions(new AbortController().signal)).toBeUndefined();
});

test('audio status describes observed streams rather than claiming speech authority', () => {
  expect(renderToStaticMarkup(createElement(SpeakingStatus, { activity: undefined }))).toContain(
    'unavailable',
  );
  expect(
    renderToStaticMarkup(
      createElement(SpeakingStatus, { activity: { user: true, assistant: false } }),
    ),
  ).toContain('Your microphone is active');
  expect(
    renderToStaticMarkup(
      createElement(SpeakingStatus, { activity: { user: false, assistant: true } }),
    ),
  ).toContain('Assistant audio is active');
  expect(
    renderToStaticMarkup(
      createElement(SpeakingStatus, { activity: { user: true, assistant: true } }),
    ),
  ).toContain('Both audio streams active');
  expect(renderToStaticMarkup(createElement(CostPanel, { cost: undefined }))).toBe('');
});

test('native clients never offer ElevenLabs and choose a compatible default', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue(
      Response.json({
        session_ui: true,
        adapter: 'elevenlabs',
        available_adapters: ['elevenlabs', 'openai', 'azure'],
      }),
    ),
  );
  const options = await voiceOptions(new AbortController().signal, 'platform', true);
  expect(options?.adapter).toBe('openai');
  expect(options?.available_adapters).toEqual(['openai', 'azure']);
});

test('personal discovery uses its own endpoint without keys or platform authorization', async () => {
  const fetch = vi.fn().mockResolvedValue(
    Response.json({
      session_ui: true,
      adapter: 'openai',
      available_adapters: ['openai'],
    }),
  );
  vi.stubGlobal('fetch', fetch);
  await voiceOptions(new AbortController().signal, 'personal');
  expect(fetch.mock.calls[0]?.[0]).toContain('/api/personal/config');
  expect(fetch.mock.calls[0]?.[1].body).toBe('{}');
  expect(fetch.mock.calls[0]?.[1].headers.Authorization).toBeUndefined();
});
