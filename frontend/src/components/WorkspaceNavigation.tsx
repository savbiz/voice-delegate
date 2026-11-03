/** Secondary tools stay discoverable without competing with the voice workspace. */
export type Mode = 'live' | 'demo' | 'reference';

export function WorkspaceNavigation({ mode }: { mode: Mode }) {
  return (
    <nav className="workspace-navigation" aria-label="Workspace">
      <a href="#live" aria-current={mode === 'live' ? 'page' : undefined}>
        Live voice
      </a>
      <details open={mode !== 'live' ? true : undefined}>
        <summary>Tools &amp; examples</summary>
        <p className="muted">Explore the project without starting a voice conversation.</p>
        <a href="#demo" aria-current={mode === 'demo' ? 'page' : undefined}>
          Offline example
        </a>
        <a href="#reference" aria-current={mode === 'reference' ? 'page' : undefined}>
          Project documentation
        </a>
      </details>
    </nav>
  );
}
