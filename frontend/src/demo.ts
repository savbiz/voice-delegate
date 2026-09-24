/** Deterministic, offline scenario: timings are illustrative, never measured audio. */
export const scenario = [
  { speaker: 'You', text: 'Hi! What can you help me with?', gap: null },
  {
    speaker: 'Assistant',
    text: 'We can talk naturally. Calculations and project questions go to a separate worker.',
    gap: 240,
  },
  { speaker: 'You', text: 'Calculate (120 + 80) * 1.22.', gap: null },
  {
    speaker: 'Assistant',
    text: 'Simulated worker result: 244. The real offline worker is available from the command line.',
    gap: 310,
  },
] as const;
export function visibleScenario(step: number): (typeof scenario)[number][] {
  return scenario.slice(0, Math.max(0, Math.min(step, scenario.length)));
}
