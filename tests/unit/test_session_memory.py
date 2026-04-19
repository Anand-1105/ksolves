"""
tests/unit/test_session_memory.py — Unit tests for SessionMemory.

Requirements: 16.1, 16.6
"""

from __future__ import annotations

import asyncio

import pytest

from agent.session_memory import SessionMemory


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(coro):
    return asyncio.run(coro)


def _make_record(ticket_id="T001", resolution="APPROVE", escalation_category=None, fraud_flags=None):
    return {
        "ticket_id": ticket_id,
        "resolution": resolution,
        "escalation_category": escalation_category,
        "fraud_flags": fraud_flags or [],
        "timestamp": "2024-01-01T00:00:00Z",
    }


# ===========================================================================
# Basic read/write
# ===========================================================================

class TestSessionMemoryBasic:
    def test_get_returns_empty_list_for_unknown_customer(self):
        sm = SessionMemory()
        records = _run(sm.get("C999"))
        assert records == []

    def test_write_then_get_returns_record(self):
        sm = SessionMemory()
        record = _make_record()
        _run(sm.write("C001", record))
        records = _run(sm.get("C001"))
        assert len(records) == 1
        assert records[0]["ticket_id"] == "T001"
        assert records[0]["resolution"] == "APPROVE"

    def test_multiple_writes_accumulate(self):
        sm = SessionMemory()
        _run(sm.write("C001", _make_record("T001", "APPROVE")))
        _run(sm.write("C001", _make_record("T002", "DENY")))
        _run(sm.write("C001", _make_record("T003", "ESCALATE")))
        records = _run(sm.get("C001"))
        assert len(records) == 3

    def test_different_customers_are_isolated(self):
        sm = SessionMemory()
        _run(sm.write("C001", _make_record("T001")))
        _run(sm.write("C002", _make_record("T002")))
        assert len(_run(sm.get("C001"))) == 1
        assert len(_run(sm.get("C002"))) == 1
        assert len(_run(sm.get("C003"))) == 0

    def test_get_returns_copy_not_reference(self):
        sm = SessionMemory()
        _run(sm.write("C001", _make_record("T001")))
        records1 = _run(sm.get("C001"))
        records1.append({"fake": "record"})
        records2 = _run(sm.get("C001"))
        assert len(records2) == 1  # Original not mutated

    def test_clear_resets_store(self):
        sm = SessionMemory()
        _run(sm.write("C001", _make_record("T001")))
        _run(sm.write("C002", _make_record("T002")))
        sm.clear()
        assert _run(sm.get("C001")) == []
        assert _run(sm.get("C002")) == []


# ===========================================================================
# Fraud flag detection
# ===========================================================================

class TestSessionMemoryFraudFlags:
    def test_has_fraud_flag_false_for_empty(self):
        sm = SessionMemory()
        assert sm.has_fraud_flag("C001") is False

    def test_has_fraud_flag_true_for_threat_detected_category(self):
        sm = SessionMemory()
        _run(sm.write("C001", _make_record("T001", "ESCALATE", escalation_category="threat_detected")))
        assert sm.has_fraud_flag("C001") is True

    def test_has_fraud_flag_true_for_social_engineering_category(self):
        sm = SessionMemory()
        _run(sm.write("C001", _make_record("T001", "ESCALATE", escalation_category="social_engineering")))
        assert sm.has_fraud_flag("C001") is True

    def test_has_fraud_flag_true_for_fraud_flags_list(self):
        sm = SessionMemory()
        _run(sm.write("C001", _make_record("T001", "ESCALATE", fraud_flags=["threat_detected"])))
        assert sm.has_fraud_flag("C001") is True

    def test_has_fraud_flag_false_for_non_fraud_category(self):
        sm = SessionMemory()
        _run(sm.write("C001", _make_record("T001", "ESCALATE", escalation_category="warranty_claim")))
        assert sm.has_fraud_flag("C001") is False

    def test_has_fraud_flag_false_for_approve(self):
        sm = SessionMemory()
        _run(sm.write("C001", _make_record("T001", "APPROVE")))
        assert sm.has_fraud_flag("C001") is False


# ===========================================================================
# Concurrency
# ===========================================================================

class TestSessionMemoryConcurrency:
    def test_concurrent_writes_do_not_corrupt_store(self):
        """Multiple concurrent writers for the same customer must all succeed."""
        sm = SessionMemory()

        async def write_many():
            tasks = [
                sm.write("C001", _make_record(f"T{i:03d}", "APPROVE"))
                for i in range(20)
            ]
            await asyncio.gather(*tasks)

        asyncio.run(write_many())
        records = _run(sm.get("C001"))
        assert len(records) == 20

    def test_concurrent_writes_different_customers(self):
        """Concurrent writes for different customers must not interfere."""
        sm = SessionMemory()

        async def write_all():
            tasks = [
                sm.write(f"C{i:03d}", _make_record(f"T{i:03d}", "APPROVE"))
                for i in range(10)
            ]
            await asyncio.gather(*tasks)

        asyncio.run(write_all())
        for i in range(10):
            records = _run(sm.get(f"C{i:03d}"))
            assert len(records) == 1

    def test_clear_between_runs_isolates_state(self):
        """clear() must reset all state so a new run starts fresh."""
        sm = SessionMemory()
        _run(sm.write("C001", _make_record("T001", "APPROVE")))
        sm.clear()
        _run(sm.write("C001", _make_record("T002", "DENY")))
        records = _run(sm.get("C001"))
        assert len(records) == 1
        assert records[0]["ticket_id"] == "T002"
