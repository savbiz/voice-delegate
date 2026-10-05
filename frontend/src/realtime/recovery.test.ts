import { expect, test } from 'vitest';
import { shouldRecover } from './recovery';

test('provider errors and healthy heartbeat state do not initiate recovery', () => {
  expect(shouldRecover('error')).toBe(false);
  expect(shouldRecover('heartbeat', 'connected')).toBe(false);
  expect(shouldRecover('heartbeat', 'closed')).toBe(false);
  expect(shouldRecover('connectionstatechange', 'disconnected')).toBe(false);
  expect(shouldRecover('connectionstatechange', 'connected')).toBe(false);
});

test('failed media, closed data channels and server transport failure initiate recovery', () => {
  expect(shouldRecover('connectionstatechange', 'failed')).toBe(true);
  expect(shouldRecover('data-channel-close')).toBe(true);
  expect(shouldRecover('heartbeat', 'reconnecting')).toBe(true);
});
