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

for (const enabled of [false, true]) {
  test(`production build requires server permission and consent for debugging (${enabled})`, async ({
    page,
  }) => {
    await page.addInitScript(installFakePeers);
    await page.clock.install();
    const creates: unknown[] = [];
    await page.route('**/api/**', (route) => {
      const path = new URL(route.request().url()).pathname;
      if (path.endsWith('/config'))
        return route.fulfill({
          json: { voice_available: true, debug_recording_available: enabled },
        });
      if (path.endsWith('/sessions')) {
        creates.push(route.request().postDataJSON());
        return route.fulfill({ json: { id: 'debug-consent', key: 'key' } });
      }
      return route.fulfill({ json: { sdp: 'v=0\r\n', finalized: true, recording: true } });
    });
    await page.goto('/');
    await page.getByRole('tab', { name: 'Live voice', exact: true }).click();
    const checkbox = page.getByLabel(/Record this session for server debugging/);
    await expect(checkbox).not.toBeChecked();
    await checkbox.check();
    await page.getByRole('button', { name: 'Start conversation' }).click();
    if (enabled) {
      await expect(page.locator('#status')).toContainText('Connected');
      expect(creates).toEqual([{ language: 'auto', mode: 'conversation', debug_recording: true }]);
      await page.getByRole('button', { name: 'Stop', exact: true }).click();
    } else {
      await expect(page.locator('#status')).toContainText('Server debugging is disabled');
      expect(creates).toEqual([]);
    }
    await expect(checkbox).not.toBeChecked();
  });
}
