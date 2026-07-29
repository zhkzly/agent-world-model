"""Contract tests for the Scheduler-owned structured Agent turn boundary.

The recording backend below is only a protocol-boundary test double.  It never
stands in for the production success path: the test proves that malformed Agent
output causes exactly one physical invocation and returns a safe, path-addressed
failure to the Scheduler rather than entering the legacy local retry loop.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Literal

import pytest
from pydantic import BaseModel, ConfigDict, Field, JsonValue, ValidationError, model_validator

from agent_world.agent_output_authority import (
    AgentOutputAuthority,
    SemanticAdvisoryOutput,
    register_agent_output_contract,
)
from agent_world.agent_profiles import IsolatedAgentProfileProvider
from agent_world.artifact_store import ArtifactStore
from agent_world.config import AgentBackendConfig
from agent_world.contracts import (
    ArtifactRef,
    Budget,
    PermissionScope,
    canonical_json_bytes,
    sha256_digest,
)
from agent_world.control import (
    GenerationWorkGraph,
    LeafProposal,
    LeaseBudgetLedger,
    SchedulerLeafExecutor,
    ValidationReport,
    WorkControlRuntime,
    WorkControlStore,
    WorkScheduler,
)
from agent_world.control.leaf_executor import (
    AgentCorrectionBrief,
    LeafExecutionFailure,
    LeafValidationFailure,
)
from agent_world.control.validation import pydantic_validation_diagnostic
from agent_world.control.work import ValidationIssue, WorkAttempt
from agent_world.control.work_graph import structured_agent_work_definition
from agent_world.designer.models import (
    ActorAuthoritySourceDraft,
    CompactFieldSemanticDraft,
    StateFieldSourceDraft,
    ToolInterfaceSourceDraft,
    ToolSurfacePlan,
)
from agent_world.designer.one_shot import invoke_structured_once
from agent_world.designer.validation import StructuredSemanticError, StructuredSemanticIssue
from agent_world.invocation import (
    InvocationError,
    InvocationExecutionMode,
    InvocationRequest,
    InvocationResult,
    InvocationSession,
    InvocationStatus,
    InvocationUsage,
    NodeCapabilityRequirement,
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


class _SequenceOutputBackend(_MalformedOutputBackend):
    """Return each parsed candidate through the normal Direct boundary once."""

    def __init__(self, outputs: list[dict[str, JsonValue]]) -> None:
        super().__init__()
        self._outputs = list(outputs)

    async def invoke(self, request: InvocationRequest) -> InvocationResult:
        if not self._outputs:
            raise AssertionError("test backend received an unexpected extra model invocation")
        result = await super().invoke(request)
        return replace(
            result,
            turn_id=f"turn:sequence:{len(self.requests)}",
            structured_output=self._outputs.pop(0),
        )


class _HangingOutputBackend(_MalformedOutputBackend):
    """Record one dispatch, then exceed the leaf's real wall budget."""

    async def invoke(self, request: InvocationRequest) -> InvocationResult:
        self.requests.append(request)
        await asyncio.sleep(1)
        raise AssertionError("the Scheduler timeout must cancel this invocation")


class _ProviderRejectedBackend(_MalformedOutputBackend):
    """Expose a known terminal provider rejection through the normal adapter result."""

    async def invoke(self, request: InvocationRequest) -> InvocationResult:
        result = await super().invoke(request)
        return replace(
            result,
            status=InvocationStatus.FAILED,
            structured_output=None,
            error=InvocationError(
                code="turn_failed_provider_rejected",
                message="safe test-only provider rejection",
                # A generic worker flag must not override the fixed terminal
                # compatibility classification at the Scheduler boundary.
                retryable=True,
            ),
        )


class _ProviderDisconnectBackend(_MalformedOutputBackend):
    """Expose a retryable Codex response-stream interruption safely."""

    async def invoke(self, request: InvocationRequest) -> InvocationResult:
        result = await super().invoke(request)
        return replace(
            result,
            status=InvocationStatus.FAILED,
            structured_output=None,
            error=InvocationError(
                code="turn_failed_provider_unavailable",
                message="TOP_SECRET_PROVIDER_TRANSCRIPT",
                retryable=True,
                details={
                    "terminal_error_shape": "object",
                    "codex_error_info": "transport:response_stream_disconnected",
                    "provider_text": "TOP_SECRET_PROVIDER_TRANSCRIPT",
                },
            ),
        )


class _QuotaExhaustedBackend(_MalformedOutputBackend):
    """Expose a non-retryable Provider-account terminal through the normal adapter."""

    async def invoke(self, request: InvocationRequest) -> InvocationResult:
        result = await super().invoke(request)
        return replace(
            result,
            status=InvocationStatus.FAILED,
            structured_output=None,
            error=InvocationError(
                code="turn_failed_quota_exhausted",
                message="TOP_SECRET_PROVIDER_TRANSCRIPT",
                retryable=True,
            ),
        )


class _SessionBudgetExhaustedBackend(_MalformedOutputBackend):
    """Expose a closed session-budget terminal without retaining provider text."""

    async def invoke(self, request: InvocationRequest) -> InvocationResult:
        result = await super().invoke(request)
        return replace(
            result,
            status=InvocationStatus.FAILED,
            structured_output=None,
            error=InvocationError(
                code="turn_failed_session_budget_exhausted",
                message="TOP_SECRET_PROVIDER_TRANSCRIPT",
                retryable=True,
                details={
                    "terminal_error_shape": "object",
                    "codex_error_info": "enum:sessionbudgetexceeded",
                    "provider_text": "TOP_SECRET_PROVIDER_TRANSCRIPT",
                },
            ),
        )


class _DirectInvalidJsonBackend(_MalformedOutputBackend):
    """Return a safe Direct-adapter parse classification with hostile raw fields."""

    async def invoke(self, request: InvocationRequest) -> InvocationResult:
        result = await super().invoke(request)
        return replace(
            result,
            status=InvocationStatus.FAILED,
            structured_output=None,
            error=InvocationError(
                code="direct_structured_output_invalid_json",
                message="TOP_SECRET_PROVIDER_TRANSCRIPT",
                # A malformed Direct response is an incompatibility terminal,
                # even if an arbitrary backend incorrectly labels it retryable.
                retryable=True,
                details={
                    "response_shape": "markdown_fence",
                    "parse_failure": "syntax",
                    "parse_offset": 0,
                    "response_characters": 73,
                    "provider_text": "TOP_SECRET_PROVIDER_TRANSCRIPT",
                },
            ),
        )


class _DirectOutputLimitBackend(_MalformedOutputBackend):
    """Return a safe Direct-adapter output-ceiling terminal."""

    async def invoke(self, request: InvocationRequest) -> InvocationResult:
        result = await super().invoke(request)
        return replace(
            result,
            status=InvocationStatus.FAILED,
            structured_output=None,
            usage=InvocationUsage(turn=TokenBreakdown(total_tokens=1_000)),
            error=InvocationError(
                code="direct_output_limit",
                message="safe test-only output limit",
                retryable=True,
                details={
                    "terminal_status": "incomplete",
                    "terminal_reason": "max_output_tokens",
                    "configured_max_output_tokens": 65_536,
                },
            ),
        )


class _DirectProviderStreamStalledBackend(_MalformedOutputBackend):
    """Return a started-then-silent Direct stream terminal with no transcript."""

    async def invoke(self, request: InvocationRequest) -> InvocationResult:
        result = await super().invoke(request)
        return replace(
            result,
            status=InvocationStatus.FAILED,
            structured_output=None,
            error=InvocationError(
                code="direct_provider_stream_stalled",
                message="TOP_SECRET_PROVIDER_TRANSCRIPT",
                retryable=True,
                details={
                    "waiting_phase": "direct_awaiting_stream_event",
                    "idle_timeout_seconds": 300,
                    "observed_provider_event_count": 4,
                    "provider_text": "TOP_SECRET_PROVIDER_TRANSCRIPT",
                },
            ),
        )


class _AgenticOutputLimitBackend(_MalformedOutputBackend):
    """Return one resumable Codex physical-turn output ceiling."""

    async def invoke(self, request: InvocationRequest) -> InvocationResult:
        result = await super().invoke(request)
        profile = request.profile
        return replace(
            result,
            status=InvocationStatus.FAILED,
            structured_output=None,
            usage=InvocationUsage(turn=TokenBreakdown(total_tokens=125_000)),
            session=InvocationSession(
                thread_id="private-output-limit-thread",
                lineage_id=profile.lineage_id,
                workspace=profile.workspace,
                profile_hash=profile.profile_hash,
                codex_config_sha256=profile.codex_config_sha256,
            ),
            error=InvocationError(
                code="turn_failed_output_limit",
                message="safe test-only Agent output limit",
                retryable=False,
                details={
                    "terminal_status": "incomplete",
                    "terminal_reason": "max_output_tokens",
                },
            ),
        )


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
    assert backend.requests[0].execution_mode is InvocationExecutionMode.SINGLE_SHOT_STRUCTURED
    assert backend.requests[0].profile.limits.timeout_seconds == (
        definition.proposal_policy.budget.wall_seconds
    )
    assert failure.category == "structured_output_shape"
    assert failure.issues[0].code == "schema_string_type"
    assert failure.issues[0].path == ("title",)
    assert failure.issues[0].remediation == (
        "Return a string value; the rejected value has safe JSON type `number`."
    )
    assert failure.issues[0].violated_condition == (
        "closed schema constraint string_type; received JSON type `number`"
    )
    assert failure.agent is not None
    assert failure.observed_actual.llm_tokens == 11
    assert failure.observed_actual.agent_turns == 1
    assert failure.unknown_upper_bound.llm_tokens == 989


@pytest.mark.asyncio
async def test_structured_read_uses_one_real_agentic_turn(tmp_path: Path) -> None:
    """A declared shell-read node must not silently route through Direct LLM."""

    definition = _definition()
    backend = _StaticOutputBackend({"title": "Frozen input inspection"})
    profiles = IsolatedAgentProfileProvider(
        AgentBackendConfig(
            model="test-read-agent-model",
            api_key_environment="AGENT_WORLD_TEST_MODEL_KEY",
        ),
        source_environment={
            "PATH": "/usr/bin:/bin",
            "AGENT_WORLD_TEST_MODEL_KEY": "test-only-credential",
        },
    )

    result = await invoke_structured_once(
        backend=backend,
        profiles=profiles,
        definition=definition,
        attempt=_attempt(definition),
        dispatch_id="dispatch:structured-read:1",
        lineage_id="lineage:structured-read",
        workspace=tmp_path / "isolated-reader",
        model=_StrictOneShotOutput,
        prompt="Read the staged frozen inputs and return the requested title object.",
        permissions=PermissionScope(),
        capability_requirement=NodeCapabilityRequirement.structured_read(
            node_id="researcher.frozen-input-inspection",
            role="researcher",
        ),
    )

    assert result.output.title == "Frozen input inspection"
    assert len(backend.requests) == 1
    assert backend.requests[0].execution_mode is InvocationExecutionMode.AGENTIC
    assert backend.requests[0].profile.allowed_builtin_tools == ("shell",)


@pytest.mark.asyncio
async def test_one_shot_resolves_the_durable_fallback_route_for_its_physical_turn(
    tmp_path: Path,
) -> None:
    """A Scheduler-authorized fallback reaches the actual backend profile.

    The preceding Scheduler/RepairLedger boundary proves that a fallback
    ``WorkAttempt`` is durably authorized.  This narrower boundary proves the
    next necessary link: the persisted selected route, rather than the ambient
    primary model, is what reaches ``InvocationBackend`` for that new physical
    proposal.
    """

    definition = _definition()
    attempt = WorkAttempt.model_validate(
        {
            **_attempt(definition).model_dump(mode="python"),
            "attempt_id": "attempt:one-shot:fallback",
            "ordinal": 2,
            "repair_action_ref": _repair_action_ref(),
            "repair_attempt_charge": 1,
            "model_override": "gpt-5.3-codex-spark",
        }
    )
    backend = _SemanticOutputBackend()
    profiles = IsolatedAgentProfileProvider(
        AgentBackendConfig(
            model="grok-4.5",
            fallback_models=("gpt-5.3-codex-spark", "gpt-5.4-mini"),
            api_key_environment="AGENT_WORLD_TEST_MODEL_KEY",
        ),
        source_environment={
            "PATH": "/usr/bin:/bin",
            "AGENT_WORLD_TEST_MODEL_KEY": "test-only-credential",
        },
    )

    result = await invoke_structured_once(
        backend=backend,
        profiles=profiles,
        definition=definition,
        attempt=attempt,
        dispatch_id="dispatch:one-shot:fallback",
        lineage_id="lineage:one-shot:fallback",
        workspace=tmp_path / "fallback",
        model=_StrictOneShotOutput,
        prompt="Produce the requested title object.",
        permissions=PermissionScope(),
    )

    assert result.output.title == "Hotel booking"
    assert len(backend.requests) == 1
    assert backend.requests[0].profile.model == "gpt-5.3-codex-spark"
    assert backend.requests[0].metadata["repair_mode"] == "authorized_repair"


def test_missing_pydantic_field_has_an_explicit_safe_repair_condition() -> None:
    """A correction brief can distinguish an omitted field from an opaque schema failure."""

    with pytest.raises(ValidationError) as captured:
        _StrictOneShotOutput.model_validate({})

    diagnostic = pydantic_validation_diagnostic(
        captured.value,
        owner_component="design",
        validation_phase="task_curriculum",
        frontier_ordinal=10,
    )

    issue = diagnostic.issues[0]
    assert issue.code == "schema_missing"
    assert issue.location == ("title",)
    assert issue.message == (
        "Include the named required field; it cannot be omitted from the structured output."
    )
    assert issue.violated_condition == "the named field is required by the closed output schema"
    assert issue.expected_category == (
        "the named required field with a value satisfying its closed output schema"
    )
    assert issue.actionable_for_agent is True


def test_pydantic_v2_schema_version_feedback_is_safe_and_actionable() -> None:
    """A common input/output-version mix-up must be repairable without echoing model text."""

    class VersionProbe(BaseModel):
        model_config = ConfigDict(strict=True)

        schema_version: Literal["v2"] = "v2"

    with pytest.raises(ValidationError) as captured:
        VersionProbe.model_validate({"schema_version": "agent-world.challenger-context.v4"})

    diagnostic = pydantic_validation_diagnostic(
        captured.value,
        owner_component="verifier",
        validation_phase="intent_schema",
        frontier_ordinal=10,
    )

    issue = diagnostic.issues[0]
    assert issue.code == "schema_literal_error"
    assert issue.location == ("schema_version",)
    assert issue.message == (
        "Use the literal schema_version `v2`; never copy a version label from an input or "
        "context document."
    )
    assert issue.violated_condition == "closed schema literal schema_version=v2"
    assert issue.expected_category == "the literal string `v2`"
    assert issue.remediation == (
        "Set schema_version to exactly `v2`; do not copy a version label from an input or "
        "context document."
    )
    assert "agent-world.challenger-context.v4" not in diagnostic.feedback


def test_pydantic_shape_feedback_discloses_safe_kind_and_length_not_raw_input() -> None:
    """A repair can see structural facts without receiving rejected model content."""

    class ShapeProbe(BaseModel):
        model_config = ConfigDict(strict=True)

        values: Annotated[tuple[str, ...], Field(min_length=2)]

    with pytest.raises(ValidationError) as captured:
        ShapeProbe.model_validate_json(json.dumps({"values": [{"private": "do-not-persist"}]}))

    diagnostic = pydantic_validation_diagnostic(
        captured.value,
        owner_component="design",
        validation_phase="tool_semantics",
        frontier_ordinal=20,
    )

    issues = {issue.code: issue for issue in diagnostic.issues}
    type_issue = issues["schema_string_type"]
    length_issue = issues["schema_too_short"]
    assert type_issue.message == (
        "Return a string value; the rejected value has safe JSON type `object`."
    )
    assert type_issue.violated_condition == (
        "closed schema constraint string_type; received JSON type `object`"
    )
    assert length_issue.message == (
        "Return at least 2 items; the response has 1 items, but only 0 passed nested item "
        "validation. Fix the item errors at their reported paths."
    )
    assert length_issue.violated_condition == (
        "closed schema minimum length 2; response length 1, validated length 0"
    )
    assert "private" not in diagnostic.feedback
    assert "do-not-persist" not in diagnostic.feedback


def test_pydantic_numeric_floor_feedback_discloses_the_safe_schema_bound() -> None:
    """A correction can select a valid retry count without seeing raw output."""

    class RetryProbe(BaseModel):
        model_config = ConfigDict(strict=True)

        maximum_attempts: Annotated[int, Field(ge=1)]

    with pytest.raises(ValidationError) as captured:
        RetryProbe.model_validate({"maximum_attempts": 0})

    diagnostic = pydantic_validation_diagnostic(
        captured.value,
        owner_component="design",
        validation_phase="tool_semantics",
        frontier_ordinal=20,
    )

    issue = diagnostic.issues[0]
    assert issue.code == "schema_greater_than_equal"
    assert issue.location == ("maximum_attempts",)
    assert issue.message == "Return a numeric value greater than or equal to 1."
    assert issue.violated_condition == "closed schema lower bound 1 (inclusive)"
    assert issue.expected_category == "a numeric value greater than or equal to 1"
    assert issue.actionable_for_agent is True


@pytest.mark.asyncio
async def test_one_shot_marks_provider_contract_rejection_non_retryable(
    tmp_path: Path,
) -> None:
    """A known provider contract rejection must not authorize a blind re-dispatch."""

    definition = _definition()
    backend = _ProviderRejectedBackend()
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
            dispatch_id="dispatch:one-shot:provider-rejected",
            lineage_id="lineage:one-shot:provider-rejected",
            workspace=tmp_path / "provider-rejected",
            model=_StrictOneShotOutput,
            prompt="Produce the requested title object.",
            permissions=PermissionScope(),
        )

    failure = captured.value
    assert len(backend.requests) == 1
    assert failure.code == "agent_backend_turn_failed_provider_rejected"
    assert failure.retryable is False


@pytest.mark.asyncio
async def test_one_shot_routes_codex_stream_disconnect_to_bounded_infrastructure_recovery(
    tmp_path: Path,
) -> None:
    """A closed stream-interruption fact is not a semantic correction request."""

    definition = _definition()
    backend = _ProviderDisconnectBackend()
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
            dispatch_id="dispatch:one-shot:provider-disconnect",
            lineage_id="lineage:one-shot:provider-disconnect",
            workspace=tmp_path / "provider-disconnect",
            model=_StrictOneShotOutput,
            prompt="Produce the requested title object.",
            permissions=PermissionScope(),
        )

    failure = captured.value
    assert len(backend.requests) == 1
    assert failure.code == "agent_backend_turn_failed_provider_unavailable"
    assert failure.category == (
        "the Codex Provider response stream disconnected before a terminal response"
    )
    assert failure.expected_category == (
        "a recovered Codex Provider route followed by an authorized bounded infrastructure "
        "retry; do not issue a model correction"
    )
    assert failure.retryable is True
    assert "TOP_SECRET_PROVIDER_TRANSCRIPT" not in failure.category


@pytest.mark.asyncio
async def test_one_shot_routes_direct_started_stream_stall_to_liveness_recovery(
    tmp_path: Path,
) -> None:
    """A silent stream gets transport feedback, never a fabricated model correction."""

    definition = _definition()
    backend = _DirectProviderStreamStalledBackend()
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
            dispatch_id="dispatch:one-shot:direct-stream-stalled",
            lineage_id="lineage:one-shot:direct-stream-stalled",
            workspace=tmp_path / "direct-stream-stalled",
            model=_StrictOneShotOutput,
            prompt="Produce the requested title object.",
            permissions=PermissionScope(),
        )

    failure = captured.value
    assert len(backend.requests) == 1
    assert failure.code == "agent_backend_direct_provider_stream_stalled"
    assert failure.category == (
        "the Direct Provider stream emitted 4 event(s) then yielded no next event for 300 seconds"
    )
    assert failure.expected_category == (
        "a profile-matched Direct Provider liveness control and either a corrected Direct "
        "stream/route boundary or one Scheduler-authorized fresh physical execution; do not "
        "change the Prompt or Runtime Skill without semantic output"
    )
    assert failure.remediation == (
        "Inspect the safe Provider-event count, idle interval, and local waiting heartbeat; "
        "run one profile-matched Direct control. If that control passes, treat this as one "
        "stalled stream and repair the Direct route/proxy/adapter boundary or use only an "
        "existing Scheduler-authorized retry."
    )
    assert failure.retryable is True
    assert failure.terminal_details == {
        "waiting_phase": "direct_awaiting_stream_event",
        "idle_timeout_seconds": 300,
        "observed_provider_event_count": 4,
    }
    assert "TOP_SECRET_PROVIDER_TRANSCRIPT" not in repr(failure)


@pytest.mark.asyncio
async def test_one_shot_routes_provider_quota_to_external_recovery(
    tmp_path: Path,
) -> None:
    """Quota exhaustion is not an Agent correction or an identical retry."""

    definition = _definition()
    backend = _QuotaExhaustedBackend()
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
            dispatch_id="dispatch:one-shot:quota-exhausted",
            lineage_id="lineage:one-shot:quota-exhausted",
            workspace=tmp_path / "quota-exhausted",
            model=_StrictOneShotOutput,
            prompt="Produce the requested title object.",
            permissions=PermissionScope(),
        )

    failure = captured.value
    assert len(backend.requests) == 1
    assert failure.code == "agent_backend_turn_failed_quota_exhausted"
    assert failure.category == "the configured Provider reported that its quota is exhausted"
    assert failure.expected_category == (
        "restored Provider quota or an explicitly authorized model/provider route; "
        "do not issue a model correction or blind retry"
    )
    assert failure.retryable is False
    assert "TOP_SECRET_PROVIDER_TRANSCRIPT" not in failure.category
    assert failure.remediation == (
        "Restore quota or select an explicitly authorized Provider/model route; do not replay "
        "this physical attempt."
    )


@pytest.mark.asyncio
async def test_one_shot_routes_session_budget_to_a_new_declared_envelope(
    tmp_path: Path,
) -> None:
    """A session cap is neither account quota nor a semantic repair signal."""

    definition = _definition()
    backend = _SessionBudgetExhaustedBackend()
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
            dispatch_id="dispatch:one-shot:session-budget-exhausted",
            lineage_id="lineage:one-shot:session-budget-exhausted",
            workspace=tmp_path / "session-budget-exhausted",
            model=_StrictOneShotOutput,
            prompt="Produce the requested title object.",
            permissions=PermissionScope(),
        )

    failure = captured.value
    assert len(backend.requests) == 1
    assert failure.code == "agent_backend_turn_failed_session_budget_exhausted"
    assert failure.category == (
        "the Codex Agent session exhausted its declared rollout token budget before returning "
        "a result"
    )
    assert failure.expected_category == (
        "a new diagnostic definition with a larger declared rollout-token budget, a smaller or "
        "split effective runtime input, or a narrower Runtime Skill scope; do not issue a model "
        "correction or blind retry"
    )
    assert failure.retryable is False
    assert failure.terminal_details == {
        "terminal_error_shape": "object",
        "codex_error_info": "enum:sessionbudgetexceeded",
    }
    assert "TOP_SECRET_PROVIDER_TRANSCRIPT" not in repr(failure.terminal_details)


@pytest.mark.asyncio
async def test_one_shot_projects_safe_direct_json_diagnostic_without_blind_retry(
    tmp_path: Path,
) -> None:
    """The scheduler receives parser facts, never the provider transcript."""

    definition = _definition()
    backend = _DirectInvalidJsonBackend()
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
            dispatch_id="dispatch:one-shot:invalid-json",
            lineage_id="lineage:one-shot:invalid-json",
            workspace=tmp_path / "invalid-json",
            model=_StrictOneShotOutput,
            prompt="Produce the requested title object.",
            permissions=PermissionScope(),
        )

    failure = captured.value
    assert len(backend.requests) == 1
    assert failure.code == "agent_backend_direct_structured_output_invalid_json"
    assert failure.category == (
        "structured JSON response invalid (shape=markdown_fence; parse=syntax; offset=0; chars=73)"
    )
    assert failure.retryable is False
    assert "TOP_SECRET_PROVIDER_TRANSCRIPT" not in failure.category


@pytest.mark.asyncio
async def test_one_shot_projects_output_limit_as_a_new_policy_choice(
    tmp_path: Path,
) -> None:
    """A ceiling terminal directs a new declared policy, never an in-attempt retry."""

    definition = _definition().model_copy(
        update={
            "proposal_policy": _definition().proposal_policy.model_copy(
                update={
                    "budget": _definition().proposal_policy.budget.model_copy(
                        update={"llm_tokens": 65_536}
                    )
                }
            )
        }
    )
    backend = _DirectOutputLimitBackend()
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
            dispatch_id="dispatch:one-shot:output-limit",
            lineage_id="lineage:one-shot:output-limit",
            workspace=tmp_path / "output-limit",
            model=_StrictOneShotOutput,
            prompt="Produce the requested title object.",
            permissions=PermissionScope(),
        )

    failure = captured.value
    assert len(backend.requests) == 1
    assert failure.code == "agent_backend_direct_output_limit"
    assert failure.category == (
        "the provider stopped because the declared structured output token limit was exhausted "
        "(max_output_tokens=65536)"
    )
    assert failure.expected_category == (
        "a new diagnostic definition with an explicitly changed structured output-token budget "
        "(the failed attempt declared 65536) or a smaller bounded structured response; never "
        "a blind retry of this attempt"
    )
    assert failure.retryable is False


@pytest.mark.asyncio
async def test_agentic_output_limit_retains_only_a_private_resumable_session(
    tmp_path: Path,
) -> None:
    """A 5M logical session does not turn one Provider ceiling into completion."""

    definition = structured_agent_work_definition(
        scope_id="job:one-shot",
        component="design",
        stage="world_rules",
        artifact_slot="world_rules",
        dependency_coordinates=(),
        claim_id="design.world_rules.compiles",
        claim="One read-only Agent proposal compiles the frozen world rules.",
        timing_reason="The next physical Agent turn may resume only after a closed ceiling.",
        output_contract_id="contract:world-rules",
        agent_role="environment_engineer",
        allowed_mutation_roots=("/implementation-plan",),
        agent_wall_seconds=720,
        agent_token_limit=125_000,
        session_token_limit=5_000_000,
        session_wall_seconds=28_800,
        maximum_session_continuations=39,
    )
    backend = _AgenticOutputLimitBackend()
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
            dispatch_id="dispatch:one-shot:agentic-output-limit",
            lineage_id="lineage:one-shot:agentic-output-limit",
            workspace=tmp_path / "agentic-output-limit",
            model=_StrictOneShotOutput,
            prompt="Produce the requested title object.",
            permissions=PermissionScope(),
            capability_requirement=NodeCapabilityRequirement.structured_read(
                node_id="environment-engineer.implementation-plan",
                role="environment-engineer",
            ),
        )

    failure = captured.value
    assert len(backend.requests) == 1
    assert backend.requests[0].execution_mode is InvocationExecutionMode.AGENTIC
    assert backend.requests[0].profile.rollout_token_limit == 5_000_000
    assert failure.code == "turn_failed_output_limit"
    assert failure.session_continuation is not None
    assert failure.session_continuation.session.thread_id == "private-output-limit-thread"
    assert failure.session_continuation.output_schema_digest == sha256_digest(
        canonical_json_bytes(_StrictOneShotOutput.model_json_schema(mode="validation"))
    )


@pytest.mark.asyncio
async def test_bc44_provider_rejection_cannot_authorize_a_scheduler_retry(
    tmp_path: Path,
) -> None:
    """BC-44: a generic worker retry flag cannot spend a second physical turn."""

    definition = _definition()
    assert definition.repair_policy.maximum_infrastructure_retries == 1
    graph = GenerationWorkGraph.compile((definition,), mode="diagnostic")
    artifacts = ArtifactStore(tmp_path / "artifacts").issue_writer(
        producer="work-controller",
        allowed_artifact_type_prefixes=("control.", "design."),
    )
    context_ref = artifacts.put_json(
        artifact_id="context:bc-44",
        artifact_type="control.generation_context",
        value={"case": "BC-44"},
    )
    manifest = graph.manifest(
        topology_id="topology:bc-44-provider-rejection",
        external_root_refs=(context_ref,),
    )
    manifest_ref = artifacts.put_json(
        artifact_id=manifest.graph_id,
        artifact_type="control.work_graph_manifest",
        value=manifest,
        dependencies=(context_ref,),
    )
    heads = WorkControlStore(tmp_path / "work-control")
    runtime = WorkControlRuntime(
        artifacts=artifacts,
        heads=heads,
        budget=LeaseBudgetLedger(
            Budget(
                llm_tokens=2_000,
                agent_turns=2,
                repair_attempts=1,
                wall_seconds=300,
            )
        ),
    )
    scheduler = WorkScheduler(
        graph=graph,
        manifest=manifest,
        manifest_ref=manifest_ref,
        heads=heads,
        artifacts=artifacts,
        runtime=runtime,
    )
    leaf = SchedulerLeafExecutor(runtime=runtime)
    backend = _ProviderRejectedBackend()
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

    async def proposal(_context, attempt: WorkAttempt, dispatch_id: str):
        return await invoke_structured_once(
            backend=backend,
            profiles=profiles,
            definition=definition,
            attempt=attempt,
            dispatch_id=dispatch_id,
            lineage_id="lineage:bc-44",
            workspace=tmp_path / "isolated-researcher",
            model=_StrictOneShotOutput,
            prompt="Produce the requested title object.",
            permissions=PermissionScope(),
        )

    async def execute(context) -> None:
        await leaf.execute(context, definition=definition, proposal_runner=proposal)

    results = await scheduler.run_until_stalled(executors={definition.work_id: execute})

    assert [result.after_state for result in results] == ["blocked"]
    assert len(backend.requests) == 1
    assert backend.requests[0].execution_mode is InvocationExecutionMode.SINGLE_SHOT_STRUCTURED
    head = heads.read_head(definition.coordinate)
    assert head is not None
    assert head.status == "failed"
    assert head.repair_action_ref is None
    assert not runtime.repairs.entries
    attempt = artifacts.get_json(head.attempt_ref, WorkAttempt)
    assert attempt.validation_report_ref is not None
    report = artifacts.get_json(attempt.validation_report_ref, ValidationReport)
    assert report.status == "error"
    assert report.infrastructure_retryable is False
    assert report.issues[0].code == "agent_backend_turn_failed_provider_rejected"


@pytest.mark.asyncio
async def test_scheduler_passes_a_parsed_direct_candidate_only_to_its_authorized_repair(
    tmp_path: Path,
) -> None:
    """A stateless repair gets data plus feedback, never a fake Provider session.

    This crosses the real Scheduler -> leaf -> structured invocation boundary
    twice.  The first Direct response is shape-valid but semantically rejected;
    the second physical Direct request must carry only the parsed prior object
    and the safe correction brief that the Scheduler authorized in between.
    """

    definition = structured_agent_work_definition(
        scope_id="job:direct-semantic-repair-seed",
        component="research",
        stage="research_plan",
        artifact_slot="research_plan",
        dependency_coordinates=(),
        claim_id="research.plan.valid",
        claim="One stateless Researcher response satisfies the repairable plan contract.",
        timing_reason="A correction needs the rejected parsed plan and its exact finding.",
        output_contract_id="contract:research-plan",
        agent_role="researcher",
        allowed_mutation_roots=("/",),
        agent_wall_seconds=30,
        agent_token_limit=1_000,
        maximum_local_corrections=1,
        strict_progress_bonus_corrections=0,
        maximum_infrastructure_retries=0,
        maximum_model_fallbacks=0,
        maximum_total_repair_attempts=1,
    )
    graph = GenerationWorkGraph.compile((definition,), mode="diagnostic")
    artifacts = ArtifactStore(tmp_path / "artifacts").issue_writer(
        producer="work-controller",
        allowed_artifact_type_prefixes=("control.", "design."),
    )
    context_ref = artifacts.put_json(
        artifact_id="context:direct-semantic-repair-seed",
        artifact_type="control.generation_context",
        value={"case": "stateless semantic repair seed"},
    )
    manifest = graph.manifest(
        topology_id="topology:direct-semantic-repair-seed",
        external_root_refs=(context_ref,),
    )
    manifest_ref = artifacts.put_json(
        artifact_id=manifest.graph_id,
        artifact_type="control.work_graph_manifest",
        value=manifest,
        dependencies=(context_ref,),
    )
    heads = WorkControlStore(tmp_path / "work-control")
    runtime = WorkControlRuntime(
        artifacts=artifacts,
        heads=heads,
        budget=LeaseBudgetLedger(
            Budget(
                llm_tokens=2_000,
                agent_turns=2,
                repair_attempts=1,
                wall_seconds=300,
            )
        ),
    )
    scheduler = WorkScheduler(
        graph=graph,
        manifest=manifest,
        manifest_ref=manifest_ref,
        heads=heads,
        artifacts=artifacts,
        runtime=runtime,
    )
    kernel = SchedulerLeafExecutor(runtime=runtime)
    backend = _SequenceOutputBackend(
        [{"title": "prior-invalid-title"}, {"title": "repaired-title"}]
    )
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
    received_seeds = []

    def semantic_validator(value: _StrictOneShotOutput) -> None:
        if value.title == "prior-invalid-title":
            raise StructuredSemanticError(
                (
                    StructuredSemanticIssue(
                        code="research_plan_title_requires_repair",
                        location=("title",),
                        message="The title must name the repaired research plan.",
                        violated_condition="the title still names the rejected plan",
                        expected_category="a title for the repaired research plan",
                    ),
                )
            )

    async def proposal(context, attempt: WorkAttempt, dispatch_id: str) -> LeafProposal:
        seed = kernel.agent_semantic_repair_seed(
            context,
            definition=definition,
            attempt=attempt,
        )
        received_seeds.append(seed)
        turn = await invoke_structured_once(
            backend=backend,
            profiles=profiles,
            definition=definition,
            attempt=attempt,
            dispatch_id=dispatch_id,
            lineage_id="lineage:direct-semantic-repair-seed",
            workspace=tmp_path / "direct-semantic-repair" / attempt.attempt_id,
            model=_StrictOneShotOutput,
            prompt="Produce one research plan title.",
            permissions=PermissionScope(),
            semantic_validator=semantic_validator,
            correction_brief=kernel.agent_correction_brief(context, definition=definition),
            semantic_repair_seed=seed,
        )
        output_ref = artifacts.put_json(
            artifact_id=f"research-plan:{attempt.ordinal}",
            artifact_type="design.research_plan",
            value=turn.output,
            dependencies=context.external_input_refs,
        )
        return LeafProposal(
            output_refs=(output_ref,),
            subject_refs=(output_ref,),
            observed_actual=turn.observed_actual,
            unknown_upper_bound=turn.unknown_upper_bound,
            agent=turn.agent,
        )

    async def execute(context) -> None:
        await kernel.execute(context, definition=definition, proposal_runner=proposal)

    results = await scheduler.run_until_stalled(executors={definition.work_id: execute})

    assert [result.after_state for result in results] == ["repair_ready", "committed"]
    assert len(backend.requests) == 2
    assert received_seeds[0] is None
    assert received_seeds[1] is not None
    assert received_seeds[1].previous_candidate == {"title": "prior-invalid-title"}
    assert backend.requests[0].session is None
    assert backend.requests[1].session is None
    assert "<prior_candidate_json>" not in backend.requests[0].prompt
    prior_candidate_marker = '<prior_candidate_json>\n{"title":"prior-invalid-title"}'
    assert prior_candidate_marker in backend.requests[1].prompt
    assert "the title still names the rejected plan" in backend.requests[1].prompt
    assert "repair_action_ref" not in backend.requests[1].prompt
    head = heads.read_head(definition.coordinate)
    assert head is not None and head.status == "committed"
    assert runtime.repairs.entries[0].outcome == "resolved"


@pytest.mark.asyncio
async def test_one_shot_declares_json_envelope_without_weakening_local_validation(
    tmp_path: Path,
) -> None:
    definition = _definition()
    backend = _SemanticOutputBackend()
    profiles = IsolatedAgentProfileProvider(
        AgentBackendConfig(
            model="test-structured-model",
            api_key_environment="AGENT_WORLD_TEST_MODEL_KEY",
            structured_output_transport="json_envelope",
        ),
        source_environment={
            "PATH": "/usr/bin:/bin",
            "AGENT_WORLD_TEST_MODEL_KEY": "test-only-credential",
        },
    )

    turn = await invoke_structured_once(
        backend=backend,
        profiles=profiles,
        definition=definition,
        attempt=_attempt(definition),
        dispatch_id="dispatch:one-shot:json-envelope",
        lineage_id="lineage:one-shot:json-envelope",
        workspace=tmp_path / "json-envelope",
        model=_StrictOneShotOutput,
        prompt="Produce the requested title object.",
        permissions=PermissionScope(),
    )

    assert turn.output.title == "Hotel booking"
    assert len(backend.requests) == 1
    assert "Structured-output transport requirement:" in backend.requests[0].prompt
    assert "every inner double quote" in backend.requests[0].prompt
    assert "every backslash" in backend.requests[0].prompt
    assert "U+005C followed by" in backend.requests[0].prompt
    assert '"title"' in backend.requests[0].prompt


@pytest.mark.asyncio
async def test_one_shot_declares_direct_json_object_without_an_inner_envelope(
    tmp_path: Path,
) -> None:
    definition = _definition()
    backend = _SemanticOutputBackend()
    profiles = IsolatedAgentProfileProvider(
        AgentBackendConfig(
            model="test-structured-model",
            api_key_environment="AGENT_WORLD_TEST_MODEL_KEY",
            structured_output_transport="json_object",
        ),
        source_environment={
            "PATH": "/usr/bin:/bin",
            "AGENT_WORLD_TEST_MODEL_KEY": "test-only-credential",
        },
    )

    turn = await invoke_structured_once(
        backend=backend,
        profiles=profiles,
        definition=definition,
        attempt=_attempt(definition),
        dispatch_id="dispatch:one-shot:json-object",
        lineage_id="lineage:one-shot:json-object",
        workspace=tmp_path / "json-object",
        model=_StrictOneShotOutput,
        prompt="Produce the requested title object.",
        permissions=PermissionScope(),
    )

    assert turn.output.title == "Hotel booking"
    assert len(backend.requests) == 1
    assert "Return the complete requested logical artifact" in backend.requests[0].prompt
    assert "Do not wrap it in an\n`artifact_json` field" in backend.requests[0].prompt


@pytest.mark.asyncio
async def test_one_shot_can_use_a_compact_logical_protocol_without_changing_the_model(
    tmp_path: Path,
) -> None:
    """A compact prompt contract changes transport text, never local parsing."""

    definition = _definition()
    backend = _SemanticOutputBackend()
    profiles = IsolatedAgentProfileProvider(
        AgentBackendConfig(
            model="test-structured-model",
            api_key_environment="AGENT_WORLD_TEST_MODEL_KEY",
            structured_output_transport="json_envelope",
        ),
        source_environment={
            "PATH": "/usr/bin:/bin",
            "AGENT_WORLD_TEST_MODEL_KEY": "test-only-credential",
        },
    )
    protocol = "compact-protocol-test.v1: return one title string field."

    turn = await invoke_structured_once(
        backend=backend,
        profiles=profiles,
        definition=definition,
        attempt=_attempt(definition),
        dispatch_id="dispatch:one-shot:compact-envelope",
        lineage_id="lineage:one-shot:compact-envelope",
        workspace=tmp_path / "compact-envelope",
        model=_StrictOneShotOutput,
        prompt="Produce the requested title object.",
        permissions=PermissionScope(),
        logical_output_protocol=protocol,
    )

    assert turn.output == _StrictOneShotOutput(title="Hotel booking")
    assert len(backend.requests) == 1
    assert protocol in backend.requests[0].prompt
    assert '"title"' not in backend.requests[0].prompt


@pytest.mark.asyncio
async def test_one_shot_carries_a_compact_logical_protocol_over_json_object(
    tmp_path: Path,
) -> None:
    """A Direct JSON object still needs its logical output instructions."""

    definition = _definition()
    backend = _SemanticOutputBackend()
    profiles = IsolatedAgentProfileProvider(
        AgentBackendConfig(
            model="test-structured-model",
            api_key_environment="AGENT_WORLD_TEST_MODEL_KEY",
            structured_output_transport="json_object",
        ),
        source_environment={
            "PATH": "/usr/bin:/bin",
            "AGENT_WORLD_TEST_MODEL_KEY": "test-only-credential",
        },
    )
    protocol = "compact-protocol-test.v1: return one title string field."

    turn = await invoke_structured_once(
        backend=backend,
        profiles=profiles,
        definition=definition,
        attempt=_attempt(definition),
        dispatch_id="dispatch:one-shot:compact-object",
        lineage_id="lineage:one-shot:compact-object",
        workspace=tmp_path / "compact-object",
        model=_StrictOneShotOutput,
        prompt="Produce the requested title object.",
        permissions=PermissionScope(),
        logical_output_protocol=protocol,
    )

    assert turn.output == _StrictOneShotOutput(title="Hotel booking")
    assert len(backend.requests) == 1
    assert protocol in backend.requests[0].prompt
    assert '"title"' not in backend.requests[0].prompt


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
    assert (
        issue.remediation == "Shared domains must partition every frozen group tool exactly once."
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


@pytest.mark.parametrize(
    ("model", "payload", "expected_code", "expected_condition", "expected_category"),
    (
        (
            ToolSurfacePlan,
            {
                "tool_id": "hotel.search",
                "namespace": "hotel",
                "name": "search",
                "description": "Search bookable hotels.",
                "transport": "runtime",
                "reads_state_entities": ["hotel", "hotel"],
                "writes_state_entities": [],
                "evidence_claim_ids": ["claim-1"],
            },
            "schema_tool_plan_read_state_duplicate",
            "read-state entities must be unique",
            "a read-state entity list without repeats",
        ),
        (
            ToolSurfacePlan,
            {
                "tool_id": "hotel.search",
                "namespace": "hotel",
                "name": "search",
                "description": "Search bookable hotels.",
                "transport": "runtime",
                "reads_state_entities": [],
                "writes_state_entities": [],
                "evidence_claim_ids": ["claim-1"],
            },
            "schema_tool_plan_state_footprint_empty",
            "a tool plan must read or write at least one state entity",
            "a non-empty read/write state footprint",
        ),
        (
            ToolInterfaceSourceDraft,
            {"input_fields": [], "output_fields": [], "observation_fields": []},
            "schema_tool_interface_result_fields_missing",
            "a tool interface must expose a result",
            "at least one output or observation field",
        ),
        (
            ActorAuthoritySourceDraft,
            {"actor": "guest", "authorities": ["book", "book"]},
            "schema_actor_authority_duplicate",
            "actor authorities must be unique",
            "an authority list without repeats",
        ),
    ),
)
def test_bc14_designer_semantic_validators_keep_a_repairable_identity(
    model: type[BaseModel],
    payload: dict[str, JsonValue],
    expected_code: str,
    expected_condition: str,
    expected_category: str,
) -> None:
    """BC-14: a Rule/ToolSemantics-path violation must stay field-addressable.

    These validators previously raised an untyped ``ValueError``, which the
    canonical translator could only render as the generic, non-actionable
    ``framework_diagnostic_incomplete`` -- discarding the real violated
    condition and denying the Agent any repairable identity.  Each case now
    proves the stable code, the safe condition, and the expected category all
    survive translation.
    """

    # Production validates provider output in JSON mode (see
    # ``invoke_structured_once``): these contracts are strict, and their tuple
    # fields arrive as JSON arrays.  Python-mode validation would reject the
    # shape before the semantic validator under test could run.
    with pytest.raises(ValidationError) as captured:
        model.model_validate_json(json.dumps(payload))

    diagnostic = pydantic_validation_diagnostic(
        captured.value,
        owner_component="design",
        validation_phase="semantic_contract",
        frontier_ordinal=3,
    )

    codes = {issue.code for issue in diagnostic.issues}
    assert "framework_diagnostic_incomplete" not in codes
    issue = next(item for item in diagnostic.issues if item.code == expected_code)
    assert issue.violated_condition == expected_condition
    assert issue.expected_category == expected_category
    assert issue.actionable_for_agent is True
    assert diagnostic.actionable_for_agent is True


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
                remediation="Partition the listed frozen tool ids exactly once.",
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
    assert "Partition the listed frozen tool ids exactly once." in rendered
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
                    "budget": base.proposal_policy.budget.model_copy(update={"wall_seconds": 0.01})
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
