/** Own microphone, peer connection, captions, and explicitly approximate turn timing. */
import "./style.css";

function element<T extends HTMLElement>(id: string): T {
  const value = document.getElementById(id);
  if (!value) throw new Error(`Missing element: ${id}`);
  return value as T;
}
const start = element<HTMLButtonElement>("start");
const stop = element<HTMLButtonElement>("stop");
const status = element("status");
const audio = element<HTMLAudioElement>("audio");
const captions = { user: element("user"), assistant: element("assistant") };
const timings = element<HTMLOListElement>("timings");
type Session = { id: string; key: string };
type Turn = { end: number; reply?: number; row: HTMLLIElement };
let peer: RTCPeerConnection | undefined;
let microphone: MediaStream | undefined;
let channel: RTCDataChannel | undefined;
let session: Session | undefined;
let heartbeat: ReturnType<typeof setInterval> | undefined;
let startup: ReturnType<typeof setTimeout> | undefined;
let generation = 0;
let ending = false;
let turn: Turn | undefined;
let turnNumber = 0;

function release(): void {
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
}

async function request(path: string, owner?: Session, body?: unknown): Promise<unknown> {
  const response = await fetch(`/api${path}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(owner ? { "X-Session-Key": owner.key } : {}),
    },
    body: JSON.stringify(body ?? {}),
    signal: AbortSignal.timeout(35000),
  });
  if (!response.ok) {
    throw new Error(`Request failed (${response.status}). Check server configuration and access.`);
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
    status.textContent = message;
    ending = false;
  }
}

function processEvent(raw: unknown): void {
  if (typeof raw !== "object" || raw === null) return;
  const event = raw as Record<string, unknown>;
  if (event.type === "session.started") {
    clearTimeout(startup);
    status.textContent = "Connected. Speak naturally.";
  } else if (event.type === "session.closed") {
    if (!ending) {
      generation += 1;
      release();
      status.textContent = "Conversation ended. Provider finalization confirmed.";
    }
  } else if (event.type === "error") {
    void finish("The provider reported an error.");
  } else if (event.type === "session.delegation.created") {
    status.textContent = "Task execution arrives in M2. No external action was taken.";
  }
  const speaker = event.type === "session.input_transcript.delta" ? "user"
    : event.type === "session.output_transcript.delta" ? "assistant" : undefined;
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

start.addEventListener("click", () => { void begin(); });
stop.addEventListener("click", () => { void finish("Conversation ended."); });

async function begin(): Promise<void> {
  const attempt = ++generation;
  start.disabled = true;
  stop.disabled = false;
  status.textContent = "Requesting microphone…";
  captions.user.textContent = "—";
  captions.assistant.textContent = "—";
  timings.replaceChildren();
  turn = undefined;
  turnNumber = 0;
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
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
      if (attempt === generation && connection.connectionState === "failed") {
        void finish("Media connection failed.");
      }
    });
    channel = connection.createDataChannel("oai-events");
    channel.addEventListener("message", (message: MessageEvent<unknown>) => {
      if (attempt !== generation || typeof message.data !== "string" || message.data.length > 65536) return;
      try { processEvent(JSON.parse(message.data)); } catch { void finish("Invalid provider event."); }
    });
    channel.addEventListener("close", () => {
      if (attempt === generation) void finish("Event connection closed.");
    });
    await connection.setLocalDescription(await connection.createOffer());
    await gather(connection);
    if (attempt !== generation) return;
    status.textContent = "Connecting…";
    const created = await request("/sessions") as Session;
    if (attempt !== generation) {
      await request(`/sessions/${created.id}/close`, created);
      return;
    }
    session = created;
    heartbeat = setInterval(() => {
      if (attempt !== generation) return;
      void request(`/sessions/${created.id}/heartbeat`, created).catch(() => {
        if (attempt === generation) void finish("Server connection lost or session expired.");
      });
    }, 10000);
    startup = setTimeout(() => { void finish("Voice startup timed out."); }, 40000);
    const result = await request(`/sessions/${created.id}/offer`, created,
      { sdp: connection.localDescription?.sdp }) as { sdp: string };
    if (attempt !== generation) return;
    await connection.setRemoteDescription({ type: "answer", sdp: result.sdp });
  } catch (error) {
    if (attempt === generation) {
      await finish(error instanceof Error ? error.message : "Could not start conversation.");
    }
  }
}

window.addEventListener("pagehide", () => {
  if (session) {
    void fetch(`/api/sessions/${session.id}/close`, {
      method: "POST", keepalive: true, headers: { "X-Session-Key": session.key },
    }).catch(() => undefined);
  }
  generation += 1;
  release();
});
