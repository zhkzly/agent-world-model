from __future__ import annotations

from dataclasses import asdict, dataclass, fields as dataclass_fields
from datetime import datetime
from typing import Any, ClassVar


class ValidationError(ValueError):
    """Raised when an artifact does not satisfy the minimal contract."""


def _require_non_empty_string(value: Any, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{field_name} must be a non-empty string")


def _require_mapping(value: Any, field_name: str) -> None:
    if not isinstance(value, dict):
        raise ValidationError(f"{field_name} must be a mapping")


def _require_list(value: Any, field_name: str) -> None:
    if not isinstance(value, list):
        raise ValidationError(f"{field_name} must be a list")


def _require_string_list(value: Any, field_name: str) -> None:
    _require_list(value, field_name)
    if not all(isinstance(item, str) for item in value):
        raise ValidationError(f"{field_name} must contain only strings")


def _require_iso_datetime(value: Any, field_name: str) -> None:
    _require_non_empty_string(value, field_name)
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValidationError(f"{field_name} must be an ISO-8601 datetime") from exc


def _contains_key(value: Any, key: str) -> bool:
    if isinstance(value, dict):
        return any(item_key == key or _contains_key(item_value, key) for item_key, item_value in value.items())
    if isinstance(value, list):
        return any(_contains_key(item, key) for item in value)
    return False


@dataclass
class BaseArtifact:
    id: str
    version: str
    created_at: str
    source: dict[str, Any]
    metadata: dict[str, Any]

    artifact_type: ClassVar[str] = "base"

    def __post_init__(self) -> None:
        _require_non_empty_string(self.id, "id")
        _require_non_empty_string(self.version, "version")
        _require_iso_datetime(self.created_at, "created_at")
        _require_mapping(self.source, "source")
        _require_non_empty_string(self.source.get("kind"), "source.kind")
        _require_mapping(self.metadata, "metadata")

    @classmethod
    def fields(cls) -> set[str]:
        return {field.name for field in dataclass_fields(cls)}

    @classmethod
    def from_dict(cls, payload: dict[str, Any]):
        return cls(**payload)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ScenarioSpec(BaseArtifact):
    name: str
    description: str

    artifact_type: ClassVar[str] = "scenario"

    def __post_init__(self) -> None:
        super().__post_init__()
        _require_non_empty_string(self.name, "name")
        _require_non_empty_string(self.description, "description")


@dataclass
class TaskSpec(BaseArtifact):
    scenario_id: str
    prompt: str
    success_criteria: list[str]
    allowed_tool_ids: list[str]

    artifact_type: ClassVar[str] = "task"

    def __post_init__(self) -> None:
        super().__post_init__()
        _require_non_empty_string(self.scenario_id, "scenario_id")
        _require_non_empty_string(self.prompt, "prompt")
        _require_string_list(self.success_criteria, "success_criteria")
        _require_string_list(self.allowed_tool_ids, "allowed_tool_ids")


@dataclass
class EnvironmentSpec(BaseArtifact):
    scenario_id: str
    state_backend: dict[str, Any]
    runtime: dict[str, Any]
    tool_ids: list[str]

    artifact_type: ClassVar[str] = "environment"

    def __post_init__(self) -> None:
        super().__post_init__()
        _require_non_empty_string(self.scenario_id, "scenario_id")
        _require_mapping(self.state_backend, "state_backend")
        _require_non_empty_string(self.state_backend.get("kind"), "state_backend.kind")
        _require_mapping(self.runtime, "runtime")
        _require_non_empty_string(self.runtime.get("kind"), "runtime.kind")
        _require_string_list(self.tool_ids, "tool_ids")


@dataclass
class ToolSpec(BaseArtifact):
    name: str
    adapter_type: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    side_effects: list[str]
    permissions: dict[str, Any]

    artifact_type: ClassVar[str] = "tool"

    def __post_init__(self) -> None:
        super().__post_init__()
        _require_non_empty_string(self.name, "name")
        _require_non_empty_string(self.adapter_type, "adapter_type")
        _require_mapping(self.input_schema, "input_schema")
        _require_mapping(self.output_schema, "output_schema")
        _require_string_list(self.side_effects, "side_effects")
        _require_mapping(self.permissions, "permissions")


@dataclass
class VerifierSpec(BaseArtifact):
    target_task_id: str
    verifier_type: str
    deterministic: bool
    inputs: dict[str, Any]
    reward_mapping: dict[str, Any]

    artifact_type: ClassVar[str] = "verifier"

    def __post_init__(self) -> None:
        super().__post_init__()
        _require_non_empty_string(self.target_task_id, "target_task_id")
        _require_non_empty_string(self.verifier_type, "verifier_type")
        if not isinstance(self.deterministic, bool):
            raise ValidationError("deterministic must be a boolean")
        _require_mapping(self.inputs, "inputs")
        _require_mapping(self.reward_mapping, "reward_mapping")


@dataclass
class WorkflowNodeSpec:
    id: str
    node_type: str
    needs: list[str]
    config: dict[str, Any]

    def __post_init__(self) -> None:
        _require_non_empty_string(self.id, "node.id")
        _require_non_empty_string(self.node_type, "node.node_type")
        _require_string_list(self.needs, "node.needs")
        _require_mapping(self.config, "node.config")

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "WorkflowNodeSpec":
        return cls(**payload)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class WorkflowSpec(BaseArtifact):
    nodes: list[WorkflowNodeSpec]
    budgets: dict[str, Any]
    gates: dict[str, Any]

    artifact_type: ClassVar[str] = "workflow"

    def __post_init__(self) -> None:
        super().__post_init__()
        converted_nodes = [
            node if isinstance(node, WorkflowNodeSpec) else WorkflowNodeSpec.from_dict(node)
            for node in self.nodes
        ]
        self.nodes = converted_nodes
        _require_list(self.nodes, "nodes")
        _require_mapping(self.budgets, "budgets")
        _require_mapping(self.gates, "gates")
        self._validate_node_references()

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "WorkflowSpec":
        return cls(**payload)

    def _validate_node_references(self) -> None:
        node_ids = [node.id for node in self.nodes]
        if len(node_ids) != len(set(node_ids)):
            raise ValidationError("workflow nodes must have unique ids")
        known = set(node_ids)
        for node in self.nodes:
            unknown = [dependency for dependency in node.needs if dependency not in known]
            if unknown:
                raise ValidationError(f"node {node.id} has unknown dependencies: {unknown}")


@dataclass
class RunSpec(BaseArtifact):
    workflow_id: str
    environment_id: str
    task_id: str
    runner: dict[str, Any]
    budgets: dict[str, Any]

    artifact_type: ClassVar[str] = "run"

    def __post_init__(self) -> None:
        super().__post_init__()
        _require_non_empty_string(self.workflow_id, "workflow_id")
        _require_non_empty_string(self.environment_id, "environment_id")
        _require_non_empty_string(self.task_id, "task_id")
        _require_mapping(self.runner, "runner")
        _require_non_empty_string(self.runner.get("type"), "runner.type")
        _require_mapping(self.budgets, "budgets")


@dataclass
class TraceRecord(BaseArtifact):
    run_id: str
    sequence: int
    event_type: str
    actor: str
    action: dict[str, Any]
    observation: dict[str, Any]
    evidence: dict[str, Any]

    artifact_type: ClassVar[str] = "trace"

    def __post_init__(self) -> None:
        super().__post_init__()
        _require_non_empty_string(self.run_id, "run_id")
        if not isinstance(self.sequence, int) or self.sequence < 1:
            raise ValidationError("sequence must be a positive integer")
        _require_non_empty_string(self.event_type, "event_type")
        _require_non_empty_string(self.actor, "actor")
        _require_mapping(self.action, "action")
        _require_mapping(self.observation, "observation")
        _require_mapping(self.evidence, "evidence")
        if self.event_type == "runner_step":
            permission = self.evidence.get("permission")
            _require_mapping(permission, "evidence.permission")
            if permission.get("allowed") is not True:
                raise ValidationError("runner_step trace records require an allowed permission decision")
            _require_non_empty_string(permission.get("kind"), "evidence.permission.kind")


@dataclass
class RewardRecord(BaseArtifact):
    run_id: str
    task_id: str
    verifier_id: str
    passed: bool
    score: float
    evidence: dict[str, Any]
    failure_reason: str | None

    artifact_type: ClassVar[str] = "reward"

    def __post_init__(self) -> None:
        super().__post_init__()
        _require_non_empty_string(self.run_id, "run_id")
        _require_non_empty_string(self.task_id, "task_id")
        _require_non_empty_string(self.verifier_id, "verifier_id")
        if not isinstance(self.passed, bool):
            raise ValidationError("passed must be a boolean")
        if isinstance(self.score, bool) or not isinstance(self.score, int | float) or not 0.0 <= float(self.score) <= 1.0:
            raise ValidationError("score must be a number between 0.0 and 1.0")
        _require_mapping(self.evidence, "evidence")
        if self.source.get("kind") != "verifier":
            raise ValidationError("reward source.kind must be verifier")
        _require_non_empty_string(self.source.get("uri"), "source.uri")
        if _contains_key(self.evidence, "runner_final_answer"):
            raise ValidationError("reward evidence must not include runner_final_answer")
        check_results = self._validate_verifier_evidence()
        if self.passed and not all(check_results):
            raise ValidationError("passed reward must not include failed checks")
        if not self.passed and all(check_results):
            raise ValidationError("failed reward must include at least one failed check")
        if not self.passed and not self.failure_reason:
            raise ValidationError("failed rewards must include failure_reason")
        if self.failure_reason is not None and not isinstance(self.failure_reason, str):
            raise ValidationError("failure_reason must be null or a string")

    def _validate_verifier_evidence(self) -> list[bool]:
        has_checks = "checks" in self.evidence
        has_verifier_outputs = "verifier_outputs" in self.evidence
        if has_checks and has_verifier_outputs:
            raise ValidationError("mixed verifier evidence is not allowed")

        checks = self.evidence.get("checks")
        verifier_outputs = self.evidence.get("verifier_outputs")
        if checks is not None:
            return self._validate_checks(checks)
        if verifier_outputs is not None:
            _require_mapping(verifier_outputs, "evidence.verifier_outputs")
            if "runner_final_answer" in verifier_outputs:
                raise ValidationError("verifier_outputs must not include runner_final_answer")
            checks = verifier_outputs.get("checks")
            if checks is None:
                raise ValidationError("evidence.verifier_outputs must contain structured checks")
            return self._validate_checks(checks)
        raise ValidationError("evidence must contain verifier evidence from checks or verifier_outputs")

    def _validate_checks(self, checks: Any) -> list[bool]:
        _require_list(checks, "evidence.checks")
        if not checks:
            raise ValidationError("evidence.checks must not be empty")
        results = []
        for check in checks:
            _require_mapping(check, "evidence.checks[]")
            _require_non_empty_string(check.get("name"), "evidence.checks[].name")
            if not isinstance(check.get("passed"), bool):
                raise ValidationError("evidence.checks[].passed must be a boolean")
            results.append(check["passed"])
            if "runner_final_answer" in check:
                raise ValidationError("reward checks must not include runner_final_answer")
            if not any(key in check for key in ("path", "evidence", "detail", "details")):
                raise ValidationError("evidence.checks[] must include a path, evidence, detail, or details reference")
            if check["passed"] is False and not (check.get("failure_reason") or self.failure_reason):
                raise ValidationError("failed checks must include failure_reason")
        return results


SCHEMA_REGISTRY: dict[str, type[BaseArtifact]] = {
    ScenarioSpec.artifact_type: ScenarioSpec,
    TaskSpec.artifact_type: TaskSpec,
    EnvironmentSpec.artifact_type: EnvironmentSpec,
    ToolSpec.artifact_type: ToolSpec,
    VerifierSpec.artifact_type: VerifierSpec,
    WorkflowSpec.artifact_type: WorkflowSpec,
    RunSpec.artifact_type: RunSpec,
    TraceRecord.artifact_type: TraceRecord,
    RewardRecord.artifact_type: RewardRecord,
}
