"""
tests/unit/test_validators.py — Unit tests for all three validator functions.

Tests validate_tool_output, validate_audit_record, and validate_trace_event
for correct schema enforcement, type checking, and edge case handling.
"""

from __future__ import annotations

import pytest

from utils.validators import (
    validate_tool_output,
    validate_audit_record,
    validate_trace_event,
)


# ===========================================================================
# validate_tool_output
# ===========================================================================

class TestValidateToolOutput:
    """Tests for validate_tool_output()."""

    def test_non_dict_is_invalid(self):
        assert validate_tool_output("get_order", "string") is False
        assert validate_tool_output("get_order", None) is False
        assert validate_tool_output("get_order", []) is False

    def test_error_response_is_always_valid(self):
        """Any dict with an 'error' key is valid (error response)."""
        for tool in ["get_order", "get_customer", "get_product",
                      "check_refund_eligibility", "issue_refund",
                      "send_reply", "escalate", "search_knowledge_base"]:
            assert validate_tool_output(tool, {"error": "not_found"}) is True
            assert validate_tool_output(tool, {"error": "timeout"}) is True

    def test_get_order_valid(self):
        assert validate_tool_output("get_order", {"order_id": "O001", "amount": 100}) is True

    def test_get_order_missing_key(self):
        assert validate_tool_output("get_order", {"amount": 100}) is False

    def test_get_customer_valid(self):
        assert validate_tool_output("get_customer", {"customer_id": "C001", "name": "Alice"}) is True

    def test_get_customer_missing_key(self):
        assert validate_tool_output("get_customer", {"name": "Alice"}) is False

    def test_get_product_valid(self):
        assert validate_tool_output("get_product", {"product_id": "P001"}) is True

    def test_get_product_missing_key(self):
        assert validate_tool_output("get_product", {"name": "Laptop"}) is False

    def test_check_refund_eligibility_valid_true(self):
        assert validate_tool_output("check_refund_eligibility", {"eligible": True, "reason": "ok"}) is True

    def test_check_refund_eligibility_valid_false(self):
        assert validate_tool_output("check_refund_eligibility", {"eligible": False, "reason": "expired"}) is True

    def test_check_refund_eligibility_valid_escalate(self):
        assert validate_tool_output("check_refund_eligibility", {"eligible": "escalate", "reason": "warranty"}) is True

    def test_check_refund_eligibility_invalid_string(self):
        """eligible must be bool or 'escalate', not arbitrary string."""
        assert validate_tool_output("check_refund_eligibility", {"eligible": "yes"}) is False

    def test_check_refund_eligibility_invalid_int(self):
        assert validate_tool_output("check_refund_eligibility", {"eligible": 1}) is False

    def test_issue_refund_valid(self):
        assert validate_tool_output("issue_refund", {"refund_id": "REF-001"}) is True

    def test_issue_refund_empty_string_is_invalid(self):
        """refund_id must be non-empty string."""
        assert validate_tool_output("issue_refund", {"refund_id": ""}) is False

    def test_issue_refund_none_is_invalid(self):
        assert validate_tool_output("issue_refund", {"refund_id": None}) is False

    def test_send_reply_valid(self):
        assert validate_tool_output("send_reply", {"delivered": True}) is True

    def test_send_reply_missing_key(self):
        assert validate_tool_output("send_reply", {"status": "sent"}) is False

    def test_escalate_valid(self):
        assert validate_tool_output("escalate", {"case_id": "ESC-001"}) is True

    def test_escalate_empty_case_id_is_invalid(self):
        assert validate_tool_output("escalate", {"case_id": ""}) is False

    def test_search_knowledge_base_valid(self):
        assert validate_tool_output("search_knowledge_base", {"result": "policy text"}) is True

    def test_search_knowledge_base_null_result_valid(self):
        assert validate_tool_output("search_knowledge_base", {"result": None}) is True

    def test_unknown_tool_accepts_any_dict(self):
        """Unknown tool names should accept any dict (no required keys)."""
        assert validate_tool_output("unknown_tool", {"foo": "bar"}) is True
        assert validate_tool_output("unknown_tool", {}) is True


# ===========================================================================
# validate_audit_record
# ===========================================================================

class TestValidateAuditRecord:
    """Tests for validate_audit_record()."""

    def _valid_record(self):
        return {
            "ticket_id": "T001",
            "customer_id": "C001",
            "tool_calls": [],
            "reasoning": {
                "q1_identified": True,
                "q2_in_policy": True,
                "q3_confident": True,
            },
            "confidence_score": 0.85,
            "confidence_factors": {"data_completeness": 1.0},
            "self_reflection_note": "All good",
            "replan_attempts": [],
            "checkpoint_events": [],
            "resolution": "APPROVE",
            "escalation_category": None,
        }

    def test_valid_record_passes(self):
        assert validate_audit_record(self._valid_record()) is True

    def test_non_dict_fails(self):
        assert validate_audit_record("not a dict") is False
        assert validate_audit_record(None) is False
        assert validate_audit_record([]) is False

    def test_missing_ticket_id_fails(self):
        record = self._valid_record()
        del record["ticket_id"]
        assert validate_audit_record(record) is False

    def test_missing_reasoning_fails(self):
        record = self._valid_record()
        del record["reasoning"]
        assert validate_audit_record(record) is False

    def test_reasoning_missing_q_key_fails(self):
        record = self._valid_record()
        del record["reasoning"]["q1_identified"]
        assert validate_audit_record(record) is False

    def test_non_string_ticket_id_fails(self):
        record = self._valid_record()
        record["ticket_id"] = 123
        assert validate_audit_record(record) is False

    def test_non_list_tool_calls_fails(self):
        record = self._valid_record()
        record["tool_calls"] = "not a list"
        assert validate_audit_record(record) is False

    def test_confidence_score_none_is_valid(self):
        record = self._valid_record()
        record["confidence_score"] = None
        assert validate_audit_record(record) is True

    def test_confidence_score_int_is_valid(self):
        record = self._valid_record()
        record["confidence_score"] = 1
        assert validate_audit_record(record) is True

    def test_confidence_score_string_is_invalid(self):
        record = self._valid_record()
        record["confidence_score"] = "0.85"
        assert validate_audit_record(record) is False

    def test_resolution_none_is_valid(self):
        record = self._valid_record()
        record["resolution"] = None
        assert validate_audit_record(record) is True

    def test_resolution_non_string_is_invalid(self):
        record = self._valid_record()
        record["resolution"] = 123
        assert validate_audit_record(record) is False

    def test_escalation_category_none_is_valid(self):
        record = self._valid_record()
        record["escalation_category"] = None
        assert validate_audit_record(record) is True

    def test_all_required_fields_present(self):
        """Remove each required field one at a time and verify failure."""
        required = [
            "ticket_id", "customer_id", "tool_calls", "reasoning",
            "confidence_score", "confidence_factors", "self_reflection_note",
            "replan_attempts", "checkpoint_events", "resolution", "escalation_category",
        ]
        for field in required:
            record = self._valid_record()
            del record[field]
            assert validate_audit_record(record) is False, f"Missing '{field}' should fail"


# ===========================================================================
# validate_trace_event
# ===========================================================================

class TestValidateTraceEvent:
    """Tests for validate_trace_event()."""

    def _valid_event(self):
        return {
            "event_type": "ticket_ingested",
            "ticket_id": "T001",
            "timestamp": "2026-04-19T00:00:00Z",
            "payload": {"issue_type": "refund_request"},
        }

    def test_valid_event_passes(self):
        assert validate_trace_event(self._valid_event()) is True

    def test_non_dict_fails(self):
        assert validate_trace_event("string") is False
        assert validate_trace_event(None) is False

    def test_missing_event_type_fails(self):
        event = self._valid_event()
        del event["event_type"]
        assert validate_trace_event(event) is False

    def test_missing_ticket_id_fails(self):
        event = self._valid_event()
        del event["ticket_id"]
        assert validate_trace_event(event) is False

    def test_missing_timestamp_fails(self):
        event = self._valid_event()
        del event["timestamp"]
        assert validate_trace_event(event) is False

    def test_missing_payload_fails(self):
        event = self._valid_event()
        del event["payload"]
        assert validate_trace_event(event) is False

    def test_non_string_event_type_fails(self):
        event = self._valid_event()
        event["event_type"] = 123
        assert validate_trace_event(event) is False

    def test_non_dict_payload_fails(self):
        event = self._valid_event()
        event["payload"] = "not a dict"
        assert validate_trace_event(event) is False

    def test_all_required_fields_present(self):
        """Remove each required field one at a time and verify failure."""
        for field in ["event_type", "ticket_id", "timestamp", "payload"]:
            event = self._valid_event()
            del event[field]
            assert validate_trace_event(event) is False, f"Missing '{field}' should fail"
