from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import get_type_hints

import pytest

from agent_env_foundry.preparation import (
    ENVIRONMENT_RELEASE_V2_FORMAT,
    PreparationContractError,
    PreparedRelease,
    PreparedReleaseIdentity,
    PreparedSession,
    PreparedSessionIdentity,
    TrustedCallEvent,
    parse_public_release_identity,
)
from agent_env_foundry.semantics import (
    AnswerFieldSpec,
    AtomCheckRequest,
    AtomCheckResult,
    BindingCandidate,
    CapabilitySpec,
    CompositionRule,
    ConditionCheckRequest,
    ConditionCheckResult,
    ConditionSpec,
    EvaluationBinding,
    FacetSpec,
    GoalEvaluationContext,
    PublicFieldSource,
    PublicValueSource,
    RenderingSpec,
    SemanticsContractError,
    StartCase,
    TaskSemantics,
    TraceEvent,
    validate_binding,
    validate_bindings,
    validate_catalog,
    validate_start_cases,
)

OBJECT = {"type": "object", "additionalProperties": True}
STRING = {"type": "string"}
DIGEST_A = "a" * 64
DIGEST_B = "b" * 64
DIGEST_C = "c" * 64
DIGEST_D = "d" * 64


def test_non_v2_identity_is_rejected_and_public_projection_cannot_decode_trusted_fields() -> None:
    with pytest.raises(PreparationContractError, match="environment-release/2"):
        PreparedReleaseIdentity("environment-release/unsupported", DIGEST_A, DIGEST_B, DIGEST_C)

    identity = PreparedReleaseIdentity(
        ENVIRONMENT_RELEASE_V2_FORMAT,
        DIGEST_A,
        DIGEST_B,
        DIGEST_C,
    )
    assert identity.public_document() == {
        "format": "environment-release/2",
        "release_id": DIGEST_A,
    }
    assert identity.trusted_document()["actor_digest"] == DIGEST_B
    assert identity.trusted_document()["semantics_digest"] == DIGEST_C
    assert parse_public_release_identity(identity.public_document()).release_id == DIGEST_A
    with pytest.raises(PreparationContractError, match="public release identity"):
        parse_public_release_identity(identity.trusted_document())


def test_prepared_protocols_bind_session_to_exact_release_and_instance() -> None:
    release_hints = get_type_hints(PreparedRelease)
    session_hints = get_type_hints(PreparedSession)
    assert release_hints["identity"] is PreparedReleaseIdentity
    assert session_hints["identity"] is PreparedSessionIdentity
    identity = PreparedSessionIdentity(DIGEST_A, DIGEST_B, DIGEST_C, DIGEST_D)
    assert identity.release_id == DIGEST_A
    assert identity.materialization_id == DIGEST_D


def test_trusted_call_event_records_and_rejects_instance_mutation() -> None:
    identity = PreparedSessionIdentity(DIGEST_A, DIGEST_B, DIGEST_C, DIGEST_D)
    unchanged = TrustedCallEvent(
        seq=1,
        session=identity,
        operation="inspect",
        request_digest=DIGEST_A,
        response_digest=DIGEST_B,
        before_tree_digest=DIGEST_C,
        after_tree_digest=DIGEST_C,
    )
    assert unchanged.unchanged
    assert unchanged.to_document()["operation"] == "inspect"

    changed = TrustedCallEvent(
        seq=2,
        session=identity,
        operation="evaluate_atom",
        request_digest=DIGEST_A,
        response_digest=DIGEST_B,
        before_tree_digest=DIGEST_C,
        after_tree_digest=DIGEST_D,
    )
    assert not changed.unchanged
    with pytest.raises(PreparationContractError, match="operation"):
        TrustedCallEvent(
            seq=3,
            session=identity,
            operation="write_state",  # type: ignore[arg-type]
            request_digest=DIGEST_A,
            response_digest=DIGEST_B,
            before_tree_digest=DIGEST_C,
            after_tree_digest=DIGEST_C,
        )


def test_public_tool_source_binds_tool_and_output_pointer_together() -> None:
    with pytest.raises(SemanticsContractError, match="tool_name"):
        PublicValueSource("tool_output", None, "/reference", None)
    with pytest.raises(SemanticsContractError, match="json_pointer"):
        PublicValueSource("tool_output", "lookup", None, None)
    source = PublicValueSource("tool_output", "lookup", "/reference", None)
    assert source.tool_name == "lookup"
    facet = FacetSpec(
        "reference",
        "reference",
        STRING,
        ("eq",),
    )
    assert facet.to_document()["name"] == "reference"


def test_condition_binding_scope_is_closed() -> None:
    with pytest.raises(SemanticsContractError, match="binding_scope"):
        ConditionSpec(
            "can_finish",
            "can finish",
            "target",  # type: ignore[arg-type]
            ("finish",),
            (),
            None,
            PublicValueSource("reset", None, "/can_finish", None),
        )


def test_composition_and_rendering_use_the_final_plan_contract() -> None:
    rule = CompositionRule("complete-workflow", "workflow", "all", ("a", "b"), 2)
    assert rule.max_occurrences == 2
    with pytest.raises(SemanticsContractError, match="max_occurrences"):
        CompositionRule("bad", "workflow", "all", ("a", "b"), 0)

    answer = AnswerFieldSpec(
        "confirmation",
        STRING,
        "confirmation",
        PublicValueSource("tool_output", "finish_item", "/confirmation", None),
    )
    rendering = RenderingSpec("finish", "item", "report the confirmation")
    assert answer.to_document() == {
        "field_id": "confirmation",
        "schema": STRING,
        "public_label": "confirmation",
        "public_source": {
            "kind": "tool_output",
            "tool_name": "finish_item",
            "json_pointer": "/confirmation",
            "value": None,
        },
    }
    assert rendering.to_document()["imperative"] == "finish"
    assert rendering.to_document()["answer_phrase"] == "report the confirmation"


def test_answer_field_schema_is_strict_structured_output_compatible() -> None:
    source = PublicValueSource("tool_output", "inspect", "/value", None)
    invalid = (
        {"type": "array"},
        {"type": ["array", "null"]},
        {"type": "object", "properties": {}, "additionalProperties": True},
        {
            "type": ["object", "null"],
            "properties": {"value": {"type": "string"}},
            "required": [],
            "additionalProperties": False,
        },
    )
    for schema in invalid:
        with pytest.raises(SemanticsContractError, match="strict structured output"):
            AnswerFieldSpec("value", schema, "value", source)

    valid = AnswerFieldSpec(
        "values",
        {"type": ["array", "null"], "items": {"type": "string"}},
        "values",
        source,
    )
    assert valid.schema["items"] == {"type": "string"}


def _capability(*, capability_id: str = "finish") -> CapabilitySpec:
    return CapabilitySpec(
        capability_id=capability_id,
        requirement_ids=(f"REQ-{capability_id}",),
        workflow_ids=("workflow",),
        composition_rules=(),
        actor_role="user",
        task_kind="state_change",
        intent_label="finish an item",
        protected_binding_schema=OBJECT,
        public_descriptor_schema=OBJECT,
        facets=(
            FacetSpec(
                "name",
                "name",
                STRING,
                ("eq",),
            ),
        ),
        conditions=(),
        answer_fields=(
            AnswerFieldSpec(
                "confirmation",
                STRING,
                "confirmation",
                PublicValueSource("tool_output", "finish_item", "/confirmation", None),
            ),
        ),
        supported_goal_kinds=("atom",),
        rendering=RenderingSpec("finish", "item", "report the confirmation"),
    )


def test_capability_binding_and_start_validation_are_closed() -> None:
    capability = _capability()
    assert validate_catalog((capability,)) == {"finish": capability}
    with pytest.raises(SemanticsContractError, match="duplicate capability"):
        validate_catalog((capability, capability))

    binding = BindingCandidate(
        "item-alpha",
        True,
        (),
        {"native_id": 1},
        {"name": "alpha"},
        {"name": "alpha"},
        (
            PublicFieldSource(
                "/public_descriptor/name",
                PublicValueSource("task_literal", None, None, "alpha"),
            ),
            PublicFieldSource(
                "/facets/name",
                PublicValueSource("task_literal", None, None, "alpha"),
            ),
        ),
    )
    validate_binding(capability, binding)
    validate_bindings(capability, (binding,))
    assert binding.public_document() == {
        "public_descriptor": {"name": "alpha"},
        "facets": {"name": "alpha"},
    }
    with pytest.raises(SemanticsContractError, match="reason_codes"):
        BindingCandidate(
            "item-alpha",
            True,
            ("not_eligible",),
            {"native_id": 1},
            {"name": "alpha"},
            {"name": "alpha"},
            binding.public_sources,
        )
    with pytest.raises(SemanticsContractError, match="task_kind"):
        replace(capability, task_kind="mutation")  # type: ignore[arg-type]
    with pytest.raises(SemanticsContractError, match="supported_goal_kinds"):
        replace(
            capability,
            supported_goal_kinds=("atom", "unknown"),  # type: ignore[arg-type]
        )

    cases = (StartCase("case-1", {"seed": 1}, ("baseline",)),)
    validate_start_cases(
        cases,
        start_schema={
            "type": "object",
            "properties": {"seed": {"type": "integer"}},
            "required": ["seed"],
            "additionalProperties": False,
        },
        limit=1,
    )
    with pytest.raises(SemanticsContractError, match="limit"):
        validate_start_cases(cases, start_schema=OBJECT, limit=0)


def test_query_capability_requires_a_structured_answer_contract() -> None:
    capability = _capability(capability_id="inspect")
    with pytest.raises(SemanticsContractError, match="answer_fields"):
        replace(capability, task_kind="query", answer_fields=())
    with pytest.raises(SemanticsContractError, match="answer_phrase"):
        replace(
            capability,
            task_kind="query",
            rendering=RenderingSpec("inspect", "item", None),
        )


def test_atomic_contract_has_no_scalar_reward_and_task_semantics_is_release_local() -> None:
    trace = (
        TraceEvent(
            1,
            "finish_item",
            {"name": "alpha"},
            {"ok": True, "data": {"confirmation": "ok-alpha"}, "error": None},
        ),
    )
    request = AtomCheckRequest(
        "finish",
        {"done": False},
        {"done": True},
        {"native_id": 1},
        trace,
        {"confirmation": "ok-alpha"},
        GoalEvaluationContext(
            "target",
            (EvaluationBinding("target", "finish", "item-alpha", {"native_id": 1}),),
            None,
            None,
            (),
        ),
    )
    result = AtomCheckResult(False, True, True, True, True, None, {"confirmation": "ok-alpha"}, ())
    assert request.trace_projection == trace
    assert result.satisfied
    assert "reward" not in result.to_document()
    with pytest.raises(SemanticsContractError, match="contradictory"):
        AtomCheckResult(False, True, False, True, True, None, {}, ())

    condition_request = ConditionCheckRequest("can_finish", {"ready": True}, None, ())
    condition_result = ConditionCheckResult("true", {"reason": "ready"}, ())
    assert condition_request.condition_id == "can_finish"
    assert condition_result.status == "true"
    assert "inspect" in TaskSemantics.__dict__
    assert get_type_hints(TaskSemantics.inspect)["instance_directory"] is Path
