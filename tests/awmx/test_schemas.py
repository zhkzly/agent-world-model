from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from awmx.artifacts import schemas
from awmx.config import load_agent_world_config, load_workflow_config


def _artifact_payload(**overrides):
    payload = {
        "id": "artifact.demo",
        "version": "0.1.0",
        "created_at": "2026-06-27T00:00:00Z",
        "source": {"kind": "fixture", "uri": "tests/awmx/test_schemas.py"},
        "metadata": {"suite": "contracts"},
    }
    payload.update(overrides)
    return payload


def test_contracts_cover_minimum_agent_world_artifacts():
    expected = {
        "scenario",
        "task",
        "environment",
        "tool",
        "verifier",
        "workflow",
        "run",
        "trace",
        "reward",
    }

    assert expected.issubset(schemas.SCHEMA_REGISTRY)
    for artifact_type in expected:
        assert issubclass(schemas.SCHEMA_REGISTRY[artifact_type], schemas.BaseArtifact)


def test_every_artifact_requires_common_metadata():
    for artifact_type, schema_cls in schemas.SCHEMA_REGISTRY.items():
        for field_name in ("id", "version", "created_at", "source", "metadata"):
            assert field_name in schema_cls.fields(), artifact_type

    with pytest.raises(schemas.ValidationError, match="metadata"):
        schemas.ScenarioSpec(
            **_artifact_payload(metadata=None),
            name="ticketing",
            description="Ticketing workflow scenario.",
        )


def test_artifact_validation_roundtrip_and_json_ready_dicts():
    task = schemas.TaskSpec(
        **_artifact_payload(id="task.ticketing.close_stale"),
        scenario_id="scenario.ticketing",
        prompt="Close stale resolved tickets.",
        success_criteria=["Resolved tickets older than 30 days are closed."],
        allowed_tool_ids=["tool.ticketing.update_ticket"],
    )

    as_dict = task.to_dict()

    assert as_dict["id"] == "task.ticketing.close_stale"
    assert as_dict["source"]["kind"] == "fixture"
    assert as_dict["success_criteria"] == ["Resolved tickets older than 30 days are closed."]
    assert schemas.TaskSpec.from_dict(as_dict) == task


def test_environment_tool_verifier_and_trace_contracts_validate():
    environment = schemas.EnvironmentSpec(
        **_artifact_payload(id="environment.ticketing"),
        scenario_id="scenario.ticketing",
        state_backend={"kind": "sqlite", "db_path": "outputs/agent_world/demo/initial.db"},
        runtime={"kind": "awm_mcp", "env_code_ref": "research/data/awm_1k_samples/gen_envs.jsonl"},
        tool_ids=["tool.ticketing.update_ticket"],
    )
    tool = schemas.ToolSpec(
        **_artifact_payload(id="tool.ticketing.update_ticket"),
        name="update_ticket",
        adapter_type="mcp",
        input_schema={"type": "object"},
        output_schema={"type": "object"},
        side_effects=["database_write"],
        permissions={"mcp_tools": ["update_ticket"]},
    )
    verifier = schemas.VerifierSpec(
        **_artifact_payload(id="verifier.ticketing.close_stale"),
        target_task_id="task.ticketing.close_stale",
        verifier_type="pure_code",
        deterministic=True,
        inputs={"initial_db_path": "initial.db", "final_db_path": "final.db"},
        reward_mapping={"passed": 1.0, "failed": 0.0},
    )
    trace = schemas.TraceRecord(
        **_artifact_payload(id="trace.run_demo.0001"),
        run_id="run.demo",
        sequence=1,
        event_type="observation",
        actor="scripted",
        action={"kind": "tool_call", "tool_id": "tool.ticketing.update_ticket"},
        observation={"status": "ok"},
        evidence={"stdout_path": "logs/step-0001.stdout"},
    )

    assert environment.state_backend["kind"] == "sqlite"
    assert tool.adapter_type == "mcp"
    assert verifier.deterministic is True
    assert trace.sequence == 1

    runner_trace = schemas.TraceRecord(
        **_artifact_payload(id="trace.run_demo.0002"),
        run_id="run.demo",
        sequence=2,
        event_type="runner_step",
        actor="scripted",
        action={"kind": "message", "content": "ok"},
        observation={"status": "ok"},
        evidence={"permission": {"allowed": True, "kind": "message"}},
    )
    assert runner_trace.evidence["permission"]["allowed"] is True


@pytest.mark.parametrize(
    ("schema_cls", "payload", "match"),
    [
        (
            schemas.EnvironmentSpec,
            {
                "scenario_id": "scenario.ticketing",
                "state_backend": {},
                "runtime": {"kind": "awm_mcp"},
                "tool_ids": [],
            },
            "state_backend.kind",
        ),
        (
            schemas.ToolSpec,
            {
                "name": "update_ticket",
                "adapter_type": "",
                "input_schema": {},
                "output_schema": {},
                "side_effects": [],
                "permissions": {},
            },
            "adapter_type",
        ),
        (
            schemas.VerifierSpec,
            {
                "target_task_id": "task.ticketing.close_stale",
                "verifier_type": "pure_code",
                "deterministic": "yes",
                "inputs": {},
                "reward_mapping": {},
            },
            "deterministic",
        ),
        (
            schemas.TraceRecord,
            {
                "run_id": "run.demo",
                "sequence": 0,
                "event_type": "observation",
                "actor": "scripted",
                "action": {},
                "observation": {},
                "evidence": {},
            },
            "sequence",
        ),
        (
            schemas.TraceRecord,
            {
                "run_id": "run.demo",
                "sequence": 1,
                "event_type": "runner_step",
                "actor": "scripted",
                "action": {"kind": "message"},
                "observation": {},
                "evidence": {},
            },
            "permission",
        ),
    ],
)
def test_artifact_specific_validation_rejects_invalid_payloads(schema_cls, payload, match):
    with pytest.raises(schemas.ValidationError, match=match):
        schema_cls(**_artifact_payload(), **payload)


def test_run_contract_is_runner_neutral():
    run_schema_source = inspect.getsource(schemas.RunSpec)
    disallowed_backend_names = ("mini_swe", "mini-swe", "codex_sdk", "codex-sdk", "deep_search")

    for backend_name in disallowed_backend_names:
        assert backend_name not in run_schema_source

    run = schemas.RunSpec(
        **_artifact_payload(id="run.demo"),
        workflow_id="workflow.vertical_slice",
        environment_id="environment.ticketing",
        task_id="task.ticketing.close_stale",
        runner={"type": "scripted", "config_ref": "configs/agent_world/runners/scripted.yaml"},
        budgets={"max_steps": 4},
    )

    assert run.runner["type"] == "scripted"


def test_reward_must_come_from_verifier():
    with pytest.raises(schemas.ValidationError, match="verifier"):
        schemas.RewardRecord(
            **_artifact_payload(id="reward.bad", source={"kind": "verifier", "uri": "reward.json"}),
            run_id="run.demo",
            task_id="task.ticketing.close_stale",
            verifier_id="",
            passed=True,
            score=1.0,
            evidence={"runner_final_answer": "done"},
            failure_reason=None,
        )

    reward = schemas.RewardRecord(
        **_artifact_payload(id="reward.good", source={"kind": "verifier", "uri": "reward.json"}),
        run_id="run.demo",
        task_id="task.ticketing.close_stale",
        verifier_id="verifier.ticketing.close_stale",
        passed=True,
        score=1.0,
        evidence={"checks": [{"name": "db_state", "passed": True, "detail": "state matched"}]},
        failure_reason=None,
    )

    assert reward.to_dict()["score"] == 1.0

    with pytest.raises(schemas.ValidationError, match="runner_final_answer"):
        schemas.RewardRecord(
            **_artifact_payload(id="reward.runner_only", source={"kind": "verifier", "uri": "reward.json"}),
            run_id="run.demo",
            task_id="task.ticketing.close_stale",
            verifier_id="verifier.ticketing.close_stale",
            passed=True,
            score=1.0,
            evidence={"runner_final_answer": "done"},
            failure_reason=None,
        )

    with pytest.raises(schemas.ValidationError, match="source.kind"):
        schemas.RewardRecord(
            **_artifact_payload(id="reward.non_verifier"),
            run_id="run.demo",
            task_id="task.ticketing.close_stale",
            verifier_id="verifier.ticketing.close_stale",
            passed=True,
            score=1.0,
            evidence={"checks": [{"name": "db_state", "passed": True, "detail": "state matched"}]},
            failure_reason=None,
        )

    with pytest.raises(schemas.ValidationError, match="runner_final_answer"):
        schemas.RewardRecord(
            **_artifact_payload(id="reward.mixed", source={"kind": "verifier", "uri": "reward.json"}),
            run_id="run.demo",
            task_id="task.ticketing.close_stale",
            verifier_id="verifier.ticketing.close_stale",
            passed=True,
            score=1.0,
            evidence={
                "checks": [{"name": "db_state", "passed": True, "detail": "state matched"}],
                "runner_final_answer": "done",
            },
            failure_reason=None,
        )


def test_reward_requires_replayable_verifier_source():
    with pytest.raises(schemas.ValidationError, match="source.uri"):
        schemas.RewardRecord(
            **_artifact_payload(id="reward.no_source_uri", source={"kind": "verifier"}),
            run_id="run.demo",
            task_id="task.ticketing.close_stale",
            verifier_id="verifier.ticketing.close_stale",
            passed=True,
            score=1.0,
            evidence={"checks": [{"name": "db_state", "passed": True, "detail": "state matched"}]},
            failure_reason=None,
        )


def test_reward_checks_must_match_reward_status():
    with pytest.raises(schemas.ValidationError, match="passed reward"):
        schemas.RewardRecord(
            **_artifact_payload(id="reward.false_check", source={"kind": "verifier", "uri": "reward.json"}),
            run_id="run.demo",
            task_id="task.ticketing.close_stale",
            verifier_id="verifier.ticketing.close_stale",
            passed=True,
            score=1.0,
            evidence={
                "checks": [
                    {
                        "name": "db_state",
                        "passed": False,
                        "detail": "state diverged",
                        "failure_reason": "state diverged",
                    }
                ]
            },
            failure_reason=None,
        )

    with pytest.raises(schemas.ValidationError, match="failed reward"):
        schemas.RewardRecord(
            **_artifact_payload(id="reward.true_checks", source={"kind": "verifier", "uri": "reward.json"}),
            run_id="run.demo",
            task_id="task.ticketing.close_stale",
            verifier_id="verifier.ticketing.close_stale",
            passed=False,
            score=0.0,
            evidence={"checks": [{"name": "db_state", "passed": True, "detail": "state matched"}]},
            failure_reason="verifier failed",
        )


def test_reward_rejects_mixed_or_nested_runner_evidence():
    with pytest.raises(schemas.ValidationError, match="mixed verifier evidence"):
        schemas.RewardRecord(
            **_artifact_payload(id="reward.mixed_evidence", source={"kind": "verifier", "uri": "verifier.py"}),
            run_id="run.demo",
            task_id="task.ticketing.close_stale",
            verifier_id="verifier.ticketing.close_stale",
            passed=True,
            score=1.0,
            evidence={
                "checks": [{"name": "db_state", "passed": True, "detail": "state matched"}],
                "verifier_outputs": {
                    "checks": [
                        {
                            "name": "db_state",
                            "passed": False,
                            "detail": "state diverged",
                            "failure_reason": "state diverged",
                        }
                    ]
                },
            },
            failure_reason=None,
        )

    with pytest.raises(schemas.ValidationError, match="runner_final_answer"):
        schemas.RewardRecord(
            **_artifact_payload(id="reward.nested_runner_answer", source={"kind": "verifier", "uri": "verifier.py"}),
            run_id="run.demo",
            task_id="task.ticketing.close_stale",
            verifier_id="verifier.ticketing.close_stale",
            passed=True,
            score=1.0,
            evidence={
                "checks": [
                    {
                        "name": "db_state",
                        "passed": True,
                        "details": {"runner_final_answer": "claimed success"},
                    }
                ]
            },
            failure_reason=None,
        )


def test_base_config_and_vertical_slice_load():
    config = load_agent_world_config(Path("configs/agent_world/base.yaml"))
    workflow = load_workflow_config(Path("configs/agent_world/workflows/vertical_slice.yaml"))

    assert config["paths"]["config_root"] == "configs/agent_world"
    assert config["paths"]["output_root"] == "outputs/agent_world"
    assert config["policies"]["first_stage_backends"] == ["scripted", "awm"]
    assert workflow.id == "workflow.vertical_slice"
    assert workflow.metadata["stage"] == "contracts"
    assert [node.id for node in workflow.nodes] == [
        "load_awm_fixture",
        "check_environment",
        "scripted_rollout",
        "deterministic_verify",
        "record_reward",
    ]
    assert not any(node.node_type.startswith("training.") for node in workflow.nodes)
