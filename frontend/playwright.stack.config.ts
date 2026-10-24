import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './stack-tests',
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  use: { baseURL: 'http://127.0.0.1:5174', trace: 'on-first-retry' },
  webServer: {
    command:
      'VITE_OFFLINE_STACK=true pnpm build && pnpm exec vite preview --host 127.0.0.1 --port 5174 --strictPort',
    url: 'http://127.0.0.1:5174',
    reuseExistingServer: false,
  },
});
