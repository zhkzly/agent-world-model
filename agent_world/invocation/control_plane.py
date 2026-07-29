"""One parent-side lifecycle supervisor around real invocation adapters.

The control plane owns only physical invocation facts: durable admission,
local/provider-progress distinction, declared-wall enforcement, cancellation,
and exactly-once terminal projection.  It deliberately does *not* choose a
semantic repair, retry, fallback, Prompt, Runtime Skill, or release decision.
Those remain Scheduler/WorkRuntime responsibilities once they have a complete
terminal fact.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from dataclasses import replace
from typing import Literal

from .contracts import (
    InvocationBackend,
    InvocationError,
    InvocationLifecyclePhase,
    InvocationLifecycleSink,
    InvocationLifecycleSupervision,
    InvocationOwnerKind,
    InvocationOwnership,
    InvocationRequest,
    InvocationResult,
    InvocationStatus,
)
from .control_store import (
    InvocationAlreadyActiveError,
    InvocationControlStore,
    InvocationControlStoreError,
    InvocationTerminalFact,
)

_CONTROL_PLANE_VERSION = "invocation-control-plane.v1"


class InvocationControlPlane:
    """Wrap one routed real backend with durable physical-attempt ownership."""

    # Scheduler leaves use this explicit capability marker only while callers
    # migrate away from their historical local timeout wrappers.  Production
    # composition always supplies this control plane, so it has one physical
    # lifecycle owner; test doubles and deliberately standalone adapters keep
    # their own declared-envelope guard.
    owns_declared_lifecycle = True

    def __init__(
        self,
        backend: InvocationBackend,
        store: InvocationControlStore,
        *,
        require_explicit_ownership: bool = False,
    ) -> None:
        self._backend = backend
        self.store = store
        self.require_explicit_ownership = require_explicit_ownership

    @property
    def supported_executor_revision_ids(self) -> tuple[str, ...]:
        return self._backend.supported_executor_revision_ids

    async def invoke(self, request: InvocationRequest) -> InvocationResult:
        started = time.monotonic()
        ownership = request.ownership
        if ownership is None:
            if self.require_explicit_ownership:
                return _preflight_failure(request, "invocation_owner_missing", started)
            ownership = _inferred_ownership(request)
        route = _route_for(request)
        try:
            self.store.begin(
                invocation_id=request.invocation_id,
                owner=ownership,
                route=route,
                model=request.profile.model,
                profile_digest=f"sha256:{request.profile.profile_hash}",
                envelope_digest=_envelope_digest(request),
                declared_wall_seconds=request.profile.limits.supervisor_wall_ceiling_seconds,
            )
            self.store.record_local(request.invocation_id, InvocationLifecyclePhase.ADMITTED)
        except InvocationAlreadyActiveError:
            return _preflight_failure(request, "duplicate_invocation_id", started)
        except InvocationControlStoreError:
            return _preflight_failure(request, "invocation_control_store_unavailable", started)

        sink = _StoreLifecycleSink(self.store, request.invocation_id)
        bound_request = replace(
            request,
            ownership=ownership,
            lifecycle_sink=sink,
            lifecycle_supervision=InvocationLifecycleSupervision.CONTROL_PLANE,
        )
        invocation_task = asyncio.create_task(
            self._backend.invoke(bound_request),
            name=f"invocation-control-{request.invocation_id}",
        )
        limits = request.profile.limits
        normal_lifecycle_seconds = limits.timeout_seconds + limits.interrupt_grace_seconds + 0.5
        try:
            result = await asyncio.wait_for(
                asyncio.shield(invocation_task),
                timeout=normal_lifecycle_seconds,
            )
        except TimeoutError:
            _best_effort(self.store.expire_declared_wall, request.invocation_id)
            await self._cancel_and_await_cleanup(
                request.invocation_id,
                invocation_task,
                cleanup_seconds=2 * limits.kill_grace_seconds,
            )
            result = _terminal_result(
                request,
                status=InvocationStatus.TIMED_OUT,
                code="declared_wall_expired",
                started=started,
            )
            _best_effort(self.store.settle_result, result)
            return result
        except asyncio.CancelledError:
            _best_effort(self.store.request_cancel, request.invocation_id)
            await self._cancel_and_await_cleanup(
                request.invocation_id,
                invocation_task,
                cleanup_seconds=2 * limits.kill_grace_seconds,
            )
            _best_effort(
                self.store.settle,
                request.invocation_id,
                terminal=InvocationTerminalFact(
                    status=InvocationStatus.CANCELLED,
                    code="owner_cancelled",
                    retryable=False,
                ),
                final_phase=InvocationLifecyclePhase.CLEANUP_FINISHED,
            )
            raise
        except Exception:
            _best_effort(
                self.store.settle,
                request.invocation_id,
                terminal=InvocationTerminalFact(
                    status=InvocationStatus.FAILED,
                    code="backend_raised_before_terminal",
                    retryable=False,
                ),
            )
            raise
        _best_effort(self.store.settle_result, result)
        return result

    async def cancel(self, invocation_id: str) -> bool:
        """Record cancellation intent before forwarding it to the real adapter."""

        _best_effort(self.store.request_cancel, invocation_id)
        return await self._backend.cancel(invocation_id)

    async def _cancel_and_await_cleanup(
        self,
        invocation_id: str,
        invocation_task: asyncio.Task[InvocationResult],
        *,
        cleanup_seconds: float,
    ) -> None:
        """Cancel and wait for the adapter's declared cleanup path to settle.

        A successful process-tree kill is not sufficient: adapters may still
        need their invocation coroutine to run its ``finally`` block and
        release a per-invocation handle.  Returning before that point leaves a
        dead worker visible as an active invocation, so cancellation and a
        future retry disagree about ownership.  The wait remains bounded by
        the profile-derived cleanup envelope; a truly stuck adapter is
        detached only after that declared grace is exhausted.
        """

        _best_effort(
            self.store.record_local,
            invocation_id,
            InvocationLifecyclePhase.CLEANUP_RUNNING,
        )
        cancel_task = asyncio.create_task(
            self._backend.cancel(invocation_id),
            name=f"invocation-control-cancel-{invocation_id}",
        )
        # Request cancellation before awaiting either side.  The adapter's
        # task owns its final local cleanup (for Codex, removing the worker
        # handle under its lock), while ``cancel`` owns process interruption.
        # Both must converge before the control plane publishes its terminal
        # result whenever the declared cleanup envelope permits it.
        if not invocation_task.done():
            invocation_task.cancel()
        try:
            await asyncio.wait_for(
                asyncio.gather(cancel_task, invocation_task, return_exceptions=True),
                timeout=cleanup_seconds,
            )
        except TimeoutError:
            # The profile has explicitly spent its cleanup allowance.  Leave
            # no unobserved exception behind, but do not make an unbounded
            # cleanup wait part of a caller's declared lifecycle.
            for task in (cancel_task, invocation_task):
                if not task.done():
                    task.cancel()
                    task.add_done_callback(_consume_task_result)
        finally:
            _best_effort(
                self.store.record_local,
                invocation_id,
                InvocationLifecyclePhase.CLEANUP_FINISHED,
            )


class _StoreLifecycleSink(InvocationLifecycleSink):
    """Never let best-effort observation corrupt a live adapter protocol."""

    def __init__(self, store: InvocationControlStore, invocation_id: str) -> None:
        self._store = store
        self._invocation_id = invocation_id

    def local(self, phase: InvocationLifecyclePhase) -> None:
        _best_effort(self._store.record_local, self._invocation_id, phase)

    def provider_progress(self, activity: str = "provider_event") -> None:
        _best_effort(
            self._store.record_provider_progress,
            self._invocation_id,
            activity=activity,
        )


def _route_for(request: InvocationRequest) -> Literal["codex_sdk", "direct_llm"]:
    if (
        request.execution_mode.value == "single_shot_structured"
        and not request.profile.allowed_builtin_tools
    ):
        return "direct_llm"
    return "codex_sdk"


def _envelope_digest(request: InvocationRequest) -> str:
    limits = request.profile.limits
    safe_envelope = {
        "profile_hash": request.profile.profile_hash,
        "execution_mode": request.execution_mode.value,
        "timeout_seconds": limits.timeout_seconds,
        "interrupt_grace_seconds": limits.interrupt_grace_seconds,
        "kill_grace_seconds": limits.kill_grace_seconds,
        "rollout_token_limit": request.profile.rollout_token_limit,
    }
    encoded = json.dumps(safe_envelope, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _inferred_ownership(request: InvocationRequest) -> InvocationOwnership:
    """Bridge old callers while preserving a visible migration signal.

    The fallback is intentionally deterministic and safe, but it grants no
    retry authority.  Scheduler leaves should pass explicit Work ownership as
    they migrate; callers without durable operation identity remain clearly
    marked ``standalone_component`` rather than silently sharing a session.
    """

    metadata = request.metadata
    work_id = metadata.get("work_id")
    coordinate = metadata.get("coordinate")
    dispatch_id = metadata.get("dispatch_id")
    if (
        isinstance(work_id, str)
        and bool(work_id)
        and isinstance(coordinate, str)
        and bool(coordinate)
        and isinstance(dispatch_id, str)
        and bool(dispatch_id)
    ):
        return InvocationOwnership(
            owner_kind=InvocationOwnerKind.WORK_OPERATION,
            owner_id=dispatch_id,
            scope_id=work_id,
            coordinate=coordinate,
        )
    run_id = metadata.get("run_id")
    transaction = metadata.get("semantic_transaction")
    if (
        isinstance(run_id, str)
        and run_id
        and isinstance(transaction, str)
        and transaction.startswith("invocation_audit")
    ):
        return InvocationOwnership(
            owner_kind=InvocationOwnerKind.DIAGNOSTIC_AUDIT,
            owner_id=request.invocation_id,
            scope_id=run_id,
            coordinate=transaction,
        )
    return InvocationOwnership(
        owner_kind=InvocationOwnerKind.STANDALONE_COMPONENT,
        owner_id=request.invocation_id,
        scope_id="invocation_control",
    )


def _preflight_failure(
    request: InvocationRequest,
    code: str,
    started: float,
) -> InvocationResult:
    return _terminal_result(
        request,
        status=InvocationStatus.FAILED,
        code=code,
        started=started,
    )


def _terminal_result(
    request: InvocationRequest,
    *,
    status: InvocationStatus,
    code: str,
    started: float,
) -> InvocationResult:
    return InvocationResult(
        invocation_id=request.invocation_id,
        status=status,
        session=None,
        turn_id=None,
        final_text=None,
        structured_output=None,
        usage=None,
        events=(),
        error=InvocationError(code=code, message=code, retryable=False),
        duration_ms=max(0, int((time.monotonic() - started) * 1000)),
        backend_version=_CONTROL_PLANE_VERSION,
    )


def _best_effort(callback: object, *args: object, **kwargs: object) -> None:
    try:
        callable_callback = callback
        if callable(callable_callback):
            callable_callback(*args, **kwargs)
    except InvocationControlStoreError:
        return


def _consume_task_result(task: asyncio.Task[object]) -> None:
    try:
        task.result()
    except (asyncio.CancelledError, Exception):
        return
