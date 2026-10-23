/** Immutable display state and pure provider-event transitions. */
import type { Source } from '../reference';

const TRANSCRIPT_GAP_MS = 800;

export type Phase =
  'ready' | 'connecting' | 'connected' | 'working' | 'busy' | 'recovering' | 'ended';
export type TranscriptDelta = {
  speaker: 'user' | 'assistant';
  delta: string;
  start_ms?: number;
  end_ms?: number;
};
export type TurnTiming = {
  id: number;
  transportId: number;
  end: number;
  reply?: number;
  receivedEnd: number;
  estimated: boolean;
};
export type ChatMessage = { id: number; speaker: 'user' | 'assistant'; text: string };
type CaptionTail = {
  messageId?: number;
  key?: string;
  length: number;
  complete: boolean;
  end?: number;
  transportId: number;
};
export type LiveState = {
  phase: Phase;
  status: string;
  help: string;
  worker: string;
  workerMessage: string;
  active: boolean;
  ending: boolean;
  recovering: boolean;
  cancelPending: boolean;
  captions: { user: string; assistant: string };
  messages: ChatMessage[];
  audioBlocked: boolean;
  captionTails: Partial<Record<'user' | 'assistant', CaptionTail>>;
  lastSpeaker?: 'user' | 'assistant';
  timings: TurnTiming[];
  timingTransportId: number;
  sources: Source[];
  recap: string;
  feedbackStatus: string;
  debugStatus: string;
  audioStatus: string;
  audioUrl: string;
  audioFilename: string;
  reportPending: boolean;
  reportSent: boolean;
  reportLocked: boolean;
};
export const workerMessages: Record<string, string> = {
  idle: 'Worker ready.',
  running: 'Working on your request. You can interrupt by speaking.',
  busy: 'Worker busy. Your task was not started. Repeat your request later if you still need it.',
  completed: 'Task completed.',
  cancelled: 'Task cancelled. You can give a new request.',
  timeout: 'The task took too long and was stopped. You can give a new request.',
  failed: 'The task failed. You can give a new request; nothing is retried automatically.',
  request_limit:
    'This conversation has reached its task limit. Start a new conversation if your allowance permits.',
  delivery_failed:
    'The worker result could not be delivered. Repeat your request if you still need it.',
};
export function initialLiveState(): LiveState {
  return {
    phase: 'ready',
    status: 'Ready to connect',
    help: 'Start a conversation when you are ready.',
    worker: 'idle',
    workerMessage: workerMessages.idle!,
    active: false,
    ending: false,
    recovering: false,
    cancelPending: false,
    captions: { user: '', assistant: '' },
    messages: [],
    audioBlocked: false,
    captionTails: {},
    timings: [],
    timingTransportId: 0,
    sources: [],
    recap: 'No conversation yet.',
    reportPending: false,
    reportSent: false,
    reportLocked: false,
    debugStatus: '',
    audioStatus: '',
    audioUrl: '',
    audioFilename: '',
    feedbackStatus: 'An invitation or access code is required to send feedback.',
  };
}
export function workerState(state: LiveState, worker: string): LiveState {
  const cancelPending = state.cancelPending && worker === 'running';
  const phase =
    state.active && !state.ending && !state.recovering
      ? worker === 'running'
        ? 'working'
        : worker === 'busy'
          ? 'busy'
          : 'connected'
      : state.phase;
  return {
    ...state,
    phase,
    worker,
    cancelPending,
    workerMessage: cancelPending
      ? state.workerMessage
      : (workerMessages[worker] ?? 'Waiting for worker status.'),
  };
}
export function updateTurnTiming(
  timings: TurnTiming[],
  speaker: 'user' | 'assistant',
  start?: number,
  end?: number,
  receivedAt = 0,
  transportId = 0,
): TurnTiming[] {
  const timed =
    typeof start === 'number' &&
    typeof end === 'number' &&
    Number.isFinite(start) &&
    Number.isFinite(end);
  const latest = timings[0];
  if (speaker === 'user') {
    const gap =
      timed && latest && !latest.estimated
        ? start - latest.end
        : receivedAt - (latest?.receivedEnd ?? 0);
    if (
      !latest ||
      latest.reply !== undefined ||
      latest.transportId !== transportId ||
      gap > TRANSCRIPT_GAP_MS
    ) {
      return [
        {
          id: (latest?.id ?? 0) + 1,
          transportId,
          end: timed ? end : receivedAt,
          receivedEnd: receivedAt,
          estimated: !timed,
        },
        ...timings,
      ].slice(0, 20);
    }
    const estimated = latest.estimated || !timed;
    return [
      {
        ...latest,
        estimated,
        receivedEnd: receivedAt,
        end: estimated ? receivedAt : Math.max(latest.end, end),
      },
      ...timings.slice(1),
    ];
  }
  if (!latest || latest.transportId !== transportId || latest.reply !== undefined) return timings;
  const estimated = latest.estimated || !timed;
  return [
    {
      ...latest,
      estimated,
      end: estimated ? latest.receivedEnd : latest.end,
      reply: estimated ? receivedAt : start,
    },
    ...timings.slice(1),
  ];
}

export function processEvent(
  state: LiveState,
  raw: unknown,
  receivedAt = 0,
): {
  state: LiveState;
  effect?: 'started' | 'closed';
} {
  if (typeof raw !== 'object' || raw === null) return { state };
  const event = raw as Record<string, unknown>;
  if (event.type === 'session.started' || event.type === 'session.created') {
    return {
      effect: 'started',
      state: {
        ...state,
        phase: 'connected',
        status: 'Connected. Speak naturally.',
        help: 'Speak to give a request or interrupt. Select Stop to end the conversation.',
      },
    };
  }
  if (event.type === 'session.closed') return { state, effect: 'closed' };
  if (event.type === 'error')
    return {
      state: {
        ...state,
        status: 'The provider reported an error.',
        help: 'You can continue speaking or stop the conversation.',
      },
    };
  if (event.type === 'session.delegation.created') return { state: workerState(state, 'running') };
  const speaker = [
    'session.input_transcript.delta',
    'conversation.item.input_audio_transcription.completed',
  ].includes(String(event.type))
    ? 'user'
    : [
          'session.output_transcript.delta',
          'response.output_audio_transcript.delta',
          'response.output_audio_transcript.done',
        ].includes(String(event.type))
      ? 'assistant'
      : undefined;
  const delta =
    event.type === 'conversation.item.input_audio_transcription.completed' ||
    event.type === 'response.output_audio_transcript.done'
      ? event.transcript
      : event.delta;
  if (!speaker || typeof delta !== 'string') return { state };
  if (!delta) return { state };
  const complete =
    event.type === 'conversation.item.input_audio_transcription.completed' ||
    event.type === 'response.output_audio_transcript.done';
  const key = typeof event.item_id === 'string' ? event.item_id : undefined;
  const tail = state.captionTails[speaker];
  const sameTransport = tail?.transportId === state.timingTransportId;
  const sameItem = key !== undefined && tail?.key === key && sameTransport;
  if (sameItem && tail.complete) return { state };
  const start = typeof event.start_ms === 'number' ? event.start_ms : undefined;
  const gap =
    start !== undefined && tail?.end !== undefined && start > tail.end + TRANSCRIPT_GAP_MS;
  const continuation =
    sameItem ||
    (key === undefined &&
      tail?.key === undefined &&
      sameTransport &&
      !tail.complete &&
      (state.lastSpeaker === speaker ||
        (start !== undefined && tail.end !== undefined && start >= tail.end)) &&
      !gap);
  const prior = state.captions[speaker];
  const replace = complete && continuation;
  const prefix = replace ? prior.slice(0, prior.length - (tail?.length ?? 0)) : prior;
  const separator = !continuation && prefix ? '\n' : '';
  const caption = (prefix + separator + delta).slice(-6000);
  const length = Math.min(
    6000,
    (continuation && !replace ? (tail?.length ?? 0) : 0) + delta.length,
  );
  const messages = [...state.messages];
  const existingIndex = continuation
    ? messages.findIndex((message) => message.id === tail?.messageId)
    : -1;
  const existing = messages[existingIndex];
  const messageId = existing?.id ?? (messages.at(-1)?.id ?? 0) + 1;
  const message: ChatMessage = {
    id: messageId,
    speaker,
    text: ((existing && !replace ? existing.text : '') + delta).slice(-6000),
  };
  if (existingIndex >= 0) messages[existingIndex] = message;
  else messages.push(message);
  let total = messages.reduce((sum, entry) => sum + entry.text.length, 0);
  while (messages.length > 40 || total > 12000) total -= messages.shift()!.text.length;
  const transcript: TranscriptDelta = {
    speaker,
    delta,
    ...(typeof event.start_ms === 'number' ? { start_ms: event.start_ms } : {}),
    ...(typeof event.end_ms === 'number' ? { end_ms: event.end_ms } : {}),
  };
  const timings = updateTurnTiming(
    state.timings,
    transcript.speaker,
    transcript.start_ms,
    transcript.end_ms,
    receivedAt,
    state.timingTransportId,
  );
  return {
    state: {
      ...state,
      timings,
      messages,
      captions: { ...state.captions, [speaker]: caption },
      lastSpeaker: speaker,
      captionTails: {
        ...state.captionTails,
        [speaker]: {
          key,
          messageId,
          length,
          complete,
          end: transcript.end_ms,
          transportId: state.timingTransportId,
        },
      },
    },
  };
}
export function createLiveStore() {
  let state = initialLiveState();
  const listeners = new Set<() => void>();
  return {
    getSnapshot: () => state,
    subscribe: (listener: () => void) => {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
    update: (patch: Partial<LiveState>) => {
      state = { ...state, ...patch };
      listeners.forEach((listener) => listener());
    },
  };
}
export type LiveStore = ReturnType<typeof createLiveStore>;
