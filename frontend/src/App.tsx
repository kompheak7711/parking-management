export interface AppProps {
  environment: string;
  buildId: string;
}

export function App({ environment, buildId }: AppProps) {
  return (
    <div className="app-shell">
      <header className="app-header">
        <p className="eyebrow">Staff application</p>
        <h1>Property Rental Management</h1>
      </header>

      <main aria-label="Application status" className="app-content">
        <p>The frontend foundation is ready.</p>
        <p>No business workflows are available in this bootstrap tranche.</p>
      </main>

      <footer aria-label="Build information" className="app-footer">
        {environment !== "production" && (
          <span className="environment">{environment}</span>
        )}
        <span>Build {buildId}</span>
      </footer>
    </div>
  );
}
