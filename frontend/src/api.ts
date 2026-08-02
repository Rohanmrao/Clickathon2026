import type { EvidenceBundle, Health, InvestigationRow } from "./types";
import sampleBundle from "./sample_bundle.json";

const API = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

export interface InvestigateResult {
  bundle: EvidenceBundle;
  live: boolean; // false => the backend was unreachable and we fell back to the bundled sample
}

/** Run an investigation. Returns the bundle WITHOUT a narrative (that's the second step, narrate()).
 *  Fixtures-first: if the API is unreachable we fall back to the sample so the UI always renders. */
export async function investigate(
  metric = "revenue",
  window?: { start: string; end: string },
): Promise<InvestigateResult> {
  try {
    const res = await fetch(`${API}/investigate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ metric, window: window ?? null }),
    });
    if (!res.ok) throw new Error(String(res.status));
    return { bundle: (await res.json()) as EvidenceBundle, live: true };
  } catch {
    return { bundle: sampleBundle as EvidenceBundle, live: false };
  }
}

/** Add prose to a stored investigation. Returns the narrated bundle, or null if narration is
 *  unavailable (no LLM creds / Bedrock down) — the numbers are already complete either way. */
export async function narrate(investigationId: string): Promise<EvidenceBundle | null> {
  try {
    const res = await fetch(`${API}/narrate/${investigationId}`, { method: "POST" });
    if (!res.ok) return null;
    return (await res.json()) as EvidenceBundle;
  } catch {
    return null;
  }
}

/** Investigation history (flattened rows, not full bundles) for the past-runs panel. */
export async function listBundles(limit = 20): Promise<InvestigationRow[]> {
  try {
    const res = await fetch(`${API}/bundles?limit=${limit}`);
    if (!res.ok) return [];
    const data = await res.json();
    return (data.investigations ?? []) as InvestigationRow[];
  } catch {
    return [];
  }
}

/** Re-read a stored bundle by id (clicking a history row). */
export async function getBundle(investigationId: string): Promise<EvidenceBundle | null> {
  try {
    const res = await fetch(`${API}/bundle/${investigationId}`);
    if (!res.ok) return null;
    return (await res.json()) as EvidenceBundle;
  } catch {
    return null;
  }
}

/** Liveness + engine status (live vs fixture) + Langfuse wiring, for the topbar. */
export async function getHealth(): Promise<Health | null> {
  try {
    const res = await fetch(`${API}/health`);
    if (!res.ok) return null;
    return (await res.json()) as Health;
  } catch {
    return null;
  }
}

// One row per stored anomaly/run — the dashboard's incident switcher list.
export interface IncidentRow {
  investigation_id: string;
  created_at: string;
  window_start: string;
  window_end: string;
  metric: string;
  direction: string;
  pct_delta: number;
  is_anomaly: number;
  primary_factor: string;
  localized_segment: string; // JSON string
  narrated: number;
}

export async function listIncidents(limit = 50): Promise<IncidentRow[]> {
  try {
    const res = await fetch(`${API}/dashboard?limit=${limit}`);
    if (!res.ok) throw new Error(String(res.status));
    const data = await res.json();
    // The chat path (POST /v1/chat/completions) persists a detection-only bundle — real
    // anomaly, but no decompose/drill yet (primary_factor stays "pending"). Showcasing one
    // would leave the factor split, ruled-out panel and drill tree empty on the dashboard, so
    // the switcher only offers fully-investigated bundles. Chat-only anomalies still surface
    // through GET /bundles (Past investigations) and remain replayable in chat.
    return (data.incidents as IncidentRow[]).filter(
      (r) => r.is_anomaly === 1 && r.primary_factor && r.primary_factor !== "pending"
    );
  } catch {
    return [];
  }
}

// Dashboard chat: talks to our own OpenAI-shaped endpoint, carrying the showcased
// anomaly's bundle id so "this anomaly" resolves to what's on screen.
export interface ChatTurn {
  role: "user" | "assistant";
  content: string;
}

export async function sendChat(
  messages: ChatTurn[],
  bundleId: string | null,
  sessionId: string,
): Promise<string> {
  const res = await fetch(`${API}/v1/chat/completions`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Session-Id": sessionId },
    body: JSON.stringify({ messages, bundle_id: bundleId }),
  });
  if (!res.ok) throw new Error(String(res.status));
  const data = await res.json();
  return data.choices?.[0]?.message?.content ?? "(no reply)";
}
