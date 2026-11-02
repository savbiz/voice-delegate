import { afterEach, expect, it, vi } from 'vitest';
import { ElevenToolBridge } from './elevenlabs';
import type { ElevenToolRequest } from './elevenlabs';

afterEach(() => vi.useRealTimers());

function observe(
  bridge: ElevenToolBridge,
  parameters: object,
  id = 'native-call-1',
  name = 'delegate_task',
) {
  bridge.observe({
    type: 'client_tool_call',
    client_tool_call: {
      tool_name: name,
      tool_call_id: id,
      parameters,
    },
  });
}

it('uses native correlation and deduplicates repeated SDK delivery', async () => {
  const submit = vi.fn(async (request: ElevenToolRequest) => {
    expect(request.call_id).toBe('native-call-1');
    return 'Result [1]';
  });
  const bridge = new ElevenToolBridge(submit);
  const parameters = { goal: ' Find documentation ', call_id: 'model-chosen-id' };
  observe(bridge, parameters);
  expect(await bridge.delegate(parameters)).toBe('Result [1]');
  expect(await bridge.delegate(parameters)).toBe('Result [1]');
  expect(submit).toHaveBeenCalledTimes(1);
  expect(submit.mock.calls[0]?.[0]).toEqual({
    call_id: 'native-call-1',
    goal: 'Find documentation',
  });
  bridge.dispose();
});

it('does not trust unknown tools, copied parameters or model-supplied IDs', async () => {
  const submit = vi.fn(async () => 'unused');
  const bridge = new ElevenToolBridge(submit);
  const parameters = { goal: 'hello', call_id: 'fake' };
  observe(bridge, parameters, 'native', 'unknown');
  await expect(bridge.delegate(parameters)).rejects.toThrow('could not be verified');
  observe(bridge, parameters);
  await expect(bridge.delegate({ ...parameters })).rejects.toThrow('could not be verified');
  expect(submit).not.toHaveBeenCalled();
  bridge.dispose();
});

it('caps response bytes and redacts extension errors', async () => {
  for (const submit of [
    async () => 'é'.repeat(251),
    async () => {
      throw new Error('private detail');
    },
  ]) {
    const bridge = new ElevenToolBridge(submit);
    const parameters = { goal: 'hello' };
    observe(bridge, parameters);
    await expect(bridge.delegate(parameters)).rejects.toThrow('Delegation unavailable or stopped.');
    bridge.dispose();
  }
});

it('bounds callbacks even when the extension ignores cancellation', async () => {
  vi.useFakeTimers();
  const bridge = new ElevenToolBridge(() => new Promise(() => {}));
  const parameters = { goal: 'hello' };
  observe(bridge, parameters);
  const pending = expect(bridge.delegate(parameters)).rejects.toThrow('unavailable or stopped');
  await vi.advanceTimersByTimeAsync(20000);
  await pending;
  bridge.dispose();
});

it('disposal stops pending callbacks and rejects new work', async () => {
  const bridge = new ElevenToolBridge(() => new Promise(() => {}));
  const parameters = { goal: 'hello' };
  observe(bridge, parameters);
  const pending = expect(bridge.delegate(parameters)).rejects.toThrow('unavailable or stopped');
  bridge.dispose();
  await pending;
  await expect(bridge.delegate(parameters)).rejects.toThrow('Delegation unavailable.');
});

it('handles synchronous disposal inside an extension without waiting for the deadline', async () => {
  const bridge = new ElevenToolBridge(async () => {
    bridge.dispose();
    return new Promise(() => {});
  });
  const parameters = { goal: 'hello' };
  observe(bridge, parameters);
  await expect(bridge.delegate(parameters)).rejects.toThrow('unavailable or stopped');
});
