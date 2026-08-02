"""Shared transport-liveness primitives for real Provider adapters.

The first-event budget answers whether a request reached a Provider at all.
``ProviderProgressWatch`` answers the separate question of whether a started
Provider stream stopped producing validated events.  Neither primitive limits
model output or reasoning; both are adapter-side liveness facts.
"""

from __future__ import annotations

import asyncio
import time


class ProviderFirstEventBudget:
    """One monotonic deadline shared by all pre-Provider-event waits."""

    __slots__ = ("_deadline", "timeout_seconds")

    def __init__(self, timeout_seconds: float | None) -> None:
        self.timeout_seconds = timeout_seconds
        self._deadline = None if timeout_seconds is None else time.monotonic() + timeout_seconds

    @property
    def enabled(self) -> bool:
        return self._deadline is not None

    def remaining(self) -> float | None:
        if self._deadline is None:
            return None
        return self._deadline - time.monotonic()


class ProviderProgressWatch:
    """Observe validated Provider events without retaining their contents.

    The parent adapter owns this watch because it can terminate an entire
    worker process tree.  A count is enough: it proves that progress happened
    and lets the adapter identify a subsequent no-progress interval without
    retaining model text, paths, or private worker protocol data.
    """

    __slots__ = ("_changed", "_count")

    def __init__(self) -> None:
        self._changed = asyncio.Event()
        self._count = 0

    @property
    def count(self) -> int:
        return self._count

    def observe(self) -> None:
        """Record one already-validated Provider event."""

        self._count += 1
        self._changed.set()

    async def wait_for_first_progress(self) -> None:
        """Wait until at least one validated Provider event is observed."""

        observed = self._count
        while observed == 0:
            self._changed.clear()
            if self._count != observed:
                observed = self._count
                continue
            await self._changed.wait()
            observed = self._count

    async def wait_for_started_stream_stall(self, idle_timeout_seconds: float) -> int:
        """Return the stable event count after a started stream goes silent.

        This intentionally waits indefinitely for a first event when the
        caller disables its first-event policy.  Once the first event exists,
        every subsequent quiet interval is bounded by ``idle_timeout_seconds``.
        The count is rechecked around clearing the event so a concurrent event
        cannot be lost between observation and waiting.
        """

        await self.wait_for_first_progress()
        observed = self._count
        while True:
            self._changed.clear()
            if self._count != observed:
                observed = self._count
                continue
            try:
                await asyncio.wait_for(self._changed.wait(), timeout=idle_timeout_seconds)
            except TimeoutError:
                if self._count == observed:
                    return observed
            else:
                observed = self._count


__all__ = ["ProviderFirstEventBudget", "ProviderProgressWatch"]
