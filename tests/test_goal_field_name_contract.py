from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

from agent_world.contracts import (
    ArtifactRef,
    CorrectionPacket,
    EntityDeclaration,
    FieldDeclaration,
    SemanticCatalog,
    ToolCouplingPlan,
    ToolSurface,
    WorldArchitecture,
    WorldBoundary,
)
from agent_world.design import (
    _catalog,
    _catalog_categories,
    _goal_field_correction,
    _goal_name_lookup,
    _object_violation,
)


def _digest() -> str:
    return "sha256:" + "a" * 64


def _field(name: str, category: str, values: tuple[str, ...] = ()) -> FieldDeclaration:
    return FieldDeclaration(name, cast(Any, category), False, values)


def _tool(
    index: int,
    name: str,
    args: tuple[FieldDeclaration, ...],
    results: tuple[FieldDeclaration, ...],
) -> ToolSurface:
    return ToolSurface(index, name, "purpose", (1,), args, results)


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


def test_goal_name_lookup_qualified_tier_preference() -> None:
    tool = _tool(
        1,
        "alpha",
        (_field("status", "text"), _field("query", "text")),
        (_field("status", "enum", ("a", "b")), _field("report", "text")),
    )
    arch = _architecture((tool,))
    lookup = _goal_name_lookup(arch)
    # post_state beats tool_result / argument / pre_state / reset_state.
    assert lookup["alpha.status"] == 7
    assert lookup["alpha.report"] == 8
    # argument-only name resolves to its single binding.
    assert lookup["alpha.query"] == 2
    # bare names are accepted only when globally unambiguous.
    assert lookup["query"] == 2
    assert "status" not in lookup
    assert "report" not in lookup


def test_goal_name_lookup_family_restriction() -> None:
    alpha = _tool(1, "alpha", (_field("q", "text"),), (_field("r", "text"),))
    beta = _tool(2, "beta", (_field("s", "text"),), (_field("t", "text"),))
    arch = _architecture((alpha, beta))
    full = _goal_name_lookup(arch)
    family = _goal_name_lookup(arch, (2,))
    assert "beta.t" in family
    assert "beta.s" in family
    assert "alpha.r" not in family
    assert "alpha.r" in full


def test_goal_field_correction_budget_and_content() -> None:
    alpha = _tool(1, "alpha", (_field("q", "text"),), (_field("r", "text"),))
    arch = _architecture((alpha,))
    lookup = _goal_name_lookup(arch, (1,))
    text = _goal_field_correction("alpha.r", lookup)
    assert 0 < len(text) <= 280
    assert "alpha.r" in text
    assert "valid names:" in text
    huge = {("tool_" + str(i) + ".field_name_" + "x" * 40): i for i in range(30)}
    big = _goal_field_correction("x" * 300, huge)
    assert 0 < len(big) <= 280
    CorrectionPacket(
        "task_requirement_invalid", "$.public_goal_fields[0]", big, "string"
    )


def test_object_violation_names_offenders_and_stays_bounded() -> None:
    text = _object_violation({"a": 1, "junk": 2, "noise": 3}, {"a", "b"})
    assert "extra keys: junk, noise" in text
    assert "missing keys: b" in text
    worst = {("key_" + str(i)): i for i in range(40)}
    big = _object_violation(worst, {"z0", "z1", "z2", "z3", "z4"})
    assert 0 < len(big) <= 280
    CorrectionPacket("task_requirement_invalid", "$", big, "object")


def test_goal_correction_hint_lists_only_resolvable_names() -> None:
    alpha = _tool(1, "alpha", (_field("q", "text"),), (_field("r", "text"),))
    beta = _tool(2, "beta", (_field("q", "text"),), (_field("s", "text"),))
    arch = _architecture((alpha, beta))
    lookup = _goal_name_lookup(arch)
    text = _goal_field_correction("q", lookup, "the bare name is declared on alpha and beta; write tool.field")
    assert 0 < len(text) <= 280
    # The bare ambiguous name must never appear as a suggested valid name.
    valid_part = text.split("; valid names: ", 1)
    assert len(valid_part) == 2
    names = [name.strip() for name in valid_part[1].split(",")]
    assert "q" not in names
    assert "alpha.q" in names and "beta.q" in names
    CorrectionPacket("task_requirement_invalid", "$.public_goal_fields[0]", text, "string")


def test_goal_tier_category_follows_resolved_index() -> None:
    tool = _tool(
        1,
        "alpha",
        (_field("status", "text"),),
        (_field("status", "enum", ("a", "b")), _field("report", "text")),
    )
    arch = _architecture((tool,))
    categories = _catalog_categories(arch)
    lookup = _goal_name_lookup(arch)
    # The qualified name resolves to the post_state row; the goal leaf's
    # category is the chosen tier's projected category (enum), never the
    # argument column's (text).
    assert categories[lookup["alpha.status"] - 1] == "enum"
    assert categories[lookup["alpha.report"] - 1] == "text"
