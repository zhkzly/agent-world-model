from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import traceback
from pathlib import Path, PurePath
from typing import Any

import yaml

from agent_world.artifacts import GENERATED_PROJECT_FILE_KINDS, RUNTIME_ABI_INTERFACES, make_artifact, stable_json
from agent_world.candidate_check import check_generated_candidate


GENERATED_FILE_KINDS = set(GENERATED_PROJECT_FILE_KINDS)


def strategy_selection_fields(domain_plan: dict[str, Any]) -> dict[str, Any]:
    if domain_plan.get("planning_status") != "planned":
        return {
            "strategy_selection_id": "strategy-selection-blocked-request",
            "domain_plan_ref": domain_plan["id"],
            "domain_seed": domain_plan.get("domain_seed", "blocked-request"),
            "selection_status": "blocked",
            "selected_strategies": [],
            "source_strategy": "",
            "extraction_strategy": "",
            "synthesis_strategy": "",
            "implementation_strategy": "",
            "independent_verifier_strategy": "",
            "package_strategy": "",
            "selection_reason": "No request can be planned from an empty raw request.",
            "blocked_reasons": list(domain_plan.get("blocked_reasons", [])),
        }
    return {
        "strategy_selection_id": f"strategy-selection-{_stable_id_fragment(domain_plan['domain_seed'])}",
        "domain_plan_ref": domain_plan["id"],
        "domain_seed": domain_plan["domain_seed"],
        "selection_status": "selected",
        "selected_strategies": [
            "raw-request-source-discovery-v1",
            "source-grounded-generic-extraction-v1",
            "artifact-driven-task-synthesis-v1",
            "agent-generated-contract-project-v1",
            "framework-replay-contract-verifier-v1",
            "generated-runtime-package-v1",
        ],
        "source_strategy": "raw-request-source-discovery-v1",
        "extraction_strategy": "source-grounded-generic-extraction-v1",
        "synthesis_strategy": "artifact-driven-task-synthesis-v1",
        "implementation_strategy": "agent-generated-contract-project-v1",
        "independent_verifier_strategy": "framework-replay-contract-verifier-v1",
        "package_strategy": "generated-runtime-package-v1",
        "selection_reason": "The request-driven path selects a generic artifact pipeline and delegates executable code to the configured agent backend.",
        "blocked_reasons": [],
    }


def _stable_id_fragment(value: Any, *, max_length: int = 64) -> str:
    raw = str(value or "request").strip().lower()
    chars = []
    previous_dash = False
    for char in raw:
        keep = ("a" <= char <= "z") or ("0" <= char <= "9") or char in {"_", "-", ".", ":", "/", "#"}
        if keep:
            chars.append(char)
            previous_dash = False
        elif not previous_dash:
            chars.append("-")
            previous_dash = True
    slug = "".join(chars).strip("-._:/#") or "request"
    if len(slug) <= max_length:
        return slug
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:10]
    prefix = slug[: max_length - len(digest) - 1].strip("-._:/#") or "request"
    return f"{prefix}-{digest}"


def feasibility_report_fields(context: Any) -> dict[str, Any]:
    blockers = blocking_source_uncertainties(context.artifact("KnowledgePack"))
    return {
        "status": "needs_human" if blockers else "pass",
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
            for record in context.gate_records
        ],
        "minimum_viable_surface": "python",
        "minimum_viable_task_ids": [task["task_id"] for task in context.artifact("TaskSet")["tasks"]],
        "minimum_viable_verifier_ids": [verifier["verifier_id"] for verifier in context.artifact("VerifierPlan")["verifiers"]],
        "implementation_blockers": blockers,
    }


def implementation_request_fields(artifacts: dict[str, dict[str, Any]], review_records: list[dict[str, Any]]) -> dict[str, Any]:
    environment_id = artifacts["EnvironmentSpec"]["environment_id"]
    return {
        "request_id": f"impl-{environment_id}",
        "environment_id": environment_id,
        "source_artifact_ids": [
            artifacts["DomainPlan"]["id"],
            artifacts["StrategySelection"]["id"],
            artifacts["SourceEvidenceIndex"]["id"],
            artifacts["KnowledgePack"]["id"],
            artifacts["TaskSet"]["id"],
            artifacts["VerifierPlan"]["id"],
        ],
        "accepted_task_ids": [task["task_id"] for task in artifacts["TaskSet"]["tasks"]],
        "accepted_verifier_ids": [verifier["verifier_id"] for verifier in artifacts["VerifierPlan"]["verifiers"]],
        "required_surface_ids": [binding["binding_id"] for binding in artifacts["SurfacePlan"]["bindings"] if binding["surface"] == "python"],
        "package_layout_ref": "envpkg/",
        "implementation_scope": [
            "agent-written contract.json",
            "agent-written free-form source project",
            "agent-written state fixtures, adapters, scripts, specs, and deterministic verifier behavior",
            "framework-owned replay and independent verifier records",
        ],
        "non_goals": ["training integration", "rollout", "reward export", "AWM reproduction", "live external service access", "generic shell environment surface"],
        "tdd_requirements": ["machine-readable framework replay contract", "positive and negative verifier behavior", "forged generated check rejection"],
        "launch_check_commands": ["run candidate_manifest.self_check.command from <candidate_dir>"],
        "review_record_refs": [record["id"] for record in review_records],
        "strategy_selection_ref": artifacts["StrategySelection"]["id"],
    }


def generated_implementation_record(context: Any, **_: Any) -> dict[str, Any]:
    environment_id = context.artifact("ImplementationRequest")["environment_id"]
    return {
        "implementation_id": f"implementation-{environment_id}-agent-required",
        "mode": "agent_required",
        "environment_id": environment_id,
        "implementation_request_id": context.artifact("ImplementationRequest")["id"],
        "static_check_command": "not run",
        "test_command": "not run",
        "replay_command": "not run",
        "implementation_check_records": [],
        "verifier_result": {},
        "status": "fail",
        "failure_class": "agent_backend_required",
        "recovery_suggestion": "Request-driven generation requires implementation_mode=agent and a backend that writes a contract-project candidate.",
    }


def agent_generated_implementation_record(context: Any, *, agent_invocation: dict[str, Any], agent_result: Any, work_dir: Path) -> dict[str, Any]:
    work_dir = Path(work_dir)
    request = context.artifact("ImplementationRequest")
    environment_id = request["environment_id"]
    base = {
        "implementation_id": f"implementation-{environment_id}-agent-generated",
        "mode": "agent_backed_contract_project",
        "environment_id": environment_id,
        "implementation_request_id": request["id"],
        "agent_invocation_id": agent_invocation["id"],
        "agent_work_dir": str(work_dir),
        "source_artifact_ids": request["source_artifact_ids"],
        "static_check_command": "validate agent candidate manifest, contract.json, path boundaries, file hashes, generated self-check, and framework independent verifier",
        "test_command": "run candidate_manifest.self_check.command",
        "replay_command": "framework ABI replay through contract.json interfaces",
        "self_check_commands": [],
        "replay_commands": [],
    }
    if agent_result.status != "pass":
        return _agent_failure_record(base, status=agent_result.status, failure_class=agent_result.failure_class or "agent_backend_failed", recovery_suggestion=agent_result.recovery_suggestion or "Fix or configure the agent backend.")
    manifest, manifest_error = _agent_candidate_manifest(agent_result.text, work_dir)
    if manifest_error:
        return _agent_failure_record(base, failure_class=manifest_error["failure_class"], recovery_suggestion=manifest_error["recovery_suggestion"])
    validation_error = _validate_agent_candidate_files(work_dir, manifest)
    if validation_error:
        return _agent_failure_record(base, failure_class=validation_error["failure_class"], recovery_suggestion=validation_error["recovery_suggestion"])
    project_dir = _agent_candidate_root(work_dir, manifest)
    if isinstance(project_dir, dict):
        return _agent_failure_record(base, failure_class=project_dir["failure_class"], recovery_suggestion=project_dir["recovery_suggestion"])
    contract = _read_project_contract(project_dir, manifest)
    if isinstance(contract, dict) and "failure_class" in contract:
        return _agent_failure_record(base, failure_class=contract["failure_class"], recovery_suggestion=contract["recovery_suggestion"])
    generated_files = _project_records_from_agent_manifest(project_dir, manifest, fallback_source_refs=_source_refs(context))
    check_record = check_generated_project(
        project_dir,
        environment_id=environment_id,
        accepted_tasks=context.artifact("TaskSet")["tasks"],
        manifest=manifest,
    )
    implementation_check_records = _project_check_records(check_record)
    status = "pass" if check_record["success"] else "fail"
    self_check_commands = [list(manifest.get("self_check", {}).get("command", []))] if isinstance(manifest.get("self_check"), dict) else []
    replay_commands = [["framework-abi-replay", task_id] for task_id in _accepted_task_ids(context)]
    project_artifact = _project_artifact(
        context=context,
        project_id=str(manifest.get("implementation_id") or f"project-{environment_id}-agent-generated"),
        producer="request-driven-agent-codegen",
        build_dir=project_dir,
        contract=contract,
        contract_ref=str(manifest.get("contract_ref") or "contract.json"),
        generated_files=generated_files,
        independent_check_records=implementation_check_records,
        status=status,
        implementation_mode="agent_backed_contract_project",
        extra_inputs=[agent_invocation["id"]],
        self_check_commands=self_check_commands,
        replay_commands=replay_commands,
        agent_invocation_ref=agent_invocation["id"],
    )
    independent_report = independent_verification_report_from_check(context, project_artifact, check_record)
    return {
        **base,
        "generated_project_id": project_artifact["id"],
        "generated_environment_project": project_artifact,
        "independent_verification_report": independent_report,
        "generated_paths": [item["path"] for item in generated_files],
        "generated_file_hashes": {item["path"]: item["sha256"] for item in generated_files},
        "agent_candidate_dir": str(project_dir),
        "test_command": self_check_commands[0] if self_check_commands else "not declared",
        "replay_command": replay_commands[0] if replay_commands else "",
        "self_check_commands": self_check_commands,
        "replay_commands": replay_commands,
        "implementation_check_records": implementation_check_records,
        "verifier_result": check_record.get("positive_verifier_result", {}),
        "negative_verifier_result": check_record.get("negative_verifier_result", {}),
        "status": status,
        "failure_class": "" if status == "pass" else check_record.get("failure_class", "generated_project_check_failed"),
        "recovery_suggestion": "" if status == "pass" else check_record.get("recovery_suggestion", "Repair generated contract project before release planning."),
    }


def package_plan_fields(context: Any) -> dict[str, Any]:
    project = context.artifact("GeneratedEnvironmentProject")
    environment_id = project["environment_id"]
    package_ref = f"package-{environment_id}"
    replay_ref = f"replay-{environment_id}"
    release_ref = f"release-{environment_id}"
    included_ids = (
        [artifact["id"] for artifact in context.artifacts.values()]
        + [package_ref, replay_ref, f"consumer-{environment_id}", release_ref]
        + [record["id"] for record in context.review_records]
        + [record["id"] for record in context.gate_records]
        + [record["implementation_id"] for record in context.implementation_check_records]
    )
    return {
        "package_plan_id": package_ref,
        "environment_id": environment_id,
        "layout": "envpkg/",
        "included_artifact_ids": included_ids,
        "fixture_refs": [f"fixtures/seed/{environment_id}.json"],
        "static_check_refs": "request-driven S0-S11 gates plus framework independent verifier",
        "review_record_refs": [record["id"] for record in context.review_records],
        "replay_plan_ref": replay_ref,
        "release_manifest_ref": release_ref,
        "generated_project_ref": project["id"],
        "independent_verification_report_ref": context.artifact("IndependentVerificationReport")["id"],
        "consumer_output_refs": ["release/task-records.jsonl", "release/verifier-records.jsonl", "release/consumer-index.yaml", "runtime/runtime_index.json"],
        "excluded_items": [
            {"item": "live external services", "reason": "release package must not mutate undeclared external services"},
            {"item": "generic shell executor", "reason": "environment tools are logical Python callables"},
            {"item": "trainer runtime", "reason": "training is a downstream consumer"},
        ],
    }


def release_manifest_fields(context: Any) -> dict[str, Any]:
    project = context.artifact("GeneratedEnvironmentProject")
    environment_id = project["environment_id"]
    artifacts = context.artifacts | {"EnvironmentPackagePlan": context.artifact("EnvironmentPackagePlan")}
    return {
        "release_id": f"release-{environment_id}",
        "environment_id": environment_id,
        "version": "0.1.0",
        "artifact_hashes": {name: artifact["hash"] for name, artifact in artifacts.items()},
        "package_layout": "envpkg/",
        "task_index": [task["task_id"] for task in context.artifact("TaskSet")["tasks"]],
        "verifier_index": [verifier["verifier_id"] for verifier in context.artifact("VerifierPlan")["verifiers"]],
        "surface_index": context.artifact("SurfacePlan")["surface_status"],
        "fixture_index": [f"fixtures/seed/{environment_id}.json"],
        "replay_contract": "checks/framework-replay-contract.json",
        "generated_project_ref": project["id"],
        "independent_verification_report_ref": context.artifact("IndependentVerificationReport")["id"],
        "request_lineage": {
            "domain_plan_ref": context.artifact("DomainPlan")["id"],
            "strategy_selection_ref": context.artifact("StrategySelection")["id"],
            "source_evidence_ref": context.artifact("SourceEvidenceIndex")["id"],
            "knowledge_pack_ref": context.artifact("KnowledgePack")["id"],
            "task_set_ref": context.artifact("TaskSet")["id"],
            "verifier_plan_ref": context.artifact("VerifierPlan")["id"],
            "implementation_request_ref": context.artifact("ImplementationRequest")["id"],
            "generated_project_ref": project["id"],
            "independent_verification_report_ref": context.artifact("IndependentVerificationReport")["id"],
        },
        "generated_project": {
            "project_id": project["id"],
            "build_dir": project["build_dir"],
            "contract_ref": project["contract_ref"],
            "runtime_abi_version": project["runtime_abi_version"],
            "self_check_commands": project["self_check_commands"],
            "replay_commands": project["replay_commands"],
        },
        "consumer_outputs": ["release/task-records.jsonl", "release/verifier-records.jsonl", "release/consumer-index.yaml", "runtime/runtime_index.json"],
        "known_limits": [
            "The request-driven path requires an agent backend to write executable candidate files.",
            "Source discovery is performed by the configured research provider and accepted agent output.",
            "Training, deployment, and online rollout remain downstream consumers.",
        ],
    }


def blocking_source_uncertainties(knowledge: dict[str, Any]) -> list[dict[str, Any]]:
    return [item for item in knowledge.get("uncertainties", []) if item.get("blocking")]


def check_generated_project(
    build_dir: Path,
    *,
    environment_id: str,
    accepted_tasks: list[dict[str, Any]] | None = None,
    manifest: dict[str, Any] | None = None,
) -> dict[str, Any]:
    build_dir = Path(build_dir)
    manifest = manifest or {}
    self_check = manifest.get("self_check") if isinstance(manifest.get("self_check"), dict) else {}
    command = list(self_check.get("command") or [])
    generated_check = _run_generated_check(command, build_dir)
    framework_check = check_generated_candidate(
        build_dir=build_dir,
        environment_id=environment_id,
        accepted_tasks=accepted_tasks,
    )
    independent = framework_check["independent_verification_record"]
    success = generated_check["success"] and framework_check["success"]
    if not generated_check["success"]:
        failure_class = generated_check.get("failure_class", "generated_project_self_check_failed")
        recovery = generated_check.get("recovery_suggestion", "Repair generated self-check command or contract project files.")
    elif not framework_check["success"]:
        failure_class = framework_check.get("failure_class", "framework_candidate_check_failed")
        recovery = framework_check.get("recovery_suggestion", "Repair generated runtime, verifier, seed, or trace behavior.")
    else:
        failure_class = ""
        recovery = ""
    return {
        "check_id": "request-driven-generated-project-check",
        "success": success,
        "command": generated_check["command"],
        "exit_code": generated_check.get("exit_code"),
        "stdout": generated_check.get("stdout", ""),
        "stderr": generated_check.get("stderr", ""),
        "generated_check_record": generated_check,
        "independent_verification_record": independent,
        "framework_candidate_check_record": framework_check,
        "framework_check_observation": framework_check.get("framework_check_observation", {}),
        "independent_task_records": independent.get("task_records", []),
        "positive_verifier_result": _first_task_result(independent, "positive_verifier_result"),
        "negative_verifier_result": _first_task_result(independent, "negative_verifier_result"),
        "failure_class": failure_class,
        "recovery_suggestion": recovery,
    }


def independent_verification_report_from_check(context: Any, project: dict[str, Any], check_record: dict[str, Any]) -> dict[str, Any]:
    independent = check_record.get("independent_verification_record", {})
    task_records = list(independent.get("task_records", []))
    positive_count = sum(1 for record in task_records if isinstance(record.get("positive_verifier_result"), dict) and record["positive_verifier_result"].get("success") is True)
    negative_count = sum(1 for record in task_records if isinstance(record.get("negative_verifier_result"), dict) and record["negative_verifier_result"].get("success") is False)
    success = bool(independent.get("success"))
    environment_id = project["environment_id"]
    return make_artifact(
        "IndependentVerificationReport",
        source_stage="IMPLEMENT",
        producer="framework-replay-contract-verifier",
        artifact_id=f"independent-verification-{environment_id}",
        inputs=[project["id"], context.artifact("TaskSet")["id"], context.artifact("VerifierPlan")["id"]],
        status="accepted" if success else "fail",
        fields={
            "report_id": f"independent-verification-{environment_id}",
            "environment_id": environment_id,
            "generated_project_ref": project["id"],
            "verifier_strategy": "framework-contract-project-abi-verifier-v1",
            "accepted_task_ids": list(independent.get("accepted_task_ids", [])),
            "verified_task_ids": list(independent.get("verified_task_ids", [])),
            "task_records": task_records,
            "framework_check_observation": independent.get("framework_check_observation", {}),
            "positive_record_count": positive_count,
            "negative_record_count": negative_count,
            "success": success,
            "failure_class": independent.get("failure_class", ""),
            "recovery_suggestion": independent.get("recovery_suggestion", ""),
            "source_artifact_refs": [context.artifact("TaskSet")["id"], context.artifact("VerifierPlan")["id"], project["id"]],
        },
    )


def run_summary(context: Any) -> dict[str, Any]:
    order = [
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
        "ImplementationRequest",
        "GeneratedEnvironmentProject",
        "IndependentVerificationReport",
        "EnvironmentPackagePlan",
        "ReleaseManifest",
    ]
    return {
        "summary_id": "request-driven-generated-run-summary",
        "artifact_flow": [
            {
                "artifact_type": name,
                "artifact_id": context.artifacts[name]["id"],
                "inputs": list(context.artifacts[name].get("inputs", [])),
                "producer": context.artifacts[name].get("producer", ""),
            }
            for name in order
            if name in context.artifacts
        ],
        "environment_id": context.artifacts.get("ReleaseManifest", {}).get("environment_id", ""),
    }


def _project_artifact(
    *,
    context: Any,
    project_id: str,
    producer: str,
    build_dir: Path,
    contract: dict[str, Any],
    contract_ref: str,
    generated_files: list[dict[str, Any]],
    independent_check_records: list[dict[str, Any]],
    status: str,
    implementation_mode: str,
    extra_inputs: list[str],
    self_check_commands: list[list[str]],
    replay_commands: list[list[str]],
    agent_invocation_ref: str = "",
) -> dict[str, Any]:
    fields = {
        "project_id": project_id,
        "environment_id": context.artifact("ImplementationRequest")["environment_id"],
        "source_artifact_ids": context.artifact("ImplementationRequest")["source_artifact_ids"],
        "implementation_request_id": context.artifact("ImplementationRequest")["id"],
        "build_dir": str(build_dir),
        "contract_ref": contract_ref,
        "contract": contract,
        "generated_files": generated_files,
        "runtime_abi_version": "agent-world.runtime-abi.v1",
        "required_interfaces": sorted(RUNTIME_ABI_INTERFACES),
        "self_check_commands": self_check_commands,
        "replay_commands": replay_commands,
        "independent_check_records": independent_check_records,
        "implementation_mode": implementation_mode,
    }
    if agent_invocation_ref:
        fields["agent_invocation_ref"] = agent_invocation_ref
    return make_artifact(
        "GeneratedEnvironmentProject",
        source_stage="IMPLEMENT",
        producer=producer,
        artifact_id=project_id,
        inputs=[context.artifact("ImplementationRequest")["id"]] + list(extra_inputs),
        status="accepted" if status == "pass" else "fail",
        fields=fields,
    )


def _project_check_records(check_record: dict[str, Any]) -> list[dict[str, Any]]:
    return [check_record] + list(check_record.get("independent_task_records", []))


def _first_task_result(independent_record: dict[str, Any], field: str) -> dict[str, Any]:
    for record in independent_record.get("task_records", []):
        value = record.get(field)
        if isinstance(value, dict) and value:
            return value
    return {}


def _accepted_task_ids(context: Any) -> list[str]:
    if "TaskSet" not in getattr(context, "artifacts", {}):
        return []
    return [str(task["task_id"]) for task in context.artifact("TaskSet").get("tasks", [])]


def _source_refs(context: Any) -> list[str]:
    refs = []
    for artifact_type in ["DomainPlan", "StrategySelection", "SourceEvidenceIndex", "KnowledgePack", "EnvironmentSpec", "LogicalToolGraph", "TaskSet", "VerifierPlan"]:
        if artifact_type in context.artifacts:
            refs.append(context.artifact(artifact_type)["id"])
    return refs


def _run_generated_check(command: list[str], build_dir: Path) -> dict[str, Any]:
    if not command:
        return {
            "check_id": "generated-self-check",
            "success": False,
            "command": [],
            "exit_code": None,
            "stdout": "",
            "stderr": "candidate manifest self_check.command is missing",
            "failure_class": "missing_generated_self_check",
            "recovery_suggestion": "Candidate manifest must declare self_check.command.",
        }
    argv = [sys.executable if str(part) == "python" else str(part) for part in command]
    try:
        completed = subprocess.run(argv, cwd=build_dir, text=True, capture_output=True, timeout=10, check=False)
    except Exception as exc:
        return {
            "check_id": "generated-self-check",
            "success": False,
            "command": argv,
            "exit_code": None,
            "stdout": "",
            "stderr": str(exc),
            "exception": {"type": exc.__class__.__name__, "message": str(exc), "traceback": traceback.format_exc()},
            "failure_class": exc.__class__.__name__,
            "recovery_suggestion": "Generated check entrypoint could not be executed.",
        }
    parsed = _parse_check_stdout(completed.stdout)
    success = completed.returncode == 0 and parsed.get("success") is True
    return {
        "check_id": "generated-self-check",
        "success": success,
        "command": argv,
        "exit_code": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "positive_verifier_result": parsed.get("positive_verifier_result", {}),
        "negative_verifier_result": parsed.get("negative_verifier_result", {}),
        "failure_class": "" if success else "generated_project_self_check_failed",
        "recovery_suggestion": "" if success else "Generated self-check did not report success.",
    }


def _parse_check_stdout(stdout: str) -> dict[str, Any]:
    try:
        parsed = json.loads(stdout)
    except json.JSONDecodeError:
        parsed = None
    if isinstance(parsed, dict):
        return parsed
    for line in reversed(stdout.splitlines()):
        if not line.strip():
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _agent_failure_record(
    base: dict[str, Any],
    *,
    status: str = "fail",
    failure_class: str,
    recovery_suggestion: str,
) -> dict[str, Any]:
    return {
        **base,
        "generated_paths": [],
        "generated_file_hashes": {},
        "implementation_check_records": [
            {
                "check_id": base["implementation_id"],
                "success": False,
                "failure_class": failure_class,
                "recovery_suggestion": recovery_suggestion,
            }
        ],
        "verifier_result": {},
        "negative_verifier_result": {},
        "status": status,
        "failure_class": failure_class,
        "recovery_suggestion": recovery_suggestion,
    }


def _agent_candidate_manifest(text: str, work_dir: Path) -> tuple[dict[str, Any], dict[str, str] | None]:
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return {}, {"failure_class": "malformed_agent_output", "recovery_suggestion": "Agent output must be a JSON candidate manifest."}
    if not isinstance(parsed, dict):
        return {}, {"failure_class": "malformed_agent_output", "recovery_suggestion": "Agent output must be a JSON object."}
    if "candidate_manifest_ref" in parsed and "generated_files" not in parsed:
        ref = str(parsed.get("candidate_manifest_ref") or "")
        path_error = _candidate_path_error(ref)
        if path_error:
            return {}, path_error
        root = Path(work_dir).resolve()
        manifest_path = (root / ref).resolve()
        if not _inside(manifest_path, root):
            return {}, {"failure_class": "path_traversal_rejected", "recovery_suggestion": "Agent candidate_manifest_ref must resolve inside the isolated workdir."}
        if not manifest_path.is_file():
            return {}, {"failure_class": "missing_candidate_manifest", "recovery_suggestion": "Agent candidate_manifest_ref does not point to a file in the isolated workdir."}
        parsed = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
    if not isinstance(parsed.get("generated_files"), list):
        return {}, {"failure_class": "missing_candidate_files", "recovery_suggestion": "Agent candidate manifest must declare generated_files."}
    for field in ["candidate_dir", "environment_id", "implementation_id", "contract_ref", "self_check"]:
        if field not in parsed:
            return {}, {"failure_class": "missing_candidate_manifest_field", "recovery_suggestion": f"Agent candidate manifest must declare {field}."}
    if not isinstance(parsed.get("self_check"), dict) or not isinstance(parsed["self_check"].get("command"), list):
        return {}, {"failure_class": "missing_generated_self_check", "recovery_suggestion": "Agent candidate manifest must declare self_check.command as a list."}
    return parsed, None


def _validate_agent_candidate_files(work_dir: Path, manifest: dict[str, Any]) -> dict[str, str] | None:
    candidate_root = _agent_candidate_root(work_dir, manifest)
    if isinstance(candidate_root, dict):
        return candidate_root
    root = candidate_root.resolve()
    if str(manifest.get("candidate_dir") or "") != "generated":
        return {"failure_class": "invalid_candidate_dir", "recovery_suggestion": "Agent candidate manifest must declare candidate_dir: generated."}
    contract_ref = str(manifest.get("contract_ref") or "contract.json")
    if contract_ref != "contract.json":
        return {"failure_class": "invalid_contract_ref", "recovery_suggestion": "Agent candidate manifest must declare contract_ref: contract.json."}
    for dirname in ["source", "state", "adapters", "scripts", "spec"]:
        if not (candidate_root / dirname).is_dir():
            return {"failure_class": "missing_project_directory", "recovery_suggestion": f"Generated project is missing required directory: {dirname}/"}
    declared: set[str] = set()
    for item in manifest.get("generated_files", []):
        if not isinstance(item, dict):
            return {"failure_class": "malformed_candidate_manifest", "recovery_suggestion": "Each generated_files item must be an object."}
        rel_text = str(item.get("path") or "")
        path_error = _candidate_path_error(rel_text)
        if path_error:
            return path_error
        if item.get("kind") not in GENERATED_FILE_KINDS:
            return {"failure_class": "candidate_file_kind_mismatch", "recovery_suggestion": f"Agent candidate file {rel_text} has an unsupported kind."}
        actual = (candidate_root / rel_text).resolve()
        if not _inside(actual, root):
            return {"failure_class": "symlink_escape", "recovery_suggestion": "Agent candidate file resolves outside the candidate project directory."}
        if not actual.is_file():
            return {"failure_class": "missing_generated_file", "recovery_suggestion": f"Agent candidate file is missing: {rel_text}"}
        expected_hash = str(item.get("sha256") or "")
        if expected_hash != _sha256(actual):
            return {"failure_class": "hash_mismatch", "recovery_suggestion": f"Agent candidate file hash mismatch: {rel_text}"}
        declared.add(rel_text)
    if contract_ref not in declared:
        return {"failure_class": "missing_generated_file", "recovery_suggestion": "Agent candidate must declare contract.json in generated_files."}
    observed = {path.relative_to(candidate_root).as_posix() for path in candidate_root.rglob("*") if path.is_file() and not _is_python_cache_file(path)}
    extra = sorted(observed - declared)
    if extra:
        return {"failure_class": "undeclared_generated_file", "recovery_suggestion": f"Agent wrote files that were not declared in the candidate manifest: {extra}"}
    contract = _read_project_contract(candidate_root, manifest)
    if isinstance(contract, dict) and "failure_class" in contract:
        return contract
    if contract.get("environment_id") != manifest.get("environment_id"):
        return {"failure_class": "contract_environment_mismatch", "recovery_suggestion": "contract.json environment_id must match candidate manifest environment_id."}
    if set((contract.get("interfaces") or {}).keys()) != RUNTIME_ABI_INTERFACES:
        return {"failure_class": "missing_runtime_interface", "recovery_suggestion": "contract.json must declare exactly the eight runtime ABI interfaces."}
    for filename in sorted(path for path in declared if path.endswith(".py")):
        text = (candidate_root / filename).read_text(encoding="utf-8")
        if "agent_world." in text:
            return {"failure_class": "framework_runtime_import", "recovery_suggestion": "Generated project files must be self-contained and must not import the framework package."}
    return None


def _read_project_contract(project_dir: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    contract_ref = str(manifest.get("contract_ref") or "contract.json")
    path_error = _candidate_path_error(contract_ref)
    if path_error:
        return path_error
    path = (project_dir / contract_ref).resolve()
    if not _inside(path, project_dir.resolve()) or not path.is_file():
        return {"failure_class": "missing_contract", "recovery_suggestion": "Generated project must contain contract.json."}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"failure_class": "malformed_contract", "recovery_suggestion": "Generated contract.json must be valid JSON."}
    if not isinstance(value, dict):
        return {"failure_class": "malformed_contract", "recovery_suggestion": "Generated contract.json must contain an object."}
    return value


def _project_records_from_agent_manifest(project_dir: Path, manifest: dict[str, Any], *, fallback_source_refs: list[str]) -> list[dict[str, Any]]:
    by_path = {str(item.get("path")): item for item in manifest.get("generated_files", []) if isinstance(item, dict)}
    records = []
    for filename in sorted(by_path):
        item = by_path[filename]
        records.append(
            {
                "path": filename,
                "kind": str(item.get("kind") or "other"),
                "sha256": str(item.get("sha256") or _sha256(project_dir / filename)),
                "source_refs": [str(ref) for ref in item.get("source_refs", [])] or fallback_source_refs,
            }
        )
    return records


def _agent_candidate_root(work_dir: Path, manifest: dict[str, Any]) -> Path | dict[str, str]:
    work_root = Path(work_dir).resolve()
    candidate_dir = str(manifest.get("candidate_dir") or ".")
    if candidate_dir == ".":
        candidate_root = work_root
    else:
        path_error = _candidate_path_error(candidate_dir)
        if path_error:
            return path_error
        candidate_root = (work_root / candidate_dir).resolve()
    if not _inside(candidate_root, work_root):
        return {"failure_class": "path_traversal_rejected", "recovery_suggestion": "Agent candidate_dir must resolve inside the isolated workdir."}
    if not candidate_root.is_dir():
        return {"failure_class": "missing_candidate_dir", "recovery_suggestion": "Agent candidate_dir does not exist in the isolated workdir."}
    return candidate_root


def _candidate_path_error(path_text: str) -> dict[str, str] | None:
    if not path_text:
        return {"failure_class": "invalid_candidate_path", "recovery_suggestion": "Candidate paths must be non-empty relative paths."}
    if "\\" in path_text:
        return {"failure_class": "invalid_candidate_path", "recovery_suggestion": "Candidate paths must use POSIX separators."}
    path = PurePath(path_text)
    if path.is_absolute() or path_text.startswith("~"):
        return {"failure_class": "absolute_path_rejected", "recovery_suggestion": "Candidate paths must not be absolute or home-relative."}
    if any(part in {"", ".."} for part in path.parts):
        return {"failure_class": "path_traversal_rejected", "recovery_suggestion": "Candidate paths must not contain parent directory segments."}
    if "." in path.parts and path_text != ".":
        return {"failure_class": "path_traversal_rejected", "recovery_suggestion": "Candidate file paths must not contain current directory segments."}
    return None


def _is_python_cache_file(path: Path) -> bool:
    return "__pycache__" in path.parts or path.suffix in {".pyc", ".pyo"}


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
