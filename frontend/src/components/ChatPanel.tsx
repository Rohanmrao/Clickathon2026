import { useState } from "react";

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

/** Floating assistant: a launcher button that toggles a polished chat popover embedding
 *  LibreChat (the RCA conversational interface). The iframe mounts on first open and stays
 *  mounted so the conversation persists across open/close. URL: VITE_LIBRECHAT_URL. */
export function ChatPanel() {
  const [open, setOpen] = useState(false);
  const [mounted, setMounted] = useState(false); // lazy-load LibreChat on first open

  const toggle = () => {
    setMounted(true);
    setOpen((o) => !o);
  };

  return (
    <>
      <div className={`chat-widget ${open ? "open" : ""}`} role="dialog" aria-label="RCA Assistant" aria-hidden={!open}>
        <div className="chat-widget-head">
          <div className="cw-title">
            <span className="cw-avatar">{ChatIcon}</span>
            <span className="cw-titles">
              <span className="cw-name">RCA Assistant</span>
              <span className="cw-status"><span className="cw-live" /> Online · ask about any metric</span>
            </span>
          </div>
          <button className="cw-close" onClick={() => setOpen(false)} aria-label="Close assistant">{CloseIcon}</button>
        </div>
        <div className="chat-widget-body">
          {mounted ? (
            <iframe className="chat-frame" src={LIBRECHAT_URL} title="RCA Assistant" allow="clipboard-write" />
          ) : null}
        </div>
      </div>

      <button
        className={`chat-fab ${open ? "active" : ""}`}
        onClick={toggle}
        aria-label={open ? "Close assistant" : "Open assistant"}
        aria-expanded={open}
      >
        <span className="scan-tile fab-mark">{open ? CloseIcon : ChatIcon}</span>
        {!open && <span className="fab-dot" />}
      </button>
    </>
  );
}
