"""Node contract and registry for the StateGraph control plane.

A node is one pipeline stage: ``async (RunState, NodeContext) -> NodeResult``.
It reads only the upstream output refs it declares and writes only its declared
outputs.  Every node returns exactly one typed ``NodeResult``; the executor is
the single place that turns raw exceptions into the three finding lanes, so the
7+ ad hoc except branches of the old leaf executor collapse here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Awaitable, Callable, Literal, Protocol

from pydantic import Field, model_validator

from ..contracts.base import ArtifactRef, Identifier, NonEmptyStr, V2Contract
from ..contracts.jobs import BudgetUsage
from .state import Finding, RunState

NodeOutcome = Literal["committed", "failed", "honest_stop"]


class NodeResult(V2Contract):
    """The single typed value every node returns.

    ``outputs`` are written into the node's slice on ``committed``.  ``findings``
    feed the router; a ``design_defect`` finding with a ``rerun_target`` requests
    a bounded back-jump.  ``usage`` is charged against the run's budget lease.
    """

    status: NodeOutcome
    outputs: dict[Identifier, ArtifactRef] = Field(default_factory=dict)
    findings: tuple[Finding, ...] = ()
    usage: BudgetUsage = Field(default_factory=BudgetUsage)
    failure_code: Identifier | None = None
    failure_summary: NonEmptyStr | None = None

    @model_validator(mode="after")
    def _outcome_shape(self) -> NodeResult:
        if self.status == "committed" and not self.outputs:
            raise ValueError("committed results must carry at least one output ref")
        if self.status in ("failed", "honest_stop") and self.failure_code is None:
            raise ValueError(f"{self.status} results require a failure_code")
        if self.status == "committed" and self.failure_code is not None:
            raise ValueError("committed results cannot carry a failure_code")
        return self


@dataclass(frozen=True)
class NodeContext:
    """Ambient, non-state services handed to a node body.

    These are impure edges of the world (artifact store, backends, clocks) that
    must not live inside the content-addressed ``RunState``.  Kept deliberately
    minimal; concrete node families extend it via composition, not inheritance.
    """

    scope_id: str
    inputs: dict[str, ArtifactRef]


NodeFn = Callable[[RunState, NodeContext], Awaitable[NodeResult]]


class Node(Protocol):
    """A registered pipeline stage."""

    node_id: str

    async def run(self, state: RunState, ctx: NodeContext) -> NodeResult: ...


@dataclass(frozen=True)
class FunctionNode:
    """Wrap a plain async function as a Node."""

    node_id: str
    fn: NodeFn

    async def run(self, state: RunState, ctx: NodeContext) -> NodeResult:
        return await self.fn(state, ctx)


class NodeRegistry:
    """A flat, name-keyed set of nodes; the graph topology lives in edge.py."""

    def __init__(self) -> None:
        self._nodes: dict[str, Node] = {}

    def register(self, node: Node) -> Node:
        if node.node_id in self._nodes:
            raise ValueError(f"node {node.node_id!r} already registered")
        self._nodes[node.node_id] = node
        return node

    def function(self, node_id: str) -> Callable[[NodeFn], NodeFn]:
        def decorate(fn: NodeFn) -> NodeFn:
            self.register(FunctionNode(node_id=node_id, fn=fn))
            return fn

        return decorate

    def get(self, node_id: str) -> Node:
        try:
            return self._nodes[node_id]
        except KeyError:
            raise KeyError(f"no node registered for {node_id!r}") from None

    def __contains__(self, node_id: str) -> bool:
        return node_id in self._nodes

    def ids(self) -> frozenset[str]:
        return frozenset(self._nodes)
