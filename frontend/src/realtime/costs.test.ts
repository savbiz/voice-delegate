import { expect, test } from 'vitest';
import { costText, type CostSummary } from './costs';

test('cost wording distinguishes partial estimates and final snapshots from billing', () => {
  const value: CostSummary = {
    version: 'v1',
    price_date: '2026-11-02',
    estimated_usd: 0.01,
    components: { voice: 0.01 },
    usage: { worker_calls: 0, decision_calls: 0, web_calls: 0, uncertain: false },
    voice_seconds: 12,
    partial: true,
    unpriced: ['voice.azure.second'],
    final: false,
  };
  expect(costText(value)).toContain('Current estimate: $0.010000 (partial)');
  expect(costText({ ...value, final: true, partial: false })).toContain(
    'Final estimate: $0.010000.',
  );
  expect(costText(value)).toContain('Excludes billing adjustments');
});
