/** Browser smoke tests run entirely against the static frontend. */
import { defineConfig } from '@playwright/test';
export default defineConfig({ testDir: './tests', use: { baseURL: 'http://localhost:4173' }, webServer: { command: 'pnpm preview --host localhost', url: 'http://localhost:4173', reuseExistingServer: !process.env.CI } });
