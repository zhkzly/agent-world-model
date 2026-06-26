from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
import yaml

from awmx.artifacts.schemas import RunSpec
from awmx.harness.trace import EventLogger, TraceLogger, create_run_directory


def _artifact_payload(**overrides):
    payload = {
        "id": "artifact.demo",
        "version": "0.1.0",
        "created_at": "2026-06-27T00:00:00Z",
        "source": {"kind": "fixture", "uri": "tests/awmx/test_trace.py"},
        "metadata": {"suite": "foundation"},
    }
    payload.update(overrides)
    return payload


def _run_spec(**overrides) -> RunSpec:
    run_id = overrides.pop("id", "run.demo")
    payload = {
        "workflow_id": "workflow.vertical_slice",
        "environment_id": "environment.ticketing",
        "task_id": "task.ticketing.close_stale",
        "runner": {"type": "scripted", "config_ref": "configs/agent_world/runners/scripted.yaml"},
        "budgets": {"max_steps": 8},
    }
    payload.update(overrides)
    return RunSpec(**_artifact_payload(id=run_id), **payload)


def test_create_run_directory_writes_required_foundation_artifacts(tmp_path: Path):
    run_dir = create_run_directory(tmp_path / "outputs/agent_world/runs", _run_spec())

    assert run_dir.path == tmp_path / "outputs/agent_world/runs" / "run.demo"
    assert (run_dir.path / "run.yaml").exists()
    assert (run_dir.path / "events.jsonl").exists()
    assert (run_dir.path / "trace.jsonl").exists()
    assert (run_dir.path / "logs").is_dir()

    run_payload = yaml.safe_load((run_dir.path / "run.yaml").read_text(encoding="utf-8"))
    assert run_payload["id"] == "run.demo"
    assert run_payload["runner"]["type"] == "scripted"


def test_create_run_directory_rejects_path_like_run_ids(tmp_path: Path):
    run_spec = _run_spec(id="../escape")

    with pytest.raises(Exception, match="path|separator|traversal"):
        create_run_directory(tmp_path / "outputs/agent_world/runs", run_spec)

    assert not (tmp_path / "outputs" / "escape").exists()


def test_create_run_directory_rejects_existing_run_id(tmp_path: Path):
    runs_root = tmp_path / "outputs/agent_world/runs"
    create_run_directory(runs_root, _run_spec())

    with pytest.raises(FileExistsError):
        create_run_directory(runs_root, _run_spec(task_id="task.changed"))


def test_event_and_trace_loggers_append_jsonl_records(tmp_path: Path):
    run_dir = create_run_directory(tmp_path / "outputs/agent_world/runs", _run_spec())
    events = EventLogger(run_dir.events_path)
    traces = TraceLogger(run_dir.trace_path)

    events.append(
        {
            "timestamp": "2026-06-27T00:00:00Z",
            "run_id": "run.demo",
            "node_id": "check_environment",
            "status": "planned",
        }
    )
    events.append(
        {
            "timestamp": "2026-06-27T00:00:01Z",
            "run_id": "run.demo",
            "node_id": "check_environment",
            "status": "skipped",
        }
    )
    traces.append(
        {
            "id": "trace.run_demo.0001",
            "version": "0.1.0",
            "created_at": "2026-06-27T00:00:02Z",
            "source": {"kind": "fixture", "uri": "tests/awmx/test_trace.py"},
            "metadata": {"suite": "foundation"},
            "run_id": "run.demo",
            "sequence": 1,
            "event_type": "observation",
            "actor": "scripted",
            "action": {"kind": "tool_call", "tool_id": "tool.ticketing.update_ticket"},
            "observation": {"status": "ok"},
            "evidence": {"stdout_path": "logs/step-0001.stdout"},
        }
    )

    event_lines = run_dir.events_path.read_text(encoding="utf-8").splitlines()
    trace_lines = run_dir.trace_path.read_text(encoding="utf-8").splitlines()

    assert [json.loads(line)["status"] for line in event_lines] == ["planned", "skipped"]
    assert json.loads(trace_lines[0])["sequence"] == 1


def test_create_run_cli_scaffolds_foundation_run_directory(tmp_path: Path):
    project_root = tmp_path / "project"
    config_path = project_root / "configs" / "agent_world" / "base.yaml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        yaml.safe_dump(
            {
                "id": "config.agent_world.base",
                "version": "0.1.0",
                "created_at": "2026-06-27T00:00:00Z",
                "source": {"kind": "fixture", "uri": str(config_path)},
                "metadata": {"suite": "foundation"},
                "paths": {
                    "config_root": "configs/agent_world",
                    "output_root": "outputs/agent_world",
                },
                "policies": {},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    subprocess.run(
        [
            "uv",
            "run",
            "--project",
            str(Path.cwd()),
            "python",
            "-m",
            "awmx.cli",
            "create-run",
            str(config_path),
            "--run-id",
            "run.cli_demo",
            "--workflow-id",
            "workflow.vertical_slice",
            "--environment-id",
            "environment.ticketing",
            "--task-id",
            "task.ticketing.close_stale",
            "--runner-type",
            "scripted",
        ],
        check=True,
        cwd=project_root,
    )

    run_root = project_root / "outputs/agent_world/runs" / "run.cli_demo"
    assert (run_root / "run.yaml").exists()
    assert (run_root / "events.jsonl").exists()
    assert (run_root / "trace.jsonl").exists()
    assert (run_root / "logs").is_dir()


def test_create_run_cli_uses_config_root_when_called_from_another_cwd(tmp_path: Path):
    project_root = tmp_path / "project"
    call_cwd = tmp_path / "caller"
    call_cwd.mkdir()
    config_path = project_root / "configs" / "agent_world" / "base.yaml"
    config_path.parent.mkdir(parents=True)
    config_path.write_text(
        yaml.safe_dump(
            {
                "id": "config.agent_world.base",
                "version": "0.1.0",
                "created_at": "2026-06-27T00:00:00Z",
                "source": {"kind": "fixture", "uri": str(config_path)},
                "metadata": {"suite": "foundation"},
                "paths": {
                    "config_root": "configs/agent_world",
                    "output_root": "outputs/agent_world",
                },
                "policies": {},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    subprocess.run(
        [
            "uv",
            "run",
            "--project",
            str(Path.cwd()),
            "python",
            "-m",
            "awmx.cli",
            "create-run",
            str(config_path),
            "--run-id",
            "run.other_cwd",
            "--workflow-id",
            "workflow.vertical_slice",
            "--environment-id",
            "environment.ticketing",
            "--task-id",
            "task.ticketing.close_stale",
            "--runner-type",
            "scripted",
        ],
        check=True,
        cwd=call_cwd,
    )

    assert (project_root / "outputs/agent_world/runs/run.other_cwd/run.yaml").exists()
    assert not (call_cwd / "outputs").exists()


def test_validate_config_uses_config_root_when_called_from_another_cwd(tmp_path: Path):
    project_root = tmp_path / "project"
    call_cwd = tmp_path / "caller"
    call_cwd.mkdir()
    config_path = project_root / "configs" / "agent_world" / "base.yaml"
    workflow_path = project_root / "configs" / "agent_world" / "workflows" / "vertical_slice.yaml"
    workflow_path.parent.mkdir(parents=True)
    workflow_path.write_text(
        yaml.safe_dump(
            {
                "id": "workflow.test",
                "version": "0.1.0",
                "created_at": "2026-06-27T00:00:00Z",
                "source": {"kind": "fixture", "uri": str(workflow_path)},
                "metadata": {"suite": "foundation"},
                "nodes": [],
                "budgets": {},
                "gates": {},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    config_path.write_text(
        yaml.safe_dump(
            {
                "id": "config.agent_world.base",
                "version": "0.1.0",
                "created_at": "2026-06-27T00:00:00Z",
                "source": {"kind": "fixture", "uri": str(config_path)},
                "metadata": {"suite": "foundation"},
                "paths": {
                    "config_root": "configs/agent_world",
                    "output_root": "outputs/agent_world",
                },
                "defaults": {"workflow": "configs/agent_world/workflows/vertical_slice.yaml"},
                "policies": {},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
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
            "validate-config",
            str(config_path),
        ],
        check=True,
        cwd=call_cwd,
        stdout=subprocess.PIPE,
        text=True,
    )

    assert json.loads(result.stdout)["workflow_id"] == "workflow.test"


@pytest.mark.parametrize("bad_id", ["../escape", "/tmp/escape", "run..demo"])
def test_create_run_cli_rejects_path_like_run_ids(tmp_path: Path, bad_id: str):
    config_path = tmp_path / "base.yaml"
    config_path.write_text(
        yaml.safe_dump(
            {
                "id": "config.agent_world.base",
                "version": "0.1.0",
                "created_at": "2026-06-27T00:00:00Z",
                "source": {"kind": "fixture", "uri": str(config_path)},
                "metadata": {"suite": "foundation"},
                "paths": {
                    "config_root": "configs/agent_world",
                    "output_root": "outputs/agent_world",
                },
                "policies": {},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
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
            "create-run",
            str(config_path),
            "--run-id",
            bad_id,
            "--workflow-id",
            "workflow.vertical_slice",
            "--environment-id",
            "environment.ticketing",
            "--task-id",
            "task.ticketing.close_stale",
            "--runner-type",
            "scripted",
        ],
        check=False,
        cwd=tmp_path,
        stderr=subprocess.PIPE,
        text=True,
    )

    assert result.returncode != 0
    assert not (tmp_path / "escape").exists()
