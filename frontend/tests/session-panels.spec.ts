import { expect, test } from '@playwright/test';
import { installFakePeers } from './fixtures';

test('mobile session chooses a server-enabled provider and retains final costs', async ({
  page,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.addInitScript(installFakePeers);
  await page.clock.install();
  const selected: unknown[] = [];
  const cost = {
    version: 'offline-fixture',
    price_date: '2026-11-02',
    estimated_usd: 0.012,
    components: { voice: 0.01, worker: 0.002 },
    usage: { worker_calls: 1, decision_calls: 0, web_calls: 0, uncertain: false },
    voice_seconds: 12,
    partial: false,
    unpriced: [],
    final: false,
  };
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
    if (path.endsWith('/sessions')) {
      selected.push(route.request().postDataJSON());
      return route.fulfill({ json: { id: 'owned', key: 'fixture' } });
    }
    if (path.endsWith('/heartbeat'))
      return route.fulfill({
        json: { state: 'connected', delegation: 'idle', tasks: [], costs: cost },
      });
    if (path.endsWith('/close'))
      return route.fulfill({ json: { finalized: true, costs: { ...cost, final: true } } });
    return route.fulfill({ json: { sdp: 'v=0\r\n' } });
  });
  await page.goto('/');
  await page.getByRole('link', { name: 'Live voice', exact: true }).click();
  const provider = page.getByRole('combobox', { name: 'Voice provider', exact: false });
  await expect(provider).toBeVisible();
  await provider.selectOption('elevenlabs');
  await page.getByText('Voice settings & recording', { exact: true }).click();
  await expect(page.getByLabel('Response language')).toBeDisabled();
  await expect(page.getByLabel('Record audio locally.', { exact: false })).toBeDisabled();
  await provider.selectOption('azure');
  await expect(page.getByLabel('Response language')).toBeEnabled();
  await page.getByRole('button', { name: 'Start conversation', exact: true }).click();
  await expect(page.locator('#status')).toContainText('Connected');
  await expect(provider).toBeDisabled();
  expect(selected).toEqual([expect.objectContaining({ adapter: 'azure' })]);
  await page.clock.runFor(2100);
  const panel = page.getByRole('region', { name: 'Session cost estimate' });
  await expect(panel).toContainText('$0.012000');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  );
  await page.screenshot({ path: test.info().outputPath('mobile-session.png'), fullPage: true });
  await page.getByRole('button', { name: 'Stop', exact: true }).click();
  await expect(panel).toContainText('Finished');
  await expect(provider).toBeEnabled();
  await expect(page.getByLabel('Observed audio activity')).toHaveCount(0);
});

test('leaving voice for a secondary tool closes the session and releases media', async ({
  page,
}) => {
  await page.addInitScript(installFakePeers);
  const closed: string[] = [];
  await page.route('**/api/**', (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith('/close')) closed.push(path);
    return route.fulfill({
      json: path.endsWith('/config')
        ? { voice_available: true }
        : path.endsWith('/sessions')
          ? { id: 'owned', key: 'fixture' }
          : path.endsWith('/close')
            ? { finalized: true }
            : { sdp: 'v=0\r\n' },
    });
  });
  await page.goto('/');
  await page.getByRole('button', { name: 'Start conversation', exact: true }).click();
  await expect(page.locator('#status')).toContainText('Connected');
  await page.getByText('Tools & examples', { exact: true }).click();
  await page.getByRole('link', { name: 'Offline example', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Start demo', exact: true })).toBeVisible();
  await expect.poll(() => closed).toEqual(['/api/sessions/owned/close']);
  expect(
    await page.evaluate(
      () =>
        (window as unknown as { __peers: { connectionState: string }[] }).__peers.at(-1)
          ?.connectionState,
    ),
  ).toBe('closed');
});

test('both API sources display providers and explain unconfigured choices', async ({ page }) => {
  await page.route('**/api/**', (route) =>
    route.fulfill({
      json: {
        session_ui: true,
        adapter: 'openai',
        available_adapters: route.request().url().includes('/personal/')
          ? ['openai', 'azure']
          : ['openai'],
        voice_available: true,
      },
    }),
  );
  await page.goto('/');
  const provider = page.getByRole('combobox', { name: 'Voice provider', exact: false });
  await expect(provider.locator('option')).toHaveCount(3);
  await expect(provider.locator('option[value="azure"]')).toHaveAttribute('disabled', '');
  await expect(provider.locator('option[value="elevenlabs"]')).toContainText('not configured');
  await page.getByRole('radio', { name: 'Your API keys', exact: true }).check();
  await expect(provider.locator('option')).toHaveCount(3);
  await expect(provider.locator('option[value="azure"]')).not.toHaveAttribute('disabled');
  await provider.selectOption('azure');
  await expect(page.getByLabel('Azure API key', { exact: true })).toBeVisible();
  await expect(provider.locator('option[value="elevenlabs"]')).toContainText(
    'unavailable on this server',
  );
  await expect(provider.locator('option[value="elevenlabs"]')).toHaveAttribute('disabled', '');
  await expect(
    page.getByText('ElevenLabs is unavailable until the server operator', { exact: false }),
  ).toBeVisible();
  await page.getByRole('radio', { name: 'Platform API', exact: true }).check();
  await expect(provider).toHaveValue('openai');
  await expect(provider.locator('option[value="azure"]')).toHaveAttribute('disabled', '');
});

test('a server with no configured provider explains it and blocks Start', async ({ page }) => {
  await page.route('**/api/**', (route) =>
    route.fulfill({
      json: {
        session_ui: true,
        adapter: 'openai',
        available_adapters: ['openai'],
        voice_available: false,
      },
    }),
  );
  await page.goto('/');
  await expect(page.getByRole('alert')).toContainText('No voice provider is configured');
  await expect(page.locator('#status')).toContainText('Voice is unavailable');
  await expect(
    page.getByRole('button', { name: 'Start conversation', exact: true }),
  ).toBeDisabled();
  await page.getByRole('radio', { name: 'Your API keys', exact: true }).check();
});
