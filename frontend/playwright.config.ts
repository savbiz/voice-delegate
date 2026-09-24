/** Browser checks build and serve the static frontend. */
import { defineConfig } from '@playwright/test';
export default defineConfig({
  testDir: './tests',
  forbidOnly: Boolean(process.env.CI),
  retries: 1,
  use: {
    baseURL: 'http://localhost:4173',
    trace: 'on-first-retry',
    launchOptions: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE
      ? {
          executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE,
          args: ['--disable-gpu', '--no-sandbox'],
        }
      : {},
  },
  webServer: {
    command: 'pnpm build && vite preview --host localhost --strictPort',
    url: 'http://localhost:4173',
    reuseExistingServer: !process.env.CI,
  },
});
