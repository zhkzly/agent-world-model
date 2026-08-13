from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Literal

import pytest

import agent_world.runtime as runtime_module
from agent_world.contracts import (
    ArtifactRef,
    AssuranceRecipe,
    CurriculumFamily,
    DifficultyDimension,
    DifficultyLevel,
    DifficultySchema,
    EffectDraft,
    EvaluatorGoalBinding,
    ExecutableTaskContract,
    FieldDeclaration,
    PredicateDraft,
    RewardSpec,
    RuleDraft,
    SemanticBinding,
    TaskRequirement,
    TerminationSpec,
    ToolDraft,
    ToolSurface,
    VerificationRequirements,
    compile_difficulty_schema,
    digest_value,
    json_value,
    validate_difficulty_selection,
)
from agent_world.design import _local_rules_digest
from agent_world.runtime import (
    CandidateProcess,
    CandidateRuntimeError,
    MaterializationRequest,
    PrivateVerifierCase,
    _rule_matches,
    _task_outcome,
    integrate,
    judge,
    materialize,
)


@dataclass(frozen=True)
class RuntimeContracts:
    recipes: tuple[AssuranceRecipe, ...]
    tasks: tuple[ExecutableTaskContract, ...]
    schemas: tuple[DifficultySchema, ...]
    tools: tuple[ToolDraft, ...]
    families: tuple[CurriculumFamily, ...]


def _ref(name: str) -> ArtifactRef:
    return ArtifactRef(name, f"test.{name}", "sha256:" + "a" * 64, f"{name}.json")


def _tool(surface: ToolSurface, shared_digest: str) -> ToolDraft:
    bindings = (
        SemanticBinding(1, "argument", "request_id", ("arguments", "request_id")),
        SemanticBinding(2, "tool_result", "status", ("result", "status")),
        SemanticBinding(
            3,
            "pre_state",
            "status",
            ("pre_state", "tools", surface.name, "status"),
        ),
        SemanticBinding(
            4,
            "post_state",
            "status",
            ("post_state", "tools", surface.name, "status"),
        ),
    )
    preconditions = (RuleDraft((), (EffectDraft(2, "set", "ok"),), None, "result exists", (1,)),)
    transitions = (RuleDraft((), (EffectDraft(4, "set", "ok"),), None, "state updates", (1,)),)
    local_digest = _local_rules_digest(
        surface.tool_index,
        bindings,
        preconditions,
        transitions,
        (),
        (),
        shared_digest,
    )
    return ToolDraft(
        surface.tool_index,
        surface,
        bindings,
        preconditions,
        transitions,
        (),
        (),
        shared_digest,
        local_digest,
    )


def _task_rule(binding_index: int, value: str = "ok") -> RuleDraft:
    return RuleDraft(
        (PredicateDraft(binding_index, "eq", {"kind": "literal", "value": value}),),
        (),
        None,
        "the scoped tool completed",
        (1,),
    )


def _runtime_contracts() -> RuntimeContracts:
    request_id = FieldDeclaration("request_id", "identifier", True)
    status = FieldDeclaration("status", "text", True)
    surfaces = (
        ToolSurface(1, "create", "create a record", (1,), (request_id,), (status,)),
        ToolSurface(2, "close", "close a record", (1,), (request_id,), (status,)),
    )
    shared_digest = digest_value({"tools": [1, 2]})
    tools = tuple(_tool(surface, shared_digest) for surface in surfaces)
    schemas = (
        compile_difficulty_schema(
            "resolve-record",
            (
                DifficultyDimension(
                    "urgency",
                    "how urgent the record is",
                    (DifficultyLevel("low", "normal"), DifficultyLevel("high", "urgent")),
                ),
            ),
        ),
        compile_difficulty_schema(
            "close-record",
            (
                DifficultyDimension(
                    "volume",
                    "how many records are involved",
                    (DifficultyLevel("one", "one"), DifficultyLevel("many", "many")),
                ),
            ),
        ),
    )
    families = (
        CurriculumFamily(
            1,
            "resolve-record",
            "resolve a support record",
            1,
            (1, 2),
            schemas[0],
            "sample urgency",
            (1,),
        ),
        CurriculumFamily(
            2,
            "close-record",
            "close a support record",
            1,
            (2,),
            schemas[1],
            "sample volume",
            (1,),
        ),
    )
    requirements = (
        TaskRequirement(1, (1,), (), (_task_rule(2),), (), (_task_rule(2),), _ref("task-1")),
        TaskRequirement(2, (5,), (), (_task_rule(6),), (), (_task_rule(6),), _ref("task-2")),
    )
    recipes: list[AssuranceRecipe] = []
    for family, requirement in zip(families, requirements, strict=True):
        primary = tuple(
            (dimension.name, dimension.levels[0].name)
            for dimension in family.difficulty_schema.dimensions
        )
        alternate = tuple(
            (dimension.name, dimension.levels[1].name)
            for dimension in family.difficulty_schema.dimensions
        )
        task_digest = digest_value(
            {"task_requirement": json_value(requirement), "family": json_value(family)}
        )
        for tool_index in family.tool_indexes:
            payload = {
                "task_family_index": family.task_family_index,
                "tool_index": tool_index,
                "task_digest": task_digest,
                "difficulty_digest": family.difficulty_schema.schema_digest,
                "tool_digest": tools[tool_index - 1].local_rules_digest,
                "actor": "operator",
                "primary_difficulty": primary,
                "alternate_difficulty": alternate,
                "action_tool_indexes": family.tool_indexes,
            }
            recipes.append(
                AssuranceRecipe(
                    family.task_family_index,
                    tool_index,
                    task_digest,
                    family.difficulty_schema.schema_digest,
                    tools[tool_index - 1].local_rules_digest,
                    "operator",
                    primary,
                    alternate,
                    family.tool_indexes,
                    digest_value(payload),
                )
            )
    initial_schema = tuple(
        (f"/tools/{tool.tool_index}/{field.name}", field.category)
        for tool in surfaces
        for field in (*tool.argument_fields, *tool.result_fields)
    )
    tasks: list[ExecutableTaskContract] = []
    for family, requirement, public_index in zip(families, requirements, (1, 5), strict=True):
        public_schema = ((f"/goal/{public_index}", "identifier"),)
        verification = VerificationRequirements(
            family.task_family_index,
            True,
            tuple(
                recipe.recipe_digest
                for recipe in recipes
                if recipe.task_family_index == family.task_family_index
            ),
        )
        reward = RewardSpec()
        termination = TerminationSpec()
        tasks.append(
            ExecutableTaskContract(
                family.task_family_index,
                requirement,
                public_schema,
                initial_schema,
                (EvaluatorGoalBinding(public_schema[0][0], public_schema[0][0]),),
                digest_value({"objective": family.objective, "public_goal_schema": public_schema}),
                reward,
                digest_value(reward),
                termination,
                digest_value(termination),
                verification,
                digest_value(verification),
            )
        )
    return RuntimeContracts(tuple(recipes), tuple(tasks), schemas, tools, families)


_MATERIALIZER = """import json, sys
for line in sys.stdin:
    value = json.loads(line)
    if value.get('op') == 'materialize':
        family = value['task_type']
        goal_index = '1' if family == 'resolve-record' else '5'
        level = next(iter(value['difficulty'].values()))
        public_goal = {'goal': {goal_index: f\"{level}-{value['seed']}\"}}
        initial_config = {'tools': {
            '1': {'request_id': 'public-id', 'status': 'pending'},
            '2': {'request_id': 'public-id', 'status': 'pending'},
        }}
        out = {key: value[key] for key in ('seed', 'task_type', 'actor', 'difficulty')}
        out.update(public_goal=public_goal, initial_config=initial_config)
        # MATERIALIZER_MUTATION
        print(json.dumps(out), flush=True)
"""


_RUNTIME = """import json, sys
seen = {}
state = {'create': {'status': 'pending'}, 'close': {'status': 'pending'}}
for line in sys.stdin:
    value = json.loads(line)
    op = value.get('op')
    if op == 'handshake':
        out = {'operations': ['handshake', 'reset', 'invoke', 'snapshot', 'close']}
    elif op == 'reset':
        initial = value['initial_config']['tools']
        state = {
            'create': {'status': initial['1']['status']},
            'close': {'status': initial['2']['status']},
        }
        seen = {}
        out = {'status': 'ok'}
    elif op == 'invoke':
        tool_id = value['tool_id']
        state[tool_id]['status'] = 'ok'
        out = seen.setdefault(
            value['idempotency_key'], {'status': 'ok', 'result': {'status': 'ok'}}
        )
    elif op == 'snapshot':
        out = {'state': {'tools': state}}
    elif op == 'close':
        out = {'status': 'ok'}
        print(json.dumps(out), flush=True)
        break
    else:
        out = {'status': 'error'}
    print(json.dumps(out), flush=True)
"""


def _candidate(root: Path) -> None:
    (root / "materializer.py").write_text(_MATERIALIZER, encoding="utf-8")
    (root / "runtime.py").write_text(_RUNTIME, encoding="utf-8")


def _replace_source(path: Path, old: str, new: str) -> None:
    body = path.read_text(encoding="utf-8")
    assert old in body
    path.write_text(body.replace(old, new), encoding="utf-8")


def test_integration_and_judge_execute_every_typed_recipe(tmp_path: Path) -> None:
    _candidate(tmp_path)
    contracts = _runtime_contracts()

    integration = integrate(
        tmp_path,
        contracts.recipes,
        contracts.tasks,
        contracts.schemas,
        contracts.tools,
    )
    outcomes = judge(
        tmp_path,
        contracts.recipes,
        contracts.tasks,
        contracts.schemas,
        contracts.tools,
    )

    expected = [
        {
            "task_family_index": recipe.task_family_index,
            "tool_index": recipe.tool_index,
            "recipe_digest": recipe.recipe_digest,
        }
        for recipe in contracts.recipes
    ]
    assert integration == {"status": "passed", "code": "ok", "baseline_coverage": expected}
    assert [outcome["gate_id"] for outcome in outcomes] == [
        gate
        for recipe in contracts.recipes
        for gate in (
            f"task_materialization:{recipe.task_family_index}:{recipe.tool_index}",
            f"task_reachability:{recipe.task_family_index}:{recipe.tool_index}",
        )
    ]
    assert all(outcome["status"] == "passed" for outcome in outcomes)


@pytest.mark.parametrize(
    ("old", "new", "code"),
    [
        (
            "out = {'operations': ['handshake', 'reset', 'invoke', 'snapshot', 'close']}",
            "out = {}",
            "candidate_protocol_mismatch",
        ),
        (
            "out = {'operations': ['handshake', 'reset', 'invoke', 'snapshot', 'close']}",
            "out = {'operations': ['handshake', 'reset', 'invoke', 'snapshot', 'close'], "
            "'extra': True}",
            "candidate_protocol_mismatch",
        ),
        ("out = {'status': 'ok'}", "out = {}", "candidate_reset_rejected"),
        (
            "value['idempotency_key'], {'status': 'ok', 'result': {'status': 'ok'}}",
            "value['idempotency_key'], {'status': 'ok'}",
            "candidate_property_mismatch",
        ),
        ("out = {'state': {'tools': state}}", "out = {}", "candidate_snapshot_rejected"),
        (
            "out = {'state': {'tools': state}}",
            "out = {'state': {'tools': state}, 'extra': True}",
            "candidate_snapshot_rejected",
        ),
        (
            "out = {'status': 'ok'}\n        print(json.dumps(out), flush=True)\n        break",
            "out = {}\n        print(json.dumps(out), flush=True)\n        break",
            "candidate_close_rejected",
        ),
    ],
)
def test_runtime_rejects_missing_or_extra_protocol_fields(
    tmp_path: Path, old: str, new: str, code: str
) -> None:
    _candidate(tmp_path)
    _replace_source(tmp_path / "runtime.py", old, new)
    contracts = _runtime_contracts()

    result = integrate(
        tmp_path,
        contracts.recipes,
        contracts.tasks,
        contracts.schemas,
        contracts.tools,
    )

    assert result["status"] == "failed" and result["code"] == code


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        ("out['public_goal']['extra'] = 'x'", "materializer_public_goal_invalid"),
        ("out['initial_config']['extra'] = 'x'", "materializer_initial_config_invalid"),
        ("out['public_goal']['goal']['1'] = 4", "materializer_public_goal_invalid"),
    ],
)
def test_materializer_outputs_are_closed_and_typed(
    tmp_path: Path, mutation: str, code: str
) -> None:
    _candidate(tmp_path)
    _replace_source(tmp_path / "materializer.py", "# MATERIALIZER_MUTATION", mutation)
    contracts = _runtime_contracts()

    result = integrate(
        tmp_path,
        contracts.recipes,
        contracts.tasks,
        contracts.schemas,
        contracts.tools,
    )

    assert result["status"] == "failed" and result["code"] == code


@pytest.mark.parametrize(
    "bindings",
    [
        (),
        (EvaluatorGoalBinding("/goal/unbound", "/goal/unbound"),),
        (EvaluatorGoalBinding("/goal/1", "/goal/nonidentity"),),
    ],
)
def test_materializer_requires_complete_identity_goal_bindings(
    tmp_path: Path, bindings: tuple[EvaluatorGoalBinding, ...]
) -> None:
    _candidate(tmp_path)
    contracts = _runtime_contracts()
    tasks = (replace(contracts.tasks[0], evaluator_goal_bindings=bindings), contracts.tasks[1])

    result = integrate(
        tmp_path,
        contracts.recipes,
        tasks,
        contracts.schemas,
        contracts.tools,
    )

    assert result["status"] == "failed" and result["code"] == "evaluator_goal_binding_invalid"


def test_executable_task_rejects_duplicate_goal_bindings() -> None:
    task = _runtime_contracts().tasks[0]
    binding = task.evaluator_goal_bindings[0]
    with pytest.raises(ValueError, match="executable_task_invalid"):
        replace(task, evaluator_goal_bindings=(binding, binding))


@pytest.mark.parametrize(
    "pairs",
    [
        (),
        (("other", "low"),),
        (("urgency", "other"),),
        (("urgency", "low"), ("urgency", "high")),
    ],
)
def test_difficulty_selection_rejects_missing_extra_unknown_and_duplicate_pairs(
    pairs: tuple[tuple[str, str], ...],
) -> None:
    with pytest.raises(ValueError):
        validate_difficulty_selection(_runtime_contracts().schemas[0], pairs)


def test_reordered_selection_fails_before_materializer_launch(tmp_path: Path) -> None:
    schema = compile_difficulty_schema(
        "resolve-record",
        (
            DifficultyDimension(
                "urgency",
                "urgency",
                (DifficultyLevel("low", "low"), DifficultyLevel("high", "high")),
            ),
            DifficultyDimension(
                "scope",
                "scope",
                (DifficultyLevel("one", "one"), DifficultyLevel("many", "many")),
            ),
        ),
    )
    request = MaterializationRequest(
        7,
        "resolve-record",
        "operator",
        (("scope", "one"), ("urgency", "low")),
    )

    with pytest.raises(ValueError, match="difficulty_selection_order_invalid"):
        materialize(tmp_path, request, schema)


def test_materializer_echo_order_is_exact(tmp_path: Path) -> None:
    _candidate(tmp_path)
    _replace_source(
        tmp_path / "materializer.py",
        "out = {key: value[key] for key in ('seed', 'task_type', 'actor', 'difficulty')}",
        "out = {key: value[key] for key in ('task_type', 'seed', 'actor', 'difficulty')}",
    )
    contracts = _runtime_contracts()
    recipe = contracts.recipes[0]

    with pytest.raises(CandidateRuntimeError, match="materializer_echo_mismatch"):
        materialize(
            tmp_path,
            MaterializationRequest(
                7,
                contracts.schemas[0].task_family_id,
                recipe.actor,
                recipe.primary_difficulty,
            ),
            contracts.schemas[0],
        )


def _private_cases(contracts: RuntimeContracts) -> tuple[PrivateVerifierCase, ...]:
    first, second, third = contracts.recipes
    return (
        PrivateVerifierCase(
            "verifier-unknown-seed",
            1,
            1,
            "unknown_seed",
            first.recipe_digest,
            MaterializationRequest(991, "resolve-record", first.actor, first.primary_difficulty),
            {"request_id": "unknown-seed-id"},
            ("unknown-seed-key",),
        ),
        PrivateVerifierCase(
            "verifier-alternate-difficulty",
            1,
            1,
            "alternate_difficulty",
            first.recipe_digest,
            MaterializationRequest(7, "resolve-record", first.actor, first.alternate_difficulty),
            {"request_id": "alternate-id"},
            ("alternate-key",),
        ),
        PrivateVerifierCase(
            "verifier-idempotency-key",
            1,
            2,
            "idempotency_key_variation",
            second.recipe_digest,
            MaterializationRequest(7, "resolve-record", second.actor, second.primary_difficulty),
            {"request_id": "idempotent-id"},
            ("first-private-key", "second-private-key"),
        ),
        PrivateVerifierCase(
            "verifier-argument",
            2,
            2,
            "argument_variation",
            third.recipe_digest,
            MaterializationRequest(8, "close-record", third.actor, third.primary_difficulty),
            {"request_id": "varied-private-id"},
            ("argument-private-key",),
        ),
    )


def test_judge_executes_each_private_case_in_fresh_process_and_returns_safe_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _candidate(tmp_path)
    contracts = _runtime_contracts()
    cases = _private_cases(contracts)
    original_popen = runtime_module.subprocess.Popen
    processes: list[subprocess.Popen[str]] = []

    def recording_popen(*args: Any, **kwargs: Any) -> subprocess.Popen[str]:
        process = original_popen(*args, **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(runtime_module.subprocess, "Popen", recording_popen)
    outcomes = judge(
        tmp_path,
        contracts.recipes,
        contracts.tasks,
        contracts.schemas,
        contracts.tools,
        cases,
    )

    assert len(processes) == (len(contracts.recipes) + len(cases)) * 2
    assert len({process.pid for process in processes}) == len(processes)
    assert all(outcome["status"] == "passed" for outcome in outcomes)
    serialized = json.dumps(outcomes, sort_keys=True)
    for case in cases:
        assert all(key not in serialized for key in case.idempotency_keys)
        assert all(str(value) not in serialized for value in case.arguments.values())
    evidence_keys = {key for outcome in outcomes for key in (*outcome, *outcome["binding"])}
    assert evidence_keys.isdisjoint(
        {"public_goal", "initial_config", "snapshot", "result", "reward", "termination", "seed"}
    )


_RULE_BINDINGS = (
    SemanticBinding(1, "tool_result", "number", ("result", "number")),
    SemanticBinding(2, "tool_result", "text", ("result", "text")),
    SemanticBinding(3, "tool_result", "items", ("result", "items")),
    SemanticBinding(4, "tool_result", "missing", ("result", "missing")),
    SemanticBinding(5, "pre_state", "counter", ("pre_state", "tools", "create", "counter")),
    SemanticBinding(6, "post_state", "counter", ("post_state", "tools", "create", "counter")),
    SemanticBinding(7, "pre_state", "items", ("pre_state", "tools", "create", "items")),
    SemanticBinding(8, "post_state", "items", ("post_state", "tools", "create", "items")),
    SemanticBinding(9, "pre_state", "preserved", ("pre_state", "tools", "create", "preserved")),
    SemanticBinding(10, "post_state", "preserved", ("post_state", "tools", "create", "preserved")),
)


def _rule_trace() -> dict[str, Any]:
    return {
        "result": {"number": 5, "text": "hello", "items": ["a"]},
        "pre_state": {"tools": {"create": {"counter": 1, "items": ["a"], "preserved": "ok"}}},
        "post_state": {"tools": {"create": {"counter": 3, "items": ["a", "b"], "preserved": "ok"}}},
    }


@pytest.mark.parametrize(
    ("operator", "left", "right"),
    [
        ("eq", 1, {"kind": "literal", "value": 5}),
        ("ne", 1, {"kind": "literal", "value": 6}),
        ("lt", 1, {"kind": "literal", "value": 6}),
        ("le", 1, {"kind": "literal", "value": 5}),
        ("gt", 1, {"kind": "literal", "value": 4}),
        ("ge", 1, {"kind": "literal", "value": 5}),
        ("contains", 2, {"kind": "literal", "value": "ell"}),
        ("not_contains", 3, {"kind": "literal", "value": "b"}),
        ("exists", 1, {"kind": "literal", "value": None}),
        ("not_exists", 4, {"kind": "literal", "value": None}),
    ],
)
def test_rule_ir_supports_every_predicate(
    operator: Literal[
        "eq", "ne", "lt", "le", "gt", "ge", "contains", "not_contains", "exists", "not_exists"
    ],
    left: int,
    right: dict[str, object],
) -> None:
    rule = RuleDraft(
        (PredicateDraft(left, operator, right),),
        (EffectDraft(1, "set", 5),),
        None,
        "predicate coverage",
        (),
    )
    assert _rule_matches(rule, _RULE_BINDINGS, _rule_trace())


@pytest.mark.parametrize(
    "effect",
    [
        EffectDraft(1, "set", 5),
        EffectDraft(6, "increment", 2),
        EffectDraft(6, "decrement", 2),
        EffectDraft(8, "add", "b"),
        EffectDraft(8, "remove", "a"),
        EffectDraft(10, "preserve", None),
    ],
)
def test_rule_ir_supports_every_effect(effect: EffectDraft) -> None:
    trace = _rule_trace()
    post = trace["post_state"]["tools"]["create"]
    if effect.operation == "decrement":
        post["counter"] = -1
    elif effect.operation == "remove":
        post["items"] = []
    rule = RuleDraft((), (effect,), None, "effect coverage", ())
    assert _rule_matches(rule, _RULE_BINDINGS, trace)


def test_rule_ir_fails_closed_for_category_mismatch_and_reject() -> None:
    category = RuleDraft(
        (PredicateDraft(2, "contains", {"kind": "literal", "value": 1}),),
        (),
        None,
        "category mismatch",
        (),
    )
    rejected = RuleDraft((), (EffectDraft(1, "reject", None),), None, "reject", ())
    invalid_increment = RuleDraft(
        (), (EffectDraft(6, "increment", "two"),), None, "bad increment", ()
    )

    with pytest.raises(CandidateRuntimeError, match="rule_ir_category_mismatch"):
        _rule_matches(category, _RULE_BINDINGS, _rule_trace())
    with pytest.raises(CandidateRuntimeError, match="rule_ir_category_mismatch"):
        _rule_matches(invalid_increment, _RULE_BINDINGS, _rule_trace())
    assert not _rule_matches(rejected, _RULE_BINDINGS, _rule_trace())


def test_task_evaluator_uses_failure_precedence_and_exact_termination() -> None:
    contracts = _runtime_contracts()
    task = contracts.tasks[0]
    trace = {
        "argument": {"1": {"request_id": "public-id"}},
        "tool_result": {"1": {"status": "ok"}},
        "pre_state": {"1": {"status": "pending"}},
        "post_state": {"1": {"status": "ok"}},
    }
    assert _task_outcome(task, contracts.tools, trace) == (1, True)
    failed_requirement = replace(
        task.task_requirement,
        failure_rules=task.task_requirement.success_rules,
    )
    assert _task_outcome(
        replace(task, task_requirement=failed_requirement), contracts.tools, trace
    ) == (-1, True)
    unreachable_requirement = replace(
        task.task_requirement,
        success_rules=(_task_rule(2, "never"),),
        terminal_rules=(_task_rule(2, "never"),),
    )
    assert _task_outcome(
        replace(task, task_requirement=unreachable_requirement), contracts.tools, trace
    ) == (0, False)


def test_judge_requires_terminal_success_reward_plus_one(tmp_path: Path) -> None:
    _candidate(tmp_path)
    contracts = _runtime_contracts()
    first = contracts.tasks[0]
    requirement = replace(
        first.task_requirement,
        success_rules=(_task_rule(2, "never"),),
        terminal_rules=(_task_rule(2, "never"),),
    )
    tasks = (replace(first, task_requirement=requirement), contracts.tasks[1])

    outcomes = judge(
        tmp_path,
        contracts.recipes,
        tasks,
        contracts.schemas,
        contracts.tools,
    )

    failures = [
        outcome for outcome in outcomes if outcome["gate_id"].startswith("task_reachability:1:")
    ]
    assert failures
    assert all(
        outcome
        == {
            **outcome,
            "status": "failed",
            "code": "task_not_terminal_success_reward_plus_one",
        }
        for outcome in failures
    )


def test_candidate_process_uses_only_explicit_minimal_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _candidate(tmp_path)
    original_popen = runtime_module.subprocess.Popen
    environments: list[dict[str, str]] = []

    def recording_popen(*args: Any, **kwargs: Any) -> subprocess.Popen[str]:
        environment = kwargs.get("env")
        assert isinstance(environment, dict)
        environments.append(environment)
        return original_popen(*args, **kwargs)

    monkeypatch.setattr(runtime_module.subprocess, "Popen", recording_popen)
    with CandidateProcess(tmp_path, "runtime.py") as process:
        assert process.call({"op": "handshake"}) == {
            "operations": ["handshake", "reset", "invoke", "snapshot", "close"]
        }

    assert environments == [{"PATH": os.defpath}]


def test_runtime_requires_clean_teardown_after_close_ack(tmp_path: Path) -> None:
    _candidate(tmp_path)
    _replace_source(
        tmp_path / "runtime.py",
        "print(json.dumps(out), flush=True)\n        break",
        "print(json.dumps(out), flush=True)\n        sys.exit(2)",
    )
    contracts = _runtime_contracts()

    result = integrate(
        tmp_path,
        contracts.recipes,
        contracts.tasks,
        contracts.schemas,
        contracts.tools,
    )

    assert result["status"] == "failed" and result["code"] == "candidate_teardown_failed"
