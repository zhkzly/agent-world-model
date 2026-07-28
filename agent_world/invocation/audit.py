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
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, TypedDict

from pydantic import BaseModel, ConfigDict, Field

from agent_world.agent_profiles import IsolatedAgentProfileProvider
from agent_world.builder.models import CandidateCompletion
from agent_world.config import FoundryConfig
from agent_world.contracts import PermissionScope
from agent_world.control import TelemetryStore

from .capabilities import NodeCapabilityRequirement
from .codex_sdk import CodexSdkBackend
from .contracts import (
    InvocationExecutionMode,
    InvocationRequest,
    InvocationResult,
    ResolvedAgentProfile,
)
from .direct_llm import DirectLlmBackend
from .routing import RoutedInvocationBackend
from .structured_diagnostics import safe_terminal_details

type AuditStatus = Literal["running", "passed", "failed"]
type AuditBackend = Literal["direct_llm", "codex_sdk"]
type AuditOutputContract = Literal["status", "candidate_completion_blocked"]


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
_RUN_ID_PREFIX = "invocation-audit:"


@dataclass(frozen=True, slots=True)
class _AuditLane:
    lane_id: str
    node_id: str
    role: Literal["researcher", "environment-engineer", "challenger"]
    capability: Literal["structured_output", "structured_read", "isolated_build", "solver"]
    execution_mode: InvocationExecutionMode
    expected_backend: AuditBackend
    workspace_write: bool = False
    require_session_resume: bool = False
    output_contract: AuditOutputContract = "status"


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
        lane_id="codex_engineer_candidate_completion",
        node_id="environment-engineer.runtime-build",
        role="environment-engineer",
        capability="isolated_build",
        execution_mode=InvocationExecutionMode.AGENTIC,
        expected_backend="codex_sdk",
        workspace_write=True,
        output_contract="candidate_completion_blocked",
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
        backend = RoutedInvocationBackend(
            codex_backend=CodexSdkBackend(telemetry=telemetry),
            direct_backend=DirectLlmBackend(telemetry=telemetry),
            max_concurrent_invocations=audit_config.agent.max_concurrent_invocations,
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
    backend: RoutedInvocationBackend,
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
                )
            marker = profile.workspace / "candidate" / "invocation-audit-marker.txt"
            try:
                result = await backend.invoke(
                    InvocationRequest(
                        invocation_id=f"{lane.lane_id}-{uuid.uuid4().hex}",
                        prompt=_prompt_for_lane(lane, profile.structured_output_transport),
                        profile=profile,
                        metadata={
                            "trace_id": trace_id,
                            "run_id": run_id,
                            "role": lane.role,
                            "semantic_transaction": f"invocation_audit.{lane.lane_id}",
                        },
                        execution_mode=lane.execution_mode,
                    )
                )
            except Exception:
                workspace_write_verified = marker.is_file() if marker_expected else None
                return _exception_record(
                    lane,
                    started_at=started_at,
                    telemetry=telemetry,
                    trace_id=trace_id,
                    phase="backend_invoke",
                    profile=profile,
                    workspace_write_verified=workspace_write_verified,
                )
            resumed_result: InvocationResult | None = None
            if lane.require_session_resume and result.succeeded and result.session is not None:
                try:
                    resumed_result = await backend.invoke(
                        InvocationRequest(
                            invocation_id=f"{lane.lane_id}-resume-{uuid.uuid4().hex}",
                            prompt=_resume_prompt_for_lane(
                                lane,
                                profile.structured_output_transport,
                            ),
                            profile=profile,
                            session=result.session,
                            metadata={
                                "trace_id": trace_id,
                                "run_id": run_id,
                                "role": lane.role,
                                "semantic_transaction": f"invocation_audit.{lane.lane_id}",
                                "physical_turn": 2,
                            },
                            execution_mode=lane.execution_mode,
                        )
                    )
                except Exception:
                    workspace_write_verified = marker.is_file() if marker_expected else None
                    return _exception_record(
                        lane,
                        started_at=started_at,
                        telemetry=telemetry,
                        trace_id=trace_id,
                        phase="session_resume",
                        profile=profile,
                        workspace_write_verified=workspace_write_verified,
                        prior_results=(result,),
                    )
            workspace_write_verified = marker.is_file() if marker_expected else None
            return _result_record(
                lane,
                result=result,
                resumed_result=resumed_result,
                profile=profile,
                started_at=started_at,
                telemetry=telemetry,
                trace_id=trace_id,
                workspace_write_verified=workspace_write_verified,
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
    prior_results: tuple[InvocationResult, ...] = (),
) -> InvocationAuditLaneResult:
    """Persist a safe, recipient-actionable failure without raw Provider text."""

    observed, activity = _safe_activity_counts(telemetry, trace_id)
    terminal_details: dict[str, object] = {"phase": phase}
    if profile is not None:
        terminal_details["structured_output_transport"] = profile.structured_output_transport
    profile_details = _safe_profile_details(profile)
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
) -> InvocationAuditLaneResult:
    results = (result,) if resumed_result is None else (result, resumed_result)
    physical_turns = tuple(
        _physical_turn_record(index + 1, item) for index, item in enumerate(results)
    )
    valid_output = all(
        item.succeeded and _output_matches_lane(lane, item.structured_output) for item in results
    )
    requires_session = lane.execution_mode is InvocationExecutionMode.AGENTIC
    initial_session_ok = not requires_session or result.session is not None
    resume_ok = not lane.require_session_resume or (
        resumed_result is not None
        and resumed_result.succeeded
        and resumed_result.session is not None
    )
    session_ok = initial_session_ok and resume_ok
    write_ok = workspace_write_verified is not False
    passed = valid_output and session_ok and write_ok
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
    elif not write_ok or not valid_output:
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
    )


def _output_matches_lane(lane: _AuditLane, output: object) -> bool:
    if lane.output_contract == "status":
        return output == _STATUS_VALUE
    try:
        completion = CandidateCompletion.model_validate(output)
    except ValueError:
        return False
    return (
        completion.status == "blocked"
        and completion.blocking_reason == _CANDIDATE_COMPLETION_BLOCKED_VALUE["blocking_reason"]
    )


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
    run_token = run_id.removeprefix(_RUN_ID_PREFIX)
    if (
        run_token == run_id
        or len(run_token) != 32
        or any(character not in "0123456789abcdef" for character in run_token)
    ):
        raise ValueError("invocation audit run id must use the framework UUID format")
    return f"{run_token}.json"


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
