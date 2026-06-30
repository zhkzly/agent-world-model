import pytest

from agent_world.artifacts import ArtifactValidationError, artifact_hash, make_artifact
from agent_world.gates import evaluate_gate
from agent_world.pipeline import PipelineRunConfig, PipelineRunner, request_driven_node_registry
from agent_world.review import independent_review


RAW_REQUEST = "Generate an incident response environment with alerts, owners, notes, and final summaries."


def _context(tmp_path, *, stop_after: str = "S8"):
    _, context = PipelineRunner(request_driven_node_registry()).run(
        PipelineRunConfig(
            run_id=f"contract-{stop_after.lower()}",
            raw_request=RAW_REQUEST,
            output_dir=tmp_path,
            stop_after=stop_after,
        )
    )
    return context


def _review_for(context, artifact_type):
    artifact_id = context.artifacts[artifact_type]["id"]
    return next(record for record in context.review_records if artifact_id in record["reviewed_artifact_ids"])


def test_nested_task_schema_rejects_missing_verifier_refs():
    fields = {
        "tasks": [
            {
                "task_id": "task-bad",
                "natural_request": "Capture the first accepted alert update.",
                "target_capability": "bad",
                "initial_state_refs": ["seed"],
                "expected_state_delta": {},
                "expected_answer": "ok",
                "allowed_logical_tool_ids": ["capture_alert"],
                "forbidden_leakage": [],
                "dependency_path": ["capture_alert"],
                "difficulty": {},
            }
        ],
        "coverage": {"tool_ids": ["capture_alert"], "capabilities": ["read"], "state_entities": ["alert_record"]},
        "rejected_candidates": [],
    }

    with pytest.raises(ArtifactValidationError):
        make_artifact("TaskSet", source_stage="S5", producer="test", fields=fields)


def test_review_requires_upstream_artifacts_and_gate_checklist():
    artifact = make_artifact(
        "SourceEvidenceIndex",
        source_stage="S1",
        producer="producer",
        fields={
            "sources": [
                {
                    "source_id": "source-1",
                    "kind": "manual_note",
                    "uri_or_path": "fixture://x",
                    "version_or_hash": "v1",
                    "retrieved_at": "2026-06-27T00:00:00Z",
                    "license": "local_fixture",
                    "auth_requirement": "none",
                    "network_requirement": "none",
                    "security_note": "none",
                }
            ],
            "extractable_objects": [],
            "mock_boundaries": [],
            "open_questions": [],
            "rejected_sources": [],
        },
    )

    review = independent_review(
        stage="S1",
        artifact=artifact,
        need_spec=None,
        upstream_artifacts=[],
        gate_checklist=[],
        source_of_truth_refs=["docs/agent-world-environment-generation.zh.md"],
        reviewer_ref="reviewer",
    )

    assert review["alignment_status"] == "fail"


def test_feasibility_gate_rejects_unknown_minimum_task(tmp_path):
    context = _context(tmp_path, stop_after="S8")
    report = dict(context.artifacts["FeasibilityReport"])
    report["minimum_viable_task_ids"] = ["missing-task"]
    report["hash"] = ""
    report["hash"] = artifact_hash(report)

    gate = evaluate_gate("G10", "S8", "FeasibilityReport", report, context.artifacts, _review_for(context, "FeasibilityReport"), [])

    assert gate["status"] == "fail"
    assert "unknown tasks" in gate["recovery_suggestion"]


def test_task_gate_rejects_unknown_tool_ref(tmp_path):
    context = _context(tmp_path, stop_after="S7")
    task_set = dict(context.artifacts["TaskSet"])
    task_set["tasks"] = [dict(task) for task in task_set["tasks"]]
    task_set["tasks"][0]["allowed_logical_tool_ids"] = ["missing_tool"]
    task_set["hash"] = ""
    task_set["hash"] = artifact_hash(task_set)

    gate = evaluate_gate("G6", "S5", "TaskSet", task_set, context.artifacts, _review_for(context, "TaskSet"), [])

    assert gate["status"] == "fail"
    assert "unknown logical tools" in gate["recovery_suggestion"]


def test_task_gate_rejects_dependency_path_outside_allowed_tools(tmp_path):
    context = _context(tmp_path, stop_after="S7")
    task_set = dict(context.artifacts["TaskSet"])
    task_set["tasks"] = [dict(task) for task in task_set["tasks"]]
    task_set["tasks"][0]["dependency_path"] = [task_set["tasks"][0]["dependency_path"][0], task_set["tasks"][1]["dependency_path"][0]]
    task_set["hash"] = ""
    task_set["hash"] = artifact_hash(task_set)

    gate = evaluate_gate("G6", "S5", "TaskSet", task_set, context.artifacts, _review_for(context, "TaskSet"), [])

    assert gate["status"] == "fail"
    assert "outside allowed tools" in gate["recovery_suggestion"]


def test_feasibility_report_contains_structured_gate_results(tmp_path):
    context = _context(tmp_path, stop_after="S8")
    report = context.artifacts["FeasibilityReport"]

    assert report["gate_results"]
    assert {"gate_id", "status", "evidence", "failure_class", "recovery_suggestion"}.issubset(report["gate_results"][0])


def test_review_invocation_output_must_be_structured():
    artifact = _need_artifact()
    review = independent_review(
        stage="S0",
        artifact=artifact,
        need_spec=artifact,
        upstream_artifacts=[],
        gate_checklist=["G0", "G1", "G13"],
        source_of_truth_refs=["docs/agent-world-environment-generation.zh.md"],
        reviewer_ref="reviewer",
        invocation_ref="invoke-review",
        reviewer_output="not json",
    )

    assert review["alignment_status"] == "fail"


def test_review_pass_with_required_fixes_fails():
    artifact = _need_artifact()
    output = '{"alignment_status":"pass","reviewed_artifact_ids":["%s"],"drift_findings":[],"required_fixes":["fix it"],"waived_risks":[]}' % artifact["id"]
    review = independent_review(
        stage="S0",
        artifact=artifact,
        need_spec=artifact,
        upstream_artifacts=[],
        gate_checklist=["G0", "G1", "G13"],
        source_of_truth_refs=["docs/agent-world-environment-generation.zh.md"],
        reviewer_ref="reviewer",
        invocation_ref="invoke-review",
        reviewer_output=output,
    )
    assert review["alignment_status"] == "fail"


def test_review_normalizes_unstructured_drift_findings():
    artifact = _need_artifact()
    output = (
        '{"alignment_status":"fail","reviewed_artifact_ids":["%s"],'
        '"drift_findings":["too vague"],"required_fixes":[],"waived_risks":[]}'
    ) % artifact["id"]

    review = independent_review(
        stage="S0",
        artifact=artifact,
        need_spec=artifact,
        upstream_artifacts=[],
        gate_checklist=["G0", "G1", "G13"],
        source_of_truth_refs=["docs/agent-world-environment-generation.zh.md"],
        reviewer_ref="reviewer",
        invocation_ref="invoke-review",
        reviewer_output=output,
    )

    assert review["alignment_status"] == "fail"
    assert all({"requirement_ref", "finding", "severity", "evidence"}.issubset(finding) for finding in review["drift_findings"])


def test_surface_gate_rejects_unknown_logical_tool(tmp_path):
    context = _context(tmp_path, stop_after="S7")
    surface = dict(context.artifacts["SurfacePlan"])
    surface["bindings"] = [dict(binding) for binding in surface["bindings"]]
    surface["bindings"][0]["logical_tool_id"] = "missing-tool"
    surface["hash"] = ""
    surface["hash"] = artifact_hash(surface)

    gate = evaluate_gate("G8", "S6", "SurfacePlan", surface, context.artifacts, _review_for(context, "SurfacePlan"), [])

    assert gate["status"] == "fail"
    assert "unknown logical tool" in gate["recovery_suggestion"]


def test_tool_graph_gate_rejects_unknown_state_entity(tmp_path):
    context = _context(tmp_path, stop_after="S7")
    graph = dict(context.artifacts["LogicalToolGraph"])
    graph["tools"] = [dict(tool) for tool in graph["tools"]]
    graph["tools"][0]["reads"] = ["missing_entity"]
    graph["hash"] = ""
    graph["hash"] = artifact_hash(graph)

    gate = evaluate_gate("G5", "S4", "LogicalToolGraph", graph, context.artifacts, _review_for(context, "LogicalToolGraph"), [])

    assert gate["status"] == "fail"
    assert "unknown state entities" in gate["recovery_suggestion"]


def test_tool_graph_gate_rejects_tool_missing_from_environment_spec(tmp_path):
    context = _context(tmp_path, stop_after="S7")
    graph = dict(context.artifacts["LogicalToolGraph"])
    graph["tools"] = [dict(tool) for tool in graph["tools"]]
    extra = dict(graph["tools"][0])
    extra["tool_id"] = "missing_from_env"
    graph["tools"].append(extra)
    graph["hash"] = ""
    graph["hash"] = artifact_hash(graph)

    gate = evaluate_gate("G5", "S4", "LogicalToolGraph", graph, context.artifacts, _review_for(context, "LogicalToolGraph"), [])

    assert gate["status"] == "fail"
    assert "absent from EnvironmentSpec" in gate["recovery_suggestion"]


def test_tool_graph_gate_rejects_missing_required_parameter_catalog_entry(tmp_path):
    context = _context(tmp_path, stop_after="S7")
    graph = dict(context.artifacts["LogicalToolGraph"])
    graph["parameters"] = [dict(parameter) for parameter in graph["parameters"] if parameter["name"] != "payload"]
    graph["hash"] = ""
    graph["hash"] = artifact_hash(graph)

    gate = evaluate_gate("G5", "S4", "LogicalToolGraph", graph, context.artifacts, _review_for(context, "LogicalToolGraph"), [])

    assert gate["status"] == "fail"
    assert "required parameters missing" in gate["recovery_suggestion"]


def _need_artifact():
    return make_artifact(
        "NeedSpec",
        source_stage="S0",
        producer="producer",
        fields={
            "goal": "x",
            "target_capabilities": [],
            "domain_seed": "env-generic",
            "expected_agent_behavior": "x",
            "constraints": {"network": "not_required", "auth": "not_required", "license": "local", "safety": "local", "local_execution": True, "mocking_allowed": True},
            "preferred_surfaces": ["python"],
            "out_of_scope": ["training", "rollout", "reward export", "awm reproduction", "mcp-only", "cli-only"],
            "human_confirmation_required": [],
        },
    )
