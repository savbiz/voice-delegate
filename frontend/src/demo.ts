/** Deterministic, offline scenario: timings are illustrative, never measured audio. */
export const scenario = [
  { speaker: 'You', text: 'Hi! What can you help me with?', gap: null },
  { speaker: 'Assistant', text: 'We can talk naturally. Longer tasks will go to a delegated worker in M2.', gap: 240 },
  { speaker: 'You', text: 'Can you plan a weekend trip?', gap: null },
  { speaker: 'Assistant', text: 'That needs a worker. This M1 demo does not execute tasks or make bookings.', gap: 310 },
] as const;
export function visibleScenario(step: number): (typeof scenario)[number][] { return scenario.slice(0, Math.max(0, Math.min(step, scenario.length))); }
