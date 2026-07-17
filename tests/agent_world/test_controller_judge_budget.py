from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import HttpUrl, JsonValue

from agent_world.app import build_application
from agent_world.artifact_store import ArtifactStore
from agent_world.config import AgentBackendConfig, FoundryConfig, ResearchConfig
from agent_world.contracts import (
    ArtifactRef,
    Budget,
    BudgetUsage,
    CurriculumRequirements,
    DifficultyDimension,
    EnvironmentDesign,
    EvaluatorGoalBinding,
    KeyValue,
    ParameterizedSolveRecipe,
    ParameterizedSolveStep,
    ReachabilityPolicy,
    RecipeLiteral,
    Rule,
    RuleClause,
    RuleValueRef,
    RuntimeAction,
    TaskRequirement,
    VerificationRequirements,
    VerifierAssertion,
    VerifierCase,
    VerifierIR,
    VerifierProperty,
    sha256_digest,
)
from agent_world.control import BudgetExceeded, BudgetLease, BudgetLedger
from agent_world.controller import _RunState
from agent_world.invocation import (
    InvocationResult,
    InvocationStatus,
    InvocationUsage,
    TokenBreakdown,
)
from agent_world.judge import EnvironmentJudge


def _ref(name: str) -> ArtifactRef:
    digest = sha256_digest(name.encode())
    return ArtifactRef(
        artifact_id=name,
        revision_id=digest,
        artifact_type="test.contract",
        content_hash=digest,
        media_type="application/json",
        size_bytes=0,
    )


def _goal_rule(task_type: str, family: str) -> Rule:
    return Rule(
        rule_id=f"rule:{task_type}:{family}",
        family=family,  # type: ignore[arg-type]
        description="The counter reaches the framework-projected public target.",
        boolean_operator="all",
        case_sensitivity="positive_only",
        clauses=(
            RuleClause(
                clause_id=f"clause:{task_type}:{family}",
                left=RuleValueRef(
                    source="post_state",
                    pointer="/counter/value",
                    value_type="number",
                ),
                operator="greater_or_equal",
                right=RuleValueRef(
                    source="task_goal",
                    pointer="/target",
                    value_type="number",
                ),
            ),
        ),
    )


def _task(task_type: str, policy: ReachabilityPolicy | None = None) -> TaskRequirement:
    closed_goal: dict[str, JsonValue] = {
        "type": "object",
        "properties": {"target": {"type": "integer"}},
        "required": ["target"],
        "additionalProperties": False,
    }
    return TaskRequirement(
        task_type=task_type,
        objective=f"Reach the {task_type} counter target.",
        allowed_actor_ids=("user",),
        required_tool_ids=("counter.increment",),
        success_conditions=(_goal_rule(task_type, "task_success"),),
        terminal_conditions=(_goal_rule(task_type, "task_terminal"),),
        initial_config_schema={
            "type": "object",
            "properties": {"initial": {"type": "integer"}},
            "required": ["initial"],
            "additionalProperties": False,
        },
        public_goal_schema=closed_goal,
        evaluator_goal_schema=closed_goal,
        evaluator_goal_bindings=(
            EvaluatorGoalBinding(
                binding_id=f"binding:{task_type}:target",
                public_pointer="/target",
                evaluator_pointer="/target",
            ),
        ),
        difficulty_dimensions=("scale",),
        reachability_policy=policy or ReachabilityPolicy(),
    )


def _design(second_policy: ReachabilityPolicy | None = None) -> EnvironmentDesign:
    curriculum = CurriculumRequirements(
        task_types=(
            _task("increase"),
            _task("restore", second_policy),
        ),
        difficulty_dimensions=(
            DifficultyDimension(
                dimension="scale",
                description="Distance from the target.",
                levels=("small", "large"),
            ),
        ),
        generation_seed_space="all uint64 seeds",
    )
    verification = VerificationRequirements(
        required_rule_ids=("rule:increase:task_success",),
    )
    # required_evaluation_budget is deliberately a pure compiler over these two
    # validated branches; the unrelated WorldSpec fields are not part of this unit.
    return EnvironmentDesign.model_construct(
        curriculum=curriculum,
        verification=verification,
    )


def _verifier() -> VerifierIR:
    cases = tuple(
        VerifierCase(
            case_id=f"case:{task_type}",
            partition=partition,  # type: ignore[arg-type]
            task_type=task_type,
            evaluator_goal={"target": 3},
            seed=index,
            actor="user",
            reset_config={"initial": 0},
            actions=(
                RuntimeAction(
                    tool_id="counter.increment",
                    arguments={"amount": 3},
                ),
            ),
            assertions=(
                VerifierAssertion(
                    assertion_id=f"assertion:{task_type}",
                    rule_id=f"rule:{task_type}:task_success",
                    action_index=0,
                    expected=True,
                ),
            ),
        )
        for index, (task_type, partition) in enumerate(
            (("increase", "public"), ("restore", "sealed")),
            start=1,
        )
    )
    return VerifierIR(
        verifier_ir_id="verifier:two-task-budget",
        revision=1,
        world_spec_ref=_ref("world:two-task"),
        design_ref=_ref("design:two-task"),
        properties=(
            VerifierProperty(
                property_id="property:task-success",
                kind="task_success",
                rule_ids=(
                    "rule:increase:task_success",
                    "rule:restore:task_success",
                ),
                case_ids=tuple(case.case_id for case in cases),
                description="Both task types must reach their projected goal.",
            ),
        ),
        cases=cases,
        solve_recipes=tuple(
            ParameterizedSolveRecipe(
                recipe_id=f"recipe:{task_type}",
                task_type=task_type,
                preferred=True,
                steps=tuple(
                    ParameterizedSolveStep(
                        step_id=f"step:{task_type}:{index}",
                        tool_id="counter.increment",
                        arguments={"amount": RecipeLiteral(value=1)},
                    )
                    for index in range(16)
                ),
            )
            for task_type in ("increase", "restore")
        ),
    )


def _config(tmp_path: Path) -> FoundryConfig:
    return FoundryConfig(
        state_root=tmp_path,
        agent=AgentBackendConfig(
            model="configured-real-model",
            api_key_environment="AGENT_WORLD_TEST_MODEL_KEY",
        ),
        research=ResearchConfig(
            provider="searxng",
            searxng_base_url=HttpUrl("http://127.0.0.1:18080"),
            searxng_allow_private_endpoint=True,
            use_jina_reader_fallback=False,
        ),
    )


def _judge(tmp_path: Path) -> EnvironmentJudge:
    store = ArtifactStore(tmp_path / "judge-budget-artifacts")
    return EnvironmentJudge(
        artifact_store=store.issue_writer(
            producer="environment-judge",
            allowed_artifact_types=("judge_report",),
            allowed_artifact_type_prefixes=("judge.",),
        )
    )


def _invocation_result(
    invocation_id: str,
    *,
    total_tokens: int | None,
) -> InvocationResult:
    usage = (
        None
        if total_tokens is None
        else InvocationUsage(turn=TokenBreakdown(total_tokens=total_tokens))
    )
    return InvocationResult(
        invocation_id=invocation_id,
        status=InvocationStatus.COMPLETED,
        session=None,
        turn_id=f"turn:{invocation_id}",
        final_text="completed",
        structured_output=None,
        usage=usage,
        events=(),
        error=None,
        duration_ms=1,
    )


def test_normal_agent_turns_do_not_consume_repair_and_unknown_tokens_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "AGENT_WORLD_TEST_MODEL_KEY",
        "controller-invocation-usage-test-credential-canary",
    )
    app = build_application(_config(tmp_path))
    cap = 12_000

    usage = app.controller._invocation_usage(  # noqa: SLF001
        (
            _invocation_result("known", total_tokens=2_000),
            _invocation_result("unknown", total_tokens=None),
        ),
        unknown_token_cap=cap,
        base_turns=2,
    )

    assert usage.agent_turns == 2
    assert usage.llm_tokens == cap
    assert usage.repair_attempts == 0

    corrected = app.controller._invocation_usage(  # noqa: SLF001
        (
            _invocation_result("batch-1", total_tokens=1_000),
            _invocation_result("batch-2", total_tokens=1_000),
            _invocation_result("batch-1-correction", total_tokens=1_000),
        ),
        unknown_token_cap=cap,
        base_turns=2,
    )
    # Invocation cardinality cannot prove that a correction was authorized;
    # RepairLedger is the sole repair-attempt accountant.
    assert corrected.repair_attempts == 0


def test_judge_root_cause_fingerprint_is_stable_across_candidate_revisions() -> None:
    evidence = _ref("runtime-evidence")
    first = EnvironmentJudge._finding(  # noqa: SLF001
        "run:one",
        "runtime_protocol",
        _ref("candidate:one"),
        evidence,
        owner="build",
        summary="Runtime reset returned an invalid state envelope.",
        suggested_repair="Repair the runtime protocol implementation.",
    )
    second = EnvironmentJudge._finding(  # noqa: SLF001
        "run:two",
        "runtime_protocol",
        _ref("candidate:two"),
        _ref("runtime-evidence-two"),
        owner="build",
        summary="  Runtime RESET returned an invalid state envelope. ",
        suggested_repair="Repair the runtime protocol implementation.",
    )

    assert first.fingerprint == second.fingerprint
    assert first.finding_id != second.finding_id


def test_default_budget_covers_canonical_two_task_reachability(tmp_path: Path) -> None:
    available = _config(tmp_path).generation_budget
    required = _judge(tmp_path).required_evaluation_budget(
        design=_design(),
        verifier=_verifier(),
        available=available,
    )

    assert required.llm_tokens == 40_960
    assert required.agent_turns == 80
    assert required.tool_calls == 356
    assert required.evaluation_episodes == 37
    assert required.build_seconds == 300
    for dimension in type(required).model_fields:
        if dimension != "schema_version":
            assert getattr(required, dimension) <= getattr(available, dimension)


def test_budget_compiler_aggregates_each_task_policy_independently(tmp_path: Path) -> None:
    available = _config(tmp_path).generation_budget
    required = _judge(tmp_path).required_evaluation_budget(
        design=_design(
            ReachabilityPolicy(
                random_tail_samples=0,
                maximum_steps_per_attempt=8,
                maximum_agent_turns_per_attempt=4,
                maximum_llm_tokens_per_attempt=2_048,
            )
        ),
        verifier=_verifier(),
        available=available,
    )

    assert required.llm_tokens == 28_672
    assert required.agent_turns == 56
    assert required.tool_calls == 260
    assert required.evaluation_episodes == 34


def test_controller_persists_and_fail_closed_settles_judge_leases(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "AGENT_WORLD_TEST_MODEL_KEY",
        "controller-judge-budget-test-credential-canary",
    )
    app = build_application(_config(tmp_path))
    requested = Budget(
        llm_tokens=4_096,
        agent_turns=8,
        tool_calls=16,
        evaluation_episodes=4,
        container_seconds=30,
        wall_seconds=60,
    )

    success_job = app.controller.artifacts.put_json(
        artifact_id="job:judge-lease-success",
        artifact_type="control.test_job",
        value=KeyValue(key="kind", value="judge-lease-success"),
    )
    success_run = _RunState(
        run_id="run:judge-lease-success",
        job_ref=success_job,
        ledger=BudgetLedger(requested),
    )
    success_work = app.controller._reserve_judge_work(  # noqa: SLF001
        success_run,
        attempt_id="attempt:judge:success",
        requested=requested,
    )
    active = app.artifacts.get_json(success_work.lease_ref, BudgetLease)
    assert active.status == "active"
    actual = BudgetUsage(
        llm_tokens=1_024,
        agent_turns=2,
        tool_calls=3,
        evaluation_episodes=2,
        container_seconds=4,
    )
    settled_ref = app.controller._settle_judge_work(  # noqa: SLF001
        success_run,
        success_work,
        actual,
    )
    settled = app.artifacts.get_json(settled_ref, BudgetLease)
    assert settled.status == "settled"
    assert settled.observed_actual == actual
    assert settled.unknown_upper_bound == BudgetUsage()
    assert settled.conservative_committed == actual
    assert success_run.ledger.used == actual
    assert success_work.lease_ref in app.artifacts.dependencies(settled_ref)

    failed_job = app.controller.artifacts.put_json(
        artifact_id="job:judge-lease-unknown",
        artifact_type="control.test_job",
        value=KeyValue(key="kind", value="judge-lease-unknown"),
    )
    failed_run = _RunState(
        run_id="run:judge-lease-unknown",
        job_ref=failed_job,
        ledger=BudgetLedger(requested),
    )
    failed_work = app.controller._reserve_judge_work(  # noqa: SLF001
        failed_run,
        attempt_id="attempt:judge:unknown",
        requested=requested,
    )
    charged = app.controller._settle_failed_judge_work(  # noqa: SLF001
        failed_run,
        failed_work,
    )
    assert charged == BudgetUsage(
        llm_tokens=requested.llm_tokens,
        agent_turns=requested.agent_turns,
        tool_calls=requested.tool_calls,
        evaluation_episodes=requested.evaluation_episodes,
        container_seconds=requested.container_seconds,
        wall_seconds=0,
    )
    assert failed_run.ledger.used == charged
    failed_settled_ref = failed_run.latest[failed_work.lease_ref.artifact_id]
    failed_settled = app.artifacts.get_json(failed_settled_ref, BudgetLease)
    assert failed_settled.status == "settled"
    assert failed_settled.observed_actual == BudgetUsage()
    assert failed_settled.unknown_upper_bound == charged
    assert failed_settled.conservative_committed == charged
    assert failed_work.lease_ref in app.artifacts.dependencies(failed_settled_ref)

    zero_time = Budget(evaluation_episodes=1)
    zero_time_run = _RunState(
        run_id="run:judge-lease-zero-time",
        job_ref=failed_job,
        ledger=BudgetLedger(zero_time),
    )
    with pytest.raises(BudgetExceeded) as captured:
        app.controller._reserve_judge_work(  # noqa: SLF001
            zero_time_run,
            attempt_id="attempt:judge:zero-time",
            requested=zero_time,
        )
    assert captured.value.dimensions == ("container_seconds", "wall_seconds")
