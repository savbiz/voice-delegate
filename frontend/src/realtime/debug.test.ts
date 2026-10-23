import { expect, test } from 'vitest';
import { audioSample } from './debug';

test('audio diagnostics only select finite numeric fields', () => {
  expect(
    audioSample({
      type: 'inbound-rtp',
      kind: 'audio',
      packetsLost: 3,
      jitter: 0.02,
      address: 'private',
      token: 'private',
      audioLevel: NaN,
    }),
  ).toEqual({ event: 'stats', packets_lost: 3, jitter_seconds: 0.02 });
  expect(audioSample({ type: 'candidate-pair', address: 'private' })).toBeUndefined();
  expect(audioSample({ type: 'inbound-rtp', kind: 'video', packetsLost: 3 })).toBeUndefined();
});
