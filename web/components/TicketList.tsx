"use client";

import clsx from "clsx";
import type { Ticket } from "@/lib/types";
import { customerName, customerTier, tierColor, statusColor, statusLabel } from "@/lib/utils";

interface Props {
  tickets: Ticket[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}

function TierDot({ customerId }: { customerId: string }) {
  const tier = customerTier(customerId);
  return (
    <span
      className="w-1.5 h-1.5 rounded-full shrink-0"
      style={{ backgroundColor: tierColor(tier) }}
      title={tier}
    />
  );
}

function StatusBadge({ status }: { status: Ticket["status"] }) {
  return (
    <span
      className="text-[10px] font-medium rounded-badge px-1.5 py-0.5 border"
      style={{
        color: statusColor(status),
        borderColor: statusColor(status) + "40",
        backgroundColor: statusColor(status) + "15",
      }}
    >
      {statusLabel(status)}
    </span>
  );
}

export default function TicketList({ tickets, selectedId, onSelect }: Props) {
  return (
    <div className="flex flex-col">
      {tickets.map((ticket) => {
        const selected = ticket.ticket_id === selectedId;
        return (
          <button
            key={ticket.ticket_id}
            onClick={() => onSelect(ticket.ticket_id)}
            className={clsx(
              "w-full text-left px-4 py-3 relative transition-colors",
              "border-b border-border-subtle",
              selected
                ? "bg-bg-elevated"
                : "hover:bg-bg-hover"
            )}
          >
            {selected && (
              <span className="absolute left-0 top-0 bottom-0 w-0.5 bg-accent" />
            )}
            <div className="flex items-center justify-between gap-2 mb-1">
              <span className="font-mono text-[11px] text-text-muted">
                {ticket.ticket_id}
              </span>
              <StatusBadge status={ticket.status} />
            </div>
            <div className="flex items-center gap-2">
              <TierDot customerId={ticket.customer_id} />
              <span className="text-xs text-text-secondary truncate">
                {customerName(ticket.customer_id)}
              </span>
            </div>
            <div className="mt-1">
              <span className="text-[10px] text-text-dim capitalize">
                {ticket.issue_type.replace(/_/g, " ")}
              </span>
            </div>
          </button>
        );
      })}
    </div>
  );
}
