import { ApiAccess, type ApiSource, type PersonalKeys } from './components/ApiAccess';
import { isNativeClient } from './native';
import { CostPanel, ProviderChoice, SpeakingStatus } from './components/SessionPanels';
import { voiceOptions, type Adapter, type VoiceOptions } from './realtime/provider-options';
/** React shell separating a free scripted demo from the live WebRTC lifecycle. */
import { useEffect, useRef, useState, useSyncExternalStore } from 'react';
import { canStartVoice } from './native';
import { Button } from './components/Button';
import { WorkspaceNavigation } from './components/WorkspaceNavigation';
import type { Mode } from './components/WorkspaceNavigation';
import { createLiveSession } from './realtime/live';
import type { LiveController } from './realtime/live';
import { createLiveStore, taskLabel } from './realtime/store';
import { runStackDemo, scenario, visibleScenario } from './demo';
import { Reference } from './reference';
import { Transcript } from './Transcript';
import { version } from '../package.json';
import { readInvitation, saveInvitation } from './invitation';
import { sourceUrl } from './source-url';

function Live({ code, onCode }: { code: string; onCode: (code: string) => void }) {
  const [apiSource, setApiSource] = useState<ApiSource>('platform');
  const [keys, setKeys] = useState<PersonalKeys>({});
  const keysRef = useRef(keys);
  keysRef.current = keys;
  const apiSourceRef = useRef(apiSource);
  apiSourceRef.current = apiSource;
  const [store] = useState(createLiveStore);
  const storeRef = useRef(store);
  const state = useSyncExternalStore(store.subscribe, store.getSnapshot);
  const audio = useRef<HTMLAudioElement>(null);
  const controller = useRef<LiveController | null>(null);
  const codeRef = useRef(code);
  codeRef.current = code;
  const [options, setOptions] = useState<VoiceOptions>();
  const [adapter, setAdapter] = useState<Adapter>();
  const selectedAdapter = adapter ?? options?.adapter;
  const sdkSelected = selectedAdapter === 'elevenlabs';
  const noProvider = options !== undefined && options.available_adapters.length === 0;
  const missingKeys =
    apiSource === 'personal'
      ? sdkSelected
        ? !(
            keys.elevenlabs_key?.trim() &&
            keys.elevenlabs_agent_id?.trim() &&
            keys.elevenlabs_webhook_token?.trim()
          )
        : selectedAdapter === 'azure'
          ? !(keys.azure_key?.trim() && keys.azure_endpoint?.trim())
          : !keys.openai_key?.trim()
      : false;
  useEffect(() => {
    if (!canStartVoice()) return;
    const abort = new AbortController();
    void voiceOptions(abort.signal, apiSource, isNativeClient()).then((value) => {
      if (!abort.signal.aborted) setOptions(value);
    });
    return () => abort.abort();
  }, [apiSource]);
  const [language, setLanguage] = useState('auto');
  const [connectionSounds, setConnectionSounds] = useState(true);
  const soundsRef = useRef(connectionSounds);
  soundsRef.current = connectionSounds;
  const [voiceMode, setVoiceMode] = useState('conversation');
  const [debugRecording, setDebugRecording] = useState(false);
  const [azureRecovery, setAzureRecovery] = useState(false);
  const adapterRef = useRef(selectedAdapter);
  adapterRef.current = selectedAdapter;
  const recoveryRef = useRef(azureRecovery);
  recoveryRef.current = azureRecovery;
  const [audioRecording, setAudioRecording] = useState(false);
  const recordingRef = useRef(audioRecording);
  recordingRef.current = audioRecording;
  const preferences = useRef({
    language,
    mode: voiceMode,
    debug_recording: debugRecording,
    azure_recovery: azureRecovery,
    adapter: selectedAdapter,
  });
  preferences.current = {
    language,
    mode: voiceMode,
    debug_recording: debugRecording,
    azure_recovery: azureRecovery,
    adapter: selectedAdapter,
  };
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
      () => soundsRef.current,
      () => {
        if (apiSourceRef.current !== 'personal') return undefined;
        if (adapterRef.current === 'azure' || recoveryRef.current) return keysRef.current;
        // Retained Azure values from an earlier provider choice are not part of this session.
        const rest = { ...keysRef.current };
        delete rest.azure_key;
        delete rest.azure_endpoint;
        delete rest.azure_deployment;
        return rest;
      },
      () => setKeys({}),
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
      setAzureRecovery(false);
      setAudioRecording(false);
    }
  }, [state.phase]);
  return (
    <div className={largeCaptions ? 'large-captions' : undefined}>
      <ApiAccess
        source={apiSource}
        keys={keys}
        onKeys={setKeys}
        adapter={selectedAdapter}
        recovery={azureRecovery}
        onRecovery={(enabled) => {
          setAzureRecovery(enabled);
          if (!enabled && selectedAdapter === 'openai')
            setKeys({
              ...keys,
              azure_key: undefined,
              azure_endpoint: undefined,
              azure_deployment: undefined,
            });
        }}
        recoveryAvailable={apiSource === 'personal' || options?.azure_recovery_available === true}
        disabled={state.active || state.ending}
        code={code}
        webhookUrl={options?.elevenlabs_webhook_url}
        onCode={onCode}
        onSource={(source) => {
          setApiSource(source);
          setKeys({});
          setAdapter(undefined);
          setOptions(undefined);
          setLanguage('auto');
          setVoiceMode('conversation');
          setDebugRecording(false);
          setAzureRecovery(false);
          setAudioRecording(false);
        }}
      >
        {options && selectedAdapter && (
          <ProviderChoice
            options={options}
            source={apiSource}
            value={selectedAdapter}
            disabled={state.active || state.ending}
            onChange={(value) => {
              setAdapter(value);
              setAzureRecovery(false);
              setLanguage('auto');
              setVoiceMode('conversation');
              setAudioRecording(false);
            }}
          />
        )}
      </ApiAccess>
      {!canStartVoice() && (
        <p className="notice">
          Native preview: The offline example works without a connection. Live voice is disabled
          until explicitly enabled in a test build; native microphone and playback acceptance are
          pending.
        </p>
      )}
      <p className="notice">
        {apiSource === 'personal'
          ? 'Live voice uses your own provider accounts, which bill you directly.'
          : 'Live voice uses the platform’s provider accounts and counts against your allowance.'}{' '}
        Your microphone is requested only when you start.
      </p>
      {state.sessionUi && state.active && <SpeakingStatus activity={state.speaking} />}
      <div className="session-controls">
        <p id="status" role="status">
          {noProvider && !state.active
            ? 'Voice is unavailable: no provider is configured on this server.'
            : state.status}
        </p>
        <p id="task-status" className="muted" aria-live="polite">
          {state.workerMessage}
        </p>
        {missingKeys && !state.active && !state.ending && (
          <p id="start-hint" className="muted">
            {sdkSelected
              ? 'Enter your ElevenLabs API key, agent ID and webhook token to start.'
              : selectedAdapter === 'azure'
                ? 'Enter your Azure API key and resource origin to start.'
                : 'Enter your OpenAI API key to start.'}
          </p>
        )}
        {state.worker === 'running' && !state.intentCancellation && (
          <Button
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
          </Button>
        )}
        {state.intentCancellation && state.tasks.length > 0 && (
          <div>
            <p className="muted">
              {state.transport === 'elevenlabs'
                ? 'Result sent means prepared for the webhook response; provider narration and playback are not confirmed.'
                : 'Result sent means accepted by the voice provider, not fully played.'}{' '}
              Audio interrupted by speech is not automatically repeated.
            </p>
            <ul aria-label="Delegated tasks">
              {state.tasks.map((task) => (
                <li key={task.id}>
                  <strong>{task.goal.slice(0, 100)}</strong>{' '}
                  <small>
                    {task.id} · {taskLabel(task.status, state.transport)} ·{' '}
                    {task.elapsed_seconds.toFixed(1)} s total
                    {task.work_seconds !== undefined &&
                      task.delivery_wait_seconds !== undefined && (
                        <>
                          {' '}
                          · worker {task.work_seconds.toFixed(1)} s · delivery wait{' '}
                          {task.delivery_wait_seconds.toFixed(1)} s
                        </>
                      )}
                  </small>{' '}
                  {['running', 'pending', 'delivering'].includes(task.status) && (
                    <Button
                      disabled={!state.active || state.ending || state.recovering}
                      onClick={() => controller.current?.cancel(task.id)}
                    >
                      Cancel {task.id}
                    </Button>
                  )}
                </li>
              ))}
            </ul>
          </div>
        )}
        <p id="recovery-help">{state.help}</p>
        <div className="actions">
          <Button
            id="start"
            variant="primary"
            disabled={state.active || state.ending || state.recovering || noProvider || missingKeys}
            aria-describedby={missingKeys ? 'start-hint' : undefined}
            onClick={() => controller.current?.start()}
          >
            Start conversation
          </Button>
          <Button
            id="stop"
            variant="danger"
            disabled={!state.active || state.ending}
            onClick={() => controller.current?.stop()}
          >
            Stop
          </Button>
        </div>
        <div className="actions">
          <Button id="mute-audio" aria-pressed={muted} onClick={() => setMuted((value) => !value)}>
            {muted ? 'Unmute assistant' : 'Mute assistant'}
          </Button>
          <Button
            id="large-captions"
            aria-pressed={largeCaptions}
            onClick={() => setLargeCaptions((value) => !value)}
          >
            Large captions
          </Button>
        </div>
        {state.active && state.audioBlocked && (
          <Button
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
          </Button>
        )}
      </div>
      <details className="secondary-panel settings-panel">
        <summary>Voice settings &amp; recording</summary>
        {sdkSelected && (
          <p className="notice">
            This agent manages its own language and style. Mixed audio recording is unavailable for
            this transport.
          </p>
        )}
        <fieldset id="voice-preferences" disabled={state.active}>
          <legend>Voice preferences (before starting)</legend>
          <label>
            <input
              type="checkbox"
              checked={connectionSounds}
              onChange={(event) => setConnectionSounds(event.target.checked)}
            />
            Connection sounds
          </label>
          <label>
            Response language{' '}
            <select
              id="language"
              disabled={sdkSelected}
              value={language}
              onChange={(e) => setLanguage(e.target.value)}
            >
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
              disabled={sdkSelected}
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
            network addresses. The service operator can read these recordings.
          </label>
          <label>
            <input
              type="checkbox"
              disabled={sdkSelected}
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
      <CostPanel cost={state.costs} />
      <Transcript messages={state.messages} />
      {state.sources.length > 0 && (
        <section aria-label="Worker sources">
          <h2>
            {state.sources.some((source) => source.section === 'Web search')
              ? 'Sources'
              : 'Documentation sources'}
          </h2>
          <div id="sources">
            {state.sources.map((source, index) => (
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
      )}
      <details className="secondary-panel">
        <summary>Conversation recap</summary>
        <p className="muted">
          Latest request and reply from the transcript. Interrupted work may still be incomplete.
        </p>
        <p id="recap" aria-live="off">
          {state.recap}
        </p>
      </details>
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
      <details className="secondary-panel">
        <summary>Report a problem</summary>
        <p>
          Reports include a category and app diagnostics, without audio or conversation text. They
          are kept for seven days.
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
          disabled={apiSource === 'personal' || !code || state.reportPending || state.reportSent}
          onClick={() => {
            void controller.current?.feedback(category);
          }}
        >
          Send report
        </Button>
        <p id="feedback-status" aria-live="polite">
          {apiSource === 'personal'
            ? 'Reporting is available in Platform API mode with an invitation code.'
            : !code
              ? 'Enter your invitation code to send a report.'
              : state.feedbackStatus}
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
        <Button
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
        </Button>
        <Button
          disabled={!busy}
          onClick={() => {
            pending.current?.abort();
            setResult('Demo stopped.');
          }}
        >
          Stop demo
        </Button>
      </div>
      <p role="status">{result}</p>
      <Button disabled={busy} onClick={() => setStaticDemo(true)}>
        Use static demo instead
      </Button>
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
        <Button
          disabled={running}
          onClick={() => {
            setStep(0);
            setRunning(true);
          }}
        >
          Start demo
        </Button>
        <Button disabled={!running} onClick={() => setRunning(false)}>
          Stop demo
        </Button>
      </div>
      <p role="status">
        {running
          ? 'Playing recorded scenario…'
          : step
            ? 'Demo stopped'
            : 'Ready — play the offline example'}
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
function readMode(): Mode {
  const hash = window.location.hash.slice(1);
  if (hash === 'live' || hash === 'demo' || hash === 'reference') return hash;
  return import.meta.env.VITE_OFFLINE_STACK === 'true' || !canStartVoice() ? 'demo' : 'live';
}

export default function App() {
  const [mode, setMode] = useState<Mode>(readMode);
  useEffect(() => {
    const navigate = () => setMode(readMode());
    window.addEventListener('hashchange', navigate);
    return () => window.removeEventListener('hashchange', navigate);
  }, []);
  const [code, setCode] = useState(readInvitation);
  useEffect(() => {
    saveInvitation(code);
  }, [code]);
  return (
    <main className="app-shell">
      <header className="app-header">
        <span className="badge">OPEN REFERENCE · {version}</span>
        <h1 className="brand-title">
          voice-delegate<span className="brand-accent">.</span>
        </h1>
        <p className="app-pitch">
          A fast voice conversation. A separate worker for the heavy lifting.
        </p>
      </header>
      <WorkspaceNavigation mode={mode} />
      <div
        id="mode-panel"
        role="region"
        aria-label={
          mode === 'live'
            ? 'Voice conversation'
            : mode === 'demo'
              ? 'Offline example'
              : 'Project documentation'
        }
      >
        {mode === 'reference' && (
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
          <Live code={code} onCode={setCode} />
        )}
      </div>
      <footer className="app-footer">
        React 19 · FastAPI · WebRTC
        <br />
        Background tasks · Session costs · Opt-in Azure recovery.
        <br />
        <a href="/third-party-notices.txt" className="underline">
          Third-party notices
        </a>
      </footer>
    </main>
  );
}
