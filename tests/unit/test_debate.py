"""
tests/unit/test_debate.py — Unit tests for the multi-agent debate module.

Tests debate logic with mocked LLM responses to verify:
  - Correct parsing of judge responses
  - Fallback to original resolution when parsing fails
  - Debate transcript structure
  - Handling of all resolution types
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from agent.debate import run_debate


def _run(coro):
    return asyncio.run(coro)


def _make_state(
    resolution="APPROVE",
    escalation_category=None,
    refund_amount=250.0,
    confidence_score=0.85,
):
    return {
        "ticket": {
            "ticket_id": "T001",
            "customer_id": "C001",
            "issue_type": "refund_request",
            "description": "My laptop stopped working after two days.",
        },
        "order": {
            "order_id": "O001",
            "purchase_date": "2026-04-10",
            "amount": refund_amount,
        },
        "customer": {
            "name": "Alice",
            "tier": "vip",
        },
        "product": {
            "name": "UltraBook Pro 15",
            "return_window_days": 30,
        },
        "resolution": resolution,
        "escalation_category": escalation_category,
        "refund_amount": refund_amount,
        "confidence_score": confidence_score,
        "self_reflection_note": "All data present. Refund within policy.",
        "denial_reason": "",
    }


class TestRunDebate:
    """Tests for run_debate() with mocked LLM calls."""

    def test_returns_correct_structure(self):
        """run_debate must return dict with final_resolution, debate_transcript, judge_reasoning."""
        judge_response = (
            "FINAL_RESOLUTION: APPROVE\n"
            "ESCALATION_CATEGORY: none\n"
            "REASONING: The refund is within the 30-day window and customer is VIP."
        )
        with patch("agent.llm_client.chat_completion", new_callable=AsyncMock) as mock_llm:
            mock_llm.side_effect = [
                "Advocate argument: approve is correct.",
                "Skeptic argument: what if fraud?",
                judge_response,
            ]
            result = _run(run_debate(_make_state()))

        assert "final_resolution" in result
        assert "debate_transcript" in result
        assert "judge_reasoning" in result
        assert isinstance(result["debate_transcript"], list)
        assert len(result["debate_transcript"]) == 3

    def test_parses_approve_resolution(self):
        """Judge says APPROVE → final_resolution is APPROVE."""
        judge_response = (
            "FINAL_RESOLUTION: APPROVE\n"
            "ESCALATION_CATEGORY: none\n"
            "REASONING: Approved because policy allows it."
        )
        with patch("agent.llm_client.chat_completion", new_callable=AsyncMock) as mock_llm:
            mock_llm.side_effect = ["advocate", "skeptic", judge_response]
            result = _run(run_debate(_make_state()))
        assert result["final_resolution"] == "APPROVE"

    def test_parses_deny_resolution(self):
        """Judge says DENY → final_resolution is DENY."""
        judge_response = (
            "FINAL_RESOLUTION: DENY\n"
            "ESCALATION_CATEGORY: none\n"
            "REASONING: Order is outside return window."
        )
        with patch("agent.llm_client.chat_completion", new_callable=AsyncMock) as mock_llm:
            mock_llm.side_effect = ["advocate", "skeptic", judge_response]
            result = _run(run_debate(_make_state()))
        assert result["final_resolution"] == "DENY"

    def test_parses_escalate_with_category(self):
        """Judge says ESCALATE with threat_detected → both fields are correct."""
        judge_response = (
            "FINAL_RESOLUTION: ESCALATE\n"
            "ESCALATION_CATEGORY: threat_detected\n"
            "REASONING: Customer used threatening language."
        )
        with patch("agent.llm_client.chat_completion", new_callable=AsyncMock) as mock_llm:
            mock_llm.side_effect = ["advocate", "skeptic", judge_response]
            result = _run(run_debate(_make_state(resolution="ESCALATE", escalation_category="threat_detected")))
        assert result["final_resolution"] == "ESCALATE"
        assert result["final_category"] == "threat_detected"

    def test_judge_can_override_original_resolution(self):
        """Judge overrides APPROVE to ESCALATE — final_resolution reflects judge decision."""
        judge_response = (
            "FINAL_RESOLUTION: ESCALATE\n"
            "ESCALATION_CATEGORY: ambiguous_request\n"
            "REASONING: The skeptic raised valid fraud concerns."
        )
        with patch("agent.llm_client.chat_completion", new_callable=AsyncMock) as mock_llm:
            mock_llm.side_effect = ["advocate", "skeptic", judge_response]
            result = _run(run_debate(_make_state(resolution="APPROVE")))
        assert result["final_resolution"] == "ESCALATE"
        assert result["final_category"] == "ambiguous_request"

    def test_invalid_judge_response_falls_back_to_original(self):
        """If judge response is unparseable, fall back to original resolution."""
        judge_response = "I think we should approve this because the customer is right."
        with patch("agent.llm_client.chat_completion", new_callable=AsyncMock) as mock_llm:
            mock_llm.side_effect = ["advocate", "skeptic", judge_response]
            result = _run(run_debate(_make_state(resolution="APPROVE")))
        # Should fall back to original
        assert result["final_resolution"] == "APPROVE"

    def test_debate_transcript_has_three_roles(self):
        """Transcript must have advocate, skeptic, and judge entries."""
        judge_response = (
            "FINAL_RESOLUTION: APPROVE\n"
            "ESCALATION_CATEGORY: none\n"
            "REASONING: All good."
        )
        with patch("agent.llm_client.chat_completion", new_callable=AsyncMock) as mock_llm:
            mock_llm.side_effect = ["advocate arg", "skeptic arg", judge_response]
            result = _run(run_debate(_make_state()))

        roles = [entry["role"] for entry in result["debate_transcript"]]
        assert roles == ["advocate", "skeptic", "judge"]

    def test_advocate_and_skeptic_run_in_parallel(self):
        """Advocate and skeptic are called via asyncio.gather (2 concurrent calls)."""
        call_count = 0

        async def mock_chat(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                return f"Argument {call_count}"
            return (
                "FINAL_RESOLUTION: APPROVE\n"
                "ESCALATION_CATEGORY: none\n"
                "REASONING: Both arguments considered."
            )

        with patch("agent.llm_client.chat_completion", side_effect=mock_chat):
            result = _run(run_debate(_make_state()))

        assert call_count == 3  # advocate + skeptic + judge
        assert len(result["debate_transcript"]) == 3

    def test_escalation_category_none_clears_category(self):
        """If judge says ESCALATION_CATEGORY: none, final_category should be None."""
        judge_response = (
            "FINAL_RESOLUTION: APPROVE\n"
            "ESCALATION_CATEGORY: none\n"
            "REASONING: No escalation needed."
        )
        with patch("agent.llm_client.chat_completion", new_callable=AsyncMock) as mock_llm:
            mock_llm.side_effect = ["advocate", "skeptic", judge_response]
            result = _run(run_debate(_make_state(
                resolution="ESCALATE", escalation_category="threat_detected"
            )))
        assert result["final_resolution"] == "APPROVE"
        assert result["final_category"] is None

    def test_all_valid_escalation_categories(self):
        """All valid categories should be correctly parsed."""
        valid_categories = [
            "warranty_claim", "threat_detected", "social_engineering",
            "ambiguous_request", "missing_data", "replacement_needed",
        ]
        for cat in valid_categories:
            judge_response = (
                f"FINAL_RESOLUTION: ESCALATE\n"
                f"ESCALATION_CATEGORY: {cat}\n"
                f"REASONING: Category {cat} applies."
            )
            with patch("agent.llm_client.chat_completion", new_callable=AsyncMock) as mock_llm:
                mock_llm.side_effect = ["advocate", "skeptic", judge_response]
                result = _run(run_debate(_make_state(resolution="ESCALATE")))
            assert result["final_category"] == cat, f"Failed for category: {cat}"

    def test_handles_missing_state_fields_gracefully(self):
        """run_debate should not crash on minimal state."""
        minimal_state = {
            "ticket": {},
            "order": {},
            "customer": {},
            "product": {},
            "resolution": "APPROVE",
            "escalation_category": "",
            "refund_amount": 0.0,
            "confidence_score": 0.5,
            "self_reflection_note": "",
            "denial_reason": "",
        }
        judge_response = (
            "FINAL_RESOLUTION: APPROVE\n"
            "ESCALATION_CATEGORY: none\n"
            "REASONING: Minimal state."
        )
        with patch("agent.llm_client.chat_completion", new_callable=AsyncMock) as mock_llm:
            mock_llm.side_effect = ["advocate", "skeptic", judge_response]
            result = _run(run_debate(minimal_state))
        assert result["final_resolution"] == "APPROVE"
