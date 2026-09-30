export default function Sparkline({
  history,
  w = 96,
  h = 36,
}: {
  history: number[];
  w?: number;
  h?: number;
}) {
  const n = history.length;
  const min = Math.min(...history);
  const max = Math.max(...history);
  const span = Math.max(max - min, 6);
  const pts = history.map((v, i) => {
    const x = (i / (n - 1)) * w;
    const y = h - 3 - ((v - min) / span) * (h - 6);
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  });
  const up = history[n - 1] >= history[0];
  const stroke = up ? "var(--up)" : "var(--down)";

  return (
    <svg
      className="spark"
      width={w}
      height={h}
      viewBox={`0 0 ${w} ${h}`}
      role="img"
      aria-label="Price trend"
    >
      <polyline
        points={pts.join(" ")}
        fill="none"
        stroke={stroke}
        strokeWidth="1.6"
        strokeLinejoin="round"
        strokeLinecap="round"
        opacity="0.9"
      />
    </svg>
  );
}
