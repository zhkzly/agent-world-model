"""S4 teacher-cohort contracts and lossless SFT row projection."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from agent_env_foundry.environment import JSONObject, JSONValue
from agent_env_foundry.episode_batch import EpisodeBatchManifest
from agent_env_foundry.episode_runtime import read_episode_bundle
from agent_env_foundry.episodes import PolicySpec, PublicEpisodeInput, TrainingEpisodeView
from agent_env_foundry.jsonvalue import is_json_object
from agent_env_foundry.public_agent import PUBLIC_AGENT_PROMPT_DIGEST
from agent_env_foundry.release import canonical_bytes

_HEX = frozenset("0123456789abcdef")
_CONFIG_KEYS = {
    "format",
    "release_id",
    "corpus_id",
    "teacher_policy",
    "rollouts_per_task",
    "target_model",
    "verl_commit",
}
_TEACHER_KEYS = {
    "format",
    "model_id",
    "driver_id",
    "driver_version",
    "route_id",
    "system_prompt_digest",
    "max_provider_turns",
}
_TARGET_KEYS = {
    "model_id",
    "revision",
    "tokenizer_id",
    "tokenizer_revision",
    "chat_template_source",
    "continuous_token_model_family",
    "tool_parser",
}
_COHORT_KEYS = {
    "format",
    "config_digest",
    "batch_id",
    "corpus_id",
    "release_id",
    "policy_id",
    "primary_sft_episode_ids",
    "cohort_id",
}
_BATCH_KEYS = {
    "format",
    "corpus_id",
    "release_id",
    "policy_id",
    "rollouts_per_task",
    "results",
    "aggregates",
    "batch_id",
}


class LearningDataError(ValueError):
    """The current S4 configuration or cohort violates its trust contract."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


@dataclass(frozen=True, slots=True)
class S4CoreConfig:
    release_id: str
    corpus_id: str
    teacher_policy: PolicySpec
    rollouts_per_task: int
    target_model_id: str
    target_model_revision: str
    target_tokenizer_id: str
    target_tokenizer_revision: str
    target_chat_template_source: str
    continuous_token_model_family: str
    tool_parser: str
    verl_commit: str

    def __post_init__(self) -> None:
        _digest(self.release_id, "release_id")
        _digest(self.corpus_id, "corpus_id")
        if not isinstance(self.teacher_policy, PolicySpec):
            raise LearningDataError("CONFIG_INVALID", "teacher_policy must be a PolicySpec")
        _positive(self.rollouts_per_task, "rollouts_per_task")
        _text(self.target_model_id, "target_model.model_id")
        _git_sha(self.target_model_revision, "target_model.revision")
        _text(self.target_tokenizer_id, "target_model.tokenizer_id")
        _git_sha(self.target_tokenizer_revision, "target_model.tokenizer_revision")
        _text(self.target_chat_template_source, "target_model.chat_template_source")
        _text(
            self.continuous_token_model_family,
            "target_model.continuous_token_model_family",
        )
        _text(self.tool_parser, "target_model.tool_parser")
        _git_sha(self.verl_commit, "verl_commit")

    @property
    def config_digest(self) -> str:
        return hashlib.sha256(canonical_bytes(self.to_document())).hexdigest()

    def to_document(self) -> JSONObject:
        return {
            "format": "s4-core-config/1",
            "release_id": self.release_id,
            "corpus_id": self.corpus_id,
            "teacher_policy": self.teacher_policy.to_document(),
            "rollouts_per_task": self.rollouts_per_task,
            "target_model": {
                "model_id": self.target_model_id,
                "revision": self.target_model_revision,
                "tokenizer_id": self.target_tokenizer_id,
                "tokenizer_revision": self.target_tokenizer_revision,
                "chat_template_source": self.target_chat_template_source,
                "continuous_token_model_family": self.continuous_token_model_family,
                "tool_parser": self.tool_parser,
            },
            "verl_commit": self.verl_commit,
        }


@dataclass(frozen=True, slots=True)
class TeacherCohort:
    config_digest: str
    batch_id: str
    corpus_id: str
    release_id: str
    policy_id: str
    primary_sft_episode_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        for value, role in (
            (self.config_digest, "config_digest"),
            (self.batch_id, "batch_id"),
            (self.corpus_id, "corpus_id"),
            (self.release_id, "release_id"),
            (self.policy_id, "policy_id"),
        ):
            _digest(value, role)
        if not isinstance(self.primary_sft_episode_ids, tuple):
            raise LearningDataError("COHORT_INVALID", "primary_sft_episode_ids must be a tuple")
        for episode_id in self.primary_sft_episode_ids:
            _digest(episode_id, "cohort episode_id")
        if len(self.primary_sft_episode_ids) != len(set(self.primary_sft_episode_ids)):
            raise LearningDataError("COHORT_INVALID", "primary Episode IDs contain a duplicate")
        if not self.primary_sft_episode_ids:
            raise LearningDataError(
                "DATA_INSUFFICIENT", "primary_sft_episode_ids contains no verified success"
            )

    @property
    def cohort_id(self) -> str:
        return hashlib.sha256(canonical_bytes(self._preimage())).hexdigest()

    def _preimage(self) -> JSONObject:
        return {
            "format": "teacher-cohort/1",
            "config_digest": self.config_digest,
            "batch_id": self.batch_id,
            "corpus_id": self.corpus_id,
            "release_id": self.release_id,
            "policy_id": self.policy_id,
            "primary_sft_episode_ids": list(self.primary_sft_episode_ids),
        }

    def to_document(self) -> JSONObject:
        return {**self._preimage(), "cohort_id": self.cohort_id}


def read_s4_core_config(path: Path) -> S4CoreConfig:
    """Decode the semantic S4 config at ``path``."""

    document = _read_canonical_object(Path(path), "S4 core config")
    if set(document) != _CONFIG_KEYS or document.get("format") != "s4-core-config/1":
        raise LearningDataError("CONFIG_INVALID", "S4 core config has an invalid current shape")
    teacher = _object(document.get("teacher_policy"), "teacher_policy")
    if set(teacher) != _TEACHER_KEYS or teacher.get("format") != "policy-spec/1":
        raise LearningDataError("CONFIG_INVALID", "teacher_policy has an invalid current shape")
    target = _object(document.get("target_model"), "target_model")
    if set(target) != _TARGET_KEYS:
        raise LearningDataError("CONFIG_INVALID", "target_model has an invalid current shape")
    try:
        config = S4CoreConfig(
            cast(str, document["release_id"]),
            cast(str, document["corpus_id"]),
            PolicySpec(
                cast(str, teacher["model_id"]),
                cast(str, teacher["driver_id"]),
                cast(str, teacher["driver_version"]),
                cast(str, teacher["route_id"]),
                cast(str, teacher["system_prompt_digest"]),
                cast(int, teacher["max_provider_turns"]),
            ),
            cast(int, document["rollouts_per_task"]),
            cast(str, target["model_id"]),
            cast(str, target["revision"]),
            cast(str, target["tokenizer_id"]),
            cast(str, target["tokenizer_revision"]),
            cast(str, target["chat_template_source"]),
            cast(str, target["continuous_token_model_family"]),
            cast(str, target["tool_parser"]),
            cast(str, document["verl_commit"]),
        )
    except (TypeError, ValueError) as exc:
        if isinstance(exc, LearningDataError):
            raise
        raise LearningDataError(
            "CONFIG_INVALID", f"S4 core config value is invalid: {type(exc).__name__}: {exc}"
        ) from exc
    if config.to_document() != document:
        raise LearningDataError("CONFIG_INVALID", "S4 core config differs from its projection")
    _require_primary_teacher(config.teacher_policy)
    return config


def write_teacher_cohort(output_root: Path, cohort: TeacherCohort) -> Path:
    """Write the one CP0 cohort file."""

    if not isinstance(cohort, TeacherCohort):
        raise LearningDataError("COHORT_INVALID", "cohort must be a TeacherCohort")
    root = Path(output_root)
    path = root / "TeacherCohort.json"
    if root.is_symlink() or not root.is_dir():
        raise LearningDataError(
            "COHORT_INVALID", "cohort output root must be an ordinary directory"
        )
    if path.exists() or path.is_symlink():
        raise LearningDataError("COHORT_FINAL", "TeacherCohort.json already exists")
    path.write_bytes(canonical_bytes(cohort.to_document()))
    return path


def read_teacher_cohort(
    output_root: Path,
    config: S4CoreConfig,
) -> TeacherCohort:
    """Cold-read the one CP0 cohort from only its output root and semantic config."""

    root = Path(output_root)
    path = root / "TeacherCohort.json"
    if root.is_symlink() or not root.is_dir() or path.is_symlink() or not path.is_file():
        raise LearningDataError(
            "COHORT_INVALID", "TeacherCohort must be an ordinary file under its output root"
        )
    document = _read_canonical_object(path, "TeacherCohort")
    if set(document) != _COHORT_KEYS or document.get("format") != "teacher-cohort/1":
        raise LearningDataError("COHORT_INVALID", "TeacherCohort has an invalid current shape")
    primary = document.get("primary_sft_episode_ids")
    if not isinstance(primary, list):
        raise LearningDataError(
            "COHORT_INVALID", "TeacherCohort primary_sft_episode_ids must be an array"
        )
    cohort = TeacherCohort(
        cast(str, document["config_digest"]),
        cast(str, document["batch_id"]),
        cast(str, document["corpus_id"]),
        cast(str, document["release_id"]),
        cast(str, document["policy_id"]),
        tuple(cast(list[str], primary)),
    )
    if cohort.to_document() != document:
        raise LearningDataError("COHORT_INVALID", "TeacherCohort cohort_id is invalid")
    manifest, views = _read_persisted_manifest_views(root, cohort.batch_id)
    expected = select_teacher_cohort(config, manifest, views)
    for field in ("config_digest", "batch_id", "corpus_id", "release_id", "policy_id"):
        if getattr(cohort, field) != getattr(expected, field):
            raise LearningDataError(
                "COHORT_MISMATCH", f"TeacherCohort {field} differs from expected authority"
            )
    if cohort != expected:
        raise LearningDataError(
            "COHORT_MISMATCH", "TeacherCohort primary selection differs from cold views"
        )
    return cohort


def _read_persisted_manifest_views(
    output_root: Path,
    batch_id: str,
) -> tuple[EpisodeBatchManifest, tuple[TrainingEpisodeView, ...]]:
    """Read one exact persisted S3 manifest and its public cold Episode views."""

    _digest(batch_id, "batch_id")
    root = Path(output_root)
    batches = root / "batches"
    directory = batches / batch_id
    path = directory / "EpisodeBatchManifest.json"
    if (
        root.is_symlink()
        or batches.is_symlink()
        or directory.is_symlink()
        or path.is_symlink()
        or not root.is_dir()
        or not batches.is_dir()
        or not directory.is_dir()
        or not path.is_file()
    ):
        raise LearningDataError(
            "BATCH_INVALID",
            "persisted EpisodeBatchManifest path must use ordinary directories and a file",
        )
    document = _read_canonical_object(path, "EpisodeBatchManifest")
    if set(document) != _BATCH_KEYS or document.get("format") != "episode-batch-manifest/1":
        raise LearningDataError(
            "BATCH_INVALID", "EpisodeBatchManifest has an invalid current shape"
        )
    raw_results = document.get("results")
    if not isinstance(raw_results, list) or not is_json_object(document.get("aggregates")):
        raise LearningDataError(
            "BATCH_INVALID", "EpisodeBatchManifest results or aggregates are invalid"
        )
    try:
        manifest = EpisodeBatchManifest(
            cast(str, document["corpus_id"]),
            cast(str, document["release_id"]),
            cast(str, document["policy_id"]),
            cast(int, document["rollouts_per_task"]),
            tuple(cast(JSONObject, item) for item in raw_results),
            cast(JSONObject, document["aggregates"]),
            cast(str, document["batch_id"]),
        )
    except (TypeError, ValueError) as exc:
        raise LearningDataError(
            "BATCH_INVALID",
            f"EpisodeBatchManifest value is invalid: {type(exc).__name__}: {exc}",
        ) from exc
    if manifest.to_document() != document:
        raise LearningDataError(
            "BATCH_INVALID", "EpisodeBatchManifest differs from its exact public projection"
        )
    if manifest.batch_id != batch_id:
        raise LearningDataError(
            "BATCH_MISMATCH", "persisted EpisodeBatchManifest differs from the requested batch_id"
        )
    views = tuple(
        read_episode_bundle(root, episode_id)
        for result in manifest.results
        if isinstance(episode_id := result["episode_id"], str)
    )
    return manifest, views


def select_teacher_cohort(
    config: S4CoreConfig,
    manifest: EpisodeBatchManifest,
    views: tuple[TrainingEpisodeView, ...],
) -> TeacherCohort:
    """Select the public cold views for the current formal teacher cohort."""

    if not isinstance(config, S4CoreConfig):
        raise LearningDataError("CONFIG_INVALID", "config must be an S4CoreConfig")
    if not isinstance(manifest, EpisodeBatchManifest):
        raise LearningDataError("BATCH_INVALID", "manifest must be an EpisodeBatchManifest")
    _require_primary_teacher(config.teacher_policy)
    bindings = (
        ("corpus_id", manifest.corpus_id, config.corpus_id),
        ("release_id", manifest.release_id, config.release_id),
        ("policy_id", manifest.policy_id, config.teacher_policy.policy_id),
        ("rollouts_per_task", manifest.rollouts_per_task, config.rollouts_per_task),
    )
    for role, actual, expected in bindings:
        if actual != expected:
            raise LearningDataError(
                "BATCH_MISMATCH", f"EpisodeBatchManifest {role} differs from S4 config"
            )

    slots: dict[str, list[int]] = {}
    episode_results: dict[str, JSONObject] = {}
    ordered_episode_ids: list[str] = []
    for result in manifest.results:
        task_pack_id = cast(str, result["task_pack_id"])
        slots.setdefault(task_pack_id, []).append(cast(int, result["rollout_index"]))
        episode_id = result["episode_id"]
        if isinstance(episode_id, str):
            episode_results[episode_id] = result
            ordered_episode_ids.append(episode_id)
    expected_slots = list(range(1, config.rollouts_per_task + 1))
    if any(sorted(indices) != expected_slots for indices in slots.values()):
        raise LearningDataError(
            "BATCH_INCOMPLETE", "EpisodeBatchManifest is missing requested rollout slots"
        )

    if not isinstance(views, tuple) or any(
        not isinstance(view, TrainingEpisodeView) for view in views
    ):
        raise LearningDataError("COHORT_INVALID", "views must be cold TrainingEpisodeView values")
    view_ids = [view.episode_id for view in views]
    if len(view_ids) != len(set(view_ids)):
        raise LearningDataError("COHORT_INVALID", "cold views contain a duplicate Episode ID")
    if set(view_ids) != set(ordered_episode_ids):
        raise LearningDataError(
            "COHORT_INVALID", "cold view Episode IDs must exactly match sealable batch Episodes"
        )
    by_id = {view.episode_id: view for view in views}
    for episode_id in ordered_episode_ids:
        result = episode_results[episode_id]
        view = by_id[episode_id]
        request = view.request
        if (
            view.request_id != result["request_id"]
            or request.release_id != manifest.release_id
            or request.policy_id != manifest.policy_id
            or request.task_pack_id != result["task_pack_id"]
            or request.rollout_index != result["rollout_index"]
        ):
            raise LearningDataError(
                "COHORT_INVALID", "cold TrainingEpisodeView differs from its batch result"
            )
    for disposition in ("verified_success", "verified_failure", "abstain"):
        count = sum(view.disposition == disposition for view in views)
        if manifest.aggregates.get(disposition) != count:
            raise LearningDataError(
                "BATCH_MISMATCH", "EpisodeBatchManifest disposition aggregates differ from views"
            )

    primary = tuple(
        episode_id
        for episode_id in ordered_episode_ids
        if by_id[episode_id].disposition == "verified_success" and by_id[episode_id].reward == 1.0
    )
    if not primary:
        raise LearningDataError(
            "DATA_INSUFFICIENT", "no cold verified-success Episode is eligible for primary SFT"
        )
    return TeacherCohort(
        config.config_digest,
        manifest.batch_id,
        manifest.corpus_id,
        manifest.release_id,
        manifest.policy_id,
        primary,
    )


def _sft_json_text(value: JSONValue) -> str:
    """Deterministic compact JSON text preserving the row projection key order.

    ``messages`` and ``tools`` travel to Parquet under this exact encoding so
    the pinned reader decodes them back to the pristine in-memory projection:
    no key sorting, because the target-template tool text must stay byte-equal
    to the in-memory render.
    """

    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def build_sft_rows(output_root: Path, config: S4CoreConfig) -> tuple[JSONObject, ...]:
    """Map the cold formal teacher cohort to native veRL multi-turn SFT rows.

    Each row carries exactly ``messages``, ``tools`` and ``source``:
    ``messages``/``tools`` are deterministic compact JSON strings (Parquet
    struct inference null-unions heterogeneous tool JSON), while ``source``
    stays the uniform native identity object. The pinned veRL
    ``MultiTurnSFTDataset`` owns target-template application and the
    assistant-only loss mask; Foundry emits no token IDs and no mask.
    """

    root = Path(output_root)
    cohort = read_teacher_cohort(root, config)
    return tuple(
        _sft_row(cohort, read_episode_bundle(root, episode_id))
        for episode_id in cohort.primary_sft_episode_ids
    )


def _sft_row(cohort: TeacherCohort, view: TrainingEpisodeView) -> JSONObject:
    completion = view.completion
    if (
        completion is None
        or completion.terminal_kind != "completed"
        or completion.final_answer is None
    ):
        raise LearningDataError(
            "SOURCE_INELIGIBLE", "primary SFT row requires a completed public final answer"
        )
    public_input = view.public_input
    messages: list[JSONValue] = [
        {"role": "system", "content": public_input.system_prompt},
        {"role": "user", "content": _user_content(public_input)},
    ]
    for turn in view.turns:
        calls = cast(list[JSONObject], turn["calls"])
        if not calls:
            continue
        pairs = [_tool_call_payload(call, view.episode_id) for call in calls]
        tool_calls: list[JSONValue] = [payload for payload, _observation in pairs]
        messages.append({"role": "assistant", "content": "", "tool_calls": tool_calls})
        messages.extend({"role": "tool", "content": observation} for _payload, observation in pairs)
    messages.append(
        {
            "role": "assistant",
            "content": canonical_bytes(completion.final_answer).decode(),
        }
    )
    request = view.request
    return {
        "messages": _sft_json_text(messages),
        "tools": _sft_json_text(
            [
                {
                    "type": "function",
                    "function": {
                        "name": spec["name"],
                        "description": spec["description"],
                        "parameters": spec["input_schema"],
                    },
                }
                for spec in public_input.tool_specs
            ]
        ),
        "source": {
            "cohort_id": cohort.cohort_id,
            "batch_id": cohort.batch_id,
            "episode_id": view.episode_id,
            "request_id": view.request_id,
            "release_id": request.release_id,
            "task_pack_id": request.task_pack_id,
            "policy_id": request.policy_id,
        },
    }


def _user_content(public_input: PublicEpisodeInput) -> str:
    """The same semantic object the S3 teacher received as its initial user message."""

    return canonical_bytes(
        {
            "instruction": public_input.instruction,
            "reset_observation": public_input.reset_observation,
        }
    ).decode()


def _tool_call_payload(call: JSONObject, episode_id: str) -> tuple[JSONObject, str]:
    """Return one native assistant tool call plus its public observation text."""

    call_id = call["call_id"]
    tool_name = call["tool_name"]
    arguments = call["parsed_arguments"]
    observation = call["observation"]
    if (
        call["dispatch_status"] != "dispatched"
        or not isinstance(call_id, str)
        or not isinstance(tool_name, str)
        or not is_json_object(arguments)
        or not is_json_object(observation)
    ):
        raise LearningDataError(
            "SOURCE_INELIGIBLE",
            f"primary SFT row {episode_id} requires every public call dispatched"
            " with validated arguments and a public observation",
        )
    payload: JSONObject = {
        "id": call_id,
        "type": "function",
        "function": {"name": tool_name, "arguments": arguments},
    }
    return payload, canonical_bytes(observation).decode()


def _require_primary_teacher(policy: PolicySpec) -> None:
    if (
        policy.driver_id != "openai-responses"
        or policy.driver_version != "1"
        or policy.route_id != "responses:local-8317"
        or policy.system_prompt_digest != PUBLIC_AGENT_PROMPT_DIGEST
    ):
        raise LearningDataError(
            "TEACHER_NOT_ALLOWED",
            "primary authority requires the frozen openai-responses/1 Responses teacher",
        )


def _read_canonical_object(path: Path, role: str) -> JSONObject:
    try:
        payload = path.read_bytes()
        raw = json.loads(payload)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise LearningDataError(
            "ARTIFACT_UNREADABLE",
            f"{role} at {path} is unreadable: {type(exc).__name__}: {exc}",
        ) from exc
    if not is_json_object(raw):
        raise LearningDataError("ARTIFACT_INVALID", f"{role} must be a JSON object")
    try:
        expected = canonical_bytes(raw)
    except Exception as exc:
        raise LearningDataError(
            "ARTIFACT_INVALID", f"{role} is not canonical JSON: {type(exc).__name__}: {exc}"
        ) from exc
    if payload != expected:
        raise LearningDataError("ARTIFACT_INVALID", f"{role} is not canonical JSON")
    return cast(JSONObject, raw)


def _object(value: Any, role: str) -> JSONObject:
    if not is_json_object(value):
        raise LearningDataError("CONFIG_INVALID", f"{role} must be a JSON object")
    return cast(JSONObject, value)


def _digest(value: Any, role: str) -> None:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in _HEX for character in value)
    ):
        raise LearningDataError("IDENTITY_INVALID", f"{role} must be a sha256 digest")


def _git_sha(value: Any, role: str) -> None:
    if (
        not isinstance(value, str)
        or len(value) != 40
        or any(character not in _HEX for character in value)
    ):
        raise LearningDataError("CONFIG_INVALID", f"{role} must be an exact git commit")


def _text(value: Any, role: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise LearningDataError("CONFIG_INVALID", f"{role} must be non-empty text")


def _positive(value: Any, role: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise LearningDataError("CONFIG_INVALID", f"{role} must be a positive integer")
