"""Exact single-Task S3 Episode execution over current S2 Task authority."""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast

from agent_env_foundry.batch_foundry import GoalKind, TrustedTaskView, read_task_pack_artifact
from agent_env_foundry.environment import JSONObject, JSONValue
from agent_env_foundry.episodes import (
    DefectOwner,
    EpisodeDefect,
    EpisodeRequest,
    PolicySpec,
    PublicEpisodeCapture,
    RewardOutcome,
)
from agent_env_foundry.foreach_foundry import (
    ForEachTask,
    _contexts,
    _resolve_complete_selection,
)
from agent_env_foundry.foreach_foundry import (
    _verify_task as _verify_foreach_task,
)
from agent_env_foundry.if_foundry import IfTask
from agent_env_foundry.if_foundry import _verify_task as _verify_if_task
from agent_env_foundry.jsonvalue import is_json_object, is_json_value
from agent_env_foundry.preparation import (
    OpenPreparedRelease,
    OpenPreparedSession,
    PreparationContractError,
    PreparationExecutionError,
)
from agent_env_foundry.public_agent import (
    PolicyDriver,
    _trace_from_capture,
    capture_public_episode,
)
from agent_env_foundry.release import canonical_bytes
from agent_env_foundry.semantics import (
    AtomCheckRequest,
    BindingCandidate,
    ConditionCheckRequest,
    ConditionCheckResult,
    SemanticsContractError,
    start_case_from_document,
)
from agent_env_foundry.task_execution import LifecycleEvent, ReloadEvidence
from agent_env_foundry.task_foundry import (
    AtomTask,
    TaskFoundryError,
    _context,
    _evaluate_report_atom,
    _resolve_binding,
    _verify_checker_preimage,
)

_HEX = frozenset("0123456789abcdef")
_COMPLETE_LIFECYCLE = (
    "acting_open",
    "reset",
    "capture_terminal",
    "pre_close_inspect",
    "acting_close",
    "reopened_open",
    "post_reopen_inspect",
    "checker_evaluated",
    "reopened_close",
)


@dataclass(frozen=True, slots=True)
class EpisodeRecord:
    request: EpisodeRequest
    policy_spec: PolicySpec
    capture: PublicEpisodeCapture
    policy_elapsed_ms: int
    native_instance_id: str
    acting_session_id: str
    reopened_session_id: str | None
    lifecycle_events: tuple[LifecycleEvent, ...]
    before_facts_digest: str
    pre_close_facts_digest: str | None
    post_reopen_facts_digest: str | None
    goal_kind: GoalKind
    checker_documents: JSONObject | None
    lifecycle_defect: EpisodeDefect | None
    reload_evidence: ReloadEvidence | None
    reward: RewardOutcome
    episode_id: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.request, EpisodeRequest):
            raise ValueError("request must be an EpisodeRequest")
        if not isinstance(self.policy_spec, PolicySpec):
            raise ValueError("policy_spec must be a PolicySpec")
        if not isinstance(self.capture, PublicEpisodeCapture):
            raise ValueError("capture must be a PublicEpisodeCapture")
        if self.request.policy_id != self.policy_spec.policy_id:
            raise ValueError("Episode request belongs to another policy")
        public_prompt = self.capture.public_input.system_prompt
        if (
            hashlib.sha256(public_prompt.encode()).hexdigest()
            != self.policy_spec.system_prompt_digest
        ):
            raise ValueError("Episode capture prompt differs from its PolicySpec")
        if (
            isinstance(self.policy_elapsed_ms, bool)
            or not isinstance(self.policy_elapsed_ms, int)
            or self.policy_elapsed_ms < 0
        ):
            raise ValueError("policy_elapsed_ms must be a nonnegative integer")
        for value, role in (
            (self.native_instance_id, "native_instance_id"),
            (self.acting_session_id, "acting_session_id"),
            (self.before_facts_digest, "before_facts_digest"),
        ):
            _digest(value, role)
        for optional_value, role in (
            (self.reopened_session_id, "reopened_session_id"),
            (self.pre_close_facts_digest, "pre_close_facts_digest"),
            (self.post_reopen_facts_digest, "post_reopen_facts_digest"),
        ):
            if optional_value is not None:
                _digest(optional_value, role)
        _validate_lifecycle(self)
        if self.goal_kind not in {"atom", "foreach", "if"}:
            raise ValueError("goal_kind is invalid")
        checker = (
            None
            if self.checker_documents is None
            else _object(self.checker_documents, "checker_documents")
        )
        object.__setattr__(self, "checker_documents", checker)
        if checker is not None and set(checker) != {self.goal_kind}:
            raise ValueError("checker documents belong to another goal kind")
        if self.lifecycle_defect is not None and not isinstance(
            self.lifecycle_defect, EpisodeDefect
        ):
            raise ValueError("lifecycle_defect must be an EpisodeDefect")
        if self.capture.defect is not None and self.lifecycle_defect is not None:
            raise ValueError("capture defect remains the sole primary Episode defect")
        expected_reward = _runtime_reward(
            self.capture,
            self.lifecycle_defect,
            self.lifecycle_events,
            self.checker_documents,
        )
        if self.reward != expected_reward:
            raise ValueError("Episode reward contradicts capture, lifecycle, or checker truth")
        _validate_reload(self)
        expected_id = _document_digest(self._preimage())
        if self.episode_id and self.episode_id != expected_id:
            raise ValueError("episode_id differs from the complete Episode preimage")
        object.__setattr__(self, "episode_id", expected_id)

    def _preimage(self) -> JSONObject:
        return {
            "format": "episode-record/1",
            "request": self.request.to_document(),
            "policy_spec": self.policy_spec.to_document(),
            "capture": self.capture.to_document(),
            "policy_elapsed_ms": self.policy_elapsed_ms,
            "native_instance_id": self.native_instance_id,
            "acting_session_id": self.acting_session_id,
            "reopened_session_id": self.reopened_session_id,
            "lifecycle_events": [item.to_document() for item in self.lifecycle_events],
            "before_facts_digest": self.before_facts_digest,
            "pre_close_facts_digest": self.pre_close_facts_digest,
            "post_reopen_facts_digest": self.post_reopen_facts_digest,
            "goal_kind": self.goal_kind,
            "checker_documents": (
                None
                if self.checker_documents is None
                else _object(self.checker_documents, "checker_documents")
            ),
            "lifecycle_defect": (
                None if self.lifecycle_defect is None else self.lifecycle_defect.to_document()
            ),
            "reload_evidence": (
                None if self.reload_evidence is None else self.reload_evidence.to_document()
            ),
            "reward": self.reward.to_document(),
        }

    def to_document(self) -> JSONObject:
        return {**self._preimage(), "episode_id": self.episode_id}


def run_task_episode(
    prepared: OpenPreparedRelease,
    task_pack_path: Path,
    expected_task_pack_id: str,
    *,
    policy_driver: PolicyDriver,
    rollout_index: int,
    instance_root: Path,
) -> EpisodeRecord:
    """Run one exact admitted Task through capture, reopen, checker, and Reward."""

    authority = read_task_pack_artifact(Path(task_pack_path), expected_task_pack_id)
    if authority.public.release_id != prepared.identity.release_id:
        raise TaskFoundryError(
            "task_release_mismatch", "TaskPack belongs to another prepared release"
        )
    task, branch_task = _decode_authority(authority)
    if isinstance(task, AtomTask):
        _verify_checker_preimage(prepared, task)
    elif isinstance(task, ForEachTask):
        _verify_foreach_task(prepared, task)
    else:
        _verify_if_task(prepared, task)
        if branch_task is None:
            raise AssertionError("validated If Task has no embedded branch")
        _verify_checker_preimage(prepared, branch_task)
    policy_spec = policy_driver.policy_spec
    if not isinstance(policy_spec, PolicySpec):
        raise ValueError("PolicyDriver policy_spec must be a PolicySpec")
    request = EpisodeRequest(
        prepared.identity.release_id,
        expected_task_pack_id,
        authority.public.task_id,
        policy_spec.policy_id,
        rollout_index,
    )
    native_instance_id = _document_digest(
        {
            "format": "native-episode-instance/1",
            "request_id": request.request_id,
            "nonce": uuid.uuid4().hex,
        }
    )
    instance = Path(instance_root)
    events: list[LifecycleEvent] = []
    acting: OpenPreparedSession | None = None
    capture: PublicEpisodeCapture | None = None
    lifecycle_defect: EpisodeDefect | None = None
    pre_close_facts: JSONValue | None = None
    post_reopen_facts: JSONValue | None = None
    checker_documents: JSONObject | None = None
    reopened_session_id: str | None = None
    condition_pair: tuple[ConditionCheckRequest, ConditionCheckResult] | None = None
    capture_entered = False

    try:
        acting = prepared.open(instance)
        acting_session_id = acting.identity.materialization_id
        events.append(LifecycleEvent(1, "acting_open", acting_session_id, native_instance_id))
        reset_observation = _json(
            acting.actor.reset(task.start_case.reset_input), "reset observation"
        )
        events.append(LifecycleEvent(2, "reset", acting_session_id, native_instance_id))
        before_facts = _json(acting.trusted.inspect(instance), "before facts")
        preflight_value, condition_pair = _preflight(acting, before_facts, task, branch_task)
        started_ns = time.monotonic_ns()
        capture_entered = True
        capture = capture_public_episode(
            actor=acting.actor,
            instruction=task.instruction,
            reset_observation=reset_observation,
            answer_schema=task.answer_schema,
            policy_driver=policy_driver,
        )
        policy_elapsed_ms = max(0, (time.monotonic_ns() - started_ns) // 1_000_000)
        events.append(
            LifecycleEvent(
                len(events) + 1, "capture_terminal", acting_session_id, native_instance_id
            )
        )
    except Exception:
        if acting is not None:
            acting.close()
        if not capture_entered:
            policy_driver.close()
        raise

    assert capture is not None
    acting_closed = False
    try:
        try:
            pre_close_facts = _json(acting.trusted.inspect(instance), "pre-close facts")
            events.append(
                LifecycleEvent(
                    len(events) + 1,
                    "pre_close_inspect",
                    acting_session_id,
                    native_instance_id,
                )
            )
        except Exception as exc:
            lifecycle_defect = _retain_defect(capture, lifecycle_defect, exc, "pre_close_inspect")
    finally:
        try:
            acting.close()
            acting_closed = True
            events.append(
                LifecycleEvent(
                    len(events) + 1,
                    "acting_close",
                    acting_session_id,
                    native_instance_id,
                )
            )
        except Exception as exc:
            lifecycle_defect = _retain_defect(capture, lifecycle_defect, exc, "acting_close")

    if acting_closed:
        reopened: OpenPreparedSession | None = None
        try:
            reopened = prepared.open(instance)
            reopened_session_id = reopened.identity.materialization_id
            if reopened_session_id == acting_session_id:
                lifecycle_defect = _primary_defect(
                    capture,
                    lifecycle_defect,
                    EpisodeDefect("evidence", "reopened_session_reused", "reopened_open"),
                )
                reopened_session_id = None
            else:
                events.append(
                    LifecycleEvent(
                        len(events) + 1,
                        "reopened_open",
                        reopened_session_id,
                        native_instance_id,
                    )
                )
                try:
                    post_reopen_facts = _json(
                        reopened.trusted.inspect(instance), "post-reopen facts"
                    )
                    events.append(
                        LifecycleEvent(
                            len(events) + 1,
                            "post_reopen_inspect",
                            reopened_session_id,
                            native_instance_id,
                        )
                    )
                except Exception as exc:
                    lifecycle_defect = _retain_defect(
                        capture, lifecycle_defect, exc, "post_reopen_inspect"
                    )
                if post_reopen_facts is not None:
                    try:
                        checker_documents = _evaluate_checker(
                            reopened,
                            before_facts,
                            post_reopen_facts,
                            capture,
                            task,
                            preflight_value,
                            condition_pair,
                        )
                        events.append(
                            LifecycleEvent(
                                len(events) + 1,
                                "checker_evaluated",
                                reopened_session_id,
                                native_instance_id,
                            )
                        )
                    except Exception as exc:
                        lifecycle_defect = _retain_defect(
                            capture, lifecycle_defect, exc, "checker_evaluated"
                        )
        except Exception as exc:
            lifecycle_defect = _retain_defect(capture, lifecycle_defect, exc, "reopened_open")
        finally:
            if reopened is not None:
                try:
                    reopened.close()
                    if reopened_session_id is not None:
                        events.append(
                            LifecycleEvent(
                                len(events) + 1,
                                "reopened_close",
                                reopened_session_id,
                                native_instance_id,
                            )
                        )
                except Exception as exc:
                    lifecycle_defect = _retain_defect(
                        capture, lifecycle_defect, exc, "reopened_close"
                    )

    reload_evidence = _reload_projection(
        request,
        capture,
        lifecycle_defect,
        native_instance_id,
        acting_session_id,
        reopened_session_id,
        tuple(events),
        pre_close_facts,
        post_reopen_facts,
        checker_documents,
    )
    reward = _runtime_reward(capture, lifecycle_defect, tuple(events), checker_documents)
    return EpisodeRecord(
        request=request,
        policy_spec=policy_spec,
        capture=capture,
        policy_elapsed_ms=policy_elapsed_ms,
        native_instance_id=native_instance_id,
        acting_session_id=acting_session_id,
        reopened_session_id=reopened_session_id,
        lifecycle_events=tuple(events),
        before_facts_digest=_document_digest(before_facts),
        pre_close_facts_digest=(
            None if pre_close_facts is None else _document_digest(pre_close_facts)
        ),
        post_reopen_facts_digest=(
            None if post_reopen_facts is None else _document_digest(post_reopen_facts)
        ),
        goal_kind=authority.public.goal_kind,
        checker_documents=checker_documents,
        lifecycle_defect=lifecycle_defect,
        reload_evidence=reload_evidence,
        reward=reward,
    )


def _decode_authority(
    authority: TrustedTaskView,
) -> tuple[AtomTask | ForEachTask | IfTask, AtomTask | None]:
    document = authority.task_document
    kind = authority.public.goal_kind
    if kind == "atom":
        return _decode_atom(document, authority.public.task_id), None
    if kind == "foreach":
        foreach_task = ForEachTask(
            _string(document, "release_id"),
            start_case_from_document(document.get("start_case")),
            _string(document, "capability_id"),
            _strings(document, "semantic_keys"),
            _objects(document, "public_descriptors"),
            _string(document, "selector_id"),
            _string(document, "checker_digest"),
            _string(document, "instruction"),
            _string(document, "instruction_digest"),
            _object(document.get("member_answer_schema"), "member_answer_schema"),
            _object(document.get("answer_schema"), "answer_schema"),
        )
        _require_exact_task(
            foreach_task.to_document(),
            foreach_task.task_id,
            document,
            authority.public.task_id,
        )
        return foreach_task, None
    if kind == "if":
        expected_branch = document.get("expected_branch")
        if expected_branch not in {"true", "false"}:
            raise TaskFoundryError("if_expected_branch_invalid", "If expected branch is invalid")
        if_task = IfTask(
            _string(document, "release_id"),
            start_case_from_document(document.get("start_case")),
            _string(document, "condition_id"),
            _string(document, "semantic_key"),
            _object(document.get("public_descriptor"), "public_descriptor"),
            _string(document, "true_capability_id"),
            _string(document, "false_capability_id"),
            cast(Literal["true", "false"], expected_branch),
            _string(document, "branch_task_id"),
            _string(document, "checker_digest"),
            _string(document, "instruction"),
            _string(document, "instruction_digest"),
            _object(document.get("answer_schema"), "answer_schema"),
        )
        _require_exact_task(
            if_task.to_document(), if_task.task_id, document, authority.public.task_id
        )
        branch_document = authority.branch_task_document
        if branch_document is None:
            raise TaskFoundryError(
                "task_pack_reader_if_branch_invalid", "If TaskPack has no embedded Atom branch"
            )
        branch = _decode_atom(branch_document, if_task.branch_task_id)
        return if_task, branch
    raise TaskFoundryError("task_pack_reader_format_unsupported", "Task goal kind is unsupported")


def _decode_atom(document: JSONObject, expected_task_id: str) -> AtomTask:
    task = AtomTask(
        _string(document, "release_id"),
        start_case_from_document(document.get("start_case")),
        _string(document, "capability_id"),
        _string(document, "semantic_key"),
        _object(document.get("public_descriptor"), "public_descriptor"),
        _string(document, "checker_digest"),
        _string(document, "instruction"),
        _string(document, "instruction_digest"),
        _object(document.get("answer_schema"), "answer_schema"),
    )
    _require_exact_task(task.to_document(), task.task_id, document, expected_task_id)
    return task


def _preflight(
    session: OpenPreparedSession,
    before_facts: JSONValue,
    task: AtomTask | ForEachTask | IfTask,
    branch_task: AtomTask | None,
) -> tuple[
    BindingCandidate | tuple[BindingCandidate, ...],
    tuple[ConditionCheckRequest, ConditionCheckResult] | None,
]:
    if isinstance(task, AtomTask):
        if task.capability_id not in {
            item.capability_id for item in session.trusted.capabilities()
        }:
            raise TaskFoundryError(
                "task_capability_missing", "live release no longer exposes the Task capability"
            )
        return _resolve_binding(session, task, before_facts), None
    if isinstance(task, ForEachTask):
        return _resolve_complete_selection(session, task, before_facts), None
    assert branch_task is not None
    binding = _resolve_binding(session, branch_task, before_facts)
    request = ConditionCheckRequest(task.condition_id, before_facts, binding.protected_binding, ())
    result = session.trusted.evaluate_condition(request)
    if result.status != task.expected_branch:
        raise TaskFoundryError("if_condition_drift", "Fresh If condition selected another branch")
    return binding, (request, result)


def _evaluate_checker(
    session: OpenPreparedSession,
    before_facts: JSONValue,
    post_reopen_facts: JSONValue,
    capture: PublicEpisodeCapture,
    task: AtomTask | ForEachTask | IfTask,
    preflight_value: BindingCandidate | tuple[BindingCandidate, ...],
    condition_pair: tuple[ConditionCheckRequest, ConditionCheckResult] | None,
) -> JSONObject:
    trace = _trace_from_capture(capture)
    completion = capture.completion
    final_answer = (
        completion.final_answer
        if completion is not None and completion.terminal_kind == "completed"
        else None
    )
    if isinstance(task, AtomTask):
        assert isinstance(preflight_value, BindingCandidate)
        request = AtomCheckRequest(
            task.capability_id,
            before_facts,
            post_reopen_facts,
            preflight_value.protected_binding,
            trace,
            final_answer,
            _context(
                task.capability_id,
                preflight_value.semantic_key,
                preflight_value.protected_binding,
            ),
        )
        result = _evaluate_report_atom(session, request, task.answer_schema)
        result_document = result.to_document()
        documents = _object(
            {"atom": {"request": request.to_document(), "result": result_document}},
            "Atom checker documents",
        )
        return documents
    if isinstance(task, ForEachTask):
        assert isinstance(preflight_value, tuple)
        raw_answers = final_answer.get("results") if final_answer is not None else None
        answers = raw_answers if isinstance(raw_answers, list) else []
        contexts = _contexts(task, preflight_value)
        members: list[JSONObject] = []
        for position, binding in enumerate(preflight_value):
            answer = answers[position] if position < len(answers) else None
            request = AtomCheckRequest(
                task.capability_id,
                before_facts,
                post_reopen_facts,
                binding.protected_binding,
                trace,
                answer,
                contexts[position],
            )
            result = _evaluate_report_atom(session, request, task.member_answer_schema)
            result_document = result.to_document()
            members.append({"request": request.to_document(), "result": result_document})
        return _object({"foreach": members}, "ForEach checker documents")
    assert isinstance(preflight_value, BindingCandidate)
    if condition_pair is None:
        raise AssertionError("validated If Task has no condition evidence")
    condition_request, condition_result = condition_pair
    request = AtomCheckRequest(
        task.branch_capability_id,
        before_facts,
        post_reopen_facts,
        preflight_value.protected_binding,
        trace,
        final_answer,
        _context(
            task.branch_capability_id,
            preflight_value.semantic_key,
            preflight_value.protected_binding,
        ),
    )
    result = _evaluate_report_atom(session, request, task.answer_schema)
    result_document = result.to_document()
    condition_document = condition_result.to_document()
    return {
        "if": {
            "expected_branch": task.expected_branch,
            "condition": {
                "request": condition_request.to_document(),
                "result": condition_document,
            },
            "branch": {"request": request.to_document(), "result": result_document},
        }
    }


def _reload_projection(
    request: EpisodeRequest,
    capture: PublicEpisodeCapture,
    lifecycle_defect: EpisodeDefect | None,
    native_instance_id: str,
    acting_session_id: str,
    reopened_session_id: str | None,
    events: tuple[LifecycleEvent, ...],
    pre_close_facts: JSONValue | None,
    post_reopen_facts: JSONValue | None,
    checker_documents: JSONObject | None,
) -> ReloadEvidence | None:
    completion = capture.completion
    if (
        capture.defect is not None
        or lifecycle_defect is not None
        or completion is None
        or completion.terminal_kind != "completed"
        or tuple(item.kind for item in events) != _COMPLETE_LIFECYCLE
        or reopened_session_id is None
        or pre_close_facts is None
        or post_reopen_facts is None
        or checker_documents is None
    ):
        return None
    legacy_events = tuple(
        LifecycleEvent(
            item.seq,
            "episode_complete" if item.kind == "capture_terminal" else item.kind,
            item.session_id,
            item.native_instance_id,
        )
        for item in events
    )
    legacy_attempt_id = _document_digest(
        {
            "format": "public-task-attempt/1",
            "release_id": request.release_id,
            "task_id": request.task_id,
            "native_instance_id": native_instance_id,
        }
    )
    return ReloadEvidence(
        request.release_id,
        request.task_id,
        legacy_attempt_id,
        native_instance_id,
        acting_session_id,
        reopened_session_id,
        legacy_events,
        _document_digest(pre_close_facts),
        _document_digest(post_reopen_facts),
        _document_digest(_checker_result_projection(checker_documents)),
    )


def _runtime_reward(
    capture: PublicEpisodeCapture,
    lifecycle_defect: EpisodeDefect | None,
    events: tuple[LifecycleEvent, ...],
    checker_documents: JSONObject | None,
) -> RewardOutcome:
    defect = capture.defect or lifecycle_defect
    if defect is not None:
        return RewardOutcome("abstain", None, defect.owner, defect.code)
    if tuple(item.kind for item in events) != _COMPLETE_LIFECYCLE or checker_documents is None:
        raise ValueError("incomplete trustworthy lifecycle requires an explicit defect")
    completion = capture.completion
    if (
        completion is not None
        and completion.terminal_kind == "completed"
        and _checker_satisfied(checker_documents)
    ):
        return RewardOutcome("verified_success", 1.0, None, None)
    return RewardOutcome("verified_failure", 0.0, None, None)


def _checker_satisfied(documents: JSONObject) -> bool:
    if set(documents) == {"atom"}:
        value = documents["atom"]
        return isinstance(value, dict) and _result_satisfied(value.get("result"))
    if set(documents) == {"foreach"}:
        values = documents["foreach"]
        return (
            isinstance(values, list)
            and bool(values)
            and all(
                isinstance(item, dict) and _result_satisfied(item.get("result")) for item in values
            )
        )
    if set(documents) == {"if"}:
        value = documents["if"]
        if not isinstance(value, dict) or set(value) != {
            "expected_branch",
            "condition",
            "branch",
        }:
            return False
        expected = value["expected_branch"]
        condition = value["condition"]
        branch = value["branch"]
        if not isinstance(condition, dict):
            return False
        raw_condition_result = condition.get("result")
        if not isinstance(raw_condition_result, dict):
            return False
        condition_result = raw_condition_result
        return (
            expected in {"true", "false"}
            and condition_result.get("status") == expected
            and isinstance(branch, dict)
            and _result_satisfied(branch.get("result"))
        )
    return False


def _result_satisfied(value: Any) -> bool:
    return isinstance(value, dict) and value.get("satisfied") is True


def _validate_lifecycle(record: EpisodeRecord) -> None:
    events = record.lifecycle_events
    if not isinstance(events, tuple) or any(
        not isinstance(item, LifecycleEvent) for item in events
    ):
        raise ValueError("lifecycle_events must be LifecycleEvent values")
    if tuple(item.seq for item in events) != tuple(range(1, len(events) + 1)):
        raise ValueError("lifecycle events must be contiguous")
    actual = tuple(item.kind for item in events)
    if actual[:3] != _COMPLETE_LIFECYCLE[:3]:
        raise ValueError("Episode lifecycle must reach a public capture terminal")
    positions = [_COMPLETE_LIFECYCLE.index(kind) for kind in actual]
    if positions != sorted(set(positions)):
        raise ValueError("Episode lifecycle order is invalid")
    if any(item.native_instance_id != record.native_instance_id for item in events):
        raise ValueError("Episode lifecycle crossed native instances")
    for item in events:
        if item.kind in _COMPLETE_LIFECYCLE[:5]:
            if item.session_id != record.acting_session_id:
                raise ValueError("acting lifecycle event belongs to another session")
        elif record.reopened_session_id is None or item.session_id != record.reopened_session_id:
            raise ValueError("reopened lifecycle event belongs to another session")
    kinds = set(actual)
    if ("pre_close_inspect" in kinds) != (record.pre_close_facts_digest is not None):
        raise ValueError("pre-close facts and lifecycle event disagree")
    if ("post_reopen_inspect" in kinds) != (record.post_reopen_facts_digest is not None):
        raise ValueError("post-reopen facts and lifecycle event disagree")
    if ("checker_evaluated" in kinds) != (record.checker_documents is not None):
        raise ValueError("checker documents and lifecycle event disagree")


def _validate_reload(record: EpisodeRecord) -> None:
    completion = record.capture.completion
    eligible = (
        record.capture.defect is None
        and record.lifecycle_defect is None
        and completion is not None
        and completion.terminal_kind == "completed"
        and tuple(item.kind for item in record.lifecycle_events) == _COMPLETE_LIFECYCLE
    )
    if eligible != (record.reload_evidence is not None):
        raise ValueError("legacy ReloadEvidence eligibility is inconsistent")
    evidence = record.reload_evidence
    if evidence is None:
        return
    if (
        evidence.release_id != record.request.release_id
        or evidence.task_id != record.request.task_id
        or evidence.native_instance_id != record.native_instance_id
        or evidence.acting_session_id != record.acting_session_id
        or evidence.reopened_session_id != record.reopened_session_id
        or evidence.pre_close_facts_digest != record.pre_close_facts_digest
        or evidence.post_reopen_facts_digest != record.post_reopen_facts_digest
    ):
        raise ValueError("ReloadEvidence differs from the Episode lifecycle")
    assert record.checker_documents is not None
    if evidence.post_reopen_checker_result_digest != _document_digest(
        _checker_result_projection(record.checker_documents)
    ):
        raise ValueError("ReloadEvidence checker digest differs from the Episode checker")


def _checker_result_projection(documents: JSONObject) -> JSONObject:
    if set(documents) == {"atom"}:
        atom = _object(documents["atom"], "Atom checker documents")
        return _object(atom.get("result"), "Atom checker result")
    if set(documents) == {"foreach"}:
        members = documents["foreach"]
        if not isinstance(members, list):
            raise ValueError("ForEach checker documents must be an array")
        return _object(
            {
                "member_results": [
                    _object(member, "ForEach checker member")["result"] for member in members
                ]
            },
            "ForEach checker results",
        )
    if set(documents) == {"if"}:
        grouped = _object(documents["if"], "If checker documents")
        condition = _object(grouped.get("condition"), "If condition documents")
        branch = _object(grouped.get("branch"), "If branch documents")
        return _object(
            {
                "condition_result": condition.get("result"),
                "branch_result": branch.get("result"),
            },
            "If checker results",
        )
    raise ValueError("checker documents have an invalid goal kind")


def _retain_defect(
    capture: PublicEpisodeCapture,
    current: EpisodeDefect | None,
    exc: Exception,
    phase: str,
) -> EpisodeDefect | None:
    classified = _classify_exception(exc, phase)
    if classified is None:
        raise exc
    return _primary_defect(capture, current, classified)


def _primary_defect(
    capture: PublicEpisodeCapture,
    current: EpisodeDefect | None,
    candidate: EpisodeDefect,
) -> EpisodeDefect | None:
    if capture.defect is not None:
        return None
    return current or candidate


def _classify_exception(exc: Exception, phase: str) -> EpisodeDefect | None:
    if isinstance(exc, PreparationExecutionError):
        owners = {
            "EnvironmentDefect": "environment",
            "InfrastructureFailure": "infrastructure",
            "SemanticsDefect": "semantics",
            "VerifierDefect": "verifier",
        }
        return EpisodeDefect(cast(Any, owners[exc.kind]), exc.code, phase)
    if isinstance(exc, TaskFoundryError):
        return EpisodeDefect("verifier", exc.code, phase)
    if isinstance(exc, SemanticsContractError):
        owner: DefectOwner = "verifier" if phase == "checker_evaluated" else "semantics"
        return EpisodeDefect(owner, f"{phase}_contract_invalid", phase)
    if isinstance(exc, PreparationContractError):
        return EpisodeDefect("evidence", f"{phase}_contract_invalid", phase)
    if isinstance(exc, OSError):
        return EpisodeDefect("infrastructure", f"{phase}_io_failed", phase)
    return None


def _require_exact_task(
    actual_document: JSONObject,
    actual_id: str,
    expected_document: JSONObject,
    expected_id: str,
) -> None:
    if actual_document != expected_document or actual_id != expected_id:
        raise TaskFoundryError(
            "task_pack_runtime_decode_mismatch",
            "Task constructor projection differs from the verified TaskPack",
        )


def _string(document: JSONObject, key: str) -> str:
    value = document.get(key)
    if not isinstance(value, str):
        raise TaskFoundryError("task_pack_runtime_decode_invalid", f"{key} must be text")
    return value


def _strings(document: JSONObject, key: str) -> tuple[str, ...]:
    value = document.get(key)
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise TaskFoundryError("task_pack_runtime_decode_invalid", f"{key} must be text values")
    return tuple(cast(list[str], value))


def _objects(document: JSONObject, key: str) -> tuple[JSONObject, ...]:
    value = document.get(key)
    if not isinstance(value, list):
        raise TaskFoundryError("task_pack_runtime_decode_invalid", f"{key} must be objects")
    return tuple(_object(item, key) for item in value)


def _document_digest(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _json(value: Any, role: str) -> JSONValue:
    if not is_json_value(value):
        raise ValueError(f"{role} must be JSON")
    return cast(JSONValue, json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False)))


def _object(value: Any, role: str) -> JSONObject:
    copied = _json(value, role)
    if not is_json_object(copied):
        raise ValueError(f"{role} must be a JSON object")
    return cast(JSONObject, copied)


def _digest(value: Any, role: str) -> None:
    if not isinstance(value, str) or len(value) != 64 or any(item not in _HEX for item in value):
        raise ValueError(f"{role} must be a sha256 digest")


__all__ = ["EpisodeRecord", "run_task_episode"]
