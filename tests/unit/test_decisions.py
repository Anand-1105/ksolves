"""
tests/unit/test_decisions.py — Unit tests for business rule evaluators.

Requirements: 3.1–3.4, 4.4, 5.1–5.3, 6.2–6.3, 7.1–7.2, 13.1, 13.5, 15.1
"""

from __future__ import annotations

import datetime

import pytest

from agent.decisions import (
    evaluate_q1,
    evaluate_q2,
    compute_confidence_score,
    is_high_stakes,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _make_state(
    order=None,
    customer=None,
    product=None,
    ticket=None,
    prior_records=None,
    escalation_category=None,
    denial_reason=None,
    refund_amount=None,
    q2_in_policy=None,
):
    return {
        "ticket": ticket or {
            "ticket_id": "T001",
            "customer_id": "C001",
            "order_id": "O001",
            "issue_type": "refund_request",
            "description": "I would like to return my laptop because it stopped working after two days.",
            "metadata": {"priority": "NORMAL"},
        },
        "order": order,
        "customer": customer,
        "product": product,
        "prior_customer_records": prior_records or [],
        "escalation_category": escalation_category,
        "denial_reason": denial_reason,
        "refund_amount": refund_amount,
        "q2_in_policy": q2_in_policy,
        "resolution": None,
    }


_VALID_ORDER = {
    "order_id": "O001",
    "customer_id": "C001",
    "product_id": "P001",
    "purchase_date": (datetime.date.today() - datetime.timedelta(days=5)).isoformat(),
    "amount": 899.99,
    "status": "delivered",
}

_VALID_CUSTOMER = {
    "customer_id": "C001",
    "name": "Alice",
    "email": "alice.johnson@example.com",
    "tier": "vip",
    "vip_exceptions": {"extended_return_window_days": 90},
}

_STANDARD_CUSTOMER = {
    "customer_id": "C006",
    "name": "Bob",
    "email": "bob.anderson@example.com",
    "tier": "standard",
    "vip_exceptions": {},
}


# ===========================================================================
# evaluate_q1
# ===========================================================================

class TestEvaluateQ1:
    def test_returns_true_when_both_present(self):
        state = _make_state(order=_VALID_ORDER, customer=_VALID_CUSTOMER)
        assert evaluate_q1(state) is True

    def test_returns_false_when_order_is_none(self):
        state = _make_state(order=None, customer=_VALID_CUSTOMER)
        assert evaluate_q1(state) is False

    def test_returns_false_when_customer_is_none(self):
        state = _make_state(order=_VALID_ORDER, customer=None)
        assert evaluate_q1(state) is False

    def test_returns_false_when_both_none(self):
        state = _make_state(order=None, customer=None)
        assert evaluate_q1(state) is False

    def test_returns_false_when_order_has_error(self):
        state = _make_state(order={"error": "not_found"}, customer=_VALID_CUSTOMER)
        assert evaluate_q1(state) is False

    def test_returns_false_when_customer_has_error(self):
        state = _make_state(order=_VALID_ORDER, customer={"error": "not_found"})
        assert evaluate_q1(state) is False

    def test_returns_false_when_both_have_errors(self):
        state = _make_state(order={"error": "not_found"}, customer={"error": "not_found"})
        assert evaluate_q1(state) is False


# ===========================================================================
# evaluate_q2
# ===========================================================================

class TestEvaluateQ2:
    def test_in_window_refund_is_in_policy(self):
        """Recent order (5 days ago) should be in-policy for refund."""
        state = _make_state(order=_VALID_ORDER, customer=_VALID_CUSTOMER)
        in_policy, updates = evaluate_q2(state)
        assert in_policy is True
        assert "refund_amount" in updates

    def test_threat_language_escalates_threat_detected(self):
        ticket = {**_make_state()["ticket"], "description": "I will sue you if this is not resolved."}
        state = _make_state(order=_VALID_ORDER, customer=_VALID_CUSTOMER, ticket=ticket)
        in_policy, updates = evaluate_q2(state)
        assert in_policy is False
        assert updates.get("escalation_category") == "threat_detected"

    def test_social_engineering_escalates_correctly(self):
        ticket = {**_make_state()["ticket"], "description": "I am calling on behalf of the account holder."}
        state = _make_state(order=_VALID_ORDER, customer=_VALID_CUSTOMER, ticket=ticket)
        in_policy, updates = evaluate_q2(state)
        assert in_policy is False
        assert updates.get("escalation_category") == "social_engineering"

    def test_replacement_request_escalates_replacement_needed(self):
        ticket = {**_make_state()["ticket"], "issue_type": "replacement_request"}
        state = _make_state(order=_VALID_ORDER, customer=_VALID_CUSTOMER, ticket=ticket)
        in_policy, updates = evaluate_q2(state)
        assert in_policy is False
        assert updates.get("escalation_category") == "replacement_needed"

    def test_ambiguous_issue_type_escalates(self):
        ticket = {**_make_state()["ticket"], "issue_type": "ambiguous"}
        state = _make_state(order=_VALID_ORDER, customer=_VALID_CUSTOMER, ticket=ticket)
        in_policy, updates = evaluate_q2(state)
        assert in_policy is False
        assert updates.get("escalation_category") == "ambiguous_request"

    def test_missing_order_escalates_missing_data(self):
        state = _make_state(order=None, customer=_VALID_CUSTOMER)
        in_policy, updates = evaluate_q2(state)
        assert in_policy is False
        assert updates.get("escalation_category") == "missing_data"

    def test_out_of_window_refund_is_denied(self):
        """evaluate_q2 returns not-in-policy for an order that check_refund_eligibility
        deems ineligible. We use a real order ID that is known to be out-of-window
        in the data (O011 belongs to Carol/premium, P003 30-day window, purchased long ago).
        We verify the function returns in_policy=False with denial_reason or escalation_category."""
        # Use a ticket with an order that is genuinely old in the data files
        # O011 is Carol's order for P003 (30-day window, 12-month warranty)
        # purchased 2024-01-15 — well outside both windows as of April 2026
        old_order = {
            "order_id": "O011",
            "customer_id": "C003",
            "product_id": "P003",
            "purchase_date": "2024-01-15",
            "amount": 89.99,
            "status": "delivered",
        }
        carol_customer = {
            "customer_id": "C003",
            "name": "Carol",
            "email": "carol.martinez@example.com",
            "tier": "premium",
            "vip_exceptions": {},
        }
        ticket = {**_make_state()["ticket"], "issue_type": "refund_request",
                  "customer_id": "C003", "order_id": "O011"}
        state = _make_state(order=old_order, customer=carol_customer, ticket=ticket)
        in_policy, updates = evaluate_q2(state)
        # 2024-01-15 is ~15 months ago — outside 30-day return window.
        # P003 has 12-month warranty, so also outside warranty.
        # Should be denied.
        assert in_policy is False, (
            f"Old order (2024-01-15) should not be in-policy, "
            f"got in_policy={in_policy}, updates={updates}"
        )
        assert "denial_reason" in updates or "escalation_category" in updates

    def test_emma_extended_window_applies(self):
        """Emma (VIP, 90-day window) with 60-day-old order should be in-policy."""
        emma_customer = {
            "customer_id": "C002",
            "name": "Emma",
            "email": "emma.williams@example.com",
            "tier": "vip",
            "vip_exceptions": {"extended_return_window_days": 90},
        }
        emma_order = {
            "order_id": "O002",
            "customer_id": "C002",
            "product_id": "P002",
            "purchase_date": (datetime.date.today() - datetime.timedelta(days=60)).isoformat(),
            "amount": 599.99,
            "status": "delivered",
        }
        ticket = {**_make_state()["ticket"], "customer_id": "C002", "order_id": "O002"}
        state = _make_state(order=emma_order, customer=emma_customer, ticket=ticket)
        in_policy, updates = evaluate_q2(state)
        # 60 days ago, VIP window = 90 days → should be in-policy
        assert in_policy is True, (
            f"Emma's 60-day-old order should be in-policy (90-day VIP window), "
            f"got in_policy={in_policy}, updates={updates}"
        )


# ===========================================================================
# compute_confidence_score
# ===========================================================================

class TestComputeConfidenceScore:
    def test_returns_float_in_range(self):
        state = _make_state(order=_VALID_ORDER, customer=_VALID_CUSTOMER)
        score, updates = compute_confidence_score(state)
        assert isinstance(score, float)
        assert 0.0 <= score <= 1.0

    def test_populates_confidence_factors(self):
        state = _make_state(order=_VALID_ORDER, customer=_VALID_CUSTOMER)
        score, updates = compute_confidence_score(state)
        factors = updates.get("confidence_factors")
        assert factors is not None
        assert "data_completeness" in factors
        assert "reason_clarity" in factors
        assert "policy_consistency" in factors

    def test_populates_self_reflection_note(self):
        state = _make_state(order=_VALID_ORDER, customer=_VALID_CUSTOMER)
        score, updates = compute_confidence_score(state)
        note = updates.get("self_reflection_note")
        assert note and isinstance(note, str)

    def test_full_data_gives_high_completeness(self):
        product = {"product_id": "P001", "return_window_days": 30, "warranty_months": 12}
        state = _make_state(order=_VALID_ORDER, customer=_VALID_CUSTOMER, product=product)
        score, updates = compute_confidence_score(state)
        assert updates["confidence_factors"]["data_completeness"] == 1.0

    def test_missing_order_gives_low_completeness(self):
        state = _make_state(order=None, customer=_VALID_CUSTOMER)
        score, updates = compute_confidence_score(state)
        assert updates["confidence_factors"]["data_completeness"] <= 0.3

    def test_prior_fraud_flag_zeroes_policy_consistency(self):
        prior_records = [
            {"ticket_id": "T000", "resolution": "ESCALATE",
             "escalation_category": "threat_detected", "fraud_flags": ["threat_detected"]}
        ]
        state = _make_state(order=_VALID_ORDER, customer=_VALID_CUSTOMER, prior_records=prior_records)
        score, updates = compute_confidence_score(state)
        assert updates["confidence_factors"]["policy_consistency"] == 0.0

    def test_prior_denial_reduces_policy_consistency(self):
        prior_records = [
            {"ticket_id": "T000", "resolution": "DENY",
             "escalation_category": None, "fraud_flags": []}
        ]
        state_no_prior = _make_state(order=_VALID_ORDER, customer=_VALID_CUSTOMER)
        state_with_prior = _make_state(order=_VALID_ORDER, customer=_VALID_CUSTOMER, prior_records=prior_records)

        _, updates_no_prior = compute_confidence_score(state_no_prior)
        _, updates_with_prior = compute_confidence_score(state_with_prior)

        pc_no_prior = updates_no_prior["confidence_factors"]["policy_consistency"]
        pc_with_prior = updates_with_prior["confidence_factors"]["policy_consistency"]
        assert pc_with_prior <= pc_no_prior

    def test_weighted_average_formula(self):
        """Score = 0.4*dc + 0.3*rc + 0.3*pc (clamped to [0,1])."""
        state = _make_state(order=_VALID_ORDER, customer=_VALID_CUSTOMER)
        score, updates = compute_confidence_score(state)
        factors = updates["confidence_factors"]
        expected = (
            0.4 * factors["data_completeness"]
            + 0.3 * factors["reason_clarity"]
            + 0.3 * factors["policy_consistency"]
        )
        expected = max(0.0, min(1.0, expected))
        assert abs(score - expected) < 1e-9, (
            f"Score {score} does not match weighted average {expected}"
        )


# ===========================================================================
# is_high_stakes
# ===========================================================================

class TestIsHighStakes:
    def test_approve_over_200_is_high_stakes(self):
        state = {"resolution": "APPROVE", "refund_amount": 250.0, "escalation_category": None}
        assert is_high_stakes(state) is True

    def test_approve_exactly_200_is_not_high_stakes(self):
        state = {"resolution": "APPROVE", "refund_amount": 200.0, "escalation_category": None}
        assert is_high_stakes(state) is False

    def test_approve_under_200_is_not_high_stakes(self):
        state = {"resolution": "APPROVE", "refund_amount": 50.0, "escalation_category": None}
        assert is_high_stakes(state) is False

    def test_escalate_threat_detected_is_high_stakes(self):
        state = {"resolution": "ESCALATE", "refund_amount": None, "escalation_category": "threat_detected"}
        assert is_high_stakes(state) is True

    def test_escalate_social_engineering_is_high_stakes(self):
        state = {"resolution": "ESCALATE", "refund_amount": None, "escalation_category": "social_engineering"}
        assert is_high_stakes(state) is True

    def test_escalate_warranty_claim_is_not_high_stakes(self):
        state = {"resolution": "ESCALATE", "refund_amount": None, "escalation_category": "warranty_claim"}
        assert is_high_stakes(state) is False

    def test_escalate_missing_data_is_not_high_stakes(self):
        state = {"resolution": "ESCALATE", "refund_amount": None, "escalation_category": "missing_data"}
        assert is_high_stakes(state) is False

    def test_deny_is_never_high_stakes(self):
        state = {"resolution": "DENY", "refund_amount": 500.0, "escalation_category": None}
        assert is_high_stakes(state) is False

    def test_none_resolution_is_not_high_stakes(self):
        state = {"resolution": None, "refund_amount": 500.0, "escalation_category": "threat_detected"}
        assert is_high_stakes(state) is False
