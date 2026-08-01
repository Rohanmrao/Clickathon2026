import type { EvidenceBundle } from "./types";
import sampleBundle from "./sample_bundle.json";

const API = import.meta.env.VITE_API_URL ?? "http://localhost:8000";

// Fixtures-first: try the live API, fall back to the bundled sample so the UI always renders.
export async function investigate(metric = "revenue"): Promise<EvidenceBundle> {
  try {
    const res = await fetch(`${API}/investigate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ metric }),
    });
    if (!res.ok) throw new Error(String(res.status));
    return (await res.json()) as EvidenceBundle;
  } catch {
    return sampleBundle as EvidenceBundle;
  }
}
