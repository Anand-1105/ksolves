"""
tests/unit/test_sentiment.py — Unit tests for the Sentiment Intelligence module.

Tests rule-based fallback, LLM integration (mocked), emotion detection,
churn risk, urgency, and integration with graph node and confidence scoring.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.sentiment import (
    _rule_based_sentiment,
    _llm_sentiment,
    analyse_sentiment,
    analyse_sentiment_sync,
    _EMOTION_LEXICON,
    _URGENCY_KEYWORDS,
    _CHURN_SIGNALS,
)


def _run(coro):
    return asyncio.run(coro)


# ===========================================================================
# Rule-based sentiment analysis
# ===========================================================================

class TestRuleBasedSentiment:
    """Tests for _rule_based_sentiment fallback."""

    def test_neutral_for_no_keywords(self):
        result = _rule_based_sentiment("I ordered a laptop.")
        assert result["primary_emotion"] == "neutral"
        assert result["analysis_method"] == "rule_based"

    def test_angry_detection(self):
        result = _rule_based_sentiment("This is absolutely unacceptable and ridiculous!")
        assert result["primary_emotion"] == "angry"

    def test_frustrated_detection(self):
        result = _rule_based_sentiment("I've been waiting for weeks, this keeps happening again and again.")
        assert result["primary_emotion"] == "frustrated"

    def test_desperate_detection(self):
        result = _rule_based_sentiment("Please help me, this is urgent, I desperately need this resolved.")
        assert result["primary_emotion"] == "desperate"

    def test_confused_detection(self):
        result = _rule_based_sentiment("I don't understand what happened, this makes no sense to me.")
        assert result["primary_emotion"] == "confused"

    def test_calm_detection(self):
        result = _rule_based_sentiment("I would like to request a refund when you get a chance, thank you.")
        assert result["primary_emotion"] == "calm"

    def test_sarcastic_detection(self):
        result = _rule_based_sentiment("Great job, thanks for nothing, brilliant service as usual.")
        assert result["primary_emotion"] == "sarcastic"

    def test_case_insensitive(self):
        result = _rule_based_sentiment("This is UNACCEPTABLE and RIDICULOUS!")
        assert result["primary_emotion"] == "angry"

    def test_emotion_confidence_is_float(self):
        result = _rule_based_sentiment("This is terrible and disgusting!")
        assert isinstance(result["emotion_confidence"], float)
        assert 0.0 <= result["emotion_confidence"] <= 1.0

    def test_returns_all_required_fields(self):
        result = _rule_based_sentiment("Hello")
        required = {
            "primary_emotion", "emotion_confidence", "emotion_scores",
            "urgency", "churn_risk", "recommended_tone", "analysis_method",
        }
        assert required <= set(result.keys())


class TestUrgencyDetection:
    """Tests for urgency signal detection."""

    def test_critical_urgency(self):
        result = _rule_based_sentiment("Our production is down and we're losing money!")
        assert result["urgency"] == "critical"

    def test_high_urgency(self):
        result = _rule_based_sentiment("I need this resolved ASAP, immediately please!")
        assert result["urgency"] == "high"

    def test_medium_urgency(self):
        result = _rule_based_sentiment("Could you handle this soon when possible?")
        assert result["urgency"] == "medium"

    def test_low_urgency_default(self):
        result = _rule_based_sentiment("I ordered a laptop last week.")
        assert result["urgency"] == "low"


class TestChurnRiskDetection:
    """Tests for churn risk assessment."""

    def test_high_churn_multiple_signals(self):
        result = _rule_based_sentiment(
            "I'm done with your service, switching to a competitor, never buying again."
        )
        assert result["churn_risk"] == "high"

    def test_high_churn_angry_with_signal(self):
        result = _rule_based_sentiment(
            "This is unacceptable! I'm switching to a competitor!"
        )
        assert result["churn_risk"] == "high"

    def test_medium_churn_single_signal(self):
        result = _rule_based_sentiment("I might cancel my account if this isn't resolved.")
        assert result["churn_risk"] == "medium"

    def test_medium_churn_frustrated_vip(self):
        result = _rule_based_sentiment(
            "This is frustrating, I'm tired of these issues.",
            customer_tier="vip",
        )
        assert result["churn_risk"] in ("medium", "high")

    def test_low_churn_no_signals(self):
        result = _rule_based_sentiment("I'd like to return my order.")
        assert result["churn_risk"] == "low"

    def test_churn_boost_for_repeat_customers(self):
        result_first = _rule_based_sentiment("I want a refund.", prior_tickets=0)
        result_repeat = _rule_based_sentiment("I want a refund.", prior_tickets=3)
        # Repeat customer should have equal or higher churn risk
        risk_order = {"low": 0, "medium": 1, "high": 2}
        assert risk_order.get(result_repeat["churn_risk"], 0) >= risk_order.get(result_first["churn_risk"], 0)


class TestRecommendedTone:
    """Tests for tone recommendations."""

    def test_angry_gets_empathetic_tone(self):
        result = _rule_based_sentiment("This is outraged and terrible!")
        assert result["recommended_tone"] == "empathetic_and_apologetic"

    def test_frustrated_gets_proactive_tone(self):
        result = _rule_based_sentiment("This is so frustrating, I'm tired of waiting.")
        assert result["recommended_tone"] == "understanding_and_proactive"

    def test_desperate_gets_reassuring_tone(self):
        result = _rule_based_sentiment("Please help me, I desperately need this.")
        assert result["recommended_tone"] == "reassuring_and_urgent"

    def test_confused_gets_educational_tone(self):
        result = _rule_based_sentiment("I don't understand, this makes no sense.")
        assert result["recommended_tone"] == "clear_and_educational"

    def test_calm_gets_efficient_tone(self):
        result = _rule_based_sentiment("I would like a refund, thank you.")
        assert result["recommended_tone"] == "warm_and_efficient"

    def test_neutral_gets_friendly_tone(self):
        result = _rule_based_sentiment("Requesting a refund for order O001.")
        assert result["recommended_tone"] == "professional_and_friendly"


# ===========================================================================
# LLM-based sentiment (mocked)
# ===========================================================================

class TestLLMSentiment:
    """Tests for LLM-based sentiment with mocked calls."""

    def test_valid_llm_response_parsed(self):
        llm_response = '{"primary_emotion": "angry", "emotion_confidence": 0.9, "urgency": "high", "churn_risk": "high", "recommended_tone": "empathetic_and_apologetic", "reasoning": "Customer is clearly upset"}'
        with patch("agent.llm_client.chat_completion", new_callable=AsyncMock) as mock:
            mock.return_value = llm_response
            result = _run(_llm_sentiment("I am furious!", "vip", "refund_request", 2))
        assert result["primary_emotion"] == "angry"
        assert result["urgency"] == "high"
        assert result["analysis_method"] == "llm"

    def test_llm_response_with_markdown_code_block(self):
        llm_response = '```json\n{"primary_emotion": "frustrated", "emotion_confidence": 0.85, "urgency": "medium", "churn_risk": "medium", "recommended_tone": "understanding_and_proactive", "reasoning": "test"}\n```'
        with patch("agent.llm_client.chat_completion", new_callable=AsyncMock) as mock:
            mock.return_value = llm_response
            result = _run(_llm_sentiment("Frustrating service"))
        assert result["primary_emotion"] == "frustrated"

    def test_invalid_emotion_returns_none(self):
        llm_response = '{"primary_emotion": "invalid_emotion", "urgency": "medium"}'
        with patch("agent.llm_client.chat_completion", new_callable=AsyncMock) as mock:
            mock.return_value = llm_response
            result = _run(_llm_sentiment("test"))
        assert result is None

    def test_invalid_json_returns_none(self):
        with patch("agent.llm_client.chat_completion", new_callable=AsyncMock) as mock:
            mock.return_value = "This is not JSON at all"
            result = _run(_llm_sentiment("test"))
        assert result is None

    def test_llm_exception_returns_none(self):
        with patch("agent.llm_client.chat_completion", new_callable=AsyncMock) as mock:
            mock.side_effect = Exception("LLM down")
            result = _run(_llm_sentiment("test"))
        assert result is None

    def test_defaults_for_missing_urgency(self):
        llm_response = '{"primary_emotion": "calm", "emotion_confidence": 0.7, "churn_risk": "low", "recommended_tone": "warm_and_efficient", "reasoning": "ok"}'
        with patch("agent.llm_client.chat_completion", new_callable=AsyncMock) as mock:
            mock.return_value = llm_response
            result = _run(_llm_sentiment("test"))
        assert result["urgency"] == "medium"  # Default when not provided


# ===========================================================================
# Public API: analyse_sentiment
# ===========================================================================

class TestAnalyseSentiment:
    """Tests for the public analyse_sentiment function."""

    def test_falls_back_to_rules_when_llm_fails(self):
        with patch("agent.sentiment._llm_sentiment", new_callable=AsyncMock) as mock:
            mock.return_value = None  # LLM failed
            result = _run(analyse_sentiment("This is terrible and unacceptable!"))
        assert result["analysis_method"] == "rule_based"
        assert result["primary_emotion"] == "angry"

    def test_uses_llm_when_available(self):
        llm_result = {
            "primary_emotion": "frustrated",
            "emotion_confidence": 0.9,
            "urgency": "high",
            "churn_risk": "medium",
            "recommended_tone": "understanding_and_proactive",
            "analysis_method": "llm",
            "reasoning": "test",
            "emotion_scores": {},
        }
        with patch("agent.sentiment._llm_sentiment", new_callable=AsyncMock) as mock:
            mock.return_value = llm_result
            result = _run(analyse_sentiment("test"))
        assert result["analysis_method"] == "llm"
        assert result["primary_emotion"] == "frustrated"

    def test_sync_version_uses_rules(self):
        result = analyse_sentiment_sync("This is outraged!")
        assert result["analysis_method"] == "rule_based"
        assert result["primary_emotion"] in ("angry", "neutral")


# ===========================================================================
# Edge cases
# ===========================================================================

class TestSentimentEdgeCases:
    def test_empty_description(self):
        result = _rule_based_sentiment("")
        assert result["primary_emotion"] == "neutral"
        assert result["churn_risk"] == "low"

    def test_very_long_description(self):
        long_text = "This is terrible. " * 5000
        result = _rule_based_sentiment(long_text)
        assert result["primary_emotion"] == "angry"

    def test_unicode_description(self):
        result = _rule_based_sentiment("これは受け入れられません！")
        assert result["primary_emotion"] == "neutral"
        assert result["analysis_method"] == "rule_based"

    def test_all_emotions_have_tone_mapping(self):
        """Every detectable emotion should produce a valid recommended_tone."""
        for emotion in list(_EMOTION_LEXICON.keys()) + ["neutral"]:
            # Force each emotion by using its keywords
            if emotion == "neutral":
                text = "Order inquiry."
            else:
                text = " ".join(_EMOTION_LEXICON[emotion][:3])
            result = _rule_based_sentiment(text)
            assert result["recommended_tone"] is not None
            assert isinstance(result["recommended_tone"], str)


# ===========================================================================
# Integration with graph node
# ===========================================================================

class TestSentimentNodeIntegration:
    """Tests for the analyze_sentiment_node in graph.py."""

    def test_node_populates_state(self):
        from agent.graph import analyze_sentiment_node, set_runtime
        from agent.session_memory import SessionMemory

        sm = SessionMemory()
        tl = MagicMock()
        tl.emit = AsyncMock()
        set_runtime(sm, tl, [])

        state = {
            "ticket": {
                "ticket_id": "T001",
                "customer_id": "C001",
                "description": "This is absolutely unacceptable and ridiculous!",
                "issue_type": "refund_request",
            },
            "ticket_id": "T001",
        }

        with patch("agent.sentiment._llm_sentiment", new_callable=AsyncMock) as mock:
            mock.return_value = None  # Force rule-based
            result = _run(analyze_sentiment_node(state))

        assert "sentiment" in result
        assert "primary_emotion" in result
        assert "churn_risk" in result
        assert "urgency" in result
        assert "recommended_tone" in result
        assert result["primary_emotion"] == "angry"

    def test_node_handles_exception_gracefully(self):
        from agent.graph import analyze_sentiment_node, set_runtime

        # Set runtime to None to trigger exception path
        set_runtime(None, None, [])

        state = {
            "ticket": {"ticket_id": "T001", "description": "test"},
            "ticket_id": "T001",
        }

        with patch("agent.graph.analyse_sentiment", new_callable=AsyncMock) as mock:
            mock.side_effect = Exception("boom")
            result = _run(analyze_sentiment_node(state))

        assert result["sentiment"]["analysis_method"] == "error"
        assert "boom" in result["sentiment"].get("error", "")

    def test_node_emits_trace_event(self):
        from agent.graph import analyze_sentiment_node, set_runtime
        from agent.session_memory import SessionMemory

        sm = SessionMemory()
        tl = MagicMock()
        tl.emit = AsyncMock()
        set_runtime(sm, tl, [])

        state = {
            "ticket": {
                "ticket_id": "T001",
                "customer_id": "C001",
                "description": "I need help please",
                "issue_type": "refund_request",
            },
            "ticket_id": "T001",
        }

        with patch("agent.sentiment._llm_sentiment", new_callable=AsyncMock) as mock:
            mock.return_value = None
            _run(analyze_sentiment_node(state))

        tl.emit.assert_called_once()
        args = tl.emit.call_args
        assert args[0][0] == "sentiment_analysed"
        assert args[0][1] == "T001"


# ===========================================================================
# Integration with confidence scoring
# ===========================================================================

class TestSentimentConfidenceIntegration:
    """Tests that sentiment data affects confidence scoring."""

    def test_angry_high_churn_reduces_confidence(self):
        from agent.decisions import compute_confidence_score
        import datetime

        base_state = {
            "ticket": {"ticket_id": "T001", "description": "test", "issue_type": "refund_request"},
            "order": {"order_id": "O001", "purchase_date": (datetime.date.today() - datetime.timedelta(days=5)).isoformat(), "amount": 100},
            "customer": {"customer_id": "C001", "name": "Alice", "tier": "vip", "vip_exceptions": {}},
            "product": None,
            "prior_customer_records": [],
            "escalation_category": None,
            "denial_reason": None,
            "refund_amount": None,
            "q2_in_policy": None,
            "resolution": None,
        }

        # Without sentiment
        state_neutral = {**base_state, "sentiment": {"primary_emotion": "neutral"}, "churn_risk": "low"}
        score_neutral, _ = compute_confidence_score(state_neutral)

        # With angry + high churn
        state_angry = {**base_state, "sentiment": {"primary_emotion": "angry", "churn_risk": "high"}, "churn_risk": "high"}
        score_angry, updates_angry = compute_confidence_score(state_angry)

        assert score_angry < score_neutral, (
            f"Angry+high-churn ({score_angry}) should be lower than neutral ({score_neutral})"
        )
        # Reflection should mention sentiment
        assert "sentiment" in updates_angry.get("self_reflection_note", "").lower() or "angry" in updates_angry.get("self_reflection_note", "").lower()

    def test_calm_boosts_confidence(self):
        from agent.decisions import compute_confidence_score
        import datetime

        base_state = {
            "ticket": {"ticket_id": "T001", "description": "test", "issue_type": "refund_request"},
            "order": {"order_id": "O001", "purchase_date": (datetime.date.today() - datetime.timedelta(days=5)).isoformat(), "amount": 100},
            "customer": {"customer_id": "C001", "name": "Alice", "tier": "vip", "vip_exceptions": {}},
            "product": {"product_id": "P001", "return_window_days": 30, "warranty_months": 12},
            "prior_customer_records": [],
            "escalation_category": None,
            "denial_reason": None,
            "refund_amount": None,
            "q2_in_policy": None,
            "resolution": None,
        }

        state_neutral = {**base_state, "sentiment": {"primary_emotion": "neutral"}, "churn_risk": "low"}
        score_neutral, _ = compute_confidence_score(state_neutral)

        state_calm = {**base_state, "sentiment": {"primary_emotion": "calm"}, "churn_risk": "low"}
        score_calm, _ = compute_confidence_score(state_calm)

        assert score_calm >= score_neutral, (
            f"Calm ({score_calm}) should be >= neutral ({score_neutral})"
        )
