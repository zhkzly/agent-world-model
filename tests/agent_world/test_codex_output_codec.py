from __future__ import annotations

import asyncio
import json
import time
from dataclasses import replace
from pathlib import Path

import pytest

from agent_world.agent_profiles import IsolatedAgentProfileProvider
from agent_world.config import AgentBackendConfig
from agent_world.contracts import PermissionScope
from agent_world.designer.models import (
    EnvironmentSemanticSourceDraft,
    ExpansionDesignDraft,
    ToolSchemaIRDraft,
    ToolStateTransitionDraft,
)
from agent_world.invocation import (
    InvocationLimits,
    InvocationRequest,
    InvocationResult,
    InvocationStatus,
    NodeCapabilityRequirement,
)
from agent_world.invocation.codex_sdk import (
    CodexSdkBackend,
    _decode_provider_json_ir,
    _provider_output_schema,
)


def _request(tmp_path: Path) -> InvocationRequest:
    provider = IsolatedAgentProfileProvider(
        AgentBackendConfig(
            model="configured-real-model",
            api_key_environment="AGENT_WORLD_TEST_MODEL_KEY",
        ),
        source_environment={
            "PATH": "/usr/bin:/bin",
            "AGENT_WORLD_TEST_MODEL_KEY": "test-model-credential",
        },
    )
    logical_schema = {
        "type": "object",
        "properties": {
            "language": {"type": "string", "default": "all"},
            "dynamic": {
                "type": "object",
                "additionalProperties": {"type": "string"},
            },
        },
        "required": ["dynamic"],
        "additionalProperties": False,
    }
    profile = provider.resolve(
        role="researcher",
        lineage_id="codec-contract",
        workspace=tmp_path / "researcher",
        output_schema=logical_schema,
        permissions=PermissionScope(),
        requirement=NodeCapabilityRequirement.structured_read(
            node_id="researcher.codec-contract",
            role="researcher",
        ),
    )
    return InvocationRequest(
        invocation_id="codec-contract-invocation",
        prompt="Produce the requested artifact.",
        profile=profile,
    )


def _completed_result(invocation_id: str, *, duration_ms: int = 1) -> InvocationResult:
    return InvocationResult(
        invocation_id=invocation_id,
        status=InvocationStatus.COMPLETED,
        session=None,
        turn_id="turn:test",
        final_text="completed",
        structured_output=None,
        usage=None,
        events=(),
        error=None,
        duration_ms=duration_ms,
        backend_version="test",
    )


def test_worker_payload_passes_logical_schema_directly_to_codex_sdk(
    tmp_path: Path,
) -> None:
    request = _request(tmp_path)

    payload = CodexSdkBackend._worker_payload(request)

    assert payload["output_schema"] == _provider_output_schema(
        request.profile.output_schema or {}
    )
    assert payload["prompt"] == request.prompt
    assert payload["output_schema"]["properties"]["dynamic"] == {
        "$ref": "#/$defs/AgentWorldJsonObjectIR"
    }
    assert request.profile.output_schema == {
        "type": "object",
        "properties": {
            "language": {"type": "string", "default": "all"},
            "dynamic": {
                "type": "object",
                "additionalProperties": {"type": "string"},
            },
        },
        "required": ["dynamic"],
        "additionalProperties": False,
    }


@pytest.mark.asyncio
async def test_profile_io_error_is_a_bounded_retryable_backend_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _request(tmp_path)

    def fail_profile_io(_: object) -> None:
        raise OSError("transient profile filesystem failure")

    monkeypatch.setattr(
        "agent_world.invocation.codex_sdk.verify_resolved_profile",
        fail_profile_io,
    )

    result = await CodexSdkBackend().invoke(request)

    assert result.status is InvocationStatus.FAILED
    assert result.error is not None
    assert result.error.code == "profile_io_error"
    assert result.error.retryable is True


@pytest.mark.asyncio
async def test_started_worker_protocol_error_is_retryable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _request(tmp_path)

    class FakeStdin:
        def write(self, _: bytes) -> None:
            return None

        async def drain(self) -> None:
            return None

        def close(self) -> None:
            return None

    class FakeProcess:
        def __init__(self) -> None:
            self.stdin = FakeStdin()
            self.stdout = asyncio.StreamReader()
            self.stdout.feed_data(b"not-worker-json\n")
            self.stdout.feed_eof()
            self.stderr = asyncio.StreamReader()
            self.stderr.feed_eof()
            self.returncode = 0
            self.pid = 12345

        async def wait(self) -> int:
            return 0

    async def fake_worker(*_: object, **__: object) -> FakeProcess:
        return FakeProcess()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_worker)

    result = await CodexSdkBackend().invoke(request)

    assert result.status is InvocationStatus.FAILED
    assert result.error is not None
    assert result.error.code == "worker_protocol_error"
    assert result.error.retryable is True


def test_provider_schema_compiler_closes_pydantic_objects_and_unions() -> None:
    logical = ToolStateTransitionDraft.model_json_schema(mode="validation")

    provider = _provider_output_schema(logical)

    assert provider["required"] == ["tool_id", "transition"]
    assert provider["additionalProperties"] is False
    encoded = json.dumps(provider, sort_keys=True)
    assert '"oneOf"' not in encoded
    assert '"discriminator"' not in encoded
    assert '"default"' not in encoded
    assert '"anyOf"' in encoded
    assert '"AgentWorldJsonValueIR"' in encoded
    rule = provider["$defs"]["Rule"]
    assert set(rule["required"]) == set(rule["properties"])
    assert rule["additionalProperties"] is False


def test_provider_schema_compiler_accepts_flat_tool_schema_ir() -> None:
    logical = ToolSchemaIRDraft.model_json_schema(mode="validation")

    provider = _provider_output_schema(logical)

    encoded = json.dumps(provider, sort_keys=True)
    assert provider["required"] == ["tool_id", "schema_kind", "root_node_id", "nodes"]
    assert provider["additionalProperties"] is False
    assert '"oneOf"' not in encoded
    assert '"discriminator"' not in encoded
    assert '"SchemaObjectNodeDraft"' in encoded
    assert '"SchemaUnionNodeDraft"' in encoded


@pytest.mark.parametrize(
    "model",
    [EnvironmentSemanticSourceDraft, ExpansionDesignDraft],
)
def test_provider_schema_compiler_preserves_semantic_source_authority(
    model: type[EnvironmentSemanticSourceDraft] | type[ExpansionDesignDraft],
) -> None:
    provider = _provider_output_schema(model.model_json_schema(mode="validation"))

    task = provider["$defs"]["TaskRequirementDraft"]
    semantic_source = (
        provider
        if model is EnvironmentSemanticSourceDraft
        else provider["$defs"]["EnvironmentSemanticSourceDraft"]
    )
    world_source = provider["$defs"]["WorldSemanticSourceIRDraft"]
    state_schema_ir = provider["$defs"]["StateEntitySchemaIRDraft"]
    tool_schema_ir = provider["$defs"]["ToolSchemaIRDraft"]
    assert "initial_config_schema" not in task["properties"]
    assert "public_goal_schema" not in task["properties"]
    assert "reward" not in semantic_source["properties"]
    assert "verification" not in semantic_source["properties"]
    assert "unresolved_questions" not in semantic_source["properties"]
    assert "state" not in world_source["properties"]
    assert "tools" not in world_source["properties"]
    assert "json_schema" not in state_schema_ir["properties"]
    assert "json_schema" not in tool_schema_ir["properties"]
    assert provider["additionalProperties"] is False
    if model is ExpansionDesignDraft:
        task_delta = provider["$defs"]["TaskScopeDeltaClaimDraft"]
        assert "after" not in task_delta["properties"]


def test_provider_json_ir_round_trips_nested_arbitrary_json() -> None:
    encoded = {
        "aw_kind": "object",
        "aw_entries": [
            {"aw_key": "name", "aw_value": {"aw_kind": "string", "aw_value": "hotel"}},
            {
                "aw_key": "values",
                "aw_value": {
                    "aw_kind": "array",
                    "aw_items": [
                        {"aw_kind": "number", "aw_value": 3},
                        {"aw_kind": "boolean", "aw_value": True},
                        {"aw_kind": "null"},
                    ],
                },
            },
        ],
    }

    assert _decode_provider_json_ir(encoded) == {
        "name": "hotel",
        "values": [3, True, None],
    }


@pytest.mark.asyncio
async def test_backend_capacity_queues_before_invocation_clock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = CodexSdkBackend(max_concurrent_invocations=1)
    request = _request(tmp_path)
    active = 0
    maximum_active = 0

    async def fake_invoke(
        _request: InvocationRequest,
        *,
        on_first_progress: object = None,
    ) -> InvocationResult:
        del on_first_progress
        nonlocal active, maximum_active
        active += 1
        maximum_active = max(maximum_active, active)
        await asyncio.sleep(0.01)
        active -= 1
        return _completed_result(_request.invocation_id)

    monkeypatch.setattr(backend, "_invoke_with_capacity", fake_invoke)

    await asyncio.gather(*(backend.invoke(request) for _ in range(3)))

    assert maximum_active == 1


@pytest.mark.asyncio
async def test_backend_accounts_parent_lifecycle_duration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = CodexSdkBackend()
    request = _request(tmp_path)

    async def fake_invoke(
        _request: InvocationRequest,
        *,
        on_first_progress: object = None,
    ) -> InvocationResult:
        del on_first_progress
        await asyncio.sleep(0.01)
        return _completed_result(_request.invocation_id, duration_ms=999_999)

    monkeypatch.setattr(backend, "_invoke_with_capacity", fake_invoke)

    result = await backend.invoke(request)

    assert 5 <= result.duration_ms < 1_000


@pytest.mark.asyncio
async def test_backend_deadline_covers_entire_parent_lifecycle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = CodexSdkBackend()
    base_request = _request(tmp_path)
    limits = InvocationLimits(
        timeout_seconds=0.001,
        interrupt_grace_seconds=0.001,
        kill_grace_seconds=0.001,
    )
    request = replace(base_request, profile=replace(base_request.profile, limits=limits))
    invocation_cancelled = asyncio.Event()

    async def never_finishes(
        _request: InvocationRequest,
        *,
        on_first_progress: object = None,
    ) -> InvocationResult:
        del on_first_progress
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            invocation_cancelled.set()
            raise

    monkeypatch.setattr(backend, "_invoke_with_capacity", never_finishes)
    started = time.monotonic()

    result = await backend.invoke(request)

    assert result.status is InvocationStatus.TIMED_OUT
    assert result.error is not None and result.error.code == "hard_timeout"
    assert invocation_cancelled.is_set()
    assert time.monotonic() - started < limits.supervisor_wall_ceiling_seconds + 0.2
    assert result.duration_ms >= 500


@pytest.mark.asyncio
async def test_backend_exception_closes_span_after_progress_persistence_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailingProgressSpan:
        closed = False
        terminal: tuple[str, str | None] | None = None

        def progress(self, _method: str) -> None:
            raise RuntimeError("telemetry progress unavailable")

        def finish(self, *, status: str, error_code: str | None = None) -> None:
            self.closed = True
            self.terminal = (status, error_code)

    class Telemetry:
        def __init__(self) -> None:
            self.span = FailingProgressSpan()

        def start_invocation(self, _request: InvocationRequest) -> FailingProgressSpan:
            return self.span

    telemetry = Telemetry()
    backend = CodexSdkBackend(telemetry=telemetry)  # type: ignore[arg-type]

    async def fail_after_progress(
        _request: InvocationRequest,
        *,
        on_first_progress: object = None,
    ) -> InvocationResult:
        assert callable(on_first_progress)
        on_first_progress("item.started")
        on_first_progress("item.updated")
        raise RuntimeError("provider worker crashed")

    monkeypatch.setattr(backend, "_invoke_with_capacity", fail_after_progress)

    with pytest.raises(RuntimeError, match="provider worker crashed"):
        await backend.invoke(_request(tmp_path))

    assert backend.telemetry_failures == 1
    assert telemetry.span.closed is True
    assert telemetry.span.terminal == ("error", "RuntimeError")
