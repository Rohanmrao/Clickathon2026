import { useState } from "react";
import type { InvestigationRow } from "../types";

const LIBRECHAT_URL = import.meta.env.VITE_LIBRECHAT_URL ?? "http://localhost:3080";

const ChatIcon = (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
  </svg>
);
const CloseIcon = (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" />
  </svg>
);
const EnvelopeIcon = (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <rect x="3" y="5" width="18" height="14" rx="2" /><polyline points="3 7 12 13 21 7" />
  </svg>
);
const RefreshIcon = (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M23 4v6h-6" /><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10" />
  </svg>
);

type Panel = "none" | "history" | "chat";

// The sidebar's bottom dock: two compact buttons (Past investigations, Ask a follow-up)
// each opening a panel anchored above them — the history unfolds like an envelope,
// the assistant grows up into LibreChat. Only one panel is open at a time.
export function SidebarDock({
  history,
  onOpenRun,
  onRefresh,
  segOf,
}: {
  history: InvestigationRow[];
  onOpenRun: (id: string) => void;
  onRefresh: () => void;
  segOf: (row: InvestigationRow) => string;
}) {
  const [open, setOpen] = useState<Panel>("none");
  const [chatMounted, setChatMounted] = useState(false);

  const toggle = (p: Panel) => setOpen((o) => (o === p ? "none" : p));
  const openChat = () => {
    setChatMounted(true);
    toggle("chat");
  };

  return (
    <div className="sidebar-dock">
      {/* Past investigations — unfolds like an envelope */}
      <div className={`dock-panel history-panel ${open === "history" ? "open" : ""}`} role="dialog" aria-label="Past investigations" aria-hidden={open !== "history"}>
        <div className="dock-panel-head">
          <span className="eyebrow">Past investigations</span>
          <div className="dph-actions">
            <button className="dock-icon" onClick={onRefresh} aria-label="Refresh history">{RefreshIcon}</button>
            <button className="dock-icon" onClick={() => setOpen("none")} aria-label="Close">{CloseIcon}</button>
          </div>
        </div>
        <div className="dock-panel-body history-scroll">
          {history.length === 0 ? (
            <div className="history-empty">No stored investigations yet — run one.</div>
          ) : (
            history.map((row) => (
              <button
                key={row.investigation_id}
                className="history-row"
                onClick={() => { onOpenRun(row.investigation_id); setOpen("none"); }}
              >
                <span className="hr-metric">{row.metric}</span>
                <span className={`hr-status ${row.detected ? "detected" : "flat"}`}>{row.detected ? "detected" : "flat"}</span>
                <span className="hr-seg">{segOf(row)}</span>
              </button>
            ))
          )}
        </div>
      </div>

      {/* Ask a follow-up — LibreChat */}
      <div className={`dock-panel assistant-pop ${open === "chat" ? "open" : ""}`} role="dialog" aria-label="RCA Assistant" aria-hidden={open !== "chat"}>
        <div className="assistant-pop-head">
          <div className="ap-title">
            <span className="ap-avatar">{ChatIcon}</span>
            <span className="ap-titles">
              <span className="ap-name">RCA Assistant</span>
              <span className="ap-status"><span className="ap-live" /> Online · ask about any metric</span>
            </span>
          </div>
          <button className="ap-close" onClick={() => setOpen("none")} aria-label="Close assistant">{CloseIcon}</button>
        </div>
        <div className="assistant-pop-body">
          {chatMounted && <iframe className="assistant-frame" src={LIBRECHAT_URL} title="RCA Assistant" allow="clipboard-write" />}
        </div>
      </div>

      {/* Button row: Past investigations (left) · Ask a follow-up (right) */}
      <div className="dock-buttons">
        <button
          className={`dock-btn history-btn ${open === "history" ? "is-open" : ""}`}
          onClick={() => toggle("history")}
          aria-expanded={open === "history"}
        >
          <span className="db-icon">{EnvelopeIcon}</span>
          <span>Past investigations</span>
        </button>
        <button
          className={`dock-btn chat-btn ${open === "chat" ? "is-open" : ""}`}
          onClick={openChat}
          aria-expanded={open === "chat"}
        >
          <span className="db-icon">{ChatIcon}</span>
          <span>Ask a follow-up</span>
        </button>
      </div>
    </div>
  );
}
