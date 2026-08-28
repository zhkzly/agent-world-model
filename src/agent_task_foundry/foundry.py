"""Blueprint enumeration, admission and model-independent corpus selection."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from agent_env_foundry.semantics import (
    BindingCandidate,
    CapabilitySpec,
    CompositionRule,
    JSONValue,
    StartCase,
    TaskSemantics,
    TraceEvent,
)
from agent_task_foundry.compiler import CompiledTaskChecker, compile_definition
from agent_task_foundry.facets import (
    ExtremeDirection,
    FacetValueError,
    compare_facet_values,
    extreme_facet_value,
)
from agent_task_foundry.models import (
    AdmissionReport,
    AllGoal,
    AtomGoal,
    ChallengeResult,
    CheckerMutationResult,
    CorpusManifest,
    ForEachGoal,
    IfGoal,
    RankSpec,
    ReportSpec,
    SelectorPredicate,
    SelectorSpec,
    StartRecipe,
    TaskAssessment,
    TaskBlueprint,
    TaskDefinition,
    TaskFingerprint,
    TaskPack,
    WitnessRun,
    digest_document,
    goal_capability_ids,
    goal_shape,
)


class SynthesisError(ValueError):
    """The requested Task/corpus cannot pass the Good Task contract."""


@dataclass(frozen=True, slots=True)
class SynthesisPolicy:
    max_blueprints: int = 100
    include_foreach: bool = True
    include_compositions: bool = True
    include_conditionals: bool = True
    include_reports: bool = True

    def __post_init__(self) -> None:
        if self.max_blueprints <= 0:
            raise ValueError("max_blueprints must be positive")


@dataclass(frozen=True, slots=True)
class CompiledCandidate:
    definition: TaskDefinition
    checker: CompiledTaskChecker


@dataclass(frozen=True, slots=True)
class RejectedBlueprint:
    blueprint_id: str
    reason: str


@dataclass(frozen=True, slots=True)
class CompilationBatch:
    accepted: tuple[CompiledCandidate, ...]
    rejected: tuple[RejectedBlueprint, ...]


@dataclass(frozen=True, slots=True)
class CorpusPolicy:
    max_tasks: int
    max_per_fingerprint: int = 1
    require_assessment: bool = True
    min_success_rate: float = 0.0
    max_success_rate: float = 1.0

    def __post_init__(self) -> None:
        if self.max_tasks <= 0 or self.max_per_fingerprint <= 0:
            raise ValueError("corpus limits must be positive")
        if not 0.0 <= self.min_success_rate <= self.max_success_rate <= 1.0:
            raise ValueError("invalid success-rate interval")

    @property
    def policy_digest(self) -> str:
        return digest_document(
            {
                "max_tasks": self.max_tasks,
                "max_per_fingerprint": self.max_per_fingerprint,
                "require_assessment": self.require_assessment,
                "min_success_rate": self.min_success_rate,
                "max_success_rate": self.max_success_rate,
            }
        )


def enumerate_blueprints(
    *,
    release_id: str,
    semantics_digest: str,
    start_case: StartCase,
    capabilities: tuple[CapabilitySpec, ...],
    bindings: Mapping[str, tuple[BindingCandidate, ...]],
    policy: SynthesisPolicy | None = None,
) -> tuple[TaskBlueprint, ...]:
    """Enumerate bounded candidates only from qualified release-local semantics."""

    selected = policy or SynthesisPolicy()
    atoms: dict[str, list[tuple[SelectorSpec, AtomGoal]]] = {}
    blueprints: list[TaskBlueprint] = []
    start = StartRecipe(release_id, start_case.case_id, start_case.reset_input)

    for capability in sorted(capabilities, key=lambda item: item.capability_id):
        candidates = tuple(
            value for value in bindings.get(capability.capability_id, ()) if value.eligible
        )
        atom_entries: list[tuple[SelectorSpec, AtomGoal]] = []
        for candidate in sorted(candidates, key=lambda item: item.semantic_key):
            selector = _unique_selector(capability, candidate, candidates)
            if selector is None:
                continue
            atom = AtomGoal(capability.capability_id, selector.selector_id)
            atom_entries.append((selector, atom))
            reports: list[ReportSpec | None] = [None]
            if selected.include_reports and capability.answer_fields:
                reports.append(ReportSpec(tuple(field.name for field in capability.answer_fields)))
            for report in reports:
                blueprints.append(
                    TaskBlueprint(release_id, semantics_digest, start, (selector,), atom, report)
                )
        if selected.include_foreach and "foreach" in capability.supported_goal_kinds and candidates:
            selector = _all_selector(capability)
            goal = ForEachGoal(
                selector.selector_id,
                AtomGoal(capability.capability_id, selector.selector_id),
            )
            blueprints.append(TaskBlueprint(release_id, semantics_digest, start, (selector,), goal))
        atoms[capability.capability_id] = atom_entries

    if selected.include_compositions:
        for rule in sorted(_rules(capabilities).values(), key=lambda item: item.rule_id):
            child_options = [atoms.get(capability_id, []) for capability_id in rule.capability_ids]
            if any(not options for options in child_options):
                continue
            children = tuple(options[0][1] for options in child_options)
            rule_selectors = tuple(options[0][0] for options in child_options)
            blueprints.append(
                TaskBlueprint(
                    release_id,
                    semantics_digest,
                    start,
                    rule_selectors,
                    AllGoal(children, rule.rule_id),
                )
            )

    if selected.include_conditionals:
        for capability in sorted(capabilities, key=lambda item: item.capability_id):
            for condition in capability.conditions:
                selector_id: str | None = None
                condition_selectors: tuple[SelectorSpec, ...] = ()
                if condition.binding_scope == "selected_binding" and atoms.get(
                    capability.capability_id
                ):
                    condition_selectors = (atoms[capability.capability_id][0][0],)
                    selector_id = condition_selectors[0].selector_id
                then_goal = _first_atom(condition.true_capability_ids, atoms)
                else_goal = _first_atom(condition.false_capability_ids, atoms)
                if then_goal is None and else_goal is None:
                    continue
                report = (
                    ReportSpec((condition.report_field.name,)) if condition.report_field else None
                )
                blueprints.append(
                    TaskBlueprint(
                        release_id,
                        semantics_digest,
                        start,
                        condition_selectors,
                        IfGoal(condition.condition_id, selector_id, then_goal, else_goal),
                        report,
                    )
                )

    unique = {blueprint.blueprint_id: blueprint for blueprint in blueprints}
    return tuple(unique[key] for key in sorted(unique)[: selected.max_blueprints])


def compile_candidates(
    *,
    blueprints: tuple[TaskBlueprint, ...],
    semantics: TaskSemantics,
    before_facts: JSONValue,
    bindings: Mapping[str, tuple[BindingCandidate, ...]],
    public_reset_context: JSONValue,
    tool_names: tuple[str, ...],
) -> CompilationBatch:
    accepted: list[CompiledCandidate] = []
    rejected: list[RejectedBlueprint] = []
    for blueprint in blueprints:
        try:
            definition, checker = compile_definition(
                blueprint=blueprint,
                semantics=semantics,
                before_facts=before_facts,
                bindings_by_capability=bindings,
                public_reset_context=public_reset_context,
                tool_names=tool_names,
            )
        except ValueError as exc:
            rejected.append(RejectedBlueprint(blueprint.blueprint_id, str(exc)))
            continue
        accepted.append(CompiledCandidate(definition, checker))
    return CompilationBatch(tuple(accepted), tuple(rejected))


def base_challenges(
    *,
    checker: CompiledTaskChecker,
    before_facts: JSONValue,
    successful_after_facts: JSONValue,
    successful_trace: tuple[TraceEvent, ...],
    successful_answer: JSONValue,
) -> tuple[ChallengeResult, ...]:
    no_op = checker.evaluate(before_facts, before_facts, (), None)
    positive = checker.evaluate(
        before_facts,
        successful_after_facts,
        successful_trace,
        successful_answer,
    )
    challenges = [
        ChallengeResult("positive", "satisfied", positive.status),
        ChallengeResult("no_op", "failed", no_op.status),
    ]
    if checker.blueprint.report is not None:
        wrong = checker.evaluate(before_facts, successful_after_facts, successful_trace, {})
        challenges.append(ChallengeResult("wrong_answer", "failed", wrong.status))
    return tuple(challenges)


def seal_taskpack(
    *,
    definition: TaskDefinition,
    checker: CompiledTaskChecker,
    witnesses: tuple[WitnessRun, ...],
    challenges: tuple[ChallengeResult, ...],
    checker_mutations: tuple[CheckerMutationResult, ...],
) -> TaskPack:
    successful = tuple(run for run in witnesses if run.successful)
    if len(successful) < 2:
        raise SynthesisError("Task needs two fresh public-only successful executions")
    if len({run.materialization_id for run in successful}) < 2:
        raise SynthesisError("successful witnesses must use distinct fresh materializations")
    required = _required_challenges(definition)
    present = {challenge.challenge_id for challenge in challenges if challenge.reachable}
    missing = required - present
    if missing:
        raise SynthesisError(f"missing required challenge categories: {sorted(missing)}")
    report = AdmissionReport(
        tuple(run.evidence_digest for run in successful),
        challenges,
        checker_mutations,
    )
    if not report.accepted:
        raise SynthesisError("Task failed challenge or checker-mutation admission")
    return TaskPack(definition, checker.protected_payload, successful, report)


def _required_challenges(definition: TaskDefinition) -> set[str]:
    required = {"positive", "no_op", "wrong_target", "collateral"}
    goal = definition.blueprint.goal
    if isinstance(goal, (AllGoal, ForEachGoal)):
        required.add("partial")
    if isinstance(goal, IfGoal):
        required.add("wrong_branch")
    if definition.blueprint.report is not None:
        required.add("wrong_answer")
    return required


def fingerprint_task(
    *,
    taskpack: TaskPack,
    capabilities: Mapping[str, CapabilitySpec],
    start_case: StartCase,
) -> TaskFingerprint:
    goal = taskpack.definition.blueprint.goal
    capability_ids = goal_capability_ids(goal)
    workflows = tuple(
        sorted(
            {
                workflow
                for capability_id in capability_ids
                for workflow in capabilities[capability_id].workflow_ids
            }
        )
    )
    operators = tuple(
        sorted(
            {
                predicate.operator
                for selector in taskpack.definition.blueprint.selectors
                for predicate in selector.filters
            }
            | {
                selector.rank.direction
                for selector in taskpack.definition.blueprint.selectors
                if selector.rank is not None
            }
        )
    )
    return TaskFingerprint(
        capability_ids,
        workflows,
        goal_shape(goal),
        operators,
        tuple(sorted(start_case.regime_tags)),
        taskpack.definition.blueprint.report is not None,
    )


def select_corpus(
    *,
    taskpacks: tuple[TaskPack, ...],
    fingerprints: Mapping[str, TaskFingerprint],
    assessments: Mapping[str, TaskAssessment],
    policy: CorpusPolicy,
) -> CorpusManifest:
    selected: list[str] = []
    assessment_ids: list[str] = []
    counts: dict[str, int] = {}
    rejected: dict[str, JSONValue] = {}
    for taskpack in sorted(taskpacks, key=lambda item: item.taskpack_id):
        taskpack_id = taskpack.taskpack_id
        fingerprint = fingerprints[taskpack_id]
        assessment = assessments.get(taskpack_id)
        if policy.require_assessment and assessment is None:
            rejected[taskpack_id] = "assessment_missing"
            continue
        if assessment is not None and not (
            policy.min_success_rate <= assessment.success_rate <= policy.max_success_rate
        ):
            rejected[taskpack_id] = "assessment_outside_policy"
            continue
        count = counts.get(fingerprint.fingerprint_id, 0)
        if count >= policy.max_per_fingerprint:
            rejected[taskpack_id] = "fingerprint_budget"
            continue
        selected.append(taskpack_id)
        counts[fingerprint.fingerprint_id] = count + 1
        if assessment is not None:
            assessment_ids.append(assessment.assessment_id)
        if len(selected) >= policy.max_tasks:
            break
    return CorpusManifest(
        policy.policy_digest,
        tuple(selected),
        tuple(assessment_ids),
        rejected,
    )


def _unique_selector(
    capability: CapabilitySpec,
    candidate: BindingCandidate,
    candidates: tuple[BindingCandidate, ...],
) -> SelectorSpec | None:
    for facet in capability.facets:
        if facet.visibility != "task_literal" or "eq" not in facet.allowed_operators:
            continue
        value = candidate.facets.get(facet.name)
        if value is None:
            continue
        matches = [item for item in candidates if item.facets.get(facet.name) == value]
        if len(matches) == 1:
            selector_id = (
                f"{capability.capability_id}:{facet.name}:eq:{digest_document(value)[:12]}"
            )
            return SelectorSpec(
                selector_id,
                capability.capability_id,
                (SelectorPredicate(facet.name, "eq", value),),
            )
    directions: tuple[ExtremeDirection, ...] = ("max", "min")
    for facet in capability.facets:
        if "max" not in facet.allowed_operators and "min" not in facet.allowed_operators:
            continue
        values = [item.facets.get(facet.name) for item in candidates]
        for direction in directions:
            if direction not in facet.allowed_operators:
                continue
            try:
                target = extreme_facet_value(values, direction)
            except FacetValueError as exc:
                raise SynthesisError(
                    f"qualified rank facet {facet.name!r} is not comparable: {exc}"
                ) from exc
            matches = [
                item
                for item in candidates
                if compare_facet_values(item.facets.get(facet.name), "eq", target)
            ]
            if len(matches) == 1 and matches[0] == candidate:
                return SelectorSpec(
                    f"{capability.capability_id}:{facet.name}:{direction}",
                    capability.capability_id,
                    rank=RankSpec(facet.name, direction),
                )
    return None


def _all_selector(capability: CapabilitySpec) -> SelectorSpec:
    return SelectorSpec(
        f"{capability.capability_id}:all",
        capability.capability_id,
        cardinality="all",
    )


def _rules(capabilities: tuple[CapabilitySpec, ...]) -> dict[str, CompositionRule]:
    rules: dict[str, CompositionRule] = {}
    for capability in capabilities:
        for rule in capability.composition_rules:
            rules[rule.rule_id] = rule
    return rules


def _first_atom(
    capability_ids: tuple[str, ...],
    atoms: Mapping[str, list[tuple[SelectorSpec, AtomGoal]]],
) -> AtomGoal | None:
    for capability_id in capability_ids:
        if atoms.get(capability_id):
            return atoms[capability_id][0][1]
    return None
