import { expect, test } from '@playwright/test';
import { installFakePeers } from './fixtures';

for (const width of [390, 1100]) {
  test(`conversation shows ordered chat bubbles at ${width}px`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: 1000 });
    await page.addInitScript(installFakePeers);
    await page.route('**/api/**', (route) => {
      const path = new URL(route.request().url()).pathname;
      return route.fulfill({
        json: path.endsWith('/config')
          ? { voice_available: true }
          : path.endsWith('/sessions')
            ? { id: 'chat', key: 'key' }
            : { sdp: 'v=0\r\n', finalized: true },
      });
    });
    await page.goto('/');
    await page.getByRole('tab', { name: 'Live voice', exact: true }).click();
    await expect(page.locator('.settings-panel')).not.toHaveAttribute('open');
    await expect(page.getByRole('region', { name: 'Worker sources' })).toHaveCount(0);
    await expect(page.locator('#audio')).toBeHidden();
    await page.getByRole('button', { name: 'Start conversation' }).click();
    await expect(page.locator('#status')).toContainText('Connected');
    await page.evaluate(() => {
      const peer = (window as unknown as { __peers: { channel: EventTarget }[] }).__peers.at(-1)!;
      for (const [type, delta, start_ms, end_ms] of [
        ['session.input_transcript.delta', 'Can you calculate ', 0, 200],
        ['session.input_transcript.delta', 'ten plus ten?', 200, 400],
        ['session.output_transcript.delta', 'Twenty.', 1000, 1500],
        ['session.input_transcript.delta', 'Thank you.', 3000, 3500],
      ])
        peer.channel.dispatchEvent(
          new MessageEvent('message', { data: JSON.stringify({ type, delta, start_ms, end_ms }) }),
        );
    });
    const messages = page.locator('.chat-message');
    await expect(messages).toHaveCount(3);
    await expect(messages.nth(0)).toContainText('Can you calculate ten plus ten?');
    await expect(messages.nth(1)).toContainText('Twenty.');
    await expect(messages.nth(2)).toContainText('Thank you.');
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
      true,
    );
    await page.screenshot({ path: testInfo.outputPath('conversation.png'), fullPage: true });
    await page.getByRole('button', { name: 'Stop', exact: true }).click();
    await expect(messages).toHaveCount(3);
    await page.getByRole('button', { name: 'Start conversation' }).click();
    await expect(page.locator('.chat-empty')).toBeVisible();
  });
}
