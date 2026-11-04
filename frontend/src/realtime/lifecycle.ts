/**
 * Explicit controller lifecycle for a live voice session.
 *
 * `mode` says which user and transport actions are allowed; `attempt` identifies the current
 * transport attempt so callbacks from a replaced or closed attempt can ignore themselves.
 *
 *   idle ──finish──▶ ending ──finished──▶ idle
 *   idle ──recover─▶ recovering ──fallback / recovered──▶ idle
 *                    recovering ──finish──▶ ending
 */
export type LifecycleMode = 'idle' | 'ending' | 'recovering';

export type Lifecycle = Readonly<{
  mode: LifecycleMode;
  attempt: number;
  fallbackAttempted: boolean;
}>;

export type LifecycleEvent =
  /** A new transport attempt; `fresh` is a user start, otherwise the fallback reconnect. */
  | { type: 'begin'; fresh: boolean }
  /** Invalidate callbacks of the current attempt without changing mode. */
  | { type: 'retire' }
  /** Start closing; ignored while already ending. */
  | { type: 'finish' }
  /** The close request settled. */
  | { type: 'finished' }
  /** Ask the server whether the single fallback is still available. */
  | { type: 'recover' }
  /** The fallback was granted: consume it and retire the failed attempt. */
  | { type: 'fallback' }
  /** Recovery ended without a fallback reconnect of its own. */
  | { type: 'recovered' };

export const initialLifecycle: Lifecycle = { mode: 'idle', attempt: 0, fallbackAttempted: false };

export function transition(state: Lifecycle, event: LifecycleEvent): Lifecycle {
  switch (event.type) {
    case 'begin':
      return {
        ...state,
        attempt: state.attempt + 1,
        fallbackAttempted: event.fresh ? false : state.fallbackAttempted,
      };
    case 'retire':
      return { ...state, attempt: state.attempt + 1 };
    case 'finish':
      return state.mode === 'ending'
        ? state
        : { ...state, mode: 'ending', attempt: state.attempt + 1 };
    case 'finished':
      return state.mode === 'ending' ? { ...state, mode: 'idle' } : state;
    case 'recover':
      return state.mode === 'idle' ? { ...state, mode: 'recovering' } : state;
    case 'fallback':
      return state.mode === 'recovering'
        ? { mode: 'idle', attempt: state.attempt + 1, fallbackAttempted: true }
        : state;
    case 'recovered':
      return state.mode === 'recovering' ? { ...state, mode: 'idle' } : state;
  }
}

/** A user may start only when nothing is closing or recovering. */
export const canStart = (state: Lifecycle): boolean => state.mode === 'idle';
