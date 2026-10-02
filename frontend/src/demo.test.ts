/** Verify the visible offline recording stays within its step bounds. */
import { expect, test } from 'vitest';
import { visibleScenario } from './demo';
test('bounds the visible recording', () => {
  expect(visibleScenario(-1)).toHaveLength(0);
  expect(visibleScenario(100)).toHaveLength(4);
  expect(visibleScenario(2)).toHaveLength(2);
});
