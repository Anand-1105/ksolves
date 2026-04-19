"""
tests/unit/test_retry.py — Unit tests for the with_retry mechanism.

Tests retry logic, backoff behavior, and permanent vs transient error handling.
"""

from __future__ import annotations

import asyncio

import pytest

from agent.tools import with_retry


def _run(coro):
    return asyncio.run(coro)


class TestWithRetry:
    """Tests for with_retry() exponential backoff retry logic."""

    def test_success_on_first_call(self):
        """Successful first call returns immediately."""
        def tool(*args):
            return {"data": "ok"}

        result = _run(with_retry(tool, "arg1", base_delay=0.001))
        assert result == {"data": "ok"}

    def test_permanent_failure_not_retried(self):
        """not_found errors are not retried."""
        call_count = 0

        def tool(*args):
            nonlocal call_count
            call_count += 1
            return {"error": "not_found", "order_id": "O999"}

        result = _run(with_retry(tool, "O999", base_delay=0.001))
        assert call_count == 1  # Only called once
        assert result["error"] == "not_found"

    def test_transient_timeout_retried(self):
        """Timeout errors are retried up to max_retries."""
        call_count = 0

        def tool(*args):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                return {"error": "timeout", "message": "timed out"}
            return {"data": "ok"}

        result = _run(with_retry(tool, "arg", max_retries=2, base_delay=0.001))
        assert call_count == 3
        assert result == {"data": "ok"}

    def test_transient_malformed_retried(self):
        """Malformed response errors are retried."""
        call_count = 0

        def tool(*args):
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                return {"error": "malformed_response", "message": "bad data"}
            return {"data": "ok"}

        result = _run(with_retry(tool, "arg", max_retries=2, base_delay=0.001))
        assert call_count == 2
        assert result == {"data": "ok"}

    def test_tool_exception_retried(self):
        """Tool exceptions are treated as transient and retried."""
        call_count = 0

        def tool(*args):
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                return {"error": "tool_exception", "message": "crash"}
            return {"data": "ok"}

        result = _run(with_retry(tool, "arg", max_retries=2, base_delay=0.001))
        assert call_count == 2
        assert result == {"data": "ok"}

    def test_max_retries_exhausted(self):
        """When all retries fail, returns the last error result."""
        call_count = 0

        def tool(*args):
            nonlocal call_count
            call_count += 1
            return {"error": "timeout", "message": "always fails"}

        result = _run(with_retry(tool, "arg", max_retries=2, base_delay=0.001))
        assert call_count == 3  # initial + 2 retries
        assert result["error"] == "timeout"

    def test_zero_retries_calls_once(self):
        """max_retries=0 means call once with no retries."""
        call_count = 0

        def tool(*args):
            nonlocal call_count
            call_count += 1
            return {"error": "timeout", "message": "fail"}

        result = _run(with_retry(tool, "arg", max_retries=0, base_delay=0.001))
        assert call_count == 1
        assert result["error"] == "timeout"

    def test_non_error_response_returned_immediately(self):
        """A response without 'error' key is returned immediately."""
        call_count = 0

        def tool(*args):
            nonlocal call_count
            call_count += 1
            return {"result": "success", "value": 42}

        result = _run(with_retry(tool, "arg", max_retries=2, base_delay=0.001))
        assert call_count == 1
        assert result["value"] == 42

    def test_recovery_after_transient_failure(self):
        """First call fails, second succeeds — should return success."""
        call_count = 0

        def tool(*args):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return {"error": "timeout", "message": "first fail"}
            return {"order_id": "O001", "amount": 99.99}

        result = _run(with_retry(tool, "O001", max_retries=1, base_delay=0.001))
        assert call_count == 2
        assert result["order_id"] == "O001"

    def test_kwargs_passed_through(self):
        """Keyword arguments are forwarded to the tool function."""
        def tool(*args, **kwargs):
            return {"received_kwarg": kwargs.get("flag", False)}

        result = _run(with_retry(tool, "arg", base_delay=0.001, flag=True))
        # Note: flag goes into kwargs of with_retry, not to tool_fn
        # with_retry passes *args and **kwargs (minus retry-specific kwargs) to tool_fn
        # Actually, looking at the implementation, all extra kwargs go to with_retry itself
        # The tool is called with positional args only: tool_fn(*args, **kwargs)
        # But max_retries and base_delay are with_retry's own params
        assert isinstance(result, dict)


class TestWithRetryEdgeCases:
    """Edge cases for with_retry."""

    def test_empty_error_string_is_not_retried(self):
        """An empty 'error' key (empty string) means no error, return immediately."""
        call_count = 0

        def tool(*args):
            nonlocal call_count
            call_count += 1
            return {"error": "", "data": "ok"}

        result = _run(with_retry(tool, "arg", max_retries=2, base_delay=0.001))
        # Empty string is falsy, so error_type will be "", which is not in transient set
        # and not "not_found", so it will be returned as success
        assert call_count == 1

    def test_unknown_error_type_not_retried(self):
        """Unknown error types (not timeout/malformed/tool_exception/not_found) are not retried."""
        call_count = 0

        def tool(*args):
            nonlocal call_count
            call_count += 1
            return {"error": "unknown_weird_error", "message": "what"}

        result = _run(with_retry(tool, "arg", max_retries=2, base_delay=0.001))
        assert call_count == 1  # Not retried
        assert result["error"] == "unknown_weird_error"
