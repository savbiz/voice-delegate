import type { BeforeSendEvent } from '@vercel/analytics';

/** Hosted deployments run on Vercel; every other origin (local, Codespaces, native) is never counted. */
export const ANALYTICS_HOST_SUFFIX = '.vercel.app';

export interface AnalyticsContext {
  production: boolean;
  native: boolean;
  hostname: string;
  doNotTrack: string | null | undefined;
}

/** Visitor counting is opt-out friendly and limited to the hosted production build. */
export function shouldCountVisitors(context: AnalyticsContext): boolean {
  if (!context.production || context.native) return false;
  if (context.doNotTrack === '1' || context.doNotTrack === 'yes') return false;
  return context.hostname.endsWith(ANALYTICS_HOST_SUFFIX);
}

/** Sends only the origin and path, never the query string or the hash. */
export function stripLocation(event: BeforeSendEvent): BeforeSendEvent | null {
  try {
    const url = new URL(event.url);
    return { ...event, url: `${url.origin}${url.pathname}` };
  } catch {
    return null;
  }
}
