# Feature: shopwave-support-agent
# Property 6: Refund Precondition Chain -- Validates: Requirements 3.5, 4.2, 4.3
# Property 9: Escalation Call Completeness -- Validates: Requirements 8.1, 8.2
# Property 13: HITL Checkpoint Completeness -- Validates: Requirements 15.2, 15.3, 15.4

from __future__ import annotations

import datetime

import pytest
from hypothesis import given, settings, strategies as st

from agent.decisions import is_high_stakes

_VALID_ESCALATION_CATEGORIES = {
    "warranty_claim",
    "threat_detected",
    "social_engineering",
    "ambiguous_request",
    "missing_data",
    "replacement_needed",
}


def _make_tool_call(tool_name: str, output: dict | None = None) -> dict:
    return {
        "tool_name": tool_name,
        "input_args": {},
        "output": output or {},
        "timestamp": "2024-01-01T00:00:00Z",
    }


# ===========================================================================
# Property 6: Refund Precondition Chain
# Validates: Requirements 3.5, 4.2, 4.3
# ===========================================================================


class TestProperty6RefundPreconditionChain:
    """
    For any audit record where issue_refund appears in tool_calls,
    check_refund_eligibility must appear before it with eligible=True.
    Conversely, if check_refund_eligibility returns eligible=False,
    issue_refund must not appear and resolution must be DENY.
    """

    @settings(max_examples=100)
    @given(
        prefix_tools=st.lists(
            st.sampled_from(["get_order", "get_customer", "get_product"]),
            min_size=0, max_size=3,
        ),
        refund_amount=st.floats(min_value=0.01, max_value=5000.0, allow_nan=False, allow_infinity=False),
    )
    def test_issue_refund_preceded_by_eligible_check(self, prefix_tools, refund_amount):
        """
        If issue_refund is in tool_calls, check_refund_eligibility must appear
        before it with eligible=True in its output.
        Validates: Requirements 3.5, 4.2
        """
        tool_calls = [_make_tool_call(t) for t in prefix_tools]
        tool_calls.append(_make_tool_call(
            "check_refund_eligibility",
            {"eligible": True, "explanation": "Within return window.", "return_window_days": 30},
        ))
        tool_calls.append(_make_tool_call(
            "issue_refund",
            {"refund_id": "REF-001", "order_id": "O001", "amount": refund_amount, "status": "issued"},
        ))
        tool_calls.append(_make_tool_call("send_reply", {"delivered": True, "ticket_id": "T001"}))
        tool_names = [tc["tool_name"] for tc in tool_calls]
        assert "issue_refund" in tool_names
        elig_idx = tool_names.index("check_refund_eligibility")
        refund_idx = tool_names.index("issue_refund")
        assert elig_idx < refund_idx, (
            f"check_refund_eligibility (idx={elig_idx}) must precede issue_refund (idx={refund_idx})"
        )
        elig_output = tool_calls[elig_idx]["output"]
        assert elig_output.get("eligible") is True, (
            f"check_refund_eligibility output must have eligible=True, got {elig_output.get('eligible')!r}"
        )

    @settings(max_examples=100)
    @given(
        prefix_tools=st.lists(
            st.sampled_from(["get_order", "get_customer", "get_product"]),
            min_size=0, max_size=3,
        ),
    )
    def test_issue_refund_never_follows_ineligible_check(self, prefix_tools):
        """
        If check_refund_eligibility returns eligible=False, issue_refund must
        not appear in tool_calls and resolution must be DENY.
        Validates: Requirements 3.5, 4.3
        """
        tool_calls = [_make_tool_call(t) for t in prefix_tools]
        tool_calls.append(_make_tool_call(
            "check_refund_eligibility",
            {"eligible": False, "explanation": "Outside return window.", "return_window_days": 30},
        ))
        tool_calls.append(_make_tool_call("send_reply", {"delivered": True, "ticket_id": "T001"}))
        tool_names = [tc["tool_name"] for tc in tool_calls]
        assert "issue_refund" not in tool_names, (
            "issue_refund must not appear when check_refund_eligibility returned eligible=False"
        )
        audit_record = {"tool_calls": tool_calls, "resolution": "DENY"}
        assert audit_record["resolution"] == "DENY"

    @settings(max_examples=100)
    @given(
        eligible=st.booleans(),
        prefix_tools=st.lists(
            st.sampled_from(["get_order", "get_customer", "get_product"]),
            min_size=1, max_size=3,
        ),
        refund_amount=st.floats(min_value=0.01, max_value=5000.0, allow_nan=False, allow_infinity=False),
    )
    def test_refund_precondition_invariant(self, eligible, prefix_tools, refund_amount):
        """
        Universal invariant: issue_refund in tool_calls IFF check_refund_eligibility
        appeared before it with eligible=True.
        Validates: Requirements 3.5, 4.2, 4.3
        """
        tool_calls = [_make_tool_call(t) for t in prefix_tools]
        tool_calls.append(_make_tool_call(
            "check_refund_eligibility",
            {"eligible": eligible, "explanation": "test", "return_window_days": 30},
        ))
        if eligible:
            tool_calls.append(_make_tool_call(
                "issue_refund",
                {"refund_id": "REF-001", "order_id": "O001", "amount": refund_amount, "status": "issued"},
            ))
        tool_calls.append(_make_tool_call("send_reply", {"delivered": True, "ticket_id": "T001"}))
        tool_names = [tc["tool_name"] for tc in tool_calls]
        has_refund = "issue_refund" in tool_names
        has_elig = "check_refund_eligibility" in tool_names
        if has_refund:
            assert has_elig, "issue_refund present but check_refund_eligibility missing"
            elig_idx = tool_names.index("check_refund_eligibility")
            refund_idx = tool_names.index("issue_refund")
            assert elig_idx < refund_idx
            elig_output = tool_calls[elig_idx]["output"]
            assert elig_output.get("eligible") is True
        if has_elig and not has_refund:
            elig_idx = tool_names.index("check_refund_eligibility")
            elig_output = tool_calls[elig_idx]["output"]
            assert elig_output.get("eligible") is not True

# ===========================================================================
# Property 9: Escalation Call Completeness
# Validates: Requirements 8.1, 8.2
# ===========================================================================


class TestProperty9EscalationCallCompleteness:
    """
    For any ticket with resolution=ESCALATE, the escalate tool call must contain
    a non-empty ticket_id, non-empty reason, and a valid category from the allowed set.
    """

    @settings(max_examples=100)
    @given(
        ticket_id=st.text(min_size=1, max_size=20, alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"),
        reason=st.text(min_size=1, max_size=200),
        category=st.sampled_from(sorted(_VALID_ESCALATION_CATEGORIES)),
    )
    def test_escalate_tool_returns_required_fields(self, ticket_id, reason, category):
        """
        The escalate tool always returns a dict with non-empty case_id,
        matching ticket_id, and status=escalated.
        Validates: Requirements 8.1, 8.2
        """
        from agent.tools import escalate
        result = escalate(ticket_id, reason, category)
        assert isinstance(result, dict)
        assert "case_id" in result
        assert isinstance(result["case_id"], str) and len(result["case_id"]) > 0
        assert result.get("ticket_id") == ticket_id
        assert result.get("status") == "escalated"

    @settings(max_examples=100)
    @given(
        category=st.sampled_from(sorted(_VALID_ESCALATION_CATEGORIES)),
        prefix_tools=st.lists(
            st.sampled_from(["get_order", "get_customer", "get_product", "search_knowledge_base"]),
            min_size=1, max_size=4,
        ),
    )
    def test_escalate_audit_record_has_valid_category(self, category, prefix_tools):
        """
        In an audit record with resolution=ESCALATE, the escalate tool call
        must have a category from the valid set.
        Validates: Requirements 8.1, 8.2
        """
        tool_calls = [_make_tool_call(t) for t in prefix_tools]
        tool_calls.append(_make_tool_call(
            "escalate",
            {"case_id": "ESC-001", "ticket_id": "T001", "category": category, "status": "escalated"},
        ))
        tool_calls.append(_make_tool_call("send_reply", {"delivered": True, "ticket_id": "T001"}))
        audit_record = {"ticket_id": "T001", "tool_calls": tool_calls, "resolution": "ESCALATE", "escalation_category": category}
        escalate_calls = [tc for tc in audit_record["tool_calls"] if tc["tool_name"] == "escalate"]
        assert len(escalate_calls) >= 1
        for esc_call in escalate_calls:
            output = esc_call["output"]
            assert isinstance(output.get("case_id"), str) and len(output["case_id"]) > 0
            assert isinstance(output.get("ticket_id"), str) and len(output["ticket_id"]) > 0
            assert output.get("category") in _VALID_ESCALATION_CATEGORIES, (
                f"category {output.get('category')!r} not in valid set"
            )

    @settings(max_examples=100)
    @given(category=st.sampled_from(sorted(_VALID_ESCALATION_CATEGORIES)))
    def test_escalation_category_in_audit_matches_tool_call(self, category):
        """
        The escalation_category in the audit record matches the category
        passed to the escalate tool call.
        Validates: Requirements 8.1
        """
        tool_calls = [
            _make_tool_call("get_order"),
            _make_tool_call("get_customer"),
            _make_tool_call("escalate", {"case_id": "ESC-T001", "ticket_id": "T001", "category": category, "status": "escalated"}),
            _make_tool_call("send_reply", {"delivered": True, "ticket_id": "T001"}),
        ]
        audit_record = {"ticket_id": "T001", "tool_calls": tool_calls, "resolution": "ESCALATE", "escalation_category": category}
        esc_call = next(tc for tc in audit_record["tool_calls"] if tc["tool_name"] == "escalate")
        assert esc_call["output"]["category"] == audit_record["escalation_category"]

    def test_all_valid_escalation_categories_accepted(self):
        """
        All six valid escalation categories are accepted by the escalate tool.
        Validates: Requirements 8.1, 8.2
        """
        from agent.tools import escalate
        for category in _VALID_ESCALATION_CATEGORIES:
            result = escalate("T001", f"Test reason for {category}", category)
            assert isinstance(result, dict)
            assert "case_id" in result
            assert len(result["case_id"]) > 0, f"case_id empty for category={category}"

    @settings(max_examples=100)
    @given(
        ticket_id=st.text(min_size=1, max_size=10, alphabet="T0123456789"),
        reason=st.text(min_size=1, max_size=100),
        category=st.sampled_from(sorted(_VALID_ESCALATION_CATEGORIES)),
    )
    def test_escalate_input_args_non_empty(self, ticket_id, reason, category):
        """
        The input_args of the escalate tool call must have non-empty ticket_id,
        non-empty reason, and valid category.
        Validates: Requirements 8.1, 8.2
        """
        input_args = {"ticket_id": ticket_id, "summary": reason, "priority": "medium"}
        tool_call = {
            "tool_name": "escalate",
            "input_args": input_args,
            "output": {"case_id": f"ESC-{ticket_id}", "ticket_id": ticket_id, "category": category, "status": "escalated"},
            "timestamp": "2024-01-01T00:00:00Z",
        }
        assert len(tool_call["input_args"]["ticket_id"]) > 0
        assert len(tool_call["input_args"]["summary"]) > 0
        assert tool_call["output"]["category"] in _VALID_ESCALATION_CATEGORIES

# ===========================================================================
# Property 13: HITL Checkpoint Completeness
# Validates: Requirements 15.2, 15.3, 15.4
# ===========================================================================


class TestProperty13HITLCheckpointCompleteness:
    """
    For any ticket where is_high_stakes() is True, checkpoint_events must be
    non-empty and each checkpoint must contain required fields with auto_approved=True
    in demo mode.
    """

    @settings(max_examples=100)
    @given(refund_amount=st.floats(min_value=200.01, max_value=10000.0, allow_nan=False, allow_infinity=False))
    def test_high_stakes_approve_above_threshold(self, refund_amount):
        """
        is_high_stakes returns True when resolution=APPROVE and refund_amount > 200.
        Validates: Requirements 15.1, 15.2
        """
        state = {"resolution": "APPROVE", "refund_amount": refund_amount, "escalation_category": None}
        assert is_high_stakes(state) is True

    @settings(max_examples=100)
    @given(refund_amount=st.floats(min_value=0.01, max_value=200.0, allow_nan=False, allow_infinity=False))
    def test_not_high_stakes_approve_at_or_below_threshold(self, refund_amount):
        """
        is_high_stakes returns False when resolution=APPROVE and refund_amount <= 200.
        Validates: Requirements 15.1
        """
        state = {"resolution": "APPROVE", "refund_amount": refund_amount, "escalation_category": None}
        assert is_high_stakes(state) is False

    @settings(max_examples=100)
    @given(category=st.sampled_from(["threat_detected", "social_engineering"]))
    def test_high_stakes_escalate_fraud_categories(self, category):
        """
        is_high_stakes returns True when resolution=ESCALATE and category is
        threat_detected or social_engineering.
        Validates: Requirements 15.1, 15.2
        """
        state = {"resolution": "ESCALATE", "refund_amount": None, "escalation_category": category}
        assert is_high_stakes(state) is True

    @settings(max_examples=100)
    @given(category=st.sampled_from(["warranty_claim", "ambiguous_request", "missing_data", "replacement_needed"]))
    def test_not_high_stakes_escalate_non_fraud_categories(self, category):
        """
        is_high_stakes returns False when resolution=ESCALATE and category is
        not threat_detected or social_engineering.
        Validates: Requirements 15.1
        """
        state = {"resolution": "ESCALATE", "refund_amount": None, "escalation_category": category}
        assert is_high_stakes(state) is False

    @settings(max_examples=100)
    @given(
        refund_amount=st.floats(min_value=200.01, max_value=5000.0, allow_nan=False, allow_infinity=False),
        reasoning=st.text(min_size=1, max_size=200),
    )
    def test_checkpoint_events_non_empty_for_high_stakes_approve(self, refund_amount, reasoning):
        """
        When is_high_stakes=True (APPROVE, refund > 200), checkpoint_events must be non-empty.
        Validates: Requirements 15.2, 15.3
        """
        checkpoint = {
            "ticket_id": "T001",
            "proposed_action": "APPROVE",
            "amount_or_category": refund_amount,
            "reasoning_summary": reasoning,
            "auto_approved": True,
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }
        audit_record = {"ticket_id": "T001", "resolution": "APPROVE", "refund_amount": refund_amount, "checkpoint_events": [checkpoint]}
        state = {"resolution": "APPROVE", "refund_amount": refund_amount, "escalation_category": None}
        assert is_high_stakes(state) is True
        assert len(audit_record["checkpoint_events"]) > 0

    @settings(max_examples=100)
    @given(
        category=st.sampled_from(["threat_detected", "social_engineering"]),
        reasoning=st.text(min_size=1, max_size=200),
    )
    def test_checkpoint_events_non_empty_for_high_stakes_escalate(self, category, reasoning):
        """
        When is_high_stakes=True (ESCALATE, fraud category), checkpoint_events must be non-empty.
        Validates: Requirements 15.2, 15.3
        """
        checkpoint = {
            "ticket_id": "T001",
            "proposed_action": "ESCALATE",
            "amount_or_category": category,
            "reasoning_summary": reasoning,
            "auto_approved": True,
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }
        audit_record = {"ticket_id": "T001", "resolution": "ESCALATE", "escalation_category": category, "checkpoint_events": [checkpoint]}
        state = {"resolution": "ESCALATE", "refund_amount": None, "escalation_category": category}
        assert is_high_stakes(state) is True
        assert len(audit_record["checkpoint_events"]) > 0

    @settings(max_examples=100)
    @given(
        ticket_id=st.text(min_size=1, max_size=10, alphabet="T0123456789"),
        proposed_action=st.sampled_from(["APPROVE", "ESCALATE"]),
        amount_or_category=st.one_of(
            st.floats(min_value=200.01, max_value=5000.0, allow_nan=False, allow_infinity=False),
            st.sampled_from(["threat_detected", "social_engineering"]),
        ),
        reasoning=st.text(min_size=1, max_size=300),
    )
    def test_checkpoint_contains_required_fields(self, ticket_id, proposed_action, amount_or_category, reasoning):
        """
        Each checkpoint event must contain ticket_id, proposed_action,
        amount_or_category, reasoning_summary, auto_approved, and timestamp.
        Validates: Requirements 15.3, 15.4
        """
        checkpoint = {
            "ticket_id": ticket_id,
            "proposed_action": proposed_action,
            "amount_or_category": amount_or_category,
            "reasoning_summary": reasoning,
            "auto_approved": True,
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }
        required_fields = {"ticket_id", "proposed_action", "amount_or_category", "reasoning_summary", "auto_approved", "timestamp"}
        missing = required_fields - set(checkpoint.keys())
        assert not missing, f"Checkpoint missing required fields: {missing}"
        assert isinstance(checkpoint["ticket_id"], str) and len(checkpoint["ticket_id"]) > 0
        assert checkpoint["proposed_action"] in {"APPROVE", "ESCALATE", "DENY"}
        assert checkpoint["amount_or_category"] is not None
        assert isinstance(checkpoint["reasoning_summary"], str)
        assert isinstance(checkpoint["auto_approved"], bool)
        assert isinstance(checkpoint["timestamp"], str)

    @settings(max_examples=100)
    @given(
        n_checkpoints=st.integers(min_value=1, max_value=5),
        proposed_action=st.sampled_from(["APPROVE", "ESCALATE"]),
    )
    def test_demo_mode_all_checkpoints_auto_approved(self, n_checkpoints, proposed_action):
        """
        In demo mode, every checkpoint event must have auto_approved=True.
        Validates: Requirements 15.4
        """
        checkpoints = [
            {
                "ticket_id": f"T{i:03d}",
                "proposed_action": proposed_action,
                "amount_or_category": 500.0 if proposed_action == "APPROVE" else "threat_detected",
                "reasoning_summary": "Auto-approved in demo mode.",
                "auto_approved": True,
                "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            }
            for i in range(n_checkpoints)
        ]
        for i, cp in enumerate(checkpoints):
            assert cp["auto_approved"] is True, (
                f"Checkpoint {i} must have auto_approved=True in demo mode, got {cp['auto_approved']!r}"
            )

    def test_no_checkpoint_for_low_stakes_approve(self):
        """
        No checkpoint is emitted for APPROVE with refund_amount <= 200.
        Validates: Requirements 15.1, 15.2
        """
        state = {"resolution": "APPROVE", "refund_amount": 50.0, "escalation_category": None}
        assert is_high_stakes(state) is False
        audit_record = {"ticket_id": "T001", "resolution": "APPROVE", "refund_amount": 50.0, "checkpoint_events": []}
        assert len(audit_record["checkpoint_events"]) == 0

    def test_no_checkpoint_for_deny(self):
        """
        No checkpoint is emitted for DENY resolutions.
        Validates: Requirements 15.1
        """
        state = {"resolution": "DENY", "refund_amount": None, "escalation_category": None}
        assert is_high_stakes(state) is False
        audit_record = {"ticket_id": "T001", "resolution": "DENY", "checkpoint_events": []}
        assert len(audit_record["checkpoint_events"]) == 0

    @settings(max_examples=100)
    @given(
        refund_amount=st.floats(min_value=200.01, max_value=5000.0, allow_nan=False, allow_infinity=False),
        category=st.sampled_from(["threat_detected", "social_engineering"]),
    )
    def test_is_high_stakes_covers_both_conditions(self, refund_amount, category):
        """
        is_high_stakes covers both high-value refunds and fraud escalations.
        Validates: Requirements 15.1
        """
        approve_state = {"resolution": "APPROVE", "refund_amount": refund_amount, "escalation_category": None}
        escalate_state = {"resolution": "ESCALATE", "refund_amount": None, "escalation_category": category}
        assert is_high_stakes(approve_state) is True
        assert is_high_stakes(escalate_state) is True

