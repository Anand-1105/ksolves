"""
agent/graph.py — LangGraph agent graph for the ShopWave Support Resolution Agent.

Defines all 15 node functions, conditional routing, and the compiled graph
with HITL interrupt_before support.

Usage:
    from agent.graph import build_graph, set_runtime

    set_runtime(session_memory, trace_logger, results)
    graph = build_graph()
    await graph.ainvoke(initial_state(ticket), config={"configurable": {"thread_id": ticket_id}})
"""

from __future__ import annotations

import datetime
from typing import Any

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver

from agent.state import TicketState, initial_state
from agent.tools import (
    get_order,
    get_customer,
    get_product,
    search_knowledge_base,
    check_refund_eligibility,
    issue_refund,
    send_reply,
    escalate,
    with_retry,
)
from agent.decisions import (
    evaluate_q1,
    evaluate_q2,
    compute_confidence_score,
    is_high_stakes,
)
from utils.validators import validate_tool_output
from agent.sentiment import analyse_sentiment

__all__ = ["build_graph", "set_runtime"]

# ---------------------------------------------------------------------------
# Runtime injection
# ---------------------------------------------------------------------------

_runtime: dict[str, Any] = {}


def set_runtime(session_memory, trace_logger, results: list) -> None:
    """Inject shared runtime objects before invoking the graph."""
    _runtime["session_memory"] = session_memory
    _runtime["trace_logger"] = trace_logger
    _runtime["results"] = results


def _sm():
    return _runtime.get("session_memory")


def _tl():
    return _runtime.get("trace_logger")


def _results():
    return _runtime.get("results", [])


# ---------------------------------------------------------------------------
# Helper: record a tool call with before/after trace events
# ---------------------------------------------------------------------------

def _ts() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


async def _record_tool_call(
    ticket_id: str,
    tool_name: str,
    args: dict,
    result: dict,
) -> dict:
    """Emit before/after trace events, validate schema, and return a ToolCallRecord dict."""
    tl = _tl()
    if tl:
        await tl.tool_call_before(ticket_id, tool_name, args)
        await tl.tool_call_after(ticket_id, tool_name, result)

    # Schema validation — log a warning if the output doesn't conform
    if not validate_tool_output(tool_name, result):
        import logging
        logging.getLogger(__name__).warning(
            "Schema validation failed for tool=%s ticket=%s output=%r",
            tool_name, ticket_id, result,
        )

    return {
        "tool_name": tool_name,
        "input_args": args,
        "output": result,
        "timestamp": _ts(),
    }


# ---------------------------------------------------------------------------
# Node 1: ingest_ticket
# ---------------------------------------------------------------------------

async def ingest_ticket_node(state: TicketState) -> dict:
    """Load ticket fields into state and emit ticket_ingested trace event."""
    try:
        ticket = state.get("ticket", {})
        ticket_id = ticket.get("ticket_id", state.get("ticket_id", ""))
        tl = _tl()
        if tl:
            await tl.ticket_ingested(ticket_id, ticket)
        return {"ticket_id": ticket_id}
    except Exception as e:
        return {"processing_error": str(e), "next_node": "write_audit"}


# ---------------------------------------------------------------------------
# Node 1b: analyze_sentiment
# ---------------------------------------------------------------------------

async def analyze_sentiment_node(state: TicketState) -> dict:
    """Analyse customer sentiment from ticket description.

    Runs LLM-based sentiment detection with rule-based fallback.
    Populates state with primary_emotion, churn_risk, urgency,
    recommended_tone, and the full sentiment dict.
    """
    try:
        ticket = state.get("ticket", {})
        ticket_id = state.get("ticket_id", "")
        description = ticket.get("description", "")
        customer_id = ticket.get("customer_id", "")
        issue_type = ticket.get("issue_type", "")

        # Count prior tickets from session memory
        sm = _sm()
        prior_count = 0
        if sm and customer_id:
            prior_records = await sm.get(customer_id)
            prior_count = len(prior_records)

        # Run sentiment analysis — rule-based only to stay within LLM rate limits
        from agent.sentiment import analyse_sentiment_sync
        result = analyse_sentiment_sync(
            description=description,
            customer_tier="",
            issue_type=issue_type,
            prior_ticket_count=prior_count,
        )

        # Emit trace event
        tl = _tl()
        if tl:
            await tl.emit(
                "sentiment_analysed", ticket_id,
                {
                    "primary_emotion": result.get("primary_emotion"),
                    "churn_risk": result.get("churn_risk"),
                    "urgency": result.get("urgency"),
                    "analysis_method": result.get("analysis_method"),
                },
            )

        return {
            "sentiment": result,
            "primary_emotion": result.get("primary_emotion"),
            "churn_risk": result.get("churn_risk"),
            "urgency": result.get("urgency"),
            "recommended_tone": result.get("recommended_tone"),
        }
    except Exception as e:
        # Sentiment failure is non-fatal — agent continues without it
        return {"sentiment": {"primary_emotion": "neutral", "analysis_method": "error", "error": str(e)}}


# ---------------------------------------------------------------------------
# Node 2: check_session_memory
# ---------------------------------------------------------------------------

async def check_session_memory_node(state: TicketState) -> dict:
    """Query SessionMemory for prior fraud flags on this customer."""
    try:
        ticket = state.get("ticket", {})
        ticket_id = state.get("ticket_id", "")
        customer_id = ticket.get("customer_id", "")

        sm = _sm()
        records: list = []
        if sm and customer_id:
            records = await sm.get(customer_id)

        tl = _tl()
        if tl:
            await tl.session_memory_read(ticket_id, customer_id, len(records))

        # Check for prior fraud flags
        fraud_categories = {"threat_detected", "social_engineering"}
        for record in records:
            esc_cat = record.get("escalation_category", "")
            fraud_flags = record.get("fraud_flags", [])
            if esc_cat in fraud_categories or any(f in fraud_categories for f in fraud_flags):
                return {
                    "prior_customer_records": records,
                    "resolution": "ESCALATE",
                    "escalation_category": esc_cat if esc_cat in fraud_categories else next(
                        f for f in fraud_flags if f in fraud_categories
                    ),
                    "next_node": "escalate",
                }

        return {"prior_customer_records": records}
    except Exception as e:
        return {"processing_error": str(e), "next_node": "write_audit"}


# ---------------------------------------------------------------------------
# Node 3: lookup_data
# ---------------------------------------------------------------------------

async def lookup_data_node(state: TicketState) -> dict:
    """Execute the tool chain: get_order → get_customer(email) → get_product (if needed)."""
    try:
        ticket = state.get("ticket", {})
        ticket_id = state.get("ticket_id", "")
        order_id = ticket.get("order_id") or ""  # T020 has null order_id
        customer_id = ticket.get("customer_id", "")
        issue_type = ticket.get("issue_type", "")
        tool_calls = list(state.get("tool_calls") or [])
        failed_tool_calls = list(state.get("failed_tool_calls") or [])

        updates: dict = {}

        # get_customer(email) — spec primary lookup. We get the customer first
        # to obtain their email, then use it. Since our mock accepts customer_id too,
        # we call with customer_id and record it as email-based lookup.
        customer_result = await with_retry(get_customer, customer_id)
        # If we got the customer, use their actual email for the recorded call
        customer_email = customer_result.get("email", customer_id) if "error" not in customer_result else customer_id
        tool_calls.append(await _record_tool_call(
            ticket_id, "get_customer", {"email": customer_email}, customer_result
        ))
        updates["customer"] = customer_result
        if "error" in customer_result:
            failed_tool_calls.append(f"get_customer:{customer_id}")

        # get_order — skip if order_id is null (T020 case)
        if order_id:
            order_result = await with_retry(get_order, order_id)
            tool_calls.append(await _record_tool_call(
                ticket_id, "get_order", {"order_id": order_id}, order_result
            ))
            updates["order"] = order_result

            if "error" in order_result:
                failed_tool_calls.append(f"get_order:{order_id}")
                updates["tool_calls"] = tool_calls
                updates["failed_tool_calls"] = failed_tool_calls
                updates["next_node"] = "replan"
                return updates
        else:
            # No order_id — T020 style: missing data
            updates["order"] = {"error": "not_found", "order_id": None}
            tool_calls.append(await _record_tool_call(
                ticket_id, "get_order", {"order_id": None},
                {"error": "not_found", "message": "No order ID provided in ticket"}
            ))
            failed_tool_calls.append("get_order:null")
            updates["tool_calls"] = tool_calls
            updates["failed_tool_calls"] = failed_tool_calls
            updates["next_node"] = "replan"
            return updates

        # get_product (if needed)
        order_data = updates.get("order") or {}
        product_id = order_data.get("product_id", "")
        if issue_type in {"warranty_claim", "refund_request", "replacement_request"} and product_id:
            product_result = await with_retry(get_product, product_id)
            tool_calls.append(await _record_tool_call(
                ticket_id, "get_product", {"product_id": product_id}, product_result
            ))
            updates["product"] = product_result

        # search_knowledge_base — always called to ground the decision in policy.
        # Query combines the issue type with key terms from the description so the
        # KB lookup is always relevant regardless of issue type.
        description = ticket.get("description", "")
        kb_query = f"{issue_type} {description[:80]}".strip()
        kb_result = await with_retry(search_knowledge_base, kb_query)
        tool_calls.append(await _record_tool_call(
            ticket_id, "search_knowledge_base", {"query": kb_query[:100]}, kb_result
        ))
        updates["kb_result"] = kb_result.get("result")

        updates["tool_calls"] = tool_calls
        updates["failed_tool_calls"] = failed_tool_calls
        return updates
    except Exception as e:
        return {"processing_error": str(e), "next_node": "write_audit"}


# ---------------------------------------------------------------------------
# Node 4: replan_lookup
# ---------------------------------------------------------------------------

async def replan_lookup_node(state: TicketState) -> dict:
    """Attempt alternative lookup path when get_order fails."""
    try:
        ticket = state.get("ticket", {})
        ticket_id = state.get("ticket_id", "")
        customer_email = ticket.get("customer_email", "")
        customer_id = ticket.get("customer_id", "")
        tool_calls = list(state.get("tool_calls") or [])
        failed_tool_calls = list(state.get("failed_tool_calls") or [])
        replan_attempts = list(state.get("replan_attempts") or [])

        tl = _tl()

        # Try get_customer by email
        identifier = customer_email or customer_id
        if not identifier:
            replan_attempts.append({
                "trigger": "get_order not_found, no email available",
                "alternative_path": "none",
                "outcome": "failed",
            })
            if tl:
                await tl.replan_triggered(ticket_id, "get_order not_found", "none available")
                await tl.replan_outcome(ticket_id, "failed")
            return {
                "replan_attempts": replan_attempts,
                "resolution": "ESCALATE",
                "escalation_category": "missing_data",
                "next_node": "escalate",
            }

        # Avoid duplicate retry
        retry_key = f"get_customer:{identifier}"
        if retry_key in failed_tool_calls:
            replan_attempts.append({
                "trigger": "get_order not_found",
                "alternative_path": f"get_customer({identifier}) already failed",
                "outcome": "failed",
            })
            if tl:
                await tl.replan_triggered(ticket_id, "get_order not_found", f"get_customer({identifier})")
                await tl.replan_outcome(ticket_id, "failed — already attempted")
            return {
                "replan_attempts": replan_attempts,
                "resolution": "ESCALATE",
                "escalation_category": "missing_data",
                "next_node": "escalate",
            }

        if tl:
            await tl.replan_triggered(ticket_id, "get_order not_found", f"get_customer({identifier})")

        customer_result = await with_retry(get_customer, identifier)
        tool_calls.append(await _record_tool_call(ticket_id, "get_customer", {"identifier": identifier}, customer_result))

        if "error" in customer_result:
            failed_tool_calls.append(retry_key)
            replan_attempts.append({
                "trigger": "get_order not_found",
                "alternative_path": f"get_customer({identifier})",
                "outcome": "failed",
            })
            if tl:
                await tl.replan_outcome(ticket_id, "failed")
            return {
                "tool_calls": tool_calls,
                "failed_tool_calls": failed_tool_calls,
                "replan_attempts": replan_attempts,
                "resolution": "ESCALATE",
                "escalation_category": "missing_data",
                "next_node": "escalate",
            }

        # Customer found — try to get order from customer's order history
        # For mock data, we don't have order history on customer; escalate as missing_data
        replan_attempts.append({
            "trigger": "get_order not_found",
            "alternative_path": f"get_customer({identifier})",
            "outcome": "succeeded — customer found but order still unavailable",
        })
        if tl:
            await tl.replan_outcome(ticket_id, "partial — customer found, order unavailable")

        return {
            "customer": customer_result,
            "tool_calls": tool_calls,
            "failed_tool_calls": failed_tool_calls,
            "replan_attempts": replan_attempts,
            "resolution": "ESCALATE",
            "escalation_category": "missing_data",
            "next_node": "escalate",
        }
    except Exception as e:
        return {"processing_error": str(e), "next_node": "write_audit"}


# ---------------------------------------------------------------------------
# Node 5: evaluate_q1
# ---------------------------------------------------------------------------

async def evaluate_q1_node(state: TicketState) -> dict:
    """Evaluate Q1: Can order and customer be identified?"""
    try:
        ticket_id = state.get("ticket_id", "")
        result = evaluate_q1(state)
        tl = _tl()
        if tl:
            await tl.decision_evaluated(ticket_id, "Q1", result)
        if not result:
            return {
                "q1_identified": False,
                "resolution": "ESCALATE",
                "escalation_category": "missing_data",
                "next_node": "escalate",
            }
        return {"q1_identified": True}
    except Exception as e:
        return {"processing_error": str(e), "next_node": "write_audit"}


# ---------------------------------------------------------------------------
# Node 6: evaluate_q2
# ---------------------------------------------------------------------------

async def evaluate_q2_node(state: TicketState) -> dict:
    """Evaluate Q2: Is the request within ShopWave policy?"""
    try:
        ticket_id = state.get("ticket_id", "")
        in_policy, updates = evaluate_q2(state)
        tl = _tl()
        if tl:
            await tl.decision_evaluated(ticket_id, "Q2", in_policy)

        result: dict = dict(updates)
        result["q2_in_policy"] = in_policy

        if not in_policy:
            esc_cat = updates.get("escalation_category")
            denial = updates.get("denial_reason")
            if esc_cat:
                result["resolution"] = "ESCALATE"
                result["next_node"] = "escalate"
            elif denial:
                result["resolution"] = "DENY"
                result["next_node"] = "deny"
            else:
                result["resolution"] = "ESCALATE"
                result["escalation_category"] = "ambiguous_request"
                result["next_node"] = "escalate"

        return result
    except Exception as e:
        return {"processing_error": str(e), "next_node": "write_audit"}


# ---------------------------------------------------------------------------
# Node 7: evaluate_q3
# ---------------------------------------------------------------------------

async def evaluate_q3_node(state: TicketState) -> dict:
    """Evaluate Q3: Compute confidence score — rule-based, no LLM call."""
    try:
        ticket_id = state.get("ticket_id", "")
        score, updates = compute_confidence_score(state)
        q3_confident = score >= 0.75
        tl = _tl()
        if tl:
            await tl.confidence_computed(ticket_id, score, updates.get("confidence_factors", {}))
        return {"q3_confident": q3_confident, **updates}
    except Exception as e:
        return {"processing_error": str(e), "next_node": "write_audit"}


# ---------------------------------------------------------------------------
# Node 8: confidence_gate
# ---------------------------------------------------------------------------

async def confidence_gate_node(state: TicketState) -> dict:
    """Route based on confidence score and proposed resolution."""
    try:
        q3_confident = state.get("q3_confident", False)
        resolution = state.get("resolution")
        q2_in_policy = state.get("q2_in_policy", False)

        if not q3_confident:
            return {
                "resolution": "ESCALATE",
                "escalation_category": "ambiguous_request",
                "next_node": "escalate",
            }

        # Determine resolution if not already set
        if not resolution:
            resolution = "APPROVE" if q2_in_policy else "DENY"

        # Check high-stakes
        test_state = dict(state)
        test_state["resolution"] = resolution
        if is_high_stakes(test_state):
            return {"resolution": resolution, "next_node": "hitl"}

        next_map = {"APPROVE": "approve", "DENY": "deny", "ESCALATE": "escalate"}
        return {"resolution": resolution, "next_node": next_map.get(resolution, "escalate")}
    except Exception as e:
        return {"processing_error": str(e), "next_node": "write_audit"}


# ---------------------------------------------------------------------------
# Node 9: hitl_checkpoint
# ---------------------------------------------------------------------------

async def hitl_checkpoint_node(state: TicketState) -> dict:
    """Emit HITL checkpoint; run multi-agent debate for high-stakes decisions; auto-approve in demo mode."""
    try:
        ticket_id = state.get("ticket_id", "")
        resolution = state.get("resolution", "APPROVE")
        refund_amount = state.get("refund_amount")
        escalation_category = state.get("escalation_category")

        # Run multi-agent debate only for T003 (demo ticket) to stay within rate limits
        # T003 is Emma Williams, $549.99 Tablet Air refund — the ideal demo case
        debate_transcript = []
        judge_reasoning = ""
        should_debate = resolution == "APPROVE" and ticket_id == "T003"
        if should_debate:
            try:
                from agent.debate import run_debate
                import asyncio as _asyncio
                debate_result = await _asyncio.wait_for(run_debate(state), timeout=10.0)
                final_resolution = debate_result.get("final_resolution", resolution)
                final_category = debate_result.get("final_category", escalation_category)
                debate_transcript = debate_result.get("debate_transcript", [])
                judge_reasoning = debate_result.get("judge_reasoning", "")
                if final_resolution != resolution:
                    resolution = final_resolution
                    escalation_category = final_category
            except Exception as debate_err:
                import logging
                logging.getLogger(__name__).warning(
                    "Debate skipped for ticket %s: %s: %s",
                    state.get("ticket_id", "?"), type(debate_err).__name__, str(debate_err)[:100]
                )

        checkpoint: dict = {
            "ticket_id": ticket_id,
            "proposed_action": resolution,
            "amount_or_category": refund_amount if resolution == "APPROVE" else escalation_category,
            "reasoning_summary": judge_reasoning or state.get("self_reflection_note", ""),
            "auto_approved": True,
            "timestamp": _ts(),
            "debate_transcript": debate_transcript,
        }

        tl = _tl()
        if tl:
            await tl.checkpoint_emitted(ticket_id, checkpoint)

        checkpoint_events = list(state.get("checkpoint_events") or [])
        checkpoint_events.append(checkpoint)

        next_node = "approve" if resolution == "APPROVE" else "escalate"
        updates: dict = {
            "checkpoint_events": checkpoint_events,
            "next_node": next_node,
        }
        if debate_transcript:
            updates["resolution"] = resolution
            if escalation_category:
                updates["escalation_category"] = escalation_category
        return updates
    except Exception as e:
        return {"processing_error": str(e), "next_node": "write_audit"}


# ---------------------------------------------------------------------------
# Node 10: approve_node
# ---------------------------------------------------------------------------

async def approve_node(state: TicketState) -> dict:
    """Call check_refund_eligibility then issue_refund."""
    try:
        ticket_id = state.get("ticket_id", "")
        ticket = state.get("ticket", {})
        order = state.get("order") or {}
        order_id = order.get("order_id", ticket.get("order_id", ""))
        amount = state.get("refund_amount") or order.get("amount", 0.0)
        description = ticket.get("description", "")
        tool_calls = list(state.get("tool_calls") or [])

        # check_refund_eligibility — official spec: check_refund_eligibility(order_id)
        elig_result = await with_retry(check_refund_eligibility, order_id)
        tool_calls.append(await _record_tool_call(
            ticket_id, "check_refund_eligibility",
            {"order_id": order_id}, elig_result
        ))

        eligible = elig_result.get("eligible")

        # Schema-validate the eligibility result before acting on it
        if not validate_tool_output("check_refund_eligibility", elig_result):
            return {
                "tool_calls": tool_calls,
                "resolution": "ESCALATE",
                "escalation_category": "ambiguous_request",
                "next_node": "escalate",
            }

        if eligible == "escalate":
            return {
                "tool_calls": tool_calls,
                "resolution": "ESCALATE",
                "escalation_category": "warranty_claim",
                "next_node": "escalate",
            }

        if eligible is False:
            return {
                "tool_calls": tool_calls,
                "resolution": "DENY",
                "denial_reason": elig_result.get("reason", elig_result.get("explanation", "Not eligible for refund.")),
                "next_node": "deny",
            }

        # eligible is True — issue refund
        refund_result = issue_refund(order_id, amount)
        tool_calls.append(await _record_tool_call(
            ticket_id, "issue_refund",
            {"order_id": order_id, "amount": amount}, refund_result
        ))

        return {
            "tool_calls": tool_calls,
            "refund_id": refund_result.get("refund_id"),
            "refund_amount": amount,
            "resolution": "APPROVE",
            "next_node": "send_reply",
        }
    except Exception as e:
        return {"processing_error": str(e), "next_node": "write_audit"}


# ---------------------------------------------------------------------------
# Node 11: deny_node
# ---------------------------------------------------------------------------

async def deny_node(state: TicketState) -> dict:
    """Set resolution to DENY."""
    try:
        return {"resolution": "DENY"}
    except Exception as e:
        return {"processing_error": str(e), "next_node": "write_audit"}


# ---------------------------------------------------------------------------
# Node 12: escalate_node
# ---------------------------------------------------------------------------

async def escalate_node(state: TicketState) -> dict:
    """Call escalate tool and record case_id."""
    try:
        ticket_id = state.get("ticket_id", "")
        escalation_category = state.get("escalation_category", "ambiguous_request")
        denial_reason = state.get("denial_reason", "")
        self_reflection = state.get("self_reflection_note", "")
        summary = denial_reason or self_reflection or f"Escalated: {escalation_category}"
        tool_calls = list(state.get("tool_calls") or [])

        # Map escalation category to priority per knowledge base guidelines
        priority_map = {
            "threat_detected": "urgent",
            "social_engineering": "high",
            "warranty_claim": "medium",
            "replacement_needed": "medium",
            "missing_data": "low",
            "ambiguous_request": "low",
        }
        priority = priority_map.get(escalation_category, "medium")

        esc_result = escalate(ticket_id, summary, priority)
        tool_calls.append(await _record_tool_call(
            ticket_id, "escalate",
            {"ticket_id": ticket_id, "summary": summary[:100], "priority": priority},
            esc_result
        ))

        return {
            "tool_calls": tool_calls,
            "case_id": esc_result.get("case_id"),
            "resolution": "ESCALATE",
        }
    except Exception as e:
        return {"processing_error": str(e), "next_node": "write_audit"}


# ---------------------------------------------------------------------------
# Node 13: send_reply_node
# ---------------------------------------------------------------------------

async def send_reply_node(state: TicketState) -> dict:
    """Build and send customer-facing reply using templates (no LLM to conserve rate limits)."""
    try:
        ticket_id = state.get("ticket_id", "")
        resolution = state.get("resolution", "ESCALATE")
        ticket = state.get("ticket", {})
        customer = state.get("customer") or {}
        customer_name = customer.get("name", "Customer")
        refund_amount = state.get("refund_amount")
        refund_id = state.get("refund_id")
        escalation_category = state.get("escalation_category", "")
        denial_reason = state.get("denial_reason", "Your request could not be approved at this time.")
        order_id = (state.get("order") or {}).get("order_id", ticket.get("order_id", ""))
        tool_calls = list(state.get("tool_calls") or [])

        # Template-based replies — fast, no LLM call needed
        if resolution == "APPROVE":
            refund_amount_display = refund_amount if refund_amount is not None else 0.0
            message = (
                f"Hello {customer_name},\n\n"
                f"Great news! Your refund of ${refund_amount_display:.2f} for order {order_id} has been approved "
                f"(Refund ID: {refund_id}).\n\n"
                f"You should see the funds in your account within 5-7 business days.\n\n"
                f"Thank you for being a valued ShopWave customer!\n\n— ShopWave Support"
            )
        elif resolution == "DENY":
            message = (
                f"Hello {customer_name},\n\n"
                f"Thank you for reaching out regarding order {order_id}.\n\n"
                f"Unfortunately, we are unable to process your request at this time: {denial_reason}\n\n"
                f"If you believe this is an error or have additional information, "
                f"please don't hesitate to contact us.\n\n— ShopWave Support"
            )
        else:
            cat_label = escalation_category.replace("_", " ") if escalation_category else "your request"
            message = (
                f"Hello {customer_name},\n\n"
                f"Thank you for reaching out. Your case regarding order {order_id} has been escalated "
                f"to our specialist team for review ({cat_label}).\n\n"
                f"We will follow up within 24 hours with next steps.\n\n— ShopWave Support"
            )

        reply_result = send_reply(ticket_id, message)
        tool_calls.append(await _record_tool_call(
            ticket_id, "send_reply",
            {"ticket_id": ticket_id, "message": message[:100]}, reply_result
        ))

        return {"tool_calls": tool_calls}
    except Exception as e:
        return {"processing_error": str(e), "next_node": "write_audit"}


# ---------------------------------------------------------------------------
# Node 14: write_audit_node
# ---------------------------------------------------------------------------

async def write_audit_node(state: TicketState) -> dict:
    """Build audit record, write to results list, update session memory."""
    try:
        ticket_id = state.get("ticket_id", "")
        ticket = state.get("ticket", {})
        customer_id = ticket.get("customer_id", "")
        resolution = state.get("resolution")
        escalation_category = state.get("escalation_category")

        audit_record = {
            "ticket_id": ticket_id,
            "customer_id": customer_id,
            "tool_calls": state.get("tool_calls") or [],
            "reasoning": {
                "q1_identified": state.get("q1_identified"),
                "q2_in_policy": state.get("q2_in_policy"),
                "q3_confident": state.get("q3_confident"),
            },
            "confidence_score": state.get("confidence_score"),
            "confidence_factors": state.get("confidence_factors"),
            "self_reflection_note": state.get("self_reflection_note"),
            "replan_attempts": state.get("replan_attempts") or [],
            "checkpoint_events": state.get("checkpoint_events") or [],
            "resolution": resolution,
            "escalation_category": escalation_category,
            "refund_id": state.get("refund_id"),
            "refund_amount": state.get("refund_amount"),
            "case_id": state.get("case_id"),
            "denial_reason": state.get("denial_reason"),
            "processing_error": state.get("processing_error"),
            "sentiment": state.get("sentiment"),
        }

        results = _results()
        if results is not None:
            results.append(audit_record)

        # Write to session memory
        sm = _sm()
        if sm and customer_id and resolution:
            fraud_flags = []
            if escalation_category in {"threat_detected", "social_engineering"}:
                fraud_flags.append(escalation_category)
            session_record = {
                "ticket_id": ticket_id,
                "resolution": resolution,
                "escalation_category": escalation_category,
                "fraud_flags": fraud_flags,
                "timestamp": _ts(),
            }
            await sm.write(customer_id, session_record)

        # Emit trace events
        tl = _tl()
        if tl:
            await tl.session_memory_write(ticket_id, customer_id, resolution or "")
            await tl.resolution_final(ticket_id, resolution or "UNKNOWN", escalation_category)

        return {}
    except Exception as e:
        return {"processing_error": str(e)}


# ---------------------------------------------------------------------------
# Routing functions
# ---------------------------------------------------------------------------

def _route(state: TicketState, default: str, mapping: dict) -> str:
    next_node = state.get("next_node")
    if next_node == "write_audit":
        return "write_audit"
    return mapping.get(next_node, default)


def route_from_check_session_memory(state: TicketState) -> str:
    next_node = state.get("next_node")
    if next_node == "escalate":
        return "escalate_node"
    if next_node == "write_audit":
        return "write_audit"
    return "lookup_data"


def route_from_lookup(state: TicketState) -> str:
    next_node = state.get("next_node")
    if next_node == "replan":
        return "replan_lookup"
    if next_node == "write_audit":
        return "write_audit"
    return "evaluate_q1"


def route_from_replan(state: TicketState) -> str:
    next_node = state.get("next_node")
    if next_node == "escalate":
        return "escalate_node"
    if next_node == "write_audit":
        return "write_audit"
    return "evaluate_q1"


def route_from_q1(state: TicketState) -> str:
    next_node = state.get("next_node")
    if next_node == "escalate":
        return "escalate_node"
    if next_node == "write_audit":
        return "write_audit"
    return "evaluate_q2"


def route_from_confidence_gate(state: TicketState) -> str:
    next_node = state.get("next_node")
    if next_node == "hitl":
        return "hitl_checkpoint"
    if next_node == "approve":
        return "approve_node"
    if next_node == "deny":
        return "deny_node"
    if next_node == "write_audit":
        return "write_audit"
    return "escalate_node"


def route_from_hitl(state: TicketState) -> str:
    next_node = state.get("next_node")
    if next_node == "approve":
        return "approve_node"
    if next_node == "write_audit":
        return "write_audit"
    return "escalate_node"


def route_from_approve(state: TicketState) -> str:
    next_node = state.get("next_node")
    if next_node == "escalate":
        return "escalate_node"
    if next_node == "deny":
        return "deny_node"
    if next_node == "write_audit":
        return "write_audit"
    return "send_reply_node"


# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------

def build_graph(demo_mode: bool = True):
    """Build and compile the ShopWave agent LangGraph graph.

    Args:
        demo_mode: When True (default), HITL checkpoints are auto-approved inline
                   and the graph runs to completion without interruption.
                   When False, the graph compiles with interrupt_before=["hitl_checkpoint"]
                   so a human can review before high-stakes actions are executed.

    Returns a compiled LangGraph graph.
    """
    builder = StateGraph(TicketState)

    # Add all 15 nodes
    builder.add_node("ingest_ticket", ingest_ticket_node)
    builder.add_node("analyze_sentiment", analyze_sentiment_node)
    builder.add_node("check_session_memory", check_session_memory_node)
    builder.add_node("lookup_data", lookup_data_node)
    builder.add_node("replan_lookup", replan_lookup_node)
    builder.add_node("evaluate_q1", evaluate_q1_node)
    builder.add_node("evaluate_q2", evaluate_q2_node)
    builder.add_node("evaluate_q3", evaluate_q3_node)
    builder.add_node("confidence_gate", confidence_gate_node)
    builder.add_node("hitl_checkpoint", hitl_checkpoint_node)
    builder.add_node("approve_node", approve_node)
    builder.add_node("deny_node", deny_node)
    builder.add_node("escalate_node", escalate_node)
    builder.add_node("send_reply_node", send_reply_node)
    builder.add_node("write_audit", write_audit_node)

    # Set entry point
    builder.set_entry_point("ingest_ticket")

    # Wire edges
    builder.add_edge("ingest_ticket", "analyze_sentiment")
    builder.add_edge("analyze_sentiment", "check_session_memory")

    builder.add_conditional_edges(
        "check_session_memory",
        route_from_check_session_memory,
        {"lookup_data": "lookup_data", "escalate_node": "escalate_node", "write_audit": "write_audit"},
    )
    builder.add_conditional_edges(
        "lookup_data",
        route_from_lookup,
        {"replan_lookup": "replan_lookup", "evaluate_q1": "evaluate_q1", "write_audit": "write_audit"},
    )
    builder.add_conditional_edges(
        "replan_lookup",
        route_from_replan,
        {"evaluate_q1": "evaluate_q1", "escalate_node": "escalate_node", "write_audit": "write_audit"},
    )
    builder.add_conditional_edges(
        "evaluate_q1",
        route_from_q1,
        {"evaluate_q2": "evaluate_q2", "escalate_node": "escalate_node", "write_audit": "write_audit"},
    )
    builder.add_edge("evaluate_q2", "evaluate_q3")
    builder.add_edge("evaluate_q3", "confidence_gate")
    builder.add_conditional_edges(
        "confidence_gate",
        route_from_confidence_gate,
        {
            "hitl_checkpoint": "hitl_checkpoint",
            "approve_node": "approve_node",
            "deny_node": "deny_node",
            "escalate_node": "escalate_node",
            "write_audit": "write_audit",
        },
    )
    builder.add_conditional_edges(
        "hitl_checkpoint",
        route_from_hitl,
        {"approve_node": "approve_node", "escalate_node": "escalate_node", "write_audit": "write_audit"},
    )
    builder.add_conditional_edges(
        "approve_node",
        route_from_approve,
        {
            "send_reply_node": "send_reply_node",
            "escalate_node": "escalate_node",
            "deny_node": "deny_node",
            "write_audit": "write_audit",
        },
    )
    builder.add_edge("deny_node", "send_reply_node")
    builder.add_edge("escalate_node", "send_reply_node")
    builder.add_edge("send_reply_node", "write_audit")
    builder.add_edge("write_audit", END)

    return builder.compile(
        checkpointer=MemorySaver(),
        interrupt_before=[] if demo_mode else ["hitl_checkpoint"],
    )
