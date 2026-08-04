"""The StateGraph step loop.

One deterministic executor drives a run to a terminal frontier.  It replaces
``WorkScheduler.run_until_stalled`` and the duplicated readiness filter inlined
in ``DirectWorkRunner``.  The loop is intentionally small:

    while there is a ready node:
        run it -> NodeResult
        commit / fail / honest-stop its slice (append a new RunState version)
        route any actionable findings into a bounded back-jump

Resume is not a special path: a persisted ``RunState`` whose slices are not all
terminal simply re-enters the same loop, and every committed slice short-circuits
(``is_ready`` is False for terminal slices).  Raw exceptions from a node body are
classified here, in one place, into the ``framework_diagnosis`` lane.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .edge import GraphTopology
from .node import NodeContext, NodeRegistry, NodeResult
from .router import route_finding
from .state import Finding, NodeSlice, RunState

DEFAULT_RETRY_CEILING = 8


@dataclass(frozen=True)
class StepRecord:
    node_id: str
    status: str
    reason: str


@dataclass
class RunOutcome:
    state: RunState
    steps: list[StepRecord] = field(default_factory=list)

    @property
    def is_released(self) -> bool:
        return all(sl.is_committed for sl in self.state.slices.values()) and bool(
            self.state.slices
        )

    @property
    def stopped_node(self) -> str | None:
        for sl in self.state.slices.values():
            if sl.status in ("failed", "honest_stop"):
                return sl.node_id
        return None


class GraphExecutor:
    """Drive a RunState across a topology using a node registry."""

    def __init__(
        self,
        topology: GraphTopology,
        registry: NodeRegistry,
        *,
        retry_ceiling: int = DEFAULT_RETRY_CEILING,
    ) -> None:
        missing = topology.nodes and set(topology.nodes) - registry.ids()
        if missing:
            raise ValueError(f"topology references unregistered nodes: {sorted(missing)}")
        self._topology = topology
        self._registry = registry
        self._retry_ceiling = retry_ceiling

    async def run(
        self,
        state: RunState,
        *,
        persist: "StatePersister | None" = None,
    ) -> RunOutcome:
        outcome = RunOutcome(state=state)
        while True:
            ready = self._topology.ready_nodes(outcome.state)
            if not ready:
                break
            node_id = ready[0]
            await self._advance(node_id, outcome, persist)
            if outcome.stopped_node is not None:
                break
        return outcome

    async def _advance(
        self,
        node_id: str,
        outcome: RunOutcome,
        persist: "StatePersister | None",
    ) -> None:
        node = self._registry.get(node_id)
        prior = outcome.state.slice_for(node_id)
        inputs = self._gather_inputs(node_id, outcome.state)
        ctx = NodeContext(scope_id=outcome.state.scope_id, inputs=inputs)

        try:
            result = await node.run(outcome.state, ctx)
        except Exception as exc:  # noqa: BLE001 - single classification boundary
            result = self._classify_exception(node_id, exc)

        self._apply(node_id, prior, result, outcome)
        if persist is not None:
            persist.save(outcome.state)

    def _gather_inputs(self, node_id: str, state: RunState):
        inputs: dict = {}
        for up in self._topology.upstream_of(node_id):
            inputs.update(state.slice_for(up).outputs)
        return inputs

    def _apply(
        self,
        node_id: str,
        prior: NodeSlice,
        result: NodeResult,
        outcome: RunOutcome,
    ) -> None:
        state = outcome.state
        if result.findings:
            state = state.with_findings(result.findings)

        if result.status == "committed":
            slice_ = prior.model_copy(
                update={
                    "status": "committed",
                    "outputs": dict(result.outputs),
                    "attempts": prior.attempts + 1,
                    "failure_code": None,
                    "failure_summary": None,
                }
            )
            outcome.state = state.with_slice(slice_)
            outcome.steps.append(StepRecord(node_id, "committed", "node produced outputs"))
            return

        # Non-committed: consult the router using the node's own finding, if any.
        decision = self._decide(node_id, result, state)
        if decision.kind in ("local", "backjump"):
            target = decision.target or node_id
            # Every reset-to-pending consumes one attempt against the retry
            # ceiling, whether it is a local correction or a backjump target.
            # Without this, a node that never commits would never trip
            # route_finding's ceiling check and the loop would never converge
            # (violates S4: no-progress terminates).
            reset = state.slice_for(target).model_copy(
                update={"status": "pending", "attempts": state.slice_for(target).attempts + 1}
            )
            outcome.state = state.with_slice(reset)
            outcome.steps.append(StepRecord(node_id, decision.kind, decision.reason))
            return

        slice_ = prior.model_copy(
            update={
                "status": "honest_stop" if result.status == "honest_stop" else "failed",
                "attempts": prior.attempts + 1,
                "failure_code": result.failure_code or "framework_diagnostic_incomplete",
                "failure_summary": result.failure_summary or decision.reason,
            }
        )
        outcome.state = state.with_slice(slice_)
        outcome.steps.append(StepRecord(node_id, slice_.status, decision.reason))

    def _decide(self, node_id: str, result: NodeResult, state: RunState):
        from .router import RouteDecision

        actionable = [f for f in result.findings if f.lane == "design_defect"]
        if not actionable:
            return RouteDecision(
                kind="honest_stop",
                target=None,
                reason=result.failure_summary or "no actionable design finding",
            )
        return route_finding(
            actionable[0], state, self._topology, retry_ceiling=self._retry_ceiling
        )

    @staticmethod
    def _classify_exception(node_id: str, exc: Exception) -> NodeResult:
        return NodeResult(
            status="failed",
            failure_code="framework_diagnostic_incomplete",
            failure_summary=f"{node_id} raised {type(exc).__name__}: {exc}",
            findings=(
                Finding(
                    finding_id=f"{node_id}-exception",
                    source_node=node_id,
                    lane="framework_diagnosis",
                    code="framework_diagnostic_incomplete",
                    summary=f"unhandled {type(exc).__name__} in node body",
                ),
            ),
        )


class StatePersister:
    """Minimal persistence hook; concrete CAS head lives in head.py."""

    def save(self, state: RunState) -> None:  # pragma: no cover - interface
        raise NotImplementedError
