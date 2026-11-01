import { expect, test } from '@playwright/test';
import { installFakePeers } from './fixtures';

for (const platform of ['ios', 'android']) {
  test(`${platform} preview keeps the demo offline and blocks voice by default`, async ({
    page,
  }) => {
    const requests: string[] = [];
    await page.addInitScript((name) => {
      Object.defineProperty(window, 'CapacitorCustomPlatform', { value: { name } });
    }, platform);
    page.on('request', (request) => {
      if (request.url().includes('/api/')) requests.push(request.url());
    });
    await page.clock.install();
    await page.goto('/');
    await expect(page.locator('html')).toHaveClass('native-app');
    await page.getByRole('button', { name: 'Start demo', exact: true }).click();
    await page.clock.runFor(4000);
    await expect(page.getByText('310 ms · simulated')).toBeVisible();
    await page.getByRole('tab', { name: 'Live voice', exact: true }).click();
    await page.getByRole('button', { name: 'Start conversation', exact: true }).click();
    await expect(page.getByRole('status')).toHaveText('Native live voice is disabled.');
    expect(requests).toEqual([]);
  });
}

test('native background transition closes the owned session and releases its peer', async ({
  page,
}) => {
  const closed: string[] = [];
  await page.addInitScript(installFakePeers);
  await page.route('**/api/**', (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith('/close')) closed.push(path);
    return route.fulfill({
      json: path.endsWith('/config')
        ? { voice_available: true }
        : path.endsWith('/sessions')
          ? { id: 'native-session', key: 'key' }
          : { sdp: 'v=0\r\n', finalized: true },
    });
  });
  await page.goto('/');
  await page.getByRole('tab', { name: 'Live voice', exact: true }).click();
  await page.getByRole('button', { name: 'Start conversation', exact: true }).click();
  await expect(page.getByRole('status')).toContainText('Connected');
  await page.evaluate(() => {
    const bridge = (window as unknown as { Capacitor: { isNativePlatform: () => boolean } })
      .Capacitor;
    bridge.isNativePlatform = () => true;
    Object.defineProperty(document, 'visibilityState', { configurable: true, value: 'hidden' });
    document.dispatchEvent(new Event('visibilitychange'));
  });
  await expect(page.getByRole('status')).toHaveText('Conversation ended.');
  await expect.poll(() => closed).toEqual(['/api/sessions/native-session/close']);
  expect(
    await page.evaluate(
      () =>
        (window as unknown as { __peers: { connectionState: string }[] }).__peers.at(-1)
          ?.connectionState,
    ),
  ).toBe('closed');
});
