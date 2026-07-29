"""Typed ownership constructors for non-Work physical invocations.

Work-backed requests obtain their owner from ``WorkControlRuntime`` because
only it can prove an active operation and immutable parent closure.  A small
set of diagnostic or legacy component calls has no Work head; those calls must
still identify one physical attempt explicitly instead of relying on metadata
inference in the Invocation Control Plane.
"""

from __future__ import annotations

from .contracts import InvocationOwnerKind, InvocationOwnership


def standalone_component_ownership(
    *,
    invocation_id: str,
    component: str,
    coordinate: str | None = None,
) -> InvocationOwnership:
    """Return explicit safe ownership for one non-Work physical turn.

    ``component`` and ``coordinate`` are framework-defined identifiers, never
    Prompt, response, session, workspace, or user-visible task text.  The
    ``InvocationOwnership`` contract validates them before anything reaches a
    durable control record.
    """

    return InvocationOwnership(
        owner_kind=InvocationOwnerKind.STANDALONE_COMPONENT,
        owner_id=invocation_id,
        scope_id=component,
        coordinate=coordinate,
    )


__all__ = ["standalone_component_ownership"]
