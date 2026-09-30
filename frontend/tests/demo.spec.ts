/** Exercise free playback, cancellation, and the live-mode boundary without a key. */
import { expect, test } from '@playwright/test';
import vercel from '../vercel.json' with { type: 'json' };
test('demo completes without backend requests', async ({ page }) => {
  const api: string[] = [];
  page.on('request', (request) => {
    if (request.url().includes('/api/')) api.push(request.url());
  });
  await page.clock.install();
  await page.goto('/');
  await expect(page.locator('header .badge')).toHaveText('OPEN REFERENCE · 0.1.0');
  await page.getByRole('button', { name: 'Start demo', exact: true }).click();
  await page.clock.runFor(4000);
  await expect(page.getByText('310 ms · simulated')).toBeVisible();
  expect(api).toEqual([]);
});
test('stopping cancels further playback', async ({ page }) => {
  await page.clock.install();
  await page.goto('/');
  await page.getByRole('button', { name: 'Start demo', exact: true }).click();
  await page.clock.fastForward(1000);
  await page.getByRole('button', { name: 'Stop demo', exact: true }).click();
  await page.clock.fastForward(5000);
  await expect(page.getByText('240 ms · simulated')).not.toBeVisible();
  await page.getByRole('tab', { name: 'Live voice', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Start conversation' })).toBeVisible();
});

test('live mode without a server key explains how to proceed', async ({ page }) => {
  await page.route('**/api/config', (route) => route.fulfill({ json: { voice_available: false } }));
  await page.goto('/');
  await page.getByRole('tab', { name: 'Live voice', exact: true }).click();
  await page.getByRole('button', { name: 'Start conversation' }).click();
  await expect(page.getByRole('status')).toContainText('Set OPENAI_API_KEY on the backend');
  await expect(page.getByRole('button', { name: 'Start conversation' })).toBeEnabled();
});

test('voice preferences and accessible playback controls work before connecting', async ({
  page,
}) => {
  await page.goto('/');
  await page.getByRole('tab', { name: 'Live voice', exact: true }).click();
  await page.getByLabel('Response language').selectOption('it');
  await page.getByLabel('Conversation style').selectOption('translate');
  await page.getByRole('button', { name: 'Mute assistant', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Unmute assistant' })).toHaveAttribute(
    'aria-pressed',
    'true',
  );
  await page.getByRole('button', { name: 'Large captions' }).click();
  await expect(page.getByRole('button', { name: 'Large captions' })).toHaveAttribute(
    'aria-pressed',
    'true',
  );
  await page.getByLabel('Response language').focus();
  await expect(page.getByLabel('Response language')).toBeFocused();
});

test('mode tabs support keyboard selection and expose their panel', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('tab', { name: 'Free demo' }).focus();
  await page.keyboard.press('ArrowRight');
  await expect(page.getByRole('tab', { name: 'Live voice' })).toBeFocused();
  await expect(page.getByRole('tab', { name: 'Live voice' })).toHaveAttribute(
    'aria-selected',
    'true',
  );
  await expect(page.getByRole('tabpanel')).toHaveAttribute('aria-labelledby', 'tab-live');
  await expect(page.locator('#recap')).toHaveAttribute('aria-live', 'off');
});

test('demo head and favicon load without console errors under production CSP', async ({ page }) => {
  const errors: string[] = [];
  page.on('console', (message) => {
    if (message.type() === 'error') errors.push(message.text());
  });
  page.on('pageerror', (error) => errors.push(error.message));
  const headers = Object.fromEntries(
    vercel.headers.flatMap((route) => route.headers.map(({ key, value }) => [key, value])),
  );
  await page.route('**/', async (route) => {
    const response = await route.fetch();
    await route.fulfill({ response, headers: { ...response.headers(), ...headers } });
  });
  await page.goto('/');
  await expect(page.getByRole('button', { name: 'Start demo', exact: true })).toBeVisible();
  await expect(page.locator('meta[name="description"]')).toHaveAttribute(
    'content',
    'A reference architecture for real-time voice agents that stay responsive while doing real work.',
  );
  await expect(page.locator('meta[name="theme-color"]')).toHaveAttribute('content', '#0b1120');
  await expect(page.locator('link[rel="icon"]')).toHaveAttribute('href', '/favicon.svg');
  const faviconLoaded = await page.evaluate(async () => {
    const icon = document.querySelector<HTMLLinkElement>('link[rel="icon"]');
    if (!icon) return false;
    const image = new Image();
    image.src = icon.href;
    await image.decode();
    return image.naturalWidth > 0;
  });
  expect(faviconLoaded).toBe(true);
  expect(errors).toEqual([]);
});
