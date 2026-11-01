import { copyFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
/** React development server and a same-origin bridge to the Python API. */
import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';
import { nativeEnvironment } from './scripts/native-build.ts';

export default defineConfig(({ mode }) => {
  const native = mode === 'native';
  const api = native ? nativeEnvironment(process.env).VITE_API_BASE_URL : undefined;
  return {
    plugins: [
      {
        name: 'native-content-policy',
        transformIndexHtml(html) {
          if (!native) return [];
          return {
            html: html.replace(
              'width=device-width, initial-scale=1.0',
              'width=device-width, initial-scale=1.0, viewport-fit=cover',
            ),
            tags: [
              {
                tag: 'meta',
                attrs: {
                  'http-equiv': 'Content-Security-Policy',
                  content: `default-src 'self'; script-src 'self'; connect-src 'self' ${api}; style-src 'self'; img-src 'self'; media-src 'self' blob:; object-src 'none'; base-uri 'none'; form-action 'self'`,
                },
                injectTo: 'head-prepend' as const,
              },
            ],
          };
        },
      },
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
    build: {
      outDir: mode === 'native' ? 'dist-native' : 'dist',
      rolldownOptions: { output: { comments: { legal: true } } },
    },
    server: {
      host: '127.0.0.1',
      port: 5173,
      strictPort: true,
      proxy: { '/api': 'http://127.0.0.1:8000' },
    },
    test: { include: ['src/**/*.test.ts'] },
  };
});
