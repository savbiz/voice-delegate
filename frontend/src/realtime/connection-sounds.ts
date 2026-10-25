/** Optional local UI tones; never connected to the microphone or recording graph. */
export class ConnectionSounds {
  private context: AudioContext | undefined;
  private connected = false;
  private closing: ReturnType<typeof setTimeout> | undefined;

  constructor(private readonly createContext = () => new AudioContext()) {}

  arm(enabled: boolean): void {
    this.dispose();
    if (!enabled) return;
    try {
      const context = this.createContext();
      this.context = context;
      void context.resume().catch(() => {
        if (this.context === context) this.dispose();
      });
    } catch {
      this.dispose();
    }
  }

  established(): void {
    if (this.connected || !this.context) return;
    this.connected = true;
    this.play([440, 660]);
  }

  ended(): void {
    if (!this.connected) {
      if (!this.closing) this.dispose();
      return;
    }
    this.connected = false;
    this.play([660, 440]);
    this.closing = setTimeout(() => this.dispose(), 350);
  }

  dispose(): void {
    clearTimeout(this.closing);
    this.closing = undefined;
    const context = this.context;
    this.context = undefined;
    this.connected = false;
    if (context) void context.close().catch(() => undefined);
  }

  private play(frequencies: number[]): void {
    const context = this.context;
    if (!context || context.state !== 'running') return;
    try {
      frequencies.forEach((frequency, index) => {
        const oscillator = context.createOscillator();
        const gain = context.createGain();
        const start = context.currentTime + index * 0.12;
        oscillator.frequency.setValueAtTime(frequency, start);
        gain.gain.setValueAtTime(0, start);
        gain.gain.linearRampToValueAtTime(0.04, start + 0.01);
        gain.gain.linearRampToValueAtTime(0, start + 0.1);
        oscillator.connect(gain);
        gain.connect(context.destination);
        oscillator.onended = () => {
          oscillator.disconnect();
          gain.disconnect();
        };
        oscillator.start(start);
        oscillator.stop(start + 0.11);
      });
    } catch {
      this.dispose();
    }
  }
}
