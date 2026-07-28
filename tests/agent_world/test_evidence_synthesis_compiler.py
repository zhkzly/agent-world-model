"""True compiler-boundary regressions for Researcher citation selection."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from agent_world.contracts import Evidence
from agent_world.designer.evidence_synthesis_compiler import (
    compile_evidence_synthesis,
    project_evidence_citation_catalog,
)
from agent_world.designer.models import EvidenceSynthesisSourceDraft
from agent_world.designer.validation import StructuredSemanticError


def _evidence(evidence_id: str, *, summary: str) -> Evidence:
    content_hash = "sha256:" + "a" * 64
    return Evidence(
        evidence_id=evidence_id,
        source_kind="web",
        source_uri="https://example.invalid/source",
        retrieved_at=datetime.now(UTC),
        retrieval_status="success",
        raw_content_hash=content_hash,
        content_hash=content_hash,
        fetcher="test-fetcher",
        fetcher_version="1",
        extractor="test-extractor",
        extractor_version="1",
        observed_summary=summary,
    )


def _source(*, indexes: tuple[int, ...]) -> EvidenceSynthesisSourceDraft:
    return EvidenceSynthesisSourceDraft.model_validate(
        {
            "claims": (
                {
                    "claim_id": "claim:catalog-selection",
                    "kind": "observed",
                    "statement": "The source supports the selected workflow fact.",
                    "confidence": 0.9,
                    "evidence_catalog_indexes": indexes,
                    "claim_status": "supported",
                    "risk": "low",
                },
            )
        }
    )


def test_compiler_maps_a_researcher_catalog_position_to_the_opaque_framework_id() -> None:
    opaque_id = "evidence:opaque-framework-identity"
    evidence = (
        _evidence(opaque_id, summary="One bounded source body is available."),
    )

    compiled = compile_evidence_synthesis(_source(indexes=(1,)), evidence=evidence)
    catalog = project_evidence_citation_catalog(evidence)

    assert compiled.claims[0].evidence_ids == (opaque_id,)
    assert catalog == (
        {
            "citation_index": 1,
            "source_kind": "web",
            "source_uri": "https://example.invalid/source",
            "title": None,
            "observed_summary": "One bounded source body is available.",
            "retrieval_status": "success",
            "newly_fetched": False,
        },
    )
    assert opaque_id not in json.dumps(catalog, sort_keys=True)


def test_compiler_returns_actionable_feedback_for_one_invalid_catalog_position() -> None:
    source = _source(indexes=(2,))
    evidence = (_evidence("evidence:one", summary="One source."),)

    with pytest.raises(StructuredSemanticError) as captured:
        compile_evidence_synthesis(source, evidence=evidence)

    issue = captured.value.issues[0]
    assert issue.code == "evidence_catalog_index_out_of_range"
    assert issue.location == (
        "claims",
        "claim:catalog-selection",
        "evidence_catalog_indexes",
        0,
    )
    assert issue.violated_condition == (
        "every evidence_catalog_indexes value selects one supplied catalog entry"
    )
    assert issue.expected_category == "an integer from 1 through 1"
