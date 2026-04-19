import { create } from "zustand";
import type { Ticket, AuditRecord, SSEEvent, TicketStatus } from "./types";

interface ShopWaveStore {
  // State
  tickets: Ticket[];
  selectedTicketId: string | null;
  auditRecords: Record<string, AuditRecord>;
  processingTickets: Set<string>;
  streamEvents: Record<string, SSEEvent[]>;

  // Actions
  setTickets: (tickets: Ticket[]) => void;
  selectTicket: (id: string | null) => void;
  setTicketStatus: (ticketId: string, status: TicketStatus) => void;
  addStreamEvent: (ticketId: string, event: SSEEvent) => void;
  clearStreamEvents: (ticketId: string) => void;
  setAuditRecord: (ticketId: string, record: AuditRecord) => void;
  setProcessing: (ticketId: string, processing: boolean) => void;
}

export const useStore = create<ShopWaveStore>((set) => ({
  tickets: [],
  selectedTicketId: null,
  auditRecords: {},
  processingTickets: new Set(),
  streamEvents: {},

  setTickets: (tickets) => set({ tickets }),

  selectTicket: (id) => set({ selectedTicketId: id }),

  setTicketStatus: (ticketId, status) =>
    set((state) => ({
      tickets: state.tickets.map((t) =>
        t.ticket_id === ticketId ? { ...t, status } : t
      ),
    })),

  addStreamEvent: (ticketId, event) =>
    set((state) => ({
      streamEvents: {
        ...state.streamEvents,
        [ticketId]: [...(state.streamEvents[ticketId] ?? []), event],
      },
    })),

  clearStreamEvents: (ticketId) =>
    set((state) => ({
      streamEvents: {
        ...state.streamEvents,
        [ticketId]: [],
      },
    })),

  setAuditRecord: (ticketId, record) =>
    set((state) => ({
      auditRecords: {
        ...state.auditRecords,
        [ticketId]: record,
      },
    })),

  setProcessing: (ticketId, processing) =>
    set((state) => {
      const next = new Set(state.processingTickets);
      if (processing) {
        next.add(ticketId);
      } else {
        next.delete(ticketId);
      }
      return { processingTickets: next };
    }),
}));
