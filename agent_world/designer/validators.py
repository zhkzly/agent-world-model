"""Pure deterministic validators shared by Scheduler-owned Designer leaves.

These checks deliberately contain no invocation, workspace, ArtifactStore or
repair state.  They answer only whether a proposed artifact satisfies one
closed claim, so the Scheduler can decide if a correction is justified.
"""

from __future__ import annotations

from agent_world.contracts import Evidence, EvidenceGraph

from .models import EvidenceSynthesis, ResearchPlan
from .validation import StructuredSemanticError, StructuredSemanticIssue


def validate_research_plan_coverage(plan: ResearchPlan) -> None:
    """Require the pre-search coverage claim before spending real web budget."""

    corpus = " ".join(
        (
            *plan.target_coverage_dimensions,
            *(topic for query in plan.queries for topic in query.topics),
            *(query.text for query in plan.queries),
            *(query.rationale for query in plan.queries),
        )
    ).casefold()
    categories = {
        "workflow": ("workflow", "flow", "lifecycle", "task sequence", "流程", "生命周期"),
        "tools": ("tool", "api", "sdk", "cli", "mcp", "surface", "工具", "接口"),
        "state": ("state", "transition", "system of record", "状态", "转移"),
        "authority": ("authority", "permission", "auth", "role", "权限", "授权"),
        "errors": ("error", "failure", "retry", "rollback", "错误", "失败", "重试"),
        "risks": ("risk", "concurrency", "idempot", "security", "overbook", "风险", "并发"),
    }
    issues = tuple(
        StructuredSemanticIssue(
            code=f"research_plan_{category}_coverage_missing",
            location=("target_coverage_dimensions",),
            message=f"ResearchPlan must expose the {category} coverage category.",
        )
        for category, aliases in categories.items()
        if not any(alias in corpus for alias in aliases)
    )
    if issues:
        raise StructuredSemanticError(issues)


def validate_evidence_synthesis_references(
    value: EvidenceSynthesis,
    evidence: tuple[Evidence, ...],
) -> None:
    """Validate every claim reference against the frozen acquisition closure."""

    evidence_ids = {item.evidence_id for item in evidence}
    usable_evidence_ids = {
        item.evidence_id for item in evidence if item.retrieval_status != "failed"
    }
    claim_ids = [claim.claim_id for claim in value.claims]
    claim_id_set = set(claim_ids)
    issues: list[StructuredSemanticIssue] = []
    if len(claim_ids) != len(claim_id_set):
        issues.append(
            StructuredSemanticIssue(
                code="claim_id_duplicate",
                location=("claims",),
                message="claim_id values must be unique",
            )
        )
    claim_id_counts = {claim_id: claim_ids.count(claim_id) for claim_id in claim_id_set}
    for index, claim in enumerate(value.claims):
        claim_anchor: str | int = (
            claim.claim_id if claim_id_counts[claim.claim_id] == 1 else index
        )
        for evidence_index, evidence_id in enumerate(claim.evidence_ids):
            if evidence_id not in evidence_ids:
                issues.append(
                    StructuredSemanticIssue(
                        code="evidence_reference_unknown",
                        location=("claims", claim_anchor, "evidence_ids", evidence_index),
                        message=(
                            "claim references an id outside the exact allowed evidence-id list"
                        ),
                    )
                )
        for field_name, related_values in (
            ("supports_claim_ids", claim.supports_claim_ids),
            ("contradicts_claim_ids", claim.contradicts_claim_ids),
        ):
            for related_index, related_id in enumerate(related_values):
                if related_id not in claim_id_set:
                    issues.append(
                        StructuredSemanticIssue(
                            code="claim_reference_unknown",
                            location=("claims", claim_anchor, field_name, related_index),
                            message="claim references a claim_id absent from this synthesis",
                        )
                    )
        related_ids = set(claim.supports_claim_ids) | set(claim.contradicts_claim_ids)
        if claim.claim_id in related_ids:
            issues.append(
                StructuredSemanticIssue(
                    code="claim_reference_self",
                    location=("claims", claim_anchor),
                    message="a claim cannot support or contradict itself",
                )
            )
        if claim.kind == "observed":
            for evidence_index, evidence_id in enumerate(claim.evidence_ids):
                if evidence_id in evidence_ids and evidence_id not in usable_evidence_ids:
                    issues.append(
                        StructuredSemanticIssue(
                            code="observed_claim_failed_evidence",
                            location=("claims", claim_anchor, "evidence_ids", evidence_index),
                            message="an observed claim may reference only admitted evidence",
                        )
                    )
    for conflict in value.conflicts:
        for claim_index, claim_id in enumerate(conflict.claim_ids):
            if claim_id not in claim_id_set:
                issues.append(
                    StructuredSemanticIssue(
                        code="conflict_claim_reference_unknown",
                        location=("conflicts", conflict.conflict_id, "claim_ids", claim_index),
                        message="a conflict references a claim_id absent from this synthesis",
                    )
                )
    if issues:
        raise StructuredSemanticError(tuple(issues))


def validate_grounded_evidence_graph(evidence_graph: EvidenceGraph) -> None:
    """Require the one non-negotiable synthesis readiness claim."""

    if not any(
        claim.kind == "observed" and claim.status == "supported" and claim.evidence_ids
        for claim in evidence_graph.claims
    ):
        raise StructuredSemanticError(
            (
                StructuredSemanticIssue(
                    code="supported_observed_claim_missing",
                    location=("claims",),
                    message="at least one observed claim must be supported by admitted evidence",
                ),
            )
        )


__all__ = [
    "validate_evidence_synthesis_references",
    "validate_grounded_evidence_graph",
    "validate_research_plan_coverage",
]
