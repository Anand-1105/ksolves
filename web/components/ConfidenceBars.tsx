"use client";

import type { ConfidenceFactors } from "@/lib/types";

interface Props {
  score: number;
  factors: ConfidenceFactors;
  animate?: boolean;
}

const factorLabels: Record<keyof ConfidenceFactors, string> = {
  data_completeness: "Data Completeness",
  reason_clarity: "Reason Clarity",
  policy_consistency: "Policy Consistency",
};

function Bar({
  label,
  value,
  animate,
}: {
  label: string;
  value: number;
  animate: boolean;
}) {
  const pct = Math.round(value * 100);
  return (
    <div className="flex items-center gap-3">
      <span className="text-xs text-text-muted w-36 shrink-0">{label}</span>
      <div className="flex-1 h-1.5 bg-bg-elevated rounded-full overflow-hidden">
        <div
          className={animate ? "animate-bar-fill h-full rounded-full" : "h-full rounded-full"}
          style={
            {
              "--bar-width": `${pct}%`,
              width: animate ? undefined : `${pct}%`,
              backgroundColor:
                pct >= 90
                  ? "#22c55e"
                  : pct >= 70
                  ? "#6366f1"
                  : "#f59e0b",
            } as React.CSSProperties
          }
        />
      </div>
      <span className="text-xs text-text-secondary w-8 text-right tabular-nums">
        {pct}%
      </span>
    </div>
  );
}

export default function ConfidenceBars({ score, factors, animate = false }: Props) {
  return (
    <div className="space-y-2.5">
      <div className="flex items-center justify-between mb-3">
        <span className="text-xs text-text-muted uppercase tracking-wider">
          Confidence
        </span>
        <span className="text-sm font-semibold tabular-nums text-text-primary">
          {Math.round(score * 100)}%
        </span>
      </div>
      {(Object.keys(factorLabels) as (keyof ConfidenceFactors)[]).map((key) => (
        <Bar
          key={key}
          label={factorLabels[key]}
          value={factors[key] ?? 0}
          animate={animate}
        />
      ))}
    </div>
  );
}
