"""
tests/unit/test_tools.py — Unit tests for all 8 tool contracts.

Requirements: 12.1–12.8
"""

from __future__ import annotations

import pytest

from agent.tools import (
    get_order,
    get_customer,
    get_product,
    search_knowledge_base,
    check_refund_eligibility,
    issue_refund,
    send_reply,
    escalate,
)


# ===========================================================================
# get_order
# ===========================================================================

class TestGetOrder:
    def test_known_order_returns_record(self):
        result = get_order("O001")
        assert "error" not in result
        assert result["order_id"] == "O001"
        assert "customer_id" in result
        assert "product_id" in result
        assert "amount" in result

    def test_unknown_order_returns_not_found(self):
        result = get_order("O999")
        assert result.get("error") == "not_found"
        assert result.get("order_id") == "O999"

    def test_empty_string_returns_not_found(self):
        result = get_order("")
        assert result.get("error") == "not_found"

    def test_does_not_raise(self):
        # Should never raise — safe_tool_call wraps it
        result = get_order(None)  # type: ignore
        assert isinstance(result, dict)


# ===========================================================================
# get_customer
# ===========================================================================

class TestGetCustomer:
    def test_known_customer_id_returns_record(self):
        result = get_customer("C001")
        assert "error" not in result
        assert result["customer_id"] == "C001"
        assert result["name"] == "Alice"
        assert result["tier"] == "vip"

    def test_known_email_returns_record(self):
        result = get_customer("alice.johnson@example.com")
        assert "error" not in result
        assert result["customer_id"] == "C001"

    def test_email_lookup_is_case_insensitive(self):
        result = get_customer("ALICE.JOHNSON@EXAMPLE.COM")
        assert "error" not in result
        assert result["customer_id"] == "C001"

    def test_unknown_customer_id_returns_not_found(self):
        result = get_customer("C999")
        assert result.get("error") == "not_found"

    def test_unknown_email_returns_not_found(self):
        result = get_customer("nobody@example.com")
        assert result.get("error") == "not_found"

    def test_does_not_raise(self):
        result = get_customer(None)  # type: ignore
        assert isinstance(result, dict)

    def test_vip_customer_has_vip_exceptions(self):
        result = get_customer("C001")
        assert result.get("tier") == "vip"
        assert "vip_exceptions" in result
        assert result["vip_exceptions"].get("extended_return_window_days") == 90

    def test_emma_is_vip_with_extended_window(self):
        result = get_customer("C002")
        assert result.get("tier") == "vip"
        assert result["vip_exceptions"].get("extended_return_window_days") == 90


# ===========================================================================
# get_product
# ===========================================================================

class TestGetProduct:
    def test_known_product_returns_record(self):
        result = get_product("P001")
        assert "error" not in result
        assert result["product_id"] == "P001"
        assert "return_window_days" in result
        assert "warranty_months" in result
        assert "price" in result

    def test_unknown_product_returns_not_found(self):
        result = get_product("P999")
        # May get transient failure or not_found — both are valid structured errors
        assert result.get("error") in ("not_found", "timeout", "malformed_response")

    def test_all_8_products_exist(self):
        for i in range(1, 9):
            result = get_product(f"P00{i}")
            assert "error" not in result, f"P00{i} should exist"

    def test_does_not_raise(self):
        result = get_product(None)  # type: ignore
        assert isinstance(result, dict)

    def test_products_have_distinct_return_windows(self):
        windows = set()
        for i in range(1, 9):
            r = get_product(f"P00{i}")
            if "error" not in r:
                windows.add(r["return_window_days"])
        # Should have at least 2 distinct values (15, 30, 60)
        assert len(windows) >= 2


# ===========================================================================
# search_knowledge_base
# ===========================================================================

class TestSearchKnowledgeBase:
    def test_return_query_returns_result(self):
        result = search_knowledge_base("What is your return policy?")
        assert isinstance(result, dict)
        assert "result" in result

    def test_warranty_query_returns_result(self):
        # May get transient failure — just check it returns a dict
        result = search_knowledge_base("warranty coverage for defective products")
        assert isinstance(result, dict)
        assert "result" in result or "error" in result

    def test_unknown_query_returns_no_result(self):
        result = search_knowledge_base("xyzzy frobnicator")
        assert isinstance(result, dict)
        assert "result" in result
        # Either None or a string
        assert result["result"] is None or isinstance(result["result"], str)

    def test_empty_query_does_not_raise(self):
        result = search_knowledge_base("")
        assert isinstance(result, dict)

    def test_result_key_always_present(self):
        for query in ["return", "warranty", "vip", "refund", "escalation", "unknown_xyz"]:
            result = search_knowledge_base(query)
            assert "result" in result or "error" in result, (
                f"'result' or 'error' key missing for query='{query}'"
            )


# ===========================================================================
# check_refund_eligibility
# ===========================================================================

class TestCheckRefundEligibility:
    def test_returns_eligible_bool_and_explanation(self):
        result = check_refund_eligibility("O001")
        assert isinstance(result, dict)
        assert "eligible" in result
        assert "reason" in result
        assert isinstance(result["reason"], str)

    def test_recent_order_is_eligible(self):
        # O001 has a recent purchase_date (within 90-day VIP window for Alice)
        result = check_refund_eligibility("O001")
        assert result.get("eligible") is True

    def test_unknown_order_returns_not_found(self):
        result = check_refund_eligibility("O999")
        assert result.get("error") == "not_found"

    def test_does_not_raise(self):
        result = check_refund_eligibility(None)  # type: ignore
        assert isinstance(result, dict)

    def test_eligible_field_is_bool_or_escalate_or_false(self):
        result = check_refund_eligibility("O001")
        assert result.get("eligible") in (True, False, "escalate")


# ===========================================================================
# issue_refund
# ===========================================================================

class TestIssueRefund:
    def test_returns_refund_id(self):
        result = issue_refund("O001", 129.99)
        assert isinstance(result, dict)
        assert result.get("refund_id"), "refund_id must be non-empty"

    def test_refund_id_contains_order_id(self):
        result = issue_refund("O001", 50.0)
        assert "O001" in result["refund_id"]

    def test_returns_correct_amount(self):
        result = issue_refund("O001", 299.99)
        assert result.get("amount") == 299.99

    def test_status_is_issued(self):
        result = issue_refund("O001", 100.0)
        assert result.get("status") == "issued"

    def test_does_not_raise(self):
        result = issue_refund(None, None)  # type: ignore
        assert isinstance(result, dict)

    def test_zero_amount_returns_refund_id(self):
        result = issue_refund("O001", 0.0)
        assert result.get("refund_id"), "refund_id must be non-empty even for zero amount"


# ===========================================================================
# send_reply
# ===========================================================================

class TestSendReply:
    def test_returns_delivered_true(self):
        result = send_reply("T001", "Hello customer")
        assert result.get("delivered") is True

    def test_returns_matching_ticket_id(self):
        result = send_reply("T042", "Your refund is approved.")
        assert result.get("ticket_id") == "T042"

    def test_returns_timestamp(self):
        result = send_reply("T001", "Hello")
        assert result.get("timestamp"), "timestamp must be present"

    def test_does_not_raise(self):
        result = send_reply(None, None)  # type: ignore
        assert isinstance(result, dict)

    def test_long_message_does_not_raise(self):
        long_msg = "A" * 10000
        result = send_reply("T001", long_msg)
        assert result.get("delivered") is True


# ===========================================================================
# escalate
# ===========================================================================

class TestEscalate:
    def test_returns_case_id(self):
        result = escalate("T001", "Warranty claim summary", "medium")
        assert result.get("case_id"), "case_id must be non-empty"

    def test_case_id_contains_ticket_id(self):
        result = escalate("T001", "Threat detected", "urgent")
        assert "T001" in result["case_id"]

    def test_returns_correct_priority(self):
        result = escalate("T001", "Social engineering", "high")
        assert result.get("priority") == "high"

    def test_status_is_escalated(self):
        result = escalate("T001", "Missing data", "low")
        assert result.get("status") == "escalated"

    def test_all_valid_priorities_accepted(self):
        for priority in ["low", "medium", "high", "urgent"]:
            result = escalate("T001", f"Summary for {priority}", priority)
            assert result.get("case_id"), f"case_id must be non-empty for priority={priority}"
            assert result.get("priority") == priority

    def test_does_not_raise(self):
        result = escalate(None, None, None)  # type: ignore
        assert isinstance(result, dict)
