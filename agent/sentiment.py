"""
agent/sentiment.py — Adaptive Sentiment Intelligence Module

Analyses customer ticket descriptions to detect:
  - Emotional state: angry, frustrated, confused, desperate, calm, sarcastic
  - Churn risk: high, medium, low
  - Urgency signal: critical, high, medium, low

Uses LLM-based analysis with rule-based fallback. Results are stored in
TicketState and used downstream by confidence scoring, HITL thresholds,
and reply generation to adapt the agent's behaviour to the customer's
emotional context.
"""

from __future__ import annotations

import json
import re
from typing import Any


# ---------------------------------------------------------------------------
# Emotion keyword lexicons (rule-based fallback)
# ---------------------------------------------------------------------------

_EMOTION_LEXICON: dict[str, list[str]] = {
    "angry": [
        "unacceptable", "outraged", "furious", "terrible", "worst",
        "disgusting", "never again", "fed up", "ridiculous", "absurd",
        "infuriating", "appalling", "demand", "incompetent",
    ],
    "frustrated": [
        "frustrated", "annoying", "disappointing", "still waiting",
        "multiple times", "again and again", "no response", "keeps happening",
        "tired of", "waste of time", "getting nowhere", "third time",
    ],
    "desperate": [
        "please help", "urgent", "desperately", "last resort", "beg",
        "can't afford", "need this resolved", "emergency", "critical",
        "depend on", "rely on", "livelihood",
    ],
    "confused": [
        "don't understand", "confused", "unclear", "not sure", "how do i",
        "what does", "explain", "lost", "makes no sense", "why was",
    ],
    "sarcastic": [
        "great job", "wonderful service", "thanks for nothing",
        "oh sure", "brilliant", "clearly you", "love how",
        "congratulations", "as usual",
    ],
    "calm": [
        "i would like", "could you", "please", "when you get a chance",
        "no rush", "wondering if", "appreciate", "thank you",
    ],
}

_URGENCY_KEYWORDS: dict[str, list[str]] = {
    "critical": [
        "business stopped", "can't operate", "production down",
        "losing money", "customers affected", "deadline", "emergency",
    ],
    "high": [
        "urgent", "asap", "immediately", "right away", "as soon as possible",
        "time sensitive", "need this today",
    ],
    "medium": [
        "soon", "when possible", "this week", "at your convenience",
    ],
}

_CHURN_SIGNALS: list[str] = [
    "cancel my account", "switching to", "competitor", "never buying",
    "close my account", "unsubscribe", "done with", "leaving",
    "going elsewhere", "last order", "final purchase",
]


# ---------------------------------------------------------------------------
# Rule-based fallback analysis
# ---------------------------------------------------------------------------

def _rule_based_sentiment(description: str, customer_tier: str = "",
                          prior_tickets: int = 0) -> dict:
    """
    Keyword-based sentiment analysis. Fast, deterministic, zero-cost.
    Used when LLM is unavailable.
    """
    text = description.lower()

    # --- Emotion detection ---
    emotion_scores: dict[str, float] = {}
    for emotion, keywords in _EMOTION_LEXICON.items():
        hits = sum(1 for kw in keywords if kw in text)
        if hits > 0:
            emotion_scores[emotion] = hits / len(keywords)

    if emotion_scores:
        primary_emotion = max(emotion_scores, key=emotion_scores.get)
        emotion_confidence = min(emotion_scores[primary_emotion] * 3, 1.0)
    else:
        primary_emotion = "neutral"
        emotion_confidence = 0.5

    # --- Urgency ---
    urgency = "low"
    for level in ["critical", "high", "medium"]:
        if any(kw in text for kw in _URGENCY_KEYWORDS.get(level, [])):
            urgency = level
            break

    # --- Churn risk ---
    churn_hits = sum(1 for signal in _CHURN_SIGNALS if signal in text)
    if churn_hits >= 2 or (churn_hits >= 1 and primary_emotion == "angry"):
        churn_risk = "high"
    elif churn_hits >= 1 or primary_emotion in ("angry", "desperate"):
        churn_risk = "medium"
    elif customer_tier == "vip" and primary_emotion == "frustrated":
        churn_risk = "medium"
    else:
        churn_risk = "low"

    # Boost churn risk for repeat complainers
    if prior_tickets >= 2:
        if churn_risk == "low":
            churn_risk = "medium"
        elif churn_risk == "medium":
            churn_risk = "high"

    # --- Recommended tone ---
    tone_map = {
        "angry": "empathetic_and_apologetic",
        "frustrated": "understanding_and_proactive",
        "desperate": "reassuring_and_urgent",
        "confused": "clear_and_educational",
        "sarcastic": "professional_and_sincere",
        "calm": "warm_and_efficient",
        "neutral": "professional_and_friendly",
    }

    return {
        "primary_emotion": primary_emotion,
        "emotion_confidence": round(emotion_confidence, 2),
        "emotion_scores": {k: round(v, 3) for k, v in emotion_scores.items()},
        "urgency": urgency,
        "churn_risk": churn_risk,
        "recommended_tone": tone_map.get(primary_emotion, "professional_and_friendly"),
        "analysis_method": "rule_based",
    }


# ---------------------------------------------------------------------------
# LLM-based sentiment analysis
# ---------------------------------------------------------------------------

_LLM_ANALYSIS_PROMPT = """Analyse the emotional state of this customer support ticket.

Customer tier: {tier}
Prior support interactions: {prior_count}
Issue type: {issue_type}

Ticket text:
\"\"\"{description}\"\"\"

Respond in this EXACT JSON format (no markdown, no extra text):
{{
  "primary_emotion": "<angry|frustrated|confused|desperate|calm|sarcastic|neutral>",
  "emotion_confidence": <0.0-1.0>,
  "urgency": "<critical|high|medium|low>",
  "churn_risk": "<high|medium|low>",
  "recommended_tone": "<empathetic_and_apologetic|understanding_and_proactive|reassuring_and_urgent|clear_and_educational|professional_and_sincere|warm_and_efficient|professional_and_friendly>",
  "reasoning": "<1 sentence explaining your assessment>"
}}"""


async def _llm_sentiment(description: str, customer_tier: str = "",
                         issue_type: str = "", prior_count: int = 0) -> dict | None:
    """
    LLM-powered sentiment analysis. Returns parsed dict or None on failure.
    """
    try:
        from agent.llm_client import chat_completion

        prompt = _LLM_ANALYSIS_PROMPT.format(
            tier=customer_tier or "unknown",
            prior_count=prior_count,
            issue_type=issue_type or "unknown",
            description=description[:500],
        )

        response = await chat_completion(
            messages=[{"role": "user", "content": prompt}],
            system="You are an expert sentiment analyst. Respond only with valid JSON.",
            max_tokens=250,
            temperature=0.0,
        )

        # Parse JSON from response — handle markdown code blocks
        text = response.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)

        result = json.loads(text)

        # Validate required fields
        valid_emotions = {"angry", "frustrated", "confused", "desperate",
                          "calm", "sarcastic", "neutral"}
        valid_urgency = {"critical", "high", "medium", "low"}
        valid_churn = {"high", "medium", "low"}

        if result.get("primary_emotion") not in valid_emotions:
            return None
        if result.get("urgency") not in valid_urgency:
            result["urgency"] = "medium"
        if result.get("churn_risk") not in valid_churn:
            result["churn_risk"] = "low"

        result["analysis_method"] = "llm"
        result.setdefault("emotion_confidence", 0.8)
        result.setdefault("emotion_scores", {})

        return result

    except Exception:
        return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def analyse_sentiment(
    description: str,
    customer_tier: str = "",
    issue_type: str = "",
    prior_ticket_count: int = 0,
) -> dict:
    """
    Analyse customer sentiment. Tries LLM first, falls back to rules.

    Returns a dict with:
      - primary_emotion: str
      - emotion_confidence: float  (0.0–1.0)
      - emotion_scores: dict       (per-emotion scores, rule-based only)
      - urgency: str               (critical/high/medium/low)
      - churn_risk: str            (high/medium/low)
      - recommended_tone: str
      - analysis_method: str       ("llm" or "rule_based")
      - reasoning: str             (LLM only)
    """
    # Try LLM first
    llm_result = await _llm_sentiment(description, customer_tier, issue_type, prior_ticket_count)
    if llm_result is not None:
        return llm_result

    # Fall back to rule-based
    return _rule_based_sentiment(description, customer_tier, prior_ticket_count)


def analyse_sentiment_sync(description: str, customer_tier: str = "",
                           issue_type: str = "",
                           prior_ticket_count: int = 0) -> dict:
    """Synchronous rule-based-only sentiment analysis (for tests and non-async contexts)."""
    return _rule_based_sentiment(description, customer_tier, prior_ticket_count)
