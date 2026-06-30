from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path, PurePath
from typing import Any

import yaml

from agent_world.artifacts import GENERATED_BUNDLE_FILE_KINDS, make_artifact, stable_json
from agent_world.candidate_check import check_generated_candidate


GENERATED_FILE_KINDS = dict(GENERATED_BUNDLE_FILE_KINDS)
GENERIC_STRATEGY_FAMILY = "request-driven-generated-environment-v1"
RAW_REQUEST_SOURCE_ID = "source-raw-request"


def domain_plan_fields(raw_request: str) -> dict[str, Any]:
    """Plan a generated environment from the request itself, without domain registries."""
    normalized = _normalize_text(raw_request)
    environment_id = _environment_id(raw_request)
    concepts = _concepts(raw_request)
    operations = _operation_ids(concepts)
    return {
        "domain_plan_id": f"domain-plan-{environment_id}",
        "raw_request": raw_request,
        "domain_seed": environment_id,
        "domain_intent": _sentence(raw_request),
        "recognized_intents": concepts,
        "required_state_objects": _state_object_ids(concepts),
        "required_operations": operations,
        "likely_source_needs": ["raw request", "provided local source paths", "generated replay contract", "agent-written runtime bundle"],
        "constraints": {
            "network": "not_required",
            "auth": "not_required",
            "license": "user_supplied_or_generated_local_sources",
            "safety": "synthetic_local_state_only",
            "local_execution": True,
            "mocking_allowed": True,
        },
        "license_auth_network_security": {
            "license": "user_supplied_request",
            "auth_requirement": "none",
            "network_requirement": "none",
            "security_note": "The default request-driven path uses local synthetic state and never contacts external services during planning.",
        },
        "planner_evidence": {
            "raw_request_ref": "PipelineRunConfig.raw_request",
            "request_hash": hashlib.sha256(normalized.encode("utf-8")).hexdigest(),
            "strategy_family": GENERIC_STRATEGY_FAMILY,
            "generated_environment_id": environment_id,
        },
        "planning_status": "planned" if normalized else "blocked",
        "blocked_reasons": [] if normalized else ["raw_request is empty"],
    }


def strategy_selection_fields(domain_plan: dict[str, Any]) -> dict[str, Any]:
    if domain_plan.get("planning_status") != "planned":
        return {
            "strategy_selection_id": "strategy-selection-blocked-request",
            "domain_plan_ref": domain_plan["id"],
            "domain_seed": domain_plan.get("domain_seed", "blocked-request"),
            "selection_status": "blocked",
            "selected_strategies": [],
            "source_strategy": "",
            "extraction_strategy": "",
            "synthesis_strategy": "",
            "implementation_strategy": "",
            "independent_verifier_strategy": "",
            "package_strategy": "",
            "selection_reason": "No request can be planned from an empty raw request.",
            "blocked_reasons": list(domain_plan.get("blocked_reasons", [])),
        }
    return {
        "strategy_selection_id": f"strategy-selection-{domain_plan['domain_seed']}",
        "domain_plan_ref": domain_plan["id"],
        "domain_seed": domain_plan["domain_seed"],
        "selection_status": "selected",
        "selected_strategies": [
            "raw-request-source-discovery-v1",
            "source-grounded-generic-extraction-v1",
            "artifact-driven-task-synthesis-v1",
            "agent-generated-bundle-v1",
            "framework-replay-contract-verifier-v1",
            "generated-runtime-package-v1",
        ],
        "source_strategy": "raw-request-source-discovery-v1",
        "extraction_strategy": "source-grounded-generic-extraction-v1",
        "synthesis_strategy": "artifact-driven-task-synthesis-v1",
        "implementation_strategy": "agent-generated-bundle-v1",
        "independent_verifier_strategy": "framework-replay-contract-verifier-v1",
        "package_strategy": "generated-runtime-package-v1",
        "selection_reason": "The request-driven path selects a generic artifact pipeline and delegates executable code to the configured agent backend.",
        "blocked_reasons": [],
    }


def need_spec_fields(domain_plan: dict[str, Any]) -> dict[str, Any]:
    return {
        "goal": domain_plan["raw_request"],
        "target_capabilities": [
            "request-driven environment generation",
            "source-grounded task construction",
            "agent-backed executable runtime generation",
            "framework-owned replay and verifier feedback",
        ],
        "domain_seed": domain_plan["domain_seed"],
        "expected_agent_behavior": "Use the generated logical tools to mutate or inspect an isolated local state according to the accepted tasks.",
        "constraints": dict(domain_plan["constraints"]),
        "preferred_surfaces": ["python", "cli", "http", "mcp"],
        "out_of_scope": [
            "training integration",
            "rollout",
            "reward export",
            "AWM reproduction",
            "MCP-only architecture",
            "CLI-only architecture",
            "live external service access",
            "generic shell execution surface",
        ],
        "human_confirmation_required": [],
        "domain_plan_ref": domain_plan["id"],
    }


def source_evidence_fields(context: Any) -> dict[str, Any]:
    selection = context.artifact("StrategySelection")
    if selection.get("selection_status") != "selected":
        return _empty_source_index(["StrategySelection did not select a source strategy."])
    env = context.config.env or {}
    if env.get("AGENT_WORLD_REQUEST_SOURCE_STRATEGY") == "none":
        return _empty_source_index(["Source strategy disabled by AGENT_WORLD_REQUEST_SOURCE_STRATEGY=none."])
    root = _source_root(context)
    root.mkdir(parents=True, exist_ok=True)
    request_path = root / "raw-request.md"
    request_path.write_text(_raw_request_document(context), encoding="utf-8")
    source_paths = [request_path] + [Path(path) for path in context.config.source_paths]
    sources = []
    extractable = []
    rejected = []
    for index, path in enumerate(source_paths, start=1):
        resolved = path.resolve()
        if not resolved.is_file():
            rejected.append({"source": str(path), "reason": "source path is not a file"})
            continue
        source_id = RAW_REQUEST_SOURCE_ID if resolved == request_path.resolve() else f"source-local-{index}"
        sources.append(
            {
                "source_id": source_id,
                "kind": "manual_note" if source_id == RAW_REQUEST_SOURCE_ID else "local_files",
                "uri_or_path": str(resolved),
                "version_or_hash": _sha256(resolved),
                "license": "user_supplied",
                "auth_requirement": "none",
                "network_requirement": "none",
                "security_note": "Local request-driven source; no credentials or live service access required.",
            }
        )
        extractable.append(
            {
                "source_id": source_id,
                "object_kind": "request_source",
                "name": resolved.name,
                "evidence_refs": [f"{source_id}#sha256:{_sha256(resolved)}"],
            }
        )
    return {
        "planned_environment_id": context.artifact("DomainPlan")["domain_seed"],
        "sources": sources,
        "extractable_objects": extractable,
        "mock_boundaries": ["synthetic local state", "no external credentials", "no live service mutation"],
        "open_questions": [],
        "rejected_sources": rejected,
    }


def knowledge_pack_fields(source_index: dict[str, Any], *, base_dir: Path | None = None) -> dict[str, Any]:
    text = _source_text(source_index, base_dir=base_dir)
    concepts = _concepts(text)
    state_objects = _state_objects(concepts)
    operations = _operations(concepts)
    rules = _business_rules(source_index)
    return {
        "environment_id": source_index.get("planned_environment_id") or _environment_id(text),
        "state_objects": state_objects,
        "operations": operations,
        "business_rules": rules,
        "verifiable_fields": _verifiable_fields(state_objects),
        "uncertainties": [],
        "request_concepts": concepts,
    }


def environment_spec_fields(knowledge: dict[str, Any]) -> dict[str, Any]:
    environment_id = str(knowledge.get("environment_id") or _environment_id(" ".join(knowledge.get("request_concepts", []))))
    return {
        "environment_id": environment_id,
        "domain": "request-generated local executable environment",
        "state_backend": {
            "kind": "json",
            "reset_strategy": "load seed_state.json and deep-copy it for every replay",
            "isolation_strategy": "one in-memory state snapshot per task replay",
            "seed_fixture_refs": [f"fixtures/seed/{environment_id}.json"],
        },
        "state_entities": [item["object_id"] for item in knowledge.get("state_objects", [])],
        "logical_tools": [{"tool_id": operation["operation_id"], "name": operation["name"]} for operation in knowledge.get("operations", [])],
        "permissions": {"network": False, "filesystem": "package_dir_only", "auth": False},
        "safety_boundaries": ["synthetic state only", "no live external service calls", "no generic shell execution surface"],
        "mock_policy": {"external_services": "represented by generated local state only"},
        "release_surfaces_allowed": ["python", "cli", "http", "mcp"],
        "observability": {"logs": True, "traces": True, "state_snapshots": ["before", "after", "on_failure"]},
    }


def logical_tool_graph_fields(knowledge: dict[str, Any]) -> dict[str, Any]:
    operations = list(knowledge.get("operations", []))
    parameters = {"payload": _parameter("payload", optional=False), "note": _parameter("note", optional=True)}
    return {
        "tools": [
            {
                "tool_id": operation["operation_id"],
                "name": operation["name"],
                "input_schema": {"required": ["payload"], "optional": ["note"]},
                "output_schema": {"type": "object"},
                "reads": list(operation.get("reads", [])),
                "writes": list(operation.get("writes", [])),
                "side_effects": list(operation.get("side_effects", [])),
                "errors": ["invalid_payload", "state_update_failed"],
                "idempotency": operation.get("idempotency", "non_idempotent"),
                "source_refs": list(operation.get("source_refs", [])),
            }
            for operation in operations
        ],
        "edges": [
            {
                "from_tool_id": operations[index]["operation_id"],
                "to_tool_id": operations[index + 1]["operation_id"],
                "dependency_type": "weak",
                "reason": "Generated tasks may compose tools in source order, but each accepted replay case remains explicit.",
            }
            for index in range(len(operations) - 1)
        ],
        "parameters": list(parameters.values()),
        "forbidden_direct_access": ["state file path", "verifier implementation", "internal artifact ids"],
    }


def task_set_fields(graph: dict[str, Any], knowledge: dict[str, Any]) -> dict[str, Any]:
    tools = [tool["tool_id"] for tool in graph.get("tools", [])]
    concepts = list(knowledge.get("request_concepts", [])) or ["request", "state", "result"]
    environment_id = str(knowledge.get("environment_id") or _environment_id(" ".join(concepts)))
    tasks = []
    for index, tool_id in enumerate(tools[:3], start=1):
        task_id = f"{environment_id}-task-{index}"
        payload = f"{concepts[(index - 1) % len(concepts)]} acceptance payload {index}"
        expected_answer = {"task_id": task_id, "tool": tool_id, "accepted": True} if index == 3 else ""
        expected_delta = {} if index == 3 else {"state_changed": True, "tool": tool_id}
        tasks.append(
            {
                "task_id": task_id,
                "natural_request": _natural_task_request(index, concepts),
                "target_capability": f"request-derived capability {index}",
                "initial_state_refs": [f"fixtures/seed/{environment_id}.json#initial"],
                "expected_state_delta": expected_delta,
                "expected_answer": expected_answer,
                "allowed_logical_tool_ids": [tool_id],
                "forbidden_leakage": ["state file path", "verifier id", "logical tool id"],
                "dependency_path": [tool_id],
                "difficulty": {"level": "easy" if index == 3 else "medium", "requires_state_change": index != 3},
                "verifier_refs": [f"verifier-{task_id}"],
                "source_refs": _knowledge_source_refs(knowledge),
                "framework_replay": {
                    "tool_calls": [
                        {
                            "tool": tool_id,
                            "kwargs": {"payload": payload, "note": f"task-{index}"},
                            "expects": {"type": "object"},
                        }
                    ],
                    "expected_final_answer": expected_answer,
                },
            }
        )
    return {
        "tasks": tasks,
        "minimum_task_count": 3,
        "coverage": {
            "tool_ids": sorted({tool_id for task in tasks for tool_id in task["allowed_logical_tool_ids"]}),
            "capabilities": [task["target_capability"] for task in tasks],
            "state_entities": [item["object_id"] for item in knowledge.get("state_objects", [])],
        },
        "rejected_candidates": [],
    }


def surface_plan_fields(env_spec: dict[str, Any]) -> dict[str, Any]:
    return {
        "bindings": [
            {
                "binding_id": f"python-{tool['tool_id']}",
                "logical_tool_id": tool["tool_id"],
                "surface": "python",
                "exposure_name": f"GeneratedEnvironment.{tool['tool_id']}",
                "input_mapping": "same as logical tool schema",
                "output_mapping": "JSON-compatible object",
                "error_mapping": "Python exception to logical error",
                "auth_context": "none",
                "state_scope": "isolated generated state snapshot",
            }
            for tool in env_spec.get("logical_tools", [])
        ],
        "surface_status": {"python": "required_for_first_slice", "cli": "planned", "http": "deferred", "mcp": "deferred"},
        "compatibility_notes": ["The first generated slice verifies the Python callable surface; other surfaces remain descriptors until implemented by later nodes."],
    }


def verifier_plan_fields(task_set: dict[str, Any], knowledge: dict[str, Any]) -> dict[str, Any]:
    evidence_refs = _knowledge_source_refs(knowledge)
    verifiers = []
    for task in task_set.get("tasks", []):
        kind = "state_query" if task.get("expected_answer") else "state_diff"
        verifiers.append(
            {
                "verifier_id": f"verifier-{task['task_id']}",
                "task_id": task["task_id"],
                "kind": kind,
                "inputs": ["initial_state", "final_state", "final_answer", "surface_trace_path", "expected_dependency_path", "trace_call_group"],
                "checks": ["dependency path trace assertion", "state snapshot or answer assertion", "negative replay rejection"],
                "success_criteria": "success=true only when the replay trace and expected state or answer evidence match the task contract",
                "failure_criteria": "missing trace entries, unchanged state for mutating tasks, wrong answer, or negative replay success",
                "positive_examples": [f"{task['task_id']}: replay contract succeeds"],
                "negative_examples": [f"{task['task_id']}: empty trace and unchanged state are rejected"],
                "evidence_refs": evidence_refs,
                "replay_inputs": ["seed fixture", "initial snapshot", "final snapshot", "surface trace", "trace call group", "declared dependency path", "final answer"],
                "assertions": [
                    {"assertion_id": f"assert-{task['task_id']}-success", "target": "verify_task_completion.success", "operator": "equals", "expected": True, "tolerance": 0, "source_ref": "framework-replay-contract-verifier-v1"},
                    {"assertion_id": f"assert-{task['task_id']}-path", "target": "dependency_path_trace_matches", "operator": "equals", "expected": True, "tolerance": 0, "source_ref": "framework-replay-contract-verifier-v1"},
                ],
                "allowed_side_effects": [],
                "timeout_ms": 1000,
                "isolation_requirement": "read-only verifier over copied generated state",
                "failure_diagnostics": ["return structured failed checks and observed trace evidence"],
            }
        )
    return {"verifiers": verifiers, "llm_judges": []}


def feasibility_report_fields(context: Any) -> dict[str, Any]:
    blockers = blocking_source_uncertainties(context.artifact("KnowledgePack"))
    return {
        "status": "needs_human" if blockers else "pass",
        "gate_result_scope": "upstream_accepted_gates_before_s8_self_evaluation",
        "self_gate_expectations": ["G0", "G10", "G13"],
        "gate_results": [
            {
                "gate_id": record["gate_id"],
                "status": record["status"],
                "evidence": [record["id"]] + record["evidence_refs"],
                "failure_class": record["failure_class"],
                "recovery_suggestion": record["recovery_suggestion"],
            }
            for record in context.gate_records
        ],
        "minimum_viable_surface": "python",
        "minimum_viable_task_ids": [task["task_id"] for task in context.artifact("TaskSet")["tasks"]],
        "minimum_viable_verifier_ids": [verifier["verifier_id"] for verifier in context.artifact("VerifierPlan")["verifiers"]],
        "implementation_blockers": blockers,
    }


def implementation_request_fields(artifacts: dict[str, dict[str, Any]], review_records: list[dict[str, Any]]) -> dict[str, Any]:
    environment_id = artifacts["EnvironmentSpec"]["environment_id"]
    return {
        "request_id": f"impl-{environment_id}",
        "environment_id": environment_id,
        "source_artifact_ids": [
            artifacts["DomainPlan"]["id"],
            artifacts["StrategySelection"]["id"],
            artifacts["SourceEvidenceIndex"]["id"],
            artifacts["KnowledgePack"]["id"],
            artifacts["TaskSet"]["id"],
            artifacts["VerifierPlan"]["id"],
        ],
        "accepted_task_ids": [task["task_id"] for task in artifacts["TaskSet"]["tasks"]],
        "accepted_verifier_ids": [verifier["verifier_id"] for verifier in artifacts["VerifierPlan"]["verifiers"]],
        "required_surface_ids": [binding["binding_id"] for binding in artifacts["SurfacePlan"]["bindings"] if binding["surface"] == "python"],
        "package_layout_ref": "envpkg/",
        "implementation_scope": [
            "agent-written runtime.py",
            "agent-written seed_state.json",
            "agent-written deterministic verifier.py",
            "agent-written surface descriptor and check script",
            "framework-owned replay and independent verifier records",
        ],
        "non_goals": ["training integration", "rollout", "reward export", "AWM reproduction", "live external service access", "generic shell environment surface"],
        "tdd_requirements": ["machine-readable framework replay contract", "positive and negative verifier behavior", "forged generated check rejection"],
        "launch_check_replay_commands": ["python <candidate_dir>/check_replay.py"],
        "review_record_refs": [record["id"] for record in review_records],
        "strategy_selection_ref": artifacts["StrategySelection"]["id"],
    }


def generated_implementation_record(context: Any, **_: Any) -> dict[str, Any]:
    environment_id = context.artifact("ImplementationRequest")["environment_id"]
    return {
        "implementation_id": f"implementation-{environment_id}-agent-required",
        "mode": "agent_required",
        "environment_id": environment_id,
        "implementation_request_id": context.artifact("ImplementationRequest")["id"],
        "static_check_command": "not run",
        "test_command": "not run",
        "replay_command": "not run",
        "build_check_replay_records": [],
        "verifier_result": {},
        "status": "fail",
        "failure_class": "agent_backend_required",
        "recovery_suggestion": "Request-driven generation requires implementation_mode=agent and a backend that writes a candidate bundle.",
    }


def agent_generated_implementation_record(context: Any, *, agent_invocation: dict[str, Any], agent_result: Any, work_dir: Path) -> dict[str, Any]:
    work_dir = Path(work_dir)
    request = context.artifact("ImplementationRequest")
    environment_id = request["environment_id"]
    base = {
        "implementation_id": f"implementation-{environment_id}-agent-generated",
        "mode": "agent_backed_codegen",
        "environment_id": environment_id,
        "implementation_request_id": request["id"],
        "agent_invocation_id": agent_invocation["id"],
        "agent_work_dir": str(work_dir),
        "source_artifact_ids": request["source_artifact_ids"],
        "static_check_command": "validate agent candidate manifest, path boundaries, file hashes, generated self-check, and framework independent verifier",
        "test_command": f"{sys.executable} <candidate_dir>/check_replay.py",
        "replay_command": f"{sys.executable} <candidate_dir>/check_replay.py --task <task_id>",
        "check_commands": [],
        "replay_commands": [],
    }
    if agent_result.status != "pass":
        return _agent_failure_record(base, status=agent_result.status, failure_class=agent_result.failure_class or "agent_backend_failed", recovery_suggestion=agent_result.recovery_suggestion or "Fix or configure the agent backend.")
    manifest, manifest_error = _agent_candidate_manifest(agent_result.text, work_dir)
    if manifest_error:
        return _agent_failure_record(base, failure_class=manifest_error["failure_class"], recovery_suggestion=manifest_error["recovery_suggestion"])
    validation_error = _validate_agent_candidate_files(work_dir, manifest)
    if validation_error:
        return _agent_failure_record(base, failure_class=validation_error["failure_class"], recovery_suggestion=validation_error["recovery_suggestion"])
    bundle_dir = _agent_candidate_root(work_dir, manifest)
    if isinstance(bundle_dir, dict):
        return _agent_failure_record(base, failure_class=bundle_dir["failure_class"], recovery_suggestion=bundle_dir["recovery_suggestion"])
    runtime_entrypoint = str(manifest.get("runtime_entrypoint") or "runtime.GeneratedEnvironment")
    verifier_entrypoint = str(manifest.get("verifier_entrypoint") or "verifier.verify_task_completion")
    generated_files = _bundle_records_from_agent_manifest(bundle_dir, manifest, fallback_source_refs=_source_refs(context))
    check_record = check_generated_bundle(
        bundle_dir,
        environment_id=environment_id,
        accepted_tasks=context.artifact("TaskSet")["tasks"],
        runtime_entrypoint=runtime_entrypoint,
        verifier_entrypoint=verifier_entrypoint,
    )
    build_check_replay_records = _bundle_check_records(check_record)
    status = "pass" if check_record["success"] else "fail"
    check_commands = [[sys.executable, str(bundle_dir / "check_replay.py")]]
    replay_commands = [[sys.executable, str(bundle_dir / "check_replay.py"), "--task", task_id] for task_id in _accepted_task_ids(context)]
    bundle_artifact = _bundle_artifact(
        context=context,
        bundle_id=str(manifest.get("bundle_id") or f"bundle-{environment_id}-agent-generated"),
        producer="request-driven-agent-codegen",
        build_dir=bundle_dir,
        generated_files=generated_files,
        build_check_replay_records=build_check_replay_records,
        status=status,
        implementation_mode="agent_backed_codegen",
        extra_inputs=[agent_invocation["id"]],
        runtime_entrypoint=runtime_entrypoint,
        verifier_entrypoint=verifier_entrypoint,
        check_commands=check_commands,
        replay_commands=replay_commands,
        agent_invocation_ref=agent_invocation["id"],
    )
    independent_report = independent_verification_report_from_check(context, bundle_artifact, check_record)
    return {
        **base,
        "generated_bundle_id": bundle_artifact["id"],
        "generated_environment_bundle": bundle_artifact,
        "independent_verification_report": independent_report,
        "generated_paths": [item["path"] for item in generated_files],
        "generated_file_hashes": {item["path"]: item["sha256"] for item in generated_files},
        "agent_candidate_dir": str(bundle_dir),
        "test_command": f"{sys.executable} {bundle_dir / 'check_replay.py'}",
        "replay_command": replay_commands[0] if replay_commands else "",
        "check_commands": check_commands,
        "replay_commands": replay_commands,
        "build_check_replay_records": build_check_replay_records,
        "verifier_result": check_record.get("positive_verifier_result", {}),
        "negative_verifier_result": check_record.get("negative_verifier_result", {}),
        "status": status,
        "failure_class": "" if status == "pass" else check_record.get("failure_class", "generated_bundle_check_failed"),
        "recovery_suggestion": "" if status == "pass" else check_record.get("recovery_suggestion", "Repair generated runtime, verifier, seed, or check files before release planning."),
    }


def package_plan_fields(context: Any) -> dict[str, Any]:
    bundle = context.artifact("GeneratedEnvironmentBundle")
    environment_id = bundle["environment_id"]
    package_ref = f"package-{environment_id}"
    replay_ref = f"replay-{environment_id}"
    release_ref = f"release-{environment_id}"
    included_ids = (
        [artifact["id"] for artifact in context.artifacts.values()]
        + [package_ref, replay_ref, f"consumer-{environment_id}", release_ref]
        + [record["id"] for record in context.review_records]
        + [record["id"] for record in context.gate_records]
        + [record["implementation_id"] for record in context.build_check_replay_records]
    )
    return {
        "package_plan_id": package_ref,
        "environment_id": environment_id,
        "layout": "envpkg/",
        "included_artifact_ids": included_ids,
        "fixture_refs": [f"fixtures/seed/{environment_id}.json"],
        "static_check_refs": "request-driven S0-S11 gates plus framework independent verifier",
        "review_record_refs": [record["id"] for record in context.review_records],
        "replay_plan_ref": replay_ref,
        "release_manifest_ref": release_ref,
        "generated_bundle_ref": bundle["id"],
        "independent_verification_report_ref": context.artifact("IndependentVerificationReport")["id"],
        "consumer_output_refs": ["release/task-records.jsonl", "release/verifier-records.jsonl", "release/consumer-index.yaml", "release/generated-runtime-index.yaml"],
        "excluded_items": [
            {"item": "live external services", "reason": "request-driven first slice uses synthetic local state"},
            {"item": "generic shell executor", "reason": "environment tools are logical Python callables"},
            {"item": "trainer runtime", "reason": "training is a downstream consumer"},
        ],
    }


def release_manifest_fields(context: Any) -> dict[str, Any]:
    bundle = context.artifact("GeneratedEnvironmentBundle")
    environment_id = bundle["environment_id"]
    artifacts = context.artifacts | {"EnvironmentPackagePlan": context.artifact("EnvironmentPackagePlan")}
    return {
        "release_id": f"release-{environment_id}",
        "environment_id": environment_id,
        "version": "0.1.0",
        "artifact_hashes": {name: artifact["hash"] for name, artifact in artifacts.items()},
        "package_layout": "envpkg/",
        "task_index": [task["task_id"] for task in context.artifact("TaskSet")["tasks"]],
        "verifier_index": [verifier["verifier_id"] for verifier in context.artifact("VerifierPlan")["verifiers"]],
        "surface_index": context.artifact("SurfacePlan")["surface_status"],
        "fixture_index": [f"fixtures/seed/{environment_id}.json"],
        "replay_contract": "checks/framework-replay-contract.json",
        "generated_bundle_ref": bundle["id"],
        "independent_verification_report_ref": context.artifact("IndependentVerificationReport")["id"],
        "request_lineage": {
            "domain_plan_ref": context.artifact("DomainPlan")["id"],
            "strategy_selection_ref": context.artifact("StrategySelection")["id"],
            "source_evidence_ref": context.artifact("SourceEvidenceIndex")["id"],
            "knowledge_pack_ref": context.artifact("KnowledgePack")["id"],
            "task_set_ref": context.artifact("TaskSet")["id"],
            "verifier_plan_ref": context.artifact("VerifierPlan")["id"],
            "implementation_request_ref": context.artifact("ImplementationRequest")["id"],
            "generated_bundle_ref": bundle["id"],
            "independent_verification_report_ref": context.artifact("IndependentVerificationReport")["id"],
        },
        "generated_bundle": {
            "bundle_id": bundle["id"],
            "build_dir": bundle["build_dir"],
            "runtime_entrypoint": bundle["runtime_entrypoint"],
            "verifier_entrypoint": bundle["verifier_entrypoint"],
            "check_commands": bundle["check_commands"],
            "replay_commands": bundle["replay_commands"],
        },
        "consumer_outputs": ["release/task-records.jsonl", "release/verifier-records.jsonl", "release/consumer-index.yaml", "release/generated-runtime-index.yaml"],
        "known_limits": [
            "The request-driven path requires an agent backend to write executable candidate files.",
            "Default source discovery consumes the raw request and optional local source paths; it does not perform live crawling.",
            "Training, deployment, and online rollout remain downstream consumers.",
        ],
    }


def blocking_source_uncertainties(knowledge: dict[str, Any]) -> list[dict[str, Any]]:
    return [item for item in knowledge.get("uncertainties", []) if item.get("blocking")]


def check_generated_bundle(
    build_dir: Path,
    *,
    environment_id: str,
    accepted_tasks: list[dict[str, Any]] | None = None,
    runtime_entrypoint: str = "runtime.GeneratedEnvironment",
    verifier_entrypoint: str = "verifier.verify_task_completion",
) -> dict[str, Any]:
    build_dir = Path(build_dir)
    generated_check = _run_generated_check([sys.executable, str(build_dir / "check_replay.py")], build_dir)
    framework_check = check_generated_candidate(
        build_dir=build_dir,
        environment_id=environment_id,
        accepted_tasks=accepted_tasks,
        runtime_entrypoint=runtime_entrypoint,
        verifier_entrypoint=verifier_entrypoint,
    )
    independent = framework_check["independent_verification_record"]
    success = generated_check["success"] and framework_check["success"]
    if not generated_check["success"]:
        failure_class = generated_check.get("failure_class", "generated_bundle_check_failed")
        recovery = generated_check.get("recovery_suggestion", "Repair generated check_replay.py or runtime files.")
    elif not framework_check["success"]:
        failure_class = framework_check.get("failure_class", "framework_candidate_check_failed")
        recovery = framework_check.get("recovery_suggestion", "Repair generated runtime, verifier, seed, or trace behavior.")
    else:
        failure_class = ""
        recovery = ""
    return {
        "check_id": "request-driven-generated-check",
        "success": success,
        "command": generated_check["command"],
        "exit_code": generated_check.get("exit_code"),
        "stdout": generated_check.get("stdout", ""),
        "stderr": generated_check.get("stderr", ""),
        "generated_check_record": generated_check,
        "independent_verification_record": independent,
        "framework_candidate_check_record": framework_check,
        "framework_check_observation": framework_check.get("framework_check_observation", {}),
        "independent_task_records": independent.get("task_records", []),
        "positive_verifier_result": _first_task_result(independent, "positive_verifier_result"),
        "negative_verifier_result": _first_task_result(independent, "negative_verifier_result"),
        "failure_class": failure_class,
        "recovery_suggestion": recovery,
    }


def independent_verification_report_from_check(context: Any, bundle: dict[str, Any], check_record: dict[str, Any]) -> dict[str, Any]:
    independent = check_record.get("independent_verification_record", {})
    task_records = list(independent.get("task_records", []))
    positive_count = sum(1 for record in task_records if isinstance(record.get("positive_verifier_result"), dict) and record["positive_verifier_result"].get("success") is True)
    negative_count = sum(1 for record in task_records if isinstance(record.get("negative_verifier_result"), dict) and record["negative_verifier_result"].get("success") is False)
    success = bool(independent.get("success"))
    environment_id = bundle["environment_id"]
    return make_artifact(
        "IndependentVerificationReport",
        source_stage="IMPLEMENT",
        producer="framework-replay-contract-verifier",
        artifact_id=f"independent-verification-{environment_id}",
        inputs=[bundle["id"], context.artifact("TaskSet")["id"], context.artifact("VerifierPlan")["id"]],
        status="accepted" if success else "fail",
        fields={
            "report_id": f"independent-verification-{environment_id}",
            "environment_id": environment_id,
            "generated_bundle_ref": bundle["id"],
            "verifier_strategy": "framework-replay-contract-verifier-v1",
            "accepted_task_ids": list(independent.get("accepted_task_ids", [])),
            "verified_task_ids": list(independent.get("verified_task_ids", [])),
            "task_records": task_records,
            "framework_check_observation": independent.get("framework_check_observation", {}),
            "positive_record_count": positive_count,
            "negative_record_count": negative_count,
            "success": success,
            "failure_class": independent.get("failure_class", ""),
            "recovery_suggestion": independent.get("recovery_suggestion", ""),
            "source_artifact_refs": [context.artifact("TaskSet")["id"], context.artifact("VerifierPlan")["id"], bundle["id"]],
        },
    )


def run_summary(context: Any) -> dict[str, Any]:
    order = [
        "DomainPlan",
        "StrategySelection",
        "NeedSpec",
        "SourceEvidenceIndex",
        "KnowledgePack",
        "EnvironmentSpec",
        "LogicalToolGraph",
        "TaskSet",
        "SurfacePlan",
        "VerifierPlan",
        "FeasibilityReport",
        "ImplementationRequest",
        "GeneratedEnvironmentBundle",
        "IndependentVerificationReport",
        "EnvironmentPackagePlan",
        "ReleaseManifest",
    ]
    return {
        "summary_id": "request-driven-generated-run-summary",
        "artifact_flow": [
            {
                "artifact_type": name,
                "artifact_id": context.artifacts[name]["id"],
                "inputs": list(context.artifacts[name].get("inputs", [])),
                "producer": context.artifacts[name].get("producer", ""),
            }
            for name in order
            if name in context.artifacts
        ],
        "environment_id": context.artifacts.get("ReleaseManifest", {}).get("environment_id", ""),
    }


def _raw_request_document(context: Any) -> str:
    domain_plan = context.artifact("DomainPlan")
    return (
        "# Raw Request Source\n\n"
        f"run_id: {context.config.run_id}\n"
        f"environment_id: {domain_plan['domain_seed']}\n\n"
        "## Request\n\n"
        f"{domain_plan['raw_request']}\n\n"
        "## Generated Planning Notes\n\n"
        "- Build a deterministic local environment from this request.\n"
        "- Generate executable files through the configured agent backend.\n"
        "- Verify with framework-owned positive and negative replay cases.\n"
    )


def _source_root(context: Any) -> Path:
    if context.store.root:
        return context.store.root / "sources" / "request-driven" / context.artifact("DomainPlan")["domain_seed"]
    return Path(tempfile.mkdtemp(prefix="agent-world-request-source-"))


def _empty_source_index(reasons: list[str]) -> dict[str, Any]:
    return {
        "sources": [],
        "extractable_objects": [],
        "mock_boundaries": ["local files only", "no external credentials"],
        "open_questions": [{"question": reason, "blocking": True, "candidate_resolution": "Retry source planning or stop without release."} for reason in reasons],
        "rejected_sources": [{"source": "request-driven-source-strategy", "reason": reason} for reason in reasons],
    }


def _source_text(source_index: dict[str, Any], *, base_dir: Path | None) -> str:
    root = Path.cwd() if base_dir is None else Path(base_dir)
    chunks = []
    for source in source_index.get("sources", []):
        path = Path(str(source.get("uri_or_path", "")))
        if not path.is_absolute():
            path = root / path
        if path.is_file():
            chunks.append(path.read_text(encoding="utf-8", errors="replace"))
    return "\n".join(chunks)


def _state_objects(concepts: list[str]) -> list[dict[str, Any]]:
    object_ids = _state_object_ids(concepts)
    names = ["primary request record", "operation evidence log", "result summary"]
    fields = [
        ["id", "payload", "status", "notes"],
        ["id", "tool", "payload", "result"],
        ["id", "accepted", "summary", "last_tool"],
    ]
    return [
        {
            "object_id": object_id,
            "name": names[index],
            "fields": fields[index],
            "relations": object_ids[:index],
            "source_refs": [f"{RAW_REQUEST_SOURCE_ID}#concept-{index + 1}"],
        }
        for index, object_id in enumerate(object_ids)
    ]


def _operations(concepts: list[str]) -> list[dict[str, Any]]:
    object_ids = _state_object_ids(concepts)
    operation_ids = _operation_ids(concepts)
    return [
        {
            "operation_id": operation_id,
            "name": operation_id.replace("_", " "),
            "inputs": ["payload", "note"],
            "outputs": ["object"],
            "side_effects": [object_ids[min(index, len(object_ids) - 1)]],
            "source_refs": [f"{RAW_REQUEST_SOURCE_ID}#operation-{index + 1}"],
            "required_inputs": ["payload"],
            "optional_inputs": ["note"],
            "reads": object_ids[: max(1, index)],
            "writes": [object_ids[min(index, len(object_ids) - 1)]],
            "idempotency": "non_idempotent" if index < 2 else "read_only",
        }
        for index, operation_id in enumerate(operation_ids)
    ]


def _business_rules(source_index: dict[str, Any]) -> list[dict[str, Any]]:
    refs = [f"{source.get('source_id', RAW_REQUEST_SOURCE_ID)}#sha256:{source.get('version_or_hash', '')}" for source in source_index.get("sources", [])]
    refs = refs or [f"{RAW_REQUEST_SOURCE_ID}#request"]
    return [
        {"rule_id": "rule-trace-every-call", "description": "Every replayed tool call must append a structured trace record.", "source_refs": refs, "confidence": "inferred"},
        {"rule_id": "rule-mutation-needs-state-evidence", "description": "Tasks with expected state deltas must change the generated state snapshot.", "source_refs": refs, "confidence": "inferred"},
        {"rule_id": "rule-query-needs-answer-evidence", "description": "Tasks with expected answers must return the declared final answer.", "source_refs": refs, "confidence": "inferred"},
    ]


def _verifiable_fields(state_objects: list[dict[str, Any]]) -> list[str]:
    fields = []
    for item in state_objects:
        for field in item.get("fields", []):
            fields.append(f"{item['object_id']}.{field}")
    return fields


def _knowledge_source_refs(knowledge: dict[str, Any]) -> list[str]:
    refs = []
    for key in ["state_objects", "operations", "business_rules"]:
        for item in knowledge.get(key, []):
            refs.extend(str(ref) for ref in item.get("source_refs", []))
    return sorted(set(refs)) or [f"{RAW_REQUEST_SOURCE_ID}#request"]


def _parameter(name: str, *, optional: bool) -> dict[str, str]:
    return {
        "name": name,
        "classification": "optional" if optional else "external",
        "source": "user request or generated replay contract",
        "validation": "non-empty JSON-compatible value",
    }


def _natural_task_request(index: int, concepts: list[str]) -> str:
    concept = concepts[(index - 1) % len(concepts)] if concepts else "request"
    if index == 1:
        return f"Create the first accepted state change for the {concept} need."
    if index == 2:
        return f"Apply a second accepted update and keep evidence for the {concept} need."
    return f"Return the accepted summary for the {concept} need without requiring external services."


def _environment_id(text: str) -> str:
    concepts = _concepts(text)
    seed = "-".join(item.replace("_", "-") for item in concepts[:3]) or "request"
    digest = hashlib.sha1(_normalize_text(text).encode("utf-8")).hexdigest()[:8]
    return f"env-{seed}-{digest}"


def _state_object_ids(concepts: list[str]) -> list[str]:
    base = concepts[:3] or ["request", "state", "result"]
    while len(base) < 3:
        base.append(["request", "state", "result"][len(base)])
    return [f"{item}_record" for item in base[:1]] + [f"{base[1]}_evidence", f"{base[2]}_summary"]


def _operation_ids(concepts: list[str]) -> list[str]:
    base = concepts[:3] or ["request", "state", "result"]
    while len(base) < 3:
        base.append(["request", "state", "result"][len(base)])
    return [f"capture_{base[0]}", f"apply_{base[1]}", f"summarize_{base[2]}"]


def _concepts(text: str) -> list[str]:
    words = re.findall(r"[A-Za-z][A-Za-z0-9]{2,}|[\u4e00-\u9fff]{2,}", text.lower())
    stop = {
        "generate",
        "create",
        "build",
        "environment",
        "service",
        "system",
        "with",
        "and",
        "the",
        "for",
        "that",
        "this",
        "支持",
        "生成",
        "环境",
        "系统",
        "服务",
        "以及",
        "一个",
    }
    result = []
    for word in words:
        slug = _slug(word)
        if len(slug) < 3 or slug in stop or slug in result:
            continue
        result.append(slug)
        if len(result) == 6:
            break
    return result or ["request", "state", "result"]


def _sentence(text: str) -> str:
    compact = " ".join(text.split())
    return compact[:240] if compact else "Generated local environment request"


def _normalize_text(text: str) -> str:
    return " ".join(text.split()).strip().lower()


def _slug(value: str) -> str:
    ascii_text = re.sub(r"[^a-zA-Z0-9]+", "_", value).strip("_").lower()
    if ascii_text:
        return ascii_text[:32]
    digest = hashlib.sha1(value.encode("utf-8")).hexdigest()[:8]
    return f"term_{digest}"


def _bundle_artifact(
    *,
    context: Any,
    bundle_id: str,
    producer: str,
    build_dir: Path,
    generated_files: list[dict[str, Any]],
    build_check_replay_records: list[dict[str, Any]],
    status: str,
    implementation_mode: str,
    extra_inputs: list[str],
    runtime_entrypoint: str,
    verifier_entrypoint: str,
    check_commands: list[list[str]],
    replay_commands: list[list[str]],
    agent_invocation_ref: str = "",
) -> dict[str, Any]:
    fields = {
        "bundle_id": bundle_id,
        "environment_id": context.artifact("ImplementationRequest")["environment_id"],
        "source_artifact_ids": context.artifact("ImplementationRequest")["source_artifact_ids"],
        "implementation_request_id": context.artifact("ImplementationRequest")["id"],
        "build_dir": str(build_dir),
        "generated_files": generated_files,
        "runtime_entrypoint": runtime_entrypoint,
        "seed_fixture_ref": "seed_state.json",
        "verifier_entrypoint": verifier_entrypoint,
        "surface_descriptors": ["surface_descriptor.json"],
        "check_commands": check_commands,
        "replay_commands": replay_commands,
        "build_check_replay_records": build_check_replay_records,
        "implementation_mode": implementation_mode,
    }
    if agent_invocation_ref:
        fields["agent_invocation_ref"] = agent_invocation_ref
    return make_artifact(
        "GeneratedEnvironmentBundle",
        source_stage="IMPLEMENT",
        producer=producer,
        artifact_id=bundle_id,
        inputs=[context.artifact("ImplementationRequest")["id"]] + list(extra_inputs),
        status="accepted" if status == "pass" else "fail",
        fields=fields,
    )


def _bundle_check_records(check_record: dict[str, Any]) -> list[dict[str, Any]]:
    return [check_record] + list(check_record.get("independent_task_records", []))


def _first_task_result(independent_record: dict[str, Any], field: str) -> dict[str, Any]:
    for record in independent_record.get("task_records", []):
        value = record.get(field)
        if isinstance(value, dict) and value:
            return value
    return {}


def _accepted_task_ids(context: Any) -> list[str]:
    if "TaskSet" not in getattr(context, "artifacts", {}):
        return []
    return [str(task["task_id"]) for task in context.artifact("TaskSet").get("tasks", [])]


def _source_refs(context: Any) -> list[str]:
    refs = []
    for artifact_type in ["DomainPlan", "StrategySelection", "SourceEvidenceIndex", "KnowledgePack", "EnvironmentSpec", "LogicalToolGraph", "TaskSet", "VerifierPlan"]:
        if artifact_type in context.artifacts:
            refs.append(context.artifact(artifact_type)["id"])
    return refs


def _run_generated_check(command: list[str], build_dir: Path) -> dict[str, Any]:
    try:
        completed = subprocess.run(command, cwd=build_dir, text=True, capture_output=True, timeout=10, check=False)
    except Exception as exc:
        return {
            "check_id": "generated-self-check",
            "success": False,
            "command": command,
            "exit_code": None,
            "stdout": "",
            "stderr": str(exc),
            "exception": {"type": exc.__class__.__name__, "message": str(exc), "traceback": traceback.format_exc()},
            "failure_class": exc.__class__.__name__,
            "recovery_suggestion": "Generated check entrypoint could not be executed.",
        }
    parsed = _parse_check_stdout(completed.stdout)
    success = completed.returncode == 0 and parsed.get("success") is True
    return {
        "check_id": "generated-self-check",
        "success": success,
        "command": command,
        "exit_code": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "positive_verifier_result": parsed.get("positive_verifier_result", {}),
        "negative_verifier_result": parsed.get("negative_verifier_result", {}),
        "failure_class": "" if success else "generated_bundle_check_failed",
        "recovery_suggestion": "" if success else "Generated check_replay.py did not report success.",
    }


def _parse_check_stdout(stdout: str) -> dict[str, Any]:
    try:
        parsed = json.loads(stdout)
    except json.JSONDecodeError:
        parsed = None
    if isinstance(parsed, dict):
        return parsed
    for line in reversed(stdout.splitlines()):
        if not line.strip():
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _agent_failure_record(
    base: dict[str, Any],
    *,
    status: str = "fail",
    failure_class: str,
    recovery_suggestion: str,
) -> dict[str, Any]:
    return {
        **base,
        "generated_paths": [],
        "generated_file_hashes": {},
        "build_check_replay_records": [
            {
                "check_id": base["implementation_id"],
                "success": False,
                "failure_class": failure_class,
                "recovery_suggestion": recovery_suggestion,
            }
        ],
        "verifier_result": {},
        "negative_verifier_result": {},
        "status": status,
        "failure_class": failure_class,
        "recovery_suggestion": recovery_suggestion,
    }


def _agent_candidate_manifest(text: str, work_dir: Path) -> tuple[dict[str, Any], dict[str, str] | None]:
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return {}, {"failure_class": "malformed_agent_output", "recovery_suggestion": "Agent output must be a JSON candidate manifest."}
    if not isinstance(parsed, dict):
        return {}, {"failure_class": "malformed_agent_output", "recovery_suggestion": "Agent output must be a JSON object."}
    if "candidate_manifest_ref" in parsed and "generated_files" not in parsed:
        ref = str(parsed.get("candidate_manifest_ref") or "")
        path_error = _candidate_path_error(ref)
        if path_error:
            return {}, path_error
        root = Path(work_dir).resolve()
        manifest_path = (root / ref).resolve()
        if not _inside(manifest_path, root):
            return {}, {"failure_class": "path_traversal_rejected", "recovery_suggestion": "Agent candidate_manifest_ref must resolve inside the isolated workdir."}
        if not manifest_path.is_file():
            return {}, {"failure_class": "missing_candidate_manifest", "recovery_suggestion": "Agent candidate_manifest_ref does not point to a file in the isolated workdir."}
        parsed = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
    if not isinstance(parsed.get("generated_files"), list):
        return {}, {"failure_class": "missing_candidate_files", "recovery_suggestion": "Agent candidate manifest must declare generated_files."}
    return parsed, None


def _validate_agent_candidate_files(work_dir: Path, manifest: dict[str, Any]) -> dict[str, str] | None:
    candidate_root = _agent_candidate_root(work_dir, manifest)
    if isinstance(candidate_root, dict):
        return candidate_root
    root = candidate_root.resolve()
    declared: set[str] = set()
    for item in manifest.get("generated_files", []):
        if not isinstance(item, dict):
            return {"failure_class": "malformed_candidate_manifest", "recovery_suggestion": "Each generated_files item must be an object."}
        rel_text = str(item.get("path") or "")
        path_error = _candidate_path_error(rel_text)
        if path_error:
            return path_error
        expected_kind = GENERATED_FILE_KINDS.get(rel_text)
        if not expected_kind:
            return {"failure_class": "unexpected_candidate_file", "recovery_suggestion": "Agent candidate may only declare the generated bundle files."}
        if item.get("kind") != expected_kind:
            return {"failure_class": "candidate_file_kind_mismatch", "recovery_suggestion": f"Agent candidate file {rel_text} has the wrong kind."}
        actual = (candidate_root / rel_text).resolve()
        if not _inside(actual, root):
            return {"failure_class": "symlink_escape", "recovery_suggestion": "Agent candidate file resolves outside the candidate bundle directory."}
        if not actual.is_file():
            return {"failure_class": "missing_generated_file", "recovery_suggestion": f"Agent candidate file is missing: {rel_text}"}
        expected_hash = str(item.get("sha256") or "")
        if expected_hash != _sha256(actual):
            return {"failure_class": "hash_mismatch", "recovery_suggestion": f"Agent candidate file hash mismatch: {rel_text}"}
        declared.add(rel_text)
    missing = sorted(set(GENERATED_FILE_KINDS) - declared)
    if missing:
        return {"failure_class": "missing_generated_file", "recovery_suggestion": f"Agent candidate is missing required files: {missing}"}
    observed = {path.relative_to(candidate_root).as_posix() for path in candidate_root.rglob("*") if path.is_file() and not _is_python_cache_file(path)}
    extra = sorted(observed - declared)
    if extra:
        return {"failure_class": "undeclared_generated_file", "recovery_suggestion": f"Agent wrote files that were not declared in the candidate manifest: {extra}"}
    for filename in ["runtime.py", "verifier.py", "check_replay.py"]:
        text = (candidate_root / filename).read_text(encoding="utf-8")
        if "agent_world." in text:
            return {"failure_class": "framework_runtime_import", "recovery_suggestion": "Generated bundle files must be self-contained and must not import the framework package."}
    return None


def _bundle_records_from_agent_manifest(bundle_dir: Path, manifest: dict[str, Any], *, fallback_source_refs: list[str]) -> list[dict[str, Any]]:
    by_path = {str(item.get("path")): item for item in manifest.get("generated_files", []) if isinstance(item, dict)}
    records = []
    for filename, kind in GENERATED_FILE_KINDS.items():
        item = by_path[filename]
        records.append(
            {
                "path": str((bundle_dir / filename).resolve()),
                "kind": kind,
                "sha256": str(item.get("sha256") or _sha256(bundle_dir / filename)),
                "source_refs": [str(ref) for ref in item.get("source_refs", [])] or fallback_source_refs,
            }
        )
    return records


def _agent_candidate_root(work_dir: Path, manifest: dict[str, Any]) -> Path | dict[str, str]:
    work_root = Path(work_dir).resolve()
    candidate_dir = str(manifest.get("candidate_dir") or ".")
    if candidate_dir == ".":
        candidate_root = work_root
    else:
        path_error = _candidate_path_error(candidate_dir)
        if path_error:
            return path_error
        candidate_root = (work_root / candidate_dir).resolve()
    if not _inside(candidate_root, work_root):
        return {"failure_class": "path_traversal_rejected", "recovery_suggestion": "Agent candidate_dir must resolve inside the isolated workdir."}
    if not candidate_root.is_dir():
        return {"failure_class": "missing_candidate_dir", "recovery_suggestion": "Agent candidate_dir does not exist in the isolated workdir."}
    return candidate_root


def _candidate_path_error(path_text: str) -> dict[str, str] | None:
    if not path_text:
        return {"failure_class": "invalid_candidate_path", "recovery_suggestion": "Candidate paths must be non-empty relative paths."}
    if "\\" in path_text:
        return {"failure_class": "invalid_candidate_path", "recovery_suggestion": "Candidate paths must use POSIX separators."}
    path = PurePath(path_text)
    if path.is_absolute() or path_text.startswith("~"):
        return {"failure_class": "absolute_path_rejected", "recovery_suggestion": "Candidate paths must not be absolute or home-relative."}
    if any(part in {"", ".."} for part in path.parts):
        return {"failure_class": "path_traversal_rejected", "recovery_suggestion": "Candidate paths must not contain parent directory segments."}
    if "." in path.parts and path_text != ".":
        return {"failure_class": "path_traversal_rejected", "recovery_suggestion": "Candidate file paths must not contain current directory segments."}
    return None


def _is_python_cache_file(path: Path) -> bool:
    return "__pycache__" in path.parts or path.suffix in {".pyc", ".pyo"}


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
