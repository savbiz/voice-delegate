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
          adapter: 'openai',
          available_adapters: ['openai', 'azure', 'elevenlabs'],
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
        adapter: 'openai',
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
        available_adapters: ['elevenlabs', 'openai', 'azure'],
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
  await expect(provider).toHaveValue('openai');
  await expect(provider.locator('option[value="elevenlabs"]')).toHaveCount(0);
  await page.getByRole('radio', { name: 'Platform API', exact: true }).check();
  await expect(provider).toHaveValue('openai');
  await expect(provider.locator('option[value="elevenlabs"]')).toHaveCount(0);
});

test('Azure recovery requires per-session choice and personal Azure fields', async ({ page }) => {
  await page.addInitScript(installFakePeers);
  let submitted: Record<string, unknown> | undefined;
  await page.route('**/api/**', (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith('/config'))
      return route.fulfill({
        json: {
          session_ui: true,
          adapter: 'openai',
          available_adapters: ['openai', 'azure'],
          voice_available: true,
          azure_recovery_available: true,
        },
      });
    if (path === '/api/personal/sessions') {
      submitted = route.request().postDataJSON();
      return route.fulfill({ json: { id: 'owned', key: 'key' } });
    }
    return route.fulfill({
      json: path.endsWith('/close') ? { finalized: true } : { sdp: 'answer' },
    });
  });
  await page.goto('/');
  await page.getByRole('radio', { name: 'Your API keys', exact: true }).check();
  const recovery = page.getByLabel('Allow one Azure recovery', { exact: false });
  await expect(recovery).not.toBeChecked();
  await expect(page.getByLabel('Azure API key', { exact: true })).toHaveCount(0);
  await recovery.check();
  await page.getByLabel('Azure API key', { exact: true }).fill('discarded');
  await recovery.uncheck();
  await recovery.check();
  await expect(page.getByLabel('Azure API key', { exact: true })).toHaveValue('');
  await page.getByLabel('OpenAI API key (voice and worker)', { exact: true }).fill('own-openai');
  await page.getByLabel('Azure API key', { exact: true }).fill('own-azure');
  await page.getByLabel('Azure resource HTTPS origin').fill('https://own.openai.azure.com');
  await page.getByLabel('Azure deployment', { exact: false }).fill('own-live');
  await page.getByRole('button', { name: 'Start conversation', exact: true }).click();
  await expect(page.locator('#status')).toContainText('Connected');
  expect(submitted).toMatchObject({
    azure_recovery: true,
    keys: {
      openai_key: 'own-openai',
      azure_key: 'own-azure',
      azure_endpoint: 'https://own.openai.azure.com',
      azure_deployment: 'own-live',
    },
  });
  await expect(recovery).toBeDisabled();
  await expect(page.getByLabel('Azure API key', { exact: true })).toHaveValue('');
  await page.getByRole('button', { name: 'Stop', exact: true }).click();
  await expect(recovery).not.toBeChecked();
  await expect(page.getByLabel('Azure API key', { exact: true })).toHaveCount(0);
});
