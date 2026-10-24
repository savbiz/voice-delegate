import { expect, test } from '@playwright/test';
import { installFakePeers } from './fixtures';

test('audio telemetry uses playback energy and survives upload failure', async ({ page }) => {
  await page.clock.install();
  await page.addInitScript(installFakePeers);
  await page.addInitScript(() => {
    const NativeContext = window.AudioContext;
    const track = new NativeContext().createMediaStreamDestination().stream.getAudioTracks()[0]!;
    Object.defineProperty(window, '__audioTrack', { value: track });
    let analyserId = 0;
    class FakeContext {
      state = 'running';
      createMediaStreamSource() {
        return { connect() {}, disconnect() {} };
      }
      createAnalyser() {
        const remote = analyserId++ % 2 === 1;
        return {
          fftSize: 1024,
          disconnect() {},
          getFloatTimeDomainData(values: Float32Array) {
            values.fill(remote ? 0.1 : 0);
          },
        };
      }
      async resume() {}
      async close() {
        this.state = 'closed';
      }
    }
    Object.defineProperty(window, 'AudioContext', { value: FakeContext });
    Object.defineProperty(HTMLMediaElement.prototype, 'paused', { get: () => false });
    HTMLMediaElement.prototype.play = async () => {};
  });
  const measurements: unknown[] = [];
  await page.route('**/api/**', (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith('/audio-timing')) {
      measurements.push(route.request().postDataJSON());
      return route.fulfill({ status: 503, json: {} });
    }
    return route.fulfill({
      json: path.endsWith('/config')
        ? { voice_available: true, audio_timing_available: true }
        : path.endsWith('/sessions')
          ? { id: 'audio', key: 'key' }
          : { sdp: 'v=0\r\n', finalized: true },
    });
  });
  await page.goto('/');
  await page.getByRole('tab', { name: 'Live voice', exact: true }).click();
  await page.getByRole('button', { name: 'Start conversation' }).click();
  await expect(page.locator('#status')).toContainText('Connected');
  await page.evaluate(() => {
    const globals = window as unknown as { __peers: EventTarget[]; __audioTrack: MediaStreamTrack };
    const event = new Event('track');
    Object.defineProperty(event, 'track', { value: globals.__audioTrack });
    globals.__peers.at(-1)!.dispatchEvent(event);
  });
  await page.clock.runFor(100);
  await page.getByText('Connection timings', { exact: true }).click();
  await expect(page.getByLabel('Audio playback measurements')).toContainText(
    'Offer to first audio',
  );
  await expect(page.getByText('Audio measured locally; metric upload failed.')).toBeVisible();
  expect(measurements).toHaveLength(1);
  expect(measurements[0]).toMatchObject({ kind: 'setup', generation: 0 });
  await expect(page.locator('#status')).toContainText('Connected');
  await page.getByRole('button', { name: 'Stop', exact: true }).click();
  await page.clock.runFor(100);
  expect(measurements).toHaveLength(1);
});
