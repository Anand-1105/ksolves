"""
agent/self_improvement.py — Agent Self-Improvement Loop

After processing all 20 tickets, this module runs a second LLM pass that:
1. Reads the audit_log.json
2. Identifies patterns in decisions (over-escalation, borderline confidence, etc.)
3. Proposes updated thresholds and new keyword rules
4. Writes AGENT_LEARNINGS.md with specific, actionable recommendations

This is an agent that critiques its own decisions and improves its own rules.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Analytics — pure Python, no LLM needed for data extraction
# ---------------------------------------------------------------------------

def analyse_audit_log(audit_records: list[dict]) -> dict:
    """
    Extract patterns from audit records without LLM.
    Returns a structured analysis dict.
    """
    total = len(audit_records)
    if total == 0:
        return {}

    resolutions = Counter(r.get("resolution") for r in audit_records)
    escalation_categories = Counter(
        r.get("escalation_category")
        for r in audit_records
        if r.get("resolution") == "ESCALATE" and r.get("escalation_category")
    )

    # Confidence score distribution
    scores = [r.get("confidence_score") for r in audit_records if r.get("confidence_score") is not None]
    borderline = [s for s in scores if s is not None and 0.70 <= s < 0.80]
    low_confidence = [s for s in scores if s is not None and s < 0.75]

    # Tickets that were escalated as ambiguous_request (potential over-escalation)
    ambiguous_escalations = [
        r for r in audit_records
        if r.get("escalation_category") == "ambiguous_request"
    ]

    # Tickets with replan attempts
    replanned = [r for r in audit_records if r.get("replan_attempts")]

    # Tool call chain lengths
    chain_lengths = [len(r.get("tool_calls") or []) for r in audit_records]
    avg_chain = sum(chain_lengths) / len(chain_lengths) if chain_lengths else 0

    # Factor breakdown for low-confidence tickets
    factor_issues: dict[str, list[float]] = defaultdict(list)
    for r in audit_records:
        factors = r.get("confidence_factors") or {}
        score = r.get("confidence_score")
        if score is not None and score < 0.80:
            for k, v in factors.items():
                if v is not None:
                    factor_issues[k].append(v)

    avg_factors_low = {
        k: round(sum(v) / len(v), 3) for k, v in factor_issues.items() if v
    }

    # HITL checkpoints triggered
    hitl_triggered = [
        r for r in audit_records
        if r.get("checkpoint_events")
    ]

    return {
        "total_tickets": total,
        "resolutions": dict(resolutions),
        "escalation_categories": dict(escalation_categories),
        "confidence": {
            "scores": scores,
            "avg": round(sum(scores) / len(scores), 3) if scores else None,
            "min": round(min(scores), 3) if scores else None,
            "max": round(max(scores), 3) if scores else None,
            "borderline_count": len(borderline),
            "low_confidence_count": len(low_confidence),
        },
        "ambiguous_escalations": len(ambiguous_escalations),
        "ambiguous_ticket_ids": [r.get("ticket_id") for r in ambiguous_escalations],
        "replanned_count": len(replanned),
        "avg_tool_chain_length": round(avg_chain, 1),
        "hitl_triggered_count": len(hitl_triggered),
        "avg_factors_for_low_confidence": avg_factors_low,
        # Sentiment distribution
        "sentiment_distribution": dict(Counter(
            (r.get("sentiment") or {}).get("primary_emotion", "unknown")
            for r in audit_records
        )),
        "churn_risk_distribution": dict(Counter(
            (r.get("sentiment") or {}).get("churn_risk", "unknown")
            for r in audit_records
        )),
    }


# ---------------------------------------------------------------------------
# LLM-powered self-critique and recommendations
# ---------------------------------------------------------------------------

async def generate_learnings(
    audit_records: list[dict],
    output_path: str | Path = "AGENT_LEARNINGS.md",
) -> str:
    """
    Run the self-improvement loop:
    1. Analyse audit records
    2. Ask LLM to critique decisions and propose improvements
    3. Write AGENT_LEARNINGS.md
    Returns the markdown content.
    """
    from agent.llm_client import chat_completion

    analysis = analyse_audit_log(audit_records)
    if not analysis:
        return "No audit records to analyse."

    # Build a compact summary of decisions for the LLM
    decision_summaries = []
    for r in audit_records:
        # Extract issue_type from the ticket description in tool_calls or from denial_reason
        # The ticket itself isn't stored in audit records, so we infer from available fields
        summary = {
            "ticket_id": r.get("ticket_id"),
            "resolution": r.get("resolution"),
            "escalation_category": r.get("escalation_category"),
            "confidence_score": r.get("confidence_score"),
            "confidence_factors": r.get("confidence_factors"),
            "self_reflection_note": r.get("self_reflection_note"),
            "replan_attempts": len(r.get("replan_attempts") or []),
            "denial_reason": r.get("denial_reason"),
            "tool_call_count": len(r.get("tool_calls") or []),
        }
        decision_summaries.append(summary)

    prompt = f"""You are a senior AI systems engineer reviewing an autonomous support agent's performance.

## Run Summary ({analysis['total_tickets']} tickets)
- APPROVE: {analysis['resolutions'].get('APPROVE', 0)}, DENY: {analysis['resolutions'].get('DENY', 0)}, ESCALATE: {analysis['resolutions'].get('ESCALATE', 0)}
- Avg confidence: {analysis['confidence']['avg']}, Min: {analysis['confidence']['min']}, Borderline (0.70-0.80): {analysis['confidence']['borderline_count']}
- Ambiguous escalations: {analysis['ambiguous_escalations']} tickets {analysis['ambiguous_ticket_ids']}
- Replanning triggered: {analysis['replanned_count']} tickets
- HITL checkpoints: {analysis['hitl_triggered_count']}
- Avg tool chain: {analysis['avg_tool_chain_length']} calls
- Escalation breakdown: {json.dumps(analysis['escalation_categories'])}
- Low-confidence factor averages: {json.dumps(analysis['avg_factors_for_low_confidence'])}

Provide a concise self-improvement report with:
1. **What went well** (2-3 bullet points)
2. **Patterns of concern** (2-3 bullet points with ticket IDs)
3. **Top 3 actionable recommendations** (specific threshold/keyword changes)
4. **Suggested confidence threshold** (currently 0.75)

Be specific and data-driven. Keep total response under 400 words."""

    llm_analysis = await chat_completion(
        messages=[{"role": "user", "content": prompt}],
        system="You are a precise, data-driven AI systems engineer. Be specific and concise.",
        max_tokens=600,
        temperature=0.1,
    )

    # Build the full markdown document
    markdown = f"""# Agent Self-Improvement Report

*Generated automatically after processing {analysis['total_tickets']} tickets.*

---

## Run Statistics

| Metric | Value |
|--------|-------|
| Total tickets | {analysis['total_tickets']} |
| APPROVE | {analysis['resolutions'].get('APPROVE', 0)} |
| DENY | {analysis['resolutions'].get('DENY', 0)} |
| ESCALATE | {analysis['resolutions'].get('ESCALATE', 0)} |
| Avg confidence score | {analysis['confidence']['avg']} |
| Borderline decisions (0.70–0.80) | {analysis['confidence']['borderline_count']} |
| Replanning triggered | {analysis['replanned_count']} |
| HITL checkpoints | {analysis['hitl_triggered_count']} |

## Escalation Breakdown

{chr(10).join(f"- **{k}**: {v}" for k, v in analysis['escalation_categories'].items())}

---

## LLM Self-Critique & Recommendations

{llm_analysis}

---

*This report was generated by the agent analysing its own audit log. Implement the recommendations above to improve future runs.*
"""

    output_path = Path(output_path)
    output_path.write_text(markdown, encoding="utf-8")

    # -----------------------------------------------------------------------
    # Persist learnings to learned_config.json (closes the learning loop)
    # -----------------------------------------------------------------------
    try:
        from agent.learned_config import load_config, save_config, record_run_stats

        config = load_config()

        # Record run statistics for trend detection
        run_stats = {
            "total_tickets": analysis["total_tickets"],
            "resolutions": analysis["resolutions"],
            "avg_confidence": analysis["confidence"]["avg"],
            "borderline_count": analysis["confidence"]["borderline_count"],
            "sentiment_distribution": analysis.get("sentiment_distribution", {}),
            "churn_risk_distribution": analysis.get("churn_risk_distribution", {}),
        }
        config = record_run_stats(config, run_stats)

        # Auto-tune confidence threshold based on borderline count
        # If too many borderline decisions, the threshold may be too aggressive
        if analysis["confidence"]["borderline_count"] >= 3 and analysis["confidence"]["avg"]:
            avg = analysis["confidence"]["avg"]
            if avg >= 0.78:
                # Scores are generally high — safe to slightly lower threshold
                config["confidence_threshold"] = max(0.70, config.get("confidence_threshold", 0.75) - 0.01)

        save_config(config)
    except Exception:
        pass  # Config persistence is best-effort

    return markdown
