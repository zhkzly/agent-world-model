from __future__ import annotations

import json
from pathlib import Path

from awmx.artifacts.schemas import RewardRecord, RunSpec, TaskSpec, TraceRecord, VerifierSpec
from awmx.artifacts.schemas import ValidationError
from awmx.harness.permissions import PermissionGate
from awmx.rollout.base import RolloutSession
from awmx.rollout.scripted import ScriptedRunner
from awmx.training.export import export_rl_dataset
from awmx.verification.base import DeterministicVerifier
from awmx.verification.rewards import write_reward_record


def _artifact_payload(**overrides):
    payload = {
        "id": "artifact.demo",
        "version": "0.1.0",
        "created_at": "2026-06-27T00:00:00Z",
        "source": {"kind": "fixture", "uri": "tests/awmx/test_rewards.py"},
        "metadata": {"suite": "rewards"},
    }
    payload.update(overrides)
    return payload


def _run_spec(tmp_path: Path) -> RunSpec:
    return RunSpec(
        **_artifact_payload(id="run.demo"),
        workflow_id="workflow.vertical_slice",
        environment_id="environment.demo",
        task_id="task.demo",
        runner={"type": "scripted", "config": {}, "output_dir": str(tmp_path)},
        budgets={"max_steps": 8},
    )


def _task() -> TaskSpec:
    return TaskSpec(
        **_artifact_payload(id="task.demo"),
        scenario_id="scenario.demo",
        prompt="Write a completion file.",
        success_criteria=["done.txt exists and contains done"],
        allowed_tool_ids=["tool.demo.write"],
    )


def _verifier_spec() -> VerifierSpec:
    return VerifierSpec(
        **_artifact_payload(id="verifier.demo"),
        target_task_id="task.demo",
        verifier_type="deterministic_function",
        deterministic=True,
        inputs={"expected_file": "workspace/done.txt"},
        reward_mapping={"passed": 1.0, "failed": 0.0},
    )


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_deterministic_verifier_success_and_reward_record(tmp_path: Path):
    run_spec = _run_spec(tmp_path)
    session = RolloutSession(
        run_spec=run_spec,
        task=_task(),
        permission_gate=PermissionGate(
            allowed_action_kinds={"write_file"},
            writable_roots=[tmp_path],
        ),
        output_dir=tmp_path,
    )

    ScriptedRunner(
        steps=[
            {
                "action": {
                    "kind": "write_file",
                    "path": str(tmp_path / "workspace" / "done.txt"),
                    "content": "done\n",
                },
                "observation": {"status": "ok"},
                "evidence": {"artifact": "completion_marker"},
            }
        ]
    ).run(session)

    verifier = DeterministicVerifier(
        verifier_spec=_verifier_spec(),
        verify_fn=lambda ctx: {
            "passed": (ctx.output_dir / "workspace" / "done.txt").read_text(encoding="utf-8").strip() == "done",
            "checks": [
                {
                    "name": "completion_file",
                    "passed": True,
                    "path": "workspace/done.txt",
                }
            ],
        },
    )

    reward = verifier.verify(run_spec=run_spec, task=_task(), output_dir=tmp_path)
    reward_path = write_reward_record(reward, tmp_path / "reward.json")

    payload = _read_json(reward_path)
    assert reward.passed is True
    assert reward.score == 1.0
    assert reward.source["uri"] == _verifier_spec().source["uri"]
    assert reward.source["uri"] != str(reward_path)
    assert payload["verifier_id"] == "verifier.demo"
    assert payload["source"]["uri"] == _verifier_spec().source["uri"]
    assert payload["evidence"]["checks"][0]["name"] == "completion_file"


def test_deterministic_verifier_failure_uses_verifier_mapping_not_runner_output(tmp_path: Path):
    verifier = DeterministicVerifier(
        verifier_spec=_verifier_spec(),
        verify_fn=lambda ctx: {
            "passed": False,
            "checks": [
                {
                    "name": "completion_file",
                    "passed": False,
                    "path": "workspace/done.txt",
                    "failure_reason": "missing completion marker",
                }
            ],
            "failure_reason": "missing completion marker",
            "runner_final_answer": "claimed success",
        },
    )

    reward = verifier.verify(run_spec=_run_spec(tmp_path), task=_task(), output_dir=tmp_path)

    assert reward.passed is False
    assert reward.score == 0.0
    assert reward.failure_reason == "missing completion marker"
    assert "runner_final_answer" not in reward.evidence


def test_deterministic_verifier_rejects_target_task_mismatch(tmp_path: Path):
    verifier_spec = VerifierSpec(
        **_artifact_payload(id="verifier.other"),
        target_task_id="task.other",
        verifier_type="deterministic_function",
        deterministic=True,
        inputs={},
        reward_mapping={"passed": 1.0, "failed": 0.0},
    )
    verifier = DeterministicVerifier(
        verifier_spec=verifier_spec,
        verify_fn=lambda ctx: {
            "passed": True,
            "checks": [{"name": "noop", "passed": True, "detail": "not reached"}],
        },
    )

    try:
        verifier.verify(run_spec=_run_spec(tmp_path), task=_task(), output_dir=tmp_path)
    except ValidationError as exc:
        assert "target_task_id" in str(exc)
    else:
        raise AssertionError("expected ValidationError")


def test_deterministic_verifier_rejects_run_task_mismatch(tmp_path: Path):
    other_task = TaskSpec(
        **_artifact_payload(id="task.other"),
        scenario_id="scenario.demo",
        prompt="Different task.",
        success_criteria=["not used"],
        allowed_tool_ids=[],
    )
    verifier_spec = VerifierSpec(
        **_artifact_payload(id="verifier.other"),
        target_task_id=other_task.id,
        verifier_type="deterministic_function",
        deterministic=True,
        inputs={},
        reward_mapping={"passed": 1.0, "failed": 0.0},
    )
    verifier = DeterministicVerifier(
        verifier_spec=verifier_spec,
        verify_fn=lambda ctx: {
            "passed": True,
            "checks": [{"name": "noop", "passed": True, "detail": "not reached"}],
        },
    )

    try:
        verifier.verify(run_spec=_run_spec(tmp_path), task=other_task, output_dir=tmp_path)
    except ValidationError as exc:
        assert "run_spec.task_id" in str(exc)
    else:
        raise AssertionError("expected ValidationError")


def test_deterministic_verifier_rejects_non_deterministic_spec(tmp_path: Path):
    verifier_spec = VerifierSpec(
        **_artifact_payload(id="verifier.nondeterministic"),
        target_task_id="task.demo",
        verifier_type="llm_judge",
        deterministic=False,
        inputs={},
        reward_mapping={"passed": 1.0, "failed": 0.0},
    )
    verifier = DeterministicVerifier(
        verifier_spec=verifier_spec,
        verify_fn=lambda ctx: {
            "passed": True,
            "checks": [{"name": "noop", "passed": True, "detail": "not reached"}],
        },
    )

    try:
        verifier.verify(run_spec=_run_spec(tmp_path), task=_task(), output_dir=tmp_path)
    except ValidationError as exc:
        assert "deterministic" in str(exc)
    else:
        raise AssertionError("expected ValidationError")


def test_reward_record_rejects_unstructured_verifier_outputs(tmp_path: Path):
    try:
        RewardRecord(
            **_artifact_payload(id="reward.unstructured", source={"kind": "verifier", "uri": "reward.json"}),
            run_id="run.demo",
            task_id="task.demo",
            verifier_id="verifier.demo",
            passed=True,
            score=1.0,
            evidence={"verifier_outputs": {"ok": True}},
            failure_reason=None,
        )
    except ValidationError as exc:
        assert "structured checks" in str(exc)
    else:
        raise AssertionError("expected ValidationError")


def test_rl_dataset_export_reads_trace_and_reward_artifacts(tmp_path: Path):
    run_spec = _run_spec(tmp_path)
    task = _task()
    session = RolloutSession(
        run_spec=run_spec,
        task=task,
        permission_gate=PermissionGate(
            allowed_action_kinds={"message", "write_file"},
            writable_roots=[tmp_path],
        ),
        output_dir=tmp_path,
    )

    ScriptedRunner(
        steps=[
            {
                "action": {"kind": "message", "content": "starting"},
                "observation": {"status": "ok"},
                "evidence": {"note": "prelude"},
            },
            {
                "action": {
                    "kind": "write_file",
                    "path": str(tmp_path / "workspace" / "done.txt"),
                    "content": "done\n",
                },
                "observation": {"status": "ok"},
                "evidence": {"artifact": "completion_marker"},
            },
        ]
    ).run(session)

    reward = RewardRecord(
        **_artifact_payload(id="reward.demo", source={"kind": "verifier", "uri": "reward.json"}),
        run_id=run_spec.id,
        task_id=task.id,
        verifier_id="verifier.demo",
        passed=True,
        score=1.0,
        evidence={"checks": [{"name": "completion_file", "passed": True, "path": "workspace/done.txt"}]},
        failure_reason=None,
    )
    write_reward_record(reward, tmp_path / "reward.json")

    export_path = export_rl_dataset(
        run_spec=run_spec,
        task=task,
        trace_path=tmp_path / "trace.jsonl",
        reward_path=tmp_path / "reward.json",
        dataset_root=tmp_path / "datasets" / "rl",
    )

    rows = _read_jsonl(export_path)
    assert export_path == tmp_path / "datasets" / "rl" / "run.demo.jsonl"
    assert rows[0]["run_id"] == "run.demo"
    assert rows[0]["reward"]["score"] == 1.0
    assert rows[0]["trace"][1]["action"]["kind"] == "write_file"
    assert rows[0]["task"]["prompt"] == "Write a completion file."


def test_rl_dataset_export_rejects_mismatched_trace_run(tmp_path: Path):
    run_spec = _run_spec(tmp_path)
    trace = TraceRecord(
        **_artifact_payload(id="trace.other.0001"),
        run_id="run.other",
        sequence=1,
        event_type="runner_step",
        actor="scripted",
        action={"kind": "message"},
        observation={"status": "ok"},
        evidence={"permission": {"allowed": True, "kind": "message"}},
    )
    (tmp_path / "trace.jsonl").write_text(json.dumps(trace.to_dict()) + "\n", encoding="utf-8")
    reward = RewardRecord(
        **_artifact_payload(id="reward.demo", source={"kind": "verifier", "uri": "verifier.py"}),
        run_id=run_spec.id,
        task_id=run_spec.task_id,
        verifier_id="verifier.demo",
        passed=True,
        score=1.0,
        evidence={"checks": [{"name": "completion_file", "passed": True, "path": "workspace/done.txt"}]},
        failure_reason=None,
    )
    write_reward_record(reward, tmp_path / "reward.json")

    try:
        export_rl_dataset(
            run_spec=run_spec,
            task=_task(),
            trace_path=tmp_path / "trace.jsonl",
            reward_path=tmp_path / "reward.json",
            dataset_root=tmp_path / "datasets" / "rl",
        )
    except ValidationError as exc:
        assert "trace.run_id" in str(exc)
    else:
        raise AssertionError("expected ValidationError")


def test_rl_dataset_export_rejects_mismatched_reward_or_task(tmp_path: Path):
    run_spec = _run_spec(tmp_path)
    (tmp_path / "trace.jsonl").write_text("", encoding="utf-8")
    reward = RewardRecord(
        **_artifact_payload(id="reward.other", source={"kind": "verifier", "uri": "verifier.py"}),
        run_id="run.other",
        task_id=run_spec.task_id,
        verifier_id="verifier.demo",
        passed=True,
        score=1.0,
        evidence={"checks": [{"name": "completion_file", "passed": True, "path": "workspace/done.txt"}]},
        failure_reason=None,
    )
    write_reward_record(reward, tmp_path / "reward.json")

    try:
        export_rl_dataset(
            run_spec=run_spec,
            task=_task(),
            trace_path=tmp_path / "trace.jsonl",
            reward_path=tmp_path / "reward.json",
            dataset_root=tmp_path / "datasets" / "rl",
        )
    except ValidationError as exc:
        assert "reward.run_id" in str(exc)
    else:
        raise AssertionError("expected ValidationError")

    reward = RewardRecord(
        **_artifact_payload(id="reward.task_mismatch", source={"kind": "verifier", "uri": "verifier.py"}),
        run_id=run_spec.id,
        task_id="task.other",
        verifier_id="verifier.demo",
        passed=True,
        score=1.0,
        evidence={"checks": [{"name": "completion_file", "passed": True, "path": "workspace/done.txt"}]},
        failure_reason=None,
    )
    write_reward_record(reward, tmp_path / "reward.json")

    try:
        export_rl_dataset(
            run_spec=run_spec,
            task=_task(),
            trace_path=tmp_path / "trace.jsonl",
            reward_path=tmp_path / "reward.json",
            dataset_root=tmp_path / "datasets" / "rl",
        )
    except ValidationError as exc:
        assert "reward.task_id" in str(exc)
    else:
        raise AssertionError("expected ValidationError")
