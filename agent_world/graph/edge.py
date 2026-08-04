"""Forward topology for the StateGraph.

A declarative DAG of ``node -> downstream nodes``.  A node is ready when every
upstream node's slice is committed.  This replaces the 4-epoch WorkGraph
compilation and its three separate compile entry points with one immutable,
validated adjacency structure that both generate and expand instantiate.
"""

from __future__ import annotations

from dataclasses import dataclass

from .state import RunState


@dataclass(frozen=True)
class GraphTopology:
    """Immutable forward DAG keyed by node id.

    ``upstream`` is derived once and cached; ``downstream`` is the authored
    adjacency.  Construction validates that the graph is acyclic and closed
    (every referenced node exists), so the executor never has to defend against
    a malformed topology at run time.
    """

    downstream: dict[str, frozenset[str]]
    _upstream: dict[str, frozenset[str]]
    _order: tuple[str, ...]

    @classmethod
    def build(cls, edges: dict[str, frozenset[str] | set[str] | tuple[str, ...]]) -> "GraphTopology":
        downstream = {node: frozenset(succ) for node, succ in edges.items()}
        nodes = set(downstream)
        for succ in downstream.values():
            nodes |= succ
        # every referenced node must have an entry (leaves map to empty set)
        for node in nodes:
            downstream.setdefault(node, frozenset())

        upstream: dict[str, set[str]] = {node: set() for node in downstream}
        for node, succ in downstream.items():
            for child in succ:
                upstream[child].add(node)

        order = _topological_order(downstream)
        return cls(
            downstream={n: frozenset(s) for n, s in downstream.items()},
            _upstream={n: frozenset(s) for n, s in upstream.items()},
            _order=order,
        )

    @property
    def nodes(self) -> tuple[str, ...]:
        return self._order

    def upstream_of(self, node_id: str) -> frozenset[str]:
        return self._upstream.get(node_id, frozenset())

    def downstream_of(self, node_id: str) -> frozenset[str]:
        return self.downstream.get(node_id, frozenset())

    def roots(self) -> tuple[str, ...]:
        return tuple(n for n in self._order if not self._upstream.get(n))

    def is_ready(self, node_id: str, state: RunState) -> bool:
        """A node is ready when all upstream slices are committed and it isn't done."""

        if state.slice_for(node_id).is_terminal:
            return False
        return all(state.slice_for(up).is_committed for up in self.upstream_of(node_id))

    def ready_nodes(self, state: RunState) -> tuple[str, ...]:
        return tuple(n for n in self._order if self.is_ready(n, state))


def _topological_order(downstream: dict[str, frozenset[str]]) -> tuple[str, ...]:
    """Kahn's algorithm; raises on a cycle so bad topologies fail at build time."""

    indegree = {node: 0 for node in downstream}
    for succ in downstream.values():
        for child in succ:
            indegree[child] += 1
    queue = sorted(n for n, d in indegree.items() if d == 0)
    order: list[str] = []
    while queue:
        node = queue.pop(0)
        order.append(node)
        for child in sorted(downstream[node]):
            indegree[child] -= 1
            if indegree[child] == 0:
                queue.append(child)
        queue.sort()
    if len(order) != len(downstream):
        cyclic = sorted(set(downstream) - set(order))
        raise ValueError(f"graph topology has a cycle among {cyclic}")
    return tuple(order)
