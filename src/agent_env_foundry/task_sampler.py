"""Small Direct sampler: propose, freeze one checker, solve twice, package."""

from __future__ import annotations

import json
import time
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
from agent_env_foundry.task_pack import TASK_PACK_FORMAT, task_structure_id, verify_task_pack
from agent_env_foundry.task_proposal import (
    PreparedTaskEnvironment,
    ProposalFailure,
    propose_task_direct,
)

SAMPLING_REPORT_FORMAT = "direct-task-sampling/1"


class TaskSamplingError(RuntimeError):
    pass


def sample_good_tasks(
    prepared: PreparedTaskEnvironment,
    *,
    development_brief: JSONObject,
    builder_projection_digest: str,
    output_root: Path,
    candidate_budget: int,
    target_count: int | None,
    route: AgentRoute | None = None,
    checker_config: BuilderConfig | None = None,
    client_factory: Any = None,
) -> JSONObject:
    """Run one universal sampling loop; a failed candidate never changes its Release."""

    if candidate_budget <= 0 or (
        target_count is not None and not 0 < target_count <= candidate_budget
    ):
        raise ValueError("candidate_budget must be positive and cover optional target_count")
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
    accepted_structures: set[str] = set()
    for index in range(1, candidate_budget + 1):
        attempt_root = root / "attempts" / f"attempt-{index:03d}"
        attempt_root.mkdir()
        stage = "proposal"
        attempt_started = time.monotonic_ns()
        stage_started = attempt_started
        stage_elapsed: dict[str, int] = {}
        candidate_id: str | None = None
        task_id: str | None = None
        structure_id: str | None = None
        proposal_provider_turns: int | None = None
        proposal_tool_calls: int | None = None
        proposal_usage: list[JSONObject | None] = []
        witness_provider_turns: list[int] = []
        witness_tool_calls: list[int] = []
        witness_usage: list[JSONValue] = []
        try:
            proposed = propose_task_direct(
                prepared,
                development_brief=development_brief,
                builder_projection_digest=builder_projection_digest,
                instance_directory=attempt_root / "proposal-instance",
                route=selected_route,
                client_factory=client_factory,
            )
            stage_elapsed[stage] = _elapsed_ms(stage_started)
            proposal_provider_turns = proposed.provider_turns
            proposal_tool_calls = len(proposed.evidence.public_trace)
            proposal_usage = list(proposed.usage)
            candidate_id = proposed.candidate.candidate_id
            _write(attempt_root / "CandidateTaskContract.json", proposed.candidate.to_document())
            _write(attempt_root / "TaskProposalEvidence.json", proposed.evidence.to_document())

            stage = "dedup"
            stage_started = time.monotonic_ns()
            structure_id = task_structure_id(proposed.candidate, proposed.evidence)
            if structure_id in accepted_structures:
                raise _CandidateRejected("duplicate_task_structure")
            stage_elapsed[stage] = _elapsed_ms(stage_started)

            stage = "checker"
            stage_started = time.monotonic_ns()
            workspace = prepare_checker_author_workspace(
                attempt_root / "checker-project",
                candidate=proposed.candidate,
                proposal_evidence=proposed.evidence,
            )
            checker = run_checker_author(workspace, config=selected_checker)
            task = checker.task_contract
            task_id = task.task_id
            _write(attempt_root / "TaskContract.json", task.to_document())
            stage_elapsed[stage] = _elapsed_ms(stage_started)

            stage = "checker_sanity"
            stage_started = time.monotonic_ns()
            _checker_sanity(
                checker.root,
                task=task,
                evidence=proposed.evidence,
                runtime_root=attempt_root / "checker-sanity-runtime",
                settings=settings,
            )
            stage_elapsed[stage] = _elapsed_ms(stage_started)

            stage = "fresh_solve"
            stage_started = time.monotonic_ns()
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
            stage_elapsed[stage] = _elapsed_ms(stage_started)
            witness_provider_turns = [cast(int, item["provider_turns"]) for item in witnesses]
            witness_tool_calls = [
                len(cast(list[JSONValue], item["public_trace"])) for item in witnesses
            ]
            witness_usage = [item["usage"] for item in witnesses]
            for witness in witnesses:
                _write(
                    attempt_root / f"TaskWitness-{witness['witness_index']}.json",
                    witness,
                )

            stage = "package"
            stage_started = time.monotonic_ns()
            preimage: JSONObject = {
                "format": TASK_PACK_FORMAT,
                "candidate": proposed.candidate.to_document(),
                "proposal_evidence": proposed.evidence.to_document(),
                "task": task.to_document(),
                "structure_id": structure_id,
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
            try:
                verify_task_pack(pack_root, expected_id=task_pack_id)
            except ValueError as exc:
                raise TaskSamplingError(f"cold TaskPack verification failed: {exc}") from exc
            stage_elapsed[stage] = _elapsed_ms(stage_started)
            attempts.append(
                {
                    "attempt_index": index,
                    "status": "accepted",
                    "stage": stage,
                    "candidate_id": candidate_id,
                    "task_id": task_id,
                    "task_pack_id": task_pack_id,
                    "structure_id": structure_id,
                    "kind": None,
                    "code": None,
                    **_attempt_metrics(
                        attempt_started=attempt_started,
                        stage_elapsed=stage_elapsed,
                        proposal_provider_turns=proposal_provider_turns,
                        proposal_tool_calls=proposal_tool_calls,
                        proposal_usage=proposal_usage,
                        witness_provider_turns=witness_provider_turns,
                        witness_tool_calls=witness_tool_calls,
                        witness_usage=witness_usage,
                    ),
                }
            )
            accepted += 1
            accepted_structures.add(structure_id)
        except Exception as exc:
            stage_elapsed.setdefault(stage, _elapsed_ms(stage_started))
            kind, code, details = _attribution(exc)
            attempts.append(
                {
                    "attempt_index": index,
                    "status": "rejected",
                    "stage": stage,
                    "candidate_id": candidate_id,
                    "task_id": task_id,
                    "task_pack_id": None,
                    "structure_id": structure_id,
                    "kind": kind,
                    "code": code,
                    **_attempt_metrics(
                        attempt_started=attempt_started,
                        stage_elapsed=stage_elapsed,
                        proposal_provider_turns=proposal_provider_turns,
                        proposal_tool_calls=proposal_tool_calls,
                        proposal_usage=proposal_usage,
                        witness_provider_turns=witness_provider_turns,
                        witness_tool_calls=witness_tool_calls,
                        witness_usage=witness_usage,
                    ),
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
        if target_count is not None and accepted >= target_count:
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
    target_count: int | None,
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


def _attempt_metrics(
    *,
    attempt_started: int,
    stage_elapsed: dict[str, int],
    proposal_provider_turns: int | None,
    proposal_tool_calls: int | None,
    proposal_usage: list[JSONObject | None],
    witness_provider_turns: list[int],
    witness_tool_calls: list[int],
    witness_usage: list[JSONValue],
) -> JSONObject:
    return {
        "elapsed_ms": _elapsed_ms(attempt_started),
        "stage_elapsed_ms": cast(JSONObject, dict(stage_elapsed)),
        "proposal_provider_turns": proposal_provider_turns,
        "proposal_tool_calls": proposal_tool_calls,
        "witness_provider_turns": cast(JSONValue, list(witness_provider_turns)),
        "witness_tool_calls": cast(JSONValue, list(witness_tool_calls)),
        "provider_usage": {
            "proposal": cast(JSONValue, list(proposal_usage)),
            "witnesses": cast(JSONValue, list(witness_usage)),
        },
    }


def _elapsed_ms(started: int) -> int:
    return max(0, (time.monotonic_ns() - started) // 1_000_000)


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
