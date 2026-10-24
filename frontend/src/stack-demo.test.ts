import { afterEach, expect, it, vi } from 'vitest';
import { runStackDemo } from './demo';

afterEach(() => vi.unstubAllGlobals());
it('delegates via owned session and closes after the result', async () => {
  const fetch = vi
    .fn()
    .mockResolvedValueOnce(Response.json({ id: 'demo', key: 'owner' }))
    .mockResolvedValueOnce(Response.json({ sdp: 'v=0\r\n' }))
    .mockResolvedValueOnce(Response.json({ delegation: 'completed', recap: { latest_reply: '4' } }))
    .mockResolvedValueOnce(Response.json({ finalized: true }));
  vi.stubGlobal('fetch', fetch);
  expect(await runStackDemo(new AbortController().signal)).toBe('4');
  expect(fetch).toHaveBeenLastCalledWith(
    '/api/sessions/demo/close',
    expect.objectContaining({
      headers: expect.objectContaining({ 'X-Session-Key': 'owner' }),
    }),
  );
});
it('closes an owned session after offer failure without retrying', async () => {
  const fetch = vi
    .fn()
    .mockResolvedValueOnce(Response.json({ id: 'demo', key: 'owner' }))
    .mockResolvedValueOnce(new Response('{}', { status: 503 }))
    .mockResolvedValueOnce(Response.json({ finalized: true }));
  vi.stubGlobal('fetch', fetch);
  await expect(runStackDemo(new AbortController().signal)).rejects.toThrow(
    'Offline stack unavailable',
  );
  expect(fetch).toHaveBeenCalledTimes(3);
});
it('closes if Stop arrives while creation is pending', async () => {
  const controller = new AbortController();
  const fetch = vi
    .fn()
    .mockImplementationOnce(async () => {
      controller.abort();
      return Response.json({ id: 'demo', key: 'owner' });
    })
    .mockResolvedValueOnce(Response.json({ finalized: true }));
  vi.stubGlobal('fetch', fetch);
  await expect(runStackDemo(controller.signal)).rejects.toThrow();
  expect(fetch).toHaveBeenCalledTimes(2);
  expect(fetch.mock.calls[1]?.[0]).toBe('/api/sessions/demo/close');
});
it('bounds response bytes and still closes ownership', async () => {
  const fetch = vi
    .fn()
    .mockResolvedValueOnce(Response.json({ id: 'demo', key: 'owner' }))
    .mockResolvedValueOnce(new Response('x'.repeat(8193)))
    .mockResolvedValueOnce(Response.json({ finalized: true }));
  vi.stubGlobal('fetch', fetch);
  await expect(runStackDemo(new AbortController().signal)).rejects.toThrow('too much data');
  expect(fetch.mock.calls[2]?.[0]).toBe('/api/sessions/demo/close');
});
