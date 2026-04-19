import type { Ticket, TicketDetail, AuditRecord, SSEEvent } from "./types";

const BASE_URL =
  typeof window !== "undefined"
    ? "" // use Next.js proxy in browser
    : process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

async function apiFetch<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, options);
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(`API ${path} failed: ${res.status} ${text}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  health(): Promise<{ status: string }> {
    return apiFetch("/api/health");
  },

  tickets(): Promise<Ticket[]> {
    return apiFetch("/api/tickets");
  },

  ticket(ticketId: string): Promise<TicketDetail> {
    return apiFetch(`/api/tickets/${ticketId}`);
  },

  auditLog(): Promise<{ ticket_audit: AuditRecord[]; execution_metadata: Record<string, unknown> }> {
    return apiFetch("/api/audit-log");
  },

  learnings(): Promise<{ content: string | null; exists: boolean }> {
    return apiFetch("/api/learnings");
  },

  generateLearnings(): Promise<{ content: string | null; exists: boolean }> {
    return apiFetch("/api/generate-learnings", { method: "POST" });
  },

  debate(ticketId: string): Promise<{
    ticket_id: string;
    debate_transcript: Array<{ role: string; argument: string }> | null;
    judge_reasoning: string;
    final_resolution: string;
  }> {
    return apiFetch(`/api/tickets/${ticketId}/debate`);
  },

  /**
   * Consume the SSE stream for resolving a single ticket.
   * Calls `onEvent` for each parsed event, `onDone` when complete.
   */
  resolveTicketStream(
    ticketId: string,
    onEvent: (event: SSEEvent) => void,
    onDone: () => void,
    onError: (err: Error) => void
  ): () => void {
    const controller = new AbortController();

    (async () => {
      try {
        const res = await fetch(`${BASE_URL}/api/tickets/${ticketId}/resolve`, {
          method: "POST",
          signal: controller.signal,
        });

        if (!res.ok || !res.body) {
          throw new Error(`Stream failed: ${res.status}`);
        }

        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split("\n");
          buffer = lines.pop() ?? "";

          for (const line of lines) {
            const trimmed = line.trim();
            if (trimmed.startsWith("data: ")) {
              const data = trimmed.slice(6).trim();
              if (!data || data === "[DONE]") continue;
              try {
                const event = JSON.parse(data) as SSEEvent;
                onEvent(event);
                if (event.type === "done") {
                  onDone();
                  return;
                }
              } catch {
                // skip malformed lines
              }
            }
          }
        }
        onDone();
      } catch (err) {
        if ((err as Error).name !== "AbortError") {
          onError(err as Error);
        }
      }
    })();

    return () => controller.abort();
  },

  /**
   * Consume the SSE stream for running all tickets.
   */
  runAllStream(
    onEvent: (event: SSEEvent) => void,
    onDone: () => void,
    onError: (err: Error) => void
  ): () => void {
    const controller = new AbortController();

    (async () => {
      try {
        const res = await fetch(`${BASE_URL}/api/run-all`, {
          method: "POST",
          signal: controller.signal,
        });

        if (!res.ok || !res.body) {
          throw new Error(`Stream failed: ${res.status}`);
        }

        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split("\n");
          buffer = lines.pop() ?? "";

          for (const line of lines) {
            const trimmed = line.trim();
            if (trimmed.startsWith("data: ")) {
              const data = trimmed.slice(6).trim();
              if (!data || data === "[DONE]") continue;
              try {
                const event = JSON.parse(data) as SSEEvent;
                onEvent(event);
                if (event.type === "all_done") {
                  onDone();
                  return;
                }
              } catch {
                // skip malformed lines
              }
            }
          }
        }
        onDone();
      } catch (err) {
        if ((err as Error).name !== "AbortError") {
          onError(err as Error);
        }
      }
    })();

    return () => controller.abort();
  },
};
