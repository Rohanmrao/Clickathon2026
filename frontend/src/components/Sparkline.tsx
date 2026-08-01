// Synthetic actual-vs-expected curve for the anomaly card. Coordinates are SVG
// viewBox units (not px), so no layout tokens apply here — colours come from CSS.
export function Sparkline() {
  const pts = 48;
  const drop = 40;
  const base = (i: number) => 88 + Math.sin(i / 3.1) * 5 + Math.sin(i / 7.7) * 4;
  const y = (v: number) => 200 - (v - 55) * 3.2;
  const x = (i: number) => (i / (pts - 1)) * 900;

  let exp = "";
  let act = "";
  for (let i = 0; i < pts; i++) {
    const e = base(i);
    const a = i < drop ? e - 1.5 + Math.sin(i * 1.7) * 1.6 : e - (i - drop + 1) * 3.4;
    exp += (i ? "L" : "M") + x(i).toFixed(1) + " " + y(e).toFixed(1);
    act += (i ? "L" : "M") + x(i).toFixed(1) + " " + y(a).toFixed(1);
  }
  const last = base(pts - 1) - (pts - drop) * 3.4;
  const areaPath = act + "L900 212 L0 212 Z";

  return (
    <svg className="spark" viewBox="0 0 900 220" preserveAspectRatio="none">
      <defs>
        <linearGradient id="fillDrop" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="var(--content-negative-dark)" stopOpacity="0.34" />
          <stop offset="100%" stopColor="var(--content-negative-dark)" stopOpacity="0" />
        </linearGradient>
      </defs>
      {[40, 90, 140, 190].map((gy) => (
        <line key={gy} x1="0" y1={gy} x2="900" y2={gy} stroke="var(--border-neutral-default)" />
      ))}
      <path d={exp} fill="none" stroke="var(--content-neutral-bright)" strokeWidth="1.6" strokeDasharray="5 5" />
      <path d={areaPath} fill="url(#fillDrop)" stroke="none" />
      <path d={act} fill="none" stroke="var(--content-secondary-main)" strokeWidth="2.4" strokeLinejoin="round" strokeLinecap="round" />
      <line x1={x(drop)} y1="8" x2={x(drop)} y2="212" stroke="var(--content-negative-dark)" strokeWidth="1" strokeDasharray="3 4" opacity="0.7" />
      <circle cx={x(pts - 1)} cy={y(last)} r="4.5" fill="var(--content-negative-dark)" />
    </svg>
  );
}
