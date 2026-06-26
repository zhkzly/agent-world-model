from __future__ import annotations

import json
import subprocess
from pathlib import Path

import yaml


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _write_config(path: Path, *, runs_root: str = "outputs/agent_world/runs", datasets_root: str = "outputs/agent_world/datasets") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(
            {
                "id": "config.agent_world.base",
                "version": "0.1.0",
                "created_at": "2026-06-27T00:00:00Z",
                "source": {"kind": "fixture", "uri": str(path)},
                "metadata": {"suite": "e2e"},
                "paths": {
                    "config_root": "configs/agent_world",
                    "output_root": "outputs/agent_world",
                    "runs_root": runs_root,
                    "datasets_root": datasets_root,
                },
                "policies": {},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return path


def _write_workflow(path: Path, *, nodes: list[dict]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(
            {
                "id": "workflow.vertical_slice",
                "version": "0.1.0",
                "created_at": "2026-06-27T00:00:00Z",
                "source": {"kind": "fixture", "uri": str(path)},
                "metadata": {"suite": "e2e"},
                "nodes": nodes,
                "budgets": {"max_rollout_steps": 8},
                "gates": {},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return path


def _vertical_nodes(*, verifier_ref: str = "deterministic.yaml") -> list[dict]:
    return [
        {
            "id": "load_fixture_custom",
            "node_type": "awm.import_fixture",
            "needs": [],
            "config": {},
        },
        {
            "id": "check_env_custom",
            "node_type": "awm.check_environment",
            "needs": ["load_fixture_custom"],
            "config": {},
        },
        {
            "id": "rollout_custom",
            "node_type": "rollout.scripted",
            "needs": ["check_env_custom"],
            "config": {},
        },
        {
            "id": "verify_custom",
            "node_type": "verification.deterministic",
            "needs": ["rollout_custom"],
            "config": {"verifier_ref": verifier_ref},
        },
        {
            "id": "reward_custom",
            "node_type": "verification.reward_record",
            "needs": ["verify_custom"],
            "config": {},
        },
    ]


def test_awmx_run_creates_trace_reward_and_rl_export():
    result = subprocess.run(
        [
            "uv",
            "run",
            "python",
            "-m",
            "awmx.cli",
            "run",
            "configs/agent_world/workflows/vertical_slice.yaml",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    payload = json.loads(result.stdout)
    run_dir = Path(payload["run_dir"])
    dataset_path = Path(payload["dataset_path"])

    assert payload["status"] == "ok"
    assert payload["workflow_id"] == "workflow.vertical_slice"
    assert run_dir == Path.cwd() / "outputs/agent_world/runs" / payload["run_id"]
    assert (run_dir / "run.yaml").exists()
    assert (run_dir / "events.jsonl").exists()
    assert (run_dir / "trace.jsonl").exists()
    assert (run_dir / "reward.json").exists()
    assert dataset_path == Path.cwd() / "outputs/agent_world/datasets/rl" / f"{payload['run_id']}.jsonl"
    assert dataset_path.exists()

    run_yaml = yaml.safe_load((run_dir / "run.yaml").read_text(encoding="utf-8"))
    assert run_yaml["id"] == payload["run_id"]
    assert run_yaml["runner"]["type"] == "scripted"

    events = _read_jsonl(run_dir / "events.jsonl")
    event_names = [event["event"] for event in events]
    assert "workflow_started" in event_names
    assert "rollout_started" in event_names
    assert "rollout_completed" in event_names
    assert "verification_completed" in event_names
    assert "reward_recorded" in event_names
    assert "dataset_exported" in event_names
    assert event_names[-1] == "workflow_completed"

    trace_rows = _read_jsonl(run_dir / "trace.jsonl")
    assert [row["sequence"] for row in trace_rows] == [1, 2]
    assert trace_rows[0]["action"]["kind"] == "message"
    assert trace_rows[1]["action"]["kind"] == "write_file"
    assert trace_rows[1]["evidence"]["permission"]["allowed"] is True
    assert (run_dir / "workspace" / "done.txt").read_text(encoding="utf-8") == "done\n"

    reward = json.loads((run_dir / "reward.json").read_text(encoding="utf-8"))
    assert reward["source"]["kind"] == "verifier"
    assert reward["passed"] is True
    assert reward["score"] == 1.0
    assert reward["evidence"]["checks"][0]["name"] == "completion_file"

    dataset_rows = _read_jsonl(dataset_path)
    assert len(dataset_rows) == 1
    assert dataset_rows[0]["run_id"] == payload["run_id"]
    assert dataset_rows[0]["reward"]["id"] == reward["id"]
    assert dataset_rows[0]["trace"][1]["action"]["kind"] == "write_file"


def test_awmx_run_uses_config_root_when_called_from_another_cwd(tmp_path: Path):
    call_cwd = tmp_path / "caller"
    call_cwd.mkdir()
    workflow_path = Path.cwd() / "configs/agent_world/workflows/vertical_slice.yaml"
    config_path = Path.cwd() / "configs/agent_world/base.yaml"

    result = subprocess.run(
        [
            "uv",
            "run",
            "--project",
            str(Path.cwd()),
            "python",
            "-m",
            "awmx.cli",
            "run",
            str(workflow_path),
            "--config",
            str(config_path),
        ],
        check=True,
        cwd=call_cwd,
        capture_output=True,
        text=True,
    )

    payload = json.loads(result.stdout)
    assert Path(payload["run_dir"]).is_relative_to(Path.cwd() / "outputs/agent_world/runs")
    assert Path(payload["dataset_path"]).is_relative_to(Path.cwd() / "outputs/agent_world/datasets/rl")
    assert not (call_cwd / "outputs").exists()


def test_awmx_run_honors_configured_datasets_root(tmp_path: Path):
    project_root = tmp_path / "project"
    workflow_path = _write_workflow(
        project_root / "configs/agent_world/workflows/custom_vertical.yaml",
        nodes=_vertical_nodes(),
    )
    config_path = _write_config(
        project_root / "configs/agent_world/base.yaml",
        runs_root="runtime/runs",
        datasets_root="exports/datasets",
    )

    result = subprocess.run(
        [
            "uv",
            "run",
            "--project",
            str(Path.cwd()),
            "python",
            "-m",
            "awmx.cli",
            "run",
            str(workflow_path),
            "--config",
            str(config_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    payload = json.loads(result.stdout)
    assert Path(payload["run_dir"]).is_relative_to(project_root / "runtime/runs")
    assert Path(payload["dataset_path"]).is_relative_to(project_root / "exports/datasets/rl")
    assert not (project_root / "runtime" / "datasets").exists()
    events = _read_jsonl(Path(payload["run_dir"]) / "events.jsonl")
    completed_node_ids = [event["payload"].get("node_id") for event in events if event["event"] == "node_completed"]
    assert "rollout_custom" in completed_node_ids


def test_awmx_run_rejects_workflow_without_required_vertical_nodes(tmp_path: Path):
    workflow_path = _write_workflow(
        tmp_path / "project/configs/agent_world/workflows/no_reward.yaml",
        nodes=_vertical_nodes()[:-1],
    )
    config_path = _write_config(tmp_path / "project/configs/agent_world/base.yaml")

    result = subprocess.run(
        [
            "uv",
            "run",
            "--project",
            str(Path.cwd()),
            "python",
            "-m",
            "awmx.cli",
            "run",
            str(workflow_path),
            "--config",
            str(config_path),
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "requires exactly one node of type verification.reward_record" in result.stderr
    assert not (tmp_path / "project/outputs").exists()


def test_awmx_run_records_workflow_failed_after_verifier_error(tmp_path: Path):
    project_root = tmp_path / "project"
    workflow_path = _write_workflow(
        project_root / "configs/agent_world/workflows/failing_verifier.yaml",
        nodes=_vertical_nodes(verifier_ref="force_failure"),
    )
    config_path = _write_config(project_root / "configs/agent_world/base.yaml")

    result = subprocess.run(
        [
            "uv",
            "run",
            "--project",
            str(Path.cwd()),
            "python",
            "-m",
            "awmx.cli",
            "run",
            str(workflow_path),
            "--config",
            str(config_path),
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "forced verifier failure" in result.stderr
    run_dirs = list((project_root / "outputs/agent_world/runs").iterdir())
    assert len(run_dirs) == 1
    events = _read_jsonl(run_dirs[0] / "events.jsonl")
    assert events[-1]["event"] == "workflow_failed"
    assert events[-1]["payload"]["stage"] == "verification"
    assert events[-1]["payload"]["exception"]["type"] == "RuntimeError"
    assert "forced verifier failure" in events[-1]["payload"]["exception"]["message"]
