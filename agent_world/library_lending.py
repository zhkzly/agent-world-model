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

from agent_world.artifacts import GENERATED_BUNDLE_FILE_KINDS, make_artifact, stable_json
from agent_world.independent_verifier import verify_library_generated_bundle_independent
from agent_world.request_matching import match_request_tokens
from agent_world.sources import LocalSourceConnector


LIBRARY_ENVIRONMENT_ID = "library-lending-lite"
LIBRARY_DETERMINISTIC_BUNDLE_ID = "bundle-library-lending-lite-generated"
LIBRARY_TASK_IDS = ["library-task-1", "library-task-2", "library-task-3"]
GENERATED_FILE_KINDS = dict(GENERATED_BUNDLE_FILE_KINDS)
LIBRARY_REQUIRED_STATE_OBJECTS = ["book", "book_inventory", "patron", "loan", "fine", "audit_event"]
LIBRARY_REQUIRED_OPERATIONS = ["search_books", "check_availability", "borrow_book", "return_book"]
LIBRARY_REQUIRED_RULES = ["available-before-borrow", "return-restores-availability", "overdue-fine-assessed"]
LIBRARY_DOMAIN_TOKENS = {"library", "book", "loan", "borrow", "图书馆", "图书", "书籍", "借阅", "借书", "还书"}
LIBRARY_SUPPORTING_TOKENS = {"return", "fine", "available", "inventory", "归还", "罚金", "库存", "可用", "逾期"}


def matches_domain(raw_request: str, lowered: str) -> tuple[list[str], list[str]]:
    domain = match_request_tokens(raw_request, lowered, LIBRARY_DOMAIN_TOKENS)
    supporting = match_request_tokens(raw_request, lowered, LIBRARY_SUPPORTING_TOKENS)
    return domain, supporting


def domain_plan_fields(raw_request: str, *, matched_domain: list[str], matched_supporting: list[str]) -> dict[str, Any]:
    matched = sorted(set(matched_domain + matched_supporting))
    return {
        "domain_plan_id": "domain-plan-library-lending-lite",
        "raw_request": raw_request,
        "domain_seed": LIBRARY_ENVIRONMENT_ID,
        "domain_intent": "Generate a local library lending and return management environment.",
        "recognized_intents": matched,
        "required_state_objects": list(LIBRARY_REQUIRED_STATE_OBJECTS),
        "required_operations": list(LIBRARY_REQUIRED_OPERATIONS),
        "likely_source_needs": ["local PRD notes", "CLI/tool help", "state schema", "acceptance examples"],
        "constraints": {
            "network": "not_required",
            "auth": "not_required",
            "license": "local_generated_source_packet",
            "safety": "synthetic_local_library_state_only",
            "local_execution": True,
            "mocking_allowed": True,
        },
        "license_auth_network_security": {
            "license": "local_fixture",
            "auth_requirement": "none",
            "network_requirement": "none",
            "security_note": "Use generated local source packet; no live library system or patron credentials.",
        },
        "planner_evidence": {
            "matched_terms": matched,
            "matched_domain_terms": matched_domain,
            "matched_supporting_terms": matched_supporting,
            "raw_request_ref": "PipelineRunConfig.raw_request",
            "strategy_family": "request_driven_library_probe",
        },
        "planning_status": "planned",
        "blocked_reasons": [],
    }


def strategy_selection_fields(domain_plan: dict[str, Any]) -> dict[str, Any]:
    return {
        "strategy_selection_id": "strategy-selection-library-lending-lite",
        "domain_plan_ref": domain_plan["id"],
        "domain_seed": LIBRARY_ENVIRONMENT_ID,
        "selection_status": "selected",
        "selected_strategies": [
            "library-source-packet-v1",
            "library-source-grounded-extractor-v1",
            "library-synthesis-v1",
            "library-generated-bundle-v1",
            "library-independent-verifier-v1",
            "generated-runtime-package-v1",
        ],
        "source_strategy": "library-source-packet-v1",
        "extraction_strategy": "library-source-grounded-extractor-v1",
        "synthesis_strategy": "library-synthesis-v1",
        "implementation_strategy": "library-generated-bundle-v1",
        "independent_verifier_strategy": "library-independent-verifier-v1",
        "package_strategy": "generated-runtime-package-v1",
        "selection_reason": "DomainPlan matched library/book/loan intent and selected the request-driven library probe.",
        "blocked_reasons": [],
    }


def need_spec_fields(domain_plan: dict[str, Any]) -> dict[str, Any]:
    return {
        "goal": domain_plan["raw_request"],
        "target_capabilities": ["request-driven environment generation", "stateful library workflow tool use", "source-grounded synthesis", "deterministic verification"],
        "domain_seed": LIBRARY_ENVIRONMENT_ID,
        "expected_agent_behavior": "Use patron-facing library requests to search books, check available copies, borrow books, return loans, and account for overdue fines.",
        "constraints": dict(domain_plan["constraints"]),
        "preferred_surfaces": ["python", "cli", "http", "mcp"],
        "out_of_scope": [
            "training integration",
            "rollout",
            "reward export",
            "AWM reproduction",
            "MCP-only architecture",
            "CLI-only architecture",
            "live library system",
            "patron PII",
            "generic shell surface",
        ],
        "human_confirmation_required": [],
        "domain_plan_ref": domain_plan["id"],
    }


def source_evidence_fields(context: Any) -> dict[str, Any]:
    paths = context.config.source_paths or _write_library_source_packet(context)
    return LocalSourceConnector(base_dir=Path.cwd()).build_index_fields(paths)


def knowledge_pack_fields(source_index: dict[str, Any], *, base_dir: Path | None = None) -> dict[str, Any]:
    base = Path.cwd() if base_dir is None else Path(base_dir)
    state_objects: list[dict[str, Any]] = []
    operations: list[dict[str, Any]] = []
    business_rules: list[dict[str, Any]] = []
    examples: list[dict[str, Any]] = []
    for source in source_index.get("sources", []):
        path = Path(source["uri_or_path"])
        path = path if path.is_absolute() else base / path
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
    return {
        "state_objects": _dedupe_by_id(state_objects, "object_id"),
        "operations": _dedupe_by_id(operations, "operation_id"),
        "business_rules": _dedupe_by_id(business_rules, "rule_id"),
        "verifiable_fields": _verifiable_fields(state_objects, operations),
        "uncertainties": _uncertainties(state_objects, operations, business_rules),
        "examples": examples,
    }


def environment_spec_fields(knowledge: dict[str, Any]) -> dict[str, Any]:
    return {
        "environment_id": LIBRARY_ENVIRONMENT_ID,
        "domain": "local library lending and return workflow",
        "state_backend": {
            "kind": "json",
            "reset_strategy": "copy versioned JSON seed state into isolated run memory",
            "isolation_strategy": "one in-memory library state snapshot per run",
            "seed_fixture_refs": ["fixtures/seed/library-lending-lite.json"],
        },
        "state_entities": [item["object_id"] for item in knowledge.get("state_objects", [])],
        "logical_tools": [{"tool_id": operation["operation_id"], "name": operation["name"]} for operation in knowledge.get("operations", [])],
        "permissions": {"network": False, "filesystem": "package_dir_only", "auth": False},
        "safety_boundaries": ["synthetic local library data only", "no patron PII", "no generic shell execution surface"],
        "mock_policy": {"external_services": "mocked by local state", "fines": "synthetic status field only"},
        "release_surfaces_allowed": ["python", "cli", "http", "mcp"],
        "observability": {"logs": True, "traces": True, "state_snapshots": ["before", "after", "on_failure"]},
    }


def logical_tool_graph_fields(knowledge: dict[str, Any]) -> dict[str, Any]:
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
                "errors": ["unknown_book", "no_available_copy", "unknown_loan", "already_returned"],
                "idempotency": operation.get("idempotency", "unknown"),
                "source_refs": list(operation.get("source_refs", [])),
            }
        )
    edge_templates = [
        ("search_books", "check_availability", "strong", "search returns book identifiers for availability checks"),
        ("check_availability", "borrow_book", "strong", "availability must be checked before borrowing"),
        ("borrow_book", "return_book", "weak", "returning depends on an active loan created earlier or already visible to user"),
    ]
    return {
        "tools": tools,
        "edges": [
            {"from_tool_id": source, "to_tool_id": target, "dependency_type": kind, "reason": reason}
            for source, target, kind, reason in edge_templates
            if source in operation_ids and target in operation_ids
        ],
        "parameters": list(parameters.values()),
        "forbidden_direct_access": ["state JSON path", "internal verifier ids", "patron backend id"],
    }


def task_set_fields(graph: dict[str, Any], knowledge: dict[str, Any]) -> dict[str, Any]:
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
            "capabilities": ["search", "availability_check", "borrow", "return", "fine_assessment", "read_only_answer"],
            "state_entities": list(LIBRARY_REQUIRED_STATE_OBJECTS),
        },
        "rejected_candidates": rejected,
    }


def surface_plan_fields(env_spec: dict[str, Any]) -> dict[str, Any]:
    return {
        "bindings": [
            {
                "binding_id": f"python-{tool['tool_id']}",
                "logical_tool_id": tool["tool_id"],
                "surface": "python",
                "exposure_name": f"LibraryLendingLite.{tool['tool_id']}",
                "input_mapping": "same as logical tool schema",
                "output_mapping": "dict/list JSON-compatible Python objects",
                "error_mapping": "Python exception to logical error",
                "auth_context": "none",
                "state_scope": "isolated library state snapshot",
            }
            for tool in env_spec.get("logical_tools", [])
        ],
        "surface_status": {"python": "required_for_first_slice", "cli": "planned", "http": "deferred", "mcp": "deferred"},
        "compatibility_notes": ["Published first slice verifies the Python callable surface; CLI/HTTP/MCP descriptors are retained as planned/deferred surfaces."],
    }


def verifier_plan_fields(task_set: dict[str, Any], knowledge: dict[str, Any]) -> dict[str, Any]:
    return {"verifiers": [_verifier(task["task_id"], "state_query" if task["task_id"] == "library-task-3" else "state_diff", knowledge) for task in task_set["tasks"]], "llm_judges": []}


def feasibility_report_fields(context: Any) -> dict[str, Any]:
    blockers = [item for item in context.artifact("KnowledgePack").get("uncertainties", []) if item.get("blocking")]
    return {
        "status": "pass" if not blockers else "needs_human",
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
    return {
        "request_id": "impl-library-lending-lite-first-slice",
        "environment_id": LIBRARY_ENVIRONMENT_ID,
        "source_artifact_ids": [artifacts[name]["id"] for name in ["DomainPlan", "StrategySelection", "SourceEvidenceIndex", "KnowledgePack"]],
        "accepted_task_ids": [task["task_id"] for task in artifacts["TaskSet"]["tasks"]],
        "accepted_verifier_ids": [verifier["verifier_id"] for verifier in artifacts["VerifierPlan"]["verifiers"]],
        "required_surface_ids": [binding["binding_id"] for binding in artifacts["SurfacePlan"]["bindings"] if binding["surface"] == "python"],
        "package_layout_ref": "envpkg/",
        "implementation_scope": ["verified generated environment bundle", "generated Python callable library runtime", "generated seed fixture", "generated deterministic verifier", "framework-owned independent verifier records"],
        "non_goals": ["training integration", "live library system", "patron PII", "generic shell environment surface"],
        "tdd_requirements": ["source-grounded library tasks", "positive and negative deterministic verifier examples", "forged generated check rejection"],
        "launch_check_replay_commands": ["python <generated_build_dir>/check_replay.py"],
        "review_record_refs": [record["id"] for record in review_records],
        "strategy_selection_ref": artifacts["StrategySelection"]["id"],
    }


def generated_implementation_record(context: Any) -> dict[str, Any]:
    build_dir = _build_dir(context)
    task_ids = [task["task_id"] for task in context.artifact("TaskSet")["tasks"]]
    _write_generated_files(build_dir)
    build_manifest = _build_manifest(context, build_dir, task_ids, _generated_file_records(build_dir, source_refs=_source_refs(context), include_manifest=False))
    _write_yaml(build_dir / "build_manifest.yaml", build_manifest)
    generated_files = _generated_file_records(build_dir, source_refs=_source_refs(context), include_manifest=True)
    check_record = check_library_generated_bundle(build_dir, accepted_tasks=context.artifact("TaskSet")["tasks"])
    records = [check_record] + list(check_record.get("independent_task_records", []))
    status = "pass" if check_record["success"] else "fail"
    bundle = _bundle_artifact(context, build_dir, generated_files, records, status)
    independent_report = independent_verification_report_from_check(context, bundle, check_record)
    return {
        "implementation_id": "implementation-library-lending-lite-generated",
        "mode": "deterministic_template_codegen",
        "environment_id": LIBRARY_ENVIRONMENT_ID,
        "implementation_request_id": context.artifact("ImplementationRequest")["id"],
        "generated_bundle_id": bundle["id"],
        "generated_environment_bundle": bundle,
        "independent_verification_report": independent_report,
        "generated_paths": [item["path"] for item in generated_files],
        "generated_file_hashes": {item["path"]: item["sha256"] for item in generated_files},
        "source_artifact_ids": context.artifact("ImplementationRequest")["source_artifact_ids"],
        "static_check_command": "validate generated bundle artifact, generated file hashes, and independent library verifier",
        "test_command": f"{sys.executable} {build_dir / 'check_replay.py'}",
        "replay_command": f"{sys.executable} {build_dir / 'check_replay.py'} --task library-task-1",
        "check_commands": [[sys.executable, str(build_dir / "check_replay.py")]],
        "replay_commands": [[sys.executable, str(build_dir / "check_replay.py"), "--task", task_id] for task_id in task_ids],
        "build_check_replay_records": records,
        "verifier_result": check_record.get("positive_verifier_result", {}),
        "negative_verifier_result": check_record.get("negative_verifier_result", {}),
        "status": status,
        "failure_class": "" if status == "pass" else check_record.get("failure_class", "generated_bundle_check_failed"),
        "recovery_suggestion": "" if status == "pass" else check_record.get("recovery_suggestion", "Fix generated library files before release planning."),
    }


def package_plan_fields(context: Any) -> dict[str, Any]:
    bundle = context.artifact("GeneratedEnvironmentBundle")
    included_ids = (
        [artifact["id"] for artifact in context.artifacts.values()]
        + ["package-library-lending-lite", "replay-library-lending-lite", "consumer-library-lending-lite", "release-library-lending-lite"]
        + [record["id"] for record in context.review_records]
        + [record["id"] for record in context.gate_records]
        + [record["implementation_id"] for record in context.build_check_replay_records]
    )
    return {
        "package_plan_id": "package-library-lending-lite",
        "environment_id": LIBRARY_ENVIRONMENT_ID,
        "layout": "envpkg/",
        "included_artifact_ids": included_ids,
        "fixture_refs": ["fixtures/seed/library-lending-lite.json"],
        "static_check_refs": "request-driven S0-S11 gates plus framework independent verifier",
        "review_record_refs": [record["id"] for record in context.review_records],
        "replay_plan_ref": "replay-library-lending-lite",
        "release_manifest_ref": "release-library-lending-lite",
        "generated_bundle_ref": bundle["id"],
        "independent_verification_report_ref": context.artifact("IndependentVerificationReport")["id"],
        "consumer_output_refs": ["release/task-records.jsonl", "release/verifier-records.jsonl", "release/consumer-index.yaml", "release/generated-runtime-index.yaml"],
        "excluded_items": [{"item": "live library system", "reason": "first slice uses synthetic local state"}, {"item": "generic shell executor", "reason": "environment tools are logical Python callables"}],
    }


def release_manifest_fields(context: Any) -> dict[str, Any]:
    artifacts = context.artifacts | {"EnvironmentPackagePlan": context.artifact("EnvironmentPackagePlan")}
    bundle = context.artifact("GeneratedEnvironmentBundle")
    implementation_mode = bundle.get("implementation_mode", "deterministic_template_codegen")
    return {
        "release_id": "release-library-lending-lite",
        "environment_id": LIBRARY_ENVIRONMENT_ID,
        "version": "0.1.0",
        "artifact_hashes": {name: artifact["hash"] for name, artifact in artifacts.items()},
        "package_layout": "envpkg/",
        "task_index": [task["task_id"] for task in context.artifact("TaskSet")["tasks"]],
        "verifier_index": [verifier["verifier_id"] for verifier in context.artifact("VerifierPlan")["verifiers"]],
        "surface_index": context.artifact("SurfacePlan")["surface_status"],
        "fixture_index": ["fixtures/seed/library-lending-lite.json"],
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
            "Library lending is a second request-driven strategy, not proof of arbitrary-domain generation.",
            "Source packet is generated locally from the DomainPlan; default tests do not perform live network discovery.",
            f"Implementation mode: {implementation_mode}.",
        ],
    }


def check_library_generated_bundle(build_dir: Path, *, accepted_tasks: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    build_dir = Path(build_dir)
    command = [sys.executable, str(build_dir / "check_replay.py")]
    generated_check = _run_generated_check(command, build_dir)
    independent = verify_library_generated_bundle_independent(build_dir, accepted_tasks=accepted_tasks)
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
        "check_id": "library-generated-check",
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
        producer="library-independent-verifier-strategy",
        artifact_id="independent-verification-library-lending-lite",
        inputs=[bundle["id"], context.artifact("TaskSet")["id"], context.artifact("VerifierPlan")["id"]],
        status="accepted" if success else "fail",
        fields={
            "report_id": "independent-verification-library-lending-lite",
            "environment_id": LIBRARY_ENVIRONMENT_ID,
            "generated_bundle_ref": bundle["id"],
            "verifier_strategy": "library-independent-verifier-v1",
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


def is_library_knowledge(knowledge: dict[str, Any]) -> bool:
    return any(operation.get("operation_id") == "search_books" for operation in knowledge.get("operations", []))


def is_library_source_index(source_index: dict[str, Any]) -> bool:
    text = json.dumps(source_index, ensure_ascii=False)
    return "library_lending_lite" in text or "library-lending-lite" in text


def is_library_environment(env_spec: dict[str, Any]) -> bool:
    return env_spec.get("environment_id") == LIBRARY_ENVIRONMENT_ID


def _write_library_source_packet(context: Any) -> list[Path]:
    root = context.store.root / "sources" / "request-driven" / LIBRARY_ENVIRONMENT_ID if context.store.root else Path(tempfile.mkdtemp(prefix="agent-world-library-source-packet-"))
    root.mkdir(parents=True, exist_ok=True)
    prd = root / "library_lending_lite_prd.md"
    cli = root / "library_lending_lite_cli_help.txt"
    schema = root / "library_lending_lite_schema.yaml"
    prd.write_text(_source_prd(), encoding="utf-8")
    cli.write_text(_source_cli_help(), encoding="utf-8")
    schema.write_text(_source_schema_yaml(), encoding="utf-8")
    return [prd, cli, schema]


def _source_prd() -> str:
    return textwrap.dedent(
        """
        # Library Lending Lite Source Packet

        This source packet describes a synthetic library lending service for local execution.
        It covers book search, copy availability, borrowing, returns, overdue fine assessment,
        and read-only availability answers.

        - rule: available-before-borrow - A patron can borrow a book only when an available copy exists.
        - rule: return-restores-availability - Returning an active loan increases the available copy count.
        - rule: overdue-fine-assessed - Returning a loan with days_late > 0 creates a fine at 5 units per late day.

        Acceptance examples:
        - library-task-1: patron searches for a distributed systems book, checks availability, and borrows one copy.
        - library-task-2: patron returns existing loan L-200 two days late and a fine is assessed.
        - library-task-3: patron asks for remaining copies and title without changing state.
        """
    ).strip() + "\n"


def _source_cli_help() -> str:
    return textwrap.dedent(
        """
        library-lending-lite commands:
          search-books operation=search_books required= optional=keyword,author reads=book writes= idempotency=read_only
          check-availability operation=check_availability required=book_id optional= reads=book,book_inventory writes= idempotency=read_only
          borrow-book operation=borrow_book required=book_id,patron_id optional= reads=book_inventory,patron writes=book_inventory,loan,audit_event idempotency=non_idempotent
          return-book operation=return_book required=loan_id optional=days_late reads=loan,book_inventory writes=loan,book_inventory,fine,audit_event idempotency=idempotent
        """
    ).strip() + "\n"


def _source_schema_yaml() -> str:
    return textwrap.dedent(
        """
        state_objects:
          - object_id: book
            name: library book
            fields: [book_id, title, author, genre]
            relations: [book_inventory]
          - object_id: book_inventory
            name: available copy counter
            fields: [book_id, total, available]
            relations: [book]
          - object_id: patron
            name: library patron
            fields: [patron_id, name, status]
            relations: [loan]
          - object_id: loan
            name: book loan
            fields: [loan_id, book_id, patron_id, status, days_late]
            relations: [book, patron]
          - object_id: fine
            name: overdue fine
            fields: [fine_id, loan_id, amount, status]
            relations: [loan]
          - object_id: audit_event
            name: library audit event
            fields: [event_type, entity_id, field, old_value, new_value, note]
            relations: [loan, fine]
        business_rules:
          - rule_id: available-before-borrow
            description: Borrowing decreases available copies only when at least one copy remains.
          - rule_id: return-restores-availability
            description: Returning an active loan marks it returned and increases available copies.
          - rule_id: overdue-fine-assessed
            description: Returning a loan with days_late > 0 creates a fine at 5 units per late day.
        examples:
          - example_id: library-task-borrow
            task_id: library-task-1
            dependency_path: [search_books, check_availability, borrow_book]
          - example_id: library-task-return
            task_id: library-task-2
            dependency_path: [return_book]
          - example_id: library-task-read-only
            task_id: library-task-3
            dependency_path: [search_books, check_availability]
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
        state_objects.append({"object_id": object_id, "name": str(item.get("name") or object_id), "fields": [str(field) for field in item.get("fields", [])], "relations": [str(relation) for relation in item.get("relations", [])], "source_refs": [f"{source_id}#L{_line_number(text, f'object_id: {object_id}')}"]})
    rules = []
    for item in data.get("business_rules", []) or []:
        rule_id = str(item["rule_id"])
        rules.append({"rule_id": rule_id, "description": str(item.get("description", "")), "source_refs": [f"{source_id}#L{_line_number(text, f'rule_id: {rule_id}')}"], "confidence": "high"})
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
        example = re.match(r"^\s*-\s+(library-task-[0-9]+):\s+(.*)$", line)
        if example:
            examples.append({"example_id": f"prd-{example.group(1)}", "task_id": example.group(1), "description": example.group(2), "source_refs": [f"{source_id}#L{line_no}"]})
    return rules, examples


def _task_templates(knowledge: dict[str, Any]) -> list[dict[str, Any]]:
    refs = {str(example.get("task_id")): list(example.get("source_refs", [])) for example in knowledge.get("examples", []) if isinstance(example, dict) and example.get("task_id")}
    return [
        {
            "task_id": "library-task-1",
            "natural_request": "Find the distributed systems book, check that a copy is available, and borrow it for patron P-1.",
            "target_capability": "multi-step library borrowing after search and availability check",
            "initial_state_refs": ["fixtures/seed/library-lending-lite.json#BK-100"],
            "expected_state_delta": {"loan": "active book=BK-100 patron=P-1", "book_inventory": "BK-100 available decreases by 1"},
            "expected_answer": "",
            "allowed_logical_tool_ids": ["search_books", "check_availability", "borrow_book"],
            "forbidden_leakage": ["state file path", "schema ids", "verifier ids"],
            "dependency_path": ["search_books", "check_availability", "borrow_book"],
            "difficulty": {"level": "medium", "requires_state_change": True},
            "verifier_refs": ["verifier-library-task-1"],
            "source_refs": refs.get("library-task-1", []),
        },
        {
            "task_id": "library-task-2",
            "natural_request": "Return loan L-200 two days late and make sure the copy is available again and the fine is recorded.",
            "target_capability": "return workflow with inventory restoration and fine assessment",
            "initial_state_refs": ["fixtures/seed/library-lending-lite.json#L-200"],
            "expected_state_delta": {"loan": "L-200 status=returned", "book_inventory": "BK-200 available increases by 1", "fine": "amount=10"},
            "expected_answer": "",
            "allowed_logical_tool_ids": ["return_book"],
            "forbidden_leakage": ["state file path", "schema ids", "verifier ids"],
            "dependency_path": ["return_book"],
            "difficulty": {"level": "medium", "requires_state_change": True},
            "verifier_refs": ["verifier-library-task-2"],
            "source_refs": refs.get("library-task-2", []),
        },
        {
            "task_id": "library-task-3",
            "natural_request": "Tell me the title and available copies for the distributed systems book without changing any loans.",
            "target_capability": "read-only book availability answer",
            "initial_state_refs": ["fixtures/seed/library-lending-lite.json#BK-100"],
            "expected_state_delta": {},
            "expected_answer": {"book_id": "BK-100", "available_copies": 2, "title": "Distributed Systems"},
            "allowed_logical_tool_ids": ["search_books", "check_availability"],
            "forbidden_leakage": ["state file path", "schema ids", "verifier ids"],
            "dependency_path": ["search_books", "check_availability"],
            "difficulty": {"level": "easy", "requires_state_change": False},
            "verifier_refs": ["verifier-library-task-3"],
            "source_refs": refs.get("library-task-3", []),
        },
    ]


def _verifier(task_id: str, kind: str, knowledge: dict[str, Any]) -> dict[str, Any]:
    evidence_refs = sorted({ref for collection in ["operations", "business_rules", "state_objects"] for item in knowledge.get(collection, []) for ref in item.get("source_refs", [])})
    return {
        "verifier_id": f"verifier-{task_id}",
        "task_id": task_id,
        "kind": kind,
        "inputs": ["initial_state", "final_state", "final_answer", "surface_trace_path", "expected_dependency_path", "trace_call_group"],
        "checks": ["dependency path trace assertion", "state snapshot assertion", "loan/fine or read-only answer"],
        "success_criteria": f"library verifier returns success=true for {task_id} only when state or answer and dependency trace checks pass",
        "failure_criteria": "Any deterministic library check returns false.",
        "positive_examples": [f"{task_id}: expected library state delta or read-only answer present"],
        "negative_examples": [f"{task_id}: missing dependency path trace, state delta, fine, inventory update, or expected answer"],
        "evidence_refs": evidence_refs,
        "replay_inputs": ["seed fixture", "initial snapshot", "final snapshot", "surface trace", "trace call group", "declared dependency path", "agent final answer"],
        "assertions": [
            {"assertion_id": f"assert-{task_id}", "target": "verify_task_completion.success", "operator": "equals", "expected": True, "tolerance": 0, "source_ref": "library-independent-verifier-v1"},
            {"assertion_id": f"assert-{task_id}-path", "target": "dependency_path_trace_matches", "operator": "equals", "expected": True, "tolerance": 0, "source_ref": "library-independent-verifier-v1"},
        ],
        "allowed_side_effects": [],
        "timeout_ms": 1000,
        "isolation_requirement": "read-only verifier over copied library state",
        "failure_diagnostics": ["return structured failed checks"],
    }


def _uncertainties(state_objects: list[dict[str, Any]], operations: list[dict[str, Any]], rules: list[dict[str, Any]]) -> list[dict[str, Any]]:
    state_ids = {item["object_id"] for item in state_objects}
    operation_ids = {item["operation_id"] for item in operations}
    rule_ids = {item["rule_id"] for item in rules}
    uncertainties = []
    for required in LIBRARY_REQUIRED_STATE_OBJECTS:
        if required not in state_ids:
            uncertainties.append({"question": f"Missing required library schema state object evidence: {required}", "blocking": True, "candidate_resolution": "Retry source planning with schema evidence or stop before synthesis."})
    for required in LIBRARY_REQUIRED_OPERATIONS:
        if required not in operation_ids:
            uncertainties.append({"question": f"Missing required library operation evidence: {required}", "blocking": True, "candidate_resolution": "Retry source planning with CLI/API evidence or stop before task generation."})
    for required in LIBRARY_REQUIRED_RULES:
        if required not in rule_ids:
            uncertainties.append({"question": f"Missing required library business rule evidence: {required}", "blocking": True, "candidate_resolution": "Retry source planning with rule/example evidence or stop before feasibility."})
    return uncertainties


def _verifiable_fields(state_objects: list[dict[str, Any]], operations: list[dict[str, Any]]) -> list[str]:
    state_by_id = {item["object_id"]: item for item in state_objects}
    fields = set()
    for operation in operations:
        for state_id in operation.get("writes", []):
            for field in state_by_id.get(state_id, {}).get("fields", []):
                fields.add(f"{state_id}.{field}")
    for state_id in LIBRARY_REQUIRED_STATE_OBJECTS:
        for field in state_by_id.get(state_id, {}).get("fields", []):
            fields.add(f"{state_id}.{field}")
    return sorted(fields)


def _parameter(name: str, *, optional: bool) -> dict[str, str]:
    source = "search_books/check_availability result" if name == "book_id" else ("user-visible loan reference" if name == "loan_id" else "user request")
    validation = "non-negative integer" if name == "days_late" else "non-empty string"
    return {"name": name, "classification": "internal" if name == "book_id" else ("optional" if optional else "external"), "source": source, "validation": validation}


def _attrs(value: str) -> dict[str, str]:
    result = {}
    for chunk in value.split():
        if "=" in chunk:
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
    return context.store.root / "build" / "generated" / LIBRARY_ENVIRONMENT_ID if context.store.root else Path(tempfile.mkdtemp(prefix="agent-world-library-generated-"))


def _write_generated_files(build_dir: Path) -> None:
    build_dir.mkdir(parents=True, exist_ok=True)
    (build_dir / "runtime.py").write_text(_runtime_py(), encoding="utf-8")
    (build_dir / "seed_state.json").write_text(stable_json(_seed_state()), encoding="utf-8")
    (build_dir / "verifier.py").write_text(_verifier_py(), encoding="utf-8")
    (build_dir / "surface_descriptor.json").write_text(stable_json(_surface_descriptor()), encoding="utf-8")
    (build_dir / "check_replay.py").write_text(_check_replay_py(), encoding="utf-8")


def _bundle_artifact(context: Any, build_dir: Path, generated_files: list[dict[str, Any]], records: list[dict[str, Any]], status: str) -> dict[str, Any]:
    return make_artifact(
        "GeneratedEnvironmentBundle",
        source_stage="IMPLEMENT",
        producer="library-deterministic-template-codegen",
        artifact_id=LIBRARY_DETERMINISTIC_BUNDLE_ID,
        inputs=[context.artifact("ImplementationRequest")["id"]],
        status="accepted" if status == "pass" else "fail",
        fields={
            "bundle_id": LIBRARY_DETERMINISTIC_BUNDLE_ID,
            "environment_id": LIBRARY_ENVIRONMENT_ID,
            "source_artifact_ids": context.artifact("ImplementationRequest")["source_artifact_ids"],
            "implementation_request_id": context.artifact("ImplementationRequest")["id"],
            "build_dir": str(build_dir),
            "generated_files": generated_files,
            "runtime_entrypoint": "runtime.LibraryLendingLite",
            "seed_fixture_ref": "seed_state.json",
            "verifier_entrypoint": "verifier.verify_task_completion",
            "surface_descriptors": ["surface_descriptor.json"],
            "check_commands": [[sys.executable, str(build_dir / "check_replay.py")]],
            "replay_commands": [[sys.executable, str(build_dir / "check_replay.py"), "--task", task_id] for task_id in LIBRARY_TASK_IDS],
            "build_check_replay_records": records,
            "implementation_mode": "deterministic_template_codegen",
        },
    )


def _build_manifest(context: Any, build_dir: Path, task_ids: list[str], generated_files: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "bundle_id": LIBRARY_DETERMINISTIC_BUNDLE_ID,
        "environment_id": LIBRARY_ENVIRONMENT_ID,
        "source_artifact_ids": context.artifact("ImplementationRequest")["source_artifact_ids"],
        "implementation_request_id": context.artifact("ImplementationRequest")["id"],
        "build_dir": str(build_dir),
        "generated_files": generated_files,
        "runtime_entrypoint": "runtime.LibraryLendingLite",
        "seed_fixture_ref": "seed_state.json",
        "verifier_entrypoint": "verifier.verify_task_completion",
        "surface_descriptors": ["surface_descriptor.json"],
        "check_commands": [[sys.executable, str(build_dir / "check_replay.py")]],
        "replay_commands": [[sys.executable, str(build_dir / "check_replay.py"), "--task", task_id] for task_id in task_ids],
    }


def _generated_file_records(build_dir: Path, *, source_refs: list[str], include_manifest: bool) -> list[dict[str, Any]]:
    records = []
    for filename, kind in GENERATED_FILE_KINDS.items():
        if filename == "build_manifest.yaml" and not include_manifest:
            continue
        path = build_dir / filename
        records.append({"path": str(path), "kind": kind, "sha256": _sha256(path), "source_refs": source_refs})
    return records


def _source_refs(context: Any) -> list[str]:
    return [context.artifact(name)["id"] for name in ["DomainPlan", "StrategySelection", "SourceEvidenceIndex", "KnowledgePack", "EnvironmentSpec", "LogicalToolGraph", "TaskSet", "VerifierPlan"] if name in context.artifacts]


def _write_yaml(path: Path, value: Any) -> None:
    path.write_text(yaml.safe_dump(value, sort_keys=False), encoding="utf-8")


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
        return {"check_id": "library-generated-check", "success": False, "command": command, "exit_code": None, "stdout": "", "stderr": str(exc), "failure_class": exc.__class__.__name__, "recovery_suggestion": "Generated library check entrypoint could not be executed."}
    parsed = _parse_check_stdout(completed.stdout)
    success = completed.returncode == 0 and parsed.get("success") is True
    return {
        "check_id": "library-generated-check",
        "success": success,
        "command": command,
        "exit_code": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "positive_verifier_result": parsed.get("positive_verifier_result", {}),
        "negative_verifier_result": parsed.get("negative_verifier_result", {}),
        "failure_class": "" if success else "generated_bundle_check_failed",
        "recovery_suggestion": "" if success else "Regenerate or fix library runtime/verifier/check files before release.",
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


def _first_task_result(independent_record: dict[str, Any], field: str) -> dict[str, Any]:
    for record in independent_record.get("task_records", []):
        value = record.get(field)
        if isinstance(value, dict) and value:
            return value
    return {}


def _seed_state() -> dict[str, Any]:
    return {
        "book": [
            {"book_id": "BK-100", "title": "Distributed Systems", "author": "Tanenbaum", "genre": "computer-science"},
            {"book_id": "BK-200", "title": "Data Pipelines", "author": "Stone", "genre": "data"},
        ],
        "book_inventory": [
            {"book_id": "BK-100", "total": 3, "available": 2},
            {"book_id": "BK-200", "total": 2, "available": 0},
        ],
        "patron": [{"patron_id": "P-1", "name": "Ada", "status": "active"}],
        "loan": [{"loan_id": "L-200", "book_id": "BK-200", "patron_id": "P-1", "status": "active", "days_late": 0}],
        "fine": [],
        "audit_event": [],
    }


def _surface_descriptor() -> dict[str, Any]:
    return {
        "environment_id": LIBRARY_ENVIRONMENT_ID,
        "implemented_surfaces": {
            "python": {"status": "implemented", "entrypoint": "runtime.LibraryLendingLite", "verified_by": "check_replay.py"},
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
        import json
        from pathlib import Path
        from typing import Any


        def load_seed_state(seed_path: Path) -> dict[str, Any]:
            return json.loads(Path(seed_path).read_text(encoding="utf-8"))


        def reset_environment(seed_state: dict[str, Any]) -> dict[str, Any]:
            return copy.deepcopy(seed_state)


        class LibraryLendingLite:
            def __init__(self, state: dict[str, Any], *, trace_path: Path | None = None, task_id: str | None = None, call_group: str | None = None):
                self.state = state
                self.trace_path = Path(trace_path) if trace_path else None
                self.task_id = task_id
                self.call_group = call_group or task_id or "ad-hoc"

            def search_books(self, *, keyword: str | None = None, author: str | None = None) -> list[dict[str, Any]]:
                keyword_lower = (keyword or "").lower()
                books = [
                    copy.deepcopy(book)
                    for book in self.state["book"]
                    if (not keyword_lower or keyword_lower in book["title"].lower() or keyword_lower in book["genre"].lower())
                    and (author is None or book["author"] == author)
                ]
                self._trace("search_books", {"keyword": keyword, "author": author}, {"count": len(books)})
                return books

            def check_availability(self, book_id: str) -> dict[str, Any]:
                book = _book(self.state, book_id)
                inventory = _inventory(self.state, book_id)
                result = {"book_id": book_id, "title": book["title"], "available_copies": inventory["available"]}
                self._trace("check_availability", {"book_id": book_id}, result)
                return result

            def borrow_book(self, *, book_id: str, patron_id: str) -> dict[str, Any]:
                _patron(self.state, patron_id)
                inventory = _inventory(self.state, book_id)
                if inventory["available"] <= 0:
                    raise ValueError("no available copy")
                old = inventory["available"]
                inventory["available"] -= 1
                loan = {"loan_id": f"L-{len(self.state['loan']) + 301}", "book_id": book_id, "patron_id": patron_id, "status": "active", "days_late": 0}
                self.state["loan"].append(loan)
                _audit(self.state, "loan_created", loan["loan_id"], "available", old, inventory["available"], "borrowed")
                self._trace("borrow_book", {"book_id": book_id, "patron_id": patron_id}, {"loan_id": loan["loan_id"]})
                return copy.deepcopy(loan)

            def return_book(self, *, loan_id: str, days_late: int = 0) -> dict[str, Any]:
                loan = _loan(self.state, loan_id)
                if loan["status"] == "returned":
                    self._trace("return_book", {"loan_id": loan_id, "days_late": days_late}, {"loan_id": loan_id, "status": "returned"})
                    return copy.deepcopy(loan)
                loan["status"] = "returned"
                loan["days_late"] = days_late
                inventory = _inventory(self.state, loan["book_id"])
                old = inventory["available"]
                inventory["available"] += 1
                _audit(self.state, "loan_returned", loan_id, "status", "active", "returned", f"days_late={days_late}")
                _audit(self.state, "copy_released", loan["book_id"], "available", old, inventory["available"], loan_id)
                fine = None
                if days_late > 0:
                    fine = {"fine_id": f"F-{len(self.state['fine']) + 301}", "loan_id": loan_id, "amount": days_late * 5, "status": "assessed"}
                    self.state["fine"].append(fine)
                    _audit(self.state, "fine_assessed", fine["fine_id"], "amount", 0, fine["amount"], loan_id)
                self._trace("return_book", {"loan_id": loan_id, "days_late": days_late}, {"loan_id": loan_id, "fine": fine})
                return copy.deepcopy({"loan": loan, "fine": fine})

            def _trace(self, tool: str, arguments: dict[str, Any], result: Any) -> None:
                if not self.trace_path:
                    return
                self.trace_path.parent.mkdir(parents=True, exist_ok=True)
                with self.trace_path.open("a", encoding="utf-8") as handle:
                    handle.write(json.dumps({"task_id": self.task_id, "call_group": self.call_group, "tool": tool, "arguments": arguments, "result": result}, sort_keys=True) + "\n")


        def _book(state: dict[str, Any], book_id: str) -> dict[str, Any]:
            for book in state["book"]:
                if book["book_id"] == book_id:
                    return book
            raise KeyError(book_id)


        def _inventory(state: dict[str, Any], book_id: str) -> dict[str, Any]:
            for inventory in state["book_inventory"]:
                if inventory["book_id"] == book_id:
                    return inventory
            raise KeyError(book_id)


        def _patron(state: dict[str, Any], patron_id: str) -> dict[str, Any]:
            for patron in state["patron"]:
                if patron["patron_id"] == patron_id:
                    return patron
            raise KeyError(patron_id)


        def _loan(state: dict[str, Any], loan_id: str) -> dict[str, Any]:
            for loan in state["loan"]:
                if loan["loan_id"] == loan_id:
                    return loan
            raise KeyError(loan_id)


        def _audit(state: dict[str, Any], event_type: str, entity_id: str, field: str, old_value: Any, new_value: Any, note: str) -> None:
            state["audit_event"].append({"event_type": event_type, "entity_id": entity_id, "field": field, "old_value": old_value, "new_value": new_value, "note": note})
        '''
    ).strip() + "\n"


def _verifier_py() -> str:
    return textwrap.dedent(
        r'''
        from __future__ import annotations

        import json
        from pathlib import Path
        from typing import Any


        def verify_task_completion(task_id: str, initial_state: dict[str, Any], final_state: dict[str, Any], *, final_answer: Any = None, surface_trace_path: Path | None = None, expected_dependency_path: list[str] | None = None, trace_call_group: str | None = None) -> dict[str, Any]:
            checks = []
            expected_dependency_path = expected_dependency_path or _default_path(task_id)
            checks.append(_check("dependency_path_trace_matches", _trace_tools(surface_trace_path, task_id, trace_call_group) == expected_dependency_path, {"expected": expected_dependency_path, "trace_path": str(surface_trace_path) if surface_trace_path else ""}))
            if task_id == "library-task-1":
                loan = _matching_loan(final_state, "BK-100", "P-1")
                checks.append(_check("loan_created", loan.get("status") == "active", loan))
                checks.append(_check("inventory_decremented", _inventory(final_state, "BK-100").get("available") == _inventory(initial_state, "BK-100").get("available") - 1, _inventory(final_state, "BK-100")))
                checks.append(_check("audit_written", _has_audit(final_state, "loan_created"), final_state.get("audit_event", [])))
            elif task_id == "library-task-2":
                loan = _loan(final_state, "L-200")
                fine = _fine(final_state, "L-200")
                checks.append(_check("loan_returned", loan.get("status") == "returned", loan))
                checks.append(_check("inventory_restored", _inventory(final_state, "BK-200").get("available") == _inventory(initial_state, "BK-200").get("available") + 1, _inventory(final_state, "BK-200")))
                checks.append(_check("fine_assessed", fine.get("amount") == 10 and fine.get("status") == "assessed", fine))
                checks.append(_check("audit_written", _has_audit(final_state, "loan_returned") and _has_audit(final_state, "fine_assessed"), final_state.get("audit_event", [])))
            elif task_id == "library-task-3":
                expected = {"book_id": "BK-100", "available_copies": 2, "title": "Distributed Systems"}
                checks.append(_check("answer_matches", final_answer == expected, {"expected": expected, "actual": final_answer}))
                checks.append(_check("state_unchanged", initial_state == final_state, ""))
            else:
                checks.append(_check("known_task", False, task_id))
            return {"task_id": task_id, "success": all(item["passed"] for item in checks), "checks": checks}


        def _trace_tools(path: Path | None, task_id: str, call_group: str | None) -> list[str]:
            if not path or not Path(path).exists():
                return []
            tools = []
            for line in Path(path).read_text(encoding="utf-8").splitlines():
                record = json.loads(line)
                if record.get("task_id") == task_id and record.get("call_group") in {call_group, None, ""}:
                    tools.append(record.get("tool"))
            return tools


        def _default_path(task_id: str) -> list[str]:
            return {"library-task-1": ["search_books", "check_availability", "borrow_book"], "library-task-2": ["return_book"], "library-task-3": ["search_books", "check_availability"]}.get(task_id, [])


        def _matching_loan(state: dict[str, Any], book_id: str, patron_id: str) -> dict[str, Any]:
            for loan in state.get("loan", []):
                if loan.get("book_id") == book_id and loan.get("patron_id") == patron_id:
                    return loan
            return {}


        def _loan(state: dict[str, Any], loan_id: str) -> dict[str, Any]:
            for loan in state.get("loan", []):
                if loan.get("loan_id") == loan_id:
                    return loan
            return {}


        def _inventory(state: dict[str, Any], book_id: str) -> dict[str, Any]:
            for inventory in state.get("book_inventory", []):
                if inventory.get("book_id") == book_id:
                    return inventory
            return {}


        def _fine(state: dict[str, Any], loan_id: str) -> dict[str, Any]:
            for fine in state.get("fine", []):
                if fine.get("loan_id") == loan_id:
                    return fine
            return {}


        def _has_audit(state: dict[str, Any], event_type: str) -> bool:
            return any(event.get("event_type") == event_type for event in state.get("audit_event", []))


        def _check(name: str, passed: bool, detail: Any) -> dict[str, Any]:
            return {"name": name, "passed": bool(passed), "detail": detail}
        '''
    ).strip() + "\n"


def _check_replay_py() -> str:
    return textwrap.dedent(
        r'''
        from __future__ import annotations

        import argparse
        import json
        from pathlib import Path

        import runtime
        import verifier

        ROOT = Path(__file__).resolve().parent


        def run_task(task_id: str) -> dict:
            seed = runtime.load_seed_state(ROOT / "seed_state.json")
            initial = runtime.reset_environment(seed)
            final = runtime.reset_environment(seed)
            trace = ROOT / f"{task_id}-positive-trace.jsonl"
            if trace.exists():
                trace.unlink()
            env = runtime.LibraryLendingLite(final, trace_path=trace, task_id=task_id, call_group="positive")
            final_answer = None
            if task_id == "library-task-1":
                books = env.search_books(keyword="distributed")
                availability = env.check_availability(books[0]["book_id"])
                env.borrow_book(book_id=availability["book_id"], patron_id="P-1")
            elif task_id == "library-task-2":
                env.return_book(loan_id="L-200", days_late=2)
            elif task_id == "library-task-3":
                books = env.search_books(keyword="distributed")
                availability = env.check_availability(books[0]["book_id"])
                final_answer = {"book_id": availability["book_id"], "available_copies": availability["available_copies"], "title": availability["title"]}
            else:
                raise SystemExit(f"unknown task: {task_id}")
            positive = verifier.verify_task_completion(task_id, initial, final, final_answer=final_answer, surface_trace_path=trace, trace_call_group="positive")
            negative_trace = ROOT / f"{task_id}-negative-trace.jsonl"
            if negative_trace.exists():
                negative_trace.unlink()
            negative_answer = {"book_id": "BK-100", "available_copies": 0, "title": "Distributed Systems"} if task_id == "library-task-3" else None
            negative = verifier.verify_task_completion(task_id, initial, runtime.reset_environment(seed), final_answer=negative_answer, surface_trace_path=negative_trace, trace_call_group="negative")
            return {"task_id": task_id, "success": positive["success"] and not negative["success"], "positive_verifier_result": positive, "negative_verifier_result": negative}


        def main() -> None:
            parser = argparse.ArgumentParser()
            parser.add_argument("--task", default="")
            args = parser.parse_args()
            tasks = [args.task] if args.task else ["library-task-1", "library-task-2", "library-task-3"]
            results = [run_task(task_id) for task_id in tasks]
            print(json.dumps({"success": all(item["success"] for item in results), "task_results": results, "positive_verifier_result": results[0]["positive_verifier_result"], "negative_verifier_result": results[0]["negative_verifier_result"]}, sort_keys=True))


        if __name__ == "__main__":
            main()
        '''
    ).strip() + "\n"
