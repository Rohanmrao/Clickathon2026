import type { StreamStatus } from "../api";

function pct(value: number): string {
  return `${value < 0 ? "−" : "+"}${Math.abs(value * 100).toFixed(1)}%`;
}

function hourLabel(iso: string): string {
  return iso.replace("T", " ").slice(5, 16); // "07-09 02:00"
}

// Real-time mode. Shown only while a replay is live (or just finished), so the dashboard looks
// exactly as before when nothing is streaming. Detections appear newest-first as they are found
// — the point of the mode is watching them arrive, not reading a report afterwards.
export function StreamBar({ stream, onStop }: { stream: StreamStatus; onStop: () => void }) {
  const done = stream.batches_done ?? 0;
  const total = stream.batches_total ?? 0;
  const progress = total ? Math.round((done / total) * 100) : 0;
  const live = stream.status === "running";
  const hits = [...(stream.detections ?? [])].reverse();

  return (
    <div className={`stream-bar ${live ? "is-live" : ""}`} role="status">
      <div className="sb-head">
        <span className="sb-title">
          {live && <span className="sb-pulse" />}
          {live ? "Real-time mode" : `Replay ${stream.status}`}
        </span>
        <span className="sb-meta mono">
          {done}/{total} batches · {(stream.rows_ingested ?? 0).toLocaleString()} events ·{" "}
          {stream.checks ?? 0} checks
          {stream.current_window && ` · ${hourLabel(stream.current_window[0])}`}
          {stream.last_tick_ms != null && ` · ${stream.last_tick_ms}ms/tick`}
        </span>
        {live && (
          <button className="ghost-btn sb-stop" onClick={onStop}>Stop</button>
        )}
      </div>

      <div className="sb-track" aria-label={`${progress}% replayed`}>
        <div className="sb-fill" style={{ width: `${progress}%` }} />
      </div>

      {stream.error && <div className="sb-error">Stream error: {stream.error}</div>}

      {hits.length > 0 ? (
        <div className="sb-hits">
          <span className="eyebrow">{hits.length} anomal{hits.length === 1 ? "y" : "ies"} detected live</span>
          <div className="sb-hit-list">
            {hits.slice(0, 8).map((d, i) => (
              <span key={`${d.metric}-${d.hour}-${i}`} className="sb-hit">
                <span className="mono">{d.metric}</span>
                <span className={d.pct_delta < 0 ? "is-drop" : "is-spike"}>{pct(d.pct_delta)}</span>
                <span className="sb-hit-hour mono">{hourLabel(d.hour)}</span>
              </span>
            ))}
          </div>
        </div>
      ) : (
        live && <div className="sb-waiting">Scoring each hour as it lands — nothing anomalous yet.</div>
      )}
    </div>
  );
}
