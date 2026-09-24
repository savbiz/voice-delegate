import { expect, test } from '@playwright/test';

test('documentation search shows source evidence without starting voice', async ({ page }) => {
  const requests: string[] = [];
  const queries: unknown[] = [];
  await page.route('**/api/**', async (route) => {
    requests.push(new URL(route.request().url()).pathname);
    queries.push(route.request().postDataJSON().query);
    await route.fulfill({
      json: {
        sources: [
          {
            id: 'source-1',
            title: 'Architecture',
            section: 'History',
            path: 'docs/architecture.md',
            text: 'Only sealed text segments are replayed.',
            digest: 'snapshot',
          },
        ],
      },
    });
  });
  await page.goto('/');
  await page.getByRole('tab', { name: 'Documentation', exact: true }).click();
  await page.getByLabel('Project question').fill('fallback history');
  await page.getByRole('button', { name: 'Search documentation' }).click();
  await expect(page.getByRole('status')).toContainText('1 source excerpts found');
  await page.getByText('[1] Architecture — History').click();
  await expect(page.getByText('Only sealed text segments are replayed.')).toBeVisible();
  await expect(page.getByText('docs/architecture.md')).toBeVisible();
  expect(queries).toEqual(['fallback history']);
  expect(requests).toEqual(['/api/reference/search']);
});

test('missing evidence is explicit', async ({ page }) => {
  await page.route('**/api/reference/search', (route) => route.fulfill({ json: { sources: [] } }));
  await page.goto('/');
  await page.getByRole('tab', { name: 'Documentation', exact: true }).click();
  await page.getByRole('button', { name: 'Search documentation' }).click();
  await expect(page.getByRole('status')).toContainText('No supporting documentation found');
});

test('invalid search results produce a friendly error', async ({ page }) => {
  await page.route('**/api/reference/search', (route) => route.fulfill({ json: { sources: {} } }));
  await page.goto('/');
  await page.getByRole('tab', { name: 'Documentation', exact: true }).click();
  await page.getByRole('button', { name: 'Search documentation' }).click();
  await expect(page.getByRole('status')).toContainText('returned invalid results');
});

test('timeout is friendly and changing the invitation resets an aborted search', async ({
  page,
}) => {
  await page.addInitScript(() => {
    const originalFetch = window.fetch;
    let calls = 0;
    window.fetch = (input, init) => {
      if (!String(input).endsWith('/api/reference/search')) return originalFetch(input, init);
      if (++calls === 1) return Promise.reject(new DOMException('Expired', 'TimeoutError'));
      return new Promise((_, reject) =>
        init?.signal?.addEventListener('abort', () =>
          reject(new DOMException('Aborted', 'AbortError')),
        ),
      );
    };
  });
  await page.goto('/');
  await page.getByRole('tab', { name: 'Documentation', exact: true }).click();
  await page.getByRole('button', { name: 'Search documentation' }).click();
  await expect(page.getByRole('status')).toContainText('took too long. Please try again');
  await page.getByRole('button', { name: 'Search documentation' }).click();
  await expect(page.getByRole('status')).toHaveText('Searching…');
  await page.getByLabel('Personal invitation code').fill('new-code');
  await expect(page.getByRole('status')).toContainText('Search cancelled');
  await expect(page.getByRole('button', { name: 'Search documentation' })).toBeEnabled();
});
