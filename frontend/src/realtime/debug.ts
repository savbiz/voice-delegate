/** Select numeric audio diagnostics; never upload candidate addresses or full RTC reports. */
export type DebugSample = {
  event: 'stats' | 'local_onset' | 'client_stop' | 'peer_state' | 'channel_closed';
  peer_state?: RTCPeerConnectionState;
  packets_lost?: number;
  packets_received?: number;
  jitter_seconds?: number;
  concealed_samples?: number;
  audio_level?: number;
};
export function audioSample(report: Record<string, unknown>): DebugSample | undefined {
  if (report.type !== 'inbound-rtp' || report.kind !== 'audio') return;
  const sample: DebugSample = { event: 'stats' };
  const fields = {
    packetsLost: 'packets_lost',
    packetsReceived: 'packets_received',
    jitter: 'jitter_seconds',
    concealedSamples: 'concealed_samples',
    audioLevel: 'audio_level',
  } as const;
  for (const [key, target] of Object.entries(fields)) {
    const value = report[key];
    if (typeof value === 'number' && Number.isFinite(value) && value >= 0) sample[target] = value;
  }
  return sample;
}
