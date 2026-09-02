"""Small Direct sampler: propose, freeze one checker, solve twice, package."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, cast

from agent_env_foundry.agents import AgentRoute
from agent_env_foundry.builder import BuilderConfig, BuilderFailure
from agent_env_foundry.checker_author import (
    CheckerAuthorFailure,
    execute_task_checker,
    prepare_checker_author_workspace,
    run_checker_author,
)
from agent_env_foundry.environment import JSONObject, JSONValue
from agent_env_foundry.physical_runtime import PreparationSettings
from agent_env_foundry.project_identity import ProjectIdentityError, copy_authored_project
from agent_env_foundry.public_agent import PublicAgentFailure, run_public_episode
from agent_env_foundry.release import canonical_bytes, sha256_hex
from agent_env_foundry.task_contract import TaskContract, make_task_check_request
from agent_env_foundry.task_proposal import (
    PreparedTaskEnvironment,
    ProposalFailure,
    propose_task_direct,
)

SAMPLING_REPORT_FORMAT = "direct-task-sampling/1"
TASK_PACK_FORMAT = "task-pack/1"


class TaskSamplingError(RuntimeError):
    pass


def sample_good_tasks(
    prepared: PreparedTaskEnvironment,
    *,
    development_brief: JSONObject,
    research_digest: str,
    output_root: Path,
    candidate_budget: int,
    target_count: int,
    route: AgentRoute | None = None,
    checker_config: BuilderConfig | None = None,
    client_factory: Any = None,
) -> JSONObject:
    """Run one universal sampling loop; a failed candidate never changes its Release."""

    if candidate_budget <= 0 or not 0 < target_count <= candidate_budget:
        raise ValueError("candidate_budget must be positive and cover target_count")
    root = _fresh_root(output_root)
    (root / "attempts").mkdir()
    (root / "packs").mkdir()
    selected_route = route or AgentRoute()
    selected_checker = checker_config or BuilderConfig(uv_cache_dir=root / "checker-uv-cache")
    settings = PreparationSettings(
        selected_checker.uv_cache_dir,
        selected_checker.command_timeout_seconds,
    )
    attempts: list[JSONObject] = []
    accepted = 0
    for index in range(1, candidate_budget + 1):
        attempt_root = root / "attempts" / f"attempt-{index:03d}"
        attempt_root.mkdir()
        stage = "proposal"
        candidate_id: str | None = None
        task_id: str | None = None
        try:
            proposed = propose_task_direct(
                prepared,
                development_brief=development_brief,
                research_digest=research_digest,
                instance_directory=attempt_root / "proposal-instance",
                route=selected_route,
                client_factory=client_factory,
            )
            candidate_id = proposed.candidate.candidate_id
            _write(attempt_root / "CandidateTaskContract.json", proposed.candidate.to_document())
            _write(attempt_root / "TaskProposalEvidence.json", proposed.evidence.to_document())

            stage = "checker"
            workspace = prepare_checker_author_workspace(
                attempt_root / "checker-project",
                candidate=proposed.candidate,
                proposal_evidence=proposed.evidence,
            )
            checker = run_checker_author(workspace, config=selected_checker)
            task = checker.task_contract
            task_id = task.task_id
            _write(attempt_root / "TaskContract.json", task.to_document())

            stage = "checker_sanity"
            _checker_sanity(
                checker.root,
                task=task,
                evidence=proposed.evidence,
                runtime_root=attempt_root / "checker-sanity-runtime",
                settings=settings,
            )

            stage = "fresh_solve"
            witnesses = tuple(
                _fresh_solve(
                    prepared,
                    task=task,
                    checker_project_root=checker.root,
                    instance_directory=attempt_root / f"witness-{witness_index}-instance",
                    checker_runtime_root=(
                        attempt_root / f"witness-{witness_index}-checker-runtime"
                    ),
                    settings=settings,
                    route=selected_route,
                    client_factory=client_factory,
                    witness_index=witness_index,
                )
                for witness_index in (1, 2)
            )
            for witness in witnesses:
                _write(
                    attempt_root / f"TaskWitness-{witness['witness_index']}.json",
                    witness,
                )

            stage = "package"
            preimage: JSONObject = {
                "format": TASK_PACK_FORMAT,
                "candidate": proposed.candidate.to_document(),
                "proposal_evidence": proposed.evidence.to_document(),
                "task": task.to_document(),
                "witnesses": list(witnesses),
            }
            task_pack_id = sha256_hex(canonical_bytes(preimage))
            pack_document = {**preimage, "task_pack_id": task_pack_id}
            pack_root = root / "packs" / task_pack_id
            pack_root.mkdir()
            copied = copy_authored_project(
                checker.root,
                pack_root / "checker",
                "checker",
            )
            if copied != task.checker_project_digest:
                raise TaskSamplingError("copied checker identity changed")
            _write(pack_root / "TaskPack.json", pack_document)
            attempts.append(
                {
                    "attempt_index": index,
                    "status": "accepted",
                    "stage": stage,
                    "candidate_id": candidate_id,
                    "task_id": task_id,
                    "task_pack_id": task_pack_id,
                    "kind": None,
                    "code": None,
                }
            )
            accepted += 1
        except Exception as exc:
            kind, code, details = _attribution(exc)
            attempts.append(
                {
                    "attempt_index": index,
                    "status": "rejected",
                    "stage": stage,
                    "candidate_id": candidate_id,
                    "task_id": task_id,
                    "task_pack_id": None,
                    "kind": kind,
                    "code": code,
                }
            )
            _write(
                attempt_root / "Rejection.json",
                {
                    "format": "task-sampling-rejection/1",
                    "stage": stage,
                    "kind": kind,
                    "code": code,
                    "message": str(exc),
                    "details": details,
                },
            )
        report = _report(prepared.identity.release_id, candidate_budget, target_count, attempts)
        _write(root / "DirectSamplingReport.json", report)
        if accepted >= target_count:
            return report
    return _report(prepared.identity.release_id, candidate_budget, target_count, attempts)


def _fresh_solve(
    prepared: PreparedTaskEnvironment,
    *,
    task: TaskContract,
    checker_project_root: Path,
    instance_directory: Path,
    checker_runtime_root: Path,
    settings: PreparationSettings,
    route: AgentRoute,
    client_factory: Any,
    witness_index: int,
) -> JSONObject:
    with prepared.open(instance_directory) as session:
        reset = session.actor.reset(task.reset_start)
        before = prepared.read_state(instance_directory)
        episode = run_public_episode(
            actor=session.actor,
            instruction=task.instruction,
            reset_observation=reset,
            tool_specs=session.actor.tools(),
            answer_schema=task.final_answer_schema,
            route=route,
            client_factory=client_factory,
        )
    after = prepared.read_state(instance_directory)
    trace: tuple[JSONObject, ...] = tuple(
        {
            "tool": item.tool_name,
            "arguments": _object(item.arguments),
            "observation": _object(item.observation),
        }
        for item in episode.trace
    )
    request = make_task_check_request(
        task,
        before_state=before,
        after_state=after,
        public_trace=trace,
        final_answer=episode.final_answer,
    )
    result = execute_task_checker(
        checker_project_root,
        task=task,
        request=request,
        runtime_root=checker_runtime_root,
        settings=settings,
    )
    if not result.passed:
        raise _CandidateRejected("fresh_solution_rejected")
    preimage: JSONObject = {
        "format": "task-witness/1",
        "task_id": task.task_id,
        "release_id": task.release_id,
        "witness_index": witness_index,
        "reset_observation": reset,
        "before_state": before,
        "after_state": after,
        "public_trace": list(trace),
        "final_answer": episode.final_answer,
        "checker_result": result.to_document(),
        "provider_turns": episode.provider_turns,
        "usage": list(episode.usage),
    }
    return {**preimage, "witness_id": sha256_hex(canonical_bytes(preimage))}


def _checker_sanity(
    checker_project_root: Path,
    *,
    task: TaskContract,
    evidence: Any,
    runtime_root: Path,
    settings: PreparationSettings,
) -> None:
    no_op = make_task_check_request(
        task,
        before_state=evidence.before_state,
        after_state=evidence.before_state,
        public_trace=(),
        final_answer=evidence.proposed_final_answer,
    )
    if execute_task_checker(
        checker_project_root,
        task=task,
        request=no_op,
        runtime_root=runtime_root / "no-op",
        settings=settings,
    ).passed:
        raise _CandidateRejected("initial_state_already_satisfies_task")
    try:
        wrong_answer = make_task_check_request(
            task,
            before_state=evidence.before_state,
            after_state=evidence.after_state,
            public_trace=evidence.public_trace,
            final_answer={},
        )
    except ValueError:
        return
    if execute_task_checker(
        checker_project_root,
        task=task,
        request=wrong_answer,
        runtime_root=runtime_root / "wrong-answer",
        settings=settings,
    ).passed:
        raise _CandidateRejected("empty_final_answer_accepted")


class _CandidateRejected(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _attribution(exc: Exception) -> tuple[str, str, JSONObject]:
    if isinstance(exc, ProposalFailure):
        return exc.kind, exc.code, _json_object(exc.details)
    if isinstance(exc, PublicAgentFailure):
        return exc.kind, exc.code, _json_object(exc.details)
    if isinstance(exc, CheckerAuthorFailure):
        kind = "InfrastructureFailure" if exc.phase == "infrastructure" else "CheckerDefect"
        return kind, exc.code, _json_object(exc.details)
    if isinstance(exc, BuilderFailure):
        return "InfrastructureFailure", exc.code, _json_object(exc.details)
    if isinstance(exc, ProjectIdentityError):
        return "FrameworkDefect", exc.code, {"path": exc.path}
    if isinstance(exc, _CandidateRejected):
        return "TaskRejected", exc.code, {}
    if isinstance(exc, TaskSamplingError):
        return "FrameworkDefect", "task_pack_invalid", {}
    raise exc


def _report(
    release_id: str,
    candidate_budget: int,
    target_count: int,
    attempts: list[JSONObject],
) -> JSONObject:
    preimage: JSONObject = {
        "format": SAMPLING_REPORT_FORMAT,
        "release_id": release_id,
        "candidate_budget": candidate_budget,
        "target_count": target_count,
        "accepted_count": sum(item["status"] == "accepted" for item in attempts),
        "rejected_count": sum(item["status"] == "rejected" for item in attempts),
        "attempts": cast(JSONValue, attempts),
    }
    return {**preimage, "report_id": sha256_hex(canonical_bytes(preimage))}


def _fresh_root(path: Path) -> Path:
    root = Path(path)
    if root.is_symlink() or (root.exists() and (not root.is_dir() or any(root.iterdir()))):
        raise ValueError("sampling output_root must be absent or empty")
    root.mkdir(parents=True, exist_ok=True)
    return root.resolve()


def _write(path: Path, document: JSONObject) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical_bytes(document))


def _object(value: JSONObject) -> JSONObject:
    return cast(JSONObject, json.loads(json.dumps(value, ensure_ascii=False)))


def _json_object(value: Any) -> JSONObject:
    copied = json.loads(json.dumps(value, ensure_ascii=False, default=str))
    return copied if isinstance(copied, dict) else {"value": copied}


__all__ = ["SAMPLING_REPORT_FORMAT", "TASK_PACK_FORMAT", "sample_good_tasks"]
