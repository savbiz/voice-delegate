import { describe, expect, it } from 'vitest';
import { sourceUrl } from './source-url';
import type { Source } from './reference';

const source: Source = {
  id: 'web-example',
  title: 'Notice',
  path: 'https://example.org/news',
  section: 'Web search',
  text: 'A public update.',
  digest: 'test',
};

describe('web evidence links', () => {
  it('links public HTTPS evidence and leaves bundled documentation alone', () => {
    expect(sourceUrl(source)).toBe('https://example.org/news');
    expect(
      sourceUrl({ ...source, section: 'Architecture', path: 'docs/architecture.md' }),
    ).toBeUndefined();
  });
  it.each([
    'javascript:alert(1)',
    'http://example.org',
    'https://user:pass@example.org',
    'not a URL',
  ])('rejects unsafe target %s', (path) => {
    expect(sourceUrl({ ...source, path })).toBeUndefined();
  });
});
