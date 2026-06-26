from __future__ import annotations

import json
from pathlib import Path

import pytest

from awmx.artifacts.schemas import ValidationError
from awmx.config import load_workflow_config
from awmx.workflow.runner import WorkflowDryRunRunner
from awmx.workflow.spec import topological_order


def _workflow_yaml(nodes: list[dict[str, object]]) -> str:
    return """
id: workflow.test
version: 0.1.0
created_at: "2026-06-27T00:00:00Z"
source:
  kind: fixture
  uri: tests/awmx/test_workflow.py
metadata:
  stage: workflow
nodes:
{nodes_block}
budgets:
  max_nodes: 8
gates:
  require_events_jsonl: true
""".strip().format(nodes_block=_nodes_block(nodes))


def _nodes_block(nodes: list[dict[str, object]]) -> str:
    lines: list[str] = []
    for node in nodes:
        needs = node.get("needs", [])
        config = node.get("config", {})
        lines.extend(
            [
                f"  - id: {node['id']}",
                f"    node_type: {node['node_type']}",
                "    needs:",
            ]
        )
        if needs:
            for dependency in needs:
                lines.append(f"      - {dependency}")
        else:
            lines.append("      []")
        lines.append("    config:")
        if config:
            for key, value in config.items():
                lines.append(f"      {key}: {json.dumps(value)}")
        else:
            lines.append("      {}")
    return "\n".join(lines)


def _write_workflow(path: Path, nodes: list[dict[str, object]]) -> Path:
    path.write_text(_workflow_yaml(nodes) + "\n", encoding="utf-8")
    return path


def test_topological_order_respects_dependencies(tmp_path: Path):
    workflow_path = _write_workflow(
        tmp_path / "workflow.yaml",
        [
            {"id": "verify", "node_type": "verification.deterministic", "needs": ["rollout"]},
            {"id": "import", "node_type": "awm.import_fixture", "needs": []},
            {"id": "rollout", "node_type": "rollout.scripted", "needs": ["import"]},
        ],
    )

    workflow = load_workflow_config(workflow_path)

    assert [node.id for node in topological_order(workflow)] == ["import", "rollout", "verify"]


def test_missing_dependency_fails_validation(tmp_path: Path):
    workflow_path = _write_workflow(
        tmp_path / "missing_dependency.yaml",
        [
            {"id": "import", "node_type": "awm.import_fixture", "needs": []},
            {"id": "verify", "node_type": "verification.deterministic", "needs": ["missing"]},
        ],
    )

    with pytest.raises(ValidationError, match="unknown dependencies"):
        load_workflow_config(workflow_path)


def test_cycle_fails_validation(tmp_path: Path):
    workflow_path = _write_workflow(
        tmp_path / "cycle.yaml",
        [
            {"id": "a", "node_type": "awm.import_fixture", "needs": ["c"]},
            {"id": "b", "node_type": "awm.check_environment", "needs": ["a"]},
            {"id": "c", "node_type": "rollout.scripted", "needs": ["b"]},
        ],
    )

    with pytest.raises(ValidationError, match="cycle"):
        load_workflow_config(workflow_path)


def test_unknown_node_type_fails_validation(tmp_path: Path):
    workflow_path = _write_workflow(
        tmp_path / "unknown_type.yaml",
        [{"id": "mystery", "node_type": "workflow.unknown", "needs": []}],
    )

    with pytest.raises(ValidationError, match="unknown node type"):
        load_workflow_config(workflow_path)


def test_dry_run_writes_planned_blocked_and_skipped_events(tmp_path: Path):
    workflow = load_workflow_config(Path("configs/agent_world/workflows/vertical_slice.yaml"))
    runner = WorkflowDryRunRunner(output_root=tmp_path / "outputs")

    result = runner.run(workflow, workflow_path=Path("configs/agent_world/workflows/vertical_slice.yaml"))

    assert result.events_path.exists()
    events = [
        json.loads(line)
        for line in result.events_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    statuses = {event["node_id"]: event["status"] for event in events}

    assert statuses["load_awm_fixture"] == "planned"
    assert statuses["check_environment"] == "planned"
    assert statuses["scripted_rollout"] == "blocked"
    assert statuses["deterministic_verify"] == "skipped"
    assert statuses["record_reward"] == "skipped"
    assert {event["status"] for event in events} == {"planned", "blocked", "skipped"}
