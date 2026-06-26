from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from awmx.adapters.cli import CliAdapter, CliCommandSpec
from awmx.artifacts.schemas import ValidationError
from awmx.harness.permissions import PermissionGate


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _adapter(tmp_path: Path, **overrides) -> CliAdapter:
    kwargs = {
        "allowed_commands": {sys.executable},
        "permission_gate": PermissionGate(
            allowed_action_kinds={"command"},
            writable_roots=[tmp_path],
        ),
        "logs_dir": tmp_path / "logs",
        "events_path": tmp_path / "events.jsonl",
        "stdout_limit": 12,
        "stderr_limit": 12,
    }
    kwargs.update(overrides)
    return CliAdapter(**kwargs)


def test_cli_adapter_rejects_unallowlisted_command_before_execution(tmp_path: Path):
    adapter = _adapter(tmp_path, allowed_commands={"definitely-not-python"})
    spec = CliCommandSpec(
        command=[sys.executable, "-c", "print('should not run')"],
        cwd=tmp_path,
        timeout_s=1.0,
    )

    with pytest.raises(ValidationError, match="allowlist"):
        adapter.run(spec)

    assert not (tmp_path / "logs").exists()
    events = _read_jsonl(tmp_path / "events.jsonl")
    assert events[0]["event"] == "cli_command_rejected"
    assert events[0]["payload"]["reason"].startswith("command is not allowlisted")


def test_cli_adapter_rejects_shell_string_commands(tmp_path: Path):
    adapter = _adapter(tmp_path)
    spec = CliCommandSpec(
        command=f"{sys.executable} -c \"print('shell')\"",
        cwd=tmp_path,
        timeout_s=1.0,
    )

    with pytest.raises(ValidationError, match="command must be a list"):
        adapter.run(spec)


def test_cli_adapter_captures_raw_logs_and_truncated_summaries(tmp_path: Path):
    adapter = _adapter(tmp_path, stdout_limit=10, stderr_limit=8)
    spec = CliCommandSpec(
        command=[
            sys.executable,
            "-c",
            "import sys; print('x' * 24); print('e' * 18, file=sys.stderr)",
        ],
        cwd=tmp_path,
        timeout_s=2.0,
    )

    result = adapter.run(spec)

    assert result.exit_code == 0
    assert result.timed_out is False
    assert result.stdout_summary == "x" * 10 + "...[truncated]"
    assert result.stderr_summary == "e" * 8 + "...[truncated]"
    assert Path(result.stdout_path).read_text(encoding="utf-8") == "x" * 24 + "\n"
    assert Path(result.stderr_path).read_text(encoding="utf-8") == "e" * 18 + "\n"
    assert result.to_observation()["exit_code"] == 0
    assert result.to_evidence()["command_audit"]["stdout_path"] == result.stdout_path

    events = _read_jsonl(tmp_path / "events.jsonl")
    assert [row["event"] for row in events] == ["cli_command_started", "cli_command_completed"]
    assert events[1]["payload"]["stdout_path"] == result.stdout_path


def test_cli_adapter_writes_raw_non_utf8_logs_and_replacement_summaries(tmp_path: Path):
    adapter = _adapter(tmp_path, stdout_limit=20, stderr_limit=20)
    spec = CliCommandSpec(
        command=[
            sys.executable,
            "-c",
            "import sys; sys.stdout.buffer.write(b'raw\\xffout'); sys.stderr.buffer.write(b'err\\xferaw')",
        ],
        cwd=tmp_path,
        timeout_s=2.0,
    )

    result = adapter.run(spec)

    assert result.exit_code == 0
    assert Path(result.stdout_path).read_bytes() == b"raw\xffout"
    assert Path(result.stderr_path).read_bytes() == b"err\xferaw"
    assert result.stdout_summary == "raw\ufffdout"
    assert result.stderr_summary == "err\ufffdraw"


def test_cli_adapter_timeout_records_failure_event(tmp_path: Path):
    adapter = _adapter(tmp_path)
    spec = CliCommandSpec(
        command=[sys.executable, "-c", "import time; time.sleep(2)"],
        cwd=tmp_path,
        timeout_s=0.1,
    )

    result = adapter.run(spec)

    assert result.exit_code is None
    assert result.timed_out is True
    assert result.failure_reason == "timeout"
    assert Path(result.stdout_path).exists()
    assert Path(result.stderr_path).exists()

    events = _read_jsonl(tmp_path / "events.jsonl")
    assert [row["event"] for row in events] == ["cli_command_started", "cli_command_failed"]
    assert events[1]["payload"]["reason"] == "timeout"
    assert events[1]["payload"]["timeout_s"] == 0.1


def test_cli_adapter_missing_allowlisted_executable_returns_failed_result(tmp_path: Path):
    missing = str(tmp_path / "missing-python")
    adapter = _adapter(tmp_path, allowed_commands={missing})
    spec = CliCommandSpec(
        command=[missing, "-c", "print('no')"],
        cwd=tmp_path,
        timeout_s=1.0,
    )

    result = adapter.run(spec)

    assert result.exit_code is None
    assert result.failure_reason == "exec_error"
    assert result.timed_out is False
    assert Path(result.stdout_path).read_bytes() == b""
    stderr_raw = Path(result.stderr_path).read_text(encoding="utf-8")
    assert "No such file" in stderr_raw or "no such file" in stderr_raw

    events = _read_jsonl(tmp_path / "events.jsonl")
    assert [row["event"] for row in events] == ["cli_command_started", "cli_command_failed"]
    assert events[1]["payload"]["reason"] == "exec_error"
    assert events[1]["payload"]["exception"]["type"] == "FileNotFoundError"


def test_cli_adapter_permission_denied_executable_returns_failed_result(tmp_path: Path):
    script = tmp_path / "not-executable"
    script.write_text("#!/bin/sh\necho no\n", encoding="utf-8")
    script.chmod(0o600)
    adapter = _adapter(tmp_path, allowed_commands={str(script)})
    spec = CliCommandSpec(
        command=[str(script)],
        cwd=tmp_path,
        timeout_s=1.0,
    )

    result = adapter.run(spec)

    assert result.exit_code is None
    assert result.failure_reason == "exec_error"
    assert result.timed_out is False
    assert Path(result.stdout_path).read_bytes() == b""
    stderr_raw = Path(result.stderr_path).read_text(encoding="utf-8")
    assert "Permission" in stderr_raw or "permission" in stderr_raw

    events = _read_jsonl(tmp_path / "events.jsonl")
    assert [row["event"] for row in events] == ["cli_command_started", "cli_command_failed"]
    assert events[1]["payload"]["reason"] == "exec_error"
    assert events[1]["payload"]["exception"]["type"] == "PermissionError"


def test_cli_adapter_controls_cwd_and_env(tmp_path: Path):
    adapter = _adapter(tmp_path, allowed_env_keys={"AWMX_TEST_FLAG"})
    spec = CliCommandSpec(
        command=[
            sys.executable,
            "-c",
            "import os, pathlib; print(pathlib.Path.cwd()); print(os.environ['AWMX_TEST_FLAG'])",
        ],
        cwd=tmp_path,
        env={"AWMX_TEST_FLAG": "enabled"},
        timeout_s=2.0,
    )

    result = adapter.run(spec)

    assert Path(result.stdout_path).read_text(encoding="utf-8").splitlines() == [
        str(tmp_path),
        "enabled",
    ]
    assert result.cwd == str(tmp_path.resolve())
    assert result.env == {"AWMX_TEST_FLAG": "enabled"}

    rejected = CliCommandSpec(
        command=[sys.executable, "-c", "print('no')"],
        cwd=tmp_path,
        env={"UNAPPROVED": "1"},
        timeout_s=1.0,
    )
    with pytest.raises(ValidationError, match="env key"):
        adapter.run(rejected)


def test_cli_adapter_uses_permission_gate_for_cwd(tmp_path: Path):
    adapter = _adapter(tmp_path)
    outside = tmp_path.parent / "outside"
    outside.mkdir(exist_ok=True)
    spec = CliCommandSpec(
        command=[sys.executable, "-c", "print('blocked')"],
        cwd=outside,
        timeout_s=1.0,
    )

    with pytest.raises(ValidationError, match="permission denied"):
        adapter.run(spec)

    events = _read_jsonl(tmp_path / "events.jsonl")
    assert events[0]["event"] == "cli_command_rejected"
    assert events[0]["payload"]["permission"]["allowed"] is False


def test_cli_adapter_requires_logs_dir_inside_writable_root(tmp_path: Path):
    outside_logs = tmp_path.parent / "outside-cli-logs"
    adapter = _adapter(tmp_path, logs_dir=outside_logs)
    spec = CliCommandSpec(
        command=[sys.executable, "-c", "print('blocked')"],
        cwd=tmp_path,
        timeout_s=1.0,
    )

    with pytest.raises(ValidationError, match="logs_dir"):
        adapter.run(spec)

    assert not outside_logs.exists()
    events = _read_jsonl(tmp_path / "events.jsonl")
    assert events[0]["event"] == "cli_command_rejected"
