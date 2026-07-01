import pytest

from agent_world.artifacts import ArtifactValidationError, make_artifact
from agent_world.gates import evaluate_gate
import agent_world.request_driven as request_driven
from agent_world.review import independent_review


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


def test_strategy_selection_sanitizes_agent_domain_seed_for_artifact_id():
    domain_plan = make_artifact(
        "DomainPlan",
        source_stage="PLAN",
        producer="agent",
        fields={
            "domain_plan_id": "domain-plan-incident",
            "raw_request": "Generate an incident runbook environment",
            "domain_seed": "Create a local incident runbook workflow domain with owners and escalation notes.",
            "domain_intent": "incident runbook",
            "recognized_intents": ["incident"],
            "required_state_objects": ["incident"],
            "required_operations": ["assign_owner"],
            "likely_source_needs": ["raw request"],
            "constraints": {},
            "license_auth_network_security": {},
            "planner_evidence": ["raw request"],
            "planning_status": "planned",
            "blocked_reasons": [],
        },
    )
    fields = request_driven.strategy_selection_fields(domain_plan)

    artifact = make_artifact("StrategySelection", source_stage="SELECT", producer="test", fields=fields, artifact_id=fields["strategy_selection_id"])

    assert artifact["id"].startswith("strategy-selection-create-a-local-incident")
    assert " " not in artifact["id"]


def test_state_reset_gate_accepts_object_shaped_entity_ids():
    env_spec = {
        "id": "env-artifact",
        "state_backend": {
            "kind": "in_memory",
            "reset_strategy": "reset_to_seed_fixture",
            "isolation_strategy": "per_run_isolated_state",
            "seed_fixture_refs": ["fixture:initial-state"],
        },
        "state_entities": [{"object_id": "alert_record"}],
        "logical_tools": [{"tool_id": "op-log-alert"}],
    }
    context = {
        "KnowledgePack": {
            "state_objects": [{"state_object_id": "alert_record"}],
            "operations": [{"operation_id": "op-log-alert"}],
        }
    }
    gate = evaluate_gate("G4", "S3", "EnvironmentSpec", env_spec, context, {"id": "review-record"}, [])

    assert gate["status"] == "pass"


def test_tool_graph_gate_accepts_environment_entity_id_aliases():
    graph = {
        "id": "graph-artifact",
        "tools": [{"tool_id": "op-track-alerts", "reads": ["entity-incidents"], "writes": ["entity-alerts"]}],
        "edges": [],
        "parameters": [],
        "forbidden_direct_access": [],
    }
    context = {
        "EnvironmentSpec": {
            "state_entities": [
                {"entity_id": "entity-incidents", "state_object_id": "obj-incident"},
                {"entity_id": "entity-alerts", "state_object_id": "obj-alert"},
            ],
            "logical_tools": [{"tool_id": "op-track-alerts"}],
        }
    }
    gate = evaluate_gate("G5", "S4", "LogicalToolGraph", graph, context, {"id": "review-record"}, [])

    assert gate["status"] == "pass"


def test_logical_tool_graph_rejects_parameter_map_with_contract_error():
    fields = {
        "tools": [
            {
                "tool_id": "op-log-alert",
                "name": "Log alert",
                "input_schema": {"required": ["alert_id"], "optional": []},
                "output_schema": {"updated": ["alert"]},
                "reads": ["alert"],
                "writes": ["alert"],
                "side_effects": ["creates alert record"],
                "errors": ["missing alert_id"],
                "idempotency": "not_idempotent",
            }
        ],
        "edges": [],
        "parameters": {"op-log-alert": {"required": ["alert_id"], "optional": []}},
        "forbidden_direct_access": [],
    }

    with pytest.raises(ArtifactValidationError, match="parameters must be a list"):
        make_artifact("LogicalToolGraph", source_stage="S4", producer="test", fields=fields)


def test_task_set_rejects_edge_object_dependency_path():
    fields = {
        "tasks": [
            {
                "task_id": "task-bad-path",
                "natural_request": "Create an alert and assign an owner.",
                "target_capability": "alert ownership",
                "initial_state_refs": ["seed"],
                "expected_state_delta": {"updated": ["alert"]},
                "expected_answer": "",
                "allowed_logical_tool_ids": ["op-create-alert", "op-assign-owner"],
                "forbidden_leakage": [],
                "dependency_path": [{"from_tool_id": "op-create-alert", "to_tool_id": "op-assign-owner"}],
                "difficulty": "easy",
                "verifier_refs": ["verifier-alert-owner"],
            }
        ],
        "coverage": {"tool_ids": ["op-create-alert"], "capabilities": ["alert ownership"], "state_entities": ["alert"]},
        "rejected_candidates": [],
    }

    with pytest.raises(ArtifactValidationError, match="dependency_path must contain tool id strings"):
        make_artifact("TaskSet", source_stage="S5", producer="test", fields=fields)


def test_surface_plan_rejects_object_status_values():
    fields = {
        "bindings": [
            {
                "binding_id": "bind-op-python",
                "logical_tool_id": "op-create-alert",
                "surface": "python",
                "exposure_name": "create_alert",
                "input_mapping": {},
                "output_mapping": {},
                "error_mapping": {},
                "auth_context": {},
                "state_scope": ["alert"],
            }
        ],
        "surface_status": {"python": {"required_for_first_slice": True}},
        "compatibility_notes": [],
    }

    with pytest.raises(ArtifactValidationError, match="surface_status values must be status strings"):
        make_artifact("SurfacePlan", source_stage="S6", producer="test", fields=fields)


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


def test_review_allows_explicit_scope_exclusions_without_scope_drift():
    need = _need_artifact()
    artifact = make_artifact(
        "KnowledgePack",
        source_stage="S2",
        producer="producer",
        fields={
            "state_objects": [{"object_id": "obj_work_item", "name": "work item", "source_refs": ["source"]}],
            "operations": [{"operation_id": "op_create_work_item", "name": "create work item", "source_refs": ["source"]}],
            "business_rules": [],
            "verifiable_fields": [
                {
                    "field_id": "field_scope_exclusions",
                    "statement": "Runtime package must not include training, rollout, or reward export.",
                    "source_refs": ["source"],
                }
            ],
            "uncertainties": [],
        },
    )

    review = independent_review(
        stage="S2",
        artifact=artifact,
        need_spec=need,
        upstream_artifacts=[need],
        gate_checklist=["G0", "G2", "G13"],
        source_of_truth_refs=["docs/agent-world-environment-generation.zh.md"],
        reviewer_ref="reviewer",
    )

    assert review["alignment_status"] == "pass"
    assert review["drift_findings"] == []


def test_review_still_rejects_positive_training_scope_drift():
    need = _need_artifact()
    artifact = make_artifact(
        "KnowledgePack",
        source_stage="S2",
        producer="producer",
        fields={
            "state_objects": [{"object_id": "obj_work_item", "name": "work item", "source_refs": ["source"]}],
            "operations": [{"operation_id": "op_train_reward", "name": "training integration", "source_refs": ["source"]}],
            "business_rules": [],
            "verifiable_fields": [{"field_id": "field_reward", "statement": "Add reward export for training integration.", "source_refs": ["source"]}],
            "uncertainties": [],
        },
    )

    review = independent_review(
        stage="S2",
        artifact=artifact,
        need_spec=need,
        upstream_artifacts=[need],
        gate_checklist=["G0", "G2", "G13"],
        source_of_truth_refs=["docs/agent-world-environment-generation.zh.md"],
        reviewer_ref="reviewer",
    )

    assert review["alignment_status"] == "fail"
    assert {finding["finding"] for finding in review["drift_findings"]} >= {
        "artifact may drift toward training integration",
        "artifact may drift toward reward export",
    }


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
            "constraints": {"network": "not_required", "auth": "not_required", "license": "local", "safety": "local", "local_execution": True, "mocking_allowed": False},
            "preferred_surfaces": ["python"],
            "out_of_scope": ["training", "rollout", "reward export", "awm reproduction", "mcp-only", "cli-only"],
            "human_confirmation_required": [],
        },
    )
