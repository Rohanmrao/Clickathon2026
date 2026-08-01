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

// Compact launcher: the "Ask a follow-up" header with a chat icon that opens
// LibreChat (the RCA conversational interface) in a popover. Keeping it small
// lets the metric tree expand to fill the sidebar. URL: VITE_LIBRECHAT_URL.
export function FollowUpChat() {
  const [open, setOpen] = useState(false);
  const [mounted, setMounted] = useState(false); // lazy-load LibreChat on first open

  const openChat = () => {
    setMounted(true);
    setOpen(true);
  };

  return (
    <>
      <section className="card followup">
        <div className="eyebrow-row">
          <span className="eyebrow">Ask a follow-up</span>
          <button className="chat-icon-btn" onClick={openChat} aria-label="Open RCA assistant" aria-expanded={open}>
            {ChatIcon}
          </button>
        </div>
      </section>

      <div className={`assistant-pop ${open ? "open" : ""}`} role="dialog" aria-label="RCA Assistant" aria-hidden={!open}>
        <div className="assistant-pop-head">
          <div className="ap-title">
            <span className="ap-avatar">{ChatIcon}</span>
            <span className="ap-titles">
              <span className="ap-name">RCA Assistant</span>
              <span className="ap-status"><span className="ap-live" /> Online · ask about any metric</span>
            </span>
          </div>
          <button className="ap-close" onClick={() => setOpen(false)} aria-label="Close assistant">{CloseIcon}</button>
        </div>
        <div className="assistant-pop-body">
          {mounted && <iframe className="assistant-frame" src={LIBRECHAT_URL} title="RCA Assistant" allow="clipboard-write" />}
        </div>
      </div>
    </>
  );
}
