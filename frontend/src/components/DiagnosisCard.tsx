import type { Anomaly } from "../types";

export function DiagnosisCard({
  metric,
  anomaly,
  narrative,
}: {
  metric: string;
  anomaly: Anomaly;
  narrative?: string | null;
}) {
  const pct = (anomaly.pct_delta * 100).toFixed(1);
  return (
    <section className="card">
      <div className="headline">
        {metric} {anomaly.direction === "drop" ? "▼" : "▲"} {pct}%
      </div>
      <p className="narrative">{narrative ?? "Awaiting narration…"}</p>
    </section>
  );
}
