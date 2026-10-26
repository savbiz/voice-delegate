import { afterEach, expect, test, vi } from 'vitest';
import { ConnectionSounds } from './connection-sounds';

function fixture() {
  const frequencies: number[] = [];
  const stops: number[] = [];
  const close = vi.fn(async () => undefined);
  const resume = vi.fn(async () => undefined);
  vi.stubGlobal(
    'AudioContext',
    class {
      state = 'running';
      currentTime = 0;
      destination = {};
      close = close;
      resume = resume;
      createGain() {
        return {
          gain: { setValueAtTime() {}, linearRampToValueAtTime() {} },
          connect() {},
          disconnect() {},
        };
      }
      createOscillator() {
        return {
          frequency: { setValueAtTime: (value: number) => frequencies.push(value) },
          connect() {},
          disconnect() {},
          start() {},
          stop: (time: number) => stops.push(time),
          onended: undefined,
        };
      }
    },
  );
  return { sounds: new ConnectionSounds(), frequencies, stops, close, resume };
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

test('disabled by default and failed connection never plays a disconnect cue', () => {
  const { sounds, frequencies, resume, close } = fixture();
  sounds.arm(false);
  sounds.established();
  sounds.ended();
  expect(resume).not.toHaveBeenCalled();
  sounds.arm(true);
  sounds.ended();
  expect(frequencies).toEqual([]);
  expect(close).toHaveBeenCalledOnce();
});

test('connection and closure play bounded distinct cues once and release audio', async () => {
  vi.useFakeTimers();
  const { sounds, frequencies, stops, close } = fixture();
  sounds.arm(true);
  sounds.established();
  sounds.established();
  sounds.ended();
  sounds.ended();
  expect(frequencies).toEqual([440, 660, 660, 440]);
  expect(Math.max(...stops)).toBeLessThan(0.3);
  await vi.advanceTimersByTimeAsync(350);
  expect(close).toHaveBeenCalledOnce();
});

test('a new session cancels old cleanup and dispose closes its context', async () => {
  vi.useFakeTimers();
  const { sounds, close } = fixture();
  sounds.arm(true);
  sounds.established();
  sounds.ended();
  sounds.arm(true);
  await vi.advanceTimersByTimeAsync(350);
  expect(close).toHaveBeenCalledOnce();
  sounds.dispose();
  expect(close).toHaveBeenCalledTimes(2);
});

test('unsupported or blocked audio does not break the session', async () => {
  const { sounds, resume, close } = fixture();
  resume.mockRejectedValueOnce(new Error('blocked'));
  sounds.arm(true);
  await Promise.resolve();
  expect(close).toHaveBeenCalledOnce();
  expect(() =>
    new ConnectionSounds(() => {
      throw new Error('unsupported');
    }).arm(true),
  ).not.toThrow();
});
