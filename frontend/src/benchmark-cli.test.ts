/** Safety gates must reject a paid run before opening a browser or provider session. */
import { spawnSync } from 'node:child_process';
import { describe, expect, it } from 'vitest';

describe('voice benchmark CLI opt-ins', () => {
  it.each([['--live'], ['--live', '--allow-paid']])(
    'rejects incomplete authorization: %s',
    (...flags) => {
      const result = spawnSync(process.execPath, ['benchmarks/run.ts', ...flags], {
        cwd: process.cwd(),
        env: { ...process.env, VOICE_BENCHMARK_LIVE: '' },
        encoding: 'utf8',
        timeout: 5000,
      });
      expect(result.status).toBe(1);
      expect(result.stderr).toContain('Live runs require both opt-ins');
    },
  );
});
