from __future__ import annotations
from typing import Any, Optional
from typing_extensions import TypedDict
from enum import Enum


class Resolution(str, Enum):
    APPROVE = "APPROVE"
    DENY = "DENY"
    ESCALATE = "ESCALATE"


class EscalationCategory(str, Enum):
    WARRANTY_CLAIM = "warranty_claim"
    THREAT_DETECTED = "threat_detected"
    SOCIAL_ENGINEERING = "social_engineering"
    AMBIGUOUS_REQUEST = "ambiguous_request"
    MISSING_DATA = "missing_data"
    REPLACEMENT_NEEDED = "replacement_needed"


class ToolCallRecord(TypedDict):
    tool_name: str
    input_args: dict
    output: Any
    timestamp: str  # ISO 8601


class ReplanRecord(TypedDict):
    trigger: str           # what caused the replan
    alternative_path: str  # description of the alternative taken
    outcome: str           # "succeeded" | "failed"


class CheckpointRecord(TypedDict):
    ticket_id: str
    proposed_action: str
    amount_or_category: Any
    reasoning_summary: str
    auto_approved: bool
    timestamp: str  # ISO 8601


class SessionRecord(TypedDict):
    ticket_id: str
    resolution: str                    # APPROVE | DENY | ESCALATE
    escalation_category: Optional[str]
    fraud_flags: list                  # ["threat_detected", "social_engineering"]
    timestamp: str                     # ISO 8601


class TicketState(TypedDict):
    # Input
    ticket: dict
    ticket_id: str

    # Retrieved data
    order: Optional[dict]
    customer: Optional[dict]
    product: Optional[dict]
    kb_result: Optional[str]

    # Tool call history (ordered)
    tool_calls: list  # List[ToolCallRecord]

    # Replanning
    replan_attempts: list  # List[ReplanRecord]
    failed_tool_calls: list  # List[str] — "tool_name:arg_hash" to prevent duplicate retries

    # Decision flags
    q1_identified: Optional[bool]
    q2_in_policy: Optional[bool]
    q3_confident: Optional[bool]

    # Confidence scoring
    confidence_score: Optional[float]
    confidence_factors: Optional[dict]  # {data_completeness, reason_clarity, policy_consistency}
    self_reflection_note: Optional[str]

    # Resolution
    resolution: Optional[str]          # Resolution enum value
    escalation_category: Optional[str] # EscalationCategory enum value
    denial_reason: Optional[str]
    refund_amount: Optional[float]
    refund_id: Optional[str]
    case_id: Optional[str]

    # HITL
    checkpoint_events: list  # List[CheckpointRecord]

    # Session memory snapshot (read at start of processing)
    prior_customer_records: list  # List[SessionRecord]

    # Error tracking
    processing_error: Optional[str]

    # Routing helper (used by graph nodes to signal next step)
    next_node: Optional[str]

    # Audit record built by write_audit node
    audit_record: Optional[dict]

    # Sentiment analysis (populated by analyze_sentiment node)
    sentiment: Optional[dict]          # Full sentiment analysis result
    primary_emotion: Optional[str]     # angry/frustrated/confused/desperate/calm/sarcastic/neutral
    churn_risk: Optional[str]          # high/medium/low
    urgency: Optional[str]             # critical/high/medium/low
    recommended_tone: Optional[str]    # e.g. empathetic_and_apologetic


def initial_state(ticket: dict) -> TicketState:
    """Create a fresh TicketState from a raw ticket dict."""
    return TicketState(
        ticket=ticket,
        ticket_id=ticket.get("ticket_id", ""),
        order=None,
        customer=None,
        product=None,
        kb_result=None,
        tool_calls=[],
        replan_attempts=[],
        failed_tool_calls=[],
        q1_identified=None,
        q2_in_policy=None,
        q3_confident=None,
        confidence_score=None,
        confidence_factors=None,
        self_reflection_note=None,
        resolution=None,
        escalation_category=None,
        denial_reason=None,
        refund_amount=None,
        refund_id=None,
        case_id=None,
        checkpoint_events=[],
        prior_customer_records=[],
        processing_error=None,
        next_node=None,
        audit_record=None,
        sentiment=None,
        primary_emotion=None,
        churn_risk=None,
        urgency=None,
        recommended_tone=None,
    )
