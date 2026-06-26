from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import yaml

from awmx.artifacts.schemas import WorkflowSpec
from awmx.workflow.nodes import NODE_TYPE_REGISTRY
from awmx.workflow.spec import topological_order, validate_workflow_spec


@dataclass(frozen=True)
class WorkflowDryRunResult:
    run_id: str
    run_dir: Path
    events_path: Path
    node_statuses: dict[str, str]


class WorkflowDryRunRunner:
    def __init__(self, output_root: Path | str = Path("outputs/agent_world")) -> None:
        self.output_root = Path(output_root)

    def run(self, workflow: WorkflowSpec, workflow_path: Path) -> WorkflowDryRunResult:
        validate_workflow_spec(workflow)

        run_id = self._make_run_id(workflow.id)
        run_dir = self.output_root / "runs" / run_id
        run_dir.mkdir(parents=True, exist_ok=False)
        events_path = run_dir / "events.jsonl"

        ordered_nodes = topological_order(workflow)
        node_statuses: dict[str, str] = {}
        with events_path.open("w", encoding="utf-8") as handle:
            for sequence, node in enumerate(ordered_nodes, start=1):
                status, reason = self._resolve_node_status(node.id, node.node_type, node.needs, node_statuses)
                node_statuses[node.id] = status
                event = {
                    "sequence": sequence,
                    "timestamp": _utc_now(),
                    "mode": "dry_run",
                    "workflow_id": workflow.id,
                    "workflow_path": str(workflow_path),
                    "node_id": node.id,
                    "node_type": node.node_type,
                    "needs": node.needs,
                    "status": status,
                    "reason": reason,
                }
                handle.write(json.dumps(event, sort_keys=True) + "\n")

        self._write_run_manifest(run_dir / "run.yaml", workflow, workflow_path, run_id, node_statuses)
        return WorkflowDryRunResult(
            run_id=run_id,
            run_dir=run_dir,
            events_path=events_path,
            node_statuses=node_statuses,
        )

    def _resolve_node_status(
        self,
        node_id: str,
        node_type: str,
        dependencies: list[str],
        prior_statuses: dict[str, str],
    ) -> tuple[str, str | None]:
        blocked_dependencies = [
            dependency
            for dependency in dependencies
            if prior_statuses.get(dependency) in {"blocked", "skipped"}
        ]
        if blocked_dependencies:
            reason = f"upstream nodes not plannable in dry-run: {', '.join(blocked_dependencies)}"
            return "skipped", reason

        behavior = NODE_TYPE_REGISTRY[node_type].dry_run_behavior
        if behavior == "planned":
            return "planned", None
        if behavior == "blocked":
            return "blocked", "dry-run does not execute runtime or verifier nodes"
        raise ValueError(f"unsupported dry-run behavior for node {node_id}: {behavior}")

    def _make_run_id(self, workflow_id: str) -> str:
        safe_workflow_id = workflow_id.replace(".", "_")
        return f"{safe_workflow_id}_dry_run_{uuid4().hex[:8]}"

    def _write_run_manifest(
        self,
        path: Path,
        workflow: WorkflowSpec,
        workflow_path: Path,
        run_id: str,
        node_statuses: dict[str, str],
    ) -> None:
        payload = {
            "run_id": run_id,
            "mode": "dry_run",
            "workflow_id": workflow.id,
            "workflow_path": str(workflow_path),
            "created_at": _utc_now(),
            "node_statuses": node_statuses,
        }
        with path.open("w", encoding="utf-8") as handle:
            yaml.safe_dump(payload, handle, sort_keys=True)


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
