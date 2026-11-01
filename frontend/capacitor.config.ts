import type { CapacitorConfig } from '@capacitor/cli';

const config: CapacitorConfig = {
  appId: 'io.github.savbiz.voicedelegate',
  appName: 'voice-delegate',
  webDir: 'dist-native',
  loggingBehavior: 'none',
  server: {
    hostname: 'localhost',
    iosScheme: 'capacitor',
    androidScheme: 'https',
    cleartext: false,
  },
  ios: { webContentsDebuggingEnabled: false },
  android: { webContentsDebuggingEnabled: false, allowMixedContent: false },
  plugins: { CapacitorHttp: { enabled: false }, CapacitorCookies: { enabled: false } },
};
export default config;
