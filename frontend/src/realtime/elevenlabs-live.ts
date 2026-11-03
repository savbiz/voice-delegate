import type { CostSummary } from './costs';
/** SDK media and UI events; tools execute over authenticated server webhooks. */
import type { PartialOptions, VoiceConversation } from '@elevenlabs/client';
import rawAudioProcessor from '@elevenlabs/client/worklets/rawAudioProcessor.js?url&no-inline';
import type { LiveStore, TaskStatus } from './store';
import { processEvent, recapText, workerState } from './store';
import { AudioTimingMeter } from './audio-timing';
import type { Source } from '../reference';
type SDK = Pick<
  VoiceConversation,
  'endSession' | 'setVolume' | 'getInputVolume' | 'getOutputVolume'
>;
export type ElevenFactory = (options: PartialOptions) => Promise<SDK>;
export type SDKRequest = <T>(path: string, body?: unknown) => Promise<T>;
export function elevenSession(
  store: LiveStore,
  request: SDKRequest,
  ended: (message: string) => void,
  connected: () => void,
  muted: () => boolean,
  timing: boolean,
  factory: ElevenFactory = async (options) =>
    (await import('@elevenlabs/client')).VoiceConversation.startSession(options),
) {
  let sdk: SDK | undefined;
  let stopped = false;
  let sequence = 1;
  let allowEvents: (() => void) | undefined;
  let rejectEvents: (() => void) | undefined;
  const admitted = new Promise<void>((resolve, reject) => {
    allowEvents = resolve;
    rejectEvents = () => reject(new Error('Session ended.'));
  });
  void admitted.catch(() => undefined);
  let queued = 0;
  let chain = Promise.resolve();
  let interval: ReturnType<typeof setInterval> | undefined;
  let activityTimer: ReturnType<typeof setInterval> | undefined;
  let activityBusy = false;
  let polling = false;
  let errors = 0;
  const meter = timing ? new AudioTimingMeter(performance.now()) : undefined;
  const postEvent = (body: object) => {
    if (stopped || queued >= 16) return Promise.reject(new Error('SDK event unavailable.'));
    queued += 1;
    const pending = chain.then(async () => {
      await admitted;
      if (stopped) throw new Error('Session ended.');
      return request('/elevenlabs/events', { ...body, sequence: sequence++ });
    });
    chain = pending.then(
      () => undefined,
      () => undefined,
    );
    return pending.finally(() => {
      queued -= 1;
    });
  };
  async function end() {
    stopped = true;
    rejectEvents?.();
    clearInterval(interval);
    clearInterval(activityTimer);
    const current = sdk;
    sdk = undefined;
    if (!current) return;
    let timer: ReturnType<typeof setTimeout> | undefined;
    try {
      await Promise.race([
        current.endSession(),
        new Promise<void>((resolve) => {
          timer = setTimeout(resolve, 3000);
        }),
      ]);
    } catch {
      /* Backend confirmation remains independent of SDK disconnect. */
    } finally {
      clearTimeout(timer);
    }
  }
  async function start() {
    const bootstrap = await request<{ token: string; conversation_id: string }>(
      '/elevenlabs/bootstrap',
    );
    if (stopped) return;
    let connectedReport: Promise<unknown> | undefined;
    const opening = factory({
      conversationToken: bootstrap.token,
      connectionType: 'webrtc',
      workletPaths: { rawAudioProcessor },
      onConnect: ({ conversationId }) => {
        if (stopped || conversationId !== bootstrap.conversation_id) {
          ended('Voice conversation identity mismatch.');
          return;
        }
        connectedReport = request('/elevenlabs/events', {
          kind: 'connected',
          sequence: 0,
          conversation_id: conversationId,
        }).then((result) => {
          allowEvents?.();
          return result;
        });
        void connectedReport.catch(() => ended('Server connection failed.'));
      },
      onMessage: ({ message, role, event_id, response_id }) => {
        if (stopped || !message || message.length > 8192) return;
        const speaker = role === 'user' ? 'user' : 'assistant';
        store.update(
          processEvent(
            store.getSnapshot(),
            {
              type:
                speaker === 'user'
                  ? 'conversation.item.input_audio_transcription.completed'
                  : 'response.output_audio_transcript.done',
              transcript: message,
              item_id: response_id ?? String(event_id),
            },
            performance.now(),
          ).state,
        );
        void postEvent({ kind: 'transcript', speaker, text: message }).catch(() =>
          ended('Transcript synchronization failed.'),
        );
      },
      onError: () => ended('Voice provider connection failed.'),
      onDisconnect: () => {
        if (!stopped) ended('Conversation ended.');
      },
    });
    void opening.then(
      (value) => {
        if (stopped) void value.endSession().catch(() => undefined);
      },
      () => undefined,
    );
    let timeout: ReturnType<typeof setTimeout> | undefined;
    try {
      sdk = await Promise.race([
        opening,
        new Promise<never>((_, reject) => {
          timeout = setTimeout(() => {
            stopped = true;
            reject(new Error('Voice startup timed out.'));
          }, 20000);
        }),
      ]);
    } finally {
      clearTimeout(timeout);
    }
    if (stopped) {
      await end();
      return;
    }
    if (!connectedReport) throw new Error('Voice connection was not confirmed.');
    await connectedReport;
    store.update({
      phase: 'connected',
      status: 'Connected.',
      help: 'You can speak now.',
      audioTimingStatus: timing ? 'Waiting for SDK audio energy.' : 'Audio measurement disabled.',
    });
    connected();
    interval = setInterval(() => {
      if (stopped || polling) return;
      polling = true;
      void request<{
        state: string;
        delegation: string;
        tasks: TaskStatus[];
        sources: Source[];
        costs?: CostSummary;
        decision_cost_usd: number;
        recap: { latest_request: string; latest_reply: string; interrupted: boolean };
      }>('/heartbeat')
        .then((state) => {
          if (stopped) return;
          errors = 0;
          store.update({
            tasks: state.tasks,
            sources: state.sources,
            costs: state.costs,
            decisionCostUsd: state.decision_cost_usd,
            recap: recapText(state.recap),
          });
          store.update(workerState(store.getSnapshot(), state.delegation));
          if (state.state !== 'connected') ended('Conversation ended or session expired.');
        })
        .catch(() => {
          if (++errors >= 3) ended('Server connection lost.');
        })
        .finally(() => {
          polling = false;
        });
    }, 2000);
    let samples = 0;
    let ticks = 0;
    activityTimer = setInterval(() => {
      if (stopped || !sdk) return;
      sdk.setVolume({ volume: muted() ? 0 : 1 });
      const input = sdk.getInputVolume();
      const output = sdk.getOutputVolume();
      if (++ticks % 5 === 0 && !activityBusy) {
        activityBusy = true;
        void postEvent({
          kind: 'activity',
          user_speaking: input > 0.035,
          assistant_speaking: output > 0.02,
        })
          .catch(() => ended('Activity synchronization failed.'))
          .finally(() => {
            activityBusy = false;
          });
      }
      if (samples >= 120) return;
      for (const sample of meter?.sample(performance.now(), input, output, !muted()) ?? []) {
        samples += 1;
        store.update({
          audioTimings: [...store.getSnapshot().audioTimings, sample].slice(-40),
          audioTimingStatus: 'SDK audio-energy observation; not acoustic latency.',
        });
        void request('/audio-timing', {
          kind: sample.kind,
          seconds: sample.milliseconds / 1000,
          generation: 0,
        }).catch(() => undefined);
      }
    }, 50);
  }
  return { start, end };
}
