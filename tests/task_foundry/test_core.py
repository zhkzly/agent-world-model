from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from agent_env_foundry.semantics import (
    AnswerFieldSpec,
    AtomCheckRequest,
    AtomCheckResult,
    BindingCandidate,
    CapabilitySpec,
    CompositionRule,
    ConditionCheckRequest,
    ConditionCheckResult,
    FacetSpec,
    RenderingSpec,
    StartCase,
)
from agent_task_foundry.compiler import CompilationError, compile_definition
from agent_task_foundry.foundry import (
    CorpusPolicy,
    SynthesisPolicy,
    base_challenges,
    enumerate_blueprints,
    fingerprint_task,
    seal_taskpack,
    select_corpus,
)
from agent_task_foundry.models import (
    AllGoal,
    AtomGoal,
    ChallengeResult,
    CheckerMutationResult,
    ReportSpec,
    SelectorPredicate,
    SelectorSpec,
    StartRecipe,
    TaskAssessment,
    TaskBlueprint,
)
from agent_task_foundry.runner import PolicyAction, PolicyFinish, run_public_policy

OBJECT = {"type": "object", "additionalProperties": True}
STRING = {"type": "string"}


class Semantics:
    def __init__(self, capabilities: tuple[CapabilitySpec, ...]) -> None:
        self._capabilities = capabilities

    def start_cases(self, seed: int, limit: int) -> tuple[StartCase, ...]:
        return (StartCase("case-1", {"seed": seed}, ("multi_candidate",)),)[:limit]

    def inspect(self, instance_directory: Path) -> Any:
        return {"done": (instance_directory / "done").exists()}

    def capabilities(self) -> tuple[CapabilitySpec, ...]:
        return self._capabilities

    def enumerate_bindings(
        self,
        capability_id: str,
        facts: Any,
    ) -> tuple[BindingCandidate, ...]:
        return ()

    def evaluate_atom(self, request: AtomCheckRequest) -> AtomCheckResult:
        key = request.protected_binding["key"]
        before = request.before_facts.get("done", {})
        after = request.after_facts.get("done", {})
        initially = before.get(key, False)
        achieved = after.get(key, False)
        answer_values = {"confirmation": f"ok-{key}"} if achieved else {}
        failures = () if achieved else ("not_done",)
        return AtomCheckResult(
            "satisfied" if achieved else "failed",
            initially,
            achieved,
            request.after_facts.get("collateral", True),
            answer_values,
            failures=failures,
        )

    def evaluate_condition(self, request: ConditionCheckRequest) -> ConditionCheckResult:
        return ConditionCheckResult("true")


@dataclass
class Actor:
    state: dict[str, Any]

    def reset(self, start: dict[str, Any] | None = None) -> Any:
        self.state.clear()
        self.state.update({"done": {}, "collateral": True})
        return {"actor": "user"}

    def tools(self) -> tuple[dict[str, Any], ...]:
        return (
            {
                "name": "finish_item",
                "description": "finish an item",
                "input_schema": {
                    "type": "object",
                    "properties": {"name": {"type": "string"}},
                    "required": ["name"],
                    "additionalProperties": False,
                },
                "output_schema": OBJECT,
            },
        )

    def invoke(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self.state["done"][arguments["name"]] = True
        return {
            "ok": True,
            "data": {"confirmation": f"ok-{arguments['name']}"},
            "error": None,
        }

    def close(self) -> None:
        return


def capability(
    *,
    capability_id: str = "finish",
    rules: tuple[CompositionRule, ...] = (),
) -> CapabilitySpec:
    return CapabilitySpec(
        capability_id=capability_id,
        requirement_ids=(f"req-{capability_id}",),
        workflow_ids=("workflow",),
        actor_role="user",
        task_kind="state_change",
        intent_label="finish an item",
        protected_binding_schema=OBJECT,
        public_descriptor_schema=OBJECT,
        facets=(FacetSpec("name", "name", STRING, ("eq",), "task_literal"),),
        composition_rules=rules,
        answer_fields=(AnswerFieldSpec("confirmation", "confirmation", STRING),),
        supported_goal_kinds=("atom", "all", "foreach"),
        rendering=RenderingSpec("item", "items", "finish"),
    )


def binding(key: str) -> BindingCandidate:
    return BindingCandidate(key, True, {"key": key}, {"name": key}, {"name": key})


def compile_one(*, report: bool = True):
    spec = capability()
    semantics = Semantics((spec,))
    selector = SelectorSpec(
        "target",
        "finish",
        (SelectorPredicate("name", "eq", "alpha"),),
    )
    blueprint = TaskBlueprint(
        "release",
        "semantics",
        StartRecipe("release", "case-1", {"seed": 1}),
        (selector,),
        AtomGoal("finish", "target"),
        ReportSpec(("confirmation",)) if report else None,
    )
    before = {"done": {}, "collateral": True}
    definition, checker = compile_definition(
        blueprint=blueprint,
        semantics=semantics,
        before_facts=before,
        bindings_by_capability={"finish": (binding("alpha"),)},
        public_reset_context={"actor": "user"},
        tool_names=("finish_item",),
    )
    return spec, semantics, definition, checker, before


def test_checker_is_frozen_before_witness_and_rejects_noop() -> None:
    _, _, definition, checker, before = compile_one()
    assert checker.evaluate(before, before, (), None).status == "failed"
    assert "finish_item" not in definition.instruction
    assert definition.checker.checker_digest == checker.checker_digest
    assert checker.protected_payload["checker_digest"] == checker.checker_digest


def test_unqualified_all_composition_is_rejected() -> None:
    first = capability(capability_id="a")
    second = capability(capability_id="b")
    semantics = Semantics((first, second))
    first_selector = SelectorSpec(
        "a-one",
        "a",
        (SelectorPredicate("name", "eq", "a"),),
    )
    second_selector = SelectorSpec(
        "b-one",
        "b",
        (SelectorPredicate("name", "eq", "b"),),
    )
    blueprint = TaskBlueprint(
        "release",
        "semantics",
        StartRecipe("release", "case", None),
        (first_selector, second_selector),
        AllGoal(
            (AtomGoal("a", "a-one"), AtomGoal("b", "b-one")),
            "missing",
        ),
    )
    with pytest.raises(CompilationError, match="CompositionRule"):
        compile_definition(
            blueprint=blueprint,
            semantics=semantics,
            before_facts={"done": {}, "collateral": True},
            bindings_by_capability={"a": (binding("a"),), "b": (binding("b"),)},
            public_reset_context={},
        )


def test_two_fresh_public_runs_and_provenance_seal_taskpack() -> None:
    spec, _, definition, checker, before = compile_one()

    def policy(definition, reset, trace):
        if not trace:
            return PolicyAction("finish_item", {"name": "alpha"})
        return PolicyFinish({"confirmation": "ok-alpha"})

    runs = []
    for _ in range(2):
        actor = Actor({})
        run = run_public_policy(
            actor=actor,
            definition=definition,
            checker=checker,
            before_facts=before,
            after_facts=lambda actor=actor: actor.state,
            policy=policy,
            materialization_id=f"episode-{len(runs)}",
        )
        assert run.successful
        assert run.trace[0].provenance.complete
        runs.append(run)
    challenges = base_challenges(
        checker=checker,
        before_facts=before,
        successful_after_facts={"done": {"alpha": True}, "collateral": True},
        successful_trace=(),
        successful_answer={"confirmation": "ok-alpha"},
    )
    pack = seal_taskpack(
        definition=definition,
        checker=checker,
        witnesses=tuple(runs),
        challenges=challenges
        + (
            ChallengeResult("wrong_target", "failed", "failed"),
            ChallengeResult("collateral", "failed", "failed"),
        ),
        checker_mutations=(CheckerMutationResult("drop-goal", True, True, "evidence-drop-goal"),),
    )
    assert pack.taskpack_id
    assert "checker_payload" not in pack.public_projection()
    fingerprint = fingerprint_task(
        taskpack=pack,
        capabilities={"finish": spec},
        start_case=StartCase("case-1", {"seed": 1}, ("multi_candidate",)),
    )
    assessment = TaskAssessment(pack.taskpack_id, "policy-a", 2, 1, 2)
    corpus = select_corpus(
        taskpacks=(pack,),
        fingerprints={pack.taskpack_id: fingerprint},
        assessments={pack.taskpack_id: assessment},
        policy=CorpusPolicy(max_tasks=1),
    )
    assert corpus.taskpack_ids == (pack.taskpack_id,)
    assert assessment.assessment_id not in pack.to_document()


def test_hidden_argument_is_rejected_by_provenance() -> None:
    _, _, definition, checker, before = compile_one(report=False)

    def policy(definition, reset, trace):
        if not trace:
            return PolicyAction("finish_item", {"name": "hidden-native-id"})
        return PolicyFinish(None)

    actor = Actor({})
    run = run_public_policy(
        actor=actor,
        definition=definition,
        checker=checker,
        before_facts=before,
        after_facts=lambda: actor.state,
        policy=policy,
        materialization_id="hidden-episode",
    )
    assert not run.successful
    assert not run.trace[0].provenance.complete


def test_blueprint_enumeration_uses_qualified_structure_not_paraphrases() -> None:
    spec = capability()
    result = enumerate_blueprints(
        release_id="release",
        semantics_digest="semantics",
        start_case=StartCase("case", {"seed": 1}),
        capabilities=(spec,),
        bindings={"finish": (binding("alpha"), binding("beta"))},
        policy=SynthesisPolicy(max_blueprints=20),
    )
    shapes = {blueprint.goal.to_document()["kind"] for blueprint in result}
    assert "atom" in shapes
    assert "foreach" in shapes
    assert len({blueprint.blueprint_id for blueprint in result}) == len(result)


def test_task_identity_excludes_model_assessment() -> None:
    _, _, definition, _, _ = compile_one()
    first = TaskAssessment("pack", "model-a", 3, 1, 7)
    second = TaskAssessment("pack", "model-b", 3, 2, 8)
    assert first.assessment_id != second.assessment_id
    assert definition.task_definition_id == definition.task_definition_id


def test_no_argument_tool_has_vacuously_complete_provenance() -> None:
    from agent_task_foundry.runner import trace_argument_provenance

    report = trace_argument_provenance(
        arguments={},
        instruction_literals=(),
        reset_context={},
        tool_spec={"input_schema": {"type": "object", "properties": {}}},
        prior_trace=(),
    )
    assert report.complete
