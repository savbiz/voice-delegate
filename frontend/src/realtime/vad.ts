/** Local energy onset detector for task cancellation; transcript events remain a fallback. */
export class SpeechGate {
  private speaking = false;
  private loud = 0;
  private quiet = 0;
  update(rms: number): boolean {
    this.loud = rms > 0.035 ? this.loud + 1 : 0;
    this.quiet = rms < 0.02 ? this.quiet + 1 : 0;
    if (this.quiet >= 15) this.speaking = false;
    if (this.loud >= 3 && !this.speaking) { this.speaking = true; return true; }
    return false;
  }
}
export function watchSpeech(stream: MediaStream, onset: () => void): () => void {
  const context = new AudioContext();
  const source = context.createMediaStreamSource(stream);
  const analyser = context.createAnalyser();
  analyser.fftSize = 1024;
  source.connect(analyser);
  const samples = new Float32Array(analyser.fftSize);
  const gate = new SpeechGate();
  void context.resume().catch(() => undefined);
  const timer = setInterval(() => {
    analyser.getFloatTimeDomainData(samples);
    const rms = Math.sqrt(samples.reduce((sum, value) => sum + value * value, 0) / samples.length);
    if (gate.update(rms)) onset();
  }, 20);
  return () => { clearInterval(timer); source.disconnect(); analyser.disconnect(); void context.close(); };
}
