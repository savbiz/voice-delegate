import { describe, expect, it } from 'vitest';
import { AudioTimingMeter } from './audio-timing';

describe('browser audio timing', () => {
  it('requires playback and energy, and reports setup once', () => {
    const meter = new AudioTimingMeter(100);
    expect(meter.sample(200, 0, 0.4, false)).toEqual([]);
    expect(meter.sample(220, 0, 0, true)).toEqual([]);
    expect(meter.sample(240, 0, 0.4, true)).toEqual([{ kind: 'setup', milliseconds: 140 }]);
    expect(meter.sample(260, 0, 0.4, true)).toEqual([]);
  });
  it('measures from last local energy rather than transcript receipt', () => {
    const meter = new AudioTimingMeter(0);
    meter.sample(0, 0, 0.3, true);
    meter.sample(20, 0.2, 0, true);
    meter.sample(40, 0.2, 0, true);
    for (let now = 60; now < 400; now += 20) meter.sample(now, 0, 0, true);
    expect(meter.sample(400, 0, 0.3, true)).toEqual([{ kind: 'turn', milliseconds: 360 }]);
    expect(meter.sample(420, 0, 0.3, true)).toEqual([]);
  });
  it('excludes overlap, mute, suspended sampling and out-of-budget values', () => {
    for (const mode of ['overlap', 'muted', 'gap']) {
      const meter = new AudioTimingMeter(0);
      meter.sample(0, 0, 0.3, true);
      meter.sample(20, 0.2, mode === 'overlap' ? 0.3 : 0, mode !== 'muted');
      if (mode !== 'gap') for (let now = 40; now < 400; now += 20) meter.sample(now, 0, 0, true);
      expect(meter.sample(400, 0, 0.3, true)).toEqual([]);
    }
    expect(new AudioTimingMeter(0).sample(120001, 0, 1, true)).toEqual([]);
    expect(new AudioTimingMeter(0).sample(NaN, 0, 1, true)).toEqual([]);
  });
});
