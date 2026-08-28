"""Deterministic Goal compilation, checking, and canonical instruction rendering."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from agent_env_foundry.semantics import (
    AnswerFieldSpec,
    AtomCheckRequest,
    BindingCandidate,
    CapabilitySpec,
    CheckStatus,
    CompositionRule,
    ConditionCheckRequest,
    ConditionSpec,
    FacetSpec,
    JSONObject,
    JSONValue,
    TaskSemantics,
    TraceEvent,
    validate_binding,
    validate_catalog,
)
from agent_task_foundry.facets import (
    FacetValueError,
    compare_facet_values,
    extreme_facet_value,
)
from agent_task_foundry.models import (
    AllGoal,
    AtomGoal,
    CheckerArtifact,
    ForEachGoal,
    GoalProgram,
    IfGoal,
    InstructionAudit,
    RankSpec,
    ReportSpec,
    ResolvedSelector,
    SelectorSpec,
    TaskBlueprint,
    TaskDefinition,
    digest_document,
    goal_capability_ids,
)


class CompilationError(ValueError):
    """A Blueprint cannot be compiled without changing its semantics."""


@dataclass(frozen=True, slots=True)
class TaskCheckResult:
    status: CheckStatus
    failures: tuple[str, ...]
    expected_answer: JSONObject


@dataclass(frozen=True, slots=True)
class _GoalResult:
    status: CheckStatus
    failures: tuple[str, ...]
    answer_values: JSONObject


class SemanticsCatalog:
    """Validated index over one exact release-local TaskSemantics surface."""

    def __init__(self, semantics: TaskSemantics) -> None:
        self.semantics = semantics
        self.capabilities = validate_catalog(semantics.capabilities())
        self.conditions: dict[str, tuple[CapabilitySpec, ConditionSpec]] = {}
        self.rules: dict[str, CompositionRule] = {}
        for capability in self.capabilities.values():
            for condition in capability.conditions:
                if condition.condition_id in self.conditions:
                    raise CompilationError(f"duplicate condition {condition.condition_id!r}")
                self.conditions[condition.condition_id] = (capability, condition)
            for rule in capability.composition_rules:
                previous = self.rules.setdefault(rule.rule_id, rule)
                if previous != rule:
                    raise CompilationError(f"inconsistent composition rule {rule.rule_id!r}")

    def capability(self, capability_id: str) -> CapabilitySpec:
        try:
            return self.capabilities[capability_id]
        except KeyError as exc:
            raise CompilationError(f"unknown capability {capability_id!r}") from exc


@dataclass(frozen=True, slots=True)
class CompiledTaskChecker:
    blueprint: TaskBlueprint
    resolved: Mapping[str, tuple[str, ...]]
    bindings: Mapping[str, BindingCandidate]
    catalog: SemanticsCatalog

    @property
    def checker_digest(self) -> str:
        return digest_document(self._payload(include_digest=False))

    @property
    def protected_payload(self) -> JSONObject:
        return self._payload(include_digest=True)

    def _payload(self, *, include_digest: bool) -> JSONObject:
        document: JSONObject = {
            "blueprint": self.blueprint.to_document(),
            "resolved": {key: list(value) for key, value in sorted(self.resolved.items())},
            "bindings": {
                key: {
                    "protected": binding.protected_binding,
                    "public": binding.public_descriptor,
                    "facets": binding.facets,
                }
                for key, binding in sorted(self.bindings.items())
            },
        }
        if include_digest:
            document["checker_digest"] = self.checker_digest
        return document

    def evaluate(
        self,
        before_facts: JSONValue,
        after_facts: JSONValue,
        trace: tuple[TraceEvent, ...],
        final_answer: JSONValue,
    ) -> TaskCheckResult:
        result = self._goal(self.blueprint.goal, before_facts, after_facts, trace, final_answer)
        failures = list(result.failures)
        if self.blueprint.report is not None:
            failures.extend(
                _check_report(self.blueprint.report, result.answer_values, final_answer)
            )
        if result.status == "abstain":
            return TaskCheckResult("abstain", tuple(dict.fromkeys(failures)), result.answer_values)
        if result.status == "failed" or failures:
            return TaskCheckResult("failed", tuple(dict.fromkeys(failures)), result.answer_values)
        return TaskCheckResult("satisfied", (), result.answer_values)

    def _goal(
        self,
        goal: GoalProgram,
        before: JSONValue,
        after: JSONValue,
        trace: tuple[TraceEvent, ...],
        answer: JSONValue,
    ) -> _GoalResult:
        if isinstance(goal, AtomGoal):
            return self._atom(goal, before, after, trace, answer)
        if isinstance(goal, ForEachGoal):
            return _combine(
                [
                    self._atom(goal.atom, before, after, trace, answer, semantic_key=key)
                    for key in self.resolved[goal.selector_id]
                ],
                "foreach",
            )
        if isinstance(goal, AllGoal):
            return _combine(
                [
                    self._goal(child_goal, before, after, trace, answer)
                    for child_goal in goal.children
                ],
                "all",
            )
        if isinstance(goal, IfGoal):
            return self._if(goal, before, after, trace, answer)
        raise CompilationError(f"unsupported goal type {type(goal).__name__}")

    def _atom(
        self,
        goal: AtomGoal,
        before: JSONValue,
        after: JSONValue,
        trace: tuple[TraceEvent, ...],
        answer: JSONValue,
        *,
        semantic_key: str | None = None,
    ) -> _GoalResult:
        keys = self.resolved[goal.selector_id]
        key = semantic_key or (keys[0] if len(keys) == 1 else "")
        if not key:
            return _GoalResult("failed", ("atom_target_not_unique",), {})
        binding = self.bindings[key]
        checked = self.catalog.semantics.evaluate_atom(
            AtomCheckRequest(
                goal.capability_id,
                before,
                after,
                binding.protected_binding,
                trace,
                answer,
            )
        )
        failures = list(checked.failures)
        if checked.initially_satisfied:
            failures.append(f"initially_satisfied:{goal.capability_id}:{key}")
        if not checked.required_effects_satisfied:
            failures.append(f"required_effect_missing:{goal.capability_id}:{key}")
        if not checked.collateral_ok:
            failures.append(f"collateral_damage:{goal.capability_id}:{key}")
        if checked.process_ok is False:
            failures.append(f"process_violation:{goal.capability_id}:{key}")
        status = checked.status
        if failures and status == "satisfied":
            status = "failed"
        return _GoalResult(status, tuple(failures), checked.answer_values)

    def _if(
        self,
        goal: IfGoal,
        before: JSONValue,
        after: JSONValue,
        trace: tuple[TraceEvent, ...],
        answer: JSONValue,
    ) -> _GoalResult:
        _, condition = self.catalog.conditions[goal.condition_id]
        binding: JSONObject | None = None
        if goal.selector_id is not None:
            keys = self.resolved[goal.selector_id]
            if len(keys) != 1:
                return _GoalResult("failed", ("condition_target_not_unique",), {})
            binding = self.bindings[keys[0]].protected_binding
        checked = self.catalog.semantics.evaluate_condition(
            ConditionCheckRequest(goal.condition_id, before, binding, trace)
        )
        if checked.status == "abstain":
            return _GoalResult("abstain", checked.failures or ("condition_abstained",), {})
        branch = goal.then_goal if checked.status == "true" else goal.else_goal
        if branch is None:
            return _GoalResult("satisfied", checked.failures, checked.report_values)
        child = self._goal(branch, before, after, trace, answer)
        return _GoalResult(
            child.status,
            checked.failures + child.failures,
            {**checked.report_values, **child.answer_values},
        )


def compile_definition(
    *,
    blueprint: TaskBlueprint,
    semantics: TaskSemantics,
    before_facts: JSONValue,
    bindings_by_capability: Mapping[str, tuple[BindingCandidate, ...]],
    public_reset_context: JSONValue,
    tool_names: tuple[str, ...] = (),
) -> tuple[TaskDefinition, CompiledTaskChecker]:
    """Freeze checker, then render the exact instruction later given to the Agent."""

    catalog = SemanticsCatalog(semantics)
    selectors = {selector.selector_id: selector for selector in blueprint.selectors}
    flat_bindings: dict[str, BindingCandidate] = {}
    resolved: dict[str, tuple[str, ...]] = {}
    for selector in blueprint.selectors:
        capability = catalog.capability(selector.capability_id)
        candidates = bindings_by_capability.get(selector.capability_id, ())
        for binding in candidates:
            validate_binding(capability, binding)
            previous = flat_bindings.setdefault(binding.semantic_key, binding)
            if previous != binding:
                raise CompilationError(f"semantic key {binding.semantic_key!r} is unstable")
        resolved[selector.selector_id] = _resolve_selector(selector, capability, candidates)
    _validate_goal(blueprint.goal, selectors, catalog)
    checker = CompiledTaskChecker(blueprint, resolved, flat_bindings, catalog)
    if checker.evaluate(before_facts, before_facts, (), None).status == "satisfied":
        raise CompilationError("Task is already satisfied at its initial state")
    instruction = render_instruction(blueprint, catalog, resolved, flat_bindings)
    audit = audit_instruction(instruction, tool_names=tool_names, bindings=flat_bindings)
    if not audit.accepted:
        raise CompilationError("instruction audit failed: " + ", ".join(audit.findings))
    artifact = CheckerArtifact(
        blueprint.blueprint_id,
        tuple(ResolvedSelector(key, value) for key, value in sorted(resolved.items())),
        checker.checker_digest,
    )
    definition = TaskDefinition(
        blueprint,
        artifact,
        instruction,
        _answer_schema(blueprint.report, catalog, blueprint.goal),
        public_reset_context,
        audit,
    )
    return definition, checker


def _resolve_selector(
    selector: SelectorSpec,
    capability: CapabilitySpec,
    candidates: tuple[BindingCandidate, ...],
) -> tuple[str, ...]:
    facets = {facet.name: facet for facet in capability.facets}
    selected = [candidate for candidate in candidates if candidate.eligible]
    for predicate in selector.filters:
        facet = facets.get(predicate.facet)
        if facet is None or predicate.operator not in facet.allowed_operators:
            raise CompilationError(f"unsupported selector predicate {predicate}")
        selected = [
            candidate
            for candidate in selected
            if _compare(candidate.facets.get(predicate.facet), predicate.operator, predicate.value)
        ]
    if selector.rank is not None:
        selected = _rank(selected, selector.rank, facets)
    if not selected:
        raise CompilationError(f"selector {selector.selector_id!r} has no eligible binding")
    if selector.cardinality == "one" and len(selected) != 1:
        raise CompilationError(f"selector {selector.selector_id!r} is ambiguous")
    return tuple(candidate.semantic_key for candidate in selected)


def _rank(
    candidates: list[BindingCandidate],
    rank: RankSpec,
    facets: Mapping[str, FacetSpec],
) -> list[BindingCandidate]:
    facet = facets.get(rank.facet)
    if facet is None:
        raise CompilationError(f"unknown rank facet {rank.facet!r}")
    if rank.direction not in facet.allowed_operators:
        raise CompilationError(
            f"rank direction {rank.direction!r} is not allowed for facet {rank.facet!r}"
        )
    values = [candidate.facets.get(rank.facet) for candidate in candidates]
    try:
        target = extreme_facet_value(values, rank.direction)
    except FacetValueError as exc:
        raise CompilationError(f"invalid rank facet {rank.facet!r}: {exc}") from exc
    return [
        candidate
        for candidate in candidates
        if compare_facet_values(candidate.facets.get(rank.facet), "eq", target)
    ]


def _compare(left: JSONValue, operator: str, right: JSONValue) -> bool:
    try:
        return compare_facet_values(left, operator, right)
    except FacetValueError as exc:
        raise CompilationError(f"invalid facet comparison {operator!r}: {exc}") from exc


def _validate_goal(
    goal: GoalProgram,
    selectors: Mapping[str, SelectorSpec],
    catalog: SemanticsCatalog,
) -> None:
    if isinstance(goal, AtomGoal):
        selector = _selector(goal.selector_id, selectors)
        capability = catalog.capability(goal.capability_id)
        if selector.capability_id != goal.capability_id:
            raise CompilationError("atom selector capability mismatch")
        if "atom" not in capability.supported_goal_kinds:
            raise CompilationError("capability does not support atom")
        return
    if isinstance(goal, ForEachGoal):
        selector = _selector(goal.selector_id, selectors)
        capability = catalog.capability(goal.atom.capability_id)
        if selector.cardinality != "all" or selector.capability_id != goal.atom.capability_id:
            raise CompilationError("ForEach requires an all-cardinality selector")
        if "foreach" not in capability.supported_goal_kinds:
            raise CompilationError("capability does not support ForEach")
        return
    if isinstance(goal, AllGoal):
        for child_goal in goal.children:
            _validate_goal(child_goal, selectors, catalog)
        rule = catalog.rules.get(goal.composition_rule_id)
        if rule is None:
            raise CompilationError("AllGoal has no qualified CompositionRule")
        if set(goal_capability_ids(goal)) != set(rule.capability_ids):
            raise CompilationError("AllGoal capability set does not match CompositionRule")
        return
    if isinstance(goal, IfGoal):
        owner, condition = catalog.conditions.get(goal.condition_id, (None, None))
        if condition is None or owner is None:
            raise CompilationError(f"unknown condition {goal.condition_id!r}")
        if condition.binding_scope == "selected_binding":
            if goal.selector_id is None:
                raise CompilationError("selected-binding condition requires selector_id")
            if _selector(goal.selector_id, selectors).capability_id != owner.capability_id:
                raise CompilationError("condition selector uses the wrong capability")
        elif goal.selector_id is not None:
            raise CompilationError("world condition must not carry a binding selector")
        branches = (
            (goal.then_goal, condition.true_capability_ids),
            (goal.else_goal, condition.false_capability_ids),
        )
        for branch_goal, allowed_capability_ids in branches:
            if branch_goal is None:
                if condition.report_field is None:
                    raise CompilationError("goal-less condition branch lacks a qualified report")
                continue
            _validate_goal(branch_goal, selectors, catalog)
            if not set(goal_capability_ids(branch_goal)) <= set(allowed_capability_ids):
                raise CompilationError("condition branch uses an unlicensed capability")
        return
    raise CompilationError(f"unsupported goal type {type(goal).__name__}")


def _selector(selector_id: str, selectors: Mapping[str, SelectorSpec]) -> SelectorSpec:
    try:
        return selectors[selector_id]
    except KeyError as exc:
        raise CompilationError(f"unknown selector {selector_id!r}") from exc


def render_instruction(
    blueprint: TaskBlueprint,
    catalog: SemanticsCatalog,
    resolved: Mapping[str, tuple[str, ...]],
    bindings: Mapping[str, BindingCandidate],
) -> str:
    sentence = _render_goal(blueprint.goal, blueprint, catalog, resolved, bindings)
    if blueprint.report is not None:
        labels = _answer_labels(blueprint.report, catalog, blueprint.goal)
        sentence += "; report " + ", ".join(labels)
    return sentence.rstrip(". ") + "."


def _render_goal(
    goal: GoalProgram,
    blueprint: TaskBlueprint,
    catalog: SemanticsCatalog,
    resolved: Mapping[str, tuple[str, ...]],
    bindings: Mapping[str, BindingCandidate],
) -> str:
    selectors = {selector.selector_id: selector for selector in blueprint.selectors}
    if isinstance(goal, AtomGoal):
        capability = catalog.capability(goal.capability_id)
        target, constraints = _target(
            selectors[goal.selector_id], capability, resolved, bindings, plural=False
        )
        return f"{capability.rendering.action_phrase} {target}" + (
            f" that {constraints}" if constraints else ""
        )
    if isinstance(goal, ForEachGoal):
        capability = catalog.capability(goal.atom.capability_id)
        target, constraints = _target(
            selectors[goal.selector_id], capability, resolved, bindings, plural=True
        )
        return f"{capability.rendering.action_phrase} {target}" + (
            f" that {constraints}" if constraints else ""
        )
    if isinstance(goal, AllGoal):
        return "; also ".join(
            _render_goal(child_goal, blueprint, catalog, resolved, bindings)
            for child_goal in goal.children
        )
    if isinstance(goal, IfGoal):
        _, condition = catalog.conditions[goal.condition_id]
        then_text = _branch_text(goal.then_goal, condition, blueprint, catalog, resolved, bindings)
        else_text = _branch_text(goal.else_goal, condition, blueprint, catalog, resolved, bindings)
        return f"if {condition.public_label}, {then_text}; otherwise, {else_text}"
    raise CompilationError(f"unsupported goal type {type(goal).__name__}")


def _branch_text(
    goal: GoalProgram | None,
    condition: ConditionSpec,
    blueprint: TaskBlueprint,
    catalog: SemanticsCatalog,
    resolved: Mapping[str, tuple[str, ...]],
    bindings: Mapping[str, BindingCandidate],
) -> str:
    if goal is not None:
        return _render_goal(goal, blueprint, catalog, resolved, bindings)
    assert condition.report_field is not None
    return f"report {condition.report_field.public_label}"


def _target(
    selector: SelectorSpec,
    capability: CapabilitySpec,
    resolved: Mapping[str, tuple[str, ...]],
    bindings: Mapping[str, BindingCandidate],
    *,
    plural: bool,
) -> tuple[str, str]:
    keys = resolved[selector.selector_id]
    label = capability.rendering.target_plural if plural else capability.rendering.target_singular
    facet_specs = {facet.name: facet for facet in capability.facets}
    constraints = [
        _predicate_text(
            facet_specs[predicate.facet].public_label,
            predicate.operator,
            predicate.value,
        )
        for predicate in selector.filters
    ]
    if selector.rank is not None:
        public = facet_specs[selector.rank.facet].public_label
        direction = "lowest" if selector.rank.direction == "min" else "highest"
        constraints.append(f"has the {direction} {public}")
    if not constraints and len(keys) == 1:
        visible = [
            str(value)
            for value in bindings[keys[0]].public_descriptor.values()
            if isinstance(value, (str, int, float))
        ]
        if visible:
            constraints.append("is identified as " + ", ".join(visible))
    return f"{'all' if plural else 'the'} {label}", " and ".join(constraints)


def _predicate_text(label: str, operator: str, value: JSONValue) -> str:
    rendered = repr(value)
    phrases = {
        "eq": f"has {label} equal to {rendered}",
        "neq": f"has {label} different from {rendered}",
        "lt": f"has {label} below {rendered}",
        "lte": f"has {label} at most {rendered}",
        "gt": f"has {label} above {rendered}",
        "gte": f"has {label} at least {rendered}",
    }
    try:
        return phrases[operator]
    except KeyError as exc:
        raise CompilationError(f"unsupported public predicate operator {operator!r}") from exc


def audit_instruction(
    instruction: str,
    *,
    tool_names: tuple[str, ...],
    bindings: Mapping[str, BindingCandidate],
) -> InstructionAudit:
    findings: list[str] = []
    lowered = instruction.casefold()
    for tool_name in tool_names:
        normalized = tool_name.casefold()
        code_like = any(not character.isalpha() for character in tool_name)
        quoted = f"`{normalized}`" in lowered or f'"{normalized}"' in lowered
        if quoted or (code_like and normalized in lowered):
            findings.append(f"tool_name_leak:{tool_name}")
    public_values = (
        set().union(
            *(
                _strings(value.public_descriptor) | _strings(value.facets)
                for value in bindings.values()
            )
        )
        if bindings
        else set()
    )
    protected_values = (
        set().union(*(_strings(value.protected_binding) for value in bindings.values()))
        if bindings
        else set()
    )
    for value in sorted(protected_values - public_values):
        if len(value) >= 4 and value.casefold() in lowered:
            findings.append(f"protected_value_leak:{value}")
    if "{" in instruction or "}" in instruction:
        findings.append("unresolved_placeholder")
    return InstructionAudit(not findings, tuple(findings))


def _answer_schema(
    report: ReportSpec | None,
    catalog: SemanticsCatalog,
    goal: GoalProgram,
) -> JSONObject | None:
    if report is None:
        return None
    specs = _answer_specs(catalog, goal)
    properties: JSONObject = {}
    for name in report.field_names:
        if name not in specs:
            raise CompilationError(f"report field {name!r} is not qualified")
        properties[name] = specs[name].value_schema
    return {
        "type": "object",
        "properties": properties,
        "required": list(report.field_names),
        "additionalProperties": False,
    }


def _answer_specs(
    catalog: SemanticsCatalog,
    goal: GoalProgram,
) -> dict[str, AnswerFieldSpec]:
    specs: dict[str, AnswerFieldSpec] = {}
    for capability_id in goal_capability_ids(goal):
        for field in catalog.capability(capability_id).answer_fields:
            specs[field.name] = field
    if isinstance(goal, IfGoal):
        _, condition = catalog.conditions[goal.condition_id]
        if condition.report_field is not None:
            specs[condition.report_field.name] = condition.report_field
    return specs


def _answer_labels(
    report: ReportSpec,
    catalog: SemanticsCatalog,
    goal: GoalProgram,
) -> list[str]:
    specs = _answer_specs(catalog, goal)
    return [specs[name].public_label for name in report.field_names]


def _check_report(report: ReportSpec, expected: JSONObject, actual: JSONValue) -> list[str]:
    if not isinstance(actual, dict):
        return ["answer_not_object"]
    failures: list[str] = []
    for name in report.field_names:
        if name not in expected:
            failures.append(f"answer_truth_missing:{name}")
        elif actual.get(name) != expected[name]:
            failures.append(f"answer_mismatch:{name}")
    return failures


def _combine(children: list[_GoalResult], prefix: str) -> _GoalResult:
    if any(child.status == "abstain" for child in children):
        status: CheckStatus = "abstain"
    elif any(child.status == "failed" for child in children):
        status = "failed"
    else:
        status = "satisfied"
    failures = tuple(failure for child in children for failure in child.failures)
    answers: JSONObject = {}
    for child in children:
        overlap = set(answers) & set(child.answer_values)
        if any(answers[name] != child.answer_values[name] for name in overlap):
            return _GoalResult("failed", (f"{prefix}_answer_conflict",), {})
        answers.update(child.answer_values)
    return _GoalResult(status, failures, answers)


def _strings(value: JSONValue) -> set[str]:
    if isinstance(value, str):
        return {value}
    if isinstance(value, list):
        return {item for child in value for item in _strings(child)}
    if isinstance(value, dict):
        return {item for child in value.values() for item in _strings(child)}
    return set()
