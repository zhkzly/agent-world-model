from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from agent_world.agents import (
    AgentRequest,
    default_agent_backend_registry,
    invoke_agent,
    load_agent_backend_config_from_env,
)
from agent_world.artifacts import make_artifact, stable_json
from agent_world.gates import STAGE_GATES, evaluate_gate, evaluate_stage_gates
from agent_world.package import PackageAssembler, PackageAssemblyResult
from agent_world.package import file_sha256
from agent_world.fixtures.support_desk_lite import create_seed_db
from agent_world.review import independent_review


SOURCE_DOC_REF = "docs/agent-world-environment-generation.zh.md"
REVIEW_OUTPUT_INSTRUCTION = (
    "Return only a JSON object with keys alignment_status, reviewed_artifact_ids, "
    "drift_findings, required_fixes, waived_risks, and reviewer_note. "
    "alignment_status must be pass, fail, or needs_human. "
    "reviewed_artifact_ids must include the current artifact id. "
    "The current stage gate checklist is evaluated after this review record is produced; "
    "do not fail an artifact merely because current-stage GateRecord artifacts are not already embedded. "
    "Only require upstream gate records when the artifact contract explicitly says it records upstream gates. "
    "drift_findings must be an empty array or objects with requirement_ref, finding, severity, and evidence. "
    "waived_risks must be an empty array or objects with risk, reason, and approver. "
    "Use empty arrays when there are no drift findings, required fixes, or waived risks. "
    "Do not wrap the JSON in Markdown."
)


@dataclass(frozen=True)
class WorkflowResult:
    package: PackageAssemblyResult
    artifacts: dict[str, dict[str, Any]]
    gate_records: list[dict[str, Any]]
    review_records: list[dict[str, Any]]
    agent_invocations: list[dict[str, Any]]


class FirstSliceWorkflow:
    """Deterministic S0-S11 workflow for the frozen first vertical slice."""

    def __init__(self, registry=None) -> None:
        self.registry = registry or default_agent_backend_registry()
        self.artifacts: dict[str, dict[str, Any]] = {}
        self.gate_records: list[dict[str, Any]] = []
        self.review_records: list[dict[str, Any]] = []
        self.agent_invocations: list[dict[str, Any]] = []

    def run(
        self,
        *,
        output_dir: Path,
        raw_request: str = "Generate the support-desk-lite first slice.",
        env: dict[str, str] | None = None,
    ) -> WorkflowResult:
        self.artifacts = {"AgentBackendConfig": load_agent_backend_config_from_env(env)}
        self.gate_records = []
        self.review_records = []
        self.agent_invocations = []

        need = self._stage("S0", "NeedSpec", self._need_spec(raw_request))
        self._review_support_artifact(
            "S0",
            "AgentBackendConfig",
            self.artifacts["AgentBackendConfig"],
            inputs=[need["id"]],
            gate_ids=["G0", "G13"],
        )
        source_index = self._stage("S1", "SourceEvidenceIndex", self._source_evidence(), purpose="search", inputs=[need["id"]])
        knowledge = self._stage("S2", "KnowledgePack", self._knowledge_pack(), purpose="extract", inputs=[source_index["id"]])
        env_spec = self._stage("S3", "EnvironmentSpec", self._environment_spec(), purpose="synthesize", inputs=[need["id"], knowledge["id"]])
        tool_graph = self._stage("S4", "LogicalToolGraph", self._tool_graph(), purpose="synthesize", inputs=[env_spec["id"], knowledge["id"]])
        task_set = self._stage("S5", "TaskSet", self._task_set(), purpose="synthesize", inputs=[need["id"], tool_graph["id"]])
        surface_plan = self._stage("S6", "SurfacePlan", self._surface_plan(), purpose="synthesize", inputs=[tool_graph["id"], env_spec["id"]])
        verifier_plan = self._stage("S7", "VerifierPlan", self._verifier_plan(), purpose="synthesize", inputs=[task_set["id"], env_spec["id"]])
        feasibility = self._stage("S8", "FeasibilityReport", self._feasibility_report(), inputs=[artifact["id"] for artifact in self._primary_artifacts()])
        implementation_request = self._stage(
            "S9",
            "ImplementationRequest",
            self._implementation_request(),
            purpose="draft_implementation_request",
            inputs=[feasibility["id"], env_spec["id"], task_set["id"], verifier_plan["id"]],
        )
        replay_plan = self._support_artifact(
            "ReplayPlan",
            "S10",
            self._replay_plan(),
            inputs=[implementation_request["id"], task_set["id"], surface_plan["id"], verifier_plan["id"]],
        )
        self.artifacts["ReplayPlan"] = replay_plan
        self._review_support_artifact(
            "S10",
            "ReplayPlan",
            replay_plan,
            inputs=[implementation_request["id"], task_set["id"], surface_plan["id"], verifier_plan["id"]],
            gate_ids=["G0", "G13"],
        )
        consumer_index = self._support_artifact(
            "ConsumerIndex",
            "S10",
            self._consumer_index(),
            inputs=[implementation_request["id"], replay_plan["id"]],
        )
        self.artifacts["ConsumerIndex"] = consumer_index
        self._review_support_artifact(
            "S10",
            "ConsumerIndex",
            consumer_index,
            inputs=[implementation_request["id"], replay_plan["id"]],
            gate_ids=["G0", "G13"],
        )
        package_plan = self._stage(
            "S10",
            "EnvironmentPackagePlan",
            self._package_plan(replay_plan),
            inputs=[implementation_request["id"], replay_plan["id"], consumer_index["id"]],
        )
        release_manifest = self._stage(
            "S11",
            "ReleaseManifest",
            self._release_manifest(package_plan, consumer_index),
            inputs=[package_plan["id"], consumer_index["id"]],
        )

        self.artifacts["ReleaseManifest"] = release_manifest
        package = PackageAssembler().assemble(
            output_dir=output_dir,
            artifacts=self.artifacts,
            gate_records=self.gate_records,
            review_records=self.review_records,
            agent_invocations=self.agent_invocations,
        )
        return WorkflowResult(package, dict(self.artifacts), list(self.gate_records), list(self.review_records), list(self.agent_invocations))

    def _stage(
        self,
        stage: str,
        artifact_type: str,
        fields: dict[str, Any],
        *,
        purpose: str | None = None,
        inputs: list[str] | None = None,
    ) -> dict[str, Any]:
        inputs = inputs or []
        invocations = []
        if purpose:
            invocations.append(self._invoke(stage, purpose, inputs))
        artifact = make_artifact(
            artifact_type,
            source_stage=stage,
            producer="first-slice-workflow",
            fields=fields,
            artifact_id=_artifact_id_from_fields(fields),
            inputs=inputs + [record["id"] for record in invocations],
        )
        review_inputs = [artifact["id"]] + inputs + [record["id"] for record in invocations] + list(STAGE_GATES[stage])
        review_invocation, review_result = self._invoke(
            stage,
            "review",
            review_inputs,
            instruction=(
                f"Review {artifact_type} for {stage} against {SOURCE_DOC_REF}. "
                f"Artifact fields: {sorted(artifact.keys())}. "
                f"Current artifact id: {artifact['id']}. "
                f"Artifact JSON: {_artifact_review_json(artifact)}. "
                f"Upstream artifact IDs: {inputs}. Gate checklist: {STAGE_GATES[stage]}. "
                f"{REVIEW_OUTPUT_INSTRUCTION}"
            ),
            return_result=True,
        )
        invocations.append(review_invocation)
        review = independent_review(
            stage=stage,
            artifact=artifact,
            need_spec=self.artifacts.get("NeedSpec") or (artifact if artifact_type == "NeedSpec" else None),
            upstream_artifacts=[self.artifacts[name] for name in self.artifacts if name not in {"AgentBackendConfig"}],
            gate_checklist=list(STAGE_GATES[stage]),
            source_of_truth_refs=[SOURCE_DOC_REF],
            reviewer_ref="independent-reviewer",
            invocation_ref=review_invocation["id"],
            reviewer_output=review_result.text,
        )
        gate_records = evaluate_stage_gates(
            stage=stage,
            artifact_type=artifact_type,
            artifact=artifact,
            context=self.artifacts | {artifact_type: artifact, "__gate_records__": {record["id"]: record for record in self.gate_records}},
            review=review,
            invocations=invocations,
        )
        failures = [record for record in gate_records if record["status"] != "pass"]
        self.agent_invocations.extend(invocations)
        self.review_records.append(review)
        self.gate_records.extend(gate_records)
        self.artifacts[artifact_type] = artifact
        if failures:
            details = "; ".join(f"{record['gate_id']}={record['recovery_suggestion']}" for record in failures)
            raise RuntimeError(f"{stage} failed gates: {details}")
        return artifact

    def _support_artifact(self, artifact_type: str, stage: str, fields: dict[str, Any], *, inputs: list[str] | None = None) -> dict[str, Any]:
        return make_artifact(
            artifact_type,
            source_stage=stage,
            producer="first-slice-workflow",
            fields=fields,
            artifact_id=_artifact_id_from_fields(fields),
            inputs=inputs or [artifact["id"] for artifact in self._primary_artifacts()],
        )

    def _review_support_artifact(
        self,
        stage: str,
        artifact_type: str,
        artifact: dict[str, Any],
        *,
        inputs: list[str],
        gate_ids: list[str],
    ) -> None:
        review_inputs = [artifact["id"]] + inputs + list(gate_ids)
        review_invocation, review_result = self._invoke(
            stage,
            "review",
            review_inputs,
            instruction=(
                f"Review support artifact {artifact_type} for {stage} against {SOURCE_DOC_REF}. "
                f"Current artifact id: {artifact['id']}. Artifact JSON: {_artifact_review_json(artifact)}. "
                f"Upstream artifact IDs: {inputs}. Gate checklist: {gate_ids}. "
                f"{REVIEW_OUTPUT_INSTRUCTION}"
            ),
            return_result=True,
        )
        upstream_artifacts = self._artifacts_for_ids(inputs)
        review = independent_review(
            stage=stage,
            artifact=artifact,
            need_spec=self.artifacts.get("NeedSpec"),
            upstream_artifacts=upstream_artifacts,
            gate_checklist=list(gate_ids),
            source_of_truth_refs=[SOURCE_DOC_REF],
            reviewer_ref="independent-reviewer",
            invocation_ref=review_invocation["id"],
            reviewer_output=review_result.text,
        )
        gate_records = [
            evaluate_gate(
                gate_id,
                stage,
                artifact_type,
                artifact,
                self.artifacts | {artifact_type: artifact, "__gate_records__": {record["id"]: record for record in self.gate_records}},
                review,
                [review_invocation],
            )
            for gate_id in list(gate_ids) + ["G14"]
        ]
        failures = [record for record in gate_records if record["status"] != "pass"]
        self.agent_invocations.append(review_invocation)
        self.review_records.append(review)
        self.gate_records.extend(gate_records)
        if failures:
            details = "; ".join(f"{record['gate_id']}={record['recovery_suggestion']}" for record in failures)
            raise RuntimeError(f"{stage} support artifact {artifact_type} failed gates: {details}")

    def _invoke(
        self,
        stage: str,
        purpose: str,
        inputs: list[str],
        instruction: str | None = None,
        *,
        return_result: bool = False,
    ):
        request = AgentRequest(
            stage=stage,
            node_purpose=purpose,
            instruction=instruction or f"{purpose} for {stage} under {SOURCE_DOC_REF}",
            input_artifact_ids=inputs,
            invocation_id=_invocation_id(stage, purpose, inputs),
            permissions=self._request_permissions(),
            instruction_ref=f"{SOURCE_DOC_REF}#{stage}-{purpose}",
        )
        record, result = invoke_agent(self.registry, request, self.artifacts["AgentBackendConfig"])
        return (record, result) if return_result else record

    def _request_permissions(self) -> dict[str, Any]:
        config_permissions = self.artifacts["AgentBackendConfig"].get("permissions", {})
        return {
            "network": bool(config_permissions.get("network")),
            "filesystem": config_permissions.get("filesystem", "artifact_context"),
            "auth": bool(config_permissions.get("auth")),
            "sandbox": bool(config_permissions.get("sandbox")),
        }

    def _artifacts_for_ids(self, artifact_ids: list[str]) -> list[dict[str, Any]]:
        wanted = set(artifact_ids)
        return [artifact for artifact in self.artifacts.values() if artifact.get("id") in wanted]

    def _primary_artifacts(self) -> list[dict[str, Any]]:
        names = [
            "NeedSpec",
            "SourceEvidenceIndex",
            "KnowledgePack",
            "EnvironmentSpec",
            "LogicalToolGraph",
            "TaskSet",
            "SurfacePlan",
            "VerifierPlan",
            "FeasibilityReport",
            "ImplementationRequest",
            "EnvironmentPackagePlan",
            "ReleaseManifest",
        ]
        return [self.artifacts[name] for name in names if name in self.artifacts]

    def _need_spec(self, raw_request: str) -> dict[str, Any]:
        return {
            "goal": raw_request,
            "target_capabilities": ["stateful tool use", "source-grounded environment generation", "deterministic verification"],
            "domain_seed": "support-desk-lite",
            "expected_agent_behavior": "Use user-facing support requests to inspect and update ticket state through logical tools.",
            "constraints": {
                "network": "not_required",
                "auth": "not_required",
                "license": "local_fixture",
                "safety": "local_state_only",
                "local_execution": True,
                "mocking_allowed": True,
            },
            "preferred_surfaces": ["python", "cli", "http", "mcp"],
            "out_of_scope": [
                "training integration",
                "rollout",
                "reward export",
                "AWM reproduction",
                "MCP-only architecture",
                "CLI-only architecture",
            ],
            "human_confirmation_required": [],
        }

    def _source_evidence(self) -> dict[str, Any]:
        return {
            "sources": [
                {
                    "source_id": "source-support-desk-lite-prd",
                    "kind": "manual_note",
                    "uri_or_path": "fixture://support-desk-lite/prd",
                    "version_or_hash": "support-desk-lite-v1",
                    "retrieved_at": "2026-06-27T00:00:00Z",
                    "license": "local_fixture",
                    "auth_requirement": "none",
                    "network_requirement": "none",
                    "security_note": "Local synthetic support-desk fixture; no external customer data.",
                }
            ],
            "extractable_objects": [
                {"source_id": "source-support-desk-lite-prd", "object_kind": "state_entity", "name": "ticket", "evidence_refs": ["fixture://support-desk-lite/prd#ticket"]},
                {"source_id": "source-support-desk-lite-prd", "object_kind": "operation", "name": "assign ticket", "evidence_refs": ["fixture://support-desk-lite/prd#assignment"]},
            ],
            "mock_boundaries": ["no network", "no real customer data", "local SQLite only"],
            "open_questions": [],
            "rejected_sources": [
                {"source_id": "awm-1k", "reason": "background only; not needed for the first non-AWM fixture"}
            ],
        }

    def _knowledge_pack(self) -> dict[str, Any]:
        source = ["source-support-desk-lite-prd"]
        return {
            "state_objects": [
                {"object_id": "customer", "name": "customer", "fields": ["id", "name", "tier", "region", "email"], "relations": [], "source_refs": source},
                {"object_id": "ticket", "name": "ticket", "fields": ["id", "customer_id", "status", "priority", "subject", "description"], "relations": ["customer"], "source_refs": source},
                {"object_id": "ticket_note", "name": "ticket note", "fields": ["ticket_id", "visibility", "body"], "relations": ["ticket"], "source_refs": source},
                {"object_id": "assignment", "name": "assignment", "fields": ["ticket_id", "assignee", "queue"], "relations": ["ticket"], "source_refs": source},
                {"object_id": "audit_event", "name": "audit event", "fields": ["ticket_id", "event_type", "field", "old_value", "new_value"], "relations": ["ticket"], "source_refs": source},
            ],
            "operations": [
                {"operation_id": tool_id, "name": tool_id.replace("_", " "), "inputs": [], "outputs": [], "side_effects": side_effects, "source_refs": source}
                for tool_id, side_effects in [
                    ("search_tickets", []),
                    ("get_ticket", []),
                    ("add_ticket_note", ["ticket_note", "audit_event"]),
                    ("update_ticket_priority", ["ticket", "audit_event"]),
                    ("assign_ticket", ["assignment", "audit_event"]),
                    ("resolve_ticket", ["ticket", "ticket_note", "audit_event"]),
                ]
            ],
            "business_rules": [
                {"rule_id": "audit-on-write", "description": "Every state-changing tool writes an audit_event.", "source_refs": source, "confidence": "high"},
                {"rule_id": "python-required", "description": "The first runnable surface is Python callable.", "source_refs": source, "confidence": "high"},
            ],
            "verifiable_fields": ["ticket.status", "ticket.priority", "assignment.queue", "ticket_note.body", "audit_event.event_type"],
            "uncertainties": [],
        }

    def _environment_spec(self) -> dict[str, Any]:
        logical_tools = [
            {"tool_id": tool_id, "name": name}
            for tool_id, name in [
                ("search_tickets", "Search tickets"),
                ("get_ticket", "Get ticket"),
                ("add_ticket_note", "Add ticket note"),
                ("update_ticket_priority", "Update ticket priority"),
                ("assign_ticket", "Assign ticket"),
                ("resolve_ticket", "Resolve ticket"),
            ]
        ]
        return {
            "environment_id": "support-desk-lite",
            "domain": "support desk ticket handling",
            "state_backend": {
                "kind": "sqlite",
                "reset_strategy": "copy versioned seed database into isolated run directory",
                "isolation_strategy": "one SQLite file per run directory",
                "seed_fixture_refs": ["fixtures/seed/support-desk-lite.sqlite"],
            },
            "state_entities": ["customer", "ticket", "ticket_note", "assignment", "audit_event"],
            "logical_tools": logical_tools,
            "permissions": {"network": False, "filesystem": "package_dir_only", "auth": False},
            "safety_boundaries": ["synthetic fixture only", "no external services", "no generic shell execution surface"],
            "mock_policy": {"external_services": "not_required", "data": "synthetic"},
            "release_surfaces_allowed": ["python", "cli", "http", "mcp"],
            "observability": {"logs": True, "traces": True, "state_snapshots": ["before", "after", "on_failure"]},
        }

    def _tool_graph(self) -> dict[str, Any]:
        tools = [
            ("search_tickets", [], ["status", "customer_tier", "keyword", "queue"], ["ticket", "customer", "assignment"], [], "safe"),
            ("get_ticket", ["ticket_id"], [], ["ticket", "customer", "assignment", "ticket_note", "audit_event"], [], "safe"),
            ("add_ticket_note", ["ticket_id", "visibility", "body"], [], ["ticket"], ["ticket_note", "audit_event"], "non_idempotent"),
            ("update_ticket_priority", ["ticket_id", "priority", "note"], [], ["ticket"], ["ticket", "audit_event"], "idempotent_by_target_value"),
            ("assign_ticket", ["ticket_id", "queue", "assignee", "note"], [], ["assignment"], ["assignment", "audit_event"], "idempotent_by_target_value"),
            ("resolve_ticket", ["ticket_id", "resolution_note"], [], ["ticket"], ["ticket", "ticket_note", "audit_event"], "idempotent_by_status"),
        ]
        return {
            "tools": [
                {
                    "tool_id": tool_id,
                    "name": tool_id.replace("_", " "),
                    "input_schema": {"required": required_inputs, "optional": optional_inputs},
                    "output_schema": {"type": "object"},
                    "reads": reads,
                    "writes": writes,
                    "side_effects": writes,
                    "errors": ["unknown_ticket", "invalid_argument"],
                    "idempotency": idempotency,
                }
                for tool_id, required_inputs, optional_inputs, reads, writes, idempotency in tools
            ],
            "edges": [
                {"from_tool_id": "search_tickets", "to_tool_id": "get_ticket", "dependency_type": "strong", "reason": "search yields ticket id for detail inspection"},
                {"from_tool_id": "get_ticket", "to_tool_id": "resolve_ticket", "dependency_type": "strong", "reason": "details determine whether resolution is appropriate"},
                {"from_tool_id": "get_ticket", "to_tool_id": "add_ticket_note", "dependency_type": "strong", "reason": "details confirm the correct ticket before adding notes"},
                {"from_tool_id": "get_ticket", "to_tool_id": "update_ticket_priority", "dependency_type": "weak", "reason": "details may justify escalation"},
                {"from_tool_id": "search_tickets", "to_tool_id": "assign_ticket", "dependency_type": "weak", "reason": "search can identify queue candidates"},
            ],
            "parameters": [
                {"name": "ticket_id", "classification": "internal", "source": "search_tickets/get_ticket", "validation": "existing ticket"},
                {"name": "visibility", "classification": "external", "source": "task requirement or fixed verifier expectation", "validation": "internal or customer"},
                {"name": "body", "classification": "external", "source": "agent synthesis from user request", "validation": "non-empty string"},
                {"name": "queue", "classification": "external", "source": "user request", "validation": "non-empty string"},
                {"name": "assignee", "classification": "external", "source": "user request", "validation": "non-empty string"},
                {"name": "priority", "classification": "external", "source": "user request", "validation": "low, medium, high, or urgent"},
                {"name": "note", "classification": "external", "source": "agent synthesis", "validation": "non-empty string"},
                {"name": "resolution_note", "classification": "external", "source": "agent synthesis from user request", "validation": "non-empty string"},
                {"name": "keyword", "classification": "optional", "source": "user request", "validation": "string"},
                {"name": "status", "classification": "optional", "source": "user request or task fixture", "validation": "open, pending, resolved, or closed"},
                {"name": "customer_tier", "classification": "optional", "source": "user request or fixture metadata", "validation": "known customer tier"},
            ],
            "forbidden_direct_access": ["sqlite file path", "table names in user request", "verifier ids"],
        }

    def _task_set(self) -> dict[str, Any]:
        tasks = [
            {
                "task_id": "task-1",
                "natural_request": "Find the VIP customer's open refund case and leave an internal note explaining the refund follow-up.",
                "target_capability": "stateful note creation",
                "initial_state_refs": ["fixtures/seed/support-desk-lite.sqlite#T-100"],
                "expected_state_delta": {"ticket_note": "internal note added to T-100", "audit_event": "note_added"},
                "expected_answer": "",
                "allowed_logical_tool_ids": ["search_tickets", "get_ticket", "add_ticket_note"],
                "forbidden_leakage": ["table names", "backend ids", "verifier ids"],
                "dependency_path": ["search_tickets", "get_ticket", "add_ticket_note"],
                "difficulty": {"level": "easy", "requires_state_change": True},
                "verifier_refs": ["verifier-task-1"],
            },
            {
                "task_id": "task-2",
                "natural_request": "Move the idle high-priority login outage case to enterprise support and assign it to iris.",
                "target_capability": "assignment update",
                "initial_state_refs": ["fixtures/seed/support-desk-lite.sqlite#T-101"],
                "expected_state_delta": {"assignment": "T-101 queue=enterprise-support assignee=iris", "audit_event": "assignment_updated"},
                "expected_answer": "",
                "allowed_logical_tool_ids": ["search_tickets", "assign_ticket"],
                "forbidden_leakage": ["table names", "backend ids", "verifier ids"],
                "dependency_path": ["search_tickets", "assign_ticket"],
                "difficulty": {"level": "medium", "requires_state_change": True},
                "verifier_refs": ["verifier-task-2"],
            },
            {
                "task_id": "task-3",
                "natural_request": "The VIP refund issue looks under-prioritized. Raise it to high priority and record why.",
                "target_capability": "priority escalation",
                "initial_state_refs": ["fixtures/seed/support-desk-lite.sqlite#T-100"],
                "expected_state_delta": {"ticket": "T-100 priority=high", "audit_event": "priority_updated"},
                "expected_answer": "",
                "allowed_logical_tool_ids": ["search_tickets", "get_ticket", "update_ticket_priority"],
                "forbidden_leakage": ["table names", "backend ids", "verifier ids"],
                "dependency_path": ["search_tickets", "get_ticket", "update_ticket_priority"],
                "difficulty": {"level": "medium", "requires_state_change": True},
                "verifier_refs": ["verifier-task-3"],
            },
            {
                "task_id": "task-4",
                "natural_request": "For Acme Corp, report how many open cases they have and the highest current priority.",
                "target_capability": "read-only aggregation",
                "initial_state_refs": ["fixtures/seed/support-desk-lite.sqlite#cust-vip"],
                "expected_state_delta": {},
                "expected_answer": {"customer_id": "cust-vip", "open_ticket_count": 2, "highest_priority": "medium"},
                "allowed_logical_tool_ids": ["search_tickets", "get_ticket"],
                "forbidden_leakage": ["table names", "backend ids", "verifier ids"],
                "dependency_path": ["search_tickets"],
                "difficulty": {"level": "easy", "requires_state_change": False},
                "verifier_refs": ["verifier-task-4"],
            },
            {
                "task_id": "task-5",
                "natural_request": "Inspect the duplicate refund confirmation case, then close it with a customer-visible resolution note.",
                "target_capability": "strong dependency state update",
                "initial_state_refs": ["fixtures/seed/support-desk-lite.sqlite#T-102"],
                "expected_state_delta": {"ticket": "T-102 status=resolved", "ticket_note": "customer-visible resolution", "audit_event": "ticket_resolved"},
                "expected_answer": "",
                "allowed_logical_tool_ids": ["search_tickets", "get_ticket", "resolve_ticket"],
                "forbidden_leakage": ["table names", "backend ids", "verifier ids"],
                "dependency_path": ["search_tickets", "get_ticket", "resolve_ticket"],
                "difficulty": {"level": "hard", "requires_state_change": True, "strong_dependency_path": True},
                "verifier_refs": ["verifier-task-5"],
            },
        ]
        return {
            "tasks": tasks,
            "coverage": {
                "tool_ids": ["search_tickets", "get_ticket", "add_ticket_note", "update_ticket_priority", "assign_ticket", "resolve_ticket"],
                "capabilities": ["read", "write", "audit", "strong_dependency"],
                "state_entities": ["ticket", "ticket_note", "assignment", "audit_event"],
            },
            "rejected_candidates": [],
        }

    def _surface_plan(self) -> dict[str, Any]:
        tools = ["search_tickets", "get_ticket", "add_ticket_note", "update_ticket_priority", "assign_ticket", "resolve_ticket"]
        return {
            "bindings": [
                {
                    "binding_id": f"python-{tool_id}",
                    "logical_tool_id": tool_id,
                    "surface": "python",
                    "exposure_name": f"SupportDeskLite.{tool_id}",
                    "input_mapping": "same as logical tool schema",
                    "output_mapping": "dict/list JSON-compatible Python objects",
                    "error_mapping": "Python exception to logical error",
                    "auth_context": "none",
                    "state_scope": "isolated SQLite file per run",
                }
                for tool_id in tools
            ],
            "surface_status": {"python": "required_for_first_slice", "cli": "deferred", "http": "deferred", "mcp": "deferred"},
            "compatibility_notes": ["CLI/HTTP/MCP remain planned surfaces; Python is the only required runnable surface."],
        }

    def _verifier_plan(self) -> dict[str, Any]:
        return {
            "verifiers": [
                self._verifier(task_id, kind)
                for task_id, kind in [
                    ("task-1", "state_diff"),
                    ("task-2", "state_diff"),
                    ("task-3", "state_diff"),
                    ("task-4", "state_query"),
                    ("task-5", "state_diff"),
                ]
            ],
            "llm_judges": [],
        }

    def _verifier(self, task_id: str, kind: str) -> dict[str, Any]:
        return {
            "verifier_id": f"verifier-{task_id}",
            "task_id": task_id,
            "kind": kind,
            "inputs": ["initial_db_path", "final_db_path", "final_answer", "surface_trace_path", "expected_dependency_path", "trace_call_group"],
            "checks": ["dependency path trace assertion", "state snapshot assertion", "target changed", "non-target preserved", "audit evidence"],
            "success_criteria": f"support_desk_lite.verify_task_completion({task_id!r}) returns success=true only when state checks and dependency trace checks pass",
            "failure_criteria": "Any deterministic check returns false.",
            "positive_examples": [f"{task_id}: expected mutation or answer present"],
            "negative_examples": [f"{task_id}: missing target state, audit, or declared dependency path trace"],
            "evidence_refs": ["agent_world/fixtures/support_desk_lite.py"],
            "replay_inputs": ["seed fixture", "initial snapshot", "final snapshot", "surface trace", "trace call group", "declared dependency path", "agent final answer"],
            "assertions": [
                {"assertion_id": f"assert-{task_id}", "target": "verify_task_completion.success", "operator": "equals", "expected": True, "tolerance": 0, "source_ref": "support_desk_lite.py"},
                {"assertion_id": f"assert-{task_id}-path", "target": "dependency_path_trace_matches", "operator": "equals", "expected": True, "tolerance": 0, "source_ref": "support_desk_lite.py"},
            ],
            "allowed_side_effects": [],
            "timeout_ms": 1000,
            "isolation_requirement": "read-only verifier over copied SQLite files",
            "failure_diagnostics": ["return structured failed checks"],
        }

    def _feasibility_report(self) -> dict[str, Any]:
        return {
            "status": "pass",
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
                for record in self.gate_records
            ],
            "minimum_viable_surface": "python",
            "minimum_viable_task_ids": [task["task_id"] for task in self.artifacts["TaskSet"]["tasks"]],
            "minimum_viable_verifier_ids": [verifier["verifier_id"] for verifier in self.artifacts["VerifierPlan"]["verifiers"]],
            "implementation_blockers": [],
        }

    def _implementation_request(self) -> dict[str, Any]:
        return {
            "request_id": "impl-support-desk-lite-first-slice",
            "environment_id": "support-desk-lite",
            "source_artifact_ids": [self.artifacts["SourceEvidenceIndex"]["id"], self.artifacts["KnowledgePack"]["id"]],
            "accepted_task_ids": [task["task_id"] for task in self.artifacts["TaskSet"]["tasks"]],
            "accepted_verifier_ids": [verifier["verifier_id"] for verifier in self.artifacts["VerifierPlan"]["verifiers"]],
            "required_surface_ids": [binding["binding_id"] for binding in self.artifacts["SurfacePlan"]["bindings"] if binding["surface"] == "python"],
            "package_layout_ref": "envpkg/",
            "implementation_scope": ["artifact schema", "static validators", "S0-S11 workflow", "Python callable fixture", "package assembly"],
            "non_goals": ["training integration", "rollout", "reward export", "AWM reproduction", "MCP-only architecture", "generic shell environment surface"],
            "tdd_requirements": ["schema validation", "gate records", "independent review records", "support-desk fixture verifier"],
            "launch_check_replay_commands": ["python -m pytest tests/agent_world"],
            "review_record_refs": [record["id"] for record in self.review_records],
        }

    def _replay_plan(self) -> dict[str, Any]:
        with TemporaryDirectory() as td:
            seed_hash = file_sha256(create_seed_db(Path(td) / "support-desk-lite.sqlite"))
        return {
            "replay_plan_id": "replay-support-desk-lite",
            "environment_id": "support-desk-lite",
            "seed_fixture_refs": ["fixtures/seed/support-desk-lite.sqlite"],
            "task_ids": [task["task_id"] for task in self.artifacts["TaskSet"]["tasks"]],
            "surface_binding_ids": [binding["binding_id"] for binding in self.artifacts["SurfacePlan"]["bindings"]],
            "reset_steps": ["copy seed SQLite into isolated run directory"],
            "execution_trace_inputs": ["task_id", "call_group", "surface_calls", "initial_snapshot_hash", "final_snapshot_hash", "final_answer", "verifier_result"],
            "state_snapshot_points": {
                "before": "initial SQLite copy; hash recorded as initial_snapshot_hash",
                "after": "post-run SQLite file; hash recorded as final_snapshot_hash",
                "on_failure": "failed run directory; hash recorded when failure snapshot is emitted",
            },
            "snapshot_hashes": {"seed": seed_hash, "initial_snapshot": seed_hash},
            "runtime_snapshot_hash_refs": {
                "final_snapshot_hash": "checks/surface-traces.jsonl#final_snapshot_hash",
                "failure_snapshot_hash": "checks/surface-traces.jsonl#failure_snapshot_hash_when_present",
            },
            "replay_commands": [
                f"python -m agent_world.replay --package . --task {task['task_id']}"
                for task in self.artifacts["TaskSet"]["tasks"]
            ],
            "execution_trace_schema": {
                "task_id": "string",
                "call_group": "string",
                "surface_calls": "array",
                "initial_snapshot_hash": "string",
                "final_snapshot_hash": "string",
                "final_answer": "object|string|null",
                "verifier_result": "object",
            },
            "verifier_ids": [verifier["verifier_id"] for verifier in self.artifacts["VerifierPlan"]["verifiers"]],
            "expected_gate_ids": sorted({record["gate_id"] for record in self.gate_records}),
            "determinism_notes": "Synthetic SQLite fixture, fixed timestamps, no network.",
            "known_nondeterminism": [],
        }

    def _package_plan(self, replay_plan: dict[str, Any]) -> dict[str, Any]:
        included_ids = (
            [artifact["id"] for artifact in self.artifacts.values()]
            + [replay_plan["id"]]
            + ["package-support-desk-lite", "consumer-support-desk-lite", "release-support-desk-lite"]
            + [record["id"] for record in self.review_records]
            + [record["id"] for record in self.gate_records]
        )
        return {
            "package_plan_id": "package-support-desk-lite",
            "environment_id": "support-desk-lite",
            "layout": "envpkg/",
            "included_artifact_ids": included_ids,
            "fixture_refs": ["fixtures/seed/support-desk-lite.sqlite"],
            "static_check_refs": STAGE_GATES,
            "review_record_refs": [record["id"] for record in self.review_records],
            "replay_plan_ref": replay_plan["id"],
            "release_manifest_ref": "release-support-desk-lite",
            "consumer_output_refs": ["release/task-records.jsonl", "release/verifier-records.jsonl", "release/consumer-index.yaml"],
            "excluded_items": [
                {"item": "training integration", "reason": "consumer-only, out of first runtime slice"},
                {"item": "AWM JSONL schema", "reason": "background only, not target schema"},
            ],
        }

    def _consumer_index(self) -> dict[str, Any]:
        return {
            "consumer_index_id": "consumer-support-desk-lite",
            "release_id": "release-support-desk-lite",
            "task_records_ref": "release/task-records.jsonl",
            "verifier_records_ref": "release/verifier-records.jsonl",
            "surface_index_ref": "spec/surfaces.yaml",
            "reset_contract_ref": "checks/replay-plan.yaml#reset_steps",
            "trace_contract_ref": "checks/surface-traces.jsonl",
            "result_record_schema": {"task_id": "string", "success": "boolean", "checks": "array"},
            "adapter_notes": "Consumers may convert these records to eval/RL formats outside the core generator.",
        }

    def _release_manifest(self, package_plan: dict[str, Any], consumer_index: dict[str, Any]) -> dict[str, Any]:
        artifacts = self.artifacts | {"ConsumerIndex": consumer_index, "EnvironmentPackagePlan": package_plan}
        return {
            "release_id": "release-support-desk-lite",
            "environment_id": "support-desk-lite",
            "artifact_hashes": {name: artifact["hash"] for name, artifact in artifacts.items()},
            "package_layout": "envpkg/",
            "task_index": [task["task_id"] for task in self.artifacts["TaskSet"]["tasks"]],
            "verifier_index": [verifier["verifier_id"] for verifier in self.artifacts["VerifierPlan"]["verifiers"]],
            "surface_index": self.artifacts["SurfacePlan"]["surface_status"],
            "fixture_index": ["fixtures/seed/support-desk-lite.sqlite"],
            "replay_contract": "checks/replay-plan.yaml",
            "consumer_outputs": ["release/task-records.jsonl", "release/verifier-records.jsonl", "release/consumer-index.yaml"],
            "known_limits": ["CLI, HTTP, and MCP surfaces are planned but deferred.", "No training or rollout integration."],
        }


def _artifact_id_from_fields(fields: dict[str, Any]) -> str | None:
    for key in [
        "request_id",
        "package_plan_id",
        "replay_plan_id",
        "consumer_index_id",
        "release_id",
        "backend_id",
    ]:
        if fields.get(key):
            return fields[key]
    return None


def _artifact_review_json(artifact: dict[str, Any]) -> str:
    metadata = {
        key: artifact.get(key)
        for key in ["id", "version", "source_stage", "status", "producer", "inputs", "hash"]
    }
    encoded = stable_json(artifact)
    if len(encoded) <= 12000:
        body = encoded
    else:
        body = encoded[:12000] + "...[truncated]"
    return f'{{"metadata":{stable_json(metadata)},"artifact":{body}}}'


def _invocation_id(stage: str, purpose: str, inputs: list[str]) -> str:
    if inputs:
        suffix = "-".join(_slug(item) for item in inputs[:3])
        if len(inputs) > 3:
            suffix = f"{suffix}-plus{len(inputs) - 3}"
    else:
        suffix = "no-input"
    if len(suffix) > 180:
        digest = hashlib.sha256(stable_json(inputs).encode("utf-8")).hexdigest()[:10]
        suffix = f"{suffix[:150]}-{digest}"
    return f"invoke-{_slug(stage)}-{_slug(purpose)}-{suffix}"


def _slug(value: str) -> str:
    return "".join(char.lower() if char.isalnum() else "-" for char in value).strip("-") or "x"
