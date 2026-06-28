from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_world.sources import (
    SUPPORT_DESK_REQUIRED_OPERATIONS,
    SUPPORT_DESK_REQUIRED_STATE_OBJECTS,
    LocalSourceConnector,
    SupportDeskLiteKnowledgeExtractor,
)


SUPPORT_DESK_LITE_PRD_PATH = Path(__file__).with_name("support_desk_lite_prd.md")


def source_evidence_fields(*, base_dir: Path | None = None, source_paths: list[Path] | None = None) -> dict[str, Any]:
    paths = source_paths or [SUPPORT_DESK_LITE_PRD_PATH]
    connector = LocalSourceConnector(base_dir=base_dir)
    return connector.build_index_fields(paths)


def knowledge_pack_fields(source_index: dict[str, Any], *, base_dir: Path | None = None) -> dict[str, Any]:
    return SupportDeskLiteKnowledgeExtractor(base_dir=base_dir).build_knowledge_fields(source_index)


def environment_spec_fields(knowledge: dict[str, Any]) -> dict[str, Any]:
    state_ids = [item["object_id"] for item in knowledge.get("state_objects", [])]
    operation_ids = [item["operation_id"] for item in knowledge.get("operations", [])]
    return {
        "environment_id": "support-desk-lite",
        "domain": "support desk ticket handling",
        "state_backend": {
            "kind": "sqlite",
            "reset_strategy": "copy versioned seed database into isolated run directory",
            "isolation_strategy": "one SQLite file per run directory",
            "seed_fixture_refs": ["fixtures/seed/support-desk-lite.sqlite"],
        },
        "state_entities": state_ids,
        "logical_tools": [{"tool_id": operation_id, "name": operation_id.replace("_", " ")} for operation_id in operation_ids],
        "permissions": {"network": False, "filesystem": "package_dir_only", "auth": False},
        "safety_boundaries": ["synthetic fixture only", "no external services", "no generic shell execution surface"],
        "mock_policy": {"external_services": "not_required", "data": "synthetic"},
        "release_surfaces_allowed": ["python", "cli", "http", "mcp"],
        "observability": {"logs": True, "traces": True, "state_snapshots": ["before", "after", "on_failure"]},
    }


def logical_tool_graph_fields(knowledge: dict[str, Any]) -> dict[str, Any]:
    operations = knowledge.get("operations", [])
    operation_ids = {operation["operation_id"] for operation in operations}
    tools = []
    parameters: dict[str, dict[str, str]] = {}
    for operation in operations:
        required_inputs = list(operation.get("required_inputs", []))
        optional_inputs = list(operation.get("optional_inputs", []))
        for parameter in required_inputs:
            parameters.setdefault(parameter, _parameter_catalog_entry(parameter, optional=False))
        for parameter in optional_inputs:
            parameters.setdefault(parameter, _parameter_catalog_entry(parameter, optional=True))
        tools.append(
            {
                "tool_id": operation["operation_id"],
                "name": operation["name"],
                "input_schema": {"required": required_inputs, "optional": optional_inputs},
                "output_schema": {"type": "object"},
                "reads": list(operation.get("reads", [])),
                "writes": list(operation.get("writes", [])),
                "side_effects": list(operation.get("side_effects", [])),
                "errors": ["unknown_ticket", "invalid_argument"],
                "idempotency": operation.get("idempotency", "unknown"),
                "source_refs": list(operation.get("source_refs", [])),
            }
        )
    edges = [
        {"from_tool_id": "search_tickets", "to_tool_id": "get_ticket", "dependency_type": "strong", "reason": "search yields ticket id for detail inspection"},
        {"from_tool_id": "get_ticket", "to_tool_id": "resolve_ticket", "dependency_type": "strong", "reason": "details determine whether resolution is appropriate"},
        {"from_tool_id": "get_ticket", "to_tool_id": "add_ticket_note", "dependency_type": "strong", "reason": "details confirm the correct ticket before adding notes"},
        {"from_tool_id": "get_ticket", "to_tool_id": "update_ticket_priority", "dependency_type": "weak", "reason": "details may justify escalation"},
        {"from_tool_id": "search_tickets", "to_tool_id": "assign_ticket", "dependency_type": "weak", "reason": "search can identify queue candidates"},
    ]
    return {
        "tools": tools,
        "edges": [edge for edge in edges if edge["from_tool_id"] in operation_ids and edge["to_tool_id"] in operation_ids],
        "parameters": list(parameters.values()),
        "forbidden_direct_access": ["sqlite file path", "table names in user request", "verifier ids"],
    }


def task_set_fields(graph: dict[str, Any]) -> dict[str, Any]:
    known_tools = {tool["tool_id"] for tool in graph.get("tools", [])}
    tasks = [task for task in _task_templates() if set(task["dependency_path"]).issubset(known_tools)]
    rejected = [
        {
            "candidate_id": task["task_id"],
            "reason": "source evidence did not provide every operation in dependency_path",
        }
        for task in _task_templates()
        if not set(task["dependency_path"]).issubset(known_tools)
    ]
    return {
        "tasks": tasks,
        "coverage": {
            "tool_ids": sorted({tool_id for task in tasks for tool_id in task["allowed_logical_tool_ids"]}),
            "capabilities": ["read", "write", "audit", "strong_dependency"],
            "state_entities": [state for state in SUPPORT_DESK_REQUIRED_STATE_OBJECTS if any(state in str(task.get("expected_state_delta", {})) for task in tasks)],
        },
        "rejected_candidates": rejected,
    }


def surface_plan_fields(env_spec: dict[str, Any]) -> dict[str, Any]:
    tool_ids = [tool["tool_id"] for tool in env_spec.get("logical_tools", [])]
    return {
        "bindings": [
            {
                "binding_id": f"python-{tool_id}",
                "logical_tool_id": tool_id,
                "surface": "python",
                "exposure_name": f"SupportDeskLite.{tool_id}",
                "input_mapping": "same as logical tool schema",
                "output_mapping": "dict/list JSON-compatible Python objects",
                "error_mapping": "Python exception to logical error",
                "auth_context": "none",
                "state_scope": "isolated SQLite file per run",
            }
            for tool_id in tool_ids
        ],
        "surface_status": {"python": "required_for_first_slice", "cli": "deferred", "http": "deferred", "mcp": "deferred"},
        "compatibility_notes": ["CLI/HTTP/MCP remain planned surfaces; Python is the only required runnable surface."],
    }


def verifier_plan_fields(task_set: dict[str, Any]) -> dict[str, Any]:
    return {
        "verifiers": [
            _verifier(task["task_id"], "state_query" if task["task_id"] == "task-4" else "state_diff")
            for task in task_set.get("tasks", [])
        ],
        "llm_judges": [],
    }


def implementation_request_fields(
    artifacts: dict[str, dict[str, Any]],
    review_records: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "request_id": "impl-support-desk-lite-first-slice",
        "environment_id": "support-desk-lite",
        "source_artifact_ids": [artifacts["SourceEvidenceIndex"]["id"], artifacts["KnowledgePack"]["id"]],
        "accepted_task_ids": [task["task_id"] for task in artifacts["TaskSet"]["tasks"]],
        "accepted_verifier_ids": [verifier["verifier_id"] for verifier in artifacts["VerifierPlan"]["verifiers"]],
        "required_surface_ids": [binding["binding_id"] for binding in artifacts["SurfacePlan"]["bindings"] if binding["surface"] == "python"],
        "package_layout_ref": "envpkg/",
        "implementation_scope": ["fixture node set", "Python callable support-desk-lite implementation", "deterministic verifier", "package assembly"],
        "non_goals": ["training integration", "rollout", "reward export", "AWM reproduction", "MCP-only architecture", "generic shell environment surface"],
        "tdd_requirements": ["schema validation", "source-grounded gates", "support-desk fixture verifier", "build/check/replay gate evidence"],
        "launch_check_replay_commands": ["python -m pytest tests/agent_world", "python -m agent_world.replay --package <package> --task task-1"],
        "review_record_refs": [record["id"] for record in review_records],
    }


def blocking_source_uncertainties(knowledge: dict[str, Any]) -> list[dict[str, Any]]:
    return [item for item in knowledge.get("uncertainties", []) if item.get("blocking")]


def missing_required_operations(knowledge: dict[str, Any]) -> list[str]:
    known = {operation["operation_id"] for operation in knowledge.get("operations", [])}
    return [operation for operation in SUPPORT_DESK_REQUIRED_OPERATIONS if operation not in known]


def _parameter_catalog_entry(name: str, *, optional: bool) -> dict[str, str]:
    return {
        "name": name,
        "classification": "internal" if name == "ticket_id" else ("optional" if optional else "external"),
        "source": _parameter_source(name, optional=optional),
        "validation": _parameter_validation(name),
    }


def _parameter_source(name: str, *, optional: bool) -> str:
    if name == "ticket_id":
        return "search_tickets/get_ticket"
    if optional:
        return "user request or task fixture"
    return "user request or agent synthesis"


def _parameter_validation(name: str) -> str:
    if name == "priority":
        return "low, medium, high, or urgent"
    if name == "visibility":
        return "internal or customer"
    if name == "ticket_id":
        return "existing ticket"
    return "non-empty string" if name not in {"status", "keyword", "customer_tier"} else "string or known enum"


def _task_templates() -> list[dict[str, Any]]:
    return [
        {
            "task_id": "task-1",
            "natural_request": "Find the VIP customer's open refund case and leave an internal note explaining the refund follow-up.",
            "target_capability": "stateful note creation",
            "initial_state_refs": ["fixtures/seed/support-desk-lite.sqlite#T-100"],
            "expected_state_delta": {"ticket_note": "internal note added to T-100", "audit_event": "note_added"},
            "expected_answer": "",
            "allowed_logical_tool_ids": ["search_tickets", "get_ticket", "add_ticket_note"],
            "forbidden_leakage": ["table names", "backend ids", "verifier ids"],
            "dependency_path": ["search_tickets", "get_ticket", "add_ticket_note"],
            "difficulty": {"level": "easy", "requires_state_change": True},
            "verifier_refs": ["verifier-task-1"],
        },
        {
            "task_id": "task-2",
            "natural_request": "Move the idle high-priority login outage case to enterprise support and assign it to iris.",
            "target_capability": "assignment update",
            "initial_state_refs": ["fixtures/seed/support-desk-lite.sqlite#T-101"],
            "expected_state_delta": {"assignment": "T-101 queue=enterprise-support assignee=iris", "audit_event": "assignment_updated"},
            "expected_answer": "",
            "allowed_logical_tool_ids": ["search_tickets", "assign_ticket"],
            "forbidden_leakage": ["table names", "backend ids", "verifier ids"],
            "dependency_path": ["search_tickets", "assign_ticket"],
            "difficulty": {"level": "medium", "requires_state_change": True},
            "verifier_refs": ["verifier-task-2"],
        },
        {
            "task_id": "task-3",
            "natural_request": "The VIP refund issue looks under-prioritized. Raise it to high priority and record why.",
            "target_capability": "priority escalation",
            "initial_state_refs": ["fixtures/seed/support-desk-lite.sqlite#T-100"],
            "expected_state_delta": {"ticket": "T-100 priority=high", "audit_event": "priority_updated"},
            "expected_answer": "",
            "allowed_logical_tool_ids": ["search_tickets", "get_ticket", "update_ticket_priority"],
            "forbidden_leakage": ["table names", "backend ids", "verifier ids"],
            "dependency_path": ["search_tickets", "get_ticket", "update_ticket_priority"],
            "difficulty": {"level": "medium", "requires_state_change": True},
            "verifier_refs": ["verifier-task-3"],
        },
        {
            "task_id": "task-4",
            "natural_request": "For Acme Corp, report how many open cases they have and the highest current priority.",
            "target_capability": "read-only aggregation",
            "initial_state_refs": ["fixtures/seed/support-desk-lite.sqlite#cust-vip"],
            "expected_state_delta": {},
            "expected_answer": {"customer_id": "cust-vip", "open_ticket_count": 2, "highest_priority": "medium"},
            "allowed_logical_tool_ids": ["search_tickets", "get_ticket"],
            "forbidden_leakage": ["table names", "backend ids", "verifier ids"],
            "dependency_path": ["search_tickets"],
            "difficulty": {"level": "easy", "requires_state_change": False},
            "verifier_refs": ["verifier-task-4"],
        },
        {
            "task_id": "task-5",
            "natural_request": "Inspect the duplicate refund confirmation case, then close it with a customer-visible resolution note.",
            "target_capability": "strong dependency state update",
            "initial_state_refs": ["fixtures/seed/support-desk-lite.sqlite#T-102"],
            "expected_state_delta": {"ticket": "T-102 status=resolved", "ticket_note": "customer-visible resolution", "audit_event": "ticket_resolved"},
            "expected_answer": "",
            "allowed_logical_tool_ids": ["search_tickets", "get_ticket", "resolve_ticket"],
            "forbidden_leakage": ["table names", "backend ids", "verifier ids"],
            "dependency_path": ["search_tickets", "get_ticket", "resolve_ticket"],
            "difficulty": {"level": "hard", "requires_state_change": True, "strong_dependency_path": True},
            "verifier_refs": ["verifier-task-5"],
        },
    ]


def _verifier(task_id: str, kind: str) -> dict[str, Any]:
    return {
        "verifier_id": f"verifier-{task_id}",
        "task_id": task_id,
        "kind": kind,
        "inputs": ["initial_db_path", "final_db_path", "final_answer", "surface_trace_path", "expected_dependency_path", "trace_call_group"],
        "checks": ["dependency path trace assertion", "state snapshot assertion", "target changed", "non-target preserved", "audit evidence"],
        "success_criteria": f"support_desk_lite.verify_task_completion({task_id!r}) returns success=true only when state checks and dependency trace checks pass",
        "failure_criteria": "Any deterministic check returns false.",
        "positive_examples": [f"{task_id}: expected mutation or answer present"],
        "negative_examples": [f"{task_id}: missing target state, audit, or declared dependency path trace"],
        "evidence_refs": ["agent_world/fixtures/support_desk_lite.py"],
        "replay_inputs": ["seed fixture", "initial snapshot", "final snapshot", "surface trace", "trace call group", "declared dependency path", "agent final answer"],
        "assertions": [
            {"assertion_id": f"assert-{task_id}", "target": "verify_task_completion.success", "operator": "equals", "expected": True, "tolerance": 0, "source_ref": "support_desk_lite.py"},
            {"assertion_id": f"assert-{task_id}-path", "target": "dependency_path_trace_matches", "operator": "equals", "expected": True, "tolerance": 0, "source_ref": "support_desk_lite.py"},
        ],
        "allowed_side_effects": [],
        "timeout_ms": 1000,
        "isolation_requirement": "read-only verifier over copied SQLite files",
        "failure_diagnostics": ["return structured failed checks"],
    }
