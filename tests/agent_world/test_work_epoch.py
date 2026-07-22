from __future__ import annotations

from pathlib import Path

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
    compile_design_work_graph,
    complete_generation_work_graph,
    deterministic_boundary_work_definition,
    verifier_plan_work_definition,
)
from agent_world.judge import VerifierBatchPlan, VerifierBatchPlanItem


def _stage(
    *,
    component: str,
    stage: str,
    dependencies=(),
):
    return deterministic_boundary_work_definition(
        scope_id="job:hotel",
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

    plan = _stage(component="research", stage="research_plan")
    acquisition = _stage(
        component="research",
        stage="evidence_acquisition",
        dependencies=(plan.coordinate,),
    )
    synthesis = _stage(
        component="research",
        stage="evidence_synthesis",
        dependencies=(acquisition.coordinate,),
    )
    architecture = _stage(
        component="design",
        stage="world_architecture",
        dependencies=(synthesis.coordinate,),
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
    curriculum = _stage(
        component="design",
        stage="task_curriculum",
        dependencies=(rules.coordinate,),
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
        design_definitions=(*bootstrap_definitions, behavior, rules, curriculum),
        modeling_definition=modeling,
        verifier_plan_definition=verifier_plan,
    )
    _, _, _, design_epoch_ref = epochs.freeze_design(
        context_ref=context_ref,
        bootstrap_epoch_ref=bootstrap_epoch_ref,
        graph=design_graph,
        topology_id="topology:hotel-design",
    )
    design_prior_ref = prior_ref
    design_output_ref: ArtifactRef | None = None
    world_spec_ref: ArtifactRef | None = None
    for definition in (behavior, rules, curriculum, modeling):
        output_ref = artifacts.put_json(
            artifact_id=f"design:{definition.coordinate.stage}",
            artifact_type=(
                "design.environment_design"
                if definition.coordinate.stage == "modeling_boundary"
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
