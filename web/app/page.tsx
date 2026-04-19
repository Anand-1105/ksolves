"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import clsx from "clsx";
import { api } from "@/lib/api";
import { useStore } from "@/lib/store";
import type { Ticket, AuditRecord, SSEEvent } from "@/lib/types";
import { customerName, customerTier, tierColor } from "@/lib/utils";
import TicketList from "@/components/TicketList";
import AgentStream from "@/components/AgentStream";
import ResolutionBadge from "@/components/ResolutionBadge";
import ConfidenceBars from "@/components/ConfidenceBars";

// ---------------------------------------------------------------------------
// Ticket detail (resolved state)
// ---------------------------------------------------------------------------

function TicketDetailPanel({ ticket, audit }: { ticket: Ticket; audit: AuditRecord }) {
  const router = useRouter();
  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-start justify-between">
        <div>
          <div className="flex items-center gap-3 mb-1">
            <span className="font-mono text-2xl text-text-primary">{ticket.ticket_id}</span>
            <ResolutionBadge resolution={audit.resolution} size="lg" />
          </div>
          <div className="flex items-center gap-2">
            <span
              className="w-2 h-2 rounded-full"
              style={{ backgroundColor: tierColor(customerTier(ticket.customer_id)) }}
            />
            <span className="text-sm text-text-secondary">
              {customerName(ticket.customer_id)}
            </span>
            <span className="text-xs text-text-dim capitalize">
              · {customerTier(ticket.customer_id)}
            </span>
          </div>
        </div>
        <button
          onClick={() => router.push(`/tickets/${ticket.ticket_id}`)}
          className="text-xs text-text-muted hover:text-text-secondary border border-border rounded-input px-3 py-1.5"
        >
          Full detail →
        </button>
      </div>

      {/* Q1/Q2/Q3 */}
      <div className="border border-border rounded-container p-4">
        <p className="text-[10px] text-text-dim uppercase tracking-wider mb-3">
          Decision Gates
        </p>
        <div className="space-y-2">
          {[
            { key: "q1_identified", label: "Q1 — Order & customer identified" },
            { key: "q2_in_policy", label: "Q2 — Request within policy" },
            { key: "q3_confident", label: "Q3 — Confidence threshold met" },
          ].map(({ key, label }) => {
            const val = audit.reasoning[key as keyof typeof audit.reasoning];
            return (
              <div key={key} className="flex items-center gap-3">
                <span
                  className={clsx(
                    "text-sm font-medium",
                    val === true
                      ? "text-resolution-approve"
                      : val === false
                      ? "text-resolution-deny"
                      : "text-text-dim"
                  )}
                >
                  {val === true ? "✓" : val === false ? "✗" : "—"}
                </span>
                <span className="text-xs text-text-secondary">{label}</span>
              </div>
            );
          })}
        </div>
      </div>

      {/* Confidence */}
      {audit.confidence_score != null && audit.confidence_factors && (
        <div className="border border-border rounded-container p-4">
          <ConfidenceBars
            score={audit.confidence_score}
            factors={audit.confidence_factors}
          />
        </div>
      )}

      {/* Reply preview */}
      {audit.tool_calls && (() => {
        const replyCall = [...audit.tool_calls].reverse().find(
          (tc) => tc.tool_name === "send_reply"
        );
        const msg =
          replyCall?.input_args?.message as string | undefined ??
          (replyCall?.output as { message_preview?: string })?.message_preview;
        if (!msg) return null;
        return (
          <div className="border border-border rounded-container p-4 bg-bg-elevated">
            <p className="text-[10px] text-text-dim uppercase tracking-wider mb-2">
              Customer Reply
            </p>
            <pre className="text-xs text-text-secondary whitespace-pre-wrap font-sans leading-relaxed line-clamp-6">
              {msg}
            </pre>
          </div>
        );
      })()}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export default function DashboardPage() {
  const router = useRouter();
  const {
    tickets,
    selectedTicketId,
    auditRecords,
    processingTickets,
    setTickets,
    selectTicket,
    setAuditRecord,
    setTicketStatus,
    setProcessing,
    clearStreamEvents,
  } = useStore();

  const [resolving, setResolving] = useState(false);

  // Load tickets on mount
  useEffect(() => {
    api.tickets().then((data) => {
      setTickets(data);
      // Populate audit records from tickets that already have them
      data.forEach((t) => {
        const td = t as Ticket & { audit_record?: AuditRecord };
        if (td.audit_record) {
          setAuditRecord(t.ticket_id, td.audit_record);
        }
      });
    });
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const selectedTicket = tickets.find((t) => t.ticket_id === selectedTicketId) ?? null;
  const selectedAudit = selectedTicketId ? auditRecords[selectedTicketId] : null;
  const isProcessing = selectedTicketId
    ? processingTickets.has(selectedTicketId)
    : false;

  function handleResolve() {
    if (!selectedTicketId || resolving) return;
    setResolving(true);
    setProcessing(selectedTicketId, true);
    clearStreamEvents(selectedTicketId);
  }

  function handleStreamComplete(events: SSEEvent[]) {
    if (!selectedTicketId) return;
    setResolving(false);
    setProcessing(selectedTicketId, false);

    // Extract resolution from events
    const resEvent = events.find((e) => e.type === "resolution") as
      | { type: "resolution"; resolution: string }
      | undefined;
    if (resEvent) {
      const status =
        resEvent.resolution === "APPROVE"
          ? "resolved"
          : resEvent.resolution === "DENY"
          ? "denied"
          : "escalated";
      setTicketStatus(selectedTicketId, status as Ticket["status"]);
    }

    // Refresh ticket detail to get audit record
    api.ticket(selectedTicketId).then((detail) => {
      if (detail.audit_record) {
        setAuditRecord(selectedTicketId, detail.audit_record);
      }
    });
  }

  return (
    <div className="flex h-[calc(100vh-48px)]">
      {/* Sidebar */}
      <aside className="w-[260px] shrink-0 border-r border-border flex flex-col">
        <div className="flex items-center justify-between px-4 py-3 border-b border-border">
          <span className="text-xs text-text-muted">
            {tickets.length} tickets
          </span>
          <button
            onClick={() => router.push("/run")}
            className="text-[11px] font-medium bg-accent hover:bg-accent-hover text-white px-3 py-1 rounded-badge transition-colors"
          >
            Run All 20
          </button>
        </div>
        <div className="flex-1 overflow-y-auto">
          <TicketList
            tickets={tickets}
            selectedId={selectedTicketId}
            onSelect={selectTicket}
          />
        </div>
      </aside>

      {/* Main area */}
      <main className="flex-1 overflow-y-auto">
        {!selectedTicket ? (
          <div className="flex flex-col items-center justify-center h-full text-center">
            <div className="w-12 h-12 rounded-container border border-border flex items-center justify-center mb-4">
              <span className="text-text-dim text-xl">↖</span>
            </div>
            <p className="text-sm text-text-muted">Select a ticket to begin</p>
            <p className="text-xs text-text-dim mt-1">
              Choose from the sidebar to view or resolve
            </p>
          </div>
        ) : (
          <div className="p-6 max-w-2xl">
            {/* Ticket header */}
            <div className="mb-6 pb-4 border-b border-border">
              <div className="flex items-start justify-between gap-4">
                <div>
                  <div className="flex items-center gap-2 mb-1">
                    <span className="font-mono text-lg text-text-primary">
                      {selectedTicket.ticket_id}
                    </span>
                    <span className="text-xs text-text-dim capitalize">
                      {selectedTicket.issue_type.replace(/_/g, " ")}
                    </span>
                  </div>
                  <div className="flex items-center gap-2">
                    <span
                      className="w-1.5 h-1.5 rounded-full"
                      style={{
                        backgroundColor: tierColor(
                          customerTier(selectedTicket.customer_id)
                        ),
                      }}
                    />
                    <span className="text-sm text-text-secondary">
                      {customerName(selectedTicket.customer_id)}
                    </span>
                  </div>
                </div>
                {!selectedAudit && !isProcessing && (
                  <button
                    onClick={handleResolve}
                    className="shrink-0 text-xs font-medium bg-accent hover:bg-accent-hover text-white px-4 py-2 rounded-input transition-colors"
                  >
                    Resolve ticket
                  </button>
                )}
              </div>
              <p className="mt-3 text-xs text-text-secondary leading-relaxed">
                {selectedTicket.description}
              </p>
            </div>

            {/* Stream or detail */}
            {isProcessing && (
              <AgentStream
                ticketId={selectedTicketId!}
                onComplete={handleStreamComplete}
              />
            )}

            {!isProcessing && selectedAudit && (
              <TicketDetailPanel
                ticket={selectedTicket}
                audit={selectedAudit}
              />
            )}
          </div>
        )}
      </main>
    </div>
  );
}
