import { readFileSync, readdirSync } from 'node:fs';
import vercel from '../vercel.json' with { type: 'json' };
import { expect, test } from '@playwright/test';
test('SDK transport rejects unavailable mixed recording before session creation', async ({
  page,
}) => {
  const requests: string[] = [];
  await page.route('**/api/**', (route) => {
    const path = new URL(route.request().url()).pathname;
    requests.push(path);
    return route.fulfill({
      json: { voice_available: true, transport: 'elevenlabs_agents_webrtc' },
    });
  });
  await page.goto('/');
  await page.getByRole('link', { name: 'Live voice', exact: true }).click();
  await page.getByText('Voice settings & recording', { exact: true }).click();
  await page.getByLabel(/Record audio locally/).check();
  await page.getByRole('button', { name: 'Start conversation' }).click();
  await expect(page.locator('#status')).toContainText('Mixed audio recording is not available');
  expect(requests.every((path) => path.endsWith('/config'))).toBe(true);
});

test('the installed SDK audio worklet loads under the production CSP without external scripts', async ({
  page,
}) => {
  const assetDirectory = new URL('../dist/assets/', import.meta.url);
  const filename = readdirSync(assetDirectory).find((name) =>
    /^rawAudioProcessor-.*\.js$/.test(name),
  );
  expect(filename).toBeDefined();
  const source = readFileSync(new URL(filename!, assetDirectory), 'utf8');
  const processor = source.match(/registerProcessor\("([^"]+)"/)?.[1];
  expect(processor).toBeDefined();
  const headers = Object.fromEntries(
    vercel.headers.flatMap((route) => route.headers.map(({ key, value }) => [key, value])),
  );
  const errors: string[] = [];
  page.on('console', (message) => {
    if (message.type() === 'error') errors.push(message.text());
  });
  await page.route('**/', async (route) => {
    const response = await route.fetch();
    await route.fulfill({ response, headers: { ...response.headers(), ...headers } });
  });
  await page.goto('/#demo');
  const loaded = await page.evaluate(
    async ({ url, name }) => {
      const context = new AudioContext();
      try {
        await context.audioWorklet.addModule(url);
        const node = new AudioWorkletNode(context, name);
        node.disconnect();
        return true;
      } finally {
        await context.close();
      }
    },
    { url: `/assets/${filename}`, name: processor! },
  );
  expect(loaded).toBe(true);
  expect(errors).toEqual([]);
});
