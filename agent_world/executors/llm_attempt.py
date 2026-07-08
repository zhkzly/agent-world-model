from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent_world.agents import InvocationRequest, invoke_backend
from agent_world.artifacts import ARTIFACT_REQUIRED_FIELDS, make_artifact, stable_json
from agent_world.canonical_ids import canonicalize_stage_fields
from agent_world.executors.base import NodeAttemptResult


class LlmAttemptExecutor:
    executor_id = "llm_attempt"

    def execute(self, context: Any, node: Any, profile: Any, *, attempt_index: int = 1) -> NodeAttemptResult:
        prompt_text = _read_project_text(profile.prompt_ref)
        skill_texts = [(ref, _read_project_text(ref)) for ref in profile.skill_refs]
        backend_config = context.artifact("InvocationBackendConfig")
        if backend_config.get("backend_kind") == "mock":
            return NodeAttemptResult(
                status="needs_human",
                failure_class="mock_backend_not_allowed",
                recovery_suggestion=f"Configure a real InvocationBackend for {node.stage}; mock backends cannot produce accepted semantic artifact fields.",
            )
        invocations = []
        evidence_refs = []
        trace_refs = []
        stage_feedback = list(getattr(context, "node_feedback", {}).get(node.stage, []))
        instruction = _instruction(context, node, profile, prompt_text, skill_texts, feedback=stage_feedback)
        request = InvocationRequest(
            stage=node.stage,
            node_purpose=profile.node_purpose,
            instruction=instruction,
            input_artifact_ids=[context.artifacts[name]["id"] for name in node.input_artifact_types if name in context.artifacts],
            invocation_id=f"invoke-{node.stage.lower()}-{profile.executor_id}-{profile.node_purpose}-attempt-{attempt_index}",
            permissions={
                "network": bool(backend_config.get("permissions", {}).get("network")),
                "filesystem": "artifact_context",
                "auth": bool(backend_config.get("permissions", {}).get("auth")),
                "sandbox": False,
            },
            budget={
                "tokens": int(backend_config.get("budgets", {}).get("max_tokens", 0)),
                "time_ms": int(backend_config.get("timeouts", {}).get("run_ms", 5000)),
                "cost_limit": int(backend_config.get("budgets", {}).get("max_cost", 0)),
            },
            instruction_ref=profile.prompt_ref or f"stage:{node.stage}",
        )
        invocation, result = invoke_backend(context.invocation_registry, request, backend_config)
        invocation = _annotate_invocation(invocation, profile)
        invocations.append(invocation)
        evidence_refs.extend(result.evidence_refs)
        if result.trace_ref:
            trace_refs.append(result.trace_ref)
        if result.status != "pass":
            return NodeAttemptResult(
                status=result.status,
                invocation_records=invocations,
                evidence_refs=evidence_refs,
                trace_refs=trace_refs,
                failure_class=result.failure_class or "llm_attempt_failed",
                recovery_suggestion=result.recovery_suggestion or "Fix the configured invocation backend or stage prompt.",
            )
        parsed, parse_error = _parse_json_object(result.text)
        if parse_error:
            return NodeAttemptResult(
                status="fail",
                invocation_records=invocations,
                evidence_refs=evidence_refs,
                trace_refs=trace_refs,
                failure_class="invalid_invocation_json",
                recovery_suggestion=parse_error,
            )
        fields = _fields_for_stage(context, node.stage, parsed)
        validation_error = _validate_fields(context, node, fields)
        if validation_error:
            return NodeAttemptResult(
                status="fail",
                invocation_records=invocations,
                evidence_refs=evidence_refs,
                trace_refs=trace_refs,
                failure_class="invalid_attempt_artifact_fields",
                recovery_suggestion=validation_error,
            )
        return NodeAttemptResult(
            status="pass",
            fields=fields,
            invocation_records=invocations,
            evidence_refs=evidence_refs,
            trace_refs=trace_refs,
        )


def _fields_for_stage(context: Any, stage: str, parsed: dict[str, Any]) -> dict[str, Any]:
    return canonicalize_stage_fields(context, stage, dict(parsed.get("fields") if isinstance(parsed.get("fields"), dict) else parsed))


def _instruction(context: Any, node: Any, profile: Any, prompt_text: str, skill_texts: list[tuple[str, str]], *, feedback: list[dict[str, str]]) -> str:
    target_type = node.output_artifact_type
    required = ARTIFACT_REQUIRED_FIELDS.get(target_type, [])
    artifacts = {
        name: context.artifacts[name]
        for name in node.input_artifact_types
        if name in context.artifacts
    }
    skills = [{"ref": ref, "text": text} for ref, text in skill_texts]
    packet = {
        "stage": node.stage,
        "node_id": node.node_id,
        "target_artifact_type": target_type,
        "required_fields": required,
        "raw_request": context.config.raw_request,
        "upstream_artifacts": artifacts,
        "skill_refs": list(profile.skill_refs),
        "contract_hints": _contract_hints(target_type),
    }
    feedback_text = ""
    if feedback:
        feedback_text = (
            "\nPrevious invalid attempts JSON:\n"
            f"{stable_json(feedback)}\n"
            "Return a corrected JSON object that satisfies the target artifact contract. Do not repeat invalid enum values, invalid IDs, or extra prose.\n"
        )
    return (
        f"{prompt_text.strip()}\n\n"
        "Stage skills JSON:\n"
        f"{stable_json(skills)}\n\n"
        "Artifact generation packet JSON:\n"
        f"{stable_json(packet)}\n\n"
        f"{feedback_text}"
        "Return only a JSON object containing the fields for the target artifact. "
        "Do not wrap the result in id/version/hash/status metadata. "
        "Every field ending with _id or _ref must be a stable ASCII identifier using letters, digits, underscore, dash, dot, colon, slash, or hash; never use a sentence as an id."
    )


def _read_project_text(ref: str) -> str:
    if not ref:
        return ""
    path = Path(__file__).resolve().parents[1] / ref
    return path.read_text(encoding="utf-8")


def _parse_json_object(text: str) -> tuple[dict[str, Any], str]:
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            return {}, "Invocation output is not a JSON object."
        try:
            parsed = json.loads(text[start : end + 1])
        except json.JSONDecodeError as exc:
            return {}, f"Invocation output JSON parse failed: {exc}"
    if not isinstance(parsed, dict):
        return {}, "Invocation output must be a JSON object."
    return parsed, ""


def _annotate_invocation(invocation: dict[str, Any], profile: Any) -> dict[str, Any]:
    updated = dict(invocation)
    updated["executor_id"] = profile.executor_id
    updated["attempt_profile"] = {
        "stage": profile.stage,
        "executor_id": profile.executor_id,
        "node_purpose": profile.node_purpose,
        "prompt_ref": profile.prompt_ref,
        "skill_refs": list(profile.skill_refs),
    }
    updated["skill_refs"] = list(profile.skill_refs)
    return updated


def _validate_fields(context: Any, node: Any, fields: dict[str, Any]) -> str:
    try:
        make_artifact(
            node.output_artifact_type,
            source_stage=node.stage,
            producer=node.node_id,
            fields=fields,
            artifact_id=_artifact_id_from_fields(fields),
            inputs=[context.artifacts[name]["id"] for name in node.input_artifact_types if name in context.artifacts],
        )
    except Exception as exc:
        return str(exc)
    return ""


def _artifact_id_from_fields(fields: dict[str, Any]) -> str | None:
    for key in ["domain_plan_id", "strategy_selection_id", "request_id", "package_plan_id", "release_id", "backend_id", "report_id"]:
        if fields.get(key):
            return str(fields[key])
    return None


def _contract_hints(target_type: str) -> dict[str, Any]:
    hints: dict[str, Any] = {
        "stable_id_rule": "Fields ending in _id/_ref must match ^[A-Za-z0-9][A-Za-z0-9_.:/#-]*$.",
    }
    if target_type == "DomainPlan":
        hints["planning_status_allowed"] = ["planned", "unsupported", "blocked"]
        hints["domain_seed_rule"] = "Use a compact stable seed such as incident-runbook, not a full prose sentence."
    if target_type == "NeedSpec":
        hints["out_of_scope_must_include"] = ["training", "rollout", "reward export", "awm reproduction", "mcp-only", "cli-only"]
        hints["preferred_surfaces"] = "Include python unless a source-grounded reason forbids it."
    if target_type == "KnowledgePack":
        hints["state_objects_required_fields"] = ["object_id", "name", "source_refs"]
        hints["operations_required_fields"] = ["operation_id", "name", "source_refs"]
        hints["business_rules_required_fields"] = ["rule_id", "statement", "source_refs"]
    if target_type == "EnvironmentSpec":
        hints["state_backend_required_shape"] = {
            "kind": "in_memory",
            "reset_strategy": "reset_to_seed_fixture",
            "isolation_strategy": "per_run_isolated_state",
            "seed_fixture_refs": ["fixture:initial-state"],
        }
        hints["release_surfaces_allowed_values"] = ["python", "cli", "http", "mcp"]
        hints["logical_tools_required_fields"] = ["tool_id", "name"]
        hints["logical_tool_id_rule"] = "Copy KnowledgePack.operations[].operation_id exactly for every logical_tools[].tool_id."
    if target_type == "LogicalToolGraph":
        hints["tools_required_fields"] = ["tool_id", "name", "input_schema", "output_schema", "reads", "writes", "side_effects", "errors", "idempotency"]
        hints["edge_dependency_type_allowed"] = ["strong", "weak", "independent"]
        hints["parameters_shape"] = "Flat list of objects, not a dictionary. Each item must include name, classification, source, validation."
        hints["parameter_classification_allowed"] = ["external", "internal", "optional"]
    if target_type == "StrategySelection":
        hints["selection_status_allowed"] = ["selected", "unsupported", "blocked"]
    if target_type == "TaskSet":
        hints["minimum_task_count"] = 5
        hints["task_required_fields"] = [
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
        ]
        hints["coverage_required_fields"] = ["tool_ids", "capabilities", "state_entities"]
        hints["dependency_path_shape"] = "List of logical tool id strings in execution order, not edge objects."
        hints["dependency_path_edge_rule"] = "Every adjacent pair in dependency_path must be identical or match a declared directed LogicalToolGraph.edges from_tool_id -> to_tool_id edge; never invent implicit sibling edges."
        hints["natural_request_rule"] = "Do not mention database, backend, verifier, logical_tool, tool_id, or actual tool ids in user-facing natural_request."
    if target_type == "SurfacePlan":
        hints["python_surface_required"] = "surface_status.python must be required_for_first_slice and at least one binding must use surface=python."
        hints["binding_required_fields"] = ["binding_id", "logical_tool_id", "surface", "exposure_name", "input_mapping", "output_mapping", "error_mapping", "auth_context", "state_scope"]
        hints["surface_status_values"] = ["planned", "required_for_first_slice", "deferred", "rejected"]
        hints["surface_status_shape"] = {"python": "required_for_first_slice"}
    if target_type == "FeasibilityReport":
        hints["status_allowed"] = ["pass", "fail", "needs_human"]
        hints["gate_result_rule"] = "Include all upstream passing gate records with gate_id, status, evidence, failure_class, and recovery_suggestion."
    if target_type == "VerifierPlan":
        hints["verifier_kind_allowed"] = ["state_query", "state_diff", "file_assertion", "command_assertion", "test_assertion", "api_assertion"]
        hints["verifier_trace_rule"] = "Every verifier inputs must include surface_trace_path, expected_dependency_path, and trace_call_group, and checks/assertions must validate dependency path trace."
        hints["verifier_required_fields"] = [
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
        ]
        hints["assertion_required_fields"] = ["assertion_id", "target", "operator", "expected", "tolerance", "source_ref"]
        hints["required_assertion_target"] = "dependency_path_trace_matches"
    return hints
