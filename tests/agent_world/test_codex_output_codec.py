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
    CompactFieldSemanticDraft,
    EnvironmentSemanticSourceDraft,
    ExpansionDesignDraft,
    ObservationSemanticsSourceDraft,
    PermissionRuleSourceDraft,
    ToolSchemaIRDraft,
    ToolStateTransitionDraft,
)
from agent_world.invocation import (
    DiagnosticCommandExpectation,
    InvocationLimits,
    InvocationOwnerKind,
    InvocationOwnership,
    InvocationRequest,
    InvocationResult,
    InvocationSession,
    InvocationStatus,
    NodeCapabilityRequirement,
)
from agent_world.invocation.codex_sdk import (
    CodexSdkBackend,
    _decode_json_envelope,
    _decode_provider_json_ir,
    _open_ephemeral_sqlite_home,
    _provider_output_schema,
    _telemetry_event_payload,
)


def _request(tmp_path: Path) -> InvocationRequest:
    provider = IsolatedAgentProfileProvider(
        AgentBackendConfig(
            model="configured-real-model",
            api_key_environment="AGENT_WORLD_TEST_MODEL_KEY",
            openai_base_url_environment="OPENAI_BASE_URL",
        ),
        source_environment={
            "PATH": "/usr/bin:/bin",
            "AGENT_WORLD_TEST_MODEL_KEY": "test-model-credential",
            "OPENAI_BASE_URL": "https://provider.example.test/v1",
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

    assert payload["output_schema"] == _provider_output_schema(request.profile.output_schema or {})
    assert payload["prompt"] == request.prompt
    assert payload["sandbox"] == "read-only"
    assert request.profile.codex_bin is not None
    assert request.profile.codex_bin_sha256 is not None
    assert payload["codex_bin"] == str(request.profile.codex_bin)
    assert payload["codex_bin_sha256"] == request.profile.codex_bin_sha256
    assert f'"{request.profile.codex_bin}" = "read"' in (
        request.profile.codex_home / "config.toml"
    ).read_text(encoding="utf-8")
    assert payload["openai_base_url_environment"] == "OPENAI_BASE_URL"
    assert payload["sensitive_environment_names"] == ["OPENAI_API_KEY", "OPENAI_BASE_URL"]
    assert payload["diagnostic_capture_terminal_excerpt"] is False
    assert "provider.example.test" not in json.dumps(payload, sort_keys=True)
    assert payload["output_schema"]["properties"]["dynamic"] == {
        "type": "object",
        "properties": {
            "aw_object_entries": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "aw_key": {"type": "string"},
                        "aw_value": {"type": "string"},
                    },
                    "required": ["aw_key", "aw_value"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["aw_object_entries"],
        "additionalProperties": False,
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


def test_json_envelope_transport_uses_a_shallow_provider_schema(tmp_path: Path) -> None:
    request = _request(tmp_path)
    envelope_request = replace(
        request,
        profile=replace(request.profile, structured_output_transport="json_envelope"),
    )

    payload = CodexSdkBackend._worker_payload(envelope_request)

    assert payload["structured_output_transport"] == "json_envelope"
    assert payload["output_schema"] == {
        "type": "object",
        "properties": {"artifact_json": {"type": "string"}},
        "required": ["artifact_json"],
        "additionalProperties": False,
    }


def test_worker_payload_forwards_terminal_excerpt_capture_only_when_explicitly_opted_in(
    tmp_path: Path,
) -> None:
    request = _request(tmp_path)
    diagnostic_request = replace(
        request,
        metadata={"diagnostic_capture_terminal_excerpt": True},
    )

    assert (
        CodexSdkBackend._worker_payload(diagnostic_request)["diagnostic_capture_terminal_excerpt"]
        is True
    )


def test_worker_payload_forwards_private_audit_command_expectations_without_durable_output(
    tmp_path: Path,
) -> None:
    request = _request(tmp_path)
    diagnostic_request = replace(
        request,
        ownership=InvocationOwnership(
            owner_kind=InvocationOwnerKind.DIAGNOSTIC_AUDIT,
            owner_id="diagnostic:command-proof",
            scope_id="diagnostic:scope",
        ),
        diagnostic_command_expectations=(
            DiagnosticCommandExpectation(
                label="uv_version",
                command_fragment="./.agent-world-tools/uv --version",
            ),
        ),
    )

    payload = CodexSdkBackend._worker_payload(diagnostic_request)

    assert payload["diagnostic_command_expectations"] == [
        {
            "label": "uv_version",
            "command_fragment": "./.agent-world-tools/uv --version",
        }
    ]


def test_normal_telemetry_strips_local_diagnostic_command_sidecar() -> None:
    diagnostic_canary = "local-command-failure-must-not-reach-telemetry"

    payload = _telemetry_event_payload(
        {
            "item": {"type": "commandExecution", "status": "failed"},
            "diagnosticCommandProof": [
                {
                    "label": "uv_version",
                    "outcome": "failed",
                    "diagnosticExcerpt": diagnostic_canary,
                }
            ],
        }
    )

    assert payload == {"item": {"type": "commandExecution", "status": "failed"}}
    assert diagnostic_canary not in str(payload)


def test_json_envelope_decodes_the_inner_json_document_or_gateway_object() -> None:
    assert _decode_json_envelope({"artifact_json": '{"status":"ok"}'}) == {"status": "ok"}
    assert _decode_json_envelope({"artifact_json": {"status": "ok"}}) == {"status": "ok"}
    assert _decode_json_envelope({"status": "ok"}) == {"status": "ok"}
    with pytest.raises(ValueError, match="must be a JSON string or object"):
        _decode_json_envelope({"artifact_json": 7})


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
    captured_environment: dict[str, str] = {}

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

    async def fake_worker(*_: object, **kwargs: object) -> FakeProcess:
        environment = kwargs.get("env")
        assert isinstance(environment, dict)
        captured_environment.update(environment)
        return FakeProcess()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_worker)

    result = await CodexSdkBackend().invoke(request)

    assert result.status is InvocationStatus.FAILED
    assert result.error is not None
    assert result.error.code == "worker_protocol_error"
    assert result.error.retryable is True
    assert "CODEX_SQLITE_HOME" in captured_environment


def test_ephemeral_sqlite_home_is_memory_backed_and_removed_after_use() -> None:
    with _open_ephemeral_sqlite_home() as sqlite_home_text:
        sqlite_home = Path(sqlite_home_text)
        assert sqlite_home.parent == Path("/dev") / "shm"
        assert sqlite_home.is_dir()

    assert not sqlite_home.exists()


@pytest.mark.asyncio
async def test_backend_reuses_private_sqlite_home_for_a_resumed_session(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = CodexSdkBackend()
    initial = _request(tmp_path)
    observed_homes: list[Path] = []

    async def fake_worker(
        request: InvocationRequest,
        *,
        sqlite_home: Path,
        **_: object,
    ) -> InvocationResult:
        observed_homes.append(sqlite_home)
        return InvocationResult(
            invocation_id=request.invocation_id,
            status=InvocationStatus.COMPLETED,
            session=InvocationSession(
                thread_id="retained-thread",
                lineage_id=request.profile.lineage_id,
                workspace=request.profile.workspace,
                profile_hash=request.profile.profile_hash,
                codex_config_sha256=request.profile.codex_config_sha256,
            ),
            turn_id="turn:test",
            final_text="completed",
            structured_output=None,
            usage=None,
            events=(),
            error=None,
            duration_ms=1,
            backend_version="test",
        )

    monkeypatch.setattr(backend, "_invoke_worker_process", fake_worker)

    first = await backend._invoke_with_capacity(initial)
    assert first.session is not None
    second = await backend._invoke_with_capacity(
        replace(initial, invocation_id="codec-contract-resume", session=first.session)
    )

    assert second.succeeded
    assert observed_homes[0] == observed_homes[1]
    assert observed_homes[0].is_dir()
    assert await backend.close_session(first.session) is True
    assert not observed_homes[0].exists()


@pytest.mark.asyncio
async def test_resume_without_private_runtime_state_fails_before_a_worker_starts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    backend = CodexSdkBackend()
    initial = _request(tmp_path)
    session = InvocationSession(
        thread_id="missing-private-runtime",
        lineage_id=initial.profile.lineage_id,
        workspace=initial.profile.workspace,
        profile_hash=initial.profile.profile_hash,
        codex_config_sha256=initial.profile.codex_config_sha256,
    )

    async def unexpected_worker(**_: object) -> InvocationResult:
        raise AssertionError("a missing session runtime must fail before worker startup")

    monkeypatch.setattr(backend, "_invoke_worker_process", unexpected_worker)

    result = await backend._invoke_with_capacity(
        replace(initial, invocation_id="codec-contract-missing-runtime", session=session)
    )

    assert result.status is InvocationStatus.FAILED
    assert result.error is not None
    assert result.error.code == "session_runtime_unavailable"


@pytest.mark.asyncio
async def test_missing_declared_runtime_tool_fails_before_a_worker_starts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = IsolatedAgentProfileProvider(
        AgentBackendConfig(
            model="configured-real-model",
            api_key_environment="AGENT_WORLD_TEST_MODEL_KEY",
        ),
        source_environment={
            "PATH": str(tmp_path / "empty-bin"),
            "AGENT_WORLD_TEST_MODEL_KEY": "test-model-credential",
        },
    )
    profile = provider.resolve(
        role="environment-engineer",
        lineage_id="missing-runtime-tool",
        workspace=tmp_path / "engineer",
        output_schema={"type": "object", "additionalProperties": False},
        permissions=PermissionScope(),
        requirement=NodeCapabilityRequirement.isolated_build(
            node_id="environment-engineer.runtime-build"
        ),
    )
    request = InvocationRequest(
        invocation_id="missing-runtime-tool",
        prompt="This call must fail during toolchain preflight.",
        profile=profile,
    )
    backend = CodexSdkBackend()

    async def unexpected_worker(**_: object) -> InvocationResult:
        raise AssertionError("a missing runtime tool must fail before worker startup")

    monkeypatch.setattr(backend, "_invoke_worker_process", unexpected_worker)

    result = await backend._invoke_with_capacity(request)

    assert result.status is InvocationStatus.FAILED
    assert result.error is not None
    assert result.error.code == "runtime_toolchain_unavailable"
    assert result.error.retryable is False
    assert result.error.message == "required isolated runtime toolchain is unavailable: uv"


@pytest.mark.asyncio
async def test_session_from_a_previous_backend_instance_fails_closed_before_worker_start(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A thread id is not mistaken for its missing private SQLite checkpoint."""

    first_backend = CodexSdkBackend()
    initial = _request(tmp_path)

    async def first_worker(
        request: InvocationRequest,
        **_: object,
    ) -> InvocationResult:
        return InvocationResult(
            invocation_id=request.invocation_id,
            status=InvocationStatus.COMPLETED,
            session=InvocationSession(
                thread_id="prior-backend-thread",
                lineage_id=request.profile.lineage_id,
                workspace=request.profile.workspace,
                profile_hash=request.profile.profile_hash,
                codex_config_sha256=request.profile.codex_config_sha256,
            ),
            turn_id="turn:first",
            final_text="completed",
            structured_output=None,
            usage=None,
            events=(),
            error=None,
            duration_ms=1,
            backend_version="test",
        )

    monkeypatch.setattr(first_backend, "_invoke_worker_process", first_worker)
    first = await first_backend._invoke_with_capacity(initial)
    assert first.session is not None

    restarted_backend = CodexSdkBackend()

    async def unexpected_worker(**_: object) -> InvocationResult:
        raise AssertionError("a restarted backend must not fabricate a resumed worker")

    monkeypatch.setattr(restarted_backend, "_invoke_worker_process", unexpected_worker)
    resumed = await restarted_backend._invoke_with_capacity(
        replace(initial, invocation_id="codec-contract-restarted", session=first.session)
    )

    assert resumed.status is InvocationStatus.FAILED
    assert resumed.error is not None
    assert resumed.error.code == "session_runtime_unavailable"
    assert await first_backend.close_session(first.session) is True


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


@pytest.mark.parametrize(
    ("model", "field_name"),
    [
        (ObservationSemanticsSourceDraft, "visible_fields_by_actor"),
        (PermissionRuleSourceDraft, "required_scopes_by_actor"),
    ],
)
def test_provider_schema_preserves_typed_map_value_contract(
    model: type[ObservationSemanticsSourceDraft] | type[PermissionRuleSourceDraft],
    field_name: str,
) -> None:
    provider = _provider_output_schema(model.model_json_schema(mode="validation"))

    encoded_map = provider["properties"][field_name]
    entry = encoded_map["properties"]["aw_object_entries"]["items"]
    assert entry["properties"]["aw_key"] == {"$ref": "#/$defs/Identifier"}
    assert entry["properties"]["aw_value"] == {
        "type": "array",
        "items": {"$ref": "#/$defs/Identifier"},
    }


def test_typed_actor_map_decodes_to_json_array_and_strict_semantic_tuple() -> None:
    provider_output = {
        "visible_fields_by_actor": {
            "aw_object_entries": [
                {"aw_key": "guest", "aw_value": ["booking_id"]},
                {"aw_key": "staff", "aw_value": []},
            ]
        },
        "consistency": "strong",
        "staleness_bound_seconds": None,
    }

    decoded = _decode_provider_json_ir(provider_output)
    value = ObservationSemanticsSourceDraft.model_validate_json(json.dumps(decoded))

    assert value.visible_fields_by_actor == {
        "guest": ("booking_id",),
        "staff": (),
    }


def test_typed_actor_map_does_not_rewrite_object_value_as_empty_array() -> None:
    provider_output = {
        "visible_fields_by_actor": {
            "aw_object_entries": [
                {"aw_key": "guest", "aw_value": {}},
            ]
        },
        "consistency": "strong",
        "staleness_bound_seconds": None,
    }

    decoded = _decode_provider_json_ir(provider_output)
    with pytest.raises(ValueError, match="tuple_type"):
        ObservationSemanticsSourceDraft.model_validate_json(json.dumps(decoded))


@pytest.mark.parametrize("method", ["python", "json"])
def test_agent_output_rejects_scalar_string_coercion(method: str) -> None:
    payload = {
        "name": "nightly_rate",
        "value_type": "number",
        "description": "Nightly booking rate.",
        "minimum": "1",
    }

    with pytest.raises(ValueError, match="float_type"):
        if method == "python":
            CompactFieldSemanticDraft.model_validate(payload)
        else:
            CompactFieldSemanticDraft.model_validate_json(json.dumps(payload))


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
