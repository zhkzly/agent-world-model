"""Self-owned deterministic StateGraph control plane.

This package replaces the fragmented WorkGraph / WorkScheduler / DirectWorkRunner
/ WorkControlRuntime / leaf-executor control stack with four first-class
concepts (see docs/plans/stategraph-rewrite.md):

* ``state``    - RunState / NodeSlice / Finding: content-addressed run state.
* ``node``     - Node protocol, NodeResult, NodeContext, NodeRegistry.
* ``edge``     - GraphTopology: the forward DAG and readiness rule.
* ``router``   - route_finding: bounded feedback back-jumps (S3/S4).
* ``executor`` - GraphExecutor: the single deterministic step loop.
* ``head``     - RunHeadStore: one file-locked CAS head per scope.
"""

from __future__ import annotations

from .edge import GraphTopology
from .executor import DEFAULT_RETRY_CEILING, GraphExecutor, RunOutcome, StatePersister, StepRecord
from .head import RunHeadStore
from .node import (
    FunctionNode,
    Node,
    NodeContext,
    NodeRegistry,
    NodeResult,
)
from .router import RouteDecision, route_finding
from .state import Finding, FindingLane, NodeSlice, NodeStatus, RunState

__all__ = [
    "DEFAULT_RETRY_CEILING",
    "Finding",
    "FindingLane",
    "FunctionNode",
    "GraphExecutor",
    "GraphTopology",
    "Node",
    "NodeContext",
    "NodeRegistry",
    "NodeResult",
    "NodeSlice",
    "NodeStatus",
    "RouteDecision",
    "RunHeadStore",
    "RunOutcome",
    "RunState",
    "StatePersister",
    "StepRecord",
    "route_finding",
]
