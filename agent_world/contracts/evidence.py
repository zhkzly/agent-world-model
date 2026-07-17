"""Evidence graph and multi-dimensional coverage contracts."""

from __future__ import annotations

import hashlib
from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, model_validator

from .base import ArtifactRef, ContentHash, Identifier, NonEmptyStr, V2Contract


class Evidence(V2Contract):
    evidence_id: Identifier
    source_kind: Literal[
        "web",
        "repository",
        "api",
        "sdk",
        "cli",
        "mcp",
        "database",
        "schema",
        "user_asset",
        "live_probe",
    ]
    source_uri: NonEmptyStr
    retrieved_at: AwareDatetime
    retrieval_status: Literal["success", "partial", "failed"]
    raw_content_hash: ContentHash
    # Hash of the normalized content from which claims were actually extracted.
    content_hash: ContentHash
    fetcher: Identifier
    fetcher_version: NonEmptyStr
    extractor: Identifier
    extractor_version: NonEmptyStr
    title: NonEmptyStr | None = None
    source_version: NonEmptyStr | None = None
    license: NonEmptyStr | None = None
    source_risk: Literal["low", "medium", "high", "critical"] = "medium"
    observed_summary: NonEmptyStr
    # content_ref is the normalized/extracted body, never an unlabelled raw response.
    content_ref: ArtifactRef | None = None
    raw_content_ref: ArtifactRef | None = None
    response_metadata_ref: ArtifactRef | None = None


class Claim(V2Contract):
    claim_id: Identifier
    kind: Literal["observed", "inference", "product_decision", "bounded_assumption"]
    statement: NonEmptyStr
    confidence: Annotated[float, Field(ge=0, le=1)]
    evidence_ids: tuple[Identifier, ...] = ()
    supports_claim_ids: tuple[Identifier, ...] = ()
    contradicts_claim_ids: tuple[Identifier, ...] = ()
    status: Literal["supported", "contested", "unresolved", "superseded"] = "unresolved"
    risk: Literal["low", "medium", "high", "critical"] = "medium"

    @model_validator(mode="after")
    def observed_claim_has_evidence(self) -> Claim:
        if self.kind == "observed" and not self.evidence_ids:
            raise ValueError("observed claims require evidence_ids")
        return self


class EvidenceConflict(V2Contract):
    conflict_id: Identifier
    claim_ids: Annotated[tuple[Identifier, ...], Field(min_length=2)]
    description: NonEmptyStr
    resolution: NonEmptyStr | None = None


class EvidenceGraph(V2Contract):
    graph_id: Identifier
    revision: Annotated[int, Field(ge=1)]
    evidence: tuple[Evidence, ...] = ()
    claims: tuple[Claim, ...] = ()
    conflicts: tuple[EvidenceConflict, ...] = ()
    unresolved_questions: tuple[NonEmptyStr, ...] = ()

    @model_validator(mode="after")
    def validate_references(self) -> EvidenceGraph:
        evidence_ids = [item.evidence_id for item in self.evidence]
        claim_ids = [item.claim_id for item in self.claims]
        if len(set(evidence_ids)) != len(evidence_ids):
            raise ValueError("evidence_id values must be unique")
        if len(set(claim_ids)) != len(claim_ids):
            raise ValueError("claim_id values must be unique")
        evidence_set = set(evidence_ids)
        usable_evidence = {
            item.evidence_id for item in self.evidence if item.retrieval_status != "failed"
        }
        claim_set = set(claim_ids)
        for claim in self.claims:
            if not set(claim.evidence_ids) <= evidence_set:
                raise ValueError(f"claim {claim.claim_id} references unknown evidence")
            related = set(claim.supports_claim_ids) | set(claim.contradicts_claim_ids)
            if not related <= claim_set:
                raise ValueError(f"claim {claim.claim_id} references unknown claims")
            if claim.claim_id in related:
                raise ValueError(f"claim {claim.claim_id} cannot reference itself")
            if claim.kind == "observed" and not set(claim.evidence_ids) <= usable_evidence:
                raise ValueError(f"observed claim {claim.claim_id} references failed retrieval")
        for conflict in self.conflicts:
            if not set(conflict.claim_ids) <= claim_set:
                raise ValueError(f"conflict {conflict.conflict_id} references unknown claims")
        return self


class EvidencePassage(V2Contract):
    """One bounded, byte-auditable excerpt selected from extracted evidence."""

    passage_id: Identifier
    evidence_id: Identifier
    source_uri: NonEmptyStr
    source_content_hash: ContentHash
    start_char: Annotated[int, Field(ge=0)]
    end_char: Annotated[int, Field(gt=0)]
    passage_hash: ContentHash
    text: NonEmptyStr
    matched_terms: tuple[NonEmptyStr, ...] = ()

    @model_validator(mode="after")
    def valid_range_and_hash(self) -> EvidencePassage:
        if self.end_char <= self.start_char:
            raise ValueError("evidence passage end_char must exceed start_char")
        if self.end_char - self.start_char != len(self.text):
            raise ValueError("evidence passage character range must match text length")
        digest = "sha256:" + hashlib.sha256(self.text.encode("utf-8")).hexdigest()
        if self.passage_hash != digest:
            raise ValueError("evidence passage hash does not match text")
        if len(self.matched_terms) != len(set(self.matched_terms)):
            raise ValueError("evidence passage matched_terms must be unique")
        return self


class EvidencePassagePack(V2Contract):
    """Framework-selected bounded context for one tool-free synthesis turn."""

    pack_id: Identifier
    query_fingerprint: ContentHash
    source_count: Annotated[int, Field(ge=1)]
    passages: Annotated[tuple[EvidencePassage, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def unique_passages_and_complete_source_coverage(self) -> EvidencePassagePack:
        passage_ids = [item.passage_id for item in self.passages]
        if len(passage_ids) != len(set(passage_ids)):
            raise ValueError("evidence passage ids must be unique")
        evidence_ids = {item.evidence_id for item in self.passages}
        if len(evidence_ids) != self.source_count:
            raise ValueError("passage pack must cover every counted evidence source")
        return self


CoverageLevel = Literal["absent", "partial", "complete", "not_applicable"]


class CoverageDimension(V2Contract):
    dimension: Identifier
    evidence_discovered: CoverageLevel = "absent"
    world_modelled: CoverageLevel = "absent"
    runtime_implemented: CoverageLevel = "absent"
    verifier_covered: CoverageLevel = "absent"
    claim_ids: tuple[Identifier, ...] = ()
    rule_ids: tuple[Identifier, ...] = ()
    unknowns: tuple[NonEmptyStr, ...] = ()
    known_divergences: tuple[NonEmptyStr, ...] = ()


class CoverageMap(V2Contract):
    coverage_id: Identifier
    revision: Annotated[int, Field(ge=1)]
    dimensions: Annotated[tuple[CoverageDimension, ...], Field(min_length=1)]
    evidence_graph_ref: ArtifactRef

    @model_validator(mode="after")
    def unique_dimensions(self) -> CoverageMap:
        names = [entry.dimension for entry in self.dimensions]
        if len(set(names)) != len(names):
            raise ValueError("coverage dimensions must be unique")
        return self


__all__ = [
    "Claim",
    "CoverageDimension",
    "CoverageLevel",
    "CoverageMap",
    "Evidence",
    "EvidenceConflict",
    "EvidenceGraph",
    "EvidencePassage",
    "EvidencePassagePack",
]
