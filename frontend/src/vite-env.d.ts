/// <reference types="vite/client" />
interface ImportMetaEnv {
  readonly VITE_NATIVE_LIVE?: string;
  readonly VITE_OFFLINE_STACK?: string;
  readonly VITE_API_BASE_URL?: string;
}
interface ImportMeta {
  readonly env: ImportMetaEnv;
}
