"""The research_plan node: one bounded structured Agent turn, no old-plane coupling.

Uses the shared ``run_structured_agent_turn`` scaffolding (see ``_agent_turn.py``)
for the definition/attempt/translation boilerplate every Agent-turn node shares;
only the definition factory, prompt, validator, and success-path artifact write
are specific to this stage.
"""

from __future__ import annotations

from pathlib import Path

from agent_world.artifact_store import ArtifactWriter
from agent_world.contracts import EnvironmentRequest, GenerationContext
from agent_world.control.work_graph import research_plan_work_definition
from agent_world.designer.models import ResearchPlan
from agent_world.designer.one_shot import StructuredProfileProvider
from agent_world.designer.research_leaf import _research_plan_prompt
from agent_world.designer.validators import validate_research_plan_coverage
from agent_world.invocation import InvocationBackend

from ._agent_turn import run_structured_agent_turn
from ..node import NodeContext, NodeResult
from ..state import Finding, RunState

NODE_ID = "research_plan"


def make_research_plan_node(
    *,
    backend: InvocationBackend,
    profiles: StructuredProfileProvider,
    artifacts: ArtifactWriter,
    workspace_root: Path,
    agent_wall_seconds: float = 600.0,
    agent_token_limit: int = 65_536,
):
    """Bind the research_plan node body to its real backend/profile/artifact services."""

    async def run(state: RunState, _ctx: NodeContext) -> NodeResult:
        generation = artifacts.get_json(state.context_ref, GenerationContext)
        if generation.kind != "generate" or generation.request_ref is None:
            return NodeResult(
                status="honest_stop",
                failure_code="research_plan_context_kind_unsupported",
                failure_summary="research_plan requires one generate GenerationContext",
                findings=(
                    Finding(
                        finding_id=f"{NODE_ID}-context-kind",
                        source_node=NODE_ID,
                        lane="framework_diagnosis",
                        code="research_plan_context_kind_unsupported",
                        summary="GenerationContext is not a generate root",
                    ),
                ),
            )
        request = artifacts.get_json(generation.request_ref, EnvironmentRequest)

        definition = research_plan_work_definition(
            scope_id=state.scope_id,
            agent_wall_seconds=agent_wall_seconds,
            agent_token_limit=agent_token_limit,
        )
        turn = await run_structured_agent_turn(
            node_id=NODE_ID,
            state=state,
            backend=backend,
            profiles=profiles,
            definition=definition,
            workspace_root=workspace_root,
            model=ResearchPlan,
            prompt=_research_plan_prompt(request),
            permissions=generation.permissions,
            semantic_validator=validate_research_plan_coverage,
        )
        if isinstance(turn, NodeResult):
            return turn

        plan_ref = artifacts.put_json(
            artifact_id=f"{generation.context_id}:research-plan",
            artifact_type="design.research_plan",
            value=turn.output,
            dependencies=(state.context_ref,),
        )
        return NodeResult(status="committed", outputs={"research_plan": plan_ref})

    return run


__all__ = ["NODE_ID", "make_research_plan_node"]
