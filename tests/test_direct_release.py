from __future__ import annotations

import copy
import json
import os
import sys
import zipfile
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import replace
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from typing import Any

import pytest

import agent_world.candidate as candidate_module
from agent_world.artifacts import ArtifactStore
from agent_world.candidate import (
    CandidateError,
    CandidateExecutor,
    CandidateResult,
    _verify_package,
    compile_implementation_contract,
    validate_build_plan,
    validate_candidate_completion,
)
from agent_world.config import load_settings
from agent_world.contracts import (
    ArtifactRef,
    AssuranceRecipe,
    CitationCatalog,
    CitationCatalogItem,
    CurriculumFamily,
    CurriculumPlan,
    DesignContract,
    DifficultyDimension,
    DifficultyLevel,
    EffectDraft,
    EntityDeclaration,
    EvaluatorGoalBinding,
    EvidenceClaim,
    EvidenceGraph,
    ExecutableTaskContract,
    FieldDeclaration,
    OperationEvidence,
    PredicateDraft,
    RewardSpec,
    RuleDraft,
    SemanticBinding,
    SemanticCatalog,
    SharedToolContract,
    TaskRequirement,
    TerminationSpec,
    ToolCouplingPlan,
    ToolDraft,
    ToolSurface,
    VerificationRequirements,
    WorkCoordinate,
    WorkRecord,
    WorldArchitecture,
    WorldBoundary,
    WorldRuleSet,
    compile_difficulty_schema,
    digest_value,
    json_value,
)
from agent_world.design import _local_rules_digest
from agent_world.graph import NodeExecutionError, candidate_graph
from agent_world.invocation import InvocationResult
from agent_world.runtime import PrivateVerifierCase
from agent_world.supply_chain import (
    AdmittedLockClosure,
    AdmittedLockEntry,
    LockedWheel,
    PreparedCandidate,
)


def _artifact(store: ArtifactStore, name: str) -> ArtifactRef:
    return store.put_json(f"test.{name}", {"name": name})


def _catalog(surfaces: tuple[ToolSurface, ...]) -> tuple[SemanticBinding, ...]:
    bindings: list[SemanticBinding] = []
    for tool in surfaces:
        for source, fields in (
            ("argument", tool.argument_fields),
            ("tool_result", tool.result_fields),
            ("pre_state", tool.result_fields),
            ("post_state", tool.result_fields),
        ):
            for field in fields:
                bindings.append(
                    SemanticBinding(
                        len(bindings) + 1,
                        source,  # type: ignore[arg-type]
                        field.name,
                        (source, str(tool.tool_index), field.name),
                    )
                )
    return tuple(bindings)


def _task_rule(result_index: int) -> RuleDraft:
    return RuleDraft(
        (PredicateDraft(result_index, "eq", {"kind": "literal", "value": "ok"}),),
        (),
        None,
        "the scoped tool completed",
        (1,),
    )


def _design(store: ArtifactStore) -> DesignContract:
    citation = CitationCatalog(
        (CitationCatalogItem(1, "docs", "https://example.test/docs", "two-tool workflow"),)
    )
    evidence = EvidenceGraph(
        (EvidenceClaim("the workflow has create and close operations", "observed", (1,)),),
        (),
        ("external concurrency remains unproved",),
        citation,
        _artifact(store, "evidence"),
    )
    request_id = FieldDeclaration("request_id", "identifier", True)
    status = FieldDeclaration("status", "text", True)
    surfaces = (
        ToolSurface(1, "create", "create a record", (1,), (request_id,), (status,)),
        ToolSurface(2, "close", "close a record", (1,), (request_id,), (status,)),
    )
    architecture = WorldArchitecture(
        WorldBoundary(
            "support-records",
            "manage support records",
            "support-db",
            "operator",
            ("operator",),
        ),
        (EntityDeclaration("record", "a support record", (request_id, status)),),
        surfaces,
        (),
        SemanticCatalog(_catalog(surfaces)),
        ToolCouplingPlan(((1, 2),)),
        _artifact(store, "architecture"),
    )
    shared_payload = {
        "tool_indexes": [1, 2],
        "atomicity": [[1, 2]],
        "concurrency": [[1, 2]],
        "idempotency": [[1, 2]],
        "ordering": ["create precedes close"],
        "compensation": [],
        "error_policy": [
            {"tool_index": 1, "policy": "reject invalid create"},
            {"tool_index": 2, "policy": "reject invalid close"},
        ],
    }
    shared = SharedToolContract(
        (1, 2),
        ((1, 2),),
        ((1, 2),),
        ((1, 2),),
        ("create precedes close",),
        (),
        ((1, "reject invalid create"), (2, "reject invalid close")),
        digest_value(shared_payload),
        _artifact(store, "shared"),
    )
    tools: list[ToolDraft] = []
    for surface in surfaces:
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
        preconditions = (
            RuleDraft((), (EffectDraft(2, "set", "ok"),), None, "result is public", (1,)),
        )
        transitions = (
            RuleDraft((), (EffectDraft(4, "set", "ok"),), None, "state is updated", (1,)),
        )
        local_digest = _local_rules_digest(
            surface.tool_index,
            bindings,
            preconditions,
            transitions,
            (),
            (),
            shared.digest,
        )
        tools.append(
            ToolDraft(
                surface.tool_index,
                surface,
                bindings,
                preconditions,
                transitions,
                (),
                (),
                shared.digest,
                local_digest,
            )
        )
    world_rules = WorldRuleSet(
        (),
        (),
        digest_value({"initial_rules": (), "invariants": ()}),
        _artifact(store, "world-rules"),
    )
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
    curriculum = CurriculumPlan(families, _artifact(store, "curriculum"))
    requirements = (
        TaskRequirement(
            1,
            (1,),
            (),
            (_task_rule(2),),
            (),
            (_task_rule(2),),
            _artifact(store, "task-1"),
        ),
        TaskRequirement(
            2,
            (5,),
            (),
            (_task_rule(6),),
            (),
            (_task_rule(6),),
            _artifact(store, "task-2"),
        ),
    )
    recipe_values: list[AssuranceRecipe] = []
    for family, task in zip(families, requirements, strict=True):
        primary = tuple(
            (item.name, item.levels[0].name) for item in family.difficulty_schema.dimensions
        )
        alternate = tuple(
            (item.name, item.levels[1].name if index == 0 else item.levels[0].name)
            for index, item in enumerate(family.difficulty_schema.dimensions)
        )
        task_digest = digest_value(
            {"task_requirement": json_value(task), "family": json_value(family)}
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
            recipe_values.append(
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
    recipes = tuple(recipe_values)
    initial_schema = tuple(
        (f"/tools/{tool.tool_index}/{field.name}", field.category)
        for tool in surfaces
        for field in (*tool.argument_fields, *tool.result_fields)
    )
    executable: list[ExecutableTaskContract] = []
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
        executable.append(
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
    return DesignContract(
        evidence,
        architecture,
        (shared,),
        tuple(tools),
        world_rules,
        curriculum,
        requirements,
        tuple(executable),
        recipes,
        _artifact(store, "design"),
    )


def _candidate_files(root: Path) -> None:
    (root / "materializer.py").write_text("# candidate materializer\n", encoding="utf-8")
    (root / "runtime.py").write_text("# candidate runtime\n", encoding="utf-8")
    (root / "pyproject.toml").write_text(
        "[project]\nname = 'candidate'\nversion = '0'\ndependencies = []\n",
        encoding="utf-8",
    )
    (root / "uv.lock").write_text("version = 1\n", encoding="utf-8")
    (root / "LICENSE").write_text("unknown\n", encoding="utf-8")


@contextmanager
def _prepared_candidate(*_: object):
    yield PreparedCandidate(Path(sys.executable), AdmittedLockClosure(()))


def _plan() -> dict[str, object]:
    return {
        "steps": [
            {
                "goal": "Implement every family and tool in the process ABI.",
                "suggested_paths": ["materializer.py", "runtime.py"],
                "contract_sections": ["materializer", "runtime", "tool_semantics"],
                "self_check": "Review all ordered request and response fields.",
            }
        ],
        "risks": ["Keep framework authority out of candidate source."],
    }


def _completion() -> dict[str, object]:
    return {
        "summary": "Wrote the bounded candidate source closure.",
        "self_checks": [
            {"name": "protocol", "observed": "passed", "note": "Five operations exist."}
        ],
        "known_limits": ["No third-party dependency is required."],
    }


def _passed_work(
    store: ArtifactStore,
    run_id: str,
    graph_id: str,
    node_id: str,
    evidence: tuple[OperationEvidence, ...],
) -> ArtifactRef:
    validation = store.put_json("control.validation", {"status": "passed", "node": node_id})
    output = store.put_json("test.output", {"node": node_id})
    assurances = tuple(store.put_json("assurance.operation", item) for item in evidence)
    return store.put_work_record(
        WorkRecord(
            WorkCoordinate(run_id, graph_id, node_id, None, 1),  # type: ignore[arg-type]
            "designer" if graph_id == "design" else "builder",
            "framework",
            "sha256:" + "e" * 64,
            (),
            (),
            (output,),
            validation,
            assurances,
            (),
            "passed",
        )
    )


def _integration_value(design: DesignContract) -> dict[str, Any]:
    return {
        "status": "passed",
        "code": "ok",
        "baseline_coverage": [
            {
                "task_family_index": recipe.task_family_index,
                "tool_index": recipe.tool_index,
                "recipe_digest": recipe.recipe_digest,
            }
            for recipe in design.assurance_recipes
        ],
    }


def _judge_outcomes(
    recipes: tuple[AssuranceRecipe, ...], cases: tuple[PrivateVerifierCase, ...]
) -> tuple[dict[str, Any], ...]:
    outcomes: list[dict[str, Any]] = []
    for recipe in recipes:
        binding = {
            "task_family_index": recipe.task_family_index,
            "tool_index": recipe.tool_index,
            "recipe_digest": recipe.recipe_digest,
        }
        for gate in ("task_materialization", "task_reachability"):
            outcomes.append(
                {
                    "gate_id": f"{gate}:{recipe.task_family_index}:{recipe.tool_index}",
                    "status": "passed",
                    "code": "ok"
                    if gate == "task_materialization"
                    else "terminal_success_reward_plus_one",
                    "binding": binding,
                }
            )
    for case in cases:
        outcomes.append(
            {
                "gate_id": case.commitment_id,
                "status": "passed",
                "code": "terminal_success_reward_plus_one",
                "binding": {
                    "task_family_index": case.task_family_index,
                    "tool_index": case.tool_index,
                    "recipe_digest": case.baseline_recipe_digest,
                },
            }
        )
    return tuple(outcomes)


def _release_candidate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    run_id: str = "run_release",
) -> tuple[CandidateExecutor, ArtifactStore, DesignContract, CandidateResult]:
    settings = replace(
        load_settings(Path("config/agent-world.example.toml")), state_root=tmp_path / "state"
    )
    store = ArtifactStore(settings.state_root / "runs" / run_id)
    design = _design(store)
    design_work = _passed_work(
        store,
        run_id,
        "design",
        "research_acquire",
        (
            OperationEvidence("direct_llm", "world_architecture", "direct-test", None),
            OperationEvidence(
                "agent",
                "research_plan",
                "agent-test",
                {"total_tokens": 4},
                "sha256:" + "d" * 64,
            ),
            OperationEvidence("search", "research_acquire", None, None),
            OperationEvidence("fetch", "research_acquire", None, None),
            OperationEvidence("extract", "research_acquire", None, None),
        ),
    )
    design = replace(design, work_refs=(design_work,))

    class Agent:
        def invoke_json(self, **kwargs: object) -> InvocationResult:
            workspace = kwargs["workspace"]
            work = kwargs["work"]
            assert isinstance(workspace, Path)
            if work == "build_plan":
                value = _plan()
            elif work == "candidate_build":
                _candidate_files(workspace)
                value = _completion()
            elif work == "verifier_intent":
                value = {
                    "checks": [
                        {
                            "task_family_index": 1,
                            "tool_index": 1,
                            "family": "unknown_seed",
                            "argument_index": None,
                            "risk": "exercise an unknown seed",
                        },
                        {
                            "task_family_index": 1,
                            "tool_index": 2,
                            "family": "argument_variation",
                            "argument_index": 1,
                            "risk": "vary the close identifier",
                        },
                        {
                            "task_family_index": 2,
                            "tool_index": 2,
                            "family": "alternate_difficulty",
                            "argument_index": None,
                            "risk": "exercise alternate volume",
                        },
                    ]
                }
            else:
                raise AssertionError(work)
            return InvocationResult(value, "agent-test", None, "sha256:" + "c" * 64)

    executor = CandidateExecutor(settings, Agent())  # type: ignore[arg-type]
    monkeypatch.setattr(candidate_module, "prepare_candidate", _prepared_candidate)
    monkeypatch.setattr(
        candidate_module,
        "integrate",
        lambda *_: _integration_value(design),
    )

    def fake_judge(*args: object) -> tuple[dict[str, Any], ...]:
        recipes = args[1]
        cases = args[5]
        assert isinstance(recipes, tuple) and isinstance(cases, tuple)
        return _judge_outcomes(recipes, cases)

    monkeypatch.setattr(candidate_module, "judge", fake_judge)
    return executor, store, design, executor.run(design, store, candidate_graph(), run_id)


def _artifact_map(result: CandidateResult) -> dict[str, ArtifactRef]:
    return {ref.kind: ref for ref in result.artifact_refs}


def test_builder_projection_contains_every_family_tool_recipe_without_release_authority(
    tmp_path: Path,
) -> None:
    store = ArtifactStore(tmp_path / "run")
    design = _design(store)
    projection = CandidateExecutor._projection(design)
    contract = compile_implementation_contract(design)

    assert len(projection["curriculum"]["families"]) == 2
    assert len(projection["tools"]) == 2
    assert [
        (item["task_family_index"], item["tool_index"]) for item in projection["assurance_recipes"]
    ] == [
        (1, 1),
        (1, 2),
        (2, 2),
    ]
    assert len(contract["tool_semantics"]["executable_tasks"]) == 2
    serialized = json.dumps({"projection": projection, "contract": contract})
    for forbidden in (
        "reward_spec",
        "termination_spec",
        "verification_requirements",
        "verifier_intent",
        "judge_report",
        "release_dossier",
    ):
        assert forbidden not in serialized
    assert validate_build_plan(_plan(), contract) == _plan()
    assert validate_candidate_completion(_completion()) == _completion()
    with pytest.raises(NodeExecutionError, match="build_plan_invalid"):
        plan = copy.deepcopy(_plan())
        plan["steps"][0]["suggested_paths"] = ["../escape.py"]  # type: ignore[index]
        validate_build_plan(plan, contract)


def test_candidate_graph_integration_failure_records_finding_and_preserves_inputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = replace(
        load_settings(Path("config/agent-world.example.toml")), state_root=tmp_path / "state"
    )
    store = ArtifactStore(settings.state_root / "runs" / "test")
    design = _design(store)
    captured: dict[str, dict[str, bytes]] = {}

    class Agent:
        def invoke_json(self, **kwargs: object) -> InvocationResult:
            workspace, work = kwargs["workspace"], kwargs["work"]
            assert isinstance(workspace, Path)
            if work == "build_plan":
                captured["build_plan"] = {
                    path.name: path.read_bytes() for path in workspace.iterdir()
                }
                value = _plan()
            elif work == "candidate_build":
                inputs = workspace / "inputs"
                captured["candidate_build"] = {
                    path.name: path.read_bytes() for path in inputs.iterdir()
                }
                _candidate_files(workspace)
                value = _completion()
            else:
                raise AssertionError(work)
            return InvocationResult(value, "agent-test", None, "sha256:" + "a" * 64)

    executor = CandidateExecutor(settings, Agent())  # type: ignore[arg-type]
    monkeypatch.setattr(candidate_module, "prepare_candidate", _prepared_candidate)
    monkeypatch.setattr(
        candidate_module,
        "integrate",
        lambda *_: {"status": "failed", "code": "candidate_protocol_mismatch"},
    )
    with pytest.raises(CandidateError, match="candidate_protocol_mismatch"):
        executor.run(design, store, candidate_graph(), "run_candidate_failure")
    assert (
        captured["build_plan"]["implementation-contract.json"]
        == captured["candidate_build"]["implementation-contract.json"]
    )
    assert set(captured["candidate_build"]) == {
        "design.json",
        "implementation-contract.json",
        "build-plan.json",
    }
    payloads = [
        json.loads(path.read_text(encoding="utf-8"))["payload"]
        for path in store.artifacts_root.glob("*.json")
    ]
    works = {value["coordinate"]["node_id"]: value for value in payloads if "coordinate" in value}
    assert works["integration"]["finding_refs"]
    assert {
        node: works[node]["status"] for node in ("verifier_intent", "judge", "package", "registry")
    } == {
        "verifier_intent": "not_run",
        "judge": "not_run",
        "package": "not_run",
        "registry": "not_run",
    }


def test_verifier_bindings_are_complete_and_private_values_never_persist(
    tmp_path: Path,
) -> None:
    settings = replace(
        load_settings(Path("config/agent-world.example.toml")), state_root=tmp_path / "state"
    )
    store = ArtifactStore(settings.state_root / "runs" / "test")
    design = _design(store)
    captured: dict[str, Any] = {}

    class Agent:
        def invoke_json(self, **kwargs: object) -> InvocationResult:
            workspace = kwargs["workspace"]
            assert isinstance(workspace, Path)
            captured["catalog"] = json.loads(
                (workspace / "public-design.json").read_text(encoding="utf-8")
            )
            return InvocationResult(
                {
                    "checks": [
                        {
                            "task_family_index": 1,
                            "tool_index": 1,
                            "family": family,
                            "argument_index": 1 if family == "argument_variation" else None,
                            "risk": f"exercise {family}",
                        }
                        for family in (
                            "unknown_seed",
                            "alternate_difficulty",
                            "idempotency_key_variation",
                            "argument_variation",
                        )
                    ]
                },
                "agent-test",
                None,
                "sha256:" + "b" * 64,
            )

    executor = CandidateExecutor(settings, Agent())  # type: ignore[arg-type]
    node = executor._verifier_bundle(design, store, candidate_graph(), "run_verifier")
    payload = store.read_envelope(node.artifact)["payload"]
    catalog = captured["catalog"]
    assert set(catalog) == {
        "families",
        "tools",
        "assurance_recipes",
        "task_rule_summaries",
    }
    assert len(catalog["families"]) == 2
    assert len(catalog["tools"]) == 2
    assert len(catalog["assurance_recipes"]) == 3
    assert all(
        forbidden not in json.dumps(catalog, sort_keys=True)
        for forbidden in ("evaluator_goal", "reward_spec", "termination_spec", "candidate")
    )
    assert set(payload) == {"commitments", "commitment_count"}
    assert all(
        item["baseline_recipe_digest"] == design.assurance_recipes[0].recipe_digest
        for item in payload["commitments"]
    )
    CandidateExecutor._validate_private_bindings(design, payload, node.value.private_cases)
    private_values = [
        *[str(case.request.seed) for case in node.value.private_cases],
        *[key for case in node.value.private_cases for key in case.idempotency_keys],
        *[str(value) for case in node.value.private_cases for value in case.arguments.values()],
    ]
    serialized = "\n".join(
        path.read_text(encoding="utf-8") for path in store.artifacts_root.glob("*.json")
    )
    assert all(value not in serialized for value in private_values if value)
    assert all(
        forbidden not in serialized
        for forbidden in ("initial_config", "snapshot", "evaluator_goal_value")
    )


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("commitment_id", "verifier-different", "verifier_private_binding_mismatch"),
        ("task_family_index", 2, "verifier_private_binding_mismatch"),
        ("tool_index", 2, "verifier_private_binding_mismatch"),
        ("variation_kind", "alternate_difficulty", "verifier_private_binding_mismatch"),
        ("baseline_recipe_digest", "sha256:" + "f" * 64, "verifier_private_binding_mismatch"),
    ],
)
def test_judge_rejects_every_private_binding_mismatch(
    tmp_path: Path, field: str, value: Any, code: str
) -> None:
    store = ArtifactStore(tmp_path / "run")
    design = _design(store)
    recipe = design.assurance_recipes[0]
    commitment = {
        "commitment_id": "verifier-binding",
        "task_family_index": 1,
        "tool_index": 1,
        "variation_kind": "unknown_seed",
        "argument_index": None,
        "risk": "binding risk",
        "baseline_recipe_digest": recipe.recipe_digest,
    }
    bundle = {"commitments": [commitment], "commitment_count": 1}
    case = PrivateVerifierCase(
        "verifier-binding",
        1,
        1,
        "unknown_seed",
        recipe.recipe_digest,
        candidate_module.MaterializationRequest(
            7, "resolve-record", "operator", recipe.primary_difficulty
        ),
        {"request_id": "public-id"},
        ("private-key",),
    )
    bad = replace(case, **{field: value})
    with pytest.raises(NodeExecutionError, match=code):
        CandidateExecutor._validate_private_bindings(design, bundle, (bad,))
    with pytest.raises(NodeExecutionError, match="verifier_private_binding_missing"):
        CandidateExecutor._validate_private_bindings(design, bundle, ())


def test_judge_rejects_duplicate_and_multiple_private_variations(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "run")
    design = _design(store)
    recipe = design.assurance_recipes[0]
    commitment = {
        "commitment_id": "verifier-binding",
        "task_family_index": 1,
        "tool_index": 1,
        "variation_kind": "unknown_seed",
        "argument_index": None,
        "risk": "binding risk",
        "baseline_recipe_digest": recipe.recipe_digest,
    }
    case = PrivateVerifierCase(
        "verifier-binding",
        1,
        1,
        "unknown_seed",
        recipe.recipe_digest,
        candidate_module.MaterializationRequest(
            7, "resolve-record", "operator", recipe.primary_difficulty
        ),
        {"request_id": "public-id"},
        ("private-key",),
    )
    duplicate_commitment = {**commitment, "commitment_id": "verifier-binding-two"}
    duplicate_case = replace(case, commitment_id="verifier-binding-two")
    with pytest.raises(NodeExecutionError, match="verifier_private_binding_duplicate"):
        CandidateExecutor._validate_private_bindings(
            design,
            {
                "commitments": [commitment, duplicate_commitment],
                "commitment_count": 2,
            },
            (case, duplicate_case),
        )

    extra_variations = (
        replace(case, arguments={"request_id": "private-value"}),
        replace(
            case,
            request=replace(case.request, difficulty_pairs=recipe.alternate_difficulty),
        ),
        replace(case, idempotency_keys=("private-key", "other-private-key")),
    )
    for varied in extra_variations:
        with pytest.raises(NodeExecutionError, match="verifier_private_variation_mismatch"):
            CandidateExecutor._validate_private_bindings(
                design,
                {"commitments": [commitment], "commitment_count": 1},
                (varied,),
            )


def test_candidate_graph_release_packages_all_family_tool_coverage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, store, design, result = _release_candidate(tmp_path, monkeypatch)
    artifacts = _artifact_map(result)
    package = store.read_bytes(artifacts["registry.package"])
    closure = candidate_module._cold_read_package(package, result.package_ref.package_digest)
    metadata = closure["metadata"]
    assert metadata["world/world_spec.json"] == {
        "schema_version": "world-spec@1",
        "architecture": json_value(design.architecture),
    }
    assert metadata["world/rule_ir.json"]["tasks"] == candidate_module._task_rule_ir(design)
    assert metadata["tasks/curriculum.json"]["families"] == json_value(design.curriculum.families)
    assert metadata["tasks/materializer_protocol.json"][
        "tasks"
    ] == candidate_module._materializer_tasks(design)
    assurance = metadata["evidence/assurance.json"]
    assert assurance["integration_coverage"] == _integration_value(design)["baseline_coverage"]
    assert len(assurance["judge_coverage"]) == len(design.assurance_recipes) * 2 + 3
    package_path = tmp_path / "package.zip"
    package_path.write_bytes(package)
    package_payload = store.read_envelope(artifacts["release.package"])["payload"]
    _verify_package(package_path, result.package_ref.package_digest, package_payload["manifest"])


def _rewrite_json_entry(
    source: bytes, path: str, mutation: Callable[[dict[str, Any]], None]
) -> bytes:
    with zipfile.ZipFile(BytesIO(source)) as archive:
        infos = archive.infolist()
        bodies = {info.filename: archive.read(info.filename) for info in infos}
    value = json.loads(bodies[path])
    mutation(value)
    bodies[path] = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()
    manifest = json.loads(bodies["manifest.json"])
    digest = f"sha256:{sha256(bodies[path]).hexdigest()}"
    manifest["metadata_digests"][path] = digest
    for entry in manifest["physical_entries"]:
        if entry["path"] == path:
            entry["digest"] = digest
            entry["size"] = len(bodies[path])
    bodies["manifest.json"] = json.dumps(
        manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()
    rewritten = BytesIO()
    with zipfile.ZipFile(rewritten, "w") as output:
        for info in infos:
            output.writestr(info, bodies[info.filename])
    return rewritten.getvalue()


@pytest.mark.parametrize(
    ("path", "mutation", "code"),
    [
        (
            "world/rule_ir.json",
            lambda value: value["tasks"][0]["reward_spec"].__setitem__("success", 2),
            "registry_reward_digest_mismatch",
        ),
        (
            "world/rule_ir.json",
            lambda value: value["tasks"][0].__setitem__("reward_digest", "sha256:" + "0" * 64),
            "registry_reward_digest_mismatch",
        ),
        (
            "world/rule_ir.json",
            lambda value: value["tasks"][0]["termination_spec"].__setitem__("otherwise", "stop"),
            "registry_termination_digest_mismatch",
        ),
        (
            "world/rule_ir.json",
            lambda value: value["tasks"][0].__setitem__("termination_digest", "sha256:" + "0" * 64),
            "registry_termination_digest_mismatch",
        ),
        (
            "tasks/materializer_protocol.json",
            lambda value: value["tasks"][0]["verification_requirements"].__setitem__(
                "required_recipe_digests",
                list(
                    reversed(
                        value["tasks"][0]["verification_requirements"]["required_recipe_digests"]
                    )
                ),
            ),
            "registry_verification_digest_mismatch",
        ),
        (
            "tasks/materializer_protocol.json",
            lambda value: value["tasks"][0].__setitem__(
                "verification_digest", "sha256:" + "0" * 64
            ),
            "registry_verification_digest_mismatch",
        ),
    ],
)
def test_cold_read_rejects_independent_task_value_and_digest_mutations(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    path: str,
    mutation: Callable[[dict[str, Any]], None],
    code: str,
) -> None:
    _, store, _, result = _release_candidate(tmp_path, monkeypatch)
    source = store.read_bytes(_artifact_map(result)["registry.package"])
    body = _rewrite_json_entry(source, path, mutation)
    with pytest.raises(CandidateError, match=code):
        candidate_module._cold_read_package(body, f"sha256:{sha256(body).hexdigest()}")


@pytest.mark.parametrize(
    ("path", "mutation", "code"),
    [
        (
            "world/rule_ir.json",
            lambda value: value["tools"][0]["transitions"][0].__setitem__("rationale", "mutated"),
            "registry_local_tool_semantics_digest_mismatch",
        ),
        (
            "world/rule_ir.json",
            lambda value: value["shared_tool_contracts"][0]["ordering"].append("mutated"),
            "registry_shared_tool_digest_mismatch",
        ),
        (
            "world/rule_ir.json",
            lambda value: value["world_rules"].__setitem__("digest", "sha256:" + "0" * 64),
            "registry_world_rule_digest_mismatch",
        ),
        (
            "tasks/curriculum.json",
            lambda value: value["families"].reverse(),
            "registry_design_order_mismatch",
        ),
        (
            "tasks/materializer_protocol.json",
            lambda value: value["tasks"][0].pop("evaluator_goal_bindings"),
            "registry_task_contract_invalid",
        ),
        (
            "evidence/assurance.json",
            lambda value: value["judge_coverage"].reverse(),
            "registry_assurance_coverage_mismatch",
        ),
    ],
)
def test_cold_read_rejects_rule_metadata_omission_and_reorder(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    path: str,
    mutation: Callable[[dict[str, Any]], None],
    code: str,
) -> None:
    _, store, _, result = _release_candidate(tmp_path, monkeypatch)
    source = store.read_bytes(_artifact_map(result)["registry.package"])
    body = _rewrite_json_entry(source, path, mutation)
    with pytest.raises(CandidateError, match=code):
        candidate_module._cold_read_package(body, f"sha256:{sha256(body).hexdigest()}")


def test_registry_exact_compare_rejects_mutated_cold_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, store, design, result = _release_candidate(tmp_path, monkeypatch)
    artifacts = _artifact_map(result)
    source = store.read_bytes(artifacts["registry.package"])
    closure = candidate_module._cold_read_package(source, result.package_ref.package_digest)
    closure["metadata"]["world/world_spec.json"]["architecture"]["boundary"]["name"] = "mutated"

    with pytest.raises(NodeExecutionError, match="registry_lineage_mismatch"):
        candidate_module._cold_verify(
            store,
            design,
            result.manifest,
            result.integration,
            result.verifier,
            result.judge,
            artifacts["release.dossier"],
            artifacts["release.telemetry_summary"],
            artifacts["lineage.semantic"],
            artifacts["lineage.implementation"],
            closure,
        )


def test_release_semantics_bind_work_records_and_exact_physical_package_ref(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    executor, store, design, result = _release_candidate(tmp_path, monkeypatch)
    artifacts, graph = _artifact_map(result), candidate_graph()
    candidate_material = {
        "design": design.artifact.digest,
        "build_plan": artifacts["candidate.build_plan"].digest,
        "projection": CandidateExecutor._projection(design),
        "implementation_contract": compile_implementation_contract(design),
    }
    assert store.read_envelope(artifacts["build.environment_candidate"])[
        "semantic_revision_digest"
    ] == graph.semantic_revision(graph.node("candidate_build"), candidate_material)
    package_material = {
        "design": design.artifact.digest,
        "candidate": result.manifest.artifact.digest,
        "integration": result.integration.digest,
        "judge": result.judge.artifact.digest,
        "verifier": result.verifier.digest,
        "semantic_lineage": artifacts["lineage.semantic"].digest,
        "implementation_lineage": artifacts["lineage.implementation"].digest,
        "design_work_record_digests": tuple(ref.digest for ref in design.work_refs),
        "candidate_work_record_digests": tuple(ref.digest for ref in result.manifest.work_refs),
    }
    package_revision = graph.semantic_revision(graph.node("package"), package_material)
    assert store.read_envelope(artifacts["release.package"])["semantic_revision_digest"] == (
        package_revision
    )
    for key, value in (
        ("design_work_record_digests", ("sha256:" + "0" * 64,)),
        (
            "candidate_work_record_digests",
            tuple(reversed(package_material["candidate_work_record_digests"])),
        ),
    ):
        assert graph.semantic_revision(graph.node("package"), {**package_material, key: value}) != (
            package_revision
        )
    registry_material = {
        "package": artifacts["release.package"].digest,
        "design": design.artifact.digest,
        "candidate": result.manifest.artifact.digest,
        "dossier": artifacts["release.dossier"].digest,
        "integration": result.integration.digest,
        "judge": result.judge.artifact.digest,
        "verifier": result.verifier.digest,
        "physical_package": artifacts["registry.package"].digest,
        "telemetry": artifacts["release.telemetry_summary"].digest,
        "semantic_lineage": artifacts["lineage.semantic"].digest,
        "implementation_lineage": artifacts["lineage.implementation"].digest,
        "design_work_record_digests": package_material["design_work_record_digests"],
        "candidate_work_record_digests": package_material["candidate_work_record_digests"],
        "registry_acceptance_revision": "physical-package-ref-equality@1",
    }
    registry_revision = graph.semantic_revision(graph.node("registry"), registry_material)
    assert store.read_envelope(artifacts["registry.receipt"])["semantic_revision_digest"] == (
        registry_revision
    )
    for key, registry_value in (
        ("physical_package", "sha256:" + "0" * 64),
        ("registry_acceptance_revision", "physical-package-ref-equality@2"),
    ):
        revision = graph.semantic_revision(
            graph.node("registry"), {**registry_material, key: registry_value}
        )
        assert revision != registry_revision
    source = store.read_bytes(artifacts["registry.package"])
    rewritten = BytesIO()
    with zipfile.ZipFile(BytesIO(source)) as original, zipfile.ZipFile(rewritten, "w") as archive:
        archive.comment = b"same-contents-different-zip"
        for info in original.infolist():
            archive.writestr(info, original.read(info.filename))
    body = rewritten.getvalue()
    package_payload = store.read_envelope(artifacts["release.package"])["payload"]
    assert body != source
    assert (
        candidate_module._cold_read_package(
            body, f"sha256:{sha256(body).hexdigest()}", package_payload["manifest"]
        )["manifest"]
        == package_payload["manifest"]
    )
    alternate = store.put_bytes("registry.package", body, media_type="application/zip")
    monkeypatch.setattr(candidate_module, "_publish", lambda *_: pytest.fail("must not publish"))
    with pytest.raises(NodeExecutionError, match="registry_physical_package_mismatch") as raised:
        executor._registry(
            design,
            result.manifest,
            result.integration,
            result.verifier,
            result.judge,
            artifacts["release.package"],
            alternate,
            artifacts["release.dossier"],
            artifacts["release.telemetry_summary"],
            artifacts["lineage.semantic"],
            artifacts["lineage.implementation"],
            store,
            graph,
            "run_rejected_physical_package",
        )
    work = store.read_json(raised.value.artifact_refs[-1])
    finding = store.read_json(ArtifactRef(**work["finding_refs"][0]))
    assert work["coordinate"]["node_id"] == "registry"
    assert work["status"] == "failed" and work["safe_code"] == "registry_physical_package_mismatch"
    assert finding["code"] == "registry_physical_package_mismatch"


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        ("extra", "registry_package_entry_set_mismatch"),
        ("duplicate", "registry_package_duplicate_entry"),
        ("missing", "registry_package_entry_set_mismatch"),
    ],
)
def test_package_cold_read_rejects_extra_duplicate_and_missing_entries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
    code: str,
) -> None:
    _, store, _, result = _release_candidate(tmp_path, monkeypatch)
    source = store.read_bytes(_artifact_map(result)["registry.package"])
    rewritten = BytesIO()
    with zipfile.ZipFile(BytesIO(source)) as original, zipfile.ZipFile(rewritten, "w") as archive:
        for info in original.infolist():
            if mutation == "missing" and info.filename == "LICENSE":
                continue
            archive.writestr(info, original.read(info.filename))
        if mutation == "extra":
            archive.writestr("extra.txt", b"extra")
        if mutation == "duplicate":
            with pytest.warns(UserWarning, match="Duplicate name"):
                archive.writestr("manifest.json", original.read("manifest.json"))
    body = rewritten.getvalue()
    with pytest.raises(CandidateError, match=code):
        candidate_module._cold_read_package(body, f"sha256:{sha256(body).hexdigest()}")


def test_judge_requires_exact_independently_readmitted_lock_closure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = replace(
        load_settings(Path("config/agent-world.example.toml")), state_root=tmp_path / "state"
    )
    store = ArtifactStore(settings.state_root / "runs" / "test")
    design = _design(store)

    class Agent:
        def invoke_json(self, **kwargs: object) -> InvocationResult:
            workspace, work = kwargs["workspace"], kwargs["work"]
            assert isinstance(workspace, Path)
            if work == "build_plan":
                value = _plan()
            elif work == "candidate_build":
                _candidate_files(workspace)
                value = _completion()
            elif work == "verifier_intent":
                value = {
                    "checks": [
                        {
                            "task_family_index": 1,
                            "tool_index": 1,
                            "family": "unknown_seed",
                            "argument_index": None,
                            "risk": "unknown seed",
                        }
                    ]
                }
            else:
                raise AssertionError(work)
            return InvocationResult(value, "agent-test", None, "sha256:" + "c" * 64)

    closures = iter(
        (
            AdmittedLockClosure(()),
            AdmittedLockClosure(
                (
                    AdmittedLockEntry(
                        "other",
                        "1",
                        (LockedWheel("other-1.whl", "sha256:" + "d" * 64, 1),),
                    ),
                )
            ),
        )
    )

    @contextmanager
    def prepared(*_: object):
        yield PreparedCandidate(Path(sys.executable), next(closures))

    called = False

    def unexpected_judge(*_: object) -> tuple[dict[str, Any], ...]:
        nonlocal called
        called = True
        return ()

    executor = CandidateExecutor(settings, Agent())  # type: ignore[arg-type]
    monkeypatch.setattr(candidate_module, "prepare_candidate", prepared)
    monkeypatch.setattr(
        candidate_module,
        "integrate",
        lambda *_: _integration_value(design),
    )
    monkeypatch.setattr(candidate_module, "judge", unexpected_judge)
    with pytest.raises(CandidateError, match="judge_admitted_lock_closure_mismatch"):
        executor.run(design, store, candidate_graph(), "run_closure_mismatch")
    assert not called


def test_candidate_scan_rejects_hidden_symlink_nonregular_and_unsupported_entries(
    tmp_path: Path,
) -> None:
    root = tmp_path / "candidate"
    root.mkdir()
    _candidate_files(root)
    os.chmod(root / "runtime.py", 0o640)
    scanned = CandidateExecutor._scan(root)
    runtime = next(item for item in scanned["files"] if item["path"] == "runtime.py")
    assert runtime["mode"] == "0640"
    (root / ".hidden.py").write_text("x = 1\n", encoding="utf-8")
    with pytest.raises(NodeExecutionError, match="candidate_source_hidden_path"):
        CandidateExecutor._scan(root)
    (root / ".hidden.py").unlink()
    (root / "README.md").write_text("not source\n", encoding="utf-8")
    with pytest.raises(NodeExecutionError, match="candidate_source_unsupported_file"):
        CandidateExecutor._scan(root)
    (root / "README.md").unlink()
    (root / "link.py").symlink_to(root / "runtime.py")
    with pytest.raises(NodeExecutionError, match="candidate_source_symlink"):
        CandidateExecutor._scan(root)
    (root / "link.py").unlink()
    if hasattr(os, "mkfifo"):
        os.mkfifo(root / "candidate.pipe")
        with pytest.raises(NodeExecutionError, match="candidate_source_non_regular"):
            CandidateExecutor._scan(root)
