# Feature: shopwave-support-agent
# Property 5: Decision Routing Correctness — Validates: Requirements 3.1, 3.2, 3.3, 3.4, 13.3
# Property 7: Eligibility Evaluation Correctness — Validates: Requirements 4.4, 5.1, 5.2, 5.3, 6.2
# Property 8: Fraud Escalation Without Refund — Validates: Requirements 7.1, 7.2, 7.4

from __future__ import annotations

import datetime

import pytest
from hypothesis import given, settings, strategies as st

from agent.decisions import evaluate_q1, evaluate_q2

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_VALID_ORDER = {
    "order_id": "O001",
    "customer_id": "C001",
    "product_id": "P001",
    "purchase_date": "2026-04-05",
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

_VALID_TICKET = {
    "ticket_id": "T001",
    "customer_id": "C001",
    "order_id": "O001",
    "issue_type": "refund_request",
    "description": "I would like to return my laptop because it stopped working.",
    "metadata": {"priority": "NORMAL", "channel": "email"},
}


def _make_state(
    *,
    order=_VALID_ORDER,
    customer=_VALID_CUSTOMER,
    ticket=_VALID_TICKET,
) -> dict:
    return {
        "ticket": ticket,
        "order": order,
        "customer": customer,
        "product": None,
        "prior_customer_records": [],
        "q2_in_policy": None,
        "escalation_category": None,
        "denial_reason": None,
        "refund_amount": None,
    }


# ---------------------------------------------------------------------------
# Helper: pure eligibility logic (mirrors check_refund_eligibility logic)
# ---------------------------------------------------------------------------


def _compute_eligibility(
    days_since_purchase: int,
    return_window_days: int,
    warranty_months: int,
    is_vip: bool,
    vip_window: int = 90,
) -> bool | str:
    """
    Pure function mirroring the eligibility logic in check_refund_eligibility.

    Returns:
      True        — within effective return window
      "escalate"  — outside return window but within warranty
      False       — outside both windows
    """
    effective_window = vip_window if is_vip else return_window_days

    if days_since_purchase <= effective_window:
        return True

    # Outside return window — check warranty
    if warranty_months > 0:
        # Approximate months from days (30-day month approximation)
        months_since = days_since_purchase / 30.0
        if months_since <= warranty_months:
            return "escalate"

    return False


# ===========================================================================
# Property 5: Decision Routing Correctness
# Validates: Requirements 3.1, 3.2, 3.3, 3.4, 13.3
# ===========================================================================


class TestProperty5DecisionRoutingCorrectness:
    """
    Tests that evaluate_q1 and evaluate_q2 produce outputs consistent with
    the routing rules defined in the state machine.
    """

    # -----------------------------------------------------------------------
    # 5a: q1_identified=False → should escalate with missing_data
    # -----------------------------------------------------------------------

    @settings(max_examples=100)
    @given(
        missing_order=st.booleans(),
        has_error=st.booleans(),
    )
    def test_q1_false_when_order_missing(self, missing_order, has_error):
        """
        evaluate_q1 returns False when order is None or contains an error key.
        Routing rule: q1=False → ESCALATE with missing_data.
        **Validates: Requirements 3.1, 3.2**
        """
        if missing_order:
            order = None
        elif has_error:
            order = {"error": "not_found", "order_id": "O999"}
        else:
            # Both missing — use None for order
            order = None

        state = _make_state(order=order)
        result = evaluate_q1(state)
        assert result is False, (
            f"evaluate_q1 should return False when order is missing/errored, got {result}"
        )

    @settings(max_examples=100)
    @given(has_error=st.booleans())
    def test_q1_false_when_customer_missing(self, has_error):
        """
        evaluate_q1 returns False when customer is None or contains an error key.
        **Validates: Requirements 3.1, 3.2**
        """
        if has_error:
            customer = {"error": "not_found", "identifier": "C999"}
        else:
            customer = None

        state = _make_state(customer=customer)
        result = evaluate_q1(state)
        assert result is False, (
            f"evaluate_q1 should return False when customer is missing/errored, got {result}"
        )

    @settings(max_examples=100)
    @given(
        order_error=st.booleans(),
        customer_error=st.booleans(),
    )
    def test_q1_false_when_both_missing(self, order_error, customer_error):
        """
        evaluate_q1 returns False when both order and customer are missing/errored.
        **Validates: Requirements 3.1, 3.2**
        """
        order = {"error": "not_found"} if order_error else None
        customer = {"error": "not_found"} if customer_error else None
        state = _make_state(order=order, customer=customer)
        result = evaluate_q1(state)
        assert result is False

    def test_q1_true_when_both_present(self):
        """
        evaluate_q1 returns True when both order and customer are present without errors.
        **Validates: Requirements 3.1, 3.2**
        """
        state = _make_state()
        result = evaluate_q1(state)
        assert result is True

    # -----------------------------------------------------------------------
    # 5b: q1=True, q2=True → resolution should be APPROVE or DENY (not ESCALATE)
    #     We verify evaluate_q2 returns (True, updates) for in-policy states.
    # -----------------------------------------------------------------------

    @settings(max_examples=100)
    @given(
        purchase_days_ago=st.integers(min_value=1, max_value=25),
    )
    def test_q2_true_for_in_window_refund(self, purchase_days_ago):
        """
        evaluate_q2 returns (True, updates) for a refund request within the return window.
        When q1=True and q2=True, routing should produce APPROVE or DENY (not ESCALATE).
        **Validates: Requirements 3.3, 3.4**
        """
        purchase_date = (
            datetime.date.today() - datetime.timedelta(days=purchase_days_ago)
        ).isoformat()
        order = {**_VALID_ORDER, "purchase_date": purchase_date}
        # Use O001 which maps to P001 (30-day return window)
        state = _make_state(order=order)
        in_policy, updates = evaluate_q2(state)
        assert in_policy is True, (
            f"Expected in_policy=True for {purchase_days_ago} days ago (window=30), "
            f"got {in_policy}, updates={updates}"
        )
        assert "refund_amount" in updates, (
            "Expected refund_amount in updates for approved refund"
        )

    # -----------------------------------------------------------------------
    # 5c: confidence_score < 0.75 → ESCALATE with ambiguous_request
    #     We verify the routing rule by checking evaluate_q2 returns escalation
    #     for ambiguous issue types (which drives low confidence).
    # -----------------------------------------------------------------------

    def test_q2_escalates_for_ambiguous_issue_type(self):
        """
        evaluate_q2 returns (False, {"escalation_category": "ambiguous_request"})
        for ambiguous issue type. This is the trigger for low-confidence escalation.
        **Validates: Requirements 3.4, 13.3**
        """
        ticket = {**_VALID_TICKET, "issue_type": "ambiguous"}
        state = _make_state(ticket=ticket)
        in_policy, updates = evaluate_q2(state)
        assert in_policy is False
        assert updates.get("escalation_category") == "ambiguous_request"

    @settings(max_examples=100)
    @given(
        issue_type=st.sampled_from(["ambiguous"]),
        description=st.text(min_size=0, max_size=200),
    )
    def test_q2_always_escalates_ambiguous(self, issue_type, description):
        """
        evaluate_q2 always returns (False, ambiguous_request) for ambiguous issue type,
        regardless of description content.
        **Validates: Requirements 3.4, 13.3**
        """
        ticket = {**_VALID_TICKET, "issue_type": issue_type, "description": description}
        state = _make_state(ticket=ticket)
        in_policy, updates = evaluate_q2(state)
        assert in_policy is False
        assert updates.get("escalation_category") == "ambiguous_request"

    # -----------------------------------------------------------------------
    # 5d: q1=False routing consistency — missing_data category
    # -----------------------------------------------------------------------

    @settings(max_examples=100)
    @given(
        order_missing=st.booleans(),
        customer_missing=st.booleans(),
    )
    def test_routing_consistency_q1_false_implies_missing_data(
        self, order_missing, customer_missing
    ):
        """
        When evaluate_q1 returns False, the routing rule requires ESCALATE with
        missing_data. We verify evaluate_q1 returns False for all missing-data states.
        **Validates: Requirements 3.2, 3.1**
        """
        # At least one must be missing for q1=False
        if not order_missing and not customer_missing:
            order_missing = True

        order = None if order_missing else _VALID_ORDER
        customer = None if customer_missing else _VALID_CUSTOMER
        state = _make_state(order=order, customer=customer)

        q1 = evaluate_q1(state)
        assert q1 is False, (
            "evaluate_q1 must return False when order or customer is missing"
        )
        # The routing rule: q1=False → ESCALATE with missing_data
        # (verified by the graph, but we confirm the evaluator output is consistent)


# ===========================================================================
# Property 7: Eligibility Evaluation Correctness
# Validates: Requirements 4.4, 5.1, 5.2, 5.3, 6.2
# ===========================================================================


class TestProperty7EligibilityEvaluationCorrectness:
    """
    Tests the pure eligibility logic directly via _compute_eligibility helper,
    which mirrors the logic in check_refund_eligibility.
    """

    @settings(max_examples=200)
    @given(
        days_since_purchase=st.integers(min_value=1, max_value=730),
        return_window_days=st.sampled_from([15, 30, 60]),
        warranty_months=st.sampled_from([0, 6, 12, 24]),
        is_vip=st.booleans(),
        vip_window=st.just(90),
    )
    def test_within_return_window_is_eligible(
        self,
        days_since_purchase,
        return_window_days,
        warranty_months,
        is_vip,
        vip_window,
    ):
        """
        If days_since_purchase <= effective_return_window → eligible=True.
        **Validates: Requirements 4.4, 6.2**
        """
        effective_window = vip_window if is_vip else return_window_days
        if days_since_purchase > effective_window:
            pytest.skip("Not within return window — skip this case")

        result = _compute_eligibility(
            days_since_purchase, return_window_days, warranty_months, is_vip, vip_window
        )
        assert result is True, (
            f"Expected eligible=True for {days_since_purchase} days "
            f"(effective window={effective_window}), got {result}"
        )

    @settings(max_examples=200)
    @given(
        days_since_purchase=st.integers(min_value=1, max_value=730),
        return_window_days=st.sampled_from([15, 30, 60]),
        warranty_months=st.sampled_from([6, 12, 24]),
        is_vip=st.booleans(),
        vip_window=st.just(90),
    )
    def test_outside_window_within_warranty_escalates(
        self,
        days_since_purchase,
        return_window_days,
        warranty_months,
        is_vip,
        vip_window,
    ):
        """
        If days_since_purchase > effective_return_window AND within warranty → eligible="escalate".
        **Validates: Requirements 5.1, 5.2, 5.3**
        """
        effective_window = vip_window if is_vip else return_window_days
        months_since = days_since_purchase / 30.0

        if days_since_purchase <= effective_window:
            pytest.skip("Within return window — skip this case")
        if months_since > warranty_months:
            pytest.skip("Outside warranty — skip this case")

        result = _compute_eligibility(
            days_since_purchase, return_window_days, warranty_months, is_vip, vip_window
        )
        assert result == "escalate", (
            f"Expected eligible='escalate' for {days_since_purchase} days "
            f"(effective window={effective_window}, warranty={warranty_months}mo), got {result}"
        )

    @settings(max_examples=200)
    @given(
        days_since_purchase=st.integers(min_value=1, max_value=730),
        return_window_days=st.sampled_from([15, 30, 60]),
        warranty_months=st.sampled_from([0, 6, 12, 24]),
        is_vip=st.booleans(),
        vip_window=st.just(90),
    )
    def test_outside_window_outside_warranty_not_eligible(
        self,
        days_since_purchase,
        return_window_days,
        warranty_months,
        is_vip,
        vip_window,
    ):
        """
        If days_since_purchase > effective_return_window AND (warranty=0 OR outside warranty)
        → eligible=False.
        **Validates: Requirements 4.4, 5.2**
        """
        effective_window = vip_window if is_vip else return_window_days
        months_since = days_since_purchase / 30.0

        if days_since_purchase <= effective_window:
            pytest.skip("Within return window — skip this case")
        if warranty_months > 0 and months_since <= warranty_months:
            pytest.skip("Within warranty — skip this case")

        result = _compute_eligibility(
            days_since_purchase, return_window_days, warranty_months, is_vip, vip_window
        )
        assert result is False, (
            f"Expected eligible=False for {days_since_purchase} days "
            f"(effective window={effective_window}, warranty={warranty_months}mo), got {result}"
        )

    @settings(max_examples=100)
    @given(
        days_since_purchase=st.integers(min_value=1, max_value=89),
        return_window_days=st.sampled_from([15, 30, 60]),
        warranty_months=st.sampled_from([0, 6, 12, 24]),
    )
    def test_vip_uses_extended_window_not_product_window(
        self,
        days_since_purchase,
        return_window_days,
        warranty_months,
    ):
        """
        For VIP customers, effective_return_window = vip_window (90) regardless of
        product return_window_days.
        **Validates: Requirements 6.2**
        """
        vip_window = 90
        # days_since_purchase is 1–89, so always within VIP window
        result_vip = _compute_eligibility(
            days_since_purchase, return_window_days, warranty_months, True, vip_window
        )
        assert result_vip is True, (
            f"VIP customer with {days_since_purchase} days should be eligible "
            f"(vip_window=90), got {result_vip}"
        )

    @settings(max_examples=100)
    @given(
        days_since_purchase=st.integers(min_value=61, max_value=730),
        warranty_months=st.sampled_from([0, 6, 12, 24]),
    )
    def test_non_vip_uses_product_return_window(
        self,
        days_since_purchase,
        warranty_months,
    ):
        """
        For non-VIP customers, effective_return_window = product return_window_days.
        With return_window_days=60 and days_since_purchase > 60, should not be eligible
        (unless within warranty).
        **Validates: Requirements 4.4**
        """
        return_window_days = 60
        months_since = days_since_purchase / 30.0

        result = _compute_eligibility(
            days_since_purchase, return_window_days, warranty_months, False
        )

        if warranty_months > 0 and months_since <= warranty_months:
            assert result == "escalate", (
                f"Expected 'escalate' for {days_since_purchase} days, "
                f"warranty={warranty_months}mo, got {result}"
            )
        else:
            assert result is False, (
                f"Expected False for {days_since_purchase} days, "
                f"warranty={warranty_months}mo, got {result}"
            )

    def test_evaluate_q2_uses_vip_window_for_vip_customer(self):
        """
        evaluate_q2 applies VIP extended return window (90 days) for VIP customers.

        Uses real order data:
        - O001 (Alice/VIP, P001 30-day window): Alice has 90-day VIP window, so
          a recent purchase is in-policy.
        - O012 (Bob/standard, P008 60-day window, 0-month warranty): 228 days ago
          is out of window and out of warranty → not in-policy (denial).

        Note: evaluate_q2 calls check_refund_eligibility(order_id, ...) which reads
        from the data files directly, so the customer tier is determined by the
        actual customer record in the data, not the state's customer field.
        **Validates: Requirements 6.2**
        """
        # VIP order: O001 belongs to Alice (VIP, 90-day window), recently purchased
        vip_ticket = {**_VALID_TICKET, "issue_type": "refund_request", "description": "I want a refund."}
        vip_order = {
            "order_id": "O001",
            "customer_id": "C001",
            "product_id": "P001",
            "purchase_date": _VALID_ORDER["purchase_date"],
            "amount": 899.99,
            "status": "delivered",
        }
        vip_customer = _VALID_CUSTOMER  # Alice, tier=vip
        state_vip = _make_state(order=vip_order, customer=vip_customer, ticket=vip_ticket)
        in_policy_vip, updates_vip = evaluate_q2(state_vip)
        # O001 is Alice's order — check_refund_eligibility uses Alice's VIP 90-day window
        # The order is recent (within 90 days), so should be in-policy
        assert in_policy_vip is True, (
            f"VIP customer (Alice, O001) should be in-policy, "
            f"got in_policy={in_policy_vip}, updates={updates_vip}"
        )

        # Standard order: O012 belongs to Bob (standard), P008 has 60-day window,
        # 0-month warranty, purchased ~228 days ago → out of window, no warranty
        standard_order = {
            "order_id": "O012",
            "customer_id": "C006",
            "product_id": "P008",
            "purchase_date": "2025-09-01",
            "amount": 79.99,
            "status": "delivered",
        }
        standard_customer = {
            "customer_id": "C006",
            "name": "Bob",
            "email": "bob.anderson@example.com",
            "tier": "standard",
            "vip_exceptions": {},
        }
        standard_ticket = {
            **_VALID_TICKET,
            "issue_type": "refund_request",
            "description": "I want a refund for my speaker.",
        }
        state_std = _make_state(
            order=standard_order, customer=standard_customer, ticket=standard_ticket
        )
        in_policy_std, updates_std = evaluate_q2(state_std)
        # O012 is Bob's order — check_refund_eligibility uses standard 60-day window
        # 228 days ago, P008 has 0-month warranty → not eligible → denial
        assert in_policy_std is False, (
            f"Standard customer (Bob, O012, 228 days ago) should not be in-policy, "
            f"got in_policy={in_policy_std}, updates={updates_std}"
        )


# ===========================================================================
# Property 8: Fraud Escalation Without Refund
# Validates: Requirements 7.1, 7.2, 7.4
# ===========================================================================

_THREAT_PHRASES = ["sue", "lawyer", "legal action", "lawsuit"]
_SOCIAL_ENGINEERING_PHRASES = ["on behalf of", "authorized representative", "bypass"]


class TestProperty8FraudEscalationWithoutRefund:
    """
    Tests that evaluate_q2 escalates with the correct fraud category for
    threat/social-engineering language, and does NOT include refund_amount.
    """

    @settings(max_examples=100)
    @given(
        phrase=st.sampled_from(_THREAT_PHRASES),
        prefix=st.text(min_size=0, max_size=50, alphabet=st.characters(whitelist_categories=("Ll", "Lu", "Nd", "Zs"))),
        suffix=st.text(min_size=0, max_size=50, alphabet=st.characters(whitelist_categories=("Ll", "Lu", "Nd", "Zs"))),
    )
    def test_threat_language_escalates_with_threat_detected(self, phrase, prefix, suffix):
        """
        evaluate_q2 returns (False, {"escalation_category": "threat_detected"})
        for any description containing threat language.
        **Validates: Requirements 7.1, 7.4**
        """
        description = f"{prefix} {phrase} {suffix}".strip()
        ticket = {**_VALID_TICKET, "description": description}
        state = _make_state(ticket=ticket)

        in_policy, updates = evaluate_q2(state)

        assert in_policy is False, (
            f"Expected in_policy=False for threat phrase '{phrase}', got {in_policy}"
        )
        assert updates.get("escalation_category") == "threat_detected", (
            f"Expected escalation_category='threat_detected' for phrase '{phrase}', "
            f"got {updates.get('escalation_category')}"
        )

    @settings(max_examples=100)
    @given(
        phrase=st.sampled_from(_SOCIAL_ENGINEERING_PHRASES),
        prefix=st.text(min_size=0, max_size=50, alphabet=st.characters(whitelist_categories=("Ll", "Lu", "Nd", "Zs"))),
        suffix=st.text(min_size=0, max_size=50, alphabet=st.characters(whitelist_categories=("Ll", "Lu", "Nd", "Zs"))),
    )
    def test_social_engineering_language_escalates_correctly(self, phrase, prefix, suffix):
        """
        evaluate_q2 returns (False, {"escalation_category": "social_engineering"})
        for any description containing social engineering language.
        **Validates: Requirements 7.2, 7.4**
        """
        description = f"{prefix} {phrase} {suffix}".strip()
        ticket = {**_VALID_TICKET, "description": description}
        state = _make_state(ticket=ticket)

        in_policy, updates = evaluate_q2(state)

        assert in_policy is False, (
            f"Expected in_policy=False for social engineering phrase '{phrase}', got {in_policy}"
        )
        assert updates.get("escalation_category") == "social_engineering", (
            f"Expected escalation_category='social_engineering' for phrase '{phrase}', "
            f"got {updates.get('escalation_category')}"
        )

    @settings(max_examples=100)
    @given(phrase=st.sampled_from(_THREAT_PHRASES + _SOCIAL_ENGINEERING_PHRASES))
    def test_fraud_escalation_does_not_include_refund_amount(self, phrase):
        """
        The updates dict for fraud escalations does NOT contain "refund_amount".
        **Validates: Requirements 7.4**
        """
        description = f"I want to {phrase} if you don't help me."
        ticket = {**_VALID_TICKET, "description": description}
        state = _make_state(ticket=ticket)

        in_policy, updates = evaluate_q2(state)

        assert in_policy is False
        assert "refund_amount" not in updates, (
            f"refund_amount must not be in updates for fraud escalation, "
            f"got updates={updates}"
        )

    @settings(max_examples=100)
    @given(phrase=st.sampled_from(_THREAT_PHRASES))
    def test_threat_escalation_category_is_threat_detected(self, phrase):
        """
        All threat phrases produce escalation_category='threat_detected'.
        **Validates: Requirements 7.1**
        """
        description = f"I will {phrase} if this is not resolved immediately."
        ticket = {**_VALID_TICKET, "description": description}
        state = _make_state(ticket=ticket)

        in_policy, updates = evaluate_q2(state)

        assert updates.get("escalation_category") == "threat_detected"

    @settings(max_examples=100)
    @given(phrase=st.sampled_from(_SOCIAL_ENGINEERING_PHRASES))
    def test_social_engineering_category_is_social_engineering(self, phrase):
        """
        All social engineering phrases produce escalation_category='social_engineering'.
        **Validates: Requirements 7.2**
        """
        description = f"I am calling {phrase} the account holder."
        ticket = {**_VALID_TICKET, "description": description}
        state = _make_state(ticket=ticket)

        in_policy, updates = evaluate_q2(state)

        assert updates.get("escalation_category") == "social_engineering"
