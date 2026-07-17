from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from agent_world.contracts import (
    ArtifactRef,
    Budget,
    ExpansionClue,
    ExpansionClueSnapshot,
    ExpansionSourceCatalog,
    ExpansionSourceDescriptor,
    ExpansionSourceRequest,
    ExpansionSourceResult,
    PermissionScope,
)
from agent_world.designer.expansion_source import EvidenceBackedExpansionSource
from agent_world.designer.models import (
    ExpansionSourceClueDraft,
    ExpansionSourceHypothesisDraft,
    ExpansionSourcePlan,
    ExpansionSourceSynthesis,
    PlannedSearchQuery,
)

SOURCE_KINDS = (
    "requirement_gap",
    "web_workflow",
    "tool_ecosystem",
    "repository",
    "pool_neighborhood",
    "random_theme",
    "capability_gap",
)


def ref(artifact_id: str, artifact_type: str) -> ArtifactRef:
    suffix = artifact_id.encode().hex().ljust(64, "0")[:64]
    digest = f"sha256:{suffix}"
    return ArtifactRef(
        artifact_id=artifact_id,
        revision_id=digest,
        artifact_type=artifact_type,
        content_hash=digest,
        media_type="application/json",
        size_bytes=1,
    )


def source_budget(**updates: object) -> Budget:
    return Budget(
        llm_tokens=20_000,
        agent_turns=2,
        search_calls=1,
        tool_calls=4,
        wall_seconds=120,
    ).model_copy(update=updates)


def descriptor(kind: str, **updates: object) -> ExpansionSourceDescriptor:
    return ExpansionSourceDescriptor(
        source_id=f"source:{kind}",
        kind=kind,
        budget=source_budget(),
    ).model_copy(update=updates)


def request(kind: str, *, feedback: bool = False) -> ExpansionSourceRequest:
    return ExpansionSourceRequest(
        request_id=f"source-request:{kind}",
        created_at=datetime.now(UTC),
        descriptor=descriptor(kind),
        parents=(
            {
                "package_manifest_ref": ref("manifest", "environment_package_manifest"),
                "design_ref": ref("design", "design.environment_design"),
                "coverage_map_ref": ref("coverage", "design.coverage_map"),
            },
        ),
        target_coverage_dimensions=("tool_semantics",),
        feedback_refs=(ref("feedback", "consumer.capability_feedback"),) if feedback else (),
        permissions=PermissionScope(),
        seed=7,
    )


def test_catalog_accepts_all_replaceable_source_kinds() -> None:
    catalog = ExpansionSourceCatalog(
        catalog_id="source-catalog:test",
        sources=tuple(descriptor(kind) for kind in SOURCE_KINDS),
    )

    assert tuple(item.kind for item in catalog.sources) == SOURCE_KINDS
    for item in catalog.sources:
        prompt = EvidenceBackedExpansionSource._plan_prompt(  # noqa: SLF001
            request(item.kind, feedback=item.kind == "capability_gap")
        )
        assert f"Source kind: {item.kind}" in prompt
        assert "Search snippets and model memory are never evidence" in prompt


def test_source_budget_cannot_reserve_candidate_execution() -> None:
    with pytest.raises(ValidationError, match="cannot reserve candidate work"):
        ExpansionSourceDescriptor(
            source_id="source:invalid",
            kind="random_theme",
            budget=source_budget(build_seconds=1),
        )


def test_capability_gap_requires_frozen_feedback_but_other_sources_do_not() -> None:
    with pytest.raises(ValidationError, match="explicit frozen feedback"):
        request("capability_gap")

    value = request("capability_gap", feedback=True)
    assert value.feedback_refs[0].artifact_type == "consumer.capability_feedback"
    assert request("random_theme").feedback_refs == ()


def test_insufficient_evidence_cannot_publish_a_clue() -> None:
    request_ref = ref("source-request", "expansion.source_request")
    clue_ref = ref("source-clue", "expansion.source_clue")

    with pytest.raises(ValidationError, match="cannot publish clues"):
        ExpansionSourceResult(
            result_id="source-result:test",
            source_request_ref=request_ref,
            status="insufficient_evidence",
            clue_refs=(clue_ref,),
        )

    result = ExpansionSourceResult(
        result_id="source-result:test",
        source_request_ref=request_ref,
        status="insufficient_evidence",
    )
    assert result.clue_refs == ()


def test_source_uses_the_canonical_expansion_clue_contract() -> None:
    request_ref = ref("source-request", "expansion.source_request")
    evidence_ref = ref("evidence", "evidence.extracted_content")
    clue = ExpansionClue(
        clue_id="clue:canonical",
        origin_run_ref=request_ref,
        evidence_refs=(evidence_ref,),
        hypothesis="A retry-aware tool workflow may expose a missing transition constraint.",
        tool_or_workflow_surface=("retry-aware-api",),
        coverage_dimensions=("tool_semantics",),
        scope_relation="adjacent",
        feasibility="plausible",
        risk="low",
        dedup_fingerprint="sha256:" + "1" * 64,
    )

    assert clue.origin_run_ref == request_ref
    assert clue.evidence_refs == (evidence_ref,)


def test_synthesis_rejects_unknown_evidence_and_out_of_scope_coverage() -> None:
    source_request = request("random_theme")
    plan = ExpansionSourcePlan(
        hypotheses=(
            ExpansionSourceHypothesisDraft(
                statement="A supported workflow",
                coverage_dimensions=("tool_semantics",),
            ),
        ),
        queries=(
            PlannedSearchQuery(
                text="supported workflow tool semantics",
                rationale="Find complete external documentation.",
            ),
        ),
    )
    unknown = ExpansionSourceSynthesis(
        clues=(
            ExpansionSourceClueDraft(
                hypothesis_index=0,
                hypothesis="A supported workflow",
                evidence_ids=("missing",),
                coverage_dimensions=("tool_semantics",),
                scope_relation="adjacent",
                feasibility="plausible",
                risk="low",
            ),
        )
    )
    with pytest.raises(ValueError, match="unknown fetched evidence"):
        EvidenceBackedExpansionSource._validate_synthesis(  # noqa: SLF001
            source_request,
            unknown,
            plan,
            {"known"},
        )

    out_of_scope = unknown.model_copy(
        update={
            "clues": (
                unknown.clues[0].model_copy(
                    update={"evidence_ids": ("known",), "coverage_dimensions": ("other",)}
                ),
            )
        }
    )
    with pytest.raises(ValueError, match="target coverage"):
        EvidenceBackedExpansionSource._validate_synthesis(  # noqa: SLF001
            source_request,
            out_of_scope,
            plan,
            {"known"},
        )


def test_random_theme_plan_remains_a_hypothesis_before_fetch() -> None:
    source_request = request("random_theme")
    plan = ExpansionSourcePlan(
        hypotheses=(
            ExpansionSourceHypothesisDraft(
                statement="Investigate a cross-system approval timeout workflow.",
                coverage_dimensions=("tool_semantics",),
            ),
        ),
        queries=(
            PlannedSearchQuery(
                text="approval workflow timeout API semantics",
                rationale="Find complete external documentation.",
            ),
        ),
    )

    EvidenceBackedExpansionSource._validate_plan(source_request, plan)  # noqa: SLF001
    assert plan.hypotheses[0].statement


def test_clue_snapshot_requires_one_result_for_every_source_request() -> None:
    with pytest.raises(ValidationError, match="one Source result per request"):
        ExpansionClueSnapshot(
            snapshot_id="clue-snapshot:test",
            created_at=datetime.now(UTC),
            source_catalog_ref=ref("catalog", "expansion.source_catalog"),
            source_request_refs=(
                ref("request-a", "expansion.source_request"),
                ref("request-b", "expansion.source_request"),
            ),
            source_result_refs=(ref("result-a", "expansion.source_result"),),
        )
