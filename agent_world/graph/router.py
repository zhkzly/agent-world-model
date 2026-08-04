"""Feedback routing: turn an actionable finding into a bounded back-jump.

This is the single authority that the old ``_route_parent_repair_if_requested``
plus ``_authorize_next_or_fail`` (five ``no_*_authority`` booleans) collapse
into.  Only a ``design_defect`` finding can move control backwards, and only by
a bounded hop distance (S3):

* distance 0  — local correction: rerun the source node itself.
* distance 1  — one topological hop to a direct upstream node, with causal
  evidence (the finding's ``rerun_target``).
* distance >=2 — not authorised: converge to an honest stop for a human.

A node that has exhausted its retry ceiling also converges to an honest stop
rather than looping (S4: no-progress terminates).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .edge import GraphTopology
from .state import Finding, RunState

RouteKind = Literal["local", "backjump", "honest_stop"]


@dataclass(frozen=True)
class RouteDecision:
    kind: RouteKind
    target: str | None
    reason: str


def route_finding(
    finding: Finding,
    state: RunState,
    topology: GraphTopology,
    *,
    retry_ceiling: int,
) -> RouteDecision:
    """Decide where an actionable finding sends control, fail-closed."""

    if finding.lane != "design_defect":
        # infra_retryable and framework_diagnosis never move the design graph.
        return RouteDecision(
            kind="honest_stop",
            target=None,
            reason=f"lane {finding.lane} does not authorise a feedback rerun",
        )

    source = finding.source_node
    target = finding.rerun_target or source

    # S4: a node past its retry ceiling stops honestly instead of looping.
    if state.slice_for(target).attempts >= retry_ceiling:
        return RouteDecision(
            kind="honest_stop",
            target=target,
            reason=f"{target} reached retry ceiling {retry_ceiling}",
        )

    if target == source:
        return RouteDecision(kind="local", target=source, reason="local correction")

    # distance-1 back-jump: target must be a direct upstream of the source.
    if target in topology.upstream_of(source):
        return RouteDecision(
            kind="backjump",
            target=target,
            reason=f"distance-1 causal rerun from {source} to {target}",
        )

    # distance >= 2 (or not an ancestor edge) is never auto-authorised.
    return RouteDecision(
        kind="honest_stop",
        target=target,
        reason=f"{target} is not a direct upstream of {source}; needs human",
    )
