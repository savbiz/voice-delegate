/** React shell separating a free scripted demo from the live WebRTC lifecycle. */
import { useEffect, useState } from 'react';
import { canStartVoice } from './native';
import { WorkspaceNavigation } from './components/WorkspaceNavigation';
import type { Mode } from './components/WorkspaceNavigation';
import { Reference } from './reference';
import { version } from '../package.json';
import { readInvitation, saveInvitation } from './invitation';
import { LiveWorkspace as Live } from './components/LiveWorkspace';
import { StackDemo, StaticDemo } from './components/DemoPanels';

function readMode(): Mode {
  const hash = window.location.hash.slice(1);
  if (hash === 'live' || hash === 'demo' || hash === 'reference') return hash;
  return import.meta.env.VITE_OFFLINE_STACK === 'true' || !canStartVoice() ? 'demo' : 'live';
}

export default function App() {
  const [mode, setMode] = useState<Mode>(readMode);
  useEffect(() => {
    const navigate = () => setMode(readMode());
    window.addEventListener('hashchange', navigate);
    return () => window.removeEventListener('hashchange', navigate);
  }, []);
  const [code, setCode] = useState(readInvitation);
  useEffect(() => {
    saveInvitation(code);
  }, [code]);
  return (
    <main className="app-shell">
      <header className="app-header">
        <span className="badge">OPEN REFERENCE · {version}</span>
        <h1 className="brand-title">
          voice-delegate<span className="brand-accent">.</span>
        </h1>
        <p className="app-pitch">
          A fast voice conversation. A separate worker for the heavy lifting.
        </p>
      </header>
      <WorkspaceNavigation mode={mode} />
      <div
        id="mode-panel"
        role="region"
        aria-label={
          mode === 'live'
            ? 'Voice conversation'
            : mode === 'demo'
              ? 'Offline example'
              : 'Project documentation'
        }
      >
        {mode === 'reference' && (
          <label className="block my-5">
            Personal invitation code{' '}
            <input
              type="password"
              autoComplete="off"
              value={code}
              onChange={(e) => setCode(e.target.value)}
              placeholder="Only if configured on the server"
            />
          </label>
        )}
        {mode === 'demo' ? (
          import.meta.env.VITE_OFFLINE_STACK === 'true' ? (
            <StackDemo />
          ) : (
            <StaticDemo />
          )
        ) : mode === 'reference' ? (
          <Reference code={code} />
        ) : (
          <Live code={code} onCode={setCode} />
        )}
      </div>
      <footer className="app-footer">
        React 19 · FastAPI · WebRTC
        <br />
        Background tasks · Session costs · Opt-in Azure recovery.
        <br />
        <a href="/third-party-notices.txt" className="underline">
          Third-party notices
        </a>
      </footer>
    </main>
  );
}
