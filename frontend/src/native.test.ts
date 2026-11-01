import { afterEach, describe, expect, it, vi } from 'vitest';
import { Capacitor } from '@capacitor/core';
import config from '../capacitor.config';
import { nativeEnvironment } from '../scripts/native-build';
import { canStartVoice, nativeVoiceAvailable } from './native';

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllEnvs();
});

describe('native preview boundaries', () => {
  it.each(['ios', 'android', 'other'])('requires voice opt-in on %s', (platform) => {
    expect(nativeVoiceAvailable(platform, false)).toBe(false);
    expect(nativeVoiceAvailable(platform, true)).toBe(true);
  });
  it('preserves browser voice and reads the native build flag', () => {
    expect(nativeVoiceAvailable('web', false)).toBe(true);
    vi.spyOn(Capacitor, 'getPlatform').mockReturnValue('ios');
    vi.stubEnv('VITE_NATIVE_LIVE', 'false');
    expect(canStartVoice()).toBe(false);
    vi.stubEnv('VITE_NATIVE_LIVE', 'true');
    expect(canStartVoice()).toBe(true);
  });
  it('requires explicit packaging and a canonical HTTPS backend', () => {
    expect(() => nativeEnvironment({})).toThrow('opt-in');
    for (const origin of [
      '',
      'http://api.example.test',
      'https://user:pass@api.example.test',
      'https://api.example.test/path',
      'https://api.example.test/',
    ]) {
      expect(() =>
        nativeEnvironment({ VOICE_NATIVE_BUILD: 'true', VITE_API_BASE_URL: origin }),
      ).toThrow();
    }
    const environment = {
      VOICE_NATIVE_BUILD: 'true',
      VITE_API_BASE_URL: 'https://api.example.test',
    };
    expect(nativeEnvironment(environment).VITE_NATIVE_LIVE).toBe('false');
    expect(nativeEnvironment({ ...environment, VITE_NATIVE_LIVE: 'true' }).VITE_NATIVE_LIVE).toBe(
      'true',
    );
  });
  it('packages local assets without a remote page or native HTTP bypass', () => {
    expect(config.webDir).toBe('dist-native');
    expect(config.server?.url).toBeUndefined();
    expect(config.server?.allowNavigation).toBeUndefined();
    expect(config.server?.cleartext).toBe(false);
    expect(config.server?.iosScheme).toBe('capacitor');
    expect(config.server?.androidScheme).toBe('https');
    expect(config.loggingBehavior).toBe('none');
    expect(config.plugins?.CapacitorHttp?.enabled).toBe(false);
  });
});
