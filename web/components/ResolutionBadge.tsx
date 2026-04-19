import clsx from "clsx";
import type { Resolution } from "@/lib/types";

interface Props {
  resolution: Resolution | null;
  size?: "sm" | "md" | "lg";
}

const labels: Record<string, string> = {
  APPROVE: "Approved",
  DENY: "Denied",
  ESCALATE: "Escalated",
};

export default function ResolutionBadge({ resolution, size = "md" }: Props) {
  if (!resolution) return null;

  return (
    <span
      className={clsx(
        "inline-flex items-center font-medium rounded-badge border",
        size === "sm" && "px-2 py-0.5 text-xs",
        size === "md" && "px-2.5 py-1 text-xs",
        size === "lg" && "px-3 py-1.5 text-sm",
        resolution === "APPROVE" &&
          "text-resolution-approve bg-resolution-approve-bg border-resolution-approve-border",
        resolution === "DENY" &&
          "text-resolution-deny bg-resolution-deny-bg border-resolution-deny-border",
        resolution === "ESCALATE" &&
          "text-resolution-escalate bg-resolution-escalate-bg border-resolution-escalate-border"
      )}
    >
      {labels[resolution] ?? resolution}
    </span>
  );
}
