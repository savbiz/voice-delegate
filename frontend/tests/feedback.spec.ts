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
  await page.getByRole('link', { name: 'Live voice', exact: true }).click();
  await page.getByText('Report a problem', { exact: true }).click();
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

test('feedback sends an optional note and refuses one that looks like a key', async ({ page }) => {
  const bodies: unknown[] = [];
  await page.route('**/api/feedback', (route) => {
    const body = route.request().postDataJSON();
    bodies.push(body);
    return route.fulfill({ status: 201, json: { diagnostic_id: body.diagnostic_id } });
  });
  await page.goto('/');
  await page.getByRole('link', { name: 'Live voice', exact: true }).click();
  await page.getByText('Report a problem', { exact: true }).click();
  await page.getByLabel('Personal invitation code').fill('invitation');
  const note = page.getByLabel('What happened? (optional)');
  const send = page.getByRole('button', { name: 'Send report' });
  await note.fill('my key sk-' + 'a'.repeat(40));
  await expect(page.getByRole('alert')).toContainText('looks like it contains a key');
  await expect(send).toBeDisabled();
  await note.fill('  It said Juve won,\n but they lost  ');
  await expect(send).toBeEnabled();
  await send.click();
  await expect(page.locator('#feedback-status')).toContainText('Report received');
  await expect(note).toBeDisabled();
  expect(bodies).toEqual([
    {
      diagnostic_id: expect.any(String),
      category: 'wrong_answer',
      state: 'ready',
      note: 'It said Juve won, but they lost',
    },
  ]);
});
