"""
tests/integration/test_full_run.py — End-to-end integration test.

Runs the complete agent against all 20 tickets and verifies:
- audit_log.json is produced with exactly 20 records
- trace_log.jsonl is produced with valid JSON lines
- No unhandled exceptions propagate

Requirements: 1.1, 1.2, 9.1, 9.5, 17.3, 17.4
"""

from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path

import pytest

from agent.graph import build_graph, set_runtime
from agent.session_memory import SessionMemory
from agent.state import initial_state
from utils.logger import TraceLogger


def _load_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


async def _run_all_tickets(tickets, tmp_dir: Path):
    """Run all tickets through the agent and return (audit_records, trace_path)."""
    trace_path = tmp_dir / "trace_log.jsonl"

    session_memory = SessionMemory()
    trace_logger = TraceLogger(str(trace_path))
    results = []

    graph = build_graph(demo_mode=True)
    set_runtime(session_memory, trace_logger, results)

    async def process_one(ticket):
        ticket_id = ticket.get("ticket_id", "unknown")
        try:
            state = initial_state(ticket)
            config = {"configurable": {"thread_id": ticket_id}}
            final_state = await graph.ainvoke(state, config=config)
            return {
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
                "case_id": final_state.get("case_id"),
                "denial_reason": final_state.get("denial_reason"),
                "processing_error": final_state.get("processing_error"),
            }
        except Exception as exc:
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

    raw = await asyncio.gather(*[process_one(t) for t in tickets], return_exceptions=True)

    audit_records = []
    for ticket, result in zip(tickets, raw):
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

    trace_logger.close()
    return audit_records, trace_path


class TestFullRun:
    @pytest.fixture(scope="class")
    def run_results(self):
        """Run the full agent once and cache results for all tests in this class."""
        data_dir = Path(__file__).parent.parent.parent / "data"
        tickets = _load_json(data_dir / "tickets.json")

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            audit_records, trace_path = asyncio.run(
                _run_all_tickets(tickets, tmp_path)
            )
            # Read trace log before tmp dir is cleaned up
            trace_lines = []
            if trace_path.exists():
                with open(trace_path, encoding="utf-8") as fh:
                    trace_lines = [line.strip() for line in fh if line.strip()]

        return {
            "tickets": tickets,
            "audit_records": audit_records,
            "trace_lines": trace_lines,
        }

    def test_audit_log_has_20_records(self, run_results):
        """audit_log must contain exactly 20 records — one per ticket."""
        assert len(run_results["audit_records"]) == 20, (
            f"Expected 20 audit records, got {len(run_results['audit_records'])}"
        )

    def test_every_ticket_has_an_audit_record(self, run_results):
        """Every ticket_id must appear in the audit records."""
        ticket_ids = {t["ticket_id"] for t in run_results["tickets"]}
        audit_ids = {r["ticket_id"] for r in run_results["audit_records"]}
        assert ticket_ids == audit_ids, (
            f"Missing audit records for tickets: {ticket_ids - audit_ids}"
        )

    def test_no_unhandled_exceptions(self, run_results):
        """No audit record should have a processing_error from an unhandled exception."""
        errors = [
            r for r in run_results["audit_records"]
            if r.get("processing_error")
        ]
        assert not errors, (
            f"Unexpected processing errors in {len(errors)} tickets: "
            f"{[(r['ticket_id'], r['processing_error']) for r in errors]}"
        )

    def test_all_records_have_resolution(self, run_results):
        """Every audit record must have a resolution (APPROVE, DENY, or ESCALATE)."""
        for record in run_results["audit_records"]:
            assert record.get("resolution") in ("APPROVE", "DENY", "ESCALATE"), (
                f"Ticket {record['ticket_id']} has invalid resolution: {record.get('resolution')}"
            )

    def test_all_records_have_minimum_tool_calls(self, run_results):
        """Every resolved ticket must have at least 3 tool calls."""
        for record in run_results["audit_records"]:
            if not record.get("processing_error"):
                assert len(record.get("tool_calls", [])) >= 3, (
                    f"Ticket {record['ticket_id']} has only "
                    f"{len(record.get('tool_calls', []))} tool calls"
                )

    def test_trace_log_is_produced(self, run_results):
        """trace_log.jsonl must be produced with at least one event."""
        assert len(run_results["trace_lines"]) > 0, "trace_log.jsonl must contain trace events"

    def test_trace_log_all_lines_are_valid_json(self, run_results):
        """Every non-empty line in trace_log.jsonl must be valid JSON."""
        for i, line in enumerate(run_results["trace_lines"]):
            try:
                json.loads(line)
            except json.JSONDecodeError as e:
                pytest.fail(f"trace_log.jsonl line {i+1} is not valid JSON: {e}\nLine: {line[:100]}")

    def test_trace_events_have_required_fields(self, run_results):
        """Every trace event must have event_type, ticket_id, timestamp, payload."""
        for i, line in enumerate(run_results["trace_lines"]):
            event = json.loads(line)
            for field in ("event_type", "ticket_id", "timestamp", "payload"):
                assert field in event, (
                    f"trace event at line {i+1} missing field '{field}': {event}"
                )

    def test_audit_log_is_valid_json_serialisable(self, run_results):
        """The full audit log must be JSON-serialisable."""
        audit_log = {
            "execution_metadata": {"total_tickets": 20},
            "ticket_audit": run_results["audit_records"],
        }
        serialised = json.dumps(audit_log, default=str)
        parsed = json.loads(serialised)
        assert len(parsed["ticket_audit"]) == 20

    def test_escalate_resolutions_have_case_id(self, run_results):
        """Every ESCALATE resolution must have a non-empty case_id."""
        for record in run_results["audit_records"]:
            if record.get("resolution") == "ESCALATE" and not record.get("processing_error"):
                assert record.get("case_id"), (
                    f"Ticket {record['ticket_id']} has ESCALATE resolution but no case_id"
                )

    def test_approve_resolutions_have_refund_id(self, run_results):
        """Every APPROVE resolution must have a non-empty refund_id."""
        for record in run_results["audit_records"]:
            if record.get("resolution") == "APPROVE" and not record.get("processing_error"):
                assert record.get("refund_id"), (
                    f"Ticket {record['ticket_id']} has APPROVE resolution but no refund_id"
                )

    def test_confidence_scores_are_in_valid_range(self, run_results):
        """All confidence scores must be in [0.0, 1.0]."""
        for record in run_results["audit_records"]:
            score = record.get("confidence_score")
            if score is not None:
                assert 0.0 <= score <= 1.0, (
                    f"Ticket {record['ticket_id']} has invalid confidence_score: {score}"
                )
