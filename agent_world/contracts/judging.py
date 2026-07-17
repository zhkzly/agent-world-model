"""Independent Judge findings, gate evidence, and verdict contracts."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, model_validator

from .base import ArtifactRef, ContentHash, Identifier, NonEmptyStr, V2Contract
from .jobs import BudgetUsage


class Finding(V2Contract):
    finding_id: Identifier
    category: Identifier
    severity: Literal["info", "low", "medium", "high", "critical"]
    owner: Literal[
        "design",
        "verifier",
        "build",
        "judge_infrastructure",
        "permissions",
        "release_policy",
    ]
    subject_ref: ArtifactRef
    summary: NonEmptyStr
    evidence_refs: Annotated[tuple[ArtifactRef, ...], Field(min_length=1)]
    fingerprint: ContentHash
    disclosure: Literal["public", "repair", "sealed_summary"]
    suggested_repair: NonEmptyStr | None = None
    blocks_release: bool = True


class GateResult(V2Contract):
    gate_id: Identifier
    status: Literal["pass", "fail", "inconclusive", "error"]
    hard: bool
    subject_ref: ArtifactRef
    evidence_refs: Annotated[tuple[ArtifactRef, ...], Field(min_length=1)]
    observed_metrics: dict[Identifier, float] = Field(default_factory=dict)
    duration_seconds: Annotated[float, Field(ge=0)]
    summary: NonEmptyStr


class JudgeReport(V2Contract):
    report_id: Identifier
    revision: Annotated[int, Field(ge=1)]
    candidate_ref: ArtifactRef
    candidate_source_tree_digest: ContentHash | None = None
    verdict: Literal["pass", "fail", "inconclusive", "error"]
    gate_results: Annotated[tuple[GateResult, ...], Field(min_length=1)]
    findings: tuple[Finding, ...] = ()
    evaluation_evidence_refs: Annotated[tuple[ArtifactRef, ...], Field(min_length=1)]
    budget_usage: BudgetUsage = Field(default_factory=BudgetUsage)

    @model_validator(mode="after")
    def validate_verdict(self) -> JudgeReport:
        hard_failures = [
            result for result in self.gate_results if result.hard and result.status != "pass"
        ]
        blocking_findings = [finding for finding in self.findings if finding.blocks_release]
        if self.verdict == "pass" and (hard_failures or blocking_findings):
            raise ValueError(
                "pass verdict cannot contain a non-passing hard gate or blocking finding"
            )
        if self.verdict == "pass" and self.candidate_source_tree_digest is None:
            raise ValueError("pass verdict must bind the independently verified source tree")
        if self.verdict == "fail" and not (hard_failures or blocking_findings):
            raise ValueError("fail verdict requires a hard gate failure or blocking finding")
        return self


class IntegrationReport(V2Contract):
    """Real candidate execution evidence that cannot itself authorize release."""

    report_id: Identifier
    revision: Annotated[int, Field(ge=1)]
    candidate_ref: ArtifactRef
    candidate_source_tree_digest: ContentHash | None = None
    status: Literal["ready", "failed", "error"]
    gate_results: Annotated[tuple[GateResult, ...], Field(min_length=1)]
    findings: tuple[Finding, ...] = ()
    evidence_refs: Annotated[tuple[ArtifactRef, ...], Field(min_length=1)]
    budget_usage: BudgetUsage = Field(default_factory=BudgetUsage)

    @model_validator(mode="after")
    def validate_integration_status(self) -> IntegrationReport:
        failures = [item for item in self.gate_results if item.status != "pass"]
        blockers = [item for item in self.findings if item.blocks_release]
        if self.status == "ready" and (failures or blockers):
            raise ValueError("ready IntegrationReport requires every integration gate to pass")
        if self.status == "ready" and self.candidate_source_tree_digest is None:
            raise ValueError("ready IntegrationReport must bind the verified source tree")
        if self.status == "failed" and not (failures or blockers):
            raise ValueError("failed IntegrationReport requires failure evidence")
        return self


__all__ = ["Finding", "GateResult", "IntegrationReport", "JudgeReport"]
