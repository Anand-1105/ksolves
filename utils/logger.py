"""
utils/logger.py — TraceLogger

Thread-safe (asyncio-safe) writer for trace_log.jsonl.
Emits one JSON object per line, immediately on each call.
"""

from __future__ import annotations

import asyncio
import atexit
import datetime
import json
from typing import Optional


class TraceLogger:
    """
    Async-safe trace event writer.

    Opens `trace_log.jsonl` in append mode at construction.
    All writes are protected by an asyncio.Lock to prevent
    interleaved JSON lines when multiple coroutines write concurrently.
    """

    def __init__(self, path: str = "trace_log.jsonl") -> None:
        self._path = path
        self._file = open(path, "a", encoding="utf-8")  # noqa: WPS515
        self._lock = asyncio.Lock()
        atexit.register(self.close)

    # ------------------------------------------------------------------
    # Core emit
    # ------------------------------------------------------------------

    async def emit(self, event_type: str, ticket_id: str, payload: dict) -> None:
        """
        Serialize and write a single trace event as a JSON line.

        Holds the asyncio lock for the entire duration of the write so
        that concurrent coroutines never produce interleaved output.
        """
        timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
        record = {
            "event_type": event_type,
            "ticket_id": ticket_id,
            "timestamp": timestamp,
            "payload": payload,
        }
        line = json.dumps(record, default=str) + "\n"
        async with self._lock:
            self._file.write(line)
            self._file.flush()

    # ------------------------------------------------------------------
    # Convenience methods
    # ------------------------------------------------------------------

    async def ticket_ingested(self, ticket_id: str, ticket: dict) -> None:
        """Emits a ticket_ingested event with issue_type and customer_id."""
        await self.emit(
            "ticket_ingested",
            ticket_id,
            {
                "issue_type": ticket.get("issue_type"),
                "customer_id": ticket.get("customer_id"),
            },
        )

    async def tool_call_before(self, ticket_id: str, tool_name: str, args: dict) -> None:
        """Emits a tool_call_before event with tool name and input args."""
        await self.emit(
            "tool_call_before",
            ticket_id,
            {"tool_name": tool_name, "args": args},
        )

    async def tool_call_after(self, ticket_id: str, tool_name: str, result: dict) -> None:
        """Emits a tool_call_after event with tool name and result."""
        await self.emit(
            "tool_call_after",
            ticket_id,
            {"tool_name": tool_name, "result": result},
        )

    async def decision_evaluated(self, ticket_id: str, question: str, value: bool) -> None:
        """Emits a decision_evaluated event for Q1/Q2/Q3."""
        await self.emit(
            "decision_evaluated",
            ticket_id,
            {"question": question, "value": value},
        )

    async def confidence_computed(self, ticket_id: str, score: float, factors: dict) -> None:
        """Emits a confidence_computed event with score and factor breakdown."""
        await self.emit(
            "confidence_computed",
            ticket_id,
            {"score": score, "factors": factors},
        )

    async def checkpoint_emitted(self, ticket_id: str, checkpoint: dict) -> None:
        """Emits a checkpoint_emitted event; payload is the full checkpoint record."""
        await self.emit("checkpoint_emitted", ticket_id, checkpoint)

    async def resolution_final(
        self,
        ticket_id: str,
        resolution: str,
        category: Optional[str] = None,
    ) -> None:
        """Emits a resolution_final event with the resolution and optional category."""
        await self.emit(
            "resolution_final",
            ticket_id,
            {"resolution": resolution, "category": category},
        )

    async def replan_triggered(
        self, ticket_id: str, trigger: str, alternative_path: str
    ) -> None:
        """Emits a replan_triggered event describing why and what alternative was chosen."""
        await self.emit(
            "replan_triggered",
            ticket_id,
            {"trigger": trigger, "alternative_path": alternative_path},
        )

    async def replan_outcome(self, ticket_id: str, outcome: str) -> None:
        """Emits a replan_outcome event with the result of the replan attempt."""
        await self.emit(
            "replan_outcome",
            ticket_id,
            {"outcome": outcome},
        )

    async def session_memory_read(
        self, ticket_id: str, customer_id: str, records_count: int
    ) -> None:
        """Emits a session_memory_read event with customer_id and number of prior records."""
        await self.emit(
            "session_memory_read",
            ticket_id,
            {"customer_id": customer_id, "records_count": records_count},
        )

    async def session_memory_write(
        self, ticket_id: str, customer_id: str, resolution: str
    ) -> None:
        """Emits a session_memory_write event after writing a resolution to session memory."""
        await self.emit(
            "session_memory_write",
            ticket_id,
            {"customer_id": customer_id, "resolution": resolution},
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Close the underlying file handle."""
        self._file.close()
