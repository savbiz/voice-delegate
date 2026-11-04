import fc from 'fast-check';
import { describe, expect, it } from 'vitest';
import { canStart, initialLifecycle, transition, type LifecycleEvent } from './realtime/lifecycle';
import { sourceUrl } from './source-url';
import type { Source } from './reference';

const events = fc.oneof(
  fc.record({ type: fc.constant('begin' as const), fresh: fc.boolean() }),
  ...(['retire', 'finish', 'finished', 'recover', 'fallback', 'recovered'] as const).map((type) =>
    fc.constant({ type } as LifecycleEvent),
  ),
);

describe('lifecycle state machine (generated event sequences)', () => {
  it('only ever moves the attempt counter forward', () => {
    fc.assert(
      fc.property(fc.array(events), (sequence) => {
        let state = initialLifecycle;
        for (const event of sequence) {
          const next = transition(state, event);
          expect(next.attempt).toBeGreaterThanOrEqual(state.attempt);
          state = next;
        }
      }),
    );
  });

  it('never leaves a closing or recovering session startable', () => {
    fc.assert(
      fc.property(fc.array(events), (sequence) => {
        const state = sequence.reduce(transition, initialLifecycle);
        expect(canStart(state)).toBe(state.mode === 'idle');
      }),
    );
  });

  it('consumes the single fallback only through a granted fallback', () => {
    fc.assert(
      fc.property(fc.array(events), (sequence) => {
        let state = initialLifecycle;
        for (const event of sequence) {
          const next = transition(state, event);
          if (next.fallbackAttempted && !state.fallbackAttempted) {
            expect(event.type).toBe('fallback');
            expect(state.mode).toBe('recovering');
          }
          state = next;
        }
      }),
    );
  });

  it('ignores a repeated finish', () => {
    fc.assert(
      fc.property(fc.array(events), (sequence) => {
        const once = transition(sequence.reduce(transition, initialLifecycle), { type: 'finish' });
        expect(transition(once, { type: 'finish' })).toEqual(once);
      }),
    );
  });
});

describe('evidence links (generated URLs)', () => {
  const web = (path: string): Source => ({
    id: 'web-x',
    title: 'Notice',
    path,
    section: 'Web search',
    text: 'A public update.',
    digest: 'test',
  });

  it('returns only credential-free HTTPS links', () => {
    fc.assert(
      fc.property(
        fc.webUrl({ validSchemes: ['http', 'https', 'ftp'], withFragments: true }),
        (url) => {
          const link = sourceUrl(web(url));
          if (link !== undefined) {
            const parsed = new URL(link);
            expect(parsed.protocol).toBe('https:');
            expect(parsed.username + parsed.password).toBe('');
          }
        },
      ),
    );
  });

  it('never throws on arbitrary text', () => {
    fc.assert(fc.property(fc.string(), (text) => void sourceUrl(web(text))));
  });

  it('rejects every non-HTTPS scheme', () => {
    fc.assert(
      fc.property(
        fc.constantFrom('http', 'ftp', 'javascript', 'data', 'file'),
        fc.string(),
        (scheme, rest) => {
          expect(sourceUrl(web(`${scheme}:${rest}`))).toBeUndefined();
        },
      ),
    );
  });
});
