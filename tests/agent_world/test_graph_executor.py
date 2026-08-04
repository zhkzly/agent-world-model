"""P0 unit tests for the self-owned StateGraph executor.

These are deterministic and burn no LLM: they prove ready/commit/resume/router
behaviour on toy nodes so later phases can trust the executor while real node
bodies are ported in.
"""

from __future__ import annotations

import asyncio

import pytest

from agent_world.contracts.base import ArtifactRef
from agent_world.graph import (
    Finding,
    GraphExecutor,
    GraphTopology,
    NodeContext,
    NodeRegistry,
    NodeResult,
    NodeSlice,
    RunState,
    route_finding,
)


def _ref(name: str) -> ArtifactRef:
    h = "sha256:" + "0" * 64
    return ArtifactRef(
        artifact_id=name,
        revision_id=h,
        artifact_type="test.output",
        content_hash=h,
        media_type="application/json",
        size_bytes=1,
    )


def _context_ref() -> ArtifactRef:
    h = "sha256:" + "1" * 64
    return ArtifactRef(
        artifact_id="ctx",
        revision_id=h,
        artifact_type="control.generation_context",
        content_hash=h,
        media_type="application/json",
        size_bytes=1,
    )


def _fresh_state() -> RunState:
    return RunState(
        request_id="req-1",
        scope_id="scope-1",
        context_ref=_context_ref(),
        lease_id="lease-1",
    )


def _linear_topology() -> GraphTopology:
    return GraphTopology.build({"a": {"b"}, "b": {"c"}, "c": set()})


def _commit_node(node_id: str):
    async def fn(state: RunState, ctx: NodeContext) -> NodeResult:
        return NodeResult(status="committed", outputs={node_id: _ref(node_id)})

    return fn


def test_linear_run_reaches_release() -> None:
    reg = NodeRegistry()
    for nid in ("a", "b", "c"):
        reg.function(nid)(_commit_node(nid))
    ex = GraphExecutor(_linear_topology(), reg)

    outcome = asyncio.run(ex.run(_fresh_state()))

    assert outcome.is_released
    assert [s.status for s in outcome.steps] == ["committed", "committed", "committed"]
    assert set(outcome.state.slices) == {"a", "b", "c"}


def test_committed_slices_short_circuit_on_resume() -> None:
    reg = NodeRegistry()
    calls: list[str] = []

    for nid in ("a", "b", "c"):
        def make(nid: str):
            async def fn(state: RunState, ctx: NodeContext) -> NodeResult:
                calls.append(nid)
                return NodeResult(status="committed", outputs={nid: _ref(nid)})

            return fn

        reg.function(nid)(make(nid))

    ex = GraphExecutor(_linear_topology(), reg)
    # Pre-commit 'a' so resume must skip it.
    state = _fresh_state().with_slice(
        NodeSlice(node_id="a", status="committed", outputs={"a": _ref("a")})
    )

    asyncio.run(ex.run(state))

    assert calls == ["b", "c"]  # 'a' was not re-run


def test_upstream_inputs_are_gathered_for_downstream_node() -> None:
    reg = NodeRegistry()
    seen: dict[str, dict] = {}

    async def a(state: RunState, ctx: NodeContext) -> NodeResult:
        return NodeResult(status="committed", outputs={"a_out": _ref("a")})

    async def b(state: RunState, ctx: NodeContext) -> NodeResult:
        seen["b"] = dict(ctx.inputs)
        return NodeResult(status="committed", outputs={"b_out": _ref("b")})

    reg.function("a")(a)
    reg.function("b")(b)
    ex = GraphExecutor(GraphTopology.build({"a": {"b"}, "b": set()}), reg)

    asyncio.run(ex.run(_fresh_state()))

    assert "a_out" in seen["b"]


def test_design_defect_local_finding_reruns_node_until_commit() -> None:
    reg = NodeRegistry()
    attempts = {"n": 0}

    async def flaky(state: RunState, ctx: NodeContext) -> NodeResult:
        attempts["n"] += 1
        if attempts["n"] < 2:
            return NodeResult(
                status="failed",
                failure_code="rule_gap",
                failure_summary="needs one more pass",
                findings=(
                    Finding(
                        finding_id="f1",
                        source_node="only",
                        lane="design_defect",
                        code="rule_gap",
                        summary="local correctable gap",
                    ),
                ),
            )
        return NodeResult(status="committed", outputs={"only": _ref("only")})

    reg.function("only")(flaky)
    ex = GraphExecutor(GraphTopology.build({"only": set()}), reg)

    outcome = asyncio.run(ex.run(_fresh_state()))

    assert outcome.is_released
    assert attempts["n"] == 2


def test_non_design_lane_finding_stops_honestly() -> None:
    reg = NodeRegistry()

    async def infra(state: RunState, ctx: NodeContext) -> NodeResult:
        return NodeResult(
            status="failed",
            failure_code="provider_unavailable",
            failure_summary="tunnel 502",
            findings=(
                Finding(
                    finding_id="f1",
                    source_node="only",
                    lane="infra_retryable",
                    code="provider_unavailable",
                    summary="tunnel 502",
                ),
            ),
        )

    reg.function("only")(infra)
    ex = GraphExecutor(GraphTopology.build({"only": set()}), reg)

    outcome = asyncio.run(ex.run(_fresh_state()))

    assert not outcome.is_released
    assert outcome.stopped_node == "only"


def test_node_exception_classified_as_framework_diagnosis() -> None:
    reg = NodeRegistry()

    async def boom(state: RunState, ctx: NodeContext) -> NodeResult:
        raise RuntimeError("kaboom")

    reg.function("only")(boom)
    ex = GraphExecutor(GraphTopology.build({"only": set()}), reg)

    outcome = asyncio.run(ex.run(_fresh_state()))

    assert outcome.stopped_node == "only"
    stopped = outcome.state.slice_for("only")
    assert stopped.failure_code == "framework_diagnostic_incomplete"


def test_executor_rejects_unregistered_topology_node() -> None:
    reg = NodeRegistry()
    reg.function("a")(_commit_node("a"))
    with pytest.raises(ValueError, match="unregistered"):
        GraphExecutor(GraphTopology.build({"a": {"b"}, "b": set()}), reg)


def test_router_backjump_requires_direct_upstream() -> None:
    topology = GraphTopology.build({"a": {"b"}, "b": {"c"}, "c": set()})
    state = _fresh_state()

    # c blames its direct upstream b -> distance-1 backjump authorised.
    f_ok = Finding(
        finding_id="f",
        source_node="c",
        lane="design_defect",
        code="x",
        summary="s",
        rerun_target="b",
    )
    assert route_finding(f_ok, state, topology, retry_ceiling=8).kind == "backjump"

    # c blames a (distance 2) -> not authorised, honest stop.
    f_far = f_ok.model_copy(update={"rerun_target": "a"})
    assert route_finding(f_far, state, topology, retry_ceiling=8).kind == "honest_stop"


def test_router_retry_ceiling_converges_to_honest_stop() -> None:
    topology = GraphTopology.build({"only": set()})
    state = _fresh_state().with_slice(NodeSlice(node_id="only", status="pending", attempts=8))
    finding = Finding(
        finding_id="f",
        source_node="only",
        lane="design_defect",
        code="x",
        summary="s",
    )
    decision = route_finding(finding, state, topology, retry_ceiling=8)
    assert decision.kind == "honest_stop"


def test_head_store_round_trips_and_persists_progress(tmp_path) -> None:
    from agent_world.graph import RunHeadStore

    store = RunHeadStore(tmp_path)
    assert store.read("scope-1") is None

    state = _fresh_state().with_slice(
        NodeSlice(node_id="a", status="committed", outputs={"a": _ref("a")})
    )
    store.save(state)

    reloaded = store.read("scope-1")
    assert reloaded is not None
    assert reloaded.stable_json() == state.stable_json()
    assert reloaded.slice_for("a").is_committed
    assert store.scopes() == ("scope-1",)


def test_executor_persists_each_committed_step(tmp_path) -> None:
    from agent_world.graph import RunHeadStore

    reg = NodeRegistry()
    for nid in ("a", "b", "c"):
        reg.function(nid)(_commit_node(nid))
    store = RunHeadStore(tmp_path)
    ex = GraphExecutor(_linear_topology(), reg)

    asyncio.run(ex.run(_fresh_state(), persist=store))

    # After the run the head reflects a fully released state, resumable in place.
    head = store.read("scope-1")
    assert head is not None
    assert all(head.slice_for(n).is_committed for n in ("a", "b", "c"))
