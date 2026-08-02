from __future__ import annotations

import asyncio
import json
import os
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest

import agent_world.invocation.control_store as control_store_module
from agent_world.agent_profiles import AgentProfileProvider
from agent_world.config import AgentBackendConfig
from agent_world.contracts import PermissionScope
from agent_world.invocation import (
    CodexSdkBackend,
    InvocationControlPlane,
    InvocationControlStore,
    InvocationError,
    InvocationLifecyclePhase,
    InvocationLimits,
    InvocationOwnerKind,
    InvocationOwnership,
    InvocationRequest,
    InvocationResult,
    InvocationStatus,
    NodeCapabilityRequirement,
)


class _LifecycleBackend:
    supported_executor_revision_ids = ("framework.executor.v1",)

    def __init__(self) -> None:
        self.requests: list[InvocationRequest] = []
        self.cancelled: list[str] = []

    async def invoke(self, request: InvocationRequest) -> InvocationResult:
        self.requests.append(request)
        assert request.lifecycle_sink is not None
        request.lifecycle_sink.local(InvocationLifecyclePhase.PROFILE_VERIFIED)
        request.lifecycle_sink.local(InvocationLifecyclePhase.DIRECT_DISPATCHED)
        request.lifecycle_sink.provider_progress("direct_provider_event")
        return InvocationResult(
            invocation_id=request.invocation_id,
            status=InvocationStatus.COMPLETED,
            session=None,
            turn_id=None,
            final_text=None,
            structured_output={"title": "ok"},
            usage=None,
            events=(),
            error=None,
            duration_ms=1,
            backend_version="test",
        )

    async def cancel(self, invocation_id: str) -> bool:
        self.cancelled.append(invocation_id)
        return True


class _BlockingBackend(_LifecycleBackend):
    async def invoke(self, request: InvocationRequest) -> InvocationResult:
        self.requests.append(request)
        assert request.lifecycle_sink is not None
        request.lifecycle_sink.local(InvocationLifecyclePhase.WORKER_SPAWNED)
        await asyncio.Event().wait()
        raise AssertionError("blocking control backend unexpectedly resumed")


def _request(tmp_path: Path, *, invocation_id: str = "control-plane-test") -> InvocationRequest:
    provider = AgentProfileProvider(
        AgentBackendConfig(
            model="control-plane-test-model",
            api_key_environment="OPENAI_API_KEY",
            openai_base_url_environment="OPENAI_BASE_URL",
        ),
        source_environment={
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "OPENAI_API_KEY": uuid4().hex,
            "OPENAI_BASE_URL": f"https://{uuid4().hex}.invalid/v1",
        },
    )
    profile = provider.resolve(
        role="researcher",
        lineage_id="invocation-control-test",
        workspace=tmp_path / "researcher",
        output_schema={
            "type": "object",
            "properties": {"title": {"type": "string"}},
            "required": ["title"],
            "additionalProperties": False,
        },
        permissions=PermissionScope(),
        requirement=NodeCapabilityRequirement.structured_output(
            node_id="researcher.invocation-control-test",
            role="researcher",
        ),
        rollout_token_limit=123,
    )
    return InvocationRequest(
        invocation_id=invocation_id,
        prompt="private prompt text must not enter the physical-attempt record",
        profile=profile,
        ownership=InvocationOwnership(
            owner_kind=InvocationOwnerKind.WORK_OPERATION,
            owner_id="operation:control-plane-test",
            scope_id="scope:control-plane-test",
            coordinate="design:world_rules",
            immutable_input_closure_digest="a" * 64,
        ),
    )


@pytest.mark.asyncio
async def test_control_plane_records_real_adapter_lifecycle_without_provider_text(
    tmp_path: Path,
) -> None:
    backend = _LifecycleBackend()
    store = InvocationControlStore(tmp_path / "invocation-control")
    control = InvocationControlPlane(backend, store, require_explicit_ownership=True)
    request = _request(tmp_path)

    result = await control.invoke(request)

    assert result.succeeded
    record = store.read(request.invocation_id)
    assert record is not None
    assert record.settled
    assert record.owner.owner_kind is InvocationOwnerKind.WORK_OPERATION
    assert record.owner.immutable_input_closure_digest == "a" * 64
    assert record.provider_progress_count == 1
    assert record.first_provider_progress_at is not None
    assert record.last_provider_progress_at is not None
    assert record.last_provider_progress_at >= record.first_provider_progress_at
    assert record.last_local_activity_at is not None
    assert record.last_provider_activity == "direct_provider_event"
    assert record.terminal is not None
    assert record.terminal.status is InvocationStatus.COMPLETED
    assert record.request_shape is not None
    assert record.request_shape.prompt_bytes == len(request.prompt.encode("utf-8"))
    assert record.request_shape.runtime_skill_count == len(request.profile.skills)
    assert record.request_shape.output_schema_bytes is not None
    assert record.request_shape.execution_mode == "agentic"
    assert not record.request_shape.continued_session
    serialized = next((tmp_path / "invocation-control" / "attempts").glob("*.json")).read_text(
        encoding="utf-8"
    )
    assert "OPENAI_API_KEY" not in serialized
    assert "private prompt text" not in serialized
    assert "first_provider_progress_at" in serialized
    assert "last_provider_progress_at" in serialized


def test_reconcile_owner_loss_rejects_a_reused_or_cross_namespace_pid(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A numeric PID match alone cannot keep an orphan invocation running."""

    identities = iter(("a" * 64, "b" * 64))
    monkeypatch.setattr(
        control_store_module,
        "_process_identity_for_pid",
        lambda _pid: next(identities),
    )
    store = InvocationControlStore(tmp_path / "invocation-control")
    request = _request(tmp_path, invocation_id="control-plane-pid-identity")
    assert request.ownership is not None
    record = store.begin(
        invocation_id=request.invocation_id,
        owner=request.ownership,
        route="codex_sdk",
        model=request.profile.model,
        profile_digest=f"sha256:{request.profile.profile_hash}",
        envelope_digest="c" * 64,
        declared_wall_seconds=30,
    )

    assert record.owner_process_identity_kind == "linux_proc"
    settled = store.reconcile_owner_loss()

    assert len(settled) == 1
    assert settled[0].terminal is not None
    assert settled[0].terminal.code == "owner_process_interrupted"
    assert store.read(request.invocation_id) == settled[0]


def test_reconcile_owner_loss_keeps_the_exact_live_process_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The same process birth identity remains a live owner."""

    monkeypatch.setattr(control_store_module, "_process_identity_for_pid", lambda _pid: "a" * 64)
    store = InvocationControlStore(tmp_path / "invocation-control")
    request = _request(tmp_path, invocation_id="control-plane-live-owner")
    assert request.ownership is not None
    store.begin(
        invocation_id=request.invocation_id,
        owner=request.ownership,
        route="codex_sdk",
        model=request.profile.model,
        profile_digest=f"sha256:{request.profile.profile_hash}",
        envelope_digest="e" * 64,
        declared_wall_seconds=30,
    )

    assert store.reconcile_owner_loss() == ()
    record = store.read(request.invocation_id)
    assert record is not None and not record.settled


def test_reconcile_owner_loss_fails_closed_for_pre_identity_running_record(
    tmp_path: Path,
) -> None:
    """A schema-v2 active record cannot safely survive a PID reuse boundary."""

    store = InvocationControlStore(tmp_path / "invocation-control")
    request = _request(tmp_path, invocation_id="control-plane-legacy-owner")
    assert request.ownership is not None
    store.begin(
        invocation_id=request.invocation_id,
        owner=request.ownership,
        route="codex_sdk",
        model=request.profile.model,
        profile_digest=f"sha256:{request.profile.profile_hash}",
        envelope_digest="d" * 64,
        declared_wall_seconds=30,
    )
    record_path = next((tmp_path / "invocation-control" / "attempts").glob("*.json"))
    legacy = json.loads(record_path.read_text(encoding="utf-8"))
    legacy["schema_version"] = 2
    legacy.pop("owner_process_identity_kind")
    legacy.pop("owner_process_identity")
    legacy.pop("request_shape")
    record_path.write_text(json.dumps(legacy), encoding="utf-8")

    settled = store.reconcile_owner_loss()

    assert len(settled) == 1
    assert settled[0].terminal is not None
    assert settled[0].terminal.code == "owner_process_interrupted"


@pytest.mark.asyncio
async def test_control_plane_rejects_ownerless_call_before_adapter_invocation(
    tmp_path: Path,
) -> None:
    backend = _LifecycleBackend()
    control = InvocationControlPlane(
        backend,
        InvocationControlStore(tmp_path / "invocation-control"),
        require_explicit_ownership=True,
    )
    request = replace(_request(tmp_path), ownership=None)

    result = await control.invoke(request)

    assert result.status is InvocationStatus.FAILED
    assert result.error == InvocationError(
        code="invocation_owner_missing",
        message="invocation_owner_missing",
        retryable=False,
    )
    assert backend.requests == []


@pytest.mark.asyncio
async def test_declared_wall_terminalizes_stuck_backend_without_provider_progress(
    tmp_path: Path,
) -> None:
    backend = _BlockingBackend()
    store = InvocationControlStore(tmp_path / "invocation-control")
    control = InvocationControlPlane(backend, store, require_explicit_ownership=True)
    request = _request(tmp_path, invocation_id="control-plane-declared-wall")
    request = replace(
        request,
        profile=replace(
            request.profile,
            limits=InvocationLimits(
                timeout_seconds=0.01,
                interrupt_grace_seconds=0.01,
                kill_grace_seconds=0.01,
            ),
        ),
    )

    result = await asyncio.wait_for(control.invoke(request), timeout=1.0)

    assert result.status is InvocationStatus.TIMED_OUT
    assert result.error is not None
    assert result.error.code == "declared_wall_expired"
    assert backend.cancelled == [request.invocation_id]
    record = store.read(request.invocation_id)
    assert record is not None and record.settled
    assert record.provider_progress_count == 0
    assert record.terminal is not None
    assert record.terminal.code == "declared_wall_expired"


@pytest.mark.asyncio
async def test_declared_wall_kills_a_real_blocking_codex_worker_and_settles_once(
    tmp_path: Path,
) -> None:
    """Exercise the real parent/child protocol, not a mocked adapter task.

    The child receives the normal worker payload, records a safe local phase,
    then deliberately ignores graceful termination.  The only timeout in this
    proof is the fixture profile's declared physical envelope; the assertion
    proves that the control-plane terminal is durable and the actual child PID
    has been reaped without pretending a local lifecycle event was Provider
    progress.
    """

    worker = (Path(__file__).parent / "fixtures" / "blocking_codex_worker.py").resolve(strict=True)
    backend = CodexSdkBackend()
    backend._worker_path = worker
    store = InvocationControlStore(tmp_path / "invocation-control")
    control = InvocationControlPlane(backend, store, require_explicit_ownership=True)
    request = _request(tmp_path, invocation_id="control-plane-real-blocking-worker")
    request = replace(
        request,
        profile=replace(
            request.profile,
            limits=InvocationLimits(
                timeout_seconds=0.05,
                interrupt_grace_seconds=0.01,
                kill_grace_seconds=0.01,
            ),
        ),
    )

    result = await control.invoke(request)

    assert result.status is InvocationStatus.TIMED_OUT
    assert result.error is not None
    assert result.error.code == "declared_wall_expired"
    marker = request.profile.workspace / ".blocking-worker-pid"
    assert marker.is_file()
    worker_pid = int(marker.read_text(encoding="utf-8"))
    with pytest.raises(ProcessLookupError):
        os.kill(worker_pid, 0)
    assert backend._active == {}
    record = store.read(request.invocation_id)
    assert record is not None and record.settled
    assert record.provider_progress_count == 0
    assert record.terminal is not None
    assert record.terminal.code == "declared_wall_expired"
    serialized = next((tmp_path / "invocation-control" / "attempts").glob("*.json")).read_text(
        encoding="utf-8"
    )
    assert str(request.profile.workspace) not in serialized
    assert ".blocking-worker-pid" not in serialized


@pytest.mark.asyncio
async def test_codex_first_provider_event_bound_settles_a_real_silent_worker(
    tmp_path: Path,
) -> None:
    """A started Codex worker cannot consume the declared wall with zero events.

    Boundary: the production control plane -> production Codex parent/worker
    protocol -> controlled child process. The child receives the normal payload,
    writes its PID, and emits ``sdk_session_open`` but no Provider event. That
    exact distinction mirrors the real Candidate stall: Prompt and mounted Skill
    delivery remain unproven, while the control plane must still obtain a safe,
    retryable transport terminal and reap the process group.
    """

    worker = (Path(__file__).parent / "fixtures" / "blocking_codex_worker.py").resolve(strict=True)
    backend = CodexSdkBackend()
    backend._worker_path = worker
    store = InvocationControlStore(tmp_path / "invocation-control")
    control = InvocationControlPlane(backend, store, require_explicit_ownership=True)
    request = _request(tmp_path, invocation_id="control-plane-codex-no-first-event")
    request = replace(
        request,
        profile=replace(
            request.profile,
            limits=InvocationLimits(
                timeout_seconds=30.0,
                provider_first_event_timeout_seconds=0.2,
                interrupt_grace_seconds=0.01,
                kill_grace_seconds=0.01,
            ),
        ),
    )

    result = await asyncio.wait_for(control.invoke(request), timeout=2.0)

    assert result.status is InvocationStatus.FAILED
    assert result.error is not None
    assert result.error.code == "codex_no_first_provider_event"
    assert result.error.retryable is True
    assert result.error.details == {
        "waiting_phase": "parent_waiting",
        "first_event_timeout_seconds": 0.2,
        "observed_provider_event_count": 0,
    }
    marker = request.profile.workspace / ".blocking-worker-pid"
    assert marker.is_file()
    worker_pid = int(marker.read_text(encoding="utf-8"))
    with pytest.raises(ProcessLookupError):
        os.kill(worker_pid, 0)
    assert backend._active == {}
    record = store.read(request.invocation_id)
    assert record is not None and record.settled
    assert record.provider_progress_count == 0
    # Settlement intentionally becomes the last local phase. The count proves
    # the child lifecycle entered the normal parent/worker path before that
    # terminal projection; it must not be mistaken for Provider progress.
    assert record.local_event_count >= 6
    assert record.last_local_phase is InvocationLifecyclePhase.TERMINAL_RECEIVED
    assert record.terminal is not None
    assert record.terminal.code == "codex_no_first_provider_event"
    assert record.terminal.retryable is True
    serialized = next((tmp_path / "invocation-control" / "attempts").glob("*.json")).read_text(
        encoding="utf-8"
    )
    assert str(request.profile.workspace) not in serialized
    assert ".blocking-worker-pid" not in serialized


@pytest.mark.asyncio
async def test_codex_started_stream_idle_bound_settles_a_real_stalling_worker(
    tmp_path: Path,
) -> None:
    """A real post-progress Codex stall gets a safe retryable terminal.

    Boundary: production control plane -> production Codex parent/worker
    protocol -> controlled child. The worker emits exactly one valid Provider
    event, then refuses graceful termination. This proves that the parent-side
    generic stream-idle policy reaps the actual process group, settles the
    control record, and never turns the framework's worker topology into
    Candidate feedback.
    """

    worker = (
        Path(__file__).parent / "fixtures" / "started_stalling_codex_worker.py"
    ).resolve(strict=True)
    backend = CodexSdkBackend()
    backend._worker_path = worker
    store = InvocationControlStore(tmp_path / "invocation-control")
    control = InvocationControlPlane(backend, store, require_explicit_ownership=True)
    request = _request(tmp_path, invocation_id="control-plane-codex-started-stream-idle")
    request = replace(
        request,
        profile=replace(
            request.profile,
            limits=InvocationLimits(
                timeout_seconds=30.0,
                provider_first_event_timeout_seconds=0.2,
                provider_stream_idle_timeout_seconds=0.05,
                interrupt_grace_seconds=0.01,
                kill_grace_seconds=0.01,
            ),
        ),
    )

    result = await asyncio.wait_for(control.invoke(request), timeout=2.0)

    assert result.status is InvocationStatus.FAILED
    assert result.error is not None
    assert result.error.code == "codex_provider_stream_stalled"
    assert result.error.retryable is True
    assert result.error.details == {
        "waiting_phase": "parent_awaiting_worker_result",
        "idle_timeout_seconds": 0.05,
        "observed_provider_event_count": 1,
    }
    marker = request.profile.workspace / ".started-stalling-worker-pid"
    assert marker.is_file()
    worker_pid = int(marker.read_text(encoding="utf-8"))
    with pytest.raises(ProcessLookupError):
        os.kill(worker_pid, 0)
    assert backend._active == {}
    record = store.read(request.invocation_id)
    assert record is not None and record.settled
    assert record.provider_progress_count == 1
    assert record.terminal is not None
    assert record.terminal.code == "codex_provider_stream_stalled"
    assert record.terminal.retryable is True
    serialized = next((tmp_path / "invocation-control" / "attempts").glob("*.json")).read_text(
        encoding="utf-8"
    )
    assert str(request.profile.workspace) not in serialized
    assert ".started-stalling-worker-pid" not in serialized
