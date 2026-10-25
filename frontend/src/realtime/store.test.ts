import { expect, test, vi } from 'vitest';
import {
  chatBubbles,
  endedWorkerState,
  taskLabel,
  recapText,
  createLiveStore,
  initialLiveState,
  processEvent,
  updateTurnTiming,
  workerState,
} from './store';

test('provider errors update display without requesting recovery', () => {
  const state = { ...initialLiveState(), active: true };
  const connected = processEvent(state, { type: 'session.started' });
  expect(connected.effect).toBe('started');
  const failed = processEvent(connected.state, { type: 'error' });
  expect(failed.effect).toBeUndefined();
  expect(failed.state.phase).toBe('connected');
  expect(failed.state.status).toBe('The provider reported an error.');
  expect(processEvent(state, { type: 'session.closed' }).effect).toBe('closed');
});

test('transcripts remain bounded and input events are not mutated', () => {
  const event = Object.freeze({
    type: 'conversation.item.input_audio_transcription.completed',
    transcript: 'x'.repeat(7000),
  });
  const initial = initialLiveState();
  const result = processEvent(initial, event).state;
  expect(result.captions.user).toHaveLength(6000);
  expect(initial.captions.user).toBe('');
  expect(event).not.toHaveProperty('delta');
  expect(processEvent(initial, null).state).toBe(initial);
  expect(processEvent(initial, { type: 'unrecognized' }).state).toBe(initial);
});

test('delegation updates worker display and preserves captions', () => {
  const state = {
    ...initialLiveState(),
    active: true,
    captions: { user: 'question', assistant: '' },
  };
  const next = processEvent(state, { type: 'session.delegation.created' }).state;
  expect(next.phase).toBe('working');
  expect(next.worker).toBe('running');
  expect(next.captions).toBe(state.captions);
});

test('turn timing merges fragments, preserves overlap and bounds history', () => {
  let timings = updateTurnTiming([], 'user', 0, 100);
  timings = updateTurnTiming(timings, 'user', 100, 200);
  timings = updateTurnTiming(timings, 'assistant', 150, 300);
  expect(timings).toEqual([
    { id: 1, transportId: 0, end: 200, reply: 150, receivedEnd: 0, estimated: false },
  ]);
  const unchanged = updateTurnTiming(timings, 'assistant', 200, 400);
  expect(unchanged).toBe(timings);
  expect(updateTurnTiming(timings, 'user', Infinity, 0)[0]?.estimated).toBe(true);
  for (let id = 2; id <= 25; id++)
    timings = updateTurnTiming(timings, 'user', id * 1000, id * 1000 + 100);
  expect(timings).toHaveLength(20);
  expect(timings[0]?.id).toBe(25);
  expect(timings.at(-1)?.id).toBe(6);
});

test('store snapshots are stable between updates and unsubscribe releases listeners', () => {
  const store = createLiveStore();
  const original = store.getSnapshot();
  const listener = vi.fn();
  const unsubscribe = store.subscribe(listener);
  expect(store.getSnapshot()).toBe(original);
  store.update({ status: 'new status' });
  expect(listener).toHaveBeenCalledOnce();
  expect(original.status).toBe('Ready to connect');
  expect(store.getSnapshot().status).toBe('new status');
  unsubscribe();
  store.update({ status: 'later status' });
  expect(listener).toHaveBeenCalledOnce();
});

test('missing provider timing uses receipt timestamps without mixing clock origins', () => {
  let state = processEvent(
    initialLiveState(),
    { type: 'session.input_transcript.delta', delta: 'hello', start_ms: 100, end_ms: 200 },
    5000,
  ).state;
  state = processEvent(
    state,
    { type: 'response.output_audio_transcript.delta', delta: 'hi' },
    5200,
  ).state;
  expect(state.timings[0]).toMatchObject({ end: 5000, reply: 5200, estimated: true });
  const input = processEvent(
    initialLiveState(),
    { type: 'conversation.item.input_audio_transcription.completed', transcript: 'hello' },
    6000,
  ).state;
  const reply = processEvent(
    input,
    { type: 'response.output_audio_transcript.delta', delta: 'hi' },
    6300,
  ).state;
  expect(reply.timings[0]).toMatchObject({ end: 6000, reply: 6300, estimated: true });
});

test('a user turn after a reply starts a fresh timing row even within 800 ms', () => {
  let rows = updateTurnTiming([], 'user', 100, 200, 5000);
  rows = updateTurnTiming(rows, 'assistant', 300, 400, 5200);
  const completed = rows[0];
  rows = updateTurnTiming(rows, 'user', 600, 700, 5500);
  rows = updateTurnTiming(rows, 'assistant', 800, 900, 5700);
  expect(rows).toHaveLength(2);
  expect(rows[1]).toEqual(completed);
  expect(rows[0]).toMatchObject({ id: 2, end: 700, reply: 800 });
});

test('fallback preserves old rows but never joins timestamps across transports', () => {
  let rows = updateTurnTiming([], 'user', 10000, 11000, 15000, 1);
  const before = rows;
  expect(updateTurnTiming(rows, 'assistant', undefined, undefined, 15200, 2)).toBe(before);
  rows = updateTurnTiming(rows, 'user', undefined, undefined, 15300, 2);
  rows = updateTurnTiming(rows, 'assistant', undefined, undefined, 15400, 2);
  expect(rows).toHaveLength(2);
  expect(rows[1]).toEqual(before[0]);
  expect(rows[0]).toMatchObject({ transportId: 2, end: 15300, reply: 15400, estimated: true });
  const reset = updateTurnTiming(rows, 'user', 0, 100, 15500, 3);
  expect(reset).toHaveLength(3);
  expect(reset[0]).toMatchObject({ transportId: 3, end: 100, estimated: false });
});

test('running heartbeats retain cancellation until the worker changes state', () => {
  const message = 'Worker cancellation requested. You can give a new request.';
  const state = {
    ...initialLiveState(),
    worker: 'running',
    cancelPending: true,
    workerMessage: message,
  };
  const running = workerState(state, 'running');
  expect(running.cancelPending).toBe(true);
  expect(running.workerMessage).toBe(message);
  const cancelled = workerState(running, 'cancelled');
  expect(cancelled.cancelPending).toBe(false);
  expect(cancelled.workerMessage).toContain('Task cancelled');
  expect(workerState(running, 'completed').cancelPending).toBe(false);
});

test('completed user turns are separated, including identical repeated words', () => {
  const event = {
    type: 'conversation.item.input_audio_transcription.completed',
    transcript: 'Hello',
  };
  let state = processEvent(initialLiveState(), { ...event, item_id: 'one' }).state;
  state = processEvent(state, { ...event, item_id: 'two' }).state;
  expect(state.captions.user).toBe('Hello\nHello');
  expect(processEvent(state, { ...event, item_id: 'two' }).state).toBe(state);
});

test('assistant final transcript replaces fragments and next response starts a line', () => {
  let state = initialLiveState();
  for (const delta of ['Hel', 'lo'])
    state = processEvent(state, {
      type: 'response.output_audio_transcript.delta',
      item_id: 'one',
      delta,
    }).state;
  expect(state.captions.assistant).toBe('Hello');
  state = processEvent(state, {
    type: 'response.output_audio_transcript.done',
    item_id: 'one',
    transcript: 'Hello!',
  }).state;
  expect(state.captions.assistant).toBe('Hello!');
  state = processEvent(state, {
    type: 'response.output_audio_transcript.delta',
    item_id: 'two',
    delta: 'Next',
  }).state;
  expect(state.captions.assistant).toBe('Hello!\nNext');
});

test('Live fragments keep word boundaries intact and separate turns after pauses', () => {
  let state = initialLiveState();
  for (const [delta, start_ms, end_ms] of [
    ['Hel', 10, 20],
    ['lo', 20, 30],
    ['Again', 1000, 1100],
  ] as const) {
    state = processEvent(state, {
      type: 'session.input_transcript.delta',
      delta,
      start_ms,
      end_ms,
    }).state;
  }
  expect(state.captions.user).toBe('Hello\nAgain');
  state = processEvent(state, { type: 'session.output_transcript.delta', delta: 'Yes' }).state;
  state = processEvent(state, { type: 'session.input_transcript.delta', delta: 'Thanks' }).state;
  expect(state.captions.user).toBe('Hello\nAgain\nThanks');
});

test('timed fragments stay together when the other speaker interleaves', () => {
  let state = processEvent(initialLiveState(), {
    type: 'session.input_transcript.delta',
    delta: 'Bye-b',
    start_ms: 100,
    end_ms: 200,
  }).state;
  state = processEvent(state, {
    type: 'session.output_transcript.delta',
    delta: 'Goodbye',
    start_ms: 150,
    end_ms: 250,
  }).state;
  state = processEvent(state, {
    type: 'session.input_transcript.delta',
    delta: 'ye',
    start_ms: 200,
    end_ms: 300,
  }).state;
  expect(state.captions.user).toBe('Bye-bye');
  expect(workerState(state, 'failed').workerMessage).not.toContain('completed');
});

test('chat retains chronological turns and merges overlapping speaker fragments', () => {
  let state = initialLiveState();
  for (const [type, delta, start_ms, end_ms] of [
    ['session.input_transcript.delta', 'Hel', 0, 100],
    ['session.output_transcript.delta', 'Hi', 100, 200],
    ['session.input_transcript.delta', 'lo', 100, 200],
    ['session.input_transcript.delta', 'Next question', 2000, 2200],
  ] as const)
    state = processEvent(state, { type, delta, start_ms, end_ms }).state;
  expect(state.messages.map(({ speaker, text }) => ({ speaker, text }))).toEqual([
    { speaker: 'user', text: 'Hello' },
    { speaker: 'assistant', text: 'Hi' },
    { speaker: 'user', text: 'Next question' },
  ]);
});

test('chat replaces finalized text and bounds retained content', () => {
  let state = processEvent(initialLiveState(), {
    type: 'response.output_audio_transcript.delta',
    item_id: 'one',
    delta: 'Par',
  }).state;
  state = processEvent(state, {
    type: 'response.output_audio_transcript.done',
    item_id: 'one',
    transcript: 'Partial answer.',
  }).state;
  expect(state.messages.map((message) => message.text)).toEqual(['Partial answer.']);
  for (let i = 0; i < 60; i++)
    state = processEvent(state, {
      type: 'conversation.item.input_audio_transcription.completed',
      item_id: String(i),
      transcript: 'x'.repeat(500),
    }).state;
  expect(state.messages.length).toBeLessThanOrEqual(40);
  expect(
    state.messages.reduce((total, message) => total + message.text.length, 0),
  ).toBeLessThanOrEqual(12000);
});

test('intent mode describes continuing work and allows cancelling another task', () => {
  const state = workerState(
    { ...initialLiveState(), active: true, intentCancellation: true, cancelPending: true },
    'running',
  );
  expect(state.workerMessage).toContain('continue while you speak');
  expect(state.cancelPending).toBe(false);
});

test('chat hides empty segments and groups consecutive speaker segments without mutating data', () => {
  const messages = [
    { id: 1, speaker: 'user' as const, text: ' Dimmi' },
    { id: 2, speaker: 'assistant' as const, text: ' ' },
    { id: 3, speaker: 'user' as const, text: ' come ' },
    { id: 4, speaker: 'user' as const, text: 'funziona' },
    { id: 5, speaker: 'assistant' as const, text: 'Certo.' },
    { id: 6, speaker: 'user' as const, text: 'Grazie.' },
  ];
  expect(chatBubbles(messages)).toEqual([
    { id: 1, speaker: 'user', text: 'Dimmi come funziona' },
    { id: 5, speaker: 'assistant', text: 'Certo.' },
    { id: 6, speaker: 'user', text: 'Grazie.' },
  ]);
  expect(messages[0]?.text).toBe(' Dimmi');
});

test('ending keeps last reported tasks and does not imply playback completion or readiness', () => {
  const state = {
    ...initialLiveState(),
    intentCancellation: true,
    tasks: [{ id: 'one', goal: 'Calculate', status: 'completed', elapsed_seconds: 3 }],
    cancelPending: true,
  };
  const ended = endedWorkerState(state);
  expect(ended.tasks).toBe(state.tasks);
  expect(ended.workerMessage).toContain('last reported');
  expect(ended.workerMessage).not.toContain('ready');
  expect(ended.cancelPending).toBe(false);
  expect(workerState(state, 'completed').workerMessage).toContain('full playback is not confirmed');
  expect(taskLabel('completed')).toBe('Result sent to voice provider');
  expect(taskLabel('pending')).toBe('Waiting for silence');
});

test('recap never implies the latest assistant excerpt answers the latest request', () => {
  expect(
    recapText({
      latest_request: 'Stop that topic',
      latest_reply: 'Earlier answer',
      interrupted: false,
    }),
  ).toBe(
    'Latest request: Stop that topic · Latest assistant transcript (may precede this request): Earlier answer',
  );
  expect(recapText({ latest_request: '', latest_reply: '', interrupted: true })).toBe(
    'Interrupted task. Latest request: —',
  );
});
