import { expect, test } from '@playwright/test';
import { probe } from '../benchmarks/probe';

test.use({
  launchOptions: {
    args: [
      '--disable-features=WebRtcHideLocalIpsWithMdns',
      '--autoplay-policy=no-user-gesture-required',
    ],
  },
});

function wavFixture(): string {
  const wav = Buffer.alloc(1644);
  wav.write('RIFF', 0);
  wav.writeUInt32LE(wav.length - 8, 4);
  wav.write('WAVEfmt ', 8);
  wav.writeUInt32LE(16, 16);
  wav.writeUInt16LE(1, 20);
  wav.writeUInt16LE(1, 22);
  wav.writeUInt32LE(8000, 24);
  wav.writeUInt32LE(16000, 28);
  wav.writeUInt16LE(2, 32);
  wav.writeUInt16LE(16, 34);
  wav.write('data', 36);
  wav.writeUInt32LE(1600, 40);
  return wav.toString('base64');
}

test('benchmark observes loopback audio and cleans up without calling an API', async ({ page }) => {
  const requests: string[] = [];
  page.on('request', (request) => requests.push(request.url()));
  await page.goto('/');
  const result = await page.evaluate(probe, {
    fake: true,
    speechEndMs: 200,
    timeoutMs: 5000,
  });
  expect(result, JSON.stringify(result)).toMatchObject({ outcome: 'completed' });
  expect(result.delegated).toBe(false);
  expect(result.first_audio_ms).toBeGreaterThan(200);
  expect(result.turn_ms).toBeGreaterThanOrEqual(result.first_audio_ms!);
  expect(requests.some((url) => url.includes('/api/'))).toBe(false);
});

test('benchmark connection errors expose no response content', async ({ page }) => {
  await page.route('**/api/**', (route) =>
    route.fulfill({ status: 401, body: 'private response content' }),
  );
  await page.goto('/');
  const result = await page.evaluate(probe, {
    api: new URL(page.url()).origin,
    wav: wavFixture(),
    speechEndMs: 50,
    timeoutMs: 1000,
  });
  expect(result).toEqual({
    outcome: 'error',
    delegated: null,
    setup_ms: null,
    first_audio_ms: null,
    turn_ms: null,
    failure_stage: 'setup',
  });
});

test('benchmark closes an owned session after offer rejection', async ({ page }) => {
  let closes = 0;
  await page.route('**/api/**', (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith('/offer')) return route.fulfill({ status: 502, json: {} });
    if (path.endsWith('/close')) {
      closes++;
      expect(route.request().headers()['x-session-key']).toBe('fixture-key');
      return route.fulfill({ json: { finalized: true } });
    }
    return route.fulfill({
      json: path.endsWith('/sessions') ? { id: 'fixture', key: 'fixture-key' } : {},
    });
  });
  await page.goto('/');
  const result = await page.evaluate(probe, {
    api: new URL(page.url()).origin,
    wav: wavFixture(),
    speechEndMs: 50,
    timeoutMs: 1000,
  });
  expect(result.outcome).toBe('error');
  expect(result.failure_stage).toBe('setup');
  expect(closes).toBe(1);
});
