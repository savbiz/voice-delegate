/** React shell separating a free scripted demo from the live WebRTC lifecycle. */
import { useEffect, useRef, useState, useSyncExternalStore } from 'react';
import { createLiveSession } from './realtime/live';
import type { LiveController } from './realtime/live';
import { createLiveStore } from './realtime/store';
import { runStackDemo, scenario, visibleScenario } from './demo';
import { Reference } from './reference';
import { Transcript } from './Transcript';
import { version } from '../package.json';
import { readInvitation, saveInvitation } from './invitation';

function Live({ code }: { code: string }) {
  const [store] = useState(createLiveStore);
  const storeRef = useRef(store);
  const state = useSyncExternalStore(store.subscribe, store.getSnapshot);
  const audio = useRef<HTMLAudioElement>(null);
  const controller = useRef<LiveController | null>(null);
  const codeRef = useRef(code);
  codeRef.current = code;
  const [language, setLanguage] = useState('auto');
  const [voiceMode, setVoiceMode] = useState('conversation');
  const [debugRecording, setDebugRecording] = useState(false);
  const [audioRecording, setAudioRecording] = useState(false);
  const recordingRef = useRef(audioRecording);
  recordingRef.current = audioRecording;
  const preferences = useRef({ language, mode: voiceMode, debug_recording: debugRecording });
  preferences.current = { language, mode: voiceMode, debug_recording: debugRecording };
  const [muted, setMuted] = useState(false);
  const [largeCaptions, setLargeCaptions] = useState(false);
  const [category, setCategory] = useState('wrong_answer');
  useEffect(() => {
    if (!audio.current) return;
    const session = createLiveSession(
      storeRef.current,
      audio.current,
      () => codeRef.current,
      () => preferences.current,
      () => recordingRef.current,
    );
    controller.current = session;
    return () => {
      session.dispose();
      controller.current = null;
    };
  }, []);
  useEffect(() => {
    if (state.phase === 'ended') {
      setDebugRecording(false);
      setAudioRecording(false);
    }
  }, [state.phase]);
  return (
    <div className={largeCaptions ? 'large-captions' : undefined}>
      <p className="notice">
        Live voice requires a server API key and incurs provider usage charges. Your microphone is
        requested only when you start.
      </p>
      <div className="session-controls">
        <p id="status" role="status">
          {state.status}
        </p>
        <p id="task-status" className="muted" aria-live="polite">
          {state.workerMessage}
        </p>
        {state.worker === 'running' && (
          <button
            id="cancel-task"
            disabled={
              state.worker !== 'running' ||
              !state.active ||
              state.ending ||
              state.recovering ||
              state.cancelPending
            }
            onClick={() => controller.current?.cancel()}
          >
            Cancel task
          </button>
        )}
        <p id="recovery-help">{state.help}</p>
        <div className="actions">
          <button
            id="start"
            disabled={state.active || state.ending || state.recovering}
            onClick={() => controller.current?.start()}
          >
            Start conversation
          </button>
          <button
            id="stop"
            disabled={!state.active || state.ending}
            onClick={() => controller.current?.stop()}
          >
            Stop
          </button>
        </div>
        <div className="actions">
          <button id="mute-audio" aria-pressed={muted} onClick={() => setMuted((value) => !value)}>
            {muted ? 'Unmute assistant' : 'Mute assistant'}
          </button>
          <button
            id="large-captions"
            aria-pressed={largeCaptions}
            onClick={() => setLargeCaptions((value) => !value)}
          >
            Large captions
          </button>
        </div>
        {state.active && state.audioBlocked && (
          <button
            onClick={() => {
              void audio.current
                ?.play()
                .then(() => {
                  if (store.getSnapshot().active)
                    store.update({ audioBlocked: false, status: 'Connected. Speak naturally.' });
                })
                .catch(() => {});
            }}
          >
            Enable audio
          </button>
        )}
      </div>
      <details className="secondary-panel settings-panel">
        <summary>Voice settings &amp; recording</summary>
        <fieldset id="voice-preferences" disabled={state.active}>
          <legend>Voice preferences (before starting)</legend>
          <label>
            Response language{' '}
            <select id="language" value={language} onChange={(e) => setLanguage(e.target.value)}>
              <option value="auto">Follow the speaker</option>
              <option value="it">Italiano</option>
              <option value="en">English</option>
              <option value="es">Español</option>
              <option value="fr">Français</option>
              <option value="de">Deutsch</option>
            </select>
          </label>
          <label>
            Conversation style{' '}
            <select
              id="voice-mode"
              value={voiceMode}
              onChange={(e) => setVoiceMode(e.target.value)}
            >
              <option value="conversation">Assistant conversation</option>
              <option value="translate">Translation mode</option>
            </select>
          </label>
          <label>
            <input
              type="checkbox"
              checked={debugRecording}
              onChange={(event) => setDebugRecording(event.target.checked)}
            />
            Record this session for server debugging. I consent to saving transcripts, bounded
            worker results, session events and selected audio connection statistics on this backend
            for up to 24 hours while it is running. No audio recording, request credentials or
            network addresses. Requires server debug mode. The service operator can read these
            recordings.
          </label>
          <label>
            <input
              type="checkbox"
              checked={audioRecording}
              onChange={(event) => setAudioRecording(event.target.checked)}
            />
            Record audio locally. I consent to recording my microphone and the assistant for this
            session (up to five minutes or approximately 20 MiB). The recording is not uploaded;
            live audio still goes to the voice provider. Download it before reloading, leaving Live
            voice or starting another recording.
          </label>
        </fieldset>
      </details>
      {state.debugStatus && <p aria-live="polite">{state.debugStatus}</p>}
      {state.audioStatus && <p aria-live="polite">{state.audioStatus}</p>}
      {state.audioUrl && (
        <a className="download-button" href={state.audioUrl} download={state.audioFilename}>
          Download session audio
        </a>
      )}
      <audio id="audio" ref={audio} muted={muted} autoPlay hidden />
      <Transcript messages={state.messages} />
      {state.sources.length > 0 && (
        <section aria-label="Worker sources">
          <h2>Documentation sources</h2>
          <div id="sources">
            {state.sources.map((source, index) => (
              <details key={source.id}>
                <summary>
                  [{index + 1}] {source.title} — {source.section}
                </summary>
                <blockquote>{source.text}</blockquote>
                <small>
                  {source.path} · Snapshot {source.id}
                </small>
              </details>
            ))}
          </div>
        </section>
      )}
      <details className="secondary-panel">
        <summary>Conversation recap</summary>
        <p className="muted">
          Live transcript excerpts, refreshed every 10 seconds; not an AI summary. Interruption does
          not mean completion.
        </p>
        <p id="recap" aria-live="off">
          {state.recap}
        </p>
      </details>
      <details className="secondary-panel">
        <summary>Connection timings</summary>
        <p>{state.audioTimingStatus}</p>
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
      <details className="secondary-panel">
        <summary>Report a problem</summary>
        <p>
          Send only a category, diagnostic ID, interface state, configured provider and app version.
          No audio, transcripts or message text. Reports expire after seven days. A pseudonymous
          identity is used to limit submissions.
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
        <button
          id="send-feedback"
          disabled={!code || state.reportPending || state.reportSent}
          onClick={() => {
            void controller.current?.feedback(category);
          }}
        >
          Send report
        </button>
        <p id="feedback-status" aria-live="polite">
          {state.feedbackStatus}
        </p>
      </details>
    </div>
  );
}
function StackDemo() {
  const [staticDemo, setStaticDemo] = useState(false);
  const [result, setResult] = useState('Ready to run 2 + 2 through the offline worker.');
  const [busy, setBusy] = useState(false);
  const pending = useRef<AbortController | undefined>(undefined);
  useEffect(() => () => pending.current?.abort(), []);
  if (staticDemo) return <StaticDemo />;
  return (
    <>
      <p className="notice">
        Offline stack · Fake voice provider, real backend and LangGraph worker. No microphone,
        generated audio or paid calls.
      </p>
      <div className="actions">
        <button
          disabled={busy}
          onClick={() => {
            const controller = new AbortController();
            pending.current = controller;
            setBusy(true);
            setResult('Delegating 2 + 2 to the worker…');
            void runStackDemo(controller.signal)
              .then((text) => {
                if (!controller.signal.aborted) setResult(`Worker result: ${text}`);
              })
              .catch((error: unknown) => {
                if (!controller.signal.aborted)
                  setResult(error instanceof Error ? error.message : 'Offline stack unavailable.');
              })
              .finally(() => {
                if (pending.current === controller) setBusy(false);
              });
          }}
        >
          Run offline worker
        </button>
        <button
          disabled={!busy}
          onClick={() => {
            pending.current?.abort();
            setResult('Demo stopped.');
          }}
        >
          Stop demo
        </button>
      </div>
      <p role="status">{result}</p>
      <button disabled={busy} onClick={() => setStaticDemo(true)}>
        Use static demo instead
      </button>
      <p>
        Open Grafana on port 3000 to inspect backend metrics. No audio latency is measured in this
        demo.
      </p>
    </>
  );
}

function StaticDemo() {
  const [step, setStep] = useState(0);
  const [running, setRunning] = useState(false);
  useEffect(() => {
    if (!running) return;
    const timer = setInterval(
      () => setStep((previous) => Math.min(previous + 1, scenario.length)),
      900,
    );
    return () => clearInterval(timer);
  }, [running]);
  useEffect(() => {
    if (step === scenario.length) setRunning(false);
  }, [step]);
  return (
    <>
      <p className="notice">
        Simulated demo · No API key, network requests, microphone or generated audio. Timing values
        are illustrative.
      </p>
      <div className="actions">
        <button
          disabled={running}
          onClick={() => {
            setStep(0);
            setRunning(true);
          }}
        >
          Start demo
        </button>
        <button disabled={!running} onClick={() => setRunning(false)}>
          Stop demo
        </button>
      </div>
      <p role="status">
        {running
          ? 'Playing recorded scenario…'
          : step
            ? 'Demo stopped'
            : 'Ready — try the free demo'}
      </p>
      <div aria-live="polite" className="space-y-3">
        {visibleScenario(step).map((turn, i) => (
          <section key={i}>
            <h2>{turn.speaker}</h2>
            <p>{turn.text}</p>
            {turn.gap !== null && <span className="badge">{turn.gap} ms · simulated</span>}
          </section>
        ))}
      </div>
    </>
  );
}
export default function App() {
  const [mode, setMode] = useState<'demo' | 'live' | 'reference'>('demo');
  const [code, setCode] = useState(readInvitation);
  useEffect(() => {
    saveInvitation(code);
  }, [code]);
  return (
    <main className="mx-auto max-w-4xl px-6 py-12">
      <header className="mb-10">
        <span className="badge">OPEN REFERENCE · {version}</span>
        <h1 className="mt-5 text-5xl font-semibold tracking-tight">
          voice-delegate<span className="text-emerald-400">.</span>
        </h1>
        <p className="mt-4 text-lg text-slate-400">
          A fast voice conversation. A separate worker for the heavy lifting.
        </p>
      </header>
      <nav className="actions" role="tablist" aria-label="Conversation mode">
        {(['demo', 'live', 'reference'] as const).map((tab, index, tabs) => (
          <button
            key={tab}
            role="tab"
            id={`tab-${tab}`}
            aria-controls="mode-panel"
            aria-selected={mode === tab}
            tabIndex={mode === tab ? 0 : -1}
            onClick={() => setMode(tab)}
            onKeyDown={(event) => {
              const next =
                event.key === 'ArrowRight'
                  ? tabs[(index + 1) % tabs.length]
                  : event.key === 'ArrowLeft'
                    ? tabs[(index + tabs.length - 1) % tabs.length]
                    : event.key === 'Home'
                      ? tabs[0]
                      : event.key === 'End'
                        ? tabs.at(-1)
                        : undefined;
              if (next) {
                event.preventDefault();
                setMode(next);
                document.getElementById(`tab-${next}`)?.focus();
              }
            }}
          >
            {tab === 'demo' ? 'Free demo' : tab === 'live' ? 'Live voice' : 'Documentation'}
          </button>
        ))}
      </nav>
      <div id="mode-panel" role="tabpanel" aria-labelledby={`tab-${mode}`}>
        {mode !== 'demo' && (
          <label className="block my-5">
            Personal invitation code{' '}
            <input
              type="password"
              autoComplete="off"
              value={code}
              onChange={(e) => setCode(e.target.value)}
              placeholder="Only if configured on the server"
            />
          </label>
        )}
        {mode === 'demo' ? (
          import.meta.env.VITE_OFFLINE_STACK === 'true' ? (
            <StackDemo />
          ) : (
            <StaticDemo />
          )
        ) : mode === 'reference' ? (
          <Reference code={code} />
        ) : (
          <Live code={code} />
        )}
      </div>
      <footer className="mt-12 border-t border-slate-800 pt-6 text-sm text-slate-400">
        React 19 · FastAPI · WebRTC
        <br />
        Bounded delegation · Azure recovery · Optional telemetry.
        <br />
        <a href="/third-party-notices.txt" className="underline">
          Third-party notices
        </a>
      </footer>
    </main>
  );
}
