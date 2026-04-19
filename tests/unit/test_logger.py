"""
tests/unit/test_logger.py — Unit tests for the TraceLogger.

Tests file writing, JSONL format, concurrent access, and lifecycle.
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile

import pytest

from utils.logger import TraceLogger


def _run(coro):
    return asyncio.run(coro)


class TestTraceLoggerEmit:
    """Tests for TraceLogger.emit()."""

    def test_writes_valid_jsonl(self):
        """Each emit should write a valid JSON line."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            path = f.name
        try:
            logger = TraceLogger(path)
            _run(logger.emit("test_event", "T001", {"key": "value"}))
            logger.close()

            with open(path, "r") as f:
                lines = f.readlines()
            assert len(lines) == 1
            event = json.loads(lines[0])
            assert event["event_type"] == "test_event"
            assert event["ticket_id"] == "T001"
            assert event["payload"]["key"] == "value"
            assert "timestamp" in event
        finally:
            os.unlink(path)

    def test_multiple_emits_produce_multiple_lines(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            path = f.name
        try:
            logger = TraceLogger(path)
            _run(logger.emit("event1", "T001", {"n": 1}))
            _run(logger.emit("event2", "T002", {"n": 2}))
            _run(logger.emit("event3", "T003", {"n": 3}))
            logger.close()

            with open(path, "r") as f:
                lines = f.readlines()
            assert len(lines) == 3
            for line in lines:
                event = json.loads(line)
                assert "event_type" in event
        finally:
            os.unlink(path)

    def test_concurrent_emits_do_not_interleave(self):
        """Multiple concurrent emits should each produce a complete JSON line."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            path = f.name
        try:
            logger = TraceLogger(path)

            async def emit_many():
                tasks = [
                    logger.emit(f"event_{i}", f"T{i:03d}", {"index": i})
                    for i in range(20)
                ]
                await asyncio.gather(*tasks)

            asyncio.run(emit_many())
            logger.close()

            with open(path, "r") as f:
                lines = f.readlines()
            assert len(lines) == 20
            for line in lines:
                event = json.loads(line)  # Should not raise
                assert "event_type" in event
                assert "ticket_id" in event
        finally:
            os.unlink(path)


class TestTraceLoggerConvenienceMethods:
    """Tests for convenience logger methods."""

    def test_ticket_ingested(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            path = f.name
        try:
            logger = TraceLogger(path)
            _run(logger.ticket_ingested("T001", {"issue_type": "refund", "customer_id": "C001"}))
            logger.close()

            with open(path, "r") as f:
                event = json.loads(f.readline())
            assert event["event_type"] == "ticket_ingested"
            assert event["payload"]["issue_type"] == "refund"
        finally:
            os.unlink(path)

    def test_tool_call_before_and_after(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            path = f.name
        try:
            logger = TraceLogger(path)
            _run(logger.tool_call_before("T001", "get_order", {"order_id": "O001"}))
            _run(logger.tool_call_after("T001", "get_order", {"order_id": "O001", "amount": 100}))
            logger.close()

            with open(path, "r") as f:
                lines = f.readlines()
            assert len(lines) == 2
            assert json.loads(lines[0])["event_type"] == "tool_call_before"
            assert json.loads(lines[1])["event_type"] == "tool_call_after"
        finally:
            os.unlink(path)

    def test_decision_evaluated(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            path = f.name
        try:
            logger = TraceLogger(path)
            _run(logger.decision_evaluated("T001", "Q1", True))
            logger.close()

            with open(path, "r") as f:
                event = json.loads(f.readline())
            assert event["event_type"] == "decision_evaluated"
            assert event["payload"]["question"] == "Q1"
            assert event["payload"]["value"] is True
        finally:
            os.unlink(path)

    def test_confidence_computed(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            path = f.name
        try:
            logger = TraceLogger(path)
            _run(logger.confidence_computed("T001", 0.85, {"dc": 1.0, "rc": 0.9}))
            logger.close()

            with open(path, "r") as f:
                event = json.loads(f.readline())
            assert event["event_type"] == "confidence_computed"
            assert event["payload"]["score"] == 0.85
        finally:
            os.unlink(path)

    def test_resolution_final(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            path = f.name
        try:
            logger = TraceLogger(path)
            _run(logger.resolution_final("T001", "APPROVE", None))
            logger.close()

            with open(path, "r") as f:
                event = json.loads(f.readline())
            assert event["event_type"] == "resolution_final"
            assert event["payload"]["resolution"] == "APPROVE"
        finally:
            os.unlink(path)

    def test_session_memory_read_and_write(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            path = f.name
        try:
            logger = TraceLogger(path)
            _run(logger.session_memory_read("T001", "C001", 3))
            _run(logger.session_memory_write("T001", "C001", "APPROVE"))
            logger.close()

            with open(path, "r") as f:
                lines = f.readlines()
            assert json.loads(lines[0])["event_type"] == "session_memory_read"
            assert json.loads(lines[1])["event_type"] == "session_memory_write"
        finally:
            os.unlink(path)


class TestTraceLoggerLifecycle:
    """Tests for TraceLogger lifecycle."""

    def test_close_is_idempotent(self):
        """Calling close() multiple times should not raise."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            path = f.name
        try:
            logger = TraceLogger(path)
            logger.close()
            # Second close should not raise
            try:
                logger.close()
            except Exception as e:
                pytest.fail(f"Second close() raised: {e}")
        finally:
            os.unlink(path)

    def test_appends_to_existing_file(self):
        """TraceLogger should append to existing file contents."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
            path = f.name
            f.write('{"existing": true}\n')
        try:
            logger = TraceLogger(path)
            _run(logger.emit("new_event", "T001", {}))
            logger.close()

            with open(path, "r") as f:
                lines = f.readlines()
            assert len(lines) == 2
            assert json.loads(lines[0])["existing"] is True
            assert json.loads(lines[1])["event_type"] == "new_event"
        finally:
            os.unlink(path)
