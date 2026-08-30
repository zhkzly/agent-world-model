from __future__ import annotations

import json
from dataclasses import replace
from typing import Any

import pytest

from agent_env_foundry.agents import AgentRoute
from agent_env_foundry.qualification_contracts import PublicSurfaceManifest
from agent_env_foundry.research import BuilderProjection, ResearchFailure
from agent_env_foundry.semantics_authoring import (
    EXPECTED_TASK_SEMANTICS_SCHEMA,
    ExpectedSemanticsError,
    freeze_expected_task_semantics,
    generate_expected_task_semantics,
)


def test_provider_schema_declares_a_type_for_every_property() -> None:
    pending: list[Any] = [EXPECTED_TASK_SEMANTICS_SCHEMA]
    while pending:
        node = pending.pop()
        if not isinstance(node, dict):
            continue
        properties = node.get("properties")
        if isinstance(properties, dict):
            assert all(isinstance(value, dict) and "type" in value for value in properties.values())
        pending.extend(node.values())


def _projection() -> BuilderProjection:
    return BuilderProjection(
        frozen_need={"original_need": "A persistent counter", "clauses": []},
        selected_world={"scope": "counter world"},
        requirements=(
            {
                "id": "REQ-001",
                "kind": "workflows",
                "state_relation": "Increment changes the counter",
                "observable_relation": "A read returns the new count",
                "precondition": "Counter exists",
                "postcondition": "Counter is larger",
                "falsifiable_consequence": "Count is unchanged",
            },
            {
                "id": "REQ-002",
                "kind": "workflows",
                "state_relation": "Read reports the current counter",
                "observable_relation": "The response contains the current count",
                "precondition": "Counter exists",
                "postcondition": "Counter state is unchanged",
                "falsifiable_consequence": "The response differs from native state",
            },
            {
                "id": "REQ-003",
                "kind": "refusals",
                "state_relation": "Invalid increments are refused",
                "observable_relation": "A refusal is returned",
                "refusal_condition": "Amount is non-positive",
                "prohibited_mutation": "Counter must not change",
                "falsifiable_consequence": "Counter changes",
            },
        ),
        initial_world_relations=(
            {
                "id": "REQ-004",
                "state_relation": "Counter starts at zero",
                "observable_relation": "Reset reports zero",
                "falsifiable_consequence": "Reset reports non-zero",
            },
        ),
        cited_evidence=({"source_revision_id": "source-secret-must-not-be-forwarded"},),
    )


def _surface() -> PublicSurfaceManifest:
    return PublicSurfaceManifest(
        start_schema={"type": "object", "additionalProperties": True},
        reset_observation_schema={
            "type": "object",
            "properties": {"count": {"type": "integer"}},
            "required": ["count"],
            "additionalProperties": False,
        },
        tool_specs=(
            {
                "name": "read_counter",
                "description": "Read the current counter.",
                "input_schema": {
                    "type": "object",
                    "properties": {},
                    "required": [],
                    "additionalProperties": False,
                },
                "output_schema": {
                    "type": "object",
                    "properties": {"current_count": {"type": "integer"}},
                    "required": ["current_count"],
                    "additionalProperties": False,
                },
            },
        ),
        public_documents_digest="a" * 64,
    )


def _document() -> dict[str, Any]:
    return {
        "requirements": [
            {
                "requirement_id": "REQ-001",
                "disposition": "Taskable",
                "rationale": "Public increment can establish the relation",
                "preconditions": ["counter exists"],
                "outcomes": ["counter increases"],
                "refusals": [],
                "collateral_constraints": ["no unrelated state changes"],
                "workflow_ids": ["counter-workflow"],
            },
            {
                "requirement_id": "REQ-002",
                "disposition": "Taskable",
                "rationale": "A public read can answer the current-value query",
                "preconditions": ["counter exists"],
                "outcomes": ["the current count is reported"],
                "refusals": [],
                "collateral_constraints": ["counter state remains unchanged"],
                "workflow_ids": ["counter-workflow"],
            },
            {
                "requirement_id": "REQ-003",
                "disposition": "NotTaskable",
                "rationale": "A refusal is Qualification evidence, not a user goal",
                "preconditions": [],
                "outcomes": [],
                "refusals": ["non-positive amount"],
                "collateral_constraints": ["counter unchanged"],
                "workflow_ids": ["counter-workflow"],
            },
            {
                "requirement_id": "REQ-004",
                "disposition": "NotTaskable",
                "rationale": "Initial state licenses starts and conditions, not an outcome Task",
                "preconditions": [],
                "outcomes": [],
                "refusals": [],
                "collateral_constraints": [],
                "workflow_ids": ["counter-workflow"],
            },
        ],
        "capabilities": [
            {
                "capability_id": "increment",
                "requirement_ids": ["REQ-001"],
                "workflow_ids": ["counter-workflow"],
                "actor_role": "operator",
                "task_kind": "state_change",
                "intent_label": "increment the counter",
                "qualification_goal": (
                    "Increase the selected counter and report the resulting public value."
                ),
                "answer_fields": [{"field_id": "current-count", "public_label": "Current count"}],
            },
            {
                "capability_id": "read-counter",
                "requirement_ids": ["REQ-002"],
                "workflow_ids": ["counter-workflow"],
                "actor_role": "operator",
                "task_kind": "query",
                "intent_label": "read the current counter",
                "qualification_goal": (
                    "Read the selected counter through the public interface and report "
                    "Current count."
                ),
                "answer_fields": [{"field_id": "current-count", "public_label": "Current count"}],
            },
        ],
        "composition_rules": [
            {
                "rule_id": "increment-then-read",
                "workflow_id": "counter-workflow",
                "capability_ids": ["increment", "read-counter"],
                "max_occurrences": 1,
            }
        ],
        "conditions": [
            {
                "condition_id": "counter-is-zero",
                "requirement_ids": ["REQ-004"],
                "workflow_ids": ["counter-workflow"],
                "observable_relation": "Reset publicly reports whether the counter is zero",
                "public_label": "the counter is zero",
                "visibility": "reset",
                "binding_scope": "world",
                "true_capability_ids": ["increment"],
                "false_capability_ids": ["read-counter"],
                "report_field_id": "current-count",
            }
        ],
    }


def test_expected_semantics_freezes_complete_requirement_coverage() -> None:
    frozen = freeze_expected_task_semantics(_projection(), _document())
    frozen_document = frozen.to_document()
    assert frozen_document["format"] == "expected-task-semantics/1"
    assert [item["requirement_id"] for item in frozen_document["requirements"]] == [
        "REQ-001",
        "REQ-002",
        "REQ-003",
        "REQ-004",
    ]
    assert [
        item["requirement_id"]
        for item in frozen_document["requirements"]
        if item["disposition"] == "Taskable"
    ] == ["REQ-001", "REQ-002"]
    assert frozen.digest
    assert frozen_document["capabilities"][1]["answer_fields"] == [
        {"field_id": "current-count", "public_label": "Current count"}
    ]
    reordered = _document()
    reordered["requirements"] = list(reversed(reordered["requirements"]))
    reordered["capabilities"] = list(reversed(reordered["capabilities"]))
    reordered["composition_rules"][0]["capability_ids"].reverse()
    reordered["conditions"][0]["true_capability_ids"].reverse()
    assert freeze_expected_task_semantics(_projection(), reordered).digest == frozen.digest


def test_expected_semantics_rejects_omission_and_incomplete_taskable_relation() -> None:
    missing = _document()
    missing["requirements"] = missing["requirements"][:-1]
    with pytest.raises(ExpectedSemanticsError, match="coverage"):
        freeze_expected_task_semantics(_projection(), missing)

    incomplete = _document()
    incomplete["requirements"][0]["outcomes"] = []
    with pytest.raises(ExpectedSemanticsError, match="Taskable"):
        freeze_expected_task_semantics(_projection(), incomplete)

    unknown = _document()
    unknown["capabilities"][0]["requirement_ids"] = ["REQ-999"]
    with pytest.raises(ExpectedSemanticsError, match="unknown Requirement"):
        freeze_expected_task_semantics(_projection(), unknown)

    initial_task = _document()
    initial_task["requirements"][3].update(
        disposition="Taskable",
        preconditions=["world can be reset"],
        outcomes=["initial world exists"],
    )
    initial_task["capabilities"].append(
        {
            "capability_id": "reset-world",
            "requirement_ids": ["REQ-004"],
            "workflow_ids": ["counter-workflow"],
            "actor_role": "operator",
            "task_kind": "process",
            "intent_label": "reset the world",
            "qualification_goal": "Create the initial public world and report completion.",
            "answer_fields": [],
        }
    )
    with pytest.raises(ExpectedSemanticsError, match="initial-world"):
        freeze_expected_task_semantics(_projection(), initial_task)

    missing_query_answer = _document()
    missing_query_answer["capabilities"][1]["answer_fields"] = []
    with pytest.raises(ExpectedSemanticsError, match="Taskable capability requires answer_fields"):
        freeze_expected_task_semantics(_projection(), missing_query_answer)

    missing_state_answer = _document()
    missing_state_answer["capabilities"][0]["answer_fields"] = []
    with pytest.raises(ExpectedSemanticsError, match="Taskable capability requires answer_fields"):
        freeze_expected_task_semantics(_projection(), missing_state_answer)


def test_expected_semantics_rejects_unanchored_composition_and_condition() -> None:
    bad_rule = _document()
    bad_rule["composition_rules"][0]["capability_ids"] = ["increment", "missing"]
    with pytest.raises(ExpectedSemanticsError, match=r"composition_rules\[0\]"):
        freeze_expected_task_semantics(_projection(), bad_rule)

    bad_condition = _document()
    bad_condition["conditions"][0]["requirement_ids"] = ["REQ-999"]
    bad_condition["conditions"][0]["true_capability_ids"] = ["missing"]
    with pytest.raises(ExpectedSemanticsError) as caught:
        freeze_expected_task_semantics(_projection(), bad_condition)
    message = str(caught.value)
    assert "conditions[0].requirement_ids" in message
    assert "conditions[0].true_capability_ids" in message

    branch_specific_contract = _document()
    branch_specific_contract["capabilities"][0]["answer_fields"] = [
        {"field_id": "updated-count", "public_label": "Updated count"}
    ]
    assert freeze_expected_task_semantics(_projection(), branch_specific_contract).digest


class _Response:
    output = ()

    def __init__(self, document: dict[str, Any]) -> None:
        self.output_text = json.dumps(document)


class _Responses:
    def __init__(self, documents: list[dict[str, Any]], calls: list[dict[str, Any]]) -> None:
        self.documents = documents
        self.calls = calls

    def create(self, **kwargs: Any) -> _Response:
        self.calls.append(kwargs)
        return _Response(self.documents[min(len(self.calls) - 1, len(self.documents) - 1)])


class _Client:
    def __init__(self, responses: _Responses) -> None:
        self.responses = responses


def test_expected_semantics_provider_turn_is_fresh_typed_and_candidate_blind(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    calls: list[dict[str, Any]] = []
    responses = _Responses([_document()], calls)
    result = generate_expected_task_semantics(
        _projection(),
        public_surface=_surface(),
        route=AgentRoute(),
        client_factory=lambda **_: _Client(responses),
    )
    assert len(result.to_document()["capabilities"]) == 2
    assert len(calls) == 1
    request = calls[0]
    assert request["text"]["format"]["type"] == "json_schema"
    visible = json.dumps(request["input"], sort_keys=True)
    assert "candidate" not in visible.casefold()
    assert "source-secret-must-not-be-forwarded" not in visible
    assert "public_surface" in visible
    assert "read_counter" in visible
    assert "current_count" in visible
    assert "REQ-001" in visible
    assert "required_requirement_ids" in visible
    assert "covers every mapped Taskable Requirement outcome" in visible
    assert "one exact value" in visible
    assert "free-form summaries" in visible
    assert "must use task_kind=state_change" in visible
    assert "task_kind=process only when success requires no business state change" in visible
    assert "Every Taskable capability must declare at least one answer field" in visible
    assert "padded AnswerFields" in visible
    assert "one uniform public source" in visible
    assert "split capabilities" in visible.casefold()


def test_provider_validation_feedback_reports_all_findings_then_accepts_replacement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    invalid = _document()
    invalid["requirements"] = invalid["requirements"][:-1]
    invalid["capabilities"][0]["requirement_ids"] = ["REQ-999"]
    calls: list[dict[str, Any]] = []
    responses = _Responses([invalid, _document()], calls)
    result = generate_expected_task_semantics(
        _projection(),
        public_surface=_surface(),
        route=replace(AgentRoute(), max_provider_turns=2),
        client_factory=lambda **_: _Client(responses),
    )
    assert len(result.to_document()["capabilities"]) == 2
    assert len(calls) == 2
    feedback = json.dumps(calls[1]["input"], ensure_ascii=False)
    assert "Requirement coverage mismatch" in feedback
    assert "capabilities[0].requirement_ids" in feedback
    assert "complete corrected Expected TaskSemantics" in feedback


def test_provider_validation_failure_exhausts_bounded_turns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    invalid = _document()
    invalid["requirements"] = invalid["requirements"][:-1]
    responses = _Responses([invalid], [])
    with pytest.raises(ResearchFailure, match="budget"):
        generate_expected_task_semantics(
            _projection(),
            public_surface=_surface(),
            route=replace(AgentRoute(), max_provider_turns=1),
            client_factory=lambda **_: _Client(responses),
        )
