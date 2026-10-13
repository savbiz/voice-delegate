import { copyFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
/** React development server and a same-origin bridge to the Python API. */
import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';
// Vite 8 makes esbuild optional; preserve this policy if its compatibility path is used.
const esbuild = { include: /\.[jt]sx?$/, legalComments: 'eof' as const };

export default defineConfig({
  plugins: [
    {
      name: 'third-party-notices',
      buildStart() {
        copyFileSync(
          fileURLToPath(new URL('../THIRD_PARTY_NOTICES.md', import.meta.url)),
          fileURLToPath(new URL('./public/third-party-notices.txt', import.meta.url)),
        );
      },
    },
    react(),
    tailwindcss(),
  ],
  esbuild,
  build: { rolldownOptions: { output: { comments: { legal: true } } } },
  server: {
    host: '127.0.0.1',
    port: 5173,
    strictPort: true,
    proxy: { '/api': 'http://127.0.0.1:8000' },
  },
  test: { include: ['src/**/*.test.ts'] },
});
