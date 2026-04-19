import type { CustomerTier, Resolution, TicketStatus } from "./types";

export function tierLabel(tier: CustomerTier): string {
  return tier.charAt(0).toUpperCase() + tier.slice(1);
}

export function tierColor(tier: CustomerTier): string {
  switch (tier) {
    case "vip":
      return "#f59e0b";
    case "premium":
      return "#a1a1aa";
    case "standard":
    default:
      return "#52525b";
  }
}

export function resolutionColor(resolution: Resolution | null): string {
  switch (resolution) {
    case "APPROVE":
      return "#22c55e";
    case "DENY":
      return "#ef4444";
    case "ESCALATE":
      return "#f59e0b";
    default:
      return "#52525b";
  }
}

export function resolutionBg(resolution: Resolution | null): string {
  switch (resolution) {
    case "APPROVE":
      return "#052e16";
    case "DENY":
      return "#2d0a0a";
    case "ESCALATE":
      return "#2d1a00";
    default:
      return "#1a1a1a";
  }
}

export function resolutionBorder(resolution: Resolution | null): string {
  switch (resolution) {
    case "APPROVE":
      return "#14532d";
    case "DENY":
      return "#7f1d1d";
    case "ESCALATE":
      return "#78350f";
    default:
      return "#2a2a2a";
  }
}

export function statusLabel(status: TicketStatus): string {
  switch (status) {
    case "resolved":
      return "Resolved";
    case "escalated":
      return "Escalated";
    case "denied":
      return "Denied";
    case "error":
      return "Error";
    case "pending":
    default:
      return "Pending";
  }
}

export function statusColor(status: TicketStatus): string {
  switch (status) {
    case "resolved":
      return "#22c55e";
    case "escalated":
      return "#f59e0b";
    case "denied":
      return "#ef4444";
    case "error":
      return "#ef4444";
    case "pending":
    default:
      return "#52525b";
  }
}

export function formatToolName(name: string): string {
  return name.replace(/_/g, " ");
}

export function formatTimestamp(ts: string): string {
  try {
    return new Date(ts).toLocaleTimeString("en-US", {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
  } catch {
    return ts;
  }
}

// Customer name lookup from customer_id
const CUSTOMER_NAMES: Record<string, string> = {
  C001: "Alice Johnson",
  C002: "Emma Williams",
  C003: "Carol Martinez",
  C004: "Grace Thompson",
  C005: "Irene Garcia",
  C006: "Bob Anderson",
  C007: "Dave Robinson",
  C008: "Frank Lewis",
  C009: "Henry Walker",
  C010: "Jane Harris",
};

const CUSTOMER_TIERS: Record<string, CustomerTier> = {
  C001: "vip",
  C002: "vip",
  C003: "premium",
  C004: "premium",
  C005: "premium",
  C006: "standard",
  C007: "standard",
  C008: "standard",
  C009: "standard",
  C010: "standard",
};

export function customerName(customerId: string): string {
  return CUSTOMER_NAMES[customerId] ?? customerId;
}

export function customerTier(customerId: string): CustomerTier {
  return CUSTOMER_TIERS[customerId] ?? "standard";
}
