/** Feedback never sends conversation content; ambiguous retries keep their identity. */
import { expect, test } from '@playwright/test';

test('feedback retries the same bounded report and prevents duplicate clicks', async ({ page }) => {
  const bodies: unknown[] = [];
  const authorization: (string | undefined)[] = [];
  await page.route('**/api/feedback', (route) => {
    const body = route.request().postDataJSON();
    bodies.push(body);
    authorization.push(route.request().headers().authorization);
    return route.fulfill(
      bodies.length === 1
        ? { status: 503, json: {} }
        : { status: 201, json: { diagnostic_id: body.diagnostic_id } },
    );
  });
  await page.goto('/');
  await page.getByRole('tab', { name: 'Live voice', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Send report' })).toBeDisabled();
  await page.getByLabel('Personal invitation code').fill('invitation');
  await page.getByLabel('Problem category').selectOption('audio');
  await page.getByRole('button', { name: 'Send report' }).click();
  await expect(page.locator('#feedback-status')).toContainText('Report not confirmed');
  await expect(page.getByLabel('Problem category')).toBeDisabled();
  await page.getByRole('button', { name: 'Send report' }).click();
  await expect(page.locator('#feedback-status')).toContainText('Report received. Diagnostic ID:');
  await expect(page.getByRole('button', { name: 'Send report' })).toBeDisabled();
  expect(authorization).toEqual(['Bearer invitation', 'Bearer invitation']);
  expect(bodies).toHaveLength(2);
  expect(bodies[0]).toEqual(bodies[1]);
  expect(bodies[0]).toEqual({
    diagnostic_id: expect.any(String),
    category: 'audio',
    state: 'ready',
  });
});
