/** Numeric estimates supplied by the owned backend; never a provider invoice. */
export type CostSummary = {
  provider_usage?: {
    provider: 'elevenlabs';
    credits: number | null;
    voice_surcharge_credits: number | null;
    usd: number | null;
  } | null;
  adapters?: string[];
  version: string;
  price_date: string;
  estimated_usd: number;
  components: Record<string, number>;
  usage: { worker_calls: number; decision_calls: number; web_calls: number; uncertain: boolean };
  voice_seconds: number;
  partial: boolean;
  unpriced: string[];
  final: boolean;
};

export function costText(cost: CostSummary): string {
  const reported = cost.provider_usage;
  const details = reported
    ? [
        reported.credits === null ? undefined : `${reported.credits} base credits`,
        reported.voice_surcharge_credits === null
          ? undefined
          : `${reported.voice_surcharge_credits} additional voice surcharge credits`,
        reported.usd === null ? undefined : `$${reported.usd.toFixed(6)} reported USD`,
      ].filter(Boolean)
    : [];
  const receipt = details.length
    ? ` ElevenLabs reports: ${details.join('; ')}. Shown separately, not added to the estimate.`
    : cost.adapters?.includes('elevenlabs') || cost.unpriced.includes('voice.elevenlabs.second')
      ? ' ElevenLabs usage has not been reported yet.'
      : '';
  return `${cost.final ? 'Final' : 'Current'} estimate: $${cost.estimated_usd.toFixed(6)}${cost.partial ? ' (partial)' : ''}. Price snapshot ${cost.price_date}. Excludes billing adjustments, discounts and unobserved usage.${receipt}`;
}
