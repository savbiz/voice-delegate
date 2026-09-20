/** Browser smoke tests run entirely against the static frontend. */
import { defineConfig } from '@playwright/test';
export default defineConfig({ testDir: './tests', use: { baseURL: 'http://localhost:4173', launchOptions: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE, args: ['--disable-gpu', '--no-sandbox'] } : {} }, webServer: { command: 'node node_modules/vite/bin/vite.js preview --host localhost', url: 'http://localhost:4173', reuseExistingServer: !process.env.CI } });
