# Feature: shopwave-support-agent, Property 15: Trace Log Validity
# Validates: Requirements 17.1, 17.2, 17.4, 17.5

import asyncio
import json
import tempfile
from pathlib import Path

import pytest
from hypothesis import given, settings, strategies as st

from utils.logger import TraceLogger
from utils.validators import validate_trace_event


# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

_EVENT_TYPES = [
    "ticket_ingested",
    "tool_call_before",
    "tool_call_after",
    "decision_evaluated",
    "confidence_computed",
    "checkpoint_emitted",
    "resolution_final",
    "replan_triggered",
    "replan_outcome",
    "session_memory_read",
    "session_memory_write",
]

event_type_strategy = st.sampled_from(_EVENT_TYPES)

ticket_id_strategy = st.text(
    alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd"), whitelist_characters="-_"),
    min_size=1,
    max_size=20,
)

payload_strategy = st.dictionaries(
    keys=st.text(
        alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd")),
        min_size=1,
        max_size=20,
    ),
    values=st.one_of(st.text(max_size=50), st.integers(), st.booleans(), st.none()),
    max_size=5,
)

trace_event_input_strategy = st.tuples(
    event_type_strategy,
    ticket_id_strategy,
    payload_strategy,
)

trace_event_sequence_strategy = st.lists(
    trace_event_input_strategy,
    min_size=1,
    max_size=20,
)


# ---------------------------------------------------------------------------
# Helper: run a sequence of emit() calls and return the written lines
# ---------------------------------------------------------------------------

def _write_events_to_temp(events: list[tuple[str, str, dict]]) -> list[str]:
    """
    Write a sequence of trace events to a fresh temp file using TraceLogger.
    Returns the non-empty lines from the written file.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        log_path = Path(tmpdir) / "trace_log.jsonl"

        async def _run():
            logger = TraceLogger(str(log_path))
            try:
                for event_type, ticket_id, payload in events:
                    await logger.emit(event_type, ticket_id, payload)
            finally:
                logger.close()

        asyncio.run(_run())
        content = log_path.read_text(encoding="utf-8")

    return [line for line in content.splitlines() if line.strip()]


# ===========================================================================
# Property 15: Trace Log Validity
# Validates: Requirements 17.1, 17.2, 17.4, 17.5
# ===========================================================================


class TestProperty15TraceLogValidity:
    """
    Tests that TraceLogger produces a valid newline-delimited JSON file where
    every event is parseable, contains required fields, and timestamps are
    monotonically non-decreasing.
    """

    # -----------------------------------------------------------------------
    # 15a: Every non-empty line is parseable as JSON
    # Validates: Requirements 17.4
    # -----------------------------------------------------------------------

    @settings(max_examples=50)
    @given(events=trace_event_sequence_strategy)
    def test_every_line_is_valid_json(self, events):
        """
        Every non-empty line written by TraceLogger is parseable as JSON.
        **Validates: Requirements 17.4**
        """
        non_empty_lines = _write_events_to_temp(events)

        assert len(non_empty_lines) == len(events), (
            f"Expected {len(events)} lines, got {len(non_empty_lines)}"
        )

        for i, line in enumerate(non_empty_lines):
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError as exc:
                pytest.fail(
                    f"Line {i} is not valid JSON: {exc!r}\nLine content: {line!r}"
                )
            assert isinstance(parsed, dict), (
                f"Line {i} parsed to {type(parsed)}, expected dict"
            )

    # -----------------------------------------------------------------------
    # 15b: Every event contains required fields with correct types
    # Validates: Requirements 17.1, 17.2
    # -----------------------------------------------------------------------

    @settings(max_examples=50)
    @given(events=trace_event_sequence_strategy)
    def test_every_event_contains_required_fields(self, events):
        """
        Every trace event contains event_type (str), ticket_id (str),
        timestamp (str), and payload (dict).
        **Validates: Requirements 17.1, 17.2**
        """
        non_empty_lines = _write_events_to_temp(events)

        for i, line in enumerate(non_empty_lines):
            record = json.loads(line)

            assert "event_type" in record, f"Line {i} missing 'event_type'"
            assert "ticket_id" in record, f"Line {i} missing 'ticket_id'"
            assert "timestamp" in record, f"Line {i} missing 'timestamp'"
            assert "payload" in record, f"Line {i} missing 'payload'"

            assert isinstance(record["event_type"], str), (
                f"Line {i}: event_type must be str, got {type(record['event_type'])}"
            )
            assert isinstance(record["ticket_id"], str), (
                f"Line {i}: ticket_id must be str, got {type(record['ticket_id'])}"
            )
            assert isinstance(record["timestamp"], str), (
                f"Line {i}: timestamp must be str, got {type(record['timestamp'])}"
            )
            assert isinstance(record["payload"], dict), (
                f"Line {i}: payload must be dict, got {type(record['payload'])}"
            )

    # -----------------------------------------------------------------------
    # 15c: Timestamps are monotonically non-decreasing
    # Validates: Requirements 17.5
    # -----------------------------------------------------------------------

    @settings(max_examples=50)
    @given(events=trace_event_sequence_strategy)
    def test_timestamps_are_monotonically_non_decreasing(self, events):
        """
        Timestamps in the trace log are monotonically non-decreasing (wall-clock order).
        **Validates: Requirements 17.5**
        """
        non_empty_lines = _write_events_to_temp(events)
        timestamps = [json.loads(line)["timestamp"] for line in non_empty_lines]

        for i in range(1, len(timestamps)):
            assert timestamps[i - 1] <= timestamps[i], (
                f"Timestamp at line {i - 1} ({timestamps[i - 1]!r}) is after "
                f"timestamp at line {i} ({timestamps[i]!r}): "
                "timestamps are not monotonically non-decreasing"
            )

    # -----------------------------------------------------------------------
    # 15d: validate_trace_event returns True for all events written by TraceLogger
    # Validates: Requirements 17.4
    # -----------------------------------------------------------------------

    @settings(max_examples=50)
    @given(events=trace_event_sequence_strategy)
    def test_validate_trace_event_returns_true_for_written_events(self, events):
        """
        validate_trace_event returns True for every event written by TraceLogger.
        **Validates: Requirements 17.4**
        """
        non_empty_lines = _write_events_to_temp(events)

        for i, line in enumerate(non_empty_lines):
            record = json.loads(line)
            assert validate_trace_event(record) is True, (
                f"validate_trace_event returned False for line {i}: {record!r}"
            )

    # -----------------------------------------------------------------------
    # 15e: validate_trace_event returns False for events missing required fields
    # Validates: Requirements 17.4
    # -----------------------------------------------------------------------

    def test_validate_trace_event_returns_false_for_missing_event_type(self):
        """validate_trace_event returns False when event_type is missing."""
        event = {
            "ticket_id": "T001",
            "timestamp": "2024-01-01T00:00:00Z",
            "payload": {},
        }
        assert validate_trace_event(event) is False

    def test_validate_trace_event_returns_false_for_missing_ticket_id(self):
        """validate_trace_event returns False when ticket_id is missing."""
        event = {
            "event_type": "ticket_ingested",
            "timestamp": "2024-01-01T00:00:00Z",
            "payload": {},
        }
        assert validate_trace_event(event) is False

    def test_validate_trace_event_returns_false_for_missing_timestamp(self):
        """validate_trace_event returns False when timestamp is missing."""
        event = {
            "event_type": "ticket_ingested",
            "ticket_id": "T001",
            "payload": {},
        }
        assert validate_trace_event(event) is False

    def test_validate_trace_event_returns_false_for_missing_payload(self):
        """validate_trace_event returns False when payload is missing."""
        event = {
            "event_type": "ticket_ingested",
            "ticket_id": "T001",
            "timestamp": "2024-01-01T00:00:00Z",
        }
        assert validate_trace_event(event) is False

    def test_validate_trace_event_returns_false_for_empty_dict(self):
        """validate_trace_event returns False for an empty dict."""
        assert validate_trace_event({}) is False

    def test_validate_trace_event_returns_false_for_non_dict(self):
        """validate_trace_event returns False for non-dict inputs."""
        assert validate_trace_event(None) is False
        assert validate_trace_event("string") is False
        assert validate_trace_event(42) is False
        assert validate_trace_event([]) is False

    def test_validate_trace_event_returns_false_for_wrong_types(self):
        """validate_trace_event returns False when field types are wrong."""
        # event_type not a str
        assert validate_trace_event({
            "event_type": 123,
            "ticket_id": "T001",
            "timestamp": "2024-01-01T00:00:00Z",
            "payload": {},
        }) is False

        # ticket_id not a str
        assert validate_trace_event({
            "event_type": "ticket_ingested",
            "ticket_id": 999,
            "timestamp": "2024-01-01T00:00:00Z",
            "payload": {},
        }) is False

        # timestamp not a str
        assert validate_trace_event({
            "event_type": "ticket_ingested",
            "ticket_id": "T001",
            "timestamp": 1234567890,
            "payload": {},
        }) is False

        # payload not a dict
        assert validate_trace_event({
            "event_type": "ticket_ingested",
            "ticket_id": "T001",
            "timestamp": "2024-01-01T00:00:00Z",
            "payload": "not-a-dict",
        }) is False

    def test_validate_trace_event_returns_true_for_valid_event(self):
        """validate_trace_event returns True for a fully valid event."""
        event = {
            "event_type": "ticket_ingested",
            "ticket_id": "T001",
            "timestamp": "2024-01-01T00:00:00.000000Z",
            "payload": {"issue_type": "refund_request", "customer_id": "C001"},
        }
        assert validate_trace_event(event) is True

    # -----------------------------------------------------------------------
    # 15f: Property — validate_trace_event returns True for all generated valid events
    # Validates: Requirements 17.4
    # -----------------------------------------------------------------------

    @settings(max_examples=50)
    @given(
        event_type=event_type_strategy,
        ticket_id=ticket_id_strategy,
        payload=payload_strategy,
    )
    def test_validate_trace_event_property_valid_events(
        self, event_type, ticket_id, payload
    ):
        """
        validate_trace_event returns True for any event with all required fields
        having correct types.
        **Validates: Requirements 17.4**
        """
        event = {
            "event_type": event_type,
            "ticket_id": ticket_id,
            "timestamp": "2024-01-01T00:00:00.000000Z",
            "payload": payload,
        }
        assert validate_trace_event(event) is True

    @settings(max_examples=50)
    @given(
        missing_field=st.sampled_from(["event_type", "ticket_id", "timestamp", "payload"]),
        event_type=event_type_strategy,
        ticket_id=ticket_id_strategy,
        payload=payload_strategy,
    )
    def test_validate_trace_event_property_missing_field(
        self, missing_field, event_type, ticket_id, payload
    ):
        """
        validate_trace_event returns False whenever any required field is absent.
        **Validates: Requirements 17.4**
        """
        event = {
            "event_type": event_type,
            "ticket_id": ticket_id,
            "timestamp": "2024-01-01T00:00:00.000000Z",
            "payload": payload,
        }
        del event[missing_field]
        assert validate_trace_event(event) is False
