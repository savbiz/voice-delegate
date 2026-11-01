import { Button } from './Button';

const modes = [
  { value: 'demo', label: 'Free demo' },
  { value: 'live', label: 'Live voice' },
  { value: 'reference', label: 'Documentation' },
] as const;

export type Mode = (typeof modes)[number]['value'];

export function ModeTabs({ mode, onChange }: { mode: Mode; onChange: (mode: Mode) => void }) {
  return (
    <nav className="mode-tabs" role="tablist" aria-label="Conversation mode">
      {modes.map((tab, index) => (
        <Button
          key={tab.value}
          role="tab"
          id={`tab-${tab.value}`}
          aria-controls="mode-panel"
          aria-selected={mode === tab.value}
          tabIndex={mode === tab.value ? 0 : -1}
          onClick={() => onChange(tab.value)}
          onKeyDown={(event) => {
            const next =
              event.key === 'ArrowRight'
                ? modes[(index + 1) % modes.length]
                : event.key === 'ArrowLeft'
                  ? modes[(index + modes.length - 1) % modes.length]
                  : event.key === 'Home'
                    ? modes[0]
                    : event.key === 'End'
                      ? modes.at(-1)
                      : undefined;
            if (next) {
              event.preventDefault();
              onChange(next.value);
              document.getElementById(`tab-${next.value}`)?.focus();
            }
          }}
        >
          {tab.label}
        </Button>
      ))}
    </nav>
  );
}
