"""Fail-closed routing between the two real invocation adapters.

The router is the one production selection point. Pipeline code continues to
depend on :class:`InvocationBackend` and cannot reach an SDK client directly.
Direct requests need an explicit one-shot declaration in addition to a
tool-free, structured profile, so a future continuation cannot silently lose
its session semantics.
"""

from __future__ import annotations

import asyncio

from .contracts import (
    InvocationBackend,
    InvocationExecutionMode,
    InvocationRequest,
    InvocationResult,
)


class RoutedInvocationBackend:
    """Select one real backend without fallback or semantic reinterpretation."""

    def __init__(
        self,
        *,
        codex_backend: InvocationBackend,
        direct_backend: InvocationBackend,
        max_concurrent_invocations: int = 1,
    ) -> None:
        if not 1 <= max_concurrent_invocations <= 32:
            raise ValueError("max_concurrent_invocations must be between 1 and 32")
        self.codex_backend = codex_backend
        self.direct_backend = direct_backend
        # Each nested adapter retains its own lifecycle/cancellation guard.
        # This outer semaphore is the single application-wide admission limit;
        # otherwise one Codex and one Direct call could exceed configuration.
        self._capacity = asyncio.Semaphore(max_concurrent_invocations)

    @property
    def supported_executor_revision_ids(self) -> tuple[str, ...]:
        """Expose every revision that the selected backend can execute."""

        revisions = (
            *self.codex_backend.supported_executor_revision_ids,
            *self.direct_backend.supported_executor_revision_ids,
        )
        return tuple(dict.fromkeys(revisions))

    async def invoke(self, request: InvocationRequest) -> InvocationResult:
        """Execute the selected transport exactly once.

        A Direct failure stays a Direct failure. Retrying or changing transport
        is Scheduler policy and must retain an explicit new request.
        """

        async with self._capacity:
            return await self._backend_for(request).invoke(request)

    async def cancel(self, invocation_id: str) -> bool:
        """Forward cancellation to both adapters without exposing routing state."""

        codex_cancelled, direct_cancelled = await asyncio.gather(
            self.codex_backend.cancel(invocation_id),
            self.direct_backend.cancel(invocation_id),
        )
        return codex_cancelled or direct_cancelled

    def _backend_for(self, request: InvocationRequest) -> InvocationBackend:
        if _is_direct_request(request):
            return self.direct_backend
        return self.codex_backend


def _is_direct_request(request: InvocationRequest) -> bool:
    """Return true only for the intentionally narrow Direct execution shape."""

    return (
        request.execution_mode is InvocationExecutionMode.SINGLE_SHOT_STRUCTURED
        and request.session is None
        and not request.profile.allowed_builtin_tools
        and request.profile.output_schema is not None
    )


__all__ = ["RoutedInvocationBackend"]
