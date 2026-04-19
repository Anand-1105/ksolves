"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import clsx from "clsx";
import { api } from "@/lib/api";
import type { TicketDetail, ToolCallRecord } from "@/lib/types";
import { customerName, customerTier, tierColor, tierLabel } from "@/lib/utils";
import ResolutionBadge from "@/components/ResolutionBadge";
import ConfidenceBars from "@/components/ConfidenceBars";

// ---------------------------------------------------------------------------
// Fraud phrase highlighting
// ---------------------------------------------------------------------------

const THREAT_PHRASES = [
  "sue", "lawyer", "legal action", "lawsuit", "attorney", "court",
  "chargeback", "dispute with my bank", "report you", "showing up in person",
];

const SOCIAL_ENGINEERING_PHRASES = [
  "on behalf of", "authorized representative", "bypass", "without requiring",
  "act on his behalf", "act on her behalf", "urgent", "immediately without",
  "skip verification", "no questions",
];

function HighlightedDescription({
  text,
  escalationCategory,
}: {
  text: string;
  escalationCategory: string | null | undefined;
}) {
  const isThreat = escalationCategory === "threat_detected";
  const isSocial = escalationCategory === "social_engineering";

  if (!isThreat && !isSocial) {
    return <p className="text-xs text-text-secondary leading-relaxed">{text}</p>;
  }

  const phrases = isThreat ? THREAT_PHRASES : SOCIAL_ENGINEERING_PHRASES;
  const color = isThreat ? "#ef4444" : "#f59e0b";
  const bgColor = isThreat ? "#2d0a0a" : "#2d1a00";

  // Build regex from phrases, longest first to avoid partial matches
  const sorted = [...phrases].sort((a, b) => b.length - a.length);
  const pattern = new RegExp(`(${sorted.map((p) => p.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|")})`, "gi");

  const parts = text.split(pattern);

  return (
    <p className="text-xs text-text-secondary leading-relaxed">
      {parts.map((part, i) => {
        const isMatch = phrases.some((p) => p.toLowerCase() === part.toLowerCase());
        if (isMatch) {
          return (
            <mark
              key={i}
              title={isThreat ? "Threat language detected" : "Social engineering pattern detected"}
              style={{ backgroundColor: bgColor, color, borderBottom: `1px solid ${color}` }}
              className="rounded px-0.5 font-medium not-italic"
            >
              {part}
            </mark>
          );
        }
        return <span key={i}>{part}</span>;
      })}
    </p>
  );
}

// ---------------------------------------------------------------------------
// Debate transcript panel
// ---------------------------------------------------------------------------

const ROLE_STYLES: Record<string, { label: string; color: string; bg: string; border: string }> = {
  advocate: {
    label: "Advocate",
    color: "#22c55e",
    bg: "#052e16",
    border: "#14532d",
  },
  skeptic: {
    label: "Skeptic",
    color: "#f59e0b",
    bg: "#2d1a00",
    border: "#78350f",
  },
  judge: {
    label: "Judge",
    color: "#6366f1",
    bg: "#1e1b4b",
    border: "#312e81",
  },
};

function DebatePanel({
  transcript,
}: {
  transcript: Array<{ role: string; argument: string }>;
}) {
  return (
    <section>
      <div className="flex items-center gap-2 mb-3">
        <h2 className="text-xs font-medium text-text-muted uppercase tracking-wider">
          Multi-Agent Debate
        </h2>
        <span className="text-[10px] text-text-dim border border-border rounded-badge px-1.5 py-0.5">
          High-stakes review
        </span>
      </div>
      <div className="space-y-3">
        {transcript.map((entry, i) => {
          const style = ROLE_STYLES[entry.role] ?? {
            label: entry.role,
            color: "#71717a",
            bg: "#18181b",
            border: "#27272a",
          };
          return (
            <div
              key={i}
              className="rounded-container border p-4"
              style={{ backgroundColor: style.bg, borderColor: style.border }}
            >
              <div className="flex items-center gap-2 mb-2">
                <span
                  className="text-[11px] font-semibold uppercase tracking-wider"
                  style={{ color: style.color }}
                >
                  {style.label}
                </span>
                {entry.role === "judge" && (
                  <span className="text-[10px] text-text-dim">— Final decision</span>
                )}
              </div>
              <p className="text-xs text-text-secondary leading-relaxed">
                {entry.argument}
              </p>
            </div>
          );
        })}
      </div>
    </section>
  );
}

// ---------------------------------------------------------------------------
// Tool call step
// ---------------------------------------------------------------------------

function ToolCallStep({ tc, index }: { tc: ToolCallRecord; index: number }) {
  const [open, setOpen] = useState(false);

  return (
    <div className="flex gap-4">
      {/* Timeline line */}
      <div className="flex flex-col items-center">
        <div className="w-2 h-2 rounded-full bg-border-strong mt-1.5 shrink-0" />
        <div className="w-px flex-1 bg-border-subtle mt-1" />
      </div>

      <div className="flex-1 pb-4 min-w-0">
        <button
          onClick={() => setOpen((v) => !v)}
          className="flex items-center gap-2 w-full text-left group mb-1"
        >
          <span className="font-mono text-[11px] bg-bg-elevated border border-border px-2 py-0.5 rounded-input text-accent">
            {tc.tool_name}
          </span>
          <span className="text-[10px] text-text-dim group-hover:text-text-muted transition-colors">
            {open ? "▲" : "▼"}
          </span>
          <span className="ml-auto text-[10px] text-text-dim tabular-nums">
            {tc.timestamp
              ? new Date(tc.timestamp).toLocaleTimeString("en-US", {
                  hour: "2-digit",
                  minute: "2-digit",
                  second: "2-digit",
                })
              : ""}
          </span>
        </button>

        {open && (
          <div className="grid grid-cols-2 gap-3 mt-2">
            <div>
              <p className="text-[10px] text-text-dim uppercase tracking-wider mb-1">
                Input
              </p>
              <pre className="text-[11px] text-text-secondary bg-bg-elevated border border-border rounded-input p-2 overflow-auto max-h-48">
                {JSON.stringify(tc.input_args, null, 2)}
              </pre>
            </div>
            <div>
              <p className="text-[10px] text-text-dim uppercase tracking-wider mb-1">
                Output
              </p>
              <pre className="text-[11px] text-text-secondary bg-bg-elevated border border-border rounded-input p-2 overflow-auto max-h-48">
                {JSON.stringify(tc.output, null, 2)}
              </pre>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

export default function TicketDetailPage({
  params,
}: {
  params: { id: string };
}) {
  const router = useRouter();
  const [detail, setDetail] = useState<TicketDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [debateTranscript, setDebateTranscript] = useState<Array<{ role: string; argument: string }> | null>(null);

  useEffect(() => {
    api.ticket(params.id).then((data) => {
      setDetail(data);
      setLoading(false);
    });
    // Load debate transcript if available
    api.debate(params.id).then((data) => {
      if (data.debate_transcript) {
        setDebateTranscript(data.debate_transcript);
      }
    }).catch(() => {
      // No debate for this ticket — that's fine
    });
  }, [params.id]);

  if (loading) {
    return (
      <div className="p-6 text-text-muted text-sm">Loading ticket…</div>
    );
  }

  if (!detail) {
    return (
      <div className="p-6 text-text-muted text-sm">Ticket not found.</div>
    );
  }

  const audit = detail.audit_record;
  const tier = customerTier(detail.customer_id);

  // Extract reply message
  let replyMessage: string | null = null;
  if (audit?.tool_calls) {
    const replyCall = [...audit.tool_calls].reverse().find(
      (tc) => tc.tool_name === "send_reply"
    );
    replyMessage =
      (replyCall?.input_args?.message as string | undefined) ??
      ((replyCall?.output as { message_preview?: string })?.message_preview ?? null);
  }

  return (
    <div className="p-6 max-w-3xl">
      {/* Back */}
      <button
        onClick={() => router.back()}
        className="flex items-center gap-1.5 text-xs text-text-muted hover:text-text-secondary mb-6 transition-colors"
      >
        ← Tickets
      </button>

      {/* Header */}
      <div className="flex items-start justify-between mb-6 pb-4 border-b border-border">
        <div>
          <div className="flex items-center gap-3 mb-2">
            <span className="font-mono text-2xl text-text-primary">
              {detail.ticket_id}
            </span>
            {audit && <ResolutionBadge resolution={audit.resolution} size="lg" />}
          </div>
          <div className="flex items-center gap-2">
            <span
              className="w-2 h-2 rounded-full"
              style={{ backgroundColor: tierColor(tier) }}
            />
            <span className="text-sm text-text-secondary">
              {customerName(detail.customer_id)}
            </span>
            <span
              className="text-xs font-medium rounded-badge px-2 py-0.5 border"
              style={{
                color: tierColor(tier),
                borderColor: tierColor(tier) + "40",
                backgroundColor: tierColor(tier) + "15",
              }}
            >
              {tierLabel(tier)}
            </span>
          </div>
        </div>
        <div className="text-right">
          <p className="text-[10px] text-text-dim uppercase tracking-wider mb-1">
            Issue Type
          </p>
          <p className="text-xs text-text-secondary capitalize">
            {detail.issue_type.replace(/_/g, " ")}
          </p>
        </div>
      </div>

      {/* Description */}
      <div className="mb-6 p-4 border border-border rounded-container bg-bg-surface">
        <p className="text-[10px] text-text-dim uppercase tracking-wider mb-2">
          Customer Message
        </p>
        <HighlightedDescription
          text={detail.description}
          escalationCategory={detail.audit_record?.escalation_category}
        />
      </div>

      {!audit ? (
        <div className="text-center py-12 text-text-muted text-sm border border-border rounded-container">
          This ticket has not been processed yet.
        </div>
      ) : (
        <div className="space-y-6">
          {/* Tool call timeline */}
          {audit.tool_calls && audit.tool_calls.length > 0 && (
            <section>
              <h2 className="text-xs font-medium text-text-muted uppercase tracking-wider mb-4">
                Tool Call Timeline
              </h2>
              <div>
                {audit.tool_calls.map((tc, i) => (
                  <ToolCallStep key={i} tc={tc} index={i} />
                ))}
              </div>
            </section>
          )}

          {/* Q1/Q2/Q3 */}
          <section className="border border-border rounded-container p-4">
            <h2 className="text-xs font-medium text-text-muted uppercase tracking-wider mb-4">
              Decision Gates
            </h2>
            <div className="space-y-3">
              {[
                {
                  key: "q1_identified" as const,
                  label: "Q1",
                  desc: "Order & customer identified",
                },
                {
                  key: "q2_in_policy" as const,
                  label: "Q2",
                  desc: "Request within ShopWave policy",
                },
                {
                  key: "q3_confident" as const,
                  label: "Q3",
                  desc: "Confidence threshold met (≥75%)",
                },
              ].map(({ key, label, desc }) => {
                const val = audit.reasoning[key];
                return (
                  <div key={key} className="flex items-center gap-3">
                    <span
                      className={clsx(
                        "text-base font-medium w-5 text-center",
                        val === true
                          ? "text-resolution-approve"
                          : val === false
                          ? "text-resolution-deny"
                          : "text-text-dim"
                      )}
                    >
                      {val === true ? "✓" : val === false ? "✗" : "—"}
                    </span>
                    <span className="font-mono text-xs text-text-muted w-6">
                      {label}
                    </span>
                    <span className="text-xs text-text-secondary">{desc}</span>
                  </div>
                );
              })}
            </div>
          </section>

          {/* Confidence */}
          {audit.confidence_score != null && audit.confidence_factors && (
            <section className="border border-border rounded-container p-4">
              <ConfidenceBars
                score={audit.confidence_score}
                factors={audit.confidence_factors}
              />
            </section>
          )}

          {/* Self-reflection note */}
          {audit.self_reflection_note && (
            <section className="border border-border rounded-container p-4">
              <h2 className="text-xs font-medium text-text-muted uppercase tracking-wider mb-2">
                Agent Reasoning
              </h2>
              <p className="text-xs text-text-secondary leading-relaxed">
                {audit.self_reflection_note}
              </p>
            </section>
          )}

          {/* Sentiment analysis */}
          {audit.sentiment && audit.sentiment.primary_emotion !== "neutral" && (
            <section className="border border-border rounded-container p-4">
              <h2 className="text-xs font-medium text-text-muted uppercase tracking-wider mb-3">
                Customer Sentiment
              </h2>
              <div className="flex flex-wrap gap-4">
                {[
                  { label: "Emotion", value: audit.sentiment.primary_emotion },
                  { label: "Churn Risk", value: audit.sentiment.churn_risk },
                  { label: "Urgency", value: audit.sentiment.urgency },
                  { label: "Tone", value: audit.sentiment.recommended_tone?.replace(/_/g, " ") },
                ].map(({ label, value }) =>
                  value ? (
                    <div key={label}>
                      <p className="text-[10px] text-text-dim uppercase tracking-wider mb-1">{label}</p>
                      <p className="text-xs text-text-secondary capitalize">{value}</p>
                    </div>
                  ) : null
                )}
              </div>
            </section>
          )}

          {/* Multi-agent debate transcript */}
          {debateTranscript && debateTranscript.length > 0 && (
            <DebatePanel transcript={debateTranscript} />
          )}

          {/* Customer reply */}
          {replyMessage && (
            <section>
              <h2 className="text-xs font-medium text-text-muted uppercase tracking-wider mb-3">
                Customer Reply
              </h2>
              <div className="border border-border rounded-container p-4 bg-bg-elevated">
                <pre className="text-xs text-text-secondary whitespace-pre-wrap font-sans leading-relaxed">
                  {replyMessage}
                </pre>
              </div>
            </section>
          )}

          {/* Refund / Case ID */}
          {(audit.refund_id || audit.case_id) && (
            <section className="border border-border rounded-container p-4">
              <div className="flex gap-8">
                {audit.refund_id && (
                  <div>
                    <p className="text-[10px] text-text-dim uppercase tracking-wider mb-1">
                      Refund ID
                    </p>
                    <p className="font-mono text-xs text-text-primary">
                      {audit.refund_id}
                    </p>
                  </div>
                )}
                {audit.case_id && (
                  <div>
                    <p className="text-[10px] text-text-dim uppercase tracking-wider mb-1">
                      Case ID
                    </p>
                    <p className="font-mono text-xs text-text-primary">
                      {audit.case_id}
                    </p>
                  </div>
                )}
                {audit.escalation_category && (
                  <div>
                    <p className="text-[10px] text-text-dim uppercase tracking-wider mb-1">
                      Category
                    </p>
                    <p className="text-xs text-text-secondary capitalize">
                      {audit.escalation_category.replace(/_/g, " ")}
                    </p>
                  </div>
                )}
              </div>
            </section>
          )}
        </div>
      )}
    </div>
  );
}
