/** Explicit opt-in benchmark CLI. No microphone, provider key, transcript or HTTP trace recording. */
import { chromium } from '@playwright/test';
import { createHash } from 'node:crypto';
import { execFileSync } from 'node:child_process';
import { createServer } from 'node:http';
import { mkdir, readFile, realpath, stat, writeFile } from 'node:fs/promises';
import { dirname, isAbsolute, relative, resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';
import { parseArgs } from 'node:util';
import { probe } from './probe.ts';

const root = fileURLToPath(new URL('../../', import.meta.url));
const { values } = parseArgs({
  options: {
    live: { type: 'boolean', default: false },
    'allow-paid': { type: 'boolean', default: false },
    provider: { type: 'string', default: 'fake' },
    model: { type: 'string', default: 'loopback-tone' },
    api: { type: 'string', default: 'http://127.0.0.1:8000' },
    recordings: { type: 'string' },
    output: { type: 'string', default: '../.local/benchmarks/browser.json' },
    trials: { type: 'string', default: '1' },
    'max-sessions': { type: 'string', default: '0' },
  },
});
const trials = Number(values.trials);
const maxSessions = Number(values['max-sessions']);
const dirty = Boolean(
  execFileSync('git', ['status', '--porcelain'], { cwd: root, encoding: 'utf8' }).trim(),
);
const providers = ['live', 'realtime', 'azure'];
const datasetBytes = await readFile(resolve(root, 'evals/data/voice-v1.json'));
const dataset = JSON.parse(datasetBytes.toString()) as {
  cases: { id: string; utterance: string; label: string }[];
};
if (!Number.isInteger(trials) || trials < 1 || trials > 2) throw new Error('Use one or two trials');
if (
  values.live &&
  (!values['allow-paid'] ||
    process.env.VOICE_BENCHMARK_LIVE !== 'true' ||
    !providers.includes(values.provider) ||
    !values.recordings ||
    !Number.isInteger(maxSessions) ||
    maxSessions !== dataset.cases.length * trials)
)
  throw new Error(
    'Live runs require both opt-ins, recordings, a provider and an exact session budget',
  );
const api = new URL(values.api);
if (
  !['http:', 'https:'].includes(api.protocol) ||
  api.username ||
  api.password ||
  api.search ||
  api.hash ||
  api.pathname !== '/' ||
  (api.protocol === 'http:' && !['localhost', '127.0.0.1'].includes(api.hostname))
)
  throw new Error('Use a canonical HTTPS API origin or local HTTP origin');
if (values.model.length > 100) throw new Error('Model label too long');
if (values.live && dirty) throw new Error('Commit the benchmark source before a live run');

type Clip = { wav: string; speechEndMs: number; sha256: string };
const clips = new Map<string, Clip>();
if (values.live && values.recordings) {
  const folder = await realpath(values.recordings);
  const manifestPath = resolve(folder, 'manifest.json');
  if ((await stat(manifestPath)).size > 65536) throw new Error('Manifest too large');
  const manifest = JSON.parse(await readFile(manifestPath, 'utf8')) as Record<
    string,
    { file: string; sha256: string; speech_end_ms: number }
  >;
  // Validate every recording before the first potentially billable session.
  for (const entry of dataset.cases) {
    const clip = manifest[entry.id];
    if (!clip || !Number.isFinite(clip.speech_end_ms) || clip.speech_end_ms <= 0)
      throw new Error('Missing recording or speech boundary');
    const path = await realpath(resolve(folder, clip.file));
    const local = relative(folder, path);
    if (isAbsolute(local) || local === '..' || local.startsWith(`..${sep}`))
      throw new Error('Recording must stay inside its folder');
    if ((await stat(path)).size > 1_000_000) throw new Error('Recording exceeds one megabyte');
    const bytes = await readFile(path);
    const hash = createHash('sha256').update(bytes).digest('hex');
    if (
      bytes.toString('ascii', 0, 4) !== 'RIFF' ||
      bytes.toString('ascii', 8, 12) !== 'WAVE' ||
      hash !== clip.sha256 ||
      clip.speech_end_ms > 10000
    )
      throw new Error('Invalid WAV, hash or speech boundary');
    clips.set(entry.id, {
      wav: bytes.toString('base64'),
      speechEndMs: clip.speech_end_ms,
      sha256: hash,
    });
  }
}

const server = createServer((_request, response) => {
  response.writeHead(200, { 'Content-Type': 'text/html', 'Cache-Control': 'no-store' });
  response.end('<!doctype html><title>Local voice benchmark</title>');
});
await new Promise<void>((resolve, reject) => {
  server.once('error', reject);
  server.listen(4175, '127.0.0.1', resolve);
});
const output = resolve(values.output);
await mkdir(dirname(output), { recursive: true });
const browser = await chromium.launch({
  args: [
    '--autoplay-policy=no-user-gesture-required',
    ...(!values.live ? ['--disable-features=WebRtcHideLocalIpsWithMdns'] : []),
  ],
  ...(process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE
    ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE }
    : {}),
});
const capture = {
  schema_version: 1,
  mode: values.live ? 'live' : 'offline',
  provider: values.live ? values.provider : 'fake',
  model: values.live ? values.model : 'loopback-tone',
  model_source: values.live ? 'operator-declared' : 'scripted',
  revision: execFileSync('git', ['rev-parse', 'HEAD'], { cwd: root, encoding: 'utf8' }).trim(),
  working_tree_dirty: dirty,
  dataset_sha256: createHash('sha256').update(datasetBytes).digest('hex'),
  recorded_at: new Date().toISOString(),
  browser: `Chromium ${browser.version()} headless`,
  trials,
  observations: [] as object[],
};
try {
  for (let trial = 1; trial <= trials; trial++) {
    for (const entry of dataset.cases) {
      const page = await browser.newPage();
      // Offline runs are restricted to the blank local harness and loopback WebRTC.
      if (!values.live)
        await page.route('**/*', (route) =>
          new URL(route.request().url()).origin === 'http://127.0.0.1:4175'
            ? route.continue()
            : route.abort(),
        );
      try {
        await page.goto('http://127.0.0.1:4175');
        const clip = clips.get(entry.id);
        const observation = await page.evaluate(probe, {
          fake: !values.live,
          api: api.origin,
          invitation: process.env.VOICE_BENCHMARK_INVITATION,
          wav: clip?.wav,
          speechEndMs: clip?.speechEndMs ?? 200,
          timeoutMs: 15000,
        });
        capture.observations.push({
          case_id: entry.id,
          trial,
          ...observation,
          input_sha256: clip?.sha256 ?? null,
          speech_end_ms: clip?.speechEndMs ?? null,
        });
        // Preserve all completed attempts if a later browser failure interrupts the run.
        await writeFile(output, `${JSON.stringify(capture, null, 2)}\n`, { mode: 0o600 });
        console.log(`${entry.id} trial=${trial} outcome=${observation.outcome}`);
      } finally {
        await page.close();
      }
    }
  }
} finally {
  await browser.close();
  server.close();
}
