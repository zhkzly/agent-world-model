"""Scheduler-owned ResearchPlan leaf for the new Direct generation path.

The leaf owns one semantic proposal only.  It cannot search, retry, select a
repair target, or decide a gate.  Its output is a durable, typed
``ResearchPlan`` consumed by the next real-tools acquisition leaf.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from agent_world.artifact_store import ArtifactWriter
from agent_world.contracts import ArtifactRef, EnvironmentJob, EnvironmentRequest, GenerationContext
from agent_world.control.leaf_executor import (
    LeafExecutionFailure,
    LeafProposal,
    SchedulerLeafExecutor,
)
from agent_world.control.work import WorkAttempt, WorkDefinition
from agent_world.control.work_scheduler import WorkExecutionContext
from agent_world.invocation import InvocationBackend

from .models import ResearchPlan
from .one_shot import StructuredProfileProvider, invoke_structured_once
from .validators import validate_research_plan_coverage


@dataclass(frozen=True, slots=True)
class DirectGenerationInputs:
    """The exact generate-only root closure shared by research leaves."""

    context: GenerationContext
    job: EnvironmentJob
    request: EnvironmentRequest


def load_direct_generation_inputs(
    *,
    context_ref: ArtifactRef,
    execution_context: WorkExecutionContext,
    artifacts: ArtifactWriter,
) -> DirectGenerationInputs:
    """Load the typed root; never recover request/job from Controller state."""

    if context_ref.artifact_type != "control.generation_context":
        raise LeafExecutionFailure(
            code="preflight_generation_context_ref_type_invalid",
            category="Research root is not a GenerationContext Artifact",
        )
    if execution_context.external_input_refs != (context_ref,):
        raise LeafExecutionFailure(
            code="preflight_generation_context_root_mismatch",
            category="Research work must receive exactly its frozen GenerationContext root",
        )
    generation = artifacts.get_json(context_ref, GenerationContext)
    if generation.kind != "generate" or generation.request_ref is None:
        raise LeafExecutionFailure(
            code="preflight_research_context_kind_unsupported",
            category="Direct Research requires one generate GenerationContext",
        )
    job = artifacts.get_json(generation.job_ref, EnvironmentJob)
    request = artifacts.get_json(generation.request_ref, EnvironmentRequest)
    if job.kind != "generate" or job.request_ref != generation.request_ref:
        raise LeafExecutionFailure(
            code="preflight_generation_context_job_request_mismatch",
            category="GenerationContext does not bind one exact generate job and request",
        )
    if generation.permissions != job.permissions or generation.permissions != request.permissions:
        raise LeafExecutionFailure(
            code="preflight_generation_context_permission_mismatch",
            category="Research requires one exact context/job/request permission closure",
        )
    return DirectGenerationInputs(context=generation, job=job, request=request)


@dataclass(slots=True)
class ResearchPlanLeaf:
    """Compile a bounded search plan from one immutable GenerationContext."""

    context_ref: ArtifactRef
    workspace_root: Path
    backend: InvocationBackend
    profiles: StructuredProfileProvider
    kernel: SchedulerLeafExecutor

    async def execute(
        self,
        context: WorkExecutionContext,
        *,
        definition: WorkDefinition,
    ) -> None:
        async def proposal(
            _context: WorkExecutionContext,
            attempt: WorkAttempt,
            dispatch_id: str,
        ) -> LeafProposal:
            inputs = load_direct_generation_inputs(
                context_ref=self.context_ref,
                execution_context=context,
                artifacts=self.kernel.runtime.artifacts,
            )
            turn = await invoke_structured_once(
                backend=self.backend,
                profiles=self.profiles,
                definition=definition,
                attempt=attempt,
                dispatch_id=dispatch_id,
                ownership=self.kernel.invocation_ownership(
                    definition=definition,
                    attempt=attempt,
                    dispatch_id=dispatch_id,
                ),
                lineage_id=f"{inputs.job.job_id}.research-plan.{attempt.ordinal}",
                workspace=self.workspace_root / "research-plan" / attempt.attempt_id,
                model=ResearchPlan,
                prompt=_research_plan_prompt(inputs.request),
                permissions=inputs.context.permissions,
                semantic_validator=validate_research_plan_coverage,
                correction_brief=self.kernel.agent_correction_brief(
                    context,
                    definition=definition,
                ),
                semantic_repair_seed=self.kernel.agent_semantic_repair_seed(
                    context,
                    definition=definition,
                    attempt=attempt,
                ),
            )
            plan_ref = self.kernel.runtime.artifacts.put_json(
                artifact_id=f"{inputs.context.context_id}:research-plan",
                artifact_type="design.research_plan",
                value=turn.output,
                dependencies=(self.context_ref,),
            )
            return LeafProposal(
                output_refs=(plan_ref,),
                subject_refs=(plan_ref,),
                observed_actual=turn.observed_actual,
                unknown_upper_bound=turn.unknown_upper_bound,
                agent=turn.agent,
            )

        await self.kernel.execute(context, definition=definition, proposal_runner=proposal)

def _research_plan_prompt(request: EnvironmentRequest) -> str:
    """Prompt only a research plan; tools and factual claims stay out of this turn."""

    return f"""You are the isolated Researcher for an Agent World Foundry.
Project purpose: compile a short human need into a faithful executable programmatic environment.
Your role here is only to plan real searches. Do not answer from memory and do not design code.

Need:
{request.need}

Produce the requested ResearchPlan JSON. Cover workflow, systems of record, tool/API/SDK/CLI/MCP
surfaces, state transitions, errors, permissions, time, idempotency, concurrency, rollback, tasks,
and fidelity. `topics` are audit-only semantic labels, not provider category names. Put
authoritative URLs already known to you in `known_source_urls`; framework code will validate and
fetch them under the same tool budget. Queries will be executed by framework-owned real providers;
unsupported facts must remain unknown.
"""


__all__ = ["DirectGenerationInputs", "ResearchPlanLeaf", "load_direct_generation_inputs"]
