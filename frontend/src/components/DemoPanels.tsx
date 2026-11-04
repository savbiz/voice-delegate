import { useEffect, useRef, useState } from 'react';
import { Button } from './Button';
import { runStackDemo, scenario, visibleScenario } from '../demo';

/** Offline examples: the scripted browser demo and the optional local demo stack. */
export function StackDemo() {
  const [staticDemo, setStaticDemo] = useState(false);
  const [result, setResult] = useState('Ready to run 2 + 2 through the offline worker.');
  const [busy, setBusy] = useState(false);
  const pending = useRef<AbortController | undefined>(undefined);
  useEffect(() => () => pending.current?.abort(), []);
  if (staticDemo) return <StaticDemo />;
  return (
    <>
      <p className="notice">
        Offline stack · Fake voice provider, real backend and LangGraph worker. No microphone,
        generated audio or paid calls.
      </p>
      <div className="actions">
        <Button
          disabled={busy}
          onClick={() => {
            const controller = new AbortController();
            pending.current = controller;
            setBusy(true);
            setResult('Delegating 2 + 2 to the worker…');
            void runStackDemo(controller.signal)
              .then((text) => {
                if (!controller.signal.aborted) setResult(`Worker result: ${text}`);
              })
              .catch((error: unknown) => {
                if (!controller.signal.aborted)
                  setResult(error instanceof Error ? error.message : 'Offline stack unavailable.');
              })
              .finally(() => {
                if (pending.current === controller) setBusy(false);
              });
          }}
        >
          Run offline worker
        </Button>
        <Button
          disabled={!busy}
          onClick={() => {
            pending.current?.abort();
            setResult('Demo stopped.');
          }}
        >
          Stop demo
        </Button>
      </div>
      <p role="status">{result}</p>
      <Button disabled={busy} onClick={() => setStaticDemo(true)}>
        Use static demo instead
      </Button>
      <p>
        Open Grafana on port 3000 to inspect backend metrics. No audio latency is measured in this
        demo.
      </p>
    </>
  );
}

export function StaticDemo() {
  const [step, setStep] = useState(0);
  const [running, setRunning] = useState(false);
  useEffect(() => {
    if (!running) return;
    const timer = setInterval(
      () => setStep((previous) => Math.min(previous + 1, scenario.length)),
      900,
    );
    return () => clearInterval(timer);
  }, [running]);
  useEffect(() => {
    if (step === scenario.length) setRunning(false);
  }, [step]);
  return (
    <>
      <p className="notice">
        Simulated demo · No API key, network requests, microphone or generated audio. Timing values
        are illustrative.
      </p>
      <div className="actions">
        <Button
          disabled={running}
          onClick={() => {
            setStep(0);
            setRunning(true);
          }}
        >
          Start demo
        </Button>
        <Button disabled={!running} onClick={() => setRunning(false)}>
          Stop demo
        </Button>
      </div>
      <p role="status">
        {running
          ? 'Playing recorded scenario…'
          : step
            ? 'Demo stopped'
            : 'Ready — play the offline example'}
      </p>
      <div aria-live="polite" className="space-y-3">
        {visibleScenario(step).map((turn, i) => (
          <section key={i}>
            <h2>{turn.speaker}</h2>
            <p>{turn.text}</p>
            {turn.gap !== null && <span className="badge">{turn.gap} ms · simulated</span>}
          </section>
        ))}
      </div>
    </>
  );
}
