/** Browser audio observations, never transcript-derived or acoustic ground truth. */
export type AudioTiming = { kind: 'setup' | 'turn'; milliseconds: number };
export class AudioTimingMeter {
  private first = true;
  private localEnd: number | undefined;
  private remoteActive = false;
  private lastSample: number | undefined;
  constructor(private readonly started: number) {}

  sample(now: number, local: number, remote: number, playing: boolean): AudioTiming[] {
    if (![now, local, remote].every(Number.isFinite)) return [];
    // Background tabs and suspended audio contexts cannot provide continuous observations.
    if (this.lastSample !== undefined && now - this.lastSample > 100) this.localEnd = undefined;
    this.lastSample = now;
    const audible = playing && remote > 0.02;
    if (local > 0.035) this.localEnd = audible ? undefined : now;
    const result: AudioTiming[] = [];
    if (audible && !this.remoteActive) {
      if (this.first) {
        const duration = now - this.started;
        if (duration >= 0 && duration <= 120000)
          result.push({ kind: 'setup', milliseconds: duration });
        this.first = false;
      }
      if (this.localEnd !== undefined) {
        const duration = now - this.localEnd;
        if (duration >= 300 && duration <= 120000)
          result.push({ kind: 'turn', milliseconds: duration });
      }
      this.localEnd = undefined;
    }
    if (!playing) this.localEnd = undefined;
    this.remoteActive = audible;
    return result;
  }
}
