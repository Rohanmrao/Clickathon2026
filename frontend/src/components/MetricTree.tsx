import type { DrilldownNode } from "../types";

const COLOR: Record<string, string> = {
  culprit: "#e5484d",
  contributor: "#f5a623",
  normal: "#30a46c",
};

function label(node: DrilldownNode): string {
  const entries = Object.entries(node.segment);
  const [dim, val] = entries[entries.length - 1] ?? [node.split_dimension, "?"];
  return `${dim} = ${val}`;
}

// Hero component: the drill-down path lighting up from broad metric to the localized culprit.
export function MetricTree({ metric, nodes }: { metric: string; nodes: DrilldownNode[] }) {
  return (
    <div className="tree">
      <div className="node root">{metric}</div>
      {nodes.map((n) => (
        <div key={n.query_id} className="branch">
          <span className="edge" />
          <div className="node" style={{ borderColor: COLOR[n.status], color: COLOR[n.status] }}>
            <strong>{label(n)}</strong>
            <span className="pct">{Math.round(n.contribution_pct * 100)}% of drop</span>
          </div>
        </div>
      ))}
    </div>
  );
}
