"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import clsx from "clsx";
import { api } from "@/lib/api";
import type { Ticket, SSEEvent, Resolution } from "@/lib/types";
import { customerName } from "@/lib/utils";
import ResolutionBadge from "@/components/ResolutionBadge";
import ConfidenceChart from "@/components/ConfidenceChart";

interface CardState {
  status: "idle" | "processing" | "done" | "error";
  resolution: Resolution | null;
  confidence: number | null;
  error?: string;
}

export default function RunAllPage() {
  const router = useRouter();
  const [tickets, setTickets] = useState<Ticket[]>([]);
  const [cards, setCards] = useState<Record<string, CardState>>({});
  const [running, setRunning] = useState(false);
  const [done, setDone] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [stats, setStats] = useState({ resolved: 0, escalated: 0, denied: 0 });
  const startTimeRef = useRef<number>(0);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const cancelRef = useRef<(() => void) | null>(null);

  useEffect(() => {
    api.tickets().then(setTickets);
  }, []);

  useEffect(() => {
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
      cancelRef.current?.();
    };
  }, []);

  function startRun() {
    if (running) return;

    // Reset state
    const initial: Record<string, CardState> = {};
    tickets.forEach((t) => {
      initial[t.ticket_id] = { status: "idle", resolution: null, confidence: null };
    });
    setCards(initial);
    setStats({ resolved: 0, escalated: 0, denied: 0 });
    setElapsed(0);
    setDone(false);
    setRunning(true);

    startTimeRef.current = Date.now();
    timerRef.current = setInterval(() => {
      setElapsed(Math.floor((Date.now() - startTimeRef.current) / 1000));
    }, 1000);

    cancelRef.current = api.runAllStream(
      (event: SSEEvent) => {
        if (event.type === "tool_call" || event.type === "decision" || event.type === "confidence") {
          const tid = event.ticket_id;
          setCards((prev) => ({
            ...prev,
            [tid]: { ...prev[tid], status: "processing" },
          }));
        }

        if (event.type === "confidence") {
          const tid = event.ticket_id;
          setCards((prev) => ({
            ...prev,
            [tid]: { ...prev[tid], confidence: event.score },
          }));
        }

        if (event.type === "resolution") {
          const tid = event.ticket_id;
          const res = event.resolution;
          setCards((prev) => ({
            ...prev,
            [tid]: { ...prev[tid], status: "done", resolution: res },
          }));
          setStats((prev) => ({
            resolved: prev.resolved + (res === "APPROVE" ? 1 : 0),
            escalated: prev.escalated + (res === "ESCALATE" ? 1 : 0),
            denied: prev.denied + (res === "DENY" ? 1 : 0),
          }));
        }

        if (event.type === "error" && "ticket_id" in event) {
          const tid = event.ticket_id;
          setCards((prev) => ({
            ...prev,
            [tid]: { status: "error", resolution: null, confidence: null, error: event.message },
          }));
        }
      },
      () => {
        setRunning(false);
        setDone(true);
        if (timerRef.current) clearInterval(timerRef.current);
      },
      (err) => {
        setRunning(false);
        setDone(true);
        if (timerRef.current) clearInterval(timerRef.current);
        console.error("Run all error:", err);
      }
    );
  }

  function formatElapsed(s: number): string {
    const m = Math.floor(s / 60);
    const sec = s % 60;
    return m > 0 ? `${m}m ${sec}s` : `${sec}s`;
  }

  return (
    <div className="p-6 max-w-5xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-lg font-semibold text-text-primary">Run All Tickets</h1>
          <p className="text-xs text-text-muted mt-0.5">
            Process all 20 support tickets concurrently
          </p>
        </div>
        <button
          onClick={startRun}
          disabled={running || tickets.length === 0}
          className={clsx(
            "text-sm font-medium px-5 py-2 rounded-input transition-colors",
            running || tickets.length === 0
              ? "bg-bg-elevated text-text-dim cursor-not-allowed"
              : "bg-accent hover:bg-accent-hover text-white"
          )}
        >
          {running ? "Running…" : done ? "Run Again" : "Run All 20 Tickets"}
        </button>
      </div>

      {/* Stats bar */}
      {(running || done) && (
        <div className="flex items-center gap-6 mb-6 p-4 border border-border rounded-container bg-bg-surface">
          <StatItem label="Approved" value={stats.resolved} color="#22c55e" />
          <div className="w-px h-6 bg-border" />
          <StatItem label="Escalated" value={stats.escalated} color="#f59e0b" />
          <div className="w-px h-6 bg-border" />
          <StatItem label="Denied" value={stats.denied} color="#ef4444" />
          <div className="w-px h-6 bg-border ml-auto" />
          <div className="text-right">
            <p className="text-xs text-text-muted">Elapsed</p>
            <p className="text-sm font-mono text-text-primary tabular-nums">
              {formatElapsed(elapsed)}
            </p>
          </div>
        </div>
      )}

      {/* Ticket grid */}
      {tickets.length > 0 && (
        <div className="grid grid-cols-4 gap-3">
          {tickets.map((ticket) => {
            const card = cards[ticket.ticket_id];
            const status = card?.status ?? "idle";
            const resolution = card?.resolution ?? null;

            return (
              <div
                key={ticket.ticket_id}
                onClick={() => status === "done" ? router.push(`/tickets/${ticket.ticket_id}`) : undefined}
                className={clsx(
                  "p-3 rounded-container border transition-all",
                  status === "idle" && "border-border bg-bg-surface",
                  status === "processing" && "border-accent bg-bg-surface animate-pulse-border",
                  status === "done" && resolution === "APPROVE" && "border-resolution-approve-border bg-resolution-approve-bg cursor-pointer hover:opacity-80",
                  status === "done" && resolution === "DENY" && "border-resolution-deny-border bg-resolution-deny-bg cursor-pointer hover:opacity-80",
                  status === "done" && resolution === "ESCALATE" && "border-resolution-escalate-border bg-resolution-escalate-bg cursor-pointer hover:opacity-80",
                  status === "error" && "border-resolution-deny-border bg-resolution-deny-bg"
                )}
                title={status === "done" ? `View ${ticket.ticket_id} detail` : undefined}
              >
                <div className="flex items-center justify-between mb-1.5">
                  <span className="font-mono text-[11px] text-text-muted">
                    {ticket.ticket_id}
                  </span>
                  {status === "processing" && (
                    <span className="flex gap-0.5">
                      {[0, 1, 2].map((i) => (
                        <span
                          key={i}
                          className="w-1 h-1 rounded-full bg-accent animate-pulse"
                          style={{ animationDelay: `${i * 150}ms` }}
                        />
                      ))}
                    </span>
                  )}
                  {status === "done" && resolution && (
                    <ResolutionBadge resolution={resolution} size="sm" />
                  )}
                  {status === "error" && (
                    <span className="text-[10px] text-resolution-deny">error</span>
                  )}
                </div>
                <p className="text-xs text-text-secondary truncate">
                  {customerName(ticket.customer_id)}
                </p>
                <p className="text-[10px] text-text-dim capitalize mt-0.5 truncate">
                  {ticket.issue_type.replace(/_/g, " ")}
                </p>
                {status === "done" && (
                  <p className="text-[9px] text-text-dim mt-1 opacity-60">tap to view →</p>
                )}
              </div>
            );
          })}
        </div>
      )}

      {done && (
        <div className="mt-6 space-y-4">
          {/* Confidence trend chart */}
          <ConfidenceChart
            data={tickets
              .map((t) => ({
                ticketId: t.ticket_id,
                score: cards[t.ticket_id]?.confidence ?? 0,
                resolution: cards[t.ticket_id]?.resolution ?? null,
              }))
              .filter((d) => d.score > 0)}
          />

          <div className="p-4 border border-border rounded-container text-center">
            <p className="text-sm text-text-secondary">
              All {tickets.length} tickets processed in{" "}
              <span className="font-mono text-text-primary">{formatElapsed(elapsed)}</span>
            </p>
            <p className="text-xs text-text-muted mt-1">
              Audit log updated — view results in the{" "}
              <a href="/audit" className="text-accent hover:underline">
                Audit Log
              </a>
              {" "}or check{" "}
              <a href="/learnings" className="text-accent hover:underline">
                Agent Learnings
              </a>
            </p>
          </div>
        </div>
      )}
    </div>
  );
}

function StatItem({
  label,
  value,
  color,
}: {
  label: string;
  value: number;
  color: string;
}) {
  return (
    <div>
      <p className="text-xs text-text-muted">{label}</p>
      <p
        className="text-xl font-semibold tabular-nums"
        style={{ color }}
      >
        {value}
      </p>
    </div>
  );
}
