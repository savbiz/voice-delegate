import { expect, test } from '@playwright/test';
import { installFakePeers } from './fixtures';

test('audio capture is explicit and produces a local download without uploading audio', async ({
  page,
}) => {
  const paths: string[] = [];
  const creates: unknown[] = [];
  await page.addInitScript(installFakePeers);
  await page.addInitScript(() => {
    const start = MediaRecorder.prototype.start;
    MediaRecorder.prototype.start = function (timeslice?: number) {
      this.addEventListener('dataavailable', (event) => {
        if (event.data.size) document.documentElement.dataset.audioCaptured = 'true';
      });
      start.call(this, timeslice);
    };
    Object.defineProperty(navigator.mediaDevices, 'getUserMedia', {
      value: async () => {
        const context = new AudioContext();
        const destination = context.createMediaStreamDestination();
        const tone = context.createOscillator();
        tone.connect(destination);
        tone.start();
        return destination.stream;
      },
      configurable: true,
    });
  });
  await page.route('**/api/**', (route) => {
    const path = new URL(route.request().url()).pathname;
    paths.push(path);
    if (path.endsWith('/config')) return route.fulfill({ json: { voice_available: true } });
    if (path.endsWith('/sessions')) {
      creates.push(route.request().postDataJSON());
      return route.fulfill({ json: { id: 'recorded', key: 'test-key' } });
    }
    return route.fulfill({ json: { sdp: 'v=0\r\n', finalized: true } });
  });
  await page.goto('/');
  await page.getByRole('tab', { name: 'Live voice', exact: true }).click();
  const checkbox = page.getByLabel(/Record audio locally/);
  await expect(checkbox).not.toBeChecked();
  await checkbox.check();
  await page.getByRole('button', { name: 'Start conversation' }).click();
  await expect(page.locator('#status')).toContainText('Connected');
  await expect(checkbox).toBeDisabled();
  await expect(page.locator('html')).toHaveAttribute('data-audio-captured', 'true', {
    timeout: 10000,
  });
  await page.getByRole('button', { name: 'Stop', exact: true }).click();
  const link = page.getByRole('link', { name: 'Download session audio' });
  await expect(link).toHaveAttribute('href', /^blob:/);
  await expect(checkbox).not.toBeChecked();
  const duration = await page.evaluate(async () => {
    const link = document.querySelector('a[download]');
    if (!(link instanceof HTMLAnchorElement)) throw new Error('Missing recording');
    const response = await fetch(link.href);
    const context = new AudioContext();
    try {
      return (await context.decodeAudioData(await response.arrayBuffer())).duration;
    } finally {
      await context.close();
    }
  });
  expect(duration).toBeGreaterThan(0);
  const [download] = await Promise.all([page.waitForEvent('download'), link.click()]);
  expect(download.suggestedFilename()).toMatch(/^voice-session-\d+\.(webm|ogg|m4a)$/);
  expect(await download.failure()).toBeNull();
  expect(creates).toEqual([{ language: 'auto', mode: 'conversation', debug_recording: false }]);
  expect(
    paths.every((path) =>
      [
        '/api/config',
        '/api/sessions',
        '/api/sessions/recorded/offer',
        '/api/sessions/recorded/close',
      ].includes(path),
    ),
  ).toBe(true);
});
