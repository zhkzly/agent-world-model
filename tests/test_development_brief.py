"""Slice 2 acceptance tests for evidence closure and deterministic Briefs."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import httpx
import pytest

from agent_env_foundry.research import (
    DraftValidationError,
    EvidenceReview,
    EvidenceStore,
    NeedRecord,
    NotReleased,
    ResearchBudget,
    ResearchConfig,
    ResearchReady,
    ResearchTools,
    derive_development_brief,
    finalize_research,
)

EVIDENCE_HTML = b"""<html><body><main>
<h1>Capacity rules</h1>
<p>A successful booking reserves one available unit for the selected interval.</p>
<p>A sold-out request is refused and does not create a booking.</p>
<p>Concurrent requests must not consume the same final unit twice.</p>
</main></body></html>"""


def _evidence_response(request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        200,
        headers={"Content-Type": "text/html; charset=utf-8"},
        stream=httpx.ByteStream(EVIDENCE_HTML),
        request=request,
    )


@pytest.fixture
def evidence_context(tmp_path: Path) -> tuple[NeedRecord, EvidenceStore, dict[str, str]]:
    client = httpx.Client(transport=httpx.MockTransport(_evidence_response))
    store = EvidenceStore(tmp_path / "evidence")
    tools = ResearchTools(
        store=store,
        config=ResearchConfig(
            searxng_url="https://evidence.test",
            request_timeout_seconds=2.0,
        ),
        budget=ResearchBudget(max_fetches=1),
        http_client=client,
    )
    read = tools.read_sources(
        entries=[
            {
                "source": "https://evidence.test/capacity",
                "focus": "booking reserves sold-out refused concurrent requests",
            }
        ]
    )["reads"][0]
    passages = read["passages"]
    need = NeedRecord.from_clauses(
        "Create a synthetic reservation environment.",
        [
            "A successful reservation must consume available capacity.",
            "A sold-out request must be refused without creating a reservation.",
        ],
    )
    return (
        need,
        store,
        {
            "success_evidence": passages[0]["evidence_handle"],
            "refusal_evidence": passages[1]["evidence_handle"],
        },
    )


def _requirement(draft_id: str, statement: str, evidence_handle: str) -> dict:
    return {
        "draft_id": draft_id,
        "basis": "external_evidence",
        "statement": statement,
        "observable": f"Observe whether: {statement}",
        "falsifiable_consequence": f"The requirement is false if not: {statement}",
        "evidence": [{"evidence_handle": evidence_handle}],
    }


def valid_draft(ids: dict[str, str]) -> dict:
    sold_out_refusal = _requirement(
        "sold-out-refusal",
        "A sold-out request is refused without creating a reservation.",
        ids["refusal_evidence"],
    )
    sold_out_refusal.update(
        {
            "refusal_condition": "The selected interval has no available units.",
            "prohibited_mutation": "No reservation is created and capacity is unchanged.",
        }
    )
    return {
        "selected_interpretation": "A bounded reservation world with finite interval capacity.",
        "need_mapping": [
            {
                "clause_id": "NEED-001",
                "disposition": "accepted",
                "requirement_refs": ["capacity-consumption"],
                "rationale": "The selected world makes capacity independently observable.",
            },
            {
                "clause_id": "NEED-002",
                "disposition": "accepted",
                "requirement_refs": ["sold-out-refusal"],
                "rationale": "The refusal is a core externally visible invariant.",
            },
        ],
        "capabilities": [
            _requirement(
                "capacity-consumption",
                "A successful reservation consumes one available unit.",
                ids["success_evidence"],
            )
        ],
        "workflows": [],
        "invariants": [],
        "refusals": [sold_out_refusal],
        "initial_world": [],
        "assumptions": ["Capacity is synthetic and scoped to one interval."],
        "alternatives": ["A wait-list interpretation was considered but not selected."],
        "exclusions": ["Payment settlement is outside this environment."],
        "contradictions": [],
        "open_gaps": [],
    }


def test_host_assigns_stable_ids_and_renders_evidence_closed_brief(
    evidence_context: tuple[NeedRecord, EvidenceStore, dict[str, str]],
) -> None:
    need, store, ids = evidence_context
    draft = valid_draft(ids)

    first = derive_development_brief(need=need, draft=draft, store=store)
    second = derive_development_brief(need=need, draft=draft, store=store)

    assert [item.requirement_id for item in first.requirements] == ["REQ-001", "REQ-002"]
    assert first.digest == second.digest
    assert first.markdown == second.markdown
    assert "NEED-001" in first.markdown and "NEED-002" in first.markdown
    assert "REQ-001" in first.markdown and "REQ-002" in first.markdown
    assert ids["success_evidence"] in first.markdown
    assert first.evidence_index.entries[0].body_digest
    assert not any("Concurrent requests" in entry.text for entry in first.evidence_index.entries)
    assert "Payment settlement" in first.markdown


def test_builder_projection_is_immutable_and_excludes_raw_audit_and_downstream_fields(
    evidence_context: tuple[NeedRecord, EvidenceStore, dict[str, str]],
) -> None:
    need, store, ids = evidence_context
    draft = valid_draft(ids)
    draft["need_mapping"][0]["requirement_refs"].append("ready-world")
    draft["initial_world"] = [
        _requirement(
            "ready-world",
            "The default world contains one reservable unit and one sold-out interval.",
            ids["success_evidence"],
        )
    ]
    brief = derive_development_brief(need=need, draft=draft, store=store)
    review = EvidenceReview(
        clause_findings=tuple(
            {
                "clause_id": clause.clause_id,
                "judgment": "supported",
                "rationale": "The accepted Brief covers this Need anchor.",
                "evidence_refs": [],
            }
            for clause in need.clauses
        ),
        requirement_findings=tuple(
            {
                "requirement_id": requirement.requirement_id,
                "judgment": "supported",
                "rationale": "The declared authority and relation are supported.",
                "evidence_refs": [
                    {"evidence_handle": reference["evidence_handle"]}
                    for reference in requirement.evidence
                ],
            }
            for requirement in brief.requirements
        ),
        scope_assessment={
            "judgment": "acceptable_selection",
            "rationale": "The selected synthetic world is explicit and coherent.",
        },
        residual_limitations=("Payment settlement remains outside the selected world.",),
        unsupported_findings=(),
    )

    outcome = finalize_research(brief=brief, review=review)

    assert isinstance(outcome, ResearchReady)
    projection = outcome.builder_projection
    document = projection.to_document()
    assert set(document) == {
        "frozen_need",
        "selected_world",
        "requirements",
        "initial_world_relations",
        "cited_evidence",
    }
    assert document["frozen_need"] == need.to_document()
    assert document["selected_world"] == {
        "scope": draft["selected_interpretation"],
        "assumptions": draft["assumptions"],
        "exclusions": draft["exclusions"],
        "residual_limitations": ["Payment settlement remains outside the selected world."],
    }
    assert [item["id"] for item in document["requirements"]] == ["REQ-001", "REQ-002"]
    assert document["requirements"][0]["need_origins"] == ["NEED-001"]
    assert document["requirements"][1]["need_origins"] == ["NEED-002"]
    assert document["requirements"][0]["kind"] == "capabilities"
    assert document["requirements"][1]["kind"] == "refusals"
    assert "precondition" not in document["requirements"][0]
    assert "postcondition" not in document["requirements"][0]
    assert "refusal" not in document["requirements"][1]
    assert (
        document["requirements"][1]["refusal_condition"]
        == (draft["refusals"][0]["refusal_condition"])
    )
    assert (
        document["requirements"][1]["prohibited_mutation"]
        == (draft["refusals"][0]["prohibited_mutation"])
    )
    assert [item["id"] for item in document["initial_world_relations"]] == ["REQ-003"]
    assert {item["evidence_handle"] for item in document["cited_evidence"]} == {
        ids["success_evidence"],
        ids["refusal_evidence"],
    }

    def all_keys(value: object) -> set[str]:
        if isinstance(value, dict):
            return set(value).union(*(all_keys(item) for item in value.values()))
        if isinstance(value, list):
            return set().union(*(all_keys(item) for item in value))
        return set()

    assert all_keys(document).isdisjoint(
        {
            "brief",
            "draft",
            "need_mapping",
            "review",
            "review_evidence_index",
            "receipts",
            "acquisition_summary",
            "producer_response_ids",
            "response_ids",
            "research_trace_digest",
            "research_trace_event_count",
            "research_trace_member",
            "search_candidates",
            "uncited_evidence",
            "tools",
            "input_schema",
            "output_schema",
            "storage",
            "dependencies",
            "seed_ids",
            "task",
            "verifier",
            "reward",
            "trajectory",
        }
    )
    with pytest.raises(TypeError):
        projection.frozen_need["original_need"] = "mutated"  # type: ignore[index]


def test_workflow_and_refusal_semantics_remain_explicit_through_builder_projection(
    evidence_context: tuple[NeedRecord, EvidenceStore, dict[str, str]],
) -> None:
    need, store, ids = evidence_context
    draft = valid_draft(ids)
    workflow = _requirement(
        "reserve-workflow",
        "An available unit can be reserved.",
        ids["success_evidence"],
    )
    workflow.update(
        {
            "precondition": "The selected interval has at least one available unit.",
            "postcondition": "One reservation exists and available capacity decreases by one.",
        }
    )
    draft["workflows"] = [workflow]
    draft["need_mapping"][0]["requirement_refs"].append("reserve-workflow")
    draft["refusals"][0].update(
        {
            "refusal_condition": "The selected interval has no available units.",
            "prohibited_mutation": "No reservation is created and capacity is unchanged.",
        }
    )

    brief = derive_development_brief(need=need, draft=draft, store=store)
    model_requirements = {
        item["draft_id"]: item for item in brief.to_model_document()["requirements"]
    }
    assert model_requirements["reserve-workflow"]["precondition"] == workflow["precondition"]
    assert model_requirements["reserve-workflow"]["postcondition"] == workflow["postcondition"]
    assert (
        model_requirements["sold-out-refusal"]["refusal_condition"]
        == (draft["refusals"][0]["refusal_condition"])
    )
    assert (
        model_requirements["sold-out-refusal"]["prohibited_mutation"]
        == (draft["refusals"][0]["prohibited_mutation"])
    )

    review = EvidenceReview(
        clause_findings=tuple(
            {
                "clause_id": clause.clause_id,
                "judgment": "supported",
                "rationale": "The accepted Brief covers this Need anchor.",
                "evidence_refs": [],
            }
            for clause in need.clauses
        ),
        requirement_findings=tuple(
            {
                "requirement_id": requirement.requirement_id,
                "judgment": "supported",
                "rationale": "The declared authority and relation are supported.",
                "evidence_refs": [
                    {"evidence_handle": reference["evidence_handle"]}
                    for reference in requirement.evidence
                ],
            }
            for requirement in brief.requirements
        ),
        scope_assessment={"judgment": "supported", "rationale": "Scope is coherent."},
        residual_limitations=(),
        unsupported_findings=(),
    )
    outcome = finalize_research(brief=brief, review=review)
    assert isinstance(outcome, ResearchReady)
    projected = {
        item["kind"]: item for item in outcome.builder_projection.to_document()["requirements"]
    }
    assert projected["workflows"]["precondition"] == workflow["precondition"]
    assert projected["workflows"]["postcondition"] == workflow["postcondition"]
    assert projected["refusals"]["refusal_condition"] == (draft["refusals"][0]["refusal_condition"])
    assert (
        projected["refusals"]["prohibited_mutation"]
        == (draft["refusals"][0]["prohibited_mutation"])
    )

    for section, field in (
        ("workflows", "precondition"),
        ("workflows", "postcondition"),
        ("refusals", "refusal_condition"),
        ("refusals", "prohibited_mutation"),
    ):
        invalid = copy.deepcopy(draft)
        del invalid[section][0][field]
        with pytest.raises(DraftValidationError, match=field):
            derive_development_brief(need=need, draft=invalid, store=store)


def test_every_atomic_need_clause_requires_an_explicit_disposition(
    evidence_context: tuple[NeedRecord, EvidenceStore, dict[str, str]],
) -> None:
    need, store, ids = evidence_context
    draft = valid_draft(ids)
    draft["need_mapping"].pop()

    with pytest.raises(DraftValidationError, match="NEED-002|coverage"):
        derive_development_brief(need=need, draft=draft, store=store)


def test_duplicate_requirement_refs_are_rejected_by_host_validation(
    evidence_context: tuple[NeedRecord, EvidenceStore, dict[str, str]],
) -> None:
    need, store, ids = evidence_context
    draft = valid_draft(ids)
    draft["need_mapping"][0]["requirement_refs"] = [
        "capacity-consumption",
        "capacity-consumption",
    ]

    with pytest.raises(DraftValidationError, match="duplicate requirement references"):
        derive_development_brief(need=need, draft=draft, store=store)


def test_search_candidate_or_snippet_can_never_close_a_factual_claim(
    evidence_context: tuple[NeedRecord, EvidenceStore, dict[str, str]],
) -> None:
    need, store, ids = evidence_context
    draft = valid_draft(ids)
    draft["capabilities"][0]["evidence"] = [
        {"candidate_id": "candidate-deadbeef", "snippet": "sounds plausible"}
    ]

    with pytest.raises(DraftValidationError, match="SourceRevision|retained|evidence"):
        derive_development_brief(need=need, draft=draft, store=store)


def test_citation_must_bind_an_existing_passage_of_the_exact_revision(
    evidence_context: tuple[NeedRecord, EvidenceStore, dict[str, str]],
) -> None:
    need, store, ids = evidence_context
    draft = valid_draft(ids)
    draft["refusals"][0]["evidence"][0]["evidence_handle"] = "E999"

    with pytest.raises(DraftValidationError, match="E999"):
        derive_development_brief(need=need, draft=draft, store=store)


@pytest.mark.parametrize(
    "forbidden",
    [
        "Create tool reserve_room with input_schema and output_schema.",
        "Use CREATE TABLE reservations(id TEXT PRIMARY KEY).",
        "Emit a TaskPack verifier and scalar reward.",
    ],
)
def test_research_draft_cannot_prescribe_builder_or_downstream_schemas(
    evidence_context: tuple[NeedRecord, EvidenceStore, dict[str, str]],
    forbidden: str,
) -> None:
    need, store, ids = evidence_context
    draft = valid_draft(ids)
    draft["capabilities"][0]["statement"] = forbidden

    with pytest.raises(DraftValidationError, match="downstream|schema|prescribe"):
        derive_development_brief(need=need, draft=draft, store=store)


def test_open_core_gap_reaches_critic_but_cannot_finalize_research_ready(
    evidence_context: tuple[NeedRecord, EvidenceStore, dict[str, str]],
) -> None:
    need, store, ids = evidence_context
    draft = valid_draft(ids)
    draft["open_gaps"] = [
        {
            "clause_id": "NEED-002",
            "description": "Whether refusal preserves capacity is still unknown.",
            "can_change_core_requirement": True,
        }
    ]

    brief = derive_development_brief(need=need, draft=draft, store=store)
    assert brief.to_model_document()["open_gaps"] == draft["open_gaps"]

    outcome = finalize_research(
        brief=brief,
        review=EvidenceReview(
            clause_findings=tuple(
                {
                    "clause_id": clause.clause_id,
                    "judgment": "supported",
                    "rationale": "supported",
                    "evidence_refs": [],
                }
                for clause in need.clauses
            ),
            requirement_findings=tuple(
                {
                    "requirement_id": requirement.requirement_id,
                    "judgment": "supported",
                    "rationale": "supported",
                    "evidence_refs": [
                        {"evidence_handle": item["evidence_handle"]}
                        for item in requirement.evidence
                    ],
                }
                for requirement in brief.requirements
            ),
            scope_assessment={"judgment": "supported", "rationale": "supported"},
            residual_limitations=(),
            unsupported_findings=(),
        ),
    )
    assert isinstance(outcome, NotReleased)
    assert outcome.code == "review_requires_revision"
    assert outcome.details["declared_open_gaps"][0]["clause_id"] == "NEED-002"


def test_brief_and_evidence_index_are_plain_deterministic_documents(
    evidence_context: tuple[NeedRecord, EvidenceStore, dict[str, str]],
) -> None:
    need, store, ids = evidence_context
    brief = derive_development_brief(need=need, draft=valid_draft(ids), store=store)

    encoded = json.dumps(brief.to_document(), sort_keys=True)
    assert "candidate-" not in encoded
    assert "snippet" not in encoded
    assert "provider" not in encoded
    assert "OPENAI_API_KEY" not in encoded


def test_need_text_atomization_preserves_leading_numeric_content() -> None:
    need = NeedRecord.from_text(
        "3D assets must persist across close and reload.\n"
        "2. Refused writes must leave the original bytes unchanged."
    )

    assert [clause.text for clause in need.clauses] == [
        "3D assets must persist across close and reload.",
        "Refused writes must leave the original bytes unchanged.",
    ]


def test_need_text_atomization_ignores_prose_line_wrapping() -> None:
    wrapped = NeedRecord.from_text(
        "Create a resettable synthetic dispute environment that represents realistic\n"
        "actors, invoices, containers, charge periods, and supporting evidence.\n\n"
        "Refuse invalid or late disputes without prohibited state\n"
        "mutation."
    )
    unwrapped = NeedRecord.from_text(
        "Create a resettable synthetic dispute environment that represents realistic "
        "actors, invoices, containers, charge periods, and supporting evidence.\n\n"
        "Refuse invalid or late disputes without prohibited state mutation."
    )

    assert wrapped.original_need != unwrapped.original_need
    assert wrapped.clauses == unwrapped.clauses
    assert [clause.text for clause in wrapped.clauses] == [
        "Create a resettable synthetic dispute environment that represents realistic "
        "actors, invoices, containers, charge periods, and supporting evidence.",
        "Refuse invalid or late disputes without prohibited state mutation.",
    ]


def test_need_basis_requirement_passes_without_web_evidence(tmp_path: Path) -> None:
    need = NeedRecord.from_clauses(
        "Payments must be due within 30 days after invoice receipt.",
        ["Payments must be due within 30 days after invoice receipt."],
    )
    requirement = {
        "draft_id": "payment-due",
        "basis": "need",
        "statement": "Payment is due within 30 days after invoice receipt.",
        "observable": "The invoice records a due date no later than day 30.",
        "precondition": "The invoice has been received.",
        "postcondition": "The invoice records a due date no later than day 30.",
        "falsifiable_consequence": "A due date after day 30 violates the Need.",
        "evidence": [],
    }
    draft = {
        "selected_interpretation": "The original Need directly fixes the payment deadline.",
        "need_mapping": [
            {
                "clause_id": "NEED-001",
                "disposition": "accepted",
                "requirement_refs": ["payment-due"],
                "rationale": "The requirement restates the original Need clause.",
            }
        ],
        "capabilities": [],
        "workflows": [requirement],
        "invariants": [],
        "refusals": [],
        "initial_world": [],
        "assumptions": [],
        "alternatives": [],
        "exclusions": [],
        "contradictions": [],
        "open_gaps": [],
    }

    brief = derive_development_brief(
        need=need,
        draft=draft,
        store=EvidenceStore(tmp_path / "evidence"),
    )

    assert brief.requirements[0].basis == "need"
    assert brief.requirements[0].evidence == ()
    assert brief.evidence_index.entries == ()


def test_need_basis_requirement_with_evidence_handles_is_rejected(
    evidence_context: tuple[NeedRecord, EvidenceStore, dict[str, str]],
) -> None:
    need, store, ids = evidence_context
    draft = valid_draft(ids)
    draft["capabilities"][0]["basis"] = "need"

    with pytest.raises(DraftValidationError, match="zero evidence handles"):
        derive_development_brief(need=need, draft=draft, store=store)


def test_external_basis_without_evidence_fails_closed(
    evidence_context: tuple[NeedRecord, EvidenceStore, dict[str, str]],
) -> None:
    need, store, ids = evidence_context
    draft = valid_draft(ids)
    draft["capabilities"][0]["evidence"] = []

    with pytest.raises(DraftValidationError, match="external_evidence.*at least one"):
        derive_development_brief(need=need, draft=draft, store=store)


def test_explicit_contract_like_need_remains_need_authorized_without_web_evidence(
    tmp_path: Path,
) -> None:
    need = NeedRecord.from_clauses(
        "The generated package implements reset, tools, invoke, and close.",
        ["The generated package implements reset, tools, invoke, and close."],
    )
    draft = {
        "selected_interpretation": "The canonical package contract is host authority.",
        "need_mapping": [
            {
                "clause_id": "NEED-001",
                "disposition": "accepted",
                "requirement_refs": ["contract-row"],
                "rationale": "The explicit user clause remains original-Need authority.",
            }
        ],
        "capabilities": [
            {
                "draft_id": "contract-row",
                "basis": "need",
                "statement": "Implement reset, tools, invoke, and close.",
                "observable": "The package exposes the canonical methods.",
                "falsifiable_consequence": "A missing method violates the Need.",
                "evidence": [],
            }
        ],
        "workflows": [],
        "invariants": [],
        "refusals": [],
        "initial_world": [],
        "assumptions": [],
        "alternatives": [],
        "exclusions": [],
        "contradictions": [],
        "open_gaps": [],
    }
    store = EvidenceStore(tmp_path / "evidence")

    brief = derive_development_brief(need=need, draft=draft, store=store)

    assert len(brief.requirements) == 1
    assert brief.requirements[0].basis == "need"
    assert brief.requirements[0].evidence == ()
    assert brief.evidence_index.entries == ()

    invalid = json.loads(json.dumps(draft))
    invalid["need_mapping"][0]["disposition"] = "contract"
    with pytest.raises(DraftValidationError, match="schema/evidence contract"):
        derive_development_brief(need=need, draft=invalid, store=store)
