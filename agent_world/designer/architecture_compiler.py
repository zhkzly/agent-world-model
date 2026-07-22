"""Pure deterministic Architecture compilation used by Scheduler leaves.

The legacy ``EnvironmentDesigner`` owns an older multi-turn orchestration
loop, but its architecture compiler is intentionally stateless: it turns one
typed source draft and one frozen evidence graph into framework-owned schema
and coupling artifacts.  This module exposes only that deterministic boundary
so a Scheduler leaf never enters the old feedback/retry controller.
"""

from __future__ import annotations

from agent_world.contracts import ArtifactRef, EvidenceGraph

from .models import ToolCouplingPlan, WorldArchitectureSourceDraft, WorldSkeletonDraft
from .service import EnvironmentDesigner


def compile_world_architecture(
    source: WorldArchitectureSourceDraft,
    *,
    evidence_graph: EvidenceGraph,
) -> WorldSkeletonDraft:
    """Compile one Agent-authored architecture into a closed WorldSkeleton.

    The call has no profile, workspace, artifact store, retry state, or release
    authority.  Every schema, reference, identity, and evidence check remains
    framework code and produces a typed validation failure at this leaf.
    """

    return EnvironmentDesigner._compile_architecture_skeleton(
        source,
        evidence_graph=evidence_graph,
    )


def compile_tool_coupling_plan(
    source: WorldArchitectureSourceDraft,
    *,
    architecture_ref: ArtifactRef,
) -> ToolCouplingPlan:
    """Derive fixed tool coupling from frozen tool/state footprints in code."""

    return EnvironmentDesigner._compile_tool_coupling_plan(
        source,
        architecture_ref=architecture_ref,
    )


__all__ = ["compile_tool_coupling_plan", "compile_world_architecture"]
