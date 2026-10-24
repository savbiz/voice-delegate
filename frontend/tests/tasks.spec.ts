import { expect, test } from '@playwright/test';
import { installFakePeers } from './fixtures';

test('two tasks display independently and cancellation targets the selected id', async ({
  page,
}) => {
  await page.addInitScript(installFakePeers);
  await page.clock.install();
  const cancellations: unknown[] = [];
  await page.route('**/api/**', (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith('/config'))
      return route.fulfill({ json: { voice_available: true, intent_cancellation: true } });
    if (path.endsWith('/sessions')) return route.fulfill({ json: { id: 'owned', key: 'key' } });
    if (path.endsWith('/heartbeat'))
      return route.fulfill({
        json: {
          state: 'connected',
          delegation: 'running',
          tasks: [
            {
              id: 'first',
              goal: 'Calculate 2+2',
              status: cancellations.length ? 'cancelled' : 'running',
              elapsed_seconds: 2,
            },
            { id: 'second', goal: 'Find documentation', status: 'pending', elapsed_seconds: 1 },
          ],
        },
      });
    if (path.endsWith('/interrupt')) cancellations.push(route.request().postDataJSON());
    return route.fulfill({ json: { sdp: 'v=0\r\n', finalized: true } });
  });
  await page.goto('/');
  await page.getByRole('tab', { name: 'Live voice', exact: true }).click();
  await page.getByRole('button', { name: 'Start conversation' }).click();
  await expect(page.getByRole('status')).toContainText('Connected');
  await page.clock.runFor(2100);
  await expect(page.getByRole('list', { name: 'Delegated tasks' })).toContainText(
    'Find documentation',
  );
  await page.getByRole('button', { name: 'Cancel first', exact: true }).click();
  await expect.poll(() => cancellations).toEqual([{ task_id: 'first' }]);
  await page.clock.runFor(2100);
  await expect(page.getByRole('button', { name: 'Cancel first', exact: true })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Cancel second', exact: true })).toBeEnabled();
  await page.getByRole('button', { name: 'Stop', exact: true }).click();
});
