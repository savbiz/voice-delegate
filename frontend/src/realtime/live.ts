/** Own microphone, peer connection, captions, and explicitly approximate turn timing. */
import type { Source } from "../reference";
import { watchSpeech } from "./vad";
import { shouldRecover } from "./recovery";

export function mountLive(root: HTMLElement, getAccessCode: () => string): () => void {

function element<T extends HTMLElement>(id: string): T {
  const value = root.querySelector<T>(`#${id}`);
  if (!value) throw new Error(`Missing element: ${id}`);
  return value as T;
}
const start = element<HTMLButtonElement>("start");
const stop = element<HTMLButtonElement>("stop");
const status = element("status");
const taskStatus = element("task-status");
const recoveryHelp = element("recovery-help");
const feedbackButton = element<HTMLButtonElement>("send-feedback");
const feedbackCategory = element<HTMLSelectElement>("feedback-category");
const feedbackStatus = element("feedback-status");
let diagnosticId = crypto.randomUUID();
let uiState = "ready";
let reportBody: { diagnostic_id: string; category: string; state: string } | undefined;
let reportSent = false;
let reportPending = false;
function showState(state: string, message: string, help: string): void {
  uiState = state;
  status.textContent = message;
  recoveryHelp.textContent = help;
}
function showWorker(state: string): void {
  const messages: Record<string, string> = {
    idle: "Worker ready.", running: "Working on your request. You can interrupt by speaking.",
    busy: "Worker busy. Your task was not started. Repeat your request later if you still need it.",
    completed: "Task completed.", cancelled: "Task cancelled. You can give a new request.",
    timeout: "The task took too long and was stopped. You can give a new request.",
    failed: "The task failed. You can give a new request; nothing is retried automatically.",
    request_limit: "This conversation has reached its task limit. Start a new conversation if your allowance permits.",
    delivery_failed: "The worker result could not be delivered. Repeat your request if you still need it.",
  };
  taskStatus.textContent = messages[state] ?? "Waiting for worker status.";
  cancelTask.disabled = state !== "running" || ending || recovering || !session;
  if (!ending && !recovering && session) uiState = state === "running" ? "working" : state === "busy" ? "busy" : "connected";
}
const cancelTask = element<HTMLButtonElement>("cancel-task");
const preferences = element<HTMLFieldSetElement>("voice-preferences");
const language = element<HTMLSelectElement>("language");
const voiceMode = element<HTMLSelectElement>("voice-mode");
const recap = element("recap");
const mute = element<HTMLButtonElement>("mute-audio");
const largeCaptions = element<HTMLButtonElement>("large-captions");
const audio = element<HTMLAudioElement>("audio");
const captions = { user: element("user"), assistant: element("assistant") };
const sources = element("sources");
const timings = element<HTMLOListElement>("timings");
type Session = { id: string; key: string };
type Turn = { end: number; reply?: number; row: HTMLLIElement };
let stopVad: (() => void) | undefined;
let peer: RTCPeerConnection | undefined;
let microphone: MediaStream | undefined;
let channel: RTCDataChannel | undefined;
let session: Session | undefined;
let heartbeat: ReturnType<typeof setInterval> | undefined;
let startup: ReturnType<typeof setTimeout> | undefined;
let generation = 0;
let ending = false;
let recovering = false;
let fallbackAttempted = false;
let turn: Turn | undefined;
let turnNumber = 0;

function renderSources(items: Source[]): void {
  sources.replaceChildren();
  for (const [index, source] of items.slice(0, 3).entries()) {
    const detail = document.createElement("details");
    const title = document.createElement("summary");
    title.textContent = `[${index + 1}] ${source.title} — ${source.section}`;
    const text = document.createElement("blockquote");
    text.textContent = source.text;
    const origin = document.createElement("small");
    origin.textContent = `${source.path} · Snapshot ${source.id}`;
    detail.append(title, text, origin);
    sources.append(detail);
  }
}

function release(): void {
  stopVad?.();
  stopVad = undefined;
  clearInterval(heartbeat);
  clearTimeout(startup);
  microphone?.getTracks().forEach(track => track.stop());
  channel?.close();
  peer?.close();
  audio.srcObject = null;
  microphone = undefined;
  channel = undefined;
  peer = undefined;
  session = undefined;
  start.disabled = false;
  stop.disabled = true;
  preferences.disabled = false;
  cancelTask.disabled = true;
}

async function request(path: string, owner?: Session, body?: unknown): Promise<unknown> {
  const accessCode = getAccessCode();
  const response = await fetch(`${import.meta.env.VITE_API_BASE_URL ?? ""}/api${path}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(accessCode ? { Authorization: `Bearer ${accessCode}` } : {}),
      ...(owner ? { "X-Session-Key": owner.key } : {}),
    },
    body: JSON.stringify(body ?? {}),
    signal: AbortSignal.timeout(35000),
  });
  if (!response.ok) {
    const messages: Record<number, string> = {
      401: "Your invitation is missing, invalid or revoked.",
      429: "Demo allowance reached or another conversation is active. Try again later.",
      503: "New conversations are temporarily unavailable.",
    };
    throw new Error(messages[response.status] ?? `Request failed (${response.status}). Check server configuration and access.`);
  }
  return response.json();
}

async function finish(message: string): Promise<void> {
  if (ending) return;
  ending = true;
  generation += 1;
  stop.disabled = true;
  clearInterval(heartbeat);
  clearTimeout(startup);
  status.textContent = "Closing conversation…";
  const owner = session;
  // Stop recording immediately, keeping the transport alive for final events.
  microphone?.getTracks().forEach(track => { track.enabled = false; });
  try {
    if (owner) {
      const result = await request(`/sessions/${owner.id}/close`, owner) as { finalized: boolean };
      if (!result.finalized) message += " Provider finalization unconfirmed.";
    }
  } catch {
    message += " Close was not confirmed; the server also enforces session expiry.";
  } finally {
    release();
    showState("ended", message, message === "Conversation ended."
      ? "Select Start conversation when you want a new session."
      : "Check your connection or access code, then select Start conversation to begin a new session. Previous tasks will not be replayed.");
    showWorker("idle");
    ending = false;
  }
}

function processEvent(raw: unknown): void {
  if (typeof raw !== "object" || raw === null) return;
  const event = raw as Record<string, unknown>;
  if (event.type === "session.started" || event.type === "session.created") {
    clearTimeout(startup);
    showState("connected", "Connected. Speak naturally.", "Speak to give a request or interrupt. Select Stop to end the conversation.");
  } else if (event.type === "session.closed") {
    if (!ending) {
      generation += 1;
      release();
      showState("ended", "Conversation ended. Provider finalization confirmed.", "Select Start conversation when you want a new session.");
      showWorker("idle");
    }
  } else if (event.type === "error") {
    showState(uiState, "The provider reported an error.", "You can continue speaking or stop the conversation.");
  } else if (event.type === "session.delegation.created") {
    showWorker("running");
  }
  const speaker = ["session.input_transcript.delta", "conversation.item.input_audio_transcription.completed"].includes(String(event.type)) ? "user"
    : ["session.output_transcript.delta", "response.output_audio_transcript.delta"].includes(String(event.type)) ? "assistant" : undefined;
  if (event.type === "conversation.item.input_audio_transcription.completed") event.delta = event.transcript;
  if (!speaker || typeof event.delta !== "string") return;
  const caption = captions[speaker];
  caption.textContent = ((caption.textContent === "—" ? "" : caption.textContent) + event.delta).slice(-6000);
  caption.scrollTop = caption.scrollHeight;
  if (typeof event.start_ms !== "number" || typeof event.end_ms !== "number"
      || !Number.isFinite(event.start_ms) || !Number.isFinite(event.end_ms)) return;
  if (speaker === "user") {
    if (!turn || event.start_ms - turn.end > 800) {
      const row = document.createElement("li");
      row.dataset.turn = String(++turnNumber);
      timings.prepend(row);
      while (timings.children.length > 20) timings.lastElementChild?.remove();
      turn = { end: event.end_ms, row };
    } else {
      turn.end = Math.max(turn.end, event.end_ms);
    }
  } else if (turn && turn.reply === undefined) {
    turn.reply = event.start_ms;
  }
  if (turn) {
    turn.row.textContent = `Turn ${turn.row.dataset.turn}: ` + (turn.reply === undefined
      ? "waiting for assistant transcript" : `${Math.round(turn.reply - turn.end)} ms transcript gap`);
  }
}

async function gather(connection: RTCPeerConnection): Promise<void> {
  if (connection.iceGatheringState === "complete") return;
  await new Promise<void>((resolve, reject) => {
    const timer = setTimeout(() => { cleanup(); reject(new Error("ICE gathering timed out")); }, 10000);
    function cleanup(): void {
      clearTimeout(timer);
      connection.removeEventListener("icegatheringstatechange", changed);
    }
    function changed(): void {
      if (connection.iceGatheringState === "complete") { cleanup(); resolve(); }
    }
    connection.addEventListener("icegatheringstatechange", changed);
    changed();
  });
}

const onMute = () => {
  audio.muted = !audio.muted;
  mute.setAttribute("aria-pressed", String(audio.muted));
  mute.textContent = audio.muted ? "Unmute assistant" : "Mute assistant";
};
const onLargeCaptions = () => {
  const active = root.classList.toggle("large-captions");
  largeCaptions.setAttribute("aria-pressed", String(active));
};
mute.addEventListener("click", onMute);
largeCaptions.addEventListener("click", onLargeCaptions);
const onStart = () => { if (!start.disabled && !ending && !recovering) void begin(); };
const onStop = () => { void finish("Conversation ended."); };
start.addEventListener("click", onStart);
stop.addEventListener("click", onStop);
const onCancelTask = () => {
  const owner = session;
  cancelTask.disabled = true;
  if (owner) void request(`/sessions/${owner.id}/interrupt`, owner)
    .then(() => { if (session === owner && !ending) taskStatus.textContent = "Worker cancellation requested. You can give a new request."; })
    .catch(() => { if (session === owner && !ending) { taskStatus.textContent = "Cancellation not confirmed. Try Cancel task again or stop the conversation."; cancelTask.disabled = false; } });
};
cancelTask.addEventListener("click", onCancelTask);

async function recover(message: string): Promise<void> {
  if (ending || recovering) return;
  const owner = session;
  if (!owner || fallbackAttempted) { await finish(message); return; }
  recovering = true;
  try {
    const state = await request(`/sessions/${owner.id}/heartbeat`, owner) as { generation: number; fallback_available: boolean };
    if (ending || session !== owner) return;
    if (!state.fallback_available) { await finish(message); return; }
    fallbackAttempted = true;
    generation += 1;
    release();
    session = owner;
    start.disabled = true;
    showState("recovering", "Reconnecting with Azure…", "Wait for connection confirmation, then repeat the unfinished phrase if needed.");
    await begin(owner, state.generation);
  } catch { await finish("Fallback failed."); }
  finally { recovering = false; }
}

async function begin(existing?: Session, serverGeneration = 0): Promise<void> {
  if (!existing) {
    fallbackAttempted = false;
    if (!reportPending) {
      diagnosticId = crypto.randomUUID(); reportBody = undefined; reportSent = false;
      feedbackCategory.disabled = false;
      feedbackButton.disabled = !getAccessCode();
      feedbackStatus.textContent = "Ready to send a report if something goes wrong.";
    }
  }
  const attempt = ++generation;
  start.disabled = true;
  stop.disabled = false;
  preferences.disabled = true;
  showState(existing ? "recovering" : "connecting", existing ? "Reconnecting with Azure…" : "Requesting microphone…", "Allow microphone access to continue. Select Stop to cancel.");
  showWorker("idle");
  captions.user.textContent = "—";
  captions.assistant.textContent = "—";
  timings.replaceChildren();
  renderSources([]);
  turn = undefined;
  turnNumber = 0;
  try {
    const config = await request("/config") as { voice_available: boolean };
    if (attempt !== generation) return;
    if (!config.voice_available) throw new Error("Set OPENAI_API_KEY on the backend to use live voice. Free demo works without a key.");
    const stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
    if (attempt !== generation) { stream.getTracks().forEach(track => track.stop()); return; }
    microphone = stream;
    const connection = new RTCPeerConnection();
    peer = connection;
    stream.getTracks().forEach(track => connection.addTrack(track, stream));
    connection.addEventListener("track", event => {
      if (attempt !== generation) return;
      audio.srcObject = new MediaStream([event.track]);
      void audio.play().catch(() => { status.textContent = "Press Play below to hear the assistant."; });
    });
    connection.addEventListener("connectionstatechange", () => {
      if (attempt === generation && shouldRecover("connectionstatechange", connection.connectionState)) {
        void recover("Media connection failed.");
      }
    });
    channel = connection.createDataChannel("oai-events");
    channel.addEventListener("message", (message: MessageEvent<unknown>) => {
      if (attempt !== generation || typeof message.data !== "string" || message.data.length > 65536) return;
      try { processEvent(JSON.parse(message.data)); } catch { void finish("Invalid provider event."); }
    });
    channel.addEventListener("close", () => {
      if (attempt === generation && shouldRecover("data-channel-close")) void recover("Event connection closed.");
    });
    await connection.setLocalDescription(await connection.createOffer());
    await gather(connection);
    if (attempt !== generation) return;
    showState(existing ? "recovering" : "connecting", existing ? "Reconnecting with Azure…" : "Connecting…", "Please wait. Select Stop to cancel.");
    const created = existing ?? await request("/sessions", undefined, { language: language.value, mode: voiceMode.value }) as Session;
    if (attempt !== generation) {
      await request(`/sessions/${created.id}/close`, created);
      return;
    }
    session = created;
    try {
      stopVad = watchSpeech(stream, () => {
        if (attempt !== generation) return;
        void request(`/sessions/${created.id}/interrupt`, created).catch(() => undefined);
      }, audio);
    } catch { /* Provider-side speech detection remains authoritative without local analysis. */ }
    heartbeat = setInterval(() => {
      if (attempt !== generation) return;
      void request(`/sessions/${created.id}/heartbeat`, created).then(result => {
        if (attempt === generation) {
          const state = result as { delegation: string; state: string; sources?: Source[]; recap?: { latest_request: string; latest_reply: string; interrupted: boolean } };
          renderSources(state.sources ?? []);
          if (state.recap) {
            recap.textContent = `${state.recap.interrupted ? "Interrupted task. " : ""}Latest request: ${state.recap.latest_request || "—"}` +
              (state.recap.latest_reply ? ` · Latest reply excerpt: ${state.recap.latest_reply}` : "");
          }
          showWorker(state.delegation);
          if (state.state === "closed" || state.state === "closing") void finish("Conversation ended.");
          if (state.state === "reconnecting") showState("recovering", "Provider connection lost.", "Waiting for transport recovery. You can select Stop.");
        }
      }).catch(() => {
        if (attempt === generation) void finish("Server connection lost or session expired.");
      });
    }, 10000);
    startup = setTimeout(() => { void finish("Voice startup timed out."); }, 40000);
    const result = await request(`/sessions/${created.id}/${existing ? "reconnect" : "offer"}`, created,
      { sdp: connection.localDescription?.sdp, ...(existing ? { generation: serverGeneration } : {}) }) as { sdp: string };
    if (attempt !== generation) return;
    await connection.setRemoteDescription({ type: "answer", sdp: result.sdp });
  } catch (error) {
    if (attempt === generation) {
      await finish(error instanceof Error ? error.message : "Could not start conversation.");
    }
  }
}

const onFeedback = async () => {
  if (reportPending || reportSent || !getAccessCode()) return;
  reportPending = true;
  feedbackButton.disabled = true;
  feedbackCategory.disabled = true;
  reportBody ??= { diagnostic_id: diagnosticId, category: feedbackCategory.value, state: uiState };
  feedbackStatus.textContent = "Sending report…";
  try {
    const result = await request("/feedback", undefined, reportBody) as { diagnostic_id: string };
    reportSent = true;
    feedbackStatus.textContent = `Report received. Diagnostic ID: ${result.diagnostic_id}. Retained for seven days.`;
  } catch {
    feedbackStatus.textContent = `Report not confirmed. Check your access code or try later (maximum five reports per day). Retrying uses the same diagnostic ID: ${diagnosticId}.`;
  } finally {
    reportPending = false;
    feedbackButton.disabled = reportSent;
  }
};
feedbackButton.disabled = !getAccessCode();
feedbackButton.addEventListener("click", onFeedback);

const onPageHide = () => {
  const accessCode = getAccessCode();
  if (session) {
    void fetch(`${import.meta.env.VITE_API_BASE_URL ?? ""}/api/sessions/${session.id}/close`, {
      method: "POST", keepalive: true, headers: { "X-Session-Key": session.key, ...(accessCode ? { Authorization: `Bearer ${accessCode}` } : {}) },
    }).catch(() => undefined);
  }
  generation += 1;
  release();
  showState("ended", "Conversation ended.", "Select Start conversation to begin a new session.");
 };
showState("ready", "Ready to connect", "Start a conversation when you are ready.");
window.addEventListener("pagehide", onPageHide);
return () => {
  window.removeEventListener("pagehide", onPageHide);
  feedbackButton.removeEventListener("click", onFeedback);
  start.removeEventListener("click", onStart);
  stop.removeEventListener("click", onStop);
  cancelTask.removeEventListener("click", onCancelTask);
  mute.removeEventListener("click", onMute);
  largeCaptions.removeEventListener("click", onLargeCaptions);
  onPageHide();
};
}
