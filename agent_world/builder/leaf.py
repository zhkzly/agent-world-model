"""Scheduler-owned one-attempt adapter for the real Environment Builder."""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from pathlib import Path

from agent_world.agent_profiles import logical_workspace_for_agent_workspace
from agent_world.artifact_store import ArtifactStoreError
from agent_world.contracts import (
    ArtifactRef,
    Budget,
    BudgetUsage,
    EnvironmentCandidate,
    EnvironmentDesign,
    GenerationContext,
    canonical_json_bytes,
    sha256_digest,
)
from agent_world.control.continuation_store import ContinuationStoreError, NodeContinuationRecord
from agent_world.control.leaf_executor import (
    AgentExecutionProvenance,
    LeafExecutionFailure,
    LeafProposal,
    LeafSemanticRepairContinuation,
    LeafSessionContinuation,
    LeafValidationFailure,
    LeafWorkspaceRecovery,
    SchedulerLeafExecutor,
)
from agent_world.control.validation import ValidationDiagnostic
from agent_world.control.work import (
    RepairAction,
    ValidationIssue,
    WorkAttempt,
    WorkDefinition,
    work_input_fingerprint,
)
from agent_world.control.work_scheduler import WorkExecutionContext
from agent_world.designer.one_shot import invoke_structured_once
from agent_world.invocation import InvocationError, NodeCapabilityRequirement
from agent_world.invocation.contracts import JsonObject
from agent_world.invocation.recovery import (
    InvocationFailureClass,
    InvocationRecoveryEvidence,
    InvocationRecoveryPolicy,
)
from agent_world.invocation.structured_diagnostics import (
    safe_terminal_code,
    safe_terminal_condition,
    safe_terminal_details,
    safe_terminal_expected_category,
    safe_terminal_remediation,
    terminal_failure_retryable,
)

from .models import CandidateCompletion, ImplementationPlan, ImplementationPlanDraft
from .service import (
    BuildBundle,
    BuilderError,
    BuilderSessionState,
    BuildInvocationSummary,
    EnvironmentBuilder,
)


@dataclass(frozen=True, slots=True)
class _SnapshotRepairSeed:
    """One verified committed Candidate closure for a fresh repair session."""

    candidate_ref: ArtifactRef
    candidate: EnvironmentCandidate
    correction_feedback: bytes


@dataclass(slots=True)
class BuildPlanningLeaf:
    """Make one read-only, durable implementation plan before CandidateBuild.

    The plan is deliberately prose-first and advisory.  It improves the next
    Engineer turn's orientation without creating partial source, changing the
    frozen semantic closure, or gaining release/repair authority.
    """

    builder: EnvironmentBuilder
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
            return await self._proposal(
                current_context,
                attempt,
                dispatch_id,
                definition=definition,
            )

        await self.kernel.execute(
            context,
            definition=definition,
            proposal_runner=proposal,
        )

    async def _proposal(
        self,
        context: WorkExecutionContext,
        attempt: WorkAttempt,
        dispatch_id: str,
        *,
        definition: WorkDefinition,
    ) -> LeafProposal:
        design_ref, design = _modeling_design_from_context(context, self.kernel)
        permissions = _generation_permissions(context, self.kernel)
        contract, contract_ref = self.builder.create_implementation_contract(
            design=design,
            design_ref=design_ref,
        )
        continuation = self._load_output_limited_continuation(
            context=context,
            attempt=attempt,
            definition=definition,
        )
        if continuation is None:
            workspace = self.workspace_root / attempt.attempt_id
            session = None
            lineage_id = self.builder._stable_id(  # noqa: SLF001 - one framework identity algorithm
                "implementation-plan-session",
                design_ref.revision_id,
                contract_ref.revision_id,
            )
            prompt = self._prompt(design_id=design.design_id)
        else:
            session = continuation.restore_session()
            # The private record stores the exact Agent workspace. Recover the
            # logical frozen-input root so profile resolution can reproduce
            # its primary or selected-fallback materialization layout.
            workspace = logical_workspace_for_agent_workspace(session.workspace)
            lineage_id = session.lineage_id
            prompt = self._continuation_prompt()
        self.builder.materialize_implementation_inputs(
            workspace=workspace,
            design=design,
            contract=contract,
        )
        candidate_root = workspace / "candidate"
        if candidate_root.exists() and any(candidate_root.iterdir()):
            raise LeafExecutionFailure(
                code="preflight_implementation_plan_workspace_not_empty",
                category="BuildImplementationPlan requires a fresh read-only workspace",
            )
        turn = await invoke_structured_once(
            backend=self.builder.backend,
            profiles=self.builder.profiles,
            definition=definition,
            attempt=attempt,
            dispatch_id=dispatch_id,
            ownership=self.kernel.invocation_ownership(
                definition=definition,
                attempt=attempt,
                dispatch_id=dispatch_id,
            ),
            lineage_id=lineage_id,
            workspace=workspace,
            model=ImplementationPlanDraft,
            prompt=prompt,
            permissions=permissions,
            capability_requirement=NodeCapabilityRequirement.structured_read(
                node_id="environment-engineer.implementation-plan",
                role="environment-engineer",
            ),
            correction_brief=self.kernel.agent_correction_brief(
                context,
                definition=definition,
            ),
            session=session,
        )
        if candidate_root.exists() and any(candidate_root.iterdir()):
            raise LeafExecutionFailure(
                code="implementation_plan_workspace_write_detected",
                category="read-only BuildImplementationPlan wrote candidate source",
                observed_actual=turn.observed_actual,
                unknown_upper_bound=turn.unknown_upper_bound,
                agent=turn.agent,
                retryable=False,
            )
        plan = ImplementationPlan(
            plan_id=self.builder._stable_id(  # noqa: SLF001 - one framework identity algorithm
                "implementation-plan",
                design_ref.revision_id,
                contract_ref.revision_id,
            ),
            design_ref=design_ref,
            implementation_contract_ref=contract_ref,
            world_spec_hash=design.world_spec.content_digest(),
            curriculum_hash=design.curriculum.content_digest(),
            implementation_strategy=turn.output.implementation_strategy,
        )
        plan_ref = self.builder.artifacts.put_json(
            artifact_id=f"{design.design_id}:implementation-plan",
            artifact_type="build.implementation_plan",
            value=plan,
            dependencies=(design_ref, contract_ref),
        )
        return LeafProposal(
            output_refs=(contract_ref, plan_ref),
            subject_refs=(contract_ref, plan_ref),
            observed_actual=turn.observed_actual,
            unknown_upper_bound=turn.unknown_upper_bound,
            agent=turn.agent,
        )

    def _load_output_limited_continuation(
        self,
        *,
        context: WorkExecutionContext,
        attempt: WorkAttempt,
        definition: WorkDefinition,
    ) -> NodeContinuationRecord | None:
        """Load only the private plan session authorized for this successor.

        A plan has no candidate workspace patch to preserve, but the same
        thread may already have read and reconciled the immutable inputs.  The
        private record is therefore valid only for the exact output-ceiling
        continuation action; semantic corrections remain ordinary fresh
        replacements with their own feedback route.
        """

        repair_action_ref = context.repair_action_ref
        if repair_action_ref is None:
            return None
        action = self.kernel.runtime.artifacts.get_json(repair_action_ref, RepairAction)
        if action.decision != "session_continuation":
            return None
        if (
            attempt.continuation_commitment is None
            or attempt.parent_attempt_id is None
            or self.kernel.runtime.continuations is None
            or self.kernel.runtime.continuation_workspace_root is None
        ):
            raise self._continuation_preflight_failure(
                "preflight_implementation_plan_continuation_state_missing"
            )
        try:
            record = self.kernel.runtime.continuations.load_commitment(
                attempt.continuation_commitment,
                workspace_root=self.kernel.runtime.continuation_workspace_root,
            )
        except ContinuationStoreError as exc:
            raise self._continuation_preflight_failure(
                "preflight_implementation_plan_continuation_state_invalid"
            ) from exc
        if record is None:
            raise self._continuation_preflight_failure(
                "preflight_implementation_plan_continuation_state_missing"
            )

        input_fingerprint = work_input_fingerprint(attempt.input_refs)
        expected_schema_digest = self._planning_schema_digest()
        if (
            record.work_id != definition.work_id
            or record.attempt_id != attempt.parent_attempt_id
            or record.definition_digest != definition.definition_digest
            or record.proposal_policy_digest != definition.proposal_policy.content_digest()
            or record.input_fingerprint != input_fingerprint
            or record.output_schema_digest != expected_schema_digest
            or record.previous_candidate is not None
            or record.candidate_commitment is not None
            or record.repair_action_ref != repair_action_ref
            or record.source_evaluation_ref != action.source_evaluation_ref
            or record.source_report_ref not in action.causal_evidence_refs
            or record.allowed_mutation_roots != action.allowed_mutation_roots
            or record.allowed_mutation_roots != definition.allowed_mutation_roots
            or action.definition_digest != definition.definition_digest
            or action.input_fingerprint != input_fingerprint
            or action.immutable_input_refs != attempt.input_refs
            or action.allowed_mutation_roots != definition.allowed_mutation_roots
        ):
            raise self._continuation_preflight_failure(
                "preflight_implementation_plan_continuation_binding_invalid"
            )
        return record

    @staticmethod
    def _continuation_preflight_failure(code: str) -> LeafExecutionFailure:
        return LeafExecutionFailure(
            code=code,
            category=(
                "BuildImplementationPlan output-limit continuation private state is unavailable "
                "or does not bind this authorized physical attempt"
            ),
            retryable=False,
        )

    @staticmethod
    def _planning_schema_digest() -> str:
        return sha256_digest(
            canonical_json_bytes(ImplementationPlanDraft.model_json_schema(mode="validation"))
        )

    @staticmethod
    def _prompt(*, design_id: str) -> str:
        return f"""You are BuildImplementationPlan for frozen design `{design_id}`.

Follow the mounted `engineer-build-planning` Skill. This is advisory preparation
for the later CandidateBuild turn only.

Return one complete `ImplementationPlanDraft` JSON for this design only."""

    @staticmethod
    def _continuation_prompt() -> str:
        return """Continue the same BuildImplementationPlan task in the same workspace.

Follow the mounted `engineer-build-planning` Skill and return the complete
requested `ImplementationPlanDraft` JSON only."""


@dataclass(slots=True)
class BuilderLeaf:
    """Run one real Builder turn under an already-open Scheduler attempt.

    The adapter deliberately owns no repair loop.  On an actionable candidate
    failure it returns one typed failure to ``SchedulerLeafExecutor``; a future
    Scheduler dispatch may open the separate repair WorkAttempt.  The successful
    ``BuildBundle`` remains only in this process' run registry; every downstream
    durable fact is in its immutable output Artifact closure.
    """

    builder: EnvironmentBuilder
    workspace_root: Path
    run_id: str
    kernel: SchedulerLeafExecutor
    bundle: BuildBundle | None = None

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
            return await self._proposal(
                current_context,
                attempt,
                dispatch_id,
                definition=definition,
            )

        await self.kernel.execute(
            context,
            definition=definition,
            proposal_runner=proposal,
        )

    async def _proposal(
        self,
        context: WorkExecutionContext,
        attempt: WorkAttempt,
        dispatch_id: str,
        *,
        definition: WorkDefinition,
    ) -> LeafProposal:
        design_ref, design = _modeling_design_from_context(context, self.kernel)
        implementation_plan_ref, implementation_plan = _implementation_plan_from_context(
            context,
            self.kernel,
            design_ref=design_ref,
            design=design,
        )
        permissions = _generation_permissions(context, self.kernel)
        session_token_limit = definition.proposal_policy.session_token_limit
        session_wall_seconds = definition.proposal_policy.session_wall_seconds
        continuation = self._load_session_continuation(
            context=context,
            attempt=attempt,
            definition=definition,
        )
        workspace_recovery = self._load_interrupted_workspace_recovery(
            context=context,
            attempt=attempt,
            definition=definition,
        )
        semantic_repair = self._load_semantic_repair_continuation(
            context=context,
            attempt=attempt,
            definition=definition,
        )
        snapshot_repair = self._load_snapshot_repair_seed(
            context=context,
            attempt=attempt,
            definition=definition,
        )
        invocation_ownership = self.kernel.invocation_ownership_if_dispatched(
            definition=definition,
            attempt=attempt,
            dispatch_id=dispatch_id,
        )

        async def fresh_build() -> BuildBundle:
            """Start one new Builder session for an initial or transport retry.

            A classified infrastructure retry and a model fallback preserve the
            immutable Work input closure, but deliberately do *not* preserve a
            failed provider session, workspace, or correction brief.  The
            Scheduler has already validated and charged their RepairAction;
            this leaf owns only the corresponding fresh physical turn.
            """

            return await self.builder.build_once(
                design=design,
                design_ref=design_ref,
                workspace=self.workspace_root / attempt.attempt_id,
                budget=self._budget(definition),
                permissions=permissions,
                parent_workspace_refs=(),
                run_id=self.run_id,
                attempt_id=attempt.attempt_id,
                proposal_invocation_id=dispatch_id,
                session_token_limit=session_token_limit,
                session_wall_seconds=session_wall_seconds,
                implementation_plan=implementation_plan,
                implementation_plan_ref=implementation_plan_ref,
                diagnostic_capture_terminal_excerpt=(
                    self.kernel.local_terminal_diagnostics_enabled
                ),
                invocation_ownership=invocation_ownership,
                model_override=attempt.model_override,
            )

        try:
            if snapshot_repair is not None:
                bundle = await self.builder.repair_from_snapshot(
                    design=design,
                    design_ref=design_ref,
                    candidate=snapshot_repair.candidate,
                    candidate_ref=snapshot_repair.candidate_ref,
                    workspace=self.workspace_root / attempt.attempt_id,
                    budget=self._budget(definition),
                    permissions=permissions,
                    run_id=self.run_id,
                    attempt_id=attempt.attempt_id,
                    attempt_ordinal=attempt.ordinal,
                    proposal_invocation_id=dispatch_id,
                    correction_feedback=snapshot_repair.correction_feedback,
                    session_token_limit=session_token_limit,
                    session_wall_seconds=session_wall_seconds,
                    implementation_plan=implementation_plan,
                    implementation_plan_ref=implementation_plan_ref,
                    diagnostic_capture_terminal_excerpt=(
                        self.kernel.local_terminal_diagnostics_enabled
                    ),
                    invocation_ownership=invocation_ownership,
                    model_override=attempt.model_override,
                )
            elif semantic_repair is not None:
                if session_token_limit is None or session_wall_seconds is None:
                    raise LeafExecutionFailure(
                        code="preflight_builder_repair_session_policy_missing",
                        category=(
                            "CandidateBuild semantic repair lacks a declared logical session "
                            "envelope"
                        ),
                    )
                repair_record, correction_feedback = semantic_repair
                resumed_session = repair_record.restore_session()
                bundle = await self.builder.resume_validation_repair(
                    design=design,
                    design_ref=design_ref,
                    workspace=resumed_session.workspace,
                    session=resumed_session,
                    budget=self._budget(definition),
                    permissions=permissions,
                    run_id=self.run_id,
                    attempt_id=attempt.attempt_id,
                    attempt_ordinal=attempt.ordinal,
                    proposal_invocation_id=dispatch_id,
                    session_token_limit=session_token_limit,
                    session_wall_seconds=session_wall_seconds,
                    correction_feedback=correction_feedback,
                    implementation_plan=implementation_plan,
                    implementation_plan_ref=implementation_plan_ref,
                    diagnostic_capture_terminal_excerpt=(
                        self.kernel.local_terminal_diagnostics_enabled
                    ),
                    invocation_ownership=invocation_ownership,
                    model_override=attempt.model_override,
                )
            elif workspace_recovery is not None:
                bundle = await self.builder.resume_interrupted_workspace_build(
                    design=design,
                    design_ref=design_ref,
                    # The old workspace is authorized only as an untrusted
                    # draft source.  The fresh Agent must receive a new
                    # child-local workspace; Builder copies the eligible
                    # candidate tree without exposing any host-path mapping to
                    # the Agent.
                    workspace=self.workspace_root / attempt.attempt_id,
                    recovery_workspace=workspace_recovery.workspace_for_recovery(),
                    budget=self._budget(definition),
                    permissions=permissions,
                    run_id=self.run_id,
                    attempt_id=attempt.attempt_id,
                    attempt_ordinal=attempt.ordinal,
                    proposal_invocation_id=dispatch_id,
                    recovery_lineage_id=workspace_recovery.lineage_id,
                    recovery_profile_digest=workspace_recovery.profile_digest,
                    recovery_codex_config_digest=workspace_recovery.codex_config_digest,
                    recovery_model=workspace_recovery.model,
                    session_token_limit=session_token_limit,
                    session_wall_seconds=session_wall_seconds,
                    implementation_plan=implementation_plan,
                    implementation_plan_ref=implementation_plan_ref,
                    diagnostic_capture_terminal_excerpt=(
                        self.kernel.local_terminal_diagnostics_enabled
                    ),
                    invocation_ownership=invocation_ownership,
                    model_override=attempt.model_override,
                )
            elif context.repair_action_ref is not None:
                action = self.kernel.runtime.artifacts.get_json(
                    context.repair_action_ref,
                    RepairAction,
                )
                if action.decision in {"infrastructure_retry", "model_fallback"}:
                    # These actions are authorization for one fresh node-local
                    # session.  They are neither semantic correction feedback
                    # nor a private output-limit continuation, so the model
                    # must receive no prior candidate/session state.
                    bundle = await fresh_build()
                elif action.decision == "local_correction":
                    raise self._semantic_repair_preflight_failure(
                        "preflight_builder_repair_seed_missing"
                    )
                elif action.decision != "session_continuation" or continuation is None:
                    raise LeafExecutionFailure(
                        code="preflight_builder_repair_action_unsupported",
                        category=(
                            "CandidateBuild received RepairAction that is not a supported "
                            "continuation or semantic correction"
                        ),
                        retryable=False,
                    )
                elif session_token_limit is None or session_wall_seconds is None:
                    raise LeafExecutionFailure(
                        code="preflight_builder_continuation_session_policy_missing",
                        category=(
                            "CandidateBuild continuation lacks a declared logical session envelope"
                        ),
                    )
                else:
                    resumed_session = continuation.restore_session()
                    bundle = await self.builder.resume_interrupted_session_build(
                        design=design,
                        design_ref=design_ref,
                        workspace=resumed_session.workspace,
                        session=resumed_session,
                        budget=self._budget(definition),
                        permissions=permissions,
                        run_id=self.run_id,
                        attempt_id=attempt.attempt_id,
                        attempt_ordinal=attempt.ordinal,
                        proposal_invocation_id=dispatch_id,
                        session_token_limit=session_token_limit,
                        session_wall_seconds=session_wall_seconds,
                        implementation_plan=implementation_plan,
                        implementation_plan_ref=implementation_plan_ref,
                        diagnostic_capture_terminal_excerpt=(
                            self.kernel.local_terminal_diagnostics_enabled
                        ),
                        invocation_ownership=invocation_ownership,
                        model_override=attempt.model_override,
                    )
            elif continuation is None:
                bundle = await fresh_build()
            else:
                if session_token_limit is None or session_wall_seconds is None:
                    raise LeafExecutionFailure(
                        code="preflight_builder_continuation_session_policy_missing",
                        category=(
                            "CandidateBuild continuation lacks a declared logical session envelope"
                        ),
                    )
                resumed_session = continuation.restore_session()
                bundle = await self.builder.resume_interrupted_session_build(
                    design=design,
                    design_ref=design_ref,
                    workspace=resumed_session.workspace,
                    session=resumed_session,
                    budget=self._budget(definition),
                    permissions=permissions,
                    run_id=self.run_id,
                    attempt_id=attempt.attempt_id,
                    attempt_ordinal=attempt.ordinal,
                    proposal_invocation_id=dispatch_id,
                    session_token_limit=session_token_limit,
                    session_wall_seconds=session_wall_seconds,
                    implementation_plan=implementation_plan,
                    implementation_plan_ref=implementation_plan_ref,
                    diagnostic_capture_terminal_excerpt=(
                        self.kernel.local_terminal_diagnostics_enabled
                    ),
                    invocation_ownership=invocation_ownership,
                    model_override=attempt.model_override,
                )
        except BuilderError as exc:
            preflight = exc.invocation is None
            backend_terminal = None if preflight else self._backend_terminal_error(exc)
            if backend_terminal is not None:
                self.kernel.record_local_terminal_diagnostic(
                    backend_terminal,
                    excerpt=exc.diagnostic_terminal_excerpt,
                )
            provenance = self._provenance(
                state=exc.state,
                invocation_id=(exc.invocation.invocation_id if exc.invocation else dispatch_id),
            )
            if preflight:
                provenance = None
            usage, unknown = self._usage(exc.invocation)
            diagnostic = self._candidate_output_diagnostic(
                exc,
                preflight=preflight,
                backend_terminal=backend_terminal,
            )
            if diagnostic is not None:
                raise self._validation_failure(
                    diagnostic=diagnostic,
                    definition=definition,
                    invocation_id=(exc.invocation.invocation_id if exc.invocation else dispatch_id),
                    observed_actual=usage,
                    unknown_upper_bound=unknown,
                    agent=provenance,
                    semantic_repair_continuation=(
                        self._semantic_repair_continuation_from_error(
                            state=exc.state,
                            provenance=provenance,
                            definition=definition,
                        )
                    ),
                ) from exc
            code = self._safe_code(
                (safe_terminal_code(backend_terminal) or exc.backend_error_code or exc.stage)
                if backend_terminal is not None
                else exc.backend_error_code or exc.stage
            )
            if preflight:
                code = f"preflight_builder_{code}"
            retryable = (
                terminal_failure_retryable(backend_terminal)
                if backend_terminal is not None
                else not (preflight or exc.stage == "framework.diagnostic")
            )
            terminal_details = (
                safe_terminal_details(backend_terminal) if backend_terminal is not None else {}
            )
            raise LeafExecutionFailure(
                code=code,
                category=(
                    safe_terminal_condition(backend_terminal)
                    if backend_terminal is not None
                    else self._failure_category(exc)
                ),
                observed_actual=usage,
                unknown_upper_bound=unknown,
                agent=provenance,
                retryable=retryable,
                expected_category=(
                    self._preflight_expected_category(exc.stage)
                    if preflight
                    else safe_terminal_expected_category(backend_terminal)
                    if backend_terminal is not None
                    else self._framework_diagnostic_expected_category(exc)
                    if exc.stage == "framework.diagnostic"
                    else None
                ),
                remediation=(
                    safe_terminal_remediation(backend_terminal)
                    if backend_terminal is not None
                    else None
                ),
                terminal_details=terminal_details,
                session_continuation=self._resumable_session_from_error(
                    code=code,
                    terminal_details=terminal_details,
                    retryable=retryable,
                    state=exc.state,
                    provenance=provenance,
                    definition=definition,
                ),
                workspace_recovery=self._workspace_recovery_from_error(
                    code=code,
                    terminal_details=terminal_details,
                    retryable=retryable,
                    state=exc.state,
                    provenance=provenance,
                    definition=definition,
                ),
            ) from exc

        if bundle.state is None:  # pragma: no cover - build_once always owns a live profile
            raise RuntimeError("successful Builder leaf omitted its real session state")
        self.bundle = bundle
        outputs = (
            bundle.source_snapshot_ref,
            bundle.implementation_lineage_ref,
            bundle.candidate_manifest_ref,
            bundle.build_artifact_ref,
            bundle.candidate_ref,
        )
        usage, unknown = self._usage(bundle.invocation)
        provenance = self._provenance(
            state=bundle.state,
            invocation_id=bundle.invocation.invocation_id,
        )
        if provenance is None:  # pragma: no cover - successful Builder has a profile
            raise RuntimeError("successful Builder leaf omitted real Agent provenance")
        return LeafProposal(
            output_refs=outputs,
            subject_refs=outputs,
            observed_actual=usage,
            unknown_upper_bound=unknown,
            agent=provenance,
        )

    def _load_session_continuation(
        self,
        *,
        context: WorkExecutionContext,
        attempt: WorkAttempt,
        definition: WorkDefinition,
    ) -> NodeContinuationRecord | None:
        """Load only the private session authorized for this exact successor.

        A semantic repair is deliberately not a transport continuation: it
        follows its own feedback route. This branch handles an output ceiling
        or a classified transient terminal only after the Scheduler checks
        every public/private binding before reopening the same SDK thread.
        """

        repair_action_ref = context.repair_action_ref
        if repair_action_ref is None:
            return None
        action = self.kernel.runtime.artifacts.get_json(repair_action_ref, RepairAction)
        if action.decision != "session_continuation":
            return None
        if (
            attempt.continuation_commitment is None
            or attempt.parent_attempt_id is None
            or self.kernel.runtime.continuations is None
            or self.kernel.runtime.continuation_workspace_root is None
        ):
            raise self._continuation_preflight_failure(
                "preflight_builder_continuation_state_missing"
            )
        try:
            record = self.kernel.runtime.continuations.load_commitment(
                attempt.continuation_commitment,
                workspace_root=self.kernel.runtime.continuation_workspace_root,
            )
        except ContinuationStoreError as exc:
            raise self._continuation_preflight_failure(
                "preflight_builder_continuation_state_invalid"
            ) from exc
        if record is None:
            raise self._continuation_preflight_failure(
                "preflight_builder_continuation_state_missing"
            )

        input_fingerprint = work_input_fingerprint(attempt.input_refs)
        expected_schema_digest = self._candidate_schema_digest()
        if (
            record.work_id != definition.work_id
            or record.attempt_id != attempt.parent_attempt_id
            or record.definition_digest != definition.definition_digest
            or record.proposal_policy_digest != definition.proposal_policy.content_digest()
            or record.input_fingerprint != input_fingerprint
            or record.output_schema_digest != expected_schema_digest
            or record.repair_action_ref != repair_action_ref
            or record.source_evaluation_ref != action.source_evaluation_ref
            or record.source_report_ref not in action.causal_evidence_refs
            or record.allowed_mutation_roots != action.allowed_mutation_roots
            or record.allowed_mutation_roots != definition.allowed_mutation_roots
            or action.definition_digest != definition.definition_digest
            or action.input_fingerprint != input_fingerprint
            or action.immutable_input_refs != attempt.input_refs
            or action.allowed_mutation_roots != definition.allowed_mutation_roots
        ):
            raise self._continuation_preflight_failure(
                "preflight_builder_continuation_binding_invalid"
            )
        return record

    def _load_interrupted_workspace_recovery(
        self,
        *,
        context: WorkExecutionContext,
        attempt: WorkAttempt,
        definition: WorkDefinition,
    ) -> NodeContinuationRecord | None:
        """Load one fresh-session Builder draft recovery, never a Provider thread.

        The public successor holds only a private-record commitment.  This
        loader proves that the record is for the exact immediately preceding
        attempt and the exact `infrastructure_retry` action; it does not scan
        history or accept a bare workspace path.
        """

        repair_action_ref = context.repair_action_ref
        if repair_action_ref is None:
            return None
        action = self.kernel.runtime.artifacts.get_json(repair_action_ref, RepairAction)
        if action.decision != "infrastructure_retry" or not action.workspace_recovery:
            return None
        if (
            attempt.continuation_commitment is None
            or attempt.parent_attempt_id is None
            or self.kernel.runtime.continuations is None
            or self.kernel.runtime.continuation_workspace_root is None
        ):
            raise self._workspace_recovery_preflight_failure(
                "preflight_builder_workspace_recovery_state_missing"
            )
        try:
            record = self.kernel.runtime.continuations.load_commitment(
                attempt.continuation_commitment,
                workspace_root=self.kernel.runtime.continuation_workspace_root,
            )
        except ContinuationStoreError as exc:
            raise self._workspace_recovery_preflight_failure(
                "preflight_builder_workspace_recovery_state_invalid"
            ) from exc
        if record is None:
            raise self._workspace_recovery_preflight_failure(
                "preflight_builder_workspace_recovery_state_missing"
            )

        input_fingerprint = work_input_fingerprint(attempt.input_refs)
        expected_schema_digest = self._candidate_schema_digest()
        if (
            record.continuation_kind != "workspace_recovery"
            or record.thread_id is not None
            or record.work_id != definition.work_id
            or record.attempt_id != attempt.parent_attempt_id
            or record.definition_digest != definition.definition_digest
            or record.proposal_policy_digest != definition.proposal_policy.content_digest()
            or record.input_fingerprint != input_fingerprint
            or record.output_schema_digest != expected_schema_digest
            or record.repair_action_ref != repair_action_ref
            or record.source_evaluation_ref != action.source_evaluation_ref
            or record.source_report_ref not in action.causal_evidence_refs
            or record.allowed_mutation_roots != action.allowed_mutation_roots
            or record.allowed_mutation_roots != definition.allowed_mutation_roots
            or action.definition_digest != definition.definition_digest
            or action.input_fingerprint != input_fingerprint
            or action.immutable_input_refs != attempt.input_refs
            or action.allowed_mutation_roots != definition.allowed_mutation_roots
            or action.route_model != record.model
        ):
            raise self._workspace_recovery_preflight_failure(
                "preflight_builder_workspace_recovery_binding_invalid"
            )
        try:
            record.workspace_for_recovery()
        except ContinuationStoreError as exc:
            raise self._workspace_recovery_preflight_failure(
                "preflight_builder_workspace_recovery_binding_invalid"
            ) from exc
        return record

    def _load_semantic_repair_continuation(
        self,
        *,
        context: WorkExecutionContext,
        attempt: WorkAttempt,
        definition: WorkDefinition,
    ) -> tuple[NodeContinuationRecord, bytes] | None:
        """Load one local-correction session plus its safe Scheduler brief.

        The repair action is authority for a second physical attempt, not
        runtime-Agent input.  This adapter verifies that authority, restores
        only the bound private workspace/session, and converts the associated
        ValidationReport into the data-only correction feedback consumed by
        :meth:`EnvironmentBuilder.resume_validation_repair`.
        """

        repair_action_ref = context.repair_action_ref
        if repair_action_ref is None:
            return None
        action = self.kernel.runtime.artifacts.get_json(repair_action_ref, RepairAction)
        if action.decision != "local_correction":
            return None
        # A completed Candidate may be repaired from its immutable output
        # snapshot in a fresh node-local session.  Absence of a private
        # continuation is therefore not itself a failure; the seed resolver
        # below decides whether a durable snapshot is available.  If a
        # commitment *is* present, however, it remains strict evidence and
        # must never be silently ignored when corrupt or misbound.
        if attempt.continuation_commitment is None:
            return None
        if (
            attempt.parent_attempt_id is None
            or self.kernel.runtime.continuations is None
            or self.kernel.runtime.continuation_workspace_root is None
        ):
            raise self._semantic_repair_preflight_failure("preflight_builder_repair_state_invalid")
        try:
            record = self.kernel.runtime.continuations.load_commitment(
                attempt.continuation_commitment,
                workspace_root=self.kernel.runtime.continuation_workspace_root,
            )
        except ContinuationStoreError as exc:
            raise self._semantic_repair_preflight_failure(
                "preflight_builder_repair_state_invalid"
            ) from exc
        if record is None:
            raise self._semantic_repair_preflight_failure("preflight_builder_repair_state_missing")

        input_fingerprint = work_input_fingerprint(attempt.input_refs)
        expected_schema_digest = self._candidate_schema_digest()
        if (
            record.work_id != definition.work_id
            or record.attempt_id != attempt.parent_attempt_id
            or record.definition_digest != definition.definition_digest
            or record.proposal_policy_digest != definition.proposal_policy.content_digest()
            or record.input_fingerprint != input_fingerprint
            or record.output_schema_digest != expected_schema_digest
            or record.repair_action_ref != repair_action_ref
            or record.source_evaluation_ref != action.source_evaluation_ref
            or record.source_report_ref not in action.causal_evidence_refs
            or record.allowed_mutation_roots != action.allowed_mutation_roots
            or record.allowed_mutation_roots != definition.allowed_mutation_roots
            or action.definition_digest != definition.definition_digest
            or action.input_fingerprint != input_fingerprint
            or action.immutable_input_refs != attempt.input_refs
            or action.allowed_mutation_roots != definition.allowed_mutation_roots
        ):
            raise self._semantic_repair_preflight_failure(
                "preflight_builder_repair_binding_invalid"
            )
        brief = self.kernel.agent_correction_brief(context, definition=definition)
        if brief is None:
            raise self._semantic_repair_preflight_failure(
                "preflight_builder_repair_feedback_missing"
            )
        return record, canonical_json_bytes(brief.prompt_projection())

    def _load_snapshot_repair_seed(
        self,
        *,
        context: WorkExecutionContext,
        attempt: WorkAttempt,
        definition: WorkDefinition,
    ) -> _SnapshotRepairSeed | None:
        """Bind a fresh Builder repair to one committed Candidate source closure.

        The Scheduler action carries only immutable artifact references.  This
        leaf verifies the whole relationship before materializing anything:
        current successor -> authorized semantic correction -> exact output
        closure -> one Candidate.  A Provider retry may be the current physical
        action, but it must explicitly bind that original semantic correction;
        it may not erase its feedback and fall back to an unrelated fresh build.
        This path deliberately does not scan history, revive a provider thread,
        or choose a "latest" candidate.
        """

        physical_action_ref = context.repair_action_ref
        if physical_action_ref is None:
            return None
        physical_action = self.kernel.runtime.artifacts.get_json(
            physical_action_ref,
            RepairAction,
        )
        semantic_action_ref = context.semantic_repair_context_ref or physical_action_ref
        action = self.kernel.runtime.artifacts.get_json(semantic_action_ref, RepairAction)
        if action.decision != "local_correction" or action.repair_seed_attempt_ref is None:
            return None
        transport_recovery = semantic_action_ref != physical_action_ref
        if transport_recovery and (
            physical_action.decision not in {"infrastructure_retry", "model_fallback"}
            or physical_action.semantic_repair_context_ref != semantic_action_ref
            or physical_action.definition_digest != action.definition_digest
            or physical_action.target_coordinate != action.target_coordinate
            or physical_action.input_fingerprint != action.input_fingerprint
            or physical_action.immutable_input_refs != action.immutable_input_refs
            or physical_action.allowed_mutation_roots != action.allowed_mutation_roots
        ):
            raise self._semantic_repair_preflight_failure(
                "preflight_builder_repair_transport_context_invalid"
            )
        if attempt.parent_attempt_id is None:
            raise self._semantic_repair_preflight_failure(
                "preflight_builder_repair_seed_parent_missing"
            )
        input_fingerprint = work_input_fingerprint(attempt.input_refs)
        if (
            action.definition_digest != definition.definition_digest
            or action.input_fingerprint != input_fingerprint
            or action.immutable_input_refs != attempt.input_refs
            or action.allowed_mutation_roots != definition.allowed_mutation_roots
        ):
            raise self._semantic_repair_preflight_failure(
                "preflight_builder_repair_seed_binding_invalid"
            )
        try:
            seed_attempt = self.kernel.runtime.artifacts.get_json(
                action.repair_seed_attempt_ref,
                WorkAttempt,
            )
        except (ArtifactStoreError, ValueError, TypeError) as exc:
            raise self._semantic_repair_preflight_failure(
                "preflight_builder_repair_seed_invalid"
            ) from exc
        seed_policy_matches = (
            seed_attempt.attempt_id != attempt.parent_attempt_id
            or seed_attempt.work_id != definition.work_id
            or seed_attempt.coordinate != definition.coordinate
            or seed_attempt.status != "succeeded"
            or seed_attempt.definition_digest != definition.definition_digest
            or seed_attempt.proposal_policy_digest != definition.proposal_policy.content_digest()
            or seed_attempt.validation_policy_digest
            != definition.validation_policy.content_digest()
            or seed_attempt.repair_policy_digest != definition.repair_policy.content_digest()
            or seed_attempt.input_refs != attempt.input_refs
            or seed_attempt.output_refs != action.repair_seed_output_refs
        )
        if (
            seed_policy_matches
            and not transport_recovery
            and not self._is_refreshed_causal_snapshot_seed(
                action=action,
                seed_attempt=seed_attempt,
                definition=definition,
            )
        ):
            raise self._semantic_repair_preflight_failure(
                "preflight_builder_repair_seed_binding_invalid"
            )
        candidate_refs = tuple(
            ref
            for ref in action.repair_seed_output_refs
            if ref.artifact_type == "build.environment_candidate"
        )
        if len(candidate_refs) != 1:
            raise self._semantic_repair_preflight_failure(
                "preflight_builder_repair_seed_candidate_missing"
            )
        candidate_ref = candidate_refs[0]
        try:
            candidate = self.kernel.runtime.artifacts.get_json(candidate_ref, EnvironmentCandidate)
            self.kernel.runtime.artifacts.require_exact_json(
                candidate_ref,
                candidate,
                artifact_types=("build.environment_candidate",),
            )
        except (ArtifactStoreError, ValueError, TypeError) as exc:
            raise self._semantic_repair_preflight_failure(
                "preflight_builder_repair_seed_candidate_invalid"
            ) from exc
        brief = self.kernel.agent_correction_brief(context, definition=definition)
        if brief is None:
            raise self._semantic_repair_preflight_failure(
                "preflight_builder_repair_feedback_missing"
            )
        return _SnapshotRepairSeed(
            candidate_ref=candidate_ref,
            candidate=candidate,
            correction_feedback=canonical_json_bytes(brief.prompt_projection()),
        )

    def _is_refreshed_causal_snapshot_seed(
        self,
        *,
        action: RepairAction,
        seed_attempt: WorkAttempt,
        definition: WorkDefinition,
    ) -> bool:
        """Prove the one safe old-Candidate/new-authoring revision bridge.

        A Prompt or mounted Runtime Skill revision creates a new Candidate
        definition, so a committed snapshot from the immediately preceding
        correction has the old policy digests by construction. It may be
        restored only when that preceding attempt is itself bound to a causal
        local correction and the new action carries the *same* immutable
        downstream feedback route. This does not select history, resume a
        provider thread, or allow a generic old candidate to satisfy a new
        definition.
        """

        if seed_attempt.repair_action_ref is None:
            return False
        try:
            prior_action = self.kernel.runtime.artifacts.get_json(
                seed_attempt.repair_action_ref,
                RepairAction,
            )
        except (ArtifactStoreError, ValueError, TypeError):
            return False
        return (
            prior_action.decision == "local_correction"
            and prior_action.reason_code == "causal_downstream_failure"
            and prior_action.current_coordinate == definition.coordinate
            and prior_action.target_coordinate == definition.coordinate
            and prior_action.definition_digest != definition.definition_digest
            and prior_action.input_fingerprint == action.input_fingerprint
            and prior_action.immutable_input_refs == action.immutable_input_refs
            and prior_action.allowed_mutation_roots == action.allowed_mutation_roots
            and prior_action.causal_evidence_refs == action.causal_evidence_refs
        )

    @staticmethod
    def _continuation_preflight_failure(code: str) -> LeafExecutionFailure:
        return LeafExecutionFailure(
            code=code,
            category=(
                "CandidateBuild output-limit continuation private state is unavailable "
                "or does not bind this authorized physical attempt"
            ),
            retryable=False,
        )

    @staticmethod
    def _workspace_recovery_preflight_failure(code: str) -> LeafExecutionFailure:
        return LeafExecutionFailure(
            code=code,
            category=(
                "CandidateBuild private workspace recovery is unavailable or does not bind "
                "this authorized fresh-session infrastructure retry"
            ),
            retryable=False,
        )

    @staticmethod
    def _semantic_repair_preflight_failure(code: str) -> LeafExecutionFailure:
        return LeafExecutionFailure(
            code=code,
            category=(
                "CandidateBuild semantic repair lacks a verified private continuation, "
                "committed snapshot seed, or safe feedback for this authorized physical attempt"
            ),
            retryable=False,
        )

    def _semantic_repair_continuation_from_error(
        self,
        *,
        state: BuilderSessionState | None,
        provenance: AgentExecutionProvenance | None,
        definition: WorkDefinition,
    ) -> LeafSemanticRepairContinuation | None:
        """Expose same-session state only for a repairable completed proposal."""

        if (
            state is None
            or state.invocation_session is None
            or provenance is None
            or definition.repair_policy.maximum_local_corrections < 1
            or provenance.model != state.profile.model
            or provenance.output_schema_digest != self._candidate_schema_digest()
        ):
            return None
        return LeafSemanticRepairContinuation(
            session=state.invocation_session,
            model=provenance.model,
            output_schema_digest=provenance.output_schema_digest,
        )

    @staticmethod
    def _candidate_schema_digest() -> str:
        return sha256_digest(
            canonical_json_bytes(CandidateCompletion.model_json_schema(mode="validation"))
        )

    @staticmethod
    def _candidate_output_diagnostic(
        exc: BuilderError,
        *,
        preflight: bool,
        backend_terminal: InvocationError | None,
    ) -> ValidationDiagnostic | None:
        """Return a repairable Candidate-output frontier, never raw model text.

        A real Agent has already completed when its CandidateCompletion or
        workspace is rejected.  Reporting that as an execution error loses
        field paths and incorrectly routes it as infrastructure.  Only the
        specific, safe frontiers below become a semantic validation result;
        opaque framework failures remain non-actionable execution errors.
        """

        if preflight or backend_terminal is not None:
            return None
        source = exc
        if exc.stage == "framework.diagnostic" and isinstance(exc.__cause__, BuilderError):
            source = exc.__cause__
        if source.stage not in {"agent.output", "candidate.validation"}:
            return None
        diagnostic = EnvironmentBuilder._validation_diagnostic(exc)  # noqa: SLF001 - shared diagnostic contract
        return diagnostic if diagnostic.actionable_for_agent else None

    @staticmethod
    def _validation_failure(
        *,
        diagnostic: ValidationDiagnostic,
        definition: WorkDefinition,
        invocation_id: str,
        observed_actual: BudgetUsage,
        unknown_upper_bound: BudgetUsage,
        agent: AgentExecutionProvenance | None,
        semantic_repair_continuation: LeafSemanticRepairContinuation | None = None,
    ) -> LeafValidationFailure:
        """Project one safe Builder diagnostic into Scheduler repair feedback."""

        if agent is None:  # pragma: no cover - guarded by the real invocation path
            raise RuntimeError("Candidate output validation requires Agent provenance")
        issues = tuple(
            ValidationIssue(
                code=issue.code,
                path=issue.location,
                violated_condition=(
                    issue.violated_condition
                    or "the CandidateCompletion declaration violated this framework condition"
                ),
                expected_category=(
                    issue.expected_category
                    or "a CandidateCompletion declaration satisfying this field contract"
                ),
                remediation=issue.message,
                retryable=issue.retryable,
            )
            for issue in diagnostic.issues
        )
        output_commitment = sha256_digest(
            canonical_json_bytes(
                {
                    "invocation_id": invocation_id,
                    "definition_digest": definition.definition_digest,
                    "validation_diagnostic": diagnostic.persistence_projection(),
                }
            )
        )
        return LeafValidationFailure(
            issues=issues,
            output_commitment=output_commitment,
            category=diagnostic.validation_phase,
            observed_actual=observed_actual,
            unknown_upper_bound=unknown_upper_bound,
            agent=agent,
            semantic_repair_continuation=semantic_repair_continuation,
            # A completion failure means the built Candidate is not acceptable:
            # the Builder has no mutation root of its own, so the only repair
            # is a causal rework of the frozen EnvironmentDesign parent.
            parent_repair_target=self._unique_design_repair_target(definition),
        )

    @staticmethod
    def _unique_design_repair_target(definition: WorkDefinition):
        targets = tuple(
            coordinate
            for coordinate in definition.repair_target_coordinates
            if coordinate.component == "design"
        )
        if len(targets) != 1:
            raise LeafExecutionFailure(
                code="preflight_candidate_design_route_ambiguous",
                category="candidate build definition lacks one Design causal target",
            )
        return targets[0]

    @classmethod
    def _resumable_session_from_error(
        cls,
        *,
        code: str,
        terminal_details: JsonObject,
        retryable: bool,
        state: BuilderSessionState | None,
        provenance: AgentExecutionProvenance | None,
        definition: WorkDefinition,
    ) -> LeafSessionContinuation | None:
        """Expose a same-thread recovery only for a classified terminal."""

        failure_class = InvocationRecoveryPolicy.classify(
            InvocationRecoveryEvidence(
                terminal_code=code,
                retryable=retryable,
                terminal_details=terminal_details,
            )
        )

        if (
            failure_class
            not in {
                InvocationFailureClass.OUTPUT_CEILING,
                InvocationFailureClass.TRANSIENT_CAPACITY,
                InvocationFailureClass.TRANSIENT_TRANSPORT,
            }
            or state is None
            or state.invocation_session is None
            or provenance is None
            or definition.proposal_policy.session_token_limit is None
            or definition.proposal_policy.session_wall_seconds is None
            or definition.repair_policy.maximum_session_continuations < 1
            or provenance.model != state.profile.model
            or provenance.output_schema_digest != cls._candidate_schema_digest()
        ):
            return None
        return LeafSessionContinuation(
            session=state.invocation_session,
            model=provenance.model,
            output_schema_digest=provenance.output_schema_digest,
        )

    @classmethod
    def _workspace_recovery_from_error(
        cls,
        *,
        code: str,
        terminal_details: JsonObject,
        retryable: bool,
        state: BuilderSessionState | None,
        provenance: AgentExecutionProvenance | None,
        definition: WorkDefinition,
    ) -> LeafWorkspaceRecovery | None:
        """Offer one untrusted draft only after closed transient file activity.

        A `BuilderError` without a complete CandidateCompletion cannot itself
        become a candidate.  This merely records that a fresh same-model
        session may inspect the private draft under the existing retry action.
        Any semantic or filesystem acceptance still happens later in
        `EnvironmentBuilder._validate_and_commit`.
        """

        failure_class = InvocationRecoveryPolicy.classify(
            InvocationRecoveryEvidence(
                terminal_code=code,
                retryable=retryable,
                terminal_details=terminal_details,
            )
        )
        if (
            not retryable
            or failure_class
            not in {
                InvocationFailureClass.TRANSIENT_CAPACITY,
                InvocationFailureClass.TRANSIENT_TRANSPORT,
            }
            or state is None
            or provenance is None
            or definition.repair_policy.maximum_infrastructure_retries < 1
            or provenance.model != state.profile.model
            or provenance.profile_digest != f"sha256:{state.profile.profile_hash}"
            or provenance.output_schema_digest != cls._candidate_schema_digest()
            or not cls._has_regular_candidate_draft(state.workspace)
        ):
            return None
        return LeafWorkspaceRecovery(
            workspace=state.workspace.resolve(),
            lineage_id=state.lineage_id,
            profile_digest=provenance.profile_digest,
            codex_config_digest=f"sha256:{state.profile.codex_config_sha256}",
            model=provenance.model,
            output_schema_digest=provenance.output_schema_digest,
        )

    @staticmethod
    def _has_regular_candidate_draft(workspace: Path) -> bool:
        """Return whether the private candidate root has safe normal file activity.

        This is deliberately an eligibility observation, not a partial
        Candidate validator.  It rejects links and special files so the
        control plane never binds an unsafe draft; the complete final-tree
        validator still owns all acceptance decisions after the fresh Agent
        returns a CandidateCompletion.
        """

        try:
            root = workspace.resolve(strict=True)
            if workspace.is_symlink():
                return False
            candidate_root = root / "candidate"
            if candidate_root.is_symlink() or not candidate_root.is_dir():
                return False
            for _directory, directory_names, file_names, directory_fd in os.fwalk(
                candidate_root,
                topdown=True,
                follow_symlinks=False,
            ):
                for name in directory_names:
                    observed = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
                    if stat.S_ISLNK(observed.st_mode) or not stat.S_ISDIR(observed.st_mode):
                        return False
                for name in file_names:
                    observed = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
                    if (
                        stat.S_ISLNK(observed.st_mode)
                        or not stat.S_ISREG(observed.st_mode)
                        or observed.st_nlink != 1
                    ):
                        return False
                    if observed.st_size > 0:
                        return True
        except OSError:
            return False
        return False

    @staticmethod
    def _budget(definition: WorkDefinition) -> Budget:
        policy = definition.proposal_policy.budget
        return Budget(
            llm_tokens=policy.llm_tokens,
            agent_turns=policy.agent_turns,
            tool_calls=policy.tool_calls,
            process_calls=policy.process_calls,
            build_seconds=policy.build_seconds,
            container_seconds=policy.container_seconds,
            live_probe_cost=policy.live_probe_cost,
            wall_seconds=policy.wall_seconds,
            monetary_cost=policy.monetary_cost,
        )

    @staticmethod
    def _usage(
        summary: BuildInvocationSummary | None,
    ) -> tuple[BudgetUsage, BudgetUsage]:
        if summary is None:
            return BudgetUsage(), BudgetUsage()
        return (
            BudgetUsage(
                llm_tokens=summary.total_tokens,
                agent_turns=summary.turns,
                build_seconds=max(0.0, summary.duration_ms / 1_000),
                wall_seconds=max(0.0, summary.duration_ms / 1_000),
            ),
            BudgetUsage(llm_tokens=sum(summary.unknown_token_upper_bounds)),
        )

    @staticmethod
    def _provenance(
        *,
        state: BuilderSessionState | None,
        invocation_id: str,
    ) -> AgentExecutionProvenance | None:
        if state is None:
            return None
        profile = state.profile
        continuation = (
            sha256_digest(
                canonical_json_bytes(
                    {
                        "thread_id": state.invocation_session.thread_id,
                        "lineage_id": state.invocation_session.lineage_id,
                        "profile_hash": state.invocation_session.profile_hash,
                        "codex_config_sha256": state.invocation_session.codex_config_sha256,
                    }
                )
            )
            if state.invocation_session is not None
            else None
        )
        return AgentExecutionProvenance(
            invocation_id=invocation_id,
            provider=profile.model_provider or "openai",
            model=profile.model,
            profile_digest=f"sha256:{profile.profile_hash}",
            output_schema_digest=sha256_digest(
                canonical_json_bytes(CandidateCompletion.model_json_schema(mode="validation"))
            ),
            continuation_commitment=continuation,
        )

    @staticmethod
    def _safe_code(value: str) -> str:
        safe = "".join(
            character if character.isalnum() or character in "._:-" else "_" for character in value
        ).strip("._:-")
        return (safe or "builder_failed")[:120]

    @staticmethod
    def _backend_terminal_error(exc: BuilderError) -> InvocationError | None:
        if exc.backend_error_code is None:
            return None
        return InvocationError(
            code=exc.backend_error_code,
            message=exc.backend_error_code,
            retryable=exc.backend_retryable,
            details=exc.backend_error_details,
        )

    @staticmethod
    def _builder_error_detail(exc: BuilderError) -> str:
        """Normalize one Builder-owned message before it reaches feedback."""

        detail = str(exc)
        prefix = f"{exc.stage}: "
        return detail.removeprefix(prefix) if detail.startswith(prefix) else detail

    @classmethod
    def _failure_category(cls, exc: BuilderError) -> str:
        """Return bounded Builder-owned evidence, never a backend transcript."""

        category = f"BuilderError[{exc.stage}]: {cls._builder_error_detail(exc)}"
        # ``framework.diagnostic`` is a deliberate safety wrapper around an
        # earlier BuilderError.  Preserve that safe phase and message so an
        # observer can select the correct remediation lens without exposing a
        # raw Agent transcript or a chained provider exception.
        if exc.stage == "framework.diagnostic" and isinstance(exc.__cause__, BuilderError):
            cause = exc.__cause__
            category += f"; source[{cause.stage}]: {cls._builder_error_detail(cause)}"
        return category[:512]

    @staticmethod
    def _preflight_expected_category(stage: str) -> str | None:
        if stage == "budget":
            return "a positive Builder build_seconds and wall_seconds envelope"
        if stage == "permissions":
            return "a capability profile that authorizes the declared Builder operation"
        if stage == "workspace":
            return "one fresh empty Builder workspace for this attempt"
        if stage == "implementation_contract":
            return (
                "a current framework-owned ImplementationContract compiled by "
                "BuildImplementationPlan from the exact frozen EnvironmentDesign"
            )
        if stage == "profile_resolution":
            return (
                "one unchanged Engineer model, Runtime Skill set, output schema, "
                "physical turn envelope, and Agent workspace binding"
            )
        return "a corrected Builder preflight configuration outside this attempt"

    @classmethod
    def _framework_diagnostic_expected_category(cls, exc: BuilderError) -> str:
        if isinstance(exc.__cause__, BuilderError):
            return f"a typed remediation for Builder phase {exc.__cause__.stage}"
        return "a typed framework diagnostic before another Agent attempt"


def _modeling_design_from_context(
    context: WorkExecutionContext,
    kernel: SchedulerLeafExecutor,
) -> tuple[ArtifactRef, EnvironmentDesign]:
    """Bind Builder input to the Scheduler's committed Modeling closure only."""

    design_refs = tuple(
        ref
        for ref in context.parent_output_refs
        if ref.artifact_type in {"design.environment_design", "expansion.environment_design"}
    )
    if len(design_refs) != 1:
        raise LeafExecutionFailure(
            code="preflight_builder_design_missing",
            category="Builder requires one exact committed EnvironmentDesign",
        )
    design_ref = design_refs[0]
    return design_ref, kernel.runtime.artifacts.get_json(design_ref, EnvironmentDesign)


def _implementation_plan_from_context(
    context: WorkExecutionContext,
    kernel: SchedulerLeafExecutor,
    *,
    design_ref: ArtifactRef,
    design: EnvironmentDesign,
) -> tuple[ArtifactRef, ImplementationPlan]:
    """Bind CandidateBuild to one already-committed advisory planning closure."""

    plan_refs = tuple(
        ref
        for ref in context.parent_output_refs
        if ref.artifact_type == "build.implementation_plan"
    )
    contract_refs = tuple(
        ref
        for ref in context.parent_output_refs
        if ref.artifact_type == "build.implementation_contract"
    )
    if len(plan_refs) != 1 or len(contract_refs) != 1:
        raise LeafExecutionFailure(
            code="preflight_builder_implementation_plan_missing",
            category=(
                "CandidateBuild requires one exact committed ImplementationPlan and "
                "ImplementationContract"
            ),
        )
    plan_ref = plan_refs[0]
    plan = kernel.runtime.artifacts.get_json(plan_ref, ImplementationPlan)
    kernel.runtime.artifacts.require_exact_json(
        plan_ref,
        plan,
        artifact_types=("build.implementation_plan",),
    )
    contract_ref = contract_refs[0]
    if (
        plan.design_ref != design_ref
        or plan.implementation_contract_ref != contract_ref
        or plan.world_spec_hash != design.world_spec.content_digest()
        or plan.curriculum_hash != design.curriculum.content_digest()
    ):
        raise LeafExecutionFailure(
            code="preflight_builder_implementation_plan_binding_invalid",
            category=(
                "ImplementationPlan does not bind CandidateBuild's exact frozen Design closure"
            ),
        )
    return plan_ref, plan


def _generation_permissions(
    context: WorkExecutionContext,
    kernel: SchedulerLeafExecutor,
):
    contexts = tuple(
        ref
        for ref in context.external_input_refs
        if ref.artifact_type == "control.generation_context"
    )
    if len(contexts) != 1:
        raise LeafExecutionFailure(
            code="preflight_builder_generation_context_missing",
            category="Builder requires one immutable GenerationContext root",
        )
    generation = kernel.runtime.artifacts.get_json(contexts[0], GenerationContext)
    return generation.permissions
