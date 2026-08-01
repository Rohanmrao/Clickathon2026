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
