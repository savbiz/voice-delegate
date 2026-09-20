/** React shell separating a free scripted demo from the live WebRTC lifecycle. */
import { StrictMode, useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { mountLive } from './realtime/live';
import { scenario, visibleScenario } from './demo';
import './style.css';

function Live({ code }: { code: string }) {
  const root = useRef<HTMLDivElement>(null);
  useEffect(() => root.current ? mountLive(root.current, code) : undefined, [code]);
  return <div ref={root}>
    <p className="notice">Live voice requires a server API key and incurs provider usage charges. Your microphone is requested only when you start.</p>
    <div className="actions"><button id="start">Start conversation</button><button id="stop" disabled>Stop</button></div>
    <p id="status" role="status">Ready to connect</p>
    <audio id="audio" controls autoPlay aria-label="Assistant audio" />
    <div className="grid gap-4 md:grid-cols-2"><section><h2>You</h2><p id="user">—</p></section><section><h2>Assistant</h2><p id="assistant">—</p></section></div>
    <section><h2>Turn timing</h2><p className="muted">Transcript timestamp gap: a proxy, not measured audio latency. May be negative during overlap.</p><ol id="timings" /></section>
  </div>;
}
function Demo() {
  const [step, setStep] = useState(0);
  const [running, setRunning] = useState(false);
  useEffect(() => {
    if (!running) return;
    const timer = setInterval(() => setStep(previous => Math.min(previous + 1, scenario.length)), 900);
    return () => clearInterval(timer);
  }, [running]);
  useEffect(() => { if (step === scenario.length) setRunning(false); }, [step]);
  return <>
    <p className="notice">Simulated demo · No API key, network requests, microphone or generated audio. Timing values are illustrative.</p>
    <div className="actions"><button disabled={running} onClick={() => { setStep(0); setRunning(true); }}>Start demo</button><button disabled={!running} onClick={() => setRunning(false)}>Stop demo</button></div>
    <p role="status">{running ? 'Playing recorded scenario…' : step ? 'Demo stopped' : 'Ready — try the free demo'}</p>
    <div aria-live="polite" className="space-y-3">{visibleScenario(step).map((turn, i) => <section key={i}><h2>{turn.speaker}</h2><p>{turn.text}</p>{turn.gap !== null && <span className="badge">{turn.gap} ms · simulated</span>}</section>)}</div>
  </>;
}
function App() {
  const [mode, setMode] = useState('demo');
  const [code, setCode] = useState('');
  return <main className="mx-auto max-w-4xl px-6 py-12">
    <header className="mb-10"><span className="badge">OPEN REFERENCE · M1 PREVIEW</span><h1 className="mt-5 text-5xl font-semibold tracking-tight">voice-delegate<span className="text-emerald-400">.</span></h1><p className="mt-4 text-lg text-slate-400">A fast voice conversation. A separate worker for the heavy lifting.</p></header>
    <nav className="actions" aria-label="Conversation mode"><button aria-pressed={mode === 'demo'} onClick={() => setMode('demo')}>Free demo</button><button aria-pressed={mode === 'live'} onClick={() => setMode('live')}>Live voice</button></nav>
    {mode === 'live' && <label className="block my-5">Deployment access code <input type="password" autoComplete="off" value={code} onChange={e => setCode(e.target.value)} placeholder="Only if configured on the server" /></label>}
    {mode === 'demo' ? <Demo /> : <Live code={code} />}
    <footer className="mt-12 border-t border-slate-800 pt-6 text-sm text-slate-500">React 19 · FastAPI · WebRTC<br />M1: session lifecycle and voice transport. Delegated worker arrives in M2.</footer>
  </main>;
}
createRoot(document.getElementById('root')!).render(<StrictMode><App /></StrictMode>);
