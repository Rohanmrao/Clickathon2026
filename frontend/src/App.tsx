import { useEffect, useState } from "react";
import { investigate } from "./api";
import { DiagnosisCard } from "./components/DiagnosisCard";
import { FactorSplit } from "./components/FactorSplit";
import { MetricTree } from "./components/MetricTree";
import { RuledOutPanel } from "./components/RuledOutPanel";
import type { EvidenceBundle } from "./types";

export default function App() {
  const [bundle, setBundle] = useState<EvidenceBundle | null>(null);
  const [loading, setLoading] = useState(false);

  const run = () => {
    setLoading(true);
    investigate("revenue").then((b) => {
      setBundle(b);
      setLoading(false);
    });
  };

  useEffect(run, []);

  return (
    <div className="app">
      <header>
        <h1>Automated Root-Cause Analyst</h1>
        <button onClick={run} disabled={loading}>
          {loading ? "Investigating…" : "Replay incident"}
        </button>
      </header>

      {bundle && (
        <main>
          <div className="col">
            <DiagnosisCard metric={bundle.metric} anomaly={bundle.anomaly} narrative={bundle.narrative} />
            <FactorSplit
              factors={bundle.factor_decomposition.factors}
              primary={bundle.factor_decomposition.primary_factor}
            />
            <RuledOutPanel items={bundle.ruled_out} />
            {bundle.trace_url && (
              <a className="trace" href={bundle.trace_url} target="_blank" rel="noreferrer">
                View investigation trace →
              </a>
            )}
          </div>
          <div className="col">
            <MetricTree metric={bundle.metric} nodes={bundle.drilldown} />
          </div>
        </main>
      )}
    </div>
  );
}
