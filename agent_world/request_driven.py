from __future__ import annotations

import hashlib
import json
import re
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path
from typing import Any

import yaml

from agent_world import library_lending
from agent_world.artifacts import GENERATED_BUNDLE_FILE_KINDS, make_artifact, stable_json
from agent_world.independent_verifier import verify_booking_generated_bundle_independent
from agent_world.request_matching import match_request_tokens
from agent_world.sources import LocalSourceConnector


BOOKING_ENVIRONMENT_ID = "booking-service-lite"
BOOKING_DETERMINISTIC_BUNDLE_ID = "bundle-booking-service-lite-generated"
BOOKING_AGENT_BUNDLE_ID = "bundle-booking-service-lite-agent-generated"
BOOKING_TASK_IDS = ["booking-task-1", "booking-task-2", "booking-task-3"]
GENERATED_FILE_KINDS = dict(GENERATED_BUNDLE_FILE_KINDS)
BOOKING_REQUIRED_STATE_OBJECTS = ["event", "seat_inventory", "seat_hold", "booking", "payment", "audit_event"]
BOOKING_REQUIRED_OPERATIONS = ["search_events", "check_availability", "hold_seats", "confirm_booking", "cancel_booking"]
BOOKING_REQUIRED_RULES = ["hold-before-confirm", "capacity-not-negative", "cancel-release-refund"]
BOOKING_DOMAIN_TOKENS = {
    "booking",
    "ticket",
    "reservation",
    "reserve",
    "seat",
    "订票",
    "票务",
    "门票",
    "预订",
    "预约",
    "座位",
    "演出",
    "航班",
}
BOOKING_SUPPORTING_TOKENS = {
    "payment",
    "cancel",
    "refund",
    "availability",
    "available",
    "hold",
    "支付",
    "取消",
    "退款",
    "余量",
    "暂占",
    "活动",
}


def domain_plan_fields(raw_request: str) -> dict[str, Any]:
    lowered = raw_request.lower()
    library_domain, library_supporting = library_lending.matches_domain(raw_request, lowered)
    if library_domain:
        return library_lending.domain_plan_fields(raw_request, matched_domain=library_domain, matched_supporting=library_supporting)
    matched_domain = _matched_tokens(raw_request, lowered, BOOKING_DOMAIN_TOKENS)
    matched_supporting = _matched_tokens(raw_request, lowered, BOOKING_SUPPORTING_TOKENS)
    matched = sorted(set(matched_domain + matched_supporting))
    if matched_domain:
        return {
            "domain_plan_id": "domain-plan-booking-service-lite",
            "raw_request": raw_request,
            "domain_seed": BOOKING_ENVIRONMENT_ID,
            "domain_intent": "Generate a local booking/ticket reservation service environment.",
            "recognized_intents": matched,
            "required_state_objects": list(BOOKING_REQUIRED_STATE_OBJECTS),
            "required_operations": list(BOOKING_REQUIRED_OPERATIONS),
            "likely_source_needs": ["local PRD notes", "CLI/tool help", "state schema", "acceptance examples"],
            "constraints": {
                "network": "not_required",
                "auth": "not_required",
                "license": "local_generated_source_packet",
                "safety": "synthetic_local_booking_state_only",
                "local_execution": True,
                "mocking_allowed": True,
            },
            "license_auth_network_security": {
                "license": "local_fixture",
                "auth_requirement": "none",
                "network_requirement": "none",
                "security_note": "Use generated local source packet; no live booking provider, payment network, or credentials.",
            },
            "planner_evidence": {
                "matched_terms": matched,
                "matched_domain_terms": matched_domain,
                "matched_supporting_terms": matched_supporting,
                "raw_request_ref": "PipelineRunConfig.raw_request",
                "strategy_family": "request_driven_booking_probe",
            },
            "planning_status": "planned",
            "blocked_reasons": [],
        }
    return {
        "domain_plan_id": "domain-plan-unsupported-request",
        "raw_request": raw_request,
        "domain_seed": "unsupported-request",
        "domain_intent": "Unsupported request for the current request-driven slice.",
        "recognized_intents": [],
        "required_state_objects": [],
        "required_operations": [],
        "likely_source_needs": [],
        "constraints": {
            "network": "not_required",
            "auth": "not_required",
            "license": "unknown",
            "safety": "blocked_before_source_discovery",
            "local_execution": True,
            "mocking_allowed": False,
        },
        "license_auth_network_security": {
            "license": "unknown",
            "auth_requirement": "none",
            "network_requirement": "none",
            "security_note": "No supported request-driven strategy selected.",
        },
        "planner_evidence": {
            "matched_terms": matched,
            "matched_domain_terms": matched_domain,
            "matched_supporting_terms": matched_supporting,
            "raw_request_ref": "PipelineRunConfig.raw_request",
        },
        "planning_status": "unsupported",
        "blocked_reasons": [
            "Only booking/ticket/reservation requests are supported by the first request-driven probe.",
            "Generic workflow terms such as cancel/refund/payment do not select booking without a booking domain term.",
        ],
    }


def _matched_tokens(raw_request: str, lowered: str, tokens: set[str]) -> list[str]:
    return match_request_tokens(raw_request, lowered, tokens)


def strategy_selection_fields(domain_plan: dict[str, Any]) -> dict[str, Any]:
    if domain_plan.get("domain_seed") == library_lending.LIBRARY_ENVIRONMENT_ID and domain_plan.get("planning_status") == "planned":
        return library_lending.strategy_selection_fields(domain_plan)
    if domain_plan.get("domain_seed") != BOOKING_ENVIRONMENT_ID or domain_plan.get("planning_status") != "planned":
        return {
            "strategy_selection_id": "strategy-selection-unsupported-request",
            "domain_plan_ref": domain_plan["id"],
            "domain_seed": domain_plan.get("domain_seed", "unsupported-request"),
            "selection_status": "unsupported",
            "selected_strategies": [],
            "source_strategy": "",
            "extraction_strategy": "",
            "synthesis_strategy": "",
            "implementation_strategy": "",
            "independent_verifier_strategy": "",
            "package_strategy": "",
            "selection_reason": "No request-driven strategy is registered for the planned domain.",
            "blocked_reasons": list(domain_plan.get("blocked_reasons", [])) or ["unsupported_domain"],
        }
    return {
        "strategy_selection_id": "strategy-selection-booking-service-lite",
        "domain_plan_ref": domain_plan["id"],
        "domain_seed": BOOKING_ENVIRONMENT_ID,
        "selection_status": "selected",
        "selected_strategies": [
            "booking-source-packet-v1",
            "booking-source-grounded-extractor-v1",
            "booking-synthesis-v1",
            "booking-generated-bundle-v1",
            "booking-independent-verifier-v1",
            "generated-runtime-package-v1",
        ],
        "source_strategy": "booking-source-packet-v1",
        "extraction_strategy": "booking-source-grounded-extractor-v1",
        "synthesis_strategy": "booking-synthesis-v1",
        "implementation_strategy": "booking-generated-bundle-v1",
        "independent_verifier_strategy": "booking-independent-verifier-v1",
        "package_strategy": "generated-runtime-package-v1",
        "selection_reason": "DomainPlan matched booking/ticket/reservation intent and selected the first request-driven booking probe.",
        "blocked_reasons": [],
    }


def need_spec_fields(domain_plan: dict[str, Any]) -> dict[str, Any]:
    if domain_plan.get("domain_seed") == library_lending.LIBRARY_ENVIRONMENT_ID:
        return library_lending.need_spec_fields(domain_plan)
    return {
        "goal": domain_plan["raw_request"],
        "target_capabilities": [
            "request-driven environment generation",
            "stateful booking workflow tool use",
            "source-grounded synthesis",
            "deterministic verification",
        ],
        "domain_seed": domain_plan["domain_seed"],
        "expected_agent_behavior": "Use customer-facing booking requests to search options, inspect availability, hold seats, confirm bookings, and cancel reservations through logical tools.",
        "constraints": dict(domain_plan["constraints"]),
        "preferred_surfaces": ["python", "cli", "http", "mcp"],
        "out_of_scope": [
            "training integration",
            "rollout",
            "reward export",
            "AWM reproduction",
            "MCP-only architecture",
            "CLI-only architecture",
            "live payment processing",
            "live travel or venue inventory",
        ],
        "human_confirmation_required": [],
        "domain_plan_ref": domain_plan["id"],
    }


def source_evidence_fields(context: Any) -> dict[str, Any]:
    selection = context.artifact("StrategySelection")
    if selection.get("selection_status") != "selected":
        return _empty_source_index(["Strategy selector did not select a source strategy."])
    env = context.config.env or {}
    if env.get("AGENT_WORLD_REQUEST_SOURCE_STRATEGY") == "none":
        return _empty_source_index(["Source strategy disabled by AGENT_WORLD_REQUEST_SOURCE_STRATEGY=none for failure-path coverage."])
    if selection.get("domain_seed") == library_lending.LIBRARY_ENVIRONMENT_ID:
        return library_lending.source_evidence_fields(context)
    paths = context.config.source_paths or _write_booking_source_packet(context)
    return LocalSourceConnector(base_dir=Path.cwd()).build_index_fields(paths)


class BookingKnowledgeExtractor:
    def __init__(self, *, base_dir: Path | None = None) -> None:
        self.base_dir = Path.cwd() if base_dir is None else Path(base_dir)

    def build_knowledge_fields(self, source_index: dict[str, Any]) -> dict[str, Any]:
        state_objects: list[dict[str, Any]] = []
        operations: list[dict[str, Any]] = []
        business_rules: list[dict[str, Any]] = []
        examples: list[dict[str, Any]] = []
        for source in source_index.get("sources", []):
            path = self._resolve(source["uri_or_path"])
            if not path.exists():
                continue
            text = path.read_text(encoding="utf-8")
            if source["kind"] == "cli_help":
                operations.extend(_operations_from_cli_help(source["source_id"], text))
            elif source["kind"] in {"database_schema", "local_files"}:
                schema_objects, rules, parsed_examples = _schema_rules_examples_from_yaml(source["source_id"], text)
                state_objects.extend(schema_objects)
                business_rules.extend(rules)
                examples.extend(parsed_examples)
            elif source["kind"] == "prd":
                rules, parsed_examples = _rules_examples_from_prd(source["source_id"], text)
                business_rules.extend(rules)
                examples.extend(parsed_examples)
        state_objects = _dedupe_by_id(state_objects, "object_id")
        operations = _dedupe_by_id(operations, "operation_id")
        business_rules = _dedupe_by_id(business_rules, "rule_id")
        return {
            "state_objects": state_objects,
            "operations": operations,
            "business_rules": business_rules,
            "verifiable_fields": _verifiable_fields(state_objects, operations),
            "uncertainties": _uncertainties(state_objects, operations, business_rules),
            "examples": examples,
        }

    def _resolve(self, uri_or_path: str) -> Path:
        path = Path(uri_or_path)
        return path if path.is_absolute() else self.base_dir / path


def knowledge_pack_fields(source_index: dict[str, Any], *, base_dir: Path | None = None) -> dict[str, Any]:
    if library_lending.is_library_source_index(source_index):
        return library_lending.knowledge_pack_fields(source_index, base_dir=base_dir)
    return BookingKnowledgeExtractor(base_dir=base_dir).build_knowledge_fields(source_index)


def environment_spec_fields(knowledge: dict[str, Any]) -> dict[str, Any]:
    if library_lending.is_library_knowledge(knowledge):
        return library_lending.environment_spec_fields(knowledge)
    return {
        "environment_id": BOOKING_ENVIRONMENT_ID,
        "domain": "local booking and ticket reservation workflow",
        "state_backend": {
            "kind": "json",
            "reset_strategy": "copy versioned JSON seed state into isolated run memory",
            "isolation_strategy": "one in-memory booking state snapshot per run",
            "seed_fixture_refs": ["fixtures/seed/booking-service-lite.json"],
        },
        "state_entities": [item["object_id"] for item in knowledge.get("state_objects", [])],
        "logical_tools": [{"tool_id": operation["operation_id"], "name": operation["name"]} for operation in knowledge.get("operations", [])],
        "permissions": {"network": False, "filesystem": "package_dir_only", "auth": False},
        "safety_boundaries": ["synthetic local booking data only", "no live payment or travel provider", "no generic shell execution surface"],
        "mock_policy": {"external_services": "mocked by local state", "payment": "synthetic status field only"},
        "release_surfaces_allowed": ["python", "cli", "http", "mcp"],
        "observability": {"logs": True, "traces": True, "state_snapshots": ["before", "after", "on_failure"]},
    }


def logical_tool_graph_fields(knowledge: dict[str, Any]) -> dict[str, Any]:
    if library_lending.is_library_knowledge(knowledge):
        return library_lending.logical_tool_graph_fields(knowledge)
    operations = knowledge.get("operations", [])
    operation_ids = {operation["operation_id"] for operation in operations}
    parameters: dict[str, dict[str, str]] = {}
    tools = []
    for operation in operations:
        required = list(operation.get("required_inputs", []))
        optional = list(operation.get("optional_inputs", []))
        for name in required:
            parameters.setdefault(name, _parameter(name, optional=False))
        for name in optional:
            parameters.setdefault(name, _parameter(name, optional=True))
        tools.append(
            {
                "tool_id": operation["operation_id"],
                "name": operation["name"],
                "input_schema": {"required": required, "optional": optional},
                "output_schema": {"type": "object"},
                "reads": list(operation.get("reads", [])),
                "writes": list(operation.get("writes", [])),
                "side_effects": list(operation.get("side_effects", [])),
                "errors": ["unknown_event", "insufficient_seats", "expired_hold", "unknown_booking", "invalid_payment_status"],
                "idempotency": operation.get("idempotency", "unknown"),
                "source_refs": list(operation.get("source_refs", [])),
            }
        )
    edge_templates = [
        ("search_events", "check_availability", "strong", "search returns event identifiers for availability checks"),
        ("check_availability", "hold_seats", "strong", "availability must be checked before a hold is placed"),
        ("hold_seats", "confirm_booking", "strong", "confirmation requires an active hold"),
        ("search_events", "cancel_booking", "weak", "search can orient the user before cancellation but is not required"),
    ]
    return {
        "tools": tools,
        "edges": [
            {"from_tool_id": source, "to_tool_id": target, "dependency_type": kind, "reason": reason}
            for source, target, kind, reason in edge_templates
            if source in operation_ids and target in operation_ids
        ],
        "parameters": list(parameters.values()),
        "forbidden_direct_access": ["state JSON path", "internal booking ids unless already user-visible", "verifier ids", "payment backend id"],
    }


def task_set_fields(graph: dict[str, Any], knowledge: dict[str, Any]) -> dict[str, Any]:
    if library_lending.is_library_knowledge(knowledge):
        return library_lending.task_set_fields(graph, knowledge)
    known_tools = {tool["tool_id"] for tool in graph.get("tools", [])}
    templates = _task_templates(knowledge)
    tasks = [task for task in templates if set(task["dependency_path"]).issubset(known_tools)]
    rejected = [
        {"candidate_id": task["task_id"], "reason": "source evidence did not provide every operation in dependency_path"}
        for task in templates
        if not set(task["dependency_path"]).issubset(known_tools)
    ]
    return {
        "tasks": tasks,
        "minimum_task_count": 3,
        "coverage": {
            "tool_ids": sorted({tool_id for task in tasks for tool_id in task["allowed_logical_tool_ids"]}),
            "capabilities": ["search", "availability_check", "seat_hold", "confirmation", "cancellation", "read_only_answer"],
            "state_entities": ["event", "seat_inventory", "seat_hold", "booking", "payment", "audit_event"],
        },
        "rejected_candidates": rejected,
    }


def surface_plan_fields(env_spec: dict[str, Any]) -> dict[str, Any]:
    if library_lending.is_library_environment(env_spec):
        return library_lending.surface_plan_fields(env_spec)
    return {
        "bindings": [
            {
                "binding_id": f"python-{tool['tool_id']}",
                "logical_tool_id": tool["tool_id"],
                "surface": "python",
                "exposure_name": f"BookingServiceLite.{tool['tool_id']}",
                "input_mapping": "same as logical tool schema",
                "output_mapping": "dict/list JSON-compatible Python objects",
                "error_mapping": "Python exception to logical error",
                "auth_context": "none",
                "state_scope": "isolated booking state snapshot",
            }
            for tool in env_spec.get("logical_tools", [])
        ],
        "surface_status": {"python": "required_for_first_slice", "cli": "planned", "http": "deferred", "mcp": "deferred"},
        "compatibility_notes": ["Published first slice verifies the Python callable surface; CLI/HTTP/MCP descriptors are retained as planned/deferred surfaces."],
    }


def verifier_plan_fields(task_set: dict[str, Any], knowledge: dict[str, Any]) -> dict[str, Any]:
    if library_lending.is_library_knowledge(knowledge):
        return library_lending.verifier_plan_fields(task_set, knowledge)
    return {
        "verifiers": [_verifier(task["task_id"], "state_query" if task["task_id"] == "booking-task-3" else "state_diff", knowledge) for task in task_set["tasks"]],
        "llm_judges": [],
    }


def feasibility_report_fields(context: Any) -> dict[str, Any]:
    if context.artifact("EnvironmentSpec").get("environment_id") == library_lending.LIBRARY_ENVIRONMENT_ID:
        return library_lending.feasibility_report_fields(context)
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
    if artifacts["EnvironmentSpec"].get("environment_id") == library_lending.LIBRARY_ENVIRONMENT_ID:
        return library_lending.implementation_request_fields(artifacts, review_records)
    return {
        "request_id": "impl-booking-service-lite-first-slice",
        "environment_id": BOOKING_ENVIRONMENT_ID,
        "source_artifact_ids": [
            artifacts["DomainPlan"]["id"],
            artifacts["StrategySelection"]["id"],
            artifacts["SourceEvidenceIndex"]["id"],
            artifacts["KnowledgePack"]["id"],
        ],
        "accepted_task_ids": [task["task_id"] for task in artifacts["TaskSet"]["tasks"]],
        "accepted_verifier_ids": [verifier["verifier_id"] for verifier in artifacts["VerifierPlan"]["verifiers"]],
        "required_surface_ids": [binding["binding_id"] for binding in artifacts["SurfacePlan"]["bindings"] if binding["surface"] == "python"],
        "package_layout_ref": "envpkg/",
        "implementation_scope": [
            "verified generated environment bundle",
            "generated Python callable booking runtime",
            "generated seed fixture",
            "generated deterministic verifier",
            "framework-owned independent verifier records",
        ],
        "non_goals": ["training integration", "rollout", "reward export", "AWM reproduction", "live payment network", "generic shell environment surface"],
        "tdd_requirements": ["source-grounded booking tasks", "positive and negative deterministic verifier examples", "forged generated check rejection"],
        "launch_check_replay_commands": ["python <generated_build_dir>/check_replay.py"],
        "review_record_refs": [record["id"] for record in review_records],
        "strategy_selection_ref": artifacts["StrategySelection"]["id"],
    }


def generated_implementation_record(context: Any, *, break_generated_file: str = "", forge_check_success: bool = False) -> dict[str, Any]:
    if context.artifact("ImplementationRequest").get("environment_id") == library_lending.LIBRARY_ENVIRONMENT_ID:
        if break_generated_file or forge_check_success:
            raise ValueError("library-lending-lite generated implementation does not support test-only break flags")
        return library_lending.generated_implementation_record(context)
    build_dir = _build_dir(context)
    task_ids = _accepted_task_ids(context)
    _write_generated_files(build_dir)
    if forge_check_success:
        _write_forged_check_replay(build_dir / "check_replay.py")
    elif break_generated_file:
        _break_generated_file(build_dir / break_generated_file)
    build_manifest = _build_manifest(
        context=context,
        build_dir=build_dir,
        bundle_id=BOOKING_DETERMINISTIC_BUNDLE_ID,
        task_ids=task_ids,
        generated_files=_generated_file_records(build_dir, source_refs=_source_refs(context), include_manifest=False),
    )
    _write_yaml(build_dir / "build_manifest.yaml", build_manifest)
    generated_files = _generated_file_records(build_dir, source_refs=_source_refs(context), include_manifest=True)
    check_record = check_booking_generated_bundle(build_dir, accepted_tasks=context.artifact("TaskSet")["tasks"])
    build_check_replay_records = _bundle_check_records(check_record)
    status = "pass" if check_record["success"] else "fail"
    bundle_artifact = _bundle_artifact(
        context=context,
        bundle_id=BOOKING_DETERMINISTIC_BUNDLE_ID,
        producer="booking-deterministic-template-codegen",
        build_dir=build_dir,
        generated_files=generated_files,
        build_check_replay_records=build_check_replay_records,
        status=status,
        implementation_mode="deterministic_template_codegen",
        extra_inputs=[],
    )
    independent_report = independent_verification_report_from_check(context, bundle_artifact, check_record)
    return {
        "implementation_id": "implementation-booking-service-lite-generated",
        "mode": "deterministic_template_codegen",
        "environment_id": BOOKING_ENVIRONMENT_ID,
        "implementation_request_id": context.artifact("ImplementationRequest")["id"],
        "generated_bundle_id": bundle_artifact["id"],
        "generated_environment_bundle": bundle_artifact,
        "independent_verification_report": independent_report,
        "generated_paths": [item["path"] for item in generated_files],
        "generated_file_hashes": {item["path"]: item["sha256"] for item in generated_files},
        "source_artifact_ids": context.artifact("ImplementationRequest")["source_artifact_ids"],
        "static_check_command": "validate generated bundle artifact, generated file hashes, and independent booking verifier",
        "test_command": f"{sys.executable} {build_dir / 'check_replay.py'}",
        "replay_command": f"{sys.executable} {build_dir / 'check_replay.py'} --task booking-task-1",
        "check_commands": [[sys.executable, str(build_dir / "check_replay.py")]],
        "replay_commands": _absolute_replay_commands(build_dir, task_ids),
        "build_check_replay_records": build_check_replay_records,
        "verifier_result": check_record.get("positive_verifier_result", {}),
        "negative_verifier_result": check_record.get("negative_verifier_result", {}),
        "status": status,
        "failure_class": "" if status == "pass" else check_record.get("failure_class", "generated_bundle_check_failed"),
        "recovery_suggestion": "" if status == "pass" else check_record.get("recovery_suggestion", "Fix generated booking files before release planning."),
    }


def write_booking_agent_candidate_files(
    build_dir: Path,
    *,
    source_refs: list[str] | None = None,
    implementation_request_id: str = "impl-booking-service-lite-first-slice",
    bundle_id: str = BOOKING_AGENT_BUNDLE_ID,
) -> dict[str, Any]:
    build_dir = Path(build_dir)
    source_refs = source_refs or ["agent-codegen-candidate"]
    _write_generated_files(build_dir)
    build_manifest = {
        "bundle_id": bundle_id,
        "environment_id": BOOKING_ENVIRONMENT_ID,
        "source_artifact_ids": source_refs,
        "implementation_request_id": implementation_request_id,
        "build_dir": ".",
        "generated_files": _generated_file_records_relative(build_dir, source_refs=source_refs, include_manifest=False),
        "runtime_entrypoint": "runtime.BookingServiceLite",
        "seed_fixture_ref": "seed_state.json",
        "verifier_entrypoint": "verifier.verify_task_completion",
        "surface_descriptors": ["surface_descriptor.json"],
        "check_commands": [["python", "check_replay.py"]],
        "replay_commands": [["python", "check_replay.py", "--task", task_id] for task_id in BOOKING_TASK_IDS],
    }
    _write_yaml(build_dir / "build_manifest.yaml", build_manifest)
    return {
        "candidate_dir": ".",
        "bundle_id": bundle_id,
        "environment_id": BOOKING_ENVIRONMENT_ID,
        "generated_files": _generated_file_records_relative(build_dir, source_refs=source_refs, include_manifest=True),
        "runtime_entrypoint": "runtime.BookingServiceLite",
        "seed_fixture_ref": "seed_state.json",
        "verifier_entrypoint": "verifier.verify_task_completion",
        "surface_descriptors": ["surface_descriptor.json"],
        "check_commands": [["python", "check_replay.py"]],
        "replay_commands": [["python", "check_replay.py", "--task", task_id] for task_id in BOOKING_TASK_IDS],
    }


def agent_generated_implementation_record(context: Any, *, agent_invocation: dict[str, Any], agent_result: Any, work_dir: Path) -> dict[str, Any]:
    work_dir = Path(work_dir)
    task_ids = _accepted_task_ids(context)
    base = {
        "implementation_id": "implementation-booking-service-lite-agent-generated",
        "mode": "agent_backed_codegen",
        "environment_id": BOOKING_ENVIRONMENT_ID,
        "implementation_request_id": context.artifact("ImplementationRequest")["id"],
        "agent_invocation_id": agent_invocation["id"],
        "agent_work_dir": str(work_dir),
        "source_artifact_ids": context.artifact("ImplementationRequest")["source_artifact_ids"],
        "static_check_command": "validate agent candidate manifest, path boundaries, generated file hashes, and independent booking verifier",
        "test_command": f"{sys.executable} {work_dir / 'check_replay.py'}",
        "replay_command": f"{sys.executable} {work_dir / 'check_replay.py'} --task booking-task-1",
        "check_commands": [[sys.executable, str(work_dir / "check_replay.py")]],
        "replay_commands": _absolute_replay_commands(work_dir, task_ids),
    }
    if agent_result.status != "pass":
        return _agent_failure_record(
            base,
            status=agent_result.status,
            failure_class=agent_result.failure_class or "agent_backend_failed",
            recovery_suggestion=agent_result.recovery_suggestion or "Fix or reconfigure the code agent backend.",
        )
    manifest, manifest_error = _agent_candidate_manifest(agent_result.text, work_dir)
    if manifest_error:
        return _agent_failure_record(base, failure_class=manifest_error["failure_class"], recovery_suggestion=manifest_error["recovery_suggestion"])
    validation_error = _validate_agent_candidate_files(work_dir, manifest)
    if validation_error:
        return _agent_failure_record(base, failure_class=validation_error["failure_class"], recovery_suggestion=validation_error["recovery_suggestion"])
    bundle_dir = _agent_candidate_root(work_dir, manifest)
    if isinstance(bundle_dir, dict):
        return _agent_failure_record(base, failure_class=bundle_dir["failure_class"], recovery_suggestion=bundle_dir["recovery_suggestion"])
    generated_files = _bundle_records_from_agent_manifest(bundle_dir, manifest, fallback_source_refs=_source_refs(context))
    check_record = check_booking_generated_bundle(bundle_dir, accepted_tasks=context.artifact("TaskSet")["tasks"])
    build_check_replay_records = _bundle_check_records(check_record)
    status = "pass" if check_record["success"] else "fail"
    check_commands = [[sys.executable, str(bundle_dir / "check_replay.py")]]
    replay_commands = _absolute_replay_commands(bundle_dir, task_ids)
    bundle_artifact = _bundle_artifact(
        context=context,
        bundle_id=str(manifest.get("bundle_id") or BOOKING_AGENT_BUNDLE_ID),
        producer="booking-agent-codegen",
        build_dir=bundle_dir,
        generated_files=generated_files,
        build_check_replay_records=build_check_replay_records,
        status=status,
        implementation_mode="agent_backed_codegen",
        extra_inputs=[agent_invocation["id"]],
        runtime_entrypoint=manifest.get("runtime_entrypoint") or "runtime.BookingServiceLite",
        verifier_entrypoint=manifest.get("verifier_entrypoint") or "verifier.verify_task_completion",
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
        "replay_command": f"{sys.executable} {bundle_dir / 'check_replay.py'} --task booking-task-1",
        "check_commands": check_commands,
        "replay_commands": replay_commands,
        "build_check_replay_records": build_check_replay_records,
        "verifier_result": check_record.get("positive_verifier_result", {}),
        "negative_verifier_result": check_record.get("negative_verifier_result", {}),
        "status": status,
        "failure_class": "" if status == "pass" else check_record.get("failure_class", "generated_bundle_check_failed"),
        "recovery_suggestion": "" if status == "pass" else check_record.get("recovery_suggestion", "Fix agent-generated booking files before release planning."),
    }


def package_plan_fields(context: Any) -> dict[str, Any]:
    if context.artifact("GeneratedEnvironmentBundle").get("environment_id") == library_lending.LIBRARY_ENVIRONMENT_ID:
        return library_lending.package_plan_fields(context)
    bundle = context.artifact("GeneratedEnvironmentBundle")
    included_ids = (
        [artifact["id"] for artifact in context.artifacts.values()]
        + ["package-booking-service-lite", "replay-booking-service-lite", "consumer-booking-service-lite", "release-booking-service-lite"]
        + [record["id"] for record in context.review_records]
        + [record["id"] for record in context.gate_records]
        + [record["implementation_id"] for record in context.build_check_replay_records]
    )
    return {
        "package_plan_id": "package-booking-service-lite",
        "environment_id": BOOKING_ENVIRONMENT_ID,
        "layout": "envpkg/",
        "included_artifact_ids": included_ids,
        "fixture_refs": ["fixtures/seed/booking-service-lite.json"],
        "static_check_refs": "request-driven S0-S11 gates plus framework independent verifier",
        "review_record_refs": [record["id"] for record in context.review_records],
        "replay_plan_ref": "replay-booking-service-lite",
        "release_manifest_ref": "release-booking-service-lite",
        "generated_bundle_ref": bundle["id"],
        "independent_verification_report_ref": context.artifact("IndependentVerificationReport")["id"],
        "consumer_output_refs": ["release/task-records.jsonl", "release/verifier-records.jsonl", "release/consumer-index.yaml", "release/generated-runtime-index.yaml"],
        "excluded_items": [
            {"item": "live booking provider", "reason": "first request-driven probe uses synthetic local state"},
            {"item": "live payment gateway", "reason": "payment is represented by deterministic local status"},
            {"item": "generic shell executor", "reason": "environment tools are logical Python callables in the first slice"},
        ],
    }


def release_manifest_fields(context: Any) -> dict[str, Any]:
    if context.artifact("GeneratedEnvironmentBundle").get("environment_id") == library_lending.LIBRARY_ENVIRONMENT_ID:
        return library_lending.release_manifest_fields(context)
    artifacts = context.artifacts | {"EnvironmentPackagePlan": context.artifact("EnvironmentPackagePlan")}
    bundle = context.artifact("GeneratedEnvironmentBundle")
    implementation_mode = bundle.get("implementation_mode", "deterministic_template_codegen")
    return {
        "release_id": "release-booking-service-lite",
        "environment_id": BOOKING_ENVIRONMENT_ID,
        "version": "0.1.0",
        "artifact_hashes": {name: artifact["hash"] for name, artifact in artifacts.items()},
        "package_layout": "envpkg/",
        "task_index": [task["task_id"] for task in context.artifact("TaskSet")["tasks"]],
        "verifier_index": [verifier["verifier_id"] for verifier in context.artifact("VerifierPlan")["verifiers"]],
        "surface_index": context.artifact("SurfacePlan")["surface_status"],
        "fixture_index": ["fixtures/seed/booking-service-lite.json"],
        "replay_contract": "checks/replay-plan.yaml",
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
            "Booking is the first request-driven acceptance probe, not proof of arbitrary-domain generation.",
            "Source packet is generated locally from the DomainPlan; default tests do not perform live network discovery.",
            "Deterministic fallback is available for regression; live code-agent generation still requires explicit backend configuration.",
            f"Implementation mode: {implementation_mode}.",
        ],
    }


def blocking_source_uncertainties(knowledge: dict[str, Any]) -> list[dict[str, Any]]:
    return [item for item in knowledge.get("uncertainties", []) if item.get("blocking")]


def check_booking_generated_bundle(
    build_dir: Path,
    *,
    accepted_tasks: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    build_dir = Path(build_dir)
    command = [sys.executable, str(build_dir / "check_replay.py")]
    generated_check = _run_generated_check(command, build_dir)
    independent = verify_booking_generated_bundle_independent(build_dir, accepted_tasks=accepted_tasks)
    positive = _first_task_result(independent, "positive_verifier_result")
    negative = _first_task_result(independent, "negative_verifier_result")
    success = generated_check["success"] and independent["success"]
    if not generated_check["success"]:
        failure_class = generated_check.get("failure_class", "generated_bundle_check_failed")
        recovery = generated_check.get("recovery_suggestion", "Regenerate or fix runtime/verifier/check files before release.")
    elif not independent["success"]:
        failure_class = independent.get("failure_class", "independent_generated_bundle_verification_failed")
        recovery = independent.get("recovery_suggestion", "Regenerate or repair generated runtime/verifier files before release.")
    else:
        failure_class = ""
        recovery = ""
    return {
        "check_id": "booking-generated-check",
        "success": success,
        "command": command,
        "exit_code": generated_check.get("exit_code"),
        "stdout": generated_check.get("stdout", ""),
        "stderr": generated_check.get("stderr", ""),
        "generated_check_record": generated_check,
        "independent_verification_record": independent,
        "framework_check_observation": independent.get("framework_check_observation", {}),
        "independent_task_records": independent.get("task_records", []),
        "positive_verifier_result": positive,
        "negative_verifier_result": negative,
        "failure_class": failure_class,
        "recovery_suggestion": recovery,
    }


def independent_verification_report_from_check(context: Any, bundle: dict[str, Any], check_record: dict[str, Any]) -> dict[str, Any]:
    independent = check_record.get("independent_verification_record", {})
    task_records = list(independent.get("task_records", []))
    positive_count = sum(1 for record in task_records if isinstance(record.get("positive_verifier_result"), dict) and record["positive_verifier_result"].get("success") is True)
    negative_count = sum(1 for record in task_records if isinstance(record.get("negative_verifier_result"), dict) and record["negative_verifier_result"].get("success") is False)
    success = bool(independent.get("success"))
    return make_artifact(
        "IndependentVerificationReport",
        source_stage="IMPLEMENT",
        producer="booking-independent-verifier-strategy",
        artifact_id="independent-verification-booking-service-lite",
        inputs=[bundle["id"], context.artifact("TaskSet")["id"], context.artifact("VerifierPlan")["id"]],
        status="accepted" if success else "fail",
        fields={
            "report_id": "independent-verification-booking-service-lite",
            "environment_id": BOOKING_ENVIRONMENT_ID,
            "generated_bundle_ref": bundle["id"],
            "verifier_strategy": "booking-independent-verifier-v1",
            "accepted_task_ids": list(independent.get("accepted_task_ids", [])),
            "verified_task_ids": list(independent.get("verified_task_ids", [])),
            "task_records": task_records,
            "framework_check_observation": independent.get("framework_check_observation", {}),
            "positive_record_count": positive_count,
            "negative_record_count": negative_count,
            "success": success,
            "failure_class": independent.get("failure_class", ""),
            "recovery_suggestion": independent.get("recovery_suggestion", ""),
            "source_artifact_refs": [
                context.artifact("TaskSet")["id"],
                context.artifact("VerifierPlan")["id"],
                context.artifact("GeneratedEnvironmentBundle")["id"] if "GeneratedEnvironmentBundle" in context.artifacts else bundle["id"],
            ],
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
        "summary_id": "request-driven-booking-run-summary",
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


def _write_booking_source_packet(context: Any) -> list[Path]:
    if context.store.root:
        root = context.store.root / "sources" / "request-driven" / BOOKING_ENVIRONMENT_ID
    else:
        root = Path(tempfile.mkdtemp(prefix="agent-world-booking-source-packet-"))
    root.mkdir(parents=True, exist_ok=True)
    prd = root / "booking_service_lite_prd.md"
    cli = root / "booking_service_lite_cli_help.txt"
    schema = root / "booking_service_lite_schema.yaml"
    prd.write_text(_source_prd(), encoding="utf-8")
    cli.write_text(_source_cli_help(), encoding="utf-8")
    schema.write_text(_source_schema_yaml(), encoding="utf-8")
    return [prd, cli, schema]


def _empty_source_index(reasons: list[str]) -> dict[str, Any]:
    return {
        "sources": [],
        "extractable_objects": [],
        "mock_boundaries": ["local files only", "no network search", "no external credentials"],
        "open_questions": [{"question": reason, "blocking": True, "candidate_resolution": "Retry source planning or stop without release."} for reason in reasons],
        "rejected_sources": [{"source": "request-driven-source-strategy", "reason": reason} for reason in reasons],
    }


def _source_prd() -> str:
    return textwrap.dedent(
        """
        # Booking Service Lite Source Packet

        This source packet describes a synthetic booking/ticket reservation service for local execution.
        It covers event search, availability checks, seat holds, booking confirmation, payment status,
        cancellation, refund status, and seat release.

        - rule: hold-before-confirm - A booking can only be confirmed from an active seat hold.
        - rule: capacity-not-negative - Available seats must never drop below zero.
        - rule: cancel-release-refund - Cancelling a confirmed booking releases seats and records a refunded payment status.

        Acceptance examples:
        - booking-task-1: customer finds a concert, checks availability, holds two seats, and confirms with authorized payment.
        - booking-task-2: customer cancels existing booking B-200 and seats are released with refund status.
        - booking-task-3: customer asks for remaining seats and price without changing state.
        """
    ).strip() + "\n"


def _source_cli_help() -> str:
    return textwrap.dedent(
        """
        booking-service-lite commands:
          search-events operation=search_events required= optional=city,kind,date reads=event writes= idempotency=read_only
          check-availability operation=check_availability required=event_id optional= reads=event,seat_inventory writes= idempotency=read_only
          hold-seats operation=hold_seats required=event_id,quantity,customer_id optional= reads=seat_inventory writes=seat_inventory,seat_hold,audit_event idempotency=non_idempotent
          confirm-booking operation=confirm_booking required=hold_id,payment_status optional= reads=seat_hold writes=booking,payment,seat_hold,audit_event idempotency=non_idempotent
          cancel-booking operation=cancel_booking required=booking_id optional=refund reads=booking,seat_inventory writes=booking,payment,seat_inventory,audit_event idempotency=idempotent
        """
    ).strip() + "\n"


def _source_schema_yaml() -> str:
    return textwrap.dedent(
        """
        state_objects:
          - object_id: event
            name: bookable event
            fields: [event_id, title, kind, city, date, price]
            relations: [seat_inventory]
          - object_id: seat_inventory
            name: available seat counter
            fields: [event_id, capacity, available]
            relations: [event]
          - object_id: seat_hold
            name: temporary seat hold
            fields: [hold_id, event_id, customer_id, quantity, status]
            relations: [event]
          - object_id: booking
            name: confirmed booking
            fields: [booking_id, event_id, customer_id, quantity, status, hold_id]
            relations: [event, seat_hold]
          - object_id: payment
            name: payment status
            fields: [payment_id, booking_id, status, amount]
            relations: [booking]
          - object_id: audit_event
            name: booking audit event
            fields: [event_type, entity_id, field, old_value, new_value, note]
            relations: [booking, seat_hold]
        business_rules:
          - rule_id: hold-before-confirm
            description: Confirmation requires an active hold and consumes the hold.
          - rule_id: capacity-not-negative
            description: Hold creation decreases available seats only when enough seats remain.
          - rule_id: cancel-release-refund
            description: Cancellation marks a booking canceled, releases seats, and records refunded payment when refund=true.
        examples:
          - example_id: booking-task-confirm
            task_id: booking-task-1
            dependency_path: [search_events, check_availability, hold_seats, confirm_booking]
          - example_id: booking-task-cancel
            task_id: booking-task-2
            dependency_path: [cancel_booking]
          - example_id: booking-task-read-only
            task_id: booking-task-3
            dependency_path: [search_events, check_availability]
        """
    ).strip() + "\n"


def _operations_from_cli_help(source_id: str, text: str) -> list[dict[str, Any]]:
    operations = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        match = re.match(r"^\s{2,}([a-z][a-z0-9-]+)\s+(.*operation=[a-z_].*)$", line)
        if not match:
            continue
        command, attrs_text = match.groups()
        attrs = _attrs(attrs_text)
        operation_id = attrs.get("operation", command.replace("-", "_"))
        writes = _csv(attrs.get("writes", ""))
        operations.append(
            {
                "operation_id": operation_id,
                "name": command.replace("-", " "),
                "inputs": _csv(attrs.get("required", "")) + _csv(attrs.get("optional", "")),
                "outputs": ["object"],
                "side_effects": writes,
                "source_refs": [f"{source_id}#L{line_no}"],
                "required_inputs": _csv(attrs.get("required", "")),
                "optional_inputs": _csv(attrs.get("optional", "")),
                "reads": _csv(attrs.get("reads", "")),
                "writes": writes,
                "idempotency": attrs.get("idempotency", "unknown"),
                "command_name": command,
            }
        )
    return operations


def _schema_rules_examples_from_yaml(source_id: str, text: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    data = yaml.safe_load(text) or {}
    state_objects = []
    for item in data.get("state_objects", []) or []:
        object_id = str(item["object_id"])
        state_objects.append(
            {
                "object_id": object_id,
                "name": str(item.get("name") or object_id.replace("_", " ")),
                "fields": [str(field) for field in item.get("fields", [])],
                "relations": [str(relation) for relation in item.get("relations", [])],
                "source_refs": [f"{source_id}#L{_line_number(text, f'object_id: {object_id}')}"],
            }
        )
    rules = []
    for item in data.get("business_rules", []) or []:
        rule_id = str(item["rule_id"])
        rules.append(
            {
                "rule_id": rule_id,
                "description": str(item.get("description", "")),
                "source_refs": [f"{source_id}#L{_line_number(text, f'rule_id: {rule_id}')}"],
                "confidence": "high",
            }
        )
    examples = []
    for item in data.get("examples", []) or []:
        example = dict(item)
        example_id = str(example["example_id"])
        example["source_refs"] = [f"{source_id}#L{_line_number(text, f'example_id: {example_id}')}"]
        examples.append(example)
    return state_objects, rules, examples


def _rules_examples_from_prd(source_id: str, text: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rules = []
    examples = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        rule = re.match(r"^\s*-\s+rule:\s+([a-z0-9-]+)\s+-\s+(.*)$", line)
        if rule:
            rules.append({"rule_id": rule.group(1), "description": rule.group(2), "source_refs": [f"{source_id}#L{line_no}"], "confidence": "high"})
            continue
        example = re.match(r"^\s*-\s+(booking-task-[0-9]+):\s+(.*)$", line)
        if example:
            examples.append({"example_id": f"prd-{example.group(1)}", "task_id": example.group(1), "description": example.group(2), "source_refs": [f"{source_id}#L{line_no}"]})
    return rules, examples


def _task_templates(knowledge: dict[str, Any]) -> list[dict[str, Any]]:
    refs = {
        str(example.get("task_id")): list(example.get("source_refs", []))
        for example in knowledge.get("examples", [])
        if isinstance(example, dict) and example.get("task_id")
    }
    return [
        {
            "task_id": "booking-task-1",
            "natural_request": "Find a Shanghai concert with seats left, reserve two seats for customer C-1, and confirm the reservation after payment is authorized.",
            "target_capability": "multi-step booking confirmation after search and availability check",
            "initial_state_refs": ["fixtures/seed/booking-service-lite.json#EVT-100"],
            "expected_state_delta": {"booking": "confirmed event=EVT-100 customer=C-1 quantity=2", "seat_inventory": "EVT-100 available decreases by 2", "payment": "authorized"},
            "expected_answer": "",
            "allowed_logical_tool_ids": ["search_events", "check_availability", "hold_seats", "confirm_booking"],
            "forbidden_leakage": ["state file path", "schema ids", "verifier ids", "payment backend id"],
            "dependency_path": ["search_events", "check_availability", "hold_seats", "confirm_booking"],
            "difficulty": {"level": "medium", "requires_state_change": True},
            "verifier_refs": ["verifier-booking-task-1"],
            "source_refs": refs.get("booking-task-1", []),
        },
        {
            "task_id": "booking-task-2",
            "natural_request": "Cancel reservation B-200 and make sure the released seat and refund status are reflected.",
            "target_capability": "cancellation with state rollback and payment status update",
            "initial_state_refs": ["fixtures/seed/booking-service-lite.json#B-200"],
            "expected_state_delta": {"booking": "B-200 status=canceled", "seat_inventory": "EVT-200 available increases by 1", "payment": "refunded"},
            "expected_answer": "",
            "allowed_logical_tool_ids": ["cancel_booking"],
            "forbidden_leakage": ["state file path", "schema ids", "verifier ids", "payment backend id"],
            "dependency_path": ["cancel_booking"],
            "difficulty": {"level": "medium", "requires_state_change": True},
            "verifier_refs": ["verifier-booking-task-2"],
            "source_refs": refs.get("booking-task-2", []),
        },
        {
            "task_id": "booking-task-3",
            "natural_request": "Tell me how many seats remain and the price for the Shanghai concert without changing any booking.",
            "target_capability": "read-only availability and price answer",
            "initial_state_refs": ["fixtures/seed/booking-service-lite.json#EVT-100"],
            "expected_state_delta": {},
            "expected_answer": {"event_id": "EVT-100", "available_seats": 4, "price": 120},
            "allowed_logical_tool_ids": ["search_events", "check_availability"],
            "forbidden_leakage": ["state file path", "schema ids", "verifier ids"],
            "dependency_path": ["search_events", "check_availability"],
            "difficulty": {"level": "easy", "requires_state_change": False},
            "verifier_refs": ["verifier-booking-task-3"],
            "source_refs": refs.get("booking-task-3", []),
        },
    ]


def _verifier(task_id: str, kind: str, knowledge: dict[str, Any]) -> dict[str, Any]:
    evidence_refs = sorted(
        {
            ref
            for collection in ["operations", "business_rules", "state_objects"]
            for item in knowledge.get(collection, [])
            for ref in item.get("source_refs", [])
        }
    )
    return {
        "verifier_id": f"verifier-{task_id}",
        "task_id": task_id,
        "kind": kind,
        "inputs": ["initial_state", "final_state", "final_answer", "surface_trace_path", "expected_dependency_path", "trace_call_group"],
        "checks": ["dependency path trace assertion", "state snapshot assertion", "target booking or read-only answer", "inventory/payment consistency"],
        "success_criteria": f"booking verifier returns success=true for {task_id} only when state or answer and dependency trace checks pass",
        "failure_criteria": "Any deterministic booking check returns false.",
        "positive_examples": [f"{task_id}: expected booking state delta or read-only answer present"],
        "negative_examples": [f"{task_id}: missing dependency path trace, state delta, payment/refund status, or expected answer"],
        "evidence_refs": evidence_refs,
        "replay_inputs": ["seed fixture", "initial snapshot", "final snapshot", "surface trace", "trace call group", "declared dependency path", "agent final answer"],
        "assertions": [
            {"assertion_id": f"assert-{task_id}", "target": "verify_task_completion.success", "operator": "equals", "expected": True, "tolerance": 0, "source_ref": "booking-independent-verifier-v1"},
            {"assertion_id": f"assert-{task_id}-path", "target": "dependency_path_trace_matches", "operator": "equals", "expected": True, "tolerance": 0, "source_ref": "booking-independent-verifier-v1"},
        ],
        "allowed_side_effects": [],
        "timeout_ms": 1000,
        "isolation_requirement": "read-only verifier over copied booking state",
        "failure_diagnostics": ["return structured failed checks"],
    }


def _uncertainties(state_objects: list[dict[str, Any]], operations: list[dict[str, Any]], rules: list[dict[str, Any]]) -> list[dict[str, Any]]:
    state_ids = {item["object_id"] for item in state_objects}
    operation_ids = {item["operation_id"] for item in operations}
    rule_ids = {item["rule_id"] for item in rules}
    uncertainties = []
    for required in BOOKING_REQUIRED_STATE_OBJECTS:
        if required not in state_ids:
            uncertainties.append({"question": f"Missing required booking schema state object evidence: {required}", "blocking": True, "candidate_resolution": "Retry source planning with schema evidence or stop before synthesis."})
    for required in BOOKING_REQUIRED_OPERATIONS:
        if required not in operation_ids:
            uncertainties.append({"question": f"Missing required booking operation evidence: {required}", "blocking": True, "candidate_resolution": "Retry source planning with CLI/API evidence or stop before task generation."})
    for required in BOOKING_REQUIRED_RULES:
        if required not in rule_ids:
            uncertainties.append({"question": f"Missing required booking business rule evidence: {required}", "blocking": True, "candidate_resolution": "Retry source planning with rule/example evidence or stop before feasibility."})
    return uncertainties


def _verifiable_fields(state_objects: list[dict[str, Any]], operations: list[dict[str, Any]]) -> list[str]:
    state_by_id = {item["object_id"]: item for item in state_objects}
    fields = set()
    for operation in operations:
        for state_id in operation.get("writes", []):
            for field in state_by_id.get(state_id, {}).get("fields", []):
                fields.add(f"{state_id}.{field}")
    for state_id in ["booking", "seat_inventory", "payment", "seat_hold", "audit_event"]:
        for field in state_by_id.get(state_id, {}).get("fields", []):
            fields.add(f"{state_id}.{field}")
    return sorted(fields)


def _parameter(name: str, *, optional: bool) -> dict[str, str]:
    return {
        "name": name,
        "classification": "internal" if name in {"event_id", "hold_id"} else ("optional" if optional else "external"),
        "source": _parameter_source(name),
        "validation": _validation(name),
    }


def _parameter_source(name: str) -> str:
    if name == "event_id":
        return "search_events/check_availability result"
    if name == "hold_id":
        return "hold_seats result"
    if name == "booking_id":
        return "user-visible booking reference"
    return "user request"


def _validation(name: str) -> str:
    if name == "quantity":
        return "positive integer no greater than available seats"
    if name == "payment_status":
        return "authorized or captured"
    if name == "refund":
        return "boolean"
    return "non-empty string"


def _attrs(value: str) -> dict[str, str]:
    result = {}
    for chunk in value.split():
        if "=" not in chunk:
            continue
        key, raw = chunk.split("=", 1)
        result[key.strip()] = raw.strip()
    return result


def _csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _line_number(text: str, needle: str) -> int:
    for line_no, line in enumerate(text.splitlines(), start=1):
        if needle in line:
            return line_no
    return 1


def _dedupe_by_id(items: list[dict[str, Any]], id_key: str) -> list[dict[str, Any]]:
    result = []
    seen = set()
    for item in items:
        item_id = item[id_key]
        if item_id in seen:
            continue
        seen.add(item_id)
        result.append(item)
    return result


def _build_dir(context: Any) -> Path:
    if context.store.root:
        return context.store.root / "build" / "generated" / BOOKING_ENVIRONMENT_ID
    return Path(tempfile.mkdtemp(prefix="agent-world-booking-generated-"))


def _write_generated_files(build_dir: Path) -> None:
    build_dir.mkdir(parents=True, exist_ok=True)
    (build_dir / "runtime.py").write_text(_runtime_py(), encoding="utf-8")
    (build_dir / "seed_state.json").write_text(stable_json(_seed_state()), encoding="utf-8")
    (build_dir / "verifier.py").write_text(_verifier_py(), encoding="utf-8")
    (build_dir / "surface_descriptor.json").write_text(stable_json(_surface_descriptor()), encoding="utf-8")
    (build_dir / "check_replay.py").write_text(_check_replay_py(), encoding="utf-8")


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
    runtime_entrypoint: str = "runtime.BookingServiceLite",
    verifier_entrypoint: str = "verifier.verify_task_completion",
    check_commands: list[list[str]] | None = None,
    replay_commands: list[list[str]] | None = None,
    agent_invocation_ref: str = "",
) -> dict[str, Any]:
    fields = {
        "bundle_id": bundle_id,
        "environment_id": BOOKING_ENVIRONMENT_ID,
        "source_artifact_ids": context.artifact("ImplementationRequest")["source_artifact_ids"],
        "implementation_request_id": context.artifact("ImplementationRequest")["id"],
        "build_dir": str(build_dir),
        "generated_files": generated_files,
        "runtime_entrypoint": runtime_entrypoint,
        "seed_fixture_ref": "seed_state.json",
        "verifier_entrypoint": verifier_entrypoint,
        "surface_descriptors": ["surface_descriptor.json"],
        "check_commands": check_commands or [[sys.executable, str(Path(build_dir) / "check_replay.py")]],
        "replay_commands": replay_commands or _absolute_replay_commands(build_dir, _accepted_task_ids(context)),
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


def _build_manifest(context: Any, build_dir: Path, bundle_id: str, task_ids: list[str], generated_files: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "bundle_id": bundle_id,
        "environment_id": BOOKING_ENVIRONMENT_ID,
        "source_artifact_ids": context.artifact("ImplementationRequest")["source_artifact_ids"],
        "implementation_request_id": context.artifact("ImplementationRequest")["id"],
        "build_dir": str(build_dir),
        "generated_files": generated_files,
        "runtime_entrypoint": "runtime.BookingServiceLite",
        "seed_fixture_ref": "seed_state.json",
        "verifier_entrypoint": "verifier.verify_task_completion",
        "surface_descriptors": ["surface_descriptor.json"],
        "check_commands": [[sys.executable, str(build_dir / "check_replay.py")]],
        "replay_commands": _absolute_replay_commands(build_dir, task_ids),
    }


def _generated_file_records(build_dir: Path, *, source_refs: list[str], include_manifest: bool) -> list[dict[str, Any]]:
    records = []
    for filename, kind in GENERATED_FILE_KINDS.items():
        if filename == "build_manifest.yaml" and not include_manifest:
            continue
        path = build_dir / filename
        records.append({"path": str(path), "kind": kind, "sha256": _sha256(path), "source_refs": source_refs})
    return records


def _generated_file_records_relative(build_dir: Path, *, source_refs: list[str], include_manifest: bool) -> list[dict[str, Any]]:
    records = []
    for filename, kind in GENERATED_FILE_KINDS.items():
        if filename == "build_manifest.yaml" and not include_manifest:
            continue
        path = build_dir / filename
        records.append({"path": filename, "kind": kind, "sha256": _sha256(path), "source_refs": source_refs})
    return records


def _absolute_replay_commands(build_dir: Path, task_ids: list[str]) -> list[list[str]]:
    return [[sys.executable, str(Path(build_dir) / "check_replay.py"), "--task", task_id] for task_id in task_ids]


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
        return list(BOOKING_TASK_IDS)
    task_ids = [str(task["task_id"]) for task in context.artifact("TaskSet").get("tasks", [])]
    return task_ids or list(BOOKING_TASK_IDS)


def _source_refs(context: Any) -> list[str]:
    refs = []
    for artifact_type in ["DomainPlan", "StrategySelection", "SourceEvidenceIndex", "KnowledgePack", "EnvironmentSpec", "LogicalToolGraph", "TaskSet", "VerifierPlan"]:
        if artifact_type in context.artifacts:
            refs.append(context.artifact(artifact_type)["id"])
    return refs


def _write_yaml(path: Path, value: Any) -> None:
    path.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")


def _break_generated_file(path: Path) -> None:
    if path.exists():
        path.write_text("raise RuntimeError('generated file intentionally broken for test')\n", encoding="utf-8")


def _write_forged_check_replay(path: Path) -> None:
    path.write_text(
        "import json\n"
        "print(json.dumps({'success': True, 'positive_verifier_result': {'success': True}, 'negative_verifier_result': {'success': False}}, sort_keys=True))\n",
        encoding="utf-8",
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _run_generated_check(command: list[str], build_dir: Path) -> dict[str, Any]:
    try:
        completed = subprocess.run(command, cwd=build_dir, text=True, capture_output=True, timeout=10, check=False)
    except Exception as exc:
        return {"check_id": "booking-generated-check", "success": False, "command": command, "exit_code": None, "stdout": "", "stderr": str(exc), "failure_class": exc.__class__.__name__, "recovery_suggestion": "Generated booking check entrypoint could not be executed."}
    parsed = _parse_check_stdout(completed.stdout)
    success = completed.returncode == 0 and parsed.get("success") is True
    return {
        "check_id": "booking-generated-check",
        "success": success,
        "command": command,
        "exit_code": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "positive_verifier_result": parsed.get("positive_verifier_result", {}),
        "negative_verifier_result": parsed.get("negative_verifier_result", {}),
        "failure_class": "" if success else "generated_bundle_check_failed",
        "recovery_suggestion": "" if success else "Regenerate or fix booking runtime/verifier/check files before release.",
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
    observed = {
        path.relative_to(candidate_root).as_posix()
        for path in candidate_root.rglob("*")
        if path.is_file() and not _is_python_cache_file(path)
    }
    extra = sorted(observed - declared)
    if extra:
        return {"failure_class": "undeclared_generated_file", "recovery_suggestion": f"Agent wrote files that were not declared in the candidate manifest: {extra}"}
    for filename in ["runtime.py", "verifier.py", "check_replay.py"]:
        text = (candidate_root / filename).read_text(encoding="utf-8")
        if "agent_world.fixtures." in text:
            return {"failure_class": "fixture_runtime_import", "recovery_suggestion": "Agent-generated booking files must not import repository fixture runtimes."}
    return None


def _is_python_cache_file(path: Path) -> bool:
    return "__pycache__" in path.parts or path.suffix in {".pyc", ".pyo"}


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
        return {"failure_class": "invalid_candidate_path", "recovery_suggestion": "Agent candidate paths must be non-empty relative paths."}
    if "\\" in path_text:
        return {"failure_class": "invalid_candidate_path", "recovery_suggestion": "Agent candidate paths must use POSIX-style relative paths."}
    path = Path(path_text)
    if path.is_absolute() or path_text.startswith("~"):
        return {"failure_class": "absolute_path_rejected", "recovery_suggestion": "Agent candidate paths must not be absolute or home-relative."}
    if any(part in {"", ".", ".."} for part in path.parts):
        return {"failure_class": "path_traversal_rejected", "recovery_suggestion": "Agent candidate paths must not contain empty, current-directory, or parent-directory segments."}
    return None


def _bundle_records_from_agent_manifest(bundle_dir: Path, manifest: dict[str, Any], *, fallback_source_refs: list[str]) -> list[dict[str, Any]]:
    by_path = {str(item["path"]): item for item in manifest["generated_files"]}
    records = []
    for filename, kind in GENERATED_FILE_KINDS.items():
        path = bundle_dir / filename
        source_refs = by_path.get(filename, {}).get("source_refs")
        if not isinstance(source_refs, list) or not source_refs:
            source_refs = fallback_source_refs
        records.append({"path": str(path), "kind": kind, "sha256": _sha256(path), "source_refs": source_refs})
    return records


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _agent_failure_record(base: dict[str, Any], *, failure_class: str, recovery_suggestion: str, status: str = "fail") -> dict[str, Any]:
    return {
        **base,
        "generated_paths": [],
        "generated_file_hashes": {},
        "build_check_replay_records": [],
        "verifier_result": {},
        "negative_verifier_result": {},
        "status": status,
        "failure_class": failure_class,
        "recovery_suggestion": recovery_suggestion,
    }


def _seed_state() -> dict[str, Any]:
    return {
        "event": [
            {"event_id": "EVT-100", "title": "Shanghai Jazz Night", "kind": "concert", "city": "Shanghai", "date": "2026-07-15", "price": 120},
            {"event_id": "EVT-200", "title": "Morning Flight 42", "kind": "flight", "city": "Beijing", "date": "2026-07-20", "price": 360},
        ],
        "seat_inventory": [
            {"event_id": "EVT-100", "capacity": 10, "available": 4},
            {"event_id": "EVT-200", "capacity": 6, "available": 1},
        ],
        "seat_hold": [],
        "booking": [
            {"booking_id": "B-200", "event_id": "EVT-200", "customer_id": "C-2", "quantity": 1, "status": "confirmed", "hold_id": "H-200"},
        ],
        "payment": [
            {"payment_id": "P-200", "booking_id": "B-200", "status": "captured", "amount": 360},
        ],
        "audit_event": [],
    }


def _surface_descriptor() -> dict[str, Any]:
    return {
        "environment_id": BOOKING_ENVIRONMENT_ID,
        "implemented_surfaces": {
            "python": {"status": "implemented", "entrypoint": "runtime.BookingServiceLite", "verified_by": "check_replay.py"},
            "cli": {"status": "deferred", "reason": "CLI help is source evidence; published CLI tool surface is planned."},
            "http": {"status": "deferred"},
            "mcp": {"status": "deferred"},
        },
    }


def _runtime_py() -> str:
    return textwrap.dedent(
        r'''
        from __future__ import annotations

        import copy
        import hashlib
        import json
        from pathlib import Path
        from typing import Any


        def load_seed_state(seed_path: Path) -> dict[str, Any]:
            return json.loads(Path(seed_path).read_text(encoding="utf-8"))


        def reset_environment(seed_state: dict[str, Any]) -> dict[str, Any]:
            return copy.deepcopy(seed_state)


        class BookingServiceLite:
            def __init__(self, state: dict[str, Any], *, trace_path: Path | None = None, task_id: str | None = None, call_group: str | None = None):
                self.state = state
                self.trace_path = Path(trace_path) if trace_path else None
                self.task_id = task_id
                self.call_group = call_group or task_id or "ad-hoc"

            def search_events(self, *, city: str | None = None, kind: str | None = None, date: str | None = None) -> list[dict[str, Any]]:
                events = [
                    copy.deepcopy(event)
                    for event in self.state["event"]
                    if (city is None or event["city"] == city)
                    and (kind is None or event["kind"] == kind)
                    and (date is None or event["date"] == date)
                ]
                self._trace("search_events", {"city": city, "kind": kind, "date": date}, {"count": len(events)})
                return events

            def check_availability(self, event_id: str) -> dict[str, Any]:
                event = _event(self.state, event_id)
                inventory = _inventory(self.state, event_id)
                result = {"event_id": event_id, "title": event["title"], "available_seats": inventory["available"], "price": event["price"]}
                self._trace("check_availability", {"event_id": event_id}, result)
                return result

            def hold_seats(self, *, event_id: str, quantity: int, customer_id: str) -> dict[str, Any]:
                inventory = _inventory(self.state, event_id)
                if quantity <= 0 or inventory["available"] < quantity:
                    raise ValueError("insufficient seats")
                old = inventory["available"]
                inventory["available"] -= quantity
                hold = {"hold_id": f"H-{len(self.state['seat_hold']) + 301}", "event_id": event_id, "customer_id": customer_id, "quantity": quantity, "status": "active"}
                self.state["seat_hold"].append(hold)
                _audit(self.state, "hold_created", hold["hold_id"], "available", old, inventory["available"], "temporary seat hold")
                self._trace("hold_seats", {"event_id": event_id, "quantity": quantity, "customer_id": customer_id}, {"hold_id": hold["hold_id"]})
                return copy.deepcopy(hold)

            def confirm_booking(self, *, hold_id: str, payment_status: str) -> dict[str, Any]:
                hold = _hold(self.state, hold_id)
                if hold["status"] != "active":
                    raise ValueError("hold is not active")
                if payment_status not in {"authorized", "captured"}:
                    raise ValueError("invalid payment status")
                hold["status"] = "confirmed"
                booking = {
                    "booking_id": f"B-{len(self.state['booking']) + 301}",
                    "event_id": hold["event_id"],
                    "customer_id": hold["customer_id"],
                    "quantity": hold["quantity"],
                    "status": "confirmed",
                    "hold_id": hold_id,
                }
                self.state["booking"].append(booking)
                amount = _event(self.state, hold["event_id"])["price"] * hold["quantity"]
                payment = {"payment_id": f"P-{len(self.state['payment']) + 301}", "booking_id": booking["booking_id"], "status": payment_status, "amount": amount}
                self.state["payment"].append(payment)
                _audit(self.state, "booking_confirmed", booking["booking_id"], "status", "", "confirmed", payment_status)
                self._trace("confirm_booking", {"hold_id": hold_id, "payment_status": payment_status}, {"booking_id": booking["booking_id"]})
                return copy.deepcopy({"booking": booking, "payment": payment})

            def cancel_booking(self, *, booking_id: str, refund: bool = True) -> dict[str, Any]:
                booking = _booking(self.state, booking_id)
                if booking["status"] == "canceled":
                    self._trace("cancel_booking", {"booking_id": booking_id, "refund": refund}, {"booking_id": booking_id, "status": "canceled"})
                    return copy.deepcopy(booking)
                old_status = booking["status"]
                booking["status"] = "canceled"
                inventory = _inventory(self.state, booking["event_id"])
                old_available = inventory["available"]
                inventory["available"] += booking["quantity"]
                payment = _payment_for_booking(self.state, booking_id)
                if payment and refund:
                    payment["status"] = "refunded"
                _audit(self.state, "booking_canceled", booking_id, "status", old_status, "canceled", "refund" if refund else "no refund")
                _audit(self.state, "seats_released", booking["event_id"], "available", old_available, inventory["available"], booking_id)
                self._trace("cancel_booking", {"booking_id": booking_id, "refund": refund}, {"booking_id": booking_id, "status": "canceled"})
                return copy.deepcopy({"booking": booking, "payment": payment, "inventory": inventory})

            def _trace(self, tool: str, inputs: dict[str, Any], output: Any) -> None:
                if not self.trace_path:
                    return
                self.trace_path.parent.mkdir(parents=True, exist_ok=True)
                record = {
                    "tool": tool,
                    "task_id": self.task_id,
                    "call_group": self.call_group,
                    "inputs": inputs,
                    "output_preview": str(output)[:500],
                    "snapshot_hash": snapshot_hash(self.state),
                }
                with self.trace_path.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps(record, sort_keys=True))
                    handle.write("\n")


        def snapshot_hash(state: dict[str, Any]) -> str:
            return hashlib.sha256(json.dumps(state, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


        def _event(state: dict[str, Any], event_id: str) -> dict[str, Any]:
            for event in state["event"]:
                if event["event_id"] == event_id:
                    return event
            raise KeyError(event_id)


        def _inventory(state: dict[str, Any], event_id: str) -> dict[str, Any]:
            for inventory in state["seat_inventory"]:
                if inventory["event_id"] == event_id:
                    return inventory
            raise KeyError(event_id)


        def _hold(state: dict[str, Any], hold_id: str) -> dict[str, Any]:
            for hold in state["seat_hold"]:
                if hold["hold_id"] == hold_id:
                    return hold
            raise KeyError(hold_id)


        def _booking(state: dict[str, Any], booking_id: str) -> dict[str, Any]:
            for booking in state["booking"]:
                if booking["booking_id"] == booking_id:
                    return booking
            raise KeyError(booking_id)


        def _payment_for_booking(state: dict[str, Any], booking_id: str) -> dict[str, Any] | None:
            for payment in state["payment"]:
                if payment["booking_id"] == booking_id:
                    return payment
            return None


        def _audit(state: dict[str, Any], event_type: str, entity_id: str, field: str, old_value: Any, new_value: Any, note: str) -> None:
            state["audit_event"].append({"event_type": event_type, "entity_id": entity_id, "field": field, "old_value": old_value, "new_value": new_value, "note": note})
        '''
    ).lstrip()


def _verifier_py() -> str:
    return textwrap.dedent(
        r'''
        from __future__ import annotations

        import json
        from pathlib import Path
        from typing import Any


        def verify_task_completion(
            task_id: str,
            initial_state: dict[str, Any],
            final_state: dict[str, Any],
            final_answer: Any = None,
            surface_trace_path: Path | None = None,
            expected_dependency_path: list[str] | None = None,
            trace_call_group: str | None = None,
        ) -> dict[str, Any]:
            checks: list[dict[str, Any]] = []

            def add(name: str, passed: bool, detail: Any) -> None:
                checks.append({"name": name, "passed": bool(passed), "detail": detail})

            expected_dependency_path = expected_dependency_path or _expected_dependency_path(task_id)
            add(
                "dependency_path_trace_matches",
                bool(surface_trace_path and expected_dependency_path and _trace_matches(surface_trace_path, task_id, expected_dependency_path, trace_call_group)),
                {"trace_path": str(surface_trace_path) if surface_trace_path else "", "expected": expected_dependency_path},
            )
            if task_id == "booking-task-1":
                booking = _matching_booking(final_state, event_id="EVT-100", customer_id="C-1", quantity=2)
                payment = _payment_for_booking(final_state, booking.get("booking_id", ""))
                add("booking_confirmed", booking.get("status") == "confirmed", booking)
                add("inventory_decremented", _inventory(final_state, "EVT-100")["available"] == _inventory(initial_state, "EVT-100")["available"] - 2, _inventory(final_state, "EVT-100"))
                add("payment_authorized", payment.get("status") == "authorized", payment)
                add("audit_written", _has_audit(final_state, "booking_confirmed"), final_state["audit_event"])
            elif task_id == "booking-task-2":
                add("booking_canceled", _booking(final_state, "B-200")["status"] == "canceled", _booking(final_state, "B-200"))
                add("inventory_released", _inventory(final_state, "EVT-200")["available"] == _inventory(initial_state, "EVT-200")["available"] + 1, _inventory(final_state, "EVT-200"))
                add("payment_refunded", _payment_for_booking(final_state, "B-200").get("status") == "refunded", _payment_for_booking(final_state, "B-200"))
                add("audit_written", _has_audit(final_state, "booking_canceled") and _has_audit(final_state, "seats_released"), final_state["audit_event"])
            elif task_id == "booking-task-3":
                expected = {"event_id": "EVT-100", "available_seats": 4, "price": 120}
                add("answer_matches", final_answer == expected, {"expected": expected, "actual": final_answer})
                add("state_unchanged", initial_state == final_state, "")
            else:
                add("known_task", False, task_id)
            return {"task_id": task_id, "success": all(check["passed"] for check in checks), "checks": checks}


        def _expected_dependency_path(task_id: str) -> list[str]:
            return {
                "booking-task-1": ["search_events", "check_availability", "hold_seats", "confirm_booking"],
                "booking-task-2": ["cancel_booking"],
                "booking-task-3": ["search_events", "check_availability"],
            }.get(task_id, [])


        def _trace_matches(trace_path: Path, task_id: str, expected: list[str], call_group: str | None) -> bool:
            if not trace_path.exists():
                return False
            records = [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines() if line.strip()]
            filtered = [record for record in records if record.get("task_id") == task_id and (call_group is None or record.get("call_group") == call_group)]
            return [record["tool"] for record in filtered] == expected


        def _inventory(state: dict[str, Any], event_id: str) -> dict[str, Any]:
            for inventory in state["seat_inventory"]:
                if inventory["event_id"] == event_id:
                    return inventory
            raise KeyError(event_id)


        def _booking(state: dict[str, Any], booking_id: str) -> dict[str, Any]:
            for booking in state["booking"]:
                if booking["booking_id"] == booking_id:
                    return booking
            raise KeyError(booking_id)


        def _matching_booking(state: dict[str, Any], *, event_id: str, customer_id: str, quantity: int) -> dict[str, Any]:
            for booking in state["booking"]:
                if booking["event_id"] == event_id and booking["customer_id"] == customer_id and booking["quantity"] == quantity:
                    return booking
            return {}


        def _payment_for_booking(state: dict[str, Any], booking_id: str) -> dict[str, Any]:
            for payment in state["payment"]:
                if payment["booking_id"] == booking_id:
                    return payment
            return {}


        def _has_audit(state: dict[str, Any], event_type: str) -> bool:
            return any(event["event_type"] == event_type for event in state["audit_event"])
        '''
    ).lstrip()


def _check_replay_py() -> str:
    return textwrap.dedent(
        r'''
        from __future__ import annotations

        import argparse
        import json
        import sys
        from pathlib import Path

        from runtime import BookingServiceLite, load_seed_state, reset_environment
        from verifier import verify_task_completion


        ROOT = Path(__file__).resolve().parent
        TASK_IDS = ["booking-task-1", "booking-task-2", "booking-task-3"]


        def main(argv: list[str] | None = None) -> int:
            parser = argparse.ArgumentParser()
            parser.add_argument("--task", choices=TASK_IDS)
            args = parser.parse_args(argv)
            seed = load_seed_state(ROOT / "seed_state.json")
            task_ids = [args.task] if args.task else TASK_IDS
            task_results = [run_task(seed, task_id) for task_id in task_ids]
            summary = {
                "success": all(item["success"] for item in task_results),
                "task_results": task_results,
                "positive_verifier_result": task_results[0]["positive_verifier_result"] if task_results else {},
                "negative_verifier_result": task_results[0]["negative_verifier_result"] if task_results else {},
            }
            print(json.dumps(summary, sort_keys=True))
            return 0 if summary["success"] else 1


        def run_task(seed: dict, task_id: str) -> dict:
            initial = reset_environment(seed)
            final = reset_environment(seed)
            trace = ROOT / f"{task_id}-positive-trace.jsonl"
            if trace.exists():
                trace.unlink()
            final_answer = execute_positive(BookingServiceLite(final, trace_path=trace, task_id=task_id, call_group="positive"), task_id)
            positive = verify_task_completion(task_id, initial, final, final_answer=final_answer, surface_trace_path=trace, trace_call_group="positive")

            negative_initial = reset_environment(seed)
            negative_final = reset_environment(seed)
            negative_trace = ROOT / f"{task_id}-negative-trace.jsonl"
            if negative_trace.exists():
                negative_trace.unlink()
            negative_answer = {"event_id": "EVT-100", "available_seats": 0, "price": 120} if task_id == "booking-task-3" else None
            negative = verify_task_completion(task_id, negative_initial, negative_final, final_answer=negative_answer, surface_trace_path=negative_trace, trace_call_group="negative")
            return {
                "task_id": task_id,
                "success": positive["success"] is True and negative["success"] is False,
                "positive_verifier_result": positive,
                "negative_verifier_result": negative,
            }


        def execute_positive(surface: BookingServiceLite, task_id: str):
            if task_id == "booking-task-1":
                events = surface.search_events(city="Shanghai", kind="concert")
                event_id = events[0]["event_id"]
                surface.check_availability(event_id)
                hold = surface.hold_seats(event_id=event_id, quantity=2, customer_id="C-1")
                surface.confirm_booking(hold_id=hold["hold_id"], payment_status="authorized")
                return None
            if task_id == "booking-task-2":
                surface.cancel_booking(booking_id="B-200", refund=True)
                return None
            events = surface.search_events(city="Shanghai", kind="concert")
            availability = surface.check_availability(events[0]["event_id"])
            return {"event_id": availability["event_id"], "available_seats": availability["available_seats"], "price": availability["price"]}


        if __name__ == "__main__":
            sys.exit(main())
        '''
    ).lstrip()
