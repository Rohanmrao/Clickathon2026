import type { Factor } from "../types";

// Which factor moved (requests / fill / eCPM) before which segment.
export function FactorSplit({ factors, primary }: { factors: Factor[]; primary: string }) {
  return (
    <section className="card">
      <h3>Factor split</h3>
      {factors.map((f) => (
        <div key={f.factor} className="bar-row">
          <span className="bar-label">
            {f.factor} {f.factor === primary ? "★" : ""}
          </span>
          <span className="bar-track">
            <span className="bar-fill" style={{ width: `${Math.abs(f.contribution_pct) * 100}%` }} />
          </span>
          <span className="bar-val">{Math.round(f.contribution_pct * 100)}%</span>
        </div>
      ))}
    </section>
  );
}
