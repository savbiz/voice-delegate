import { afterEach, expect, it, vi } from 'vitest';
import type { PartialOptions } from '@elevenlabs/client';
import { elevenSession } from './elevenlabs-live';
import type { ElevenFactory, SDKRequest } from './elevenlabs-live';
import { createLiveStore } from './store';
afterEach(() => vi.useRealTimers());
function fixture() {
  let options: PartialOptions | undefined;
  const sdk = {
    endSession: vi.fn(async () => {}),
    setVolume: vi.fn(),
    getInputVolume: () => 0,
    getOutputVolume: () => 0,
  };
  const factory: ElevenFactory = async (value) => {
    options = value;
    value.onConnect?.({ conversationId: 'conv_fixture' });
    return sdk;
  };
  const request = vi.fn(async (path: string) => {
    if (path === '/elevenlabs/bootstrap')
      return { token: 'ephemeral-fixture', conversation_id: 'conv_fixture' };
    if (path === '/elevenlabs/result') return { status: 'ready', text: '4' };
    return {};
  }) as unknown as SDKRequest;
  return { sdk, factory, request, options: () => options! };
}
it('uses SDK-owned media and native tool results without manufacturing a user turn', async () => {
  const setup = fixture();
  const store = createLiveStore();
  const connected = vi.fn();
  const controller = elevenSession(
    store,
    setup.request,
    vi.fn(),
    connected,
    () => false,
    false,
    setup.factory,
  );
  await controller.start();
  expect(connected).toHaveBeenCalledOnce();
  const parameters = { goal: 'calculate 2+2' };
  setup.options().onIncomingEvent?.({
    type: 'client_tool_call',
    client_tool_call: { tool_name: 'delegate_task', tool_call_id: 'native-one', parameters },
  });
  expect(await setup.options().clientTools?.delegate_task?.(parameters)).toBe('4');
  expect(setup.request).toHaveBeenCalledWith('/elevenlabs/delegate', {
    call_id: 'native-one',
    goal: 'calculate 2+2',
  });
  await controller.end();
  expect(setup.sdk.endSession).toHaveBeenCalledOnce();
});
it('admits the conversation before forwarding transcript callbacks delivered during startup', async () => {
  const setup = fixture();
  const store = createLiveStore();
  const factory: ElevenFactory = async (options) => {
    options.onMessage?.({ message: 'fixture', role: 'user', source: 'user', event_id: 1 });
    options.onConnect?.({ conversationId: 'conv_fixture' });
    return setup.sdk;
  };
  const controller = elevenSession(
    store,
    setup.request,
    vi.fn(),
    vi.fn(),
    () => false,
    false,
    factory,
  );
  await controller.start();
  await Promise.resolve();
  const calls = vi
    .mocked(setup.request)
    .mock.calls.filter(([path]) => path === '/elevenlabs/events');
  expect(calls[0]?.[1]).toMatchObject({ kind: 'connected', sequence: 0 });
  expect(calls[1]?.[1]).toMatchObject({ kind: 'transcript', sequence: 1 });
  await controller.end();
});
it('closes an SDK that completes startup after the user stops', async () => {
  const setup = fixture();
  let open: ((sdk: Awaited<ReturnType<ElevenFactory>>) => void) | undefined;
  const factory: ElevenFactory = () =>
    new Promise((resolve) => {
      open = resolve;
    });
  const controller = elevenSession(
    createLiveStore(),
    setup.request,
    vi.fn(),
    vi.fn(),
    () => false,
    false,
    factory,
  );
  const pending = controller.start();
  await Promise.resolve();
  await Promise.resolve();
  await controller.end();
  open?.(setup.sdk);
  await pending;
  expect(setup.sdk.endSession).toHaveBeenCalled();
});
