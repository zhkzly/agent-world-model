from types import SimpleNamespace

from agent_world.canonical_ids import canonicalize_stage_fields


def test_s2_generates_framework_owned_knowledge_ids():
    fields = {
        "state_objects": [{"state_object_id": "llm-alert-record", "name": "Alert"}],
        "operations": [{"tool_id": "tool-create-incident-from-alert", "name": "Create incident from alert"}],
        "business_rules": [{"statement": "Closing requires a final resolution note."}],
        "verifiable_fields": [{"object_id": "llm-alert-record", "name": "severity"}],
        "uncertainties": [],
    }

    result = canonicalize_stage_fields(_context(), "S2", fields)

    assert result["state_objects"][0]["object_id"] == "obj_alert"
    assert result["state_objects"][0]["state_object_id"] == "obj_alert"
    assert result["operations"][0]["operation_id"] == "op_create_incident_from_alert"
    assert result["operations"][0]["tool_id"] == "op_create_incident_from_alert"
    assert result["business_rules"][0]["rule_id"].startswith("rule_closing_requires")
    assert result["verifiable_fields"][0]["object_id"] == "obj_alert"


def test_s3_reuses_knowledge_pack_canonical_ids():
    context = _context(
        KnowledgePack={
            "state_objects": [{"object_id": "obj_alert", "name": "Alert"}],
            "operations": [{"operation_id": "op_create_incident_from_alert", "name": "Create incident from alert"}],
        }
    )
    fields = {
        "state_entities": [{"entity_id": "entity-alerts", "name": "alerts"}],
        "logical_tools": [{"tool_id": "tool-create-incident-from-alert", "name": "Create incident from alert"}],
    }

    result = canonicalize_stage_fields(context, "S3", fields)

    assert result["state_entities"][0]["object_id"] == "obj_alert"
    assert result["state_entities"][0]["entity_id"] == "obj_alert"
    assert result["logical_tools"][0]["tool_id"] == "op_create_incident_from_alert"


def test_s4_rewrites_graph_references_to_environment_ids():
    context = _context(
        EnvironmentSpec={
            "state_entities": [{"object_id": "obj_alert", "entity_id": "entity-alerts", "name": "alerts"}],
            "logical_tools": [{"tool_id": "op_create_incident_from_alert", "name": "Create incident from alert"}],
        }
    )
    fields = {
        "tools": [
            {
                "tool_id": "tool-create-incident-from-alert",
                "name": "Create incident from alert",
                "reads": ["entity-alerts"],
                "writes": ["alerts"],
            }
        ],
        "edges": [{"from": "tool-create-incident-from-alert", "to": "tool-create-incident-from-alert", "dependency_type": "strong"}],
        "parameters": [],
        "forbidden_direct_access": [],
    }

    result = canonicalize_stage_fields(context, "S4", fields)

    assert result["tools"][0]["tool_id"] == "op_create_incident_from_alert"
    assert result["tools"][0]["reads"] == ["obj_alert"]
    assert result["tools"][0]["writes"] == ["obj_alert"]
    assert result["edges"][0]["from_tool_id"] == "op_create_incident_from_alert"
    assert result["edges"][0]["to_tool_id"] == "op_create_incident_from_alert"
    assert "from" not in result["edges"][0]


def test_s5_and_s7_generate_task_and_verifier_ids_in_framework():
    context = _context(
        EnvironmentSpec={"state_entities": [{"object_id": "obj_alert", "name": "Alert"}]},
        LogicalToolGraph={"tools": [{"tool_id": "op_create_alert", "name": "Create alert"}]},
    )
    task_fields = {
        "tasks": [
            {
                "task_id": "llm-task",
                "natural_request": "Create a critical alert.",
                "target_capability": "Create alert",
                "allowed_logical_tool_ids": ["tool-create-alert"],
                "dependency_path": [{"from_tool_id": "tool-create-alert", "to_tool_id": "tool-create-alert"}],
                "framework_replay": [{"tool_id": "tool-create-alert", "input": {}}],
                "verifier_refs": ["llm-verifier"],
            }
        ],
        "coverage": {"tool_ids": ["tool-create-alert"], "state_entities": ["alerts"], "capabilities": ["Create alert"]},
    }

    task_result = canonicalize_stage_fields(context, "S5", task_fields)
    task_id = task_result["tasks"][0]["task_id"]

    assert task_id.startswith("task_001_create_alert")
    assert task_result["tasks"][0]["allowed_logical_tool_ids"] == ["op_create_alert"]
    assert task_result["tasks"][0]["dependency_path"] == ["op_create_alert"]
    assert task_result["tasks"][0]["framework_replay"][0]["tool_id"] == "op_create_alert"
    assert task_result["tasks"][0]["verifier_refs"] == [f"verifier_{task_id}"]
    assert "_task_id_aliases" not in task_result

    verifier_result = canonicalize_stage_fields(
        _context(TaskSet=task_result),
        "S7",
        {
            "verifiers": [
                {
                    "verifier_id": "llm-verifier",
                    "task_id": "Create alert",
                    "assertions": [{"assertion_id": "llm-assert", "target": "dependency_path_trace_matches"}],
                }
            ],
            "llm_judges": [],
        },
    )

    assert verifier_result["verifiers"][0]["task_id"] == task_id
    assert verifier_result["verifiers"][0]["verifier_id"] == f"verifier_{task_id}"
    assert verifier_result["verifiers"][0]["assertions"][0]["assertion_id"].startswith(f"assert_verifier_{task_id}")


def _context(**artifacts):
    return SimpleNamespace(artifacts=artifacts)
