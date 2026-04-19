"use client";

import { useEffect, useRef, useState } from "react";
import clsx from "clsx";
import type {
  SSEEvent,
  SSEToolCallEvent,
  SSEDecisionEvent,
  SSEConfidenceEvent,
  SSEResolutionEvent,
  SSEReplyEvent,
  ConfidenceFactors,
} from "@/lib/types";
import { api } from "@/lib/api";
import ResolutionBadge from "./ResolutionBadge";
import ConfidenceBars from "./ConfidenceBars";

interface Props {
  ticketId: string;
  onComplete?: (events: SSEEvent[]) => void;
}

function ToolCallRow({ event }: { event: SSEToolCallEvent }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="animate-fade-up flex gap-3 py-2">
      <div className="w-px bg-border-strong self-stretch shrink-0 ml-1" />
      <div className="flex-1 min-w-0">
        <button
          onClick={() => setOpen((v) => !v)}
          className="flex items-center gap-2 w-full text-left group"
        >
          <span className="font-mono text-[11px] bg-bg-elevated border border-border px-2 py-0.5 rounded-input text-accent shrink-0">
            {event.tool_name}
          </span>
          <span className="text-xs text-text-dim group-hover:text-text-muted transition-colors">
            {open ? "▲ collapse" : "▼ expand"}
          </span>
          <span className="ml-auto text-[10px] text-text-dim tabular-nums">
            {event.timestamp
              ? new Date(event.timestamp).toLocaleTimeString("en-US", {
                  hour: "2-digit",
                  minute: "2-digit",
                  second: "2-digit",
                })
              : ""}
          </span>
        </button>
        {open && (
          <div className="mt-2 grid grid-cols-2 gap-2">
            <div>
              <p className="text-[10px] text-text-dim uppercase tracking-wider mb-1">
                Result
              </p>
              <pre className="text-[11px] text-text-secondary bg-bg-elevated border border-border rounded-input p-2 overflow-auto max-h-40">
                {JSON.stringify(event.result, null, 2)}
              </pre>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function DecisionRow({ event }: { event: SSEDecisionEvent }) {
  return (
    <div className="animate-fade-up flex items-center gap-3 py-1.5">
      <div className="w-px bg-border-strong self-stretch shrink-0 ml-1" />
      <span
        className={clsx(
          "text-sm font-medium",
          event.value ? "text-resolution-approve" : "text-resolution-deny"
        )}
      >
        {event.value ? "✓" : "✗"}
      </span>
      <span className="text-xs text-text-secondary">
        <span className="font-mono text-text-muted">{event.question}</span>
        {" — "}
        {event.value ? "passed" : "failed"}
      </span>
    </div>
  );
}

function ConfidenceRow({ event }: { event: SSEConfidenceEvent }) {
  return (
    <div className="animate-fade-up py-3 pl-4 border-l border-border-strong">
      <ConfidenceBars score={event.score} factors={event.factors} animate />
    </div>
  );
}

function ResolutionRow({ event }: { event: SSEResolutionEvent }) {
  return (
    <div className="animate-fade-up flex items-center gap-3 py-3 pl-4 border-l-2 border-accent">
      <span className="text-xs text-text-muted">Resolution</span>
      <ResolutionBadge resolution={event.resolution} size="md" />
      {event.refund_id && (
        <span className="font-mono text-[11px] text-text-muted">
          {event.refund_id}
        </span>
      )}
      {event.case_id && (
        <span className="font-mono text-[11px] text-text-muted">
          {event.case_id}
        </span>
      )}
    </div>
  );
}

function ReplyRow({ event }: { event: SSEReplyEvent }) {
  return (
    <div className="animate-fade-up mt-2 p-4 bg-bg-elevated border border-border rounded-container">
      <p className="text-[10px] text-text-dim uppercase tracking-wider mb-2">
        Customer Reply
      </p>
      <pre className="text-xs text-text-secondary whitespace-pre-wrap font-sans leading-relaxed">
        {event.message}
      </pre>
    </div>
  );
}

export default function AgentStream({ ticketId, onComplete }: Props) {
  const [events, setEvents] = useState<SSEEvent[]>([]);
  const [done, setDone] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const eventsRef = useRef<SSEEvent[]>([]);

  useEffect(() => {
    eventsRef.current = [];
    setEvents([]);
    setDone(false);
    setError(null);

    const cancel = api.resolveTicketStream(
      ticketId,
      (event) => {
        eventsRef.current = [...eventsRef.current, event];
        setEvents([...eventsRef.current]);
      },
      () => {
        setDone(true);
        onComplete?.(eventsRef.current);
      },
      (err) => {
        setError(err.message);
        setDone(true);
      }
    );

    return cancel;
  }, [ticketId]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [events]);

  return (
    <div className="flex flex-col gap-0.5">
      <div className="flex items-center gap-2 mb-4">
        <span className="text-xs text-text-muted">Processing</span>
        <span className="font-mono text-xs text-accent">{ticketId}</span>
        {!done && (
          <span className="flex gap-0.5 ml-1">
            {[0, 1, 2].map((i) => (
              <span
                key={i}
                className="w-1 h-1 rounded-full bg-accent animate-pulse"
                style={{ animationDelay: `${i * 150}ms` }}
              />
            ))}
          </span>
        )}
        {done && !error && (
          <span className="text-xs text-resolution-approve ml-1">complete</span>
        )}
        {error && (
          <span className="text-xs text-resolution-deny ml-1">{error}</span>
        )}
      </div>

      <div className="space-y-0.5">
        {events.map((event, i) => {
          if (event.type === "tool_call") {
            return <ToolCallRow key={i} event={event} />;
          }
          if (event.type === "decision") {
            return <DecisionRow key={i} event={event} />;
          }
          if (event.type === "confidence") {
            return <ConfidenceRow key={i} event={event} />;
          }
          if (event.type === "resolution") {
            return <ResolutionRow key={i} event={event} />;
          }
          if (event.type === "reply") {
            return <ReplyRow key={i} event={event} />;
          }
          return null;
        })}
      </div>

      <div ref={bottomRef} />
    </div>
  );
}
