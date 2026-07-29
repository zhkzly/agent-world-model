"""Root-cause feedback routing for real Integration failures."""

from __future__ import annotations

from typing import Literal

from agent_world.contracts import (
    ArtifactRef,
    Finding,
    GateResult,
    IntegrationReport,
    sha256_digest,
)
from agent_world.judge import IntegrationLeaf


def _ref(label: str, artifact_type: str) -> ArtifactRef:
    return ArtifactRef(
        artifact_id=f"artifact:{label}",
        revision_id=sha256_digest(f"revision:{label}".encode()),
        artifact_type=artifact_type,
        content_hash=sha256_digest(f"content:{label}".encode()),
        media_type="application/json",
        size_bytes=1,
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
