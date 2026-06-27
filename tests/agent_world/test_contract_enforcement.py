import json

import pytest

from agent_world.artifacts import ArtifactValidationError, artifact_hash, make_artifact
from agent_world.gates import evaluate_gate
from agent_world.replay import replay_package
from agent_world.review import independent_review
from agent_world.workflow import FirstSliceWorkflow


def _review_for(result, artifact_type):
    artifact_id = result.artifacts[artifact_type]["id"]
    return next(record for record in result.review_records if artifact_id in record["reviewed_artifact_ids"])


def test_nested_task_schema_rejects_missing_verifier_refs():
    fields = {
        "tasks": [
            {
                "task_id": "task-bad",
                "natural_request": "Do the thing",
                "target_capability": "bad",
                "initial_state_refs": ["seed"],
                "expected_state_delta": {},
                "expected_answer": "ok",
                "allowed_logical_tool_ids": ["search_tickets"],
                "forbidden_leakage": [],
                "dependency_path": ["search_tickets"],
                "difficulty": {},
            }
        ],
        "coverage": {"tool_ids": ["search_tickets"], "capabilities": ["read"], "state_entities": ["ticket"]},
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
    workflow = FirstSliceWorkflow()
    result = workflow.run(output_dir=tmp_path / "envpkg")
    report = dict(result.artifacts["FeasibilityReport"])
    report["minimum_viable_task_ids"] = ["missing-task"]
    report["hash"] = ""
    report["hash"] = artifact_hash(report)
    review = _review_for(result, "FeasibilityReport")

    gate = evaluate_gate("G10", "S8", "FeasibilityReport", report, result.artifacts, review, [])

    assert gate["status"] == "fail"
    assert "unknown tasks" in gate["recovery_suggestion"]


def test_task_gate_rejects_unknown_tool_ref(tmp_path):
    workflow = FirstSliceWorkflow()
    result = workflow.run(output_dir=tmp_path / "envpkg")
    task_set = dict(result.artifacts["TaskSet"])
    task_set["tasks"] = [dict(task) for task in task_set["tasks"]]
    task_set["tasks"][0]["allowed_logical_tool_ids"] = ["missing_tool"]
    task_set["hash"] = ""
    task_set["hash"] = artifact_hash(task_set)

    gate = evaluate_gate("G6", "S5", "TaskSet", task_set, result.artifacts, _review_for(result, "TaskSet"), [])

    assert gate["status"] == "fail"
    assert "unknown logical tools" in gate["recovery_suggestion"]


def test_task_gate_rejects_dependency_path_outside_allowed_tools(tmp_path):
    workflow = FirstSliceWorkflow()
    result = workflow.run(output_dir=tmp_path / "envpkg")
    task_set = dict(result.artifacts["TaskSet"])
    task_set["tasks"] = [dict(task) for task in task_set["tasks"]]
    task_set["tasks"][0]["dependency_path"] = ["search_tickets", "resolve_ticket"]
    task_set["hash"] = ""
    task_set["hash"] = artifact_hash(task_set)

    gate = evaluate_gate("G6", "S5", "TaskSet", task_set, result.artifacts, _review_for(result, "TaskSet"), [])

    assert gate["status"] == "fail"
    assert "outside allowed tools" in gate["recovery_suggestion"]


def test_feasibility_report_contains_structured_gate_results(tmp_path):
    result = FirstSliceWorkflow().run(output_dir=tmp_path / "envpkg")
    report = result.artifacts["FeasibilityReport"]

    assert report["gate_results"]
    assert {"gate_id", "status", "evidence", "failure_class", "recovery_suggestion"}.issubset(report["gate_results"][0])


def test_feasibility_gate_rejects_empty_gate_results(tmp_path):
    result = FirstSliceWorkflow().run(output_dir=tmp_path / "envpkg")
    report = dict(result.artifacts["FeasibilityReport"])
    report["gate_results"] = []
    report["hash"] = ""
    report["hash"] = artifact_hash(report)

    gate = evaluate_gate("G10", "S8", "FeasibilityReport", report, result.artifacts, _review_for(result, "FeasibilityReport"), [])

    assert gate["status"] == "fail"
    assert "upstream gate results" in gate["recovery_suggestion"]


def test_feasibility_report_declares_upstream_gate_scope(tmp_path):
    result = FirstSliceWorkflow().run(output_dir=tmp_path / "envpkg")
    report = dict(result.artifacts["FeasibilityReport"])

    assert report["gate_result_scope"] == "upstream_accepted_gates_before_s8_self_evaluation"
    assert set(report["self_gate_expectations"]) == {"G0", "G10", "G13"}


def test_review_invocation_output_must_be_structured():
    artifact = make_artifact(
        "NeedSpec",
        source_stage="S0",
        producer="producer",
        fields={
            "goal": "x",
            "target_capabilities": [],
            "domain_seed": "support-desk-lite",
            "expected_agent_behavior": "x",
            "constraints": {"network": "not_required", "auth": "not_required", "license": "local", "safety": "local", "local_execution": True, "mocking_allowed": True},
            "preferred_surfaces": ["python"],
            "out_of_scope": ["training", "rollout", "reward export", "awm reproduction", "mcp-only", "cli-only"],
            "human_confirmation_required": [],
        },
    )
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
    artifact = make_artifact(
        "NeedSpec",
        source_stage="S0",
        producer="producer",
        fields={
            "goal": "x",
            "target_capabilities": [],
            "domain_seed": "support-desk-lite",
            "expected_agent_behavior": "x",
            "constraints": {"network": "not_required", "auth": "not_required", "license": "local", "safety": "local", "local_execution": True, "mocking_allowed": True},
            "preferred_surfaces": ["python"],
            "out_of_scope": ["training", "rollout", "reward export", "awm reproduction", "mcp-only", "cli-only"],
            "human_confirmation_required": [],
        },
    )
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
    artifact = make_artifact(
        "NeedSpec",
        source_stage="S0",
        producer="producer",
        fields={
            "goal": "x",
            "target_capabilities": [],
            "domain_seed": "support-desk-lite",
            "expected_agent_behavior": "x",
            "constraints": {"network": "not_required", "auth": "not_required", "license": "local", "safety": "local", "local_execution": True, "mocking_allowed": True},
            "preferred_surfaces": ["python"],
            "out_of_scope": ["training", "rollout", "reward export", "awm reproduction", "mcp-only", "cli-only"],
            "human_confirmation_required": [],
        },
    )
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
    result = FirstSliceWorkflow().run(output_dir=tmp_path / "envpkg")
    surface = dict(result.artifacts["SurfacePlan"])
    surface["bindings"] = [dict(binding) for binding in surface["bindings"]]
    surface["bindings"][0]["logical_tool_id"] = "missing-tool"
    surface["hash"] = ""
    surface["hash"] = artifact_hash(surface)

    gate = evaluate_gate("G8", "S6", "SurfacePlan", surface, result.artifacts, _review_for(result, "SurfacePlan"), [])

    assert gate["status"] == "fail"
    assert "unknown logical tool" in gate["recovery_suggestion"]


def test_tool_graph_gate_rejects_unknown_state_entity(tmp_path):
    result = FirstSliceWorkflow().run(output_dir=tmp_path / "envpkg")
    graph = dict(result.artifacts["LogicalToolGraph"])
    graph["tools"] = [dict(tool) for tool in graph["tools"]]
    graph["tools"][0]["reads"] = ["missing_entity"]
    graph["hash"] = ""
    graph["hash"] = artifact_hash(graph)

    gate = evaluate_gate("G5", "S4", "LogicalToolGraph", graph, result.artifacts, _review_for(result, "LogicalToolGraph"), [])

    assert gate["status"] == "fail"
    assert "unknown state entities" in gate["recovery_suggestion"]


def test_tool_graph_gate_rejects_tool_missing_from_environment_spec(tmp_path):
    result = FirstSliceWorkflow().run(output_dir=tmp_path / "envpkg")
    graph = dict(result.artifacts["LogicalToolGraph"])
    graph["tools"] = [dict(tool) for tool in graph["tools"]]
    extra = dict(graph["tools"][0])
    extra["tool_id"] = "missing_from_env"
    graph["tools"].append(extra)
    graph["hash"] = ""
    graph["hash"] = artifact_hash(graph)

    gate = evaluate_gate("G5", "S4", "LogicalToolGraph", graph, result.artifacts, _review_for(result, "LogicalToolGraph"), [])

    assert gate["status"] == "fail"
    assert "absent from EnvironmentSpec" in gate["recovery_suggestion"]


def test_tool_graph_gate_rejects_missing_required_parameter_catalog_entry(tmp_path):
    result = FirstSliceWorkflow().run(output_dir=tmp_path / "envpkg")
    graph = dict(result.artifacts["LogicalToolGraph"])
    graph["parameters"] = [dict(parameter) for parameter in graph["parameters"] if parameter["name"] != "body"]
    graph["hash"] = ""
    graph["hash"] = artifact_hash(graph)

    gate = evaluate_gate("G5", "S4", "LogicalToolGraph", graph, result.artifacts, _review_for(result, "LogicalToolGraph"), [])

    assert gate["status"] == "fail"
    assert "required parameters missing" in gate["recovery_suggestion"]


def test_tool_graph_gate_rejects_missing_optional_parameter_catalog_entry(tmp_path):
    result = FirstSliceWorkflow().run(output_dir=tmp_path / "envpkg")
    graph = dict(result.artifacts["LogicalToolGraph"])
    graph["parameters"] = [dict(parameter) for parameter in graph["parameters"] if parameter["name"] != "keyword"]
    graph["hash"] = ""
    graph["hash"] = artifact_hash(graph)

    gate = evaluate_gate("G5", "S4", "LogicalToolGraph", graph, result.artifacts, _review_for(result, "LogicalToolGraph"), [])

    assert gate["status"] == "fail"
    assert "optional parameters missing" in gate["recovery_suggestion"]


def test_package_gate_rejects_dangling_review_ref(tmp_path):
    result = FirstSliceWorkflow().run(output_dir=tmp_path / "envpkg")
    plan = dict(result.artifacts["EnvironmentPackagePlan"])
    plan["review_record_refs"] = ["missing-review"]
    plan["hash"] = ""
    plan["hash"] = artifact_hash(plan)

    gate = evaluate_gate("G11", "S10", "EnvironmentPackagePlan", plan, result.artifacts, _review_for(result, "EnvironmentPackagePlan"), [])

    assert gate["status"] == "fail"
    assert "review_record_ref" in gate["recovery_suggestion"]


def test_release_gate_rejects_hash_mismatch(tmp_path):
    result = FirstSliceWorkflow().run(output_dir=tmp_path / "envpkg")
    release = dict(result.artifacts["ReleaseManifest"])
    release["artifact_hashes"] = dict(release["artifact_hashes"])
    release["artifact_hashes"]["TaskSet"] = "wrong"
    release["hash"] = ""
    release["hash"] = artifact_hash(release)

    gate = evaluate_gate("G12", "S11", "ReleaseManifest", release, result.artifacts, _review_for(result, "ReleaseManifest"), [])

    assert gate["status"] == "fail"
    assert "artifact_hashes mismatch" in gate["recovery_suggestion"]


def test_release_gate_rejects_missing_task_index(tmp_path):
    result = FirstSliceWorkflow().run(output_dir=tmp_path / "envpkg")
    release = dict(result.artifacts["ReleaseManifest"])
    release["task_index"] = release["task_index"][:-1]
    release["hash"] = ""
    release["hash"] = artifact_hash(release)

    gate = evaluate_gate("G12", "S11", "ReleaseManifest", release, result.artifacts, _review_for(result, "ReleaseManifest"), [])

    assert gate["status"] == "fail"
    assert "exactly cover accepted tasks" in gate["recovery_suggestion"]


def test_package_local_replay_command_succeeds(tmp_path):
    result = FirstSliceWorkflow().run(output_dir=tmp_path / "envpkg")

    replay_result = replay_package(result.package.package_dir, "task-1")
    replay_result_2 = replay_package(result.package.package_dir, "task-1")

    assert replay_result["success"] is True
    assert replay_result_2["success"] is True
    trace_text = (result.package.package_dir / "checks" / "surface-traces.jsonl").read_text()
    assert "initial_snapshot_hash" in trace_text
    assert "search_tickets" in trace_text
    summaries = [json.loads(line) for line in trace_text.splitlines() if line.strip() and "surface_calls" in json.loads(line)]
    assert [summary["call_group"] for summary in summaries] == ["task-1-run-1", "task-1-run-2"]


def test_replay_plan_requires_command_for_each_task(tmp_path):
    result = FirstSliceWorkflow().run(output_dir=tmp_path / "envpkg")
    replay_plan = dict(result.artifacts["ReplayPlan"])
    replay_plan["replay_commands"] = replay_plan["replay_commands"][:1]
    replay_plan["hash"] = ""
    replay_plan["hash"] = artifact_hash(replay_plan)

    with pytest.raises(ArtifactValidationError):
        from agent_world.artifacts import validate_artifact

        validate_artifact("ReplayPlan", replay_plan)


def test_replay_plan_trace_schema_covers_declared_inputs(tmp_path):
    result = FirstSliceWorkflow().run(output_dir=tmp_path / "envpkg")
    replay_plan = dict(result.artifacts["ReplayPlan"])
    replay_plan["execution_trace_schema"] = dict(replay_plan["execution_trace_schema"])
    replay_plan["execution_trace_schema"].pop("final_answer")
    replay_plan["hash"] = ""
    replay_plan["hash"] = artifact_hash(replay_plan)

    with pytest.raises(ArtifactValidationError):
        from agent_world.artifacts import validate_artifact

        validate_artifact("ReplayPlan", replay_plan)


def test_verifier_rejects_direct_tool_use_when_trace_path_expected(tmp_path):
    from agent_world.fixtures.support_desk_lite import SupportDeskLite, create_seed_db, reset_environment, verify_task_completion

    seed = create_seed_db(tmp_path / "seed.sqlite")
    final = reset_environment(seed, tmp_path / "run")
    trace = tmp_path / "trace.jsonl"
    surface = SupportDeskLite(final, trace_path=trace, task_id="task-1")
    surface.add_ticket_note(ticket_id="T-100", visibility="internal", body="Refund follow-up queued with billing.")

    result = verify_task_completion(
        "task-1",
        seed,
        final,
        surface_trace_path=trace,
        expected_dependency_path=["search_tickets", "get_ticket", "add_ticket_note"],
    )

    assert result["success"] is False
    assert any(check["name"] == "dependency_path_trace_matches" and check["passed"] is False for check in result["checks"])
