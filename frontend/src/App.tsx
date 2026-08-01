import { useEffect, useRef, useState } from "react";
import { investigate } from "./api";
import sampleBundle from "./sample_bundle.json";
import { AnomalyCard } from "./components/AnomalyCard";
import { DiagnosisCard } from "./components/DiagnosisCard";
import { FactorSplit } from "./components/FactorSplit";
import { MetricTree } from "./components/MetricTree";
import { RuledOutPanel } from "./components/RuledOutPanel";
import { FollowUpChat } from "./components/FollowUpChat";
import type { EvidenceBundle } from "./types";

export default function App() {
  const [bundle, setBundle] = useState<EvidenceBundle>(sampleBundle as EvidenceBundle);
  const [source, setSource] = useState<"fixture" | "live">("fixture");
  const [running, setRunning] = useState(false);
  const [step, setStep] = useState<number>(99); // drill-down reveal cursor
  const timer = useRef<number | undefined>(undefined);

  const fd = bundle.factor_decomposition;
  const depth = bundle.drilldown.length + 1; // + root
  const pctLabel = `${bundle.anomaly.pct_delta < 0 ? "−" : "+"}${Math.abs(bundle.anomaly.pct_delta * 100).toFixed(1)}%`;

  // Replay: dim every drill-down step, then reveal them one at a time.
  const replay = () => {
    window.clearInterval(timer.current);
    setRunning(true);
    setStep(0);
    investigate(bundle.metric || "revenue").then((b) => {
      setBundle(b);
      setSource(b === (sampleBundle as EvidenceBundle) ? "fixture" : "live");
    });
    timer.current = window.setInterval(() => {
      setStep((s) => {
        const next = s + 1;
        if (next >= depth) {
          window.clearInterval(timer.current);
          setRunning(false);
          return depth;
        }
        return next;
      });
    }, 620);
  };

  useEffect(() => () => window.clearInterval(timer.current), []);

  const stepLabel = running ? `drilling ${Math.min(step + 1, depth)}/${depth}` : `depth ${depth} · localized`;

  return (
    <div className="app dark-theme spacing-default effect-smooth">
      <header className="topbar">
        <div className="brand">
          <span className="brand-logo">rc</span>
          <div className="brand-titles">
            <span className="brand-name">RCA analyst</span>
            <span className="brand-sub">
              {source === "live" ? "live · /investigate" : "fixtures/sample_bundle.json"} · incident inc_4471
            </span>
          </div>
        </div>
        <div className="topbar-actions">
          <span className="status-pill"><span className="live-dot" /> clickhouse · 41ms</span>
          {bundle.trace_url && (
            <a className="ghost-btn" href={bundle.trace_url} target="_blank" rel="noreferrer">Open trace</a>
          )}
          <button className="primary-btn" onClick={replay} disabled={running}>
            {running ? "Replaying…" : "Replay incident"}
          </button>
        </div>
      </header>

      <main className="main-grid">
        <section className="col-left">
          <AnomalyCard
            metric={bundle.metric}
            anomaly={bundle.anomaly}
            confidence={bundle.anomaly.score ? Math.min(0.99, bundle.anomaly.score / 5) : undefined}
            running={running}
          />
          <div className="split-row">
            <DiagnosisCard narrative={bundle.narrative} />
            <FactorSplit factors={fd.factors} primary={fd.primary_factor} totalPct={pctLabel} />
          </div>
          <RuledOutPanel items={bundle.ruled_out} />
        </section>

        <aside className="col-right">
          <section className="card card--feature">
            <div className="eyebrow-row">
              <span className="eyebrow">Metric tree</span>
              <span className="hint">{stepLabel}</span>
            </div>
            <MetricTree metric={bundle.metric} anomaly={bundle.anomaly} nodes={bundle.drilldown} step={running ? step : undefined} />

            {bundle.localized_segment && Object.keys(bundle.localized_segment).length > 0 && (
              <div className="localized">
                <span className="eyebrow">Localized to</span>
                <div className="chips">
                  {Object.entries(bundle.localized_segment).map(([k, v]) => (
                    <span key={k} className="chip">{k} = {v}</span>
                  ))}
                </div>
              </div>
            )}
          </section>

          <FollowUpChat />
        </aside>
      </main>
    </div>
  );
}
