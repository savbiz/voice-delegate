/** Draft SDK callback boundary. No browser SDK is started or loaded by this module. */
export type ElevenToolRequest = { call_id: string; goal: string };
export type ElevenSubmit = (request: ElevenToolRequest, signal: AbortSignal) => Promise<string>;

function record(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

/** Correlate public onIncomingEvent metadata with the SDK's parameters-only handler. */
export class ElevenToolBridge {
  private identities = new WeakMap<object, string>();
  private calls = new Map<string, Promise<string>>();
  private abort = new AbortController();

  constructor(private submit: ElevenSubmit) {}

  observe(event: unknown): void {
    if (!record(event) || event.type !== 'client_tool_call' || !record(event.client_tool_call))
      return;
    const call = event.client_tool_call;
    if (
      call.tool_name !== 'delegate_task' ||
      typeof call.tool_call_id !== 'string' ||
      !/^[a-zA-Z0-9_.:-]{1,200}$/.test(call.tool_call_id) ||
      !record(call.parameters)
    )
      return;
    this.identities.set(call.parameters, call.tool_call_id);
  }

  async delegate(parameters: unknown): Promise<string> {
    if (this.abort.signal.aborted || !record(parameters))
      throw new Error('Delegation unavailable.');
    const identity = this.identities.get(parameters);
    if (
      !identity ||
      typeof parameters.goal !== 'string' ||
      !parameters.goal.trim() ||
      new TextEncoder().encode(parameters.goal).byteLength > 8192
    ) {
      throw new Error('Delegation request could not be verified.');
    }
    const previous = this.calls.get(identity);
    if (previous) return previous;
    if (this.calls.size >= 64) throw new Error('Delegation limit reached.');
    const pending = this.execute({ call_id: identity, goal: parameters.goal.trim() });
    this.calls.set(identity, pending);
    return pending;
  }

  private async execute(request: ElevenToolRequest): Promise<string> {
    const controller = new AbortController();
    const stop = () => controller.abort();
    this.abort.signal.addEventListener('abort', stop, { once: true });
    const timer = setTimeout(stop, 20000);
    try {
      // Race explicitly: extensions that ignore AbortSignal must not hold the callback forever.
      const stopped = new Promise<never>((_, reject) =>
        controller.signal.addEventListener(
          'abort',
          () => reject(new Error('Delegation stopped.')),
          { once: true },
        ),
      );
      const result = await Promise.race([
        stopped,
        Promise.resolve().then(() => {
          if (controller.signal.aborted) throw new Error('Delegation stopped.');
          return this.submit(request, controller.signal);
        }),
      ]);
      if (
        controller.signal.aborted ||
        typeof result !== 'string' ||
        new TextEncoder().encode(result).byteLength > 500
      ) {
        throw new Error('Invalid delegation result.');
      }
      return result;
    } catch {
      throw new Error('Delegation unavailable or stopped.');
    } finally {
      clearTimeout(timer);
      this.abort.signal.removeEventListener('abort', stop);
    }
  }

  dispose(): void {
    this.abort.abort();
    this.identities = new WeakMap();
  }
}
