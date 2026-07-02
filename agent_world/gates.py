from __future__ import annotations

from typing import Any

from agent_world.artifacts import ArtifactValidationError, make_artifact, validate_artifact


STAGE_GATES: dict[str, list[str]] = {
    "PLAN": ["G0", "G13"],
    "SELECT": ["G0", "G13"],
    "S0": ["G0", "G1", "G13"],
    "S1": ["G0", "G2", "G3", "G13"],
    "S2": ["G0", "G2", "G13"],
    "S3": ["G0", "G4", "G13"],
    "S4": ["G0", "G5", "G13"],
    "S5": ["G0", "G6", "G7", "G13"],
    "S6": ["G0", "G8", "G13"],
    "S7": ["G0", "G9", "G13"],
    "S8": ["G0", "G10", "G13"],
    "S9": ["G0", "G13"],
    "S10": ["G0", "G11", "G13"],
    "S11": ["G0", "G12", "G13"],
}


def evaluate_stage_gates(
    *,
    stage: str,
    artifact_type: str,
    artifact: dict[str, Any],
    context: dict[str, dict[str, Any]],
    review: dict[str, Any],
    invocations: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    gate_ids = list(STAGE_GATES[stage])
    if invocations:
        gate_ids.append("G14")
    return [evaluate_gate(gate_id, stage, artifact_type, artifact, context, review, invocations) for gate_id in gate_ids]


def evaluate_gate(
    gate_id: str,
    stage: str,
    artifact_type: str,
    artifact: dict[str, Any],
    context: dict[str, dict[str, Any]],
    review: dict[str, Any],
    invocations: list[dict[str, Any]],
) -> dict[str, Any]:
    status = "pass"
    failure_class = ""
    recovery = ""
    try:
        if gate_id == "G0":
            validate_artifact(artifact_type, artifact)
        elif gate_id == "G1":
            _scope_gate(artifact)
        elif gate_id == "G2":
            _evidence_gate(artifact_type, artifact)
        elif gate_id == "G3":
            _permission_gate(artifact)
        elif gate_id == "G4":
            _state_reset_gate(artifact, context)
        elif gate_id == "G5":
            _tool_graph_gate(artifact, context)
        elif gate_id == "G6":
            _task_solvability_gate(artifact, context)
        elif gate_id == "G7":
            _leakage_gate(artifact)
        elif gate_id == "G8":
            _surface_gate(artifact, context)
        elif gate_id == "G9":
            _verifier_gate(artifact, context)
        elif gate_id == "G10":
            _feasibility_gate(artifact, context)
        elif gate_id == "G11":
            _package_gate(artifact)
        elif gate_id == "G12":
            _release_gate(artifact, context)
        elif gate_id == "G13":
            _review_gate(artifact, review)
        elif gate_id == "G14":
            _invocation_gate(invocations, context)
    except Exception as exc:
        status = "fail"
        failure_class = exc.__class__.__name__
        recovery = str(exc)

    fields = {
        "gate_record_id": f"gate-{stage.lower()}-{gate_id.lower()}-{artifact['id']}",
        "gate_id": gate_id,
        "stage": stage,
        "checked_artifact_ids": [artifact["id"]],
        "evidence_refs": [artifact["id"], review["id"]] + [record["id"] for record in invocations],
        "failure_class": failure_class,
        "recovery_suggestion": recovery,
        "review_record_refs": [review["id"]],
    }
    return make_artifact(
        "GateRecord",
        source_stage=stage,
        producer="deterministic-gate-evaluator",
        fields=fields,
        artifact_id=fields["gate_record_id"],
        inputs=fields["evidence_refs"],
        status=status,
    )


def _scope_gate(need: dict[str, Any]) -> None:
    out_of_scope = " ".join(need.get("out_of_scope", [])).lower()
    for term in ["training", "rollout", "reward export", "awm reproduction", "mcp-only", "cli-only"]:
        if term not in out_of_scope:
            raise ArtifactValidationError(f"NeedSpec.out_of_scope must mention {term}")


def _evidence_gate(artifact_type: str, artifact: dict[str, Any]) -> None:
    if artifact_type == "SourceEvidenceIndex":
        if not artifact.get("sources"):
            raise ArtifactValidationError("SourceEvidenceIndex must contain at least one source")
        for source in artifact["sources"]:
            if not source.get("uri_or_path") or not source.get("version_or_hash"):
                raise ArtifactValidationError("SourceEvidenceIndex source lacks uri/path or version/hash")
    if artifact_type == "KnowledgePack":
        for key in ["state_objects", "operations", "business_rules"]:
            for item in artifact.get(key, []):
                if not item.get("source_refs") and item.get("confidence") != "inferred":
                    raise ArtifactValidationError(f"KnowledgePack.{key} item lacks source_refs")


def _permission_gate(source_index: dict[str, Any]) -> None:
    for source in source_index.get("sources", []):
        if source.get("auth_requirement") not in {"none", "not_required", ""}:
            raise ArtifactValidationError("Source requires auth and must be human-reviewed")
        if source.get("license") in {"unknown_forbidden", "restricted"}:
            raise ArtifactValidationError("Source has unacceptable license")


def _state_reset_gate(env_spec: dict[str, Any], context: dict[str, dict[str, Any]] | None = None) -> None:
    backend = env_spec.get("state_backend", {})
    if not backend.get("reset_strategy") or not backend.get("isolation_strategy"):
        raise ArtifactValidationError("EnvironmentSpec.state_backend lacks reset/isolation strategy")
    if not backend.get("seed_fixture_refs"):
        raise ArtifactValidationError("EnvironmentSpec.state_backend lacks seed fixtures")
    if context and "KnowledgePack" in context:
        known_entities = _ids_from_items(context["KnowledgePack"].get("state_objects", []), ["object_id", "state_object_id"], "KnowledgePack.state_objects")
        env_entities = _ids_from_items(env_spec.get("state_entities", []), ["object_id", "state_object_id"], "EnvironmentSpec.state_entities")
        if not env_entities.issubset(known_entities):
            raise ArtifactValidationError("EnvironmentSpec references state entities absent from KnowledgePack")
        known_operations = _ids_from_items(context["KnowledgePack"].get("operations", []), ["operation_id", "tool_id"], "KnowledgePack.operations")
        tool_ids = _ids_from_items(env_spec.get("logical_tools", []), ["tool_id", "operation_id"], "EnvironmentSpec.logical_tools")
        if not tool_ids.issubset(known_operations):
            raise ArtifactValidationError("EnvironmentSpec references logical tools absent from KnowledgePack")


def _tool_graph_gate(graph: dict[str, Any], context: dict[str, dict[str, Any]] | None = None) -> None:
    tool_ids = {tool["tool_id"] for tool in graph.get("tools", [])}
    if not tool_ids:
        raise ArtifactValidationError("LogicalToolGraph must contain tools")
    declared_parameters = {parameter["name"] for parameter in graph.get("parameters", [])}
    missing_required_parameters = []
    missing_optional_parameters = []
    for tool in graph.get("tools", []):
        for parameter in tool.get("input_schema", {}).get("required", []):
            if parameter not in declared_parameters:
                missing_required_parameters.append(f"{tool['tool_id']}.{parameter}")
        for parameter in tool.get("input_schema", {}).get("optional", []):
            if parameter not in declared_parameters:
                missing_optional_parameters.append(f"{tool['tool_id']}.{parameter}")
    if missing_required_parameters:
        raise ArtifactValidationError(f"LogicalToolGraph required parameters missing from catalog: {missing_required_parameters}")
    if missing_optional_parameters:
        raise ArtifactValidationError(f"LogicalToolGraph optional parameters missing from catalog: {missing_optional_parameters}")
    for edge in graph.get("edges", []):
        if edge["from_tool_id"] not in tool_ids or edge["to_tool_id"] not in tool_ids:
            raise ArtifactValidationError("LogicalToolGraph edge references unknown tool")
    if context and "EnvironmentSpec" in context:
        entities = _aliases_from_items(context["EnvironmentSpec"].get("state_entities", []), ["object_id", "state_object_id", "entity_id"], "EnvironmentSpec.state_entities")
        env_tools = {tool["tool_id"] for tool in context["EnvironmentSpec"]["logical_tools"]}
        for tool in graph.get("tools", []):
            if tool["tool_id"] not in env_tools:
                raise ArtifactValidationError(f"Graph tool {tool['tool_id']} absent from EnvironmentSpec")
            if not set(tool.get("reads", [])).issubset(entities):
                raise ArtifactValidationError(f"Tool {tool['tool_id']} reads unknown state entities")
            if not set(tool.get("writes", [])).issubset(entities):
                raise ArtifactValidationError(f"Tool {tool['tool_id']} writes unknown state entities")


def _ids_from_items(items: list[Any], keys: list[str], label: str) -> set[str]:
    ids: set[str] = set()
    for item in items:
        value = ""
        if isinstance(item, str):
            value = item
        elif isinstance(item, dict):
            for key in keys:
                if item.get(key):
                    value = str(item[key])
                    break
        if not value:
            raise ArtifactValidationError(f"{label} item lacks identifier field: {keys}")
        ids.add(value)
    return ids


def _aliases_from_items(items: list[Any], keys: list[str], label: str) -> set[str]:
    aliases: set[str] = set()
    for item in items:
        if isinstance(item, str):
            aliases.add(item)
            continue
        if not isinstance(item, dict):
            raise ArtifactValidationError(f"{label} item lacks identifier field: {keys}")
        for key in keys:
            if item.get(key):
                aliases.add(str(item[key]))
        if not any(item.get(key) for key in keys):
            raise ArtifactValidationError(f"{label} item lacks identifier field: {keys}")
    return aliases


def _task_solvability_gate(task_set: dict[str, Any], context: dict[str, dict[str, Any]] | None = None) -> None:
    tasks = task_set.get("tasks", [])
    minimum_task_count = int(task_set.get("minimum_task_count", 5))
    if len(tasks) < minimum_task_count:
        raise ArtifactValidationError(f"TaskSet needs at least {_count_word(minimum_task_count)} accepted tasks")
    known_tools = None
    known_verifiers = None
    graph_edges = set()
    if context and "LogicalToolGraph" in context:
        known_tools = {tool["tool_id"] for tool in context["LogicalToolGraph"]["tools"]}
        graph_edges = {(edge["from_tool_id"], edge["to_tool_id"]) for edge in context["LogicalToolGraph"]["edges"]}
    if context and "VerifierPlan" in context:
        known_verifiers = {verifier["verifier_id"] for verifier in context["VerifierPlan"]["verifiers"]}
    for task in tasks:
        if not task.get("initial_state_refs") or not task.get("allowed_logical_tool_ids") or not task.get("verifier_refs"):
            raise ArtifactValidationError(f"Task {task.get('task_id')} lacks state/tools/verifiers")
        expected_answer = task.get("expected_answer")
        if not task.get("expected_state_delta") and expected_answer in (None, ""):
            raise ArtifactValidationError(f"Task {task.get('task_id')} lacks expected delta/answer")
        if known_tools is not None and not set(task["allowed_logical_tool_ids"]).issubset(known_tools):
            raise ArtifactValidationError(f"Task {task['task_id']} references unknown logical tools")
        if known_tools is not None and not set(task["dependency_path"]).issubset(known_tools):
            raise ArtifactValidationError(f"Task {task['task_id']} dependency_path references unknown tools")
        if not set(task["dependency_path"]).issubset(set(task["allowed_logical_tool_ids"])):
            raise ArtifactValidationError(f"Task {task['task_id']} dependency_path uses tools outside allowed tools")
        for before, after in zip(task["dependency_path"], task["dependency_path"][1:]):
            if before == after:
                continue
            if graph_edges and (before, after) not in graph_edges:
                raise ArtifactValidationError(f"Task {task['task_id']} dependency_path has undeclared edge {before}->{after}")
        if known_verifiers is not None and not set(task["verifier_refs"]).issubset(known_verifiers):
            raise ArtifactValidationError(f"Task {task['task_id']} references unknown verifiers")


def _leakage_gate(task_set: dict[str, Any]) -> None:
    forbidden_words = {"database", "backend", "verifier", "logical_tool", "tool_id"}
    for task in task_set.get("tasks", []):
        natural = task["natural_request"].lower()
        if any(word in natural for word in forbidden_words):
            raise ArtifactValidationError(f"Task {task['task_id']} leaks implementation detail")
        for tool_id in task.get("allowed_logical_tool_ids", []):
            if tool_id.lower() in natural:
                raise ArtifactValidationError(f"Task {task['task_id']} leaks tool id {tool_id}")


def _surface_gate(surface_plan: dict[str, Any], context: dict[str, dict[str, Any]] | None = None) -> None:
    if surface_plan.get("surface_status", {}).get("python") != "required_for_first_slice":
        raise ArtifactValidationError("Python surface must be required for first slice")
    if not any(binding.get("surface") == "python" for binding in surface_plan.get("bindings", [])):
        raise ArtifactValidationError("SurfacePlan lacks Python bindings")
    if context and "LogicalToolGraph" in context:
        tool_ids = {tool["tool_id"] for tool in context["LogicalToolGraph"]["tools"]}
        for binding in surface_plan.get("bindings", []):
            if binding["logical_tool_id"] not in tool_ids:
                raise ArtifactValidationError(f"Surface binding references unknown logical tool {binding['logical_tool_id']}")


def _verifier_gate(verifier_plan: dict[str, Any], context: dict[str, dict[str, Any]]) -> None:
    verifiers = verifier_plan.get("verifiers", [])
    if not verifiers:
        raise ArtifactValidationError("VerifierPlan lacks deterministic verifiers")
    for verifier in verifiers:
        if not verifier.get("positive_examples") or not verifier.get("negative_examples"):
            raise ArtifactValidationError(f"Verifier {verifier['verifier_id']} lacks examples")
        inputs = set(verifier.get("inputs", []))
        if not {"surface_trace_path", "expected_dependency_path", "trace_call_group"}.issubset(inputs):
            raise ArtifactValidationError(f"Verifier {verifier['verifier_id']} lacks trace/dependency path inputs")
        checks = " ".join(verifier.get("checks", [])).lower()
        if "dependency" not in checks or "trace" not in checks:
            raise ArtifactValidationError(f"Verifier {verifier['verifier_id']} lacks dependency trace check")
        assertion_targets = {assertion["target"] for assertion in verifier.get("assertions", [])}
        if "dependency_path_trace_matches" not in assertion_targets:
            raise ArtifactValidationError(f"Verifier {verifier['verifier_id']} lacks dependency path assertion")
    task_set = context.get("TaskSet")
    if task_set:
        verifier_task_ids = {verifier["task_id"] for verifier in verifiers}
        verifier_ids = {verifier["verifier_id"] for verifier in verifiers}
        missing = [task["task_id"] for task in task_set["tasks"] if task["task_id"] not in verifier_task_ids]
        if missing:
            raise ArtifactValidationError(f"VerifierPlan missing verifiers for tasks: {missing}")
        for task in task_set["tasks"]:
            if not set(task["verifier_refs"]).issubset(verifier_ids):
                raise ArtifactValidationError(f"Task {task['task_id']} references unknown verifier refs")


def _feasibility_gate(report: dict[str, Any], context: dict[str, dict[str, Any]]) -> None:
    if report.get("status") != "pass":
        raise ArtifactValidationError("FeasibilityReport must pass before implementation request")
    for field in ["minimum_viable_surface", "minimum_viable_task_ids", "minimum_viable_verifier_ids"]:
        if not report.get(field):
            raise ArtifactValidationError(f"FeasibilityReport missing {field}")
    if not report.get("gate_results"):
        raise ArtifactValidationError("FeasibilityReport must include upstream gate results")
    for result in report.get("gate_results", []):
        for field in ["gate_id", "status", "evidence", "failure_class", "recovery_suggestion"]:
            if field not in result:
                raise ArtifactValidationError("FeasibilityReport gate_results entries must be structured")
        if result["status"] != "pass":
            raise ArtifactValidationError("FeasibilityReport references a non-passing gate result")
        gate_records = context.get("__gate_records__", {})
        if gate_records:
            if not any(record_id in result["evidence"] for record_id in gate_records):
                raise ArtifactValidationError(f"FeasibilityReport gate result lacks GateRecord evidence for {result['gate_id']}")
            if not any(record["gate_id"] == result["gate_id"] and record["status"] == result["status"] for record in gate_records.values() if record["id"] in result["evidence"]):
                raise ArtifactValidationError(f"FeasibilityReport gate result is inconsistent for {result['gate_id']}")
        gate_records = context.get("__gate_records__", {})
        for record in gate_records.values():
            if record["source_stage"] in {"S0", "S1", "S2", "S3", "S4", "S5", "S6", "S7"} and record["status"] == "pass":
                represented = any(record["id"] in item["evidence"] for item in report.get("gate_results", []))
                if not represented:
                    raise ArtifactValidationError(f"FeasibilityReport omits upstream gate record {record['id']}")
    source_index = _context_required(context, "SourceEvidenceIndex")
    env_spec = _context_required(context, "EnvironmentSpec")
    graph = _context_required(context, "LogicalToolGraph")
    task_set = _context_required(context, "TaskSet")
    surface_plan = _context_required(context, "SurfacePlan")
    verifier_plan = _context_required(context, "VerifierPlan")
    _evidence_gate("SourceEvidenceIndex", source_index)
    _state_reset_gate(env_spec, context)
    _tool_graph_gate(graph, context)
    _task_solvability_gate(task_set, context | {"VerifierPlan": verifier_plan})
    _surface_gate(surface_plan, context)
    _verifier_gate(verifier_plan, context)
    _permission_gate(source_index)
    if report["minimum_viable_surface"] not in surface_plan["surface_status"]:
        raise ArtifactValidationError("FeasibilityReport minimum surface is not planned")
    task_ids = {task["task_id"] for task in task_set["tasks"]}
    verifier_ids = {verifier["verifier_id"] for verifier in verifier_plan["verifiers"]}
    if not set(report["minimum_viable_task_ids"]).issubset(task_ids):
        raise ArtifactValidationError("FeasibilityReport references unknown tasks")
    if not set(report["minimum_viable_verifier_ids"]).issubset(verifier_ids):
        raise ArtifactValidationError("FeasibilityReport references unknown verifiers")


def _package_gate(plan: dict[str, Any]) -> None:
    if not plan.get("included_artifact_ids") or not plan.get("fixture_refs") or not plan.get("review_record_refs"):
        raise ArtifactValidationError("EnvironmentPackagePlan lacks included artifacts, fixtures, or review records")
    if not plan.get("replay_plan_ref"):
        raise ArtifactValidationError("EnvironmentPackagePlan lacks replay plan ref")
    known = set(plan.get("included_artifact_ids", []))
    required_prefixes = [
        "needspec-",
        "sourceevidenceindex-",
        "knowledgepack-",
        "environmentspec-",
        "logicaltoolgraph-",
        "taskset-",
        "surfaceplan-",
        "verifierplan-",
        "feasibilityreport-",
        "impl-",
        str(plan["package_plan_id"]),
        str(plan["replay_plan_ref"]),
        str(plan["release_manifest_ref"]),
    ]
    for required in required_prefixes:
        if not any(item.startswith(required) or item == required for item in known):
            raise ArtifactValidationError(f"EnvironmentPackagePlan missing required artifact {required}")
    if plan["replay_plan_ref"] not in known:
        raise ArtifactValidationError("EnvironmentPackagePlan replay_plan_ref is not included")
    if plan["release_manifest_ref"] not in known:
        raise ArtifactValidationError("EnvironmentPackagePlan release_manifest_ref is not included")
    for ref in plan.get("review_record_refs", []):
        if ref not in known:
            raise ArtifactValidationError("EnvironmentPackagePlan review_record_ref is not included")
    for ref in plan.get("fixture_refs", []):
        if not str(ref).startswith("fixtures/"):
            raise ArtifactValidationError("EnvironmentPackagePlan fixture_ref must stay inside fixtures/")
    allowed_consumer_prefixes = ("runtime/", "release/", "checks/", "training/", "rollouts/")
    for ref in plan.get("consumer_output_refs", []):
        if not str(ref).startswith(allowed_consumer_prefixes):
            raise ArtifactValidationError("EnvironmentPackagePlan consumer_output_ref must stay inside release/, checks/, training/, or rollouts/")


def _release_gate(release: dict[str, Any], context: dict[str, dict[str, Any]]) -> None:
    for field in ["artifact_hashes", "task_index", "verifier_index", "surface_index", "fixture_index", "replay_contract", "consumer_outputs"]:
        if not release.get(field):
            raise ArtifactValidationError(f"ReleaseManifest missing {field}")
    if "TaskSet" in context:
        task_ids = {task["task_id"] for task in context["TaskSet"]["tasks"]}
        if set(release["task_index"]) != task_ids:
            raise ArtifactValidationError("ReleaseManifest task_index must exactly cover accepted tasks")
    if "VerifierPlan" in context:
        verifier_ids = {verifier["verifier_id"] for verifier in context["VerifierPlan"]["verifiers"]}
        if set(release["verifier_index"]) != verifier_ids:
            raise ArtifactValidationError("ReleaseManifest verifier_index must exactly cover accepted verifiers")
    if "SurfacePlan" in context:
        surfaces = set(context["SurfacePlan"]["surface_status"])
        if set(release["surface_index"]) != surfaces:
            raise ArtifactValidationError("ReleaseManifest surface_index must exactly cover planned surfaces")
    for name, artifact in context.items():
        if name.startswith("__") or not isinstance(artifact, dict) or "hash" not in artifact:
            continue
        if name in {"ReleaseManifest"}:
            continue
        if release["artifact_hashes"].get(name) != artifact["hash"]:
            raise ArtifactValidationError(f"ReleaseManifest artifact_hashes mismatch for {name}")


def _review_gate(artifact: dict[str, Any], review: dict[str, Any]) -> None:
    if artifact["id"] not in review.get("reviewed_artifact_ids", []):
        raise ArtifactValidationError("ReviewRecord does not review the stage artifact")
    if review.get("alignment_status") != "pass":
        raise ArtifactValidationError("ReviewRecord did not pass")
    if not review.get("source_of_truth_refs") or not review.get("gate_checklist"):
        raise ArtifactValidationError("ReviewRecord lacks source-of-truth refs or gate checklist")
    if artifact["source_stage"] not in {"PLAN", "S0"} and not review.get("upstream_artifact_ids"):
        raise ArtifactValidationError("ReviewRecord lacks upstream artifact evidence")


def _invocation_gate(invocations: list[dict[str, Any]], context: dict[str, dict[str, Any]]) -> None:
    if not invocations:
        raise ArtifactValidationError("InvocationRecord required")
    config = context.get("InvocationBackendConfig")
    if not config:
        raise ArtifactValidationError("InvocationBackendConfig required")
    for invocation in invocations:
        if invocation.get("status") != "pass":
            raise ArtifactValidationError(f"Invocation did not pass: {invocation['id']}")
        if invocation.get("config_ref") != config["id"]:
            raise ArtifactValidationError("Invocation does not reference current config")
        for field in ["instruction_text", "model_or_runtime", "trace_ref", "result_preview", "usage"]:
            if field not in invocation:
                raise ArtifactValidationError(f"Invocation lacks {field}")
        if not invocation.get("permissions") or not invocation.get("budget"):
            raise ArtifactValidationError("Invocation lacks permissions or budget")
        if config["backend_kind"] in {"process_agent", "codex_cli", "code_agent_runner", "codex_cli_runner"}:
            command = config.get("command", {})
            if not command.get("allowlist_executables"):
                raise ArtifactValidationError("Process agent config lacks executable allowlist")
            expected_filesystem = "isolated_agent_workspace" if config["backend_kind"] in {"code_agent_runner", "codex_cli_runner"} else "controlled_process_cwd"
            if config.get("permissions", {}).get("filesystem") != expected_filesystem:
                raise ArtifactValidationError(f"Process agent config must declare {expected_filesystem} filesystem scope")
            if invocation["permissions"].get("network") and not config.get("permissions", {}).get("network"):
                raise ArtifactValidationError("Invocation requests network beyond config")
            if not config.get("permissions", {}).get("auth") and invocation["permissions"].get("auth"):
                raise ArtifactValidationError("Invocation requests auth beyond config")
            if config["backend_kind"] in {"process_agent", "code_agent_runner"}:
                if config.get("permissions", {}).get("sandbox") or invocation["permissions"].get("sandbox"):
                    raise ArtifactValidationError("process/code_agent_runner must not claim sandbox enforcement")
            if not config.get("redaction_policy", {}).get("secret_env_names_only"):
                raise ArtifactValidationError("Agent config lacks secret redaction policy")
        if config["backend_kind"] == "codex_sdk":
            if config.get("permissions", {}).get("filesystem") != "isolated_agent_workspace":
                raise ArtifactValidationError("Codex SDK config must declare isolated_agent_workspace filesystem scope")
            if not config.get("permissions", {}).get("sandbox"):
                raise ArtifactValidationError("Codex SDK config must declare sandbox enforcement")
            if invocation["permissions"].get("network") and not config.get("permissions", {}).get("network"):
                raise ArtifactValidationError("Invocation requests network beyond config")
            if not config.get("permissions", {}).get("auth") and invocation["permissions"].get("auth"):
                raise ArtifactValidationError("Invocation requests auth beyond config")
            if not config.get("redaction_policy", {}).get("secret_env_names_only"):
                raise ArtifactValidationError("Agent config lacks secret redaction policy")


def _context_required(context: dict[str, dict[str, Any]], name: str) -> dict[str, Any]:
    if name not in context:
        raise ArtifactValidationError(f"Missing context artifact: {name}")
    return context[name]


def _count_word(value: int) -> str:
    return {
        1: "one",
        2: "two",
        3: "three",
        4: "four",
        5: "five",
    }.get(value, str(value))
