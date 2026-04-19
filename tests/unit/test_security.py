"""
tests/unit/test_security.py — Security and input validation tests.

Tests for:
  - Threat detection keyword coverage
  - Social engineering keyword coverage
  - Edge cases in threat detection (case sensitivity, partial matches)
  - Input sanitization and boundary values
  - .env file security
  - CORS configuration review
  - Refund amount boundary tests
"""

from __future__ import annotations

import datetime
import os

import pytest

from agent.decisions import (
    evaluate_q1,
    evaluate_q2,
    compute_confidence_score,
    is_high_stakes,
    _THREAT_KEYWORDS,
    _SOCIAL_ENGINEERING_KEYWORDS,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_state(description="Normal request", issue_type="refund_request", order=None, customer=None):
    return {
        "ticket": {
            "ticket_id": "T001",
            "customer_id": "C001",
            "order_id": "O001",
            "issue_type": issue_type,
            "description": description,
        },
        "order": order or {
            "order_id": "O001",
            "customer_id": "C001",
            "product_id": "P001",
            "purchase_date": (datetime.date.today() - datetime.timedelta(days=5)).isoformat(),
            "amount": 100.0,
            "status": "delivered",
        },
        "customer": customer or {
            "customer_id": "C001",
            "name": "Alice",
            "email": "alice@example.com",
            "tier": "vip",
            "vip_exceptions": {"extended_return_window_days": 90},
        },
        "product": None,
        "prior_customer_records": [],
        "escalation_category": None,
        "denial_reason": None,
        "refund_amount": None,
        "q2_in_policy": None,
        "resolution": None,
    }


# ===========================================================================
# Threat keyword detection
# ===========================================================================

class TestThreatDetection:
    """Ensure all threat keywords are correctly detected."""

    @pytest.mark.parametrize("keyword", _THREAT_KEYWORDS)
    def test_each_threat_keyword_triggers_escalation(self, keyword):
        """Each keyword in _THREAT_KEYWORDS must trigger threat_detected."""
        description = f"I am going to {keyword} about this issue."
        state = _make_state(description=description)
        in_policy, updates = evaluate_q2(state)
        assert in_policy is False, f"Keyword '{keyword}' should trigger escalation"
        assert updates.get("escalation_category") == "threat_detected", (
            f"Keyword '{keyword}' should set category to threat_detected, got {updates}"
        )

    def test_threat_keyword_case_sensitivity(self):
        """Threat detection uses .lower() on description, so mixed case should still match."""
        # The description is lowered in evaluate_q2
        state = _make_state(description="I will SUE you!")
        in_policy, updates = evaluate_q2(state)
        assert in_policy is False
        assert updates.get("escalation_category") == "threat_detected"

    def test_no_false_positive_on_safe_words(self):
        """Words not containing any threat keyword substring should not trigger."""
        state = _make_state(description="I want to follow up on this matter further.")
        in_policy, updates = evaluate_q2(state)
        assert updates.get("escalation_category") != "threat_detected"

    def test_known_limitation_pursue_contains_sue(self):
        """KNOWN LIMITATION: 'pursue' contains 'sue' and triggers false positive.
        This documents a substring-matching weakness in the keyword-based threat detection.
        The current implementation uses simple `in` matching, so 'pursue' triggers 'sue'."""
        state = _make_state(description="I want to pursue this matter further.")
        in_policy, updates = evaluate_q2(state)
        # This IS a false positive — but documents current behavior
        assert updates.get("escalation_category") == "threat_detected"

    def test_combined_threat_and_social_engineering(self):
        """Threat takes priority over social engineering (checked first)."""
        description = "I am calling on behalf of the owner and will sue you."
        state = _make_state(description=description)
        in_policy, updates = evaluate_q2(state)
        assert in_policy is False
        # "sue" is a threat keyword, checked first
        assert updates.get("escalation_category") == "threat_detected"


# ===========================================================================
# Social engineering detection
# ===========================================================================

class TestSocialEngineeringDetection:
    """Ensure all social engineering keywords are correctly detected."""

    @pytest.mark.parametrize("keyword", _SOCIAL_ENGINEERING_KEYWORDS)
    def test_each_social_engineering_keyword_triggers_escalation(self, keyword):
        """Each keyword in _SOCIAL_ENGINEERING_KEYWORDS must trigger social_engineering."""
        description = f"Please help, I need to {keyword} for this account."
        state = _make_state(description=description)
        in_policy, updates = evaluate_q2(state)
        assert in_policy is False, f"Keyword '{keyword}' should trigger escalation"
        assert updates.get("escalation_category") == "social_engineering", (
            f"Keyword '{keyword}' should set category to social_engineering, got {updates}"
        )

    def test_social_engineering_case_sensitivity(self):
        """Description is lowered, so mixed case should match."""
        state = _make_state(description="Please SKIP VERIFICATION for this account.")
        in_policy, updates = evaluate_q2(state)
        assert in_policy is False
        assert updates.get("escalation_category") == "social_engineering"


# ===========================================================================
# Input boundary tests
# ===========================================================================

class TestInputBoundaries:
    """Test boundary values and edge cases for inputs."""

    def test_empty_description_handled(self):
        """Empty description should not crash evaluate_q2."""
        state = _make_state(description="")
        in_policy, updates = evaluate_q2(state)
        # Empty description, valid order → should be in-policy for refund
        assert isinstance(in_policy, bool)

    def test_very_long_description_handled(self):
        """Very long description should not crash or cause issues."""
        long_desc = "A" * 100000
        state = _make_state(description=long_desc)
        in_policy, updates = evaluate_q2(state)
        assert isinstance(in_policy, bool)

    def test_unicode_description_handled(self):
        """Unicode characters in description should be handled."""
        state = _make_state(description="我想退款。この製品は壊れています。لا يعمل هذا المنتج")
        in_policy, updates = evaluate_q2(state)
        assert isinstance(in_policy, bool)

    def test_null_fields_in_ticket_handled(self):
        """Missing fields in ticket should not crash."""
        state = _make_state()
        state["ticket"] = {}  # Completely empty ticket
        in_policy, updates = evaluate_q2(state)
        assert isinstance(in_policy, bool)

    def test_special_characters_in_description(self):
        """SQL injection-like strings should be treated as normal text."""
        state = _make_state(description="'; DROP TABLE orders; --")
        in_policy, updates = evaluate_q2(state)
        assert isinstance(in_policy, bool)  # Should not crash
        # Should not trigger threat or social engineering
        assert updates.get("escalation_category") not in ("threat_detected", "social_engineering")

    def test_html_injection_in_description(self):
        """HTML/Script in description should be treated as normal text."""
        state = _make_state(description="<script>alert('xss')</script><img onerror=alert(1)>")
        in_policy, updates = evaluate_q2(state)
        assert isinstance(in_policy, bool)


# ===========================================================================
# Refund amount boundary tests
# ===========================================================================

class TestRefundAmountBoundaries:
    """Test boundary values for refund amounts."""

    def test_negative_refund_amount_not_high_stakes(self):
        """Negative refund amount should not be high stakes."""
        state = {"resolution": "APPROVE", "refund_amount": -100.0, "escalation_category": None}
        assert is_high_stakes(state) is False

    def test_zero_refund_amount_not_high_stakes(self):
        state = {"resolution": "APPROVE", "refund_amount": 0.0, "escalation_category": None}
        assert is_high_stakes(state) is False

    def test_very_large_refund_amount_is_high_stakes(self):
        state = {"resolution": "APPROVE", "refund_amount": 999999.99, "escalation_category": None}
        assert is_high_stakes(state) is True

    def test_float_precision_boundary(self):
        """200.01 should be high stakes, 199.99 should not."""
        state_high = {"resolution": "APPROVE", "refund_amount": 200.01, "escalation_category": None}
        state_low = {"resolution": "APPROVE", "refund_amount": 199.99, "escalation_category": None}
        assert is_high_stakes(state_high) is True
        assert is_high_stakes(state_low) is False

    def test_none_refund_amount_not_high_stakes(self):
        state = {"resolution": "APPROVE", "refund_amount": None, "escalation_category": None}
        assert is_high_stakes(state) is False


# ===========================================================================
# Confidence scoring security
# ===========================================================================

class TestConfidenceScoringSecurity:
    """Ensure confidence scoring cannot be manipulated."""

    def test_prior_fraud_always_zeroes_policy_consistency(self):
        """Even with complete data and clear policy, fraud zeroes consistency."""
        state = _make_state()
        state["prior_customer_records"] = [{
            "ticket_id": "T000",
            "resolution": "ESCALATE",
            "escalation_category": "threat_detected",
            "fraud_flags": ["threat_detected"],
        }]
        score, updates = compute_confidence_score(state)
        assert updates["confidence_factors"]["policy_consistency"] == 0.0

    def test_multiple_fraud_flags_still_zero(self):
        state = _make_state()
        state["prior_customer_records"] = [
            {"ticket_id": "T000", "resolution": "ESCALATE",
             "escalation_category": "threat_detected", "fraud_flags": ["threat_detected"]},
            {"ticket_id": "T001", "resolution": "ESCALATE",
             "escalation_category": "social_engineering", "fraud_flags": ["social_engineering"]},
        ]
        score, updates = compute_confidence_score(state)
        assert updates["confidence_factors"]["policy_consistency"] == 0.0

    def test_score_always_in_range(self):
        """Score must always be in [0.0, 1.0] regardless of inputs."""
        for pc in [[], [{"resolution": "DENY", "fraud_flags": []}],
                    [{"resolution": "ESCALATE", "escalation_category": "threat_detected", "fraud_flags": ["threat_detected"]}]]:
            state = _make_state()
            state["prior_customer_records"] = pc
            score, updates = compute_confidence_score(state)
            assert 0.0 <= score <= 1.0, f"Score {score} out of range for records={pc}"


# ===========================================================================
# Environment & Configuration Security
# ===========================================================================

class TestConfigSecurity:
    """Non-invasive checks for security configuration."""

    def test_env_example_does_not_contain_real_keys(self):
        """The .env.example file should not contain real API keys."""
        env_example_path = os.path.join(
            os.path.dirname(__file__), "..", "..", ".env.example"
        )
        if os.path.exists(env_example_path):
            with open(env_example_path, "r") as f:
                content = f.read()
            # Should not contain actual keys (keys start with sk-ant- or gsk_)
            assert "sk-ant-api" not in content, ".env.example should not contain real Anthropic keys"
            assert "gsk_" not in content or "gsk_your" in content.lower(), (
                ".env.example should not contain real Groq keys"
            )

    def test_gitignore_excludes_env(self):
        """The .gitignore should exclude .env files."""
        gitignore_path = os.path.join(
            os.path.dirname(__file__), "..", "..", ".gitignore"
        )
        if os.path.exists(gitignore_path):
            with open(gitignore_path, "r") as f:
                content = f.read()
            assert ".env" in content, ".gitignore should exclude .env"
