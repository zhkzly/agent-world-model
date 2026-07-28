"""Real envpkg-v3 fixture shared by Registry and consumer integration tests.

The candidate files in this module are executed by uv, bubblewrap and real child
processes.  They intentionally contain no candidate evaluator, answer, witness,
consumer adapter or release callback.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import pytest
from pydantic import JsonValue

from agent_world.artifact_store import ArtifactStore, ArtifactWriter
from agent_world.builder import (
    BuildRecord,
    CandidateCompletion,
    CandidateFileDeclaration,
    CandidatePublicSelfCheckDeclaration,
    CandidateRuntimeDeclaration,
    CandidateTaskMaterializerDeclaration,
    CandidateWorkspaceValidator,
    EnvironmentBuilder,
    ImplementationContract,
    ImplementationPlan,
)
from agent_world.builder.models import TaskMaterializerContract, ToolBindingRequirement
from agent_world.contracts import (
    ActorBoundary,
    ArtifactRef,
    Budget,
    BudgetUsage,
    CandidateManifest,
    ConcurrencySemantics,
    CoverageDimension,
    CoverageMap,
    CurriculumRequirements,
    DifficultyDimension,
    EnvironmentCandidate,
    EnvironmentDesign,
    EnvironmentJob,
    EnvironmentPackageManifest,
    EvaluatorGoalBinding,
    FidelityStatement,
    FrameworkPackagePayload,
    GateResult,
    GenerationContext,
    IdempotencySemantics,
    IdentityDecision,
    ImplementationLineage,
    IntegrationReport,
    JudgeReport,
    ObservationSemantics,
    PackageFile,
    PackageLineage,
    ParameterizedSolveRecipe,
    ParameterizedSolveStep,
    PermissionRule,
    PermissionScope,
    PublicSelfCheckDescriptor,
    ReachabilityPublicEvidence,
    RecipeLiteral,
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
    RuntimeLaunch,
    SemanticLineage,
    StateEntitySchema,
    StateSchema,
    TaskMaterializerDescriptor,
    TaskRequirement,
    TimeoutSemantics,
    ToolContract,
    ToolError,
    ToolSemantics,
    ToolSurface,
    TransactionSemantics,
    TrustedEvaluatorDescriptor,
    VerificationRequirements,
    VerifierAssertion,
    VerifierCase,
    VerifierIR,
    VerifierProperty,
    WorldBoundary,
    WorldSpec,
    canonical_json_bytes,
    compile_framework_package_payloads,
    sha256_digest,
)
from agent_world.control import (
    GenerationWorkGraph,
    LeaseBudgetLedger,
    ProposalExecution,
    ReleaseDossierCompiler,
    TelemetryReleaseSummary,
    ValidationReport,
    WorkAttempt,
    WorkControlRuntime,
    WorkControlStore,
    WorkDefinition,
    WorkGraphEpochRuntime,
    compile_design_work_graph,
    complete_generation_work_graph,
    deterministic_boundary_work_definition,
    verifier_plan_work_definition,
)
from agent_world.judge import VerifierBatchPlan, VerifierBatchPlanItem
from agent_world.task_materialization import compile_task_materializer_output_schema

RUNTIME_SOURCE = r"""from __future__ import annotations

import hashlib
import json
import os
import sys

assert os.path.isfile("/workspace/runtime.py")
assert not os.path.exists("/workspace/task_materializer.py")
assert not os.path.exists("/workspace/world/rule_ir.json")

ABI = "agent-world.runtime.v2"
OPERATIONS = ["handshake", "reset", "invoke", "snapshot", "close"]
state = {"count": 0}
idempotent_results = {}
actor = ""


def digest():
    encoded = json.dumps(state, sort_keys=True, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def full_observation():
    return {"counter": {"value": state["count"]}}


def observation():
    return full_observation() if actor == "user" else {}


def failure_result():
    return {
        "tool_result": None,
        "observation": observation(),
        "events": [],
        "state_digest": digest(),
        "reward": 0.0,
        "terminated": False,
        "truncated": False,
        "info": {},
    }


def emit(request, *, result=None, error=None):
    response = {
        "abi_version": ABI,
        "request_id": request["request_id"],
        "operation": request["operation"],
        "ok": error is None,
    }
    if error is None:
        response["result"] = result
    else:
        response["error"] = error
        if result is not None:
            response["result"] = result
    sys.stdout.write(json.dumps(response, sort_keys=True, separators=(",", ":")) + "\n")
    sys.stdout.flush()


for raw_line in sys.stdin:
    request = json.loads(raw_line)
    operation = request["operation"]
    payload = request["payload"]
    if operation == "handshake":
        emit(
            request,
            result={
                "runtime_id": "counter-runtime-v3",
                "operations": OPERATIONS,
                "tools": [
                    {
                        "tool_id": "counter.increment",
                        "namespace": "counter",
                        "name": "increment",
                        "description": "Increment the program-owned counter state.",
                        "input_schema": {
                            "type": "object",
                            "properties": {"amount": {"type": "integer", "minimum": 0}},
                            "required": ["amount"],
                            "additionalProperties": False,
                        },
                        "output_schema": {
                            "type": "object",
                            "properties": {"value": {"type": "integer"}},
                            "required": ["value"],
                            "additionalProperties": False,
                        },
                        "observation_schema": {
                            "type": "object",
                            "properties": {
                                "counter": {
                                    "type": "object",
                                    "properties": {
                                        "value": {"type": "integer", "minimum": 0}
                                    },
                                    "required": ["value"],
                                    "additionalProperties": False,
                                }
                            },
                            "required": ["counter"],
                            "additionalProperties": False,
                        },
                    }
                ],
            },
        )
    elif operation == "reset":
        actor = payload["actor"]
        state = {"count": int(payload["config"]["initial"])}
        idempotent_results = {}
        emit(
            request,
            result={
                "observation": observation(),
                "state_digest": digest(),
                "terminated": False,
                "info": {},
            },
        )
    elif operation == "invoke":
        if actor != "user":
            emit(
                request,
                result=failure_result(),
                error={
                    "code": "permission_denied",
                    "message": "Permission denied.",
                    "retryable": False,
                    "details": {},
                },
            )
            continue
        if payload["tool"] != "counter.increment":
            emit(
                request,
                result=failure_result(),
                error={
                    "code": "unknown_tool",
                    "message": "The requested tool is not available.",
                    "retryable": False,
                    "details": {},
                },
            )
            continue
        key = payload["idempotency_key"]
        if key in idempotent_results:
            emit(request, result=idempotent_results[key])
            continue
        amount = payload["args"].get("amount")
        if isinstance(amount, bool) or not isinstance(amount, int) or amount < 1:
            emit(
                request,
                result=failure_result(),
                error={
                    "code": "invalid_amount",
                    "message": "amount must be a positive integer",
                    "retryable": False,
                    "details": {},
                },
            )
            continue
        state["count"] += amount
        result = {
            "tool_result": {"value": state["count"]},
            "observation": observation(),
            "events": [],
            "state_digest": digest(),
            "reward": 0.0,
            "terminated": False,
            "truncated": False,
            "info": {},
        }
        idempotent_results[key] = result
        emit(request, result=result)
    elif operation == "snapshot":
        emit(request, result={"observation": full_observation(), "state_digest": digest()})
    elif operation == "close":
        emit(request, result={})
        break
"""


TASK_MATERIALIZER_SOURCE = r"""from __future__ import annotations

import os

assert os.path.isfile("/workspace/task_materializer.py")
assert os.path.isfile("/workspace/runtime.py")
assert not os.path.exists("/workspace/world/rule_ir.json")


def materialize(seed, task_type, actor, difficulty):
    initial = seed % 97
    amount = 3 if difficulty["scale"] == "small" else 5
    return {
        "schema_version": "v2",
        "task_schema_version": "task-materialization-v3",
        "seed": seed,
        "task_type": task_type,
        "actor": actor,
        "difficulty": difficulty,
        "public_goal": {"target": initial + amount},
        "initial_config": {"initial": initial},
    }
"""


PUBLIC_SELF_CHECK_SOURCE = r"""from __future__ import annotations

import json
import os

assert os.path.isdir(os.environ["AGENT_WORLD_STATE_DIR"])
assert os.path.isfile("/workspace/public_check.py")
assert os.path.isfile("/workspace/runtime.py")
assert os.path.isfile("/workspace/task_materializer.py")
print(json.dumps({"status": "pass", "network_required": False}, sort_keys=True))
"""


PUBLIC_TEST_SOURCE = r"""from __future__ import annotations

from pathlib import Path

root = Path(__file__).resolve().parent
assert (root / "runtime.py").is_file()
assert (root / "task_materializer.py").is_file()
"""

LICENSE_SOURCE = """MIT License

Copyright (c) 2026 Agent World test fixture contributors

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and
associated documentation files (the "Software"), to deal in the Software without restriction.
"""


SEEDED_RUNTIME_SOURCE = RUNTIME_SOURCE.replace(
    'state = {"count": int(payload["config"]["initial"])}',
    'state = {"count": int(payload["config"]["initial"]) + int(payload["seed"])}',
)
SEEDED_TASK_MATERIALIZER_SOURCE = TASK_MATERIALIZER_SOURCE.replace(
    '"public_goal": {"target": initial + amount}',
    '"public_goal": {"target": seed + initial + amount}',
)


@dataclass(frozen=True, slots=True)
class PortableCounterContracts:
    design: EnvironmentDesign
    materializer_protocol_schema: dict[str, object]


@dataclass(frozen=True, slots=True)
class ReleaseGraph:
    workspace: Path
    uv_path: Path
    uv_cache_dir: Path
    manifest_ref: ArtifactRef
    report_ref: ArtifactRef
    release_profile: ReleaseProfile
    candidate_ref: ArtifactRef
    owner_ref: ArtifactRef
    framework_payloads: tuple[FrameworkPackagePayload, ...]
    package_id: str
    version: str
    package_closure: _PrePackageFixtureClosure


@dataclass(frozen=True, slots=True)
class JudgeCandidateGraph:
    """Builder-shaped, typed input graph for the real EnvironmentJudge path."""

    workspace: Path
    uv_path: Path
    uv_cache_dir: Path
    design: EnvironmentDesign
    design_ref: ArtifactRef
    world_spec_ref: ArtifactRef
    candidate: EnvironmentCandidate
    candidate_ref: ArtifactRef
    candidate_manifest: CandidateManifest
    verifier: VerifierIR
    verifier_ref: ArtifactRef
    release_profile: ReleaseProfile
    owner_ref: ArtifactRef
    implementation_lineage: ImplementationLineage
    package_id: str
    version: str


@dataclass(frozen=True, slots=True)
class _PrePackageFixtureClosure:
    """Test-only holder for the real WorkControl authority used by Registry tests.

    The counter Runtime remains a deterministic test candidate, but publication
    evidence is intentionally not faked: every ReleaseDossier input is backed
    by a durable final WorkGraph epoch and its currently active WorkCommit.
    """

    dossier_ref: ArtifactRef
    runtime: WorkControlRuntime
    graph: GenerationWorkGraph
    final_epoch_ref: ArtifactRef
    final_manifest_ref: ArtifactRef
    package_definition: WorkDefinition
    package_input_refs: tuple[ArtifactRef, ...]


def _unique_dependencies(refs: tuple[ArtifactRef, ...]) -> tuple[ArtifactRef, ...]:
    """Mirror ArtifactStore's revision-identity edge semantics in fixture graphs."""

    by_revision: dict[str, ArtifactRef] = {}
    for ref in refs:
        by_revision.setdefault(ref.revision_id, ref)
    return tuple(by_revision.values())


def framework_writer(store: ArtifactStore) -> ArtifactWriter:
    return store.issue_writer(
        producer="framework",
        allowed_artifact_types=(
            "curriculum",
            "environment_candidate",
            "environment_design",
            "environment_package_manifest",
            "evaluation_evidence",
            "evidence_summary",
            "implementation_contract",
            "public_verifier",
            "task_materializer_protocol",
            "test.semantic_source",
        ),
        allowed_artifact_type_prefixes=("control.", "design.", "release."),
    )


def _fixture_boundary(
    *,
    scope_id: str,
    component: str,
    stage: str,
    dependencies: tuple[WorkDefinition, ...] = (),
) -> WorkDefinition:
    """Make a code-owned test boundary without weakening the production graph."""

    return deterministic_boundary_work_definition(
        scope_id=scope_id,
        component=component,  # type: ignore[arg-type]
        stage=stage,
        artifact_slot=stage,
        dependency_coordinates=tuple(item.coordinate for item in dependencies),
        claim_id=f"fixture.{component}.{stage}.passed",
        claim=f"Fixture {component}/{stage} committed its exact typed output.",
        timing_reason="Registry tests require a real active WorkCommit closure.",
        effect="block_release",
        success_maturity=f"fixture_{stage}_closed",
    )


def _commit_prepackage_fixture_closure(
    store: ArtifactStore,
    *,
    owner_ref: ArtifactRef,
    design_ref: ArtifactRef,
    candidate_ref: ArtifactRef,
    candidate_manifest_ref: ArtifactRef,
    build_record_ref: ArtifactRef,
    implementation_lineage_ref: ArtifactRef,
    verifier_ref: ArtifactRef,
    integration_report_ref: ArtifactRef,
    judge_report_ref: ArtifactRef,
    telemetry_summary_ref: ArtifactRef,
    release_profile: ReleaseProfile,
) -> _PrePackageFixtureClosure:
    """Create a complete, active final epoch for a real Registry test package.

    This intentionally replaces the former Design-only ``ClaimVector`` fixture.
    The test candidate is still exercised by real child processes elsewhere; this
    helper is only its framework-control provenance, with actual WorkControl
    heads and exact final-graph commits instead of a manually asserted readiness
    bit.
    """

    writer = framework_writer(store)
    scope_suffix = design_ref.revision_id.removeprefix("sha256:")[:24]
    scope_id = f"release-fixture:{scope_suffix}"
    request_ref = writer.put_json(
        artifact_id=f"request:release-fixture:{scope_suffix}",
        artifact_type="control.environment_request",
        value={"need": "fixture registry package"},
    )
    fixture_budget = Budget(
        llm_tokens=100_000,
        agent_turns=16,
        search_calls=100,
        tool_calls=100,
        process_calls=100,
        build_seconds=10_000,
        evaluation_episodes=100,
        container_seconds=10_000,
        live_probe_cost=100,
        repair_attempts=16,
        wall_seconds=10_000,
    )
    context = GenerationContext(
        context_id=f"context:release-fixture:{scope_suffix}",
        job_ref=owner_ref,
        kind="generate",
        request_ref=request_ref,
        permissions=PermissionScope(),
        budget=fixture_budget,
        release_profile=release_profile,
    )
    context_ref = writer.put_json(
        artifact_id=context.context_id,
        artifact_type="control.generation_context",
        value=context,
        dependencies=context.root_refs,
    )
    heads = WorkControlStore(store.root.parent / "work-control")
    runtime = WorkControlRuntime(
        artifacts=writer,
        heads=heads,
        budget=LeaseBudgetLedger(fixture_budget),
    )

    plan = _fixture_boundary(scope_id=scope_id, component="research", stage="research_plan")
    acquisition = _fixture_boundary(
        scope_id=scope_id,
        component="research",
        stage="evidence_acquisition",
        dependencies=(plan,),
    )
    synthesis = _fixture_boundary(
        scope_id=scope_id,
        component="research",
        stage="evidence_synthesis",
        dependencies=(acquisition,),
    )
    architecture = _fixture_boundary(
        scope_id=scope_id,
        component="design",
        stage="world_architecture",
        dependencies=(synthesis,),
    )
    bootstrap_definitions = (plan, acquisition, synthesis, architecture)
    bootstrap_graph = GenerationWorkGraph.compile(bootstrap_definitions, mode="diagnostic")
    epochs = WorkGraphEpochRuntime(artifacts=writer, heads=heads)
    _, _, _, bootstrap_epoch_ref = epochs.freeze_bootstrap(
        context_ref=context_ref,
        graph=bootstrap_graph,
        topology_id=f"topology:release-fixture-bootstrap:{scope_suffix}",
    )

    def stage_output(stage: str, inputs: tuple[ArtifactRef, ...]) -> ArtifactRef:
        return writer.put_json(
            artifact_id=f"fixture-output:{scope_suffix}:{stage}",
            artifact_type="control.fixture_stage_output",
            value={"stage": stage},
            dependencies=inputs,
        )

    bootstrap_inputs: tuple[ArtifactRef, ...] = (context_ref,)
    bootstrap_outputs: dict[str, ArtifactRef] = {}
    for definition in bootstrap_definitions:
        output_ref = stage_output(definition.coordinate.stage, bootstrap_inputs)
        runtime.execute_deterministic_boundary(
            definition=definition,
            input_refs=bootstrap_inputs,
            subject_ref=output_ref,
            output_refs=(output_ref,),
        )
        bootstrap_outputs[definition.coordinate.stage] = output_ref
        # Every WorkAttempt carries the immutable GenerationContext.  The
        # fixture must use the same input closure as Scheduler recovery or its
        # otherwise-valid commits are correctly classified as stale.
        bootstrap_inputs = (context_ref, output_ref)

    behavior = _fixture_boundary(
        scope_id=scope_id,
        component="design",
        stage="tool_semantics_batch",
        dependencies=(architecture,),
    )
    rules = _fixture_boundary(
        scope_id=scope_id,
        component="design",
        stage="world_rules",
        dependencies=(behavior,),
    )
    curriculum_plan = _fixture_boundary(
        scope_id=scope_id,
        component="design",
        stage="curriculum_plan",
        dependencies=(rules,),
    )
    task_requirement = _fixture_boundary(
        scope_id=scope_id,
        component="design",
        stage="task_requirement",
        dependencies=(curriculum_plan,),
    )
    curriculum = _fixture_boundary(
        scope_id=scope_id,
        component="design",
        stage="task_curriculum",
        dependencies=(curriculum_plan, task_requirement),
    )
    modeling = _fixture_boundary(
        scope_id=scope_id,
        component="design",
        stage="modeling_boundary",
        dependencies=(curriculum,),
    )
    verifier_plan = verifier_plan_work_definition(
        scope_id=scope_id,
        modeling_coordinate=modeling.coordinate,
    )
    design_graph = compile_design_work_graph(
        scope_id=scope_id,
        design_definitions=(
            *bootstrap_definitions,
            behavior,
            rules,
            curriculum_plan,
            task_requirement,
            curriculum,
        ),
        modeling_definition=modeling,
        verifier_plan_definition=verifier_plan,
    )
    _, _, _, design_epoch_ref = epochs.freeze_design(
        context_ref=context_ref,
        bootstrap_epoch_ref=bootstrap_epoch_ref,
        graph=design_graph,
        topology_id=f"topology:release-fixture-design:{scope_suffix}",
    )

    behavior_inputs = (context_ref, bootstrap_outputs["world_architecture"])
    behavior_ref = stage_output("tool-semantics", behavior_inputs)
    runtime.execute_deterministic_boundary(
        definition=behavior,
        input_refs=behavior_inputs,
        subject_ref=behavior_ref,
        output_refs=(behavior_ref,),
    )
    rules_inputs = (context_ref, behavior_ref)
    rules_ref = stage_output("world-rules", rules_inputs)
    runtime.execute_deterministic_boundary(
        definition=rules,
        input_refs=rules_inputs,
        subject_ref=rules_ref,
        output_refs=(rules_ref,),
    )
    curriculum_plan_inputs = (context_ref, rules_ref)
    curriculum_plan_ref = stage_output("curriculum-plan", curriculum_plan_inputs)
    runtime.execute_deterministic_boundary(
        definition=curriculum_plan,
        input_refs=curriculum_plan_inputs,
        subject_ref=curriculum_plan_ref,
        output_refs=(curriculum_plan_ref,),
    )
    task_requirement_inputs = (context_ref, curriculum_plan_ref)
    task_requirement_ref = stage_output("task-requirement", task_requirement_inputs)
    runtime.execute_deterministic_boundary(
        definition=task_requirement,
        input_refs=task_requirement_inputs,
        subject_ref=task_requirement_ref,
        output_refs=(task_requirement_ref,),
    )
    curriculum_inputs = (context_ref, curriculum_plan_ref, task_requirement_ref)
    curriculum_output_ref = stage_output("task-curriculum", curriculum_inputs)
    runtime.execute_deterministic_boundary(
        definition=curriculum,
        input_refs=curriculum_inputs,
        subject_ref=curriculum_output_ref,
        output_refs=(curriculum_output_ref,),
    )
    fixture_design = store.get_json(design_ref, EnvironmentDesign)
    fixture_world_spec_ref = writer.put_json(
        artifact_id=f"fixture-output:{scope_suffix}:world-spec",
        artifact_type="design.world_spec",
        value=fixture_design.world_spec,
        dependencies=(design_ref,),
    )
    runtime.execute_deterministic_boundary(
        definition=modeling,
        input_refs=(context_ref, curriculum_output_ref),
        subject_ref=design_ref,
        output_refs=(design_ref, fixture_world_spec_ref),
    )
    verifier_plan_value = VerifierBatchPlan(
        plan_id=f"verifier-plan:fixture:{scope_suffix}",
        design_ref=design_ref,
        world_spec_ref=fixture_world_spec_ref,
        maximum_tasks_per_batch=2,
        batches=(
            VerifierBatchPlanItem(
                batch_id="verifier-batch:1",
                batch_index=0,
                task_types=("fixture-booking",),
                required_rule_ids=(),
                required_property_families=(),
                semantic_case_limit=2,
                context_hash=sha256_digest(b"fixture-verifier-plan"),
            ),
        ),
    )
    fixture_judge_writer = judge_writer(store)
    verifier_plan_ref = fixture_judge_writer.put_json(
        artifact_id=f"fixture-output:{scope_suffix}:verifier-plan",
        artifact_type="judge.verifier_batch_plan",
        value=verifier_plan_value,
        dependencies=(design_ref, fixture_world_spec_ref),
    )
    runtime.execute_deterministic_boundary(
        definition=verifier_plan,
        input_refs=(context_ref, design_ref, fixture_world_spec_ref),
        subject_ref=verifier_plan_ref,
        output_refs=(verifier_plan_ref,),
    )

    candidate = store.get_json(candidate_ref, EnvironmentCandidate)
    implementation_contract_ref = candidate.implementation_contract_ref
    fixture_builder_writer = builder_writer(store)
    implementation_plan_value = ImplementationPlan(
        plan_id=f"implementation-plan:fixture:{scope_suffix}",
        design_ref=design_ref,
        implementation_contract_ref=implementation_contract_ref,
        world_spec_hash=fixture_design.world_spec.content_digest(),
        curriculum_hash=fixture_design.curriculum.content_digest(),
        implementation_strategy=(
            "Fixture provenance plan: the already-executed candidate maps the frozen WorldSpec "
            "to its Runtime and Task Materializer closure."
        ),
    )
    implementation_plan_ref = fixture_builder_writer.put_json(
        artifact_id=implementation_plan_value.plan_id,
        artifact_type="build.implementation_plan",
        value=implementation_plan_value,
        dependencies=(design_ref, implementation_contract_ref),
    )

    final_graph = complete_generation_work_graph(
        scope_id=scope_id,
        design_graph=design_graph,
        verifier_batch_count=len(verifier_plan_value.batches),
    )
    # Registry integration is deliberately independent of live Builder model
    # availability.  The Candidate passed to this helper was assembled and
    # executed by the real child-process fixture above; this test-only graph
    # records that already-existing Candidate as a code boundary so Registry
    # tests exercise publication, recovery and package closure rather than
    # inventing a second fake code-generation implementation.
    production_plan = next(
        item
        for item in final_graph.definitions
        if (item.coordinate.component, item.coordinate.stage) == ("build", "implementation_plan")
    )
    production_build = next(
        item
        for item in final_graph.definitions
        if (item.coordinate.component, item.coordinate.stage) == ("build", "candidate_build")
    )
    fixture_plan = deterministic_boundary_work_definition(
        scope_id=scope_id,
        component="build",  # type: ignore[arg-type]
        stage="implementation_plan",
        artifact_slot=production_plan.coordinate.artifact_slot,
        dependency_coordinates=production_plan.dependency_coordinates,
        claim_id="fixture.build.implementation-plan.recorded",
        claim="A pre-executed fixture implementation plan is recorded for provenance tests.",
        timing_reason="Registry tests do not execute the production planning Agent.",
        effect="block_integration",
        success_maturity="implementation_planned",
    ).model_copy(update={"input_slots": production_plan.input_slots})
    fixture_build = deterministic_boundary_work_definition(
        scope_id=scope_id,
        component="build",  # type: ignore[arg-type]
        stage="candidate_build",
        artifact_slot=production_build.coordinate.artifact_slot,
        dependency_coordinates=production_build.dependency_coordinates,
        claim_id="fixture.build.candidate.recorded",
        claim="A pre-executed fixture Candidate is recorded for Registry provenance tests.",
        timing_reason="Registry tests do not execute the production Builder Agent.",
        effect="block_integration",
        success_maturity="candidate_built",
    ).model_copy(update={"input_slots": production_build.input_slots})
    final_graph = GenerationWorkGraph.compile(
        tuple(
            fixture_plan
            if item.coordinate == production_plan.coordinate
            else fixture_build
            if item.coordinate == production_build.coordinate
            else item
            for item in final_graph.definitions
        ),
        mode="production",
        required_terminal_coordinates=final_graph.required_terminal_coordinates,
        groups=final_graph.groups,
        milestones=final_graph.milestones,
    )
    build = next(
        item
        for item in final_graph.definitions
        if (item.coordinate.component, item.coordinate.stage) == ("build", "candidate_build")
    )
    implementation_plan = next(
        item
        for item in final_graph.definitions
        if (item.coordinate.component, item.coordinate.stage) == ("build", "implementation_plan")
    )
    verifier_batch = next(
        item
        for item in final_graph.definitions
        if (item.coordinate.component, item.coordinate.stage)
        == ("verifier", "verifier_intent_batch")
    )
    verifier = next(
        item
        for item in final_graph.definitions
        if (item.coordinate.component, item.coordinate.stage) == ("verifier", "verifier_intent")
    )
    integration = next(
        item
        for item in final_graph.definitions
        if (item.coordinate.component, item.coordinate.stage)
        == ("integration", "runtime_integration")
    )
    release_assurance = next(
        item
        for item in final_graph.definitions
        if (item.coordinate.component, item.coordinate.stage) == ("judge", "release_assurance")
    )
    observability = next(
        item
        for item in final_graph.definitions
        if (item.coordinate.component, item.coordinate.stage)
        == ("release", "observability_closure")
    )
    package = next(
        item
        for item in final_graph.definitions
        if (item.coordinate.component, item.coordinate.stage) == ("release", "package")
    )
    _, final_manifest_ref, _, final_epoch_ref = epochs.freeze_final(
        context_ref=context_ref,
        design_epoch_ref=design_epoch_ref,
        graph=final_graph,
        topology_id=f"topology:release-fixture-final:{scope_suffix}",
    )

    runtime.execute_deterministic_boundary(
        definition=implementation_plan,
        input_refs=(context_ref, design_ref),
        subject_ref=implementation_plan_ref,
        output_refs=(implementation_contract_ref, implementation_plan_ref),
    )
    runtime.execute_deterministic_boundary(
        definition=build,
        input_refs=(context_ref, design_ref, implementation_contract_ref, implementation_plan_ref),
        subject_ref=candidate_ref,
        output_refs=(
            candidate_ref,
            candidate_manifest_ref,
            build_record_ref,
            implementation_lineage_ref,
        ),
    )
    verifier_checkpoint_ref = fixture_judge_writer.put_json(
        artifact_id=f"fixture-output:{scope_suffix}:verifier-checkpoint",
        artifact_type="judge.verifier_intent_checkpoint",
        value={"fixture": "checkpoint"},
        dependencies=(verifier_plan_ref,),
    )
    verifier_draft_ref = fixture_judge_writer.put_json(
        artifact_id=f"fixture-output:{scope_suffix}:verifier-draft",
        artifact_type="judge.verifier_batch_draft",
        value={"fixture": "draft"},
        dependencies=(verifier_plan_ref,),
    )
    # A physical Challenger batch is a real final-epoch member.  Recording
    # only its aggregate verifier projection hid an uncommitted prerequisite,
    # which made the scheduler correctly stall before Package while the fixture
    # incorrectly pretended the closure was complete.
    _commit_fixture_agent_boundary(
        store,
        runtime=runtime,
        definition=verifier_batch,
        input_refs=(context_ref, verifier_plan_ref),
        subject_ref=verifier_checkpoint_ref,
        output_refs=(verifier_checkpoint_ref, verifier_draft_ref),
    )
    verifier_batch_head = runtime.heads.read_head(verifier_batch.coordinate)
    assert verifier_batch_head is not None and verifier_batch_head.commit_ref is not None
    runtime.execute_deterministic_boundary(
        definition=verifier,
        input_refs=(context_ref, verifier_draft_ref),
        subject_ref=verifier_ref,
        output_refs=(verifier_ref,),
        child_commit_refs=(verifier_batch_head.commit_ref,),
    )
    runtime.execute_deterministic_boundary(
        definition=integration,
        input_refs=(context_ref, candidate_ref),
        subject_ref=integration_report_ref,
        output_refs=(integration_report_ref,),
    )
    runtime.execute_deterministic_boundary(
        definition=release_assurance,
        input_refs=(
            context_ref,
            candidate_ref,
            integration_report_ref,
            verifier_ref,
        ),
        subject_ref=judge_report_ref,
        output_refs=(judge_report_ref,),
    )
    runtime.execute_deterministic_boundary(
        definition=observability,
        input_refs=(context_ref,),
        subject_ref=telemetry_summary_ref,
        output_refs=(telemetry_summary_ref,),
    )
    _dossier, dossier_ref = ReleaseDossierCompiler(artifacts=writer, heads=heads).compile(
        final_epoch_ref=final_epoch_ref,
        graph=final_graph,
        manifest_ref=final_manifest_ref,
        design_ref=design_ref,
        candidate_ref=candidate_ref,
        candidate_manifest_ref=candidate_manifest_ref,
        build_record_ref=build_record_ref,
        implementation_lineage_ref=implementation_lineage_ref,
        verifier_ref=verifier_ref,
        integration_report_ref=integration_report_ref,
        judge_report_ref=judge_report_ref,
        telemetry_summary_ref=telemetry_summary_ref,
        release_profile=release_profile,
    )
    return _PrePackageFixtureClosure(
        dossier_ref=dossier_ref,
        runtime=runtime,
        graph=final_graph,
        final_epoch_ref=final_epoch_ref,
        final_manifest_ref=final_manifest_ref,
        package_definition=package,
        package_input_refs=(
            design_ref,
            fixture_world_spec_ref,
            candidate_ref,
            candidate_manifest_ref,
            build_record_ref,
            implementation_lineage_ref,
            verifier_ref,
            integration_report_ref,
            judge_report_ref,
            telemetry_summary_ref,
        ),
    )


def _commit_fixture_package(
    closure: _PrePackageFixtureClosure,
    *,
    manifest_ref: ArtifactRef,
) -> None:
    closure.runtime.execute_deterministic_boundary(
        definition=closure.package_definition,
        input_refs=closure.package_input_refs,
        subject_ref=manifest_ref,
        output_refs=(manifest_ref,),
    )


def _commit_fixture_agent_boundary(
    store: ArtifactStore,
    *,
    runtime: WorkControlRuntime,
    definition: WorkDefinition,
    input_refs: tuple[ArtifactRef, ...],
    subject_ref: ArtifactRef,
    output_refs: tuple[ArtifactRef, ...],
) -> None:
    """Record a closed Agent-shaped WorkCommit for Registry-only fixture graphs.

    This does not emulate a production Challenger invocation and never reaches
    ``FoundryController``.  It exercises the real WorkControl operation,
    validation, feedback and commit lifecycle so release-closure tests cannot
    erase a required physical verifier shard merely because their Candidate is
    prebuilt.  Live Direct acceptance remains responsible for a real isolated
    Challenger invocation.
    """

    with runtime.heads.exclusive(definition.coordinate) as lock:
        head = runtime.begin(
            lock,
            definition=definition,
            input_refs=input_refs,
            elapsed_wall_seconds=0,
        )
        head = runtime.schedule_operation(
            lock,
            definition=definition,
            kind="proposal",
            replay_mode=definition.proposal_policy.replay_mode,
            elapsed_wall_seconds=0,
        )
        dispatch_id = f"fixture:{definition.work_id}:proposal"
        head = runtime.start_operation(
            lock,
            definition=definition,
            dispatch_id=dispatch_id,
        )
        attempt = store.get_json(head.attempt_ref, WorkAttempt)
        now = datetime.now(UTC)
        unknown = BudgetUsage(
            llm_tokens=definition.proposal_policy.budget.llm_tokens,
            agent_turns=definition.proposal_policy.budget.agent_turns,
        )
        proposal = ProposalExecution(
            execution_id=f"fixture-execution:{definition.work_id}",
            attempt_id=attempt.attempt_id,
            executor="agent",
            executor_revision_id=definition.proposal_policy.executor_revision_id,
            operation=definition.proposal_policy.operation,
            status="completed",
            invocation_id=dispatch_id,
            provider="fixture",
            model="fixture-static-verifier-intent",
            profile_digest=sha256_digest(b"fixture-challenger-profile"),
            output_schema_digest=sha256_digest(b"fixture-verifier-intent-schema"),
            output_commitment=subject_ref.content_hash,
            continuation_commitment=sha256_digest(b"fixture-no-provider-session"),
            observed_actual=BudgetUsage(),
            unknown_upper_bound=unknown,
            conservative_committed=unknown,
            started_at=now,
            finished_at=now,
            duration_ms=0,
        )
        runtime.checkpoint_proposal(
            lock,
            definition=definition,
            execution=proposal,
            output_refs=output_refs,
        )
        head = runtime.schedule_operation(
            lock,
            definition=definition,
            kind="validation",
            replay_mode="deterministic",
            elapsed_wall_seconds=0,
        )
        head = runtime.start_operation(
            lock,
            definition=definition,
            dispatch_id=f"fixture:{definition.work_id}:validation",
        )
        attempt = store.get_json(head.attempt_ref, WorkAttempt)
        report = ValidationReport(
            report_id=f"fixture-report:{definition.work_id}",
            attempt_id=attempt.attempt_id,
            coordinate=definition.coordinate,
            policy_id=definition.validation_policy.policy_id,
            policy_digest=definition.validation_policy.content_digest(),
            status="passed",
            validation_phase=definition.validation_policy.validation_phase,
            frontier_ordinal=definition.validation_policy.frontier_ordinal,
            passed_check_ids=(definition.required_claim_id,),
            subject_refs=output_refs,
            evidence_refs=(subject_ref,),
            diagnostic_quality="not_applicable",
            evaluated_at=datetime.now(UTC),
        )
        runtime.checkpoint_validation(
            lock,
            definition=definition,
            report=report,
            observed_actual=BudgetUsage(),
        )
        runtime.evaluate(
            lock,
            definition=definition,
            report=report,
            output_refs=output_refs,
            elapsed_wall_seconds=0,
        )


def judge_writer(store: ArtifactStore) -> ArtifactWriter:
    return store.issue_writer(
        producer="environment-judge",
        allowed_artifact_types=("judge_report",),
        allowed_artifact_type_prefixes=("judge.",),
    )


def builder_writer(store: ArtifactStore) -> ArtifactWriter:
    return store.issue_writer(
        producer="environment-builder",
        allowed_artifact_type_prefixes=("build.",),
    )


def commit_json(
    store: ArtifactStore,
    artifact_id: str,
    artifact_type: str,
    value: Any,
    *,
    dependencies: tuple[ArtifactRef, ...] = (),
) -> ArtifactRef:
    return framework_writer(store).put_json(
        artifact_id=artifact_id,
        artifact_type=artifact_type,
        value=value,
        dependencies=dependencies,
    )


def _value_ref(source: str, pointer: str) -> RuleValueRef:
    return RuleValueRef(source=source, pointer=pointer, value_type="number")  # type: ignore[arg-type]


def _rule(
    rule_id: str,
    family: str,
    left: RuleValueRef,
    operator: str,
    right: RuleValueRef | RuleConstant | RuleArithmetic,
    *,
    sensitivity: str = "positive_only",
) -> Rule:
    return Rule(
        rule_id=rule_id,
        family=family,  # type: ignore[arg-type]
        description=f"Executable counter {family} rule.",
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


def portable_counter_contracts(store: ArtifactStore) -> PortableCounterContracts:
    source_ref = commit_json(
        store,
        "semantic-source:counter-v3",
        "test.semantic_source",
        {"claim": "deterministic executable counter semantics"},
    )
    zero = RuleConstant(value_type="number", value=0)
    precondition = _rule(
        "rule:counter-positive",
        "precondition",
        _value_ref("args", "/amount"),
        "greater_than",
        zero,
        sensitivity="positive_and_negative",
    )
    transition = _rule(
        "rule:counter-transition",
        "transition",
        _value_ref("post_state", "/counter/value"),
        "equal",
        RuleArithmetic(
            operator="add",
            left=_value_ref("pre_state", "/counter/value"),
            right=_value_ref("args", "/amount"),
        ),
    )
    postcondition = _rule(
        "rule:counter-postcondition",
        "postcondition",
        _value_ref("tool_result", "/value"),
        "equal",
        _value_ref("post_state", "/counter/value"),
    )
    error = _rule(
        "rule:counter-error",
        "error_condition",
        _value_ref("args", "/amount"),
        "less_or_equal",
        zero,
        sensitivity="positive_and_negative",
    )
    invariant = _rule(
        "rule:counter-invariant",
        "invariant",
        _value_ref("post_state", "/counter/value"),
        "greater_or_equal",
        zero,
    )
    success = _rule(
        "rule:counter-success",
        "task_success",
        _value_ref("post_state", "/counter/value"),
        "greater_or_equal",
        _value_ref("task_goal", "/target"),
    )
    terminal = _rule(
        "rule:counter-terminal",
        "task_terminal",
        _value_ref("post_state", "/counter/value"),
        "greater_or_equal",
        _value_ref("task_goal", "/target"),
    )
    nested_counter_schema: dict[str, JsonValue] = {
        "type": "object",
        "properties": {"value": {"type": "integer", "minimum": 0}},
        "required": ["value"],
        "additionalProperties": False,
    }
    root_schema: dict[str, JsonValue] = {
        "type": "object",
        "properties": {"counter": nested_counter_schema},
        "required": ["counter"],
        "additionalProperties": False,
    }
    tool = ToolContract(
        surface=ToolSurface(
            tool_id="counter.increment",
            namespace="counter",
            name="increment",
            description="Increment the program-owned counter state.",
            transport="runtime",
            input_schema={
                "type": "object",
                "properties": {"amount": {"type": "integer", "minimum": 0}},
                "required": ["amount"],
                "additionalProperties": False,
            },
            output_schema={
                "type": "object",
                "properties": {"value": {"type": "integer"}},
                "required": ["value"],
                "additionalProperties": False,
            },
            observation_schema=root_schema,
        ),
        semantics=ToolSemantics(
            preconditions=(precondition,),
            transition=(transition,),
            postconditions=(postcondition,),
            errors=(
                ToolError(
                    error_code="invalid_amount",
                    when=error,
                    observation="amount must be a positive integer",
                    state_effect="none",
                    retryable=False,
                ),
            ),
            permission=PermissionRule(
                permission_id="permission:counter",
                allowed_actors=("user",),
                required_scopes_by_actor={"user": ("counter.write",)},
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
                duplicate_observation="Return the first result.",
            ),
            retry=RetrySemantics(maximum_attempts=1),
            timeout=TimeoutSemantics(
                operation_timeout_seconds=5,
                timeout_error_code="invalid_amount",
                cancellation_effect="no_effect",
            ),
            transaction=TransactionSemantics(
                atomicity="atomic",
                commit_point="After positive-amount validation.",
                partial_commit_observable=False,
            ),
            rollback=RollbackSemantics(
                supported=True,
                rollback_trigger_codes=("invalid_amount",),
                guarantees="Invalid increments preserve counter state.",
            ),
            concurrency=ConcurrencySemantics(
                isolation="serializable",
                conflict_detection="One Runtime process serializes updates.",
                ordering_guarantee="Committed increments are observed in order.",
            ),
        ),
        evidence_claim_ids=("claim:counter",),
    )
    world = WorldSpec(
        world_spec_id="world:counter-v3",
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
            systems_of_record=("counter-runtime",),
            core_resources=("counter",),
            transition_authorities=("counter-runtime",),
            tool_namespaces=("counter",),
            core_invariants=("Counter never becomes negative.",),
        ),
        state=StateSchema(
            entities=(
                StateEntitySchema(
                    entity="counter",
                    json_schema=nested_counter_schema,
                    primary_key_fields=("value",),
                    mutable_fields=("value",),
                ),
            ),
            root_state_schema=root_schema,
        ),
        tools=(tool,),
        invariants=(invariant,),
        task_dimensions=("target",),
        fidelity=(
            FidelityStatement(
                statement_id="fidelity:counter-v3",
                claim="Counter behavior is a deterministic synthetic policy.",
                level="synthetic_policy",
            ),
        ),
        evidence_graph_ref=source_ref,
        coverage_map_ref=source_ref,
    )
    goal_schema: dict[str, JsonValue] = {
        "type": "object",
        "properties": {"target": {"type": "integer", "minimum": 3, "maximum": 101}},
        "required": ["target"],
        "additionalProperties": False,
    }
    curriculum = CurriculumRequirements(
        task_types=(
            TaskRequirement(
                task_type="increase_counter",
                objective="Increase the counter until the public target is reached.",
                allowed_actor_ids=("user",),
                required_tool_ids=("counter.increment",),
                success_conditions=(success,),
                terminal_conditions=(terminal,),
                initial_config_schema={
                    "type": "object",
                    "properties": {"initial": {"type": "integer", "minimum": 0, "maximum": 96}},
                    "required": ["initial"],
                    "additionalProperties": False,
                },
                public_goal_schema=goal_schema,
                evaluator_goal_schema=goal_schema,
                evaluator_goal_bindings=(
                    EvaluatorGoalBinding(
                        binding_id="binding:counter-target",
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
                description="Size of the required counter increment.",
                levels=("small", "large"),
            ),
        ),
        generation_seed_space="all uint64 seeds",
    )
    design = EnvironmentDesign(
        design_id="design:counter-v3",
        revision=1,
        job_ref=source_ref,
        request_ref=source_ref,
        evidence_graph_ref=source_ref,
        coverage_map_ref=source_ref,
        world_spec=world,
        curriculum=curriculum,
        reward=RewardSpec(
            terminal_rule_ids=(terminal.rule_id,),
            success_rule_ids=(success.rule_id,),
        ),
        verification=VerificationRequirements(
            required_rule_ids=(
                precondition.rule_id,
                transition.rule_id,
                postcondition.rule_id,
                error.rule_id,
                invariant.rule_id,
                success.rule_id,
                terminal.rule_id,
            ),
            required_property_families=(
                "precondition",
                "transition",
                "postcondition",
                "error_semantics",
                "invariant",
                "task_success",
                "task_terminal",
            ),
        ),
        target_kind="initial_package",
    )
    return PortableCounterContracts(
        design=design,
        materializer_protocol_schema=cast(
            dict[str, object],
            compile_task_materializer_output_schema(curriculum),
        ),
    )


def write_candidate_project(
    root: Path,
    *,
    public_test_source: str = PUBLIC_TEST_SOURCE,
    project_license: str | None = "MIT",
) -> tuple[Path, Path, Path]:
    project = root / "counter-runtime-v3"
    project.mkdir()
    project_lines = [
        "[project]",
        'name = "counter-runtime-v3"',
        'version = "0.1.0"',
        'requires-python = ">=3.12,<3.13"',
    ]
    if project_license is not None:
        project_lines.append(f"license = {project_license!r}")
    project_lines.extend(
        (
            "dependencies = []",
            "",
            "[tool.uv]",
            "package = false",
            "",
        )
    )
    (project / "pyproject.toml").write_text(
        "\n".join(project_lines),
        encoding="utf-8",
    )
    (project / "runtime.py").write_text(RUNTIME_SOURCE, encoding="utf-8")
    (project / "task_materializer.py").write_text(
        TASK_MATERIALIZER_SOURCE,
        encoding="utf-8",
    )
    (project / "public_check.py").write_text(PUBLIC_SELF_CHECK_SOURCE, encoding="utf-8")
    (project / "public_test.py").write_text(public_test_source, encoding="utf-8")
    (project / "LICENSE").write_text(LICENSE_SOURCE, encoding="utf-8")
    uv_text = shutil.which("uv")
    if uv_text is None:
        pytest.skip("real uv executable is unavailable")
    uv_path = Path(uv_text).resolve(strict=True)
    uv_cache_dir = root / "uv-cache"
    completed = subprocess.run(  # noqa: S603 - resolved uv is the tested executable
        [str(uv_path), "lock", "--offline", "--python", sys.executable],
        cwd=project,
        env={
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "UV_CACHE_DIR": str(uv_cache_dir),
            "UV_NO_PROGRESS": "1",
        },
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert completed.returncode == 0, completed.stderr
    return project, uv_path, uv_cache_dir


def candidate_files(project: Path) -> tuple[PackageFile, ...]:
    roles = {
        "LICENSE": "license",
        "pyproject.toml": "configuration",
        "public_check.py": "public_verifier",
        "public_test.py": "public_test",
        "runtime.py": "runtime",
        "task_materializer.py": "task_materializer",
        "uv.lock": "dependency_lock",
    }
    return tuple(
        PackageFile(
            path=path.relative_to(project).as_posix(),
            content_hash=sha256_digest(path.read_bytes()),
            size_bytes=path.stat().st_size,
            role=roles[path.relative_to(project).as_posix()],  # type: ignore[arg-type]
        )
        for path in sorted(project.iterdir())
        if path.is_file()
    )


def build_judge_candidate_graph(
    root: Path,
    store: ArtifactStore,
    *,
    public_test_source: str = PUBLIC_TEST_SOURCE,
    project_license: str | None = "MIT",
    runtime_source: str = SEEDED_RUNTIME_SOURCE,
) -> JudgeCandidateGraph:
    """Create real candidate bytes and the typed inputs consumed by EnvironmentJudge.

    This helper does not create evaluation evidence or a JudgeReport.  Those can
    only come from ``EnvironmentJudge.evaluate`` in the end-to-end test.
    """

    workspace, uv_path, uv_cache_dir = write_candidate_project(
        root,
        public_test_source=public_test_source,
        project_license=project_license,
    )
    (workspace / "runtime.py").write_text(runtime_source, encoding="utf-8")
    (workspace / "task_materializer.py").write_text(
        SEEDED_TASK_MATERIALIZER_SOURCE,
        encoding="utf-8",
    )

    portable = portable_counter_contracts(store)
    goal_schema: dict[str, JsonValue] = {
        "type": "object",
        "properties": {
            "target": {
                "type": "integer",
                "minimum": 3,
                "maximum": 2**64 + 101,
            }
        },
        "required": ["target"],
        "additionalProperties": False,
    }
    requirement = portable.design.curriculum.task_types[0].model_copy(
        update={
            "public_goal_schema": goal_schema,
            "evaluator_goal_schema": goal_schema,
        }
    )
    curriculum = portable.design.curriculum.model_copy(update={"task_types": (requirement,)})
    design = portable.design.model_copy(update={"curriculum": curriculum})

    framework = framework_writer(store)
    world_spec_ref = framework.put_json(
        artifact_id="world-spec:counter-judge-e2e",
        artifact_type="design.world_spec",
        value=design.world_spec,
        dependencies=(design.world_spec.evidence_graph_ref,),
    )
    design_ref = framework.put_json(
        artifact_id="design:counter-judge-e2e",
        artifact_type="design.environment_design",
        value=design,
        dependencies=(world_spec_ref, design.evidence_graph_ref),
    )
    owner_ref = framework.put_json(
        artifact_id="job:counter-judge-e2e",
        artifact_type="control.environment_job",
        value={"job_id": "job:counter-judge-e2e", "kind": "generate"},
        dependencies=(design_ref,),
    )

    candidate_id = "candidate:counter-judge-e2e"
    completion_files = tuple(
        CandidateFileDeclaration(
            path=item.path,
            role=item.role,  # type: ignore[arg-type]
            executable=item.executable,
        )
        for item in candidate_files(workspace)
    )
    completion = CandidateCompletion(
        status="completed",
        project_root="candidate",
        root_project_mode="virtual-read-only-source-tree",
        dependency_install_mode="offline-wheel-only",
        runtime=CandidateRuntimeDeclaration(
            argv=(".venv/bin/python", "-m", "runtime"),
            entry_path="runtime.py",
        ),
        task_materializer=CandidateTaskMaterializerDeclaration(
            entrypoint="task_materializer:materialize",
            entry_path="task_materializer.py",
        ),
        public_self_check=CandidatePublicSelfCheckDeclaration(
            argv=(".venv/bin/python", "-m", "public_check"),
            entry_path="public_check.py",
        ),
        public_test_paths=("public_test.py",),
        files=completion_files,
    )
    validated = CandidateWorkspaceValidator().validate(workspace, completion)

    builder = builder_writer(store)
    implementation_contract = ImplementationContract(
        contract_id="implementation-contract:counter-judge-e2e",
        design_ref=design_ref,
        world_spec_hash=design.world_spec.content_digest(),
        state_schema_hash=design.world_spec.state.content_digest(),
        curriculum_hash=design.curriculum.content_digest(),
        runtime=EnvironmentBuilder._runtime_wire_contract(),  # noqa: SLF001
        tools=tuple(
            ToolBindingRequirement(
                tool_id=tool.surface.tool_id,
                tool_contract_hash=tool.content_digest(),
            )
            for tool in design.world_spec.tools
        ),
        task_materializer=TaskMaterializerContract(
            task_types=tuple(item.task_type for item in design.curriculum.task_types),
            minimum_distinct_initial_states=design.curriculum.minimum_distinct_initial_states,
            minimum_distinct_tasks_per_type=design.curriculum.minimum_distinct_tasks_per_type,
        ),
    )
    implementation_contract_ref = builder.put_json(
        artifact_id="implementation-contract:counter-judge-e2e",
        artifact_type="build.implementation_contract",
        value=implementation_contract,
        dependencies=(design_ref,),
    )
    task_schema_ref = builder.put_json(
        artifact_id="task-schema:counter-judge-e2e",
        artifact_type="build.task_materialization_schema",
        value=compile_task_materializer_output_schema(design.curriculum),
        dependencies=(design_ref, implementation_contract_ref),
    )
    curriculum_ref = builder.put_json(
        artifact_id="curriculum:counter-judge-e2e",
        artifact_type="build.curriculum",
        value=design.curriculum,
        dependencies=(design_ref,),
    )
    public_verifier_ref = builder.put_blob(
        artifact_id="public-verifier:counter-judge-e2e",
        artifact_type="build.public_verifier",
        content=validated.file("public_check.py").data,
        media_type="text/x-python;charset=utf-8",
        dependencies=(design_ref, implementation_contract_ref),
    )
    public_test_ref = builder.put_blob(
        artifact_id="public-test:counter-judge-e2e",
        artifact_type="build.public_test",
        content=validated.file("public_test.py").data,
        media_type="text/x-python;charset=utf-8",
        dependencies=(design_ref, implementation_contract_ref),
    )
    source_snapshot_ref = builder.put_blob(
        artifact_id="source-snapshot:counter-judge-e2e",
        artifact_type="build.source_workspace_snapshot",
        content=validated.deterministic_tar(),
        media_type="application/x-tar",
        dependencies=(design_ref, implementation_contract_ref),
    )
    implementation_lineage = ImplementationLineage(
        lineage_id="implementation-lineage:counter-judge-e2e",
        source_snapshot_refs=(source_snapshot_ref,),
        builder_profile_hash=sha256_digest(b"builder-shaped-real-candidate-input"),
        backend="framework-test-input",
        model="not-invoked",
        session_id="session:counter-judge-e2e",
        dependency_lock_hash=validated.file("uv.lock").content_hash,
        implementation_contract_ref=implementation_contract_ref,
    )
    implementation_lineage_ref = builder.put_json(
        artifact_id="implementation-lineage:counter-judge-e2e",
        artifact_type="build.implementation_lineage",
        value=implementation_lineage,
        dependencies=(source_snapshot_ref, implementation_contract_ref),
    )
    build_record = BuildRecord(
        build_id="build:counter-judge-e2e",
        candidate_id=candidate_id,
        candidate_revision=1,
        implementation_contract_ref=implementation_contract_ref,
        source_snapshot_ref=source_snapshot_ref,
        completion_hash=completion.content_digest(),
        files=validated.package_files,
        validations=(
            "declared_file_closure",
            "regular_file_only",
            "python_uv_project",
            "locked_dependencies",
            "required_component_paths",
            "deterministic_source_snapshot",
        ),
        agent_turn_number=1,
        public_self_check_argv=(".venv/bin/python", "-m", "public_check"),
    )
    build_artifact_ref = builder.put_json(
        artifact_id="build:counter-judge-e2e",
        artifact_type="build.record",
        value=build_record,
        dependencies=(source_snapshot_ref, implementation_lineage_ref),
    )
    runtime = RuntimeLaunch(argv=(".venv/bin/python", "-m", "runtime"))
    task_materializer = TaskMaterializerDescriptor(
        entrypoint="task_materializer:materialize",
        entry_path="task_materializer.py",
        output_schema_ref=task_schema_ref,
        curriculum_ref=curriculum_ref,
    )
    public_self_check = PublicSelfCheckDescriptor(
        argv=(".venv/bin/python", "-m", "public_check"),
        entry_path="public_check.py",
    )
    candidate_manifest = CandidateManifest(
        candidate_id=candidate_id,
        design_ref=design_ref,
        candidate_source_tree_digest=validated.candidate_source_tree_digest,
        runtime=runtime,
        task_materializer=task_materializer,
        public_self_check=public_self_check,
        public_verifier_ref=public_verifier_ref,
        public_test_refs=(public_test_ref,),
        files=validated.package_files,
        implementation_lineage_ref=implementation_lineage_ref,
    )
    candidate_manifest_ref = builder.put_json(
        artifact_id="candidate-manifest:counter-judge-e2e",
        artifact_type="build.candidate_manifest",
        value=candidate_manifest,
        dependencies=(
            design_ref,
            source_snapshot_ref,
            implementation_lineage_ref,
            public_verifier_ref,
            public_test_ref,
            task_schema_ref,
            curriculum_ref,
        ),
    )
    candidate = EnvironmentCandidate(
        candidate_id=candidate_id,
        revision=1,
        design_ref=design_ref,
        implementation_contract_ref=implementation_contract_ref,
        source_workspace_snapshot_ref=source_snapshot_ref,
        build_artifact_ref=build_artifact_ref,
        runtime=runtime,
        task_materializer=task_materializer,
        public_self_check=public_self_check,
        public_verifier_ref=public_verifier_ref,
        candidate_manifest_ref=candidate_manifest_ref,
        implementation_lineage_ref=implementation_lineage_ref,
    )
    candidate_ref = builder.put_json(
        artifact_id="candidate:counter-judge-e2e",
        artifact_type="build.environment_candidate",
        value=candidate,
        dependencies=(
            design_ref,
            implementation_contract_ref,
            source_snapshot_ref,
            build_artifact_ref,
            candidate_manifest_ref,
            implementation_lineage_ref,
        ),
    )
    case_definitions = (
        ("public", 11, 2, 3, 16),
        ("sealed", 99, 4, 5, 108),
    )
    cases = tuple(
        VerifierCase(
            case_id=f"case:counter-{partition}",
            partition=partition,  # type: ignore[arg-type]
            task_type="increase_counter",
            evaluator_goal={"target": target},
            seed=seed,
            actor="user",
            reset_config={"initial": initial},
            actions=(
                RuntimeAction(
                    tool_id="counter.increment",
                    arguments={"amount": amount},
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
                    ("rule:counter-invariant", 0, True),
                    ("rule:counter-positive", 0, True),
                    ("rule:counter-positive", 1, False),
                    ("rule:counter-transition", 0, True),
                    ("rule:counter-postcondition", 0, True),
                    ("rule:counter-error", 0, False),
                    ("rule:counter-error", 1, True),
                    ("rule:counter-success", 0, True),
                    ("rule:counter-terminal", 0, True),
                )
            ),
        )
        for partition, seed, initial, amount, target in case_definitions
    )
    property_definitions = (
        ("rule:counter-invariant", "invariant"),
        ("rule:counter-positive", "precondition"),
        ("rule:counter-transition", "transition"),
        ("rule:counter-postcondition", "postcondition"),
        ("rule:counter-error", "error_semantics"),
        ("rule:counter-success", "task_success"),
        ("rule:counter-terminal", "task_terminal"),
    )
    verifier = VerifierIR(
        verifier_ir_id="verifier:counter-judge-e2e",
        revision=1,
        world_spec_ref=world_spec_ref,
        design_ref=design_ref,
        properties=tuple(
            VerifierProperty(
                property_id=f"property:{rule_id}",
                kind=kind,  # type: ignore[arg-type]
                rule_ids=(rule_id,),
                case_ids=tuple(case.case_id for case in cases),
                description=f"Exercise the canonical {kind} rule in public and sealed cases.",
            )
            for rule_id, kind in property_definitions
        ),
        cases=cases,
        solve_recipes=(
            ParameterizedSolveRecipe(
                recipe_id="recipe:counter-increment",
                task_type="increase_counter",
                preferred=True,
                steps=(
                    ParameterizedSolveStep(
                        step_id="step:counter-increment",
                        tool_id="counter.increment",
                        arguments={"amount": RecipeLiteral(value=5)},
                    ),
                ),
            ),
        ),
    )
    verifier_ref = judge_writer(store).put_json(
        artifact_id="verifier-projection:counter-judge-e2e",
        artifact_type="judge.verifier_ir_projection",
        value=verifier.persistence_projection(),
        dependencies=(design_ref, world_spec_ref),
    )
    boundary_hash = design.world_spec.boundary.content_digest()
    return JudgeCandidateGraph(
        workspace=workspace,
        uv_path=uv_path,
        uv_cache_dir=uv_cache_dir,
        design=design,
        design_ref=design_ref,
        world_spec_ref=world_spec_ref,
        candidate=candidate,
        candidate_ref=candidate_ref,
        candidate_manifest=candidate_manifest,
        verifier=verifier,
        verifier_ref=verifier_ref,
        release_profile=ReleaseProfile(profile_id="release-profile:counter-judge-e2e"),
        owner_ref=owner_ref,
        implementation_lineage=implementation_lineage,
        package_id=f"env:{boundary_hash.removeprefix('sha256:')[:32]}",
        version="1.0.0",
    )


def commit_judged_manifest(
    store: ArtifactStore,
    graph: JudgeCandidateGraph,
    judge_report_ref: ArtifactRef,
    integration_report_ref: ArtifactRef,
) -> tuple[
    EnvironmentPackageManifest,
    ArtifactRef,
    tuple[FrameworkPackagePayload, ...],
]:
    """Bind only an actual EnvironmentJudge report into a publishable manifest."""

    report = store.get_json(judge_report_ref, JudgeReport)
    integration_report = store.get_json(integration_report_ref, IntegrationReport)
    if report.candidate_ref != graph.candidate_ref or report.verdict != "pass":
        raise ValueError("only this graph's passing EnvironmentJudge report can be packaged")
    if (
        integration_report.candidate_ref != graph.candidate_ref
        or integration_report.status != "ready"
    ):
        raise ValueError("only this graph's ready IntegrationReport can be packaged")
    world_spec_hash = graph.design.world_spec.content_digest()
    boundary_hash = graph.design.world_spec.boundary.content_digest()
    tool_hash = sha256_digest(
        canonical_json_bytes(
            [
                item.model_dump(mode="json", exclude_none=False)
                for item in sorted(
                    graph.design.world_spec.tools,
                    key=lambda value: value.surface.tool_id,
                )
            ]
        )
    )
    lineage = PackageLineage(
        semantic=SemanticLineage(
            lineage_id="semantic-lineage:counter-judge-e2e",
            operator_id="direct_generation",
            operator_version="1",
            seed=17,
            tool_contract_set_after_hash=tool_hash,
            world_spec_after_hash=world_spec_hash,
            semantic_delta_hash=sha256_digest(b"counter-judge-e2e-initial-world"),
            identity_decision=IdentityDecision(
                decision_id="identity:counter-judge-e2e",
                target_kind="new_package",
                boundary_after_hash=boundary_hash,
                changed_boundary_dimensions=(),
                rationale="Direct generation creates the executable counter identity.",
                confidence=1.0,
            ),
        ),
        implementation=graph.implementation_lineage,
    )
    telemetry_metrics_summary: dict[str, JsonValue] = {
        "as_of_ns": 1,
        "open_span_count": 1,
        "provisional": True,
        "critical_path_method": "provisional_trace_wall_envelope",
        "unknown_measurements": {},
    }
    telemetry = TelemetryReleaseSummary(
        trace_id="trace:counter-judge-e2e",
        run_id="trace:counter-judge-e2e",
        collected_at=datetime.now(UTC),
        cut_stage="pre_publish",
        as_of_ns=1,
        open_span_count=1,
        provisional=True,
        span_count=12,
        metric_count=24,
        event_count=8,
        invocation_count=3,
        required_node_attempts={
            "request": 1,
            "design": 1,
            "verifier": 1,
            "build": 1,
            "integration": 1,
            "judge": 1,
        },
        required_operation_attempts={
            "research.search": 1,
            "research.fetch": 1,
            "research.extract": 1,
        },
        required_metric_observations={
            "invocation.tokens.total": 3,
            "research.search.calls": 1,
            "research.fetch.calls": 1,
            "research.documents.extracted": 1,
        },
        unknown_measurement_count=0,
        summary=telemetry_metrics_summary,
        summary_digest=sha256_digest(canonical_json_bytes(telemetry_metrics_summary)),
    )
    telemetry_ref = framework_writer(store).put_json(
        artifact_id="telemetry-summary:counter-judge-e2e",
        artifact_type="release.telemetry_summary",
        value=telemetry,
        dependencies=(graph.owner_ref, graph.candidate_ref, judge_report_ref),
    )
    closure = _commit_prepackage_fixture_closure(
        store,
        owner_ref=graph.owner_ref,
        design_ref=graph.design_ref,
        candidate_ref=graph.candidate_ref,
        candidate_manifest_ref=graph.candidate.candidate_manifest_ref,
        build_record_ref=graph.candidate.build_artifact_ref,
        implementation_lineage_ref=graph.candidate.implementation_lineage_ref,
        verifier_ref=graph.verifier_ref,
        integration_report_ref=integration_report_ref,
        judge_report_ref=judge_report_ref,
        telemetry_summary_ref=telemetry_ref,
        release_profile=graph.release_profile,
    )
    framework_payloads = compile_framework_package_payloads(
        graph.design,
        package_id=graph.package_id,
        version=graph.version,
        candidate_manifest=graph.candidate_manifest,
        judge_report=report,
        integration_report=integration_report,
        lineage=lineage,
        design_ref=graph.design_ref,
        world_spec_ref=graph.world_spec_ref,
        candidate_ref=graph.candidate_ref,
        candidate_manifest_ref=graph.candidate.candidate_manifest_ref,
        build_record_ref=graph.candidate.build_artifact_ref,
        implementation_lineage_ref=graph.candidate.implementation_lineage_ref,
        judge_report_ref=judge_report_ref,
        integration_report_ref=integration_report_ref,
        release_dossier_ref=closure.dossier_ref,
        telemetry_summary_ref=telemetry_ref,
        pyproject_bytes=(graph.workspace / "pyproject.toml").read_bytes(),
        uv_lock_bytes=(graph.workspace / "uv.lock").read_bytes(),
    )
    manifest = EnvironmentPackageManifest(
        package_id=graph.package_id,
        version=graph.version,
        created_at=datetime.now(UTC),
        world_boundary_hash=boundary_hash,
        world_spec_hash=world_spec_hash,
        candidate_source_tree_digest=graph.candidate_manifest.candidate_source_tree_digest,
        design_ref=graph.design_ref,
        world_spec_ref=graph.world_spec_ref,
        candidate_ref=graph.candidate_ref,
        candidate_manifest_ref=graph.candidate.candidate_manifest_ref,
        build_record_ref=graph.candidate.build_artifact_ref,
        implementation_lineage_ref=graph.candidate.implementation_lineage_ref,
        judge_report_ref=judge_report_ref,
        integration_report_ref=integration_report_ref,
        release_dossier_ref=closure.dossier_ref,
        telemetry_summary_ref=telemetry_ref,
        runtime=graph.candidate.runtime,
        task_materializer=graph.candidate.task_materializer,
        trusted_evaluator=TrustedEvaluatorDescriptor(),
        public_self_check=graph.candidate.public_self_check,
        public_verifier_ref=graph.candidate.public_verifier_ref,
        files=(
            *graph.candidate_manifest.files,
            *(item.descriptor() for item in framework_payloads),
        ),
        lineage=lineage,
        known_limits=graph.candidate_manifest.known_limits,
    )
    manifest_ref = framework_writer(store).put_json(
        artifact_id="manifest:counter-judge-e2e",
        artifact_type="environment_package_manifest",
        value=manifest,
        dependencies=_unique_dependencies(
            (
                graph.design_ref,
                graph.world_spec_ref,
                graph.candidate_ref,
                graph.candidate.candidate_manifest_ref,
                graph.candidate.build_artifact_ref,
                judge_report_ref,
                integration_report_ref,
                closure.dossier_ref,
                telemetry_ref,
                graph.candidate.public_verifier_ref,
                graph.candidate.task_materializer.output_schema_ref,
                graph.candidate.task_materializer.curriculum_ref,
                graph.candidate.implementation_lineage_ref,
                graph.verifier_ref,
            )
        ),
    )
    _commit_fixture_package(closure, manifest_ref=manifest_ref)
    return manifest, manifest_ref, framework_payloads


def build_release_graph(
    root: Path,
    store: ArtifactStore,
    *,
    runtime_bytes: bytes | None = None,
    judge_passes: bool = True,
    owner_ref: ArtifactRef | None = None,
    release_profile: ReleaseProfile | None = None,
    world_spec_bytes_override: bytes | None = None,
    variant: str = "",
    commit_package: bool = True,
) -> ReleaseGraph:
    if variant and (
        not variant[0].isalnum()
        or any(character not in "abcdefghijklmnopqrstuvwxyz0123456789-_" for character in variant)
    ):
        raise ValueError("variant must be a lowercase path-safe identifier")

    def scoped(identifier: str) -> str:
        return f"{identifier}:{variant}" if variant else identifier

    if release_profile is None:
        release_profile = ReleaseProfile(
            profile_id=scoped("registry-v3-integration"),
            required_hard_gates=(
                "runtime_protocol",
                "task_materialization",
                "task_reachability",
                "clean_deployment",
            ),
        )

    workspace, uv_path, uv_cache_dir = write_candidate_project(root)
    if runtime_bytes is not None:
        (workspace / "runtime.py").write_bytes(runtime_bytes)
    portable = portable_counter_contracts(store)
    design = portable.design
    if variant:
        boundary = design.world_spec.boundary.model_copy(
            update={"primary_domain": f"counter-{variant}"}
        )
        world_spec = design.world_spec.model_copy(
            update={
                "world_spec_id": scoped(design.world_spec.world_spec_id),
                "boundary": boundary,
            }
        )
        design = design.model_copy(
            update={
                "design_id": scoped(design.design_id),
                "world_spec": world_spec,
            }
        )
    coverage_ref = commit_json(
        store,
        scoped("coverage:counter-v3"),
        "design.coverage_map",
        CoverageMap(
            coverage_id=scoped("coverage:counter-v3"),
            revision=1,
            dimensions=(
                CoverageDimension(
                    dimension="tool_semantics",
                    evidence_discovered="complete",
                    world_modelled="complete",
                    runtime_implemented="complete",
                    verifier_covered="complete",
                ),
                CoverageDimension(
                    dimension="transition_constraints",
                    evidence_discovered="complete",
                    world_modelled="complete",
                    runtime_implemented="complete",
                    verifier_covered="complete",
                ),
                CoverageDimension(
                    dimension="task_scope",
                    evidence_discovered="complete",
                    world_modelled="complete",
                    runtime_implemented="complete",
                    verifier_covered="complete",
                ),
            ),
            evidence_graph_ref=design.evidence_graph_ref,
        ),
        dependencies=(design.evidence_graph_ref,),
    )
    design = design.model_copy(update={"coverage_map_ref": coverage_ref})
    world_spec_ref = commit_json(
        store,
        scoped("world-spec:counter-v3"),
        "design.world_spec",
        design.world_spec,
        dependencies=(design.evidence_graph_ref,),
    )
    design_ref = commit_json(
        store,
        scoped("design:counter-v3"),
        "design.environment_design",
        design,
        dependencies=(coverage_ref, world_spec_ref),
    )
    if owner_ref is None:
        owner_request_ref = commit_json(
            store,
            scoped("request:counter-v3"),
            "control.environment_request",
            {"need": "fixture counter environment"},
        )
        owner_ref = commit_json(
            store,
            scoped("job:counter-v3"),
            "control.environment_job",
            EnvironmentJob(
                job_id=scoped("job:counter-v3"),
                kind="generate",
                request_ref=owner_request_ref,
                budget=Budget(),
                release_profile=release_profile,
            ),
            dependencies=(owner_request_ref,),
        )
    completion = CandidateCompletion(
        status="completed",
        project_root="candidate",
        root_project_mode="virtual-read-only-source-tree",
        dependency_install_mode="offline-wheel-only",
        runtime=CandidateRuntimeDeclaration(
            argv=(".venv/bin/python", "-m", "runtime"),
            entry_path="runtime.py",
        ),
        task_materializer=CandidateTaskMaterializerDeclaration(
            entrypoint="task_materializer:materialize",
            entry_path="task_materializer.py",
        ),
        public_self_check=CandidatePublicSelfCheckDeclaration(
            argv=(".venv/bin/python", "-m", "public_check"),
            entry_path="public_check.py",
        ),
        public_test_paths=("public_test.py",),
        files=tuple(
            CandidateFileDeclaration(
                path=item.path,
                role=item.role,  # type: ignore[arg-type]
                executable=item.executable,
            )
            for item in candidate_files(workspace)
        ),
    )
    validated = CandidateWorkspaceValidator().validate(workspace, completion)
    files = validated.package_files
    source_digest = validated.candidate_source_tree_digest
    candidate_id = scoped("candidate:counter-v3")
    builder = builder_writer(store)
    implementation_contract = ImplementationContract(
        contract_id=scoped("implementation-contract:counter-v3"),
        design_ref=design_ref,
        world_spec_hash=design.world_spec.content_digest(),
        state_schema_hash=design.world_spec.state.content_digest(),
        curriculum_hash=design.curriculum.content_digest(),
        runtime=EnvironmentBuilder._runtime_wire_contract(),  # noqa: SLF001
        tools=tuple(
            ToolBindingRequirement(
                tool_id=tool.surface.tool_id,
                tool_contract_hash=tool.content_digest(),
            )
            for tool in design.world_spec.tools
        ),
        task_materializer=TaskMaterializerContract(
            task_types=tuple(item.task_type for item in design.curriculum.task_types),
            minimum_distinct_initial_states=design.curriculum.minimum_distinct_initial_states,
            minimum_distinct_tasks_per_type=design.curriculum.minimum_distinct_tasks_per_type,
        ),
    )
    implementation_ref = builder.put_json(
        artifact_id=scoped("implementation-contract:counter-v3"),
        artifact_type="build.implementation_contract",
        value=implementation_contract,
        dependencies=(design_ref, world_spec_ref),
    )
    materializer_protocol_ref = builder.put_json(
        artifact_id=scoped("materializer-protocol:counter-v3"),
        artifact_type="build.task_materialization_schema",
        value=portable.materializer_protocol_schema,
        dependencies=(design_ref, implementation_ref),
    )
    curriculum_ref = builder.put_json(
        artifact_id=scoped("curriculum:counter-v3"),
        artifact_type="build.curriculum",
        value=design.curriculum,
        dependencies=(design_ref,),
    )
    public_verifier_ref = builder.put_blob(
        artifact_id=scoped("public-verifier:counter-v3"),
        artifact_type="build.public_verifier",
        content=validated.file("public_check.py").data,
        media_type="text/x-python;charset=utf-8",
        dependencies=(design_ref, implementation_ref),
    )
    public_test_ref = builder.put_blob(
        artifact_id=scoped("public-test:counter-v3"),
        artifact_type="build.public_test",
        content=validated.file("public_test.py").data,
        media_type="text/x-python;charset=utf-8",
        dependencies=(design_ref, implementation_ref),
    )
    source_snapshot_ref = builder.put_blob(
        artifact_id=scoped("source-snapshot:counter-v3"),
        artifact_type="build.source_workspace_snapshot",
        content=validated.deterministic_tar(),
        media_type="application/x-tar",
        dependencies=(design_ref, implementation_ref),
    )
    implementation_lineage = ImplementationLineage(
        lineage_id=scoped("implementation-lineage:counter-v3"),
        source_snapshot_refs=(source_snapshot_ref,),
        builder_profile_hash=sha256_digest(b"isolated-environment-engineer"),
        backend="codex_sdk",
        model="gpt-5.4",
        session_id=scoped("session:counter-v3"),
        dependency_lock_hash=validated.file("uv.lock").content_hash,
        implementation_contract_ref=implementation_ref,
    )
    implementation_lineage_ref = builder.put_json(
        artifact_id=scoped("implementation-lineage:counter-v3"),
        artifact_type="build.implementation_lineage",
        value=implementation_lineage,
        dependencies=(source_snapshot_ref, implementation_ref),
    )
    build_record = BuildRecord(
        build_id=scoped("build:counter-v3"),
        candidate_id=candidate_id,
        candidate_revision=1,
        implementation_contract_ref=implementation_ref,
        source_snapshot_ref=source_snapshot_ref,
        completion_hash=completion.content_digest(),
        files=files,
        validations=(
            "declared_file_closure",
            "regular_file_only",
            "python_uv_project",
            "locked_dependencies",
            "required_component_paths",
            "deterministic_source_snapshot",
        ),
        agent_turn_number=1,
        public_self_check_argv=(".venv/bin/python", "-m", "public_check"),
    )
    build_record_ref = builder.put_json(
        artifact_id=scoped("build:counter-v3"),
        artifact_type="build.record",
        value=build_record,
        dependencies=(source_snapshot_ref, implementation_lineage_ref),
    )
    runtime = RuntimeLaunch(argv=(".venv/bin/python", "-m", "runtime"))
    task_materializer = TaskMaterializerDescriptor(
        entrypoint="task_materializer:materialize",
        entry_path="task_materializer.py",
        output_schema_ref=materializer_protocol_ref,
        curriculum_ref=curriculum_ref,
    )
    public_self_check = PublicSelfCheckDescriptor(
        argv=(".venv/bin/python", "-m", "public_check"),
        entry_path="public_check.py",
    )
    candidate_manifest = CandidateManifest(
        candidate_id=candidate_id,
        design_ref=design_ref,
        candidate_source_tree_digest=source_digest,
        runtime=runtime,
        task_materializer=task_materializer,
        public_self_check=public_self_check,
        public_verifier_ref=public_verifier_ref,
        public_test_refs=(public_test_ref,),
        files=files,
        implementation_lineage_ref=implementation_lineage_ref,
    )
    candidate_manifest_ref = builder.put_json(
        artifact_id=scoped("candidate-manifest:counter-v3"),
        artifact_type="build.candidate_manifest",
        value=candidate_manifest,
        dependencies=(
            design_ref,
            source_snapshot_ref,
            implementation_lineage_ref,
            public_verifier_ref,
            public_test_ref,
            materializer_protocol_ref,
            curriculum_ref,
        ),
    )
    candidate = EnvironmentCandidate(
        candidate_id=candidate_id,
        revision=1,
        design_ref=design_ref,
        implementation_contract_ref=implementation_ref,
        source_workspace_snapshot_ref=source_snapshot_ref,
        build_artifact_ref=build_record_ref,
        runtime=runtime,
        task_materializer=task_materializer,
        public_self_check=public_self_check,
        public_verifier_ref=public_verifier_ref,
        candidate_manifest_ref=candidate_manifest_ref,
        implementation_lineage_ref=implementation_lineage_ref,
    )
    candidate_ref = builder.put_json(
        artifact_id=scoped("candidate:counter-v3"),
        artifact_type="build.environment_candidate",
        value=candidate,
        dependencies=(
            design_ref,
            implementation_ref,
            source_snapshot_ref,
            build_record_ref,
            candidate_manifest_ref,
            implementation_lineage_ref,
        ),
    )
    verifier_ref = judge_writer(store).put_json(
        artifact_id=scoped("verifier-projection:counter-v3"),
        artifact_type="judge.verifier_ir_projection",
        value={
            "verifier_ir_id": scoped("verifier:counter-v3"),
            "revision": 1,
            "world_spec_ref": world_spec_ref.model_dump(mode="json"),
            "design_ref": design_ref.model_dump(mode="json"),
            "public_case_count": 1,
            "sealed_case_count": 1,
        },
        dependencies=(design_ref, world_spec_ref),
    )
    evaluation_ref = judge_writer(store).put_json(
        artifact_id=scoped("evaluation:counter-v3"),
        artifact_type="judge.evaluation_evidence",
        value={"runtime_process": "completed", "isolated": True, "protocol": "envpkg-v3"},
        dependencies=(candidate_ref,),
    )
    reachability_ref = judge_writer(store).put_json(
        artifact_id=scoped("reachability:counter-v3"),
        artifact_type="judge.reachability_public_evidence",
        value=ReachabilityPublicEvidence(
            campaign_commitment=sha256_digest(scoped("counter-v3-reachability-campaign").encode()),
            candidate_ref=candidate_ref,
            materialized_instances=1,
            certified_instances=1,
            task_type_counts={"increase_counter": 1},
            strategy_counts={"interactive_challenger": 1},
            serve_policy_counts={"sampled_release": 1},
            budget_usage=BudgetUsage(evaluation_episodes=1),
        ),
        dependencies=(candidate_ref,),
    )
    passing_gates = tuple(
        GateResult(
            gate_id=gate_id,
            status="pass",
            hard=True,
            subject_ref=candidate_ref,
            evidence_refs=(reachability_ref if gate_id == "task_reachability" else evaluation_ref,),
            duration_seconds=0.01,
            summary="Independent real-process evidence passed.",
        )
        for gate_id in release_profile.required_hard_gates
    )
    integration_gate_ids = (
        "schema",
        "supply_chain",
        "static_assurance",
        "public_self_check",
        "runtime_protocol",
        "task_materialization",
        "clean_deployment",
    )
    integration_report = IntegrationReport(
        report_id=scoped("integration-report:counter-v3"),
        revision=1,
        candidate_ref=candidate_ref,
        candidate_source_tree_digest=source_digest,
        status="ready",
        gate_results=tuple(
            GateResult(
                gate_id=gate_id,
                status="pass",
                hard=True,
                subject_ref=candidate_ref,
                evidence_refs=(evaluation_ref,),
                duration_seconds=0.01,
                summary="Clean isolated integration evidence passed.",
            )
            for gate_id in integration_gate_ids
        ),
        evidence_refs=(evaluation_ref,),
        budget_usage=BudgetUsage(tool_calls=7, evaluation_episodes=2),
    )
    integration_report_ref = judge_writer(store).put_json(
        artifact_id=integration_report.report_id,
        artifact_type="judge.integration_report",
        value=integration_report,
        dependencies=(candidate_ref, world_spec_ref, evaluation_ref),
    )
    compiler_report = JudgeReport(
        report_id=(
            scoped("judge-report:counter-v3")
            if judge_passes
            else scoped("judge-report:counter-v3:framework-payload")
        ),
        revision=1,
        candidate_ref=candidate_ref,
        candidate_source_tree_digest=source_digest,
        verdict="pass",
        gate_results=passing_gates,
        evaluation_evidence_refs=(evaluation_ref, reachability_ref),
    )
    compiler_report_ref = judge_writer(store).put_json(
        artifact_id=compiler_report.report_id,
        artifact_type="judge_report",
        value=compiler_report,
        dependencies=(candidate_ref, verifier_ref, evaluation_ref, reachability_ref),
    )
    if judge_passes:
        report = compiler_report
        report_ref = compiler_report_ref
    else:
        failing_gates = tuple(
            gate.model_copy(
                update={
                    "status": "fail" if index == 0 else "pass",
                    "summary": (
                        "Independent real-process evidence failed."
                        if index == 0
                        else gate.summary
                    ),
                }
            )
            for index, gate in enumerate(passing_gates)
        )
        report = JudgeReport(
            report_id=scoped("judge-report:counter-v3"),
            revision=1,
            candidate_ref=candidate_ref,
            candidate_source_tree_digest=source_digest,
            verdict="fail",
            gate_results=failing_gates,
            evaluation_evidence_refs=(evaluation_ref, reachability_ref),
        )
        report_ref = judge_writer(store).put_json(
            artifact_id=report.report_id,
            artifact_type="judge_report",
            value=report,
            dependencies=(candidate_ref, verifier_ref, evaluation_ref, reachability_ref),
        )
    telemetry_metrics_summary: dict[str, JsonValue] = {
        "as_of_ns": 1,
        "open_span_count": 1,
        "provisional": True,
        "span_count": 12,
        "terminal_span_count": 11,
        "critical_path_method": "provisional_trace_wall_envelope",
        "metrics_sum": {"invocation.tokens.total": 4096.0},
        "unknown_measurements": {},
    }
    telemetry_summary = TelemetryReleaseSummary(
        trace_id=scoped("trace:counter-v3"),
        run_id=scoped("trace:counter-v3"),
        collected_at=datetime.now(UTC),
        cut_stage="pre_publish",
        as_of_ns=1,
        open_span_count=1,
        provisional=True,
        span_count=12,
        metric_count=24,
        event_count=8,
        invocation_count=4,
        required_node_attempts={
            "request": 1,
            "design": 1,
            "verifier": 1,
            "build": 1,
            "integration": 1,
            "judge": 1,
        },
        required_operation_attempts={
            "research.search": 1,
            "research.fetch": 1,
            "research.extract": 1,
        },
        required_metric_observations={
            "invocation.tokens.total": 4,
            "research.search.calls": 1,
            "research.fetch.calls": 1,
            "research.documents.extracted": 1,
        },
        unknown_measurement_count=0,
        summary=telemetry_metrics_summary,
        summary_digest=sha256_digest(canonical_json_bytes(telemetry_metrics_summary)),
    )
    telemetry_summary_ref = framework_writer(store).put_json(
        artifact_id=scoped("telemetry-summary:counter-v3"),
        artifact_type="release.telemetry_summary",
        value=telemetry_summary,
        dependencies=(owner_ref, candidate_ref, report_ref),
    )
    closure = _commit_prepackage_fixture_closure(
        store,
        owner_ref=owner_ref,
        design_ref=design_ref,
        candidate_ref=candidate_ref,
        candidate_manifest_ref=candidate_manifest_ref,
        build_record_ref=build_record_ref,
        implementation_lineage_ref=implementation_lineage_ref,
        verifier_ref=verifier_ref,
        integration_report_ref=integration_report_ref,
        judge_report_ref=report_ref,
        telemetry_summary_ref=telemetry_summary_ref,
        release_profile=release_profile,
    )
    boundary_hash = design.world_spec.boundary.content_digest()
    package_id = f"env:{boundary_hash.removeprefix('sha256:')[:32]}"
    version = "1.0.0"
    tool_hash = sha256_digest(
        canonical_json_bytes(
            [
                item.model_dump(mode="json", exclude_none=False)
                for item in sorted(design.world_spec.tools, key=lambda value: value.surface.tool_id)
            ]
        )
    )
    lineage = PackageLineage(
        semantic=SemanticLineage(
            lineage_id=scoped("semantic-lineage:counter-v3"),
            operator_id="direct_generation",
            operator_version="1",
            seed=17,
            tool_contract_set_after_hash=tool_hash,
            world_spec_after_hash=design.world_spec.content_digest(),
            semantic_delta_hash=sha256_digest(scoped("counter-v3-initial-world").encode()),
            identity_decision=IdentityDecision(
                decision_id=scoped("identity:counter-v3"),
                target_kind="new_package",
                boundary_after_hash=boundary_hash,
                changed_boundary_dimensions=(),
                rationale="Direct generation creates the counter environment identity.",
                confidence=1.0,
            ),
        ),
        implementation=implementation_lineage,
    )
    framework_payloads = list(
        compile_framework_package_payloads(
            design,
            package_id=package_id,
            version=version,
            candidate_manifest=candidate_manifest,
            judge_report=report,
            integration_report=integration_report,
            lineage=lineage,
            design_ref=design_ref,
            world_spec_ref=world_spec_ref,
            candidate_ref=candidate_ref,
            candidate_manifest_ref=candidate_manifest_ref,
            build_record_ref=build_record_ref,
            implementation_lineage_ref=implementation_lineage_ref,
            judge_report_ref=report_ref,
            integration_report_ref=integration_report_ref,
            release_dossier_ref=closure.dossier_ref,
            telemetry_summary_ref=telemetry_summary_ref,
            pyproject_bytes=(workspace / "pyproject.toml").read_bytes(),
            uv_lock_bytes=(workspace / "uv.lock").read_bytes(),
        )
    )
    if world_spec_bytes_override is not None:
        framework_payloads = [
            FrameworkPackagePayload(item.path, item.role, world_spec_bytes_override)
            if item.path == "world/world_spec.json"
            else item
            for item in framework_payloads
        ]
    world_spec_bytes = next(
        item.content for item in framework_payloads if item.path == "world/world_spec.json"
    )
    world_spec_hash = sha256_digest(world_spec_bytes)
    manifest = EnvironmentPackageManifest(
        package_id=package_id,
        version=version,
        created_at=datetime.now(UTC),
        world_boundary_hash=boundary_hash,
        world_spec_hash=world_spec_hash,
        candidate_source_tree_digest=source_digest,
        design_ref=design_ref,
        world_spec_ref=world_spec_ref,
        candidate_ref=candidate_ref,
        candidate_manifest_ref=candidate_manifest_ref,
        build_record_ref=build_record_ref,
        implementation_lineage_ref=implementation_lineage_ref,
        judge_report_ref=report_ref,
        integration_report_ref=integration_report_ref,
        release_dossier_ref=closure.dossier_ref,
        telemetry_summary_ref=telemetry_summary_ref,
        runtime=runtime,
        task_materializer=task_materializer,
        trusted_evaluator=TrustedEvaluatorDescriptor(),
        public_self_check=public_self_check,
        public_verifier_ref=public_verifier_ref,
        files=(*files, *(item.descriptor() for item in framework_payloads)),
        lineage=lineage,
    )
    manifest_ref = framework_writer(store).put_json(
        artifact_id=scoped("manifest:counter-v3"),
        artifact_type="environment_package_manifest",
        value=manifest,
        dependencies=(
            design_ref,
            world_spec_ref,
            candidate_ref,
            candidate_manifest_ref,
            build_record_ref,
            implementation_lineage_ref,
            report_ref,
            integration_report_ref,
            closure.dossier_ref,
            telemetry_summary_ref,
            verifier_ref,
            public_verifier_ref,
            materializer_protocol_ref,
            curriculum_ref,
            implementation_ref,
        ),
    )
    if commit_package:
        _commit_fixture_package(closure, manifest_ref=manifest_ref)
    return ReleaseGraph(
        workspace=workspace,
        uv_path=uv_path,
        uv_cache_dir=uv_cache_dir,
        manifest_ref=manifest_ref,
        report_ref=report_ref,
        release_profile=release_profile,
        candidate_ref=candidate_ref,
        owner_ref=owner_ref,
        framework_payloads=tuple(framework_payloads),
        package_id=package_id,
        version=version,
        package_closure=closure,
    )


__all__ = [
    "PUBLIC_SELF_CHECK_SOURCE",
    "PUBLIC_TEST_SOURCE",
    "LICENSE_SOURCE",
    "RUNTIME_SOURCE",
    "JudgeCandidateGraph",
    "ReleaseGraph",
    "SEEDED_RUNTIME_SOURCE",
    "SEEDED_TASK_MATERIALIZER_SOURCE",
    "TASK_MATERIALIZER_SOURCE",
    "build_judge_candidate_graph",
    "build_release_graph",
    "builder_writer",
    "candidate_files",
    "commit_judged_manifest",
    "commit_json",
    "framework_writer",
    "judge_writer",
    "portable_counter_contracts",
    "write_candidate_project",
]
