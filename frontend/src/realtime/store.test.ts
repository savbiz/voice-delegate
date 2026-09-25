import { expect, test, vi } from 'vitest';
import { createLiveStore, initialLiveState, processEvent, updateTurnTiming } from './store';

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
