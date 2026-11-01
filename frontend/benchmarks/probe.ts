/** Isolated browser probe: media observations only, no transcripts or credentials in output. */
export type ProbeOptions = {
  api?: string;
  invitation?: string;
  wav?: string;
  speechEndMs: number;
  timeoutMs: number;
  fake?: boolean;
};
export type ProbeResult = {
  outcome: 'completed' | 'timeout' | 'overlap' | 'error';
  delegated: boolean | null;
  setup_ms: number | null;
  first_audio_ms: number | null;
  turn_ms: number | null;
  failure_stage: 'setup' | 'connect' | 'playback' | 'close' | null;
};

// Kept self-contained so Playwright can serialize it into a blank, local browser page.
export async function probe(options: ProbeOptions): Promise<ProbeResult> {
  const context = new AudioContext();
  const peers: RTCPeerConnection[] = [];
  const tracks: MediaStreamTrack[] = [];
  const audio = new Audio();
  const timers: ReturnType<typeof setInterval>[] = [];
  const nodes: AudioNode[] = [];
  let owner: { id: string; key: string } | undefined;
  let delegated = false;
  let observed = false;
  let failed = false;
  let sequence = 0;
  let first: number | undefined;
  let last: number | undefined;
  let inputEnd = 0;
  let offerAt: number;
  let analyser: AnalyserNode | undefined;
  let overlap = false;
  let heartbeatBusy = false;
  let tone: OscillatorNode | undefined;
  let stage: 'setup' | 'connect' | 'playback' | 'close' = 'setup';
  const result: ProbeResult = {
    outcome: 'error',
    delegated: null,
    setup_ms: null,
    first_audio_ms: null,
    turn_ms: null,
    failure_stage: null,
  };
  async function request(path: string, body = {}, timeout = 25000): Promise<unknown> {
    const response = await fetch(`${options.api}/api${path}`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(options.invitation ? { Authorization: `Bearer ${options.invitation}` } : {}),
        ...(owner ? { 'X-Session-Key': owner.key } : {}),
      },
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(timeout),
      redirect: 'error',
    });
    if (!response.ok) throw new Error('Benchmark request failed');
    const reader = response.body?.getReader();
    if (!reader) throw new Error('Missing benchmark response');
    let text = '';
    let size = 0;
    const decoder = new TextDecoder();
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      size += value.length;
      if (size > 65536) {
        await reader.cancel();
        throw new Error('Oversized benchmark response');
      }
      text += decoder.decode(value, { stream: true });
    }
    text += decoder.decode();
    return JSON.parse(text) as unknown;
  }
  async function gather(peer: RTCPeerConnection): Promise<void> {
    if (peer.iceGatheringState === 'complete') return;
    await new Promise<void>((resolve, reject) => {
      const timer = setTimeout(() => {
        peer.removeEventListener('icegatheringstatechange', changed);
        reject(new Error('ICE gathering timed out'));
      }, 8000);
      function changed() {
        if (peer.iceGatheringState === 'complete') {
          clearTimeout(timer);
          peer.removeEventListener('icegatheringstatechange', changed);
          resolve();
        }
      }
      peer.addEventListener('icegatheringstatechange', changed);
      changed();
    });
  }
  function attach(stream: MediaStream) {
    tracks.push(...stream.getTracks());
    analyser = context.createAnalyser();
    analyser.fftSize = 1024;
    const source = context.createMediaStreamSource(stream);
    source.connect(analyser);
    nodes.push(source, analyser);
    audio.srcObject = stream;
    void audio.play().catch(() => {
      failed = true;
    });
  }
  try {
    await context.resume();
    const destination = context.createMediaStreamDestination();
    nodes.push(destination);
    tracks.push(...destination.stream.getTracks());
    const peer = new RTCPeerConnection({ iceServers: [] });
    peers.push(peer);
    peer.addTrack(destination.stream.getAudioTracks()[0]!, destination.stream);
    peer.ontrack = (event) => attach(new MediaStream([event.track]));
    peer.onconnectionstatechange = () => {
      if (['failed', 'closed', 'disconnected'].includes(peer.connectionState)) failed = true;
    };
    const channel = peer.createDataChannel('oai-events');
    channel.onopen = () => {
      observed = true;
    };
    channel.onmessage = ({ data }: MessageEvent<unknown>) => {
      if (typeof data !== 'string' || data.length > 65536) return;
      try {
        const event = JSON.parse(data) as { type?: string; name?: string };
        if (event.type === 'session.started' || event.type === 'session.created') observed = true;
        if (
          event.type === 'session.delegation.created' ||
          (event.type === 'response.function_call_arguments.done' && event.name === 'delegate_task')
        ) {
          delegated = true;
          observed = true;
        }
      } catch {
        // Unparseable events are ignored; their content is never retained.
      }
    };
    let buffer: AudioBuffer;
    if (options.fake) {
      buffer = context.createBuffer(1, context.sampleRate * 0.2, context.sampleRate);
      const samples = buffer.getChannelData(0);
      for (let i = 0; i < samples.length; i++) samples[i] = 0.1 * Math.sin(i / 10);
    } else {
      if (!options.wav) throw new Error('Recording required');
      const bytes = Uint8Array.from(atob(options.wav), (c) => c.charCodeAt(0));
      buffer = await context.decodeAudioData(bytes.buffer);
      if (buffer.duration > 10 || options.speechEndMs > buffer.duration * 1000)
        throw new Error('Recording duration or speech boundary invalid');
    }
    offerAt = context.currentTime * 1000;
    await peer.setLocalDescription(await peer.createOffer());
    await gather(peer);
    if (options.fake) {
      const remote = new RTCPeerConnection({ iceServers: [] });
      peers.push(remote);
      remote.ondatachannel = ({ channel: incoming }) => {
        incoming.onopen = () => incoming.send(JSON.stringify({ type: 'session.created' }));
      };
      const out = context.createMediaStreamDestination();
      nodes.push(out);
      tracks.push(...out.stream.getTracks());
      remote.addTrack(out.stream.getAudioTracks()[0]!, out.stream);
      await remote.setRemoteDescription(peer.localDescription!);
      await remote.setLocalDescription(await remote.createAnswer());
      await gather(remote);
      await peer.setRemoteDescription(remote.localDescription!);
      tone = context.createOscillator();
      const gain = context.createGain();
      gain.gain.value = 0.1;
      tone.connect(gain).connect(out);
      nodes.push(tone, gain);
      // Start only after the input has finished, leaving time for the loopback ICE connection.
      observed = true;
    } else {
      const config = (await request('/config')) as { intent_cancellation?: boolean };
      owner = (await request('/sessions', { language: 'en', mode: 'conversation' })) as {
        id: string;
        key: string;
      };
      const answer = (await request(`/sessions/${owner.id}/offer`, {
        sdp: peer.localDescription!.sdp,
      })) as { sdp: string };
      await peer.setRemoteDescription({ type: 'answer', sdp: answer.sdp });
      const sessionPath = `/sessions/${owner.id}`;
      timers.push(
        setInterval(() => {
          if (heartbeatBusy) return;
          heartbeatBusy = true;
          void request(`${sessionPath}/heartbeat`, {}, 2000)
            .then(async (value) => {
              const status = value as {
                state: string;
                tasks?: unknown[];
                delegation?: string;
                generation: number;
              };
              if (status.state !== 'connected') failed = true;
              if (status.tasks?.length || (status.delegation && status.delegation !== 'idle'))
                delegated = true;
              if (config.intent_cancellation)
                await request(
                  `${sessionPath}/activity`,
                  {
                    generation: status.generation,
                    sequence: ++sequence,
                    user_speaking: context.currentTime * 1000 < inputEnd,
                    assistant_speaking:
                      last !== undefined && context.currentTime * 1000 - last < 200,
                  },
                  2000,
                );
            })
            .catch(() => {
              failed = true;
            })
            .finally(() => {
              heartbeatBusy = false;
            });
        }, 1000),
      );
    }
    stage = 'connect';
    const connectedDeadline = performance.now() + 10000;
    while (peer.connectionState !== 'connected') {
      if (failed || performance.now() > connectedDeadline) throw new Error('Connection failed');
      await new Promise((resolve) => setTimeout(resolve, 20));
    }
    stage = 'playback';
    const source = context.createBufferSource();
    source.buffer = buffer;
    source.connect(destination);
    nodes.push(source);
    inputEnd = context.currentTime * 1000 + options.speechEndMs;
    source.start();
    if (tone) {
      tone.start(context.currentTime + 0.8);
      tone.stop(context.currentTime + 1.0);
    }
    const deadline = performance.now() + options.timeoutMs + buffer.duration * 1000;
    const values = new Float32Array(1024);
    while (performance.now() < deadline && !failed) {
      const now = context.currentTime * 1000;
      if (analyser && !audio.paused) {
        analyser.getFloatTimeDomainData(values);
        const rms = Math.sqrt(
          values.reduce((sum, value) => sum + value * value, 0) / values.length,
        );
        if (rms > 0.02) {
          first ??= now;
          last = now;
          if (now < inputEnd) overlap = true;
        }
      }
      if (last !== undefined && now - last >= 1000 && now >= inputEnd) break;
      await new Promise((resolve) => setTimeout(resolve, 20));
    }
    result.delegated = observed ? delegated : null;
    result.outcome =
      failed || !observed
        ? 'error'
        : overlap
          ? 'overlap'
          : first !== undefined && last !== undefined && context.currentTime * 1000 - last >= 1000
            ? 'completed'
            : 'timeout';
    if (result.outcome === 'completed' && first !== undefined && last !== undefined) {
      result.setup_ms = Math.round(first - offerAt);
      result.first_audio_ms = Math.round(first - inputEnd);
      result.turn_ms = Math.round(last - inputEnd);
    }
    return result;
  } catch {
    result.failure_stage = stage;
    return result; // Sanitized outcome, never an exception containing a provider response.
  } finally {
    timers.forEach(clearInterval);
    nodes.forEach((node) => node.disconnect());
    tracks.forEach((track) => track.stop());
    peers.forEach((peer) => peer.close());
    audio.pause();
    audio.srcObject = null;
    await context.close();
    if (owner) {
      let confirmed = false;
      try {
        const closed = (await request(`/sessions/${owner.id}/close`, {}, 7000)) as {
          finalized?: boolean;
        };
        confirmed = closed.finalized === true;
      } catch {
        // An unconfirmed close is an error observation, never a successful latency sample.
      }
      if (!confirmed) {
        result.outcome = 'error';
        result.failure_stage = 'close';
        result.first_audio_ms = null;
        result.turn_ms = null;
      }
    }
  }
}
