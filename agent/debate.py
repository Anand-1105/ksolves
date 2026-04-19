"""
agent/debate.py — Multi-Agent Debate for High-Stakes Decisions

For tickets where is_high_stakes() returns True, spawns three sub-agents:
  - Advocate: argues FOR the proposed action (approve/escalate)
  - Skeptic:  argues AGAINST the proposed action
  - Judge:    reads both arguments, makes the final call

The debate transcript is stored in the audit record under 'debate_transcript'.
This ensures high-stakes decisions are deliberated, not just acted upon.
"""

from __future__ import annotations

import asyncio
from typing import Any


async def run_debate(state: dict) -> dict:
    """
    Run a three-agent debate for a high-stakes decision.

    Args:
        state: The current TicketState dict

    Returns:
        A dict with:
          - 'final_resolution': the judge's decision (APPROVE/DENY/ESCALATE)
          - 'final_category': escalation category if applicable
          - 'debate_transcript': list of {role, argument} dicts
          - 'judge_reasoning': the judge's final reasoning
    """
    from agent.llm_client import chat_completion

    ticket = state.get("ticket") or {}
    order = state.get("order") or {}
    customer = state.get("customer") or {}
    product = state.get("product") or {}
    resolution = state.get("resolution", "APPROVE")
    escalation_category = state.get("escalation_category", "")
    self_reflection = state.get("self_reflection_note", "") or ""
    denial_reason = state.get("denial_reason", "") or ""

    refund_amount_val = state.get("refund_amount") or order.get("amount", 0.0)
    refund_amount_display = float(refund_amount_val) if refund_amount_val is not None else 0.0
    confidence_score_val = state.get("confidence_score")
    confidence_display = float(confidence_score_val) if confidence_score_val is not None else 0.0

    # Build shared context for all agents
    context = f"""
Ticket ID: {ticket.get('ticket_id', 'unknown')}
Customer: {customer.get('name', 'unknown')} (Tier: {customer.get('tier', 'unknown')})
Issue type: {ticket.get('issue_type', 'unknown')}
Description: {ticket.get('description', '')[:300]}
Order ID: {order.get('order_id', 'N/A')}
Product: {product.get('name', 'N/A')} (Return window: {product.get('return_window_days', 'N/A')} days)
Purchase date: {order.get('purchase_date', 'N/A')}
Amount: ${refund_amount_display:.2f}
Proposed resolution: {resolution}
{f'Escalation category: {escalation_category}' if escalation_category else ''}
{f'Denial reason: {denial_reason}' if denial_reason else ''}
Confidence score: {confidence_display:.2f}
Agent reasoning: {self_reflection}
""".strip()

    system_base = "You are a ShopWave support specialist. Be concise — 2 sentences max."

    advocate_prompt = f"""ADVOCATE role. {context}

Argue FOR {resolution} in 2 sentences. Reference specific facts."""

    skeptic_prompt = f"""SKEPTIC role. {context}

Argue AGAINST {resolution} in 2 sentences. What risk is being missed?"""

    advocate_task = chat_completion(
        messages=[{"role": "user", "content": advocate_prompt}],
        system=system_base,
        max_tokens=120,
        temperature=0.3,
    )
    skeptic_task = chat_completion(
        messages=[{"role": "user", "content": skeptic_prompt}],
        system=system_base,
        max_tokens=120,
        temperature=0.3,
    )

    advocate_arg, skeptic_arg = await asyncio.gather(advocate_task, skeptic_task)

    valid_resolutions = ["APPROVE", "DENY", "ESCALATE"]
    valid_categories = [
        "warranty_claim", "threat_detected", "social_engineering",
        "ambiguous_request", "missing_data", "replacement_needed"
    ]

    judge_prompt = f"""JUDGE role. {context}

Advocate: {advocate_arg}
Skeptic: {skeptic_arg}

Respond EXACTLY:
FINAL_RESOLUTION: [APPROVE|DENY|ESCALATE]
ESCALATION_CATEGORY: [category|none]
REASONING: [1 sentence]"""

    judge_response = await chat_completion(
        messages=[{"role": "user", "content": judge_prompt}],
        system="You are a decisive judge. Follow the exact format.",
        max_tokens=100,
        temperature=0.0,
    )

    # Parse judge response
    final_resolution = resolution  # fallback to original
    final_category = escalation_category
    judge_reasoning = judge_response

    for line in judge_response.split("\n"):
        line = line.strip()
        if line.startswith("FINAL_RESOLUTION:"):
            val = line.split(":", 1)[1].strip().upper()
            if val in valid_resolutions:
                final_resolution = val
        elif line.startswith("ESCALATION_CATEGORY:"):
            val = line.split(":", 1)[1].strip().lower()
            if val in valid_categories:
                final_category = val
            elif val == "none":
                final_category = None
        elif line.startswith("REASONING:"):
            judge_reasoning = line.split(":", 1)[1].strip()

    debate_transcript = [
        {"role": "advocate", "argument": advocate_arg.strip()},
        {"role": "skeptic", "argument": skeptic_arg.strip()},
        {"role": "judge", "argument": judge_reasoning.strip()},
    ]

    return {
        "final_resolution": final_resolution,
        "final_category": final_category,
        "debate_transcript": debate_transcript,
        "judge_reasoning": judge_reasoning.strip(),
    }
