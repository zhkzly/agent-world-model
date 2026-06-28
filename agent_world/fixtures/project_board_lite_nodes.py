from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

from agent_world.fixtures.project_board_lite_codegen import project_board_generated_implementation_record
from agent_world.gates import STAGE_GATES
from agent_world.sources import LocalSourceConnector


PROJECT_BOARD_LITE_CLI_HELP_PATH = Path(__file__).with_name("project_board_lite_cli_help.txt")
PROJECT_BOARD_LITE_SCHEMA_PATH = Path(__file__).with_name("project_board_lite_schema.yaml")
PROJECT_BOARD_LITE_EXAMPLES_PATH = Path(__file__).with_name("project_board_lite_examples.yaml")
PROJECT_BOARD_SOURCE_PATHS = [
    PROJECT_BOARD_LITE_CLI_HELP_PATH,
    PROJECT_BOARD_LITE_SCHEMA_PATH,
    PROJECT_BOARD_LITE_EXAMPLES_PATH,
]

PROJECT_BOARD_REQUIRED_STATE_OBJECTS = ["board", "card", "comment", "audit_event"]
PROJECT_BOARD_REQUIRED_OPERATIONS = ["card_list", "card_get", "card_move", "card_assign", "comment_add"]
PROJECT_BOARD_REQUIRED_RULES = ["audit-on-write", "workflow-statuses"]


def project_board_source_evidence_fields(*, base_dir: Path | None = None, source_paths: list[Path] | None = None) -> dict[str, Any]:
    return LocalSourceConnector(base_dir=base_dir).build_index_fields(source_paths or PROJECT_BOARD_SOURCE_PATHS)


class ProjectBoardLiteKnowledgeExtractor:
    def __init__(self, *, base_dir: Path | None = None) -> None:
        self.base_dir = Path.cwd() if base_dir is None else Path(base_dir)

    def build_knowledge_fields(self, source_index: dict[str, Any]) -> dict[str, Any]:
        state_objects = []
        operations = []
        business_rules = []
        examples = []
        for source in source_index.get("sources", []):
            path = self._resolve(source["uri_or_path"])
            if not path.exists():
                continue
            text = path.read_text(encoding="utf-8")
            if source["kind"] == "cli_help":
                operations.extend(_operations_from_cli_help(source["source_id"], text))
            elif source["kind"] == "database_schema":
                state_objects.extend(_state_objects_from_schema(source["source_id"], text))
                rules, parsed_examples = _rules_and_examples_from_yaml(source["source_id"], text)
                business_rules.extend(rules)
                examples.extend(parsed_examples)
            elif source["kind"] == "local_files":
                rules, parsed_examples = _rules_and_examples_from_yaml(source["source_id"], text)
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


def project_board_knowledge_pack_fields(source_index: dict[str, Any], *, base_dir: Path | None = None) -> dict[str, Any]:
    return ProjectBoardLiteKnowledgeExtractor(base_dir=base_dir).build_knowledge_fields(source_index)


def project_board_need_spec_fields(raw_request: str) -> dict[str, Any]:
    return {
        "goal": raw_request,
        "target_capabilities": ["stateful planning tool use", "source-grounded CLI/schema extraction", "deterministic verification"],
        "domain_seed": "project-board-lite",
        "expected_agent_behavior": "Use project-board requests to inspect cards, update workflow state, assign owners, and add comments.",
        "constraints": {
            "network": "not_required",
            "auth": "not_required",
            "license": "local_fixture",
            "safety": "local_state_only",
            "local_execution": True,
            "mocking_allowed": True,
        },
        "preferred_surfaces": ["python", "cli", "http", "mcp"],
        "out_of_scope": ["training integration", "rollout", "reward export", "AWM reproduction", "MCP-only architecture", "CLI-only architecture"],
        "human_confirmation_required": [],
    }


def project_board_environment_spec_fields(knowledge: dict[str, Any]) -> dict[str, Any]:
    return {
        "environment_id": "project-board-lite",
        "domain": "local project board card workflow",
        "state_backend": {
            "kind": "yaml",
            "reset_strategy": "copy versioned YAML fixture into isolated run directory",
            "isolation_strategy": "one in-memory/YAML state snapshot per run",
            "seed_fixture_refs": ["fixtures/seed/project-board-lite.yaml"],
        },
        "state_entities": [item["object_id"] for item in knowledge.get("state_objects", [])],
        "logical_tools": [{"tool_id": operation["operation_id"], "name": operation["name"]} for operation in knowledge.get("operations", [])],
        "permissions": {"network": False, "filesystem": "package_dir_only", "auth": False},
        "safety_boundaries": ["synthetic local project data only", "no external project management API", "no generic shell execution surface"],
        "mock_policy": {"external_services": "not_required", "data": "synthetic"},
        "release_surfaces_allowed": ["python", "cli", "http", "mcp"],
        "observability": {"logs": True, "traces": True, "state_snapshots": ["before", "after", "on_failure"]},
    }


def project_board_logical_tool_graph_fields(knowledge: dict[str, Any]) -> dict[str, Any]:
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
                "errors": ["unknown_card", "invalid_status", "invalid_argument"],
                "idempotency": operation.get("idempotency", "unknown"),
                "source_refs": list(operation.get("source_refs", [])),
            }
        )
    edges = [
        {"from_tool_id": "card_list", "to_tool_id": "card_get", "dependency_type": "strong", "reason": "list identifies card ids for detail inspection"},
        {"from_tool_id": "card_get", "to_tool_id": "card_move", "dependency_type": "strong", "reason": "details confirm the card before workflow mutation"},
        {"from_tool_id": "card_list", "to_tool_id": "card_assign", "dependency_type": "weak", "reason": "list can identify assignment candidates"},
        {"from_tool_id": "card_assign", "to_tool_id": "comment_add", "dependency_type": "strong", "reason": "assignment change should be explained with a comment"},
    ]
    return {
        "tools": tools,
        "edges": [edge for edge in edges if edge["from_tool_id"] in operation_ids and edge["to_tool_id"] in operation_ids],
        "parameters": list(parameters.values()),
        "forbidden_direct_access": ["state YAML path", "internal schema ids in user request", "verifier ids"],
    }


def project_board_task_set_fields(graph: dict[str, Any], knowledge: dict[str, Any]) -> dict[str, Any]:
    known_tools = {tool["tool_id"] for tool in graph.get("tools", [])}
    tasks = [task for task in _task_templates(knowledge) if set(task["dependency_path"]).issubset(known_tools)]
    rejected = [
        {"candidate_id": task["task_id"], "reason": "source evidence did not provide every command in dependency_path"}
        for task in _task_templates(knowledge)
        if not set(task["dependency_path"]).issubset(known_tools)
    ]
    return {
        "tasks": tasks,
        "minimum_task_count": 3,
        "coverage": {
            "tool_ids": sorted({tool_id for task in tasks for tool_id in task["allowed_logical_tool_ids"]}),
            "capabilities": ["read", "write", "audit", "assignment", "workflow_transition"],
            "state_entities": ["card", "comment", "audit_event"],
        },
        "rejected_candidates": rejected,
    }


def project_board_surface_plan_fields(env_spec: dict[str, Any]) -> dict[str, Any]:
    return {
        "bindings": [
            {
                "binding_id": f"python-{tool['tool_id']}",
                "logical_tool_id": tool["tool_id"],
                "surface": "python",
                "exposure_name": f"ProjectBoardLite.{tool['tool_id']}",
                "input_mapping": "same as logical tool schema",
                "output_mapping": "dict/list JSON-compatible Python objects",
                "error_mapping": "Python exception to logical error",
                "auth_context": "none",
                "state_scope": "isolated project-board state snapshot",
            }
            for tool in env_spec.get("logical_tools", [])
        ],
        "surface_status": {"python": "required_for_first_slice", "cli": "planned", "http": "deferred", "mcp": "deferred"},
        "compatibility_notes": ["CLI help is a source family input; published CLI runtime surface remains planned for this fixture."],
    }


def project_board_verifier_plan_fields(task_set: dict[str, Any], knowledge: dict[str, Any]) -> dict[str, Any]:
    return {
        "verifiers": [_verifier(task["task_id"], "state_query" if task["task_id"] == "pb-task-3" else "state_diff", knowledge) for task in task_set["tasks"]],
        "llm_judges": [],
    }


def project_board_feasibility_report_fields(context) -> dict[str, Any]:
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


def project_board_implementation_request_fields(artifacts: dict[str, dict[str, Any]], review_records: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "request_id": "impl-project-board-lite-first-slice",
        "environment_id": "project-board-lite",
        "source_artifact_ids": [artifacts["SourceEvidenceIndex"]["id"], artifacts["KnowledgePack"]["id"]],
        "accepted_task_ids": [task["task_id"] for task in artifacts["TaskSet"]["tasks"]],
        "accepted_verifier_ids": [verifier["verifier_id"] for verifier in artifacts["VerifierPlan"]["verifiers"]],
        "required_surface_ids": [binding["binding_id"] for binding in artifacts["SurfacePlan"]["bindings"] if binding["surface"] == "python"],
        "package_layout_ref": "envpkg/",
        "implementation_scope": ["verified generated environment bundle", "generated Python callable runtime", "generated seed fixture", "generated verifier", "pipeline store evidence", "optional agent-backed codegen through AgentBackend"],
        "non_goals": ["training integration", "rollout", "reward export", "AWM reproduction", "MCP-only architecture", "generic shell environment surface"],
        "tdd_requirements": ["schema validation", "source-grounded CLI/schema/examples extraction", "deterministic verifier positive and negative examples"],
        "launch_check_replay_commands": ["python <generated_build_dir>/check_replay.py"],
        "review_record_refs": [record["id"] for record in review_records],
    }


def project_board_deterministic_implementation_record(context) -> dict[str, Any]:
    return project_board_generated_implementation_record(context)


def project_board_package_plan_fields(context) -> dict[str, Any]:
    bundle = context.artifact("GeneratedEnvironmentBundle")
    included_ids = (
        [artifact["id"] for artifact in context.artifacts.values()]
        + ["package-project-board-lite", "replay-project-board-lite", "consumer-project-board-lite", "release-project-board-lite"]
        + [record["id"] for record in context.review_records]
        + [record["id"] for record in context.gate_records]
        + [record["implementation_id"] for record in context.build_check_replay_records]
    )
    return {
        "package_plan_id": "package-project-board-lite",
        "environment_id": "project-board-lite",
        "layout": "envpkg/",
        "included_artifact_ids": included_ids,
        "fixture_refs": ["fixtures/seed/project-board-lite.yaml"],
        "static_check_refs": STAGE_GATES,
        "review_record_refs": [record["id"] for record in context.review_records],
        "replay_plan_ref": "replay-project-board-lite",
        "release_manifest_ref": "release-project-board-lite",
        "generated_bundle_ref": bundle["id"],
        "consumer_output_refs": ["release/task-records.jsonl", "release/verifier-records.jsonl", "release/consumer-index.yaml"],
        "excluded_items": [
            {"item": "Goal 02-04 runtime surfaces", "reason": "support-desk-lite regression only"},
            {"item": "generic shell executor", "reason": "CLI help is source evidence, not an environment shell tool"},
        ],
    }


def project_board_release_manifest_fields(context) -> dict[str, Any]:
    artifacts = context.artifacts | {"EnvironmentPackagePlan": context.artifact("EnvironmentPackagePlan")}
    bundle = context.artifact("GeneratedEnvironmentBundle")
    implementation_mode = bundle.get("implementation_mode", "deterministic_template_codegen")
    if implementation_mode == "agent_backed_codegen":
        implementation_limit = "Generated environment bundle was produced through the agent-backed codegen path and verified from agent-written files."
    else:
        implementation_limit = "Generated environment bundle is deterministic template output, not generic agent codegen."
    return {
        "release_id": "release-project-board-lite",
        "environment_id": "project-board-lite",
        "version": "0.1.0",
        "artifact_hashes": {name: artifact["hash"] for name, artifact in artifacts.items()},
        "package_layout": "envpkg/",
        "task_index": [task["task_id"] for task in context.artifact("TaskSet")["tasks"]],
        "verifier_index": [verifier["verifier_id"] for verifier in context.artifact("VerifierPlan")["verifiers"]],
        "surface_index": context.artifact("SurfacePlan")["surface_status"],
        "fixture_index": ["fixtures/seed/project-board-lite.yaml"],
        "replay_contract": "checks/replay-plan.yaml",
        "generated_bundle_ref": bundle["id"],
        "generated_bundle": {
            "bundle_id": bundle["id"],
            "build_dir": bundle["build_dir"],
            "runtime_entrypoint": bundle["runtime_entrypoint"],
            "verifier_entrypoint": bundle["verifier_entrypoint"],
            "check_commands": bundle["check_commands"],
            "replay_commands": bundle["replay_commands"],
        },
        "consumer_outputs": ["release/task-records.jsonl", "release/verifier-records.jsonl", "release/consumer-index.yaml"],
        "known_limits": [
            implementation_limit,
            "Second local source family is validated, but synthesis remains project-board-domain-specific.",
            "CLI help is source evidence only; project-board environment CLI runtime is not implemented.",
            "Agent-backed implementation output must pass path/hash/security checks and build/check/replay before release.",
        ],
    }


def blocking_source_uncertainties(knowledge: dict[str, Any]) -> list[dict[str, Any]]:
    return [item for item in knowledge.get("uncertainties", []) if item.get("blocking")]


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


def _state_objects_from_schema(source_id: str, text: str) -> list[dict[str, Any]]:
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
    return state_objects


def _rules_and_examples_from_yaml(source_id: str, text: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    data = yaml.safe_load(text) or {}
    rules = []
    for item in data.get("business_rules", []) or []:
        if not isinstance(item, dict) or not item.get("rule_id"):
            continue
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
        if not isinstance(item, dict) or not item.get("example_id"):
            continue
        example_id = str(item["example_id"])
        example = dict(item)
        example["source_refs"] = [f"{source_id}#L{_line_number(text, f'example_id: {example_id}')}"]
        examples.append(example)
    return rules, examples


def _task_templates(knowledge: dict[str, Any]) -> list[dict[str, Any]]:
    example_refs = {
        example["example_id"]: list(example.get("source_refs", []))
        for example in knowledge.get("examples", [])
        if isinstance(example, dict) and example.get("example_id")
    }
    return [
        {
            "task_id": "pb-task-1",
            "natural_request": "Move the blocked payment API card into review after checking it.",
            "target_capability": "workflow state mutation after lookup",
            "initial_state_refs": ["fixtures/seed/project-board-lite.yaml#C-11"],
            "expected_state_delta": {"card": "C-11 status=in_review", "audit_event": "card_moved"},
            "expected_answer": "",
            "allowed_logical_tool_ids": ["card_list", "card_get", "card_move"],
            "forbidden_leakage": ["state file path", "schema ids", "verifier ids"],
            "dependency_path": ["card_list", "card_get", "card_move"],
            "difficulty": {"level": "medium", "requires_state_change": True},
            "verifier_refs": ["verifier-pb-task-1"],
            "source_refs": example_refs.get("task-move-blocked-card", []),
        },
        {
            "task_id": "pb-task-2",
            "natural_request": "Assign the checkout bug to sam and add a triage comment.",
            "target_capability": "assignment update with explanatory comment",
            "initial_state_refs": ["fixtures/seed/project-board-lite.yaml#C-10"],
            "expected_state_delta": {"card": "C-10 assignee=sam", "comment": "triage comment added", "audit_event": "card_assigned"},
            "expected_answer": "",
            "allowed_logical_tool_ids": ["card_list", "card_assign", "comment_add"],
            "forbidden_leakage": ["state file path", "schema ids", "verifier ids"],
            "dependency_path": ["card_list", "card_assign", "comment_add"],
            "difficulty": {"level": "medium", "requires_state_change": True},
            "verifier_refs": ["verifier-pb-task-2"],
            "source_refs": example_refs.get("task-assign-and-comment", []),
        },
        {
            "task_id": "pb-task-3",
            "natural_request": "Report how many in-progress cards are assigned to eve and their highest priority.",
            "target_capability": "read-only filtered summary",
            "initial_state_refs": ["fixtures/seed/project-board-lite.yaml#C-12"],
            "expected_state_delta": {},
            "expected_answer": {"status": "in_progress", "assignee": "eve", "card_count": 1, "highest_priority": "medium"},
            "allowed_logical_tool_ids": ["card_list"],
            "forbidden_leakage": ["state file path", "schema ids", "verifier ids"],
            "dependency_path": ["card_list"],
            "difficulty": {"level": "easy", "requires_state_change": False},
            "verifier_refs": ["verifier-pb-task-3"],
            "source_refs": example_refs.get("task-read-only-summary", []),
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
        "checks": ["dependency path trace assertion", "state snapshot assertion", "target changed or read-only answer", "non-target preserved", "audit evidence"],
        "success_criteria": f"project_board_lite.verify_task_completion({task_id!r}) returns success=true only when state and dependency trace checks pass",
        "failure_criteria": "Any deterministic check returns false.",
        "positive_examples": [f"{task_id}: expected state delta or answer present"],
        "negative_examples": [f"{task_id}: missing dependency path trace, target state, audit, or expected answer"],
        "evidence_refs": evidence_refs,
        "replay_inputs": ["seed fixture", "initial snapshot", "final snapshot", "surface trace", "trace call group", "declared dependency path", "agent final answer"],
        "assertions": [
            {"assertion_id": f"assert-{task_id}", "target": "verify_task_completion.success", "operator": "equals", "expected": True, "tolerance": 0, "source_ref": "project_board_lite.py"},
            {"assertion_id": f"assert-{task_id}-path", "target": "dependency_path_trace_matches", "operator": "equals", "expected": True, "tolerance": 0, "source_ref": "project_board_lite.py"},
        ],
        "allowed_side_effects": [],
        "timeout_ms": 1000,
        "isolation_requirement": "read-only verifier over copied project-board state",
        "failure_diagnostics": ["return structured failed checks"],
    }


def _uncertainties(state_objects: list[dict[str, Any]], operations: list[dict[str, Any]], rules: list[dict[str, Any]]) -> list[dict[str, Any]]:
    state_ids = {item["object_id"] for item in state_objects}
    operation_ids = {item["operation_id"] for item in operations}
    rule_ids = {item["rule_id"] for item in rules}
    uncertainties = []
    for required in PROJECT_BOARD_REQUIRED_STATE_OBJECTS:
        if required not in state_ids:
            uncertainties.append(
                {
                    "question": f"Missing required project-board schema state object evidence: {required}",
                    "blocking": True,
                    "candidate_resolution": "Add schema source evidence for the state object or stop before synthesis.",
                }
            )
    for required in PROJECT_BOARD_REQUIRED_OPERATIONS:
        if required not in operation_ids:
            uncertainties.append(
                {
                    "question": f"Missing required project-board CLI command evidence: {required}",
                    "blocking": True,
                    "candidate_resolution": "Add CLI help source evidence for the command or stop before task generation.",
                }
            )
    for required in PROJECT_BOARD_REQUIRED_RULES:
        if required not in rule_ids:
            uncertainties.append(
                {
                    "question": f"Missing required project-board rule evidence: {required}",
                    "blocking": True,
                    "candidate_resolution": "Add example/rule source evidence or mark the pipeline needs_human.",
                }
            )
    return uncertainties


def _verifiable_fields(state_objects: list[dict[str, Any]], operations: list[dict[str, Any]]) -> list[str]:
    state_by_id = {item["object_id"]: item for item in state_objects}
    fields = set()
    for operation in operations:
        for state_id in operation.get("writes", []):
            for field in state_by_id.get(state_id, {}).get("fields", []):
                fields.add(f"{state_id}.{field}")
    return sorted(fields)


def _parameter(name: str, *, optional: bool) -> dict[str, str]:
    return {
        "name": name,
        "classification": "internal" if name == "card_id" else ("optional" if optional else "external"),
        "source": "card_list/card_get" if name == "card_id" else ("user request filter" if optional else "user request"),
        "validation": _validation(name),
    }


def _validation(name: str) -> str:
    if name == "status":
        return "todo, in_progress, blocked, in_review, or done"
    if name == "priority":
        return "low, medium, high, or urgent"
    if name == "card_id":
        return "existing card"
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
