"""Cross-process cancellation proof for the real invocation-audit command path."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path


def _wait_for_worker_lifecycle(state_root: Path, process: subprocess.Popen[str]) -> None:
    """Wait only for the test process to boot and emit a safe worker fact."""

    deadline = time.monotonic() + 15
    attempts = state_root / "invocation-control" / "attempts"
    while time.monotonic() < deadline:
        records = tuple(attempts.glob("*.json")) if attempts.is_dir() else ()
        if records:
            payload = json.loads(records[0].read_text(encoding="utf-8"))
            if payload["last_local_phase"] in {
                "worker_spawned",
                "payload_dispatched",
                "sdk_session_open",
                "parent_waiting",
            }:
                return
        if process.poll() is not None:
            stdout, stderr = process.communicate()
            raise AssertionError(
                "invocation-audit subprocess exited before its controlled worker started: "
                f"stdout={stdout!r}, stderr={stderr!r}"
            )
        time.sleep(0.02)
    process.send_signal(signal.SIGINT)
    stdout, stderr = process.communicate(timeout=15)
    raise AssertionError(
        "invocation-audit subprocess did not reach its real worker lifecycle: "
        f"stdout={stdout!r}, stderr={stderr!r}"
    )


def test_cli_interrupt_terminalizes_real_audit_and_physical_attempt(tmp_path: Path) -> None:
    """SIGINT cannot leave either the audit report or its owned turn running."""

    state_root = tmp_path / "state"
    config_path = tmp_path / "foundry.toml"
    config_path.write_text(
        "\n".join(
            (
                f'state_root = "{state_root}"',
                "",
                "[agent]",
                'model = "audit-blocking-model"',
                'api_key_environment = "AGENT_WORLD_TEST_AUDIT_KEY"',
                'openai_base_url_environment = "OPENAI_BASE_URL"',
                "",
                "[research]",
                'provider = "bing_rss"',
                "",
            )
        ),
        encoding="utf-8",
    )
    repository = Path(__file__).resolve().parents[2]
    runner = repository / "tests" / "agent_world" / "fixtures" / (
        "run_invocation_audit_with_blocking_worker.py"
    )
    worker = repository / "tests" / "agent_world" / "fixtures" / "blocking_codex_worker.py"
    environment = dict(os.environ)
    environment.update(
        {
            "AGENT_WORLD_TEST_AUDIT_KEY": "audit-process-secret",
            "OPENAI_BASE_URL": "https://audit-process.invalid/v1",
            "AGENT_WORLD_TEST_BLOCKING_WORKER": str(worker),
        }
    )
    process = subprocess.Popen(  # noqa: S603 - fixed Python test fixture
        (
            sys.executable,
            str(runner),
            "--config",
            str(config_path),
            "invocation-audit",
            "--lane",
            "codex_challenger_solver",
        ),
        cwd=repository,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        _wait_for_worker_lifecycle(state_root, process)
        process.send_signal(signal.SIGINT)
        stdout, stderr = process.communicate(timeout=15)
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=15)

    assert process.returncode == 130
    assert stdout == ""
    assert '"code":"interrupted"' in stderr
    report = json.loads((state_root / "invocation-audit.json").read_text(encoding="utf-8"))
    assert report["status"] == "interrupted"
    assert report["lanes"][0]["status"] == "interrupted"
    assert report["lanes"][0]["failure_code"] == "owner_process_interrupted"
    attempt_paths = tuple((state_root / "invocation-control" / "attempts").glob("*.json"))
    assert len(attempt_paths) == 1
    attempt = json.loads(attempt_paths[0].read_text(encoding="utf-8"))
    assert attempt["status"] == "settled"
    assert attempt["terminal"] == {
        "status": "cancelled",
        "code": "owner_cancelled",
        "retryable": False,
    }
    serialized = json.dumps({"report": report, "attempt": attempt}, sort_keys=True)
    assert "audit-process-secret" not in serialized
    assert "audit-process.invalid" not in serialized
