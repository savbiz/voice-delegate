/** Exercise peer replacement, one fallback, and cleanup with no paid provider. */
import { expect, test } from '@playwright/test';
import { installFakePeers, failLatestPeer } from './fixtures';

test('media failure replaces the peer once and closes the owned session', async ({ page }) => {
  await page.addInitScript(installFakePeers);
  const calls: string[] = [];
  const reconnects: { body: unknown; key: string | undefined }[] = [];
  await page.route('**/api/**', async (route) => {
    const path = new URL(route.request().url()).pathname;
    calls.push(path);
    if (path.endsWith('/config')) return route.fulfill({ json: { voice_available: true } });
    if (path.endsWith('/sessions')) return route.fulfill({ json: { id: 'owned', key: 'key' } });
    if (path.endsWith('/heartbeat'))
      return route.fulfill({
        json: { state: 'connected', delegation: 'idle', generation: 0, fallback_available: true },
      });
    if (path.endsWith('/reconnect')) {
      reconnects.push({
        body: route.request().postDataJSON(),
        key: route.request().headers()['x-session-key'],
      });
    }
    return route.fulfill({
      json: path.endsWith('/close') ? { finalized: true } : { sdp: 'v=0\r\n' },
    });
  });
  await page.goto('/');
  await page.getByRole('button', { name: 'Live voice', exact: true }).click();
  await page.getByRole('button', { name: 'Start conversation' }).click();
  await expect(page.getByRole('status')).toContainText('Connected.');
  await page.getByLabel('Personal invitation code').fill('updated-invitation');
  await expect(page.getByRole('status')).toContainText('Connected.');
  expect(calls.filter((path) => path.endsWith('/close'))).toHaveLength(0);
  const failPeer = () => page.evaluate(failLatestPeer);
  await failPeer();
  await expect.poll(() => calls.filter((p) => p.endsWith('/reconnect')).length).toBe(1);
  await expect(page.getByRole('status')).toContainText('Connected.');
  await failPeer();
  await expect.poll(() => calls.filter((p) => p.endsWith('/close')).length).toBe(1);
  expect(reconnects).toEqual([{ body: { sdp: 'v=0\r\n', generation: 0 }, key: 'key' }]);
  expect(calls.filter((p) => p.endsWith('/sessions')).length).toBe(1);
  expect(calls.filter((p) => p.endsWith('/reconnect')).length).toBe(1);
  await expect(page.getByRole('button', { name: 'Start conversation' })).toBeEnabled();
});

test('busy work and failed recovery explain manual actions without replay', async ({ page }) => {
  await page.addInitScript(installFakePeers);

  await page.clock.install();
  const calls: string[] = [];
  let worker = 'busy';
  await page.route('**/api/**', (route) => {
    const path = new URL(route.request().url()).pathname;
    calls.push(path);
    if (path.endsWith('/config')) return route.fulfill({ json: { voice_available: true } });
    if (path.endsWith('/sessions')) return route.fulfill({ json: { id: 'owned', key: 'key' } });
    if (path.endsWith('/heartbeat'))
      return route.fulfill({
        json: { state: 'connected', delegation: worker, generation: 0, fallback_available: true },
      });
    if (path.endsWith('/reconnect')) return route.fulfill({ status: 502, json: {} });
    return route.fulfill({
      json: path.endsWith('/close') ? { finalized: true } : { sdp: 'v=0\r\n' },
    });
  });
  await page.goto('/');
  await page.getByRole('button', { name: 'Live voice', exact: true }).click();
  await page.getByRole('button', { name: 'Start conversation' }).click();
  await expect(page.getByRole('status')).toContainText('Connected.');
  await page.clock.fastForward(10000);
  await expect(page.locator('#task-status')).toContainText('Your task was not started');
  await expect(page.getByRole('button', { name: 'Cancel task' })).toBeDisabled();
  worker = 'running';
  await page.clock.fastForward(10000);
  await expect(page.getByRole('button', { name: 'Cancel task' })).toBeEnabled();
  await page.getByRole('button', { name: 'Cancel task' }).click();
  await expect(page.locator('#task-status')).toContainText('cancellation requested');
  await expect(page.getByRole('button', { name: 'Cancel task' })).toBeDisabled();
  await page.evaluate(failLatestPeer);
  await expect(page.getByRole('button', { name: 'Start conversation' })).toBeEnabled();
  await expect(page.locator('#recovery-help')).toContainText('Previous tasks will not be replayed');
  expect(calls.filter((p) => p.endsWith('/sessions'))).toHaveLength(1);
  expect(calls.filter((p) => p.endsWith('/reconnect'))).toHaveLength(1);
  expect(calls.filter((p) => p.endsWith('/interrupt'))).toHaveLength(1);
});
