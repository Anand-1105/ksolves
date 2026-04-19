from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent.state import SessionRecord


class SessionMemory:
    """In-memory cross-ticket session store.

    Persists for the lifetime of a single agent run and is cleared between
    runs via :meth:`clear`.  All async methods hold an ``asyncio.Lock`` so
    concurrent ticket coroutines cannot corrupt the store.
    """

    def __init__(self) -> None:
        self._store: dict[str, list[dict]] = {}
        self._lock: asyncio.Lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Async read / write (lock-protected)
    # ------------------------------------------------------------------

    async def get(self, customer_id: str) -> list[dict]:
        """Return a *copy* of all session records for *customer_id*.

        Returns an empty list when no records exist for the customer.
        The lock is held for the duration of the read.
        """
        async with self._lock:
            records = self._store.get(customer_id, [])
            return list(records)  # shallow copy — dicts are not mutated

    async def write(self, customer_id: str, record: dict) -> None:
        """Append *record* to the list of records for *customer_id*.

        The lock is held for the duration of the write.
        """
        async with self._lock:
            if customer_id not in self._store:
                self._store[customer_id] = []
            self._store[customer_id].append(record)

    # ------------------------------------------------------------------
    # Synchronous helpers
    # ------------------------------------------------------------------

    def clear(self) -> None:
        """Reset the store to an empty dict.

        Synchronous — intended to be called between agent runs from a
        single-threaded context (i.e. before ``asyncio.gather`` is
        invoked for the next batch of tickets).
        """
        self._store = {}

    def has_fraud_flag(self, customer_id: str) -> bool:
        """Return ``True`` if any prior record for *customer_id* carries a
        fraud-related escalation.

        Specifically returns ``True`` when at least one record satisfies
        either of the following conditions:

        * ``record["escalation_category"]`` is ``"threat_detected"`` or
          ``"social_engineering"``
        * ``record["fraud_flags"]`` (a list) contains ``"threat_detected"``
          or ``"social_engineering"``

        .. warning::
            This method reads ``_store`` **without** acquiring the lock.
            It is only safe to call from a single-threaded context after
            all concurrent writes have completed (e.g. after
            ``asyncio.gather`` returns).
        """
        _fraud_categories = {"threat_detected", "social_engineering"}

        for record in self._store.get(customer_id, []):
            # Check escalation_category field
            if record.get("escalation_category") in _fraud_categories:
                return True

            # Check fraud_flags list
            fraud_flags = record.get("fraud_flags", [])
            if isinstance(fraud_flags, list):
                if any(flag in _fraud_categories for flag in fraud_flags):
                    return True

        return False
