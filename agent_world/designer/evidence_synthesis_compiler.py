"""Compile Researcher citation positions into immutable evidence references.

The Researcher decides which supplied source supports a semantic claim.  It
does not own the content-addressed ``evidence_id`` namespace: that value is an
opaque framework identity.  This module deliberately keeps the mapping local,
deterministic, and auditable while presenting a compact numbered catalog to
the runtime Agent.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping, Sequence

from agent_world.contracts import Claim, Evidence, EvidenceConflict, EvidencePassagePack

from .models import EvidenceSynthesis, EvidenceSynthesisSourceDraft
from .validation import StructuredSemanticError, StructuredSemanticIssue
from .validators import validate_evidence_synthesis_references


def canonical_evidence_catalog(evidence: Sequence[Evidence]) -> tuple[Evidence, ...]:
    """Return one frozen ordered catalog, rejecting conflicting identities."""

    by_id: dict[str, Evidence] = {}
    ordered: list[Evidence] = []
    for item in evidence:
        existing = by_id.get(item.evidence_id)
        if existing is None:
            by_id[item.evidence_id] = item
            ordered.append(item)
        elif existing != item:
            raise ValueError(f"evidence catalog id collision: {item.evidence_id}")
    if not ordered:
        raise ValueError("evidence citation catalog must not be empty")
    return tuple(ordered)


def project_evidence_citation_catalog(
    evidence: Sequence[Evidence],
    *,
    passage_pack: EvidencePassagePack | None = None,
    newly_fetched_evidence_ids: Collection[str] = (),
    source_paths_by_evidence_id: Mapping[str, str] | None = None,
) -> tuple[dict[str, object], ...]:
    """Make the runtime-facing catalog without leaking opaque framework ids."""

    catalog = canonical_evidence_catalog(evidence)
    fresh_ids = frozenset(newly_fetched_evidence_ids)
    paths = source_paths_by_evidence_id or {}
    passages_by_evidence_id: dict[str, list[dict[str, object]]] = {}
    if passage_pack is not None:
        for passage in passage_pack.passages:
            passages_by_evidence_id.setdefault(passage.evidence_id, []).append(
                {
                    "text": passage.text,
                    "matched_terms": passage.matched_terms,
                }
            )
        catalog_ids = {item.evidence_id for item in catalog}
        passage_ids = set(passages_by_evidence_id)
        if passage_ids != catalog_ids:
            raise ValueError(
                "evidence passage pack must cover exactly the frozen citation catalog"
            )

    projection: list[dict[str, object]] = []
    for index, item in enumerate(catalog, start=1):
        entry: dict[str, object] = {
            "citation_index": index,
            "source_kind": item.source_kind,
            "source_uri": item.source_uri,
            "title": item.title,
            "observed_summary": item.observed_summary,
            "retrieval_status": item.retrieval_status,
            "newly_fetched": item.evidence_id in fresh_ids,
        }
        if passage_pack is not None:
            entry["passages"] = tuple(passages_by_evidence_id[item.evidence_id])
        source_path = paths.get(item.evidence_id)
        if source_path is not None:
            entry["source_path"] = source_path
        projection.append(entry)
    return tuple(projection)


def compile_evidence_synthesis(
    source: EvidenceSynthesisSourceDraft,
    *,
    evidence: Sequence[Evidence],
) -> EvidenceSynthesis:
    """Restore canonical ids after validating every Agent-selected position."""

    catalog = canonical_evidence_catalog(evidence)
    issues: list[StructuredSemanticIssue] = []
    claim_ids = [claim.claim_id for claim in source.claims]
    claim_id_counts = {claim_id: claim_ids.count(claim_id) for claim_id in set(claim_ids)}
    for source_index, claim in enumerate(source.claims):
        anchor: str | int = (
            claim.claim_id if claim_id_counts[claim.claim_id] == 1 else source_index
        )
        if claim.kind == "observed" and not claim.evidence_catalog_indexes:
            issues.append(
                StructuredSemanticIssue(
                    code="observed_claim_citation_missing",
                    location=("claims", anchor, "evidence_catalog_indexes"),
                    message="an observed claim needs at least one supplied citation catalog index",
                    violated_condition=(
                        "every observed claim selects at least one frozen evidence catalog entry"
                    ),
                    expected_category="one or more 1-based evidence catalog indexes",
                )
            )
        for citation_offset, citation_index in enumerate(claim.evidence_catalog_indexes):
            if citation_index > len(catalog):
                issues.append(
                    StructuredSemanticIssue(
                        code="evidence_catalog_index_out_of_range",
                        location=(
                            "claims",
                            anchor,
                            "evidence_catalog_indexes",
                            citation_offset,
                        ),
                        message=(
                            "citation index is outside the supplied frozen evidence catalog"
                        ),
                        violated_condition=(
                            "every evidence_catalog_indexes value selects one supplied "
                            "catalog entry"
                        ),
                        expected_category=(
                            f"an integer from 1 through {len(catalog)}"
                        ),
                    )
                )
    if issues:
        raise StructuredSemanticError(tuple(issues))

    compiled = EvidenceSynthesis(
        claims=tuple(
            Claim(
                claim_id=claim.claim_id,
                kind=claim.kind,
                statement=claim.statement,
                confidence=claim.confidence,
                evidence_ids=tuple(
                    catalog[citation_index - 1].evidence_id
                    for citation_index in claim.evidence_catalog_indexes
                ),
                supports_claim_ids=claim.supports_claim_ids,
                contradicts_claim_ids=claim.contradicts_claim_ids,
                status=claim.claim_status,
                risk=claim.risk,
            )
            for claim in source.claims
        ),
        conflicts=tuple(
            EvidenceConflict(
                conflict_id=conflict.conflict_id,
                claim_ids=conflict.claim_ids,
                description=conflict.description,
                resolution=conflict.resolution,
            )
            for conflict in source.conflicts
        ),
        unresolved_questions=source.unresolved_questions,
    )
    validate_evidence_synthesis_references(compiled, catalog)
    return compiled


__all__ = [
    "canonical_evidence_catalog",
    "compile_evidence_synthesis",
    "project_evidence_citation_catalog",
]
