from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from agent_world.artifact_store import ArtifactStore
from agent_world.control.telemetry import TelemetryStore
from agent_world.judge import (
    EnvironmentJudge,
    LaunchContract,
    RuntimeProcessCrashed,
    RuntimeRequestTimeout,
    RuntimeSupervisor,
)
from agent_world.judge.service import (
    _runtime_protocol_failure_record,
    _RuntimeContractFailure,
)
from agent_world.observability import MAX_STDERR_TAIL_BYTES, runtime_subprocess_scene


def _candidate() -> SimpleNamespace:
    return SimpleNamespace(
        runtime=SimpleNamespace(argv=(".venv/bin/python", "-m", "candidate.runtime"))
    )


def test_runtime_subprocess_scene_keeps_only_a_16kib_tail_and_hashes_canaries() -> None:
    canary = "phase-one-secret-canary"
    scene = runtime_subprocess_scene(
        operation="handshake",
        exit_code=17,
        stderr=("prefix\n" + ("x" * MAX_STDERR_TAIL_BYTES) + canary),
        launch_argv=(".venv/bin/python", "-m", canary),
        known_secret_canaries=(canary,),
    )

    assert scene.operation == "handshake"
    assert scene.exit_code == 17
    assert scene.stderr_truncated
    assert scene.stderr_tail.startswith("sha256:")
    assert canary not in scene.stderr_tail
    assert scene.launch_argv[-1].startswith("sha256:")
    assert scene.text_redacted


def test_runtime_failure_records_match_the_actual_exception_type() -> None:
    candidate = _candidate()
    crash = RuntimeProcessCrashed(
        "runtime_process_crashed",
        "runtime exited without a response",
        details={"exit_code": 9, "stderr": "Traceback\nRuntimeError: broken"},
    )
    crash_record, _ = _runtime_protocol_failure_record(crash, candidate=candidate)
    assert crash_record["exit_code"] == 9
    assert crash_record["stderr"] == "Traceback\nRuntimeError: broken"
    assert crash_record["launch_argv"] == list(candidate.runtime.argv)
    assert "timeout_seconds" not in crash_record
    assert "mismatch_paths" not in crash_record

    timeout = RuntimeRequestTimeout(
        "runtime_request_timeout",
        "runtime handshake request timed out",
        details={"timeout_seconds": 3.5},
    )
    timeout_record, _ = _runtime_protocol_failure_record(timeout, candidate=candidate)
    assert timeout_record["timeout_seconds"] == 3.5
    assert "exit_code" not in timeout_record
    assert "stderr" not in timeout_record
    assert "launch_argv" not in timeout_record

    contract = _RuntimeContractFailure(("tools[book_room].input_schema",))
    contract_record, _ = _runtime_protocol_failure_record(contract, candidate=candidate)
    assert contract_record["mismatch_paths"] == ["tools[book_room].input_schema"]
    assert "exit_code" not in contract_record
    assert "stderr" not in contract_record
    assert "launch_argv" not in contract_record


def test_runtime_supervisor_emits_scene_and_ignores_projection_failure(tmp_path) -> None:
    emitted = []
    supervisor = RuntimeSupervisor(
        tmp_path,
        LaunchContract(argv=("python", "-c", "pass")),
        visible_workspace_paths=("runtime.py",),
        on_subprocess_scene=emitted.append,
    )
    supervisor._process = SimpleNamespace(returncode=23)  # noqa: SLF001
    supervisor._stderr_bytes = b"fatal runtime error"  # noqa: SLF001

    error = supervisor._crashed_error("runtime exited", operation="handshake")  # noqa: SLF001

    assert error.details["exit_code"] == 23
    assert len(emitted) == 1
    assert emitted[0].operation == "handshake"
    assert emitted[0].exit_code == 23

    blocked = RuntimeSupervisor(
        tmp_path,
        LaunchContract(argv=("python", "-c", "pass")),
        visible_workspace_paths=("runtime.py",),
        on_subprocess_scene=lambda _scene: (_ for _ in ()).throw(RuntimeError("telemetry down")),
    )
    assert blocked._crashed_error("runtime exited").code == "runtime_process_crashed"  # noqa: SLF001


def test_judge_persists_a_runtime_subprocess_scene_as_tier_b(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    writer = store.issue_writer(
        producer="judge",
        allowed_artifact_types=("judge.evaluation_evidence",),
    )
    scene = runtime_subprocess_scene(
        operation="handshake",
        exit_code=1,
        stderr="candidate failed before response",
        launch_argv=(".venv/bin/python", "-m", "candidate.runtime"),
    )

    with TelemetryStore(tmp_path / "telemetry") as telemetry:
        judge = EnvironmentJudge(artifact_store=writer, telemetry=telemetry)
        judge._record_runtime_subprocess_scene("phase-one-run", scene)  # noqa: SLF001
        events = telemetry.inspect_trace("phase-one-run")["events"]

    assert len(events) == 1
    assert events[0]["event_type"] == "runtime_subprocess_scene"
    payload = json.loads(events[0]["payload_json"])
    assert payload["exit_code"] == 1
    assert payload["stderr_tail"] == "candidate failed before response"
    assert json.loads(payload["launch_argv_json"]) == [
        ".venv/bin/python",
        "-m",
        "candidate.runtime",
    ]
