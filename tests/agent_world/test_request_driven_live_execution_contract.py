import textwrap

from agent_world.agents import InvocationBackendRegistry, InvocationResult, load_invocation_backend_config_from_env, load_implementation_invocation_backend_config_from_env
from agent_world.artifacts import make_artifact
from agent_world.pipeline import (
    PipelineContext,
    PipelineNode,
    PipelineRunConfig,
    PipelineRunner,
    _record_repair_failure_packet,
    _run_agent_implementation_attempt,
    request_driven_node_registry,
    run_request_driven_pipeline,
)
from agent_world.store import ArtifactStore


RAW_REQUEST = "Generate an incident runbook environment that tracks alerts and owners."


def _config_env(tmp_path, *, semantic: str = "backend_kind: llm", implementation: str = "") -> dict[str, str]:
    text = "invocation_profiles:\n  semantic:\n"
    text += textwrap.indent(textwrap.dedent(semantic).strip() + "\n", "    ")
    text += "  implementation:\n"
    implementation_text = "inherits: semantic\n" + textwrap.dedent(implementation).strip()
    text += textwrap.indent(implementation_text.strip() + "\n", "    ")
    config_path = tmp_path / "agent-world.yaml"
    config_path.write_text(text, encoding="utf-8")
    return {"AGENT_WORLD_CONFIG": str(config_path)}


def test_request_driven_pipeline_rejects_mock_semantic_backend(tmp_path):
    record, context = run_request_driven_pipeline(
        PipelineRunConfig(
            run_id="reject-mock-semantic-backend",
            raw_request=RAW_REQUEST,
            output_dir=tmp_path,
            env=_config_env(tmp_path, semantic="backend_kind: mock"),
        )
    )

    assert record.status == "needs_human"
    assert record.node_results[-1].stage == "PLAN"
    assert record.failure_class == "mock_backend_not_allowed"
    assert "DomainPlan" not in context.artifacts


def test_invalid_invocation_json_fails_with_invocation_record(tmp_path):
    backend = TextBackend("not json")
    record, context = run_request_driven_pipeline(
        PipelineRunConfig(
            run_id="invalid-json",
            raw_request=RAW_REQUEST,
            output_dir=tmp_path,
            env=_config_env(tmp_path),
        ),
        invocation_registry=_registry(backend),
    )

    assert record.status == "fail"
    assert record.node_results[-1].stage == "PLAN"
    assert record.failure_class == "invalid_invocation_json"
    assert len(context.invocation_records) == 3
    assert context.invocation_records[0]["stage"] == "PLAN"
    assert context.invocation_records[0]["backend_kind"] == "llm"
    assert context.invocation_records[-1]["id"].endswith("attempt-3")


def test_invalid_attempt_fields_fail_with_invocation_record(tmp_path):
    backend = TextBackend("{}")
    record, context = run_request_driven_pipeline(
        PipelineRunConfig(
            run_id="invalid-fields",
            raw_request=RAW_REQUEST,
            output_dir=tmp_path,
            env=_config_env(tmp_path),
        ),
        invocation_registry=_registry(backend),
    )

    assert record.status == "fail"
    assert record.node_results[-1].stage == "PLAN"
    assert record.failure_class == "invalid_attempt_artifact_fields"
    assert len(context.invocation_records) == 3
    assert context.invocation_records[0]["output_artifact_ids"] == []
    assert context.invocation_records[-1]["id"].endswith("attempt-3")
    assert "DomainPlan" not in context.artifacts


def test_s1_agent_attempt_executor_invokes_invocation_backend(tmp_path, monkeypatch):
    backend = TextBackend("not json")
    context = _context_at_s1(tmp_path, backend)

    import agent_world.executors.agent_attempt as agent_attempt

    monkeypatch.setattr(
        agent_attempt,
        "collect_research_candidates",
        lambda context, config: {
            "planned_environment_id": "env-research",
            "queries": ["incident workflow"],
            "candidates": [
                {
                    "source_id": "source-raw-request",
                    "kind": "manual_note",
                    "uri_or_path": "/tmp/raw-request.md",
                    "version_or_hash": "abc123",
                    "license": "user_supplied",
                    "auth_requirement": "none",
                    "network_requirement": "none",
                    "security_note": "test candidate",
                    "object_kind": "request_source",
                    "name": "raw-request.md",
                    "evidence_refs": ["source-raw-request#sha256:abc123"],
                    "snippet": "incident workflow",
                }
            ],
            "provider_errors": [],
            "rejected_sources": [],
        },
    )

    node = request_driven_node_registry().get("S1")
    result = PipelineRunner(request_driven_node_registry(), invocation_registry=_registry(backend))._run_artifact_node(node, context)

    assert result.status == "fail"
    assert result.failure_class == "invalid_invocation_json"
    assert backend.requests
    assert backend.requests[0].stage == "S1"
    assert "Research candidate packet JSON" in backend.requests[0].instruction


def test_implementation_repair_continue_mode_passes_conversation_ref(tmp_path):
    backend = FailingCodexBackend()
    context = _implementation_context(tmp_path, backend)
    node = PipelineNode(
        node_id="request-driven-implementation-node",
        stage="IMPLEMENT",
        artifact_type="CodeImplementation",
        input_artifact_types=["ImplementationRequest"],
        output_artifact_type="CodeImplementation",
        execution_mode="agent",
    )

    first = _run_agent_implementation_attempt(
        context,
        node,
        environment_id="env-repair-thread",
        attempt_index=1,
        total_attempts=2,
        max_repair_attempts=1,
        previous_attempt=None,
        failure_packet=None,
    )
    failure_packet = _record_repair_failure_packet(
        context,
        attempt_record=context.implementation_check_records[-1],
        attempt_result=first,
        attempt_index=1,
        max_repair_attempts=1,
    )
    _run_agent_implementation_attempt(
        context,
        node,
        environment_id="env-repair-thread",
        attempt_index=2,
        total_attempts=2,
        max_repair_attempts=1,
        previous_attempt=context.implementation_check_records[-1],
        failure_packet=failure_packet,
    )

    assert backend.requests[0].continuation_mode == "continue"
    assert backend.requests[0].conversation_ref == ""
    assert context.invocation_records[0]["conversation_ref"] == "codex-thread-1"
    assert backend.requests[1].parent_invocation_id == context.invocation_records[0]["id"]
    assert backend.requests[1].conversation_ref == "codex-thread-1"
    assert backend.requests[1].continuation_mode == "continue"


class TextBackend:
    backend_kind = "llm"

    def __init__(self, text: str) -> None:
        self.text = text
        self.requests = []

    def invoke(self, request, config):
        self.requests.append(request)
        return InvocationResult(
            text=self.text,
            evidence_refs=[f"test-backend://{request.stage.lower()}"],
            trace_ref=f"test-backend://trace/{request.stage.lower()}",
        )


def _context_at_s1(tmp_path, backend):
    record, context = run_request_driven_pipeline(
        PipelineRunConfig(
            run_id="s1-agent-call-setup",
            raw_request=RAW_REQUEST,
            output_dir=tmp_path,
            env=_config_env(tmp_path),
            stop_after="SELECT",
        ),
        invocation_registry=_registry(SetupBackend()),
    )
    assert record.status == "pass"
    context.invocation_registry = _registry(backend)
    return context


class SetupBackend(TextBackend):
    def __init__(self) -> None:
        super().__init__("")

    def invoke(self, request, config):
        self.requests.append(request)
        if request.stage == "PLAN":
            return InvocationResult(
                text=(
                    '{"domain_plan_id":"domain-plan-env-research","raw_request":"Generate an incident runbook environment",'
                    '"domain_seed":"env-research","domain_intent":"incident runbook","recognized_intents":["incident","runbook"],'
                    '"required_state_objects":["incident_record"],"required_operations":["record_incident"],'
                    '"likely_source_needs":["raw request"],'
                    '"constraints":{"network":"not_required","auth":"not_required","license":"user_supplied","safety":"isolated","local_execution":true,"mocking_allowed":false},'
                    '"license_auth_network_security":{"license":"user_supplied","auth_requirement":"none","network_requirement":"none","security_note":"none"},'
                    '"planner_evidence":{"raw_request_ref":"PipelineRunConfig.raw_request"},'
                    '"planning_status":"planned","blocked_reasons":[]}'
                ),
                evidence_refs=["test-backend://plan"],
                trace_ref="test-backend://trace/plan",
            )
        raise AssertionError(f"unexpected setup stage: {request.stage}")


def _registry(backend):
    registry = InvocationBackendRegistry()
    registry.register(backend)
    return registry


class FailingCodexBackend:
    backend_kind = "codex_sdk"

    def __init__(self) -> None:
        self.requests = []

    def invoke(self, request, config):
        self.requests.append(request)
        return InvocationResult(
            text="implementation failed",
            status="fail",
            failure_class="generated_project_check_failed",
            recovery_suggestion="repair generated project",
            conversation_ref="codex-thread-1",
        )


def _implementation_context(tmp_path, backend):
    env = _config_env(
        tmp_path,
        semantic="backend_kind: llm",
        implementation="""
        backend_kind: codex_sdk
        model: gpt-test
        code_repair_thread_mode: continue
        """,
    )
    config = PipelineRunConfig(
        run_id="implementation-repair-continuation",
        raw_request=RAW_REQUEST,
        output_dir=tmp_path,
        env=env,
    )
    context = PipelineContext(config=config, store=ArtifactStore(tmp_path), invocation_registry=_registry(backend))
    context.artifacts["InvocationBackendConfig"] = load_invocation_backend_config_from_env(env)
    context.artifacts["ImplementationInvocationBackendConfig"] = load_implementation_invocation_backend_config_from_env(env)
    context.artifacts["ImplementationRequest"] = make_artifact(
        "ImplementationRequest",
        source_stage="S9",
        producer="test",
        fields={
            "request_id": "impl-env-repair-thread",
            "environment_id": "env-repair-thread",
            "source_artifact_ids": [],
            "accepted_task_ids": [],
            "accepted_verifier_ids": [],
            "required_surface_ids": [],
            "package_layout_ref": "envpkg/",
            "implementation_scope": ["agent-written contract project"],
            "non_goals": [],
            "tdd_requirements": [],
            "launch_check_commands": [],
            "review_record_refs": [],
        },
    )
    return context
