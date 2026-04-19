"""
agent/decisions.py — Business rule evaluators for the ShopWave Support Resolution Agent.

Contains four pure functions that evaluate state dicts and return decisions:
  - evaluate_q1: Can order and customer be identified?
  - evaluate_q2: Is the request within ShopWave policy?
  - compute_confidence_score: How confident is the agent in its decision?
  - is_high_stakes: Does this action require HITL review?
"""

from __future__ import annotations

from typing import Any

from agent.tools import check_refund_eligibility

# Attempt to load learned config — non-fatal if unavailable.
# Loaded once at import time; the threshold is re-read per call via
# get_confidence_threshold() so it picks up changes between runs.
try:
    from agent.learned_config import get_confidence_threshold as _get_threshold
    _HAS_LEARNED_CONFIG = True
except Exception:
    _HAS_LEARNED_CONFIG = False
    _get_threshold = lambda _=None: 0.75  # noqa: E731

# ---------------------------------------------------------------------------
# Threat and social engineering keyword lists
# ---------------------------------------------------------------------------

_THREAT_KEYWORDS: list[str] = [
    "sue",
    "lawyer",
    "legal action",
    "lawsuit",
    "attorney",
    "court",
    "chargeback",
    "dispute with my bank",
    "report you",
    "showing up in person",
]

_SOCIAL_ENGINEERING_KEYWORDS: list[str] = [
    "on behalf of",
    "authorized representative",
    "bypass",
    "without requiring",
    "act on his behalf",
    "act on her behalf",
    "urgent",
    "immediately without",
    "skip verification",
    "no questions",
]


# ---------------------------------------------------------------------------
# Q1: Can order and customer be identified?
# ---------------------------------------------------------------------------


def evaluate_q1(state: dict) -> bool:
    """
    Returns True if state["order"] and state["customer"] are both present
    (not None) and neither contains an "error" key.

    Requirements: 3.1, 3.2
    """
    order = state.get("order")
    customer = state.get("customer")

    if order is None or customer is None:
        return False

    if "error" in order or "error" in customer:
        return False

    return True


# ---------------------------------------------------------------------------
# Q2: Is the request within ShopWave policy?
# ---------------------------------------------------------------------------


def evaluate_q2(state: dict) -> tuple[bool, dict]:
    """
    Evaluates policy compliance for the ticket in *state*.

    Returns (in_policy: bool, updates: dict) where *updates* contains fields
    to merge into state (e.g. escalation_category, denial_reason, refund_amount).

    Checks (in order):
    1. Threat language detection
    2. Social engineering pattern detection
    3. Ambiguous issue type
    4. Missing order data
    5. Replacement request
    6. Warranty claim
    7. Refund eligibility (for refund_request)
    8. Default: in-policy

    Requirements: 3.1, 4.4, 5.1, 5.2, 6.2, 6.3, 7.1, 7.2, 8.2
    """
    ticket: dict = state.get("ticket") or {}
    description: str = ticket.get("description", "").lower()
    issue_type: str = ticket.get("issue_type", "")
    order: dict | None = state.get("order")

    # 1. Threat language detection
    for keyword in _THREAT_KEYWORDS:
        if keyword in description:
            return (False, {"escalation_category": "threat_detected"})

    # 2. Social engineering pattern detection
    for keyword in _SOCIAL_ENGINEERING_KEYWORDS:
        if keyword in description:
            return (False, {"escalation_category": "social_engineering"})

    # 3. Ambiguous issue type
    if issue_type == "ambiguous":
        return (False, {"escalation_category": "ambiguous_request"})

    # 4. Missing order data
    if order is None or "error" in order:
        return (False, {"escalation_category": "missing_data"})

    # 5. Replacement request
    if issue_type == "replacement_request":
        return (False, {"escalation_category": "replacement_needed"})

    # 6. Warranty claim
    if issue_type == "warranty_claim":
        order_id: str = order.get("order_id", "")
        result = check_refund_eligibility(order_id)
        if result.get("eligible") == "escalate":
            return (False, {"escalation_category": "warranty_claim"})
        # If not escalate (e.g. eligible=True or eligible=False), fall through
        # to default handling — treat as in-policy or denial based on result
        if result.get("eligible") is True:
            return (True, {"refund_amount": order.get("amount")})
        return (False, {"escalation_category": "warranty_claim"})

    # 7. Refund eligibility for refund_request
    if issue_type == "refund_request":
        order_id = order.get("order_id", "")
        result = check_refund_eligibility(order_id)
        eligible: Any = result.get("eligible")

        if eligible is True:
            return (True, {"refund_amount": order.get("amount")})

        if eligible == "escalate":
            return (False, {"escalation_category": "warranty_claim"})

        # eligible is False
        explanation: str = result.get("reason", result.get("explanation", "Refund not eligible."))
        return (False, {"denial_reason": explanation})

    # 8. Default: in-policy
    return (True, {})


# ---------------------------------------------------------------------------
# Q3: Confidence scoring
# ---------------------------------------------------------------------------


def compute_confidence_score(state: dict) -> tuple[float, dict]:
    """
    Computes a 0.0–1.0 confidence score from three weighted sub-scores.

    Returns (score: float, updates: dict) where *updates* contains:
      - confidence_score (float)
      - confidence_factors (dict with data_completeness, reason_clarity, policy_consistency)
      - self_reflection_note (str)

    Sub-scores and weights:
      - data_completeness  (weight 0.4)
      - reason_clarity     (weight 0.3)
      - policy_consistency (weight 0.3)

    Requirements: 13.1, 13.2, 13.4, 13.5, 16.4
    """
    ticket: dict = state.get("ticket") or {}
    description: str = ticket.get("description", "")
    issue_type: str = ticket.get("issue_type", "")

    order: dict | None = state.get("order")
    customer: dict | None = state.get("customer")
    product: dict | None = state.get("product")

    prior_records: list = state.get("prior_customer_records") or []
    escalation_category: str | None = state.get("escalation_category")
    denial_reason: str | None = state.get("denial_reason")
    q2_in_policy: bool | None = state.get("q2_in_policy")
    refund_amount: float | None = state.get("refund_amount")

    # ------------------------------------------------------------------
    # data_completeness (weight 0.4)
    # ------------------------------------------------------------------
    order_ok = order is not None and "error" not in order
    customer_ok = customer is not None and "error" not in customer
    product_ok = product is not None and "error" not in product

    if order_ok and customer_ok and product_ok:
        data_completeness = 1.0
    elif order_ok and customer_ok and not product_ok:
        data_completeness = 0.7
    elif not order_ok and customer_ok:
        data_completeness = 0.3
    elif order_ok and not customer_ok:
        data_completeness = 0.3
    else:
        # Both order and customer missing
        data_completeness = 0.0

    # ------------------------------------------------------------------
    # reason_clarity (weight 0.3)
    # ------------------------------------------------------------------
    desc_len = len(description)
    if desc_len >= 100 and issue_type != "ambiguous":
        reason_clarity = 0.9
    elif desc_len >= 50:
        reason_clarity = 0.7
    elif desc_len >= 20:
        reason_clarity = 0.5
    else:
        reason_clarity = 0.3

    # Cap at 0.4 for ambiguous issue type
    if issue_type == "ambiguous":
        reason_clarity = min(reason_clarity, 0.4)

    # ------------------------------------------------------------------
    # policy_consistency (weight 0.3)
    # ------------------------------------------------------------------
    policy_consistency = 1.0

    # Check prior records for denials and fraud flags
    has_prior_denial = False
    has_prior_fraud = False
    for record in prior_records:
        resolution = record.get("resolution", "")
        if resolution == "DENY":
            has_prior_denial = True
        fraud_flags: list = record.get("fraud_flags") or []
        esc_cat = record.get("escalation_category", "")
        if "threat_detected" in fraud_flags or "social_engineering" in fraud_flags:
            has_prior_fraud = True
        if esc_cat in ("threat_detected", "social_engineering"):
            has_prior_fraud = True

    if has_prior_fraud:
        policy_consistency = 0.0
    elif has_prior_denial:
        policy_consistency -= 0.1

    # Override based on current decision state (only if not already zeroed by fraud)
    if policy_consistency > 0.0:
        if escalation_category is not None:
            # Clear policy applies — escalation category is set
            policy_consistency = 0.8
        elif denial_reason is not None:
            # Clear denial
            policy_consistency = 0.9
        elif q2_in_policy is True and refund_amount is not None:
            # Clear approval
            policy_consistency = 0.95

    # ------------------------------------------------------------------
    # Weighted average
    # ------------------------------------------------------------------
    score = (
        0.4 * data_completeness
        + 0.3 * reason_clarity
        + 0.3 * policy_consistency
    )

    # Clamp to [0.0, 1.0]
    score = max(0.0, min(1.0, score))

    # ------------------------------------------------------------------
    # Sentiment-aware adjustments
    # ------------------------------------------------------------------
    sentiment: dict = state.get("sentiment") or {}
    primary_emotion: str = sentiment.get("primary_emotion", "neutral")
    churn_risk_val: str = state.get("churn_risk") or sentiment.get("churn_risk", "low")

    sentiment_adjustment = 0.0

    # High-churn angry/desperate customers with low confidence → push toward escalation
    if primary_emotion in ("angry", "desperate") and churn_risk_val == "high":
        sentiment_adjustment = -0.05
    # Frustrated repeat customers → slight confidence reduction
    elif primary_emotion == "frustrated" and len(prior_records) >= 1:
        sentiment_adjustment = -0.03
    # Calm customers with complete data → slight confidence boost
    elif primary_emotion == "calm" and data_completeness >= 0.7:
        sentiment_adjustment = 0.03

    score = max(0.0, min(1.0, score + sentiment_adjustment))

    # ------------------------------------------------------------------
    # Self-reflection note
    # ------------------------------------------------------------------
    notes: list[str] = []

    if data_completeness == 1.0:
        notes.append("All required data retrieved successfully.")
    elif data_completeness == 0.7:
        notes.append("Order and customer data present; product data missing.")
    elif data_completeness == 0.3:
        notes.append("Partial data: one of order or customer is missing.")
    else:
        notes.append("Critical data missing: both order and customer unavailable.")

    if reason_clarity >= 0.9:
        notes.append("Customer description is detailed and issue type is clear.")
    elif reason_clarity >= 0.7:
        notes.append("Customer description is moderately detailed.")
    elif reason_clarity >= 0.5:
        notes.append("Customer description is brief but present.")
    else:
        notes.append("Customer description is very short or ambiguous.")

    if has_prior_fraud:
        notes.append("Prior fraud flag detected; policy consistency set to 0.")
    elif has_prior_denial:
        notes.append("Prior denial on record; policy consistency reduced.")

    if escalation_category:
        notes.append(f"Escalation category '{escalation_category}' clearly applies.")
    elif denial_reason:
        notes.append("Denial reason is clearly established.")
    elif q2_in_policy is True and refund_amount is not None:
        notes.append("Refund approval is clearly within policy.")

    # Sentiment context in reflection
    if primary_emotion != "neutral":
        notes.append(f"Customer sentiment: {primary_emotion} (churn risk: {churn_risk_val}).")
        if sentiment_adjustment != 0.0:
            direction = "reduced" if sentiment_adjustment < 0 else "increased"
            notes.append(f"Confidence {direction} by {abs(sentiment_adjustment):.2f} due to sentiment.")

    self_reflection_note = " ".join(notes) + f" Confidence score: {score:.2f}."

    confidence_factors = {
        "data_completeness": data_completeness,
        "reason_clarity": reason_clarity,
        "policy_consistency": policy_consistency,
    }

    updates = {
        "confidence_score": score,
        "confidence_factors": confidence_factors,
        "self_reflection_note": self_reflection_note,
    }

    return (score, updates)


# ---------------------------------------------------------------------------
# High-stakes check
# ---------------------------------------------------------------------------


def is_high_stakes(state: dict) -> bool:
    """
    Returns True if the proposed action requires HITL review:
      - resolution == "APPROVE" and refund_amount > 200.0, OR
      - resolution == "ESCALATE" and escalation_category in
        {"threat_detected", "social_engineering"}

    Requirements: 15.1
    """
    resolution: str | None = state.get("resolution")
    refund_amount: float = state.get("refund_amount") or 0.0
    escalation_category: str | None = state.get("escalation_category")

    if resolution == "APPROVE" and refund_amount > 200.0:
        return True

    if resolution == "ESCALATE" and escalation_category in {
        "threat_detected",
        "social_engineering",
    }:
        return True

    return False
