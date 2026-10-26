import { expect, test } from '@playwright/test';
import { installFakePeers } from './fixtures';

test('optional connection sounds follow confirmed connection and explicit stop', async ({
  page,
}) => {
  await page.addInitScript(installFakePeers);
  await page.addInitScript(() => {
    const notes: number[] = [];
    Object.defineProperty(window, '__connectionNotes', { value: notes });
    class CueContext {
      state = 'running';
      currentTime = 0;
      destination = {};
      async resume() {}
      async close() {}
      createGain() {
        return {
          gain: { setValueAtTime() {}, linearRampToValueAtTime() {} },
          connect() {},
          disconnect() {},
        };
      }
      createOscillator() {
        return {
          frequency: { setValueAtTime: (value: number) => notes.push(value) },
          connect() {},
          disconnect() {},
          start() {},
          stop() {},
        };
      }
    }
    Object.defineProperty(window, 'AudioContext', { value: CueContext });
  });
  await page.route('**/api/**', (route) => {
    const path = new URL(route.request().url()).pathname;
    return route.fulfill({
      json: path.endsWith('/config')
        ? { voice_available: true }
        : path.endsWith('/sessions')
          ? { id: 'cue-session', key: 'key' }
          : { sdp: 'v=0\r\n', finalized: true },
    });
  });
  await page.goto('/');
  await page.getByRole('tab', { name: 'Live voice', exact: true }).click();
  await page.getByText('Voice settings & recording', { exact: true }).click();
  const option = page.getByRole('checkbox', { name: 'Connection sounds', exact: true });
  await expect(option).toBeChecked();
  await page.getByRole('button', { name: 'Start conversation' }).click();
  await expect(page.getByRole('status')).toContainText('Connected');
  const notes = () =>
    page.evaluate(() => (window as unknown as { __connectionNotes: number[] }).__connectionNotes);
  await expect.poll(notes).toEqual([440, 660]);
  await page.getByRole('button', { name: 'Stop', exact: true }).click();
  await expect.poll(notes).toEqual([440, 660, 660, 440]);
  await expect(page.getByRole('button', { name: 'Start conversation' })).toBeEnabled();
  await option.uncheck();
  await page.getByRole('button', { name: 'Start conversation' }).click();
  await expect(page.getByRole('status')).toContainText('Connected');
  await page.getByRole('button', { name: 'Stop', exact: true }).click();
  await expect(page.getByRole('status')).toContainText('ended');
  expect(await notes()).toEqual([440, 660, 660, 440]);
});
