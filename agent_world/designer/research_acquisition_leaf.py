"""One-attempt real search/fetch/extract leaf for the Direct Scheduler graph."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from agent_world.artifact_store import ArtifactWriter
from agent_world.contracts import ArtifactRef, BudgetUsage, canonical_json_bytes, sha256_digest
from agent_world.control.leaf_executor import (
    LeafExecutionFailure,
    LeafProposal,
    LeafValidationFailure,
    SchedulerLeafExecutor,
)
from agent_world.control.work import ValidationIssue, WorkAttempt, WorkDefinition
from agent_world.control.work_scheduler import WorkExecutionContext
from agent_world.research import (
    ResearchEvidenceUnavailable,
    ResearchPermissionError,
    ResearchToolchain,
    SearchQuery,
    build_evidence_passage_pack,
)
from agent_world.research.security import ResearchSafetyError

from .models import ResearchAcquisition, ResearchPlan
from .research_leaf import load_direct_generation_inputs
from .research_materialization import materialize_research_evidence


@dataclass(slots=True)
class ResearchAcquisitionLeaf:
    """Spend one Scheduler-authorized real research operation, never a retry loop."""

    context_ref: ArtifactRef
    research: ResearchToolchain
    research_artifacts: ArtifactWriter
    workspace_root: Path
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
            _dispatch_id: str,
        ) -> LeafProposal:
            inputs = load_direct_generation_inputs(
                context_ref=self.context_ref,
                execution_context=context,
                artifacts=self.kernel.runtime.artifacts,
            )
            plan_ref = _one_parent(context, "design.research_plan")
            plan = self.kernel.runtime.artifacts.get_json(plan_ref, ResearchPlan)
            policy = definition.proposal_policy.budget
            queries = tuple(
                SearchQuery(text=item.text, language=item.language)
                for item in plan.queries[: policy.search_calls]
            )
            if not queries:
                raise LeafValidationFailure(
                    issues=(
                        ValidationIssue(
                            code="research_plan_queries_missing",
                            path=("queries",),
                            violated_condition=(
                                "Research acquisition requires one bounded planned query."
                            ),
                            expected_category="at least one planned query",
                            retryable=False,
                        ),
                    ),
                    output_commitment=_failure_commitment(
                        definition=definition,
                        plan_ref=plan_ref,
                        code="research_plan_queries_missing",
                    ),
                    category="research_plan_input",
                )
            try:
                bundle = await self.research.run(
                    queries,
                    request_permissions=inputs.request.permissions,
                    run_permissions=inputs.job.permissions,
                    allowed_source_kinds=inputs.request.allowed_source_kinds,
                    maximum_tool_calls=policy.tool_calls,
                    results_per_query=max(1, min(10, policy.tool_calls - len(queries))),
                    max_documents=max(1, min(24, policy.tool_calls - len(queries))),
                    seed_urls=plan.known_source_urls,
                    require_evidence=True,
                )
            except ResearchPermissionError as exc:
                # Permission is an explicit human/policy boundary, never a
                # blind infrastructure retry.  The current kernel records it
                # as a non-actionable terminal validation until the dedicated
                # needs-human disposition is wired into WorkControlRuntime.
                raise LeafValidationFailure(
                    issues=(
                        ValidationIssue(
                            code="research_permission_denied",
                            path=("permissions",),
                            violated_condition="the request and run must authorize research tools",
                            expected_category="an explicit permission grant",
                            retryable=False,
                        ),
                    ),
                    output_commitment=_failure_commitment(
                        definition=definition,
                        plan_ref=plan_ref,
                        code="research_permission_denied",
                    ),
                    category="research_permission_boundary",
                ) from exc
            except ResearchEvidenceUnavailable as exc:
                usage = BudgetUsage(
                    search_calls=exc.search_calls,
                    tool_calls=exc.search_calls + exc.fetch_calls + exc.extract_calls,
                )
                if exc.reason == "upstream_unavailable":
                    raise LeafExecutionFailure(
                        code=exc.failure_code,
                        category=(
                            "the configured research provider could not produce one "
                            "admissible search response"
                        ),
                        observed_actual=usage,
                        unknown_upper_bound=_remaining_tool_usage(definition, usage),
                        # Repeating an unavailable provider with the same
                        # full query envelope is not a causal repair.  A
                        # process interruption remains queryable through the
                        # dedicated replay-recovery path.
                        retryable=False,
                    ) from exc
                raise LeafValidationFailure(
                    issues=(
                        ValidationIssue(
                            code=exc.failure_code,
                            path=("evidence",),
                            violated_condition=(
                                "the bounded real research operation must admit at least one "
                                "fetched and extracted source body"
                            ),
                            expected_category="admissible fetched evidence",
                            retryable=False,
                        ),
                    ),
                    output_commitment=_failure_commitment(
                        definition=definition,
                        plan_ref=plan_ref,
                        code=exc.failure_code,
                    ),
                    category="research_evidence_unavailable",
                    observed_actual=usage,
                ) from exc
            except Exception as exc:
                raise LeafExecutionFailure(
                    code="research_toolchain_interrupted",
                    category="the real research toolchain interrupted before a bounded result",
                    unknown_upper_bound=_reserved_tool_usage(definition),
                ) from exc

            usage = BudgetUsage(
                search_calls=bundle.search_calls,
                tool_calls=bundle.search_calls + bundle.fetch_calls + bundle.extract_calls,
            )
            try:
                evidence, source_refs = materialize_research_evidence(
                    job_id=inputs.job.job_id,
                    bundle=bundle,
                    artifacts=self.research_artifacts,
                )
                passage_pack = build_evidence_passage_pack(
                    pack_id=_stable_id("evidence-passage-pack", inputs.request.request_id),
                    need=inputs.request.need,
                    query_texts=tuple(
                        value
                        for item in plan.queries
                        for value in (item.text, item.rationale)
                    )
                    + plan.target_coverage_dimensions,
                    evidence=evidence,
                    bundle=bundle,
                )
            except (ResearchSafetyError, ValueError) as exc:
                raise LeafValidationFailure(
                    issues=(
                        ValidationIssue(
                            code="research_evidence_materialization_invalid",
                            path=("evidence",),
                            violated_condition=(
                                "fetched source bodies must satisfy safety, integrity, and "
                                "passage-coverage contracts"
                            ),
                            expected_category="safe materialized evidence and passage pack",
                            retryable=False,
                        ),
                    ),
                    output_commitment=_failure_commitment(
                        definition=definition,
                        plan_ref=plan_ref,
                        code="research_evidence_materialization_invalid",
                    ),
                    category="research_evidence_materialization",
                    observed_actual=usage,
                ) from exc
            passage_pack_ref = self.kernel.runtime.artifacts.put_json(
                artifact_id=f"{inputs.context.context_id}:evidence-passage-pack",
                artifact_type="design.evidence_passage_pack",
                value=passage_pack,
                dependencies=(self.context_ref, plan_ref, *source_refs),
            )
            request_ref = inputs.context.request_ref
            if request_ref is None:  # pragma: no cover - loader proves this invariant
                raise LeafExecutionFailure(
                    code="preflight_generation_context_request_missing",
                    category="Research acquisition lacks one exact request Artifact",
                )
            record = ResearchAcquisition(
                acquisition_id=_stable_id(
                    "research-acquisition", plan_ref.revision_id, passage_pack_ref.revision_id
                ),
                plan_ref=plan_ref,
                request_ref=request_ref,
                evidence=evidence,
                source_refs=source_refs,
                passage_pack_ref=passage_pack_ref,
                usage=usage,
            )
            record_ref = self.kernel.runtime.artifacts.put_json(
                artifact_id=f"{inputs.context.context_id}:research-acquisition",
                artifact_type="design.research_acquisition",
                value=record,
                dependencies=(self.context_ref, plan_ref, passage_pack_ref, *source_refs),
            )
            closure = (record_ref, passage_pack_ref, *source_refs)
            return LeafProposal(
                output_refs=closure,
                subject_refs=closure,
                observed_actual=usage,
            )

        await self.kernel.execute(context, definition=definition, proposal_runner=proposal)


def _one_parent(context: WorkExecutionContext, artifact_type: str) -> ArtifactRef:
    matches = tuple(ref for ref in context.parent_output_refs if ref.artifact_type == artifact_type)
    if len(matches) != 1:
        raise LeafExecutionFailure(
            code="preflight_research_acquisition_plan_missing",
            category="Research acquisition lacks one committed ResearchPlan output",
        )
    return matches[0]


def _failure_commitment(*, definition: WorkDefinition, plan_ref: ArtifactRef, code: str) -> str:
    return sha256_digest(
        canonical_json_bytes(
            {
                "definition_digest": definition.definition_digest,
                "plan_revision": plan_ref.revision_id,
                "failure_code": code,
            }
        )
    )


def _reserved_tool_usage(definition: WorkDefinition) -> BudgetUsage:
    budget = definition.proposal_policy.budget
    return BudgetUsage(search_calls=budget.search_calls, tool_calls=budget.tool_calls)


def _remaining_tool_usage(definition: WorkDefinition, usage: BudgetUsage) -> BudgetUsage:
    reserved = _reserved_tool_usage(definition)
    return BudgetUsage(
        search_calls=max(0, reserved.search_calls - usage.search_calls),
        tool_calls=max(0, reserved.tool_calls - usage.tool_calls),
    )


def _stable_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256("\0".join(parts).encode("utf-8")).hexdigest()[:24]
    return f"{prefix}:{digest}"


__all__ = ["ResearchAcquisitionLeaf"]
