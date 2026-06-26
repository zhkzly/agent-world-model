from __future__ import annotations

import json
from pathlib import Path

import pytest

from awmx.artifacts.schemas import RunSpec, TaskSpec, TraceRecord, ValidationError
from awmx.harness.permissions import PermissionGate
from awmx.rollout.base import RolloutSession
from awmx.rollout.codex_sdk import FakeCodexBackend, FakeCodexRunner
from awmx.rollout.mini_swe import FakeMiniSweBackend, FakeMiniSweRunner
from awmx.rollout.scripted import ScriptedRunner


def _artifact_payload(**overrides):
    payload = {
        "id": "artifact.demo",
        "version": "0.1.0",
        "created_at": "2026-06-27T00:00:00Z",
        "source": {"kind": "fixture", "uri": "tests/awmx/test_rollout.py"},
        "metadata": {"suite": "rollout"},
    }
    payload.update(overrides)
    return payload


def _run_spec(tmp_path: Path, *, runner_type: str = "scripted", runner_config: dict | None = None) -> RunSpec:
    return RunSpec(
        **_artifact_payload(id="run.demo"),
        workflow_id="workflow.vertical_slice",
        environment_id="environment.demo",
        task_id="task.demo",
        runner={
            "type": runner_type,
            "config": runner_config or {},
            "output_dir": str(tmp_path),
        },
        budgets={"max_steps": 8},
    )


def _task() -> TaskSpec:
    return TaskSpec(
        **_artifact_payload(id="task.demo"),
        scenario_id="scenario.demo",
        prompt="Update the demo state.",
        success_criteria=["A completion marker is written."],
        allowed_tool_ids=["tool.demo.write"],
    )


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_scripted_runner_writes_canonical_trace_and_events(tmp_path: Path):
    run_spec = _run_spec(
        tmp_path,
        runner_config={
            "steps": [
                {
                    "action": {"kind": "message", "content": "Inspecting task"},
                    "observation": {"status": "ok", "message": "task_loaded"},
                    "evidence": {"note": "preflight"},
                },
                {
                    "action": {
                        "kind": "write_file",
                        "path": str(tmp_path / "workspace" / "done.txt"),
                        "content": "done\n",
                    },
                    "observation": {"status": "ok", "file_written": "done.txt"},
                    "evidence": {"artifact": "completion_marker"},
                },
            ]
        },
    )
    session = RolloutSession(
        run_spec=run_spec,
        task=_task(),
        permission_gate=PermissionGate(
            allowed_action_kinds={"message", "write_file"},
            writable_roots=[tmp_path],
        ),
        output_dir=tmp_path,
    )

    result = ScriptedRunner().run(session)

    trace_rows = _read_jsonl(tmp_path / "trace.jsonl")
    event_rows = _read_jsonl(tmp_path / "events.jsonl")

    assert result.final_output == {"status": "ok", "file_written": "done.txt"}
    assert [row["sequence"] for row in trace_rows] == [1, 2]
    assert [row["event_type"] for row in trace_rows] == ["runner_step", "runner_step"]
    assert trace_rows[1]["action"]["kind"] == "write_file"
    assert trace_rows[1]["evidence"]["permission"]["allowed"] is True
    assert [row["event"] for row in event_rows] == ["rollout_started", "step_completed", "step_completed", "rollout_completed"]
    assert (tmp_path / "workspace" / "done.txt").read_text(encoding="utf-8") == "done\n"


def test_fake_mini_swe_runner_maps_history_and_checks_permissions(tmp_path: Path):
    run_spec = _run_spec(tmp_path, runner_type="mini_swe")
    backend = FakeMiniSweBackend(
        history=[
            {
                "command": "echo ok",
                "cwd": str(tmp_path),
                "env": {"PATH": "/usr/bin"},
                "stdout": "ok\n",
                "stderr": "",
                "stdout_path": "logs/step-0001.stdout",
                "stderr_path": "logs/step-0001.stderr",
                "exit_code": 0,
                "duration_ms": 12,
            }
        ]
    )
    session = RolloutSession(
        run_spec=run_spec,
        task=_task(),
        permission_gate=PermissionGate(
            allowed_action_kinds={"command"},
            writable_roots=[tmp_path],
        ),
        output_dir=tmp_path,
    )

    result = FakeMiniSweRunner(backend=backend).run(session)

    assert result.final_output["history_length"] == 1
    trace = [TraceRecord.from_dict(row) for row in _read_jsonl(tmp_path / "trace.jsonl")]
    assert trace[0].action["kind"] == "command"
    assert trace[0].observation["exit_code"] == 0
    assert trace[0].observation["stdout_path"] == "logs/step-0001.stdout"
    assert trace[0].evidence["command_audit"]["env"] == {"PATH": "/usr/bin"}
    assert trace[0].evidence["command_audit"]["stdout_summary"] == "ok\n"
    assert trace[0].evidence["permission"]["allowed"] is True
    assert trace[0].evidence["permission"]["cwd"] == str(tmp_path.resolve())


def test_fake_codex_runner_maps_file_edits_and_test_results(tmp_path: Path):
    run_spec = _run_spec(tmp_path, runner_type="codex_sdk")
    backend = FakeCodexBackend(
        operations=[
            {
                "kind": "file_edit",
                "path": str(tmp_path / "workspace" / "report.txt"),
                "content": "patched\n",
            },
            {
                "kind": "test_result",
                "command": "uv run pytest tests/awmx/test_rollout.py",
                "exit_code": 0,
                "stdout": "1 passed",
                "stderr": "",
            },
        ],
        review_result={"passed": True, "summary": "artifacts mapped"},
    )
    session = RolloutSession(
        run_spec=run_spec,
        task=_task(),
        permission_gate=PermissionGate(
            allowed_action_kinds={"file_edit", "test_result"},
            writable_roots=[tmp_path],
        ),
        output_dir=tmp_path,
    )

    result = FakeCodexRunner(backend=backend).run(session)

    rows = _read_jsonl(tmp_path / "trace.jsonl")
    assert result.final_output["review"]["passed"] is True
    assert rows[0]["action"]["kind"] == "file_edit"
    assert rows[1]["action"]["kind"] == "test_result"
    assert rows[1]["observation"]["exit_code"] == 0
    assert rows[1]["evidence"]["permission"]["allowed"] is True
    assert (tmp_path / "workspace" / "report.txt").read_text(encoding="utf-8") == "patched\n"


def test_permission_gate_rejects_disallowed_actions(tmp_path: Path):
    run_spec = _run_spec(
        tmp_path,
        runner_config={
            "steps": [
                {
                    "action": {"kind": "command", "command": "rm -rf /"},
                    "observation": {"status": "blocked"},
                    "evidence": {"note": "should not run"},
                }
            ]
        },
    )
    session = RolloutSession(
        run_spec=run_spec,
        task=_task(),
        permission_gate=PermissionGate(allowed_action_kinds={"message"}),
        output_dir=tmp_path,
    )

    with pytest.raises(ValidationError, match="permission denied"):
        ScriptedRunner().run(session)

    events = _read_jsonl(tmp_path / "events.jsonl")
    assert [row["event"] for row in events] == ["rollout_started", "permission_denied", "rollout_failed"]
    assert events[1]["payload"]["permission"]["allowed"] is False
    assert (tmp_path / "trace.jsonl").read_text(encoding="utf-8") == ""


def test_path_actions_require_explicit_writable_roots(tmp_path: Path):
    run_spec = _run_spec(
        tmp_path,
        runner_config={
            "steps": [
                {
                    "action": {
                        "kind": "write_file",
                        "path": str(tmp_path / "workspace" / "done.txt"),
                        "content": "done\n",
                    },
                    "observation": {"status": "ok"},
                    "evidence": {},
                }
            ]
        },
    )
    session = RolloutSession(
        run_spec=run_spec,
        task=_task(),
        permission_gate=PermissionGate(allowed_action_kinds={"write_file"}),
        output_dir=tmp_path,
    )

    with pytest.raises(ValidationError, match="writable root"):
        ScriptedRunner().run(session)

    assert not (tmp_path / "workspace" / "done.txt").exists()


def test_fake_codex_runner_authorizes_before_file_edit(tmp_path: Path):
    outside_path = tmp_path.parent / "outside.txt"
    run_spec = _run_spec(tmp_path, runner_type="codex_sdk")
    backend = FakeCodexBackend(
        operations=[
            {
                "kind": "file_edit",
                "path": str(outside_path),
                "content": "should not be written\n",
            }
        ],
        review_result={"passed": False},
    )
    session = RolloutSession(
        run_spec=run_spec,
        task=_task(),
        permission_gate=PermissionGate(
            allowed_action_kinds={"file_edit"},
            writable_roots=[tmp_path],
        ),
        output_dir=tmp_path,
    )

    with pytest.raises(ValidationError, match="permission denied"):
        FakeCodexRunner(backend=backend).run(session)

    assert not outside_path.exists()
    events = _read_jsonl(tmp_path / "events.jsonl")
    assert events[1]["event"] == "permission_denied"
    assert events[1]["payload"]["permission"]["allowed"] is False


def test_fake_codex_file_edit_requires_writable_root(tmp_path: Path):
    target_path = tmp_path / "workspace" / "report.txt"
    run_spec = _run_spec(tmp_path, runner_type="codex_sdk")
    backend = FakeCodexBackend(
        operations=[
            {
                "kind": "file_edit",
                "path": str(target_path),
                "content": "should not be written\n",
            }
        ],
        review_result={"passed": False},
    )
    session = RolloutSession(
        run_spec=run_spec,
        task=_task(),
        permission_gate=PermissionGate(allowed_action_kinds={"file_edit"}),
        output_dir=tmp_path,
    )

    with pytest.raises(ValidationError, match="writable root"):
        FakeCodexRunner(backend=backend).run(session)

    assert not target_path.exists()


def test_fake_mini_swe_command_requires_writable_root_for_cwd(tmp_path: Path):
    run_spec = _run_spec(tmp_path, runner_type="mini_swe")
    backend = FakeMiniSweBackend(
        history=[
            {
                "command": "echo ok",
                "cwd": str(tmp_path),
                "exit_code": 0,
            }
        ]
    )
    session = RolloutSession(
        run_spec=run_spec,
        task=_task(),
        permission_gate=PermissionGate(allowed_action_kinds={"command"}),
        output_dir=tmp_path,
    )

    with pytest.raises(ValidationError, match="writable root"):
        FakeMiniSweRunner(backend=backend).run(session)

    events = _read_jsonl(tmp_path / "events.jsonl")
    assert events[1]["event"] == "permission_denied"
    assert events[1]["payload"]["permission"]["allowed"] is False
    assert (tmp_path / "trace.jsonl").read_text(encoding="utf-8") == ""


def test_fake_mini_swe_command_requires_cwd(tmp_path: Path):
    run_spec = _run_spec(tmp_path, runner_type="mini_swe")
    backend = FakeMiniSweBackend(history=[{"command": "echo ok", "exit_code": 0}])
    session = RolloutSession(
        run_spec=run_spec,
        task=_task(),
        permission_gate=PermissionGate(
            allowed_action_kinds={"command"},
            writable_roots=[tmp_path],
        ),
        output_dir=tmp_path,
    )

    with pytest.raises(ValidationError, match="cwd"):
        FakeMiniSweRunner(backend=backend).run(session)

    events = _read_jsonl(tmp_path / "events.jsonl")
    assert events[1]["event"] == "permission_denied"


def test_fake_mini_swe_command_rejects_none_cwd(tmp_path: Path):
    run_spec = _run_spec(tmp_path, runner_type="mini_swe")
    backend = FakeMiniSweBackend(history=[{"command": "echo ok", "cwd": None, "exit_code": 0}])
    session = RolloutSession(
        run_spec=run_spec,
        task=_task(),
        permission_gate=PermissionGate(
            allowed_action_kinds={"command"},
            writable_roots=[tmp_path],
        ),
        output_dir=tmp_path,
    )

    with pytest.raises(ValidationError, match="cwd"):
        FakeMiniSweRunner(backend=backend).run(session)


def test_fake_mini_swe_command_rejects_malformed_cwd_with_events(tmp_path: Path):
    run_spec = _run_spec(tmp_path, runner_type="mini_swe")
    backend = FakeMiniSweBackend(history=[{"command": "echo ok", "cwd": "bad\0cwd", "exit_code": 0}])
    session = RolloutSession(
        run_spec=run_spec,
        task=_task(),
        permission_gate=PermissionGate(
            allowed_action_kinds={"command"},
            writable_roots=[tmp_path],
        ),
        output_dir=tmp_path,
    )

    with pytest.raises(ValidationError, match="cwd"):
        FakeMiniSweRunner(backend=backend).run(session)

    events = _read_jsonl(tmp_path / "events.jsonl")
    assert [row["event"] for row in events] == ["rollout_started", "permission_denied", "rollout_failed"]
    assert events[1]["payload"]["permission"]["allowed"] is False


def test_fake_mini_swe_command_rejects_outside_paths(tmp_path: Path):
    run_spec = _run_spec(tmp_path, runner_type="mini_swe")
    backend = FakeMiniSweBackend(
        history=[
            {
                "command": "cat outside.txt",
                "cwd": str(tmp_path / "workspace"),
                "read_paths": [str(tmp_path.parent / "outside.txt")],
                "exit_code": 0,
            }
        ]
    )
    session = RolloutSession(
        run_spec=run_spec,
        task=_task(),
        permission_gate=PermissionGate(
            allowed_action_kinds={"command"},
            writable_roots=[tmp_path],
        ),
        output_dir=tmp_path,
    )

    with pytest.raises(ValidationError, match="permission denied"):
        FakeMiniSweRunner(backend=backend).run(session)


@pytest.mark.parametrize("field_name", ["read_paths", "write_paths"])
def test_fake_mini_swe_command_rejects_malformed_declared_paths_with_events(tmp_path: Path, field_name: str):
    run_spec = _run_spec(tmp_path, runner_type="mini_swe")
    backend = FakeMiniSweBackend(
        history=[
            {
                "command": "echo ok",
                "cwd": str(tmp_path),
                field_name: ["bad\0path"],
                "exit_code": 0,
            }
        ]
    )
    session = RolloutSession(
        run_spec=run_spec,
        task=_task(),
        permission_gate=PermissionGate(
            allowed_action_kinds={"command"},
            writable_roots=[tmp_path],
        ),
        output_dir=tmp_path,
    )

    with pytest.raises(ValidationError, match=field_name):
        FakeMiniSweRunner(backend=backend).run(session)

    events = _read_jsonl(tmp_path / "events.jsonl")
    assert [row["event"] for row in events] == ["rollout_started", "permission_denied", "rollout_failed"]
    assert events[1]["payload"]["permission"]["allowed"] is False


def test_scripted_write_file_requires_path(tmp_path: Path):
    run_spec = _run_spec(
        tmp_path,
        runner_config={
            "steps": [
                {
                    "action": {"kind": "write_file", "content": "done\n"},
                    "observation": {"status": "ok"},
                    "evidence": {},
                }
            ]
        },
    )
    session = RolloutSession(
        run_spec=run_spec,
        task=_task(),
        permission_gate=PermissionGate(
            allowed_action_kinds={"write_file"},
            writable_roots=[tmp_path],
        ),
        output_dir=tmp_path,
    )

    with pytest.raises(ValidationError, match="path"):
        ScriptedRunner().run(session)

    events = _read_jsonl(tmp_path / "events.jsonl")
    assert events[1]["event"] == "permission_denied"


def test_scripted_write_file_rejects_malformed_path_with_events(tmp_path: Path):
    run_spec = _run_spec(
        tmp_path,
        runner_config={
            "steps": [
                {
                    "action": {"kind": "write_file", "path": "bad\0path", "content": "done\n"},
                    "observation": {"status": "ok"},
                    "evidence": {},
                }
            ]
        },
    )
    session = RolloutSession(
        run_spec=run_spec,
        task=_task(),
        permission_gate=PermissionGate(
            allowed_action_kinds={"write_file"},
            writable_roots=[tmp_path],
        ),
        output_dir=tmp_path,
    )

    with pytest.raises(ValidationError, match="path"):
        ScriptedRunner().run(session)

    events = _read_jsonl(tmp_path / "events.jsonl")
    assert [row["event"] for row in events] == ["rollout_started", "permission_denied", "rollout_failed"]
    assert events[1]["payload"]["permission"]["allowed"] is False


def test_scripted_authorized_write_failure_records_failure_artifacts(tmp_path: Path):
    target_dir = tmp_path / "workspace"
    target_dir.mkdir()
    run_spec = _run_spec(
        tmp_path,
        runner_config={
            "steps": [
                {
                    "action": {"kind": "write_file", "path": str(target_dir), "content": "done\n"},
                    "observation": {"status": "ok"},
                    "evidence": {},
                }
            ]
        },
    )
    session = RolloutSession(
        run_spec=run_spec,
        task=_task(),
        permission_gate=PermissionGate(
            allowed_action_kinds={"write_file"},
            writable_roots=[tmp_path],
        ),
        output_dir=tmp_path,
    )

    with pytest.raises(ValidationError, match="runner action failed"):
        ScriptedRunner().run(session)

    events = _read_jsonl(tmp_path / "events.jsonl")
    assert [row["event"] for row in events] == ["rollout_started", "rollout_failed"]
    assert events[1]["payload"]["action"]["kind"] == "write_file"
    assert events[1]["payload"]["permission"]["allowed"] is True
    assert events[1]["payload"]["exception"]["type"] == "IsADirectoryError"

    trace_rows = _read_jsonl(tmp_path / "trace.jsonl")
    assert len(trace_rows) == 1
    assert trace_rows[0]["event_type"] == "runner_failure"
    assert trace_rows[0]["evidence"]["permission"]["allowed"] is True
    assert trace_rows[0]["evidence"]["exception"]["type"] == "IsADirectoryError"


def test_fake_codex_file_edit_requires_path(tmp_path: Path):
    run_spec = _run_spec(tmp_path, runner_type="codex_sdk")
    backend = FakeCodexBackend(
        operations=[{"kind": "file_edit", "content": "patched\n"}],
        review_result={"passed": False},
    )
    session = RolloutSession(
        run_spec=run_spec,
        task=_task(),
        permission_gate=PermissionGate(
            allowed_action_kinds={"file_edit"},
            writable_roots=[tmp_path],
        ),
        output_dir=tmp_path,
    )

    with pytest.raises(ValidationError, match="path"):
        FakeCodexRunner(backend=backend).run(session)

    events = _read_jsonl(tmp_path / "events.jsonl")
    assert events[1]["event"] == "permission_denied"


def test_fake_codex_authorized_file_edit_failure_records_failure_artifacts(tmp_path: Path):
    target_dir = tmp_path / "workspace"
    target_dir.mkdir()
    run_spec = _run_spec(tmp_path, runner_type="codex_sdk")
    backend = FakeCodexBackend(
        operations=[{"kind": "file_edit", "path": str(target_dir), "content": "patched\n"}],
        review_result={"passed": False},
    )
    session = RolloutSession(
        run_spec=run_spec,
        task=_task(),
        permission_gate=PermissionGate(
            allowed_action_kinds={"file_edit"},
            writable_roots=[tmp_path],
        ),
        output_dir=tmp_path,
    )

    with pytest.raises(ValidationError, match="runner action failed"):
        FakeCodexRunner(backend=backend).run(session)

    events = _read_jsonl(tmp_path / "events.jsonl")
    assert [row["event"] for row in events] == ["rollout_started", "rollout_failed"]
    assert events[1]["payload"]["action"]["kind"] == "file_edit"
    assert events[1]["payload"]["permission"]["allowed"] is True
    assert events[1]["payload"]["exception"]["type"] == "IsADirectoryError"

    trace_rows = _read_jsonl(tmp_path / "trace.jsonl")
    assert len(trace_rows) == 1
    assert trace_rows[0]["event_type"] == "runner_failure"
    assert trace_rows[0]["evidence"]["exception"]["type"] == "IsADirectoryError"


def test_zero_step_scripted_rollout_creates_trace_and_events_files(tmp_path: Path):
    (tmp_path / "trace.jsonl").write_text('{"stale": true}\n', encoding="utf-8")
    (tmp_path / "events.jsonl").write_text('{"event": "stale"}\n', encoding="utf-8")
    run_spec = _run_spec(tmp_path, runner_config={"steps": []})
    session = RolloutSession(
        run_spec=run_spec,
        task=_task(),
        permission_gate=PermissionGate(allowed_action_kinds={"message"}),
        output_dir=tmp_path,
    )

    result = ScriptedRunner().run(session)

    assert result.step_count == 0
    assert result.trace_path.exists()
    assert result.events_path.exists()
    assert result.trace_path.read_text(encoding="utf-8") == ""
    assert [row["event"] for row in _read_jsonl(result.events_path)] == ["rollout_started", "rollout_completed"]
