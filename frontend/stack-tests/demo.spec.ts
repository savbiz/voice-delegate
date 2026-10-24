import { expect, test } from '@playwright/test';

test('offline stack displays actual worker result and closes ownership', async ({ page }) => {
  const paths: string[] = [];
  await page.route('**/api/**', (route) => {
    const path = new URL(route.request().url()).pathname;
    paths.push(path);
    return route.fulfill({
      json: path.endsWith('/sessions')
        ? { id: 'demo', key: 'owner' }
        : path.endsWith('/heartbeat')
          ? { delegation: 'completed', recap: { latest_reply: '4' } }
          : { sdp: 'v=0\r\n', finalized: true },
    });
  });
  await page.goto('/');
  await expect(page.getByText(/Fake voice provider, real backend/)).toBeVisible();
  await page.getByRole('button', { name: 'Run offline worker' }).click();
  await expect(page.getByRole('status')).toHaveText('Worker result: 4');
  expect(paths).toEqual([
    '/api/sessions',
    '/api/sessions/demo/offer',
    '/api/sessions/demo/heartbeat',
    '/api/sessions/demo/close',
  ]);
});

test('unavailable stack offers the existing static demo without more requests', async ({
  page,
}) => {
  let requests = 0;
  await page.route('**/api/**', (route) => {
    requests += 1;
    return route.fulfill({ status: 503, json: {} });
  });
  await page.goto('/');
  await page.getByRole('button', { name: 'Run offline worker' }).click();
  await expect(page.getByRole('status')).toContainText('Offline stack unavailable');
  await page.getByRole('button', { name: 'Use static demo instead' }).click();
  await expect(page.getByRole('button', { name: 'Start demo', exact: true })).toBeVisible();
  expect(requests).toBe(1);
});
