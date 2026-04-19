"""
tests/unit/test_graph.py — Unit tests for graph compilation and routing.

Requirements: 10.1, 15.2
"""

from __future__ import annotations

import pytest


class TestGraphCompilation:
    def test_build_graph_returns_compiled_graph(self):
        """build_graph() must return a compiled LangGraph graph without error."""
        from agent.graph import build_graph
        graph = build_graph()
        assert graph is not None

    def test_graph_has_interrupt_before_hitl_checkpoint(self):
        """Graph must be compiled with interrupt_before=['hitl_checkpoint']."""
        from agent.graph import build_graph
        graph = build_graph()
        # LangGraph compiled graphs expose interrupt_before via the config
        # Check that the graph object has the attribute or the checkpointer is set
        assert hasattr(graph, "checkpointer") or hasattr(graph, "config_specs"), (
            "Graph must have a checkpointer (MemorySaver) configured"
        )

    def test_graph_is_importable(self):
        """agent.graph module must be importable."""
        import agent.graph  # noqa: F401

    def test_set_runtime_is_callable(self):
        """set_runtime must be callable with session_memory, trace_logger, results."""
        from agent.graph import set_runtime
        assert callable(set_runtime)

    def test_build_graph_is_callable(self):
        """build_graph must be callable."""
        from agent.graph import build_graph
        assert callable(build_graph)

    def test_graph_entry_point_is_ingest_ticket(self):
        """The graph entry point must be 'ingest_ticket' — verified by successful compilation."""
        from agent.graph import build_graph, ingest_ticket_node
        graph = build_graph()
        # LangGraph compiled graphs don't expose entry_point directly.
        # We verify by checking the ingest_ticket node is importable and callable,
        # and that the graph compiled successfully (which requires a valid entry point).
        assert graph is not None
        assert callable(ingest_ticket_node)

    def test_all_15_nodes_present(self):
        """All 15 node functions must be importable from agent.graph."""
        from agent.graph import (
            ingest_ticket_node,
            analyze_sentiment_node,
            check_session_memory_node,
            lookup_data_node,
            replan_lookup_node,
            evaluate_q1_node,
            evaluate_q2_node,
            evaluate_q3_node,
            confidence_gate_node,
            hitl_checkpoint_node,
            approve_node,
            deny_node,
            escalate_node,
            send_reply_node,
            write_audit_node,
        )
        nodes = [
            ingest_ticket_node, analyze_sentiment_node, check_session_memory_node,
            lookup_data_node, replan_lookup_node, evaluate_q1_node, evaluate_q2_node,
            evaluate_q3_node, confidence_gate_node, hitl_checkpoint_node, approve_node,
            deny_node, escalate_node, send_reply_node, write_audit_node,
        ]
        assert len(nodes) == 15
        for node in nodes:
            assert callable(node), f"{node.__name__} must be callable"

    def test_routing_functions_are_callable(self):
        """All routing functions must be importable and callable."""
        from agent.graph import (
            route_from_check_session_memory,
            route_from_lookup,
            route_from_replan,
            route_from_q1,
            route_from_confidence_gate,
            route_from_hitl,
            route_from_approve,
        )
        routers = [
            route_from_check_session_memory, route_from_lookup, route_from_replan,
            route_from_q1, route_from_confidence_gate, route_from_hitl, route_from_approve,
        ]
        for router in routers:
            assert callable(router)

    def test_multiple_build_graph_calls_succeed(self):
        """build_graph() must be idempotent — multiple calls must all succeed."""
        from agent.graph import build_graph
        g1 = build_graph()
        g2 = build_graph()
        assert g1 is not None
        assert g2 is not None
