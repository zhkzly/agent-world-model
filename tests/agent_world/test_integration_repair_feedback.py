"""Root-cause feedback routing for real Integration failures."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Literal

import pytest

from agent_world.artifact_store import ArtifactStore
from agent_world.contracts import (
    ArtifactRef,
    Finding,
    GateResult,
    IntegrationReport,
    JudgeReport,
    ReleaseProfile,
    sha256_digest,
)
from agent_world.judge import IntegrationLeaf, ReleaseAssuranceLeaf
from agent_world.judge.models import CaseEvaluation
from agent_world.judge.protocol import ProtocolViolation
from agent_world.judge.semantics import ToolSemanticValidationError
from agent_world.judge.service import (
    EnvironmentJudge,
    _candidate_failure_summary,
    _case_failure_repair_remediation,
    _CaseRunResult,
    _InvokeObservationProjectionFailure,
    _public_case_repair_remediation,
    _RuntimeInitialStateCheck,
)
from agent_world.judge.supervisor import ProcessResult, RuntimeProcessCrashed


def _ref(label: str, artifact_type: str) -> ArtifactRef:
    return ArtifactRef(
        artifact_id=f"artifact:{label}",
        revision_id=sha256_digest(f"revision:{label}".encode()),
        artifact_type=artifact_type,
        content_hash=sha256_digest(f"content:{label}".encode()),
        media_type="application/json",
        size_bytes=1,
    )


def _judge(tmp_path: Path, *, runtime_episode_concurrency: int = 8) -> EnvironmentJudge:
    store = ArtifactStore(tmp_path / "artifacts")
    return EnvironmentJudge(
        artifact_store=store.issue_writer(
            producer="test-judge",
            allowed_artifact_types=("judge_report",),
            allowed_artifact_type_prefixes=("judge.",),
        ),
        runtime_episode_concurrency=runtime_episode_concurrency,
    )


def _gate(
    candidate_ref: ArtifactRef,
    evidence_ref: ArtifactRef,
    gate_id: str,
    status: Literal["pass", "fail", "inconclusive", "error"],
    summary: str,
) -> GateResult:
    return GateResult(
        gate_id=gate_id,
        status=status,
        hard=True,
        subject_ref=candidate_ref,
        evidence_refs=(evidence_ref,),
        duration_seconds=0,
        summary=summary,
    )


def _finding(
    candidate_ref: ArtifactRef,
    evidence_ref: ArtifactRef,
    category: str,
    summary: str,
    remediation: str,
) -> Finding:
    return Finding(
        finding_id=f"finding:{category}",
        category=category,
        severity="high",
        owner="build",
        subject_ref=candidate_ref,
        summary=summary,
        evidence_refs=(evidence_ref,),
        fingerprint=sha256_digest(f"finding:{category}".encode()),
        disclosure="repair",
        suggested_repair=remediation,
    )


def test_public_self_check_stays_diagnostic_for_a_legacy_profile() -> None:
    """Old frozen profiles remain readable but cannot promote self-checks."""

    candidate_ref = _ref("candidate", "build.environment_candidate")
    evidence_ref = _ref("self-check", "judge.evaluation_evidence")
    profile = ReleaseProfile(
        profile_id="legacy-public-self-check",
        required_hard_gates=("schema", "public_self_check"),
    )

    gate = EnvironmentJudge._gate(  # noqa: SLF001
        "public_self_check",
        "fail",
        candidate_ref,
        (evidence_ref,),
        profile,
        "Public self-check failed in the clean sandbox.",
    )

    assert not gate.hard


def test_integration_repair_feedback_excludes_skipped_downstream_gate_noise() -> None:
    candidate_ref = _ref("candidate", "build.environment_candidate")
    evidence_ref = _ref("integration", "judge.integration_contract_evidence")
    report = IntegrationReport(
        report_id="integration-report:root-cause-only",
        revision=1,
        candidate_ref=candidate_ref,
        status="failed",
        gate_results=(
            _gate(
                candidate_ref,
                evidence_ref,
                "runtime_protocol",
                "fail",
                "handshake operations must be a JSON array of strings",
            ),
            _gate(
                candidate_ref,
                evidence_ref,
                "task_materialization",
                "fail",
                "materializer cannot pass the runtime handshake contract",
            ),
            _gate(
                candidate_ref,
                evidence_ref,
                "clean_deployment",
                "inconclusive",
                "Deployment probe was not run after an earlier integration failure.",
            ),
        ),
        findings=(
            _finding(
                candidate_ref,
                evidence_ref,
                "runtime_protocol",
                "runtime_protocol did not pass.",
                "Return the exact handshake operations string array.",
            ),
            _finding(
                candidate_ref,
                evidence_ref,
                "task_materialization",
                "task_materialization did not pass.",
                "Make materialization use the repaired runtime protocol.",
            ),
            _finding(
                candidate_ref,
                evidence_ref,
                "clean_deployment",
                "clean_deployment did not pass.",
                "Deployment was skipped; do not treat this as a separate source defect.",
            ),
        ),
        evidence_refs=(evidence_ref,),
    )

    issues, routeable = IntegrationLeaf._integration_repair_feedback(report)  # noqa: SLF001

    assert routeable is True
    assert [issue.code for issue in issues] == [
        "integration_gate_runtime_protocol_fail",
        "integration_gate_task_materialization_fail",
    ]
    assert all("Deployment probe" not in issue.violated_condition for issue in issues)
    assert issues[0].remediation == "Return the exact handshake operations string array."


def test_release_repair_feedback_projects_only_actionable_runtime_roots() -> None:
    candidate_ref = _ref("candidate", "build.environment_candidate")
    evidence_ref = _ref("release", "judge.evaluation_evidence")
    behavior_remediation = (
        "For Runtime `invoke`, build `observation` from the invoked tool's projection and "
        "validate it against that tool's observation schema; do not reuse reset state."
    )
    reachability_remediation = (
        "Every sampled reachability episode stopped at the Candidate Runtime execution boundary. "
        "Correct the disclosed Runtime behavior failure before changing Task Materializer "
        "or Verifier."
    )
    report = JudgeReport(
        report_id="report:release-root-cause-only",
        revision=1,
        candidate_ref=candidate_ref,
        verdict="fail",
        gate_results=(
            _gate(candidate_ref, evidence_ref, "behavior", "fail", "behavior: 0/5 cases passed."),
            _gate(
                candidate_ref,
                evidence_ref,
                "task_reachability",
                "fail",
                (
                    "Reachability ran 80 sampled tasks: 0 reached trusted terminal success and "
                    "80 did not; no aggregate release reachability claim was issued."
                ),
            ),
            _gate(
                candidate_ref,
                evidence_ref,
                "sealed_release",
                "fail",
                "sealed-release: 0/5 cases passed.",
            ),
        ),
        findings=(
            _finding(
                candidate_ref,
                evidence_ref,
                "behavior",
                "behavior did not pass.",
                behavior_remediation,
            ),
            _finding(
                candidate_ref,
                evidence_ref,
                "task_reachability",
                "task_reachability did not pass.",
                reachability_remediation,
            ),
            Finding(
                finding_id="finding:sealed-release",
                category="sealed_release",
                severity="high",
                owner="build",
                subject_ref=candidate_ref,
                summary="sealed_release did not pass.",
                evidence_refs=(evidence_ref,),
                fingerprint=sha256_digest(b"finding:sealed-release"),
                disclosure="sealed_summary",
                suggested_repair="sealed-release: 0/5 cases passed.",
            ),
        ),
        evaluation_evidence_refs=(evidence_ref,),
    )

    issues, routeable = ReleaseAssuranceLeaf._release_repair_feedback(report)  # noqa: SLF001

    assert routeable is True
    assert [issue.code for issue in issues] == ["release_gate_behavior_fail"]
    assert issues[0].remediation == behavior_remediation
    assert all("reachability" not in issue.code for issue in issues)
    assert all("sealed" not in issue.code for issue in issues)


def test_release_repair_feedback_keeps_an_independent_reachability_root() -> None:
    candidate_ref = _ref("candidate", "build.environment_candidate")
    evidence_ref = _ref("release", "judge.evaluation_evidence")
    remediation = "Repair the public solve path that prevents trusted terminal success."
    report = JudgeReport(
        report_id="report:release-reachability-root",
        revision=1,
        candidate_ref=candidate_ref,
        verdict="fail",
        gate_results=(
            _gate(
                candidate_ref,
                evidence_ref,
                "task_reachability",
                "fail",
                "Reachability ran 8 sampled tasks: none reached trusted terminal success.",
            ),
        ),
        findings=(
            _finding(
                candidate_ref,
                evidence_ref,
                "task_reachability",
                "task_reachability did not pass.",
                remediation,
            ),
        ),
        evaluation_evidence_refs=(evidence_ref,),
    )

    issues, routeable = ReleaseAssuranceLeaf._release_repair_feedback(report)  # noqa: SLF001

    assert routeable is True
    assert [issue.code for issue in issues] == ["release_gate_task_reachability_fail"]
    assert issues[0].remediation == remediation


def test_release_repair_feedback_refuses_generic_or_sealed_only_repair() -> None:
    candidate_ref = _ref("candidate", "build.environment_candidate")
    evidence_ref = _ref("release", "judge.evaluation_evidence")
    report = JudgeReport(
        report_id="report:release-feedback-insufficient",
        revision=1,
        candidate_ref=candidate_ref,
        verdict="fail",
        gate_results=(
            _gate(
                candidate_ref,
                evidence_ref,
                "runtime_protocol",
                "fail",
                "Runtime protocol did not pass.",
            ),
            _gate(
                candidate_ref,
                evidence_ref,
                "sealed_release",
                "fail",
                "sealed-release: 0/5 cases passed.",
            ),
        ),
        findings=(
            _finding(
                candidate_ref,
                evidence_ref,
                "runtime_protocol",
                "runtime_protocol did not pass.",
                "Runtime protocol did not pass.",
            ),
            Finding(
                finding_id="finding:sealed-only",
                category="sealed_release",
                severity="high",
                owner="build",
                subject_ref=candidate_ref,
                summary="sealed_release did not pass.",
                evidence_refs=(evidence_ref,),
                fingerprint=sha256_digest(b"finding:sealed-only"),
                disclosure="sealed_summary",
                suggested_repair="sealed-release: 0/5 cases passed.",
            ),
        ),
        evaluation_evidence_refs=(evidence_ref,),
    )

    issues, routeable = ReleaseAssuranceLeaf._release_repair_feedback(report)  # noqa: SLF001

    assert routeable is False
    assert [issue.code for issue in issues] == ["release_report_root_cause_insufficient"]


def test_public_runtime_failure_signatures_become_one_complete_repair_brief() -> None:
    """Public evidence may repair a Runtime; sealed or partial evidence may not."""

    failures = (
        ProtocolViolation("schema_mismatch", "response.error has invalid keys"),
        ToolSemanticValidationError(
            "execution.start_or_resume_task violates precondition Rules: ['rule:precondition:0']"
        ),
        _InvokeObservationProjectionFailure(
            tool_id="human.record_approval",
            actor="human_operator",
            required_fields=("approval_event_id",),
            cause=ValueError("observation projection is missing a required field"),
        ),
        ToolSemanticValidationError(
            "Runtime emitted task_not_resumable while its declared Rule is false"
        ),
    )
    runs = tuple(
        _CaseRunResult(
            evaluation=CaseEvaluation(
                case_id=f"case:public:{index}",
                partition="public",
                seed=index,
                passed=False,
                reset_ok=False,
                actions=(),
                assertions=(),
                failure_class="runtime_execution_failed",
                failure_summary=f"{type(exc).__name__}: {exc}",
            ),
            tool_calls=0,
            repair_remediation=_case_failure_repair_remediation(exc),
        )
        for index, exc in enumerate(failures)
    )

    brief = _public_case_repair_remediation(runs)

    assert brief is not None
    assert len(brief) <= 512
    assert "`error` fields: `code`, `message`, `retryable`, optional `details`" in brief
    assert "`execution.start_or_resume_task`" in brief
    assert "tool's per-actor observation projection" in brief
    assert "`approval_event_id`" in brief
    assert "frozen `when` Rule is true" in brief
    assert "task_not_resumable" not in brief
    assert "Verifier" in brief


def test_invoke_projection_feedback_discloses_only_framework_owned_fields() -> None:
    """A repair brief may name frozen schema fields, never dynamic failure text."""

    failure = _InvokeObservationProjectionFailure(
        tool_id="execution.start_or_resume_task",
        actor="agent_runtime",
        required_fields=("execution_event_id",),
        cause=ValueError("candidate supplied secret-like detail: token=not-for-feedback"),
    )

    remediation = _case_failure_repair_remediation(failure)

    assert remediation is not None
    assert "`execution.start_or_resume_task`" in remediation
    assert "`agent_runtime`" in remediation
    assert "`execution_event_id`" in remediation
    assert "token=not-for-feedback" not in remediation


def test_public_runtime_feedback_refuses_a_partial_failure_list() -> None:
    known = ProtocolViolation("schema_mismatch", "response.error has invalid keys")
    unknown = ValueError("candidate-controlled detail must not become feedback")
    runs = tuple(
        _CaseRunResult(
            evaluation=CaseEvaluation(
                case_id=f"case:public:{index}",
                partition="public",
                seed=index,
                passed=False,
                reset_ok=False,
                actions=(),
                assertions=(),
                failure_class="runtime_execution_failed",
                failure_summary=f"{type(exc).__name__}: {exc}",
            ),
            tool_calls=0,
            repair_remediation=_case_failure_repair_remediation(exc),
        )
        for index, exc in enumerate((known, unknown))
    )

    assert _public_case_repair_remediation(runs) is None


def test_sandbox_failure_feedback_exposes_safe_missing_module_coordinate() -> None:
    result = ProcessResult(
        argv=(".venv/bin/python", "-m", "meeting_room.runtime"),
        exit_code=1,
        stdout="",
        stderr=(
            "/workspace/.venv/bin/python: Error while finding module specification for "
            "'meeting_room.runtime' (ModuleNotFoundError: No module named 'meeting_room')\n"
        ),
        stdout_truncated=False,
        stderr_truncated=False,
        duration_ms=10,
    )

    with pytest.raises(ValueError, match="missing_module=meeting_room"):
        EnvironmentJudge._task_runner_outputs(result, expected_count=1)  # noqa: SLF001

    runtime_error = RuntimeProcessCrashed(
        "runtime_process_crashed",
        "runtime exited without a response",
        details={"exit_code": 1, "stderr": result.stderr},
    )
    assert _candidate_failure_summary(runtime_error).endswith(
        "stderr_exception=ModuleNotFoundError; missing_module=meeting_room"
    )


class _AggregateBoundedMaterializerRunner:
    """Return a normal per-call result but truncate every aggregate response."""

    def __init__(self, *, truncate_single_call: bool = False) -> None:
        self.calls: list[tuple[dict[str, object], ...]] = []
        self._truncate_single_call = truncate_single_call

    async def run_task_materializer(
        self,
        _candidate_root: Path,
        *,
        entrypoint: str,
        calls: tuple[dict[str, object], ...],
        visible_workspace_paths: tuple[str, ...],
    ) -> ProcessResult:
        assert entrypoint == "task_materializer:materialize"
        assert visible_workspace_paths == ("task_materializer.py",)
        self.calls.append(calls)
        if len(calls) > 1 or self._truncate_single_call:
            return ProcessResult(
                argv=(".venv/bin/python", "task-materializer-runner.py"),
                exit_code=0,
                stdout="",
                stderr="",
                stdout_truncated=True,
                stderr_truncated=False,
                duration_ms=1,
            )
        materializations = [{"seed": calls[0]["seed"]}]
        return ProcessResult(
            argv=(".venv/bin/python", "task-materializer-runner.py"),
            exit_code=0,
            stdout=json.dumps(
                {
                    "protocol": "agent-world.task-materializer-runner.v3",
                    "ok": True,
                    "materializations": materializations,
                }
            ),
            stderr="",
            stdout_truncated=False,
            stderr_truncated=False,
            duration_ms=1,
        )


@pytest.mark.asyncio
async def test_materializer_campaign_splits_only_aggregate_output_limit(tmp_path: Path) -> None:
    judge = _judge(tmp_path)
    runner = _AggregateBoundedMaterializerRunner()
    judge.process_runner = runner  # type: ignore[assignment]
    calls = tuple(
        {
            "seed": seed,
            "task_type": "reserve",
            "actor": "member",
            "difficulty": {},
        }
        for seed in range(4)
    )

    campaign = await judge._run_task_materializer_campaign(  # noqa: SLF001
        candidate_root=tmp_path,
        entrypoint="task_materializer:materialize",
        calls=calls,
        visible_workspace_paths=("task_materializer.py",),
    )

    assert [item["seed"] for item in campaign.materializations] == [0, 1, 2, 3]
    assert campaign.runner_invocations == 7
    assert campaign.adaptive_batch_splits == 3
    assert [len(item) for item in runner.calls] == [4, 2, 1, 1, 2, 1, 1]


@pytest.mark.asyncio
async def test_materializer_campaign_keeps_single_response_overflow_actionable(
    tmp_path: Path,
) -> None:
    judge = _judge(tmp_path)
    judge.process_runner = _AggregateBoundedMaterializerRunner(  # type: ignore[assignment]
        truncate_single_call=True
    )

    with pytest.raises(ValueError, match="single-call response exceeded"):
        await judge._run_task_materializer_campaign(  # noqa: SLF001
            candidate_root=tmp_path,
            entrypoint="task_materializer:materialize",
            calls=(
                {
                    "seed": 1,
                    "task_type": "reserve",
                    "actor": "member",
                    "difficulty": {},
                },
            ),
            visible_workspace_paths=("task_materializer.py",),
        )


@pytest.mark.asyncio
async def test_runtime_initial_state_campaign_is_bounded_and_preserves_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    judge = _judge(tmp_path, runtime_episode_concurrency=2)
    active = 0
    maximum_active = 0
    started: list[int] = []

    async def fake_check(
        _self: EnvironmentJudge,
        *,
        index: int,
        **_kwargs: object,
    ) -> _RuntimeInitialStateCheck:
        nonlocal active, maximum_active
        active += 1
        maximum_active = max(maximum_active, active)
        started.append(index)
        await asyncio.sleep(0)
        active -= 1
        return _RuntimeInitialStateCheck(
            index=index,
            final_state_digest=f"sha256:{index}",
            reset_observation={"index": index},
            rule_violations=(),
        )

    monkeypatch.setattr(EnvironmentJudge, "_runtime_initial_state_check", fake_check)
    checks = await judge._run_runtime_initial_state_checks(  # noqa: SLF001
        clean=SimpleNamespace(),
        candidate=SimpleNamespace(),
        manifest=SimpleNamespace(),
        envelopes=tuple(SimpleNamespace() for _ in range(9)),
        design=SimpleNamespace(),
        requirements={},
    )

    assert maximum_active == 2
    assert started == list(range(9))
    assert [check.index for check in checks] == list(range(9))


def test_initial_state_rule_feedback_lookup_covers_every_evaluated_rule() -> None:
    rules = {name: SimpleNamespace(rule_id=name) for name in ("world", "state", "task", "sampling")}
    design = SimpleNamespace(
        world_spec=SimpleNamespace(
            invariants=(rules["world"],),
            state=SimpleNamespace(initial_state_constraints=(rules["state"],)),
        )
    )
    curriculum = SimpleNamespace(
        task_types=(SimpleNamespace(initial_state_constraints=(rules["task"],)),),
        sampling_constraints=(rules["sampling"],),
    )

    lookup = EnvironmentJudge._initial_state_rule_lookup(  # noqa: SLF001
        design,  # type: ignore[arg-type]
        curriculum,  # type: ignore[arg-type]
    )

    assert set(lookup) == {"world", "state", "task", "sampling"}
    scopes = EnvironmentJudge._initial_state_rule_scope_lookup(  # noqa: SLF001
        design,  # type: ignore[arg-type]
        curriculum,  # type: ignore[arg-type]
    )
    assert scopes == {
        "world": "world_invariant",
        "state": "world_initial_state",
        "task": "task_initial_state",
        "sampling": "curriculum_sampling",
    }


def test_integration_uses_separate_bounded_materializer_repair_story(
    tmp_path: Path,
) -> None:
    judge = _judge(tmp_path)
    candidate_ref = _ref("candidate", "build.environment_candidate")
    evidence_ref = _ref("materialization", "judge.evaluation_evidence")
    gate_results: list[GateResult] = []
    evidence_refs: list[ArtifactRef] = []
    findings: list[Finding] = []
    remediation = (
        "Make Task Materializer initial_config satisfy rule:state:0 while preserving "
        "reachability; if the frozen inputs conflict, return blocked."
    )

    judge._record_gate(  # noqa: SLF001
        gate_id="task_materialization",
        status="fail",
        evidence_ref=evidence_ref,
        summary="7307 violations with complete grouped evidence stored separately.",
        suggested_repair=remediation,
        owner="build",
        candidate_ref=candidate_ref,
        release_profile=SimpleNamespace(required_hard_gates=()),  # type: ignore[arg-type]
        gate_results=gate_results,
        evidence_refs=evidence_refs,
        findings=findings,
        run_id="integration:materializer-feedback",
    )

    report = IntegrationReport(
        report_id="integration-report:materializer-feedback",
        revision=1,
        candidate_ref=candidate_ref,
        status="failed",
        gate_results=tuple(gate_results),
        findings=tuple(findings),
        evidence_refs=tuple(evidence_refs),
    )
    issues, routeable = IntegrationLeaf._integration_repair_feedback(report)  # noqa: SLF001

    assert routeable is True
    assert issues[0].remediation == remediation
    assert "7307 violations" not in issues[0].remediation
