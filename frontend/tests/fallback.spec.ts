/** Exercise peer replacement, one fallback, and cleanup with no paid provider. */
import { expect, test } from '@playwright/test';

test('media failure replaces the peer once and closes the owned session', async ({ page }) => {
  await page.addInitScript(() => {
    const peers: FakePeer[] = [];
    class FakeChannel extends EventTarget {
      close() { this.dispatchEvent(new Event('close')); }
    }
    class FakePeer extends EventTarget {
      iceGatheringState = 'complete';
      connectionState = 'new';
      localDescription = { type: 'offer', sdp: 'v=0\r\n' };
      channel = new FakeChannel();
      constructor() { super(); peers.push(this); }
      addTrack() {}
      createDataChannel() { return this.channel; }
      async createOffer() { return this.localDescription; }
      async setLocalDescription() {}
      async setRemoteDescription() {
        this.connectionState = 'connected';
        this.channel.dispatchEvent(new MessageEvent('message', { data: JSON.stringify({ type: 'session.started' }) }));
      }
      close() { this.connectionState = 'closed'; }
    }
    Object.defineProperty(window, 'RTCPeerConnection', { value: FakePeer });
    Object.defineProperty(navigator.mediaDevices, 'getUserMedia', { value: async () => new MediaStream() });
    Object.defineProperty(window, '__peers', { value: peers });
  });
  const calls: string[] = [];
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname;
    calls.push(path);
    if (path.endsWith('/config')) return route.fulfill({ json: { voice_available: true } });
    if (path.endsWith('/sessions')) return route.fulfill({ json: { id: 'owned', key: 'key' } });
    if (path.endsWith('/heartbeat')) return route.fulfill({ json: { state: 'connected', delegation: 'idle', generation: 0, fallback_available: true } });
    if (path.endsWith('/reconnect')) {
      expect(route.request().postDataJSON()).toEqual({ sdp: 'v=0\r\n', generation: 0 });
      expect(route.request().headers()['x-session-key']).toBe('key');
    }
    return route.fulfill({ json: path.endsWith('/close') ? { finalized: true } : { sdp: 'v=0\r\n' } });
  });
  await page.goto('/');
  await page.getByRole('button', { name: 'Live voice', exact: true }).click();
  await page.getByRole('button', { name: 'Start conversation' }).click();
  await expect(page.getByRole('status')).toContainText('Connected.');
  const failPeer = () => page.evaluate(() => {
    const peers = (window as unknown as { __peers: (EventTarget & { connectionState: string })[] }).__peers;
    const peer = peers[peers.length - 1];
    peer.connectionState = 'failed';
    peer.dispatchEvent(new Event('connectionstatechange'));
  });
  await failPeer();
  await expect.poll(() => calls.filter(p => p.endsWith('/reconnect')).length).toBe(1);
  await expect(page.getByRole('status')).toContainText('Connected.');
  await failPeer();
  await expect.poll(() => calls.filter(p => p.endsWith('/close')).length).toBe(1);
  expect(calls.filter(p => p.endsWith('/sessions')).length).toBe(1);
  expect(calls.filter(p => p.endsWith('/reconnect')).length).toBe(1);
  await expect(page.getByRole('button', { name: 'Start conversation' })).toBeEnabled();
});
