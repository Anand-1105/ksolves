"""
api/runner.py — SSE runner logic for the ShopWave Support Resolution Agent API.

Bridges the LangGraph agent with Server-Sent Events by replacing the file-based
TraceLogger with an SSETraceLogger that puts events into an asyncio.Queue.
"""

from __future__ import annotations

import asyncio
import datetime
import json
import sys
from pathlib import Path
from typing import Any, Optional

# Add the parent directory (shopwave-agent/) to sys.path so we can import agent/
_API_DIR = Path(__file__).parent
_AGENT_ROOT = _API_DIR.parent
if str(_AGENT_ROOT) not in sys.path:
    sys.path.insert(0, str(_AGENT_ROOT))


# ---------------------------------------------------------------------------
# SSETraceLogger — same interface as TraceLogger but emits to a queue
# ---------------------------------------------------------------------------

class SSETraceLogger:
    """
    Drop-in replacement for TraceLogger that puts SSE-formatted events
    into an asyncio.Queue instead of writing to a file.

    Handles multiple concurrent tickets — events are tagged with ticket_id.
    """

    def __init__(self, queue: asyncio.Queue) -> None:
        self._queue = queue
        self._lock = asyncio.Lock()

    def _ts(self) -> str:
        return datetime.datetime.utcnow().isoformat() + "Z"

    async def _put(self, event: dict) -> None:
        async with self._lock:
            await self._queue.put(event)

    # ------------------------------------------------------------------
    # TraceLogger interface
    # ------------------------------------------------------------------

    async def emit(self, event_type: str, ticket_id: str, payload: dict) -> None:
        pass  # handled by specific methods

    async def ticket_ingested(self, ticket_id: str, ticket: dict) -> None:
        pass  # not surfaced as SSE event

    async def tool_call_before(self, ticket_id: str, tool_name: str, args: dict) -> None:
        pass  # combined into tool_call_after

    async def tool_call_after(self, ticket_id: str, tool_name: str, result: dict) -> None:
        await self._put({
            "type": "tool_call",
            "ticket_id": ticket_id,
            "tool_name": tool_name,
            "args": {},
            "result": result,
            "timestamp": self._ts(),
        })

    async def decision_evaluated(self, ticket_id: str, question: str, value: bool) -> None:
        await self._put({
            "type": "decision",
            "ticket_id": ticket_id,
            "question": question,
            "value": value,
        })

    async def confidence_computed(self, ticket_id: str, score: float, factors: dict) -> None:
        await self._put({
            "type": "confidence",
            "ticket_id": ticket_id,
            "score": score,
            "factors": factors,
        })

    async def checkpoint_emitted(self, ticket_id: str, checkpoint: dict) -> None:
        await self._put({
            "type": "checkpoint",
            "ticket_id": ticket_id,
            "proposed_action": checkpoint.get("proposed_action"),
            "auto_approved": checkpoint.get("auto_approved", True),
            "debate_transcript": checkpoint.get("debate_transcript", []),
        })

    async def resolution_final(
        self,
        ticket_id: str,
        resolution: str,
        category: Optional[str] = None,
    ) -> None:
        pass  # handled after graph completion in run_ticket_sse

    async def replan_triggered(
        self, ticket_id: str, trigger: str, alternative_path: str
    ) -> None:
        pass

    async def replan_outcome(self, ticket_id: str, outcome: str) -> None:
        pass

    async def session_memory_read(
        self, ticket_id: str, customer_id: str, records_count: int
    ) -> None:
        pass

    async def session_memory_write(
        self, ticket_id: str, customer_id: str, resolution: str
    ) -> None:
        pass

    def close(self) -> None:
        pass


# ---------------------------------------------------------------------------
# _process_one — run a single ticket with a pre-configured graph
# ---------------------------------------------------------------------------

async def _process_one(
    ticket: dict,
    graph,
    queue: asyncio.Queue,
) -> dict:
    """
    Run one ticket through an already-built graph.
    Emits SSE events to queue. Returns audit record.
    """
    from agent.state import initial_state

    ticket_id = ticket.get("ticket_id", "unknown")

    try:
        state = initial_state(ticket)
        config = {"configurable": {"thread_id": ticket_id}}
        final_state = await graph.ainvoke(state, config=config)

        # Build audit record
        audit_record = {
            "ticket_id": final_state.get("ticket_id", ticket_id),
            "customer_id": ticket.get("customer_id", ""),
            "tool_calls": final_state.get("tool_calls") or [],
            "reasoning": {
                "q1_identified": final_state.get("q1_identified"),
                "q2_in_policy": final_state.get("q2_in_policy"),
                "q3_confident": final_state.get("q3_confident"),
            },
            "confidence_score": final_state.get("confidence_score"),
            "confidence_factors": final_state.get("confidence_factors"),
            "self_reflection_note": final_state.get("self_reflection_note"),
            "replan_attempts": final_state.get("replan_attempts") or [],
            "checkpoint_events": final_state.get("checkpoint_events") or [],
            "resolution": final_state.get("resolution"),
            "escalation_category": final_state.get("escalation_category"),
            "refund_id": final_state.get("refund_id"),
            "refund_amount": final_state.get("refund_amount"),
            "case_id": final_state.get("case_id"),
            "denial_reason": final_state.get("denial_reason"),
            "processing_error": final_state.get("processing_error"),
        }

        # Emit resolution event
        resolution = final_state.get("resolution")
        if resolution:
            await queue.put({
                "type": "resolution",
                "ticket_id": ticket_id,
                "resolution": resolution,
                "category": final_state.get("escalation_category"),
                "refund_id": final_state.get("refund_id"),
                "case_id": final_state.get("case_id"),
            })

        # Emit reply event — extract from last send_reply tool call
        tool_calls = final_state.get("tool_calls") or []
        reply_message = None
        for tc in reversed(tool_calls):
            if tc.get("tool_name") == "send_reply":
                reply_message = tc.get("input_args", {}).get("message")
                if not reply_message:
                    reply_message = tc.get("output", {}).get("message_preview")
                break

        if reply_message:
            await queue.put({
                "type": "reply",
                "ticket_id": ticket_id,
                "message": reply_message,
            })

        await queue.put({"type": "done", "ticket_id": ticket_id})
        return audit_record

    except Exception as exc:
        await queue.put({
            "type": "error",
            "ticket_id": ticket_id,
            "message": str(exc),
        })
        await queue.put({"type": "done", "ticket_id": ticket_id})
        return {
            "ticket_id": ticket_id,
            "customer_id": ticket.get("customer_id", ""),
            "tool_calls": [],
            "reasoning": {"q1_identified": None, "q2_in_policy": None, "q3_confident": None},
            "confidence_score": None,
            "confidence_factors": None,
            "self_reflection_note": None,
            "replan_attempts": [],
            "checkpoint_events": [],
            "resolution": None,
            "escalation_category": None,
            "refund_id": None,
            "case_id": None,
            "denial_reason": None,
            "processing_error": str(exc),
        }


# ---------------------------------------------------------------------------
# run_ticket_sse — public API for single ticket
# ---------------------------------------------------------------------------

async def run_ticket_sse(ticket: dict, queue: asyncio.Queue) -> dict:
    """
    Run one ticket through the LangGraph agent graph.
    Puts SSE events into `queue` as they happen.
    Returns the final audit record dict.
    """
    from agent.graph import build_graph, set_runtime
    from agent.session_memory import SessionMemory

    sse_logger = SSETraceLogger(queue)
    session_memory = SessionMemory()
    results: list = []

    graph = build_graph(demo_mode=True)
    set_runtime(session_memory, sse_logger, results)

    return await _process_one(ticket, graph, queue)


# ---------------------------------------------------------------------------
# run_all_sse — public API for all tickets concurrently
# ---------------------------------------------------------------------------

async def run_all_sse(tickets: list, queue: asyncio.Queue) -> list:
    """
    Run all tickets concurrently.
    Uses a single shared graph + session memory + SSETraceLogger.
    All events are tagged with ticket_id and go to the shared queue.
    Returns list of audit records.
    """
    from agent.graph import build_graph, set_runtime
    from agent.session_memory import SessionMemory

    sse_logger = SSETraceLogger(queue)
    session_memory = SessionMemory()
    results: list = []

    graph = build_graph(demo_mode=True)
    set_runtime(session_memory, sse_logger, results)

    tasks = [_process_one(ticket, graph, queue) for ticket in tickets]
    raw_results = await asyncio.gather(*tasks, return_exceptions=True)

    audit_records = []
    for ticket, result in zip(tickets, raw_results):
        if isinstance(result, Exception):
            audit_records.append({
                "ticket_id": ticket.get("ticket_id", "unknown"),
                "customer_id": ticket.get("customer_id", ""),
                "tool_calls": [],
                "reasoning": {"q1_identified": None, "q2_in_policy": None, "q3_confident": None},
                "confidence_score": None,
                "confidence_factors": None,
                "self_reflection_note": None,
                "replan_attempts": [],
                "checkpoint_events": [],
                "resolution": None,
                "escalation_category": None,
                "refund_id": None,
                "case_id": None,
                "denial_reason": None,
                "processing_error": str(result),
            })
        else:
            audit_records.append(result)

    return audit_records
