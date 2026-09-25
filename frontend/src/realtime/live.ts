/** Own microphone, peer connection, captions, and explicitly approximate turn timing. */
import type { Source } from '../reference';
import { watchSpeech } from './vad';
import { shouldRecover } from './recovery';

import { processEvent, workerState } from './store';
import type { LiveStore, Phase } from './store';
export type Preferences = { language: string; mode: string };
export function createLiveSession(
  store: LiveStore,
  audio: HTMLAudioElement,
  getAccessCode: () => string,
  getPreferences: () => Preferences,
) {
  let diagnosticId = crypto.randomUUID();
  let reportBody: { diagnostic_id: string; category: string; state: string } | undefined;
  let reportSent = false;
  let reportPending = false;
  function showState(phase: Phase, status: string, help: string): void {
    store.update({ phase, status, help });
  }
  function showWorker(worker: string): void {
    store.update(workerState(store.getSnapshot(), worker));
  }
  type Session = { id: string; key: string; accessCode: string };
  let stopVad: (() => void) | undefined;
  let peer: RTCPeerConnection | undefined;
  let microphone: MediaStream | undefined;
  let channel: RTCDataChannel | undefined;
  let session: Session | undefined;
  let heartbeat: ReturnType<typeof setInterval> | undefined;
  let startup: ReturnType<typeof setTimeout> | undefined;
  let attemptId = 0;
  let ending = false;
  let recovering = false;
  let fallbackAttempted = false;
  let heartbeatFailures = 0;
  let lastDelegation = 'idle';

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

  function release(): void {
    stopVad?.();
    stopVad = undefined;
    clearInterval(heartbeat);
    clearTimeout(startup);
    microphone?.getTracks().forEach((track) => track.stop());
    channel?.close();
    peer?.close();
    audio.srcObject = null;
    microphone = undefined;
    channel = undefined;
    peer = undefined;
    session = undefined;
    store.update({ active: false, cancelPending: true });
  }

  function requestOptions(
    owner?: Session,
    body?: unknown,
    timeout = 35000,
    accessCode = owner?.accessCode ?? getAccessCode(),
  ): RequestInit {
    return {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(accessCode ? { Authorization: `Bearer ${accessCode}` } : {}),
        ...(owner ? { 'X-Session-Key': owner.key } : {}),
      },
      body: JSON.stringify(body ?? {}),
      signal: AbortSignal.timeout(timeout),
    };
  }
  async function request<T>(
    path: string,
    owner?: Session,
    body?: unknown,
    timeout = 35000,
    accessCode?: string,
  ): Promise<T> {
    const response = await fetch(
      `${import.meta.env.VITE_API_BASE_URL ?? ''}/api${path}`,
      requestOptions(owner, body, timeout, accessCode),
    );
    if (!response.ok) {
      const messages: Record<number, string> = {
        401: 'Your invitation is missing, invalid or revoked.',
        429: 'Demo allowance reached or another conversation is active. Try again later.',
        503: 'New conversations are temporarily unavailable.',
      };
      throw new Error(
        messages[response.status] ??
          `Request failed (${response.status}). Check server configuration and access.`,
      );
    }
    return response.json();
  }

  async function finish(message: string): Promise<void> {
    if (ending) return;
    ending = true;
    const closedAttempt = ++attemptId;
    const owner = session;
    release();
    showState(
      'ended',
      message,
      message === 'Conversation ended.'
        ? 'Select Start conversation when you want a new session.'
        : 'Check your connection or access code, then select Start conversation to begin a new session. Previous tasks will not be replayed.',
    );
    showWorker('idle');
    ending = false;
    store.update({ ending: false });
    if (owner) {
      void request<{ finalized: boolean }>(`/sessions/${owner.id}/close`, owner, undefined, 5000)
        .then((result) => {
          if (closedAttempt === attemptId && !result.finalized)
            store.update({ status: message + ' Provider finalization unconfirmed.' });
        })
        .catch(() => {
          if (closedAttempt === attemptId)
            store.update({
              status:
                message + ' Close was not confirmed; the server also enforces session expiry.',
            });
        });
    }
  }

  function receiveEvent(raw: unknown): void {
    const result = processEvent(store.getSnapshot(), raw, performance.now());
    store.update(result.state);
    if (result.effect === 'started') clearTimeout(startup);
    if (result.effect === 'closed' && !ending) {
      attemptId += 1;
      release();
      showState(
        'ended',
        'Conversation ended. Provider finalization confirmed.',
        'Select Start conversation when you want a new session.',
      );
      showWorker('idle');
    }
  }

  async function gather(connection: RTCPeerConnection): Promise<void> {
    if (connection.iceGatheringState === 'complete') return;
    await new Promise<void>((resolve, reject) => {
      const timer = setTimeout(() => {
        cleanup();
        reject(new Error('ICE gathering timed out'));
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

  const onCancelTask = () => {
    const owner = session;
    store.update({ cancelPending: true });
    if (owner)
      void request(`/sessions/${owner.id}/interrupt`, owner)
        .then(() => {
          if (session === owner && !ending)
            store.update({
              workerMessage: 'Worker cancellation requested. You can give a new request.',
            });
        })
        .catch(() => {
          if (session === owner && !ending) {
            store.update({
              workerMessage:
                'Cancellation not confirmed. Try Cancel task again or stop the conversation.',
              cancelPending: false,
            });
          }
        });
  };

  async function recover(message: string): Promise<void> {
    if (ending || recovering) return;
    const owner = session;
    if (!owner || fallbackAttempted) {
      await finish(message);
      return;
    }
    recovering = true;
    store.update({ recovering: true });
    try {
      const state = await request<{ generation: number; fallback_available: boolean }>(
        `/sessions/${owner.id}/heartbeat`,
        owner,
        undefined,
        8000,
      );
      if (ending || session !== owner) return;
      if (!state.fallback_available) {
        await finish(message);
        return;
      }
      fallbackAttempted = true;
      attemptId += 1;
      release();
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
      recovering = false;
      store.update({ recovering: false });
    }
  }

  async function begin(existing?: Session, serverGeneration = 0): Promise<void> {
    if (!existing) {
      fallbackAttempted = false;
      store.update({ captions: { user: '', assistant: '' }, timings: [], sources: [] });
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
    const accessCode = existing?.accessCode ?? getAccessCode();
    const attempt = ++attemptId;
    store.update({ timingTransportId: attempt });
    store.update({ active: true });
    showState(
      existing ? 'recovering' : 'connecting',
      existing ? 'Reconnecting with Azure…' : 'Requesting microphone…',
      'Allow microphone access to continue. Select Stop to cancel.',
    );
    showWorker('idle');
    heartbeatFailures = 0;
    lastDelegation = 'idle';
    try {
      const config = await request<{ voice_available: boolean }>('/config');
      if (attempt !== attemptId) return;
      if (!config.voice_available)
        throw new Error(
          'Set OPENAI_API_KEY on the backend to use live voice. Free demo works without a key.',
        );
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: true, noiseSuppression: true },
      });
      if (attempt !== attemptId) {
        stream.getTracks().forEach((track) => track.stop());
        return;
      }
      microphone = stream;
      const connection = new RTCPeerConnection();
      peer = connection;
      stream.getTracks().forEach((track) => connection.addTrack(track, stream));
      connection.addEventListener('track', (event) => {
        if (attempt !== attemptId) return;
        audio.srcObject = new MediaStream([event.track]);
        void audio.play().catch(() => {
          store.update({ status: 'Press Play below to hear the assistant.' });
        });
      });
      connection.addEventListener('connectionstatechange', () => {
        if (
          attempt === attemptId &&
          shouldRecover('connectionstatechange', connection.connectionState)
        ) {
          void recover('Media connection failed.');
        }
      });
      channel = connection.createDataChannel('oai-events');
      channel.addEventListener('message', (message: MessageEvent<unknown>) => {
        if (
          attempt !== attemptId ||
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
        if (attempt === attemptId && shouldRecover('data-channel-close'))
          void recover('Event connection closed.');
      });
      await connection.setLocalDescription(await connection.createOffer());
      await gather(connection);
      if (attempt !== attemptId) return;
      showState(
        existing ? 'recovering' : 'connecting',
        existing ? 'Reconnecting with Azure…' : 'Connecting…',
        'Please wait. Select Stop to cancel.',
      );
      const created = existing ?? {
        ...(await request<{ id: string; key: string }>(
          '/sessions',
          undefined,
          getPreferences(),
          35000,
          accessCode,
        )),
        accessCode,
      };
      if (attempt !== attemptId) {
        await request(`/sessions/${created.id}/close`, created);
        return;
      }
      session = created;
      try {
        stopVad = watchSpeech(
          stream,
          () => {
            if (attempt !== attemptId || lastDelegation !== 'running') return;
            void request(`/sessions/${created.id}/interrupt`, created).catch(() => undefined);
          },
          audio,
        );
      } catch {
        /* Provider-side speech detection remains authoritative without local analysis. */
      }
      heartbeat = setInterval(() => {
        if (attempt !== attemptId) return;
        void request<{
          delegation: string;
          state: string;
          sources?: Source[];
          recap?: { latest_request: string; latest_reply: string; interrupted: boolean };
        }>(`/sessions/${created.id}/heartbeat`, created, undefined, 8000)
          .then((state) => {
            if (attempt === attemptId) {
              heartbeatFailures = 0;
              lastDelegation = state.delegation;
              renderSources(state.sources ?? []);
              if (state.recap) {
                const recap =
                  `${state.recap.interrupted ? 'Interrupted task. ' : ''}Latest request: ${state.recap.latest_request || '—'}` +
                  (state.recap.latest_reply
                    ? ` · Latest reply excerpt: ${state.recap.latest_reply}`
                    : '');
                store.update({ recap });
              }
              showWorker(state.delegation);
              if (state.state === 'closed' || state.state === 'closing')
                void finish('Conversation ended.');
              if (state.state === 'reconnecting')
                showState(
                  'recovering',
                  'Provider connection lost.',
                  'Waiting for transport recovery. You can select Stop.',
                );
            }
          })
          .catch(() => {
            if (attempt === attemptId && ++heartbeatFailures >= 3)
              void finish('Server connection lost or session expired.');
          });
      }, 10000);
      startup = setTimeout(() => {
        void finish('Voice startup timed out.');
      }, 40000);
      const result = await request<{ sdp: string }>(
        `/sessions/${created.id}/${existing ? 'reconnect' : 'offer'}`,
        created,
        {
          sdp: connection.localDescription?.sdp,
          ...(existing ? { generation: serverGeneration } : {}),
        },
      );
      if (attempt !== attemptId) return;
      await connection.setRemoteDescription({ type: 'answer', sdp: result.sdp });
    } catch (error) {
      if (attempt === attemptId) {
        await finish(error instanceof Error ? error.message : 'Could not start conversation.');
      }
    }
  }

  const onFeedback = async (category: string) => {
    if (reportPending || reportSent || !getAccessCode()) return;
    reportPending = true;
    store.update({ reportPending: true, reportLocked: true });
    reportBody ??= { diagnostic_id: diagnosticId, category, state: store.getSnapshot().phase };
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
    if (session) {
      void fetch(`${import.meta.env.VITE_API_BASE_URL ?? ''}/api/sessions/${session.id}/close`, {
        ...requestOptions(session, undefined, 5000),
        keepalive: true,
      }).catch(() => undefined);
    }
    attemptId += 1;
    release();
    showState('ended', 'Conversation ended.', 'Select Start conversation to begin a new session.');
  };
  showState('ready', 'Ready to connect', 'Start a conversation when you are ready.');
  window.addEventListener('pagehide', onPageHide);
  return {
    start: () => {
      if (!store.getSnapshot().active && !ending && !recovering) void begin();
    },
    stop: () => {
      void finish('Conversation ended.');
    },
    cancel: onCancelTask,
    feedback: onFeedback,
    dispose: () => {
      window.removeEventListener('pagehide', onPageHide);
      onPageHide();
    },
  };
}
export type LiveController = ReturnType<typeof createLiveSession>;
