from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import cast

import pytest

from agent_env_foundry.semantics import (
    AnswerFieldSpec,
    AtomCheckRequest,
    AtomCheckResult,
    BindingCandidate,
    CapabilitySpec,
    ConditionCheckRequest,
    ConditionCheckResult,
    ConditionSpec,
    FacetSpec,
    RenderingSpec,
    StartCase,
)
from agent_task_foundry.compiler import CompilationError, compile_definition
from agent_task_foundry.models import (
    AtomGoal,
    GoalProgram,
    IfGoal,
    SelectorPredicate,
    SelectorSpec,
    StartRecipe,
    TaskBlueprint,
)

OBJECT = {"type": "object", "additionalProperties": True}
STRING = {"type": "string"}


class Semantics:
    def start_cases(self, seed: int, limit: int) -> tuple[StartCase, ...]:
        return (StartCase("case", None),)[:limit]

    def inspect(self, instance_directory: Path):
        return {}

    def capabilities(self) -> tuple[CapabilitySpec, ...]:
        return (capability(),)

    def enumerate_bindings(self, capability_id: str, facts):
        return (binding(),)

    def evaluate_atom(self, request: AtomCheckRequest) -> AtomCheckResult:
        done = isinstance(request.after_facts, dict) and request.after_facts.get("done") is True
        return AtomCheckResult(
            "satisfied" if done else "failed",
            False,
            done,
            True,
            failures=() if done else ("not_done",),
        )

    def evaluate_condition(self, request: ConditionCheckRequest) -> ConditionCheckResult:
        return ConditionCheckResult("true")


def capability() -> CapabilitySpec:
    reason = AnswerFieldSpec("reason", "the reason", STRING)
    condition = ConditionSpec(
        "can_finish",
        "the selected item can be finished",
        "reset",
        binding_scope="selected_binding",
        true_capability_ids=("finish",),
        report_field=reason,
    )
    return CapabilitySpec(
        "finish",
        ("R1",),
        ("workflow",),
        "user",
        "state_change",
        "finish an item",
        OBJECT,
        OBJECT,
        (FacetSpec("name", "name", STRING, ("eq",), "task_literal"),),
        conditions=(condition,),
        supported_goal_kinds=("atom", "if"),
        rendering=RenderingSpec("item", "items", "finish"),
    )


def binding() -> BindingCandidate:
    return BindingCandidate(
        "alpha",
        True,
        {"id": "native-alpha"},
        {"name": "alpha"},
        {"name": "alpha"},
    )


def base_blueprint(goal: GoalProgram) -> TaskBlueprint:
    selector = SelectorSpec(
        "target",
        "finish",
        (SelectorPredicate("name", "eq", "alpha"),),
    )
    return TaskBlueprint(
        "release",
        "semantics",
        StartRecipe("release", "case", None),
        (selector,),
        goal,
    )


def test_if_goal_accepts_qualified_goal_less_else_branch() -> None:
    blueprint = base_blueprint(
        IfGoal(
            "can_finish",
            "target",
            AtomGoal("finish", "target"),
            None,
        )
    )
    definition, _ = compile_definition(
        blueprint=blueprint,
        semantics=Semantics(),
        before_facts={},
        bindings_by_capability={"finish": (binding(),)},
        public_reset_context={},
    )
    assert "otherwise, report the reason" in definition.instruction


@dataclass(frozen=True)
class UnknownGoal:
    def to_document(self):
        return {"kind": "unknown"}


def test_unknown_goal_variant_is_rejected_deterministically() -> None:
    blueprint = base_blueprint(cast(GoalProgram, UnknownGoal()))
    with pytest.raises(CompilationError, match="unsupported goal type UnknownGoal"):
        compile_definition(
            blueprint=blueprint,
            semantics=Semantics(),
            before_facts={},
            bindings_by_capability={"finish": (binding(),)},
            public_reset_context={},
        )
