"""
agent/llm_client.py - LLM client: Groq primary, Anthropic fallback.
"""
from __future__ import annotations
import logging, os
from typing import Optional

logger = logging.getLogger(__name__)

GROQ_MODEL = "llama-3.1-8b-instant"
ANTHROPIC_MODEL = "claude-3-5-haiku-20241022"
DEFAULT_MAX_TOKENS = 512
DEFAULT_TEMPERATURE = 0.0


class LLMUnavailableError(Exception):
    """Raised when both Groq and Anthropic are unavailable."""


async def _call_groq(messages, system, max_tokens, temperature):
    from groq import AsyncGroq
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise ValueError("GROQ_API_KEY not set")
    client = AsyncGroq(api_key=api_key)
    full_messages = []
    if system:
        full_messages.append({"role": "system", "content": system})
    full_messages.extend(messages)
    response = await client.chat.completions.create(
        model=GROQ_MODEL,
        messages=full_messages,
        max_tokens=max_tokens,
        temperature=temperature,
    )
    return response.choices[0].message.content


async def _call_anthropic(messages, system, max_tokens, temperature):
    import anthropic
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY not set")
    client = anthropic.AsyncAnthropic(api_key=api_key)
    kwargs = {"model": ANTHROPIC_MODEL, "max_tokens": max_tokens, "messages": messages}
    if system:
        kwargs["system"] = system
    response = await client.messages.create(**kwargs)
    return response.content[0].text


async def chat_completion(
    messages,
    system=None,
    max_tokens=DEFAULT_MAX_TOKENS,
    temperature=DEFAULT_TEMPERATURE,
):
    """Try Groq first, fall back to Anthropic only if key is available."""
    groq_error = None
    try:
        logger.debug("Calling Groq (%s)", GROQ_MODEL)
        result = await _call_groq(messages, system, max_tokens, temperature)
        logger.debug("Groq call succeeded")
        return result
    except Exception as exc:
        groq_error = exc
        logger.warning(
            "Groq call failed (%s: %s)",
            type(exc).__name__, exc,
        )

    # Only try Anthropic if key is set
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise LLMUnavailableError(f"Groq failed and ANTHROPIC_API_KEY not set. Groq error: {groq_error}")

    try:
        logger.debug("Calling Anthropic Claude (%s)", ANTHROPIC_MODEL)
        result = await _call_anthropic(messages, system, max_tokens, temperature)
        logger.debug("Anthropic fallback call succeeded")
        return result
    except Exception as anthropic_error:
        logger.error(
            "Anthropic fallback also failed (%s: %s)",
            type(anthropic_error).__name__, anthropic_error,
        )
        raise LLMUnavailableError(
            "Both LLM providers failed. "
            f"Groq: {groq_error}. Anthropic: {anthropic_error}."
        ) from anthropic_error


def chat_completion_sync(messages, system=None, max_tokens=DEFAULT_MAX_TOKENS, temperature=DEFAULT_TEMPERATURE):
    """Sync wrapper - use chat_completion() in async contexts instead."""
    import asyncio
    return asyncio.run(chat_completion(messages, system, max_tokens, temperature))
