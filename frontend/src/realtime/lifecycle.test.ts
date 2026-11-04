import { describe, expect, it } from 'vitest';
import { canStart, initialLifecycle, transition, type LifecycleEvent } from './lifecycle';

const run = (...events: LifecycleEvent[]) => events.reduce(transition, initialLifecycle);

describe('live session lifecycle', () => {
  it('numbers every attempt and resets the fallback on a fresh start', () => {
    const recovered = run(
      { type: 'begin', fresh: true },
      { type: 'recover' },
      { type: 'fallback' },
    );
    expect(recovered).toEqual({ mode: 'idle', attempt: 2, fallbackAttempted: true });
    expect(transition(recovered, { type: 'begin', fresh: false }).fallbackAttempted).toBe(true);
    expect(transition(recovered, { type: 'begin', fresh: true })).toEqual({
      mode: 'idle',
      attempt: 3,
      fallbackAttempted: false,
    });
  });

  it('finishes once and blocks starts until the close settles', () => {
    const ending = run({ type: 'begin', fresh: true }, { type: 'finish' });
    expect(ending).toMatchObject({ mode: 'ending', attempt: 2 });
    expect(canStart(ending)).toBe(false);
    expect(transition(ending, { type: 'finish' })).toBe(ending);
    expect(transition(ending, { type: 'recover' })).toBe(ending);
    expect(canStart(transition(ending, { type: 'finished' }))).toBe(true);
  });

  it('lets a failed recovery finish without the recovery end clobbering it', () => {
    const state = run(
      { type: 'begin', fresh: true },
      { type: 'recover' },
      { type: 'finish' },
      { type: 'recovered' },
    );
    expect(state.mode).toBe('ending');
  });

  it('ignores a second recovery and fallback outside recovery', () => {
    const recovering = run({ type: 'begin', fresh: true }, { type: 'recover' });
    expect(canStart(recovering)).toBe(false);
    expect(transition(recovering, { type: 'recover' })).toBe(recovering);
    const idle = run({ type: 'begin', fresh: true });
    expect(transition(idle, { type: 'fallback' })).toBe(idle);
    expect(transition(idle, { type: 'finished' })).toBe(idle);
  });

  it('retires an attempt without changing mode', () => {
    expect(run({ type: 'begin', fresh: true }, { type: 'retire' })).toEqual({
      mode: 'idle',
      attempt: 2,
      fallbackAttempted: false,
    });
  });
});
