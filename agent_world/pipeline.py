from __future__ import annotations

from dataclasses import dataclass, field, replace
import json
import os
from pathlib import Path
import shutil
from tempfile import mkdtemp
from typing import Any, Callable

from agent_world.agents import (
    AgentRequest,
    AgentBackendRegistry,
    default_agent_backend_registry,
    invoke_agent,
    load_agent_backend_config_from_env,
)
from agent_world.artifacts import GENERATED_BUNDLE_FILE_KINDS, artifact_hash, make_artifact, stable_json, utc_now, validate_artifact
from agent_world.gates import STAGE_GATES, evaluate_stage_gates
from agent_world.generated_bundle import assemble_generated_bundle_package
import agent_world.request_driven as request_driven
from agent_world.replay_contract import build_framework_replay_contract
from agent_world.review import independent_review
from agent_world.store import ArtifactStore


SOURCE_DOC_REF = "docs/agent-world-environment-generation.zh.md"


@dataclass(frozen=True)
class PipelineRunConfig:
    run_id: str = "pipeline-run-request-driven"
    raw_request: str = "Generate a local request-driven executable environment."
    output_dir: Path | None = None
    source_paths: list[Path] = field(default_factory=list)
    env: dict[str, str] | None = None
    implementation_mode: str = "deterministic"
    stop_after: str = ""
    max_repair_attempts: int = 0


@dataclass
class PipelineNodeResult:
    node_id: str
    stage: str
    status: str
    artifact_type: str = ""
    artifact_id: str = ""
    output_refs: list[str] = field(default_factory=list)
    gate_record_ids: list[str] = field(default_factory=list)
    review_record_ids: list[str] = field(default_factory=list)
    agent_invocation_ids: list[str] = field(default_factory=list)
    failure_class: str = ""
    recovery_suggestion: str = ""


@dataclass
class PipelineRunRecord:
    run_id: str
    status: str
    started_at: str
    completed_at: str
    node_results: list[PipelineNodeResult]
    artifact_ids: dict[str, str]
    gate_record_ids: list[str]
    review_record_ids: list[str]
    agent_invocation_ids: list[str]
    build_check_replay_records: list[dict[str, Any]]
    repair_failure_packets: list[dict[str, Any]] = field(default_factory=list)
    failure_class: str = ""
    recovery_suggestion: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "status": self.status,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "node_results": [result.__dict__ for result in self.node_results],
            "artifact_ids": self.artifact_ids,
            "gate_record_ids": self.gate_record_ids,
            "review_record_ids": self.review_record_ids,
            "agent_invocation_ids": self.agent_invocation_ids,
            "build_check_replay_records": self.build_check_replay_records,
            "repair_failure_packets": self.repair_failure_packets,
            "failure_class": self.failure_class,
            "recovery_suggestion": self.recovery_suggestion,
        }


@dataclass
class PipelineContext:
    config: PipelineRunConfig
    store: ArtifactStore
    agent_registry: AgentBackendRegistry
    artifacts: dict[str, dict[str, Any]] = field(default_factory=dict)
    gate_records: list[dict[str, Any]] = field(default_factory=list)
    review_records: list[dict[str, Any]] = field(default_factory=list)
    agent_invocations: list[dict[str, Any]] = field(default_factory=list)
    build_check_replay_records: list[dict[str, Any]] = field(default_factory=list)
    repair_failure_packets: list[dict[str, Any]] = field(default_factory=list)

    def artifact(self, artifact_type: str) -> dict[str, Any]:
        return self.artifacts[artifact_type]

    def upstream_artifacts(self) -> list[dict[str, Any]]:
        return [artifact for name, artifact in self.artifacts.items() if name != "AgentBackendConfig"]


@dataclass(frozen=True)
class PipelineNode:
    node_id: str
    stage: str
    artifact_type: str
    input_artifact_types: list[str]
    output_artifact_type: str
    allowed_agent_backend: bool
    factory: Callable[[PipelineContext], dict[str, Any]]
    failure_policy: str = "stop"


class NodeRegistry:
    def __init__(self) -> None:
        self._nodes: dict[str, PipelineNode] = {}
        self._order: list[str] = []

    def register(self, node: PipelineNode) -> None:
        if node.stage not in self._nodes:
            self._order.append(node.stage)
        self._nodes[node.stage] = node

    def get(self, stage: str) -> PipelineNode:
        return self._nodes[stage]

    def ordered_nodes(self) -> list[PipelineNode]:
        return [self._nodes[stage] for stage in self._order]

    def stages(self) -> list[str]:
        return list(self._order)


class PipelineRunner:
    """Runs replaceable environment-generation nodes through gates and reviews."""

    def __init__(
        self,
        node_registry: NodeRegistry | None = None,
        *,
        agent_registry: AgentBackendRegistry | None = None,
    ) -> None:
        self.node_registry = node_registry or request_driven_node_registry()
        self.agent_registry = agent_registry or default_agent_backend_registry()

    def run(self, config: PipelineRunConfig) -> tuple[PipelineRunRecord, PipelineContext]:
        started_at = utc_now()
        store = ArtifactStore(config.output_dir / "pipeline-store" if config.output_dir else None)
        context = PipelineContext(config=config, store=store, agent_registry=self.agent_registry)
        backend_config = load_agent_backend_config_from_env(config.env)
        context.artifacts["AgentBackendConfig"] = backend_config
        store.put_artifact("AgentBackendConfig", backend_config)
        node_results: list[PipelineNodeResult] = []
        status = "pass"
        failure_class = ""
        recovery_suggestion = ""
        for node in self.node_registry.ordered_nodes():
            if node.stage == "IMPLEMENT":
                result = self._run_implementation_node(node, context)
            else:
                result = self._run_artifact_node(node, context)
            node_results.append(result)
            if result.status != "pass":
                status = result.status
                failure_class = result.failure_class
                recovery_suggestion = result.recovery_suggestion
                break
            if config.stop_after and node.stage == config.stop_after:
                break
        if status == "pass" and not config.stop_after:
            package_error = _assemble_generated_bundle_package_if_available(context)
            if package_error:
                status = "fail"
                failure_class = package_error["failure_class"]
                recovery_suggestion = package_error["recovery_suggestion"]
        record = PipelineRunRecord(
            run_id=config.run_id,
            status=status,
            started_at=started_at,
            completed_at=utc_now(),
            node_results=node_results,
            artifact_ids={name: artifact["id"] for name, artifact in context.artifacts.items()},
            gate_record_ids=[record["id"] for record in context.gate_records],
            review_record_ids=[record["id"] for record in context.review_records],
            agent_invocation_ids=[record["id"] for record in context.agent_invocations],
            build_check_replay_records=context.build_check_replay_records,
            repair_failure_packets=context.repair_failure_packets,
            failure_class=failure_class,
            recovery_suggestion=recovery_suggestion,
        )
        store.write_run_record(record.to_dict())
        return record, context

    def _run_artifact_node(self, node: PipelineNode, context: PipelineContext) -> PipelineNodeResult:
        try:
            fields = node.factory(context)
            artifact = make_artifact(
                node.output_artifact_type,
                source_stage=node.stage,
                producer=node.node_id,
                fields=fields,
                artifact_id=_artifact_id_from_fields(fields),
                inputs=[context.artifacts[name]["id"] for name in node.input_artifact_types if name in context.artifacts],
            )
            review = independent_review(
                stage=node.stage,
                artifact=artifact,
                need_spec=context.artifacts.get("NeedSpec") or (artifact if node.output_artifact_type == "NeedSpec" else None),
                upstream_artifacts=context.upstream_artifacts(),
                gate_checklist=list(STAGE_GATES[node.stage]),
                source_of_truth_refs=[
                    SOURCE_DOC_REF,
                    ".trellis/tasks/06-30-06-30-archive-hardcoded-legacy-domains/prd.md",
                ],
                reviewer_ref="pipeline-static-reviewer",
            )
            gate_records = evaluate_stage_gates(
                stage=node.stage,
                artifact_type=node.output_artifact_type,
                artifact=artifact,
                context=context.artifacts | {node.output_artifact_type: artifact, "__gate_records__": {record["id"]: record for record in context.gate_records}},
                review=review,
                invocations=[],
            )
            context.artifacts[node.output_artifact_type] = artifact
            context.review_records.append(review)
            context.gate_records.extend(gate_records)
            context.store.put_artifact(node.output_artifact_type, artifact)
            context.store.put_review_record(review)
            context.store.put_gate_records(gate_records)
            failures = [record for record in gate_records if record["status"] != "pass"]
            if failures:
                failure_packet = _record_stage_failure_packet(
                    context,
                    node=node,
                    artifact=artifact,
                    failure_class=failures[0]["failure_class"],
                    recovery_suggestion=failures[0]["recovery_suggestion"],
                    gate_record_ids=[record["id"] for record in gate_records],
                )
                return PipelineNodeResult(
                    node_id=node.node_id,
                    stage=node.stage,
                    status="fail",
                    artifact_type=node.output_artifact_type,
                    artifact_id=artifact["id"],
                    output_refs=[failure_packet["trace_ref"]],
                    gate_record_ids=[record["id"] for record in gate_records],
                    review_record_ids=[review["id"]],
                    failure_class=failures[0]["failure_class"],
                    recovery_suggestion=failures[0]["recovery_suggestion"],
                )
            return PipelineNodeResult(
                node_id=node.node_id,
                stage=node.stage,
                status="pass",
                artifact_type=node.output_artifact_type,
                artifact_id=artifact["id"],
                gate_record_ids=[record["id"] for record in gate_records],
                review_record_ids=[review["id"]],
            )
        except Exception as exc:
            failure_packet = _record_stage_failure_packet(
                context,
                node=node,
                artifact=None,
                failure_class=exc.__class__.__name__,
                recovery_suggestion=str(exc),
                gate_record_ids=[],
            )
            return PipelineNodeResult(
                node_id=node.node_id,
                stage=node.stage,
                status="fail",
                artifact_type=node.output_artifact_type,
                output_refs=[failure_packet["trace_ref"]],
                failure_class=exc.__class__.__name__,
                recovery_suggestion=str(exc),
            )

    def _run_implementation_node(self, node: PipelineNode, context: PipelineContext) -> PipelineNodeResult:
        if context.artifact("FeasibilityReport")["status"] != "pass":
            return PipelineNodeResult(
                node_id=node.node_id,
                stage=node.stage,
                status="fail",
                failure_class="feasibility_not_passed",
                recovery_suggestion="Implementation node requires a passing FeasibilityReport.",
            )
        if context.config.implementation_mode == "agent":
            return _run_agent_implementation(context, node)
        record = node.factory(context)
        if record:
            return _record_deterministic_implementation(context, node, record)
        return PipelineNodeResult(
            node_id=node.node_id,
            stage=node.stage,
            status="fail",
            failure_class="deterministic_implementation_unavailable",
            recovery_suggestion="Generated environments require an agent backend that writes candidate bundle files.",
        )


def request_driven_node_registry() -> NodeRegistry:
    registry = NodeRegistry()
    registry.register(
        PipelineNode(
            node_id="request-domain-planner",
            stage="PLAN",
            artifact_type="DomainPlan",
            input_artifact_types=[],
            output_artifact_type="DomainPlan",
            allowed_agent_backend=True,
            factory=lambda context: request_driven.domain_plan_fields(context.config.raw_request),
        )
    )
    registry.register(
        PipelineNode(
            node_id="request-strategy-selector",
            stage="SELECT",
            artifact_type="StrategySelection",
            input_artifact_types=["DomainPlan"],
            output_artifact_type="StrategySelection",
            allowed_agent_backend=False,
            factory=lambda context: request_driven.strategy_selection_fields(context.artifact("DomainPlan")),
        )
    )
    registry.register(
        PipelineNode(
            node_id="request-driven-input-normalization",
            stage="S0",
            artifact_type="NeedSpec",
            input_artifact_types=["DomainPlan"],
            output_artifact_type="NeedSpec",
            allowed_agent_backend=False,
            factory=lambda context: request_driven.need_spec_fields(context.artifact("DomainPlan")),
        )
    )
    registry.register(
        PipelineNode(
            node_id="request-driven-source-planning-discovery",
            stage="S1",
            artifact_type="SourceEvidenceIndex",
            input_artifact_types=["NeedSpec", "DomainPlan", "StrategySelection"],
            output_artifact_type="SourceEvidenceIndex",
            allowed_agent_backend=True,
            factory=request_driven.source_evidence_fields,
        )
    )
    registry.register(
        PipelineNode(
            node_id="request-driven-source-grounded-extractor",
            stage="S2",
            artifact_type="KnowledgePack",
            input_artifact_types=["SourceEvidenceIndex", "StrategySelection"],
            output_artifact_type="KnowledgePack",
            allowed_agent_backend=True,
            factory=lambda context: request_driven.knowledge_pack_fields(context.artifact("SourceEvidenceIndex"), base_dir=Path.cwd()),
        )
    )
    registry.register(
        PipelineNode(
            node_id="request-driven-spec-synthesis",
            stage="S3",
            artifact_type="EnvironmentSpec",
            input_artifact_types=["NeedSpec", "KnowledgePack", "DomainPlan", "StrategySelection"],
            output_artifact_type="EnvironmentSpec",
            allowed_agent_backend=True,
            factory=lambda context: request_driven.environment_spec_fields(context.artifact("KnowledgePack")),
        )
    )
    registry.register(
        PipelineNode(
            node_id="request-driven-tool-graph-synthesis",
            stage="S4",
            artifact_type="LogicalToolGraph",
            input_artifact_types=["EnvironmentSpec", "KnowledgePack", "StrategySelection"],
            output_artifact_type="LogicalToolGraph",
            allowed_agent_backend=True,
            factory=lambda context: request_driven.logical_tool_graph_fields(context.artifact("KnowledgePack")),
        )
    )
    registry.register(
        PipelineNode(
            node_id="request-driven-task-generation",
            stage="S5",
            artifact_type="TaskSet",
            input_artifact_types=["NeedSpec", "LogicalToolGraph", "EnvironmentSpec", "KnowledgePack"],
            output_artifact_type="TaskSet",
            allowed_agent_backend=True,
            factory=lambda context: request_driven.task_set_fields(context.artifact("LogicalToolGraph"), context.artifact("KnowledgePack")),
        )
    )
    registry.register(
        PipelineNode(
            node_id="request-driven-surface-planning",
            stage="S6",
            artifact_type="SurfacePlan",
            input_artifact_types=["LogicalToolGraph", "EnvironmentSpec", "StrategySelection"],
            output_artifact_type="SurfacePlan",
            allowed_agent_backend=True,
            factory=lambda context: request_driven.surface_plan_fields(context.artifact("EnvironmentSpec")),
        )
    )
    registry.register(
        PipelineNode(
            node_id="request-driven-verifier-planning",
            stage="S7",
            artifact_type="VerifierPlan",
            input_artifact_types=["TaskSet", "EnvironmentSpec", "SurfacePlan", "KnowledgePack"],
            output_artifact_type="VerifierPlan",
            allowed_agent_backend=True,
            factory=lambda context: request_driven.verifier_plan_fields(context.artifact("TaskSet"), context.artifact("KnowledgePack")),
        )
    )
    registry.register(
        PipelineNode(
            node_id="request-driven-deterministic-feasibility",
            stage="S8",
            artifact_type="FeasibilityReport",
            input_artifact_types=["NeedSpec", "DomainPlan", "StrategySelection", "SourceEvidenceIndex", "KnowledgePack", "EnvironmentSpec", "LogicalToolGraph", "TaskSet", "SurfacePlan", "VerifierPlan"],
            output_artifact_type="FeasibilityReport",
            allowed_agent_backend=False,
            factory=request_driven.feasibility_report_fields,
        )
    )
    registry.register(
        PipelineNode(
            node_id="request-driven-implementation-request",
            stage="S9",
            artifact_type="ImplementationRequest",
            input_artifact_types=["FeasibilityReport", "EnvironmentSpec", "TaskSet", "VerifierPlan", "StrategySelection"],
            output_artifact_type="ImplementationRequest",
            allowed_agent_backend=True,
            factory=lambda context: request_driven.implementation_request_fields(context.artifacts, context.review_records),
        )
    )
    registry.register(
        PipelineNode(
            node_id="request-driven-implementation-node",
            stage="IMPLEMENT",
            artifact_type="CodeImplementation",
            input_artifact_types=["ImplementationRequest"],
            output_artifact_type="CodeImplementation",
            allowed_agent_backend=True,
            factory=request_driven.generated_implementation_record,
        )
    )
    registry.register(
        PipelineNode(
            node_id="request-driven-package-plan",
            stage="S10",
            artifact_type="EnvironmentPackagePlan",
            input_artifact_types=["ImplementationRequest", "GeneratedEnvironmentBundle", "IndependentVerificationReport"],
            output_artifact_type="EnvironmentPackagePlan",
            allowed_agent_backend=False,
            factory=request_driven.package_plan_fields,
        )
    )
    registry.register(
        PipelineNode(
            node_id="request-driven-release-plan",
            stage="S11",
            artifact_type="ReleaseManifest",
            input_artifact_types=["EnvironmentPackagePlan", "IndependentVerificationReport"],
            output_artifact_type="ReleaseManifest",
            allowed_agent_backend=False,
            factory=request_driven.release_manifest_fields,
        )
    )
    return registry


def run_request_driven_pipeline(
    config: PipelineRunConfig,
    *,
    agent_registry: AgentBackendRegistry | None = None,
) -> tuple[PipelineRunRecord, PipelineContext]:
    if config.implementation_mode != "agent":
        config = replace(config, implementation_mode="agent")
    return PipelineRunner(request_driven_node_registry(), agent_registry=agent_registry).run(config)


def _assemble_generated_bundle_package_if_available(context: PipelineContext) -> dict[str, str] | None:
    if context.config.output_dir is None:
        return None
    if "GeneratedEnvironmentBundle" not in context.artifacts or "ReleaseManifest" not in context.artifacts:
        return None
    try:
        assemble_generated_bundle_package(
            package_dir=context.config.output_dir / "envpkg",
            artifacts=context.artifacts,
            gate_records=context.gate_records,
            review_records=context.review_records,
            agent_invocations=context.agent_invocations,
            build_check_replay_records=context.build_check_replay_records,
        )
    except Exception as exc:
        return {
            "failure_class": exc.__class__.__name__,
            "recovery_suggestion": str(exc),
        }
    return None


def _record_deterministic_implementation(context: PipelineContext, node: PipelineNode, record: dict[str, Any]) -> PipelineNodeResult:
    bundle = record.get("generated_environment_bundle")
    if isinstance(bundle, dict):
        context.artifacts["GeneratedEnvironmentBundle"] = bundle
        context.store.put_artifact("GeneratedEnvironmentBundle", bundle)
    independent_report = record.get("independent_verification_report")
    if isinstance(independent_report, dict):
        context.artifacts["IndependentVerificationReport"] = independent_report
        context.store.put_artifact("IndependentVerificationReport", independent_report)
    trace_ref = context.store.put_trace(f"implementation-{record['environment_id']}-deterministic", record)
    context.build_check_replay_records.append(record)
    if record["status"] != "pass":
        return PipelineNodeResult(
            node_id=node.node_id,
            stage=node.stage,
            status=record["status"],
            output_refs=[trace_ref],
            failure_class=record["failure_class"],
            recovery_suggestion=record["recovery_suggestion"],
        )
    return PipelineNodeResult(node_id=node.node_id, stage=node.stage, status="pass", output_refs=[trace_ref])


def _run_agent_implementation(context: PipelineContext, node: PipelineNode) -> PipelineNodeResult:
    request_artifact = context.artifact("ImplementationRequest")
    environment_id = request_artifact["environment_id"]
    max_repair_attempts = _configured_max_repair_attempts(context.config)
    total_attempts = max_repair_attempts + 1
    all_invocation_ids: list[str] = []
    all_output_refs: list[str] = []
    previous_attempt: dict[str, Any] | None = None
    failure_packet: dict[str, Any] | None = None
    last_result: PipelineNodeResult | None = None
    for attempt_index in range(1, total_attempts + 1):
        result = _run_agent_implementation_attempt(
            context,
            node,
            environment_id=environment_id,
            attempt_index=attempt_index,
            total_attempts=total_attempts,
            max_repair_attempts=max_repair_attempts,
            previous_attempt=previous_attempt,
            failure_packet=failure_packet,
        )
        last_result = result
        all_invocation_ids.extend(result.agent_invocation_ids)
        all_output_refs.extend(ref for ref in result.output_refs if ref)
        attempt_record = context.build_check_replay_records[-1] if context.build_check_replay_records else {}
        if result.status == "pass":
            return _roll_up_attempt_result(result, invocation_ids=all_invocation_ids, output_refs=all_output_refs)
        if result.status != "fail":
            return _roll_up_attempt_result(result, invocation_ids=all_invocation_ids, output_refs=all_output_refs)
        failure_packet = _record_repair_failure_packet(
            context,
            attempt_record=attempt_record,
            attempt_result=result,
            attempt_index=attempt_index,
            max_repair_attempts=max_repair_attempts,
        )
        all_output_refs.append(failure_packet["trace_ref"])
        previous_attempt = attempt_record
        if attempt_index > max_repair_attempts:
            return _roll_up_attempt_result(result, invocation_ids=all_invocation_ids, output_refs=all_output_refs)
    return _roll_up_attempt_result(last_result or PipelineNodeResult(node_id=node.node_id, stage=node.stage, status="fail"), invocation_ids=all_invocation_ids, output_refs=all_output_refs)


def _run_agent_implementation_attempt(
    context: PipelineContext,
    node: PipelineNode,
    *,
    environment_id: str,
    attempt_index: int,
    total_attempts: int,
    max_repair_attempts: int,
    previous_attempt: dict[str, Any] | None,
    failure_packet: dict[str, Any] | None,
) -> PipelineNodeResult:
    request_artifact = context.artifact("ImplementationRequest")
    work_dir = _agent_attempt_work_dir(context, environment_id, attempt_index=attempt_index, total_attempts=total_attempts)
    _prepare_agent_work_dir(work_dir)
    backend_config = context.artifact("AgentBackendConfig")
    backend_kind = backend_config["backend_kind"]
    is_runner_backend = backend_kind in {"code_agent_runner", "codex_cli_runner"}
    if is_runner_backend:
        _write_code_agent_workspace_packet(context, work_dir, failure_packet=failure_packet, previous_attempt=previous_attempt)
    input_artifact_ids = _implementation_agent_input_ids(context)
    if failure_packet:
        input_artifact_ids.append(failure_packet["packet_id"])
    permissions = {
        "network": backend_kind in {"llm", "openai_codegen", "code_agent_runner", "codex_cli_runner"} and bool(backend_config.get("permissions", {}).get("network")),
        "filesystem": "isolated_agent_workspace" if is_runner_backend else "isolated_workdir",
        "filesystem_root": str(work_dir),
        "auth": backend_kind in {"llm", "openai_codegen", "code_agent_runner", "codex_cli_runner"} and bool(backend_config.get("permissions", {}).get("auth")),
        "sandbox": backend_kind in {"codex_cli", "codex_cli_runner"} and bool(backend_config.get("permissions", {}).get("sandbox")),
    }
    instruction = _implementation_agent_instruction(
        context,
        work_dir=work_dir,
        runner_backend=is_runner_backend,
        attempt_index=attempt_index,
        total_attempts=total_attempts,
        failure_packet=failure_packet,
    )
    request = AgentRequest(
        stage="IMPLEMENT",
        node_purpose="implement",
        instruction=instruction,
        input_artifact_ids=input_artifact_ids,
        invocation_id=f"invoke-implement-codegen-{environment_id}-attempt-{attempt_index}",
        allowed_tool_access=_implementation_agent_allowed_tools(is_runner_backend),
        permissions=permissions,
        budget={"tokens": 0, "time_ms": int(backend_config.get("timeouts", {}).get("run_ms") or 5000), "cost_limit": 0},
        instruction_ref=f"{SOURCE_DOC_REF}#agent-backed-implementation",
    )
    invocation, result = invoke_agent(context.agent_registry, request, backend_config)
    if "DomainPlan" not in context.artifacts or "StrategySelection" not in context.artifacts:
        context.agent_invocations.append(invocation)
        context.store.put_agent_invocations([invocation])
        record = {
            "implementation_id": f"implementation-{environment_id}-agent",
            "mode": "agent_backed",
            "environment_id": environment_id,
            "implementation_request_id": request_artifact["id"],
            "agent_invocation_id": invocation["id"],
            "static_check_command": "not run",
            "test_command": "not run",
            "replay_command": "not run",
            "verifier_result": {},
            "status": "needs_human" if result.status == "pass" else result.status,
            "failure_class": result.failure_class or "unchecked_agent_output",
            "recovery_suggestion": result.recovery_suggestion or "Run build/check/replay gate in an isolated workdir before package/release planning.",
        }
        record = _with_attempt_metadata(
            record,
            attempt_index=attempt_index,
            total_attempts=total_attempts,
            max_repair_attempts=max_repair_attempts,
            input_failure_packet=failure_packet,
        )
        record = _redact_attempt_record(context, record)
        trace_ref = context.store.put_trace("implementation-agent", record)
        context.build_check_replay_records.append(record)
        return PipelineNodeResult(
            node_id=node.node_id,
            stage=node.stage,
            status=record["status"],
            output_refs=[trace_ref],
            agent_invocation_ids=[invocation["id"]],
            failure_class=record["failure_class"],
            recovery_suggestion=record["recovery_suggestion"],
        )
    record = request_driven.agent_generated_implementation_record(
        context,
        agent_invocation=invocation,
        agent_result=result,
        work_dir=work_dir,
    )
    record = _with_attempt_metadata(
        record,
        attempt_index=attempt_index,
        total_attempts=total_attempts,
        max_repair_attempts=max_repair_attempts,
        input_failure_packet=failure_packet,
    )
    record = _redact_attempt_record(context, record)
    bundle = record.get("generated_environment_bundle")
    independent_report = record.get("independent_verification_report")
    if isinstance(bundle, dict):
        context.artifacts["GeneratedEnvironmentBundle"] = bundle
        context.store.put_artifact("GeneratedEnvironmentBundle", bundle)
        invocation = _with_invocation_outputs(invocation, output_artifact_ids=[bundle["id"]], evidence_refs=[bundle["id"]])
    if isinstance(independent_report, dict):
        context.artifacts["IndependentVerificationReport"] = independent_report
        context.store.put_artifact("IndependentVerificationReport", independent_report)
        invocation = _with_invocation_outputs(invocation, output_artifact_ids=[independent_report["id"]], evidence_refs=[independent_report["id"]])
    context.agent_invocations.append(invocation)
    context.store.put_agent_invocations([invocation])
    trace_ref = context.store.put_trace(f"implementation-{environment_id}-agent", record)
    context.build_check_replay_records.append(record)
    if record["status"] != "pass":
        return PipelineNodeResult(
            node_id=node.node_id,
            stage=node.stage,
            status=record["status"],
            output_refs=[trace_ref],
            agent_invocation_ids=[invocation["id"]],
            failure_class=record["failure_class"],
            recovery_suggestion=record["recovery_suggestion"],
        )
    return PipelineNodeResult(
        node_id=node.node_id,
        stage=node.stage,
        status="pass",
        output_refs=[trace_ref, bundle["id"] if isinstance(bundle, dict) else "", independent_report["id"] if isinstance(independent_report, dict) else ""],
        artifact_type="GeneratedEnvironmentBundle",
        artifact_id=bundle["id"] if isinstance(bundle, dict) else "",
        agent_invocation_ids=[invocation["id"]],
    )


def _configured_max_repair_attempts(config: PipelineRunConfig) -> int:
    env = os.environ if config.env is None else config.env
    raw = env.get("AGENT_WORLD_MAX_REPAIR_ATTEMPTS")
    if raw is None or raw == "":
        return max(0, int(config.max_repair_attempts))
    return max(0, int(raw))


def _roll_up_attempt_result(result: PipelineNodeResult, *, invocation_ids: list[str], output_refs: list[str]) -> PipelineNodeResult:
    result.agent_invocation_ids = list(dict.fromkeys(invocation_ids))
    result.output_refs = list(dict.fromkeys(output_refs))
    return result


def _with_attempt_metadata(
    record: dict[str, Any],
    *,
    attempt_index: int,
    total_attempts: int,
    max_repair_attempts: int,
    input_failure_packet: dict[str, Any] | None,
) -> dict[str, Any]:
    updated = dict(record)
    updated["attempt_index"] = attempt_index
    updated["total_attempts_allowed"] = total_attempts
    updated["max_repair_attempts"] = max_repair_attempts
    if input_failure_packet:
        updated["input_failure_packet_id"] = input_failure_packet["packet_id"]
        updated["input_failure_packet_ref"] = input_failure_packet.get("trace_ref", "")
    return updated


def _redact_attempt_record(context: PipelineContext, record: dict[str, Any]) -> dict[str, Any]:
    secrets = _secret_values_for_context(context)
    if not secrets:
        return record
    return _redact_value(record, secrets)


def _secret_values_for_context(context: PipelineContext) -> list[str]:
    config = context.artifacts.get("AgentBackendConfig", {})
    auth = config.get("auth", {}) if isinstance(config, dict) else {}
    names = set(auth.get("auth_env_refs", []))
    if auth.get("api_key_env"):
        names.add(str(auth["api_key_env"]))
    env = context.config.env or {}
    values = []
    for name in names:
        value = env.get(name) or os.environ.get(name)
        if value:
            values.append(value)
    return values


def _redact_value(value: Any, secrets: list[str]) -> Any:
    if isinstance(value, str):
        redacted = value
        for secret in secrets:
            if secret:
                redacted = redacted.replace(secret, "[REDACTED_SECRET]")
        return redacted
    if isinstance(value, list):
        return [_redact_value(item, secrets) for item in value]
    if isinstance(value, dict):
        return {key: _redact_value(item, secrets) for key, item in value.items()}
    return value


def _record_repair_failure_packet(
    context: PipelineContext,
    *,
    attempt_record: dict[str, Any],
    attempt_result: PipelineNodeResult,
    attempt_index: int,
    max_repair_attempts: int,
) -> dict[str, Any]:
    packet = _implementation_failure_packet(
        attempt_record=attempt_record,
        attempt_result=attempt_result,
        attempt_index=attempt_index,
        max_repair_attempts=max_repair_attempts,
    )
    trace_ref = context.store.put_trace(f"implementation-failure-packet-attempt-{attempt_index}", packet)
    packet = dict(packet)
    packet["trace_ref"] = trace_ref
    context.repair_failure_packets.append(packet)
    return packet


def _record_stage_failure_packet(
    context: PipelineContext,
    *,
    node: PipelineNode,
    artifact: dict[str, Any] | None,
    failure_class: str,
    recovery_suggestion: str,
    gate_record_ids: list[str],
) -> dict[str, Any]:
    packet_id = f"failure-packet-{node.stage.lower()}-{node.output_artifact_type.lower()}"
    packet = {
        "packet_id": packet_id,
        "stage": node.stage,
        "node_id": node.node_id,
        "artifact_type": node.output_artifact_type,
        "artifact_id": artifact.get("id", "") if isinstance(artifact, dict) else "",
        "input_artifact_ids": [context.artifacts[name]["id"] for name in node.input_artifact_types if name in context.artifacts],
        "failure_class": failure_class,
        "recovery_suggestion": recovery_suggestion,
        "gate_record_ids": gate_record_ids,
        "recovery_edge": _stage_recovery_edge(node.stage),
        "terminal": True,
    }
    trace_ref = context.store.put_trace(packet_id, packet)
    packet = dict(packet)
    packet["trace_ref"] = trace_ref
    context.repair_failure_packets.append(packet)
    return packet


def _stage_recovery_edge(stage: str) -> str:
    if stage == "S1":
        return "retry source planning/discovery within configured attempt budget, then terminal failed/blocked"
    if stage in {"S2", "S3", "S4", "S5", "S6", "S7"}:
        return "retry extraction/synthesis from source evidence or return to source planning, then terminal failed/blocked"
    if stage == "S8":
        return "stop before implementation and emit feasibility failure"
    return "stop before downstream release"


def _implementation_failure_packet(
    *,
    attempt_record: dict[str, Any],
    attempt_result: PipelineNodeResult,
    attempt_index: int,
    max_repair_attempts: int,
) -> dict[str, Any]:
    failed_check = _first_failed_check(attempt_record)
    failed_tasks = _failed_task_ids(attempt_record)
    framework_observation = _framework_check_observation(failed_check, attempt_record)
    return {
        "packet_id": f"failure-packet-implement-attempt-{attempt_index}",
        "stage": "IMPLEMENT",
        "attempt_index": attempt_index,
        "remaining_repair_attempts": max(0, max_repair_attempts - attempt_index),
        "previous_implementation_id": attempt_record.get("implementation_id", ""),
        "previous_agent_invocation_id": attempt_record.get("agent_invocation_id", ""),
        "failure_class": attempt_result.failure_class or attempt_record.get("failure_class", "implementation_failed"),
        "recovery_suggestion": attempt_result.recovery_suggestion or attempt_record.get("recovery_suggestion", "Repair the generated candidate and rerun checks."),
        "failed_task_ids": failed_tasks,
        "failed_verifier_ids": [f"verifier-{task_id}" for task_id in failed_tasks],
        "failed_check": {
            "check_id": failed_check.get("check_id", ""),
            "command": failed_check.get("command", attempt_record.get("test_command", "")),
            "exit_code": failed_check.get("exit_code"),
            "stdout_preview": _preview(failed_check.get("stdout", "")),
            "stderr_preview": _preview(failed_check.get("stderr", "")),
            "failure_class": failed_check.get("failure_class", ""),
            "recovery_suggestion": failed_check.get("recovery_suggestion", ""),
            "framework_check_observation": framework_observation,
            "failed_prerequisite_checks": _failed_prerequisite_checks(failed_check),
            "failed_task_errors": _failed_task_errors(failed_check),
        },
        "framework_check_observation": framework_observation,
        "candidate": {
            "generated_paths": _candidate_relative_paths(attempt_record),
            "generated_file_hashes": _candidate_relative_hashes(attempt_record),
            "agent_candidate_dir_ref": "generated",
            "agent_work_dir_ref": ".",
        },
        "manifest_contract": {
            "candidate_dir": "generated",
            "generated_file_kinds": dict(GENERATED_BUNDLE_FILE_KINDS),
            "path_rule": "Each generated_files[].path is relative to candidate_dir. Use runtime.py, not generated/runtime.py and not an absolute path.",
            "required_fields_per_generated_file": ["path", "kind", "sha256", "source_refs"],
        },
        "security_and_manifest_checks": {
            "failure_class": attempt_record.get("failure_class", ""),
            "static_check_command": attempt_record.get("static_check_command", ""),
        },
    }


def _framework_check_observation(failed_check: dict[str, Any], attempt_record: dict[str, Any]) -> dict[str, Any]:
    observation = failed_check.get("framework_check_observation")
    if isinstance(observation, dict) and observation:
        return observation
    for check in attempt_record.get("build_check_replay_records", []):
        observation = check.get("framework_check_observation")
        if isinstance(observation, dict) and observation:
            return observation
        independent = check.get("independent_verification_record")
        if isinstance(independent, dict):
            observation = independent.get("framework_check_observation")
            if isinstance(observation, dict) and observation:
                return observation
    return {}


def _failed_prerequisite_checks(check: dict[str, Any]) -> list[dict[str, Any]]:
    failures = []
    for item in check.get("prerequisite_checks", []):
        if item.get("passed") is False:
            failures.append(
                {
                    "name": item.get("name", ""),
                    "detail": item.get("detail", {}),
                }
            )
    return failures


def _failed_task_errors(check: dict[str, Any]) -> list[dict[str, Any]]:
    errors = []
    for item in check.get("task_records", []):
        if item.get("success") is False:
            observation = item.get("task_observation")
            errors.append(
                {
                    "task_id": item.get("task_id", ""),
                    "case_id": f"framework-replay-{item.get('task_id', '')}",
                    "phase": item.get("phase", ""),
                    "failure_class": item.get("failure_class", ""),
                    "stderr_preview": _preview(item.get("stderr", ""), limit=500),
                    "exception": item.get("exception", {}),
                    "task_observation": observation if isinstance(observation, dict) else {},
                    "recovery_suggestion": item.get("recovery_suggestion", ""),
                }
            )
    return errors


def _candidate_relative_paths(attempt_record: dict[str, Any]) -> list[str]:
    candidate_dir = str(attempt_record.get("agent_candidate_dir") or "")
    return [_path_relative_to_candidate(path, candidate_dir) for path in attempt_record.get("generated_paths", [])]


def _candidate_relative_hashes(attempt_record: dict[str, Any]) -> dict[str, str]:
    candidate_dir = str(attempt_record.get("agent_candidate_dir") or "")
    return {
        _path_relative_to_candidate(path, candidate_dir): value
        for path, value in dict(attempt_record.get("generated_file_hashes", {})).items()
    }


def _path_relative_to_candidate(path_value: Any, candidate_dir: str) -> str:
    text = str(path_value)
    if not candidate_dir:
        return text
    candidate_prefix = str(Path(candidate_dir).resolve())
    try:
        return Path(text).resolve().relative_to(candidate_prefix).as_posix()
    except ValueError:
        return text


def _first_failed_check(record: dict[str, Any]) -> dict[str, Any]:
    for check in record.get("build_check_replay_records", []):
        if check.get("success") is False:
            nested = check.get("generated_check_record")
            if isinstance(nested, dict) and nested.get("success") is False:
                return nested
            independent = check.get("independent_verification_record")
            if isinstance(independent, dict) and independent.get("success") is False:
                return independent
            return check
    if record.get("status") != "pass":
        return {
            "check_id": record.get("implementation_id", "implementation-attempt"),
            "success": False,
            "command": record.get("test_command", ""),
            "exit_code": None,
            "stdout": "",
            "stderr": record.get("recovery_suggestion", ""),
            "failure_class": record.get("failure_class", ""),
            "recovery_suggestion": record.get("recovery_suggestion", ""),
        }
    return {}


def _failed_task_ids(record: dict[str, Any]) -> list[str]:
    failed: list[str] = []
    for check in record.get("build_check_replay_records", []):
        task_id = check.get("task_id")
        if task_id and check.get("success") is False:
            failed.append(str(task_id))
        for task_record in check.get("independent_task_records", []):
            if task_record.get("task_id") and task_record.get("success") is False:
                failed.append(str(task_record["task_id"]))
        independent = check.get("independent_verification_record")
        if isinstance(independent, dict):
            for task_record in independent.get("task_records", []):
                if task_record.get("task_id") and task_record.get("success") is False:
                    failed.append(str(task_record["task_id"]))
    return sorted(set(failed))


def _preview(value: Any, *, limit: int = 2000) -> str:
    text = value if isinstance(value, str) else stable_json(value) if value else ""
    return text[-limit:]


def _agent_attempt_work_dir(context: PipelineContext, environment_id: str, *, attempt_index: int, total_attempts: int) -> Path:
    base = _agent_work_dir(context, environment_id)
    if total_attempts <= 1:
        return base
    return base / f"attempt-{attempt_index}"


def _agent_work_dir(context: PipelineContext, environment_id: str) -> Path:
    safe_environment_id = "".join(char if char.isalnum() or char in {"-", "_"} else "-" for char in environment_id)
    safe_run_id = "".join(char if char.isalnum() or char in {"-", "_"} else "-" for char in context.config.run_id)
    if context.store.root:
        return context.store.root / "build" / "agent-runs" / safe_run_id / safe_environment_id
    return Path(mkdtemp(prefix=f"agent-world-{safe_environment_id}-agent-"))


def _implementation_agent_input_ids(context: PipelineContext) -> list[str]:
    artifact_types = [
        "ImplementationRequest",
        "DomainPlan",
        "StrategySelection",
        "NeedSpec",
        "SourceEvidenceIndex",
        "KnowledgePack",
        "EnvironmentSpec",
        "LogicalToolGraph",
        "TaskSet",
        "SurfacePlan",
        "VerifierPlan",
        "FeasibilityReport",
    ]
    return [context.artifact(name)["id"] for name in artifact_types if name in context.artifacts]


def _implementation_agent_context_json(context: PipelineContext) -> str:
    artifact_types = [
        "ImplementationRequest",
        "DomainPlan",
        "StrategySelection",
        "NeedSpec",
        "KnowledgePack",
        "EnvironmentSpec",
        "LogicalToolGraph",
        "TaskSet",
        "SurfacePlan",
        "VerifierPlan",
    ]
    payload = {name: context.artifact(name) for name in artifact_types if name in context.artifacts}
    return stable_json(payload)


def _implementation_agent_instruction(
    context: PipelineContext,
    *,
    work_dir: Path,
    runner_backend: bool,
    attempt_index: int = 1,
    total_attempts: int = 1,
    failure_packet: dict[str, Any] | None = None,
) -> str:
    environment_id = context.artifact("ImplementationRequest")["environment_id"]
    repair_note = ""
    if failure_packet:
        repair_note = (
            f"\nThis is framework repair attempt {attempt_index} of {total_attempts}. "
            "Use the previous failure packet as the required repair target. "
            "Do not change pipeline flow or skip required files/checks. "
            "Keep candidate_manifest.json paths relative to candidate_dir unless the failure packet says the path itself is wrong.\n"
            f"Previous failure packet JSON:\n{stable_json(failure_packet)}\n"
        )
    if runner_backend:
        return (
            f"You are a code agent runner for {environment_id}. The isolated workspace is {work_dir}.\n"
            "Read the task packet under input/. Use the artifacts, brief, and acceptance checks as source of truth.\n"
            f"{repair_note}"
            "Write the generated environment only under generated/ with exactly these files: "
            "runtime.py, seed_state.json, verifier.py, surface_descriptor.json, check_replay.py, and build_manifest.yaml.\n"
            "Run at least one local check command against generated/check_replay.py. If it fails, repair the generated files and rerun the check.\n"
            "Treat input/framework-replay-contract.json and input/failure-packet.json as tool-style observations from the framework check workflow.\n"
            "Write agent-output/candidate_manifest.json after the final passing candidate. The manifest must declare "
            "candidate_dir: generated, generated_files objects with exact path/kind/sha256/source_refs values, "
            "entrypoints, check_commands, and replay_commands. Use the required kind table in input/expected-bundle-layout.md.\n"
            "Do not write outside generated/ and agent-output/. Do not import the repository fixture runtime. "
            "The framework will perform the final build/check/replay gate after you exit.\n"
        )
    return (
        f"Implement the accepted {environment_id} package in this isolated workdir: {work_dir}. "
        "Generate exactly runtime.py, seed_state.json, verifier.py, surface_descriptor.json, check_replay.py, and build_manifest.yaml. "
        "Return a JSON candidate manifest with relative paths, sha256 hashes, source refs, and build/check/replay commands. "
        "Do not modify the repository or any path outside the isolated workdir.\n\n"
        f"{repair_note}"
        "If you are an OpenAI-compatible codegen backend, return only JSON in this schema:\n"
        "{\"files\":[{\"path\":\"runtime.py\",\"content\":\"...\"}],\"evidence_refs\":[\"...\"]}.\n"
        "The backend will write the files and calculate sha256 values.\n\n"
        f"Accepted artifact context JSON:\n{_implementation_agent_context_json(context)}"
    )


def _implementation_agent_allowed_tools(runner_backend: bool) -> list[str]:
    if runner_backend:
        return [
            "read_workspace_packet",
            "write_generated_bundle_files",
            "run_local_checks",
            "repair_generated_bundle",
            "write_candidate_manifest",
        ]
    return ["write_generated_bundle_files"]


def _write_code_agent_workspace_packet(
    context: PipelineContext,
    work_dir: Path,
    *,
    failure_packet: dict[str, Any] | None = None,
    previous_attempt: dict[str, Any] | None = None,
) -> None:
    input_dir = work_dir / "input"
    artifacts_dir = input_dir / "artifacts"
    skills_dir = input_dir / "skills"
    generated_dir = work_dir / "generated"
    output_dir = work_dir / "agent-output"
    for path in [artifacts_dir, skills_dir, generated_dir, output_dir]:
        path.mkdir(parents=True, exist_ok=True)
    selected_artifacts = {
        name: context.artifact(name)
        for name in [
            "ImplementationRequest",
            "DomainPlan",
            "StrategySelection",
            "NeedSpec",
            "SourceEvidenceIndex",
            "KnowledgePack",
            "EnvironmentSpec",
            "LogicalToolGraph",
            "TaskSet",
            "SurfacePlan",
            "VerifierPlan",
            "FeasibilityReport",
        ]
        if name in context.artifacts
    }
    for name, artifact in selected_artifacts.items():
        (artifacts_dir / f"{name}.json").write_text(stable_json(artifact), encoding="utf-8")
    framework_replay_contract = build_framework_replay_contract(selected_artifacts)
    (input_dir / "framework-replay-contract.json").write_text(stable_json(framework_replay_contract), encoding="utf-8")
    (input_dir / "artifact-index.json").write_text(
        stable_json(
            {
                "artifact_files": {
                    name: f"artifacts/{name}.json"
                    for name in selected_artifacts
                },
                "artifact_ids": {
                    name: artifact["id"]
                    for name, artifact in selected_artifacts.items()
                },
                "framework_replay_contract": "framework-replay-contract.json",
            }
        ),
        encoding="utf-8",
    )
    (input_dir / "implementation-brief.md").write_text(_code_agent_implementation_brief(context), encoding="utf-8")
    (input_dir / "expected-bundle-layout.md").write_text(_code_agent_expected_bundle_layout(context), encoding="utf-8")
    (input_dir / "acceptance-checks.md").write_text(_code_agent_acceptance_checks(context), encoding="utf-8")
    (skills_dir / "environment-codegen.md").write_text(_code_agent_codegen_skill(), encoding="utf-8")
    if failure_packet:
        (input_dir / "failure-packet.json").write_text(stable_json(failure_packet), encoding="utf-8")
    if previous_attempt:
        (input_dir / "previous-attempt-record.json").write_text(stable_json(previous_attempt), encoding="utf-8")


def _code_agent_implementation_brief(context: PipelineContext) -> str:
    request = context.artifact("ImplementationRequest")
    task_ids = [task["task_id"] for task in context.artifact("TaskSet").get("tasks", [])] if "TaskSet" in context.artifacts else list(request.get("accepted_task_ids", []))
    verifier_ids = [verifier["verifier_id"] for verifier in context.artifact("VerifierPlan").get("verifiers", [])] if "VerifierPlan" in context.artifacts else list(request.get("accepted_verifier_ids", []))
    runtime_contract = _code_agent_runtime_contract(context)
    replay_notes = _code_agent_framework_replay_notes(context)
    replay_note_text = "".join(f"- framework_replay_expectation: {note}\n" for note in replay_notes)
    return (
        f"# Implementation Brief\n\n"
        f"- environment_id: {request['environment_id']}\n"
        f"- implementation_request_id: {request['id']}\n"
        "- candidate_dir: generated\n"
        "- required_files: runtime.py, seed_state.json, verifier.py, surface_descriptor.json, check_replay.py, build_manifest.yaml\n"
        f"- required_manifest_file_kinds: {stable_json(GENERATED_BUNDLE_FILE_KINDS)}\n"
        f"- required_runtime_entrypoint: {runtime_contract['runtime_entrypoint']}\n"
        "- required_runtime_constructor: __init__(state, trace_path=None, task_id=None, call_group=None)\n"
        "- required_runtime_helpers: runtime.load_seed_state(seed_path), runtime.reset_environment(seed_state)\n"
        f"- required_python_methods_on_entrypoint: {', '.join(runtime_contract['python_methods'])}\n"
        "- required_trace_jsonl: each runtime tool call appends a JSON object with `tool`, `task_id`, and `call_group` when trace_path is provided\n"
        "- required_verifier_entrypoint: verifier.verify_task_completion must accept framework kwargs `surface_trace_path`, `expected_dependency_path`, `trace_call_group`, and `final_answer`\n"
        f"{replay_note_text}"
        f"- required_tasks: {', '.join(task_ids)}\n"
        f"- required_verifiers: {', '.join(verifier_ids)}\n"
        "- required_negative_check: each task verifier must return success=false when required tool actions, state delta, or answer evidence are absent\n\n"
        "Use input/framework-replay-contract.json as the machine-readable framework execution contract, and use input/artifacts/*.json as the source-grounded specification. "
        "The generated bundle must be self-contained; "
        "runtime.py, verifier.py, and check_replay.py must not import repository fixture runtimes. "
        "If you use internal helper classes, still expose the required runtime entrypoint class and helper functions exactly as listed above.\n"
    )


def _code_agent_runtime_contract(context: PipelineContext | None) -> dict[str, Any]:
    fallback = {
        "runtime_entrypoint": "runtime.GeneratedEnvironment",
        "python_methods": [],
    }
    if context is None or "SurfacePlan" not in context.artifacts:
        return fallback
    bindings = [
        binding
        for binding in context.artifact("SurfacePlan").get("bindings", [])
        if binding.get("surface") == "python" and binding.get("logical_tool_id")
    ]
    python_methods = [str(binding.get("method_name") or binding["logical_tool_id"]) for binding in bindings]
    runtime_class = ""
    for binding in bindings:
        exposure = str(binding.get("exposure_name") or "")
        if "." in exposure:
            runtime_class = exposure.split(".", 1)[0]
            break
    if not runtime_class:
        runtime_class = fallback["runtime_entrypoint"].split(".", 1)[1]
    return {
        "runtime_entrypoint": f"runtime.{runtime_class}",
        "python_methods": python_methods,
    }


def _code_agent_framework_replay_notes(context: PipelineContext) -> list[str]:
    notes: list[str] = []
    if "TaskSet" not in context.artifacts:
        return notes
    for task in context.artifact("TaskSet").get("tasks", []):
        calls = task.get("framework_replay", {}).get("tool_calls", [])
        if not calls:
            calls = [{"tool": tool, "kwargs": {}} for tool in task.get("dependency_path", [])]
        call_text = ", ".join(f"{call.get('tool')}({stable_json(call.get('kwargs', {}))})" for call in calls)
        notes.append(f"{task.get('task_id')}: framework will replay {call_text} and then call verifier with the task dependency path")
    return notes


def _code_agent_acceptance_checks(context: PipelineContext | None = None) -> str:
    task_ids = []
    if context is not None and "TaskSet" in context.artifacts:
        task_ids = [task["task_id"] for task in context.artifact("TaskSet").get("tasks", [])]
    task_text = ", ".join(task_ids) if task_ids else "all accepted tasks in input/artifacts/TaskSet.json"
    return (
        "# Acceptance Checks\n\n"
        "1. `python generated/check_replay.py` exits 0.\n"
        "2. The check prints a final JSON object with `success: true`.\n"
        f"3. It covers {task_text}.\n"
        "4. Each task has a positive verifier result with `success: true` and a negative verifier result with `success: false`.\n"
        "5. `agent-output/candidate_manifest.json` declares `candidate_dir: generated` and a `generated_files` object for each required file.\n"
        "6. Each `generated_files[]` item declares exact `path`, exact `kind` from the required manifest kind table, lowercase 64-character `sha256`, and `source_refs`.\n"
        "7. The framework independent verifier can import `runtime.py`, instantiate the required runtime class with `trace_path`, call helper functions, find every required method, read JSONL tool traces, and call `verifier.verify_task_completion` with framework kwargs.\n"
        "8. `input/framework-replay-contract.json` describes the framework-owned replay cases and check command; generated code must satisfy that contract.\n"
        "9. On a repair attempt, read `input/failure-packet.json` and address the listed framework_check_observation, failed task/verifier, and command output without changing the manifest path shape unless the failure is a manifest/path/hash failure.\n"
    )


def _code_agent_expected_bundle_layout(context: PipelineContext | None = None) -> str:
    kind_lines = "".join(
        f"- `{filename}` -> `{kind}`\n"
        for filename, kind in GENERATED_BUNDLE_FILE_KINDS.items()
    )
    runtime_contract = _code_agent_runtime_contract(context)
    manifest_example = {
        "candidate_dir": "generated",
        "generated_files": [
            {
                "path": filename,
                "kind": kind,
                "sha256": "<lowercase 64-character sha256>",
                "source_refs": ["<artifact id or source ref>"],
            }
            for filename, kind in GENERATED_BUNDLE_FILE_KINDS.items()
        ],
        "entrypoints": {
            "runtime": "runtime.py",
            "seed_state": "seed_state.json",
            "verifier": "verifier.py",
            "surface_descriptor": "surface_descriptor.json",
            "check_replay": "check_replay.py",
            "build_manifest": "build_manifest.yaml",
        },
        "check_commands": [["python", "generated/check_replay.py"]],
        "replay_commands": [["python", "generated/check_replay.py"]],
    }
    return (
        "# Expected Bundle Layout\n\n"
        "Write exactly these files under `generated/`:\n\n"
        "- `runtime.py`: self-contained environment runtime and logical tool behavior.\n"
        "- `seed_state.json`: deterministic seed state fixture.\n"
        "- `verifier.py`: deterministic verifier with positive and negative behavior.\n"
        "- `surface_descriptor.json`: implemented/deferred concrete surfaces.\n"
        "- `check_replay.py`: executable build/check/replay entrypoint.\n"
        "- `build_manifest.yaml`: bundle metadata, entrypoints, and commands.\n\n"
        "Runtime entrypoint contract:\n\n"
        f"- `runtime.py` must expose `{runtime_contract['runtime_entrypoint']}`.\n"
        "- The runtime class constructor must accept `state`, optional `trace_path`, optional `task_id`, and optional `call_group` keyword arguments.\n"
        "- `runtime.py` must expose `load_seed_state(seed_path)` and `reset_environment(seed_state)` module functions.\n"
        f"- The runtime entrypoint class must implement these Python methods: {', '.join(runtime_contract['python_methods'])}.\n\n"
        "Independent verifier replay contract:\n\n"
        "- The framework will instantiate the runtime as `RuntimeClass(state, trace_path=Path(...), task_id=task_id, call_group=\"positive\")`.\n"
        "- Every runtime tool method should append one JSONL record to `trace_path` with at least `tool`, `task_id`, and `call_group`.\n"
        "- `verifier.verify_task_completion` will be called with `surface_trace_path` as a Path to that JSONL file, plus `expected_dependency_path`, `trace_call_group`, and `final_answer` kwargs.\n\n"
        "Required manifest kind table:\n\n"
        f"{kind_lines}\n"
        "Candidate manifest schema example:\n\n"
        "```json\n"
        f"{json.dumps(manifest_example, indent=2, sort_keys=True)}\n"
        "```\n\n"
        "Write runner traces and `candidate_manifest.json` under `agent-output/`; do not place them in `generated/`.\n"
        "`candidate_dir` is `generated`, so every `generated_files[].path` must be relative to that directory, such as `runtime.py`; do not use `generated/runtime.py` or absolute paths.\n"
        "Do not leave transient replay traces, logs, scratch files, or cleanup markers under `generated/`; use temporary directories or `agent-output/` for runner-only files.\n"
    )


def _code_agent_codegen_skill() -> str:
    return (
        "# Skill: Environment Code Generation\n\n"
        "Read the artifacts first, then implement the smallest executable environment that satisfies the task and verifier plan. "
        "Prefer deterministic state checks over text judging. Keep surfaces separate from logical tools. "
        "Expose the exact runtime entrypoint and helper functions named in the implementation brief. "
        "Keep `generated/` to the six declared bundle files only; do not use shell `rm` cleanup commands inside the Codex sandbox. "
        "After writing files, run the local check, repair failures, and update the candidate manifest only after the final check passes.\n"
    )


def _prepare_agent_work_dir(work_dir: Path) -> None:
    work_dir.mkdir(parents=True, exist_ok=True)
    for child in work_dir.iterdir():
        if child.is_dir() and not child.is_symlink():
            shutil.rmtree(child)
        else:
            child.unlink()


def _with_invocation_outputs(invocation: dict[str, Any], *, output_artifact_ids: list[str], evidence_refs: list[str]) -> dict[str, Any]:
    updated = dict(invocation)
    updated["output_artifact_ids"] = sorted(set(updated.get("output_artifact_ids", [])) | set(output_artifact_ids))
    updated["evidence_refs"] = sorted(set(updated.get("evidence_refs", [])) | set(evidence_refs))
    updated["hash"] = ""
    updated["hash"] = artifact_hash(updated)
    validate_artifact("AgentInvocationRecord", updated)
    return updated


def _artifact_id_from_fields(fields: dict[str, Any]) -> str | None:
    for key in ["domain_plan_id", "strategy_selection_id", "request_id", "package_plan_id", "replay_plan_id", "consumer_index_id", "release_id", "backend_id", "report_id"]:
        if fields.get(key):
            return fields[key]
    return None
