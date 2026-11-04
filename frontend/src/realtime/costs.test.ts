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

test('provider credits and USD remain separate from estimated application costs', () => {
  const value = {
    version: 'v1',
    price_date: '2026-11-02',
    estimated_usd: 0.01,
    components: {},
    usage: { worker_calls: 0, decision_calls: 0, web_calls: 0, uncertain: false },
    voice_seconds: 10,
    partial: true,
    unpriced: ['voice.elevenlabs.second'],
    final: true,
  };
  expect(costText(value)).toContain('ElevenLabs usage has not been reported yet');
  // With a bundled ElevenLabs rate the voice is priced, but the receipt is still pending.
  expect(costText({ ...value, partial: false, unpriced: [], adapters: ['elevenlabs'] })).toContain(
    'ElevenLabs usage has not been reported yet',
  );
  expect(costText({ ...value, unpriced: [], adapters: ['openai'] })).not.toContain('ElevenLabs');
  const text = costText({
    ...value,
    provider_usage: {
      provider: 'elevenlabs',
      credits: 296,
      voice_surcharge_credits: 4,
      usd: 0.012,
    },
  });
  expect(text).toContain('296 base credits');
  expect(text).toContain('4 additional voice surcharge credits');
  expect(text).toContain('$0.012000 reported USD');
  expect(text).toContain('not added to the estimate');
  expect(
    costText({
      ...value,
      provider_usage: {
        provider: 'elevenlabs',
        credits: 0,
        voice_surcharge_credits: null,
        usd: null,
      },
    }),
  ).toContain('0 base credits');
});
