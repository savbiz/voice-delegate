import { useEffect, useRef, useState } from 'react';

export type Source = { id: string; title: string; path: string; section: string; text: string; digest: string };

export function Reference({ code }: { code: string }) {
  const [query, setQuery] = useState('How does fallback preserve history?');
  const [sources, setSources] = useState<Source[]>([]);
  const [status, setStatus] = useState('Search the bundled public project documentation.');
  const [busy, setBusy] = useState(false);
  const pending = useRef<AbortController | undefined>(undefined);
  useEffect(() => () => { pending.current?.abort(); }, [code]);
  async function search() {
    pending.current?.abort();
    const controller = new AbortController();
    pending.current = controller;
    setBusy(true); setSources([]); setStatus('Searching…');
    try {
      const response = await fetch(`${import.meta.env.VITE_API_BASE_URL ?? ''}/api/reference/search`, {
        method: 'POST', headers: { 'Content-Type': 'application/json', ...(code ? { Authorization: `Bearer ${code}` } : {}) },
        body: JSON.stringify({ query }), signal: AbortSignal.any([controller.signal, AbortSignal.timeout(10000)]),
      });
      if (!response.ok) throw new Error(response.status === 401 ? 'Enter a valid personal invitation code.' : 'Documentation search is unavailable.');
      const data = await response.json() as { sources: Source[] };
      if (controller.signal.aborted) return;
      setSources(data.sources);
      setStatus(data.sources.length ? `${data.sources.length} source excerpts found. Open a source to inspect the evidence.` : 'No supporting documentation found. Try another project topic.');
    } catch (error) {
      if (!controller.signal.aborted) setStatus(error instanceof Error ? error.message : 'Search failed.');
    } finally { if (pending.current === controller) setBusy(false); }
  }
  return <section>
    <h2>Ask the project documentation</h2>
    <p className="notice">Read-only search · No microphone or paid model calls. Results quote a bundled documentation snapshot, not the live web or your server settings.</p>
    <form onSubmit={event => { event.preventDefault(); void search(); }}>
      <label>Project question <input value={query} maxLength={500} onChange={event => setQuery(event.target.value)} /></label>
      <button disabled={busy || !query.trim()}>Search documentation</button>
    </form>
    <p role="status">{status}</p>
    <ol className="space-y-3">{sources.map((source, index) => <li key={source.id}>
      <details><summary>[{index + 1}] {source.title} — {source.section}</summary>
        <p className="muted">{source.path}</p>
        <blockquote className="whitespace-pre-wrap">{source.text}</blockquote>
        <small>Snapshot source: {source.id}</small>
      </details>
    </li>)}</ol>
  </section>;
}
