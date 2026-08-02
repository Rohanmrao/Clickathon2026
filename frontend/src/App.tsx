import { useEffect, useRef, useState } from "react";
import { getBundle, getHealth, investigate, listBundles, listIncidents, narrate, type IncidentRow } from "./api";
import sampleBundle from "./sample_bundle.json";
import { AnomalyCard } from "./components/AnomalyCard";
import { DiagnosisCard } from "./components/DiagnosisCard";
import { FactorSplit } from "./components/FactorSplit";
import { MetricTree } from "./components/MetricTree";
import { RuledOutPanel } from "./components/RuledOutPanel";
import { SidebarDock } from "./components/SidebarDock";
import { TraceDrawer } from "./components/TraceDrawer";
import { ClickathonMark } from "./components/ClickathonMark";
import { DateField } from "./components/DateField";
import type { EvidenceBundle, InvestigationRow } from "./types";

const METRICS = ["revenue", "fill_rate", "ecpm", "requests", "ctr", "rpr", "render_rate"];

function incidentLabel(row: IncidentRow): string {
  const date = row.window_start?.slice(5, 10) ?? "";
  const pct = `${row.pct_delta < 0 ? "−" : "+"}${Math.abs(row.pct_delta * 100).toFixed(1)}%`;
  let seg = "";
  try {
    const parsed = JSON.parse(row.localized_segment || "{}");
    const vals = Object.values(parsed);
    if (vals.length) seg = ` · ${vals.join(", ")}`;
  } catch {
    /* not JSON — leave the label unsegmented */
  }
  return `${row.metric} ${row.direction} ${pct} · ${date}${seg}`;
}

export default function App() {
  const [bundle, setBundle] = useState<EvidenceBundle>(sampleBundle as EvidenceBundle);
  const [incidents, setIncidents] = useState<IncidentRow[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [source, setSource] = useState<"fixture" | "live">("fixture");
  const [engine, setEngine] = useState<"live" | "fixture" | "offline" | null>(null); // from /health
  const [running, setRunning] = useState(false);
  const [step, setStep] = useState<number>(99); // drill-down reveal cursor
  const [activePanel, setActivePanel] = useState<"both" | "diagnosis" | "factor">("both");
  const [theme, setTheme] = useState<"dark" | "light">(
    () => (localStorage.getItem("rca-theme") as "dark" | "light") || "dark"
  );
  const [metric, setMetric] = useState<string>((sampleBundle as EvidenceBundle).metric || "revenue");
  const [winStart, setWinStart] = useState("");
  const [winEnd, setWinEnd] = useState("");
  const [history, setHistory] = useState<InvestigationRow[]>([]);
  const [traceOpen, setTraceOpen] = useState(false);
  const timer = useRef<number | undefined>(undefined);

  // Theme lives on <body> so page backgrounds (not just cards) follow variables-final.css.
  // color-scheme keeps native controls (select, scrollbars) in sync with light/dark.
  useEffect(() => {
    document.body.classList.remove("light-theme", "dark-theme");
    document.body.classList.add(`${theme}-theme`);
    document.body.style.colorScheme = theme;
    localStorage.setItem("rca-theme", theme);
  }, [theme]);

  const fd = bundle.factor_decomposition;
  const depth = bundle.drilldown.length + 1; // + root
  const pctLabel = `${bundle.anomaly.pct_delta < 0 ? "−" : "+"}${Math.abs(bundle.anomaly.pct_delta * 100).toFixed(1)}%`;

  const refreshHistory = () => listBundles(15).then(setHistory);

  // On mount: report the real engine status, load past investigations, and load the stored
  // anomaly list — showcasing the biggest move first so the headline card is never a flat run.
  useEffect(() => {
    getHealth().then((h) => h && setEngine(h.engine));
    refreshHistory();
    listIncidents().then((rows) => {
      rows.sort((a, b) => Math.abs(b.pct_delta) - Math.abs(a.pct_delta));
      setIncidents(rows);
      if (rows.length) selectIncident(rows[0].investigation_id);
    });
    return () => window.clearInterval(timer.current);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const selectIncident = (id: string) => {
    setSelectedId(id);
    getBundle(id).then((b) => {
      if (b) {
        setBundle(b);
        setMetric(b.metric);
        setSource("live");
        setStep(99);
      }
    });
  };

  // Reveal the drill-down one node at a time so the localization reads as a search, not a jump.
  const revealSteps = (b: EvidenceBundle) => {
    window.clearInterval(timer.current);
    setStep(0);
    const d = b.drilldown.length + 1;
    timer.current = window.setInterval(() => {
      setStep((s) => {
        const next = s + 1;
        if (next >= d) {
          window.clearInterval(timer.current);
          setRunning(false);
          return d;
        }
        return next;
      });
    }, 620);
  };

  // Run: investigate (numbers) -> reveal drill-down -> narrate (prose arrives after, per the
  // investigate/narrate split). A window is sent only if both dates are set, else the backend
  // discovers the anomalous window itself.
  const run = async () => {
    setRunning(true);
    const win = winStart && winEnd ? { start: `${winStart}T00:00:00`, end: `${winEnd}T00:00:00` } : undefined;
    const { bundle: b, live } = await investigate(metric, win);
    setBundle(b);
    setSelectedId(b.investigation_id || null);
    setSource(live ? "live" : "fixture");
    revealSteps(b);
    if (live && b.investigation_id) {
      const narrated = await narrate(b.investigation_id);
      if (narrated) setBundle(narrated); // fills the Diagnosis card
    }
    getHealth().then((h) => h && setEngine(h.engine)); // reflect offline/live after the run
    refreshHistory();
    listIncidents().then(setIncidents); // a fresh detected anomaly joins the switcher too
  };

  // Re-open a stored investigation from the history list (already narrated, fully revealed).
  const openRun = async (id: string) => {
    const b = await getBundle(id);
    if (b) {
      window.clearInterval(timer.current);
      setBundle(b);
      setSelectedId(id);
      setMetric(b.metric);
      setSource("live");
      setRunning(false);
      setStep(99);
    }
  };

  const stepLabel = running ? `drilling ${Math.min(step + 1, depth)}/${depth}` : `depth ${depth} · localized`;
  const engineLabel = engine ? `engine · ${engine}` : "clickhouse · —";
  const segOf = (row: InvestigationRow) => {
    try {
      const s = JSON.parse(row.localized_segment || "{}");
      const keys = Object.keys(s);
      return keys.length ? keys.map((k) => `${k}=${s[k]}`).join(" ∧ ") : "—";
    } catch {
      return "—";
    }
  };
  const shortId = bundle.investigation_id ? bundle.investigation_id.slice(0, 8) : "inc_4471";

  return (
    <div className="app spacing-default effect-smooth">
      <header className="topbar">
        <div className="brand">
          <span className="brand-logo"><ClickathonMark /></span>
          <div className="brand-titles">
            <span className="brand-name">RCA analyst</span>
            <span className="brand-sub">
              {source === "live" ? "live · clickhouse bundles" : "fixtures/sample_bundle.json"} · {shortId}
            </span>
          </div>
        </div>
        <div className="topbar-actions">
          {incidents.length > 0 && (
            <select
              className="ghost-btn incident-select"
              value={selectedId ?? ""}
              onChange={(e) => selectIncident(e.target.value)}
              aria-label="Switch anomaly"
            >
              {incidents.map((row) => (
                <option key={row.investigation_id} value={row.investigation_id}>
                  {incidentLabel(row)}
                </option>
              ))}
            </select>
          )}
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
          <span className="status-pill"><span className="live-dot" /> {engineLabel}</span>
          <div className="controls">
            <select value={metric} onChange={(e) => setMetric(e.target.value)} aria-label="Metric">
              {METRICS.map((m) => <option key={m} value={m}>{m}</option>)}
            </select>
            <DateField value={winStart} onChange={setWinStart} aria-label="Window start" />
            <DateField value={winEnd} onChange={setWinEnd} aria-label="Window end" />
          </div>
          {selectedId && (
            <button className="ghost-btn" onClick={() => setTraceOpen(true)}>Open trace</button>
          )}
          <button className="primary-btn" onClick={run} disabled={running}>
            {running ? "Investigating…" : "Investigate"}
          </button>
        </div>
      </header>

      {engine === "offline" && (
        <div className="offline-banner" role="status">
          <span className="offline-dot" /> Data store offline — showing sample data. Check
          <code> CLICKHOUSE_* </code> in <code>.env</code>, then recreate the backend
          (<code>docker compose up -d backend</code>).
        </div>
      )}

      <main className="main-grid">
        <section className="col-left">
          <AnomalyCard
            metric={bundle.metric}
            anomaly={bundle.anomaly}
            confidence={bundle.anomaly.score ? Math.min(0.99, Math.abs(bundle.anomaly.score) / 5) : undefined}
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

          <SidebarDock history={history} onOpenRun={openRun} onRefresh={refreshHistory} segOf={segOf} bundleId={selectedId} />
        </aside>
      </main>

      <TraceDrawer
        investigationId={selectedId}
        traceUrl={bundle.trace_url}
        open={traceOpen}
        onClose={() => setTraceOpen(false)}
      />
    </div>
  );
}
