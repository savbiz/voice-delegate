import { useState } from 'react';
import type { Source } from '../reference';
import type { LiveState } from '../realtime/store';
import { sourceUrl } from '../source-url';
import { Button } from './Button';

/** Secondary panels below the live transcript; each renders one slice of session state. */

export function SourcesPanel({ sources }: { sources: Source[] }) {
  if (!sources.length) return null;
  return (
    <section aria-label="Worker sources">
      <h2>
        {sources.some((source) => source.section === 'Web search')
          ? 'Sources'
          : 'Documentation sources'}
      </h2>
      <div id="sources">
        {sources.map((source, index) => (
          <details key={source.id}>
            <summary>
              [{index + 1}] {source.title} — {source.section}
            </summary>
            <blockquote>{source.text}</blockquote>
            <small>
              {sourceUrl(source) ? (
                <a href={sourceUrl(source)} target="_blank" rel="noopener noreferrer">
                  {source.path}
                </a>
              ) : (
                source.path
              )}
              {' · '}
              {source.section === 'Web search' ? 'Evidence' : 'Snapshot'} {source.id}
            </small>
          </details>
        ))}
      </div>
    </section>
  );
}

export function RecapPanel({ recap }: { recap: string }) {
  return (
    <details className="secondary-panel">
      <summary>Conversation recap</summary>
      <p className="muted">
        Latest request and reply from the transcript. Interrupted work may still be incomplete.
      </p>
      <p id="recap" aria-live="off">
        {recap}
      </p>
    </details>
  );
}

export function TimingsPanel({ state }: { state: LiveState }) {
  return (
    <details className="secondary-panel">
      <summary>Connection timings</summary>
      <p>{state.audioTimingStatus}</p>
      {state.intentCancellation && (
        <p>
          Estimated Decisions input cost: ${state.decisionCostUsd.toFixed(6)} (configured rate;
          excludes failed requests and pricing adjustments).
        </p>
      )}
      <ol aria-label="Audio playback measurements">
        {state.audioTimings.map((sample, index) => (
          <li key={index}>
            {sample.kind === 'setup' ? 'Offer to first audio' : 'Speech end to audio'}:{' '}
            {Math.round(sample.milliseconds)} ms (browser playback)
          </li>
        ))}
      </ol>
      <p className="muted">
        Transcript timestamp gap: a proxy, not measured audio latency. May be negative during
        overlap.
      </p>
      <ol id="timings">
        {state.timings.map((turn) => (
          <li key={turn.id}>
            Turn {turn.id}:{' '}
            {turn.reply === undefined
              ? 'waiting for assistant transcript'
              : `${Math.round(turn.reply - turn.end)} ms ${turn.estimated ? 'client-side estimate' : 'transcript gap'}`}
          </li>
        ))}
      </ol>
    </details>
  );
}

export function FeedbackPanel({
  state,
  personal,
  code,
  onSend,
}: {
  state: LiveState;
  personal: boolean;
  code: string;
  onSend: (category: string) => void;
}) {
  const [category, setCategory] = useState('wrong_answer');
  return (
    <details className="secondary-panel">
      <summary>Report a problem</summary>
      <p>
        Reports include a category and app diagnostics, without audio or conversation text. They are
        kept for seven days.
      </p>
      <label>
        Problem category{' '}
        <select
          id="feedback-category"
          value={category}
          onChange={(e) => setCategory(e.target.value)}
          disabled={state.reportLocked}
        >
          <option value="wrong_answer">Wrong answer</option>
          <option value="source">Unhelpful source</option>
          <option value="audio">Audio problem</option>
          <option value="connection">Connection problem</option>
          <option value="other">Other problem</option>
        </select>
      </label>
      <Button
        id="send-feedback"
        disabled={personal || !code || state.reportPending || state.reportSent}
        onClick={() => {
          onSend(category);
        }}
      >
        Send report
      </Button>
      <p id="feedback-status" aria-live="polite">
        {personal
          ? 'Reporting is available in Platform API mode with an invitation code.'
          : !code
            ? 'Enter your invitation code to send a report.'
            : state.feedbackStatus}
      </p>
    </details>
  );
}
