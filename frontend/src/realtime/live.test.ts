import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { createLiveSession } from './live';
import type { LiveController } from './live';
import { createLiveStore } from './store';
import { watchSpeech } from './vad';

vi.mock('./vad', () => ({ watchSpeech: vi.fn(() => vi.fn()) }));
class FakeChannel extends EventTarget {
  close = vi.fn();
}
class FakePeer extends EventTarget {
  static instances: FakePeer[] = [];
  channel = new FakeChannel();
  connectionState = 'connected';
  iceGatheringState = 'complete';
  localDescription = { sdp: 'sdp' };
  close = vi.fn();
  addTrack = vi.fn();
  constructor() {
    super();
    FakePeer.instances.push(this);
  }
  async createOffer() {
    return { type: 'offer', sdp: 'sdp' };
  }
  createDataChannel() {
    return this.channel;
  }
  async setLocalDescription() {}
  async setRemoteDescription() {
    this.emit({ type: 'session.created' });
  }
  emit(event: unknown) {
    this.channel.dispatchEvent(new MessageEvent('message', { data: JSON.stringify(event) }));
  }
}
let controller: LiveController | undefined;
let stopTrack = vi.fn();
let responses: number[];
let delegation: string;
let transportState: string;
let closeResponse: Promise<Response> | undefined;
const source = {
  id: 's1',
  title: 'Architecture',
  section: 'History',
  path: 'docs/architecture.md',
  text: 'Evidence',
  digest: 'hash',
};
let sources = [source];
const requests: { path: string; init: RequestInit }[] = [];

beforeEach(() => {
  vi.useFakeTimers();
  requests.length = 0;
  FakePeer.instances = [];
  responses = [];
  delegation = 'idle';
  transportState = 'connected';
  closeResponse = undefined;
  sources = [source];
  stopTrack = vi.fn();
  vi.stubGlobal('window', new EventTarget());
  vi.stubGlobal('RTCPeerConnection', FakePeer);
  vi.stubGlobal('navigator', {
    mediaDevices: { getUserMedia: vi.fn(async () => ({ getTracks: () => [{ stop: stopTrack }] })) },
  });
  vi.spyOn(AbortSignal, 'timeout').mockImplementation(() => new AbortController().signal);
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init: RequestInit) => {
      const path = new URL(url, 'http://test').pathname;
      requests.push({ path, init });
      if (path.endsWith('/close') && closeResponse) return closeResponse;
      if (path.endsWith('/heartbeat')) {
        const status = responses.shift() ?? 200;
        return Response.json(
          { state: transportState, delegation, sources, generation: 0, fallback_available: true },
          { status },
        );
      }
      if (path.endsWith('/config')) return Response.json({ voice_available: true });
      if (path.endsWith('/sessions')) return Response.json({ id: 'session', key: 'key' });
      return Response.json({ sdp: 'sdp', finalized: true });
    }),
  );
});
afterEach(() => {
  controller?.dispose();
  controller = undefined;
  vi.clearAllTimers();
  vi.useRealTimers();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});
async function start(getCode = () => 'invite') {
  const store = createLiveStore();
  const audio = { srcObject: null } as HTMLAudioElement;
  controller = createLiveSession(store, audio, getCode, () => ({
    language: 'auto',
    mode: 'conversation',
  }));
  controller.start();
  await vi.waitFor(() => expect(store.getSnapshot().status).toContain('Connected'));
  return store;
}
test('heartbeat tolerates two failures, resets on success and finishes on the third consecutive failure', async () => {
  const store = await start();
  responses = [500, 500, 200, 500, 500, 500];
  for (let count = 0; count < 5; count++) {
    await vi.advanceTimersByTimeAsync(10000);
    expect(store.getSnapshot().active).toBe(true);
  }
  await vi.advanceTimersByTimeAsync(10000);
  expect(store.getSnapshot().phase).toBe('ended');
  expect(stopTrack).toHaveBeenCalledOnce();
  expect(AbortSignal.timeout).toHaveBeenCalledWith(8000);
});
test('local onset interrupts only after a running heartbeat', async () => {
  await start();
  const onset = vi.mocked(watchSpeech).mock.calls[0]?.[1];
  expect(onset).toBeDefined();
  onset?.();
  expect(requests.filter((r) => r.path.endsWith('/interrupt'))).toHaveLength(0);
  delegation = 'running';
  await vi.advanceTimersByTimeAsync(10000);
  onset?.();
  await vi.waitFor(() =>
    expect(requests.filter((r) => r.path.endsWith('/interrupt'))).toHaveLength(1),
  );
  delegation = 'completed';
  await vi.advanceTimersByTimeAsync(10000);
  onset?.();
  expect(requests.filter((r) => r.path.endsWith('/interrupt'))).toHaveLength(1);
});
test('stop releases media immediately and keeps ending true until close confirmation', async () => {
  const store = await start();
  let complete: (response: Response) => void = () => undefined;
  closeResponse = new Promise((resolve) => {
    complete = resolve;
  });
  controller?.stop();
  expect(stopTrack).toHaveBeenCalledOnce();
  expect(FakePeer.instances[0]?.close).toHaveBeenCalledOnce();
  expect(store.getSnapshot().phase).toBe('ended');
  expect(AbortSignal.timeout).toHaveBeenCalledWith(5000);
  expect(store.getSnapshot().ending).toBe(true);
  controller?.start();
  expect(FakePeer.instances).toHaveLength(1);
  complete(Response.json({ finalized: false }));
  await vi.waitFor(() => expect(store.getSnapshot().ending).toBe(false));
  controller?.start();
  await vi.waitFor(() => expect(FakePeer.instances).toHaveLength(2));
  await vi.waitFor(() => expect(store.getSnapshot().phase).toBe('connected'));
  expect(store.getSnapshot().status).toBe('Connected. Speak naturally.');
});
test('same source ids retain display state and reconnect preserves captions and timings', async () => {
  const store = await start();
  await vi.advanceTimersByTimeAsync(10000);
  const originalSources = store.getSnapshot().sources;
  sources = [{ ...source }];
  await vi.advanceTimersByTimeAsync(10000);
  expect(store.getSnapshot().sources).toBe(originalSources);
  const peer = FakePeer.instances[0]!;
  peer.emit({
    type: 'session.input_transcript.delta',
    delta: 'question',
    start_ms: 10,
    end_ms: 100,
  });
  peer.emit({
    type: 'session.output_transcript.delta',
    delta: 'answer',
    start_ms: 150,
    end_ms: 200,
  });
  const before = store.getSnapshot();
  peer.connectionState = 'failed';
  peer.dispatchEvent(new Event('connectionstatechange'));
  await vi.waitFor(() => expect(FakePeer.instances).toHaveLength(2));
  await vi.waitFor(() => expect(store.getSnapshot().phase).toBe('connected'));
  expect(store.getSnapshot().captions).toEqual(before.captions);
  expect(store.getSnapshot().timings).toEqual(before.timings);
  expect(store.getSnapshot().sources).toBe(before.sources);
});
test('pagehide uses the same authorization, content type and JSON body as a normal request', async () => {
  await start();
  window.dispatchEvent(new Event('pagehide'));
  const closed = requests.find((r) => r.path.endsWith('/close'));
  const offer = requests.find((r) => r.path.endsWith('/offer'));
  expect(closed?.init.headers).toEqual(offer?.init.headers);
  expect(closed?.init.body).toBe('{}');
  expect(closed?.init.keepalive).toBe(true);
  expect(stopTrack).toHaveBeenCalledOnce();
});

test('session credentials stay fixed while a new session uses the edited invitation', async () => {
  let code = 'original';
  await start(() => code);
  code = 'edited';
  await vi.advanceTimersByTimeAsync(10000);
  controller?.cancel();
  window.dispatchEvent(new Event('pagehide'));
  const owned = requests.filter((request) => request.path.includes('/sessions/session/'));
  expect(owned.some((request) => request.path.endsWith('/heartbeat'))).toBe(true);
  expect(owned.some((request) => request.path.endsWith('/interrupt'))).toBe(true);
  expect(owned.some((request) => request.path.endsWith('/close'))).toBe(true);
  for (const request of owned)
    expect(new Headers(request.init.headers).get('Authorization')).toBe('Bearer original');
  controller?.start();
  await vi.waitFor(() =>
    expect(requests.filter((request) => request.path.endsWith('/sessions'))).toHaveLength(2),
  );
  const created = requests.filter((request) => request.path.endsWith('/sessions')).at(-1);
  expect(new Headers(created?.init.headers).get('Authorization')).toBe('Bearer edited');
});

test('server reconnecting heartbeat recovers even when the browser peer is connected', async () => {
  const store = await start();
  FakePeer.instances[0]?.emit({ type: 'error' });
  expect(requests.filter((request) => request.path.endsWith('/reconnect'))).toHaveLength(0);
  transportState = 'reconnecting';
  await vi.advanceTimersByTimeAsync(10000);
  await vi.waitFor(() =>
    expect(requests.filter((request) => request.path.endsWith('/reconnect'))).toHaveLength(1),
  );
  expect(FakePeer.instances).toHaveLength(2);
  expect(store.getSnapshot().phase).toBe('connected');
});

test('failed close clears ending after reporting unconfirmed cleanup', async () => {
  const store = await start();
  let rejectClose: (error: Error) => void = () => undefined;
  closeResponse = new Promise((_, reject) => {
    rejectClose = reject;
  });
  controller?.stop();
  expect(store.getSnapshot().ending).toBe(true);
  rejectClose(new Error('timeout'));
  await vi.waitFor(() => expect(store.getSnapshot().ending).toBe(false));
  expect(store.getSnapshot().status).toContain('Close was not confirmed');
});
