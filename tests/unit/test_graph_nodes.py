"""
tests/unit/test_graph_nodes.py — Unit tests for individual graph node functions.

Tests each node function in isolation with mocked runtime (_sm, _tl, _results)
to verify correct state transitions, error handling, and edge cases.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agent.graph import (
    set_runtime,
    ingest_ticket_node,
    check_session_memory_node,
    evaluate_q1_node,
    evaluate_q2_node,
    evaluate_q3_node,
    confidence_gate_node,
    deny_node,
    write_audit_node,
    # Routing functions
    route_from_check_session_memory,
    route_from_lookup,
    route_from_replan,
    route_from_q1,
    route_from_confidence_gate,
    route_from_hitl,
    route_from_approve,
)
from agent.session_memory import SessionMemory


def _run(coro):
    return asyncio.run(coro)


def _setup_runtime(session_memory=None, trace_logger=None, results=None):
    """Set up mocked runtime for graph nodes."""
    sm = session_memory or SessionMemory()
    tl = trace_logger or MagicMock()
    # Make all trace logger methods async
    for method in ["ticket_ingested", "session_memory_read", "session_memory_write",
                    "decision_evaluated", "confidence_computed", "resolution_final",
                    "tool_call_before", "tool_call_after", "checkpoint_emitted",
                    "replan_triggered", "replan_outcome"]:
        setattr(tl, method, AsyncMock())
    res = results if results is not None else []
    set_runtime(sm, tl, res)
    return sm, tl, res


# ===========================================================================
# ingest_ticket_node
# ===========================================================================

class TestIngestTicketNode:
    def test_extracts_ticket_id(self):
        _setup_runtime()
        state = {
            "ticket": {"ticket_id": "T001", "issue_type": "refund_request"},
            "ticket_id": "",
        }
        result = _run(ingest_ticket_node(state))
        assert result["ticket_id"] == "T001"

    def test_handles_missing_ticket_gracefully(self):
        _setup_runtime()
        state = {"ticket": {}, "ticket_id": ""}
        result = _run(ingest_ticket_node(state))
        assert "ticket_id" in result

    def test_error_sets_processing_error(self):
        """If something goes wrong, processing_error is set."""
        # Mock trace logger to raise
        sm, tl, res = _setup_runtime()
        tl.ticket_ingested = AsyncMock(side_effect=Exception("boom"))
        state = {"ticket": {"ticket_id": "T001"}, "ticket_id": ""}
        result = _run(ingest_ticket_node(state))
        assert result.get("processing_error") == "boom"


# ===========================================================================
# check_session_memory_node
# ===========================================================================

class TestCheckSessionMemoryNode:
    def test_no_prior_fraud_returns_records(self):
        sm = SessionMemory()
        _setup_runtime(session_memory=sm)
        state = {"ticket": {"customer_id": "C001"}, "ticket_id": "T001"}
        result = _run(check_session_memory_node(state))
        assert result["prior_customer_records"] == []
        assert "resolution" not in result or result.get("resolution") is None

    def test_prior_fraud_triggers_escalation(self):
        sm = SessionMemory()
        _run(sm.write("C001", {
            "ticket_id": "T000",
            "resolution": "ESCALATE",
            "escalation_category": "threat_detected",
            "fraud_flags": ["threat_detected"],
        }))
        _setup_runtime(session_memory=sm)
        state = {"ticket": {"customer_id": "C001"}, "ticket_id": "T001"}
        result = _run(check_session_memory_node(state))
        assert result["resolution"] == "ESCALATE"
        assert result["escalation_category"] == "threat_detected"
        assert result["next_node"] == "escalate"

    def test_prior_social_engineering_triggers_escalation(self):
        sm = SessionMemory()
        _run(sm.write("C001", {
            "ticket_id": "T000",
            "resolution": "ESCALATE",
            "escalation_category": "social_engineering",
            "fraud_flags": ["social_engineering"],
        }))
        _setup_runtime(session_memory=sm)
        state = {"ticket": {"customer_id": "C001"}, "ticket_id": "T001"}
        result = _run(check_session_memory_node(state))
        assert result["resolution"] == "ESCALATE"

    def test_prior_non_fraud_does_not_escalate(self):
        sm = SessionMemory()
        _run(sm.write("C001", {
            "ticket_id": "T000",
            "resolution": "ESCALATE",
            "escalation_category": "warranty_claim",
            "fraud_flags": [],
        }))
        _setup_runtime(session_memory=sm)
        state = {"ticket": {"customer_id": "C001"}, "ticket_id": "T001"}
        result = _run(check_session_memory_node(state))
        assert result.get("resolution") is None or "resolution" not in result
        assert len(result["prior_customer_records"]) == 1

    def test_empty_customer_id_does_not_crash(self):
        _setup_runtime()
        state = {"ticket": {"customer_id": ""}, "ticket_id": "T001"}
        result = _run(check_session_memory_node(state))
        assert result["prior_customer_records"] == []


# ===========================================================================
# evaluate_q1_node
# ===========================================================================

class TestEvaluateQ1Node:
    def test_q1_true_when_data_present(self):
        _setup_runtime()
        state = {
            "ticket_id": "T001",
            "order": {"order_id": "O001"},
            "customer": {"customer_id": "C001"},
        }
        result = _run(evaluate_q1_node(state))
        assert result["q1_identified"] is True

    def test_q1_false_escalates(self):
        _setup_runtime()
        state = {
            "ticket_id": "T001",
            "order": None,
            "customer": {"customer_id": "C001"},
        }
        result = _run(evaluate_q1_node(state))
        assert result["q1_identified"] is False
        assert result["resolution"] == "ESCALATE"
        assert result["escalation_category"] == "missing_data"
        assert result["next_node"] == "escalate"


# ===========================================================================
# confidence_gate_node
# ===========================================================================

class TestConfidenceGateNode:
    def test_low_confidence_escalates(self):
        _setup_runtime()
        state = {
            "q3_confident": False,
            "resolution": None,
            "q2_in_policy": True,
            "refund_amount": 50.0,
            "escalation_category": None,
        }
        result = _run(confidence_gate_node(state))
        assert result["resolution"] == "ESCALATE"
        assert result["escalation_category"] == "ambiguous_request"

    def test_high_confidence_approve(self):
        _setup_runtime()
        state = {
            "q3_confident": True,
            "resolution": None,
            "q2_in_policy": True,
            "refund_amount": 50.0,
            "escalation_category": None,
        }
        result = _run(confidence_gate_node(state))
        assert result["resolution"] == "APPROVE"
        assert result["next_node"] == "approve"

    def test_high_confidence_deny(self):
        _setup_runtime()
        state = {
            "q3_confident": True,
            "resolution": None,
            "q2_in_policy": False,
            "refund_amount": 50.0,
            "escalation_category": None,
        }
        result = _run(confidence_gate_node(state))
        assert result["resolution"] == "DENY"
        assert result["next_node"] == "deny"

    def test_high_stakes_routes_to_hitl(self):
        _setup_runtime()
        state = {
            "q3_confident": True,
            "resolution": None,
            "q2_in_policy": True,
            "refund_amount": 500.0,
            "escalation_category": None,
        }
        result = _run(confidence_gate_node(state))
        assert result["resolution"] == "APPROVE"
        assert result["next_node"] == "hitl"

    def test_existing_resolution_preserved(self):
        """If resolution already set (e.g. from Q2), it should be preserved."""
        _setup_runtime()
        state = {
            "q3_confident": True,
            "resolution": "ESCALATE",
            "q2_in_policy": True,
            "refund_amount": 50.0,
            "escalation_category": "warranty_claim",
        }
        result = _run(confidence_gate_node(state))
        assert result["resolution"] == "ESCALATE"


# ===========================================================================
# deny_node
# ===========================================================================

class TestDenyNode:
    def test_sets_resolution_to_deny(self):
        _setup_runtime()
        result = _run(deny_node({}))
        assert result["resolution"] == "DENY"


# ===========================================================================
# Routing functions
# ===========================================================================

class TestRoutingFunctions:
    """Tests for all routing functions."""

    def test_route_from_check_session_memory_default(self):
        assert route_from_check_session_memory({"next_node": None}) == "lookup_data"

    def test_route_from_check_session_memory_escalate(self):
        assert route_from_check_session_memory({"next_node": "escalate"}) == "escalate_node"

    def test_route_from_check_session_memory_write_audit(self):
        assert route_from_check_session_memory({"next_node": "write_audit"}) == "write_audit"

    def test_route_from_lookup_default(self):
        assert route_from_lookup({"next_node": None}) == "evaluate_q1"

    def test_route_from_lookup_replan(self):
        assert route_from_lookup({"next_node": "replan"}) == "replan_lookup"

    def test_route_from_lookup_write_audit(self):
        assert route_from_lookup({"next_node": "write_audit"}) == "write_audit"

    def test_route_from_replan_default(self):
        assert route_from_replan({"next_node": None}) == "evaluate_q1"

    def test_route_from_replan_escalate(self):
        assert route_from_replan({"next_node": "escalate"}) == "escalate_node"

    def test_route_from_q1_default(self):
        assert route_from_q1({"next_node": None}) == "evaluate_q2"

    def test_route_from_q1_escalate(self):
        assert route_from_q1({"next_node": "escalate"}) == "escalate_node"

    def test_route_from_confidence_gate_hitl(self):
        assert route_from_confidence_gate({"next_node": "hitl"}) == "hitl_checkpoint"

    def test_route_from_confidence_gate_approve(self):
        assert route_from_confidence_gate({"next_node": "approve"}) == "approve_node"

    def test_route_from_confidence_gate_deny(self):
        assert route_from_confidence_gate({"next_node": "deny"}) == "deny_node"

    def test_route_from_confidence_gate_default(self):
        assert route_from_confidence_gate({"next_node": None}) == "escalate_node"

    def test_route_from_hitl_approve(self):
        assert route_from_hitl({"next_node": "approve"}) == "approve_node"

    def test_route_from_hitl_default(self):
        assert route_from_hitl({"next_node": None}) == "escalate_node"

    def test_route_from_approve_default(self):
        assert route_from_approve({"next_node": None}) == "send_reply_node"

    def test_route_from_approve_escalate(self):
        assert route_from_approve({"next_node": "escalate"}) == "escalate_node"

    def test_route_from_approve_deny(self):
        assert route_from_approve({"next_node": "deny"}) == "deny_node"

    def test_route_from_approve_write_audit(self):
        assert route_from_approve({"next_node": "write_audit"}) == "write_audit"

    def test_all_routers_handle_write_audit(self):
        """All routing functions must route write_audit to write_audit."""
        routers = [
            route_from_check_session_memory,
            route_from_lookup,
            route_from_replan,
            route_from_q1,
            route_from_confidence_gate,
            route_from_hitl,
            route_from_approve,
        ]
        for router in routers:
            result = router({"next_node": "write_audit"})
            assert result == "write_audit", f"{router.__name__} did not route write_audit correctly"
