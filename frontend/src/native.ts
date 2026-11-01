import { Capacitor } from '@capacitor/core';

export function nativeVoiceAvailable(platform: string, enabled: boolean): boolean {
  return platform === 'web' || enabled;
}

export function canStartVoice(): boolean {
  return nativeVoiceAvailable(Capacitor.getPlatform(), import.meta.env.VITE_NATIVE_LIVE === 'true');
}

export function isNativeClient(): boolean {
  return Capacitor.isNativePlatform();
}
