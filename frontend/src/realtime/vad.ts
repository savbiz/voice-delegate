/** Local energy onset detector; provider-side speech detection remains authoritative. */
export class SpeechGate {
  private speaking = false;
  private loud = 0;
  private quiet = 0;
  constructor(private threshold = 0.035, private quietThreshold = 0.02) {}
  get active(): boolean { return this.speaking; }
  reset(): void { this.speaking = false; this.loud = 0; this.quiet = 0; }
  update(rms: number): boolean {
    this.loud = rms > this.threshold ? this.loud + 1 : 0;
    this.quiet = rms < this.quietThreshold ? this.quiet + 1 : 0;
    if (this.quiet >= 15) this.speaking = false;
    if (this.loud >= 3 && !this.speaking) { this.speaking = true; return true; }
    return false;
  }
}

/** Ignore loudspeaker echo, then require a fresh local onset after remote silence. */
export class LocalInterruptGate {
  private local = new SpeechGate();
  private remote = new SpeechGate(0.06, 0.035);
  private resumeAt = -Infinity;
  update(localRms: number, remoteRms: number, now: number): boolean {
    this.remote.update(remoteRms);
    if (this.remote.active && remoteRms >= 0.035) this.resumeAt = now + 300;
    if (this.remote.active || now < this.resumeAt) {
      this.local.reset();
      return false;
    }
    return this.local.update(localRms);
  }
}

export function watchSpeech(
  stream: MediaStream, onset: () => void, remoteAudio?: HTMLAudioElement,
): () => void {
  const context = new AudioContext();
  try {
  const source = context.createMediaStreamSource(stream);
  const analyser = context.createAnalyser();
  const remoteAnalyser = context.createAnalyser();
  analyser.fftSize = remoteAnalyser.fftSize = 1024;
  source.connect(analyser);
  let remoteStream: MediaStream | undefined;
  let remoteSource: MediaStreamAudioSourceNode | undefined;
  const samples = new Float32Array(analyser.fftSize);
  const remoteSamples = new Float32Array(remoteAnalyser.fftSize);
  const gate = new LocalInterruptGate();
  const energy = (node: AnalyserNode, values: Float32Array<ArrayBuffer>): number => {
    node.getFloatTimeDomainData(values);
    return Math.sqrt(values.reduce((sum, value) => sum + value * value, 0) / values.length);
  };
  void context.resume().catch(() => undefined);
  const timer = setInterval(() => {
    const incoming = remoteAudio?.srcObject;
    const next = incoming instanceof MediaStream ? incoming : undefined;
    if (next !== remoteStream) {
      remoteSource?.disconnect();
      remoteSource = undefined;
      remoteStream = next;
      if (next?.getAudioTracks().length) {
        try {
          remoteSource = context.createMediaStreamSource(next);
          remoteSource.connect(remoteAnalyser);
        } catch { /* Provider-side speech detection still works without local analysis. */ }
      }
    }
    const playing = remoteAudio && !remoteAudio.paused && !remoteAudio.ended &&
      !remoteAudio.muted && remoteAudio.volume > 0;
    const remoteRms = playing && remoteSource
      ? energy(remoteAnalyser, remoteSamples) * remoteAudio.volume : 0;
    if (gate.update(energy(analyser, samples), remoteRms, performance.now())) onset();
  }, 20);
  return () => {
    clearInterval(timer);
    source.disconnect();
    remoteSource?.disconnect();
    analyser.disconnect();
    remoteAnalyser.disconnect();
    void context.close().catch(() => undefined);
  };
  } catch (error) {
    void context.close().catch(() => undefined);
    throw error;
  }
}
