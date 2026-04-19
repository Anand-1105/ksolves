# Feature: shopwave-support-agent, Property 14: Session Memory Correctness
# Validates: Requirements 16.2, 16.3, 16.5

import asyncio
import datetime

from hypothesis import given, settings, strategies as st

from agent.session_memory import SessionMemory

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

customer_id_strategy = st.sampled_from(
    ["C001", "C002", "C003", "C004", "C005", "C006", "C007", "C008", "C009", "C010"]
)

ticket_id_strategy = st.text(
    min_size=1,
    max_size=10,
    alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-",
)

resolution_strategy = st.sampled_from(["APPROVE", "DENY", "ESCALATE"])

escalation_category_strategy = st.sampled_from(
    [
        "warranty_claim",
        "threat_detected",
        "social_engineering",
        "ambiguous_request",
        "missing_data",
        None,
    ]
)


def _make_record(ticket_id: str, resolution: str, escalation_category) -> dict:
    """Build a SessionRecord-compatible dict."""
    fraud_flags = []
    if escalation_category in ("threat_detected", "social_engineering"):
        fraud_flags.append(escalation_category)
    return {
        "ticket_id": ticket_id,
        "resolution": resolution,
        "escalation_category": escalation_category,
        "fraud_flags": fraud_flags,
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# Property 14a: After each write, get() contains a record with matching
#               ticket_id and resolution.
# Validates: Requirement 16.2
# ---------------------------------------------------------------------------


class TestProperty14SessionMemoryCorrectness:
    """Property 14: Session Memory Correctness — Validates: Requirements 16.2, 16.3, 16.5"""

    @settings(max_examples=100)
    @given(
        customer_id=customer_id_strategy,
        ticket_id=ticket_id_strategy,
        resolution=resolution_strategy,
        escalation_category=escalation_category_strategy,
    )
    def test_get_contains_written_record(
        self, customer_id, ticket_id, resolution, escalation_category
    ):
        """
        After a write, get(customer_id) contains a record with matching
        ticket_id and resolution.
        **Validates: Requirements 16.2**
        """
        mem = SessionMemory()
        record = _make_record(ticket_id, resolution, escalation_category)

        asyncio.run(mem.write(customer_id, record))
        records = asyncio.run(mem.get(customer_id))

        assert any(
            r["ticket_id"] == ticket_id and r["resolution"] == resolution
            for r in records
        ), (
            f"Expected a record with ticket_id={ticket_id!r} and resolution={resolution!r} "
            f"after write, got: {records}"
        )

    # ---------------------------------------------------------------------------
    # Property 14b: Multiple writes for the same customer accumulate records
    #               (all are present after N writes).
    # Validates: Requirement 16.2, 16.3
    # ---------------------------------------------------------------------------

    @settings(max_examples=100)
    @given(
        customer_id=customer_id_strategy,
        entries=st.lists(
            st.tuples(ticket_id_strategy, resolution_strategy, escalation_category_strategy),
            min_size=2,
            max_size=10,
        ),
    )
    def test_multiple_writes_accumulate(self, customer_id, entries):
        """
        Multiple writes for the same customer accumulate — all records are
        present after N writes.
        **Validates: Requirements 16.2, 16.3**
        """
        mem = SessionMemory()

        async def _write_all():
            for ticket_id, resolution, escalation_category in entries:
                record = _make_record(ticket_id, resolution, escalation_category)
                await mem.write(customer_id, record)

        asyncio.run(_write_all())
        records = asyncio.run(mem.get(customer_id))

        assert len(records) == len(entries), (
            f"Expected {len(entries)} records after {len(entries)} writes, "
            f"got {len(records)}"
        )

        # Every written (ticket_id, resolution) pair must appear in the store
        for ticket_id, resolution, _ in entries:
            assert any(
                r["ticket_id"] == ticket_id and r["resolution"] == resolution
                for r in records
            ), (
                f"Record with ticket_id={ticket_id!r}, resolution={resolution!r} "
                f"not found after accumulation. Records: {records}"
            )

    # ---------------------------------------------------------------------------
    # Property 14c: If prior records contain threat_detected or
    #               social_engineering escalation_category, has_fraud_flag
    #               returns True.
    # Validates: Requirement 16.5
    # ---------------------------------------------------------------------------

    @settings(max_examples=100)
    @given(
        customer_id=customer_id_strategy,
        ticket_id=ticket_id_strategy,
        fraud_category=st.sampled_from(["threat_detected", "social_engineering"]),
        resolution=resolution_strategy,
    )
    def test_has_fraud_flag_true_when_fraud_record_present(
        self, customer_id, ticket_id, fraud_category, resolution
    ):
        """
        has_fraud_flag returns True when any prior record carries a
        threat_detected or social_engineering escalation_category.
        **Validates: Requirements 16.5**
        """
        mem = SessionMemory()
        record = _make_record(ticket_id, resolution, fraud_category)

        asyncio.run(mem.write(customer_id, record))

        assert mem.has_fraud_flag(customer_id) is True, (
            f"Expected has_fraud_flag=True after writing record with "
            f"escalation_category={fraud_category!r}"
        )

    # ---------------------------------------------------------------------------
    # Property 14d: If no fraud records, has_fraud_flag returns False.
    # Validates: Requirement 16.5
    # ---------------------------------------------------------------------------

    @settings(max_examples=100)
    @given(
        customer_id=customer_id_strategy,
        entries=st.lists(
            st.tuples(
                ticket_id_strategy,
                resolution_strategy,
                st.sampled_from(
                    ["warranty_claim", "ambiguous_request", "missing_data", None]
                ),
            ),
            min_size=0,
            max_size=5,
        ),
    )
    def test_has_fraud_flag_false_when_no_fraud_records(self, customer_id, entries):
        """
        has_fraud_flag returns False when no records carry a fraud-related
        escalation_category (threat_detected or social_engineering).
        **Validates: Requirements 16.5**
        """
        mem = SessionMemory()

        async def _write_all():
            for ticket_id, resolution, escalation_category in entries:
                record = _make_record(ticket_id, resolution, escalation_category)
                await mem.write(customer_id, record)

        asyncio.run(_write_all())

        assert mem.has_fraud_flag(customer_id) is False, (
            f"Expected has_fraud_flag=False when no fraud records present, "
            f"got True. Records: {asyncio.run(mem.get(customer_id))}"
        )

    # ---------------------------------------------------------------------------
    # Property 14e: clear() resets the store — get returns empty list after clear.
    # Validates: Requirement 16.3 (store management)
    # ---------------------------------------------------------------------------

    @settings(max_examples=100)
    @given(
        customer_id=customer_id_strategy,
        entries=st.lists(
            st.tuples(ticket_id_strategy, resolution_strategy, escalation_category_strategy),
            min_size=1,
            max_size=5,
        ),
    )
    def test_clear_resets_store(self, customer_id, entries):
        """
        clear() resets the store — get(customer_id) returns an empty list
        after clear(), regardless of how many records were written.
        **Validates: Requirements 16.3**
        """
        mem = SessionMemory()

        async def _write_all():
            for ticket_id, resolution, escalation_category in entries:
                record = _make_record(ticket_id, resolution, escalation_category)
                await mem.write(customer_id, record)

        asyncio.run(_write_all())

        # Confirm records exist before clear
        before = asyncio.run(mem.get(customer_id))
        assert len(before) == len(entries), (
            f"Expected {len(entries)} records before clear, got {len(before)}"
        )

        mem.clear()

        after = asyncio.run(mem.get(customer_id))
        assert after == [], (
            f"Expected empty list after clear(), got {after}"
        )
