/** Numeric estimates supplied by the owned backend; never a provider invoice. */
export type CostSummary = {
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
  return `${cost.final ? 'Final' : 'Current'} estimate: $${cost.estimated_usd.toFixed(6)}${cost.partial ? ' (partial)' : ''}. Price snapshot ${cost.price_date}. Excludes billing adjustments, discounts and unobserved usage.`;
}
