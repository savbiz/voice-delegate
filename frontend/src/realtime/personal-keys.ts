import type { PersonalKeys } from '../components/ApiAccess';

/** Session preferences sent at creation, and validation of personal keys before sending. */
export type Preferences = {
  language: string;
  mode: string;
  azure_recovery?: boolean;
  debug_recording?: boolean;
  adapter?: string;
};
const SECRET_FIELDS = [
  'openai_key',
  'tavily_key',
  'elevenlabs_key',
  'azure_key',
  'elevenlabs_webhook_token',
] as const;

/** Trim pasted values and explain mistakes before anything is sent or cleared. */
export function cleanPersonalKeys(keys: PersonalKeys, preferences: Preferences): PersonalKeys {
  const cleaned: PersonalKeys = {};
  for (const [name, value] of Object.entries(keys) as [keyof PersonalKeys, string | undefined][]) {
    const trimmed = value?.trim();
    if (trimmed) cleaned[name] = trimmed;
  }
  for (const name of SECRET_FIELDS)
    if (cleaned[name] && !/^[\x21-\x7e]+$/.test(cleaned[name]))
      throw new Error(
        'Keys and tokens cannot contain spaces, line breaks or non-ASCII characters.',
      );
  if (preferences.adapter === 'azure' || preferences.azure_recovery) {
    let origin: URL | undefined;
    try {
      origin = cleaned.azure_endpoint ? new URL(cleaned.azure_endpoint) : undefined;
    } catch {
      origin = undefined;
    }
    if (!origin || origin.protocol !== 'https:' || !origin.hostname.endsWith('.openai.azure.com'))
      throw new Error(
        'The Azure resource origin must look like https://<resource>.openai.azure.com (no path).',
      );
    cleaned.azure_endpoint = origin.origin;
    if (cleaned.azure_deployment && !/^[A-Za-z0-9._-]+$/.test(cleaned.azure_deployment))
      throw new Error(
        'The Azure deployment name may contain only letters, digits, dots, hyphens and underscores.',
      );
  }
  return cleaned;
}
