import { expect, test } from '@playwright/test';
import { installFakePeers } from './fixtures';

test('personal keys are submitted once without an invitation and cleared from the UI', async ({
  page,
}, testInfo) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.addInitScript(installFakePeers);
  const creations: { body: unknown; authorization?: string }[] = [];
  const ownedAuth: (string | undefined)[] = [];
  await page.route('**/api/**', (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith('/config'))
      return route.fulfill({
        json: {
          session_ui: true,
          adapter: 'live',
          available_adapters: ['live', 'realtime', 'elevenlabs'],
          voice_available: true,
          intent_cancellation: true,
        },
      });
    if (path === '/api/sessions') throw new Error('Personal session attempted platform billing');
    if (path === '/api/personal/sessions') {
      creations.push({
        body: route.request().postDataJSON(),
        authorization: route.request().headers().authorization,
      });
      return route.fulfill({ json: { id: 'personal', key: 'owner' } });
    }
    ownedAuth.push(route.request().headers().authorization);
    return route.fulfill({
      json: path.endsWith('/close')
        ? { finalized: true }
        : path.endsWith('/heartbeat')
          ? { state: 'connected', tasks: [] }
          : { sdp: 'v=0\r\n' },
    });
  });
  await page.goto('/');
  await page.getByLabel('Personal invitation code').fill('operator-invitation');
  await page.getByRole('radio', { name: 'Your API keys', exact: true }).check();
  await expect(page.getByLabel('Personal invitation code')).toHaveCount(0);
  await expect(page.getByRole('combobox', { name: 'Voice provider', exact: false })).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath('personal-api-mobile.png'), fullPage: true });
  await page
    .getByLabel('OpenAI API key (voice and worker)', { exact: true })
    .fill('my-private-openai');
  await page
    .getByLabel('Tavily API key (optional web search)', { exact: true })
    .fill('my-private-tavily');
  await page.getByRole('button', { name: 'Start conversation', exact: true }).click();
  await expect(page.locator('#status')).toContainText('Connected');
  expect(creations).toEqual([
    {
      body: expect.objectContaining({
        adapter: 'live',
        keys: { openai_key: 'my-private-openai', tavily_key: 'my-private-tavily' },
      }),
      authorization: undefined,
    },
  ]);
  await expect(page.getByLabel('OpenAI API key (voice and worker)', { exact: true })).toHaveValue(
    '',
  );
  await expect(page.getByRole('radio', { name: 'Platform API', exact: true })).toBeDisabled();
  expect(await page.evaluate(() => JSON.stringify([localStorage, sessionStorage]))).not.toContain(
    'my-private',
  );
  await page.getByRole('button', { name: 'Stop', exact: true }).click();
  await expect(page.getByRole('radio', { name: 'Platform API', exact: true })).toBeEnabled();
  expect(ownedAuth.every((value) => value === undefined)).toBe(true);
  await page.getByRole('radio', { name: 'Platform API', exact: true }).check();
  await expect(page.getByLabel('Personal invitation code')).toBeVisible();
});

test('native runtime filters ElevenLabs from both platform and personal choices', async ({
  page,
}) => {
  await page.route('**/api/**', (route) =>
    route.fulfill({
      json: {
        session_ui: true,
        adapter: 'elevenlabs',
        available_adapters: ['elevenlabs', 'live', 'realtime'],
        voice_available: true,
      },
    }),
  );
  await page.goto('/');
  await page.evaluate(() => {
    (
      window as unknown as { Capacitor: { isNativePlatform: () => boolean } }
    ).Capacitor.isNativePlatform = () => true;
  });
  await page.getByRole('radio', { name: 'Your API keys', exact: true }).check();
  const provider = page.getByRole('combobox', { name: 'Voice provider', exact: false });
  await expect(provider).toHaveValue('live');
  await expect(provider.locator('option[value="elevenlabs"]')).toHaveCount(0);
  await page.getByRole('radio', { name: 'Platform API', exact: true }).check();
  await expect(provider).toHaveValue('live');
  await expect(provider.locator('option[value="elevenlabs"]')).toHaveCount(0);
});
