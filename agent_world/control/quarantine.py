"""Controller-owned promotion of Discovery semantic advice into repair authority."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Literal

from agent_world.artifact_store import ArtifactWriter
from agent_world.contracts import (
    ArtifactRef,
    DesignBaselineCheckpoint,
    DiscoveryAdmissionDecision,
    DiscoveryQuarantineRecommendation,
    EvidenceGraph,
    ExpansionClue,
    Finding,
    QuarantineReviewDecision,
    canonical_json_bytes,
    sha256_digest,
)

_DismissReason = Literal[
    "admission_binding_mismatch",
    "baseline_binding_mismatch",
    "claim_not_hard_supported",
    "evidence_binding_mismatch",
    "evidence_not_independently_retrieved",
    "no_new_evidence",
]


@dataclass(frozen=True, slots=True)
class QuarantineReviewBundle:
    """One deterministic review and its optional framework Finding."""

    decision: QuarantineReviewDecision
    decision_ref: ArtifactRef
    finding: Finding | None = None
    finding_ref: ArtifactRef | None = None


class QuarantineReviewPolicy:
    """Validate provenance/bindings before semantic advice gains control authority.

    The Researcher has already made the open-ended semantic judgment that new
    evidence conflicts with a supported claim.  This policy does not reinterpret
    that business meaning.  It deterministically verifies the immutable Artifact
    graph and, only for a complete graph, compiles the advice into a design-owned
    ``Finding``.  The separate ``RepairRouter`` remains responsible for deciding
    whether and how that Finding may execute.
    """

    def __init__(self, *, artifact_store: ArtifactWriter) -> None:
        if artifact_store.producer != "framework":
            raise ValueError("QuarantineReviewPolicy requires the framework writer")
        self.artifacts = artifact_store

    def review(
        self,
        *,
        recommendation_ref: ArtifactRef,
        baseline_ref: ArtifactRef,
    ) -> QuarantineReviewBundle:
        recommendation = self.artifacts.get_json(
            recommendation_ref,
            DiscoveryQuarantineRecommendation,
        )
        self.artifacts.require_exact_json(
            recommendation_ref,
            recommendation,
            artifact_types=("discovery.quarantine_recommendation",),
        )
        self._require_producer(recommendation_ref, "environment-designer")
        baseline = self.artifacts.get_json(baseline_ref, DesignBaselineCheckpoint)
        self.artifacts.require_exact_json(
            baseline_ref,
            baseline,
            artifact_types=("design.baseline_checkpoint",),
        )
        self._require_producer(baseline_ref, "environment-designer")

        outcome, reason, decision_ref, clue, evidence_refs = self._evaluate(
            recommendation=recommendation,
            recommendation_ref=recommendation_ref,
            baseline=baseline,
            baseline_ref=baseline_ref,
        )
        decision = QuarantineReviewDecision(
            review_id=self._stable_id(
                "quarantine-review",
                recommendation_ref.revision_id,
                baseline_ref.revision_id,
                outcome,
                reason,
            ),
            recommendation_ref=recommendation_ref,
            baseline_ref=baseline_ref,
            outcome=outcome,
            reason_code=reason,
            challenged_claim_ids=(
                recommendation.challenged_claim_ids if outcome == "confirmed" else ()
            ),
            validated_evidence_refs=evidence_refs if outcome == "confirmed" else (),
        )
        review_ref = self.artifacts.put_json(
            artifact_id=f"{recommendation.recommendation_id}:framework-review",
            artifact_type="control.quarantine_review_decision",
            value=decision,
            dependencies=self._unique_refs(
                (
                    recommendation_ref,
                    baseline_ref,
                    *((decision_ref,) if decision_ref is not None else ()),
                    *((recommendation.clue_ref,) if clue is not None else ()),
                    *evidence_refs,
                )
            ),
        )
        if outcome == "dismissed":
            return QuarantineReviewBundle(decision=decision, decision_ref=review_ref)

        fingerprint = sha256_digest(
            canonical_json_bytes(
                {
                    "recommendation_revision": recommendation_ref.revision_id,
                    "baseline_revision": baseline_ref.revision_id,
                    "challenged_claim_ids": recommendation.challenged_claim_ids,
                    "evidence_revisions": tuple(ref.revision_id for ref in evidence_refs),
                }
            )
        )
        finding = Finding(
            finding_id=f"finding:{fingerprint.removeprefix('sha256:')[:24]}",
            category="discovery_hard_correction",
            severity=("critical" if recommendation.risk == "critical" else "high"),
            owner="design",
            subject_ref=baseline.world_spec_ref,
            summary=(
                "A provenance-checked Discovery recommendation challenges one or more "
                "supported baseline claims."
            ),
            evidence_refs=(review_ref, recommendation_ref, *evidence_refs),
            fingerprint=fingerprint,
            disclosure="repair",
            suggested_repair=(
                "Revise the owning EnvironmentDesign against the newly retrieved "
                "evidence and explicitly resolve the challenged claims."
            ),
            blocks_release=True,
        )
        finding_ref = self.artifacts.put_json(
            artifact_id=f"{recommendation.recommendation_id}:framework-finding",
            artifact_type="control.finding",
            value=finding,
            dependencies=self._unique_refs(
                (
                    baseline.world_spec_ref,
                    review_ref,
                    recommendation_ref,
                    *evidence_refs,
                )
            ),
        )
        return QuarantineReviewBundle(
            decision=decision,
            decision_ref=review_ref,
            finding=finding,
            finding_ref=finding_ref,
        )

    def _evaluate(
        self,
        *,
        recommendation: DiscoveryQuarantineRecommendation,
        recommendation_ref: ArtifactRef,
        baseline: DesignBaselineCheckpoint,
        baseline_ref: ArtifactRef,
    ) -> tuple[
        Literal["confirmed", "dismissed"],
        Literal[
            "verified_hard_correction",
            "admission_binding_mismatch",
            "baseline_binding_mismatch",
            "claim_not_hard_supported",
            "evidence_binding_mismatch",
            "evidence_not_independently_retrieved",
            "no_new_evidence",
        ],
        ArtifactRef | None,
        ExpansionClue | None,
        tuple[ArtifactRef, ...],
    ]:
        if (
            recommendation.world_spec_ref != baseline.world_spec_ref
            or baseline.world_spec_ref not in self.artifacts.dependencies(baseline_ref)
        ):
            return self._dismiss("baseline_binding_mismatch")
        try:
            self._require_producer(baseline.world_spec_ref, "environment-designer")
        except ValueError:
            return self._dismiss("baseline_binding_mismatch")

        recommendation_dependencies = self.artifacts.dependencies(recommendation_ref)
        decision_refs = tuple(
            ref
            for ref in recommendation_dependencies
            if ref.artifact_type == "discovery.admission_decision"
        )
        if len(decision_refs) != 1:
            return self._dismiss("admission_binding_mismatch")
        decision_ref = decision_refs[0]
        decision = self.artifacts.get_json(decision_ref, DiscoveryAdmissionDecision)
        self.artifacts.require_exact_json(
            decision_ref,
            decision,
            artifact_types=("discovery.admission_decision",),
        )
        try:
            self._require_producer(decision_ref, "environment-designer")
        except ValueError:
            return self._dismiss("admission_binding_mismatch")
        decision_dependencies = self.artifacts.dependencies(decision_ref)
        if (
            decision.classification != "hard_correction"
            or decision.destination != "quarantine_recommendation"
            or decision.decided_against_baseline_ref != baseline_ref
            or decision.clue_ref != recommendation.clue_ref
            or decision.challenged_claim_ids != recommendation.challenged_claim_ids
            or baseline_ref not in decision_dependencies
            or recommendation.clue_ref not in decision_dependencies
            or decision_ref not in recommendation_dependencies
        ):
            return self._dismiss("admission_binding_mismatch")

        clue = self.artifacts.get_json(recommendation.clue_ref, ExpansionClue)
        self.artifacts.require_exact_json(
            recommendation.clue_ref,
            clue,
            artifact_types=("discovery.expansion_clue",),
        )
        try:
            self._require_producer(recommendation.clue_ref, "environment-designer")
        except ValueError:
            return self._dismiss("evidence_binding_mismatch")
        if (
            tuple(recommendation.evidence_refs) != tuple(clue.evidence_refs)
            or not set(recommendation.evidence_refs) <= set(recommendation_dependencies)
        ):
            return self._dismiss("evidence_binding_mismatch")

        graph = self.artifacts.get_json(baseline.evidence_graph_ref, EvidenceGraph)
        self.artifacts.require_exact_json(
            baseline.evidence_graph_ref,
            graph,
            artifact_types=("design.evidence_graph",),
        )
        try:
            self._require_producer(baseline.evidence_graph_ref, "environment-designer")
        except ValueError:
            return self._dismiss("baseline_binding_mismatch")
        hard_claim_ids = {
            claim.claim_id
            for claim in graph.claims
            if claim.kind == "observed"
            and claim.status == "supported"
            and claim.confidence >= 0.8
        }
        if not set(recommendation.challenged_claim_ids) <= hard_claim_ids:
            return self._dismiss("claim_not_hard_supported")

        evidence_refs = tuple(recommendation.evidence_refs)
        for evidence_ref in evidence_refs:
            if evidence_ref.artifact_type != "evidence.extracted_content":
                return self._dismiss("evidence_not_independently_retrieved")
            try:
                self._require_producer(evidence_ref, "research-toolchain")
            except ValueError:
                return self._dismiss("evidence_not_independently_retrieved")
        baseline_content_hashes = {
            item.content_ref.content_hash
            for item in graph.evidence
            if item.content_ref is not None
        }
        if not any(ref.content_hash not in baseline_content_hashes for ref in evidence_refs):
            return self._dismiss("no_new_evidence")
        return (
            "confirmed",
            "verified_hard_correction",
            decision_ref,
            clue,
            evidence_refs,
        )

    @staticmethod
    def _dismiss(
        reason: _DismissReason,
    ) -> tuple[
        Literal["dismissed"],
        _DismissReason,
        None,
        None,
        tuple[ArtifactRef, ...],
    ]:
        return "dismissed", reason, None, None, ()

    def _require_producer(self, ref: ArtifactRef, producer: str) -> None:
        revision = self.artifacts.get_revision(ref)
        if revision.producer != producer:
            raise ValueError(
                f"{ref.artifact_type} requires producer {producer!r}, got "
                f"{revision.producer!r}"
            )

    @staticmethod
    def _stable_id(kind: str, *parts: str) -> str:
        digest = hashlib.sha256("\0".join(parts).encode()).hexdigest()[:24]
        return f"{kind}:{digest}"

    @staticmethod
    def _unique_refs(refs: tuple[ArtifactRef, ...]) -> tuple[ArtifactRef, ...]:
        return tuple({ref.revision_id: ref for ref in refs}.values())


__all__ = ["QuarantineReviewBundle", "QuarantineReviewPolicy"]
