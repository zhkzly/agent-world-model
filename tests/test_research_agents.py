"""Slice 2 acceptance tests for Responses history and independent Brief review."""

from __future__ import annotations

import copy
import json
import re
from dataclasses import asdict
from pathlib import Path
from typing import Any

import httpx
import pytest

import agent_env_foundry.agents as agents_module
from agent_env_foundry.agents import (
    AgentRoute,
    BriefEvidenceReviewer,
    ResponsesResearchAgent,
    load_research_skill,
    run_research,
)
from agent_env_foundry.research import (
    DevelopmentBrief,
    DraftValidationError,
    EvidenceIndex,
    EvidenceIndexEntry,
    EvidenceIntegrityError,
    EvidenceReview,
    EvidenceStore,
    NeedRecord,
    NotReleased,
    ResearchBudget,
    ResearchConfig,
    ResearchFailure,
    ResearchReady,
    ResearchTools,
    aggregate_evidence_review,
    derive_development_brief,
    finalize_research,
)

RAW_HEX_ID = re.compile(r"(?<![0-9a-f])[0-9a-f]{64}(?![0-9a-f])")


class _FunctionCall:
    type = "function_call"

    def __init__(self, name: str, arguments: str, call_id: str) -> None:
        self.name = name
        self.arguments = arguments
        self.call_id = call_id


class _FakeResponse:
    def __init__(self, response_id: str, output: list[Any], output_text: str = "") -> None:
        self.id = response_id
        self.output = output
        self.output_text = output_text


class _FakeResponses:
    def __init__(self, responses: list[_FakeResponse]) -> None:
        self._responses = iter(responses)
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> _FakeResponse:
        self.calls.append(kwargs)
        return next(self._responses)


class _FakeClient:
    def __init__(self, responses: list[_FakeResponse]) -> None:
        self.responses = _FakeResponses(responses)


class _StubTools:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def search_sources(self, **arguments: Any) -> dict[str, Any]:
        self.calls.append(("search_sources", arguments))
        return {
            "candidates": [],
            "receipts": [{"query": arguments["queries"][0]["query"]}],
            "failures": [],
            "warnings": [],
            "remaining_budget": {"search_calls": 1},
        }

    def read_sources(self, **arguments: Any) -> dict[str, Any]:
        self.calls.append(("read_sources", arguments))
        return {
            "reads": [],
            "failures": [],
            "remaining_budget": {"fetches": 1},
        }


def _minimal_draft() -> dict[str, Any]:
    return {
        "selected_interpretation": "A bounded synthetic world.",
        "need_mapping": [],
        "capabilities": [],
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


def _review_document(
    *,
    clause_ids: tuple[str, ...] = ("NEED-001",),
    requirement_ids: tuple[str, ...] = ("REQ-001",),
    clause_judgment: str = "supported",
    requirement_judgment: str = "supported",
    requirement_basis: str = "need",
    evidence_handles: tuple[str, ...] = (),
    scope_judgment: str = "supported",
    residual_limitations: tuple[str, ...] = (),
) -> dict[str, Any]:
    references = [{"evidence_handle": item} for item in evidence_handles]
    return {
        "clause_findings": [
            {
                "clause_id": clause_id,
                "judgment": clause_judgment,
                "rationale": "Clause-level semantic finding.",
                "evidence_refs": [],
            }
            for clause_id in clause_ids
        ],
        "requirement_findings": [
            {
                "requirement_id": requirement_id,
                "judgment": requirement_judgment,
                "rationale": "Requirement-level semantic finding.",
                "evidence_refs": references if requirement_basis == "external_evidence" else [],
            }
            for requirement_id in requirement_ids
        ],
        "scope_assessment": {
            "judgment": scope_judgment,
            "rationale": "Scope is explicit and faithful.",
        },
        "residual_limitations": list(residual_limitations),
        "unsupported_findings": [],
    }


def _as_review(document: dict[str, Any]) -> EvidenceReview:
    return EvidenceReview(
        clause_findings=tuple(document["clause_findings"]),
        requirement_findings=tuple(document["requirement_findings"]),
        scope_assessment=document["scope_assessment"],
        residual_limitations=tuple(document["residual_limitations"]),
        unsupported_findings=tuple(document["unsupported_findings"]),
    )


def test_responses_loop_resends_unmodified_output_items_and_matching_tool_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "invocation-only-secret"
    monkeypatch.setenv("OPENAI_API_KEY", secret)
    function_call = _FunctionCall(
        "search_sources",
        json.dumps({"queries": [{"query": "unfamiliar workflow", "focus": "NEED-001"}]}),
        "call-17",
    )
    client = _FakeClient(
        [
            _FakeResponse("resp-1", [function_call]),
            _FakeResponse("resp-2", [], json.dumps(_minimal_draft())),
        ]
    )
    factory_calls: list[tuple[str, str, int]] = []

    def factory(*, api_key: str, base_url: str, max_retries: int) -> _FakeClient:
        factory_calls.append((api_key, base_url, max_retries))
        return client

    tools = _StubTools()
    agent = ResponsesResearchAgent(tools=tools, client_factory=factory)
    need = NeedRecord.from_clauses("Need", ["Learn one unfamiliar workflow."])

    result = agent.run(need)

    assert result == _minimal_draft()
    assert tools.calls == [
        (
            "search_sources",
            {"queries": [{"query": "unfamiliar workflow", "focus": "NEED-001"}]},
        )
    ]
    assert factory_calls == [(secret, "http://127.0.0.1:8317/v1", 0)]
    first, second = client.responses.calls
    assert first["model"] == "gpt-5.6-luna"
    assert first["store"] is False
    assert {tool["name"] for tool in first["tools"]} == {"search_sources", "read_sources"}
    assert "previous_response_id" not in second
    assert any(item is function_call for item in second["input"])
    tool_outputs = [item for item in second["input"] if isinstance(item, dict)]
    matching = [item for item in tool_outputs if item.get("type") == "function_call_output"]
    assert matching[0]["call_id"] == "call-17"
    assert json.loads(matching[0]["output"])["receipts"][0]["query"] == ("unfamiliar workflow")
    assert first["text"]["format"]["type"] == "json_schema"
    assert first["text"]["format"]["strict"] is True
    assert secret not in repr(client.responses.calls)
    assert RAW_HEX_ID.search(repr(client.responses.calls)) is None
    assert not any(
        keyword in repr(first)
        for keyword in ("minItems", "maxItems", "minLength", "maxLength", "pattern")
    )


def test_raw_need_is_preserved_and_mechanical_segments_are_not_semantic_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "invocation-only-secret")
    client = _FakeClient([_FakeResponse("raw-need", [], json.dumps(_minimal_draft()))])

    def factory(*, api_key: str, base_url: str, max_retries: int) -> _FakeClient:
        return client

    original = (
        "Create a resettable synthetic booking environment.\n"
        "Refuse invalid reservations without changing capacity."
    )
    need = NeedRecord.from_text(original)
    result = ResponsesResearchAgent(tools=_StubTools(), client_factory=factory).run(need)

    assert result == _minimal_draft()
    assert need.original_need == original
    assert [item.text for item in need.clauses] == [
        "Create a resettable synthetic booking environment.",
        "Refuse invalid reservations without changing capacity.",
    ]
    rendered = client.responses.calls[0]["input"][0]["content"]
    assert "host-assigned coverage anchors" in rendered
    assert "host-assigned atomic clauses" not in rendered
    assert json.dumps(need.to_document(), ensure_ascii=False, sort_keys=True) in rendered


def test_producer_prompt_and_skill_require_agenda_before_search_and_semantic_closure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "invocation-only-secret")
    client = _FakeClient([_FakeResponse("agenda", [], json.dumps(_minimal_draft()))])

    def factory(*, api_key: str, base_url: str, max_retries: int) -> _FakeClient:
        return client

    ResponsesResearchAgent(tools=_StubTools(), client_factory=factory).run(
        NeedRecord.from_text("Research a resettable stateful environment.")
    )

    producer_prompt = client.responses.calls[0]["input"][0]["content"]
    for surface in (producer_prompt, load_research_skill().text):
        normalized = surface.lower()
        assert "research agenda" in normalized
        assert "before" in normalized and "first `search_sources`" in normalized
        for axis in (
            "world",
            "success",
            "refusal",
            "dynamics",
            "initial",
            "authority",
            "scope",
            "substrate",
        ):
            assert axis in normalized
        assert "unresolved agenda question" in normalized
        assert "semantic closure" in normalized
        assert "every need anchor" in normalized
        assert "precondition" in normalized and "postcondition" in normalized
        assert "prohibited mutation" in normalized


def test_one_provider_turn_ceiling_preserves_the_original_rejection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "invocation-only-secret")
    client = _FakeClient([_FakeResponse("draft-invalid", [], json.dumps(_minimal_draft()))])

    def factory(*, api_key: str, base_url: str, max_retries: int) -> _FakeClient:
        return client

    def reject_draft(document: dict[str, Any]) -> None:
        raise DraftValidationError("missing exact evidence binding")

    with pytest.raises(ResearchFailure) as caught:
        ResponsesResearchAgent(
            tools=_StubTools(),
            route=AgentRoute(max_provider_turns=1),
            client_factory=factory,
        ).run(NeedRecord.from_text("Learn one workflow."), final_validator=reject_draft)

    assert caught.value.code == "provider_turn_budget_exhausted"
    assert caught.value.phase == "brief"
    assert caught.value.details["original_code"] == "DraftValidationError"
    assert caught.value.details["original_message"] == "missing exact evidence binding"
    assert caught.value.details["max_provider_turns"] == 1


def test_rejected_draft_is_returned_to_same_agent_for_complete_correction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "invocation-only-secret")
    bad = _minimal_draft()
    bad["selected_interpretation"] = "Draft with a mistyped evidence handle."
    corrected = _minimal_draft()
    client = _FakeClient(
        [
            _FakeResponse("draft-bad", [], json.dumps(bad)),
            _FakeResponse("draft-corrected", [], json.dumps(corrected)),
        ]
    )

    def factory(*, api_key: str, base_url: str, max_retries: int) -> _FakeClient:
        return client

    attempts = 0

    def validate(document: dict[str, Any]) -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise DraftValidationError("unknown evidence handle E99")

    result = ResponsesResearchAgent(tools=_StubTools(), client_factory=factory).run(
        NeedRecord.from_clauses("Need", ["Learn one workflow."]),
        final_validator=validate,
    )

    assert result == corrected
    assert attempts == 2
    assert "unknown evidence handle E99" in repr(client.responses.calls[1]["input"])
    assert "complete corrected Draft" in repr(client.responses.calls[1]["input"])
    assert "copy evidence handles exactly" in repr(client.responses.calls[1]["input"])


def test_route_has_no_persistable_credential_field() -> None:
    route = AgentRoute()
    document = asdict(route)
    assert document == {
        "base_url": "http://127.0.0.1:8317/v1",
        "model": "gpt-5.6-luna",
        "max_provider_turns": 24,
    }
    assert "api_key" not in document


def test_missing_invocation_credential_is_typed_and_secret_safe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    agent = ResponsesResearchAgent(tools=_StubTools())
    need = NeedRecord.from_clauses("Need", ["Learn one workflow."])

    with pytest.raises(ResearchFailure) as excinfo:
        agent.run(need)

    assert excinfo.value.phase == "agent"
    assert excinfo.value.code == "missing_openai_api_key"
    assert "OPENAI_API_KEY" in excinfo.value.message


def test_only_the_two_stage_method_skills_are_packaged() -> None:
    skill = load_research_skill()
    skill_files = list((Path(skill.path).parents[1]).rglob("SKILL.md"))
    assert {path.parent.name for path in skill_files} == {
        "research",
        "environment-codegen",
    }
    assert Path(skill.path) in skill_files
    assert "search_sources" in skill.text
    assert "read_sources" in skill.text
    assert "select one evidence-grounded variant" in skill.text
    assert "Do not demand an exhaustive field/status taxonomy" in skill.text
    assert "stakeholder preference" in skill.text
    forbidden = ("CREATE TABLE", "input_schema", "TaskPack", "reward schema")
    assert not any(term in skill.text for term in forbidden)


def _brief() -> DevelopmentBrief:
    return DevelopmentBrief.for_test(
        markdown="# Development Brief\n\nFrozen brief.",
        evidence_index=EvidenceIndex(entries=()),
        requirement_ids=("REQ-001",),
    )


def test_fresh_evidence_reviewer_receives_only_need_bounded_evidence_and_brief(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "reviewer-secret")
    review_document = _review_document()
    client = _FakeClient([_FakeResponse("reviewer-1", [], json.dumps(review_document))])

    def factory(*, api_key: str, base_url: str, max_retries: int) -> _FakeClient:
        return client

    reviewer = BriefEvidenceReviewer(client_factory=factory)
    need = NeedRecord.from_clauses("Need", ["Cover the clause."])
    review = reviewer.review(need=need, brief=_brief())

    assert review.clause_findings[0]["judgment"] == "supported"
    assert len(client.responses.calls) == 1
    request = client.responses.calls[0]
    rendered_input = repr(request["input"])
    assert "Cover the clause" in rendered_input
    assert "REQ-001" in rendered_input
    assert "Bounded Evidence" in rendered_input
    assert "PRODUCER_PRIVATE_NONCE" not in rendered_input
    assert request["tools"] == []
    assert "previous_response_id" not in request


def test_host_accepts_supported_findings_with_residual_limitations(tmp_path: Path) -> None:
    document = _review_document(
        residual_limitations=("The selected jurisdiction is not a universal legal statement.",)
    )
    review = _as_review(document)

    outcome = finalize_research(
        brief=_brief(),
        review=review,
    )

    assert isinstance(outcome, ResearchReady)
    assert outcome.review.residual_limitations
    carrier = tmp_path / "research-ready.json"
    outcome.write(carrier)
    persisted = json.loads(carrier.read_text(encoding="utf-8"))
    assert persisted["digest"] == outcome.digest
    assert persisted["review"]["residual_limitations"] == list(outcome.review.residual_limitations)
    with pytest.raises(FileExistsError):
        outcome.write(carrier)


def test_host_maps_typed_blocking_finding_to_revision_not_terminal_llm_verdict() -> None:
    document = _review_document(requirement_judgment="contradicted")
    review = _as_review(document)

    assert aggregate_evidence_review(brief=_brief(), review=review) == "REVISE"
    outcome = finalize_research(
        brief=_brief(),
        review=review,
    )
    assert isinstance(outcome, NotReleased)
    assert outcome.code == "review_requires_revision"


def test_host_blocks_undisclosed_scope_narrowing_but_not_residual_limits() -> None:
    document = _review_document(scope_judgment="unjustified_narrowing")
    review = _as_review(document)

    assert aggregate_evidence_review(brief=_brief(), review=review) == "REVISE"


def test_empty_or_missing_review_findings_cannot_finalize() -> None:
    review = EvidenceReview(
        clause_findings=(),
        requirement_findings=(),
        scope_assessment={"judgment": "supported", "rationale": "empty forged review"},
        residual_limitations=(),
        unsupported_findings=(),
    )

    with pytest.raises(ResearchFailure, match="exactly one ordered finding"):
        finalize_research(
            brief=_brief(),
            review=review,
        )


def test_requirement_authority_mismatch_is_always_blocking() -> None:
    document = _review_document(requirement_judgment="authority_mismatch")
    assert aggregate_evidence_review(brief=_brief(), review=_as_review(document)) == "REVISE"


def test_host_requires_research_and_reviewer_agreement_for_unsupported(tmp_path: Path) -> None:
    need = NeedRecord.from_clauses("Need", ["Represent an impossible external rule."])
    draft = _minimal_draft()
    draft["need_mapping"] = [
        {
            "clause_id": "NEED-001",
            "disposition": "unsupported",
            "requirement_refs": [],
            "rationale": "No coherent evidence-grounded world can satisfy the explicit clause.",
        }
    ]
    brief = derive_development_brief(
        need=need,
        draft=draft,
        store=EvidenceStore(tmp_path / "evidence"),
    )
    document = _review_document(requirement_ids=())
    document["clause_findings"][0]["judgment"] = "contradicted"
    document["unsupported_findings"] = [
        {
            "clause_id": "NEED-001",
            "evidence_refs": [],
            "rationale": "The explicit Need clause cannot form a coherent world.",
        }
    ]
    review = _as_review(document)

    unclaimed = _review_document(requirement_ids=())
    assert aggregate_evidence_review(brief=brief, review=_as_review(unclaimed)) == "REVISE"

    # A blocking finding first requests correction; unsupported is only terminal
    # when the proposal is confirmed without a separate correctable finding.
    assert aggregate_evidence_review(brief=brief, review=review) == "REVISE"
    document["clause_findings"][0]["judgment"] = "supported"
    assert aggregate_evidence_review(brief=brief, review=_as_review(document)) == "UNSUPPORTED"


def test_provider_turn_budget_exhaustion_is_typed_without_product_receipts(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "invocation-only-secret")
    function_call = _FunctionCall(
        "search_sources",
        json.dumps({"queries": [{"query": "gap query", "focus": "NEED-001"}]}),
        "call-gap",
    )
    client = _FakeClient(
        [
            _FakeResponse("gap-1", [function_call]),
            _FakeResponse("gap-2", [function_call]),
            _FakeResponse("gap-3", [function_call]),
        ]
    )

    def factory(*, api_key: str, base_url: str, max_retries: int) -> _FakeClient:
        return client

    tools = _StubTools()
    tools.store = EvidenceStore(tmp_path / "evidence")
    need = NeedRecord.from_clauses("Need", ["Learn the core workflow."])

    outcome = run_research(
        need=need,
        tools=tools,
        route=AgentRoute(max_provider_turns=2),
        client_factory=factory,
    )

    assert isinstance(outcome, NotReleased)
    assert outcome.code == "provider_turn_budget_exhausted"
    assert outcome.details == {
        "phase": "agent",
        "original_code": "budget_exhausted",
        "original_message": "no provider turns remaining",
        "max_provider_turns": 2,
    }
    assert not hasattr(outcome, "receipts")


def test_reviewer_revises_evidence_refs_outside_the_bounded_index(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "reviewer-secret")
    review_document = _review_document()
    review_document["clause_findings"][0]["evidence_refs"] = [{"evidence_handle": "E99"}]
    corrected = _review_document()
    client = _FakeClient(
        [
            _FakeResponse("reviewer-bad-ref", [], json.dumps(review_document)),
            _FakeResponse("reviewer-corrected", [], json.dumps(corrected)),
        ]
    )

    def factory(*, api_key: str, base_url: str, max_retries: int) -> _FakeClient:
        return client

    need = NeedRecord.from_clauses("Need", ["Cover the clause."])

    review = BriefEvidenceReviewer(client_factory=factory).review(need=need, brief=_brief())

    assert review.clause_findings[0]["judgment"] == "supported"
    assert len(client.responses.calls) == 2
    second_input = repr(client.responses.calls[1]["input"])
    assert "reviewer_evidence_outside_bounded_index" in second_input
    assert "copy evidence handles exactly" in second_input


def test_reviewer_request_uses_only_short_bounded_handles_not_host_hashes_or_unrelated_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "reviewer-secret")
    protected_source_id = "source-revision-" + "a" * 64
    protected_passage_id = "passage-" + "b" * 64
    entry = EvidenceIndexEntry(
        evidence_handle="E1",
        source_handle="S1",
        source_revision_id=protected_source_id,
        body_digest="c" * 64,
        final_url="https://evidence.test/policy",
        passage_id=protected_passage_id,
        passage_digest="d" * 64,
        text="Payment is due within 30 days after invoice receipt.",
        locators=(f"extracted://{protected_source_id}#chars=1-20",),
    )
    brief = DevelopmentBrief.for_test(
        markdown=(
            "# Host audit Brief\n\n"
            f"{protected_source_id}/{protected_passage_id}\n"
            "UNRELATED_STORED_NAVIGATION must stay outside reviewer input."
        ),
        evidence_index=EvidenceIndex(entries=(entry,)),
        requirement_ids=("REQ-001",),
    )
    review_document = _review_document()
    review_document["clause_findings"][0]["evidence_refs"] = [{"evidence_handle": "E1"}]
    client = _FakeClient([_FakeResponse("reviewer-1", [], json.dumps(review_document))])

    def factory(*, api_key: str, base_url: str, max_retries: int) -> _FakeClient:
        return client

    need = NeedRecord.from_clauses(
        "Payment is due within 30 days after invoice receipt.",
        ["Payment is due within 30 days after invoice receipt."],
    )
    review = BriefEvidenceReviewer(client_factory=factory).review(need=need, brief=brief)

    assert review.clause_findings[0]["judgment"] == "supported"
    rendered = repr(client.responses.calls[0])
    assert "E1" in rendered and "S1" in rendered
    assert entry.text in rendered
    assert "UNRELATED_STORED_NAVIGATION" not in rendered
    assert RAW_HEX_ID.search(rendered) is None


def _payment_deadline_draft(statement: str) -> dict[str, Any]:
    return {
        "selected_interpretation": "A bounded invoice workflow.",
        "need_mapping": [
            {
                "clause_id": "NEED-001",
                "disposition": "accepted",
                "requirement_refs": ["payment-deadline"],
                "rationale": "The requirement is grounded directly in the original Need.",
            }
        ],
        "capabilities": [],
        "workflows": [
            {
                "draft_id": "payment-deadline",
                "basis": "need",
                "statement": statement,
                "observable": "Inspect the invoice event and the recorded deadline.",
                "precondition": "The invoice event has occurred.",
                "postcondition": "The corresponding deadline is recorded.",
                "falsifiable_consequence": "The event-specific 30-day deadline is exceeded.",
                "evidence": [],
            }
        ],
        "invariants": [],
        "refusals": [],
        "initial_world": [],
        "assumptions": [],
        "alternatives": [],
        "exclusions": [],
        "contradictions": [],
        "open_gaps": [],
    }


def test_issuance_deadline_cannot_support_payment_due_and_typed_findings_reuse_history(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "invocation-only-secret")
    first_draft = _payment_deadline_draft(
        "The invoice must be issued within 30 days after delivery."
    )
    corrected_draft = _payment_deadline_draft(
        "Payment is due within 30 days after invoice receipt."
    )
    first_output_item = {"type": "message", "id": "producer-draft-1"}
    producer = _FakeClient(
        [
            _FakeResponse("producer-1", [first_output_item], json.dumps(first_draft)),
            _FakeResponse("producer-2", [], json.dumps(corrected_draft)),
        ]
    )
    first_review = _review_document(
        clause_judgment="contradicted",
        requirement_judgment="contradicted",
    )
    first_review["clause_findings"][0]["rationale"] = (
        "An issuance deadline concerns when an invoice is sent; it does not support the distinct "
        "claim that payment is due within 30 days."
    )
    passing_review = _review_document()
    reviewer_one = _FakeClient([_FakeResponse("reviewer-1", [], json.dumps(first_review))])
    reviewer_two = _FakeClient([_FakeResponse("reviewer-2", [], json.dumps(passing_review))])
    clients = iter((producer, reviewer_one, reviewer_two))

    def factory(*, api_key: str, base_url: str, max_retries: int) -> _FakeClient:
        return next(clients)

    need = NeedRecord.from_clauses(
        "Payment is due within 30 days after invoice receipt.",
        ["Payment is due within 30 days after invoice receipt."],
    )
    tools = _StubTools()
    tools.store = EvidenceStore(tmp_path / "evidence")

    outcome = run_research(
        need=need,
        tools=tools,
        route=AgentRoute(max_provider_turns=4),
        client_factory=factory,
    )

    assert isinstance(outcome, ResearchReady)
    assert len(producer.responses.calls) == 2
    revised_input = producer.responses.calls[1]["input"]
    assert any(item is first_output_item for item in revised_input)
    feedback = repr(revised_input)
    assert "review_action" in feedback
    assert "REVISE" in feedback
    assert "clause_findings" in feedback
    assert "requirement_findings" in feedback
    assert first_review["clause_findings"][0]["rationale"] in feedback
    assert "authority_reminder" in feedback
    assert "original Need" in feedback
    assert len(reviewer_one.responses.calls) == 1
    assert len(reviewer_two.responses.calls) == 1
    assert "issued within 30 days" in repr(reviewer_one.responses.calls[0]["input"])
    assert "Payment is due within 30 days" in repr(reviewer_two.responses.calls[0]["input"])


def test_reviewer_schema_contains_no_llm_terminal_verdict() -> None:
    encoded = json.dumps(agents_module._EVIDENCE_REVIEW_SCHEMA, sort_keys=True)
    for forbidden in ("PASS", "RESEARCH_AGAIN", "NOT_RELEASED"):
        assert forbidden not in encoded


def test_declared_core_gap_reaches_fresh_critic_and_same_producer_revision(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "invocation-only-secret")
    function_call = _FunctionCall(
        "search_sources",
        json.dumps({"queries": [{"query": "gap query", "focus": "NEED-001"}]}),
        "call-gap",
    )
    corrected_draft = _minimal_draft()
    corrected_draft["need_mapping"] = [
        {
            "clause_id": "NEED-001",
            "disposition": "accepted",
            "requirement_refs": ["selected-workflow"],
            "rationale": "A coherent bounded workflow is selected and disclosed.",
        }
    ]
    corrected_draft["workflows"] = [
        {
            "draft_id": "selected-workflow",
            "basis": "need",
            "statement": "The environment implements one disclosed coherent workflow.",
            "observable": "The selected workflow is represented in public state transitions.",
            "precondition": "The disclosed workflow is selected for this synthetic world.",
            "postcondition": "The selected workflow is represented in public state transitions.",
            "falsifiable_consequence": "The disclosed workflow cannot be completed.",
            "evidence": [],
        }
    ]
    corrected_draft["assumptions"] = ["One coherent variant is selected for the synthetic world."]
    first_draft = copy.deepcopy(corrected_draft)
    first_draft["open_gaps"] = [
        {
            "clause_id": "NEED-001",
            "description": "The user did not select one of several coherent workflow variants.",
            "can_change_core_requirement": True,
        }
    ]
    first_draft["assumptions"] = []
    producer = _FakeClient(
        [
            _FakeResponse("gap-1", [function_call]),
            _FakeResponse("gap-2", [], json.dumps(first_draft)),
            _FakeResponse("gap-3", [], json.dumps(corrected_draft)),
        ]
    )
    selection_review = _review_document(
        clause_judgment="supported",
        scope_judgment="acceptable_selection",
        residual_limitations=("The Need permits several coherent workflow variants.",),
    )
    passing_review = _review_document(scope_judgment="acceptable_selection")
    reviewer_one = _FakeClient(
        [_FakeResponse("reviewer-selection", [], json.dumps(selection_review))]
    )
    reviewer_two = _FakeClient([_FakeResponse("reviewer-pass", [], json.dumps(passing_review))])
    clients = iter((producer, reviewer_one, reviewer_two))

    def factory(*, api_key: str, base_url: str, max_retries: int) -> _FakeClient:
        return next(clients)

    tools = _StubTools()
    tools.store = EvidenceStore(tmp_path / "evidence")
    need = NeedRecord.from_clauses("Need", ["Learn the core workflow."])

    outcome = run_research(
        need=need,
        tools=tools,
        route=AgentRoute(max_provider_turns=5),
        client_factory=factory,
    )

    assert isinstance(outcome, ResearchReady)
    assert len(producer.responses.calls) == 3
    assert "declared_open_gaps" in repr(producer.responses.calls[2]["input"])
    assert "REVISE" in repr(producer.responses.calls[2]["input"])
    assert len(reviewer_one.responses.calls) == 1
    assert len(reviewer_two.responses.calls) == 1


def test_evidence_integrity_failure_is_host_owned_and_never_sent_to_the_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "invocation-only-secret")
    client = _FakeClient([_FakeResponse("draft-1", [], json.dumps(_minimal_draft()))])

    def factory(*, api_key: str, base_url: str, max_retries: int) -> _FakeClient:
        return client

    def raise_integrity(document: dict[str, Any]) -> None:
        raise EvidenceIntegrityError(
            phase="evidence",
            code="evidence_handle_corrupt",
            message="a retained evidence handle no longer matches its stored identity",
            details={"evidence_handle": "E1"},
        )

    with pytest.raises(EvidenceIntegrityError):
        ResponsesResearchAgent(tools=_StubTools(), client_factory=factory).run(
            NeedRecord.from_clauses("Need", ["One clause."]),
            final_validator=raise_integrity,
        )

    assert len(client.responses.calls) == 1


def test_read_tool_schema_demands_focused_source_entries_and_no_hash_knowledge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "invocation-only-secret")
    entry = {"source": "C1", "focus": "the exact payment-due window"}
    function_call = _FunctionCall("read_sources", json.dumps({"entries": [entry]}), "call-read")
    client = _FakeClient(
        [
            _FakeResponse("read-1", [function_call]),
            _FakeResponse("read-2", [], json.dumps(_minimal_draft())),
        ]
    )

    def factory(*, api_key: str, base_url: str, max_retries: int) -> _FakeClient:
        return client

    tools = _StubTools()
    ResponsesResearchAgent(tools=tools, client_factory=factory).run(
        NeedRecord.from_clauses("Need", ["One clause."])
    )

    request = client.responses.calls[0]
    read_tool = next(item for item in request["tools"] if item["name"] == "read_sources")
    parameters = read_tool["parameters"]
    assert set(parameters["properties"]) == {"entries"}
    entry_schema = parameters["properties"]["entries"]["items"]
    assert set(entry_schema["properties"]) == {"source", "focus"}
    assert entry_schema["required"] == ["source", "focus"]
    assert "pattern" not in json.dumps(read_tool)
    assert RAW_HEX_ID.search(json.dumps(read_tool)) is None
    assert tools.calls[-1] == ("read_sources", {"entries": [entry]})


REVIEWER_EVIDENCE_HTML = b"""<html><body><main>
<p>A confirmed reservation consumes one unit of capacity.</p>
<p>The confirmed reservation capacity rule is part of the public policy.</p>
<p>Concurrent requests must not consume the same final unit twice.</p>
</main></body></html>"""


def test_reviewer_input_excludes_unshown_store_passages_and_no_bulk_expansion_exists(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "reviewer-secret")

    def serve(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"Content-Type": "text/html; charset=utf-8"},
            stream=httpx.ByteStream(REVIEWER_EVIDENCE_HTML),
            request=request,
        )

    store = EvidenceStore(tmp_path / "evidence")
    tools = ResearchTools(
        store=store,
        config=ResearchConfig(searxng_url="https://critic.test", request_timeout_seconds=2.0),
        budget=ResearchBudget(max_fetches=1),
        http_client=httpx.Client(transport=httpx.MockTransport(serve)),
    )
    read = tools.read_sources(
        entries=[
            {
                "source": "https://critic.test/policy",
                "focus": "confirmed reservation capacity",
            }
        ]
    )["reads"][0]
    cited_handle = read["passages"][0]["evidence_handle"]
    need = NeedRecord.from_clauses(
        "Reservations consume capacity.",
        ["A confirmed reservation consumes one unit of capacity."],
    )
    draft = {
        "selected_interpretation": "A bounded reservation world.",
        "need_mapping": [
            {
                "clause_id": "NEED-001",
                "disposition": "accepted",
                "requirement_refs": ["capacity-consumption"],
                "rationale": "The cited passage grounds the consumption rule.",
            }
        ],
        "capabilities": [
            {
                "draft_id": "capacity-consumption",
                "basis": "external_evidence",
                "statement": "A confirmed reservation consumes one unit of capacity.",
                "observable": "Native capacity decreases by one after confirmation.",
                "falsifiable_consequence": "Capacity is unchanged after a confirmation.",
                "evidence": [{"evidence_handle": cited_handle}],
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
    brief = derive_development_brief(need=need, draft=draft, store=store)
    review_document = _review_document(
        requirement_basis="external_evidence",
        evidence_handles=(cited_handle,),
    )
    review_document["clause_findings"][0]["evidence_refs"] = [{"evidence_handle": cited_handle}]
    client = _FakeClient([_FakeResponse("reviewer-bounded", [], json.dumps(review_document))])

    def factory(*, api_key: str, base_url: str, max_retries: int) -> _FakeClient:
        return client

    review = BriefEvidenceReviewer(client_factory=factory).review(need=need, brief=brief)

    assert review.requirement_findings[0]["judgment"] == "supported"
    rendered = repr(client.responses.calls[0]["input"])
    assert "A confirmed reservation consumes one unit of capacity." in rendered
    assert "The confirmed reservation capacity rule is part of the public policy." in rendered
    assert "Concurrent requests" not in rendered
    assert RAW_HEX_ID.search(rendered) is None
    assert len(brief.evidence_index.entries) == 1
    assert len(brief.review_evidence_index.entries) == 2
    accepted = finalize_research(
        brief=brief,
        review=review,
    )
    assert isinstance(accepted, ResearchReady)
    carrier = tmp_path / "accepted-research.json"
    accepted.write(carrier)
    persisted = json.loads(carrier.read_text(encoding="utf-8"))
    assert len(persisted["brief"]["evidence_index"]["entries"]) == 1
    assert len(persisted["brief"]["review_evidence_index"]["entries"]) == 2
    extraction_path = next((store.root / "extractions").glob("extraction-*.json"))
    protected_extraction = store.read_extraction(extraction_path.stem)
    assert any(
        "Concurrent requests" in str(passage["text"])
        for passage in protected_extraction["passages"]
    )
    # The all-EvidenceStore passage expansion is not part of the product surface.
    assert not hasattr(EvidenceStore, "iter_passages")
