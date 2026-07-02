from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent_world.agents import InvocationRequest, invoke_backend
from agent_world.artifacts import ARTIFACT_REQUIRED_FIELDS, make_artifact, stable_json
from agent_world.config import load_research_config
from agent_world.executors.base import NodeAttemptResult
from agent_world.research.lightweight import collect_research_candidates


class AgentAttemptExecutor:
    executor_id = "agent_attempt"

    def execute(self, context: Any, node: Any, profile: Any, *, attempt_index: int = 1) -> NodeAttemptResult:
        research_config = load_research_config(context.config.env)
        backend_config = context.artifact("InvocationBackendConfig")
        if backend_config.get("backend_kind") == "mock":
            return NodeAttemptResult(
                status="needs_human",
                failure_class="mock_backend_not_allowed",
                recovery_suggestion="Configure a real InvocationBackend for research execution; mock backends cannot produce accepted SourceEvidenceIndex fields.",
            )
        try:
            packet = collect_research_candidates(context, research_config)
        except Exception as exc:
            return NodeAttemptResult(
                status="fail",
                failure_class="research_provider_failed",
                recovery_suggestion=str(exc),
            )
        if not packet.get("candidates"):
            return NodeAttemptResult(
                status="fail",
                failure_class="research_result_empty",
                recovery_suggestion="Research source discovery produced no accepted sources.",
            )
        invocations = []
        evidence_refs = []
        trace_refs = []
        stage_feedback = list(getattr(context, "node_feedback", {}).get(node.stage, []))
        request = InvocationRequest(
            stage=node.stage,
            node_purpose=profile.node_purpose,
            instruction=_instruction(context, node, profile, packet, feedback=stage_feedback),
            input_artifact_ids=[context.artifacts[name]["id"] for name in node.input_artifact_types if name in context.artifacts],
            invocation_id=f"invoke-{node.stage.lower()}-{profile.executor_id}-{profile.node_purpose}-attempt-{attempt_index}",
            allowed_tool_access=["local_sources", "searxng", "jina_reader_search", "process_research"],
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
                failure_class=result.failure_class or "agent_attempt_failed",
                recovery_suggestion=result.recovery_suggestion or "Fix the configured research InvocationBackend.",
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
        fields = _normalize_source_evidence_fields(dict(parsed.get("fields") if isinstance(parsed.get("fields"), dict) else parsed))
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
            evidence_refs=[ref for item in fields.get("extractable_objects", []) for ref in item.get("evidence_refs", [])] + evidence_refs,
            trace_refs=trace_refs,
        )


def _instruction(context: Any, node: Any, profile: Any, packet: dict[str, Any], *, feedback: list[dict[str, str]]) -> str:
    prompt_text = _read_project_text(profile.prompt_ref)
    skill_texts = [{"ref": ref, "text": _read_project_text(ref)} for ref in profile.skill_refs]
    payload = {
        "stage": node.stage,
        "node_id": node.node_id,
        "target_artifact_type": node.output_artifact_type,
        "required_fields": ARTIFACT_REQUIRED_FIELDS.get(node.output_artifact_type, []),
        "raw_request": context.config.raw_request,
        "upstream_artifacts": {
            name: context.artifacts[name]
            for name in node.input_artifact_types
            if name in context.artifacts
        },
        "research_candidate_packet": packet,
        "skill_refs": list(profile.skill_refs),
        "contract_hints": {
            "stable_id_rule": "source_id and evidence refs must be stable ASCII ids/refs, never prose sentences.",
            "source_rule": "Only use candidates from research_candidate_packet.candidates.",
        },
    }
    feedback_text = ""
    if feedback:
        feedback_text = (
            "\nPrevious invalid attempts JSON:\n"
            f"{stable_json(feedback)}\n"
            "Return a corrected SourceEvidenceIndex JSON object using only the provided candidates.\n"
        )
    return (
        f"{prompt_text.strip()}\n\n"
        "Stage skills JSON:\n"
        f"{stable_json(skill_texts)}\n\n"
        "Research candidate packet JSON:\n"
        f"{stable_json(payload)}\n\n"
        f"{feedback_text}"
        "Select source evidence from the candidate packet and return only a JSON object containing SourceEvidenceIndex fields. "
        "Do not invent sources, hashes, licenses, or URLs. Do not wrap the result in id/version/hash/status metadata."
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


def _normalize_source_evidence_fields(fields: dict[str, Any]) -> dict[str, Any]:
    """Normalize common LLM field-name variants without inventing evidence."""

    extractable_objects = fields.get("extractable_objects")
    if not isinstance(extractable_objects, list):
        return fields
    normalized = dict(fields)
    normalized_objects = []
    for item in extractable_objects:
        if not isinstance(item, dict):
            normalized_objects.append(item)
            continue
        updated = dict(item)
        if "object_kind" not in updated and "object_type" in updated:
            updated["object_kind"] = updated["object_type"]
        if "name" not in updated and "value" in updated:
            updated["name"] = updated["value"]
        if "evidence_refs" not in updated and "evidence_ref" in updated:
            updated["evidence_refs"] = [updated["evidence_ref"]]
        normalized_objects.append(updated)
    normalized["extractable_objects"] = normalized_objects
    return normalized


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
            inputs=[context.artifacts[name]["id"] for name in node.input_artifact_types if name in context.artifacts],
        )
    except Exception as exc:
        return str(exc)
    return ""
