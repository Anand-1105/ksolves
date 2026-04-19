"""
tests/smoke/test_structure.py — Module structure smoke tests.

Requirements: 10.1, 10.4
"""

from __future__ import annotations

import pytest


class TestModuleStructure:
    def test_agent_state_importable(self):
        from agent.state import TicketState, Resolution, EscalationCategory
        assert TicketState is not None
        assert Resolution is not None
        assert EscalationCategory is not None

    def test_agent_tools_importable_and_callable(self):
        from agent.tools import (
            get_order, get_customer, get_product, search_knowledge_base,
            check_refund_eligibility, issue_refund, send_reply, escalate,
        )
        tools = [get_order, get_customer, get_product, search_knowledge_base,
                 check_refund_eligibility, issue_refund, send_reply, escalate]
        assert len(tools) == 8
        for tool in tools:
            assert callable(tool), f"{tool.__name__} must be callable"

    def test_agent_decisions_importable_and_callable(self):
        from agent.decisions import (
            evaluate_q1, evaluate_q2, compute_confidence_score, is_high_stakes,
        )
        for fn in [evaluate_q1, evaluate_q2, compute_confidence_score, is_high_stakes]:
            assert callable(fn)

    def test_agent_graph_importable_and_build_graph_works(self):
        from agent.graph import build_graph, set_runtime
        graph = build_graph()
        assert graph is not None
        assert callable(set_runtime)

    def test_agent_session_memory_importable(self):
        from agent.session_memory import SessionMemory
        sm = SessionMemory()
        assert sm is not None

    def test_utils_logger_importable(self):
        from utils.logger import TraceLogger
        assert TraceLogger is not None

    def test_utils_validators_importable(self):
        from utils.validators import validate_tool_output, validate_audit_record, validate_trace_event
        for fn in [validate_tool_output, validate_audit_record, validate_trace_event]:
            assert callable(fn)

    def test_resolution_enum_values(self):
        from agent.state import Resolution
        assert Resolution.APPROVE.value == "APPROVE"
        assert Resolution.DENY.value == "DENY"
        assert Resolution.ESCALATE.value == "ESCALATE"

    def test_escalation_category_enum_values(self):
        from agent.state import EscalationCategory
        expected = {
            "warranty_claim", "threat_detected", "social_engineering",
            "ambiguous_request", "missing_data", "replacement_needed",
        }
        actual = {e.value for e in EscalationCategory}
        assert actual == expected

    def test_initial_state_factory(self):
        from agent.state import initial_state
        ticket = {"ticket_id": "T001", "customer_id": "C001", "order_id": "O001",
                  "issue_type": "refund_request", "description": "Test"}
        state = initial_state(ticket)
        assert state["ticket_id"] == "T001"
        assert state["tool_calls"] == []
        assert state["replan_attempts"] == []
        assert state["checkpoint_events"] == []
        assert state["resolution"] is None
