from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from awmx.artifacts.schemas import RunSpec, TaskSpec, ValidationError, VerifierSpec, WorkflowNodeSpec, WorkflowSpec
from awmx.config import load_agent_world_config, resolve_datasets_root, resolve_runs_root
from awmx.harness.permissions import PermissionGate
from awmx.harness.trace import create_run_directory
from awmx.rollout.base import RolloutSession
from awmx.rollout.scripted import ScriptedRunner
from awmx.training.export import export_rl_dataset
from awmx.verification.base import DeterministicVerifier
from awmx.verification.rewards import write_reward_record
from awmx.workflow.spec import topological_order, validate_workflow_spec


@dataclass(frozen=True)
class WorkflowRunResult:
    run_id: str
    run_dir: Path
    events_path: Path
    trace_path: Path
    reward_path: Path
    dataset_path: Path


class ScriptedVerticalSliceExecutor:
    def __init__(self, *, config_path: Path | str) -> None:
        self.config_path = Path(config_path)
        self.config = load_agent_world_config(self.config_path)
        self.runs_root = resolve_runs_root(self.config, self.config_path)
        self.datasets_root = resolve_datasets_root(self.config, self.config_path)

    def run(self, workflow: WorkflowSpec, *, workflow_path: Path | str) -> WorkflowRunResult:
        validate_workflow_spec(workflow)
        ordered_nodes = topological_order(workflow)
        self._validate_vertical_slice_shape(ordered_nodes)
        workflow_path = Path(workflow_path)
        run_id = self._make_run_id(workflow.id)
        task = self._task_spec()
        run_spec = self._run_spec(run_id=run_id, workflow=workflow, task=task, workflow_path=workflow_path)
        run_dir = create_run_directory(self.runs_root, run_spec)
        session = RolloutSession(
            run_spec=run_spec,
            task=task,
            permission_gate=PermissionGate(
                allowed_action_kinds={"message", "write_file"},
                writable_roots=[run_dir.path],
            ),
            output_dir=run_dir.path,
        )

        self._record_workflow_started(session, workflow, workflow_path)
        try:
            reward_path: Path | None = None
            dataset_path: Path | None = None
            for node in ordered_nodes:
                if node.node_type in {"awm.import_fixture", "awm.check_environment"}:
                    self._complete_planning_node(session, node)
                elif node.node_type == "rollout.scripted":
                    ScriptedRunner(steps=self._scripted_steps(run_dir.path)).run(session)
                    session.record_event(
                        "node_completed",
                        {"node_id": node.id, "node_type": node.node_type},
                    )
                elif node.node_type == "verification.deterministic":
                    reward_path = self._run_verification_node(
                        session=session,
                        node=node,
                        run_spec=run_spec,
                        task=task,
                        run_dir=run_dir.path,
                    )
                elif node.node_type == "verification.reward_record":
                    if reward_path is None:
                        raise ValidationError("reward record node requires a completed verifier node")
                    session.record_event(
                        "reward_recorded",
                        {
                            "node_id": node.id,
                            "reward_path": str(reward_path),
                            "reward_id": f"reward.{run_id}",
                        },
                    )
                    dataset_path = self._export_dataset(
                        session=session,
                        run_spec=run_spec,
                        task=task,
                        run_dir=run_dir.path,
                        reward_path=reward_path,
                    )
                else:
                    raise ValidationError(f"unsupported executable node type: {node.node_type}")
            if reward_path is None or dataset_path is None:
                raise ValidationError("workflow did not produce reward and dataset artifacts")
        except Exception as exc:
            self._record_workflow_failed(session, stage=self._stage_for_exception(exc), exc=exc)
            raise

        return WorkflowRunResult(
            run_id=run_id,
            run_dir=run_dir.path,
            events_path=run_dir.events_path,
            trace_path=run_dir.trace_path,
            reward_path=reward_path,
            dataset_path=dataset_path,
        )

    def _validate_vertical_slice_shape(self, nodes: list[WorkflowNodeSpec]) -> None:
        required_counts = {
            "awm.import_fixture": 1,
            "awm.check_environment": 1,
            "rollout.scripted": 1,
            "verification.deterministic": 1,
            "verification.reward_record": 1,
        }
        counts = {node_type: 0 for node_type in required_counts}
        for node in nodes:
            if node.node_type not in required_counts:
                raise ValidationError(f"unsupported node type for scripted vertical slice: {node.node_type}")
            counts[node.node_type] += 1
        for node_type, expected_count in required_counts.items():
            if counts[node_type] != expected_count:
                raise ValidationError(f"scripted vertical slice requires exactly one node of type {node_type}")

    def _record_workflow_started(
        self,
        session: RolloutSession,
        workflow: WorkflowSpec,
        workflow_path: Path,
    ) -> None:
        session.record_event(
            "workflow_started",
            {
                "workflow_id": workflow.id,
                "workflow_path": str(workflow_path),
                "node_order": [node.id for node in topological_order(workflow)],
            },
        )

    def _complete_planning_node(self, session: RolloutSession, node: WorkflowNodeSpec) -> None:
        session.record_event(
            "node_completed",
            {
                "node_id": node.id,
                "node_type": node.node_type,
                "mode": "scripted_demo",
            },
        )

    def _run_verification_node(
        self,
        *,
        session: RolloutSession,
        node: WorkflowNodeSpec,
        run_spec: RunSpec,
        task: TaskSpec,
        run_dir: Path,
    ) -> Path:
        if node.config.get("verifier_ref") == "force_failure":
            raise RuntimeError("forced verifier failure")
        reward = self._verifier().verify(run_spec=run_spec, task=task, output_dir=run_dir)
        reward_path = write_reward_record(reward, run_dir / "reward.json")
        session.record_event(
            "verification_completed",
            {
                "node_id": node.id,
                "verifier_id": reward.verifier_id,
                "passed": reward.passed,
                "score": reward.score,
            },
        )
        return reward_path

    def _export_dataset(
        self,
        *,
        session: RolloutSession,
        run_spec: RunSpec,
        task: TaskSpec,
        run_dir: Path,
        reward_path: Path,
    ) -> Path:
        dataset_path = export_rl_dataset(
            run_spec=run_spec,
            task=task,
            trace_path=run_dir / "trace.jsonl",
            reward_path=reward_path,
            dataset_root=self.datasets_root / "rl",
        )
        session.record_event("dataset_exported", {"dataset_path": str(dataset_path)})
        session.record_event("workflow_completed", {"workflow_id": run_spec.workflow_id, "status": "ok"})
        return dataset_path

    def _record_workflow_failed(self, session: RolloutSession, *, stage: str, exc: Exception) -> None:
        session.record_event(
            "workflow_failed",
            {
                "stage": stage,
                "exception": {
                    "type": type(exc).__name__,
                    "message": str(exc),
                },
                "reason": str(exc),
            },
        )

    @staticmethod
    def _stage_for_exception(exc: Exception) -> str:
        message = str(exc).lower()
        if "verifier" in message or "verification" in message:
            return "verification"
        if "export" in message or "dataset" in message:
            return "export"
        return "workflow"

    def _run_spec(self, *, run_id: str, workflow: WorkflowSpec, task: TaskSpec, workflow_path: Path) -> RunSpec:
        return RunSpec(
            id=run_id,
            version="0.1.0",
            created_at=_utc_now(),
            source={"kind": "workflow", "uri": str(workflow_path)},
            metadata={"mode": "scripted_vertical_slice"},
            workflow_id=workflow.id,
            environment_id="environment.demo.scripted",
            task_id=task.id,
            runner={"type": "scripted", "config": {"mode": "demo"}},
            budgets={"max_steps": workflow.budgets.get("max_rollout_steps", 8)},
        )

    def _task_spec(self) -> TaskSpec:
        return TaskSpec(
            id="task.demo.write_completion",
            version="0.1.0",
            created_at=_utc_now(),
            source={"kind": "fixture", "uri": "awmx/workflow/executor.py"},
            metadata={"mode": "scripted_vertical_slice"},
            scenario_id="scenario.demo",
            prompt="Write a completion marker file containing done.",
            success_criteria=["workspace/done.txt exists and contains done"],
            allowed_tool_ids=["tool.demo.write_file"],
        )

    def _verifier(self) -> DeterministicVerifier:
        verifier = VerifierSpec(
            id="verifier.demo.completion_file",
            version="0.1.0",
            created_at=_utc_now(),
            source={"kind": "verifier", "uri": "awmx/workflow/executor.py"},
            metadata={"mode": "scripted_vertical_slice"},
            target_task_id="task.demo.write_completion",
            verifier_type="deterministic_function",
            deterministic=True,
            inputs={"expected_file": "workspace/done.txt"},
            reward_mapping={"passed": 1.0, "failed": 0.0},
        )
        return DeterministicVerifier(verifier_spec=verifier, verify_fn=_verify_completion_file)

    @staticmethod
    def _scripted_steps(run_dir: Path) -> list[dict[str, object]]:
        return [
            {
                "action": {"kind": "message", "content": "Starting scripted completion task."},
                "observation": {"status": "ok", "message": "task_loaded"},
                "evidence": {"note": "scripted_demo_start"},
            },
            {
                "action": {
                    "kind": "write_file",
                    "path": str(run_dir / "workspace" / "done.txt"),
                    "content": "done\n",
                },
                "observation": {"status": "ok", "file_written": "workspace/done.txt"},
                "evidence": {"artifact": "completion_marker"},
            },
        ]

    @staticmethod
    def _make_run_id(workflow_id: str) -> str:
        return f"{workflow_id.replace('.', '_')}_run_{uuid4().hex[:8]}"


def _verify_completion_file(ctx) -> dict[str, object]:
    target = ctx.output_dir / "workspace" / "done.txt"
    if not target.exists():
        return {
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
        }

    content = target.read_text(encoding="utf-8").strip()
    passed = content == "done"
    check = {
        "name": "completion_file",
        "passed": passed,
        "path": "workspace/done.txt",
        "evidence": {"content": content},
    }
    if not passed:
        check["failure_reason"] = "completion marker content did not match"
    result: dict[str, object] = {
        "passed": passed,
        "checks": [check],
    }
    if not passed:
        result["failure_reason"] = "completion marker content did not match"
    return result


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def result_to_json(result: WorkflowRunResult, *, workflow_id: str) -> str:
    return json.dumps(
        {
            "status": "ok",
            "workflow_id": workflow_id,
            "run_id": result.run_id,
            "run_dir": str(result.run_dir),
            "events_path": str(result.events_path),
            "trace_path": str(result.trace_path),
            "reward_path": str(result.reward_path),
            "dataset_path": str(result.dataset_path),
        },
        sort_keys=True,
    )
