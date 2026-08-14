from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

import pytest

from agent_world import candidate as candidate_module
from agent_world.contracts import (
    ArtifactRef,
    EffectDraft,
    EntityDeclaration,
    FieldDeclaration,
    PredicateDraft,
    RuleDraft,
    SemanticBinding,
    SemanticCatalog,
    ToolCouplingPlan,
    ToolDraft,
    ToolSurface,
    WorldArchitecture,
    WorldBoundary,
    digest_value,
)
from agent_world.design import (
    DesignError,
    _catalog,
    _reset_default,
    _reset_value_map,
    _reject_transition_degeneracy,
    _task_semantic_fields,
    _verify_family_outcome,
    _verify_initial_rules,
)


def _digest() -> str:
    return "sha256:" + "a" * 64


def _field(name: str, category: str, values: tuple[str, ...] = ()) -> FieldDeclaration:
    return FieldDeclaration(name, cast(Any, category), False, values)


def _tool(index: int, name: str) -> ToolSurface:
    return ToolSurface(
        index,
        name,
        "purpose",
        (1,),
        (_field("q_" + str(index), "identifier"),),
        (_field("status_" + str(index), "text"),),
    )


def _architecture(tools: tuple[ToolSurface, ...]) -> WorldArchitecture:
    boundary = WorldBoundary("desk", "run it", "system", "owner", ("clerk",))
    entities = (EntityDeclaration("entity_one", "state", (_field("state_field", "text"),)),)
    groups = () if len(tools) == 1 else (tuple(range(1, len(tools) + 1)),)
    bindings = _catalog(cast(Any, SimpleNamespace(tools=tools)))
    return WorldArchitecture(
        boundary,
        entities,
        tools,
        (),
        SemanticCatalog(bindings),
        ToolCouplingPlan(groups),
        ArtifactRef("arch-1", "design.world_architecture", _digest(), "x.json"),
    )


def _draft(tool_index: int, surface: ToolSurface) -> ToolDraft:
    bindings = tuple(
        binding
        for binding in _architecture((surface,)).catalog.bindings
        if binding.path[1] == str(tool_index)
    )
    return ToolDraft(
        tool_index,
        surface,
        bindings,
        (),
        (),
        (),
        (),
        None,
        digest_value({"local": tool_index}),
    )


def _rule(
    when: tuple[PredicateDraft, ...],
    effects: tuple[EffectDraft, ...],
) -> RuleDraft:
    return RuleDraft(when, effects, None, "bounded rule", ())


def _scaffold_default(category: str, values: tuple[str, ...]) -> object:
    namespace: dict[str, Any] = {}
    exec(candidate_module._DESIGN_RUNTIME_BODY.split("def _init")[0], namespace)
    return namespace["_default"](category, values)


def test_reset_default_parity_with_scaffold() -> None:
    cases = (
        ("boolean", (), False),
        ("integer", (), 0),
        ("number", (), 0.0),
        ("list", (), []),
        ("enum", ("a", "b"), "a"),
        ("timestamp", (), "1970-01-01T00:00:00Z"),
        ("text", (), ""),
        ("identifier", (), ""),
    )
    for category, values, expected in cases:
        assert _reset_default(category, values) == expected
        assert _scaffold_default(category, values) == expected


def test_reset_value_map_and_task_field_disclosure() -> None:
    tool = _tool(1, "alpha")
    arch = _architecture((tool,))
    reset = _reset_value_map(arch)
    for binding in arch.catalog.bindings:
        assert reset[binding.index] == _reset_default("text", ()) if binding.name.startswith(
            "status"
        ) else reset[binding.index] == _reset_default("identifier", ())
    rows = _task_semantic_fields(arch)
    reset_rows = [row for row in rows if row["source"] == "reset_state"]
    assert reset_rows
    for row in reset_rows:
        assert row["reset_value"] == ""
    argument_rows = [row for row in rows if row["source"] == "argument"]
    assert all("reset_value" not in row for row in argument_rows)


def test_verify_initial_rules_rejects_when_and_wrong_values() -> None:
    text_effect = EffectDraft(9, "set", "ok")
    matching = _rule((), (EffectDraft(9, "set", ""),))
    expected = {9: ""}
    assert _verify_initial_rules((matching,), expected) is None
    assert _verify_initial_rules((), expected) is None
    wrong_value = _verify_initial_rules((_rule((), (text_effect,)),), expected)
    assert wrong_value is not None and "reset value" in wrong_value
    with_when = _verify_initial_rules(
        (_rule((PredicateDraft(9, "exists", None),), ()),), expected
    )
    assert with_when is not None and "when must be []" in with_when


def test_reject_transition_degeneracy_duplicate_when() -> None:
    surface = _tool(1, "alpha")
    draft = _draft(1, surface)
    status_index = next(
        binding.index
        for binding in draft.bindings
        if binding.source == "pre_state" and binding.name == "status_1"
    )
    q_index = next(
        binding.index for binding in draft.bindings if binding.name == "q_1"
    )
    duplicate = (
        _rule((), (EffectDraft(status_index, "set", "ok"),)),
        _rule((), (EffectDraft(status_index, "set", "later"),)),
    )
    with pytest.raises(DesignError, match="tool_semantics_invalid") as raised:
        _reject_transition_degeneracy(duplicate, draft.bindings, surface)
    assert "identical when" in raised.value.correction.violated_condition
    # when on a state field no transition changes
    immutable = (
        _rule(
            (PredicateDraft(status_index, "eq", "pending"),),
            (EffectDraft(q_index, "set", "x"),),
        ),
    )
    with pytest.raises(DesignError, match="tool_semantics_invalid") as raised:
        _reject_transition_degeneracy(immutable, draft.bindings, surface)
    assert "no transition ever changes" in raised.value.correction.violated_condition
    # effect on an argument field
    argument_effect = (
        _rule((), (EffectDraft(q_index, "set", "x"),)),
    )
    with pytest.raises(DesignError, match="tool_semantics_invalid") as raised:
        _reject_transition_degeneracy(argument_effect, draft.bindings, surface)
    assert "argument field" in raised.value.correction.violated_condition
    # a valid conditional transition passes
    valid = (
        _rule(
            (PredicateDraft(q_index, "exists", None),),
            (EffectDraft(status_index, "set", "ok"),),
        ),
    )
    _reject_transition_degeneracy(valid, draft.bindings, surface)


def _simulation_fixture() -> tuple[WorldArchitecture, ToolDraft]:
    surface = _tool(1, "alpha")
    arch = _architecture((surface,))
    bindings = tuple(
        binding
        for binding in arch.catalog.bindings
        if binding.path[1] == "1"
    )
    status_index = next(
        binding.index
        for binding in bindings
        if binding.source == "pre_state" and binding.name == "status_1"
    )
    draft = ToolDraft(
        1,
        surface,
        bindings,
        (),
        (_rule((), (EffectDraft(status_index, "set", "ok"),)),),
        (),
        (),
        None,
        digest_value({"local": 1}),
    )
    return arch, draft


def _success_rule(arch: WorldArchitecture, operator: str, value: object) -> RuleDraft:
    index = next(
        binding.index
        for binding in arch.catalog.bindings
        if binding.source == "post_state" and binding.name == "status_1"
    )
    return _rule((PredicateDraft(index, operator, value),), ())


def test_family_outcome_gate_accepts_reachable_and_rejects_unreachable() -> None:
    arch, draft = _simulation_fixture()
    success = _success_rule(arch, "eq", "ok")
    assert (
        _verify_family_outcome((1,), (draft,), arch, (success,), ()) is None
    )
    unreachable = _verify_family_outcome(
        (1,), (draft,), arch, (_success_rule(arch, "eq", "ready"),), ()
    )
    assert unreachable is not None and "no success" in unreachable
    failure_holds = _verify_family_outcome(
        (1,), (draft,), arch, (success,), (success,)
    )
    assert failure_holds is not None and "failure pattern holds" in failure_holds
    rejected = _verify_family_outcome(
        (1,),
        (ToolDraft(
            1,
            draft.surface,
            draft.bindings,
            (),
            (_rule((), (EffectDraft(
                next(
                    binding.index
                    for binding in draft.bindings
                    if binding.source == "pre_state" and binding.name == "status_1"
                ),
                "reject",
                None,
            ),)),),
            (),
            (),
            None,
            digest_value({"local": 2}),
        ),),
        arch,
        (success,),
        (),
    )
    assert rejected is not None and "reject effect" in rejected
