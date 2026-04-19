"""
tests/unit/test_llm_client.py - Unit tests for the LLM client fallback logic.
Groq is primary, Anthropic is fallback.
"""
from __future__ import annotations
import asyncio
from unittest.mock import AsyncMock, patch
import pytest
from agent.llm_client import (
    LLMUnavailableError, chat_completion,
    GROQ_MODEL, ANTHROPIC_MODEL,
    DEFAULT_MAX_TOKENS, DEFAULT_TEMPERATURE,
)


def _run(coro):
    return asyncio.run(coro)


class TestChatCompletionFallback:
    def test_returns_groq_response_when_available(self):
        with patch("agent.llm_client._call_groq", new_callable=AsyncMock) as mock_groq, \
             patch("agent.llm_client._call_anthropic", new_callable=AsyncMock) as mock_anthropic:
            mock_groq.return_value = "Groq response"
            mock_anthropic.return_value = "Anthropic response"
            result = _run(chat_completion([{"role": "user", "content": "Hello"}]))
            assert result == "Groq response"
            mock_groq.assert_called_once()
            mock_anthropic.assert_not_called()

    def test_falls_back_to_anthropic_when_groq_fails(self):
        with patch("agent.llm_client._call_groq", new_callable=AsyncMock) as mock_groq, \
             patch("agent.llm_client._call_anthropic", new_callable=AsyncMock) as mock_anthropic:
            mock_groq.side_effect = Exception("Groq unavailable")
            mock_anthropic.return_value = "Anthropic fallback response"
            result = _run(chat_completion([{"role": "user", "content": "Hello"}]))
            assert result == "Anthropic fallback response"
            mock_groq.assert_called_once()
            mock_anthropic.assert_called_once()

    def test_raises_llm_unavailable_when_both_fail(self):
        with patch("agent.llm_client._call_groq", new_callable=AsyncMock) as mock_groq, \
             patch("agent.llm_client._call_anthropic", new_callable=AsyncMock) as mock_anthropic:
            mock_groq.side_effect = Exception("Groq down")
            mock_anthropic.side_effect = Exception("Anthropic down")
            with pytest.raises(LLMUnavailableError) as exc_info:
                _run(chat_completion([{"role": "user", "content": "Hello"}]))
            assert "Groq" in str(exc_info.value)
            assert "Anthropic" in str(exc_info.value)

    def test_passes_system_prompt_to_groq(self):
        with patch("agent.llm_client._call_groq", new_callable=AsyncMock) as mock_groq:
            mock_groq.return_value = "ok"
            _run(chat_completion(
                messages=[{"role": "user", "content": "Hi"}],
                system="You are a support agent.",
            ))
            assert "You are a support agent." in str(mock_groq.call_args)

    def test_passes_system_prompt_to_anthropic_on_fallback(self):
        with patch("agent.llm_client._call_groq", new_callable=AsyncMock) as mock_groq, \
             patch("agent.llm_client._call_anthropic", new_callable=AsyncMock) as mock_anthropic:
            mock_groq.side_effect = Exception("down")
            mock_anthropic.return_value = "anthropic ok"
            _run(chat_completion(
                messages=[{"role": "user", "content": "Hi"}],
                system="You are a support agent.",
            ))
            assert "You are a support agent." in str(mock_anthropic.call_args)

    def test_rate_limit_triggers_anthropic_fallback(self):
        with patch("agent.llm_client._call_groq", new_callable=AsyncMock) as mock_groq, \
             patch("agent.llm_client._call_anthropic", new_callable=AsyncMock) as mock_anthropic:
            mock_groq.side_effect = Exception("rate_limit: 429")
            mock_anthropic.return_value = "Anthropic handled it"
            result = _run(chat_completion([{"role": "user", "content": "Hello"}]))
            assert result == "Anthropic handled it"

    def test_default_parameters_are_applied(self):
        with patch("agent.llm_client._call_groq", new_callable=AsyncMock) as mock_groq:
            mock_groq.return_value = "ok"
            _run(chat_completion([{"role": "user", "content": "Hi"}]))
            mock_groq.assert_called_once()
            args = mock_groq.call_args[0]
            assert args[2] == DEFAULT_MAX_TOKENS
            assert args[3] == DEFAULT_TEMPERATURE

    def test_error_message_contains_both_provider_errors(self):
        with patch("agent.llm_client._call_groq", new_callable=AsyncMock) as mock_groq, \
             patch("agent.llm_client._call_anthropic", new_callable=AsyncMock) as mock_anthropic:
            mock_groq.side_effect = Exception("groq_specific_error")
            mock_anthropic.side_effect = Exception("anthropic_specific_error")
            with pytest.raises(LLMUnavailableError) as exc_info:
                _run(chat_completion([{"role": "user", "content": "Hi"}]))
            assert "groq_specific_error" in str(exc_info.value)
            assert "anthropic_specific_error" in str(exc_info.value)
