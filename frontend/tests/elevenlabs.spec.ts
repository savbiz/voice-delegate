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
  await page.getByRole('tab', { name: 'Live voice', exact: true }).click();
  await page.getByText('Voice settings & recording', { exact: true }).click();
  await page.getByLabel(/Record audio locally/).check();
  await page.getByRole('button', { name: 'Start conversation' }).click();
  await expect(page.locator('#status')).toContainText('Mixed audio recording is not available');
  expect(requests.every((path) => path.endsWith('/config'))).toBe(true);
});
