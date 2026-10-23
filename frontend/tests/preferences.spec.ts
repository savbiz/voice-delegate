import { expect, test } from '@playwright/test';
import { installFakePeers } from './fixtures';

test('invitation survives refresh and clearing removes it from tab storage', async ({ page }) => {
  await page.goto('/');
  await page.getByRole('tab', { name: 'Live voice', exact: true }).click();
  await page.getByLabel('Personal invitation code').fill('test-invitation');
  await page.reload();
  await page.getByRole('tab', { name: 'Live voice', exact: true }).click();
  await expect(page.getByLabel('Personal invitation code')).toHaveValue('test-invitation');
  await page.getByLabel('Personal invitation code').fill('');
  await page.reload();
  await page.getByRole('tab', { name: 'Live voice', exact: true }).click();
  await expect(page.getByLabel('Personal invitation code')).toHaveValue('');
});

test('mute and caption controls preserve a pending ICE connection', async ({ page }) => {
  await page.addInitScript(installFakePeers);
  await page.addInitScript(() => {
    RTCPeerConnection.prototype.setLocalDescription = async function () {
      Object.defineProperty(this, 'iceGatheringState', { value: 'gathering', writable: true });
      setTimeout(() => {
        Object.defineProperty(this, 'iceGatheringState', { value: 'complete', writable: true });
        this.dispatchEvent(new Event('icegatheringstatechange'));
      }, 2000);
    };
  });
  await page.clock.install();
  const paths: string[] = [];
  await page.route('**/api/**', (route) => {
    const path = new URL(route.request().url()).pathname;
    paths.push(path);
    return route.fulfill({
      json: path.endsWith('/config')
        ? { voice_available: true }
        : path.endsWith('/sessions')
          ? { id: 'controls', key: 'key' }
          : { sdp: 'v=0\r\n', finalized: true },
    });
  });
  await page.goto('/');
  await page.getByRole('tab', { name: 'Live voice', exact: true }).click();
  await page.getByRole('button', { name: 'Mute assistant', exact: true }).click();
  await page.getByRole('button', { name: 'Large captions' }).click();
  await page.getByRole('button', { name: 'Start conversation' }).click();
  await expect(page.getByRole('button', { name: 'Stop', exact: true })).toBeEnabled();
  await page.getByRole('button', { name: 'Unmute assistant', exact: true }).click();
  await page.getByRole('button', { name: 'Large captions' }).click();
  await page.clock.runFor(2100);
  await expect(page.locator('#status')).toContainText('Connected');
  expect(paths.filter((path) => path.endsWith('/sessions'))).toHaveLength(1);
  expect(paths.some((path) => path.endsWith('/close'))).toBe(false);
  await page.getByRole('button', { name: 'Stop', exact: true }).click();
});
