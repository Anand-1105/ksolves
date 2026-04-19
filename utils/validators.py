"""
utils/validators.py — Input/Output Validators

Provides three validation functions used throughout the agent to verify
that tool outputs, audit records, and trace events conform to their
expected schemas.
"""

from __future__ import annotations

from typing import Any


# ---------------------------------------------------------------------------
# Tool-specific required keys (excluding error responses)
# ---------------------------------------------------------------------------

_TOOL_REQUIRED_KEYS: dict[str, list[str]] = {
    "get_order": ["order_id"],
    "get_customer": ["customer_id"],
    "get_product": ["product_id"],
    "check_refund_eligibility": ["eligible"],
    "issue_refund": ["refund_id"],
    "send_reply": ["delivered"],
    "escalate": ["case_id"],
    "search_knowledge_base": ["result"],
}

# Keys whose values must be non-empty strings
_TOOL_NONEMPTY_STRING_KEYS: dict[str, list[str]] = {
    "issue_refund": ["refund_id"],
    "escalate": ["case_id"],
}


def validate_tool_output(tool_name: str, output: Any) -> bool:
    """
    Validate that a tool output conforms to its contract schema.

    Rules:
    - Output must be a dict.
    - If the dict contains an "error" key it is considered a valid error
      response and no further checks are performed.
    - Otherwise, tool-specific required keys must be present:
        get_order            → order_id
        get_customer         → customer_id
        get_product          → product_id
        check_refund_eligibility → eligible (bool)
        issue_refund         → refund_id (non-empty str)
        send_reply           → delivered
        escalate             → case_id (non-empty str)
        search_knowledge_base → result

    Returns True if valid, False otherwise.
    """
    if not isinstance(output, dict):
        return False

    # Error responses are always valid
    if "error" in output:
        return True

    required_keys = _TOOL_REQUIRED_KEYS.get(tool_name, [])
    for key in required_keys:
        if key not in output:
            return False

    # Additional type/value checks
    if tool_name == "check_refund_eligibility":
        eligible = output.get("eligible")
        if not isinstance(eligible, bool) and eligible != "escalate":
            return False

    nonempty_keys = _TOOL_NONEMPTY_STRING_KEYS.get(tool_name, [])
    for key in nonempty_keys:
        value = output.get(key)
        if not isinstance(value, str) or not value:
            return False

    return True


# ---------------------------------------------------------------------------
# Audit record validation
# ---------------------------------------------------------------------------

_AUDIT_REQUIRED_FIELDS = [
    "ticket_id",
    "customer_id",
    "tool_calls",
    "reasoning",
    "confidence_score",
    "confidence_factors",
    "self_reflection_note",
    "replan_attempts",
    "checkpoint_events",
    "resolution",
    "escalation_category",
]

_REASONING_REQUIRED_KEYS = ["q1_identified", "q2_in_policy", "q3_confident"]


def validate_audit_record(record: Any) -> bool:
    """
    Validate that an audit record contains all required fields with correct types.

    Required fields:
    - ticket_id          : str
    - customer_id        : str
    - tool_calls         : list
    - reasoning          : dict with q1_identified, q2_in_policy, q3_confident
    - confidence_score   : float or None
    - confidence_factors : dict or None
    - self_reflection_note : str or None
    - replan_attempts    : list
    - checkpoint_events  : list
    - resolution         : str or None
    - escalation_category: str or None

    Returns True if valid, False otherwise.
    """
    if not isinstance(record, dict):
        return False

    # All required top-level fields must be present
    for field in _AUDIT_REQUIRED_FIELDS:
        if field not in record:
            return False

    # Type checks
    if not isinstance(record["ticket_id"], str):
        return False
    if not isinstance(record["customer_id"], str):
        return False
    if not isinstance(record["tool_calls"], list):
        return False
    if not isinstance(record["replan_attempts"], list):
        return False
    if not isinstance(record["checkpoint_events"], list):
        return False

    # reasoning must be a dict with the three Q keys
    reasoning = record["reasoning"]
    if not isinstance(reasoning, dict):
        return False
    for key in _REASONING_REQUIRED_KEYS:
        if key not in reasoning:
            return False

    # confidence_score: float or None
    cs = record["confidence_score"]
    if cs is not None and not isinstance(cs, (int, float)):
        return False

    # confidence_factors: dict or None
    cf = record["confidence_factors"]
    if cf is not None and not isinstance(cf, dict):
        return False

    # self_reflection_note: str or None
    srn = record["self_reflection_note"]
    if srn is not None and not isinstance(srn, str):
        return False

    # resolution: str or None
    res = record["resolution"]
    if res is not None and not isinstance(res, str):
        return False

    # escalation_category: str or None
    ec = record["escalation_category"]
    if ec is not None and not isinstance(ec, str):
        return False

    return True


# ---------------------------------------------------------------------------
# Trace event validation
# ---------------------------------------------------------------------------

_TRACE_REQUIRED_FIELDS = ["event_type", "ticket_id", "timestamp", "payload"]


def validate_trace_event(event: Any) -> bool:
    """
    Validate that a trace event contains all required fields with correct types.

    Required fields:
    - event_type : str
    - ticket_id  : str
    - timestamp  : str
    - payload    : dict

    Returns True if valid, False otherwise.
    """
    if not isinstance(event, dict):
        return False

    for field in _TRACE_REQUIRED_FIELDS:
        if field not in event:
            return False

    if not isinstance(event["event_type"], str):
        return False
    if not isinstance(event["ticket_id"], str):
        return False
    if not isinstance(event["timestamp"], str):
        return False
    if not isinstance(event["payload"], dict):
        return False

    return True
