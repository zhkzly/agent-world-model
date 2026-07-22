"""Scheduler-owned one-attempt adapter for the real Environment Builder."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from agent_world.contracts import (
    ArtifactRef,
    Budget,
    BudgetUsage,
    EnvironmentDesign,
    GenerationContext,
    canonical_json_bytes,
    sha256_digest,
)
from agent_world.control.leaf_executor import (
    AgentExecutionProvenance,
    LeafExecutionFailure,
    LeafProposal,
    SchedulerLeafExecutor,
)
from agent_world.control.work import WorkAttempt, WorkDefinition
from agent_world.control.work_scheduler import WorkExecutionContext

from .models import CandidateCompletion
from .service import (
    BuildBundle,
    BuilderError,
    BuilderSessionState,
    BuildInvocationSummary,
    EnvironmentBuilder,
)


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
        permissions = _generation_permissions(context, self.kernel)
        try:
            bundle = await self.builder.build_once(
                design=design,
                design_ref=design_ref,
                workspace=self.workspace_root / attempt.attempt_id,
                budget=self._budget(definition),
                permissions=permissions,
                parent_workspace_refs=(),
                run_id=self.run_id,
                attempt_id=attempt.attempt_id,
                proposal_invocation_id=dispatch_id,
            )
        except BuilderError as exc:
            provenance = self._provenance(
                state=exc.state,
                invocation_id=(exc.invocation.invocation_id if exc.invocation else dispatch_id),
            )
            usage, unknown = self._usage(exc.invocation)
            code = self._safe_code(exc.backend_error_code or exc.stage)
            if provenance is None:
                code = f"preflight_builder_{code}"
            raise LeafExecutionFailure(
                code=code,
                category="BuilderError",
                observed_actual=usage,
                unknown_upper_bound=unknown,
                agent=provenance,
            ) from exc

        if bundle.state is None:  # pragma: no cover - build_once always owns a live profile
            raise RuntimeError("successful Builder leaf omitted its real session state")
        self.bundle = bundle
        outputs = (
            bundle.implementation_contract_ref,
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
            character if character.isalnum() or character in "._:-" else "_"
            for character in value
        ).strip("._:-")
        return (safe or "builder_failed")[:120]


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
