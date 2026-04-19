"""
main.py — Entry point for the ShopWave Support Resolution Agent.

Loads all 20 tickets, builds the LangGraph agent graph, and processes
all tickets concurrently using asyncio.gather(). Writes audit_log.json
and trace_log.jsonl on completion.

Usage:
    python main.py

Environment:
    ANTHROPIC_API_KEY — required for LLM-backed nodes (not used in mock mode)
"""

from __future__ import annotations

import asyncio
import datetime
import json
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
load_dotenv()  # loads ANTHROPIC_API_KEY and XAI_API_KEY from .env

from agent.graph import build_graph, set_runtime
from agent.session_memory import SessionMemory
from agent.state import initial_state
from utils.logger import TraceLogger

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_BASE_DIR = Path(__file__).parent
_DATA_DIR = _BASE_DIR / "data"

# Write output to /app/output when running in Docker (volume-mounted),
# otherwise write alongside main.py for local runs.
_OUTPUT_DIR = Path("/app/output") if Path("/app/output").exists() else _BASE_DIR
_AUDIT_LOG_PATH = _OUTPUT_DIR / "audit_log.json"
_TRACE_LOG_PATH = _OUTPUT_DIR / "trace_log.jsonl"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_json(path: Path) -> Any:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _write_json(path: Path, data: Any) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, default=str)


# ---------------------------------------------------------------------------
# process_ticket coroutine
# ---------------------------------------------------------------------------

async def process_ticket(
    ticket: dict,
    graph,
    session_memory: SessionMemory,
    trace_logger: TraceLogger,
) -> dict:
    """
    Process a single ticket through the LangGraph agent graph.

    Returns an audit record dict. On unhandled exception, returns an error
    audit record with processing_error set and resolution=None.

    Requirements: 1.1, 1.3
    """
    ticket_id = ticket.get("ticket_id", "unknown")
    try:
        state = initial_state(ticket)
        config = {"configurable": {"thread_id": ticket_id}}

        # Run the graph to completion
        final_state = await graph.ainvoke(state, config=config)

        # Build audit record from final state
        # (write_audit_node also appends to results, but we return here for
        #  the gather() aggregation path)
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
        return audit_record

    except Exception as exc:  # noqa: BLE001
        # Per-ticket fault isolation — record error, don't propagate
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
# main coroutine
# ---------------------------------------------------------------------------

async def main() -> dict:
    """
    Load tickets, build graph, process all 20 tickets concurrently,
    write audit_log.json and return the audit log dict.

    Requirements: 1.1, 1.2, 1.3, 9.1, 9.5
    """
    # Load tickets
    tickets = _load_json(_DATA_DIR / "tickets.json")
    print(f"Loaded {len(tickets)} tickets.")

    # Clear previous output files
    if _TRACE_LOG_PATH.exists():
        try:
            _TRACE_LOG_PATH.unlink()
        except PermissionError:
            pass  # File in use — TraceLogger will append to it

    # Build shared runtime objects
    session_memory = SessionMemory()
    trace_logger = TraceLogger(str(_TRACE_LOG_PATH))
    results: list = []

    # Build graph and inject runtime
    graph = build_graph(demo_mode=True)
    set_runtime(session_memory, trace_logger, results)

    # Process all tickets concurrently
    import time as _time
    start_time = _time.monotonic()
    raw_results = await asyncio.gather(
        *[process_ticket(t, graph, session_memory, trace_logger) for t in tickets],
        return_exceptions=True,
    )
    elapsed_ms = (_time.monotonic() - start_time) * 1000

    # Normalise results — convert any top-level Exception to error record
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

    # Count outcomes
    resolved = sum(1 for r in audit_records if r.get("resolution") in ("APPROVE", "DENY") and not r.get("processing_error"))
    escalated = sum(1 for r in audit_records if r.get("resolution") == "ESCALATE" and not r.get("processing_error"))
    errors = sum(1 for r in audit_records if r.get("processing_error"))

    # Build audit log
    audit_log = {
        "execution_metadata": {
            "run_id": f"run_{datetime.datetime.now(datetime.timezone.utc).isoformat()}",
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "total_tickets": len(tickets),
            "tickets_processed": len(audit_records),
            "tickets_resolved": resolved,
            "tickets_escalated": escalated,
            "tickets_errored": errors,
            "execution_time_ms": round(elapsed_ms, 2),
        },
        "ticket_audit": audit_records,
    }

    # Write audit log
    _write_json(_AUDIT_LOG_PATH, audit_log)
    trace_logger.close()

    # Run self-improvement loop — agent critiques its own decisions
    learnings_path = _OUTPUT_DIR / "AGENT_LEARNINGS.md"
    try:
        from agent.self_improvement import generate_learnings
        print("\nRunning self-improvement analysis...")
        await generate_learnings(audit_records, output_path=learnings_path)
        print(f"   AGENT_LEARNINGS.md -> {learnings_path}")
    except Exception as e:
        print(f"   Self-improvement analysis failed: {e}")

    print(f"\nProcessed {len(audit_records)} tickets in {elapsed_ms:.0f}ms")
    print(f"   Resolved: {resolved} | Escalated: {escalated} | Errors: {errors}")
    print(f"   audit_log.json -> {_AUDIT_LOG_PATH}")
    print(f"   trace_log.jsonl -> {_TRACE_LOG_PATH}")

    return audit_log


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    audit_log = asyncio.run(main())
