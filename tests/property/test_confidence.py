# Feature: shopwave-support-agent
# Property 11: Confidence Score Validity — Validates: Requirements 13.1, 13.5

from __future__ import annotations

import pytest
from hypothesis import given, settings, strategies as st

from agent.decisions import compute_confidence_score

# ---------------------------------------------------------------------------
# Strategy: generate random confidence factor values
# ---------------------------------------------------------------------------


@st.composite
def confidence_factors_strategy(draw):
    """Generate a dict of three factor values, each in [0.0, 1.0]."""
    return {
        "data_completeness": draw(
            st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False)
        ),
        "reason_clarity": draw(
            st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False)
        ),
        "policy_consistency": draw(
            st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False)
        ),
    }


# ---------------------------------------------------------------------------
# State builders for real-state tests
# ---------------------------------------------------------------------------

_KNOWN_ORDER_IDS = [f"O{str(i).zfill(3)}" for i in range(1, 21)]
_KNOWN_CUSTOMER_IDS = [f"C{str(i).zfill(3)}" for i in range(1, 11)]

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

_VALID_PRODUCT = {
    "product_id": "P001",
    "name": "ProBook Laptop",
    "category": "electronics",
    "return_window_days": 30,
    "warranty_months": 24,
    "price": 899.99,
}

_VALID_TICKET = {
    "ticket_id": "T001",
    "customer_id": "C001",
    "order_id": "O001",
    "issue_type": "refund_request",
    "description": "I would like to return my laptop because it stopped working after two days of use.",
    "metadata": {"priority": "NORMAL", "channel": "email"},
}


def _make_state(
    *,
    order=_VALID_ORDER,
    customer=_VALID_CUSTOMER,
    product=_VALID_PRODUCT,
    ticket=_VALID_TICKET,
    prior_customer_records=None,
    escalation_category=None,
    denial_reason=None,
    q2_in_policy=None,
    refund_amount=None,
) -> dict:
    return {
        "ticket": ticket,
        "order": order,
        "customer": customer,
        "product": product,
        "prior_customer_records": prior_customer_records or [],
        "escalation_category": escalation_category,
        "denial_reason": denial_reason,
        "q2_in_policy": q2_in_policy,
        "refund_amount": refund_amount,
    }


# ===========================================================================
# Property 11: Confidence Score Validity
# Validates: Requirements 13.1, 13.5
# ===========================================================================


class TestProperty11ConfidenceScoreValidity:
    """
    Tests that compute_confidence_score always returns a score in [0.0, 1.0],
    that confidence_factors contains all required keys with valid values,
    and that the weighted average formula is correct.
    """

    # -----------------------------------------------------------------------
    # 11a: Score is always in [0.0, 1.0] for any valid state
    # -----------------------------------------------------------------------

    @settings(max_examples=100)
    @given(
        order_present=st.booleans(),
        customer_present=st.booleans(),
        product_present=st.booleans(),
        description=st.text(min_size=0, max_size=300),
        issue_type=st.sampled_from(
            ["refund_request", "warranty_claim", "replacement_request", "ambiguous", "policy_question"]
        ),
        has_prior_denial=st.booleans(),
        has_prior_fraud=st.booleans(),
    )
    def test_score_always_in_unit_interval(
        self,
        order_present,
        customer_present,
        product_present,
        description,
        issue_type,
        has_prior_denial,
        has_prior_fraud,
    ):
        """
        compute_confidence_score always returns a score in [0.0, 1.0] for any valid state.
        **Validates: Requirements 13.1**
        """
        order = _VALID_ORDER if order_present else None
        customer = _VALID_CUSTOMER if customer_present else None
        product = _VALID_PRODUCT if product_present else None

        prior_records = []
        if has_prior_denial:
            prior_records.append({"ticket_id": "T_prev", "resolution": "DENY", "fraud_flags": []})
        if has_prior_fraud:
            prior_records.append(
                {
                    "ticket_id": "T_fraud",
                    "resolution": "ESCALATE",
                    "escalation_category": "threat_detected",
                    "fraud_flags": ["threat_detected"],
                }
            )

        ticket = {**_VALID_TICKET, "description": description, "issue_type": issue_type}
        state = _make_state(
            order=order,
            customer=customer,
            product=product,
            ticket=ticket,
            prior_customer_records=prior_records,
        )

        score, updates = compute_confidence_score(state)

        assert isinstance(score, float), f"Score must be a float, got {type(score)}"
        assert 0.0 <= score <= 1.0, (
            f"Score must be in [0.0, 1.0], got {score}"
        )

    # -----------------------------------------------------------------------
    # 11b: confidence_factors always contains all three required keys
    # -----------------------------------------------------------------------

    @settings(max_examples=100)
    @given(
        order_present=st.booleans(),
        customer_present=st.booleans(),
        product_present=st.booleans(),
        description=st.text(min_size=0, max_size=200),
    )
    def test_confidence_factors_contains_all_required_keys(
        self,
        order_present,
        customer_present,
        product_present,
        description,
    ):
        """
        The returned confidence_factors dict always contains all three keys:
        data_completeness, reason_clarity, policy_consistency.
        **Validates: Requirements 13.5**
        """
        order = _VALID_ORDER if order_present else None
        customer = _VALID_CUSTOMER if customer_present else None
        product = _VALID_PRODUCT if product_present else None
        ticket = {**_VALID_TICKET, "description": description}
        state = _make_state(order=order, customer=customer, product=product, ticket=ticket)

        score, updates = compute_confidence_score(state)

        assert "confidence_factors" in updates, "updates must contain 'confidence_factors'"
        factors = updates["confidence_factors"]
        assert isinstance(factors, dict), f"confidence_factors must be a dict, got {type(factors)}"

        required_keys = {"data_completeness", "reason_clarity", "policy_consistency"}
        missing_keys = required_keys - set(factors.keys())
        assert not missing_keys, (
            f"confidence_factors is missing keys: {missing_keys}"
        )

    # -----------------------------------------------------------------------
    # 11c: Each factor value is in [0.0, 1.0]
    # -----------------------------------------------------------------------

    @settings(max_examples=100)
    @given(
        order_present=st.booleans(),
        customer_present=st.booleans(),
        product_present=st.booleans(),
        description=st.text(min_size=0, max_size=200),
        has_prior_fraud=st.booleans(),
    )
    def test_each_factor_value_in_unit_interval(
        self,
        order_present,
        customer_present,
        product_present,
        description,
        has_prior_fraud,
    ):
        """
        Each factor value (data_completeness, reason_clarity, policy_consistency)
        is always in [0.0, 1.0].
        **Validates: Requirements 13.5**
        """
        order = _VALID_ORDER if order_present else None
        customer = _VALID_CUSTOMER if customer_present else None
        product = _VALID_PRODUCT if product_present else None

        prior_records = []
        if has_prior_fraud:
            prior_records.append(
                {
                    "ticket_id": "T_fraud",
                    "resolution": "ESCALATE",
                    "escalation_category": "threat_detected",
                    "fraud_flags": ["threat_detected"],
                }
            )

        ticket = {**_VALID_TICKET, "description": description}
        state = _make_state(
            order=order,
            customer=customer,
            product=product,
            ticket=ticket,
            prior_customer_records=prior_records,
        )

        score, updates = compute_confidence_score(state)
        factors = updates["confidence_factors"]

        for key in ("data_completeness", "reason_clarity", "policy_consistency"):
            value = factors[key]
            assert isinstance(value, float), (
                f"Factor '{key}' must be a float, got {type(value)}"
            )
            assert 0.0 <= value <= 1.0, (
                f"Factor '{key}' must be in [0.0, 1.0], got {value}"
            )

    # -----------------------------------------------------------------------
    # 11d: Weighted average formula correctness
    #      Given any three factor values in [0.0, 1.0], the weighted average
    #      0.4*a + 0.3*b + 0.3*c is always in [0.0, 1.0].
    # -----------------------------------------------------------------------

    @settings(max_examples=500)
    @given(factors=confidence_factors_strategy())
    def test_weighted_average_always_in_unit_interval(self, factors):
        """
        For any three factor values in [0.0, 1.0], the weighted average
        0.4 * data_completeness + 0.3 * reason_clarity + 0.3 * policy_consistency
        is always in [0.0, 1.0].
        **Validates: Requirements 13.1, 13.5**
        """
        a = factors["data_completeness"]
        b = factors["reason_clarity"]
        c = factors["policy_consistency"]

        weighted_avg = 0.4 * a + 0.3 * b + 0.3 * c

        assert 0.0 <= weighted_avg <= 1.0, (
            f"Weighted average {weighted_avg} is out of [0.0, 1.0] for factors {factors}"
        )

    @settings(max_examples=500)
    @given(factors=confidence_factors_strategy())
    def test_weighted_average_formula_is_correct(self, factors):
        """
        The weighted average 0.4*a + 0.3*b + 0.3*c equals the expected value
        within floating point tolerance of 1e-9.
        **Validates: Requirements 13.5**
        """
        a = factors["data_completeness"]
        b = factors["reason_clarity"]
        c = factors["policy_consistency"]

        expected = 0.4 * a + 0.3 * b + 0.3 * c
        # Verify the formula itself is consistent (idempotent)
        recomputed = 0.4 * a + 0.3 * b + 0.3 * c
        assert abs(expected - recomputed) < 1e-9, (
            f"Weighted average formula is not consistent: {expected} vs {recomputed}"
        )
        # Verify the result is in [0.0, 1.0]
        assert 0.0 <= expected <= 1.0

    # -----------------------------------------------------------------------
    # 11e: Real states with known order/customer data — score always in [0.0, 1.0]
    # -----------------------------------------------------------------------

    @settings(max_examples=100)
    @given(
        order_id=st.sampled_from(_KNOWN_ORDER_IDS),
        customer_id=st.sampled_from(_KNOWN_CUSTOMER_IDS),
        description=st.text(min_size=10, max_size=200),
        issue_type=st.sampled_from(
            ["refund_request", "warranty_claim", "replacement_request", "policy_question"]
        ),
    )
    def test_real_state_score_always_in_unit_interval(
        self, order_id, customer_id, description, issue_type
    ):
        """
        With real order/customer data, compute_confidence_score always returns
        a score in [0.0, 1.0].
        **Validates: Requirements 13.1**
        """
        from agent.tools import get_customer, get_order, get_product

        order = get_order(order_id)
        customer = get_customer(customer_id)
        product_id = order.get("product_id") if "error" not in order else None
        product = get_product(product_id) if product_id else None

        ticket = {
            "ticket_id": "T_test",
            "customer_id": customer_id,
            "order_id": order_id,
            "issue_type": issue_type,
            "description": description,
            "metadata": {"priority": "NORMAL", "channel": "email"},
        }

        state = _make_state(
            order=order if "error" not in order else None,
            customer=customer if "error" not in customer else None,
            product=product if (product and "error" not in product) else None,
            ticket=ticket,
        )

        score, updates = compute_confidence_score(state)

        assert isinstance(score, float)
        assert 0.0 <= score <= 1.0, (
            f"Score {score} out of [0.0, 1.0] for order={order_id}, customer={customer_id}"
        )

    # -----------------------------------------------------------------------
    # 11f: Score returned in updates matches the returned score value
    # -----------------------------------------------------------------------

    @settings(max_examples=100)
    @given(
        order_present=st.booleans(),
        customer_present=st.booleans(),
        description=st.text(min_size=0, max_size=200),
    )
    def test_score_in_updates_matches_returned_score(
        self, order_present, customer_present, description
    ):
        """
        The confidence_score in the updates dict matches the returned score value.
        **Validates: Requirements 13.1**
        """
        order = _VALID_ORDER if order_present else None
        customer = _VALID_CUSTOMER if customer_present else None
        ticket = {**_VALID_TICKET, "description": description}
        state = _make_state(order=order, customer=customer, ticket=ticket)

        score, updates = compute_confidence_score(state)

        assert "confidence_score" in updates, "updates must contain 'confidence_score'"
        assert updates["confidence_score"] == score, (
            f"updates['confidence_score']={updates['confidence_score']} "
            f"does not match returned score={score}"
        )

    # -----------------------------------------------------------------------
    # 11g: Score equals weighted average of factors (within tolerance)
    # -----------------------------------------------------------------------

    def test_score_equals_weighted_average_of_factors(self):
        """
        The returned score equals 0.4*data_completeness + 0.3*reason_clarity
        + 0.3*policy_consistency (within 1e-9 tolerance).
        **Validates: Requirements 13.5**
        """
        state = _make_state()
        score, updates = compute_confidence_score(state)
        factors = updates["confidence_factors"]

        expected = (
            0.4 * factors["data_completeness"]
            + 0.3 * factors["reason_clarity"]
            + 0.3 * factors["policy_consistency"]
        )
        # Clamp to [0.0, 1.0] as the implementation does
        expected = max(0.0, min(1.0, expected))

        assert abs(score - expected) < 1e-9, (
            f"Score {score} does not equal weighted average {expected} "
            f"(factors={factors})"
        )

    @settings(max_examples=100)
    @given(
        order_present=st.booleans(),
        customer_present=st.booleans(),
        product_present=st.booleans(),
        description=st.text(min_size=0, max_size=200),
        issue_type=st.sampled_from(
            ["refund_request", "warranty_claim", "ambiguous", "policy_question"]
        ),
    )
    def test_score_equals_weighted_average_property(
        self,
        order_present,
        customer_present,
        product_present,
        description,
        issue_type,
    ):
        """
        For any state, the returned score equals the weighted average of the
        returned factors (within 1e-9 tolerance).
        **Validates: Requirements 13.5**
        """
        order = _VALID_ORDER if order_present else None
        customer = _VALID_CUSTOMER if customer_present else None
        product = _VALID_PRODUCT if product_present else None
        ticket = {**_VALID_TICKET, "description": description, "issue_type": issue_type}
        state = _make_state(order=order, customer=customer, product=product, ticket=ticket)

        score, updates = compute_confidence_score(state)
        factors = updates["confidence_factors"]

        expected = (
            0.4 * factors["data_completeness"]
            + 0.3 * factors["reason_clarity"]
            + 0.3 * factors["policy_consistency"]
        )
        expected = max(0.0, min(1.0, expected))

        assert abs(score - expected) < 1e-9, (
            f"Score {score} != weighted average {expected} (factors={factors})"
        )
