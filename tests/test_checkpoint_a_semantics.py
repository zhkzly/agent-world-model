from __future__ import annotations

from dataclasses import replace

import pytest

from agent_env_foundry.semantics import (
    AnswerFieldSpec,
    AtomCheckRequest,
    BindingCandidate,
    CapabilitySpec,
    EvaluationBinding,
    FacetSpec,
    GoalEvaluationContext,
    PublicFieldSource,
    PublicValueSource,
    RenderingSpec,
    SemanticsContractError,
    capability_from_document,
    validate_binding,
    validate_bindings,
)

OBJECT = {"type": "object", "additionalProperties": True}
STRING = {"type": "string"}


def _literal_source(value: object = "alpha") -> PublicValueSource:
    return PublicValueSource("task_literal", None, None, value)  # type: ignore[arg-type]


def _capability() -> CapabilitySpec:
    return CapabilitySpec(
        capability_id="finish",
        requirement_ids=("REQ-001",),
        workflow_ids=("workflow",),
        composition_rules=(),
        actor_role="operator",
        task_kind="state_change",
        intent_label="finish an item",
        protected_binding_schema=OBJECT,
        public_descriptor_schema=OBJECT,
        facets=(FacetSpec("name", "name", STRING, ("eq",)),),
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
        rendering=RenderingSpec("finish", "item", "report confirmation"),
    )


def test_public_value_source_is_one_closed_non_contradictory_encoding() -> None:
    assert PublicValueSource("reset", None, "/items/0/name", None).to_document() == {
        "kind": "reset",
        "tool_name": None,
        "json_pointer": "/items/0/name",
        "value": None,
    }
    assert PublicValueSource("tool_output", "lookup", "/items/0/id", None).tool_name == "lookup"
    with pytest.raises(SemanticsContractError, match="reset.*tool_name"):
        PublicValueSource("reset", "lookup", "/name", None)
    with pytest.raises(SemanticsContractError, match="tool_output.*tool_name"):
        PublicValueSource("tool_output", None, "/name", None)
    literal = PublicValueSource("task_literal", None, None, "alpha")
    assert literal.value == "alpha"
    with pytest.raises(SemanticsContractError, match="task_literal"):
        PublicValueSource("task_literal", None, "/name", "alpha")
    with pytest.raises(SemanticsContractError, match="kind"):
        PublicValueSource("protected", None, None, None)  # type: ignore[arg-type]


def test_binding_requires_an_exact_public_source_for_every_leaf() -> None:
    capability = _capability()
    binding = BindingCandidate(
        semantic_key="item-alpha",
        eligible=True,
        reason_codes=(),
        protected_binding={"native_id": 7},
        public_descriptor={"name": "alpha"},
        facets={"name": "alpha"},
        public_sources=(
            PublicFieldSource("/public_descriptor/name", _literal_source()),
            PublicFieldSource("/facets/name", _literal_source()),
        ),
    )
    validate_binding(capability, binding)
    assert set(binding.to_document()) == {
        "semantic_key",
        "eligible",
        "reason_codes",
        "protected_binding",
        "public_descriptor",
        "facets",
        "public_sources",
    }
    with pytest.raises(SemanticsContractError, match="public_sources.*leaf"):
        replace(binding, public_sources=binding.public_sources[:1])
    with pytest.raises(SemanticsContractError, match="duplicate.*public source"):
        replace(binding, public_sources=(*binding.public_sources, binding.public_sources[0]))
    with pytest.raises(SemanticsContractError, match="task_literal.*value"):
        replace(
            binding,
            public_sources=(
                PublicFieldSource("/public_descriptor/name", _literal_source("beta")),
                binding.public_sources[1],
            ),
        )

    ambiguous = replace(binding, semantic_key="item-beta", protected_binding={"native_id": 8})
    with pytest.raises(SemanticsContractError, match="publicly indistinguishable"):
        validate_bindings(capability, (binding, ambiguous))


def test_goal_evaluation_context_is_exact_and_rejects_unselected_siblings() -> None:
    current = EvaluationBinding("target", "finish", "item-alpha", {"native_id": 7})
    sibling = EvaluationBinding("other", "finish", "item-beta", {"native_id": 8})
    context = GoalEvaluationContext(
        current_slot="target",
        resolved_bindings=(current, sibling),
        composition_rule_id="finish-both",
        foreach_selector_id=None,
        permitted_sibling_slots=("other",),
    )
    request = AtomCheckRequest(
        capability_id="finish",
        before_facts={"done": False},
        after_facts={"done": True},
        protected_binding={"native_id": 7},
        trace_projection=(),
        final_answer=None,
        evaluation_context=context,
    )
    assert request.evaluation_context.current_slot == "target"
    with pytest.raises(SemanticsContractError, match="differs from request binding"):
        replace(request, protected_binding={"native_id": 999})
    with pytest.raises(SemanticsContractError, match="permitted_sibling_slots"):
        replace(context, permitted_sibling_slots=("missing",))
    with pytest.raises(SemanticsContractError, match="mutually exclusive"):
        replace(context, foreach_selector_id="all-items")
    with pytest.raises(SemanticsContractError, match="exactly all selected siblings"):
        replace(context, permitted_sibling_slots=())


def test_old_scope_and_visibility_encodings_are_rejected_not_ignored() -> None:
    document = _capability().to_document()
    document["read_scopes"] = ["items"]
    document["write_scopes"] = ["items"]
    with pytest.raises(SemanticsContractError, match="exactly"):
        capability_from_document(document)

    document = _capability().to_document()
    document["facets"][0]["visibility"] = "task_literal"
    document["facets"][0]["tool_name"] = None
    document["facets"][0]["output_schema_pointer"] = None
    with pytest.raises(SemanticsContractError, match="exactly"):
        capability_from_document(document)
