from __future__ import annotations

import multiprocessing
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from agent_world.artifact_store import ArtifactStore
from agent_world.contracts import Budget, BudgetUsage, sha256_digest
from agent_world.control import (
    BudgetExceeded,
    DurableLeaseBudgetCoordinator,
    OperationRun,
    WorkCoordinate,
)
from agent_world.control.models import BudgetLease


def _compete_for_one_turn(
    root: str,
    lease_id: str,
    ready: multiprocessing.synchronize.Event,
    results: multiprocessing.queues.Queue,
) -> None:
    coordinator = DurableLeaseBudgetCoordinator(root)
    coordinator.initialize(
        scope_id="job:concurrent",
        reserved=Budget(agent_turns=1, wall_seconds=100),
    )
    ready.wait(timeout=10)
    try:
        coordinator.reserve(
            scope_id="job:concurrent",
            lease_id=lease_id,
            owner_id=lease_id,
            requested=Budget(agent_turns=1, wall_seconds=10),
            elapsed_wall_seconds=0,
        )
    except BudgetExceeded:
        results.put("denied")
    else:
        results.put("reserved")


def test_scope_budget_admission_is_cross_process_and_cannot_oversell(
    tmp_path: Path,
) -> None:
    root = tmp_path / "budget-control"
    context = multiprocessing.get_context("fork")
    ready = context.Event()
    results = context.Queue()
    processes = tuple(
        context.Process(
            target=_compete_for_one_turn,
            args=(str(root), f"lease:{ordinal}", ready, results),
        )
        for ordinal in (1, 2)
    )
    for process in processes:
        process.start()
    ready.set()
    outcomes = sorted(results.get(timeout=10) for _ in processes)
    for process in processes:
        process.join(timeout=10)
        assert process.exitcode == 0

    assert outcomes == ["denied", "reserved"]
    snapshot = DurableLeaseBudgetCoordinator(root).snapshot(scope_id="job:concurrent")
    assert len(snapshot.leases) == 1
    assert snapshot.leases[0].status == "active"


def test_scope_budget_settlement_is_idempotent_but_cannot_be_rewritten(
    tmp_path: Path,
) -> None:
    coordinator = DurableLeaseBudgetCoordinator(tmp_path / "budget-control")
    coordinator.initialize(
        scope_id="job:hotel",
        reserved=Budget(llm_tokens=100, agent_turns=1, wall_seconds=100),
    )
    coordinator.reserve(
        scope_id="job:hotel",
        lease_id="lease:proposal",
        owner_id="operation:proposal",
        requested=Budget(llm_tokens=100, agent_turns=1, wall_seconds=10),
        elapsed_wall_seconds=0,
    )
    actual = BudgetUsage(llm_tokens=40, agent_turns=1, wall_seconds=2)
    first = coordinator.settle(
        scope_id="job:hotel",
        lease_id="lease:proposal",
        observed_actual=actual,
    )
    second = coordinator.settle(
        scope_id="job:hotel",
        lease_id="lease:proposal",
        observed_actual=actual,
    )
    assert first == second
    with pytest.raises(ValueError, match="cannot be changed"):
        coordinator.settle(
            scope_id="job:hotel",
            lease_id="lease:proposal",
            observed_actual=BudgetUsage(llm_tokens=41, agent_turns=1, wall_seconds=2),
        )


def test_operation_run_requires_pre_dispatch_and_exact_terminal_evidence(
    tmp_path: Path,
) -> None:
    writer = ArtifactStore(tmp_path / "artifacts").issue_writer(
        producer="work-controller",
        allowed_artifact_type_prefixes=("control.",),
    )
    lease = BudgetLease(
        lease_id="lease:proposal",
        owner_id="operation:proposal",
        reserved=Budget(llm_tokens=100, agent_turns=1, wall_seconds=10),
        created_at=datetime.now(UTC),
    )
    lease_ref = writer.put_json(
        artifact_id=lease.lease_id,
        artifact_type="control.budget_lease",
        value=lease,
    )
    coordinate = WorkCoordinate(
        scope_id="job:hotel",
        component="design",
        stage="behavior",
        artifact_slot="tool_semantics",
    )
    scheduled = OperationRun(
        operation_run_id="operation-run:proposal:1",
        attempt_id="attempt:1",
        coordinate=coordinate,
        kind="proposal",
        ordinal=1,
        revision=1,
        policy_id="proposal:tool-semantics",
        policy_digest=sha256_digest(b"policy"),
        operation="design.tool_semantics",
        replay_mode="queryable",
        status="scheduled",
        budget_lease_ref=lease_ref,
        scheduled_at=datetime.now(UTC),
    )
    with pytest.raises(ValueError, match="dispatch identity"):
        scheduled.model_copy(
            update={"status": "running", "started_at": datetime.now(UTC)}
        ).model_validate(
            scheduled.model_copy(
                update={"status": "running", "started_at": datetime.now(UTC)}
            ).model_dump(mode="python")
        )

    started_at = datetime.now(UTC)
    execution_ref = writer.put_json(
        artifact_id="execution:proposal:1",
        artifact_type="control.proposal_execution",
        value={"execution_id": "execution:1"},
    )
    terminal = scheduled.model_copy(
        update={
            "status": "terminal",
            "dispatch_id": "invocation:1",
            "execution_ref": execution_ref,
            "started_at": started_at,
            "finished_at": started_at + timedelta(seconds=1),
        }
    )
    assert OperationRun.model_validate(terminal.model_dump(mode="python")).status == "terminal"
