from __future__ import annotations

from dataclasses import dataclass, field, replace
import json
import os
from pathlib import Path
import shutil
from tempfile import mkdtemp
from typing import Any, Callable

from agent_world.agents import (
    InvocationRequest,
    InvocationBackendRegistry,
    default_invocation_backend_registry,
    invoke_backend,
    load_invocation_backend_config_from_env,
    load_implementation_invocation_backend_config_from_env,
)
from agent_world.artifacts import GENERATED_PROJECT_FILE_KINDS, RUNTIME_ABI_INTERFACES, artifact_hash, make_artifact, stable_json, utc_now, validate_artifact
from agent_world.executors.base import NodeAttemptResult
from agent_world.executors.agent_attempt import AgentAttemptExecutor
from agent_world.executors.llm_attempt import LlmAttemptExecutor
from agent_world.gates import STAGE_GATES, evaluate_stage_gates
from agent_world.generated_project import assemble_generated_project_package
import agent_world.request_driven as request_driven
from agent_world.replay_contract import build_framework_replay_contract, normalise_framework_replay_calls
from agent_world.review import independent_review
from agent_world.store import ArtifactStore
from agent_world.strategies import attempt_profile_for_stage


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
    invocation_record_ids: list[str] = field(default_factory=list)
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
    invocation_record_ids: list[str]
    implementation_check_records: list[dict[str, Any]]
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
            "invocation_record_ids": self.invocation_record_ids,
            "implementation_check_records": self.implementation_check_records,
            "repair_failure_packets": self.repair_failure_packets,
            "failure_class": self.failure_class,
            "recovery_suggestion": self.recovery_suggestion,
        }


@dataclass
class PipelineContext:
    config: PipelineRunConfig
    store: ArtifactStore
    invocation_registry: InvocationBackendRegistry
    artifacts: dict[str, dict[str, Any]] = field(default_factory=dict)
    gate_records: list[dict[str, Any]] = field(default_factory=list)
    review_records: list[dict[str, Any]] = field(default_factory=list)
    invocation_records: list[dict[str, Any]] = field(default_factory=list)
    implementation_check_records: list[dict[str, Any]] = field(default_factory=list)
    repair_failure_packets: list[dict[str, Any]] = field(default_factory=list)
    node_feedback: dict[str, list[dict[str, str]]] = field(default_factory=dict)

    def artifact(self, artifact_type: str) -> dict[str, Any]:
        return self.artifacts[artifact_type]

    def upstream_artifacts(self) -> list[dict[str, Any]]:
        return [artifact for name, artifact in self.artifacts.items() if name not in {"InvocationBackendConfig", "ImplementationInvocationBackendConfig"}]


@dataclass(frozen=True)
class PipelineNode:
    node_id: str
    stage: str
    artifact_type: str
    input_artifact_types: list[str]
    output_artifact_type: str
    execution_mode: str
    factory: Callable[[PipelineContext], dict[str, Any]] | None = None
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
        invocation_registry: InvocationBackendRegistry | None = None,
    ) -> None:
        self.node_registry = node_registry or request_driven_node_registry()
        self.invocation_registry = invocation_registry or default_invocation_backend_registry()
        self.node_executors = {
            LlmAttemptExecutor.executor_id: LlmAttemptExecutor(),
            AgentAttemptExecutor.executor_id: AgentAttemptExecutor(),
        }

    def run(self, config: PipelineRunConfig) -> tuple[PipelineRunRecord, PipelineContext]:
        started_at = utc_now()
        store = ArtifactStore(config.output_dir / "pipeline-store" if config.output_dir else None)
        context = PipelineContext(config=config, store=store, invocation_registry=self.invocation_registry)
        backend_config = load_invocation_backend_config_from_env(config.env)
        implementation_backend_config = load_implementation_invocation_backend_config_from_env(config.env)
        context.artifacts["InvocationBackendConfig"] = backend_config
        context.artifacts["ImplementationInvocationBackendConfig"] = implementation_backend_config
        store.put_artifact("InvocationBackendConfig", backend_config)
        store.put_artifact("ImplementationInvocationBackendConfig", implementation_backend_config)
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
            package_error = _assemble_generated_project_package_if_available(context)
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
            invocation_record_ids=[record["id"] for record in context.invocation_records],
            implementation_check_records=context.implementation_check_records,
            repair_failure_packets=context.repair_failure_packets,
            failure_class=failure_class,
            recovery_suggestion=recovery_suggestion,
        )
        store.write_run_record(record.to_dict())
        return record, context

    def _run_artifact_node(self, node: PipelineNode, context: PipelineContext) -> PipelineNodeResult:
        attempts = _stage_attempt_budget(node, context)
        last_result: PipelineNodeResult | None = None
        for attempt_index in range(1, attempts + 1):
            snapshot = _context_stage_snapshot(context)
            result = self._run_artifact_node_once(node, context, attempt_index=attempt_index)
            last_result = result
            if result.status == "pass":
                return result
            can_retry = attempt_index < attempts and _stage_can_retry(node, result)
            _mark_latest_stage_failure_packet_terminal(context, node, attempt_index=attempt_index, terminal=not can_retry)
            if not can_retry:
                return result
            _append_node_feedback(context, node, result)
            _restore_context_stage_snapshot(context, snapshot)
        return last_result or PipelineNodeResult(node_id=node.node_id, stage=node.stage, status="fail", artifact_type=node.output_artifact_type)

    def _run_artifact_node_once(self, node: PipelineNode, context: PipelineContext, *, attempt_index: int) -> PipelineNodeResult:
        try:
            execution = self._execute_artifact_node(node, context, attempt_index=attempt_index)
            if execution.status != "pass":
                invocation_records = _store_node_invocations(context, execution, output_artifact_ids=[], evidence_refs=execution.evidence_refs)
                failure_packet = _record_stage_failure_packet(
                    context,
                    node=node,
                    artifact=None,
                    attempt_index=attempt_index,
                    failure_class=execution.failure_class or "node_attempt_failed",
                    recovery_suggestion=execution.recovery_suggestion or "Fix the configured node attempt executor or invocation backend.",
                    gate_record_ids=[],
                )
                return PipelineNodeResult(
                    node_id=node.node_id,
                    stage=node.stage,
                    status=execution.status,
                    artifact_type=node.output_artifact_type,
                    output_refs=[failure_packet["trace_ref"]] + execution.trace_refs,
                    invocation_record_ids=[record["id"] for record in invocation_records],
                    failure_class=execution.failure_class or "node_attempt_failed",
                    recovery_suggestion=execution.recovery_suggestion or "Fix the configured node attempt executor or invocation backend.",
                )
            fields = execution.fields
            base_invocation_records = _prepare_node_invocations(execution, output_artifact_ids=[], evidence_refs=execution.evidence_refs)
            try:
                artifact = make_artifact(
                    node.output_artifact_type,
                    source_stage=node.stage,
                    producer=node.node_id,
                    fields=fields,
                    artifact_id=_artifact_id_from_fields(fields),
                    inputs=[context.artifacts[name]["id"] for name in node.input_artifact_types if name in context.artifacts],
                )
            except Exception as exc:
                _store_prepared_node_invocations(context, base_invocation_records)
                failure_packet = _record_stage_failure_packet(
                    context,
                    node=node,
                    artifact=None,
                    attempt_index=attempt_index,
                    failure_class="invalid_attempt_artifact_fields",
                    recovery_suggestion=str(exc),
                    gate_record_ids=[],
                )
                return PipelineNodeResult(
                    node_id=node.node_id,
                    stage=node.stage,
                    status="fail",
                    artifact_type=node.output_artifact_type,
                    output_refs=[failure_packet["trace_ref"]] + execution.trace_refs,
                    invocation_record_ids=[record["id"] for record in base_invocation_records],
                    failure_class="invalid_attempt_artifact_fields",
                    recovery_suggestion=str(exc),
                )
            invocation_records = _store_node_invocations(
                context,
                execution,
                output_artifact_ids=[artifact["id"]],
                evidence_refs=[artifact["id"]] + execution.evidence_refs,
            )
            review = independent_review(
                stage=node.stage,
                artifact=artifact,
                need_spec=context.artifacts.get("NeedSpec") or (artifact if node.output_artifact_type == "NeedSpec" else None),
                upstream_artifacts=context.upstream_artifacts(),
                gate_checklist=list(STAGE_GATES[node.stage]),
                source_of_truth_refs=[
                    SOURCE_DOC_REF,
                ],
                reviewer_ref="pipeline-static-reviewer",
            )
            gate_records = evaluate_stage_gates(
                stage=node.stage,
                artifact_type=node.output_artifact_type,
                artifact=artifact,
                context=context.artifacts | {node.output_artifact_type: artifact, "__gate_records__": {record["id"]: record for record in context.gate_records}},
                review=review,
                invocations=invocation_records,
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
                    attempt_index=attempt_index,
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
                    invocation_record_ids=[record["id"] for record in invocation_records],
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
                invocation_record_ids=[record["id"] for record in invocation_records],
            )
        except Exception as exc:
            failure_packet = _record_stage_failure_packet(
                context,
                node=node,
                artifact=None,
                attempt_index=attempt_index,
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

    def _execute_artifact_node(self, node: PipelineNode, context: PipelineContext, *, attempt_index: int) -> NodeAttemptResult:
        if node.execution_mode == "deterministic":
            if node.factory is None:
                return NodeAttemptResult(
                    status="fail",
                    failure_class="deterministic_factory_missing",
                    recovery_suggestion=f"Stage {node.stage} is deterministic but has no factory.",
                )
            return NodeAttemptResult(status="pass", fields=node.factory(context))
        if node.execution_mode not in {"llm", "agent"}:
            return NodeAttemptResult(
                status="fail",
                failure_class="invalid_node_execution_mode",
                recovery_suggestion=f"Stage {node.stage} declares unsupported execution_mode={node.execution_mode!r}.",
            )
        profile = attempt_profile_for_stage(node.stage)
        if profile is None:
            return NodeAttemptResult(
                status="fail",
                failure_class="node_attempt_profile_missing",
                recovery_suggestion=f"Stage {node.stage} is {node.execution_mode} but has no attempt profile.",
            )
        expected_executor_id = {"llm": LlmAttemptExecutor.executor_id, "agent": AgentAttemptExecutor.executor_id}[node.execution_mode]
        if profile.executor_id != expected_executor_id:
            return NodeAttemptResult(
                status="fail",
                failure_class="node_attempt_profile_mismatch",
                recovery_suggestion=f"Stage {node.stage} declares execution_mode={node.execution_mode} but profile uses {profile.executor_id}.",
            )
        executor = self.node_executors.get(profile.executor_id)
        if executor is None:
            return NodeAttemptResult(
                status="fail",
                failure_class="node_attempt_executor_not_registered",
                recovery_suggestion=f"No attempt executor registered for {profile.executor_id}.",
            )
        return executor.execute(context, node, profile, attempt_index=attempt_index)

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
            recovery_suggestion="Generated environments require an agent execution backend that writes a contract-project candidate.",
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
            execution_mode="llm",
        )
    )
    registry.register(
        PipelineNode(
            node_id="request-strategy-selector",
            stage="SELECT",
            artifact_type="StrategySelection",
            input_artifact_types=["DomainPlan"],
            output_artifact_type="StrategySelection",
            execution_mode="deterministic",
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
            execution_mode="llm",
        )
    )
    registry.register(
        PipelineNode(
            node_id="request-driven-source-planning-discovery",
            stage="S1",
            artifact_type="SourceEvidenceIndex",
            input_artifact_types=["NeedSpec", "DomainPlan", "StrategySelection"],
            output_artifact_type="SourceEvidenceIndex",
            execution_mode="agent",
        )
    )
    registry.register(
        PipelineNode(
            node_id="request-driven-source-grounded-extractor",
            stage="S2",
            artifact_type="KnowledgePack",
            input_artifact_types=["SourceEvidenceIndex", "StrategySelection"],
            output_artifact_type="KnowledgePack",
            execution_mode="llm",
        )
    )
    registry.register(
        PipelineNode(
            node_id="request-driven-spec-synthesis",
            stage="S3",
            artifact_type="EnvironmentSpec",
            input_artifact_types=["NeedSpec", "KnowledgePack", "DomainPlan", "StrategySelection"],
            output_artifact_type="EnvironmentSpec",
            execution_mode="llm",
        )
    )
    registry.register(
        PipelineNode(
            node_id="request-driven-tool-graph-synthesis",
            stage="S4",
            artifact_type="LogicalToolGraph",
            input_artifact_types=["EnvironmentSpec", "KnowledgePack", "StrategySelection"],
            output_artifact_type="LogicalToolGraph",
            execution_mode="llm",
        )
    )
    registry.register(
        PipelineNode(
            node_id="request-driven-task-generation",
            stage="S5",
            artifact_type="TaskSet",
            input_artifact_types=["NeedSpec", "LogicalToolGraph", "EnvironmentSpec", "KnowledgePack"],
            output_artifact_type="TaskSet",
            execution_mode="llm",
        )
    )
    registry.register(
        PipelineNode(
            node_id="request-driven-surface-planning",
            stage="S6",
            artifact_type="SurfacePlan",
            input_artifact_types=["LogicalToolGraph", "EnvironmentSpec", "StrategySelection"],
            output_artifact_type="SurfacePlan",
            execution_mode="llm",
        )
    )
    registry.register(
        PipelineNode(
            node_id="request-driven-verifier-planning",
            stage="S7",
            artifact_type="VerifierPlan",
            input_artifact_types=["TaskSet", "EnvironmentSpec", "SurfacePlan", "KnowledgePack"],
            output_artifact_type="VerifierPlan",
            execution_mode="llm",
        )
    )
    registry.register(
        PipelineNode(
            node_id="request-driven-deterministic-feasibility",
            stage="S8",
            artifact_type="FeasibilityReport",
            input_artifact_types=["NeedSpec", "DomainPlan", "StrategySelection", "SourceEvidenceIndex", "KnowledgePack", "EnvironmentSpec", "LogicalToolGraph", "TaskSet", "SurfacePlan", "VerifierPlan"],
            output_artifact_type="FeasibilityReport",
            execution_mode="deterministic",
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
            execution_mode="deterministic",
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
            execution_mode="agent",
            factory=request_driven.generated_implementation_record,
        )
    )
    registry.register(
        PipelineNode(
            node_id="request-driven-package-plan",
            stage="S10",
            artifact_type="EnvironmentPackagePlan",
            input_artifact_types=["ImplementationRequest", "GeneratedEnvironmentProject", "IndependentVerificationReport"],
            output_artifact_type="EnvironmentPackagePlan",
            execution_mode="deterministic",
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
            execution_mode="deterministic",
            factory=request_driven.release_manifest_fields,
        )
    )
    return registry


def run_request_driven_pipeline(
    config: PipelineRunConfig,
    *,
    invocation_registry: InvocationBackendRegistry | None = None,
) -> tuple[PipelineRunRecord, PipelineContext]:
    if config.implementation_mode != "agent":
        config = replace(config, implementation_mode="agent")
    return PipelineRunner(request_driven_node_registry(), invocation_registry=invocation_registry).run(config)


def _assemble_generated_project_package_if_available(context: PipelineContext) -> dict[str, str] | None:
    if context.config.output_dir is None:
        return None
    if "GeneratedEnvironmentProject" not in context.artifacts or "ReleaseManifest" not in context.artifacts:
        return None
    try:
        assemble_generated_project_package(
            package_dir=context.config.output_dir / "envpkg",
            artifacts=context.artifacts,
            gate_records=context.gate_records,
            review_records=context.review_records,
            invocation_records=context.invocation_records,
            implementation_check_records=context.implementation_check_records,
        )
    except Exception as exc:
        return {
            "failure_class": exc.__class__.__name__,
            "recovery_suggestion": str(exc),
        }
    return None


def _record_deterministic_implementation(context: PipelineContext, node: PipelineNode, record: dict[str, Any]) -> PipelineNodeResult:
    project = record.get("generated_environment_project")
    if isinstance(project, dict):
        context.artifacts["GeneratedEnvironmentProject"] = project
        context.store.put_artifact("GeneratedEnvironmentProject", project)
    independent_report = record.get("independent_verification_report")
    if isinstance(independent_report, dict):
        context.artifacts["IndependentVerificationReport"] = independent_report
        context.store.put_artifact("IndependentVerificationReport", independent_report)
    trace_ref = context.store.put_trace(f"implementation-{record['environment_id']}-deterministic", record)
    context.implementation_check_records.append(record)
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
        all_invocation_ids.extend(result.invocation_record_ids)
        all_output_refs.extend(ref for ref in result.output_refs if ref)
        attempt_record = context.implementation_check_records[-1] if context.implementation_check_records else {}
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
    backend_config = context.artifact("ImplementationInvocationBackendConfig")
    backend_kind = backend_config["backend_kind"]
    is_runner_backend = backend_kind in {"code_agent_runner", "codex_cli_runner", "codex_sdk"}
    repair_thread_mode = _implementation_repair_thread_mode(backend_config)
    parent_invocation_id = str(failure_packet.get("previous_invocation_record_id", "")) if failure_packet else ""
    conversation_ref = _implementation_repair_conversation_ref(context, parent_invocation_id) if parent_invocation_id else ""
    if backend_kind == "codex_sdk" and repair_thread_mode == "continue" and failure_packet and not conversation_ref:
        record = {
            "implementation_id": f"implementation-{environment_id}-agent",
            "mode": "agent_backed",
            "environment_id": environment_id,
            "implementation_request_id": request_artifact["id"],
            "invocation_record_id": parent_invocation_id,
            "static_check_command": "not run",
            "test_command": "not run",
            "replay_command": "not run",
            "implementation_check_records": [],
            "verifier_result": {},
            "status": "fail",
            "failure_class": "missing_code_repair_conversation_ref",
            "recovery_suggestion": "Disable code_repair_thread_mode: continue in YAML or rerun the initial IMPLEMENT attempt with Codex SDK continuation enabled.",
        }
        record = _with_attempt_metadata(
            record,
            attempt_index=attempt_index,
            total_attempts=total_attempts,
            max_repair_attempts=max_repair_attempts,
            input_failure_packet=failure_packet,
        )
        trace_ref = context.store.put_trace(f"implementation-{environment_id}-agent", record)
        context.implementation_check_records.append(record)
        return PipelineNodeResult(
            node_id=node.node_id,
            stage=node.stage,
            status="fail",
            output_refs=[trace_ref],
            failure_class=record["failure_class"],
            recovery_suggestion=record["recovery_suggestion"],
        )
    if is_runner_backend:
        _write_code_agent_workspace_packet(context, work_dir, failure_packet=failure_packet, previous_attempt=previous_attempt)
    input_artifact_ids = _implementation_agent_input_ids(context)
    if failure_packet:
        input_artifact_ids.append(failure_packet["packet_id"])
    permissions = {
        "network": backend_kind in {"llm", "llm_file_codegen", "code_agent_runner", "codex_cli_runner", "codex_sdk"} and bool(backend_config.get("permissions", {}).get("network")),
        "filesystem": "isolated_agent_workspace" if is_runner_backend else "isolated_workdir",
        "filesystem_root": str(work_dir),
        "auth": backend_kind in {"llm", "llm_file_codegen", "code_agent_runner", "codex_cli_runner", "codex_sdk"} and bool(backend_config.get("permissions", {}).get("auth")),
        "sandbox": backend_kind in {"codex_cli", "codex_cli_runner", "codex_sdk"} and bool(backend_config.get("permissions", {}).get("sandbox")),
    }
    instruction = _implementation_agent_instruction(
        context,
        work_dir=work_dir,
        runner_backend=is_runner_backend,
        attempt_index=attempt_index,
        total_attempts=total_attempts,
        failure_packet=failure_packet,
    )
    request = InvocationRequest(
        stage="IMPLEMENT",
        node_purpose="implement",
        instruction=instruction,
        input_artifact_ids=input_artifact_ids,
        invocation_id=f"invoke-implement-codegen-{environment_id}-attempt-{attempt_index}",
        allowed_tool_access=_implementation_agent_allowed_tools(is_runner_backend),
        permissions=permissions,
        budget={"tokens": 0, "time_ms": int(backend_config.get("timeouts", {}).get("run_ms") or 5000), "cost_limit": 0},
        instruction_ref=f"{SOURCE_DOC_REF}#agent-backed-implementation",
        parent_invocation_id=parent_invocation_id,
        conversation_ref=conversation_ref,
        continuation_mode=repair_thread_mode if backend_kind == "codex_sdk" else "stateless",
    )
    invocation, result = invoke_backend(context.invocation_registry, request, backend_config)
    if "DomainPlan" not in context.artifacts or "StrategySelection" not in context.artifacts:
        context.invocation_records.append(invocation)
        context.store.put_invocation_records([invocation])
        record = {
            "implementation_id": f"implementation-{environment_id}-agent",
            "mode": "agent_backed",
            "environment_id": environment_id,
            "implementation_request_id": request_artifact["id"],
            "invocation_record_id": invocation["id"],
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
        record = _with_agent_continuation_metadata(record, request=request, invocation=invocation)
        record = _redact_attempt_record(context, record)
        trace_ref = context.store.put_trace("implementation-agent", record)
        context.implementation_check_records.append(record)
        return PipelineNodeResult(
            node_id=node.node_id,
            stage=node.stage,
            status=record["status"],
            output_refs=[trace_ref],
            invocation_record_ids=[invocation["id"]],
            failure_class=record["failure_class"],
            recovery_suggestion=record["recovery_suggestion"],
        )
    record = request_driven.agent_generated_implementation_record(
        context,
        invocation_record=invocation,
        invocation_result=result,
        work_dir=work_dir,
    )
    record = _with_attempt_metadata(
        record,
        attempt_index=attempt_index,
        total_attempts=total_attempts,
        max_repair_attempts=max_repair_attempts,
        input_failure_packet=failure_packet,
    )
    record = _with_agent_continuation_metadata(record, request=request, invocation=invocation)
    record = _redact_attempt_record(context, record)
    project = record.get("generated_environment_project")
    independent_report = record.get("independent_verification_report")
    if isinstance(project, dict):
        context.artifacts["GeneratedEnvironmentProject"] = project
        context.store.put_artifact("GeneratedEnvironmentProject", project)
        invocation = _with_invocation_outputs(invocation, output_artifact_ids=[project["id"]], evidence_refs=[project["id"]])
    if isinstance(independent_report, dict):
        context.artifacts["IndependentVerificationReport"] = independent_report
        context.store.put_artifact("IndependentVerificationReport", independent_report)
        invocation = _with_invocation_outputs(invocation, output_artifact_ids=[independent_report["id"]], evidence_refs=[independent_report["id"]])
    context.invocation_records.append(invocation)
    context.store.put_invocation_records([invocation])
    trace_ref = context.store.put_trace(f"implementation-{environment_id}-agent", record)
    context.implementation_check_records.append(record)
    if record["status"] != "pass":
        return PipelineNodeResult(
            node_id=node.node_id,
            stage=node.stage,
            status=record["status"],
            output_refs=[trace_ref],
            invocation_record_ids=[invocation["id"]],
            failure_class=record["failure_class"],
            recovery_suggestion=record["recovery_suggestion"],
        )
    return PipelineNodeResult(
        node_id=node.node_id,
        stage=node.stage,
        status="pass",
        output_refs=[trace_ref, project["id"] if isinstance(project, dict) else "", independent_report["id"] if isinstance(independent_report, dict) else ""],
        artifact_type="GeneratedEnvironmentProject",
        artifact_id=project["id"] if isinstance(project, dict) else "",
        invocation_record_ids=[invocation["id"]],
    )


def _configured_max_repair_attempts(config: PipelineRunConfig) -> int:
    return max(0, int(config.max_repair_attempts))


def _stage_attempt_budget(node: PipelineNode, context: PipelineContext) -> int:
    if node.execution_mode == "deterministic":
        return 1
    config = context.artifacts.get("InvocationBackendConfig", {})
    return max(1, int((config.get("retries") or {}).get("max_attempts") or 1))


def _stage_can_retry(node: PipelineNode, result: PipelineNodeResult) -> bool:
    if node.execution_mode == "deterministic":
        return False
    if result.status not in {"fail", "needs_human"}:
        return False
    return result.failure_class not in {
        "mock_backend_not_allowed",
        "manual_input_required",
        "permission_denied",
        "network_permission_denied",
        "auth_permission_denied",
        "node_attempt_profile_missing",
        "node_attempt_profile_mismatch",
        "node_attempt_executor_not_registered",
        "invalid_node_execution_mode",
    }


def _append_node_feedback(context: PipelineContext, node: PipelineNode, result: PipelineNodeResult) -> None:
    context.node_feedback.setdefault(node.stage, []).append(
        {
            "stage": node.stage,
            "artifact_type": node.output_artifact_type,
            "failure_class": result.failure_class or "stage_failed",
            "recovery_suggestion": result.recovery_suggestion or "Regenerate the artifact so all schema, review, and gate checks pass.",
            "artifact_id": result.artifact_id,
        }
    )


def _context_stage_snapshot(context: PipelineContext) -> dict[str, Any]:
    return {
        "artifacts": dict(context.artifacts),
        "gate_records": list(context.gate_records),
        "review_records": list(context.review_records),
        "store_artifacts": dict(context.store.artifacts),
        "store_gate_records": list(context.store.gate_records),
        "store_review_records": list(context.store.review_records),
    }


def _restore_context_stage_snapshot(context: PipelineContext, snapshot: dict[str, Any]) -> None:
    context.artifacts = dict(snapshot["artifacts"])
    context.gate_records = list(snapshot["gate_records"])
    context.review_records = list(snapshot["review_records"])
    context.store.artifacts = dict(snapshot["store_artifacts"])
    context.store.gate_records = list(snapshot["store_gate_records"])
    context.store.review_records = list(snapshot["store_review_records"])


def _implementation_repair_thread_mode(backend_config: dict[str, Any]) -> str:
    mode = str((backend_config.get("code_repair") or {}).get("thread_mode") or "stateless").strip().lower()
    return mode if mode in {"stateless", "continue"} else "stateless"


def _implementation_repair_conversation_ref(context: PipelineContext, parent_invocation_id: str) -> str:
    if not parent_invocation_id:
        return ""
    for invocation in reversed(context.invocation_records):
        if invocation.get("id") == parent_invocation_id:
            return str(invocation.get("conversation_ref") or "")
    return ""


def _roll_up_attempt_result(result: PipelineNodeResult, *, invocation_ids: list[str], output_refs: list[str]) -> PipelineNodeResult:
    result.invocation_record_ids = list(dict.fromkeys(invocation_ids))
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


def _with_agent_continuation_metadata(record: dict[str, Any], *, request: InvocationRequest, invocation: dict[str, Any]) -> dict[str, Any]:
    updated = dict(record)
    updated["code_repair_thread_mode"] = request.continuation_mode
    if request.parent_invocation_id:
        updated["parent_invocation_record_id"] = request.parent_invocation_id
    conversation_ref = str(invocation.get("conversation_ref") or request.conversation_ref or "")
    if conversation_ref:
        updated["agent_conversation_ref"] = conversation_ref
    return updated


def _redact_attempt_record(context: PipelineContext, record: dict[str, Any]) -> dict[str, Any]:
    secrets = _secret_values_for_context(context)
    if not secrets:
        return record
    return _redact_value(record, secrets)


def _secret_values_for_context(context: PipelineContext) -> list[str]:
    names: set[str] = set()
    for config_name in ["InvocationBackendConfig", "ImplementationInvocationBackendConfig"]:
        config = context.artifacts.get(config_name, {})
        auth = config.get("auth", {}) if isinstance(config, dict) else {}
        names.update(str(name) for name in auth.get("auth_env_refs", []))
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
    attempt_index: int,
    failure_class: str,
    recovery_suggestion: str,
    gate_record_ids: list[str],
) -> dict[str, Any]:
    packet_id = f"failure-packet-{node.stage.lower()}-{node.output_artifact_type.lower()}-attempt-{attempt_index}"
    packet = {
        "packet_id": packet_id,
        "stage": node.stage,
        "node_id": node.node_id,
        "attempt_index": attempt_index,
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


def _mark_latest_stage_failure_packet_terminal(
    context: PipelineContext,
    node: PipelineNode,
    *,
    attempt_index: int,
    terminal: bool,
) -> None:
    if not context.repair_failure_packets:
        return
    packet = context.repair_failure_packets[-1]
    if packet.get("stage") != node.stage or packet.get("attempt_index") != attempt_index:
        return
    packet["terminal"] = terminal
    context.store.put_trace(packet["packet_id"], packet)


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
        "previous_invocation_record_id": attempt_record.get("invocation_record_id", ""),
        "previous_agent_conversation_ref": attempt_record.get("agent_conversation_ref", ""),
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
            "contract_ref": "contract.json",
            "generated_file_kinds": sorted(GENERATED_PROJECT_FILE_KINDS),
            "required_interfaces": sorted(RUNTIME_ABI_INTERFACES),
            "path_rule": "Each generated_files[].path is relative to candidate_dir. Use source/app.py, not generated/source/app.py and not an absolute path.",
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
    for check in attempt_record.get("implementation_check_records", []):
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
    for check in record.get("implementation_check_records", []):
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
    for check in record.get("implementation_check_records", []):
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
        return (context.store.root / "build" / "agent-runs" / safe_run_id / safe_environment_id).resolve()
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
            "Read the task packet under input/. Use input/skills/agent-world-environment-codegen/SKILL.md, artifacts, schemas, brief, and acceptance checks as source of truth.\n"
            f"{repair_note}"
            "Write a free-form executable contract project under generated/ with contract.json, source/, state/, adapters/, scripts/, and spec/.\n"
            "Run the generated self-check declared in agent-output/candidate_manifest.json. If it fails, repair the generated project and rerun the check.\n"
            "Treat input/framework-replay-contract.json and input/failure-packet.json as tool-style observations from the framework check workflow.\n"
            "Write agent-output/candidate_manifest.json after the final passing candidate. The manifest must declare "
            "candidate_dir: generated, contract_ref: contract.json, generated_files objects with exact path/kind/sha256/source_refs values, "
            "self_check.command, and replay_commands. Use the schema files under input/schemas/.\n"
            "Generated self-check scripts must create their report directory before writing agent-output/local_check_report.json so the packaged runtime remains portable.\n"
            "Do not write outside generated/ and agent-output/. Do not import the agent_world framework package from generated code. "
            "The framework will perform the final build/check/replay gate after you exit.\n"
        )
    return (
        f"Implement the accepted {environment_id} package in this isolated workdir: {work_dir}. "
        "Generate a contract project under generated/ with contract.json, source/, state/, adapters/, scripts/, and spec/. "
        "Return a JSON candidate manifest with relative paths, sha256 hashes, source refs, self_check.command, and replay commands. "
        "Do not modify the repository or any path outside the isolated workdir.\n\n"
        f"{repair_note}"
        "If you are an LLM file codegen backend, return only JSON in this schema:\n"
        "{\"files\":[{\"path\":\"generated/contract.json\",\"content\":\"...\"}],\"evidence_refs\":[\"...\"]}.\n"
        "The backend will write the files and calculate sha256 values.\n\n"
        f"Accepted artifact context JSON:\n{_implementation_agent_context_json(context)}"
    )


def _implementation_agent_allowed_tools(runner_backend: bool) -> list[str]:
    if runner_backend:
        return [
            "read_workspace_packet",
            "write_generated_project_files",
            "run_local_checks",
            "repair_generated_project",
            "write_candidate_manifest",
        ]
    return ["write_generated_project_files"]


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
    schemas_dir = input_dir / "schemas"
    generated_dir = work_dir / "generated"
    output_dir = work_dir / "agent-output"
    for path in [artifacts_dir, skills_dir, schemas_dir, generated_dir, output_dir]:
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
    (input_dir / "implementation_contract.json").write_text(stable_json(_implementation_contract_packet(context)), encoding="utf-8")
    _write_schema_packet(schemas_dir)
    _write_skill_packet(skills_dir)
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
                "implementation_contract": "implementation_contract.json",
                "schemas": {
                    path.name: f"schemas/{path.name}"
                    for path in sorted(schemas_dir.glob("*.schema.json"))
                },
                "skills": {
                    "agent-world-environment-codegen": "skills/agent-world-environment-codegen/SKILL.md",
                },
            }
        ),
        encoding="utf-8",
    )
    (input_dir / "implementation-brief.md").write_text(_code_agent_implementation_brief(context), encoding="utf-8")
    (input_dir / "expected-project-layout.md").write_text(_code_agent_expected_project_layout(context), encoding="utf-8")
    (input_dir / "acceptance-checks.md").write_text(_code_agent_acceptance_checks(context), encoding="utf-8")
    if failure_packet:
        (input_dir / "failure-packet.json").write_text(stable_json(failure_packet), encoding="utf-8")
    if previous_attempt:
        (input_dir / "previous-attempt-record.json").write_text(stable_json(previous_attempt), encoding="utf-8")


def _implementation_contract_packet(context: PipelineContext) -> dict[str, Any]:
    request = context.artifact("ImplementationRequest")
    return {
        "schema_version": "agent-world.implementation-contract.v1",
        "environment_id": request["environment_id"],
        "candidate_dir": "generated",
        "required_layout": ["contract.json", "source/", "state/", "adapters/", "scripts/", "spec/"],
        "runtime_abi_version": "agent-world.runtime-abi.v1",
        "required_interfaces": sorted(RUNTIME_ABI_INTERFACES),
        "candidate_manifest_ref": "agent-output/candidate_manifest.json",
        "local_check_report_ref": "agent-output/local_check_report.json",
        "schema_refs": {
            "environment_project": "schemas/environment_project.schema.json",
            "runtime_abi": "schemas/runtime_abi.schema.json",
            "candidate_manifest": "schemas/candidate_manifest.schema.json",
            "trace_event": "schemas/trace_event.schema.json",
            "verification_result": "schemas/verification_result.schema.json",
        },
        "source_artifact_ids": list(request.get("source_artifact_ids", [])),
        "accepted_task_ids": list(request.get("accepted_task_ids", [])),
        "accepted_verifier_ids": list(request.get("accepted_verifier_ids", [])),
    }


def _write_schema_packet(schemas_dir: Path) -> None:
    source_dir = Path(__file__).resolve().parent / "contracts"
    for schema_path in sorted(source_dir.glob("*.schema.json")):
        shutil.copy2(schema_path, schemas_dir / schema_path.name)


def _write_skill_packet(skills_dir: Path) -> None:
    source_dir = Path.cwd() / ".agents" / "skills" / "agent-world-environment-codegen"
    target_dir = skills_dir / "agent-world-environment-codegen"
    if target_dir.exists():
        shutil.rmtree(target_dir)
    if source_dir.is_dir():
        shutil.copytree(source_dir, target_dir)
        return
    target_dir.mkdir(parents=True, exist_ok=True)
    (target_dir / "SKILL.md").write_text(
        "# Agent World Environment Codegen\n\nGenerate a contract project under generated/ and satisfy the injected schemas.\n",
        encoding="utf-8",
    )


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
        "- required_layout: contract.json, source/, state/, adapters/, scripts/, spec/\n"
        f"- required_manifest_file_kinds: {stable_json(sorted(GENERATED_PROJECT_FILE_KINDS))}\n"
        f"- required_runtime_abi_interfaces: {', '.join(runtime_contract['required_interfaces'])}\n"
        "- required_trace_export: export_trace must return ordered events with tool_id and step_index\n"
        "- required_verifier_behavior: verify must return success=true for positive replay and success=false for missing/wrong evidence\n"
        f"{replay_note_text}"
        f"- required_tasks: {', '.join(task_ids)}\n"
        f"- required_verifiers: {', '.join(verifier_ids)}\n"
        "- required_negative_check: each task verifier must return success=false when required tool actions, state delta, or answer evidence are absent\n\n"
        "Use input/framework-replay-contract.json and input/implementation_contract.json as machine-readable execution contracts, and use input/artifacts/*.json as the source-grounded specification. "
        "The generated project must be self-contained and must not import the agent_world framework package. "
        "If you implement MCP, CLI, HTTP, database, or local services, keep those details behind the eight ABI interfaces declared in generated/contract.json.\n"
    )


def _code_agent_runtime_contract(context: PipelineContext | None) -> dict[str, Any]:
    fallback = {
        "required_interfaces": sorted(RUNTIME_ABI_INTERFACES),
        "logical_tool_ids": [],
    }
    if context is None or "SurfacePlan" not in context.artifacts:
        return fallback
    bindings = [
        binding
        for binding in context.artifact("SurfacePlan").get("bindings", [])
        if binding.get("surface") == "python" and binding.get("logical_tool_id")
    ]
    return {
        "required_interfaces": sorted(RUNTIME_ABI_INTERFACES),
        "logical_tool_ids": [str(binding.get("logical_tool_id")) for binding in bindings],
    }


def _code_agent_framework_replay_notes(context: PipelineContext) -> list[str]:
    notes: list[str] = []
    if "TaskSet" not in context.artifacts:
        return notes
    for task in context.artifact("TaskSet").get("tasks", []):
        calls = normalise_framework_replay_calls(task)
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
        "1. The generated self-check command declared in `agent-output/candidate_manifest.json` exits 0.\n"
        "2. The check prints a final JSON object with `success: true` or writes `agent-output/local_check_report.json` with success evidence.\n"
        "3. The self-check creates the report directory itself before writing the local check report, so it works after packaging.\n"
        f"4. It covers {task_text}.\n"
        "5. Each task has a positive verifier result with `success: true` and a negative verifier result with `success: false`.\n"
        "6. `agent-output/candidate_manifest.json` declares `candidate_dir: generated`, `contract_ref: contract.json`, and one `generated_files` object for every file under generated/.\n"
        "7. Each `generated_files[]` item declares exact package-relative `path`, allowed `kind`, lowercase 64-character `sha256`, and `source_refs`.\n"
        "8. The framework independent verifier can load `contract.json`, call describe/setup/reset/health/invoke/verify/export_trace/teardown, and observe ordered trace evidence for every required task.\n"
        "9. `input/framework-replay-contract.json` describes the framework-owned replay cases and check command; generated code must satisfy that contract.\n"
        "10. On a repair attempt, read `input/failure-packet.json` and address the listed framework_check_observation, failed task/verifier, and command output without changing the manifest path shape unless the failure is a manifest/path/hash failure.\n"
    )


def _code_agent_expected_project_layout(context: PipelineContext | None = None) -> str:
    kind_lines = "".join(f"- `{kind}`\n" for kind in sorted(GENERATED_PROJECT_FILE_KINDS))
    manifest_example = {
        "candidate_dir": "generated",
        "environment_id": "<environment id>",
        "implementation_id": "<stable implementation id>",
        "contract_ref": "contract.json",
        "generated_files": [
            {
                "path": "contract.json",
                "kind": "contract",
                "sha256": "<lowercase 64-character sha256>",
                "source_refs": ["<artifact id or source ref>"],
            },
            {
                "path": "adapters/runtime_adapter.py",
                "kind": "adapter",
                "sha256": "<lowercase 64-character sha256>",
                "source_refs": ["<artifact id or source ref>"],
            },
        ],
        "self_check": {"command": ["python", "scripts/self_check.py"], "report_ref": "../agent-output/local_check_report.json"},
        "replay_commands": [["framework-abi-replay", "<task_id>"]],
    }
    return (
        "# Expected Project Layout\n\n"
        "Write a complete executable project under `generated/`:\n\n"
        "- `contract.json`: static environment contract and ABI entrypoint map.\n"
        "- `source/`: free-form environment implementation.\n"
        "- `state/`: seed data, migrations, fixtures, or snapshots.\n"
        "- `adapters/`: Python ABI adapter functions or thin wrappers around MCP/CLI/HTTP/DB surfaces.\n"
        "- `scripts/`: generated self-check and optional setup helpers.\n"
        "- `spec/`: tool, task, verifier, and surface descriptors.\n\n"
        "Required runtime ABI interfaces in `contract.json`: describe, setup, reset, health, invoke, verify, export_trace, teardown.\n\n"
        "Allowed manifest file kinds:\n\n"
        f"{kind_lines}\n"
        "Candidate manifest schema example:\n\n"
        "```json\n"
        f"{json.dumps(manifest_example, indent=2, sort_keys=True)}\n"
        "```\n\n"
        "Write runner traces, `candidate_manifest.json`, and `local_check_report.json` under `agent-output/`; do not place runner-only files in `generated/`.\n"
        "`candidate_dir` is `generated`, so every `generated_files[].path` must be relative to that directory, such as `source/app.py`; do not use `generated/source/app.py` or absolute paths.\n"
    )


def _prepare_agent_work_dir(work_dir: Path) -> None:
    work_dir.mkdir(parents=True, exist_ok=True)
    for child in work_dir.iterdir():
        if child.is_dir() and not child.is_symlink():
            shutil.rmtree(child)
        else:
            child.unlink()


def _store_node_invocations(
    context: PipelineContext,
    execution: NodeAttemptResult,
    *,
    output_artifact_ids: list[str],
    evidence_refs: list[str],
) -> list[dict[str, Any]]:
    records = _prepare_node_invocations(execution, output_artifact_ids=output_artifact_ids, evidence_refs=evidence_refs)
    _store_prepared_node_invocations(context, records)
    return records


def _prepare_node_invocations(
    execution: NodeAttemptResult,
    *,
    output_artifact_ids: list[str],
    evidence_refs: list[str],
) -> list[dict[str, Any]]:
    return [
        _with_invocation_outputs(invocation, output_artifact_ids=output_artifact_ids, evidence_refs=evidence_refs)
        for invocation in execution.invocation_records
    ]


def _store_prepared_node_invocations(context: PipelineContext, records: list[dict[str, Any]]) -> None:
    if records:
        context.invocation_records.extend(records)
        context.store.put_invocation_records(records)


def _with_invocation_outputs(invocation: dict[str, Any], *, output_artifact_ids: list[str], evidence_refs: list[str]) -> dict[str, Any]:
    updated = dict(invocation)
    updated["output_artifact_ids"] = sorted(set(updated.get("output_artifact_ids", [])) | set(output_artifact_ids))
    updated["evidence_refs"] = sorted(set(updated.get("evidence_refs", [])) | set(evidence_refs))
    updated["hash"] = ""
    updated["hash"] = artifact_hash(updated)
    validate_artifact("InvocationRecord", updated)
    return updated


def _artifact_id_from_fields(fields: dict[str, Any]) -> str | None:
    for key in ["domain_plan_id", "strategy_selection_id", "request_id", "package_plan_id", "replay_plan_id", "consumer_index_id", "release_id", "backend_id", "report_id"]:
        if fields.get(key):
            return fields[key]
    return None
