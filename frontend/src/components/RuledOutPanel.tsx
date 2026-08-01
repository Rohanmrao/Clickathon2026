import type { RuledOut } from "../types";

// The trust-builder: what was checked and cleared, each with a number.
export function RuledOutPanel({ items }: { items: RuledOut[] }) {
  return (
    <section className="card">
      <h3>Checked &amp; ruled out</h3>
      <ul className="ruled-out">
        {items.map((r) => (
          <li key={r.query_id}>
            <span className="check">✓</span>
            <strong>{r.hypothesis}</strong> — {r.evidence}
          </li>
        ))}
      </ul>
    </section>
  );
}
