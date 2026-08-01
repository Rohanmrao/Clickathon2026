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
  const [activePanel, setActivePanel] = useState<"both" | "diagnosis" | "factor">("both");
  const [theme, setTheme] = useState<"dark" | "light">(
    () => (localStorage.getItem("rca-theme") as "dark" | "light") || "dark"
  );
  const timer = useRef<number | undefined>(undefined);

  // Theme lives on <body> so page backgrounds (not just cards) follow variables-final.css.
  useEffect(() => {
    document.body.classList.remove("light-theme", "dark-theme");
    document.body.classList.add(`${theme}-theme`);
    localStorage.setItem("rca-theme", theme);
  }, [theme]);

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
    <div className="app spacing-default effect-smooth">
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
          <button
            className="ghost-btn icon-btn"
            onClick={() => setTheme((t) => (t === "dark" ? "light" : "dark"))}
            aria-label={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
          >
            {theme === "dark" ? (
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <circle cx="12" cy="12" r="4" />
                <path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41" />
              </svg>
            ) : (
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z" />
              </svg>
            )}
          </button>
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
          <div
            className={`split-row active-${activePanel}`}
            onClick={(e) => {
              const card = (e.target as HTMLElement).closest(".card");
              if (!card || !card.parentElement) return;
              const cards = [...card.parentElement.querySelectorAll(".card")];
              const which = cards[0] === card ? "diagnosis" : "factor";
              setActivePanel((prev) => (prev === which ? "both" : which));
            }}
          >
            <DiagnosisCard narrative={bundle.narrative} />
            <FactorSplit factors={fd.factors} primary={fd.primary_factor} totalPct={pctLabel} />
            <div className="split-nav" onClick={(e) => e.stopPropagation()}>
              <button
                className={`split-arrow ${activePanel === "factor" ? "is-active" : ""}`}
                aria-label="Expand factor split"
                onClick={() => setActivePanel("factor")}
              >
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <polyline points="15 18 9 12 15 6" />
                </svg>
              </button>
              <button
                className={`split-mid ${activePanel === "both" ? "is-active" : ""}`}
                aria-label="Reset to equal"
                onClick={() => setActivePanel("both")}
              >
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <rect x="4" y="6" width="6" height="12" rx="1.5" />
                  <rect x="14" y="6" width="6" height="12" rx="1.5" />
                </svg>
              </button>
              <button
                className={`split-arrow ${activePanel === "diagnosis" ? "is-active" : ""}`}
                aria-label="Expand diagnosis"
                onClick={() => setActivePanel("diagnosis")}
              >
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <polyline points="9 18 15 12 9 6" />
                </svg>
              </button>
            </div>
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
