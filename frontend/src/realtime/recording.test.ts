import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { recordAudio } from './recording';

class Node {
  connect = vi.fn();
  disconnect = vi.fn();
  gain = { value: 1 };
}
class Context {
  static last: Context;
  nodes: Node[] = [];
  mixer = new Node();
  close = vi.fn(async () => undefined);
  resume = vi.fn(async () => undefined);
  constructor() {
    Context.last = this;
  }
  createMediaStreamSource() {
    const node = new Node();
    this.nodes.push(node);
    return node;
  }
  createMediaStreamDestination() {
    return { stream: {} };
  }
  createGain() {
    return this.mixer;
  }
}
class Recorder extends EventTarget {
  static last: Recorder;
  static isTypeSupported = () => true;
  state = 'inactive';
  mimeType = 'audio/webm;codecs=opus';
  constructor() {
    super();
    Recorder.last = this;
  }
  start() {
    this.state = 'recording';
  }
  chunk(blob = new Blob(['audio'])) {
    this.dispatchEvent(Object.assign(new Event('dataavailable'), { data: blob }));
  }
  stop() {
    this.state = 'inactive';
    this.chunk();
    this.dispatchEvent(new Event('stop'));
  }
}
beforeEach(() => {
  vi.useFakeTimers();
  vi.stubGlobal('AudioContext', Context);
  vi.stubGlobal('MediaRecorder', Recorder);
});
afterEach(() => {
  vi.clearAllTimers();
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

test('mixes microphone and assistant without routing captured audio back to speakers', () => {
  const complete = vi.fn();
  const recording = recordAudio({} as MediaStream, complete, vi.fn());
  recording.assistant({} as MediaStream);
  recording.microphone({} as MediaStream);
  expect(Context.last.nodes[0]?.disconnect).toHaveBeenCalledOnce();
  expect(
    Context.last.nodes.every((node) => node.connect.mock.calls[0]?.[0] === Context.last.mixer),
  ).toBe(true);
  expect(Context.last.mixer.gain.value).toBe(0.5);
  recording.stop();
  recording.stop();
  expect(complete).toHaveBeenCalledOnce();
  expect(complete.mock.calls[0]?.[0]).toBeInstanceOf(Blob);
  expect(Context.last.close).toHaveBeenCalledOnce();
});

test('time and size limits stop capture and preserve a downloadable blob', () => {
  const complete = vi.fn();
  recordAudio({} as MediaStream, complete, vi.fn());
  vi.advanceTimersByTime(300000);
  expect(complete).toHaveBeenCalledOnce();
  recordAudio({} as MediaStream, complete, vi.fn());
  Recorder.last.chunk(new Blob([new Uint8Array(20 * 1024 * 1024)]));
  expect(complete).toHaveBeenCalledTimes(2);
  expect(Recorder.last.state).toBe('inactive');
});

test('capture initialization failure releases the audio context', () => {
  vi.spyOn(Recorder.prototype, 'start').mockImplementation(() => {
    throw new Error('unsupported');
  });
  expect(() => recordAudio({} as MediaStream, vi.fn(), vi.fn())).toThrow('unsupported');
  expect(Context.last.close).toHaveBeenCalledOnce();
});
