import { ApiAccess, type ApiSource, type PersonalKeys } from './ApiAccess';
import { isNativeClient } from '../native';
import { CostPanel, ProviderChoice, SpeakingStatus } from './SessionPanels';
import { type Adapter, type VoiceOptions } from '../realtime/provider-options';
import { wakeVoiceOptions, type WakeState } from '../realtime/wake';
import { useEffect, useRef, useState, useSyncExternalStore } from 'react';
import { canStartVoice } from '../native';
import { Button } from './Button';
import { createLiveSession } from '../realtime/live';
import type { LiveController } from '../realtime/live';
import { createLiveStore, taskLabel } from '../realtime/store';
import { Transcript } from '../Transcript';
import { FeedbackPanel, RecapPanel, SourcesPanel, TimingsPanel } from './LivePanels';

/** The live voice workspace: provider choice, session controls and session panels. */
export function LiveWorkspace({ code, onCode }: { code: string; onCode: (code: string) => void }) {
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
  const [wake, setWake] = useState<WakeState>('ready');
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
    void wakeVoiceOptions(abort.signal, apiSource, isNativeClient(), (value) => {
      if (!abort.signal.aborted) setWake(value);
    }).then((value) => {
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
        requestAccess={options?.access_request_available === true}
        requestAccessEmail={options?.access_request_email === true}
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
          {wake === 'waking' && !state.active
            ? 'Starting the server… this can take up to 30 seconds after a quiet period.'
            : wake === 'unavailable' && !state.active
              ? 'The server did not respond. Reload the page to try again.'
              : noProvider && !state.active
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
            disabled={
              state.active ||
              state.ending ||
              state.recovering ||
              noProvider ||
              missingKeys ||
              wake === 'waking'
            }
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
      <SourcesPanel sources={state.sources} />
      <RecapPanel recap={state.recap} summary={state.summary} />
      <TimingsPanel state={state} />
      <FeedbackPanel
        state={state}
        personal={apiSource === 'personal'}
        code={code}
        onSend={(category, note) => void controller.current?.feedback(category, note)}
      />
    </div>
  );
}
