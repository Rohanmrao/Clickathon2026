import type { Anomaly } from "../types";
import { Sparkline } from "./Sparkline";

const fmt = (n: number) => Math.round(n).toLocaleString("en-US");

// Hero card: the anomaly headline, actuals vs expected, and the drop curve.
export function AnomalyCard({
  metric,
  anomaly,
  confidence,
  running,
}: {
  metric: string;
  anomaly: Anomaly;
  confidence?: number;
  running?: boolean;
}) {
  const pct = (anomaly.pct_delta * 100).toFixed(1);
  const sign = anomaly.pct_delta < 0 ? "−" : "+";
  const headline = running ? "−?" : `${sign}${Math.abs(Number(pct))}%`;

  return (
    <section className="card card--feature">
      <div className="anomaly-head">
        <div className="anomaly-figures">
          <span className="eyebrow">Anomaly detected</span>
          <div className="figure-row">
            <span className="metric-name">{metric}</span>
            <span className={`headline ${anomaly.direction === "spike" ? "is-up" : ""}`}>{headline}</span>
          </div>
          <span className="sub-mono">
            {fmt(anomaly.observed)} actual · {fmt(anomaly.expected)} expected · Sat 14:00–15:00 UTC
          </span>
        </div>
        <div className="culprit-badge">
          <span className="dot" />
          <div>
            <div className="cb-title">culprit localized</div>
            <div className="cb-sub">confidence {(confidence ?? 0.91).toFixed(2)}</div>
          </div>
        </div>
      </div>

      <Sparkline />
      <div className="spark-legend">
        <span>−48h</span>
        <span className="keys">
          <span className="key"><span className="swatch-line" />actual</span>
          <span className="key"><span className="swatch-dash" />expected</span>
        </span>
        <span>now</span>
      </div>
    </section>
  );
}
