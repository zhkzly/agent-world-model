"""Scheduler-owned one-attempt leaves for verifier planning, compilation and join."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from agent_world.builder import BuilderError, EnvironmentBuilder
from agent_world.contracts import (
    ArtifactRef,
    Budget,
    BudgetUsage,
    EnvironmentCandidate,
    EnvironmentDesign,
    GenerationContext,
    IntegrationReport,
    JudgeReport,
    ReleaseProfile,
    VerifierIR,
    WorldSpec,
    canonical_json_bytes,
    sha256_digest,
)
from agent_world.control.leaf_executor import (
    AgentExecutionProvenance,
    LeafExecutionFailure,
    LeafProposal,
    LeafValidationFailure,
    SchedulerLeafExecutor,
)
from agent_world.control.work import ValidationIssue, WorkAttempt, WorkDefinition
from agent_world.control.work_scheduler import WorkExecutionContext
from agent_world.invocation import InvocationResult, ResolvedAgentProfile

from .compiler import VerifierCompilationError, VerifierCompiler
from .models import VerifierBatchDraft, VerifierBatchPlan, VerifierIntent
from .service import EnvironmentJudge, IntegrationBundle, JudgeBundle


@dataclass(slots=True)
class VerifierPlanLeaf:
    """Persist the deterministic verifier partition under a code-owned WorkAttempt."""

    compiler: VerifierCompiler
    kernel: SchedulerLeafExecutor

    async def execute(
        self,
        context: WorkExecutionContext,
        *,
        definition: WorkDefinition,
    ) -> None:
        async def proposal(
            current_context: WorkExecutionContext,
            _attempt: WorkAttempt,
            _dispatch_id: str,
        ) -> LeafProposal:
            design_ref, design, world_spec_ref = _modeling_design_closure(
                current_context,
                self.compiler,
            )
            plan = self.compiler.build_batch_plan(
                design=design,
                design_ref=design_ref,
                world_spec_ref=world_spec_ref,
            )
            plan_ref = self.compiler.persist_batch_plan(plan)
            return LeafProposal(
                output_refs=(plan_ref,),
                subject_refs=(plan_ref,),
            )

        await self.kernel.execute(context, definition=definition, proposal_runner=proposal)


@dataclass(slots=True)
class VerifierBatchLeaf:
    """Compile exactly one frozen Challenger partition in one Scheduler dispatch."""

    compiler: VerifierCompiler
    workspace_root: Path
    kernel: SchedulerLeafExecutor

    async def execute(
        self,
        context: WorkExecutionContext,
        *,
        definition: WorkDefinition,
    ) -> None:
        async def proposal(
            current_context: WorkExecutionContext,
            attempt: WorkAttempt,
            dispatch_id: str,
        ) -> LeafProposal:
            plan_ref, plan = self._plan_from_context(current_context)
            design_ref, design, world_spec_ref = _plan_design_closure(self.compiler, plan)
            batch_index = self._batch_index(definition, plan)
            try:
                result = await self.compiler.compile_batch_once(
                    design=design,
                    design_ref=design_ref,
                    world_spec_ref=world_spec_ref,
                    plan=plan,
                    plan_ref=plan_ref,
                    batch_index=batch_index,
                    workspace=self.workspace_root / attempt.attempt_id,
                    lineage_id=f"{definition.coordinate.scope_id}:verifier-batch",
                    budget=self._budget(definition),
                    permissions=_generation_permissions(current_context, self.compiler),
                    invocation_id=dispatch_id,
                )
            except VerifierCompilationError as exc:
                provenance = (
                    self._provenance(exc.profile, dispatch_id) if exc.profile is not None else None
                )
                usage, unknown = self._usage(
                    exc.result,
                    budget=self._budget(definition),
                )
                code = self._safe_code("verifier_compilation_error")
                if provenance is None:
                    code = f"preflight_{code}"
                raise LeafExecutionFailure(
                    code=code,
                    category="VerifierCompilationError",
                    observed_actual=usage,
                    unknown_upper_bound=unknown,
                    agent=provenance,
                ) from exc

            provenance = self._provenance(result.profile, dispatch_id)
            usage, unknown = self._usage(result.invocation, budget=self._budget(definition))
            if not result.invocation.succeeded:
                backend_code = (
                    result.invocation.error.code
                    if result.invocation.error is not None
                    else result.invocation.status.value
                )
                raise LeafExecutionFailure(
                    code=self._safe_code(f"verifier_backend_{backend_code}"),
                    category="VerifierBackendTerminal",
                    observed_actual=usage,
                    unknown_upper_bound=unknown,
                    agent=provenance,
                )
            if result.validation_diagnostic is not None:
                raise LeafValidationFailure(
                    issues=tuple(
                        ValidationIssue(
                            code=issue.code,
                            path=issue.location,
                            violated_condition=(issue.violated_condition or issue.message),
                            expected_category=(
                                issue.expected_category
                                or "the frozen verifier intent contract at this path"
                            ),
                            retryable=issue.retryable,
                        )
                        for issue in result.validation_diagnostic.issues
                    ),
                    output_commitment=self._output_commitment(result.invocation),
                    category=result.validation_diagnostic.validation_phase,
                    observed_actual=usage,
                    unknown_upper_bound=unknown,
                    agent=provenance,
                )
            if not result.succeeded or result.checkpoint_ref is None or result.draft_ref is None:
                raise RuntimeError("one-shot Verifier result omitted its required Artifact closure")
            return LeafProposal(
                output_refs=(result.checkpoint_ref, result.draft_ref),
                subject_refs=(result.checkpoint_ref, result.draft_ref),
                observed_actual=usage,
                unknown_upper_bound=unknown,
                agent=provenance,
            )

        await self.kernel.execute(context, definition=definition, proposal_runner=proposal)

    def _plan_from_context(
        self,
        context: WorkExecutionContext,
    ) -> tuple[ArtifactRef, VerifierBatchPlan]:
        candidates = tuple(
            ref
            for ref in context.parent_output_refs
            if ref.artifact_type == "judge.verifier_batch_plan"
        )
        if len(candidates) != 1:
            raise LeafExecutionFailure(
                code="preflight_verifier_plan_missing",
                category="missing exact verifier batch plan input",
            )
        plan_ref = candidates[0]
        return plan_ref, self.compiler.artifacts.get_json(plan_ref, VerifierBatchPlan)

    @staticmethod
    def _batch_index(definition: WorkDefinition, plan: VerifierBatchPlan) -> int:
        shard_id = definition.coordinate.shard_id
        if shard_id is None or not shard_id.startswith("batch-"):
            raise LeafExecutionFailure(
                code="preflight_verifier_batch_coordinate_invalid",
                category="invalid verifier physical shard coordinate",
            )
        try:
            index = int(shard_id.removeprefix("batch-")) - 1
        except ValueError as exc:
            raise LeafExecutionFailure(
                code="preflight_verifier_batch_coordinate_invalid",
                category="invalid verifier physical shard coordinate",
            ) from exc
        if not 0 <= index < len(plan.batches):
            raise LeafExecutionFailure(
                code="preflight_verifier_plan_shard_mismatch",
                category="verifier plan does not contain this physical shard",
            )
        return index

    @staticmethod
    def _budget(definition: WorkDefinition) -> Budget:
        policy = definition.proposal_policy.budget
        return Budget(
            llm_tokens=policy.llm_tokens,
            agent_turns=policy.agent_turns,
            tool_calls=policy.tool_calls,
            process_calls=policy.process_calls,
            wall_seconds=policy.wall_seconds,
            monetary_cost=policy.monetary_cost,
        )

    @staticmethod
    def _usage(
        invocation: InvocationResult | None,
        *,
        budget: Budget,
    ) -> tuple[BudgetUsage, BudgetUsage]:
        if invocation is None:
            return BudgetUsage(), BudgetUsage()
        total_tokens = (
            invocation.usage.turn.total_tokens
            if invocation.usage is not None and invocation.usage.turn is not None
            else 0
        )
        return (
            BudgetUsage(
                llm_tokens=total_tokens,
                agent_turns=1,
                wall_seconds=max(0.0, invocation.duration_ms / 1_000),
            ),
            BudgetUsage(llm_tokens=(0 if total_tokens else budget.llm_tokens)),
        )

    @staticmethod
    def _provenance(
        profile: ResolvedAgentProfile,
        invocation_id: str,
    ) -> AgentExecutionProvenance:
        return AgentExecutionProvenance(
            invocation_id=invocation_id,
            provider=profile.model_provider or "openai",
            model=profile.model,
            profile_digest=f"sha256:{profile.profile_hash}",
            output_schema_digest=sha256_digest(
                canonical_json_bytes(VerifierIntent.model_json_schema(mode="validation"))
            ),
        )

    @staticmethod
    def _output_commitment(invocation: InvocationResult) -> str:
        return sha256_digest(
            canonical_json_bytes(
                {
                    "invocation_id": invocation.invocation_id,
                    "structured_output": invocation.structured_output,
                }
            )
        )

    @staticmethod
    def _safe_code(value: str) -> str:
        safe = "".join(
            character if character.isalnum() or character in "._:-" else "_"
            for character in value
        ).strip("._:-")
        return (safe or "verifier_failed")[:120]


@dataclass(slots=True)
class VerifierAggregateLeaf:
    """Deterministically merge every exact committed verifier batch into Verifier IR."""

    compiler: VerifierCompiler
    kernel: SchedulerLeafExecutor

    async def execute(
        self,
        context: WorkExecutionContext,
        *,
        definition: WorkDefinition,
    ) -> None:
        async def proposal(
            current_context: WorkExecutionContext,
            _attempt: WorkAttempt,
            _dispatch_id: str,
        ) -> LeafProposal:
            draft_refs = tuple(
                ref
                for ref in current_context.parent_output_refs
                if ref.artifact_type == "judge.verifier_batch_draft"
            )
            if not draft_refs:
                raise LeafExecutionFailure(
                    code="verifier_aggregate_drafts_missing",
                    category="missing verifier batch draft inputs",
                )
            batch_drafts = tuple(
                self.compiler.artifacts.get_json(ref, VerifierBatchDraft) for ref in draft_refs
            )
            plan_ref = batch_drafts[0].plan_ref
            if any(item.plan_ref != plan_ref for item in batch_drafts):
                raise LeafExecutionFailure(
                    code="verifier_aggregate_plan_mismatch",
                    category="verifier batches bind different frozen plans",
                )
            plan = self.compiler.artifacts.get_json(plan_ref, VerifierBatchPlan)
            design_ref, design, world_spec_ref = _plan_design_closure(self.compiler, plan)
            if len(batch_drafts) != len(plan.batches) or {
                item.batch_id for item in batch_drafts
            } != {item.batch_id for item in plan.batches}:
                raise LeafExecutionFailure(
                    code="verifier_aggregate_batch_closure_incomplete",
                    category="verifier aggregate lacks the exact planned batch set",
                )
            by_batch_id = {item.batch_id: item for item in batch_drafts}
            drafts = tuple(by_batch_id[item.batch_id].draft for item in plan.batches)
            try:
                merged = VerifierCompiler._merge_batch_drafts(drafts)
                VerifierCompiler._validate_draft(merged, design)
                verifier = VerifierIR(
                    verifier_ir_id=f"verifier:{definition.coordinate.scope_id}",
                    revision=1,
                    world_spec_ref=world_spec_ref,
                    design_ref=design_ref,
                    properties=merged.properties,
                    cases=merged.cases,
                    solve_recipes=merged.solve_recipes,
                )
                verifier_ref = self.compiler.artifacts.put_json(
                    artifact_id=(
                        f"{definition.coordinate.scope_id}:verifier-ir-projection"
                    ),
                    artifact_type="judge.verifier_ir_projection",
                    value=verifier.persistence_projection(),
                    dependencies=(
                        design_ref,
                        world_spec_ref,
                        plan_ref,
                        *draft_refs,
                    ),
                )
            except Exception as exc:
                raise LeafExecutionFailure(
                    code="verifier_aggregate_framework_error",
                    category=type(exc).__name__,
                ) from exc
            return LeafProposal(
                output_refs=(verifier_ref,),
                subject_refs=(verifier_ref,),
                child_commit_refs=current_context.parent_commit_refs,
            )

        await self.kernel.execute(context, definition=definition, proposal_runner=proposal)


def _modeling_design_closure(
    context: WorkExecutionContext,
    compiler: VerifierCompiler,
) -> tuple[ArtifactRef, EnvironmentDesign, ArtifactRef]:
    """Load the exact Design closure committed by the direct Modeling parent.

    These references are intentionally derived from the Scheduler dispatch
    envelope.  Injecting a separately held Design into a leaf would create a
    second, unverifiable control path after a retry or resume.
    """

    design_ref = _one_parent_output(context, "design.environment_design")
    world_spec_ref = _one_parent_output(context, "design.world_spec")
    design = compiler.artifacts.get_json(design_ref, EnvironmentDesign)
    compiler.artifacts.require_exact_json(
        world_spec_ref,
        design.world_spec,
        artifact_types=("design.world_spec", "expansion.world_spec"),
    )
    return design_ref, design, world_spec_ref


def _plan_design_closure(
    compiler: VerifierCompiler,
    plan: VerifierBatchPlan,
) -> tuple[ArtifactRef, EnvironmentDesign, ArtifactRef]:
    """Recover the immutable Design bytes named by a persisted VerifierPlan."""

    design = compiler.artifacts.get_json(plan.design_ref, EnvironmentDesign)
    compiler.artifacts.require_exact_json(
        plan.world_spec_ref,
        design.world_spec,
        artifact_types=("design.world_spec", "expansion.world_spec"),
    )
    return plan.design_ref, design, plan.world_spec_ref


def _generation_permissions(
    context: WorkExecutionContext,
    compiler: VerifierCompiler,
):
    context_ref = _one_external_input(context, "control.generation_context")
    generation = compiler.artifacts.get_json(context_ref, GenerationContext)
    return generation.permissions


def _one_parent_output(context: WorkExecutionContext, artifact_type: str) -> ArtifactRef:
    matches = tuple(ref for ref in context.parent_output_refs if ref.artifact_type == artifact_type)
    if len(matches) != 1:
        raise LeafExecutionFailure(
            code=f"preflight_exact_{artifact_type.replace('.', '_')}_missing",
            category="missing exact committed parent Artifact",
        )
    return matches[0]


def _one_external_input(context: WorkExecutionContext, artifact_type: str) -> ArtifactRef:
    matches = tuple(
        ref for ref in context.external_input_refs if ref.artifact_type == artifact_type
    )
    if len(matches) != 1:
        raise LeafExecutionFailure(
            code=f"preflight_exact_{artifact_type.replace('.', '_')}_missing",
            category="missing exact immutable generation input",
        )
    return matches[0]


@dataclass(slots=True)
class IntegrationLeaf:
    """Run the one real clean-install/runtime integration pass for one Candidate.

    This leaf does not manufacture a smoke-test result or invoke a model.  It
    restores the exact source tar into a fresh workspace and calls
    :meth:`EnvironmentJudge.evaluate_integration`, whose report is the only
    evidence used by the deterministic Work validation.  Candidate failures
    are routed to the declared mutable parent only when the Judge's typed
    findings assign every blocking cause to Build.
    """

    builder: EnvironmentBuilder
    judge: EnvironmentJudge
    release_profile: ReleaseProfile
    workspace_root: Path
    run_id: str
    kernel: SchedulerLeafExecutor

    async def execute(
        self,
        context: WorkExecutionContext,
        *,
        definition: WorkDefinition,
    ) -> None:
        async def proposal(
            current_context: WorkExecutionContext,
            attempt: WorkAttempt,
            _dispatch_id: str,
        ) -> LeafProposal:
            candidate_ref, candidate = self._candidate_from_context(current_context)
            design, world_spec_ref, world_spec = self._design_world(candidate, candidate_ref)
            try:
                source_dir = self.builder.materialize_exact_candidate(
                    candidate=candidate,
                    candidate_ref=candidate_ref,
                    workspace=self.workspace_root / attempt.attempt_id,
                )
            except BuilderError as exc:
                raise LeafValidationFailure(
                    issues=(
                        ValidationIssue(
                            code="candidate_snapshot_materialization_failed",
                            path=("candidate", "source_snapshot"),
                            violated_condition=(
                                "The committed Candidate snapshot cannot be restored."
                            ),
                            expected_category="a complete verified Candidate source closure",
                        ),
                    ),
                    output_commitment=candidate_ref.content_hash,
                    category="candidate_snapshot_recovery",
                    parent_repair_target=self._unique_build_target(definition),
                ) from exc
            budget = self._budget(definition)
            try:
                bundle = await self.judge.evaluate_integration(
                    candidate=candidate,
                    candidate_ref=candidate_ref,
                    source_dir=source_dir,
                    world_spec=world_spec,
                    world_spec_ref=world_spec_ref,
                    release_profile=self.release_profile,
                    budget=budget,
                    run_id=f"{self.run_id}:integration:{attempt.attempt_id}",
                )
            except Exception as exc:
                raise LeafExecutionFailure(
                    code="integration_execution_error",
                    category=type(exc).__name__,
                ) from exc
            return self._integration_proposal(bundle, definition=definition)

        await self.kernel.execute(context, definition=definition, proposal_runner=proposal)

    def _candidate_from_context(
        self,
        context: WorkExecutionContext,
    ) -> tuple[ArtifactRef, EnvironmentCandidate]:
        candidates = tuple(
            ref
            for ref in context.parent_output_refs
            if ref.artifact_type == "build.environment_candidate"
        )
        if len(candidates) != 1:
            raise LeafExecutionFailure(
                code="preflight_integration_candidate_missing",
                category="missing exact Candidate input",
            )
        candidate_ref = candidates[0]
        return candidate_ref, self.judge.artifacts.get_json(candidate_ref, EnvironmentCandidate)

    def _design_world(
        self,
        candidate: EnvironmentCandidate,
        candidate_ref: ArtifactRef,
    ) -> tuple[EnvironmentDesign, ArtifactRef, WorldSpec]:
        design = self.judge.artifacts.get_json(candidate.design_ref, EnvironmentDesign)
        self.judge.artifacts.require_exact_json(
            candidate.design_ref,
            design,
            artifact_types=("design.environment_design", "expansion.environment_design"),
        )
        world_refs = tuple(
            ref
            for ref in self.judge.artifacts.dependencies(candidate.design_ref)
            if ref.artifact_type in {"design.world_spec", "expansion.world_spec"}
        )
        if len(world_refs) != 1:
            raise LeafExecutionFailure(
                code="preflight_integration_world_spec_closure_invalid",
                category="Candidate Design has no unique WorldSpec dependency",
            )
        world_spec_ref = world_refs[0]
        world_spec = self.judge.artifacts.get_json(world_spec_ref, WorldSpec)
        self.judge.artifacts.require_exact_json(
            candidate_ref,
            candidate,
            artifact_types=("build.environment_candidate",),
        )
        if design.world_spec != world_spec:
            raise LeafExecutionFailure(
                code="preflight_integration_design_world_mismatch",
                category="Candidate Design differs from its exact WorldSpec closure",
            )
        return design, world_spec_ref, world_spec

    def _integration_proposal(
        self,
        bundle: IntegrationBundle,
        *,
        definition: WorkDefinition,
    ) -> LeafProposal:
        report = bundle.report
        usage = report.budget_usage
        if report.status == "ready":
            return LeafProposal(
                output_refs=(bundle.report_ref,),
                subject_refs=(bundle.report_ref,),
                observed_actual=usage,
            )
        if report.status == "error":
            raise LeafExecutionFailure(
                code="integration_judge_infrastructure_error",
                category="independent integration infrastructure failed",
                observed_actual=usage,
            )
        raise LeafValidationFailure(
            issues=self._report_issues(report, stage="integration"),
            output_commitment=bundle.report_ref.content_hash,
            category="independent_integration_failed",
            observed_actual=usage,
            evidence_refs=(bundle.report_ref,),
            parent_repair_target=(
                self._unique_build_target(definition)
                if self._all_blocking_findings_owned_by(report, owner="build")
                else None
            ),
        )

    @staticmethod
    def _all_blocking_findings_owned_by(
        report: IntegrationReport | JudgeReport,
        *,
        owner: str,
    ) -> bool:
        findings = tuple(item for item in report.findings if item.blocks_release)
        return bool(findings) and all(item.owner == owner for item in findings)

    @staticmethod
    def _report_issues(
        report: IntegrationReport | JudgeReport,
        *,
        stage: str,
    ) -> tuple[ValidationIssue, ...]:
        issues: list[ValidationIssue] = []
        for index, gate in enumerate(item for item in report.gate_results if item.status != "pass"):
            issues.append(
                ValidationIssue(
                    code=f"{stage}_gate_{gate.gate_id}_{gate.status}"[:120],
                    path=(stage, "gate", index),
                    violated_condition=gate.summary[:512],
                    expected_category="the exact independent execution gate to pass",
                    retryable=gate.status != "error",
                )
            )
        for index, finding in enumerate(item for item in report.findings if item.blocks_release):
            issues.append(
                ValidationIssue(
                    code=f"{stage}_finding_{finding.category}"[:120],
                    path=(stage, "finding", index),
                    violated_condition=finding.summary[:512],
                    expected_category="a Candidate and verifier closure satisfying this finding",
                    retryable=finding.owner not in {"permissions", "release_policy"},
                )
            )
        if issues:
            return tuple(issues)
        # Contract validation permits a terminal failed report only with hard
        # gate/finding evidence, but retain one safe fallback if an external
        # implementation violates that invariant before it reaches this leaf.
        return (
            ValidationIssue(
                code=f"{stage}_report_non_passing",
                path=(stage, "report"),
                violated_condition="The independent report did not establish its required Claim.",
                expected_category="a passing independent report",
                retryable=False,
            ),
        )

    @staticmethod
    def _unique_build_target(definition: WorkDefinition):
        targets = tuple(
            coordinate
            for coordinate in definition.repair_target_coordinates
            if coordinate.component == "build"
        )
        if len(targets) != 1:
            raise LeafExecutionFailure(
                code="preflight_integration_build_route_ambiguous",
                category="integration definition lacks one Build causal target",
            )
        return targets[0]

    @staticmethod
    def _budget(definition: WorkDefinition) -> Budget:
        policy = definition.proposal_policy.budget
        return Budget(
            tool_calls=policy.tool_calls,
            process_calls=policy.process_calls,
            build_seconds=policy.build_seconds,
            evaluation_episodes=policy.evaluation_episodes,
            container_seconds=policy.container_seconds,
            live_probe_cost=policy.live_probe_cost,
            wall_seconds=policy.wall_seconds,
            monetary_cost=policy.monetary_cost,
        )


@dataclass(slots=True)
class ReleaseAssuranceLeaf(IntegrationLeaf):
    """Run the independent sealed-release Judge without hidden Agent calls."""

    async def execute(
        self,
        context: WorkExecutionContext,
        *,
        definition: WorkDefinition,
    ) -> None:
        async def proposal(
            current_context: WorkExecutionContext,
            attempt: WorkAttempt,
            _dispatch_id: str,
        ) -> LeafProposal:
            if self.judge.interactive_challenger is not None:
                raise LeafExecutionFailure(
                    code="preflight_release_hidden_agent_rollout",
                    category="release Judge must not hide Challenger Agent turns",
                )
            candidate_ref, candidate = self._candidate_from_context(current_context)
            _design, world_spec_ref, world_spec = self._design_world(candidate, candidate_ref)
            verifier_ref, verifier = self._verifier_from_context(current_context)
            integration_ref, integration = self._integration_from_context(current_context)
            if (
                integration.status != "ready"
                or integration.candidate_ref != candidate_ref
                or integration.candidate_source_tree_digest is None
            ):
                raise LeafValidationFailure(
                    issues=(
                        ValidationIssue(
                            code="release_integration_evidence_not_ready",
                            path=("integration", "report"),
                            violated_condition=(
                                "Release assurance requires exact ready Integration evidence."
                            ),
                            expected_category="a ready IntegrationReport for this Candidate",
                        ),
                    ),
                    output_commitment=integration_ref.content_hash,
                    category="integration_precondition",
                    evidence_refs=(integration_ref,),
                    parent_repair_target=self._unique_build_target(definition),
                )
            try:
                source_dir = self.builder.materialize_exact_candidate(
                    candidate=candidate,
                    candidate_ref=candidate_ref,
                    workspace=self.workspace_root / attempt.attempt_id,
                )
            except BuilderError as exc:
                raise LeafValidationFailure(
                    issues=(
                        ValidationIssue(
                            code="release_candidate_snapshot_materialization_failed",
                            path=("candidate", "source_snapshot"),
                            violated_condition=(
                                "Release Judge cannot restore the exact Candidate source."
                            ),
                            expected_category="a complete verified Candidate source closure",
                        ),
                    ),
                    output_commitment=candidate_ref.content_hash,
                    category="candidate_snapshot_recovery",
                    parent_repair_target=self._unique_build_target(definition),
                ) from exc
            try:
                bundle = await self.judge.evaluate(
                    candidate=candidate,
                    candidate_ref=candidate_ref,
                    source_dir=source_dir,
                    world_spec=world_spec,
                    world_spec_ref=world_spec_ref,
                    verifier=verifier,
                    verifier_ref=verifier_ref,
                    release_profile=self.release_profile,
                    budget=self._budget(definition),
                    reachability_workspace=(
                        self.workspace_root / f"{attempt.attempt_id}-reachability"
                    ),
                    run_id=f"{self.run_id}:release:{attempt.attempt_id}",
                )
            except Exception as exc:
                raise LeafExecutionFailure(
                    code="release_assurance_execution_error",
                    category=type(exc).__name__,
                ) from exc
            return self._judge_proposal(bundle, definition=definition)

        await self.kernel.execute(context, definition=definition, proposal_runner=proposal)

    def _verifier_from_context(
        self,
        context: WorkExecutionContext,
    ) -> tuple[ArtifactRef, VerifierIR]:
        refs = tuple(
            ref
            for ref in context.parent_output_refs
            if ref.artifact_type == "judge.verifier_ir_projection"
        )
        if len(refs) != 1:
            raise LeafExecutionFailure(
                code="preflight_release_verifier_missing",
                category="missing exact framework Verifier IR",
            )
        return refs[0], self.judge.artifacts.get_json(refs[0], VerifierIR)

    def _integration_from_context(
        self,
        context: WorkExecutionContext,
    ) -> tuple[ArtifactRef, IntegrationReport]:
        refs = tuple(
            ref
            for ref in context.parent_output_refs
            if ref.artifact_type == "judge.integration_report"
        )
        if len(refs) != 1:
            raise LeafExecutionFailure(
                code="preflight_release_integration_missing",
                category="missing exact Integration report",
            )
        return refs[0], self.judge.artifacts.get_json(refs[0], IntegrationReport)

    def _judge_proposal(
        self,
        bundle: JudgeBundle,
        *,
        definition: WorkDefinition,
    ) -> LeafProposal:
        report = bundle.report
        usage = report.budget_usage
        if report.verdict == "pass":
            return LeafProposal(
                output_refs=(bundle.report_ref,),
                subject_refs=(bundle.report_ref,),
                observed_actual=usage,
            )
        if report.verdict == "error":
            raise LeafExecutionFailure(
                code="release_judge_infrastructure_error",
                category="independent release infrastructure failed",
                observed_actual=usage,
            )
        raise LeafValidationFailure(
            issues=self._report_issues(report, stage="release"),
            output_commitment=bundle.report_ref.content_hash,
            category="independent_release_assurance_failed",
            observed_actual=usage,
            evidence_refs=(bundle.report_ref,),
            parent_repair_target=(
                self._unique_build_target(definition)
                if self._all_blocking_findings_owned_by(report, owner="build")
                else None
            ),
        )


__all__ = [
    "IntegrationLeaf",
    "ReleaseAssuranceLeaf",
    "VerifierAggregateLeaf",
    "VerifierBatchLeaf",
    "VerifierPlanLeaf",
]
