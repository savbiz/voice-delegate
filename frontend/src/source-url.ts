import type { Source } from './reference';

/** Evidence links never allow script schemes, embedded credentials or non-web sources. */
export function sourceUrl(source: Source): string | undefined {
  if (source.section !== 'Web search' || !source.id.startsWith('web-')) return;
  try {
    const url = new URL(source.path);
    if (url.protocol === 'https:' && !url.username && !url.password) return url.href;
  } catch {
    return;
  }
}
