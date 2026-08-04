"""Shared scaffolding for the "one bounded structured Agent turn" node shape.

Every semantic-authoring stage in the research/design pipeline (research_plan,
evidence_synthesis, world_architecture, ...) has the identical shape: build a
``WorkDefinition``/``WorkAttempt`` pair, run exactly one ``invoke_structured_once``
call, and translate its two safe failure types into the three-lane ``Finding``
vocabulary. Only the definition, prompt, validator, and success-path artifact
writes differ per node. Factoring the shared part out here means a new
Agent-turn node adds its own small ``run`` function instead of re-deriving this
exception-classification block from scratch each time.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Callable

from pydantic import BaseModel

from ...contracts.jobs import PermissionScope
from ...control.leaf_executor import LeafExecutionFailure, LeafValidationFailure
from ...control.work import WorkAttempt, WorkDefinition
from ...designer.one_shot import StructuredProfileProvider, StructuredTurnResult, invoke_structured_once
from ...invocation import InvocationBackend, standalone_component_ownership
from ..node import NodeResult
from ..state import Finding, RunState


def build_attempt(
    *, node_id: str, state: RunState, definition: WorkDefinition
) -> tuple[WorkAttempt, int, str]:
    """Build the fresh ``WorkAttempt``/ordinal/dispatch_id triple for one turn.

    ``ordinal`` is derived from the slice's own attempt counter, so a rerun
    (local correction or backjump target) gets a fresh, distinct attempt id
    without any old-plane head bookkeeping.
    """

    ordinal = state.slice_for(node_id).attempts + 1
    now = datetime.now(UTC)
    attempt = WorkAttempt(
        attempt_id=f"attempt:{node_id}:{state.scope_id}:{ordinal}",
        work_id=definition.work_id,
        coordinate=definition.coordinate,
        ordinal=ordinal,
        status="running",
        definition_digest=definition.definition_digest,
        proposal_policy_digest=definition.proposal_policy.content_digest(),
        validation_policy_digest=definition.validation_policy.content_digest(),
        repair_policy_digest=definition.repair_policy.content_digest(),
        scheduled_at=now,
        started_at=now,
    )
    dispatch_id = f"{node_id}.{state.scope_id}.{ordinal}"
    return attempt, ordinal, dispatch_id


async def run_structured_agent_turn[TOutput: BaseModel](
    *,
    node_id: str,
    state: RunState,
    backend: InvocationBackend,
    profiles: StructuredProfileProvider,
    definition: WorkDefinition,
    workspace_root: Path,
    model: type[TOutput],
    prompt: str,
    permissions: PermissionScope,
    semantic_validator: Callable[[TOutput], None] | None = None,
) -> StructuredTurnResult[TOutput] | NodeResult:
    """Run one bounded Agent turn.

    Returns the parsed ``StructuredTurnResult`` on success. On a safe terminal
    failure, returns a ready-to-return ``NodeResult`` instead of raising, so
    callers write a two-line dispatch (``if isinstance(result, NodeResult):
    return result``) rather than repeating this translation.
    """

    attempt, ordinal, dispatch_id = build_attempt(node_id=node_id, state=state, definition=definition)
    try:
        return await invoke_structured_once(
            backend=backend,
            profiles=profiles,
            definition=definition,
            attempt=attempt,
            dispatch_id=dispatch_id,
            ownership=standalone_component_ownership(
                invocation_id=dispatch_id,
                component=node_id,
                coordinate=state.scope_id,
            ),
            lineage_id=f"{state.scope_id}.{node_id}.{ordinal}",
            workspace=workspace_root / node_id / attempt.attempt_id,
            model=model,
            prompt=prompt,
            permissions=permissions,
            semantic_validator=semantic_validator,
        )
    except LeafValidationFailure as exc:
        # Authority for design_defect vs framework_diagnosis is `.actionable`
        # on the ValidationIssue, never a guess from the exception message
        # (see scene-lane-validation-status-authority).
        actionable = any(issue.actionable for issue in exc.issues)
        lane = "design_defect" if actionable else "framework_diagnosis"
        summary = "; ".join(issue.violated_condition for issue in exc.issues)[:500]
        code = f"{node_id}_semantic_rejected"
        return NodeResult(
            status="failed" if lane == "design_defect" else "honest_stop",
            failure_code=code,
            failure_summary=summary or exc.category,
            findings=(
                Finding(
                    finding_id=f"{node_id}-validation-{ordinal}",
                    source_node=node_id,
                    lane=lane,
                    code=code,
                    summary=summary or exc.category,
                    rerun_target=node_id if lane == "design_defect" else None,
                ),
            ),
        )
    except LeafExecutionFailure as exc:
        lane = "infra_retryable" if exc.retryable else "framework_diagnosis"
        return NodeResult(
            status="failed" if lane == "infra_retryable" else "honest_stop",
            failure_code=exc.code,
            failure_summary=exc.category,
            findings=(
                Finding(
                    finding_id=f"{node_id}-execution-{ordinal}",
                    source_node=node_id,
                    lane=lane,
                    code=exc.code,
                    summary=exc.category,
                ),
            ),
        )


__all__ = ["build_attempt", "run_structured_agent_turn"]
