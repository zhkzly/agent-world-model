"""Contract tests for the Scheduler-owned structured Agent turn boundary.

The recording backend below is only a protocol-boundary test double.  It never
stands in for the production success path: the test proves that malformed Agent
output causes exactly one physical invocation and returns a safe, path-addressed
failure to the Scheduler rather than entering the legacy local retry loop.
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import BaseModel, ConfigDict, JsonValue, ValidationError, model_validator

from agent_world.agent_output_authority import (
    AgentOutputAuthority,
    SemanticAdvisoryOutput,
    register_agent_output_contract,
)
from agent_world.agent_profiles import IsolatedAgentProfileProvider
from agent_world.config import AgentBackendConfig
from agent_world.contracts import ArtifactRef, PermissionScope, sha256_digest
from agent_world.control.leaf_executor import (
    AgentCorrectionBrief,
    LeafExecutionFailure,
    LeafValidationFailure,
)
from agent_world.control.validation import pydantic_validation_diagnostic
from agent_world.control.work import ValidationIssue, WorkAttempt
from agent_world.control.work_graph import structured_agent_work_definition
from agent_world.designer.models import CompactFieldSemanticDraft, StateFieldSourceDraft
from agent_world.designer.one_shot import invoke_structured_once
from agent_world.designer.validation import StructuredSemanticError, StructuredSemanticIssue
from agent_world.invocation import (
    InvocationRequest,
    InvocationResult,
    InvocationStatus,
    InvocationUsage,
    TokenBreakdown,
)


class _StrictOneShotOutput(SemanticAdvisoryOutput, BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    title: str


register_agent_output_contract(
    _StrictOneShotOutput,
    authority=AgentOutputAuthority.SEMANTIC_ADVISORY,
)


class _FieldContractOutput(SemanticAdvisoryOutput, BaseModel):
    """Small Agent root that exercises the Architecture field source boundary."""

    model_config = ConfigDict(strict=True, extra="forbid")

    field: CompactFieldSemanticDraft


class _StateFieldContractOutput(SemanticAdvisoryOutput, BaseModel):
    """Small Agent root that exercises the Architecture lifecycle source boundary."""

    model_config = ConfigDict(strict=True, extra="forbid")

    field: StateFieldSourceDraft


register_agent_output_contract(
    _FieldContractOutput,
    authority=AgentOutputAuthority.SEMANTIC_ADVISORY,
)
register_agent_output_contract(
    _StateFieldContractOutput,
    authority=AgentOutputAuthority.SEMANTIC_ADVISORY,
)


class _MalformedOutputBackend:
    """A bounded backend double that returns one real-protocol terminal record."""

    def __init__(self) -> None:
        self.requests: list[InvocationRequest] = []

    @property
    def supported_executor_revision_ids(self) -> tuple[str, ...]:
        return ("framework.executor.v1",)

    async def invoke(self, request: InvocationRequest) -> InvocationResult:
        self.requests.append(request)
        return InvocationResult(
            invocation_id=request.invocation_id,
            status=InvocationStatus.COMPLETED,
            session=None,
            turn_id="turn:malformed-output",
            final_text=None,
            structured_output={"title": 42},
            usage=InvocationUsage(turn=TokenBreakdown(total_tokens=11)),
            events=(),
            error=None,
            duration_ms=1,
            backend_version="test-protocol-boundary",
        )

    async def cancel(self, invocation_id: str) -> bool:
        return False


class _SemanticOutputBackend(_MalformedOutputBackend):
    """Return a shape-valid output so the semantic diagnostic path is exercised."""

    async def invoke(self, request: InvocationRequest) -> InvocationResult:
        result = await super().invoke(request)
        return replace(result, structured_output={"title": "Hotel booking"})


class _StaticOutputBackend(_MalformedOutputBackend):
    """Return one supplied structured result through the normal backend protocol."""

    def __init__(self, output: dict[str, JsonValue]) -> None:
        super().__init__()
        self.output = output

    async def invoke(self, request: InvocationRequest) -> InvocationResult:
        result = await super().invoke(request)
        return replace(result, structured_output=self.output)


class _HangingOutputBackend(_MalformedOutputBackend):
    """Record one dispatch, then exceed the leaf's real wall budget."""

    async def invoke(self, request: InvocationRequest) -> InvocationResult:
        self.requests.append(request)
        await asyncio.sleep(1)
        raise AssertionError("the Scheduler timeout must cancel this invocation")


def _definition():
    return structured_agent_work_definition(
        scope_id="job:one-shot",
        component="research",
        stage="research_plan",
        artifact_slot="research_plan",
        dependency_coordinates=(),
        claim_id="research.plan.valid",
        claim="One research Agent proposal satisfies the closed plan schema.",
        timing_reason="Research tools must consume a bounded plan.",
        output_contract_id="contract:research-plan",
        agent_role="researcher",
        allowed_mutation_roots=("/",),
        agent_wall_seconds=30,
        agent_token_limit=1_000,
    )


def _attempt(definition) -> WorkAttempt:
    now = datetime.now(UTC)
    return WorkAttempt(
        attempt_id="attempt:one-shot:1",
        work_id=definition.work_id,
        coordinate=definition.coordinate,
        ordinal=1,
        status="running",
        definition_digest=definition.definition_digest,
        proposal_policy_digest=definition.proposal_policy.content_digest(),
        validation_policy_digest=definition.validation_policy.content_digest(),
        repair_policy_digest=definition.repair_policy.content_digest(),
        scheduled_at=now,
        started_at=now,
    )


def _repair_action_ref() -> ArtifactRef:
    return ArtifactRef(
        artifact_id="repair-action:one-shot",
        revision_id=sha256_digest(b"one-shot-repair-revision"),
        artifact_type="control.repair_action",
        content_hash=sha256_digest(b"one-shot-repair-content"),
        media_type="application/json",
        size_bytes=1,
    )


@pytest.mark.asyncio
async def test_one_shot_returns_safe_field_feedback_without_component_retry(
    tmp_path: Path,
) -> None:
    """A malformed response is one call, not a hidden sequence of corrections."""

    definition = _definition()
    backend = _MalformedOutputBackend()
    profiles = IsolatedAgentProfileProvider(
        AgentBackendConfig(
            model="test-structured-model",
            api_key_environment="AGENT_WORLD_TEST_MODEL_KEY",
        ),
        source_environment={
            "PATH": "/usr/bin:/bin",
            "AGENT_WORLD_TEST_MODEL_KEY": "test-only-credential",
        },
    )

    with pytest.raises(LeafValidationFailure) as captured:
        await invoke_structured_once(
            backend=backend,
            profiles=profiles,
            definition=definition,
            attempt=_attempt(definition),
            dispatch_id="dispatch:one-shot:1",
            lineage_id="lineage:one-shot",
            workspace=tmp_path / "isolated-researcher",
            model=_StrictOneShotOutput,
            prompt="Produce the requested title object.",
            permissions=PermissionScope(),
        )

    failure = captured.value
    assert len(backend.requests) == 1
    assert backend.requests[0].session is None
    assert failure.category == "structured_output_shape"
    assert failure.issues[0].code == "schema_string_type"
    assert failure.issues[0].path == ("title",)
    assert failure.agent is not None
    assert failure.observed_actual.llm_tokens == 11
    assert failure.observed_actual.agent_turns == 1
    assert failure.unknown_upper_bound.llm_tokens == 989


@pytest.mark.asyncio
async def test_one_shot_preserves_actionable_structured_semantic_details(
    tmp_path: Path,
) -> None:
    """A semantic repair packet retains its safe condition and expected category."""

    definition = _definition()
    backend = _SemanticOutputBackend()
    profiles = IsolatedAgentProfileProvider(
        AgentBackendConfig(
            model="test-structured-model",
            api_key_environment="AGENT_WORLD_TEST_MODEL_KEY",
        ),
        source_environment={
            "PATH": "/usr/bin:/bin",
            "AGENT_WORLD_TEST_MODEL_KEY": "test-only-credential",
        },
    )

    def semantic_validator(_value: _StrictOneShotOutput) -> None:
        raise StructuredSemanticError(
            (
                StructuredSemanticIssue(
                    code="shared_contract_partition",
                    location=("concurrency_domains",),
                    message="Shared domains must partition every frozen group tool exactly once.",
                    violated_condition="shared domains omit or duplicate a frozen group tool",
                    expected_category=(
                        "one exact partition of frozen tool IDs: hotel.search, hotel.reserve"
                    ),
                ),
            )
        )

    with pytest.raises(LeafValidationFailure) as captured:
        await invoke_structured_once(
            backend=backend,
            profiles=profiles,
            definition=definition,
            attempt=_attempt(definition),
            dispatch_id="dispatch:one-shot:semantic:1",
            lineage_id="lineage:one-shot:semantic",
            workspace=tmp_path / "isolated-researcher",
            model=_StrictOneShotOutput,
            prompt="Produce the requested title object.",
            permissions=PermissionScope(),
            semantic_validator=semantic_validator,
        )

    issue = captured.value.issues[0]
    assert issue.code == "shared_contract_partition"
    assert issue.path == ("concurrency_domains",)
    assert issue.violated_condition == "shared domains omit or duplicate a frozen group tool"
    assert issue.expected_category == (
        "one exact partition of frozen tool IDs: hotel.search, hotel.reserve"
    )


@pytest.mark.asyncio
async def test_one_shot_keeps_unknown_architecture_compiler_errors_non_actionable(
    tmp_path: Path,
) -> None:
    """Compiler code must declare a safe condition before it can spend a repair turn."""

    definition = _definition()
    backend = _SemanticOutputBackend()
    profiles = IsolatedAgentProfileProvider(
        AgentBackendConfig(
            model="test-structured-model",
            api_key_environment="AGENT_WORLD_TEST_MODEL_KEY",
        ),
        source_environment={
            "PATH": "/usr/bin:/bin",
            "AGENT_WORLD_TEST_MODEL_KEY": "test-only-credential",
        },
    )

    def untyped_compiler(_value: _StrictOneShotOutput) -> None:
        raise ValueError("unlisted compiler diagnostic")

    with pytest.raises(LeafValidationFailure) as captured:
        await invoke_structured_once(
            backend=backend,
            profiles=profiles,
            definition=definition,
            attempt=_attempt(definition),
            dispatch_id="dispatch:one-shot:unknown-compiler",
            lineage_id="lineage:one-shot:unknown-compiler",
            workspace=tmp_path / "unknown-compiler",
            model=_StrictOneShotOutput,
            prompt="Produce the requested title object.",
            permissions=PermissionScope(),
            semantic_validator=untyped_compiler,
        )

    issue = captured.value.issues[0]
    assert len(backend.requests) == 1
    assert issue.code == "framework_diagnostic_incomplete"
    assert issue.retryable is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("model", "output", "expected_code", "expected_condition", "expected_category"),
    (
        (
            _FieldContractOutput,
            {
                "field": {
                    "name": "guest_count",
                    "value_type": "integer",
                    "description": "Number of guests.",
                    "string_format": "email",
                }
            },
            "schema_compact_field_string_constraints",
            "string_format and enum_values are valid only for string fields",
            "a string field when using string constraints",
        ),
        (
            _StateFieldContractOutput,
            {
                "field": {
                    "name": "status",
                    "value_type": "string",
                    "description": "Reservation state.",
                    "role": "primary_key",
                    "lifecycle": True,
                    "enum_values": ["pending", "confirmed"],
                }
            },
            "schema_state_field_lifecycle_contract",
            "lifecycle requires mutable role, string value_type, and non-empty enum_values",
            "a mutable string lifecycle field with non-empty enum_values",
        ),
    ),
)
async def test_one_shot_turns_known_architecture_model_contracts_into_actionable_diagnostics(
    tmp_path: Path,
    model: type[BaseModel],
    output: dict[str, JsonValue],
    expected_code: str,
    expected_condition: str,
    expected_category: str,
) -> None:
    """Known source-model contracts may reach the one bounded local correction."""

    definition = _definition()
    backend = _StaticOutputBackend(output)
    profiles = IsolatedAgentProfileProvider(
        AgentBackendConfig(
            model="test-structured-model",
            api_key_environment="AGENT_WORLD_TEST_MODEL_KEY",
        ),
        source_environment={
            "PATH": "/usr/bin:/bin",
            "AGENT_WORLD_TEST_MODEL_KEY": "test-only-credential",
        },
    )

    with pytest.raises(LeafValidationFailure) as captured:
        await invoke_structured_once(
            backend=backend,
            profiles=profiles,
            definition=definition,
            attempt=_attempt(definition),
            dispatch_id=f"dispatch:one-shot:{expected_code}",
            lineage_id=f"lineage:one-shot:{expected_code}",
            workspace=tmp_path / expected_code,
            model=model,
            prompt="Produce the requested field contract.",
            permissions=PermissionScope(),
        )

    issue = captured.value.issues[0]
    assert len(backend.requests) == 1
    assert issue.code == expected_code
    assert issue.retryable is True
    assert issue.violated_condition == expected_condition
    assert issue.expected_category == expected_category
    assert issue.code != "framework_diagnostic_incomplete"


def test_unknown_pydantic_value_error_remains_a_non_actionable_framework_diagnostic() -> None:
    """The allowlist must not turn arbitrary raw validator text into Agent feedback."""

    class _UnknownValidatorOutput(SemanticAdvisoryOutput, BaseModel):
        model_config = ConfigDict(strict=True, extra="forbid")

        title: str

        @model_validator(mode="after")
        def validate_unknown(self) -> _UnknownValidatorOutput:
            raise ValueError("unlisted raw validator text")

    with pytest.raises(ValidationError) as captured:
        _UnknownValidatorOutput.model_validate({"title": "hotel booking"})

    diagnostic = pydantic_validation_diagnostic(
        captured.value,
        owner_component="design",
        validation_phase="unknown_validator_shape",
        frontier_ordinal=10,
    )
    issue = diagnostic.issues[0]
    assert issue.code == "framework_diagnostic_incomplete"
    assert issue.retryable is False


@pytest.mark.asyncio
async def test_one_shot_renders_only_safe_local_correction_diagnostics(
    tmp_path: Path,
) -> None:
    """A fresh correction call receives facts, never Scheduler authority."""

    definition = _definition()
    backend = _SemanticOutputBackend()
    profiles = IsolatedAgentProfileProvider(
        AgentBackendConfig(
            model="test-structured-model",
            api_key_environment="AGENT_WORLD_TEST_MODEL_KEY",
        ),
        source_environment={
            "PATH": "/usr/bin:/bin",
            "AGENT_WORLD_TEST_MODEL_KEY": "test-only-credential",
        },
    )
    brief = AgentCorrectionBrief(
        issues=(
            ValidationIssue(
                code="shared_contract_partition",
                path=("concurrency_domains",),
                violated_condition="shared domains omit or duplicate a frozen group tool",
                expected_category=(
                    "one exact partition of frozen tool IDs: hotel.search, hotel.reserve"
                ),
            ),
        )
    )

    result = await invoke_structured_once(
        backend=backend,
        profiles=profiles,
        definition=definition,
        attempt=_attempt(definition),
        dispatch_id="dispatch:one-shot:correction",
        lineage_id="lineage:one-shot:correction",
        workspace=tmp_path / "isolated-researcher",
        model=_StrictOneShotOutput,
        prompt="Produce the requested title object.",
        permissions=PermissionScope(),
        correction_brief=brief,
    )

    assert result.output.title == "Hotel booking"
    rendered = backend.requests[0].prompt
    assert "Deterministic local-correction brief" in rendered
    assert "shared domains omit or duplicate a frozen group tool" in rendered
    assert "hotel.search, hotel.reserve" in rendered
    assert "repair_policy_id" not in rendered
    assert "allowed_mutation_roots" not in rendered
    assert "target_coordinate" not in rendered
    assert "release decision" in rendered  # prohibition, not leaked state


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("repair_action_ref", "repair_attempt_charge", "recovery_ordinal", "expected_mode"),
    (
        (None, 0, 0, "initial"),
        (_repair_action_ref(), 1, 0, "authorized_repair"),
        (_repair_action_ref(), 0, 1, "process_recovery"),
    ),
)
async def test_one_shot_projects_existing_attempt_repair_state_into_invocation_metadata(
    tmp_path: Path,
    repair_action_ref: ArtifactRef | None,
    repair_attempt_charge: int,
    recovery_ordinal: int,
    expected_mode: str,
) -> None:
    """Invocation telemetry labels existing authority; it never chooses a retry."""

    definition = _definition()
    backend = _SemanticOutputBackend()
    profiles = IsolatedAgentProfileProvider(
        AgentBackendConfig(
            model="test-structured-model",
            api_key_environment="AGENT_WORLD_TEST_MODEL_KEY",
        ),
        source_environment={
            "PATH": "/usr/bin:/bin",
            "AGENT_WORLD_TEST_MODEL_KEY": "test-only-credential",
        },
    )
    attempt = _attempt(definition).model_copy(
        update={
            "attempt_id": f"attempt:one-shot:{expected_mode}",
            "ordinal": 2 if repair_action_ref is not None else 1,
            "repair_action_ref": repair_action_ref,
            "repair_attempt_charge": repair_attempt_charge,
            "recovery_ordinal": recovery_ordinal,
            "recovery_reason_code": (
                "process_interrupted_after_proposal" if recovery_ordinal else None
            ),
        }
    )

    result = await invoke_structured_once(
        backend=backend,
        profiles=profiles,
        definition=definition,
        attempt=attempt,
        dispatch_id=f"dispatch:one-shot:{expected_mode}",
        lineage_id=f"lineage:one-shot:{expected_mode}",
        workspace=tmp_path / expected_mode,
        model=_StrictOneShotOutput,
        prompt="Produce the requested title object.",
        permissions=PermissionScope(),
    )

    assert result.output.title == "Hotel booking"
    assert backend.requests[0].metadata["repair_mode"] == expected_mode
    assert backend.requests[0].metadata["repair_attempt_charge"] == repair_attempt_charge


def test_correction_brief_groups_repeated_rule_diagnostics_without_losing_scope() -> None:
    """A repair turn receives one causal cluster, not a 100-line error dump."""

    brief = AgentCorrectionBrief(
        issues=tuple(
            ValidationIssue(
                code="rule_pointer_unreachable",
                path=(
                    "tools",
                    0,
                    "conditions",
                    "postconditions",
                    index,
                    "clauses",
                    0,
                    "left",
                    "value_pointer",
                ),
                violated_condition="the selected-record field path does not exist",
                expected_category="one of the item pointers: /booking_id, /status",
            )
            for index in range(16)
        )
    )

    projection = brief.prompt_projection()

    assert projection["total_blocking_issues"] == 16
    clusters = projection["clusters"]
    assert isinstance(clusters, tuple)
    assert len(clusters) == 1
    cluster = clusters[0]
    assert cluster["occurrence_count"] == 16
    assert cluster["affected_path_patterns"] == (
        (
            "tools",
            "*",
            "conditions",
            "postconditions",
            "*",
            "clauses",
            "*",
            "left",
            "value_pointer",
        ),
    )
    assert len(cluster["representative_paths"]) == 3


@pytest.mark.asyncio
async def test_one_shot_timeout_preserves_dispatch_provenance_for_terminal_settlement(
    tmp_path: Path,
) -> None:
    """A dispatched Agent timeout is a terminal operation, not an orphan lease."""

    base = _definition()
    definition = base.model_copy(
        update={
            "proposal_policy": base.proposal_policy.model_copy(
                update={
                    "budget": base.proposal_policy.budget.model_copy(
                        update={"wall_seconds": 0.01}
                    )
                }
            )
        }
    )
    backend = _HangingOutputBackend()
    profiles = IsolatedAgentProfileProvider(
        AgentBackendConfig(
            model="test-structured-model",
            api_key_environment="AGENT_WORLD_TEST_MODEL_KEY",
        ),
        source_environment={
            "PATH": "/usr/bin:/bin",
            "AGENT_WORLD_TEST_MODEL_KEY": "test-only-credential",
        },
    )

    with pytest.raises(LeafExecutionFailure) as captured:
        await invoke_structured_once(
            backend=backend,
            profiles=profiles,
            definition=definition,
            attempt=_attempt(definition),
            dispatch_id="dispatch:one-shot:timeout",
            lineage_id="lineage:one-shot:timeout",
            workspace=tmp_path / "isolated-researcher",
            model=_StrictOneShotOutput,
            prompt="Produce the requested title object.",
            permissions=PermissionScope(),
        )

    failure = captured.value
    assert len(backend.requests) == 1
    assert failure.code == "agent_invocation_timeout"
    assert failure.agent is not None
    assert failure.agent.invocation_id == "dispatch:one-shot:timeout"
    assert failure.agent.model == "test-structured-model"
    assert failure.unknown_upper_bound.llm_tokens == 1_000
