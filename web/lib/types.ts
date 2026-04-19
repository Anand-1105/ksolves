export type Resolution = "APPROVE" | "DENY" | "ESCALATE";

export type TicketStatus = "pending" | "resolved" | "escalated" | "denied" | "error";

export type CustomerTier = "vip" | "premium" | "standard";

export interface Ticket {
  ticket_id: string;
  customer_id: string;
  order_id: string | null;
  issue_type: string;
  description: string;
  metadata: {
    priority: string;
    channel: string;
  };
  status: TicketStatus;
}

export interface ToolCallRecord {
  tool_name: string;
  input_args: Record<string, unknown>;
  output: Record<string, unknown>;
  timestamp: string;
}

export interface ConfidenceFactors {
  data_completeness: number;
  reason_clarity: number;
  policy_consistency: number;
}

export interface SentimentResult {
  primary_emotion: string;
  churn_risk: string;
  urgency: string;
  recommended_tone: string;
  analysis_method: string;
}

export interface AuditRecord {
  ticket_id: string;
  customer_id: string;
  tool_calls: ToolCallRecord[];
  reasoning: {
    q1_identified: boolean | null;
    q2_in_policy: boolean | null;
    q3_confident: boolean | null;
  };
  confidence_score: number | null;
  confidence_factors: ConfidenceFactors | null;
  self_reflection_note: string | null;
  replan_attempts: unknown[];
  checkpoint_events: unknown[];
  resolution: Resolution | null;
  escalation_category: string | null;
  refund_id: string | null;
  refund_amount: number | null;
  case_id: string | null;
  denial_reason: string | null;
  processing_error: string | null;
  sentiment: SentimentResult | null;
}

export interface TicketDetail extends Ticket {
  audit_record: AuditRecord | null;
}

// SSE event types
export interface SSEToolCallEvent {
  type: "tool_call";
  ticket_id: string;
  tool_name: string;
  args: Record<string, unknown>;
  result: Record<string, unknown>;
  timestamp: string;
}

export interface SSEDecisionEvent {
  type: "decision";
  ticket_id: string;
  question: string;
  value: boolean;
}

export interface SSEConfidenceEvent {
  type: "confidence";
  ticket_id: string;
  score: number;
  factors: ConfidenceFactors;
}

export interface SSECheckpointEvent {
  type: "checkpoint";
  ticket_id: string;
  proposed_action: string;
  auto_approved: boolean;
  debate_transcript?: Array<{ role: string; argument: string }>;
}

export interface SSEResolutionEvent {
  type: "resolution";
  ticket_id: string;
  resolution: Resolution;
  category: string | null;
  refund_id: string | null;
  case_id: string | null;
}

export interface SSEReplyEvent {
  type: "reply";
  ticket_id: string;
  message: string;
}

export interface SSEErrorEvent {
  type: "error";
  ticket_id: string;
  message: string;
}

export interface SSEDoneEvent {
  type: "done";
  ticket_id: string;
}

export interface SSEAllDoneEvent {
  type: "all_done";
  total: number;
}

export type SSEEvent =
  | SSEToolCallEvent
  | SSEDecisionEvent
  | SSEConfidenceEvent
  | SSECheckpointEvent
  | SSEResolutionEvent
  | SSEReplyEvent
  | SSEErrorEvent
  | SSEDoneEvent
  | SSEAllDoneEvent;

export interface Customer {
  customer_id: string;
  name: string;
  email: string;
  tier: CustomerTier;
  vip_exceptions: Record<string, unknown>;
}
