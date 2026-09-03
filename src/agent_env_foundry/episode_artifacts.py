"""Current checker-free S3 Episode records and paired cold artifact reader."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from agent_env_foundry.environment import JSONObject, JSONValue, ToolSpec
from agent_env_foundry.episodes import (
    EpisodeDefect,
    EpisodeRequest,
    EpisodeToolCall,
    PolicyCompletion,
    PolicySpec,
    PolicyTurn,
    PublicEpisodeCapture,
    PublicEpisodeInput,
    RewardOutcome,
    TrainingEpisodeView,
)
from agent_env_foundry.jsonvalue import is_json_object, is_json_value
from agent_env_foundry.release import canonical_bytes
from agent_env_foundry.task_goal import EvaluationResult

EPISODE_RECORD_FORMAT = "episode-record/2"
TRAINING_VIEW_FORMAT = "training-episode-view/2"

_RECORD_KEYS = {
    "format",
    "episode_id",
    "request",
    "policy",
    "materialization_id",
    "capture",
    "before_state",
    "post_reopen_state",
    "evaluation",
    "verification_defect",
    "reward",
}


@dataclass(frozen=True, slots=True)
class EpisodeRecord:
    request: EpisodeRequest
    policy: PolicySpec
    materialization_id: str
    capture: PublicEpisodeCapture
    before_state: JSONValue
    post_reopen_state: JSONValue | None
    evaluation: EvaluationResult | None
    verification_defect: EpisodeDefect | None
    reward: RewardOutcome

    def __post_init__(self) -> None:
        if not isinstance(self.request, EpisodeRequest):
            raise ValueError("request must be an EpisodeRequest")
        if not isinstance(self.policy, PolicySpec):
            raise ValueError("policy must be a PolicySpec")
        _digest(self.materialization_id, "materialization_id")
        if self.request.policy_id != self.policy.policy_id:
            raise ValueError("request policy_id differs from policy")
        if not isinstance(self.capture, PublicEpisodeCapture):
            raise ValueError("capture must be a PublicEpisodeCapture")
        prompt_digest = hashlib.sha256(self.capture.public_input.system_prompt.encode()).hexdigest()
        if prompt_digest != self.policy.system_prompt_digest:
            raise ValueError("capture prompt differs from policy")
        before = _snapshot_json(self.before_state, "before_state")
        after = (
            None
            if self.post_reopen_state is None
            else _snapshot_json(self.post_reopen_state, "post_reopen_state")
        )
        object.__setattr__(self, "before_state", before)
        object.__setattr__(self, "post_reopen_state", after)
        if self.evaluation is not None and not isinstance(self.evaluation, EvaluationResult):
            raise ValueError("evaluation must be an EvaluationResult or null")
        if self.verification_defect is not None and not isinstance(
            self.verification_defect, EpisodeDefect
        ):
            raise ValueError("verification_defect must be an EpisodeDefect or null")
        if not isinstance(self.reward, RewardOutcome):
            raise ValueError("reward must be a RewardOutcome")
        if (after is None) != (self.evaluation is None):
            raise ValueError("post_reopen_state and evaluation must both exist or both be null")
        if self.verification_defect is None and self.evaluation is None:
            raise ValueError("verification requires evaluation or a verification_defect")
        self._validate_reward()

    def _validate_reward(self) -> None:
        defect = self.capture.defect or self.verification_defect
        if defect is not None:
            if (
                self.reward.disposition != "abstain"
                or self.reward.reward is not None
                or self.reward.abstain_owner != defect.owner
                or self.reward.abstain_code != defect.code
            ):
                raise ValueError("reward contradicts Episode defect")
            return
        completion = self.capture.completion
        if completion is None or self.evaluation is None:
            raise ValueError("reward requires completion and evaluation")
        passed = completion.terminal_kind == "completed" and self.evaluation.passed
        expected_disposition = "verified_success" if passed else "verified_failure"
        expected_reward = 1.0 if passed else 0.0
        if self.reward.disposition != expected_disposition or self.reward.reward != expected_reward:
            raise ValueError("reward contradicts completion or evaluation")

    def preimage(self) -> JSONObject:
        return {
            "format": EPISODE_RECORD_FORMAT,
            "request": self.request.to_document(),
            "policy": self.policy.to_document(),
            "materialization_id": self.materialization_id,
            "capture": self.capture.to_document(),
            "before_state": _copy_json(self.before_state),
            "post_reopen_state": _copy_json(self.post_reopen_state),
            "evaluation": self.evaluation.to_document() if self.evaluation is not None else None,
            "verification_defect": (
                self.verification_defect.to_document()
                if self.verification_defect is not None
                else None
            ),
            "reward": self.reward.to_document(),
        }

    @property
    def episode_id(self) -> str:
        return _document_digest(self.preimage())

    def to_document(self) -> JSONObject:
        return {**self.preimage(), "episode_id": self.episode_id}


def training_view(record: EpisodeRecord) -> TrainingEpisodeView:
    """Derive the only public/S4 projection from a trusted Episode record."""

    if not isinstance(record, EpisodeRecord):
        raise TypeError("training_view requires an EpisodeRecord")
    turns = tuple(
        cast(
            JSONObject,
            {
                "turn_index": turn.turn_index,
                "calls": [call.to_document() for call in turn.calls],
                "raw_public_terminal": _copy_json(turn.raw_public_terminal),
            },
        )
        for turn in record.capture.turns
    )
    return TrainingEpisodeView(
        record.episode_id,
        record.request.request_id,
        record.request,
        record.capture.public_input,
        turns,
        record.capture.completion,
        record.reward.disposition,
        record.reward.reward,
    )


def write_episode_bundle(output_root: Path, record: EpisodeRecord) -> Path:
    """Write and immediately cold-verify one new trusted/public Episode pair."""

    if not isinstance(record, EpisodeRecord):
        raise TypeError("record must be an EpisodeRecord")
    root = _ordinary_directory(Path(output_root), "output_root")
    episodes = root / "episodes"
    if episodes.is_symlink():
        raise ValueError("episodes directory cannot be a symlink")
    episodes.mkdir(exist_ok=True)
    target = episodes / record.episode_id
    if target.exists() or target.is_symlink():
        raise ValueError("Episode directory already exists")
    target.mkdir()
    (target / "EpisodeRecord.json").write_bytes(canonical_bytes(record.to_document()))
    (target / "TrainingEpisodeView.json").write_bytes(
        canonical_bytes(training_view(record).to_document())
    )
    if read_episode_bundle(root, record.episode_id) != training_view(record):
        raise ValueError("written Episode bundle differs from its projection")
    return target


def read_episode_bundle(output_root: Path, episode_id: str) -> TrainingEpisodeView:
    """Cold-verify a paired bundle and return only its derived public view."""

    _digest(episode_id, "episode_id")
    root = _ordinary_directory(Path(output_root), "output_root")
    episodes = _ordinary_directory(root / "episodes", "episodes")
    directory = _ordinary_directory(episodes / episode_id, "Episode directory")
    names = {item.name for item in directory.iterdir()}
    if names != {"EpisodeRecord.json", "TrainingEpisodeView.json"}:
        raise ValueError("Episode bundle must contain exactly its record and training view")
    record_document = _read_canonical(directory / "EpisodeRecord.json", "EpisodeRecord")
    record = _record_from_document(record_document)
    if record.episode_id != episode_id:
        raise ValueError("Episode record identity differs from requested episode_id")
    view_document = _read_canonical(directory / "TrainingEpisodeView.json", "TrainingEpisodeView")
    expected = training_view(record)
    if view_document.get("format") != TRAINING_VIEW_FORMAT:
        raise ValueError("TrainingEpisodeView format is unsupported")
    if view_document != expected.to_document():
        raise ValueError("TrainingEpisodeView differs from its trusted projection")
    return expected


def _record_from_document(document: Any) -> EpisodeRecord:
    value = _exact(document, _RECORD_KEYS, "EpisodeRecord")
    if value["format"] != EPISODE_RECORD_FORMAT:
        raise ValueError("EpisodeRecord format is unsupported")
    record = EpisodeRecord(
        _request_from_document(value["request"]),
        _policy_from_document(value["policy"]),
        cast(str, value["materialization_id"]),
        _capture_from_document(value["capture"]),
        value["before_state"],
        value["post_reopen_state"],
        None if value["evaluation"] is None else _evaluation_from_document(value["evaluation"]),
        None
        if value["verification_defect"] is None
        else _defect_from_document(value["verification_defect"]),
        _reward_from_document(value["reward"]),
    )
    if value["episode_id"] != record.episode_id or record.to_document() != value:
        raise ValueError("EpisodeRecord identity or projection is invalid")
    return record


def _policy_from_document(document: Any) -> PolicySpec:
    value = _exact(
        document,
        {
            "format",
            "model_id",
            "driver_id",
            "driver_version",
            "route_id",
            "system_prompt_digest",
            "max_provider_turns",
        },
        "PolicySpec",
    )
    if value["format"] != "policy-spec/1":
        raise ValueError("PolicySpec format is unsupported")
    return PolicySpec(
        cast(str, value["model_id"]),
        cast(str, value["driver_id"]),
        cast(str, value["driver_version"]),
        cast(str, value["route_id"]),
        cast(str, value["system_prompt_digest"]),
        cast(int, value["max_provider_turns"]),
    )


def _request_from_document(document: Any) -> EpisodeRequest:
    value = _exact(
        document,
        {"format", "release_id", "task_pack_id", "task_id", "policy_id", "rollout_index"},
        "EpisodeRequest",
    )
    if value["format"] != "episode-request/1":
        raise ValueError("EpisodeRequest format is unsupported")
    return EpisodeRequest(
        cast(str, value["release_id"]),
        cast(str, value["task_pack_id"]),
        cast(str, value["task_id"]),
        cast(str, value["policy_id"]),
        cast(int, value["rollout_index"]),
    )


def _capture_from_document(document: Any) -> PublicEpisodeCapture:
    value = _exact(document, {"public_input", "turns", "completion", "defect"}, "capture")
    turns = _array(value["turns"], "capture turns")
    return PublicEpisodeCapture(
        _public_input_from_document(value["public_input"]),
        tuple(_turn_from_document(item) for item in turns),
        None if value["completion"] is None else _completion_from_document(value["completion"]),
        None if value["defect"] is None else _defect_from_document(value["defect"]),
    )


def _public_input_from_document(document: Any) -> PublicEpisodeInput:
    value = _exact(
        document,
        {"system_prompt", "instruction", "reset_observation", "tool_specs", "answer_schema"},
        "PublicEpisodeInput",
    )
    tools = _array(value["tool_specs"], "tool_specs")
    return PublicEpisodeInput(
        cast(str, value["system_prompt"]),
        cast(str, value["instruction"]),
        value["reset_observation"],
        tuple(cast(ToolSpec, item) for item in tools),
        cast(JSONObject, value["answer_schema"]),
    )


def _turn_from_document(document: Any) -> PolicyTurn:
    value = _exact(document, {"turn_index", "calls", "raw_public_terminal", "usage"}, "PolicyTurn")
    calls = _array(value["calls"], "turn calls")
    return PolicyTurn(
        cast(int, value["turn_index"]),
        tuple(_call_from_document(item) for item in calls),
        value["raw_public_terminal"],
        cast(JSONObject | None, value["usage"]),
    )


def _call_from_document(document: Any) -> EpisodeToolCall:
    value = _exact(
        document,
        {
            "raw_call_id",
            "raw_tool_name",
            "call_id",
            "tool_name",
            "raw_arguments",
            "parsed_arguments",
            "parse_status",
            "schema_status",
            "dispatch_status",
            "observation",
        },
        "EpisodeToolCall",
    )
    return EpisodeToolCall(
        value["raw_call_id"],
        value["raw_tool_name"],
        cast(str | None, value["call_id"]),
        cast(str | None, value["tool_name"]),
        value["raw_arguments"],
        cast(JSONObject | None, value["parsed_arguments"]),
        cast(str, value["parse_status"]),
        cast(str, value["schema_status"]),
        cast(str, value["dispatch_status"]),
        cast(JSONObject | None, value["observation"]),
    )


def _completion_from_document(document: Any) -> PolicyCompletion:
    value = _exact(document, {"terminal_kind", "final_answer", "terminal_code"}, "PolicyCompletion")
    return PolicyCompletion(
        cast(Any, value["terminal_kind"]),
        cast(JSONObject | None, value["final_answer"]),
        cast(str | None, value["terminal_code"]),
    )


def _defect_from_document(document: Any) -> EpisodeDefect:
    value = _exact(document, {"owner", "code", "phase"}, "EpisodeDefect")
    return EpisodeDefect(
        cast(Any, value["owner"]), cast(str, value["code"]), cast(str, value["phase"])
    )


def _reward_from_document(document: Any) -> RewardOutcome:
    value = _exact(
        document, {"disposition", "reward", "abstain_owner", "abstain_code"}, "RewardOutcome"
    )
    reward = value["reward"]
    if type(reward) is int and reward in {0, 1}:
        reward = float(reward)
    return RewardOutcome(
        cast(Any, value["disposition"]),
        cast(float | None, reward),
        cast(Any, value["abstain_owner"]),
        cast(str | None, value["abstain_code"]),
    )


def _evaluation_from_document(document: Any) -> EvaluationResult:
    value = _exact(
        document,
        {
            "passed",
            "reset",
            "before_state",
            "after_state",
            "answer_schema",
            "answer",
            "goal",
            "checked",
            "reason_codes",
        },
        "EvaluationResult",
    )
    checked = _text_array(value["checked"], "evaluation checked")
    reasons = _text_array(value["reason_codes"], "evaluation reason_codes")
    boolean_names = (
        "passed",
        "reset",
        "before_state",
        "after_state",
        "answer_schema",
        "answer",
        "goal",
    )
    booleans = [value[name] for name in boolean_names]
    if any(type(item) is not bool for item in booleans):
        raise ValueError("EvaluationResult status fields must be booleans")
    return EvaluationResult(
        passed=cast(bool, value["passed"]),
        reset=cast(bool, value["reset"]),
        before_state=cast(bool, value["before_state"]),
        after_state=cast(bool, value["after_state"]),
        answer_schema=cast(bool, value["answer_schema"]),
        answer=cast(bool, value["answer"]),
        goal=cast(bool, value["goal"]),
        checked=checked,
        reason_codes=reasons,
    )


def _ordinary_directory(path: Path, role: str) -> Path:
    if path.is_symlink() or not path.is_dir():
        raise ValueError(f"{role} must be an ordinary directory")
    return path.resolve()


def _read_canonical(path: Path, role: str) -> JSONObject:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{role} must be an ordinary file")
    try:
        payload = path.read_bytes()
        document = json.loads(payload)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError(f"{role} is unreadable: {type(exc).__name__}: {exc}") from exc
    if not is_json_object(document) or canonical_bytes(document) != payload:
        raise ValueError(f"{role} must contain canonical JSON")
    return cast(JSONObject, document)


def _exact(document: Any, keys: set[str], role: str) -> JSONObject:
    if not is_json_object(document) or set(document) != keys:
        raise ValueError(f"{role} has an invalid exact shape")
    return cast(JSONObject, document)


def _array(value: Any, role: str) -> list[JSONValue]:
    if not isinstance(value, list) or not all(is_json_value(item) for item in value):
        raise ValueError(f"{role} must be a JSON array")
    return cast(list[JSONValue], value)


def _text_array(value: Any, role: str) -> tuple[str, ...]:
    items = _array(value, role)
    if any(not isinstance(item, str) for item in items):
        raise ValueError(f"{role} must contain strings")
    return tuple(cast(list[str], items))


def _snapshot_json(value: Any, role: str) -> JSONValue:
    if not is_json_value(value):
        raise ValueError(f"{role} must be JSON")
    return cast(JSONValue, json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False)))


def _copy_json(value: JSONValue) -> JSONValue:
    return cast(JSONValue, json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False)))


def _document_digest(document: JSONObject) -> str:
    return hashlib.sha256(canonical_bytes(document)).hexdigest()


def _digest(value: Any, role: str) -> None:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError(f"{role} must be a sha256 digest")


__all__ = [
    "EPISODE_RECORD_FORMAT",
    "EpisodeRecord",
    "TRAINING_VIEW_FORMAT",
    "read_episode_bundle",
    "training_view",
    "write_episode_bundle",
]
