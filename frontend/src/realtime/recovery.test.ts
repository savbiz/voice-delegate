import { expect, test } from 'vitest';
import { shouldRecover } from './recovery';

test('provider errors and heartbeat state do not initiate recovery', () => {
  expect(shouldRecover('error')).toBe(false);
  expect(shouldRecover('heartbeat', 'reconnecting')).toBe(false);
  expect(shouldRecover('connectionstatechange', 'disconnected')).toBe(false);
  expect(shouldRecover('connectionstatechange', 'connected')).toBe(false);
});

test('failed media and closed data channels initiate recovery', () => {
  expect(shouldRecover('connectionstatechange', 'failed')).toBe(true);
  expect(shouldRecover('data-channel-close')).toBe(true);
});
