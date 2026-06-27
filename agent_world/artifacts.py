from __future__ import annotations

import copy
import datetime as dt
import hashlib
import json
import re
from pathlib import Path
from typing import Any

import yaml


COMMON_FIELDS = [
    "id",
    "version",
    "created_at",
    "source_stage",
    "inputs",
    "producer",
    "hash",
    "status",
]

ARTIFACT_REQUIRED_FIELDS: dict[str, list[str]] = {
    "NeedSpec": [
        "goal",
        "target_capabilities",
        "domain_seed",
        "expected_agent_behavior",
        "constraints",
        "preferred_surfaces",
        "out_of_scope",
        "human_confirmation_required",
    ],
    "SourceEvidenceIndex": [
        "sources",
        "extractable_objects",
        "mock_boundaries",
        "open_questions",
        "rejected_sources",
    ],
    "KnowledgePack": [
        "state_objects",
        "operations",
        "business_rules",
        "verifiable_fields",
        "uncertainties",
    ],
    "EnvironmentSpec": [
        "environment_id",
        "domain",
        "state_backend",
        "state_entities",
        "logical_tools",
        "permissions",
        "safety_boundaries",
        "mock_policy",
        "release_surfaces_allowed",
        "observability",
    ],
    "LogicalToolGraph": ["tools", "edges", "parameters", "forbidden_direct_access"],
    "TaskSet": ["tasks", "coverage", "rejected_candidates"],
    "SurfacePlan": ["bindings", "surface_status", "compatibility_notes"],
    "VerifierPlan": ["verifiers", "llm_judges"],
    "FeasibilityReport": [
        "status",
        "gate_results",
        "minimum_viable_surface",
        "minimum_viable_task_ids",
        "minimum_viable_verifier_ids",
        "implementation_blockers",
    ],
    "ImplementationRequest": [
        "request_id",
        "environment_id",
        "source_artifact_ids",
        "accepted_task_ids",
        "accepted_verifier_ids",
        "required_surface_ids",
        "package_layout_ref",
        "implementation_scope",
        "non_goals",
        "tdd_requirements",
        "launch_check_replay_commands",
        "review_record_refs",
    ],
    "EnvironmentPackagePlan": [
        "package_plan_id",
        "environment_id",
        "layout",
        "included_artifact_ids",
        "fixture_refs",
        "static_check_refs",
        "review_record_refs",
        "replay_plan_ref",
        "release_manifest_ref",
        "consumer_output_refs",
        "excluded_items",
    ],
    "ReleaseManifest": [
        "release_id",
        "environment_id",
        "version",
        "artifact_hashes",
        "package_layout",
        "task_index",
        "verifier_index",
        "surface_index",
        "fixture_index",
        "replay_contract",
        "consumer_outputs",
        "known_limits",
    ],
    "GateRecord": [
        "gate_record_id",
        "gate_id",
        "stage",
        "checked_artifact_ids",
        "evidence_refs",
        "failure_class",
        "recovery_suggestion",
    ],
    "ReviewRecord": [
        "review_id",
        "reviewed_artifact_ids",
        "source_of_truth_refs",
        "reviewer_ref",
        "review_type",
        "alignment_status",
        "drift_findings",
        "required_fixes",
        "waived_risks",
    ],
    "ReplayPlan": [
        "replay_plan_id",
        "environment_id",
        "seed_fixture_refs",
        "task_ids",
        "surface_binding_ids",
        "reset_steps",
        "execution_trace_inputs",
        "state_snapshot_points",
        "snapshot_hashes",
        "replay_commands",
        "execution_trace_schema",
        "verifier_ids",
        "expected_gate_ids",
        "determinism_notes",
        "known_nondeterminism",
    ],
    "ConsumerIndex": [
        "consumer_index_id",
        "release_id",
        "task_records_ref",
        "verifier_records_ref",
        "surface_index_ref",
        "reset_contract_ref",
        "trace_contract_ref",
        "result_record_schema",
        "adapter_notes",
    ],
    "AgentInvocationRecord": [
        "invocation_id",
        "stage",
        "node_purpose",
        "backend_kind",
        "backend_ref",
        "config_ref",
        "model_or_runtime",
        "instruction_ref",
        "input_artifact_ids",
        "allowed_tool_access",
        "permissions",
        "budget",
        "output_artifact_ids",
        "evidence_refs",
        "trace_ref",
        "failure_class",
        "recovery_suggestion",
    ],
    "AgentBackendConfig": [
        "backend_id",
        "backend_kind",
        "provider",
        "model",
        "base_url",
        "api_version",
        "auth",
        "command",
        "timeouts",
        "budgets",
        "permissions",
        "output_schema_ref",
        "redaction_policy",
    ],
}

SOURCE_KINDS = {
    "prd",
    "repo",
    "mcp_server",
    "cli_help",
    "api_docs",
    "sdk_docs",
    "database_schema",
    "http_service",
    "local_files",
    "awm_sample",
    "manual_note",
}
DEPENDENCY_TYPES = {"strong", "weak", "independent"}
PARAMETER_CLASSES = {"external", "internal", "optional"}
SURFACES = {"python", "cli", "http", "mcp"}
SURFACE_STATUSES = {"planned", "required_for_first_slice", "deferred", "rejected"}
VERIFIER_KINDS = {
    "state_query",
    "state_diff",
    "file_assertion",
    "command_assertion",
    "test_assertion",
    "api_assertion",
}
AGENT_BACKEND_KINDS = {
    "llm",
    "codex_sdk",
    "codex_cli",
    "process_agent",
    "search_agent",
    "mini_swe_agent",
    "deep_search",
    "manual",
    "mock",
    "custom",
}
AGENT_PROVIDERS = {
    "openai",
    "openai_compatible",
    "azure_openai",
    "codex",
    "local_process",
    "manual",
    "mock",
    "custom",
}
AGENT_NODE_PURPOSES = {
    "search",
    "extract",
    "synthesize",
    "review",
    "judge",
    "draft_implementation_request",
    "implement",
    "other",
}

ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/#-]*$")


class ArtifactValidationError(ValueError):
    """Raised when an artifact fails the frozen first-slice contract."""


def utc_now() -> str:
    return dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def artifact_hash(artifact: dict[str, Any]) -> str:
    payload = copy.deepcopy(artifact)
    payload.pop("hash", None)
    return hashlib.sha256(stable_json(payload).encode("utf-8")).hexdigest()


def make_artifact(
    artifact_type: str,
    *,
    source_stage: str,
    producer: str,
    fields: dict[str, Any],
    artifact_id: str | None = None,
    inputs: list[str] | None = None,
    version: str = "0.1.0",
    status: str = "accepted",
    created_at: str | None = None,
) -> dict[str, Any]:
    if artifact_type not in ARTIFACT_REQUIRED_FIELDS:
        raise ArtifactValidationError(f"Unknown artifact type: {artifact_type}")
    artifact = {
        "id": artifact_id or _default_id(artifact_type, fields),
        "version": version,
        "created_at": created_at or utc_now(),
        "source_stage": source_stage,
        "inputs": inputs or [],
        "producer": producer,
        "hash": "",
        "status": status,
    }
    artifact.update(copy.deepcopy(fields))
    artifact["hash"] = artifact_hash(artifact)
    validate_artifact(artifact_type, artifact)
    return artifact


def _default_id(artifact_type: str, fields: dict[str, Any]) -> str:
    preferred = (
        fields.get("environment_id")
        or fields.get("review_id")
        or fields.get("gate_record_id")
        or fields.get("invocation_id")
        or fields.get("backend_id")
        or fields.get("request_id")
        or fields.get("package_plan_id")
        or fields.get("replay_plan_id")
        or fields.get("consumer_index_id")
        or fields.get("release_id")
        or fields.get("goal")
        or artifact_type
    )
    raw = f"{artifact_type}:{preferred}"
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:10]
    return f"{artifact_type.lower()}-{digest}"


def validate_artifact(artifact_type: str, artifact: dict[str, Any]) -> None:
    _require_fields(artifact_type, artifact, COMMON_FIELDS)
    _require_fields(artifact_type, artifact, ARTIFACT_REQUIRED_FIELDS[artifact_type])
    expected_hash = artifact_hash(artifact)
    if artifact["hash"] and artifact["hash"] != expected_hash:
        raise ArtifactValidationError(f"{artifact_type}.hash does not match content")
    _validate_id_fields(artifact_type, artifact)

    if artifact_type == "SourceEvidenceIndex":
        for source in artifact["sources"]:
            _require_fields(artifact_type, source, ["source_id", "kind", "uri_or_path", "version_or_hash", "license", "auth_requirement", "network_requirement", "security_note"])
            _assert_in(artifact_type, "source.kind", source.get("kind"), SOURCE_KINDS)
        for obj in artifact["extractable_objects"]:
            _require_fields(artifact_type, obj, ["source_id", "object_kind", "name", "evidence_refs"])
    elif artifact_type == "LogicalToolGraph":
        _validate_logical_tool_graph(artifact_type, artifact)
    elif artifact_type == "TaskSet":
        _validate_task_set(artifact)
    elif artifact_type == "SurfacePlan":
        _validate_surface_plan(artifact_type, artifact)
    elif artifact_type == "VerifierPlan":
        _validate_verifier_plan(artifact_type, artifact)
    elif artifact_type == "EnvironmentSpec":
        _validate_environment_spec(artifact)
    elif artifact_type == "FeasibilityReport":
        _assert_in(artifact_type, "status", artifact.get("status"), {"pass", "fail", "needs_human"})
        if artifact.get("gate_result_scope") != "upstream_accepted_gates_before_s8_self_evaluation":
            raise ArtifactValidationError("FeasibilityReport must declare upstream gate_result_scope")
        if set(artifact.get("self_gate_expectations", [])) != {"G0", "G10", "G13"}:
            raise ArtifactValidationError("FeasibilityReport must declare S8 self gate expectations")
    elif artifact_type == "ReviewRecord":
        _assert_in(artifact_type, "alignment_status", artifact.get("alignment_status"), {"pass", "fail", "needs_human"})
        for finding in artifact["drift_findings"]:
            _require_fields(artifact_type, finding, ["requirement_ref", "finding", "severity", "evidence"])
    elif artifact_type == "GateRecord":
        _assert_in(artifact_type, "status", artifact.get("status"), {"pass", "fail", "needs_human"})
    elif artifact_type == "ReplayPlan":
        _require_fields(artifact_type, artifact["state_snapshot_points"], ["before", "after", "on_failure"])
        schema_keys = set(artifact.get("execution_trace_schema", {}))
        missing_trace_keys = [key for key in artifact.get("execution_trace_inputs", []) if key not in schema_keys]
        if missing_trace_keys:
            raise ArtifactValidationError(f"ReplayPlan execution_trace_schema missing inputs: {missing_trace_keys}")
        commands = artifact.get("replay_commands", [])
        missing = [task_id for task_id in artifact.get("task_ids", []) if not any(f"--task {task_id}" in command for command in commands)]
        if missing:
            raise ArtifactValidationError(f"ReplayPlan replay_commands missing tasks: {missing}")
    elif artifact_type == "AgentInvocationRecord":
        _assert_in(artifact_type, "backend_kind", artifact.get("backend_kind"), AGENT_BACKEND_KINDS)
        _assert_in(artifact_type, "node_purpose", artifact.get("node_purpose"), AGENT_NODE_PURPOSES)
        _assert_in(artifact_type, "status", artifact.get("status"), {"pass", "fail", "needs_human"})
        _require_fields(artifact_type, artifact["permissions"], ["network", "filesystem", "auth", "sandbox"])
        _require_fields(artifact_type, artifact["budget"], ["tokens", "time_ms", "cost_limit"])
    elif artifact_type == "AgentBackendConfig":
        _assert_in(artifact_type, "backend_kind", artifact.get("backend_kind"), AGENT_BACKEND_KINDS)
        _assert_in(artifact_type, "provider", artifact.get("provider"), AGENT_PROVIDERS)
        _require_fields(artifact_type, artifact["auth"], ["api_key_env", "auth_env_refs", "requires_auth"])
        _require_fields(artifact_type, artifact["command"], ["argv", "fixed_args", "forbidden_args", "allowlist_executables", "cwd"])
        _require_fields(artifact_type, artifact["timeouts"], ["connect_ms", "run_ms"])
        _require_fields(artifact_type, artifact["budgets"], ["max_tokens", "max_cost", "max_tool_calls"])
        _require_fields(artifact_type, artifact["permissions"], ["network", "filesystem", "auth", "sandbox"])
        _validate_no_secret_material(artifact)


def _validate_id_fields(artifact_type: str, artifact: dict[str, Any]) -> None:
    for key, value in artifact.items():
        if key == "id" or key.endswith("_id") or key.endswith("_ref"):
            if isinstance(value, str) and value and not ID_RE.match(value):
                raise ArtifactValidationError(f"{artifact_type}.{key} is not a stable ID/ref: {value!r}")


def _validate_environment_spec(artifact: dict[str, Any]) -> None:
    _require_fields("EnvironmentSpec", artifact["state_backend"], ["kind", "reset_strategy", "isolation_strategy", "seed_fixture_refs"])
    for surface in artifact["release_surfaces_allowed"]:
        _assert_in("EnvironmentSpec", "release_surfaces_allowed", surface, SURFACES)
    for tool in artifact["logical_tools"]:
        _require_fields("EnvironmentSpec", tool, ["tool_id", "name"])


def _validate_logical_tool_graph(artifact_type: str, artifact: dict[str, Any]) -> None:
    tool_ids = {tool["tool_id"] for tool in artifact["tools"]}
    for edge in artifact["edges"]:
        _assert_in(artifact_type, "edge.dependency_type", edge.get("dependency_type"), DEPENDENCY_TYPES)
        if edge.get("from_tool_id") not in tool_ids or edge.get("to_tool_id") not in tool_ids:
            raise ArtifactValidationError(f"{artifact_type} edge references an unknown tool")
    for parameter in artifact["parameters"]:
        _assert_in(artifact_type, "parameter.classification", parameter.get("classification"), PARAMETER_CLASSES)
        _require_fields(artifact_type, parameter, ["name", "classification", "source", "validation"])
    for tool in artifact["tools"]:
        _require_fields(artifact_type, tool, ["tool_id", "name", "input_schema", "output_schema", "reads", "writes", "side_effects", "errors", "idempotency"])


def _validate_task_set(artifact: dict[str, Any]) -> None:
    for task in artifact["tasks"]:
        _require_fields(
            "TaskSet",
            task,
            [
                "task_id",
                "natural_request",
                "target_capability",
                "initial_state_refs",
                "expected_state_delta",
                "expected_answer",
                "allowed_logical_tool_ids",
                "forbidden_leakage",
                "dependency_path",
                "difficulty",
                "verifier_refs",
            ],
        )
        if not isinstance(task["allowed_logical_tool_ids"], list) or not isinstance(task["dependency_path"], list):
            raise ArtifactValidationError("TaskSet task tool fields must be lists")
    _require_fields("TaskSet", artifact["coverage"], ["tool_ids", "capabilities", "state_entities"])


def _validate_surface_plan(artifact_type: str, artifact: dict[str, Any]) -> None:
    for binding in artifact["bindings"]:
        _require_fields(artifact_type, binding, ["binding_id", "logical_tool_id", "surface", "exposure_name", "input_mapping", "output_mapping", "error_mapping", "auth_context", "state_scope"])
        _assert_in(artifact_type, "binding.surface", binding.get("surface"), SURFACES)
    for surface, status in artifact["surface_status"].items():
        _assert_in(artifact_type, "surface_status key", surface, SURFACES)
        _assert_in(artifact_type, "surface_status value", status, SURFACE_STATUSES)


def _validate_verifier_plan(artifact_type: str, artifact: dict[str, Any]) -> None:
    for verifier in artifact["verifiers"]:
        _require_fields(
            artifact_type,
            verifier,
            [
                "verifier_id",
                "task_id",
                "kind",
                "inputs",
                "checks",
                "success_criteria",
                "failure_criteria",
                "positive_examples",
                "negative_examples",
                "evidence_refs",
                "replay_inputs",
                "assertions",
                "allowed_side_effects",
                "timeout_ms",
                "isolation_requirement",
                "failure_diagnostics",
            ],
        )
        _assert_in(artifact_type, "verifier.kind", verifier.get("kind"), VERIFIER_KINDS)
        for assertion in verifier["assertions"]:
            _require_fields(artifact_type, assertion, ["assertion_id", "target", "operator", "expected", "tolerance", "source_ref"])


def _require_fields(artifact_type: str, artifact: dict[str, Any], fields: list[str]) -> None:
    missing = [field for field in fields if field not in artifact]
    if missing:
        raise ArtifactValidationError(f"{artifact_type} missing required fields: {', '.join(missing)}")


def _assert_in(artifact_type: str, field: str, value: Any, allowed: set[str]) -> None:
    if value not in allowed:
        raise ArtifactValidationError(f"{artifact_type}.{field}={value!r} is not one of {sorted(allowed)}")


def _validate_no_secret_material(artifact: dict[str, Any]) -> None:
    auth = artifact.get("auth", {})
    if "api_key" in auth:
        raise ArtifactValidationError("AgentBackendConfig.auth must not contain api_key values")
    api_key_env = auth.get("api_key_env", "")
    if api_key_env and not str(api_key_env).endswith("API_KEY"):
        raise ArtifactValidationError("AgentBackendConfig.auth.api_key_env must name an env var, not a secret")


def write_yaml(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(value, handle, sort_keys=False, allow_unicode=True)


def read_yaml(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(stable_json(row))
            handle.write("\n")
