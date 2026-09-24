/** Check onset hysteresis without microphones or browser audio devices. */
import { expect, test, vi } from 'vitest';
import { LocalInterruptGate, SpeechGate, watchSpeech } from './vad';
test('cancels once per speech onset and rearms after silence', () => {
  const gate = new SpeechGate();
  expect(gate.update(0.1)).toBe(false);
  expect(gate.update(0.1)).toBe(false);
  expect(gate.update(0.1)).toBe(true);
  for (let i = 0; i < 20; i++) expect(gate.update(0.1)).toBe(false);
  for (let i = 0; i < 15; i++) expect(gate.update(0)).toBe(false);
  gate.update(0.1);
  gate.update(0.1);
  expect(gate.update(0.1)).toBe(true);
});
test('isolated noise spikes never trigger', () => {
  const gate = new SpeechGate();
  for (let i = 0; i < 20; i++) {
    expect(gate.update(0.1)).toBe(false);
    expect(gate.update(0)).toBe(false);
  }
});

test('remote speech suppresses echo and rearms after 300 ms of silence', () => {
  const gate = new LocalInterruptGate();
  for (let now = 0; now <= 200; now += 20) expect(gate.update(0.1, 0.1, now)).toBe(false);
  for (let now = 220; now < 500; now += 20) expect(gate.update(0.1, 0, now)).toBe(false);
  expect(gate.update(0.1, 0, 500)).toBe(false);
  expect(gate.update(0.1, 0, 520)).toBe(false);
  expect(gate.update(0.1, 0, 540)).toBe(true);
});

test('remote noise below the higher threshold does not block local speech', () => {
  const gate = new LocalInterruptGate();
  expect(gate.update(0.1, 0.04, 0)).toBe(false);
  expect(gate.update(0.1, 0.04, 20)).toBe(false);
  expect(gate.update(0.1, 0.04, 40)).toBe(true);
});

test('renewed remote speech extends the silence guard', () => {
  const gate = new LocalInterruptGate();
  for (let now = 0; now <= 100; now += 20) gate.update(0, 0.1, now);
  for (let now = 120; now <= 240; now += 20) expect(gate.update(0.1, 0, now)).toBe(false);
  for (let now = 260; now <= 400; now += 20) expect(gate.update(0.1, 0.1, now)).toBe(false);
  for (let now = 420; now < 700; now += 20) expect(gate.update(0.1, 0, now)).toBe(false);
  gate.update(0.1, 0, 700);
  gate.update(0.1, 0, 720);
  expect(gate.update(0.1, 0, 740)).toBe(true);
});

test('speech analysis setup closes its context when initialization fails', () => {
  const close = vi.fn(async () => undefined);
  class BrokenContext {
    close = close;
    createMediaStreamSource() {
      throw new Error('no audio source');
    }
  }
  vi.stubGlobal('AudioContext', BrokenContext);
  try {
    expect(() => watchSpeech({} as MediaStream, () => undefined)).toThrow('no audio source');
    expect(close).toHaveBeenCalledOnce();
  } finally {
    vi.unstubAllGlobals();
  }
});
