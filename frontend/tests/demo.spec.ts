/** Exercise free playback, cancellation, and the live-mode boundary without a key. */
import { expect, test } from '@playwright/test';
test('demo completes without backend requests', async ({ page }) => {
  const api: string[] = [];
  page.on('request', request => { if (request.url().includes('/api/')) api.push(request.url()); });
  await page.goto('/');
  await page.getByRole('button', { name: 'Start demo', exact: true }).click();
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
  await page.getByRole('button', { name: 'Live voice', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Start conversation' })).toBeVisible();
});

test('live mode without a server key explains how to proceed', async ({ page }) => {
  await page.route('**/api/config', route => route.fulfill({ json: { voice_available: false } }));
  await page.goto('/');
  await page.getByRole('button', { name: 'Live voice', exact: true }).click();
  await page.getByRole('button', { name: 'Start conversation' }).click();
  await expect(page.getByRole('status')).toContainText('Set OPENAI_API_KEY on the backend');
  await expect(page.getByRole('button', { name: 'Start conversation' })).toBeEnabled();
});
