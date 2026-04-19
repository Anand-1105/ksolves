"use client";

import { useEffect, useState, useMemo } from "react";
import { useRouter } from "next/navigation";
import clsx from "clsx";
import { api } from "@/lib/api";
import type { AuditRecord, Resolution } from "@/lib/types";
import { customerName } from "@/lib/utils";
import ResolutionBadge from "@/components/ResolutionBadge";

type SortKey = "ticket_id" | "customer" | "issue_type" | "resolution" | "confidence" | "tool_calls" | "timestamp";
type SortDir = "asc" | "desc";

const RESOLUTION_FILTERS: Array<{ label: string; value: Resolution | "ALL" }> = [
  { label: "All", value: "ALL" },
  { label: "Approved", value: "APPROVE" },
  { label: "Denied", value: "DENY" },
  { label: "Escalated", value: "ESCALATE" },
];

export default function AuditPage() {
  const router = useRouter();
  const [records, setRecords] = useState<AuditRecord[]>([]);
  const [loading, setLoading] = useState(true);
  const [sortKey, setSortKey] = useState<SortKey>("ticket_id");
  const [sortDir, setSortDir] = useState<SortDir>("asc");
  const [filter, setFilter] = useState<Resolution | "ALL">("ALL");

  useEffect(() => {
    api.auditLog().then((data) => {
      setRecords(data.ticket_audit ?? []);
      setLoading(false);
    });
  }, []);

  function handleSort(key: SortKey) {
    if (sortKey === key) {
      setSortDir((d) => (d === "asc" ? "desc" : "asc"));
    } else {
      setSortKey(key);
      setSortDir("asc");
    }
  }

  const filtered = useMemo(() => {
    let data = [...records];
    if (filter !== "ALL") {
      data = data.filter((r) => r.resolution === filter);
    }
    data.sort((a, b) => {
      let av: string | number = "";
      let bv: string | number = "";
      switch (sortKey) {
        case "ticket_id":
          av = a.ticket_id;
          bv = b.ticket_id;
          break;
        case "customer":
          av = customerName(a.customer_id);
          bv = customerName(b.customer_id);
          break;
        case "resolution":
          av = a.resolution ?? "";
          bv = b.resolution ?? "";
          break;
        case "confidence":
          av = a.confidence_score ?? 0;
          bv = b.confidence_score ?? 0;
          break;
        case "tool_calls":
          av = a.tool_calls?.length ?? 0;
          bv = b.tool_calls?.length ?? 0;
          break;
      }
      if (av < bv) return sortDir === "asc" ? -1 : 1;
      if (av > bv) return sortDir === "asc" ? 1 : -1;
      return 0;
    });
    return data;
  }, [records, filter, sortKey, sortDir]);

  function SortIcon({ col }: { col: SortKey }) {
    if (sortKey !== col) return <span className="text-text-dim ml-1">↕</span>;
    return (
      <span className="text-accent ml-1">{sortDir === "asc" ? "↑" : "↓"}</span>
    );
  }

  function ColHeader({
    col,
    label,
  }: {
    col: SortKey;
    label: string;
  }) {
    return (
      <th
        className="px-4 py-3 text-left text-[11px] font-medium text-text-muted uppercase tracking-wider cursor-pointer hover:text-text-secondary select-none"
        onClick={() => handleSort(col)}
      >
        {label}
        <SortIcon col={col} />
      </th>
    );
  }

  return (
    <div className="p-6">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-lg font-semibold text-text-primary">Audit Log</h1>
          <p className="text-xs text-text-muted mt-0.5">
            {records.length} records
          </p>
        </div>

        {/* Filter */}
        <div className="flex items-center gap-1 border border-border rounded-input p-0.5">
          {RESOLUTION_FILTERS.map((f) => (
            <button
              key={f.value}
              onClick={() => setFilter(f.value)}
              className={clsx(
                "px-3 py-1 text-xs rounded-input transition-colors",
                filter === f.value
                  ? "bg-bg-elevated text-text-primary"
                  : "text-text-muted hover:text-text-secondary"
              )}
            >
              {f.label}
            </button>
          ))}
        </div>
      </div>

      {loading ? (
        <div className="text-center py-16 text-text-muted text-sm">
          Loading audit log…
        </div>
      ) : filtered.length === 0 ? (
        <div className="text-center py-16 text-text-muted text-sm">
          No records found
        </div>
      ) : (
        <div className="border border-border rounded-container overflow-hidden">
          <table className="w-full">
            <thead className="border-b border-border bg-bg-surface">
              <tr>
                <ColHeader col="ticket_id" label="Ticket" />
                <ColHeader col="customer" label="Customer" />
                <th className="px-4 py-3 text-left text-[11px] font-medium text-text-muted uppercase tracking-wider">
                  Issue Type
                </th>
                <ColHeader col="resolution" label="Resolution" />
                <ColHeader col="confidence" label="Confidence" />
                <ColHeader col="tool_calls" label="Tool Calls" />
                <th className="px-4 py-3 text-left text-[11px] font-medium text-text-muted uppercase tracking-wider">
                  Refund / Case
                </th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((record, i) => (
                <tr
                  key={record.ticket_id}
                  onClick={() => router.push(`/tickets/${record.ticket_id}`)}
                  className={clsx(
                    "cursor-pointer transition-colors border-b border-border-subtle last:border-0",
                    i % 2 === 0 ? "bg-bg-base" : "bg-bg-surface",
                    "hover:bg-bg-hover"
                  )}
                >
                  <td className="px-4 py-3">
                    <span className="font-mono text-xs text-text-primary">
                      {record.ticket_id}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <span className="text-xs text-text-secondary">
                      {customerName(record.customer_id)}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <span className="text-xs text-text-muted capitalize">
                      {/* We don't have issue_type in audit record, show customer_id */}
                      {record.escalation_category?.replace(/_/g, " ") ?? "—"}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <ResolutionBadge resolution={record.resolution} size="sm" />
                  </td>
                  <td className="px-4 py-3">
                    {record.confidence_score != null ? (
                      <div className="flex items-center gap-2">
                        <div className="w-16 h-1 bg-bg-elevated rounded-full overflow-hidden">
                          <div
                            className="h-full rounded-full"
                            style={{
                              width: `${Math.round(record.confidence_score * 100)}%`,
                              backgroundColor:
                                record.confidence_score >= 0.9
                                  ? "#22c55e"
                                  : record.confidence_score >= 0.7
                                  ? "#6366f1"
                                  : "#f59e0b",
                            }}
                          />
                        </div>
                        <span className="text-xs tabular-nums text-text-secondary">
                          {Math.round(record.confidence_score * 100)}%
                        </span>
                      </div>
                    ) : (
                      <span className="text-xs text-text-dim">—</span>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    <span className="text-xs tabular-nums text-text-secondary">
                      {record.tool_calls?.length ?? 0}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <span className="font-mono text-[11px] text-text-muted">
                      {record.refund_id ?? record.case_id ?? "—"}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
