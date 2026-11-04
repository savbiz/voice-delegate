/** Own microphone, peer connection, captions, and explicitly approximate turn timing. */
import type { PersonalKeys } from '../components/ApiAccess';
import { cleanPersonalKeys, type Preferences } from './personal-keys';
import type { CostSummary } from './costs';
import { elevenSession } from './elevenlabs-live';
import { canStartVoice, isNativeClient } from '../native';
import { ConnectionSounds } from './connection-sounds';
import { AudioTimingMeter } from './audio-timing';
import type { Source } from '../reference';
import { ActivityReporter, watchSpeech } from './vad';
import type { TaskStatus } from './store';
import { audioSample } from './debug';
import { recordAudio } from './recording';
import type { AudioRecording } from './recording';
import type { DebugSample } from './debug';
import { shouldRecover } from './recovery';
import { createApi, type OwnedSession as Session } from './api';
import { canStart, initialLifecycle, transition, type LifecycleEvent } from './lifecycle';
import { endedWorkerState, processEvent, recapText, workerState } from './store';
import type { LiveStore, Phase } from './store';

export function createLiveSession(
  store: LiveStore,
  audio: HTMLAudioElement,
  getAccessCode: () => string,
  getPreferences: () => Preferences,
  getAudioConsent: () => boolean = () => false,
  getConnectionSounds: () => boolean = () => false,
  getPersonalKeys: () => PersonalKeys | undefined = () => undefined,
  clearPersonalKeys: () => void = () => undefined,
) {
  const sounds = new ConnectionSounds();
  let diagnosticId = crypto.randomUUID();
  let reportBody:
    | { diagnostic_id: string; category: string; state: string; adapter?: string; note?: string }
    | undefined;
  let reportSent = false;
  let reportPending = false;
  function showState(phase: Phase, status: string, help: string): void {
    store.update({ phase, status, help });
  }
  function showWorker(worker: string): void {
    store.update(workerState(store.getSnapshot(), worker));
  }
  const { request, requestOptions } = createApi(getAccessCode);
  let life = initialLifecycle;
  function send(event: LifecycleEvent): void {
    const previous = life.mode;
    life = transition(life, event);
    if (life.mode !== previous)
      store.update({ ending: life.mode === 'ending', recovering: life.mode === 'recovering' });
  }
  /** Read through a call so checks after an await are not narrowed by earlier guards. */
  const isEnding = () => life.mode === 'ending';
  let eleven: ReturnType<typeof elevenSession> | undefined;
  let recording: AudioRecording | undefined;
  let disposed = false;
  let audioUrl: string | undefined;
  let stopVad: (() => void) | undefined;
  let peer: RTCPeerConnection | undefined;
  let microphone: MediaStream | undefined;
  let channel: RTCDataChannel | undefined;
  let session: Session | undefined;
  let heartbeat: ReturnType<typeof setInterval> | undefined;
  let debugTimer: ReturnType<typeof setInterval> | undefined;
  let debugBusy = false;
  let startup: ReturnType<typeof setTimeout> | undefined;
  let heartbeatFailures = 0;

  function renderSources(items: Source[]): void {
    const next = items.slice(0, 3);
    const previous = store.getSnapshot().sources;
    if (
      next.length !== previous.length ||
      next.some((source, index) => source.id !== previous[index]?.id)
    ) {
      store.update({ sources: next });
    }
  }

  function release(preserveRecording = false): void {
    if (!preserveRecording) {
      recording?.stop();
      recording = undefined;
    }
    void eleven?.end();
    eleven = undefined;
    stopVad?.();
    stopVad = undefined;
    clearInterval(heartbeat);
    clearInterval(debugTimer);
    clearTimeout(startup);
    microphone?.getTracks().forEach((track) => track.stop());
    channel?.close();
    peer?.close();
    audio.srcObject = null;
    microphone = undefined;
    channel = undefined;
    peer = undefined;
    session = undefined;
    store.update({ active: false, audioBlocked: false, speaking: undefined });
  }

  async function recordDebug(owner: Session, sample: DebugSample): Promise<void> {
    if (!owner.debugRecording) return;
    try {
      const result = await request<{ recording: boolean }>(
        `/sessions/${owner.id}/debug`,
        owner,
        sample,
        2000,
      );
      if (!result.recording)
        store.update({ debugStatus: 'Debug recording stopped: file limit or storage error.' });
    } catch {
      store.update({ debugStatus: 'Some debug samples could not be saved.' });
    }
  }

  async function finish(message: string, userStopped = false): Promise<void> {
    if (life.mode === 'ending') return;
    send({ type: 'finish' });
    sounds.ended();
    const closedAttempt = life.attempt;
    const owner = session;
    const sdk = eleven;
    eleven = undefined;
    if (sdk) await sdk.end();
    release();
    showState(
      'ended',
      message,
      message === 'Conversation ended.'
        ? 'Select Start conversation when you want a new session.'
        : 'Check your connection or access code, then select Start conversation to begin a new session. Previous tasks will not be replayed.',
    );
    store.update(endedWorkerState(store.getSnapshot()));
    if (owner) {
      const close = () =>
        request<{ finalized: boolean; costs?: CostSummary; summary?: string | null }>(
          `/sessions/${owner.id}/close`,
          owner,
          undefined,
          // Allows an opt-in server-side summary (bounded to about 7 seconds) to finish.
          12000,
        );
      const closing =
        owner.debugRecording && userStopped
          ? recordDebug(owner, { event: 'client_stop' }).then(close)
          : close();
      void closing
        .then((result) => {
          if (closedAttempt === life.attempt)
            store.update({
              costs: result.costs,
              summary: typeof result.summary === 'string' ? result.summary.slice(0, 600) : '',
            });
          if (closedAttempt === life.attempt && !result.finalized)
            store.update({ status: message + ' Provider finalization unconfirmed.' });
        })
        .catch(() => {
          if (closedAttempt === life.attempt)
            store.update({
              status:
                message + ' Close was not confirmed; the server also enforces session expiry.',
            });
        })
        .finally(() => send({ type: 'finished' }));
    } else {
      send({ type: 'finished' });
    }
  }

  function receiveEvent(raw: unknown): void {
    const result = processEvent(store.getSnapshot(), raw, performance.now());
    store.update(result.state);
    if (result.effect === 'started') {
      clearTimeout(startup);
      sounds.established();
    }
    if (result.effect === 'closed' && !isEnding()) {
      sounds.ended();
      send({ type: 'retire' });
      release();
      showState(
        'ended',
        'Conversation ended. Provider finalization confirmed.',
        'Select Start conversation when you want a new session.',
      );
      store.update(endedWorkerState(store.getSnapshot()));
    }
  }

  async function gather(connection: RTCPeerConnection): Promise<void> {
    if (connection.iceGatheringState === 'complete') return;
    await new Promise<void>((resolve, reject) => {
      const timer = setTimeout(() => {
        cleanup();
        reject(
          new Error(
            'Microphone connection setup timed out (ICE). Check browser permissions, VPN or network, then retry.',
          ),
        );
      }, 10000);
      function cleanup(): void {
        clearTimeout(timer);
        connection.removeEventListener('icegatheringstatechange', changed);
      }
      function changed(): void {
        if (connection.iceGatheringState === 'complete') {
          cleanup();
          resolve();
        }
      }
      connection.addEventListener('icegatheringstatechange', changed);
      changed();
    });
  }

  const onCancelTask = (taskId?: string) => {
    const owner = session;
    store.update({ cancelPending: true });
    if (owner)
      void request(
        `/sessions/${owner.id}/interrupt`,
        owner,
        taskId ? { task_id: taskId } : undefined,
      )
        .then(() => {
          if (session === owner && !isEnding())
            store.update({
              workerMessage: 'Worker cancellation requested. You can give a new request.',
            });
        })
        .catch(() => {
          if (session === owner && !isEnding()) {
            store.update({
              workerMessage:
                'Cancellation not confirmed. Try Cancel task again or stop the conversation.',
              cancelPending: false,
            });
          }
        });
  };

  async function recover(message: string): Promise<void> {
    if (life.mode !== 'idle') return;
    const owner = session;
    if (!owner || !owner.azureRecovery || life.fallbackAttempted) {
      await finish(message);
      return;
    }
    send({ type: 'recover' });
    try {
      const state = await request<{ generation: number; fallback_available: boolean }>(
        `/sessions/${owner.id}/heartbeat`,
        owner,
        undefined,
        8000,
      );
      if (isEnding() || session !== owner) return;
      if (!state.fallback_available) {
        await finish(message);
        return;
      }
      send({ type: 'fallback' });
      release(true);
      session = owner;
      store.update({ active: true });
      showState(
        'recovering',
        'Reconnecting with Azure…',
        'Wait for connection confirmation, then repeat the unfinished phrase if needed.',
      );
      await begin(owner, state.generation);
    } catch {
      await finish('Fallback failed.');
    } finally {
      send({ type: 'recovered' });
    }
  }

  async function createOwned(preferences: Preferences, accessCode: string) {
    const entered = getPersonalKeys();
    // Validation errors keep the typed fields; they clear only once a request was attempted.
    const keys = entered ? cleanPersonalKeys(entered, preferences) : undefined;
    if (keys) {
      const key =
        preferences.adapter === 'elevenlabs'
          ? keys.elevenlabs_key
          : preferences.adapter === 'azure'
            ? keys.azure_key
            : keys.openai_key;
      if (!key) throw new Error('Enter your API key for the selected voice provider.');
    }
    try {
      return {
        ...(await request<{ id: string; key: string }>(
          keys ? '/personal/sessions' : '/sessions',
          undefined,
          keys ? { ...preferences, keys } : preferences,
          35000,
          keys ? '' : accessCode,
        )),
        accessCode: keys ? '' : accessCode,
        debugRecording: preferences.debug_recording,
        azureRecovery: preferences.azure_recovery === true,
      };
    } finally {
      if (keys) clearPersonalKeys();
    }
  }

  type VoiceConfig = {
    voice_available: boolean;
    transport?: string;
    session_ui?: boolean;
    audio_timing_available?: boolean;
    intent_cancellation?: boolean;
    debug_recording_available?: boolean;
  };

  /** Clear the previous conversation's panels before a user-started session. */
  function resetConversation(): void {
    store.update({ debugStatus: '' });
    store.update({
      speaking: undefined,
      captions: { user: '', assistant: '' },
      messages: [],
      audioBlocked: false,
      captionTails: {},
      lastSpeaker: undefined,
      timings: [],
      audioTimings: [],
      tasks: [],
      costs: undefined,
      decisionCostUsd: 0,
      sources: [],
      recap: 'No conversation yet.',
      summary: '',
    });
    if (!reportPending) {
      diagnosticId = crypto.randomUUID();
      reportBody = undefined;
      reportSent = false;
      store.update({
        reportSent: false,
        reportLocked: false,
        feedbackStatus: 'Ready to send a report if something goes wrong.',
      });
    }
  }

  /** ElevenLabs Agents: the SDK owns media; the backend owns the session and webhook. */
  async function startSdk(
    attempt: number,
    config: VoiceConfig,
    preferences: Preferences,
    accessCode: string,
    recovering: boolean,
    audioConsent: boolean,
  ): Promise<void> {
    if (recovering || isNativeClient())
      throw new Error('This SDK transport is supported in browsers only. Start a new session.');
    if (audioConsent)
      throw new Error(
        'Mixed audio recording is not available with this SDK transport. Uncheck audio recording to continue.',
      );
    if (preferences.mode !== 'conversation' || preferences.language !== 'auto')
      throw new Error(
        'This agent uses its server-configured language and conversation style. Select Follow the speaker and Assistant conversation.',
      );
    const created = await createOwned(preferences, accessCode);
    if (attempt !== life.attempt) {
      await request(`/sessions/${created.id}/close`, created);
      return;
    }
    session = created;
    if (created.debugRecording)
      store.update({ debugStatus: `Debug session file: ${created.id}.jsonl` });
    eleven = elevenSession(
      store,
      (path, body) =>
        request(
          `/sessions/${created.id}${path}`,
          created,
          body,
          path.endsWith('/bootstrap') ? 10000 : 5000,
        ),
      (message) => {
        if (attempt === life.attempt) void finish(message);
      },
      () => {
        if (attempt === life.attempt) sounds.established();
      },
      () => audio.muted,
      Boolean(config.audio_timing_available),
    );
    await eleven.start();
  }

  /** Opt-in local recording of the microphone and, once connected, the assistant. */
  function startLocalRecording(stream: MediaStream): void {
    if (audioUrl) URL.revokeObjectURL(audioUrl);
    audioUrl = undefined;
    store.update({ audioUrl: '', audioFilename: '' });
    try {
      recording = recordAudio(
        stream,
        (blob) => {
          if (disposed) return;
          audioUrl = URL.createObjectURL(blob);
          const extension = blob.type.includes('ogg')
            ? 'ogg'
            : blob.type.includes('mp4')
              ? 'm4a'
              : 'webm';
          store.update({ audioUrl, audioFilename: `voice-session-${Date.now()}.${extension}` });
        },
        (audioStatus) => {
          if (!disposed) store.update({ audioStatus });
        },
      );
    } catch {
      throw new Error(
        'Audio recording is unavailable in this browser. Uncheck recording or use a supported browser.',
      );
    }
  }

  /** Peer connection, remote audio and the provider event channel for one attempt. */
  function openPeer(attempt: number, stream: MediaStream): RTCPeerConnection {
    const connection = new RTCPeerConnection();
    peer = connection;
    stream.getTracks().forEach((track) => connection.addTrack(track, stream));
    connection.addEventListener('track', (event) => {
      if (attempt !== life.attempt) return;
      const remote = new MediaStream([event.track]);
      audio.srcObject = remote;
      recording?.assistant(remote);
      void audio.play().catch(() => {
        store.update({
          audioBlocked: true,
          status: 'Select Enable audio to hear the assistant.',
        });
      });
    });
    connection.addEventListener('connectionstatechange', () => {
      if (session && attempt === life.attempt)
        void recordDebug(session, {
          event: 'peer_state',
          peer_state: connection.connectionState,
        });
      if (
        attempt === life.attempt &&
        shouldRecover('connectionstatechange', connection.connectionState)
      ) {
        void recover('Media connection failed.');
      }
    });
    channel = connection.createDataChannel('oai-events');
    channel.addEventListener('message', (message: MessageEvent<unknown>) => {
      if (
        attempt !== life.attempt ||
        typeof message.data !== 'string' ||
        message.data.length > 65536
      )
        return;
      try {
        receiveEvent(JSON.parse(message.data));
      } catch {
        void finish('Invalid provider event.');
      }
    });
    channel.addEventListener('close', () => {
      if (session && attempt === life.attempt)
        void recordDebug(session, { event: 'channel_closed' });
      if (attempt === life.attempt && shouldRecover('data-channel-close'))
        void recover('Event connection closed.');
    });
    return connection;
  }

  /** Opt-in server debugging: a few bounded audio statistics every two seconds. */
  function startDebugSampling(
    attempt: number,
    connection: RTCPeerConnection,
    created: Session,
  ): void {
    store.update({ debugStatus: `Debug session file: ${created.id}.jsonl` });
    debugTimer = setInterval(() => {
      if (debugBusy || attempt !== life.attempt) return;
      debugBusy = true;
      void connection
        .getStats()
        .then(async (reports) => {
          const samples: DebugSample[] = [];
          reports.forEach((report: Record<string, unknown>) => {
            const sample = audioSample(report);
            if (sample && samples.length < 2) samples.push(sample);
          });
          for (const sample of samples) await recordDebug(created, sample);
        })
        .catch(() => undefined)
        .finally(() => {
          debugBusy = false;
        });
    }, 2000);
  }

  /**
   * Local audio analysis: onset interrupts, the speaking indicator, intent activity and
   * playback timing. Activity starts only once the provider answered the offer.
   */
  function watchAudio(
    attempt: number,
    stream: MediaStream,
    config: VoiceConfig,
    created: Session,
    serverGeneration: number,
  ) {
    let audioMeter: AudioTimingMeter | undefined;
    let timingBusy = false;
    let timingCount = 0;
    const activityReporter = new ActivityReporter();
    let activityBusy = false;
    // The server accepts activity only for a connected transport, i.e. after the offer.
    let activityEnabled = false;
    store.update({
      audioTimingStatus: config.audio_timing_available
        ? 'Waiting for audio playback.'
        : 'Audio measurement disabled.',
    });
    function uploadTimings(samples: { kind: string; milliseconds: number }[]): void {
      if (timingBusy) {
        store.update({ audioTimingStatus: 'Audio measured locally; metric upload busy.' });
        return;
      }
      timingBusy = true;
      void Promise.all(
        samples.map((sample) =>
          request(
            `/sessions/${created.id}/audio-timing`,
            created,
            {
              kind: sample.kind,
              seconds: sample.milliseconds / 1000,
              generation: serverGeneration,
            },
            2000,
          ),
        ),
      )
        .catch(() => {
          if (attempt === life.attempt)
            store.update({ audioTimingStatus: 'Audio measured locally; metric upload failed.' });
        })
        .finally(() => {
          timingBusy = false;
        });
    }
    try {
      stopVad = watchSpeech(
        stream,
        () => {
          if (
            attempt !== life.attempt ||
            config.intent_cancellation ||
            store.getSnapshot().worker !== 'running'
          )
            return;
          void recordDebug(created, { event: 'local_onset' });
          void request(`/sessions/${created.id}/interrupt`, created).catch(() => undefined);
        },
        audio,
        config.audio_timing_available || config.intent_cancellation || config.session_ui
          ? (now, local, remote, playing, remoteEnergy) => {
              if (attempt !== life.attempt) return;
              if (config.session_ui) {
                const next = { user: local > 0.035, assistant: remoteEnergy > 0.02 };
                const previous = store.getSnapshot().speaking;
                if (
                  !previous ||
                  previous.user !== next.user ||
                  previous.assistant !== next.assistant
                )
                  store.update({ speaking: next });
              }
              if (config.intent_cancellation && activityEnabled && !activityBusy) {
                const activity = activityReporter.sample(now, local, remoteEnergy);
                if (activity) {
                  activityBusy = true;
                  void request(
                    `/sessions/${created.id}/activity`,
                    created,
                    { ...activity, generation: serverGeneration },
                    1000,
                  )
                    .catch(() => undefined)
                    .finally(() => {
                      activityBusy = false;
                    });
                }
              }
              if (timingCount >= 120) return;
              const samples = audioMeter?.sample(now, local, remote, playing) ?? [];
              for (const sample of samples) {
                timingCount += 1;
                store.update({
                  audioTimings: [...store.getSnapshot().audioTimings, sample].slice(-40),
                  audioTimingStatus: 'Browser playback observations; not acoustic latency.',
                });
              }
              if (samples.length > 0) uploadTimings(samples);
            }
          : undefined,
      );
    } catch {
      store.update({ audioTimingStatus: 'Audio measurement unavailable in this browser.' });
      /* Provider-side speech detection remains authoritative without local analysis. */
    }
    return {
      startTiming: () => {
        if (config.audio_timing_available) audioMeter = new AudioTimingMeter(performance.now());
      },
      enableActivity: () => {
        activityEnabled = true;
      },
    };
  }

  /** Poll owned session state; end or recover when the server says so. */
  function startHeartbeat(attempt: number, created: Session, config: VoiceConfig): void {
    const heartbeatMs = config.intent_cancellation ? 2000 : 10000;
    let heartbeatPending = false;
    heartbeat = setInterval(() => {
      if (attempt !== life.attempt || heartbeatPending) return;
      heartbeatPending = true;
      void request<{
        delegation: string;
        tasks?: TaskStatus[];
        costs?: CostSummary;
        decision_cost_usd?: number;
        state: string;
        sources?: Source[];
        recap?: { latest_request: string; latest_reply: string; interrupted: boolean };
      }>(`/sessions/${created.id}/heartbeat`, created, undefined, 8000)
        .then((state) => {
          if (attempt === life.attempt) {
            heartbeatFailures = 0;
            store.update({
              tasks: state.tasks ?? [],
              costs: state.costs,
              decisionCostUsd: state.decision_cost_usd ?? 0,
            });
            renderSources(state.sources ?? []);
            if (state.recap) {
              store.update({ recap: recapText(state.recap) });
            }
            showWorker(state.delegation);
            if (state.state === 'closed' || state.state === 'closing')
              void finish('Conversation ended.');
            if (shouldRecover('heartbeat', state.state)) void recover('Provider connection lost.');
          }
        })
        .catch(() => {
          if (attempt === life.attempt && ++heartbeatFailures >= Math.ceil(30000 / heartbeatMs))
            void finish('Server connection lost or session expired.');
        })
        .finally(() => {
          heartbeatPending = false;
        });
    }, heartbeatMs);
  }

  /** Start a session, or with `existing` reconnect it once through the fallback provider. */
  async function begin(existing?: Session, serverGeneration = 0): Promise<void> {
    const requestedPreferences = { ...getPreferences() };
    const personal = getPersonalKeys() !== undefined;
    const audioConsent = !existing && getAudioConsent();
    if (!existing) resetConversation();
    const accessCode = existing?.accessCode ?? getAccessCode();
    send({ type: 'begin', fresh: !existing });
    const attempt = life.attempt;
    store.update({ timingTransportId: attempt });
    store.update({ active: true });
    showState(
      existing ? 'recovering' : 'connecting',
      existing ? 'Reconnecting with Azure…' : 'Requesting microphone…',
      'Allow microphone access to continue. Select Stop to cancel.',
    );
    showWorker('idle');
    heartbeatFailures = 0;
    try {
      const config = await request<VoiceConfig>(
        personal ? '/personal/config' : '/config',
        undefined,
        { adapter: requestedPreferences.adapter },
        35000,
        personal ? '' : accessCode,
      );
      if (attempt !== life.attempt) return;
      store.update({
        sessionUi: Boolean(config.session_ui),
        intentCancellation: Boolean(config.intent_cancellation),
        transport: config.transport === 'elevenlabs_agents_webrtc' ? 'elevenlabs' : 'webrtc',
      });
      if (requestedPreferences.debug_recording && !config.debug_recording_available)
        throw new Error(
          'Server debugging is disabled. Uncheck recording to continue, or ask the operator to enable it.',
        );
      if (!config.voice_available)
        throw new Error(
          'Set OPENAI_API_KEY on the backend to use live voice. The offline example works without a key.',
        );
      if (config.transport === 'elevenlabs_agents_webrtc') {
        await startSdk(
          attempt,
          config,
          requestedPreferences,
          accessCode,
          existing !== undefined,
          audioConsent,
        );
        return;
      }
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true },
      });
      if (attempt !== life.attempt) {
        stream.getTracks().forEach((track) => track.stop());
        return;
      }
      microphone = stream;
      if (audioConsent) startLocalRecording(stream);
      else if (existing) recording?.microphone(stream);
      const connection = openPeer(attempt, stream);
      await connection.setLocalDescription(await connection.createOffer());
      await gather(connection);
      if (attempt !== life.attempt) return;
      showState(
        existing ? 'recovering' : 'connecting',
        existing ? 'Reconnecting with Azure…' : 'Connecting…',
        'Please wait. Select Stop to cancel.',
      );
      const created = existing ?? (await createOwned(requestedPreferences, accessCode));
      if (attempt !== life.attempt) {
        await request(`/sessions/${created.id}/close`, created);
        return;
      }
      session = created;
      if (created.debugRecording) startDebugSampling(attempt, connection, created);
      const audioWatch = watchAudio(attempt, stream, config, created, serverGeneration);
      startHeartbeat(attempt, created, config);
      startup = setTimeout(() => {
        void finish('Voice startup timed out.');
      }, 40000);
      audioWatch.startTiming();
      const result = await request<{ sdp: string }>(
        `/sessions/${created.id}/${existing ? 'reconnect' : 'offer'}`,
        created,
        {
          sdp: connection.localDescription?.sdp,
          ...(existing ? { generation: serverGeneration } : {}),
        },
      );
      if (attempt !== life.attempt) return;
      await connection.setRemoteDescription({ type: 'answer', sdp: result.sdp });
      audioWatch.enableActivity();
    } catch (error) {
      if (attempt === life.attempt) {
        await finish(error instanceof Error ? error.message : 'Could not start conversation.');
      }
    }
  }

  const onFeedback = async (category: string, note = '') => {
    if (reportPending || reportSent || !getAccessCode()) return;
    reportPending = true;
    store.update({ reportPending: true, reportLocked: true });
    reportBody ??= {
      diagnostic_id: diagnosticId,
      category,
      state: store.getSnapshot().phase,
      ...(getPreferences().adapter ? { adapter: getPreferences().adapter } : {}),
      // Fixed with the first attempt, so a retry repeats the same report.
      ...(note.trim() ? { note: note.split(/\s+/).join(' ').trim().slice(0, 500) } : {}),
    };
    store.update({ feedbackStatus: 'Sending report…' });
    try {
      const result = await request<{ diagnostic_id: string }>('/feedback', undefined, reportBody);
      reportSent = true;
      store.update({
        reportSent: true,
        feedbackStatus: `Report received. Diagnostic ID: ${result.diagnostic_id}. Retained for seven days.`,
      });
    } catch {
      store.update({
        feedbackStatus: `Report not confirmed. Check your access code or try later (maximum five reports per day). Retrying uses the same diagnostic ID: ${diagnosticId}.`,
      });
    } finally {
      reportPending = false;
      store.update({ reportPending: false });
    }
  };

  const onPageHide = () => {
    const hadConversation = session !== undefined || store.getSnapshot().active;
    sounds.dispose();
    if (session) {
      void fetch(`${import.meta.env.VITE_API_BASE_URL ?? ''}/api/sessions/${session.id}/close`, {
        ...requestOptions(session, undefined, 5000),
        keepalive: true,
      }).catch(() => undefined);
    }
    send({ type: 'retire' });
    release();
    if (!hadConversation) return;
    showState('ended', 'Conversation ended.', 'Select Start conversation to begin a new session.');
    store.update(endedWorkerState(store.getSnapshot()));
  };
  const onVisibilityChange = () => {
    if (isNativeClient() && document.visibilityState === 'hidden' && store.getSnapshot().active)
      onPageHide();
  };
  document.addEventListener('visibilitychange', onVisibilityChange);
  showState('ready', 'Ready to connect', 'Start a conversation when you are ready.');
  window.addEventListener('pagehide', onPageHide);
  return {
    start: () => {
      if (!canStartVoice()) {
        showState(
          'ready',
          'Native live voice is disabled.',
          'Use the offline example. Native voice requires an explicit test build and device verification.',
        );
        return;
      }
      if (!store.getSnapshot().active && canStart(life)) {
        sounds.arm(getConnectionSounds());
        void begin();
      }
    },
    stop: () => {
      void finish('Conversation ended.', true);
    },
    cancel: onCancelTask,
    feedback: onFeedback,
    dispose: () => {
      disposed = true;
      sounds.dispose();
      if (audioUrl) URL.revokeObjectURL(audioUrl);
      window.removeEventListener('pagehide', onPageHide);
      document.removeEventListener('visibilitychange', onVisibilityChange);
      onPageHide();
    },
  };
}
export type LiveController = ReturnType<typeof createLiveSession>;
