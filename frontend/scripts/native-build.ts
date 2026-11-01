import { spawnSync } from 'node:child_process';
import { existsSync, readFileSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';

export function nativeEnvironment(environment: NodeJS.ProcessEnv): NodeJS.ProcessEnv {
  if (environment.VOICE_NATIVE_BUILD !== 'true')
    throw new Error('Native packaging is opt-in: set VOICE_NATIVE_BUILD=true.');
  const base = environment.VITE_API_BASE_URL ?? '';
  let parsed: URL;
  try {
    parsed = new URL(base);
  } catch {
    throw new Error('Set VITE_API_BASE_URL to the backend HTTPS origin before native packaging.');
  }
  if (parsed.protocol !== 'https:' || base !== parsed.origin)
    throw new Error('Native packaging requires a canonical HTTPS API origin without a path.');
  return {
    ...environment,
    VITE_NATIVE_LIVE: environment.VITE_NATIVE_LIVE === 'true' ? 'true' : 'false',
  };
}

function main() {
  const operation = process.argv[2];
  if (operation !== 'build' && operation !== 'sync')
    throw new Error('Choose native:build or native:sync.');
  const environment = nativeEnvironment(process.env);
  const project = 'ios/App/App.xcodeproj/project.pbxproj';
  if (existsSync(project)) {
    const version = (JSON.parse(readFileSync('package.json', 'utf8')) as { version: string })
      .version;
    if (!/^\d+\.\d+\.\d+$/.test(version))
      throw new Error('Native packaging requires a release version.');
    writeFileSync(
      project,
      readFileSync(project, 'utf8').replace(
        /MARKETING_VERSION = [^;]+;/g,
        `MARKETING_VERSION = ${version};`,
      ),
    );
  }
  const run = (arguments_: string[]) => {
    const result = spawnSync('pnpm', arguments_, { env: environment, stdio: 'inherit' });
    if (result.error) throw new Error('Could not start native build tooling.');
    if (result.status !== 0)
      throw new Error('Native build or sync failed; inspect the tooling output.');
  };
  run(['build', '--mode', 'native']);
  if (operation === 'sync') run(['exec', 'cap', 'sync']);
}

if (process.argv[1] && pathToFileURL(resolve(process.argv[1])).href === import.meta.url) {
  try {
    main();
  } catch (error) {
    console.error(error instanceof Error ? error.message : 'Native packaging failed.');
    process.exitCode = 1;
  }
}
