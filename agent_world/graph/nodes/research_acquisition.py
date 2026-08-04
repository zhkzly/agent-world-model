"""The research_acquisition node: one real search/fetch/extract operation.

Lifted from ``ResearchAcquisitionLeaf`` (see
``agent_world/designer/research_acquisition_leaf.py``): all the manual
head/lock/OperationRun choreography (``runtime.heads.exclusive``,
``begin``/``supersede_stale``/``schedule_operation``/``start_operation``/
``checkpoint_proposal``/``checkpoint_validation``/``evaluate``) is old-plane
machinery the executor/router now own, so only the real ``ResearchToolchain.run``
call and its exception-to-lane mapping survive here.

This stage is deliberately its own node, not folded into ``research_plan`` or
``evidence_synthesis``: it has no Agent semantic output to correct, so it never
produces a ``design_defect`` finding (see the node-consolidation permission's
own-boundary exception). Its only two outcomes are infra-retryable or an honest
stop, which is the exact three-lane classification the old leaf already used
and the classification this node must not regress:

- ``ResearchPermissionError`` is a policy boundary, never a transport hiccup:
  ``framework_diagnosis``, not retryable.
- ``ResearchEvidenceUnavailable`` is retryable *only* when
  ``reason == "upstream_unavailable"`` (the provider itself failed); every
  other reason (``true_empty``, ``degraded_empty``, ``fetch_attrition``,
  ``budget_exhausted``, ``mixed``) is an evidence-availability fact, not a
  fixable defect, so it is also ``framework_diagnosis``. This mirrors the
  bad-case lesson in ``tool-semantics-invalid-json-misclassification``: an
  infra/transport failure must never be misrouted as something a rerun can fix.
- Any other exception is an unclassified toolchain interruption:
  ``infra_retryable`` (matches the old leaf's ``research_toolchain_interrupted``,
  which was always retryable).
"""

from __future__ import annotations

from agent_world.contracts.base import ArtifactRef
from agent_world.designer.models import ResearchAcquisition, ResearchPlan
from agent_world.designer.research_materialization import materialize_research_evidence
from agent_world.artifact_store import ArtifactWriter
from agent_world.contracts import BudgetUsage, EnvironmentJob, EnvironmentRequest, GenerationContext
from agent_world.research import (
    ResearchEvidenceUnavailable,
    ResearchPermissionError,
    ResearchToolchain,
    SearchQuery,
    build_evidence_passage_pack,
)
from agent_world.research.security import ResearchSafetyError

from ..node import NodeContext, NodeResult
from ..state import Finding, RunState

NODE_ID = "research_acquisition"


def make_research_acquisition_node(
    *,
    research: ResearchToolchain,
    artifacts: ArtifactWriter,
    maximum_search_calls: int = 6,
    maximum_tool_calls: int = 24,
):
    """Bind the research_acquisition node body to the real research toolchain."""

    async def run(state: RunState, ctx: NodeContext) -> NodeResult:
        generation = artifacts.get_json(state.context_ref, GenerationContext)
        job = artifacts.get_json(generation.job_ref, EnvironmentJob)
        request = artifacts.get_json(generation.request_ref, EnvironmentRequest)

        plan_ref = ctx.inputs.get("research_plan")
        if not isinstance(plan_ref, ArtifactRef) or plan_ref.artifact_type != "design.research_plan":
            return NodeResult(
                status="honest_stop",
                failure_code="research_acquisition_plan_missing",
                failure_summary="research_acquisition requires one committed ResearchPlan output",
                findings=(
                    Finding(
                        finding_id=f"{NODE_ID}-plan-missing",
                        source_node=NODE_ID,
                        lane="framework_diagnosis",
                        code="research_acquisition_plan_missing",
                        summary="upstream research_plan output ref is missing or mistyped",
                    ),
                ),
            )
        plan = artifacts.get_json(plan_ref, ResearchPlan)
        queries = tuple(
            SearchQuery(text=item.text, language=item.language)
            for item in plan.queries[:maximum_search_calls]
        )

        try:
            bundle = await research.run(
                queries,
                request_permissions=request.permissions,
                run_permissions=job.permissions,
                allowed_source_kinds=request.allowed_source_kinds,
                maximum_tool_calls=maximum_tool_calls,
                results_per_query=max(1, min(10, maximum_tool_calls - len(queries))),
                max_documents=max(1, min(24, maximum_tool_calls - len(queries))),
                seed_urls=plan.known_source_urls,
                require_evidence=True,
            )
        except ResearchPermissionError as exc:
            return _honest_stop("research_permission_denied", str(exc))
        except ResearchEvidenceUnavailable as exc:
            if exc.reason == "upstream_unavailable":
                return NodeResult(
                    status="failed",
                    failure_code=exc.failure_code,
                    failure_summary=exc.summary,
                    findings=(
                        Finding(
                            finding_id=f"{NODE_ID}-upstream-unavailable",
                            source_node=NODE_ID,
                            lane="infra_retryable",
                            code=exc.failure_code,
                            summary=exc.summary,
                        ),
                    ),
                )
            return _honest_stop(exc.failure_code, exc.summary)
        except Exception as exc:  # noqa: BLE001 - single classification boundary for this node
            return NodeResult(
                status="failed",
                failure_code="research_toolchain_interrupted",
                failure_summary=str(exc)[:500],
                findings=(
                    Finding(
                        finding_id=f"{NODE_ID}-toolchain-interrupted",
                        source_node=NODE_ID,
                        lane="infra_retryable",
                        code="research_toolchain_interrupted",
                        summary="the real research toolchain interrupted before a bounded result",
                    ),
                ),
            )

        usage = BudgetUsage(
            search_calls=bundle.search_calls,
            tool_calls=bundle.search_calls + bundle.fetch_calls + bundle.extract_calls,
        )
        try:
            evidence, source_refs = materialize_research_evidence(
                job_id=job.job_id, bundle=bundle, artifacts=artifacts
            )
            passage_pack = build_evidence_passage_pack(
                pack_id=f"{generation.context_id}:evidence-passage-pack",
                need=request.need,
                query_texts=tuple(
                    value for item in plan.queries for value in (item.text, item.rationale)
                )
                + plan.target_coverage_dimensions,
                evidence=evidence,
                bundle=bundle,
            )
        except (ResearchSafetyError, ValueError) as exc:
            return _honest_stop("research_evidence_materialization_invalid", str(exc))

        passage_pack_ref = artifacts.put_json(
            artifact_id=f"{generation.context_id}:evidence-passage-pack",
            artifact_type="design.evidence_passage_pack",
            value=passage_pack,
            dependencies=(state.context_ref, plan_ref, *source_refs),
        )
        record = ResearchAcquisition(
            acquisition_id=f"{generation.context_id}:research-acquisition",
            plan_ref=plan_ref,
            request_ref=generation.request_ref,
            evidence=evidence,
            source_refs=source_refs,
            passage_pack_ref=passage_pack_ref,
            usage=usage,
        )
        record_ref = artifacts.put_json(
            artifact_id=f"{generation.context_id}:research-acquisition",
            artifact_type="design.research_acquisition",
            value=record,
            dependencies=(state.context_ref, plan_ref, passage_pack_ref, *source_refs),
        )
        return NodeResult(
            status="committed",
            outputs={"research_acquisition": record_ref},
            usage=usage,
        )

    return run


def _honest_stop(code: str, summary: str) -> NodeResult:
    return NodeResult(
        status="honest_stop",
        failure_code=code,
        failure_summary=summary[:500] or code,
        findings=(
            Finding(
                finding_id=f"{NODE_ID}-{code}",
                source_node=NODE_ID,
                lane="framework_diagnosis",
                code=code,
                summary=(summary[:500] or code),
            ),
        ),
    )


__all__ = ["NODE_ID", "make_research_acquisition_node"]
