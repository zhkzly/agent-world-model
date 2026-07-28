from __future__ import annotations

from pathlib import Path

import pytest

from agent_world.artifact_store import ArtifactStore
from agent_world.contracts import (
    ArtifactRef,
    Budget,
    EnvironmentJob,
    GenerationContext,
    PermissionScope,
    ReleaseProfile,
    sha256_digest,
)
from agent_world.control import (
    GenerationWorkGraph,
    LeaseBudgetLedger,
    WorkControlRuntime,
    WorkControlStore,
    WorkGraphEpochRuntime,
    WorkGraphError,
    compile_design_work_graph,
    compile_world_work_graph,
    complete_generation_work_graph,
    curriculum_plan_work_definition,
    deterministic_boundary_work_definition,
    structured_agent_work_definition,
    verifier_plan_work_definition,
)
from agent_world.control.test_node import TestNodeRunner as NodeRunner
from agent_world.judge import VerifierBatchPlan, VerifierBatchPlanItem


def _stage(
    *,
    component: str,
    stage: str,
    dependencies=(),
    scope_id: str = "job:hotel",
):
    return deterministic_boundary_work_definition(
        scope_id=scope_id,
        component=component,  # type: ignore[arg-type]
        stage=stage,
        artifact_slot=stage,
        dependency_coordinates=dependencies,
        claim_id=f"{component}.{stage}.passed",
        claim=f"{component}/{stage} is committed under the exact generation context.",
        timing_reason="The final graph must retain causal bootstrap work.",
        effect="block_release",
        success_maturity=f"{stage}_closed",
    )


def test_final_epoch_retains_real_bootstrap_commits_without_shadow_design(
    tmp_path: Path,
) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    artifacts = store.issue_writer(
        producer="framework",
        allowed_artifact_type_prefixes=("control.", "design."),
    )
    judge_artifacts = store.issue_writer(
        producer="environment-judge",
        allowed_artifact_type_prefixes=("judge.",),
    )
    heads = WorkControlStore(tmp_path / "work-control")
    runtime = WorkControlRuntime(
        artifacts=artifacts,
        heads=heads,
        budget=LeaseBudgetLedger(Budget(agent_turns=10, wall_seconds=1_000)),
    )
    request_ref = artifacts.put_json(
        artifact_id="request:hotel",
        artifact_type="control.environment_request",
        value={"need": "用户预订宾馆"},
    )
    job = EnvironmentJob(
        job_id="job:hotel",
        kind="generate",
        request_ref=request_ref,
        budget=Budget(agent_turns=10, wall_seconds=1_000),
        release_profile=ReleaseProfile(profile_id="release:hotel"),
    )
    job_ref = artifacts.put_json(
        artifact_id=job.job_id,
        artifact_type="control.environment_job",
        value=job,
        dependencies=(request_ref,),
    )
    context = GenerationContext(
        context_id="context:hotel",
        job_ref=job_ref,
        kind="generate",
        request_ref=request_ref,
        permissions=PermissionScope(network_domains=("example.com",)),
        budget=job.budget,
        release_profile=job.release_profile,
    )
    context_ref = artifacts.put_json(
        artifact_id=context.context_id,
        artifact_type="control.generation_context",
        value=context,
        dependencies=context.root_refs,
    )

    plan = _stage(
        component="research",
        stage="research_plan",
        scope_id=job.job_id,
    )
    acquisition = _stage(
        component="research",
        stage="evidence_acquisition",
        dependencies=(plan.coordinate,),
        scope_id=job.job_id,
    )
    synthesis = _stage(
        component="research",
        stage="evidence_synthesis",
        dependencies=(acquisition.coordinate,),
        scope_id=job.job_id,
    )
    architecture = _stage(
        component="design",
        stage="world_architecture",
        dependencies=(synthesis.coordinate,),
        scope_id=job.job_id,
    )
    bootstrap_definitions = (plan, acquisition, synthesis, architecture)
    bootstrap_graph = GenerationWorkGraph.compile(
        bootstrap_definitions,
        mode="diagnostic",
    )
    epochs = WorkGraphEpochRuntime(artifacts=artifacts, heads=heads)
    _, _, _, bootstrap_epoch_ref = epochs.freeze_bootstrap(
        context_ref=context_ref,
        graph=bootstrap_graph,
        topology_id="topology:hotel-bootstrap",
    )

    prior_ref = context_ref
    for definition in bootstrap_definitions:
        output_ref = artifacts.put_json(
            artifact_id=f"bootstrap:{definition.coordinate.stage}",
            artifact_type=f"design.bootstrap_{definition.coordinate.stage}",
            value={"stage": definition.coordinate.stage},
            dependencies=(prior_ref,),
        )
        runtime.execute_deterministic_boundary(
            definition=definition,
            input_refs=(prior_ref,),
            subject_ref=output_ref,
            output_refs=(output_ref,),
        )
        prior_ref = output_ref

    behavior = _stage(
        component="design",
        stage="tool_semantics_batch",
        dependencies=(architecture.coordinate,),
    )
    rules = _stage(
        component="design",
        stage="world_rules",
        dependencies=(behavior.coordinate,),
    )
    curriculum_plan = _stage(
        component="design",
        stage="curriculum_plan",
        dependencies=(rules.coordinate,),
    )
    world_graph = compile_world_work_graph(
        scope_id="job:hotel",
        world_definitions=(*bootstrap_definitions, behavior, rules, curriculum_plan),
    )
    world_manifest, _, _, world_epoch_ref = epochs.freeze_world(
        context_ref=context_ref,
        bootstrap_epoch_ref=bootstrap_epoch_ref,
        graph=world_graph,
        topology_id="topology:hotel-world",
    )
    reconstructed_world = NodeRunner._reconstruct_graph(  # noqa: SLF001 - regression seed
        artifacts,
        world_manifest,
    )
    assert (
        reconstructed_world.manifest(
            topology_id=world_manifest.topology_id,
            external_root_refs=world_manifest.external_root_refs,
        )
        == world_manifest
    )

    world_prior_ref = prior_ref
    for definition, artifact_type in (
        (behavior, "design.tool_semantics_batch"),
        (rules, "design.world_rules_source"),
        (curriculum_plan, "design.curriculum_plan_source"),
    ):
        output_ref = artifacts.put_json(
            artifact_id=f"world:{definition.coordinate.stage}",
            artifact_type=artifact_type,
            value={"stage": definition.coordinate.stage},
            dependencies=(world_prior_ref,),
        )
        runtime.execute_deterministic_boundary(
            definition=definition,
            input_refs=(world_prior_ref,),
            subject_ref=output_ref,
            output_refs=(output_ref,),
        )
        world_prior_ref = output_ref

    task_requirement = _stage(
        component="design",
        stage="task_requirement",
        dependencies=(rules.coordinate, curriculum_plan.coordinate),
    ).model_copy(
        update={
            "coordinate": curriculum_plan.coordinate.model_copy(
                update={
                    "stage": "task_requirement",
                    "artifact_slot": "task_requirement_source",
                    "group_id": "task-requirements",
                    "shard_id": "booking",
                }
            )
        }
    )
    curriculum = _stage(
        component="design",
        stage="task_curriculum",
        dependencies=(rules.coordinate, curriculum_plan.coordinate, task_requirement.coordinate),
    )
    modeling = _stage(
        component="design",
        stage="modeling_boundary",
        dependencies=(curriculum.coordinate,),
    )
    verifier_plan = verifier_plan_work_definition(
        scope_id="job:hotel",
        modeling_coordinate=modeling.coordinate,
    )
    design_graph = compile_design_work_graph(
        scope_id="job:hotel",
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
    design_manifest, _, _, design_epoch_ref = epochs.freeze_design_from_world(
        context_ref=context_ref,
        world_epoch_ref=world_epoch_ref,
        graph=design_graph,
        topology_id="topology:hotel-design",
    )
    reconstructed_design = NodeRunner._reconstruct_graph(  # noqa: SLF001 - regression seed
        artifacts,
        design_manifest,
    )
    assert (
        reconstructed_design.manifest(
            topology_id=design_manifest.topology_id,
            external_root_refs=design_manifest.external_root_refs,
        )
        == design_manifest
    )
    design_prior_ref = world_prior_ref
    design_output_ref: ArtifactRef | None = None
    world_spec_ref: ArtifactRef | None = None
    for definition in (task_requirement, curriculum, modeling):
        output_ref = artifacts.put_json(
            artifact_id=f"design:{definition.coordinate.stage}",
            artifact_type=(
                "design.environment_design"
                if definition.coordinate.stage == "modeling_boundary"
                else "design.task_requirement_source"
                if definition.coordinate.stage == "task_requirement"
                else f"design.{definition.coordinate.stage}"
            ),
            value={"stage": definition.coordinate.stage},
            dependencies=(design_prior_ref,),
        )
        output_refs = (output_ref,)
        if definition.coordinate.stage == "modeling_boundary":
            world_spec_ref = artifacts.put_json(
                artifact_id="design:world-spec",
                artifact_type="design.world_spec",
                value={"world": "fixture"},
                dependencies=(output_ref,),
            )
            output_refs = (output_ref, world_spec_ref)
        runtime.execute_deterministic_boundary(
            definition=definition,
            input_refs=(design_prior_ref,),
            subject_ref=output_ref,
            output_refs=output_refs,
        )
        design_prior_ref = output_ref
        if definition.coordinate.stage == "modeling_boundary":
            design_output_ref = output_ref
    assert design_output_ref is not None
    assert world_spec_ref is not None
    plan = VerifierBatchPlan(
        plan_id="verifier-plan:hotel",
        design_ref=design_output_ref,
        world_spec_ref=world_spec_ref,
        maximum_tasks_per_batch=2,
        batches=(
            VerifierBatchPlanItem(
                batch_id="verifier-batch:1",
                batch_index=0,
                task_types=("booking",),
                required_rule_ids=(),
                required_property_families=(),
                semantic_case_limit=2,
                context_hash=sha256_digest(b"fixture-verifier-context"),
            ),
            VerifierBatchPlanItem(
                batch_id="verifier-batch:2",
                batch_index=1,
                task_types=("booking-cancel",),
                required_rule_ids=(),
                required_property_families=(),
                semantic_case_limit=2,
                context_hash=sha256_digest(b"fixture-verifier-context:2"),
            ),
        ),
    )
    plan_ref = judge_artifacts.put_json(
        artifact_id=plan.plan_id,
        artifact_type="judge.verifier_batch_plan",
        value=plan,
        dependencies=(design_output_ref, world_spec_ref),
    )
    runtime.execute_deterministic_boundary(
        definition=verifier_plan,
        input_refs=(design_output_ref, world_spec_ref),
        subject_ref=plan_ref,
        output_refs=(plan_ref,),
    )
    final_graph = complete_generation_work_graph(
        scope_id="job:hotel",
        design_graph=design_graph,
        verifier_batch_count=len(plan.batches),
    )
    manifest, _, final_epoch, _ = epochs.freeze_final(
        context_ref=context_ref,
        design_epoch_ref=design_epoch_ref,
        graph=final_graph,
        topology_id="topology:hotel-final",
    )

    assert manifest.releasable
    assert len(final_epoch.retained_commit_refs) == len(design_graph.definitions)
    assert final_epoch.predecessor_epoch_ref == design_epoch_ref


def test_legacy_diagnostic_world_epoch_replaces_only_unheaded_tail(
    tmp_path: Path,
) -> None:
    """A legacy graph may add only Plan while retaining exact committed parents.

    This is a constructed true control-plane boundary: durable WorkAttempts and
    WorkCommits are used for the historical closure, then the migration is
    rejected if one already-committed definition changes.  No model output is
    injected as a normal success path.
    """

    state_root = tmp_path / ".agent-world-live" / "test-node-legacy-world"
    store = ArtifactStore(state_root / "artifacts")
    artifacts = store.issue_writer(
        producer="framework",
        allowed_artifact_type_prefixes=("control.", "design."),
    )
    heads = WorkControlStore(state_root / "work-control")
    heads.mark_test_node_diagnostic_clone()
    runtime = WorkControlRuntime(
        artifacts=artifacts,
        heads=heads,
        budget=LeaseBudgetLedger(Budget(agent_turns=10, wall_seconds=1_000)),
        diagnostic_only=True,
    )
    request_ref = artifacts.put_json(
        artifact_id="request:legacy-world",
        artifact_type="control.environment_request",
        value={"need": "测试旧 WorldRules 闭包"},
    )
    job = EnvironmentJob(
        job_id="job:legacy-world",
        kind="generate",
        request_ref=request_ref,
        budget=Budget(agent_turns=10, wall_seconds=1_000),
        release_profile=ReleaseProfile(profile_id="release:legacy-world"),
    )
    job_ref = artifacts.put_json(
        artifact_id=job.job_id,
        artifact_type="control.environment_job",
        value=job,
        dependencies=(request_ref,),
    )
    context = GenerationContext(
        context_id="context:legacy-world",
        job_ref=job_ref,
        kind="generate",
        request_ref=request_ref,
        permissions=PermissionScope(),
        budget=job.budget,
        release_profile=job.release_profile,
    )
    context_ref = artifacts.put_json(
        artifact_id=context.context_id,
        artifact_type="control.generation_context",
        value=context,
        dependencies=context.root_refs,
    )

    plan = _stage(
        component="research",
        stage="research_plan",
        scope_id=job.job_id,
    )
    acquisition = _stage(
        component="research",
        stage="evidence_acquisition",
        dependencies=(plan.coordinate,),
        scope_id=job.job_id,
    )
    synthesis = _stage(
        component="research",
        stage="evidence_synthesis",
        dependencies=(acquisition.coordinate,),
        scope_id=job.job_id,
    )
    architecture = _stage(
        component="design",
        stage="world_architecture",
        dependencies=(synthesis.coordinate,),
        scope_id=job.job_id,
    )
    bootstrap_definitions = (plan, acquisition, synthesis, architecture)
    bootstrap_graph = GenerationWorkGraph.compile(bootstrap_definitions, mode="diagnostic")
    epochs = WorkGraphEpochRuntime(artifacts=artifacts, heads=heads)
    _, _, _, bootstrap_epoch_ref = epochs.freeze_bootstrap(
        context_ref=context_ref,
        graph=bootstrap_graph,
        topology_id="topology:legacy-world-bootstrap",
    )

    outputs: dict[str, ArtifactRef] = {}

    def commit(definition, parents: tuple[ArtifactRef, ...]) -> ArtifactRef:
        output = artifacts.put_json(
            artifact_id=(
                "legacy-output:"
                f"{definition.coordinate.stage}:{definition.coordinate.shard_id or 'one'}"
            ),
            artifact_type=f"design.legacy_{definition.coordinate.stage}",
            value={"stage": definition.coordinate.stage},
            dependencies=parents,
        )
        runtime.execute_deterministic_boundary(
            definition=definition,
            input_refs=parents,
            subject_ref=output,
            output_refs=(output,),
        )
        outputs[definition.coordinate.coordinate_key] = output
        return output

    current = context_ref
    for definition in bootstrap_definitions:
        current = commit(definition, (current,))

    behavior = _stage(
        component="design",
        stage="world_behavior",
        dependencies=(architecture.coordinate,),
        scope_id=job.job_id,
    )
    rules = _stage(
        component="design",
        stage="world_rules",
        dependencies=(behavior.coordinate,),
        scope_id=job.job_id,
    )
    legacy_curriculum = structured_agent_work_definition(
        scope_id=job.job_id,
        component="design",
        stage="task_curriculum",
        artifact_slot="task_curriculum",
        dependency_coordinates=(rules.coordinate,),
        claim_id="design.task_curriculum.compiles",
        claim="One historical whole-curriculum Agent turn compiles task semantics.",
        timing_reason="The pre-fan-out graph still needs an unheaded curriculum tail.",
        output_contract_id="contract:task-curriculum-source.v3",
        acceptance_transform_id="framework.training-semantics-compiler.v3",
        validator_revision_id="framework.validator.task-curriculum.v3",
        agent_role="environment_engineer",
        allowed_mutation_roots=("/curriculum_plan", "/task_requirements"),
        agent_wall_seconds=120,
        agent_token_limit=16_384,
    )
    modeling = _stage(
        component="design",
        stage="modeling_boundary",
        dependencies=(legacy_curriculum.coordinate,),
        scope_id=job.job_id,
    )
    verifier_plan = verifier_plan_work_definition(
        scope_id=job.job_id,
        modeling_coordinate=modeling.coordinate,
    )
    legacy_graph = compile_design_work_graph(
        scope_id=job.job_id,
        design_definitions=(*bootstrap_definitions, behavior, rules, legacy_curriculum),
        modeling_definition=modeling,
        verifier_plan_definition=verifier_plan,
    )
    legacy_manifest, legacy_manifest_ref, _, legacy_epoch_ref = epochs.freeze_design(
        context_ref=context_ref,
        bootstrap_epoch_ref=bootstrap_epoch_ref,
        graph=legacy_graph,
        topology_id="topology:legacy-world-design",
        allow_diagnostic_predecessors=True,
    )
    behavior_output = commit(behavior, (outputs[architecture.coordinate.coordinate_key],))
    commit(rules, (behavior_output,))

    curriculum_plan = curriculum_plan_work_definition(
        scope_id=job.job_id,
        task_curriculum_template=legacy_curriculum,
        agent_wall_seconds=legacy_curriculum.proposal_policy.budget.wall_seconds,
        agent_token_limit=legacy_curriculum.proposal_policy.budget.llm_tokens,
    )
    world_graph = compile_world_work_graph(
        scope_id=job.job_id,
        world_definitions=(*bootstrap_definitions, behavior, rules, curriculum_plan),
    )
    manifest, _, epoch, _ = epochs.freeze_diagnostic_world_from_legacy_design(
        context_ref=context_ref,
        legacy_design_epoch_ref=legacy_epoch_ref,
        legacy_manifest_ref=legacy_manifest_ref,
        graph=world_graph,
        topology_id="topology:legacy-world-plan",
    )

    rules_head = heads.read_head(rules.coordinate)
    assert rules_head is not None and rules_head.commit_ref is not None
    assert epoch.epoch_kind == "world"
    assert epoch.predecessor_epoch_ref == legacy_epoch_ref
    assert rules_head.commit_ref in epoch.retained_commit_refs
    assert manifest.required_terminal_coordinates == (curriculum_plan.coordinate,)
    assert heads.read_head(curriculum_plan.coordinate) is None

    drifted_rules = rules.model_copy(
        update={"claim": "This changed frozen WorldRules definition must be rejected."}
    )
    drifted_graph = compile_world_work_graph(
        scope_id=job.job_id,
        world_definitions=(
            *bootstrap_definitions,
            behavior,
            drifted_rules,
            curriculum_plan,
        ),
    )
    with pytest.raises(WorkGraphError, match="already-frozen definition"):
        epochs.freeze_diagnostic_world_from_legacy_design(
            context_ref=context_ref,
            legacy_design_epoch_ref=legacy_epoch_ref,
            legacy_manifest_ref=legacy_manifest_ref,
            graph=drifted_graph,
            topology_id="topology:legacy-world-plan-drifted",
        )
