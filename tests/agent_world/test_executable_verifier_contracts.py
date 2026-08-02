from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path
from typing import cast

import pytest

from agent_world.artifact_store import ArtifactStore
from agent_world.contracts import (
    ActorBoundary,
    ArtifactRef,
    Budget,
    ConcurrencySemantics,
    CurriculumRequirements,
    DifficultyDimension,
    EnvironmentDesign,
    EnvironmentJob,
    EvaluatorGoalBinding,
    FidelityStatement,
    GenerationContext,
    IdempotencySemantics,
    ObservationSemantics,
    ParameterizedSolveRecipe,
    ParameterizedSolveStep,
    PermissionRule,
    PermissionScope,
    RecipePointer,
    ReleaseProfile,
    RetrySemantics,
    RewardSpec,
    RollbackSemantics,
    Rule,
    RuleArithmetic,
    RuleClause,
    RuleConstant,
    RuleValueRef,
    RuntimeAction,
    StateEntitySchema,
    StateSchema,
    TaskRequirement,
    TimeoutSemantics,
    ToolContract,
    ToolError,
    ToolSemantics,
    ToolSurface,
    TransactionSemantics,
    VerificationRequirements,
    VerifierAssertion,
    VerifierCase,
    VerifierIR,
    VerifierProperty,
    WorldBoundary,
    WorldSpec,
    sha256_digest,
)
from agent_world.control import (
    ArtifactSlotContract,
    GenerationWorkGraph,
    LeaseBudgetLedger,
    OperationBudget,
    OperationRun,
    ProposalExecution,
    ProposalPolicy,
    RepairPolicy,
    SchedulerLeafExecutor,
    StructuredValidationError,
    ValidationPolicy,
    WorkAttempt,
    WorkCommit,
    WorkControlRuntime,
    WorkControlStore,
    WorkCoordinate,
    WorkDefinition,
    WorkGroupDefinition,
    WorkScheduler,
    deterministic_boundary_work_definition,
)
from agent_world.invocation import (
    InvocationError,
    InvocationExecutionMode,
    InvocationResult,
    InvocationStatus,
)
from agent_world.invocation.codex_sdk import _terminate_process_tree
from agent_world.judge import compiler as verifier_compiler_module
from agent_world.judge.compiler import VerifierCompilationError, VerifierCompiler
from agent_world.judge.leaf import VerifierAggregateLeaf, VerifierBatchLeaf, VerifierPlanLeaf
from agent_world.judge.models import (
    PropertyExpectationIntent,
    RuntimeActionObservation,
    VerifierBatchPlan,
    VerifierCaseIntent,
    VerifierDraft,
    VerifierIntent,
)
from agent_world.judge.rules import RuleExecutionContext, design_rule_index, evaluate_task_reward
from agent_world.judge.service import EnvironmentJudge


def _ref(name: str, artifact_type: str = "test.contract") -> ArtifactRef:
    digest = sha256_digest(name.encode())
    return ArtifactRef(
        artifact_id=name,
        revision_id=digest,
        artifact_type=artifact_type,
        content_hash=digest,
        media_type="application/json",
        size_bytes=0,
    )


def _invocation_result(invocation_id: str) -> InvocationResult:
    return InvocationResult(
        invocation_id=invocation_id,
        status=InvocationStatus.COMPLETED,
        session=None,
        turn_id=f"turn:{invocation_id}",
        final_text="completed",
        structured_output=None,
        usage=None,
        events=(),
        error=None,
        duration_ms=1,
        backend_version="test",
    )


def _constant(value: int) -> RuleConstant:
    return RuleConstant(value_type="number", value=value)


def _ref_value(source: str, pointer: str) -> RuleValueRef:
    return RuleValueRef(
        source=source,  # type: ignore[arg-type]
        pointer=pointer,
        value_type="number",
    )


def _rule(
    rule_id: str,
    family: str,
    left: RuleValueRef,
    operator: str,
    right: RuleConstant | RuleValueRef | RuleArithmetic,
    *,
    sensitivity: str = "positive_only",
) -> Rule:
    return Rule(
        rule_id=rule_id,
        family=family,  # type: ignore[arg-type]
        description=f"Executable {family} rule.",
        boolean_operator="all",
        case_sensitivity=sensitivity,  # type: ignore[arg-type]
        clauses=(
            RuleClause(
                clause_id=f"clause:{rule_id}",
                left=left,
                operator=operator,  # type: ignore[arg-type]
                right=right,
            ),
        ),
    )


def _design(
    *,
    transition_sensitivity: str = "positive_only",
    error_sensitivity: str = "positive_and_negative",
) -> EnvironmentDesign:
    artifact = _ref("evidence")
    transition = _rule(
        "rule:transition",
        "transition",
        _ref_value("post_state", "/counter/value"),
        "equal",
        RuleArithmetic(
            operator="add",
            left=_ref_value("pre_state", "/counter/value"),
            right=_ref_value("args", "/amount"),
        ),
        sensitivity=transition_sensitivity,
    )
    precondition = _rule(
        "rule:precondition",
        "precondition",
        _ref_value("args", "/amount"),
        "greater_than",
        _constant(0),
        sensitivity="positive_and_negative",
    )
    postcondition = _rule(
        "rule:postcondition",
        "postcondition",
        _ref_value("tool_result", "/value"),
        "equal",
        _ref_value("post_state", "/counter/value"),
    )
    error_condition = _rule(
        "rule:error",
        "error_condition",
        _ref_value("args", "/amount"),
        "less_or_equal",
        _constant(0),
        sensitivity=error_sensitivity,
    )
    invariant = _rule(
        "rule:invariant",
        "invariant",
        _ref_value("post_state", "/counter/value"),
        "greater_or_equal",
        _constant(0),
    )
    success = _rule(
        "rule:success",
        "task_success",
        _ref_value("post_state", "/counter/value"),
        "greater_or_equal",
        _ref_value("task_goal", "/target"),
    )
    terminal = _rule(
        "rule:terminal",
        "task_terminal",
        _ref_value("post_state", "/counter/value"),
        "greater_or_equal",
        _ref_value("task_goal", "/target"),
    )
    surface = ToolSurface(
        tool_id="counter.increment",
        namespace="counter",
        name="increment",
        description="Increment the counter.",
        transport="runtime",
        input_schema={
            "type": "object",
            "properties": {"amount": {"type": "integer", "minimum": -10}},
            "required": ["amount"],
            "additionalProperties": False,
        },
        output_schema={
            "type": "object",
            "properties": {"value": {"type": "integer"}},
            "required": ["value"],
            "additionalProperties": False,
        },
        observation_schema={
            "type": "object",
            "properties": {"counter": {"type": "object"}},
            "required": ["counter"],
            "additionalProperties": False,
        },
    )
    semantics = ToolSemantics(
        preconditions=(precondition,),
        transition=(transition,),
        postconditions=(postcondition,),
        errors=(
            ToolError(
                error_code="invalid_amount",
                when=error_condition,
                observation="The amount is invalid.",
                state_effect="none",
                retryable=False,
            ),
        ),
        permission=PermissionRule(
            permission_id="permission:counter",
            allowed_actors=("user",),
            required_scopes_by_actor={"user": ()},
            denied_observation="Permission denied.",
        ),
        observation=ObservationSemantics(
            visible_fields_by_actor={"user": ("counter",), "auditor": ()},
            redacted_fields_by_actor={"user": (), "auditor": ("counter",)},
        ),
        idempotency=IdempotencySemantics(
            mode="idempotency_key",
            key_field="idempotency_key",
            retention_seconds=3600,
            duplicate_observation="Return the original result.",
        ),
        retry=RetrySemantics(maximum_attempts=1),
        timeout=TimeoutSemantics(
            operation_timeout_seconds=5,
            timeout_error_code="invalid_amount",
            cancellation_effect="no_effect",
        ),
        transaction=TransactionSemantics(
            atomicity="atomic",
            commit_point="After validation.",
            partial_commit_observable=False,
        ),
        rollback=RollbackSemantics(
            supported=True,
            rollback_trigger_codes=("invalid_amount",),
            guarantees="Invalid calls preserve state.",
        ),
        concurrency=ConcurrencySemantics(
            isolation="serializable",
            conflict_detection="Runtime serializes counter updates.",
            ordering_guarantee="Committed calls are observed in order.",
        ),
    )
    world = WorldSpec(
        world_spec_id="world:counter",
        revision=1,
        boundary=WorldBoundary(
            primary_domain="counter",
            actors_and_authority=(
                ActorBoundary(
                    actor="user",
                    authorities=("counter.write",),
                    visibility=("counter",),
                ),
                ActorBoundary(actor="auditor", authorities=("counter.read",)),
            ),
            systems_of_record=("counter-store",),
            core_resources=("counter",),
            transition_authorities=("counter-runtime",),
            tool_namespaces=("counter",),
            core_invariants=("Counter never becomes negative.",),
        ),
        state=StateSchema(
            entities=(
                StateEntitySchema(
                    entity="counter",
                    json_schema={
                        "type": "object",
                        "properties": {
                            "id": {"type": "string"},
                            "value": {"type": "integer"},
                        },
                        "required": ["id", "value"],
                    },
                    primary_key_fields=("id",),
                    mutable_fields=("value",),
                ),
            ),
            root_state_schema={
                "type": "object",
                "properties": {"counter": {"type": "object"}},
                "required": ["counter"],
            },
        ),
        tools=(ToolContract(surface=surface, semantics=semantics, evidence_claim_ids=("claim",)),),
        invariants=(invariant,),
        task_dimensions=("amount",),
        fidelity=(
            FidelityStatement(
                statement_id="fidelity:counter",
                claim="Counter behavior is synthetic and deterministic.",
                level="synthetic_policy",
            ),
        ),
        evidence_graph_ref=artifact,
        coverage_map_ref=_ref("coverage"),
    )
    curriculum = CurriculumRequirements(
        task_types=(
            TaskRequirement(
                task_type="increase",
                objective="Reach the target counter value.",
                allowed_actor_ids=("user",),
                required_tool_ids=("counter.increment",),
                success_conditions=(success,),
                terminal_conditions=(terminal,),
                initial_config_schema={
                    "type": "object",
                    "properties": {"initial": {"type": "integer"}},
                    "required": ["initial"],
                    "additionalProperties": False,
                },
                public_goal_schema={
                    "type": "object",
                    "properties": {"target": {"type": "integer"}},
                    "required": ["target"],
                    "additionalProperties": False,
                },
                evaluator_goal_schema={
                    "type": "object",
                    "properties": {"target": {"type": "integer"}},
                    "required": ["target"],
                    "additionalProperties": False,
                },
                evaluator_goal_bindings=(
                    EvaluatorGoalBinding(
                        binding_id="goal-binding:target",
                        public_pointer="/target",
                        evaluator_pointer="/target",
                    ),
                ),
                difficulty_dimensions=("scale",),
            ),
        ),
        difficulty_dimensions=(
            DifficultyDimension(
                dimension="scale",
                description="Counter target distance.",
                levels=("small", "large"),
            ),
        ),
        generation_seed_space="all uint64 values",
    )
    return EnvironmentDesign(
        design_id="design:counter",
        revision=1,
        job_ref=_ref("job"),
        request_ref=_ref("request"),
        evidence_graph_ref=artifact,
        coverage_map_ref=world.coverage_map_ref,
        world_spec=world,
        curriculum=curriculum,
        reward=RewardSpec(
            terminal_rule_ids=(terminal.rule_id,),
            success_rule_ids=(success.rule_id,),
        ),
        verification=VerificationRequirements(
            required_rule_ids=(
                invariant.rule_id,
                precondition.rule_id,
                transition.rule_id,
                postcondition.rule_id,
                error_condition.rule_id,
                success.rule_id,
                terminal.rule_id,
            ),
            required_property_families=(
                "invariant",
                "precondition",
                "transition",
                "postcondition",
                "error_semantics",
                "task_success",
                "task_terminal",
            ),
        ),
        target_kind="initial_package",
    )


def _draft(design: EnvironmentDesign) -> VerifierDraft:
    definitions = (
        ("public", 1, 5),
        ("repair", 1, 10),
        ("sealed", 9_999_999_999, 5),
    )
    cases = tuple(
        VerifierCase(
            case_id=f"case:{partition}",
            partition=partition,  # type: ignore[arg-type]
            task_type="increase",
            evaluator_goal={"target": target},
            seed=seed,
            actor="user",
            reset_config={"initial": 2},
            actions=(
                RuntimeAction(
                    tool_id="counter.increment",
                    arguments={"amount": 3},
                ),
                RuntimeAction(
                    tool_id="counter.increment",
                    arguments={"amount": 0},
                ),
            ),
            assertions=tuple(
                VerifierAssertion(
                    assertion_id=f"assertion:{partition}:{rule_id}:{index}",
                    rule_id=rule_id,
                    action_index=index,
                    expected=expected,
                )
                for rule_id, index, expected in (
                    ("rule:invariant", 0, True),
                    ("rule:precondition", 0, True),
                    ("rule:precondition", 1, False),
                    ("rule:transition", 0, True),
                    ("rule:postcondition", 0, True),
                    ("rule:error", 0, False),
                    ("rule:error", 1, True),
                    ("rule:success", 0, target == 5),
                    ("rule:terminal", 0, target == 5),
                )
            ),
        )
        for partition, seed, target in definitions
    )
    return VerifierDraft(
        properties=tuple(
            VerifierProperty(
                property_id=f"property:{rule_id}",
                kind=kind,  # type: ignore[arg-type]
                rule_ids=(rule_id,),
                case_ids=tuple(case.case_id for case in cases),
                description=f"Exercise the canonical {kind} Rule.",
            )
            for rule_id, kind in (
                ("rule:invariant", "invariant"),
                ("rule:precondition", "precondition"),
                ("rule:transition", "transition"),
                ("rule:postcondition", "postcondition"),
                ("rule:error", "error_semantics"),
                ("rule:success", "task_success"),
                ("rule:terminal", "task_terminal"),
            )
        ),
        cases=cases,
        solve_recipes=(
            ParameterizedSolveRecipe(
                recipe_id="recipe:increase",
                task_type="increase",
                preferred=True,
                steps=(
                    ParameterizedSolveStep(
                        step_id="step:increment",
                        tool_id="counter.increment",
                        arguments={
                            "amount": RecipePointer(
                                source="public_goal",
                                pointer="/target",
                            )
                        },
                    ),
                ),
            ),
        ),
    )


def test_compiler_binds_required_rule_to_canonical_property_and_both_partitions() -> None:
    design = _design()
    draft = _draft(design)

    VerifierCompiler._validate_draft(draft, design)


def test_compiler_rejects_reset_config_outside_task_schema() -> None:
    design = _design()
    draft = _draft(design)
    invalid_case = draft.cases[0].model_copy(update={"reset_config": {}})
    invalid_draft = draft.model_copy(update={"cases": (invalid_case, *draft.cases[1:])})

    with pytest.raises(ValueError, match="reset_config violates increase schema"):
        VerifierCompiler._validate_draft(invalid_draft, design)


def test_challenger_context_is_deduplicated_and_omits_rule_expressions() -> None:
    design = _design()

    context = VerifierCompiler._challenger_context(design)
    serialized = json.dumps(context, sort_keys=True)

    assert context["schema_version"] == "agent-world.challenger-context.v5"
    reset_config_schemas = context["reset_config_schemas"]
    assert isinstance(reset_config_schemas, list)
    assert len(reset_config_schemas) == 1
    assert '"clauses"' not in serialized
    assert '"evidence_claim_ids"' not in serialized
    assert '"rule:transition"' not in serialized
    assert '"initial_rule_ids"' not in serialized
    assert '"success_rule_ids"' not in serialized
    assert '"property_kind": "transition"' in serialized
    assert '"rule_count"' in serialized
    coverage_requirements = context["coverage_requirements"]
    assert isinstance(coverage_requirements, list)
    coverage_entries = [item for item in coverage_requirements if isinstance(item, dict)]
    assert len(coverage_entries) == len(coverage_requirements)
    coverage_ids: list[str] = []
    for item in coverage_entries:
        coverage_id = item.get("coverage_id")
        assert isinstance(coverage_id, str)
        coverage_ids.append(coverage_id)
    assert all(item.startswith("coverage:") for item in coverage_ids)
    assert len(coverage_ids) == len(set(coverage_ids))
    shared_requirements = [item for item in coverage_entries if item.get("scope") == "world_shared"]
    assert shared_requirements
    assert all(item.get("task_type") is None for item in shared_requirements)
    assert '"task_type": "shared"' not in serialized
    prompt = VerifierCompiler._prompt(context)
    assert "You have no tools" in prompt
    assert "syntactically valid RFC\n8259 JSON object only" in prompt
    assert "`NaN`, `Infinity`, or `-Infinity` literals" in prompt
    assert "two-pass coverage audit" in prompt
    assert "`rule_count` counts the framework's private Rules" in prompt
    assert "`positive_only` error_semantics" in prompt
    assert "positive means an `expectations` item" in prompt
    assert "`expected=true`" in prompt
    assert "merely including that tool elsewhere" in prompt
    assert "One expectation item may satisfy every compatible coverage row" in prompt
    assert "never put both polarities" in prompt
    assert "Within one case, emit each" in prompt
    assert "`(kind, after_action_ordinal)` at most once" in prompt
    assert "Action-input schema audit is mandatory" in prompt
    assert "additionalProperties=false" in prompt
    assert "Solve-recipe binding audit is mandatory" in prompt
    assert "A matching field name is not proof" in prompt
    assert "`solve_recipe_binding_guide`" in prompt


def test_compact_intent_expands_to_complete_rule_bound_verifier() -> None:
    design = _design()
    draft = _draft(design)
    rules = design_rule_index(design)
    cases = tuple(
        VerifierCaseIntent(
            task_type=case.task_type,
            evaluator_goal=case.evaluator_goal,
            actor=case.actor,
            reset_config=case.reset_config,
            actions=case.actions,
            expectations=tuple(
                PropertyExpectationIntent(
                    kind={
                        "error_condition": "error_semantics",
                    }.get(rules[item.rule_id].family, rules[item.rule_id].family),  # type: ignore[arg-type]
                    after_action_ordinal=item.action_index + 1,
                    expected=item.expected,
                )
                for item in case.assertions
            ),
        )
        for case in draft.cases
    )
    intent = VerifierIntent(cases=cases, solve_recipes=draft.solve_recipes)

    schema = VerifierIntent.model_json_schema()
    case_properties = schema["$defs"]["VerifierCaseIntent"]["properties"]
    assert {"case_id", "partition", "seed"}.isdisjoint(case_properties)
    bound = VerifierCompiler._bind_intent_cases(intent)  # noqa: SLF001
    assert len(bound) == 2 * len(intent.cases)
    assert len({item.case_id for item in bound}) == len(bound)
    for index in range(0, len(bound), 2):
        public, sealed = bound[index : index + 2]
        assert (public.partition, sealed.partition) == ("public", "sealed")
        assert public.seed != sealed.seed

    compiled = VerifierCompiler._compile_intent(
        intent,
        design,
        allowed_task_types=("increase",),
        required_rule_ids=design.verification.required_rule_ids,
        required_property_families=design.verification.required_property_families,
        require_metamorphic=False,
    )

    assert {item.rule_id for case in compiled.cases for item in case.assertions} == set(
        design.verification.required_rule_ids
    )
    assert {item.rule_ids[0] for item in compiled.properties} == set(
        design.verification.required_rule_ids
    )
    VerifierCompiler._validate_draft(compiled, design)


def test_verifier_requires_preferred_recipe_for_release_without_hidden_solver() -> None:
    design = _design()
    draft = _draft(design)
    rules = design_rule_index(design)
    intent = VerifierIntent(
        cases=tuple(
            VerifierCaseIntent(
                task_type=case.task_type,
                evaluator_goal=case.evaluator_goal,
                actor=case.actor,
                reset_config=case.reset_config,
                actions=case.actions,
                expectations=tuple(
                    PropertyExpectationIntent(
                        kind={
                            "error_condition": "error_semantics",
                        }.get(rules[item.rule_id].family, rules[item.rule_id].family),  # type: ignore[arg-type]
                        after_action_ordinal=item.action_index + 1,
                        expected=item.expected,
                    )
                    for item in case.assertions
                ),
            )
            for case in draft.cases
        ),
        solve_recipes=(),
    )

    with pytest.raises(StructuredValidationError) as intent_error:
        VerifierCompiler._validate_intent(  # noqa: SLF001 - compiler boundary under test
            intent,
            design,
            allowed_task_types=("increase",),
            required_rule_ids=design.verification.required_rule_ids,
            required_property_families=design.verification.required_property_families,
            require_metamorphic=False,
        )
    with pytest.raises(StructuredValidationError) as draft_error:
        VerifierCompiler._validate_draft(  # noqa: SLF001 - compiler boundary under test
            draft.model_copy(update={"solve_recipes": ()}),
            design,
        )

    assert intent_error.value.diagnostic.issue_codes == (
        "intent_release_recipe_missing@intent.solve_recipes",
    )
    assert draft_error.value.diagnostic.issue_codes == (
        "draft_release_recipe_missing@draft.solve_recipes",
    )


def test_sampling_rules_are_owned_by_task_materialization_not_runtime_cases() -> None:
    design = _design()
    sampling = _rule(
        "rule:sampling",
        "sampling",
        _ref_value("pre_state", "/counter/value"),
        "greater_or_equal",
        _constant(0),
    )
    scoped_design = design.model_copy(
        update={
            "curriculum": design.curriculum.model_copy(
                update={"sampling_constraints": (sampling,)}
            ),
            "verification": design.verification.model_copy(
                update={
                    "required_rule_ids": (
                        *design.verification.required_rule_ids,
                        sampling.rule_id,
                    ),
                    "required_property_families": (
                        *design.verification.required_property_families,
                        "sampling",
                    ),
                }
            ),
        }
    )

    assignments = VerifierCompiler._assign_required_rules(scoped_design)  # noqa: SLF001
    assert sampling.rule_id not in {
        rule_id for rule_ids in assignments.values() for rule_id in rule_ids
    }
    context = VerifierCompiler._challenger_context(scoped_design)  # noqa: SLF001
    assert "sampling" not in context["required_property_families"]
    assert '"property_kind":"sampling"' not in json.dumps(context, sort_keys=True)
    VerifierCompiler._validate_draft(_draft(design), scoped_design)  # noqa: SLF001


def test_solve_recipe_feedback_is_exact_safe_and_shared_by_intent_and_draft() -> None:
    """A constructed invalid recipe reaches the real compiler feedback boundary.

    This is not a mocked Agent response: both validators receive a normal typed
    candidate and must expose the same structural, non-secret correction fact.
    """

    design = _design()
    draft = _draft(design)
    rules = design_rule_index(design)
    invalid_recipe = draft.solve_recipes[0].model_copy(
        update={
            "steps": (
                ParameterizedSolveStep(
                    step_id="step:untrusted-tool",
                    tool_id="counter.untrusted",
                    arguments={},
                ),
                *draft.solve_recipes[0].steps,
            )
        }
    )
    cases = tuple(
        VerifierCaseIntent(
            task_type=case.task_type,
            evaluator_goal=case.evaluator_goal,
            actor=case.actor,
            reset_config=case.reset_config,
            actions=case.actions,
            expectations=tuple(
                PropertyExpectationIntent(
                    kind={
                        "error_condition": "error_semantics",
                    }.get(rules[item.rule_id].family, rules[item.rule_id].family),  # type: ignore[arg-type]
                    after_action_ordinal=item.action_index + 1,
                    expected=item.expected,
                )
                for item in case.assertions
            ),
        )
        for case in draft.cases
    )
    intent = VerifierIntent(cases=cases, solve_recipes=(invalid_recipe,))

    with pytest.raises(StructuredValidationError) as intent_error:
        VerifierCompiler._validate_intent(  # noqa: SLF001 - compiler boundary under test
            intent,
            design,
            allowed_task_types=("increase",),
            required_rule_ids=design.verification.required_rule_ids,
            required_property_families=design.verification.required_property_families,
            require_metamorphic=False,
        )
    with pytest.raises(StructuredValidationError) as draft_error:
        VerifierCompiler._validate_draft(  # noqa: SLF001 - compiler boundary under test
            draft.model_copy(update={"solve_recipes": (invalid_recipe,)}),
            design,
        )

    for root, diagnostic in (
        ("intent", intent_error.value.diagnostic),
        ("draft", draft_error.value.diagnostic),
    ):
        assert diagnostic.validation_phase == "solve_recipe"
        assert diagnostic.frontier_ordinal == 25
        assert len(diagnostic.issues) == 1
        issue = diagnostic.issues[0]
        assert issue.code == "recipe_tool_unknown"
        assert issue.location == (root, "solve_recipes", 0, "steps", 0, "tool_id")
        assert issue.expected_category is not None
        assert issue.remediation is not None
        assert issue.actionable_for_agent
        assert "counter.untrusted" not in diagnostic.feedback
        assert "step:untrusted-tool" not in diagnostic.feedback


def test_solve_recipe_type_feedback_and_agent_view_expose_compatible_bindings() -> None:
    """The real recipe boundary explains a type mismatch without replaying Agent output."""

    design = _design()
    task = design.curriculum.task_types[0]
    numeric_goal = {
        **task.public_goal_schema,
        "properties": {
            "target": {"type": "number"},
        },
    }
    numeric_task = task.model_copy(update={"public_goal_schema": numeric_goal})
    numeric_design = design.model_copy(
        update={
            "curriculum": design.curriculum.model_copy(
                update={"task_types": (numeric_task,)}
            )
        }
    )
    recipe = _draft(numeric_design).solve_recipes[0]

    with pytest.raises(StructuredValidationError) as captured:
        verifier_compiler_module._validate_solve_recipe(  # noqa: SLF001
            recipe,
            requirement=numeric_task,
            design=numeric_design,
            location=("intent", "solve_recipes", 0),
        )

    issue = captured.value.diagnostic.issues[0]
    assert issue.code == "recipe_pointer_type_mismatch"
    assert issue.location == ("intent", "solve_recipes", 0, "steps", 0, "arguments", 0)
    assert "type `number`" in issue.message
    assert "`amount` requires `integer`" in issue.message
    assert issue.remediation == (
        "Use a compatible pointer source, or replace this binding with a literal that "
        "validates against the selected tool argument schema."
    )
    assert "/target" not in issue.feedback

    context = VerifierCompiler._challenger_context(numeric_design)  # noqa: SLF001
    assert context["solve_recipe_binding_guide"] == [
        {
            "task_type": "increase",
            "tool_id": "counter.increment",
            "required_arguments": [
                {
                    "argument": "amount",
                    "target_type": "integer",
                    "candidates": [],
                }
            ],
        }
    ]


def test_verifier_rule_binding_reports_all_independent_missing_obligations() -> None:
    design = _design()
    draft = _draft(design)
    cases = tuple(
        VerifierCaseIntent(
            task_type=case.task_type,
            evaluator_goal=case.evaluator_goal,
            actor=case.actor,
            reset_config=case.reset_config,
            actions=case.actions,
            expectations=(
                PropertyExpectationIntent(
                    kind="transition",
                    after_action_ordinal=1,
                    expected=True,
                ),
            ),
        )
        for case in draft.cases
    )
    intent = VerifierIntent(cases=cases, solve_recipes=draft.solve_recipes)

    with pytest.raises(StructuredValidationError) as captured:
        VerifierCompiler._compile_intent(  # noqa: SLF001
            intent,
            design,
            allowed_task_types=("increase",),
            required_rule_ids=design.verification.required_rule_ids,
            required_property_families=design.verification.required_property_families,
            require_metamorphic=False,
        )

    diagnostic = captured.value.diagnostic
    assert diagnostic.validation_phase == "rule_binding"
    assert len(diagnostic.issue_codes) > 2
    assert all("rule:" not in issue for issue in diagnostic.issue_codes)
    context = VerifierCompiler._challenger_context(design)
    coverage_requirements = context["coverage_requirements"]
    assert isinstance(coverage_requirements, list)
    coverage_ids: set[str] = set()
    for item in coverage_requirements:
        if not isinstance(item, dict):
            continue
        coverage_id = item.get("coverage_id")
        if isinstance(coverage_id, str):
            coverage_ids.add(coverage_id)
    assert all(issue.location[0] == "coverage_requirements" for issue in diagnostic.issues)
    assert all(issue.location[1] in coverage_ids for issue in diagnostic.issues)
    assert all("required_rules" not in issue.feedback for issue in diagnostic.issues)
    assert all(issue.expected_category is not None for issue in diagnostic.issues)
    assert all(issue.remediation is not None for issue in diagnostic.issues)
    assert "expected=true" in diagnostic.feedback
    assert "expected=false" in diagnostic.feedback


def test_positive_only_error_coverage_has_one_safe_row_level_remediation() -> None:
    """A single omitted positive error row stays actionable without exposing Rules.

    This is the deterministic counterpart of the real Challenger failure: the
    model-visible coverage row has a positive-only error obligation, but the
    candidate omits the matching expectation.  The framework must retain the
    gate and return enough safe information for a subsequent authorized repair
    or causally changed regeneration.
    """

    design = _design(error_sensitivity="positive_only")
    draft = _draft(design)
    rules = design_rule_index(design)
    cases = tuple(
        VerifierCaseIntent(
            task_type=case.task_type,
            evaluator_goal=case.evaluator_goal,
            actor=case.actor,
            reset_config=case.reset_config,
            actions=case.actions,
            expectations=tuple(
                PropertyExpectationIntent(
                    kind={
                        "error_condition": "error_semantics",
                    }.get(rules[item.rule_id].family, rules[item.rule_id].family),  # type: ignore[arg-type]
                    after_action_ordinal=item.action_index + 1,
                    expected=item.expected,
                )
                for item in case.assertions
                if rules[item.rule_id].family != "error_condition"
            ),
        )
        for case in draft.cases
    )
    intent = VerifierIntent(cases=cases, solve_recipes=draft.solve_recipes)

    with pytest.raises(StructuredValidationError) as captured:
        VerifierCompiler._compile_intent(  # noqa: SLF001
            intent,
            design,
            allowed_task_types=("increase",),
            required_rule_ids=design.verification.required_rule_ids,
            required_property_families=design.verification.required_property_families,
            require_metamorphic=False,
        )

    context = VerifierCompiler._challenger_context(design)
    rows = context["coverage_requirements"]
    assert isinstance(rows, list)
    error_rows = [
        item
        for item in rows
        if isinstance(item, dict)
        and item.get("property_kind") == "error_semantics"
        and item.get("positive_and_negative") is False
    ]
    assert len(error_rows) == 1
    coverage_id = error_rows[0]["coverage_id"]
    assert isinstance(coverage_id, str)

    diagnostic = captured.value.diagnostic
    issue = next(
        item
        for item in diagnostic.issues
        if item.code == "rule_positive_partition_coverage"
        and item.location == ("coverage_requirements", coverage_id)
    )
    assert issue.expected_category == (
        "an expectations entry with the row property_kind, expected=true, "
        "and after_action_ordinal pointing to a compatible row tool"
    )
    assert issue.remediation == (
        "Add a compatible expectation with expected=true; when this row lists tool_ids, "
        "point its ordinal at one of those tool actions."
    )
    assert "counter.increment" in issue.feedback
    assert "rule:error" not in issue.feedback


def test_verifier_turn_budget_scales_by_capacity_batch_not_task() -> None:
    compiler = VerifierCompiler.__new__(VerifierCompiler)
    compiler.maximum_structured_reworks = 2
    compiler.maximum_tasks_per_batch = 4

    assert compiler.minimum_invocation_turns(1) == 1
    assert compiler.minimum_invocation_turns(4) == 1
    assert compiler.minimum_invocation_turns(8) == 2
    assert compiler.maximum_invocation_turns(1) == 3
    assert compiler.maximum_invocation_turns(8) == 6

    budgets = compiler._batch_budgets(
        Budget(
            llm_tokens=6 * 65_536,
            agent_turns=6,
            repair_attempts=4,
            wall_seconds=2_700,
        ),
        2,
    )
    assert len(budgets) == 2
    assert {item.agent_turns for item in budgets} == {3}
    assert {item.llm_tokens for item in budgets} == {3 * 65_536}
    assert sum(item.repair_attempts for item in budgets) == 4


def test_verifier_case_pairing_reserves_global_capacity_before_checkpoint() -> None:
    design = _design()
    draft = _draft(design)
    rules = design_rule_index(design)
    source = draft.cases[0]
    semantic_case = VerifierCaseIntent(
        task_type=source.task_type,
        evaluator_goal=source.evaluator_goal,
        actor=source.actor,
        reset_config=source.reset_config,
        actions=source.actions,
        expectations=tuple(
            PropertyExpectationIntent(
                kind={"error_condition": "error_semantics"}.get(
                    rules[item.rule_id].family,
                    rules[item.rule_id].family,
                ),  # type: ignore[arg-type]
                after_action_ordinal=item.action_index + 1,
                expected=item.expected,
            )
            for item in source.assertions
        ),
    )
    oversized = VerifierIntent(cases=(semantic_case,) * 64)

    with pytest.raises(ValueError, match="semantic case capacity"):
        VerifierCompiler._bind_intent_cases(oversized)  # noqa: SLF001

    assert VerifierCompiler._semantic_case_quotas(1) == (32,)  # noqa: SLF001
    eight_batch_quotas = VerifierCompiler._semantic_case_quotas(8)  # noqa: SLF001
    assert eight_batch_quotas == (4,) * 8
    assert sum(eight_batch_quotas) * 2 == 64


def test_verifier_diagnostic_is_typed_and_does_not_persist_private_case_id() -> None:
    diagnostic = VerifierCompiler._validation_diagnostic(  # noqa: SLF001
        ValueError("VerifierIntent case sealed-private-42 uses a disallowed actor")
    )

    assert diagnostic.validation_phase == "intent_semantics"
    assert diagnostic.issue_codes == ("intent_actor_not_allowed@intent.cases.actor",)
    assert "sealed-private-42" not in diagnostic.feedback


def test_verifier_intent_schema_feedback_reports_exact_safe_field_paths() -> None:
    design = _design()
    source = _draft(design).cases[0]
    intent = VerifierIntent(
        cases=(
            VerifierCaseIntent(
                task_type=source.task_type,
                evaluator_goal={"target": 5},
                actor=source.actor,
                reset_config={"initial": []},
                actions=(
                    RuntimeAction(
                        tool_id="counter.increment",
                        arguments={"amount": "private-sentinel"},
                    ),
                ),
                expectations=(
                    PropertyExpectationIntent(
                        kind="transition",
                        after_action_ordinal=1,
                        expected=True,
                    ),
                ),
            ),
            VerifierCaseIntent(
                task_type=source.task_type,
                evaluator_goal={"target": []},
                actor=source.actor,
                reset_config={},
                actions=(source.actions[0],),
                expectations=(
                    PropertyExpectationIntent(
                        kind="transition",
                        after_action_ordinal=1,
                        expected=True,
                    ),
                ),
            ),
            VerifierCaseIntent(
                task_type=source.task_type,
                evaluator_goal={"target": 5},
                actor=source.actor,
                reset_config={"initial": 2},
                actions=(
                    RuntimeAction(
                        tool_id="counter.increment",
                        arguments={"amount": -11},
                    ),
                ),
                expectations=(
                    PropertyExpectationIntent(
                        kind="transition",
                        after_action_ordinal=1,
                        expected=True,
                    ),
                ),
            ),
        )
    )

    with pytest.raises(StructuredValidationError) as captured:
        VerifierCompiler._validate_intent(  # noqa: SLF001
            intent,
            design,
            allowed_task_types=("increase",),
            required_rule_ids=design.verification.required_rule_ids,
            required_property_families=design.verification.required_property_families,
            require_metamorphic=False,
        )

    diagnostic = captured.value.diagnostic
    assert diagnostic.validation_phase == "intent_value_schemas"
    assert {issue.issue_code for issue in diagnostic.issues} == {
        "intent_reset_config_schema_mismatch@cases.0.reset_config.initial",
        "intent_action_input_schema_mismatch@cases.0.actions.0.arguments.amount",
        "intent_evaluator_goal_schema_mismatch@cases.1.evaluator_goal.target",
        "intent_reset_config_schema_mismatch@cases.1.reset_config",
        "intent_action_input_schema_mismatch@cases.2.actions.0.arguments.amount",
    }
    assert "private-sentinel" not in diagnostic.feedback
    assert "schema type integer" in diagnostic.feedback
    assert "initial" in diagnostic.feedback
    assert "minimum=-10" in diagnostic.feedback


def test_verifier_action_schema_feedback_exposes_safe_allowed_fields_not_rejected_input() -> None:
    issues = VerifierCompiler._json_schema_issues(  # noqa: SLF001 - feedback boundary under test
        schema={
            "type": "object",
            "properties": {"title": {"type": "string"}},
            "required": ["title"],
            "additionalProperties": False,
        },
        value={"private-sentinel": "never disclose"},
        location=("cases", 0, "actions", 0, "arguments"),
        code="intent_action_input_schema_mismatch",
        value_label="action input",
    )

    additional_properties = next(
        issue for issue in issues if "declared fields are" in issue.message
    )
    assert "title" in additional_properties.message
    assert "private-sentinel" not in additional_properties.feedback
    assert "never disclose" not in additional_properties.feedback
    assert additional_properties.expected_category == (
        "a closed action input object using only declared fields: title"
    )
    assert additional_properties.remediation == (
        "Remove undeclared action input fields and use only: title"
    )
    persisted = additional_properties.persistence_projection()
    assert persisted["remediation"] == additional_properties.remediation
    assert "private-sentinel" not in str(persisted)


def test_verifier_intent_uses_one_based_ordinals_and_reports_all_bad_references() -> None:
    design = _design()
    draft = _draft(design)
    cases = tuple(
        VerifierCaseIntent(
            task_type=case.task_type,
            evaluator_goal=case.evaluator_goal,
            actor=case.actor,
            reset_config=case.reset_config,
            actions=case.actions,
            expectations=(
                PropertyExpectationIntent(
                    kind="transition",
                    after_action_ordinal=len(case.actions) + 1,
                    expected=True,
                ),
            ),
        )
        for case in draft.cases
    )
    intent = VerifierIntent(cases=cases, solve_recipes=())

    with pytest.raises(StructuredValidationError) as captured:
        VerifierCompiler._validate_intent(  # noqa: SLF001
            intent,
            design,
            allowed_task_types=("increase",),
            required_rule_ids=design.verification.required_rule_ids,
            required_property_families=design.verification.required_property_families,
            require_metamorphic=False,
        )

    diagnostic = captured.value.diagnostic
    assert diagnostic.validation_phase == "intent_references"
    assert diagnostic.frontier_ordinal == 15
    assert len(diagnostic.issues) == len(cases)
    assert all(issue.code == "intent_action_ordinal_out_of_range" for issue in diagnostic.issues)
    assert all("after_action_ordinal" in issue.issue_code for issue in diagnostic.issues)
    assert all(
        issue.violated_condition == "each expectation must point to an action in its own case"
        for issue in diagnostic.issues
    )
    assert all(
        issue.expected_category
        == "a one-based after_action_ordinal between 1 and the number of actions in that case"
        for issue in diagnostic.issues
    )
    assert "one-based" in diagnostic.feedback
    prompt = VerifierCompiler._prompt({})
    assert "one-based" in prompt
    assert "fewest distinct trajectories" in prompt
    assert "`expectations`" in prompt
    assert "`checks`" in prompt
    assert "The verifier context and requested output are different schemas" in prompt
    assert "no hidden interactive solver" in prompt
    assert "`solve_recipes` is therefore" in prompt
    assert "separate semantically distinct trajectory" in prompt
    assert 'literal `"v2"`' in prompt
    schema = VerifierIntent.model_json_schema(mode="validation")
    definitions = schema["$defs"]
    assert isinstance(definitions, dict)
    case_schema = definitions["VerifierCaseIntent"]
    assert isinstance(case_schema, dict)
    properties = case_schema["properties"]
    assert isinstance(properties, dict)
    expectations_schema = properties["expectations"]
    assert isinstance(expectations_schema, dict)
    assert "literal field name" in str(expectations_schema["description"])


def test_verifier_intent_duplicate_expectation_has_one_safe_actionable_diagnostic() -> None:
    """Duplicate coverage work remains a semantic rejection, never silent code deduplication."""

    design = _design()
    duplicate_case = VerifierCaseIntent(
        task_type="increase",
        evaluator_goal={"target": 5},
        actor="user",
        reset_config={"initial": 2},
        actions=(RuntimeAction(tool_id="counter.increment", arguments={"amount": 3}),),
        expectations=(
            PropertyExpectationIntent(
                kind="transition",
                after_action_ordinal=1,
                expected=True,
            ),
            PropertyExpectationIntent(
                kind="transition",
                after_action_ordinal=1,
                expected=True,
            ),
        ),
    )
    distinct_case = duplicate_case.model_copy(
        update={
            "expectations": (
                PropertyExpectationIntent(
                    kind="precondition",
                    after_action_ordinal=1,
                    expected=True,
                ),
            )
        }
    )
    intent = VerifierIntent(cases=(duplicate_case, distinct_case), solve_recipes=())

    with pytest.raises(StructuredValidationError) as captured:
        VerifierCompiler._validate_intent(  # noqa: SLF001 - semantic boundary under test
            intent,
            design,
            allowed_task_types=("increase",),
            required_rule_ids=design.verification.required_rule_ids,
            required_property_families=design.verification.required_property_families,
            require_metamorphic=False,
        )

    diagnostic = captured.value.diagnostic
    assert diagnostic.validation_phase == "intent_references"
    assert diagnostic.issue_codes == (
        "intent_expectation_duplicate@cases.0.expectations.1.after_action_ordinal",
    )
    issue = diagnostic.issues[0]
    assert issue.violated_condition == (
        "each case must contain at most one expectation with the same kind, "
        "after_action_ordinal, and expected value"
    )
    assert issue.expected_category == (
        "one expectation for each unique (kind, after_action_ordinal, expected) combination; "
        "compatible coverage rows may reuse it"
    )
    assert issue.remediation == (
        "Merge duplicate expectation entries and keep the one compatible expectation that covers "
        "every matching row."
    )


def test_verifier_intent_rejects_opposite_polarities_on_one_action() -> None:
    """A negative obligation needs a different trajectory, not a second boolean label."""

    design = _design()
    conflicting_case = VerifierCaseIntent(
        task_type="increase",
        evaluator_goal={"target": 5},
        actor="user",
        reset_config={"initial": 2},
        actions=(RuntimeAction(tool_id="counter.increment", arguments={"amount": 3}),),
        expectations=(
            PropertyExpectationIntent(
                kind="transition",
                after_action_ordinal=1,
                expected=True,
            ),
            PropertyExpectationIntent(
                kind="transition",
                after_action_ordinal=1,
                expected=False,
            ),
        ),
    )
    second_case = conflicting_case.model_copy(
        update={
            "expectations": (
                PropertyExpectationIntent(
                    kind="precondition",
                    after_action_ordinal=1,
                    expected=True,
                ),
            )
        }
    )

    with pytest.raises(StructuredValidationError) as captured:
        VerifierCompiler._validate_intent(  # noqa: SLF001 - semantic boundary under test
            VerifierIntent(cases=(conflicting_case, second_case), solve_recipes=()),
            design,
            allowed_task_types=("increase",),
            required_rule_ids=design.verification.required_rule_ids,
            required_property_families=design.verification.required_property_families,
            require_metamorphic=False,
        )

    diagnostic = captured.value.diagnostic
    assert diagnostic.validation_phase == "intent_references"
    assert diagnostic.issue_codes == (
        "intent_expectation_polarity_conflict@cases.0.expectations.1.expected",
    )
    issue = diagnostic.issues[0]
    assert "one expected polarity" in issue.expected_category
    assert "distinct trajectory" in issue.remediation


def test_verifier_intent_compiles_one_based_ordinal_to_zero_based_index() -> None:
    expectation = PropertyExpectationIntent(
        kind="transition",
        after_action_ordinal=1,
        expected=True,
    )

    assert expectation.action_index == 0
    assert expectation.model_dump() == {
        "schema_version": "v2",
        "kind": "transition",
        "after_action_ordinal": 1,
        "expected": True,
    }


def test_verifier_batch_plan_is_deterministic_and_persisted_before_challenger_work(
    tmp_path: Path,
) -> None:
    """A future Scheduler shard receives frozen scope, never hidden compiler fan-out."""

    store = ArtifactStore(tmp_path / "artifacts")
    design_writer = store.issue_writer(
        producer="environment-designer",
        allowed_artifact_type_prefixes=("design.",),
    )
    judge_writer = store.issue_writer(
        producer="environment-judge",
        allowed_artifact_type_prefixes=("judge.",),
    )
    design = _design()
    design_ref = design_writer.put_json(
        artifact_id="design:verifier-plan",
        artifact_type="design.environment_design",
        value=design,
    )
    world_spec_ref = design_writer.put_json(
        artifact_id="world:verifier-plan",
        artifact_type="design.world_spec",
        value=design.world_spec,
    )
    compiler = VerifierCompiler(
        artifact_store=judge_writer,
        invocation_backend=object(),  # type: ignore[arg-type]
        profile_provider=object(),  # type: ignore[arg-type]
    )

    first = compiler.build_batch_plan(
        design=design,
        design_ref=design_ref,
        world_spec_ref=world_spec_ref,
    )
    second = compiler.build_batch_plan(
        design=design,
        design_ref=design_ref,
        world_spec_ref=world_spec_ref,
    )
    plan_ref = compiler.persist_batch_plan(first)

    assert first == second
    assert first.plan_digest == second.plan_digest
    assert tuple(item.batch_index for item in first.batches) == tuple(range(len(first.batches)))
    assert tuple(task for item in first.batches for task in item.task_types) == tuple(
        task.task_type for task in design.curriculum.task_types
    )
    assert store.get_json(plan_ref, VerifierBatchPlan) == first


@pytest.mark.asyncio
async def test_verifier_context_commitment_mismatch_requests_a_plan_refresh(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A compiler-context revision is a deterministic-parent change, not an Agent retry."""

    store = ArtifactStore(tmp_path / "artifacts")
    design_writer = store.issue_writer(
        producer="environment-designer",
        allowed_artifact_type_prefixes=("design.",),
    )
    judge_writer = store.issue_writer(
        producer="environment-judge",
        allowed_artifact_type_prefixes=("judge.",),
    )
    design = _design()
    design_ref = design_writer.put_json(
        artifact_id="design:context-commitment",
        artifact_type="design.environment_design",
        value=design,
    )
    world_spec_ref = design_writer.put_json(
        artifact_id="world:context-commitment",
        artifact_type="design.world_spec",
        value=design.world_spec,
    )
    compiler = VerifierCompiler(
        artifact_store=judge_writer,
        invocation_backend=object(),  # type: ignore[arg-type]
        profile_provider=object(),  # type: ignore[arg-type]
    )
    plan = compiler.build_batch_plan(
        design=design,
        design_ref=design_ref,
        world_spec_ref=world_spec_ref,
    )
    plan_ref = compiler.persist_batch_plan(plan)
    original_context = compiler._challenger_context  # noqa: SLF001

    def revised_context(*args: object, **kwargs: object) -> dict[str, object]:
        context = original_context(*args, **kwargs)
        context["protocol_version"] = "agent-world.challenger-context.test-revised"
        return context

    monkeypatch.setattr(compiler, "_challenger_context", revised_context)

    with pytest.raises(VerifierCompilationError) as captured:
        await compiler.compile_batch_once(
            design=design,
            design_ref=design_ref,
            world_spec_ref=world_spec_ref,
            plan=plan,
            plan_ref=plan_ref,
            batch_index=0,
            workspace=tmp_path / "workspace",
            lineage_id="lineage:context-commitment",
            budget=Budget(llm_tokens=1_000, agent_turns=1, wall_seconds=30),
            permissions=PermissionScope(),
            invocation_id="dispatch:context-commitment",
        )

    error = captured.value
    assert error.safe_code == "verifier_batch_plan_context_commitment_mismatch"
    assert error.retryable is False
    assert error.expected_category is not None
    assert error.remediation == (
        "refresh the deterministic VerifierPlan before dispatching this Verifier batch"
    )


@pytest.mark.asyncio
async def test_one_shot_verifier_batch_uses_the_scheduler_dispatch_and_never_retries(
    tmp_path: Path,
) -> None:
    """One physical WorkDefinition maps to exactly one Challenger request."""

    store = ArtifactStore(tmp_path / "artifacts")
    design_writer = store.issue_writer(
        producer="environment-designer",
        allowed_artifact_type_prefixes=("design.",),
    )
    judge_writer = store.issue_writer(
        producer="environment-judge",
        allowed_artifact_type_prefixes=("judge.",),
    )
    design = _design()
    design_ref = design_writer.put_json(
        artifact_id="design:one-shot-verifier",
        artifact_type="design.environment_design",
        value=design,
    )
    world_spec_ref = design_writer.put_json(
        artifact_id="world:one-shot-verifier",
        artifact_type="design.world_spec",
        value=design.world_spec,
    )
    rules = design_rule_index(design)
    source_draft = _draft(design)
    intent = VerifierIntent(
        cases=tuple(
            VerifierCaseIntent(
                task_type=case.task_type,
                evaluator_goal=case.evaluator_goal,
                actor=case.actor,
                reset_config=case.reset_config,
                actions=case.actions,
                expectations=tuple(
                    PropertyExpectationIntent(
                        kind={"error_condition": "error_semantics"}.get(
                            rules[assertion.rule_id].family,
                            rules[assertion.rule_id].family,
                        ),  # type: ignore[arg-type]
                        after_action_ordinal=assertion.action_index + 1,
                        expected=assertion.expected,
                    )
                    for assertion in case.assertions
                ),
            )
            for case in source_draft.cases
        ),
        solve_recipes=source_draft.solve_recipes,
    )

    class Profile:
        allowed_builtin_tools: tuple[str, ...] = ()
        output_schema = {"type": "object"}
        rollout_token_limit = 1_000

    class Profiles:
        def resolve(self, **_kwargs: object) -> Profile:
            return Profile()

    class OneShotBackend:
        def __init__(self) -> None:
            self.requests: list[object] = []

        async def invoke(self, request: object) -> InvocationResult:
            self.requests.append(request)
            return InvocationResult(
                invocation_id=request.invocation_id,  # type: ignore[attr-defined]
                status=InvocationStatus.COMPLETED,
                session=None,
                turn_id="turn:one-shot",
                final_text="completed",
                structured_output=intent.model_dump(mode="json"),
                usage=None,
                events=(),
                error=None,
                duration_ms=1,
            )

    backend = OneShotBackend()
    compiler = VerifierCompiler(
        artifact_store=judge_writer,
        invocation_backend=backend,  # type: ignore[arg-type]
        profile_provider=Profiles(),  # type: ignore[arg-type]
        maximum_structured_reworks=2,
    )
    plan = compiler.build_batch_plan(
        design=design,
        design_ref=design_ref,
        world_spec_ref=world_spec_ref,
    )
    plan_ref = compiler.persist_batch_plan(plan)

    result = await compiler.compile_batch_once(
        design=design,
        design_ref=design_ref,
        world_spec_ref=world_spec_ref,
        plan=plan,
        plan_ref=plan_ref,
        batch_index=0,
        workspace=tmp_path / "workspace",
        lineage_id="lineage:one-shot",
        budget=Budget(llm_tokens=1_000, agent_turns=1, wall_seconds=30),
        permissions=PermissionScope(),
        invocation_id="dispatch:verifier-batch:1",
    )

    assert result.succeeded
    assert result.invocation.invocation_id == "dispatch:verifier-batch:1"
    assert result.checkpoint_ref is not None
    assert result.draft_ref is not None
    assert len(backend.requests) == 1
    assert backend.requests[0].invocation_id == "dispatch:verifier-batch:1"  # type: ignore[attr-defined]
    assert (  # type: ignore[attr-defined]
        backend.requests[0].execution_mode is InvocationExecutionMode.SINGLE_SHOT_STRUCTURED
    )
    assert "Structured-output transport requirement:" not in backend.requests[0].prompt  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_scheduler_verifier_leaf_repairs_a_parsed_direct_candidate_with_feedback(
    tmp_path: Path,
) -> None:
    """A Verifier batch repairs through Scheduler, not a compiler-local retry loop."""

    store = ArtifactStore(tmp_path / "artifacts")
    design_writer = store.issue_writer(
        producer="environment-designer",
        allowed_artifact_type_prefixes=("design.",),
    )
    judge_writer = store.issue_writer(
        producer="environment-judge",
        allowed_artifact_type_prefixes=("judge.",),
    )
    control_writer = store.issue_writer(
        producer="work-controller",
        allowed_artifact_type_prefixes=("control.",),
    )
    design = _design()
    design_ref = design_writer.put_json(
        artifact_id="design:scheduler-verifier",
        artifact_type="design.environment_design",
        value=design,
    )
    world_spec_ref = design_writer.put_json(
        artifact_id="world:scheduler-verifier",
        artifact_type="design.world_spec",
        value=design.world_spec,
    )
    request_ref = control_writer.put_json(
        artifact_id="request:scheduler-verifier",
        artifact_type="control.environment_request",
        value={"need": "scheduler verifier closure"},
    )
    job = EnvironmentJob(
        job_id="job:scheduler-verifier",
        kind="generate",
        request_ref=request_ref,
        permissions=PermissionScope(),
        budget=Budget(
            llm_tokens=2_000,
            agent_turns=2,
            repair_attempts=1,
            wall_seconds=300,
        ),
        release_profile=ReleaseProfile(profile_id="release:scheduler-verifier"),
    )
    job_ref = control_writer.put_json(
        artifact_id=job.job_id,
        artifact_type="control.environment_job",
        value=job,
        dependencies=(request_ref,),
    )
    generation = GenerationContext(
        context_id="context:scheduler-verifier",
        job_ref=job_ref,
        kind="generate",
        request_ref=request_ref,
        permissions=job.permissions,
        budget=job.budget,
        release_profile=job.release_profile,
    )
    context_ref = control_writer.put_json(
        artifact_id=generation.context_id,
        artifact_type="control.generation_context",
        value=generation,
        dependencies=generation.root_refs,
    )
    modeling_definition = deterministic_boundary_work_definition(
        scope_id="job:scheduler-verifier",
        component="design",
        stage="modeling_boundary",
        artifact_slot="environment_design",
        dependency_coordinates=(),
        claim_id="design.modeling.closed",
        claim="A frozen Design and WorldSpec are available to deterministic planning.",
        timing_reason="Verifier planning may consume only committed Modeling outputs.",
        effect="block_compile",
        success_maturity="design_compiled",
    )
    plan_coordinate = WorkCoordinate(
        scope_id="job:scheduler-verifier",
        component="verifier",
        stage="verifier_plan",
        artifact_slot="verifier_batch_plan",
    )
    plan_definition = WorkDefinition(
        work_id="work:verifier-plan:scheduler-test",
        coordinate=plan_coordinate,
        claim="Verifier task partition is deterministically frozen.",
        timing_reason="A Challenger must not select its own task partition.",
        dependency_coordinates=(modeling_definition.coordinate,),
        output_slots=(
            ArtifactSlotContract(
                slot_id="output:verifier-plan",
                direction="output",
                artifact_types=("judge.verifier_batch_plan",),
                minimum_count=1,
                maximum_count=1,
                producer_component="verifier",
                confidentiality="framework_private",
            ),
        ),
        proposal_policy=ProposalPolicy(
            policy_id="proposal:verifier-plan:scheduler-test",
            executor="code",
            operation="verifier.plan",
            budget=OperationBudget(wall_seconds=30),
        ),
        validation_policy=ValidationPolicy(
            policy_id="validation:verifier-plan:scheduler-test",
            validator_id="validator:verifier-plan",
            validator_revision_id="framework.validator.verifier-plan.v1",
            validation_phase="verifier_plan",
            frontier_ordinal=10,
            claim_id="verifier.plan.frozen",
            effect="block_release",
            budget=OperationBudget(wall_seconds=30),
        ),
        repair_policy=RepairPolicy(
            policy_id="repair:verifier-plan:scheduler-test",
            maximum_local_corrections=0,
            strict_progress_bonus_corrections=0,
            maximum_infrastructure_retries=0,
            maximum_total_repair_attempts=0,
        ),
        required_claim_id="verifier.plan.frozen",
        success_maturity="verifier_plan_frozen",
    )
    batch_coordinate = WorkCoordinate(
        scope_id="job:scheduler-verifier",
        component="verifier",
        stage="verifier_intent_batch",
        artifact_slot="verifier_intent_checkpoint",
        group_id="scheduler-verifier-batches",
        shard_id="batch-1",
    )
    batch_definition = WorkDefinition(
        work_id="work:verifier-batch:scheduler-test",
        coordinate=batch_coordinate,
        claim="One exact Challenger batch compiles verifier intent.",
        timing_reason="Every real Challenger turn must have independent provenance.",
        dependency_coordinates=(plan_coordinate,),
        input_slots=(
            ArtifactSlotContract(
                slot_id="input:verifier-plan",
                direction="input",
                artifact_types=("judge.verifier_batch_plan",),
                minimum_count=1,
                maximum_count=1,
                producer_component="verifier",
                confidentiality="framework_private",
            ),
        ),
        output_slots=(
            ArtifactSlotContract(
                slot_id="output:verifier-checkpoint",
                direction="output",
                artifact_types=("judge.verifier_intent_checkpoint",),
                minimum_count=1,
                maximum_count=1,
                producer_component="verifier",
            ),
            ArtifactSlotContract(
                slot_id="output:verifier-draft",
                direction="output",
                artifact_types=("judge.verifier_batch_draft",),
                minimum_count=1,
                maximum_count=1,
                producer_component="verifier",
                confidentiality="sealed",
            ),
        ),
        proposal_policy=ProposalPolicy(
            policy_id="proposal:verifier-batch:scheduler-test",
            executor="agent",
            operation="verifier.compile_intent_batch",
            budget=OperationBudget(wall_seconds=30, llm_tokens=1_000, agent_turns=1),
            agent_role="challenger",
            capability_profile_id="profile:challenger",
            output_contract_id="contract:verifier-intent-batch.v3",
        ),
        validation_policy=ValidationPolicy(
            policy_id="validation:verifier-batch:scheduler-test",
            validator_id="validator:verifier-intent-batch",
            validator_revision_id="framework.validator.verifier-intent-batch.v3",
            validation_phase="verifier_intent_batch",
            frontier_ordinal=20,
            claim_id="verifier.intent.batch.valid",
            effect="block_release",
            budget=OperationBudget(wall_seconds=30),
        ),
        repair_policy=RepairPolicy(
            policy_id="repair:verifier-batch:scheduler-test",
            maximum_local_corrections=1,
            strict_progress_bonus_corrections=1,
            maximum_infrastructure_retries=1,
            maximum_total_repair_attempts=3,
        ),
        required_claim_id="verifier.intent.batch.valid",
        allowed_mutation_roots=("/cases", "/properties", "/coverage"),
        success_maturity="verifier_batch_compiled",
    )
    aggregate_coordinate = WorkCoordinate(
        scope_id="job:scheduler-verifier",
        component="verifier",
        stage="verifier_intent",
        artifact_slot="verifier_bundle",
        group_id="scheduler-verifier-batches",
    )
    aggregate_definition = WorkDefinition(
        work_id="work:verifier-aggregate:scheduler-test",
        coordinate=aggregate_coordinate,
        claim="Exact verifier batches form one complete Verifier IR.",
        timing_reason="Release consumes a deterministic aggregate, never a partial batch.",
        dependency_coordinates=(batch_coordinate,),
        input_slots=(
            ArtifactSlotContract(
                slot_id="input:verifier-checkpoint",
                direction="input",
                artifact_types=("judge.verifier_intent_checkpoint",),
                minimum_count=1,
                maximum_count=1,
                producer_component="verifier",
                confidentiality="framework_private",
            ),
            ArtifactSlotContract(
                slot_id="input:verifier-draft",
                direction="input",
                artifact_types=("judge.verifier_batch_draft",),
                minimum_count=1,
                maximum_count=1,
                producer_component="verifier",
                confidentiality="sealed",
            ),
        ),
        output_slots=(
            ArtifactSlotContract(
                slot_id="output:verifier-ir",
                direction="output",
                artifact_types=("judge.verifier_ir_projection",),
                minimum_count=1,
                maximum_count=1,
                producer_component="verifier",
                confidentiality="sealed",
            ),
        ),
        proposal_policy=ProposalPolicy(
            policy_id="proposal:verifier-aggregate:scheduler-test",
            executor="code",
            operation="verifier.aggregate",
            budget=OperationBudget(wall_seconds=30),
        ),
        validation_policy=ValidationPolicy(
            policy_id="validation:verifier-aggregate:scheduler-test",
            validator_id="validator:verifier-aggregate",
            validator_revision_id="framework.validator.verifier-aggregate.v3",
            validation_phase="verifier_intent",
            frontier_ordinal=30,
            claim_id="verifier.intent.valid",
            effect="block_release",
            budget=OperationBudget(wall_seconds=30),
        ),
        repair_policy=RepairPolicy(
            policy_id="repair:verifier-aggregate:scheduler-test",
            maximum_local_corrections=0,
            strict_progress_bonus_corrections=0,
            maximum_infrastructure_retries=0,
            maximum_total_repair_attempts=0,
        ),
        required_claim_id="verifier.intent.valid",
        success_maturity="verifier_compiled",
    )
    group = WorkGroupDefinition(
        group_id="scheduler-verifier-batches",
        scope_id="job:scheduler-verifier",
        member_coordinates=(batch_coordinate,),
        aggregate_coordinate=aggregate_coordinate,
    )
    graph = GenerationWorkGraph.compile(
        (modeling_definition, plan_definition, batch_definition, aggregate_definition),
        groups=(group,),
        mode="diagnostic",
    )
    manifest = graph.manifest(
        topology_id="topology:scheduler-verifier-leaf",
        external_root_refs=(context_ref,),
    )
    manifest_ref = control_writer.put_json(
        artifact_id=manifest.graph_id,
        artifact_type="control.work_graph_manifest",
        value=manifest,
        dependencies=(context_ref,),
    )
    rules = design_rule_index(design)
    source_draft = _draft(design)
    intent = VerifierIntent(
        cases=tuple(
            VerifierCaseIntent(
                task_type=case.task_type,
                evaluator_goal=case.evaluator_goal,
                actor=case.actor,
                reset_config=case.reset_config,
                actions=case.actions,
                expectations=tuple(
                    PropertyExpectationIntent(
                        kind={"error_condition": "error_semantics"}.get(
                            rules[assertion.rule_id].family,
                            rules[assertion.rule_id].family,
                        ),  # type: ignore[arg-type]
                        after_action_ordinal=assertion.action_index + 1,
                        expected=assertion.expected,
                    )
                    for assertion in case.assertions
                ),
            )
            for case in source_draft.cases
        ),
        solve_recipes=source_draft.solve_recipes,
    )
    rejected_intent = intent.model_copy(
        update={
            "cases": tuple(
                case.model_copy(
                    update={
                        "expectations": tuple(
                            expectation.model_copy(update={"expected": True})
                            if expectation.kind == "error_semantics"
                            and expectation.expected is False
                            else expectation
                            for expectation in case.expectations
                        )
                    }
                )
                for case in intent.cases
            )
        }
    )

    class Profile:
        allowed_builtin_tools: tuple[str, ...] = ()
        model_provider = "openai-compatible"
        model = "grok-4.5"
        output_schema = {"type": "object"}
        profile_hash = "a" * 64
        rollout_token_limit = 1_000

    class Profiles:
        def resolve(self, **_kwargs: object) -> Profile:
            return Profile()

    class Backend:
        def __init__(self) -> None:
            self.requests: list[object] = []

        async def invoke(self, request: object) -> InvocationResult:
            self.requests.append(request)
            return InvocationResult(
                invocation_id=request.invocation_id,  # type: ignore[attr-defined]
                status=InvocationStatus.COMPLETED,
                session=None,
                turn_id="turn:scheduler-verifier",
                final_text="completed",
                structured_output=(
                    rejected_intent if len(self.requests) == 1 else intent
                ).model_dump(mode="json"),
                usage=None,
                events=(),
                error=None,
                duration_ms=1,
            )

    backend = Backend()
    compiler = VerifierCompiler(
        artifact_store=judge_writer,
        invocation_backend=backend,  # type: ignore[arg-type]
        profile_provider=Profiles(),  # type: ignore[arg-type]
    )
    heads = WorkControlStore(tmp_path / "work-control")
    runtime = WorkControlRuntime(
        artifacts=control_writer,
        heads=heads,
        budget=LeaseBudgetLedger(
            Budget(
                llm_tokens=2_000,
                agent_turns=2,
                repair_attempts=1,
                wall_seconds=300,
            )
        ),
    )
    runtime.execute_deterministic_boundary(
        definition=modeling_definition,
        input_refs=(context_ref,),
        subject_ref=design_ref,
        output_refs=(design_ref, world_spec_ref),
    )
    scheduler = WorkScheduler(
        graph=graph,
        manifest=manifest,
        manifest_ref=manifest_ref,
        heads=heads,
        artifacts=control_writer,
        runtime=runtime,
    )
    kernel = SchedulerLeafExecutor(runtime=runtime)
    plan_leaf = VerifierPlanLeaf(compiler=compiler, kernel=kernel)
    batch_leaf = VerifierBatchLeaf(
        compiler=compiler,
        workspace_root=tmp_path / "verifier-workspace",
        kernel=kernel,
    )
    aggregate_leaf = VerifierAggregateLeaf(
        compiler=compiler,
        kernel=kernel,
    )

    async def execute_plan(context) -> None:
        await plan_leaf.execute(context, definition=plan_definition)

    async def execute_batch(context) -> None:
        await batch_leaf.execute(context, definition=batch_definition)

    async def execute_aggregate(context) -> None:
        await aggregate_leaf.execute(context, definition=aggregate_definition)

    results = await scheduler.run_until_stalled(
        executors={
            plan_definition.work_id: execute_plan,
            batch_definition.work_id: execute_batch,
            aggregate_definition.work_id: execute_aggregate,
        }
    )

    assert tuple(item.after_state for item in results) == (
        "committed",
        "repair_ready",
        "committed",
        "committed",
    )
    assert len(backend.requests) == 2
    assert (  # type: ignore[attr-defined]
        backend.requests[0].execution_mode is InvocationExecutionMode.SINGLE_SHOT_STRUCTURED
    )
    assert backend.requests[0].session is None  # type: ignore[attr-defined]
    assert backend.requests[1].session is None  # type: ignore[attr-defined]
    assert "<prior_candidate_json>" not in backend.requests[0].prompt  # type: ignore[attr-defined]
    assert "<prior_candidate_json>" in backend.requests[1].prompt  # type: ignore[attr-defined]
    assert "coverage:" in backend.requests[1].prompt  # type: ignore[attr-defined]
    assert "repair_action_ref" not in backend.requests[1].prompt  # type: ignore[attr-defined]
    batch_head = heads.read_head(batch_coordinate)
    assert batch_head is not None and batch_head.commit_ref is not None
    batch_attempt = control_writer.get_json(batch_head.attempt_ref, WorkAttempt)
    assert len(batch_attempt.output_refs) == 2
    proposal_run = next(
        control_writer.get_json(ref, OperationRun)
        for ref in batch_attempt.operation_run_refs
        if control_writer.get_json(ref, OperationRun).kind == "proposal"
    )
    assert proposal_run.execution_ref is not None
    proposal = control_writer.get_json(proposal_run.execution_ref, ProposalExecution)
    assert proposal.invocation_id == backend.requests[1].invocation_id  # type: ignore[attr-defined]
    aggregate_head = heads.read_head(aggregate_coordinate)
    assert aggregate_head is not None and aggregate_head.commit_ref is not None
    aggregate_commit = control_writer.get_json(aggregate_head.commit_ref, WorkCommit)
    assert aggregate_commit.aggregate
    assert aggregate_commit.child_commit_refs == (batch_head.commit_ref,)


@pytest.mark.asyncio
async def test_legacy_verifier_does_not_spend_a_hidden_icp_retry(
    tmp_path: Path,
) -> None:
    """An ICP terminal leaves provider retry authority above the legacy loop."""

    class Profile:
        rollout_token_limit = 100
        allowed_builtin_tools: tuple[str, ...] = ()

        def __init__(self, output_schema: dict[str, object]) -> None:
            self.output_schema = output_schema

    class Profiles:
        def resolve(self, **kwargs: object) -> Profile:
            return Profile(cast(dict[str, object], kwargs["output_schema"]))

    class ControlPlaneRetryBackend:
        owns_declared_lifecycle = True

        def __init__(self) -> None:
            self.requests: list[object] = []

        async def invoke(self, request: object) -> InvocationResult:
            self.requests.append(request)
            return InvocationResult(
                invocation_id=request.invocation_id,  # type: ignore[attr-defined]
                status=InvocationStatus.FAILED,
                session=None,
                turn_id=None,
                final_text=None,
                structured_output=None,
                usage=None,
                events=(),
                error=InvocationError(
                    code="turn_failed_provider_unavailable",
                    message="closed transient terminal",
                    retryable=True,
                ),
                duration_ms=1,
            )

    backend = ControlPlaneRetryBackend()
    compiler = VerifierCompiler(
        artifact_store=object(),  # type: ignore[arg-type]
        invocation_backend=backend,  # type: ignore[arg-type]
        profile_provider=Profiles(),  # type: ignore[arg-type]
        maximum_structured_reworks=1,
    )

    with pytest.raises(VerifierCompilationError):
        await compiler._run_structured(  # noqa: SLF001
            lineage_id="verifier-icp-owned-retry",
            workspace=tmp_path / "verifier-icp-owned-retry",
            model=VerifierIntent,
            prompt="immutable verifier batch prompt",
            semantic_validator=lambda _output: None,
            budget=Budget(llm_tokens=200, agent_turns=2, wall_seconds=30),
            permissions=PermissionScope(),
        )

    assert len(backend.requests) == 1


@pytest.mark.asyncio
async def test_verifier_supervisor_cancels_real_straggler_and_keeps_success_checkpoint(
    tmp_path: Path,
) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    seed_writer = store.issue_writer(
        producer="test-seed",
        allowed_artifact_type_prefixes=("test.",),
    )
    judge_writer = store.issue_writer(
        producer="environment-judge",
        allowed_artifact_type_prefixes=("judge.",),
    )
    design_ref = seed_writer.put_json(
        artifact_id="test:design",
        artifact_type="test.design",
        value={"kind": "design"},
    )
    world_ref = seed_writer.put_json(
        artifact_id="test:world",
        artifact_type="test.world",
        value={"kind": "world"},
    )

    class ProcessCancellationBackend:
        def __init__(self) -> None:
            self.processes: dict[str, asyncio.subprocess.Process] = {}

        async def invoke(self, request: object) -> object:
            raise AssertionError("supervisor contract test does not invoke an Agent")

        async def cancel(self, invocation_id: str) -> bool:
            process = self.processes.get(invocation_id)
            if process is None or process.returncode is not None:
                return False
            await _terminate_process_tree(process, grace_seconds=1)
            return True

    backend = ProcessCancellationBackend()
    compiler = VerifierCompiler(
        artifact_store=judge_writer,
        invocation_backend=backend,  # type: ignore[arg-type]
        profile_provider=object(),  # type: ignore[arg-type]
        batch_failure_grace_seconds=0,
        cancellation_timeout_seconds=1,
    )
    active: dict[int, set[str]] = {0: set(), 1: set(), 2: set()}
    checkpoint_refs: list[ArtifactRef] = []
    straggler_started = asyncio.Event()
    design = _design()

    async def successful_job() -> tuple[VerifierDraft, tuple[object, ...], ArtifactRef]:
        process = await asyncio.create_subprocess_exec(sys.executable, "-c", "pass")
        assert await process.wait() == 0
        ref = judge_writer.put_json(
            artifact_id="lineage:test:successful-checkpoint",
            artifact_type="judge.verifier_intent_checkpoint",
            value={"batch_index": 0, "status": "passed"},
            dependencies=(design_ref, world_ref),
        )
        checkpoint_refs.append(ref)
        return _draft(design), (), ref

    async def fatal_job() -> tuple[VerifierDraft, tuple[object, ...], ArtifactRef]:
        # A production leaf records its invocation id before crossing the
        # backend boundary.  Make this real-process test exercise that same
        # state rather than racing a child process against its registration.
        await straggler_started.wait()
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-c",
            "import sys,time; time.sleep(0.2); sys.exit(7)",
        )
        assert await process.wait() == 7
        raise VerifierCompilationError("typed fatal batch")

    async def straggler_job() -> tuple[VerifierDraft, tuple[object, ...], ArtifactRef]:
        invocation_id = "inv-real-straggler"
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-c",
            "import time; time.sleep(60)",
        )
        backend.processes[invocation_id] = process
        active[2].add(invocation_id)
        straggler_started.set()
        try:
            await process.wait()
        finally:
            active[2].discard(invocation_id)
        raise AssertionError("cancelled straggler must not complete normally")

    started = time.monotonic()
    with pytest.raises(VerifierCompilationError, match="typed fatal batch") as captured:
        await compiler._supervise_capacity_batches(  # noqa: SLF001
            lineage_id="lineage:test",
            design_ref=design_ref,
            world_spec_ref=world_ref,
            jobs=(successful_job(), fatal_job(), straggler_job()),  # type: ignore[arg-type]
            active_invocations=active,
            turn_token_upper_bounds={0: 100, 1: 200, 2: 300},
        )

    assert time.monotonic() - started < 3
    assert checkpoint_refs
    assert captured.value.checkpoint_refs == tuple(checkpoint_refs)
    assert captured.value.unknown_token_upper_bounds == (300,)
    assert store.get_json(checkpoint_refs[0]) == {"batch_index": 0, "status": "passed"}
    assert backend.processes["inv-real-straggler"].returncode is not None


@pytest.mark.asyncio
async def test_verifier_supervisor_aggregates_grace_sibling_failure_accounting(
    tmp_path: Path,
) -> None:
    store = ArtifactStore(tmp_path / "grace-accounting-artifacts")
    seed_writer = store.issue_writer(
        producer="test-seed",
        allowed_artifact_type_prefixes=("test.",),
    )
    judge_writer = store.issue_writer(
        producer="environment-judge",
        allowed_artifact_type_prefixes=("judge.",),
    )
    design_ref = seed_writer.put_json(
        artifact_id="grace:design",
        artifact_type="test.design",
        value={"kind": "design"},
    )
    world_ref = seed_writer.put_json(
        artifact_id="grace:world",
        artifact_type="test.world",
        value={"kind": "world"},
    )
    checkpoint_ref = judge_writer.put_json(
        artifact_id="grace:sibling-checkpoint",
        artifact_type="judge.verifier_intent_checkpoint",
        value={"batch_index": 1},
        dependencies=(design_ref, world_ref),
    )

    class NoopBackend:
        async def invoke(self, request: object) -> object:
            raise AssertionError("supervisor contract test does not invoke an Agent")

        async def cancel(self, invocation_id: str) -> bool:
            return False

    compiler = VerifierCompiler(
        artifact_store=judge_writer,
        invocation_backend=NoopBackend(),  # type: ignore[arg-type]
        profile_provider=object(),  # type: ignore[arg-type]
        batch_failure_grace_seconds=0.2,
        cancellation_timeout_seconds=0.2,
    )
    accounting = {
        index: verifier_compiler_module._VerifierBatchAccounting()  # noqa: SLF001
        for index in range(2)
    }
    sibling_started = asyncio.Event()
    sibling_result = _invocation_result("inv-grace-sibling")

    async def primary_fatal() -> tuple[VerifierDraft, tuple[InvocationResult, ...], ArtifactRef]:
        await sibling_started.wait()
        raise VerifierCompilationError("primary fatal")

    async def grace_sibling() -> tuple[VerifierDraft, tuple[InvocationResult, ...], ArtifactRef]:
        sibling_started.set()
        await asyncio.sleep(0.01)
        raise VerifierCompilationError(
            "secondary fatal",
            invocation_results=(sibling_result,),
            unknown_token_upper_bounds=(222,),
            checkpoint_refs=(checkpoint_ref,),
        )

    with pytest.raises(VerifierCompilationError, match="primary fatal") as captured:
        await compiler._supervise_capacity_batches(  # noqa: SLF001
            lineage_id="grace",
            design_ref=design_ref,
            world_spec_ref=world_ref,
            jobs=(primary_fatal(), grace_sibling()),
            active_invocations={0: set(), 1: set()},
            batch_accounting=accounting,
            turn_token_upper_bounds={0: 111, 1: 222},
        )

    assert captured.value.invocation_results == (sibling_result,)
    assert captured.value.unknown_token_upper_bounds == (222,)
    assert captured.value.checkpoint_refs == (checkpoint_ref,)


@pytest.mark.asyncio
async def test_verifier_supervisor_keeps_prior_turn_accounting_when_cancelled_between_turns(
    tmp_path: Path,
) -> None:
    store = ArtifactStore(tmp_path / "between-turn-accounting-artifacts")
    seed_writer = store.issue_writer(
        producer="test-seed",
        allowed_artifact_type_prefixes=("test.",),
    )
    judge_writer = store.issue_writer(
        producer="environment-judge",
        allowed_artifact_type_prefixes=("judge.",),
    )
    design_ref = seed_writer.put_json(
        artifact_id="between-turn:design",
        artifact_type="test.design",
        value={"kind": "design"},
    )
    world_ref = seed_writer.put_json(
        artifact_id="between-turn:world",
        artifact_type="test.world",
        value={"kind": "world"},
    )
    checkpoint_ref = judge_writer.put_json(
        artifact_id="between-turn:checkpoint",
        artifact_type="judge.verifier_intent_checkpoint",
        value={"batch_index": 1},
        dependencies=(design_ref, world_ref),
    )

    class NoopBackend:
        async def invoke(self, request: object) -> object:
            raise AssertionError("supervisor contract test does not invoke an Agent")

        async def cancel(self, invocation_id: str) -> bool:
            raise AssertionError("there is no active invocation between Agent turns")

    compiler = VerifierCompiler(
        artifact_store=judge_writer,
        invocation_backend=NoopBackend(),  # type: ignore[arg-type]
        profile_provider=object(),  # type: ignore[arg-type]
        batch_failure_grace_seconds=0,
        cancellation_timeout_seconds=0.2,
    )
    accounting = {
        index: verifier_compiler_module._VerifierBatchAccounting()  # noqa: SLF001
        for index in range(2)
    }
    prior_turn_recorded = asyncio.Event()
    prior_result = _invocation_result("inv-prior-turn")

    async def primary_fatal() -> tuple[VerifierDraft, tuple[InvocationResult, ...], ArtifactRef]:
        await prior_turn_recorded.wait()
        raise VerifierCompilationError("primary fatal between turns")

    async def between_turns() -> tuple[VerifierDraft, tuple[InvocationResult, ...], ArtifactRef]:
        accounting[1].record_result(prior_result)
        accounting[1].record_checkpoint(checkpoint_ref)
        prior_turn_recorded.set()
        await asyncio.Event().wait()
        raise AssertionError("cancelled batch must not resume")

    with pytest.raises(
        VerifierCompilationError,
        match="primary fatal between turns",
    ) as captured:
        await compiler._supervise_capacity_batches(  # noqa: SLF001
            lineage_id="between-turn",
            design_ref=design_ref,
            world_spec_ref=world_ref,
            jobs=(primary_fatal(), between_turns()),
            active_invocations={0: set(), 1: set()},
            batch_accounting=accounting,
            turn_token_upper_bounds={0: 111, 1: 222},
        )

    assert captured.value.invocation_results == (prior_result,)
    assert captured.value.unknown_token_upper_bounds == ()
    assert captured.value.checkpoint_refs == (checkpoint_ref,)


def test_verifier_merge_namespaces_capacity_batch_ids() -> None:
    draft = _draft(_design())

    merged = VerifierCompiler._merge_batch_drafts((draft, draft))

    assert len({case.case_id for case in merged.cases}) == len(merged.cases)
    assert len({prop.property_id for prop in merged.properties}) == len(merged.properties)
    assert len({recipe.recipe_id for recipe in merged.solve_recipes}) == len(merged.solve_recipes)
    case_ids = {case.case_id for case in merged.cases}
    assert all(set(prop.case_ids) <= case_ids for prop in merged.properties)


def test_verifier_error_aggregation_deduplicates_completed_evidence() -> None:
    result = _invocation_result("inv-global-validation")
    checkpoint_ref = _ref("checkpoint-global-validation")
    accounting = verifier_compiler_module._VerifierBatchAccounting()  # noqa: SLF001
    accounting.record_result(result)
    accounting.record_checkpoint(checkpoint_ref)

    accounting.absorb_error(
        VerifierCompilationError(
            "global validation rejected the merged draft",
            invocation_results=(result,),
            unknown_token_upper_bounds=(777,),
            checkpoint_refs=(checkpoint_ref,),
        )
    )

    snapshot = accounting.snapshot()
    assert snapshot.invocation_results == (result,)
    assert snapshot.checkpoint_refs == (checkpoint_ref,)
    assert snapshot.unknown_token_upper_bounds == (777,)


def test_design_rejects_agent_selected_partial_rule_coverage() -> None:
    design = _design()
    values = {name: getattr(design, name) for name in EnvironmentDesign.model_fields}
    values["verification"] = VerificationRequirements(
        required_rule_ids=("rule:transition",),
        required_property_families=("transition",),
    )

    with pytest.raises(ValueError, match="framework-complete Rule closure"):
        EnvironmentDesign(**values)


def test_judge_executes_transition_rules_even_without_assertion_selection() -> None:
    design = _design()
    tool = design.world_spec.tools[0]
    digest_before = "sha256:" + "1" * 64
    digest_after = "sha256:" + "2" * 64
    observation = RuntimeActionObservation(
        action_index=0,
        tool_id=tool.surface.tool_id,
        arguments={"amount": 3},
        idempotency_key="test-key",
        response_ok=True,
        result={},
        events=[],
        pre_snapshot={
            "observation": {"counter": {"value": 2}},
            "state_digest": digest_before,
        },
        snapshot={
            "observation": {"counter": {"value": 4}},
            "state_digest": digest_after,
        },
        state_digest=digest_after,
        reward=0,
        terminated=False,
        truncated=False,
    )
    invalid_transition = RuleExecutionContext(
        actor="user",
        pre_state={"counter": {"value": 2}},
        post_state={"counter": {"value": 4}},
        args={"amount": 3},
        tool_result={"value": 4},
        error=None,
        observation={"counter": {"value": 4}},
        events=[],
        reset_config={"initial": 2},
        task_goal={"target": 5},
        seed=42,
        terminated=False,
        truncated=False,
    )

    with pytest.raises(ValueError, match="transition Rules"):
        EnvironmentJudge._validate_tool_semantics(
            observation,
            invalid_transition,
            tool,
            design,
            design_rule_index(design),
        )


def test_compiler_requires_negative_case_for_sensitive_rule() -> None:
    design = _design(transition_sensitivity="positive_and_negative")

    with pytest.raises(ValueError, match="positive and negative"):
        VerifierCompiler._validate_draft(_draft(design), design)


def test_sealed_verifier_projection_persists_no_seed_action_or_expected_value() -> None:
    design = _design()
    draft = _draft(design)
    verifier = VerifierIR(
        verifier_ir_id="verifier:counter",
        revision=1,
        world_spec_ref=_ref("world"),
        design_ref=_ref("design"),
        properties=draft.properties,
        cases=draft.cases,
        solve_recipes=draft.solve_recipes,
    )

    serialized = json.dumps(verifier.persistence_projection().model_dump(mode="json"))

    assert "9999999999" not in serialized
    assert "case:sealed" not in serialized
    assert '"amount": 3' in serialized  # the public case remains auditable
    assert '"amount": {"kind"' not in serialized
    assert "public_goal" not in serialized
    assert verifier.persistence_projection().sealed_case_count == 1
    assert verifier.persistence_projection().solve_recipe_count == 1


def test_reward_is_recomputed_from_rules_not_runtime_number() -> None:
    design = _design()
    context = RuleExecutionContext(
        actor="user",
        pre_state={"counter": {"value": 7}},
        post_state={"counter": {"value": 10}},
        args={"amount": 3},
        tool_result={"value": 10},
        error=None,
        observation={"counter": {"value": 10}},
        events=[],
        reset_config={},
        task_goal={"target": 10},
        seed=42,
        terminated=True,
        truncated=False,
    )

    reward = evaluate_task_reward(design, "increase", context)

    assert reward.reward == 1
    assert reward.terminated
    assert reward.succeeded


def test_duplicate_success_rules_cannot_amplify_task_reward() -> None:
    design = _design()
    task = design.curriculum.task_types[0]
    duplicate = task.success_conditions[0].model_copy(
        update={"rule_id": "rule:task:increase:success-equivalent"}
    )
    revised_task = task.model_copy(
        update={"success_conditions": (*task.success_conditions, duplicate)}
    )
    revised = design.model_copy(
        update={
            "curriculum": design.curriculum.model_copy(update={"task_types": (revised_task,)}),
            "reward": design.reward.model_copy(
                update={"success_rule_ids": (*design.reward.success_rule_ids, duplicate.rule_id)}
            ),
        }
    )
    context = RuleExecutionContext(
        actor="user",
        pre_state={"counter": {"value": 7}},
        post_state={"counter": {"value": 10}},
        args={"amount": 3},
        tool_result={"value": 10},
        error=None,
        observation={"counter": {"value": 10}},
        events=[],
        reset_config={},
        task_goal={"target": 10},
        seed=42,
        terminated=False,
        truncated=False,
    )

    reward = evaluate_task_reward(revised, "increase", context)

    assert reward.reward == 1.0
    assert reward.succeeded and not reward.failed


def test_failure_has_fixed_precedence_when_success_and_failure_both_match() -> None:
    design = _design()
    task = design.curriculum.task_types[0]
    matching_failure = task.success_conditions[0].model_copy(
        update={
            "rule_id": "rule:task:increase:failure-conflict",
            "family": "task_failure",
        }
    )
    revised_task = task.model_copy(update={"failure_conditions": (matching_failure,)})
    revised = design.model_copy(
        update={
            "curriculum": design.curriculum.model_copy(update={"task_types": (revised_task,)}),
            "reward": design.reward.model_copy(
                update={"failure_rule_ids": (matching_failure.rule_id,)}
            ),
        }
    )
    context = RuleExecutionContext(
        actor="user",
        pre_state={"counter": {"value": 7}},
        post_state={"counter": {"value": 10}},
        args={"amount": 3},
        tool_result={"value": 10},
        error=None,
        observation={"counter": {"value": 10}},
        events=[],
        reset_config={},
        task_goal={"target": 10},
        seed=42,
        terminated=False,
        truncated=False,
    )

    reward = evaluate_task_reward(revised, "increase", context)

    assert reward.reward == -1.0
    assert reward.failed and not reward.succeeded


def test_design_rejects_task_actor_without_required_tool_permission() -> None:
    payload = _design().model_dump(mode="python")
    payload["curriculum"]["task_types"][0]["allowed_actor_ids"] = ("auditor",)

    with pytest.raises(ValueError, match="allows actors without permission"):
        EnvironmentDesign.model_validate(payload)


def test_world_requires_complete_actor_specific_tool_observation_projections() -> None:
    payload = _design().world_spec.model_dump(mode="python")
    del payload["tools"][0]["semantics"]["observation"]["visible_fields_by_actor"]["auditor"]
    del payload["tools"][0]["semantics"]["observation"]["redacted_fields_by_actor"]["auditor"]

    with pytest.raises(ValueError, match="omits actor projections"):
        WorldSpec.model_validate(payload)


def test_world_rejects_reset_visibility_outside_root_state_schema() -> None:
    payload = _design().world_spec.model_dump(mode="python")
    payload["boundary"]["actors_and_authority"][1]["visibility"] = ("private",)

    with pytest.raises(ValueError, match="reset visibility references unknown root fields"):
        WorldSpec.model_validate(payload)


def test_judge_actor_projection_preserves_root_schema_definitions() -> None:
    schema = {
        "$defs": {
            "visible_resource": {
                "type": "object",
                "additionalProperties": False,
                "properties": {"resource_id": {"type": "string"}},
                "required": ["resource_id"],
            }
        },
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "resources": {
                "type": "array",
                "items": {"$ref": "#/$defs/visible_resource"},
            },
            "private": {"type": "string"},
        },
        "required": ["resources", "private"],
    }

    EnvironmentJudge._validate_actor_projection(  # noqa: SLF001
        {"resources": [{"resource_id": "resource-1"}]},
        schema=schema,
        visible_fields=("resources",),
        label="reset observation",
    )

    with pytest.raises(
        ValueError,
        match=r"violates actor-projected.*?/resources/0:required_missing=resource_id",
    ):
        EnvironmentJudge._validate_actor_projection(  # noqa: SLF001
            {"resources": [{}]},
            schema=schema,
            visible_fields=("resources",),
            label="reset observation",
        )


def test_judge_reserves_every_real_success_path_episode() -> None:
    design = _design()
    draft = _draft(design)
    verifier = VerifierIR(
        verifier_ir_id="verifier:counter",
        revision=1,
        world_spec_ref=_ref("world"),
        design_ref=_ref("design"),
        properties=draft.properties,
        cases=draft.cases,
    )

    assert (
        EnvironmentJudge.required_evaluation_episodes(
            design=design,
            verifier=verifier,
        )
        == 18
    )
