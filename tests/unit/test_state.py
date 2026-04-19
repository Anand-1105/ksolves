"""
tests/unit/test_state.py — Unit tests for TicketState, initial_state, and enums.

Tests state initialization, enum values, and TypedDict contract.
"""

from __future__ import annotations

import pytest

from agent.state import (
    Resolution,
    EscalationCategory,
    TicketState,
    initial_state,
)


# ===========================================================================
# Resolution enum
# ===========================================================================

class TestResolutionEnum:
    def test_approve_value(self):
        assert Resolution.APPROVE == "APPROVE"
        assert Resolution.APPROVE.value == "APPROVE"

    def test_deny_value(self):
        assert Resolution.DENY == "DENY"

    def test_escalate_value(self):
        assert Resolution.ESCALATE == "ESCALATE"

    def test_all_members(self):
        assert set(Resolution) == {Resolution.APPROVE, Resolution.DENY, Resolution.ESCALATE}

    def test_string_comparison(self):
        """Resolution enum members should compare equal to their string values."""
        assert Resolution.APPROVE == "APPROVE"
        assert Resolution.DENY == "DENY"
        assert Resolution.ESCALATE == "ESCALATE"


# ===========================================================================
# EscalationCategory enum
# ===========================================================================

class TestEscalationCategoryEnum:
    def test_all_categories_present(self):
        expected = {
            "warranty_claim", "threat_detected", "social_engineering",
            "ambiguous_request", "missing_data", "replacement_needed",
        }
        actual = {e.value for e in EscalationCategory}
        assert actual == expected

    def test_string_comparison(self):
        assert EscalationCategory.WARRANTY_CLAIM == "warranty_claim"
        assert EscalationCategory.THREAT_DETECTED == "threat_detected"
        assert EscalationCategory.SOCIAL_ENGINEERING == "social_engineering"


# ===========================================================================
# initial_state
# ===========================================================================

class TestInitialState:
    def test_creates_valid_state_from_ticket(self):
        ticket = {
            "ticket_id": "T001",
            "customer_id": "C001",
            "order_id": "O001",
            "issue_type": "refund_request",
            "description": "I want a refund.",
        }
        state = initial_state(ticket)
        assert state["ticket"] is ticket
        assert state["ticket_id"] == "T001"

    def test_sets_all_defaults(self):
        state = initial_state({"ticket_id": "T001"})
        assert state["order"] is None
        assert state["customer"] is None
        assert state["product"] is None
        assert state["kb_result"] is None
        assert state["tool_calls"] == []
        assert state["replan_attempts"] == []
        assert state["failed_tool_calls"] == []
        assert state["q1_identified"] is None
        assert state["q2_in_policy"] is None
        assert state["q3_confident"] is None
        assert state["confidence_score"] is None
        assert state["confidence_factors"] is None
        assert state["self_reflection_note"] is None
        assert state["resolution"] is None
        assert state["escalation_category"] is None
        assert state["denial_reason"] is None
        assert state["refund_amount"] is None
        assert state["refund_id"] is None
        assert state["case_id"] is None
        assert state["checkpoint_events"] == []
        assert state["prior_customer_records"] == []
        assert state["processing_error"] is None
        assert state["next_node"] is None
        assert state["audit_record"] is None

    def test_empty_ticket_uses_empty_string_for_id(self):
        state = initial_state({})
        assert state["ticket_id"] == ""

    def test_lists_are_independent(self):
        """Each call should produce independent lists (no shared references)."""
        s1 = initial_state({"ticket_id": "T001"})
        s2 = initial_state({"ticket_id": "T002"})
        s1["tool_calls"].append({"tool": "test"})
        assert len(s2["tool_calls"]) == 0

    def test_state_is_dict_like(self):
        """TicketState is a TypedDict — it should behave like a dict."""
        state = initial_state({"ticket_id": "T001"})
        assert isinstance(state, dict)
        assert "ticket_id" in state
        assert state.get("nonexistent_key") is None
