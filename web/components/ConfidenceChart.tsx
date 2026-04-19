"use client";

import { useMemo } from "react";

interface DataPoint {
  ticketId: string;
  score: number;
  resolution: string | null;
}

interface Props {
  data: DataPoint[];
}

const RESOLUTION_COLORS: Record<string, string> = {
  APPROVE: "#22c55e",
  DENY: "#ef4444",
  ESCALATE: "#f59e0b",
};

const THRESHOLD = 0.75;
const HEIGHT = 120;
const PADDING = { top: 12, right: 12, bottom: 24, left: 32 };

export default function ConfidenceChart({ data }: Props) {
  const points = useMemo(() => {
    if (data.length === 0) return [];
    const w = 100; // percentage-based x
    return data.map((d, i) => ({
      ...d,
      x: data.length === 1 ? 50 : (i / (data.length - 1)) * w,
      y: (1 - d.score) * (HEIGHT - PADDING.top - PADDING.bottom) + PADDING.top,
    }));
  }, [data]);

  if (data.length === 0) return null;

  const innerH = HEIGHT - PADDING.top - PADDING.bottom;
  const thresholdY = (1 - THRESHOLD) * innerH + PADDING.top;

  // Build SVG polyline path (percentage-based x, absolute y)
  const pathD = points
    .map((p, i) => `${i === 0 ? "M" : "L"} ${p.x}% ${p.y}`)
    .join(" ");

  return (
    <div className="border border-border rounded-container p-4 bg-bg-surface">
      <div className="flex items-center justify-between mb-3">
        <span className="text-xs font-medium text-text-muted uppercase tracking-wider">
          Confidence Scores
        </span>
        <div className="flex items-center gap-3 text-[10px] text-text-dim">
          <span className="flex items-center gap-1">
            <span className="w-2 h-px bg-resolution-approve inline-block" />
            Approved
          </span>
          <span className="flex items-center gap-1">
            <span className="w-2 h-px bg-resolution-deny inline-block" />
            Denied
          </span>
          <span className="flex items-center gap-1">
            <span className="w-2 h-px bg-resolution-escalate inline-block" />
            Escalated
          </span>
        </div>
      </div>

      <div className="relative" style={{ height: HEIGHT }}>
        <svg
          width="100%"
          height={HEIGHT}
          className="overflow-visible"
          aria-label="Confidence score chart"
          role="img"
        >
          {/* Y-axis labels */}
          {[0, 0.25, 0.5, 0.75, 1.0].map((v) => {
            const y = (1 - v) * innerH + PADDING.top;
            return (
              <g key={v}>
                <line
                  x1={PADDING.left}
                  y1={y}
                  x2="100%"
                  y2={y}
                  stroke="#1f1f1f"
                  strokeWidth={1}
                />
                <text
                  x={PADDING.left - 4}
                  y={y + 4}
                  textAnchor="end"
                  fontSize={9}
                  fill="#52525b"
                >
                  {Math.round(v * 100)}
                </text>
              </g>
            );
          })}

          {/* Threshold line */}
          <line
            x1={PADDING.left}
            y1={thresholdY}
            x2="100%"
            y2={thresholdY}
            stroke="#6366f1"
            strokeWidth={1}
            strokeDasharray="4 3"
            opacity={0.6}
          />
          <text x="100%" y={thresholdY - 3} textAnchor="end" fontSize={9} fill="#6366f1" opacity={0.8}>
            75%
          </text>

          {/* Line connecting dots */}
          {points.length > 1 && (
            <polyline
              points={points.map((p) => `${p.x}%,${p.y}`).join(" ")}
              fill="none"
              stroke="#3f3f46"
              strokeWidth={1.5}
            />
          )}

          {/* Data points */}
          {points.map((p, i) => {
            const color = RESOLUTION_COLORS[p.resolution ?? ""] ?? "#52525b";
            return (
              <g key={i}>
                <circle
                  cx={`${p.x}%`}
                  cy={p.y}
                  r={4}
                  fill={color}
                  stroke="#0a0a0a"
                  strokeWidth={1.5}
                />
                <title>{`${p.ticketId}: ${Math.round(p.score * 100)}% (${p.resolution ?? "pending"})`}</title>
              </g>
            );
          })}
        </svg>

        {/* X-axis ticket labels — show every 5th */}
        <div className="absolute bottom-0 left-0 right-0 flex justify-between px-8">
          {points
            .filter((_, i) => i % 4 === 0 || i === points.length - 1)
            .map((p) => (
              <span key={p.ticketId} className="text-[9px] text-text-dim tabular-nums">
                {p.ticketId}
              </span>
            ))}
        </div>
      </div>
    </div>
  );
}
