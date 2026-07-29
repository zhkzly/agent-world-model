"""Real, diagnostic-only audit of every distinct Agent invocation lane.

The normal pipeline proves semantic nodes with frozen inputs.  This module is
deliberately narrower: it proves that the configured model/profile/adapter
mechanisms can make one observable InvocationBackend round trip before a node
failure is blamed on its Prompt, Runtime Skill, or semantic compiler.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import tempfile
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, TypedDict, cast

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from agent_world.agent_profiles import IsolatedAgentProfileProvider
from agent_world.builder.models import CandidateCompletion
from agent_world.config import FoundryConfig
from agent_world.contracts import PermissionScope, canonical_json_bytes
from agent_world.control import TelemetryStore

from .capabilities import NodeCapabilityRequirement
from .codex_sdk import CodexSdkBackend
from .contracts import (
    DiagnosticCommandExpectation,
    InvocationBackend,
    InvocationExecutionMode,
    InvocationOwnerKind,
    InvocationOwnership,
    InvocationRequest,
    InvocationResult,
    ResolvedAgentProfile,
)
from .control_plane import InvocationControlPlane
from .control_store import InvocationControlStore
from .direct_llm import DirectLlmBackend
from .redaction import (
    Redactor,
    redacted_command_diagnostic_excerpt,
    redacted_terminal_diagnostic_excerpt,
)
from .routing import RoutedInvocationBackend
from .structured_diagnostics import safe_terminal_details

type AuditStatus = Literal["running", "passed", "failed", "interrupted"]
type AuditBackend = Literal["direct_llm", "codex_sdk"]
type AuditOutputContract = Literal["status", "candidate_completion_blocked"]
type AuditStructuredOutputKind = Literal[
    "not_evaluated",
    "exact_match",
    "missing",
    "non_object",
    "status_mismatch",
    "candidate_completion_invalid",
    "candidate_completion_unexpected_completed",
    "candidate_completion_blocking_reason_mismatch",
]
type AuditStructuredOutputIssueCode = Literal[
    "completion_blocking_reason_missing",
    "completion_blocked_claims_outputs",
    "completion_completed_has_blocker",
    "completion_missing_declarations",
    "completion_public_tests_missing",
    "completion_files_missing",
    "completion_file_declarations_duplicate",
    "completion_required_role_missing",
    "completion_public_test_role_invalid",
    "schema_value",
]
type AuditStructuredOutputValidationCategory = Literal[
    "candidate_rule",
    "missing_required_field",
    "unexpected_field",
    "literal_mismatch",
    "container_shape_mismatch",
    "scalar_type_mismatch",
    "value_constraint",
    "other_schema_validation",
]


class _SafeProfileDetails(TypedDict):
    profile_digest: str | None
    runtime_skill_names: tuple[str, ...]
    developer_instructions_sha256: str | None


_STATUS_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {"status": {"type": "string", "enum": ["ok"]}},
    "required": ["status"],
    "additionalProperties": False,
}
_STATUS_VALUE: dict[str, object] = {"status": "ok"}
_CANDIDATE_COMPLETION_BLOCKED_VALUE: dict[str, object] = {
    "status": "blocked",
    "blocking_reason": "invocation-audit-complete",
}
_STATUS_FILENAME = "invocation-audit.json"
_RUN_RECORDS_DIRECTORY = "invocation-audit-runs"
_DEBUG_DIRECTORY = "invocation-audit-debug"
_RUN_ID_PREFIX = "invocation-audit:"
_CANDIDATE_COMPLETION_SAFE_ISSUE_CODES = frozenset(
    {
        "completion_blocking_reason_missing",
        "completion_blocked_claims_outputs",
        "completion_completed_has_blocker",
        "completion_missing_declarations",
        "completion_public_tests_missing",
        "completion_files_missing",
        "completion_file_declarations_duplicate",
        "completion_required_role_missing",
        "completion_public_test_role_invalid",
    }
)
_WORKSPACE_TOOLCHAIN_EXPECTATIONS: tuple[DiagnosticCommandExpectation, ...] = (
    # This is deliberately an observation, not an additional Candidate or
    # runtime contract. It separates a missing/wrong workspace view from a
    # visible executable whose ELF runtime cannot start in bwrap.
    DiagnosticCommandExpectation(
        label="workspace_toolchain_visible",
        command_fragment=(
            "test -x ./.agent-world-tools/uv && test -x ./.agent-world-tools/python3.12"
        ),
    ),
    DiagnosticCommandExpectation(
        label="uv_version",
        command_fragment="./.agent-world-tools/uv --version",
    ),
    DiagnosticCommandExpectation(
        label="python312_version",
        command_fragment="./.agent-world-tools/python3.12 --version",
    ),
)
_WORKSPACE_TOOLCHAIN_EXECUTION_LABELS = ("uv_version", "python312_version")
type AuditCommandProofState = Literal[
    "unobserved",
    "unknown",
    "not_found",
    "not_executable",
    "failed",
    "succeeded",
]


@dataclass(frozen=True, slots=True)
class _AuditLane:
    lane_id: str
    node_id: str
    role: Literal["researcher", "environment-engineer", "challenger"]
    capability: Literal["structured_output", "structured_read", "isolated_build", "solver"]
    execution_mode: InvocationExecutionMode
    expected_backend: AuditBackend
    workspace_write: bool = False
    # A workspace-write marker alone proves neither that the isolated build
    # toolchain is executable nor that the runtime Agent used the stable
    # workspace-relative entrypoints.  Keep this audit-only proof explicit so
    # a future CandidateBuild stall has one narrow, truthful prerequisite.
    workspace_toolchain: bool = False
    require_session_resume: bool = False
    output_contract: AuditOutputContract = "status"
    # A terminal excerpt is an opt-in local diagnostic aid only. It is never
    # normal Agent feedback, an Artifact field, or part of the compact report.
    diagnostic_terminal_excerpt: bool = False


_AUDIT_LANES: tuple[_AuditLane, ...] = (
    _AuditLane(
        lane_id="direct_researcher_structured",
        node_id="researcher.evidence-synthesis",
        role="researcher",
        capability="structured_output",
        execution_mode=InvocationExecutionMode.SINGLE_SHOT_STRUCTURED,
        expected_backend="direct_llm",
    ),
    _AuditLane(
        lane_id="direct_engineer_structured",
        node_id="environment-engineer.tool-semantics-batch",
        role="environment-engineer",
        capability="structured_output",
        execution_mode=InvocationExecutionMode.SINGLE_SHOT_STRUCTURED,
        expected_backend="direct_llm",
    ),
    _AuditLane(
        lane_id="direct_challenger_structured",
        node_id="challenger.verifier-compile-batch",
        role="challenger",
        capability="structured_output",
        execution_mode=InvocationExecutionMode.SINGLE_SHOT_STRUCTURED,
        expected_backend="direct_llm",
    ),
    _AuditLane(
        lane_id="codex_researcher_read",
        node_id="researcher.structured-output",
        role="researcher",
        capability="structured_read",
        execution_mode=InvocationExecutionMode.AGENTIC,
        expected_backend="codex_sdk",
        require_session_resume=True,
    ),
    _AuditLane(
        lane_id="codex_engineer_implementation_plan_read",
        node_id="environment-engineer.implementation-plan",
        role="environment-engineer",
        capability="structured_read",
        execution_mode=InvocationExecutionMode.AGENTIC,
        expected_backend="codex_sdk",
        require_session_resume=True,
    ),
    _AuditLane(
        lane_id="codex_engineer_workspace_write",
        node_id="environment-engineer.runtime-build",
        role="environment-engineer",
        capability="isolated_build",
        execution_mode=InvocationExecutionMode.AGENTIC,
        expected_backend="codex_sdk",
        workspace_write=True,
        require_session_resume=True,
    ),
    _AuditLane(
        # This is deliberately separate from workspace-write proof: a failed
        # file redirect must not be mistaken for an unavailable tool facade.
        lane_id="codex_engineer_workspace_toolchain",
        node_id="environment-engineer.runtime-build",
        role="environment-engineer",
        capability="isolated_build",
        execution_mode=InvocationExecutionMode.AGENTIC,
        expected_backend="codex_sdk",
        workspace_toolchain=True,
        require_session_resume=True,
    ),
    _AuditLane(
        lane_id="codex_engineer_candidate_completion",
        node_id="environment-engineer.runtime-build",
        role="environment-engineer",
        capability="isolated_build",
        execution_mode=InvocationExecutionMode.AGENTIC,
        expected_backend="codex_sdk",
        workspace_write=True,
        output_contract="candidate_completion_blocked",
        diagnostic_terminal_excerpt=True,
    ),
    _AuditLane(
        lane_id="codex_challenger_solver",
        node_id="challenger.reachability-solver",
        role="challenger",
        capability="solver",
        execution_mode=InvocationExecutionMode.AGENTIC,
        expected_backend="codex_sdk",
        require_session_resume=True,
    ),
)
INVOCATION_AUDIT_LANE_IDS: tuple[str, ...] = tuple(item.lane_id for item in _AUDIT_LANES)


class InvocationAuditLaneResult(BaseModel):
    """One safe, durable observation of one configured invocation mechanism."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    lane_id: str
    node_id: str
    role: str
    capability: str
    execution_mode: str
    expected_backend: AuditBackend
    output_contract: AuditOutputContract
    structured_output_transport: str | None = None
    profile_digest: str | None = None
    runtime_skill_names: tuple[str, ...] = ()
    developer_instructions_sha256: str | None = None
    physical_turn_count: int = 0
    physical_turns: tuple[InvocationAuditPhysicalTurn, ...] = ()
    failure_phase: str | None = None
    same_backend_session_resume_verified: bool | None = None
    session_continuity_scope: Literal["same_backend_instance"] | None = None
    status: AuditStatus
    started_at: str
    updated_at: str
    duration_ms: int | None = None
    failure_code: str | None = None
    retryable: bool | None = None
    terminal_details: dict[str, object] = Field(default_factory=dict)
    provider_event_count: int | None = None
    activity_event_counts: dict[str, int] = Field(default_factory=dict)
    workspace_write_verified: bool | None = None
    workspace_toolchain_verified: bool | None = None
    workspace_toolchain_command_proofs: dict[str, AuditCommandProofState] = Field(
        default_factory=dict
    )
    # This exists only in the diagnostic audit report/run record. Normal
    # telemetry strips it before persistence; it is a bounded, re-scrubbed
    # shell failure clue rather than model feedback or an Artifact field.
    workspace_toolchain_command_diagnostics: dict[str, str] = Field(default_factory=dict)
    # A local, explicitly opted-in terminal excerpt may be available at this
    # path. The ordinary report retains only the path and closed terminal
    # facts; the text itself remains in a bounded, re-scrubbed sidecar.
    diagnostic_terminal_feedback_path: str | None = None
    # A closed, text-free explanation of why the audit response did not match
    # its own requested output.  This lets a project-execution Agent distinguish
    # Prompt/Skill, transport/parser, and feedback hypotheses without retaining
    # an arbitrary model response in the durable audit record.
    structured_output_observations: tuple[InvocationAuditStructuredOutputObservation, ...] = ()


class InvocationAuditStructuredOutputObservation(BaseModel):
    """One redaction-safe structured-output check for an audit physical turn."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: AuditStructuredOutputKind
    validation_issue_codes: tuple[AuditStructuredOutputIssueCode, ...] = Field(
        default_factory=tuple,
        max_length=3,
    )
    validation_issue_categories: tuple[AuditStructuredOutputValidationCategory, ...] = Field(
        default_factory=tuple,
        max_length=3,
    )


class InvocationAuditPhysicalTurn(BaseModel):
    """Safe terminal evidence for one physical invocation inside an audit lane."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    turn_index: int
    status: Literal["passed", "failed"]
    duration_ms: int
    failure_code: str | None = None
    retryable: bool | None = None
    terminal_details: dict[str, object] = Field(default_factory=dict)


class InvocationAuditReport(BaseModel):
    """A Code-Agent-facing audit view; no prompt or provider output is retained."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    diagnostic_only: Literal[True] = True
    kind: Literal["invocation_audit"] = "invocation_audit"
    run_id: str
    status: AuditStatus
    started_at: str
    updated_at: str
    source_structured_output_transport: str
    structured_output_transport: str
    lanes: tuple[InvocationAuditLaneResult, ...]


async def run_invocation_audit(
    config: FoundryConfig,
    *,
    lane_ids: tuple[str, ...] = (),
    structured_output_transport: Literal["provider_schema", "json_envelope", "json_object"]
    | None = None,
) -> InvocationAuditReport:
    """Exercise every selected real backend/profile lane sequentially.

    This is not a semantic-node replay and never creates a candidate or a
    releasable Artifact.  Each probe uses the actual resolved profile and
    ``RoutedInvocationBackend``; all configured logical envelopes are retained
    rather than replaced by a short diagnostic timeout or token limit.
    """

    selected = _select_lanes(lane_ids)
    source_transport = config.agent.structured_output_transport
    audit_config = _with_transport_override(config, structured_output_transport)
    started_at = _now()
    run_id = f"{_RUN_ID_PREFIX}{uuid.uuid4().hex}"
    state_root = audit_config.state_root
    state_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    if state_root.is_symlink() or not state_root.is_dir():
        raise OSError("invocation audit state root must be a real directory")

    records = [_pending_record(item, started_at) for item in selected]
    _write_report(
        state_root,
        _report(
            run_id=run_id,
            status="running",
            started_at=started_at,
            source_transport=source_transport,
            transport=audit_config.agent.structured_output_transport,
            records=records,
        ),
    )

    telemetry = TelemetryStore(state_root / "telemetry")
    try:
        provider = IsolatedAgentProfileProvider(audit_config.agent)
        routed_backend = RoutedInvocationBackend(
            codex_backend=CodexSdkBackend(telemetry=telemetry),
            direct_backend=DirectLlmBackend(telemetry=telemetry),
            max_concurrent_invocations=audit_config.agent.max_concurrent_invocations,
        )
        control_store = InvocationControlStore(state_root / "invocation-control")
        control_store.reconcile_owner_loss()
        backend: InvocationBackend = InvocationControlPlane(
            routed_backend,
            control_store,
            require_explicit_ownership=True,
        )
        for index, lane in enumerate(selected):
            records[index] = records[index].model_copy(
                update={"status": "running", "updated_at": _now()}
            )
            _write_report(
                state_root,
                _report(
                    run_id=run_id,
                    status="running",
                    started_at=started_at,
                    source_transport=source_transport,
                    transport=audit_config.agent.structured_output_transport,
                    records=records,
                ),
            )
            records[index] = await _run_lane(
                lane,
                provider=provider,
                backend=backend,
                telemetry=telemetry,
                state_root=state_root,
                run_id=run_id,
                rollout_token_limit=_audit_rollout_token_limit(audit_config),
            )
            _write_report(
                state_root,
                _report(
                    run_id=run_id,
                    status="running",
                    started_at=started_at,
                    source_transport=source_transport,
                    transport=audit_config.agent.structured_output_transport,
                    records=records,
                ),
            )
    except asyncio.CancelledError:
        records = [_interrupted_record(record) for record in records]
        _write_report(
            state_root,
            _report(
                run_id=run_id,
                status="interrupted",
                started_at=started_at,
                source_transport=source_transport,
                transport=audit_config.agent.structured_output_transport,
                records=records,
            ),
        )
        raise
    finally:
        telemetry.close()

    status: AuditStatus = "passed" if all(item.status == "passed" for item in records) else "failed"
    final = _report(
        run_id=run_id,
        status=status,
        started_at=started_at,
        source_transport=source_transport,
        transport=audit_config.agent.structured_output_transport,
        records=records,
    )
    _write_report(state_root, final)
    return final


async def _run_lane(
    lane: _AuditLane,
    *,
    provider: IsolatedAgentProfileProvider,
    backend: InvocationBackend,
    telemetry: TelemetryStore,
    state_root: Path,
    run_id: str,
    rollout_token_limit: int,
) -> InvocationAuditLaneResult:
    started_at = _now()
    trace_id = f"{run_id}:{lane.lane_id}"
    marker_expected = lane.workspace_write
    profile: ResolvedAgentProfile | None = None
    workspace_write_verified: bool | None = None
    workspace_toolchain_marker_verified: bool | None = None
    try:
        with tempfile.TemporaryDirectory(
            prefix=f"invocation-audit-{lane.lane_id}-",
            dir=state_root,
        ) as temporary:
            root = Path(temporary)
            try:
                profile = _resolve_profile(
                    lane,
                    provider=provider,
                    workspace=root / "logical",
                    lineage_id=f"{run_id}-{lane.lane_id}",
                    rollout_token_limit=rollout_token_limit,
                )
            except Exception:
                return _exception_record(
                    lane,
                    started_at=started_at,
                    telemetry=telemetry,
                    trace_id=trace_id,
                    phase="profile_resolution",
                    profile=None,
                    workspace_write_verified=None,
                    workspace_toolchain_marker_verified=None,
                )
            marker = profile.workspace / "candidate" / "invocation-audit-marker.txt"
            try:
                invocation_id = f"{lane.lane_id}-{uuid.uuid4().hex}"
                result = await backend.invoke(
                    InvocationRequest(
                        invocation_id=invocation_id,
                        prompt=_prompt_for_lane(lane, profile.structured_output_transport),
                        profile=profile,
                        ownership=_audit_ownership(
                            run_id=run_id,
                            lane=lane,
                            invocation_id=invocation_id,
                        ),
                        metadata={
                            "trace_id": trace_id,
                            "run_id": run_id,
                            "role": lane.role,
                            "semantic_transaction": f"invocation_audit.{lane.lane_id}",
                            "diagnostic_capture_terminal_excerpt": (
                                lane.diagnostic_terminal_excerpt
                            ),
                        },
                        execution_mode=lane.execution_mode,
                        diagnostic_command_expectations=(
                            _WORKSPACE_TOOLCHAIN_EXPECTATIONS if lane.workspace_toolchain else ()
                        ),
                    )
                )
            except Exception:
                workspace_write_verified = _marker_exists(marker) if marker_expected else None
                workspace_toolchain_marker_verified = (
                    _toolchain_marker_verified(marker) if lane.workspace_toolchain else None
                )
                return _exception_record(
                    lane,
                    started_at=started_at,
                    telemetry=telemetry,
                    trace_id=trace_id,
                    phase="backend_invoke",
                    profile=profile,
                    workspace_write_verified=workspace_write_verified,
                    workspace_toolchain_marker_verified=workspace_toolchain_marker_verified,
                )
            resumed_result: InvocationResult | None = None
            if lane.require_session_resume and result.succeeded and result.session is not None:
                try:
                    resumed_invocation_id = f"{lane.lane_id}-resume-{uuid.uuid4().hex}"
                    resumed_result = await backend.invoke(
                        InvocationRequest(
                            invocation_id=resumed_invocation_id,
                            prompt=_resume_prompt_for_lane(
                                lane,
                                profile.structured_output_transport,
                            ),
                            profile=profile,
                            session=result.session,
                            ownership=_audit_ownership(
                                run_id=run_id,
                                lane=lane,
                                invocation_id=resumed_invocation_id,
                            ),
                            metadata={
                                "trace_id": trace_id,
                                "run_id": run_id,
                                "role": lane.role,
                                "semantic_transaction": f"invocation_audit.{lane.lane_id}",
                                "physical_turn": 2,
                                "diagnostic_capture_terminal_excerpt": (
                                    lane.diagnostic_terminal_excerpt
                                ),
                            },
                            execution_mode=lane.execution_mode,
                        )
                    )
                except Exception:
                    workspace_write_verified = _marker_exists(marker) if marker_expected else None
                    workspace_toolchain_marker_verified = (
                        _toolchain_marker_verified(marker) if lane.workspace_toolchain else None
                    )
                    return _exception_record(
                        lane,
                        started_at=started_at,
                        telemetry=telemetry,
                        trace_id=trace_id,
                        phase="session_resume",
                        profile=profile,
                        workspace_write_verified=workspace_write_verified,
                        workspace_toolchain_marker_verified=workspace_toolchain_marker_verified,
                        prior_results=(result,),
                    )
            workspace_write_verified = _marker_exists(marker) if marker_expected else None
            workspace_toolchain_marker_verified = (
                _toolchain_marker_verified(marker) if lane.workspace_toolchain else None
            )
            diagnostic_terminal_feedback_path = _write_diagnostic_terminal_feedback(
                state_root=state_root,
                run_id=run_id,
                lane=lane,
                results=(result,) if resumed_result is None else (result, resumed_result),
            )
            return _result_record(
                lane,
                result=result,
                resumed_result=resumed_result,
                profile=profile,
                started_at=started_at,
                telemetry=telemetry,
                trace_id=trace_id,
                workspace_write_verified=workspace_write_verified,
                workspace_toolchain_marker_verified=workspace_toolchain_marker_verified,
                diagnostic_terminal_feedback_path=diagnostic_terminal_feedback_path,
            )
    except asyncio.CancelledError:
        raise
    except Exception:
        return _exception_record(
            lane,
            started_at=started_at,
            telemetry=telemetry,
            trace_id=trace_id,
            phase="audit_setup",
            profile=profile,
            workspace_write_verified=workspace_write_verified,
            workspace_toolchain_marker_verified=workspace_toolchain_marker_verified,
        )


def _audit_ownership(
    *,
    run_id: str,
    lane: _AuditLane,
    invocation_id: str,
) -> InvocationOwnership:
    """Bind each audit physical turn without exposing its private session."""

    return InvocationOwnership(
        owner_kind=InvocationOwnerKind.DIAGNOSTIC_AUDIT,
        owner_id=invocation_id,
        scope_id=run_id,
        coordinate=f"invocation_audit.{lane.lane_id}",
    )


def _exception_record(
    lane: _AuditLane,
    *,
    started_at: str,
    telemetry: TelemetryStore,
    trace_id: str,
    phase: Literal["profile_resolution", "backend_invoke", "session_resume", "audit_setup"],
    profile: ResolvedAgentProfile | None,
    workspace_write_verified: bool | None,
    workspace_toolchain_marker_verified: bool | None,
    prior_results: tuple[InvocationResult, ...] = (),
) -> InvocationAuditLaneResult:
    """Persist a safe, recipient-actionable failure without raw Provider text."""

    observed, activity = _safe_activity_counts(telemetry, trace_id)
    terminal_details: dict[str, object] = {"phase": phase}
    if profile is not None:
        terminal_details["structured_output_transport"] = profile.structured_output_transport
    profile_details = _safe_profile_details(profile)
    command_proofs = _command_proofs_for_results(lane, prior_results)
    command_diagnostics = _command_diagnostics_for_results(lane, prior_results)
    return InvocationAuditLaneResult(
        lane_id=lane.lane_id,
        node_id=lane.node_id,
        role=lane.role,
        capability=lane.capability,
        execution_mode=lane.execution_mode.value,
        expected_backend=lane.expected_backend,
        output_contract=lane.output_contract,
        structured_output_transport=(
            profile.structured_output_transport if profile is not None else None
        ),
        profile_digest=profile_details["profile_digest"],
        runtime_skill_names=profile_details["runtime_skill_names"],
        developer_instructions_sha256=profile_details["developer_instructions_sha256"],
        physical_turn_count=len(prior_results),
        physical_turns=tuple(
            _physical_turn_record(index + 1, result) for index, result in enumerate(prior_results)
        ),
        session_continuity_scope=("same_backend_instance" if lane.require_session_resume else None),
        failure_phase=phase,
        status="failed",
        started_at=started_at,
        updated_at=_now(),
        failure_code=f"invocation_audit_{phase}_exception",
        retryable=False,
        terminal_details=terminal_details,
        provider_event_count=observed,
        activity_event_counts=activity,
        workspace_write_verified=workspace_write_verified,
        workspace_toolchain_verified=_toolchain_verified(
            lane,
            marker_verified=workspace_toolchain_marker_verified,
            command_proofs=command_proofs,
        ),
        workspace_toolchain_command_proofs=command_proofs,
        workspace_toolchain_command_diagnostics=command_diagnostics,
    )


def _resolve_profile(
    lane: _AuditLane,
    *,
    provider: IsolatedAgentProfileProvider,
    workspace: Path,
    lineage_id: str,
    rollout_token_limit: int,
) -> ResolvedAgentProfile:
    output_schema = _output_schema_for_lane(lane)
    if lane.capability == "solver":
        return provider.resolve_solver(
            lineage_id=lineage_id,
            workspace=workspace,
            output_schema=output_schema,
            rollout_token_limit=rollout_token_limit,
        )
    if lane.capability == "structured_output":
        requirement = NodeCapabilityRequirement.structured_output(
            node_id=lane.node_id,
            role=lane.role,
        )
    elif lane.capability == "structured_read":
        requirement = NodeCapabilityRequirement.structured_read(
            node_id=lane.node_id,
            role=lane.role,
        )
    else:
        requirement = NodeCapabilityRequirement.isolated_build(node_id=lane.node_id)
    return provider.resolve(
        role=lane.role,
        lineage_id=lineage_id,
        workspace=workspace,
        output_schema=output_schema,
        permissions=PermissionScope(),
        requirement=requirement,
        rollout_token_limit=rollout_token_limit,
    )


def _output_schema_for_lane(lane: _AuditLane) -> dict[str, object]:
    """Select the real output surface under audit, never a semantic candidate."""

    if lane.output_contract == "candidate_completion_blocked":
        return CandidateCompletion.model_json_schema(mode="validation")
    return _STATUS_SCHEMA


def _expected_output_for_lane(lane: _AuditLane) -> dict[str, object]:
    if lane.output_contract == "candidate_completion_blocked":
        return _CANDIDATE_COMPLETION_BLOCKED_VALUE
    return _STATUS_VALUE


def _prompt_for_lane(lane: _AuditLane, transport: str) -> str:
    if lane.output_contract == "candidate_completion_blocked":
        base = (
            "This is an isolated production InvocationBackend audit of the Environment Engineer "
            "CandidateCompletion response channel. It is not an environment build. Create exactly "
            "one file candidate/invocation-audit-marker.txt containing the text `ok`; it is "
            "non-semantic audit evidence and must not be declared as candidate output. Do not "
            "inspect unrelated files or run network commands. Then return an honest blocked "
            "CandidateCompletion with blocking_reason `invocation-audit-complete`; do not claim "
            "candidate outputs, files, or declarations."
        )
    elif lane.workspace_toolchain:
        base = (
            "This is an isolated production InvocationBackend audit of the Environment Engineer "
            "workspace toolchain. It is not an environment build. Do not read inputs or create "
            "files. Run exactly these shell commands, in order, and wait for each to complete:\n"
            "test -x ./.agent-world-tools/uv && test -x ./.agent-world-tools/python3.12\n"
            "./.agent-world-tools/uv --version\n"
            "./.agent-world-tools/python3.12 --version\n"
            "Do not substitute bare `uv`, bare `python`, a `.venv`, or a host path. Do not read "
            "unrelated files or run network commands. Then return the required structured "
            "status object."
        )
    elif lane.workspace_write:
        base = (
            "This is an isolated production InvocationBackend audit. Create exactly one file "
            "candidate/invocation-audit-marker.txt containing the text `ok`. Do not read unrelated "
            "files or run network commands. Then return the required structured status object."
        )
    else:
        base = (
            "This is an isolated production InvocationBackend audit. Do not call tools or inspect "
            "unrelated files. Return the required structured status object."
        )
    return _transport_prompt(base, transport, _expected_output_for_lane(lane))


def _marker_exists(marker: Path) -> bool:
    """Accept only a regular audit marker, never a workspace symlink."""

    return marker.is_file() and not marker.is_symlink()


def _toolchain_marker_verified(marker: Path) -> bool:
    """Validate the bounded evidence written by the two required facades.

    This is an audit-only executable-boundary check, not a Candidate business
    contract.  The detailed command transcript remains private to the active
    Agent runtime; the durable report retains only this boolean.
    """

    if not _marker_exists(marker):
        return False
    try:
        lines = marker.read_text(encoding="utf-8").splitlines()
    except OSError:
        return False
    return len(lines) == 2 and lines[0].startswith("uv ") and lines[1].startswith("Python 3.12.")


def _command_proofs_for_results(
    lane: _AuditLane,
    results: tuple[InvocationResult, ...],
) -> dict[str, AuditCommandProofState]:
    """Collapse private event facts into an actionable, transcript-free view."""

    if not lane.workspace_toolchain:
        return {}
    proofs: dict[str, AuditCommandProofState] = {
        item.label: "unobserved" for item in _WORKSPACE_TOOLCHAIN_EXPECTATIONS
    }
    for result in results:
        for event in result.events:
            values = event.payload.get("diagnosticCommandProof")
            if not isinstance(values, list):
                continue
            for value in values:
                if not isinstance(value, dict):
                    continue
                label = value.get("label")
                outcome = value.get("outcome")
                if (
                    not isinstance(label, str)
                    or label not in proofs
                    or outcome
                    not in {"unknown", "not_found", "not_executable", "failed", "succeeded"}
                ):
                    continue
                checked_outcome = cast(AuditCommandProofState, outcome)
                current = proofs[label]
                if checked_outcome == "succeeded" or current != "succeeded":
                    proofs[label] = checked_outcome
    return proofs


def _toolchain_verified(
    lane: _AuditLane,
    *,
    marker_verified: bool | None,
    command_proofs: dict[str, AuditCommandProofState],
) -> bool | None:
    """Combine the workspace evidence with the SDK's closed command facts."""

    if not lane.workspace_toolchain:
        return None
    marker_ok = marker_verified is True if lane.workspace_write else True
    return marker_ok and all(
        command_proofs.get(label) == "succeeded" for label in _WORKSPACE_TOOLCHAIN_EXECUTION_LABELS
    )


def _command_diagnostics_for_results(
    lane: _AuditLane,
    results: tuple[InvocationResult, ...],
) -> dict[str, str]:
    """Retain a small, twice-scrubbed command clue only in audit output."""

    if not lane.workspace_toolchain:
        return {}
    diagnostics: dict[str, str] = {}
    labels = {item.label for item in _WORKSPACE_TOOLCHAIN_EXPECTATIONS}
    for result in results:
        for event in result.events:
            values = event.payload.get("diagnosticCommandProof")
            if not isinstance(values, list):
                continue
            for value in values:
                if not isinstance(value, dict):
                    continue
                label = value.get("label")
                outcome = value.get("outcome")
                if (
                    not isinstance(label, str)
                    or label not in labels
                    or outcome not in {"unknown", "not_found", "not_executable", "failed"}
                ):
                    if isinstance(label, str) and label in labels and outcome == "succeeded":
                        diagnostics.pop(label, None)
                    continue
                parts: list[str] = []
                exit_code = value.get("exitCode")
                if (
                    isinstance(exit_code, int)
                    and not isinstance(exit_code, bool)
                    and 0 <= exit_code <= 255
                ):
                    parts.append(f"exit={exit_code}")
                excerpt = redacted_command_diagnostic_excerpt(
                    value.get("diagnosticExcerpt"),
                    redactor=Redactor.from_values(()),
                )
                if excerpt is not None:
                    parts.append(excerpt)
                diagnostics[label] = "; ".join(parts) if parts else "command failed"
    return diagnostics


def _transport_prompt(base: str, transport: str, expected: dict[str, object]) -> str:
    payload = json.dumps(expected, ensure_ascii=False, separators=(",", ":"))
    if transport == "json_envelope":
        return (
            f"{base}\n\nReturn exactly one outer JSON object with the single key `artifact_json`. "
            f"Its value must be a JSON string encoding exactly {payload}. "
            "Use no Markdown or prose."
        )
    if transport == "json_object":
        return (
            f"{base}\n\nReturn exactly one JSON object: {payload}. "
            "Do not wrap it in `artifact_json`, encode it as a string, use Markdown, or add prose."
        )
    return f"{base}\n\nReturn exactly {payload} and no prose."


def _resume_prompt_for_lane(lane: _AuditLane, transport: str) -> str:
    """Ask for one second physical turn without turning it into a retry.

    The initial turn has already produced a valid object.  This second call
    only proves the same resolved Agentic session can resume under the same
    profile, workspace and logical envelope.  It does not request a semantic
    correction or write any additional candidate source.
    """

    base = (
        "This is physical turn 2 of the same isolated production InvocationBackend audit "
        "session. Do not call tools, inspect unrelated files, or modify the workspace. "
    )
    return _transport_prompt(base, transport, _expected_output_for_lane(lane))


def _result_record(
    lane: _AuditLane,
    *,
    result: InvocationResult,
    resumed_result: InvocationResult | None,
    profile: ResolvedAgentProfile,
    started_at: str,
    telemetry: TelemetryStore,
    trace_id: str,
    workspace_write_verified: bool | None,
    workspace_toolchain_marker_verified: bool | None,
    diagnostic_terminal_feedback_path: str | None,
) -> InvocationAuditLaneResult:
    results = (result,) if resumed_result is None else (result, resumed_result)
    command_proofs = _command_proofs_for_results(lane, results)
    command_diagnostics = _command_diagnostics_for_results(lane, results)
    toolchain_verified = _toolchain_verified(
        lane,
        marker_verified=workspace_toolchain_marker_verified,
        command_proofs=command_proofs,
    )
    physical_turns = tuple(
        _physical_turn_record(index + 1, item) for index, item in enumerate(results)
    )
    structured_output_observations = tuple(
        _structured_output_observation(lane, item) for item in results
    )
    valid_output = all(item.kind == "exact_match" for item in structured_output_observations)
    requires_session = lane.execution_mode is InvocationExecutionMode.AGENTIC
    initial_session_ok = not requires_session or result.session is not None
    resume_ok = not lane.require_session_resume or (
        resumed_result is not None
        and resumed_result.succeeded
        and resumed_result.session is not None
    )
    session_ok = initial_session_ok and resume_ok
    write_ok = workspace_write_verified is not False
    toolchain_ok = toolchain_verified is not False
    passed = valid_output and session_ok and write_ok and toolchain_ok
    if passed:
        failure_code = None
        retryable = None
        terminal_details: dict[str, object] = {}
    elif not result.succeeded or (resumed_result is not None and not resumed_result.succeeded):
        terminal_result = result if not result.succeeded else resumed_result
        assert terminal_result is not None
        failure_code = (
            terminal_result.error.code
            if terminal_result.error is not None
            else terminal_result.status.value
        )
        retryable = terminal_result.error.retryable if terminal_result.error is not None else None
        terminal_details = dict(safe_terminal_details(terminal_result.error))
    elif not session_ok:
        failure_code = "invocation_audit_missing_session"
        retryable = False
        terminal_details = {}
    elif not write_ok:
        failure_code = "invocation_audit_workspace_write_missing"
        retryable = False
        terminal_details = {}
    elif not toolchain_ok:
        failure_code = "invocation_audit_workspace_toolchain_unverified"
        retryable = False
        terminal_details = {}
    else:
        failure_code = "invocation_audit_structured_output_mismatch"
        retryable = False
        terminal_details = {}
    if not result.succeeded:
        failure_phase = "initial"
    elif resumed_result is not None and not resumed_result.succeeded:
        failure_phase = "session_resume"
    elif not session_ok:
        failure_phase = "session_resume" if lane.require_session_resume else "initial"
    elif not write_ok or not toolchain_ok or not valid_output:
        failure_phase = "initial"
    else:
        failure_phase = None
    observed, activity = _safe_activity_counts(telemetry, trace_id)
    profile_details = _safe_profile_details(profile)
    return InvocationAuditLaneResult(
        lane_id=lane.lane_id,
        node_id=lane.node_id,
        role=lane.role,
        capability=lane.capability,
        execution_mode=lane.execution_mode.value,
        expected_backend=lane.expected_backend,
        output_contract=lane.output_contract,
        structured_output_transport=profile.structured_output_transport,
        profile_digest=profile_details["profile_digest"],
        runtime_skill_names=profile_details["runtime_skill_names"],
        developer_instructions_sha256=profile_details["developer_instructions_sha256"],
        physical_turn_count=len(results),
        physical_turns=physical_turns,
        failure_phase=failure_phase,
        same_backend_session_resume_verified=(resume_ok if lane.require_session_resume else None),
        session_continuity_scope=("same_backend_instance" if lane.require_session_resume else None),
        status="passed" if passed else "failed",
        started_at=started_at,
        updated_at=_now(),
        duration_ms=sum(item.duration_ms for item in results),
        failure_code=failure_code,
        retryable=retryable,
        terminal_details=terminal_details,
        provider_event_count=observed,
        activity_event_counts=activity,
        workspace_write_verified=workspace_write_verified,
        workspace_toolchain_verified=toolchain_verified,
        workspace_toolchain_command_proofs=command_proofs,
        workspace_toolchain_command_diagnostics=command_diagnostics,
        diagnostic_terminal_feedback_path=diagnostic_terminal_feedback_path,
        structured_output_observations=structured_output_observations,
    )


def _write_diagnostic_terminal_feedback(
    *,
    state_root: Path,
    run_id: str,
    lane: _AuditLane,
    results: tuple[InvocationResult, ...],
) -> str | None:
    """Persist one bounded terminal excerpt for an explicitly diagnostic lane.

    This is deliberately narrower than ordinary audit reporting. The Worker
    already redacts the Provider terminal text, and this sidecar performs the
    same defensive second scrub used by Doctor before a local Code-Agent view
    is written. No raw request, response, workspace path, or session material
    crosses this boundary.
    """

    if not lane.diagnostic_terminal_excerpt:
        return None
    for result in results:
        if result.error is None:
            continue
        excerpt = redacted_terminal_diagnostic_excerpt(
            result.error.details.get("diagnostic_error_excerpt"),
            redactor=Redactor.from_values(()),
        )
        if excerpt is None:
            continue
        root = state_root / _DEBUG_DIRECTORY
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        if root.is_symlink() or not root.is_dir():
            raise OSError("invocation audit debug directory must be a real directory")
        target = root / f"{_audit_run_token(run_id)}-{lane.lane_id}.json"
        payload = {
            "diagnostic_only": True,
            "failure_code": result.error.code,
            "kind": "invocation_audit_terminal_debug",
            "lane_id": lane.lane_id,
            "run_id": run_id,
            "terminal_error_excerpt": excerpt,
            "updated_at": _now(),
        }
        _write_private_report(
            target,
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
        )
        return str(target)
    return None


def _structured_output_observation(
    lane: _AuditLane,
    result: InvocationResult,
) -> InvocationAuditStructuredOutputObservation:
    """Reduce one audit response to a bounded mismatch category.

    The audit prompt and expected response are non-semantic fixtures, but a
    raw model response still must not enter the durable run record.  Preserve
    only the closed distinction needed to choose the next diagnostic surface.
    """

    if not result.succeeded:
        return InvocationAuditStructuredOutputObservation(kind="not_evaluated")
    output = result.structured_output
    if output is None:
        return InvocationAuditStructuredOutputObservation(kind="missing")
    if not isinstance(output, Mapping):
        return InvocationAuditStructuredOutputObservation(kind="non_object")
    if lane.output_contract == "status":
        return InvocationAuditStructuredOutputObservation(
            kind="exact_match" if output == _STATUS_VALUE else "status_mismatch"
        )
    try:
        # The real Builder validates a Provider JSON result through JSON mode.
        # Keep this audit on that exact acceptance boundary: a decoded empty
        # JSON array is a valid representation of a tuple field, while strict
        # Python-mode validation would incorrectly call it a shape failure.
        completion = CandidateCompletion.model_validate_json(canonical_json_bytes(output))
    except ValidationError as exc:
        return InvocationAuditStructuredOutputObservation(
            kind="candidate_completion_invalid",
            validation_issue_codes=_safe_candidate_completion_issue_codes(exc),
            validation_issue_categories=_safe_candidate_completion_validation_categories(exc),
        )
    if completion.status == "completed":
        return InvocationAuditStructuredOutputObservation(
            kind="candidate_completion_unexpected_completed"
        )
    if completion.blocking_reason != _CANDIDATE_COMPLETION_BLOCKED_VALUE["blocking_reason"]:
        return InvocationAuditStructuredOutputObservation(
            kind="candidate_completion_blocking_reason_mismatch"
        )
    return InvocationAuditStructuredOutputObservation(kind="exact_match")


def _safe_candidate_completion_issue_codes(
    exc: ValidationError,
) -> tuple[AuditStructuredOutputIssueCode, ...]:
    """Keep only built-in CandidateCompletion rule identifiers, never values."""

    codes: list[AuditStructuredOutputIssueCode] = []
    for item in exc.errors():
        observed = item.get("type")
        code: AuditStructuredOutputIssueCode = (
            cast(AuditStructuredOutputIssueCode, observed)
            if observed in _CANDIDATE_COMPLETION_SAFE_ISSUE_CODES
            else "schema_value"
        )
        if code not in codes:
            codes.append(code)
        if len(codes) == 3:
            break
    return tuple(codes or ("schema_value",))


def _safe_candidate_completion_validation_categories(
    exc: ValidationError,
) -> tuple[AuditStructuredOutputValidationCategory, ...]:
    """Map Pydantic's evolving error names into a closed diagnostic vocabulary."""

    categories: list[AuditStructuredOutputValidationCategory] = []
    for item in exc.errors():
        observed = item.get("type")
        category = _candidate_completion_validation_category(observed)
        if category not in categories:
            categories.append(category)
        if len(categories) == 3:
            break
    return tuple(categories or ("other_schema_validation",))


def _candidate_completion_validation_category(
    observed: object,
) -> AuditStructuredOutputValidationCategory:
    """Classify error *kind* only; values, locations and prose stay private."""

    if observed in _CANDIDATE_COMPLETION_SAFE_ISSUE_CODES:
        return "candidate_rule"
    if observed == "missing":
        return "missing_required_field"
    if observed == "extra_forbidden":
        return "unexpected_field"
    if observed in {"literal_error", "enum"}:
        return "literal_mismatch"
    if observed in {"dict_type", "list_type", "tuple_type", "model_type"}:
        return "container_shape_mismatch"
    if isinstance(observed, str) and observed.endswith("_type"):
        return "scalar_type_mismatch"
    if observed in {
        "greater_than",
        "greater_than_equal",
        "less_than",
        "less_than_equal",
        "string_too_short",
        "string_too_long",
        "too_short",
        "too_long",
        "value_error",
    }:
        return "value_constraint"
    return "other_schema_validation"


def _safe_activity_counts(
    telemetry: TelemetryStore,
    trace_id: str,
) -> tuple[int | None, dict[str, int]]:
    summary = telemetry.inspect_trace(trace_id).get("summary", {})
    if not isinstance(summary, dict):
        return None, {}
    metrics = summary.get("metrics_sum", {})
    if not isinstance(metrics, dict):
        return None, {}
    observed = metrics.get("invocation.events.observed_delta")
    event_count = (
        int(observed)
        if isinstance(observed, (int, float)) and not isinstance(observed, bool)
        else None
    )
    activity: dict[str, int] = {}
    prefix = "invocation.activity."
    suffix = "_event_delta"
    for name, value in metrics.items():
        if (
            isinstance(name, str)
            and name.startswith(prefix)
            and name.endswith(suffix)
            and isinstance(value, (int, float))
            and not isinstance(value, bool)
            and value >= 0
        ):
            activity[name.removeprefix(prefix).removesuffix(suffix)] = int(value)
    return event_count, activity


def _physical_turn_record(
    turn_index: int,
    result: InvocationResult,
) -> InvocationAuditPhysicalTurn:
    if result.succeeded:
        return InvocationAuditPhysicalTurn(
            turn_index=turn_index,
            status="passed",
            duration_ms=result.duration_ms,
        )
    return InvocationAuditPhysicalTurn(
        turn_index=turn_index,
        status="failed",
        duration_ms=result.duration_ms,
        failure_code=result.error.code if result.error is not None else result.status.value,
        retryable=result.error.retryable if result.error is not None else None,
        terminal_details=dict(safe_terminal_details(result.error)),
    )


def _safe_profile_details(profile: ResolvedAgentProfile | None) -> _SafeProfileDetails:
    """Return only profile provenance useful to a project-execution Agent.

    The audit needs to prove which special Skill/profile shape actually ran,
    but it must never retain rendered instructions, prompt text, workspace
    paths or credential material.  A digest is sufficient to distinguish a
    tool-free developer instruction from a materialized Agent Skill bundle.
    """

    if profile is None:
        return {
            "profile_digest": None,
            "runtime_skill_names": (),
            "developer_instructions_sha256": None,
        }
    profile_hash = getattr(profile, "profile_hash", None)
    developer_instructions = getattr(profile, "developer_instructions", None)
    skills = getattr(profile, "skills", ())
    return {
        "profile_digest": (
            f"sha256:{profile_hash}"
            if isinstance(profile_hash, str) and len(profile_hash) == 64
            else None
        ),
        "runtime_skill_names": tuple(
            item.name for item in skills if isinstance(getattr(item, "name", None), str)
        ),
        "developer_instructions_sha256": (
            hashlib.sha256(developer_instructions.encode("utf-8")).hexdigest()
            if isinstance(developer_instructions, str)
            else None
        ),
    }


def _pending_record(lane: _AuditLane, started_at: str) -> InvocationAuditLaneResult:
    return InvocationAuditLaneResult(
        lane_id=lane.lane_id,
        node_id=lane.node_id,
        role=lane.role,
        capability=lane.capability,
        execution_mode=lane.execution_mode.value,
        expected_backend=lane.expected_backend,
        output_contract=lane.output_contract,
        status="running",
        started_at=started_at,
        updated_at=started_at,
    )


def _interrupted_record(record: InvocationAuditLaneResult) -> InvocationAuditLaneResult:
    """Turn a transient audit view into a safe terminal owner-interruption fact."""

    if record.status != "running":
        return record
    return record.model_copy(
        update={
            "status": "interrupted",
            "updated_at": _now(),
            "failure_phase": "audit_owner_interrupted",
            "failure_code": "owner_process_interrupted",
            "retryable": False,
            "terminal_details": {"phase": "audit_owner_interrupted"},
        }
    )


def _report(
    *,
    run_id: str,
    status: AuditStatus,
    started_at: str,
    source_transport: str,
    transport: str,
    records: list[InvocationAuditLaneResult],
) -> InvocationAuditReport:
    return InvocationAuditReport(
        run_id=run_id,
        status=status,
        started_at=started_at,
        updated_at=_now(),
        source_structured_output_transport=source_transport,
        structured_output_transport=transport,
        lanes=tuple(records),
    )


def _select_lanes(lane_ids: tuple[str, ...]) -> tuple[_AuditLane, ...]:
    requested = tuple(dict.fromkeys(lane_ids))
    if not requested:
        return _AUDIT_LANES
    known = {item.lane_id: item for item in _AUDIT_LANES}
    unknown = tuple(item for item in requested if item not in known)
    if unknown:
        raise ValueError(f"unknown invocation audit lane(s): {', '.join(unknown)}")
    return tuple(known[item] for item in requested)


def _with_transport_override(
    config: FoundryConfig,
    transport: Literal["provider_schema", "json_envelope", "json_object"] | None,
) -> FoundryConfig:
    if transport is None:
        return config
    return config.model_copy(
        update={"agent": config.agent.model_copy(update={"structured_output_transport": transport})}
    )


def _audit_rollout_token_limit(config: FoundryConfig) -> int:
    """Use the largest configured real-Agent envelope, never a tiny probe cap."""

    return max(
        config.agent.structured_turn_token_limit,
        config.agent.environment_codegen_turn_token_limit,
    )


def _write_report(state_root: Path, report: InvocationAuditReport) -> None:
    """Write the current snapshot and this run's immutable-safe record.

    The top-level file is intentionally a compact, current Agent-facing view.
    A subset audit must not erase the evidence from an earlier transport or
    backend run, so every update is also written to a run-specific record.
    Neither location includes prompts, raw model text, or credentials.
    """

    payload = _serialized_report(report)
    _write_private_report(state_root / _STATUS_FILENAME, payload)

    records_root = state_root / _RUN_RECORDS_DIRECTORY
    if records_root.exists() and (records_root.is_symlink() or not records_root.is_dir()):
        raise OSError("invocation audit run records path must be a real directory")
    records_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    _write_private_report(records_root / _run_record_filename(report.run_id), payload)


def _run_record_filename(run_id: str) -> str:
    return f"{_audit_run_token(run_id)}.json"


def _audit_run_token(run_id: str) -> str:
    """Return the validated opaque token used by all local audit sidecars."""

    run_token = run_id.removeprefix(_RUN_ID_PREFIX)
    if (
        run_token == run_id
        or len(run_token) != 32
        or any(character not in "0123456789abcdef" for character in run_token)
    ):
        raise ValueError("invocation audit run id must use the framework UUID format")
    return run_token


def _serialized_report(report: InvocationAuditReport) -> str:
    return (
        json.dumps(
            report.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    )


def _write_private_report(target: Path, payload: str) -> None:
    if target.exists() and target.is_symlink():
        raise OSError("invocation audit status path cannot be a symlink")
    temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
    descriptor = os.open(
        temporary,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0),
        0o600,
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink(missing_ok=True)


def _now() -> str:
    return datetime.now(UTC).isoformat()


__all__ = [
    "INVOCATION_AUDIT_LANE_IDS",
    "InvocationAuditLaneResult",
    "InvocationAuditReport",
    "run_invocation_audit",
]
