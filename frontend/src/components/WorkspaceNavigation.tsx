/** Three peer tabs: live voice first, then the two views that need no microphone or key. */
export type Mode = 'live' | 'demo' | 'reference';

const TABS: { mode: Mode; label: string }[] = [
  { mode: 'live', label: 'Live voice' },
  { mode: 'demo', label: 'Offline example' },
  { mode: 'reference', label: 'Project documentation' },
];

export function WorkspaceNavigation({ mode }: { mode: Mode }) {
  return (
    <nav className="workspace-navigation" aria-label="Workspace">
      {TABS.map((tab) => (
        <a
          key={tab.mode}
          href={`#${tab.mode}`}
          aria-current={mode === tab.mode ? 'page' : undefined}
        >
          {tab.label}
        </a>
      ))}
    </nav>
  );
}
