import { useState } from "react";
import { ChatPanel } from "./components/ChatPanel";

/* Inline icons (no icon dependency) */
const I = {
  dashboard: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="3" width="7" height="9" /><rect x="14" y="3" width="7" height="5" />
      <rect x="14" y="12" width="7" height="9" /><rect x="3" y="16" width="7" height="5" />
    </svg>
  ),
  trace: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="5" cy="6" r="2" /><circle cx="19" cy="6" r="2" /><circle cx="12" cy="18" r="2" />
      <path d="M5 8v2a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8M12 14v2" />
    </svg>
  ),
  incidents: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
      <line x1="12" y1="9" x2="12" y2="13" /><line x1="12" y1="17" x2="12.01" y2="17" />
    </svg>
  ),
  settings: (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="3" />
      <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" />
    </svg>
  ),
};

const NavItem = ({
  icon, label, active, onSelect,
}: { icon: JSX.Element; label: string; active?: boolean; onSelect?: () => void }) => (
  <a className={`nav-item ${active ? "active" : ""}`} onClick={onSelect}>
    {icon}
    {label}
  </a>
);

const PlaceholderTile = ({ label }: { label: string }) => (
  <div className="placeholder">
    <svg className="ph-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M3 3v18h18" /><path d="m7 14 4-4 3 3 5-6" />
    </svg>
    <span className="ph-title">{label}</span>
  </div>
);

export default function App() {
  const [nav, setNav] = useState("Dashboard");
  return (
    <div className="layout">
      <aside className="sidebar">
        <div className="brand">
          <span className="scan-tile brand-mark">R</span>
          <span className="brand-name">RCA Analyst</span>
        </div>

        <div className="nav-label">Workspace</div>
        <NavItem icon={I.dashboard} label="Dashboard" active={nav === "Dashboard"} onSelect={() => setNav("Dashboard")} />
        <NavItem icon={I.incidents} label="Incidents" active={nav === "Incidents"} onSelect={() => setNav("Incidents")} />
        <NavItem icon={I.trace} label="Traces" active={nav === "Traces"} onSelect={() => setNav("Traces")} />

        <div className="nav-label">Account</div>
        <NavItem icon={I.settings} label="Settings" active={nav === "Settings"} onSelect={() => setNav("Settings")} />

        <div className="sidebar-footer">
          <div className="user-chip"><div className="avatar">JG</div> Jalagaara Gang</div>
        </div>
      </aside>

      <div className="content">
        <header className="topbar">
          <div className="topbar-title">
            <span className="topbar-crumb">Workspace / </span>Dashboard
          </div>
          <div className="topbar-actions">
            <span className="pill"><span className="dot" /> ClickHouse connected</span>
          </div>
        </header>

        <div className="main">
          <section className="dash">
            <div className="dash-head">
              <h1>Dashboard</h1>
              <p>Metrics and investigations will appear here. Ask the assistant to run one.</p>
            </div>
            <div className="grid">
              <PlaceholderTile label="Revenue overview" />
              <PlaceholderTile label="Fill rate" />
              <PlaceholderTile label="eCPM" />
              <PlaceholderTile label="Recent incidents" />
              <PlaceholderTile label="Anomaly timeline" />
              <PlaceholderTile label="Segment breakdown" />
            </div>
          </section>
        </div>
      </div>

      <ChatPanel />
    </div>
  );
}
