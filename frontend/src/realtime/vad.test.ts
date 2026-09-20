/** Check onset hysteresis without microphones or browser audio devices. */
import { expect, test } from 'vitest';
import { SpeechGate } from './vad';
test('cancels once per speech onset and rearms after silence', () => {
  const gate = new SpeechGate();
  expect(gate.update(0.1)).toBe(false);
  expect(gate.update(0.1)).toBe(false);
  expect(gate.update(0.1)).toBe(true);
  for (let i=0; i<20; i++) expect(gate.update(0.1)).toBe(false);
  for (let i=0; i<15; i++) expect(gate.update(0)).toBe(false);
  gate.update(0.1); gate.update(0.1);
  expect(gate.update(0.1)).toBe(true);
});
test('isolated noise spikes never trigger', () => {
  const gate = new SpeechGate();
  for (let i=0; i<20; i++) { expect(gate.update(0.1)).toBe(false); expect(gate.update(0)).toBe(false); }
});
