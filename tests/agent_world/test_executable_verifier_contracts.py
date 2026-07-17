from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path

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
    EvaluatorGoalBinding,
    FidelityStatement,
    IdempotencySemantics,
    ObservationSemantics,
    ParameterizedSolveRecipe,
    ParameterizedSolveStep,
    PermissionRule,
    RecipePointer,
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
from agent_world.control import StructuredValidationError
from agent_world.invocation import InvocationResult, InvocationStatus
from agent_world.judge import compiler as verifier_compiler_module
from agent_world.judge.compiler import VerifierCompilationError, VerifierCompiler
from agent_world.judge.models import (
    PropertyExpectationIntent,
    RuntimeActionObservation,
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


def _design(*, transition_sensitivity: str = "positive_only") -> EnvironmentDesign:
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
        sensitivity="positive_and_negative",
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

    assert context["schema_version"] == "agent-world.challenger-context.v2"
    reset_config_schemas = context["reset_config_schemas"]
    assert isinstance(reset_config_schemas, list)
    assert len(reset_config_schemas) == 1
    assert '"clauses"' not in serialized
    assert '"evidence_claim_ids"' not in serialized
    assert '"rule:transition"' not in serialized
    assert '"property_kind": "transition"' in serialized
    assert '"rule_count"' in serialized
    assert "You have no tools" in VerifierCompiler._prompt(context)


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
    assert "one-based" in diagnostic.feedback
    assert "one-based" in VerifierCompiler._prompt({})


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
            process.terminate()
            await asyncio.wait_for(process.wait(), timeout=1)
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
