import { describe, expect, it } from 'vitest';
import { shouldCountVisitors, stripLocation, type AnalyticsContext } from './analytics';

const hosted: AnalyticsContext = {
  production: true,
  native: false,
  hostname: 'voice-delegate.vercel.app',
  doNotTrack: null,
};

describe('visitor counting', () => {
  it('counts the hosted production site', () => {
    expect(shouldCountVisitors(hosted)).toBe(true);
  });

  it.each([
    ['development builds', { production: false }],
    ['the native shells', { native: true }],
    ['local development', { hostname: 'localhost' }],
    ['Codespaces forwarding', { hostname: 'abc-8080.app.github.dev' }],
    ['a look-alike host', { hostname: 'vercel.app.example.org' }],
    ['Do Not Track', { doNotTrack: '1' }],
    ['the legacy Do Not Track value', { doNotTrack: 'yes' }],
  ])('does not count %s', (_name, override) => {
    expect(shouldCountVisitors({ ...hosted, ...override })).toBe(false);
  });

  it('keeps only the origin and path of a page view', () => {
    const event = stripLocation({
      type: 'pageview',
      url: 'https://voice-delegate.vercel.app/path?code=secret#live',
    });
    expect(event).toEqual({
      type: 'pageview',
      url: 'https://voice-delegate.vercel.app/path',
    });
  });

  it('drops an event whose address cannot be parsed', () => {
    expect(stripLocation({ type: 'event', url: 'not a url' })).toBeNull();
  });
});
