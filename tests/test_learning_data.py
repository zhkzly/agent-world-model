from __future__ import annotations

import json
import shutil
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
import scripts.s4_collect as s4_collect
import yaml

import agent_env_foundry.learning_data as learning_data
import test_episode_runtime as episode_fixtures
from agent_env_foundry.environment import JSONObject, ToolSpec
from agent_env_foundry.episode_batch import EpisodeBatchManifest
from agent_env_foundry.episode_runtime import run_task_episode, write_episode_bundle
from agent_env_foundry.episodes import (
    EpisodeRequest,
    PolicyCompletion,
    PolicySpec,
    PublicEpisodeInput,
    TrainingEpisodeView,
)
from agent_env_foundry.learning_data import (
    LearningDataError,
    S4CoreConfig,
    TeacherCohort,
    build_sft_rows,
    read_s4_core_config,
    read_teacher_cohort,
    select_teacher_cohort,
    write_teacher_cohort,
)
from agent_env_foundry.release import canonical_bytes

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "s4" / "responses_gold"
CORE_CONFIG = Path(__file__).parents[1] / "configs" / "s4" / "core.json"
VIEW_FILES = (
    "TrainingEpisodeView.json",
    "TrainingEpisodeView-c822a148.json",
    "TrainingEpisodeView-d6253c26.json",
)


def _gold_manifest() -> EpisodeBatchManifest:
    document = json.loads((FIXTURE_ROOT / "EpisodeBatchManifest.json").read_bytes())
    return EpisodeBatchManifest(
        document["corpus_id"],
        document["release_id"],
        document["policy_id"],
        document["rollouts_per_task"],
        tuple(cast(JSONObject, item) for item in document["results"]),
        cast(JSONObject, document["aggregates"]),
        document["batch_id"],
    )


def _gold_view(filename: str = VIEW_FILES[0]) -> TrainingEpisodeView:
    document = json.loads((FIXTURE_ROOT / filename).read_bytes())
    request = document["request"]
    public_input = document["public_input"]
    completion = document["completion"]
    resolved_completion = (
        None
        if completion is None
        else PolicyCompletion(
            completion["terminal_kind"],
            cast(JSONObject, completion["final_answer"]),
            completion["terminal_code"],
        )
    )
    reward = document["reward"]
    return TrainingEpisodeView(
        document["episode_id"],
        document["request_id"],
        EpisodeRequest(
            request["release_id"],
            request["task_pack_id"],
            request["task_id"],
            request["policy_id"],
            request["rollout_index"],
        ),
        PublicEpisodeInput(
            public_input["system_prompt"],
            public_input["instruction"],
            public_input["reset_observation"],
            tuple(cast(ToolSpec, item) for item in public_input["tool_specs"]),
            cast(JSONObject, public_input["answer_schema"]),
        ),
        tuple(cast(JSONObject, item) for item in document["turns"]),
        resolved_completion,
        cast(Any, document["disposition"]),
        cast(Any, None if reward is None else float(reward)),
    )


def _gold_views() -> tuple[TrainingEpisodeView, ...]:
    by_id = {view.episode_id: view for view in (_gold_view(name) for name in VIEW_FILES)}
    return tuple(by_id[cast(str, item["episode_id"])] for item in _gold_manifest().results)


def _real_policy() -> PolicySpec:
    return PolicySpec(
        "gpt-5.6-luna",
        "openai-responses",
        "1",
        "responses:local-8317",
        "79e1a505a050f69d8d5e1c83edf280794dc8a17b23d6379083bb201fbae53b16",
        12,
    )


def _real_config(
    *,
    teacher_policy: PolicySpec | None = None,
    rollouts_per_task: int = 1,
) -> S4CoreConfig:
    manifest = _gold_manifest()
    return S4CoreConfig(
        manifest.release_id,
        manifest.corpus_id,
        teacher_policy or _real_policy(),
        rollouts_per_task,
        "Qwen/Qwen3-0.6B",
        "c1899de289a04d12100db370d81485cdf75e47ca",
        "Qwen/Qwen3-0.6B",
        "c1899de289a04d12100db370d81485cdf75e47ca",
        "tokenizer_config.json",
        "qwen",
        "hermes",
        "483b8a009ba3a97563edee3a19887e4862b8094a",
    )


def _manifest_for_views(
    views: tuple[TrainingEpisodeView, ...],
    *,
    results: tuple[JSONObject, ...] | None = None,
    rollouts_per_task: int = 1,
    policy_id: str | None = None,
) -> EpisodeBatchManifest:
    original = _gold_manifest()
    resolved_results = original.results if results is None else results
    aggregates = cast(JSONObject, json.loads(json.dumps(original.aggregates)))
    aggregates["total_slots"] = len(resolved_results)
    aggregates["episode_count"] = sum(item["episode_id"] is not None for item in resolved_results)
    aggregates["blocked_count"] = sum(item["episode_id"] is None for item in resolved_results)
    for disposition in ("verified_success", "verified_failure", "abstain"):
        aggregates[disposition] = sum(view.disposition == disposition for view in views)
    blocked_counts: dict[str, int] = {}
    for item in resolved_results:
        owner = item["blocked_owner"]
        if isinstance(owner, str):
            blocked_counts[owner] = blocked_counts.get(owner, 0) + 1
    aggregates["blocked_owner_counts"] = blocked_counts
    return EpisodeBatchManifest(
        original.corpus_id,
        original.release_id,
        policy_id or original.policy_id,
        rollouts_per_task,
        resolved_results,
        aggregates,
    )


def _relocated_cold_output(
    tmp_path: Path,
) -> tuple[Path, S4CoreConfig, TeacherCohort]:
    producer = tmp_path / "producer"
    pack, pack_id, _task = episode_fixtures._write_pack(tmp_path, "atom")
    driver = episode_fixtures.Driver(episode_fixtures._completed(1, "{}"))
    driver._spec = _real_policy()
    record = run_task_episode(
        episode_fixtures.Prepared(),  # type: ignore[arg-type]
        pack,
        pack_id,
        policy_driver=driver,
        rollout_index=1,
        instance_root=tmp_path / "instance",
    )
    view = write_episode_bundle(producer, record)
    result: JSONObject = {
        "task_pack_id": record.request.task_pack_id,
        "rollout_index": record.request.rollout_index,
        "request_id": record.request.request_id,
        "episode_id": record.episode_id,
        "blocked_owner": None,
        "blocked_code": None,
        "blocked_phase": None,
    }
    aggregates: JSONObject = {
        "total_slots": 1,
        "episode_count": 1,
        "blocked_count": 0,
        "verified_success": 1,
        "verified_failure": 0,
        "abstain": 0,
        "attempted_calls": 1,
        "dispatched_calls": 1,
        "provider_turns": 2,
        "input_tokens": 0,
        "output_tokens": 0,
        "missing_usage_turns": 2,
        "policy_elapsed_ms": 0,
        "abstain_owner_counts": {},
        "blocked_owner_counts": {},
    }
    manifest = EpisodeBatchManifest(
        "b" * 64,
        record.request.release_id,
        record.request.policy_id,
        1,
        (result,),
        aggregates,
    )
    config = replace(
        _real_config(),
        release_id=manifest.release_id,
        corpus_id=manifest.corpus_id,
    )
    _publish_manifest(producer, manifest)
    cohort = select_teacher_cohort(config, manifest, (view,))
    write_teacher_cohort(producer, cohort)
    relocated = tmp_path / "relocated"
    shutil.copytree(producer, relocated)
    return relocated, config, cohort


def test_primary_cohort_rejects_scripted_policy() -> None:
    manifest = _gold_manifest()
    scripted = PolicySpec(
        "scripted-teacher",
        "scripted",
        "1",
        "scripted:test",
        "79e1a505a050f69d8d5e1c83edf280794dc8a17b23d6379083bb201fbae53b16",
        12,
    )
    config = S4CoreConfig(
        manifest.release_id,
        manifest.corpus_id,
        scripted,
        1,
        "Qwen/Qwen3-0.6B",
        "c1899de289a04d12100db370d81485cdf75e47ca",
        "Qwen/Qwen3-0.6B",
        "c1899de289a04d12100db370d81485cdf75e47ca",
        "tokenizer_config.json",
        "qwen",
        "hermes",
        "483b8a009ba3a97563edee3a19887e4862b8094a",
    )

    with pytest.raises(LearningDataError, match="Responses teacher"):
        select_teacher_cohort(config, manifest, (_gold_view(),))


def test_teacher_cohort_cold_reader_needs_no_transient_manifest_or_views(
    tmp_path: Path,
) -> None:
    relocated, config, expected = _relocated_cold_output(tmp_path)

    assert read_teacher_cohort(relocated, config=config) == expected


def test_teacher_cohort_current_schema_omits_producerless_analysis_ids() -> None:
    cohort = select_teacher_cohort(_real_config(), _gold_manifest(), _gold_views())

    assert "analysis_episode_ids" not in cohort.to_document()


def test_checked_in_core_config_is_exact_canonical_and_path_free(tmp_path: Path) -> None:
    config = read_s4_core_config(CORE_CONFIG)
    payload = CORE_CONFIG.read_bytes()
    document = json.loads(payload)

    assert payload == canonical_bytes(document)
    assert config.to_document() == document
    assert document == {
        "format": "s4-core-config/1",
        "release_id": "14331ac6e82e0ac79382d5c5e964c62f6cc9ece506f726299d0645594fbafe80",
        "corpus_id": "4fddce70a03b716de69041397b941c4e752e7bf969b8de27d387777ebaaa8344",
        "teacher_policy": _real_policy().to_document(),
        "rollouts_per_task": 1,
        "target_model": {
            "model_id": "Qwen/Qwen3-0.6B",
            "revision": "c1899de289a04d12100db370d81485cdf75e47ca",
            "tokenizer_id": "Qwen/Qwen3-0.6B",
            "tokenizer_revision": "c1899de289a04d12100db370d81485cdf75e47ca",
            "chat_template_source": "tokenizer_config.json",
            "continuous_token_model_family": "qwen",
            "tool_parser": "hermes",
        },
        "verl_commit": "483b8a009ba3a97563edee3a19887e4862b8094a",
    }
    assert not ({"release_root", "task_store_root", "corpus_manifest", "output"} & document.keys())

    relocated = tmp_path / "different-machine" / "semantic.json"
    relocated.parent.mkdir()
    relocated.write_bytes(payload)
    assert read_s4_core_config(relocated).config_digest == config.config_digest


def test_core_config_rejects_noncanonical_or_unknown_path_fields(tmp_path: Path) -> None:
    document = _real_config().to_document()
    noncanonical = tmp_path / "noncanonical.json"
    noncanonical.write_text(json.dumps(document, indent=2), encoding="utf-8")
    with pytest.raises(LearningDataError, match="canonical"):
        read_s4_core_config(noncanonical)

    document["output"] = "/tmp/machine-local"
    unknown = tmp_path / "unknown.json"
    unknown.write_bytes(canonical_bytes(document))
    with pytest.raises(LearningDataError, match="shape"):
        read_s4_core_config(unknown)


@pytest.mark.parametrize(
    "field",
    (
        "model_id",
        "tokenizer_id",
        "chat_template_source",
        "continuous_token_model_family",
        "tool_parser",
    ),
)
def test_core_config_rejects_blank_target_identity(tmp_path: Path, field: str) -> None:
    document = _real_config().to_document()
    target = cast(dict[str, Any], document["target_model"])
    target[field] = " "
    path = tmp_path / f"blank-{field}.json"
    path.write_bytes(canonical_bytes(document))

    with pytest.raises(LearningDataError, match="non-empty text"):
        read_s4_core_config(path)


@pytest.mark.parametrize("field", ("revision", "tokenizer_revision"))
def test_core_config_rejects_nonexact_target_revision(tmp_path: Path, field: str) -> None:
    document = _real_config().to_document()
    target = cast(dict[str, Any], document["target_model"])
    target[field] = "not-an-exact-revision"
    path = tmp_path / f"bad-{field}.json"
    path.write_bytes(canonical_bytes(document))

    with pytest.raises(LearningDataError, match="exact git commit"):
        read_s4_core_config(path)


def test_core_config_rejects_old_or_extended_target_shape(tmp_path: Path) -> None:
    document = _real_config().to_document()
    target = cast(dict[str, Any], document["target_model"])
    target.pop("tool_parser")
    old_shape = tmp_path / "old-target.json"
    old_shape.write_bytes(canonical_bytes(document))
    with pytest.raises(LearningDataError, match="target_model has an invalid current shape"):
        read_s4_core_config(old_shape)

    target["tool_parser"] = "hermes"
    target["future_family"] = "not-current"
    extended = tmp_path / "extended-target.json"
    extended.write_bytes(canonical_bytes(document))
    with pytest.raises(LearningDataError, match="target_model has an invalid current shape"):
        read_s4_core_config(extended)


def test_primary_cohort_rejects_wrong_route_before_manifest_binding() -> None:
    policy = replace(_real_policy(), route_id="responses:other")
    with pytest.raises(LearningDataError, match="Responses teacher"):
        select_teacher_cohort(_real_config(teacher_policy=policy), _gold_manifest(), _gold_views())


def test_primary_cohort_rejects_manifest_policy_mismatch() -> None:
    manifest = _manifest_for_views(_gold_views(), policy_id="a" * 64)
    with pytest.raises(LearningDataError, match="policy_id"):
        select_teacher_cohort(_real_config(), manifest, _gold_views())


def test_primary_is_every_success_in_exact_manifest_order() -> None:
    original = _gold_views()
    views = (
        original[0],
        replace(original[1], disposition="verified_failure", reward=0.0),
        replace(original[2], disposition="abstain", reward=None),
    )
    manifest = _manifest_for_views(views)

    cohort = select_teacher_cohort(_real_config(), manifest, tuple(reversed(views)))

    assert cohort.primary_sft_episode_ids == (views[0].episode_id,)


def test_655b_gold_batch_remains_positive_legal_structural_input() -> None:
    manifest = _gold_manifest()

    cohort = select_teacher_cohort(_real_config(), manifest, _gold_views())

    assert manifest.batch_id == "655b1fd8616a85037e55be83f55ea75ed1884f48670279da29907725c9410fcc"
    assert cohort.primary_sft_episode_ids == tuple(
        cast(str, result["episode_id"]) for result in manifest.results
    )


def test_empty_primary_is_data_insufficient() -> None:
    views = tuple(
        replace(view, disposition="verified_failure", reward=0.0) for view in _gold_views()
    )
    manifest = _manifest_for_views(views)

    with pytest.raises(LearningDataError, match="DATA_INSUFFICIENT") as raised:
        select_teacher_cohort(_real_config(), manifest, views)

    assert raised.value.code == "DATA_INSUFFICIENT"


def test_cohort_rejects_duplicate_missing_and_extra_episode_views() -> None:
    views = _gold_views()
    manifest = _gold_manifest()

    with pytest.raises(LearningDataError, match="duplicate"):
        select_teacher_cohort(_real_config(), manifest, (*views, views[0]))
    with pytest.raises(LearningDataError, match="exactly match"):
        select_teacher_cohort(_real_config(), manifest, views[:-1])
    extra = replace(views[0], episode_id="9" * 64)
    with pytest.raises(LearningDataError, match="exactly match"):
        select_teacher_cohort(_real_config(), manifest, (*views, extra))


def test_cohort_rejects_missing_requested_rollout_slot() -> None:
    views = _gold_views()
    manifest = _manifest_for_views(views, rollouts_per_task=2)

    with pytest.raises(LearningDataError, match="rollout slots"):
        select_teacher_cohort(_real_config(rollouts_per_task=2), manifest, views)


def test_cohort_rejects_episode_request_binding_drift() -> None:
    views = _gold_views()
    changed_request = replace(views[0].request, task_pack_id=views[1].request.task_pack_id)
    changed = replace(
        views[0],
        request=changed_request,
        request_id=changed_request.request_id,
    )

    with pytest.raises(LearningDataError, match="batch result"):
        select_teacher_cohort(_real_config(), _gold_manifest(), (changed, *views[1:]))


def test_teacher_cohort_is_deterministic_canonical_and_minimal(tmp_path: Path) -> None:
    config, manifest, views = _real_config(), _gold_manifest(), _gold_views()
    cohort = select_teacher_cohort(config, manifest, views)
    reordered = select_teacher_cohort(config, manifest, tuple(reversed(views)))
    assert reordered == cohort

    output = tmp_path / "published-batch"
    output.mkdir()
    path = write_teacher_cohort(output, cohort)
    document = json.loads(path.read_bytes())

    assert path.read_bytes() == canonical_bytes(document)
    assert document == cohort.to_document()
    assert set(document) == {
        "format",
        "config_digest",
        "batch_id",
        "corpus_id",
        "release_id",
        "policy_id",
        "primary_sft_episode_ids",
        "cohort_id",
    }
    assert not any("path" in key or "blocked" in key for key in document)
    _publish_manifest(output, manifest)
    with pytest.MonkeyPatch.context() as monkeypatch:
        by_id = {view.episode_id: view for view in views}
        monkeypatch.setattr(
            learning_data,
            "read_episode_bundle",
            lambda _root, episode_id: by_id[episode_id],
        )
        assert read_teacher_cohort(output, config) == cohort
    with pytest.raises(LearningDataError, match="already exists"):
        write_teacher_cohort(output, cohort)


def test_teacher_cohort_reader_binds_config_batch_and_content_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config, manifest, views = _real_config(), _gold_manifest(), _gold_views()
    cohort = select_teacher_cohort(config, manifest, views)
    output = tmp_path / "published-batch"
    output.mkdir()
    path = write_teacher_cohort(output, cohort)
    _publish_manifest(output, manifest)
    by_id = {view.episode_id: view for view in views}
    monkeypatch.setattr(
        learning_data,
        "read_episode_bundle",
        lambda _root, episode_id: by_id[episode_id],
    )

    wrong_config = replace(config, target_model_revision="0" * 40)
    with pytest.raises(LearningDataError, match="config_digest"):
        read_teacher_cohort(output, wrong_config)

    aggregates = cast(JSONObject, json.loads(json.dumps(manifest.aggregates)))
    aggregates["attempted_calls"] = cast(int, aggregates["attempted_calls"]) + 1
    wrong_manifest = EpisodeBatchManifest(
        manifest.corpus_id,
        manifest.release_id,
        manifest.policy_id,
        manifest.rollouts_per_task,
        manifest.results,
        aggregates,
    )
    manifest_path = output / "batches" / manifest.batch_id / "EpisodeBatchManifest.json"
    manifest_path.write_bytes(canonical_bytes(wrong_manifest.to_document()))
    with pytest.raises(LearningDataError, match="requested batch_id"):
        read_teacher_cohort(output, config)
    manifest_path.write_bytes(canonical_bytes(manifest.to_document()))

    document = json.loads(path.read_bytes())
    document["primary_sft_episode_ids"] = list(reversed(document["primary_sft_episode_ids"]))
    path.write_bytes(canonical_bytes(document))
    with pytest.raises(LearningDataError, match="cohort_id"):
        read_teacher_cohort(output, config)


def test_teacher_cohort_rejects_duplicate_primary_episode() -> None:
    cohort = select_teacher_cohort(_real_config(), _gold_manifest(), _gold_views())
    episode_id = cohort.primary_sft_episode_ids[0]
    with pytest.raises(LearningDataError, match="duplicate"):
        TeacherCohort(
            cohort.config_digest,
            cohort.batch_id,
            cohort.corpus_id,
            cohort.release_id,
            cohort.policy_id,
            (episode_id, episode_id),
        )


def _publish_manifest(
    output_root: Path,
    manifest: EpisodeBatchManifest,
    *,
    payload: bytes | None = None,
) -> None:
    path = output_root / "batches" / manifest.batch_id / "EpisodeBatchManifest.json"
    path.parent.mkdir(parents=True)
    path.write_bytes(payload if payload is not None else canonical_bytes(manifest.to_document()))


def test_collect_calls_exact_s3_batch_once_with_fresh_drivers_and_cold_views(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config, manifest, views = _real_config(), _gold_manifest(), _gold_views()
    view_by_id = {view.episode_id: view for view in views}
    prepared = SimpleNamespace(identity=SimpleNamespace(release_id=config.release_id))
    release_root = tmp_path / "release"
    task_store_root = tmp_path / "task-store"
    corpus_path = tmp_path / "CorpusManifest.json"
    output = tmp_path / "formal-teacher"
    prepare_calls: list[tuple[Path, Path]] = []
    batch_calls: list[tuple[Any, ...]] = []
    drivers: list[Any] = []
    cold_reads: list[tuple[str, bool]] = []
    boundary_calls: list[tuple[Path, str]] = []
    persisted_boundary = s4_collect._read_persisted_manifest_views

    def fake_prepare(path: Path, cache_root: Path) -> Any:
        prepare_calls.append((path, cache_root))
        return prepared

    def fake_driver(*, policy_spec: PolicySpec) -> Any:
        driver = SimpleNamespace(policy_spec=policy_spec)
        drivers.append(driver)
        return driver

    def fake_batch(
        received_prepared: Any,
        received_task_store: Path,
        received_corpus: Path,
        expected_corpus_id: str,
        received_output: Path,
        *,
        policy_spec: PolicySpec,
        policy_driver_factory: Any,
        rollouts_per_task: int,
    ) -> EpisodeBatchManifest:
        batch_calls.append(
            (
                received_prepared,
                received_task_store,
                received_corpus,
                expected_corpus_id,
                received_output,
                policy_spec,
                rollouts_per_task,
            )
        )
        assert not received_output.exists()
        received_output.mkdir()
        _publish_manifest(received_output, manifest)
        for _result in manifest.results:
            policy_driver_factory()
        return manifest

    def fake_read(root: Path, episode_id: str) -> TrainingEpisodeView:
        assert root == output
        cold_reads.append((episode_id, (root / "TeacherCohort.json").exists()))
        return view_by_id[episode_id]

    def tracked_boundary(
        root: Path,
        batch_id: str,
    ) -> tuple[EpisodeBatchManifest, tuple[TrainingEpisodeView, ...]]:
        boundary_calls.append((root, batch_id))
        return persisted_boundary(root, batch_id)

    monkeypatch.setattr(s4_collect, "prepare_release", fake_prepare)
    monkeypatch.setattr(s4_collect, "ResponsesPolicyDriver", fake_driver)
    monkeypatch.setattr(s4_collect, "run_episode_batch", fake_batch)
    monkeypatch.setattr(s4_collect, "_read_persisted_manifest_views", tracked_boundary)
    monkeypatch.setattr(learning_data, "read_episode_bundle", fake_read)

    cohort = s4_collect.collect(
        config_path=CORE_CONFIG,
        release_root=release_root,
        task_store_root=task_store_root,
        corpus_manifest_path=corpus_path,
        output_root=output,
    )

    assert len(prepare_calls) == 1
    assert prepare_calls[0][0] == release_root
    assert prepare_calls[0][1] != release_root
    assert len(batch_calls) == 1
    assert batch_calls[0] == (
        prepared,
        task_store_root,
        corpus_path,
        config.corpus_id,
        output,
        config.teacher_policy,
        config.rollouts_per_task,
    )
    assert len(drivers) == len(manifest.results)
    assert len({id(driver) for driver in drivers}) == len(drivers)
    assert all(driver.policy_spec == config.teacher_policy for driver in drivers)
    expected_episode_ids = [
        cast(str, result["episode_id"])
        for result in manifest.results
        if result["episode_id"] is not None
    ]
    assert boundary_calls == [(output, manifest.batch_id)]
    assert cold_reads == [
        *((episode_id, False) for episode_id in expected_episode_ids),
        *((episode_id, True) for episode_id in expected_episode_ids),
    ]
    assert cohort.primary_sft_episode_ids == tuple(expected_episode_ids)
    assert [path.name for path in output.iterdir() if path.is_file()] == ["TeacherCohort.json"]
    cohort_payload = (output / "TeacherCohort.json").read_bytes()
    assert cohort_payload == canonical_bytes(json.loads(cohort_payload))


def test_collect_rejects_manifest_byte_drift_before_cold_read_or_cohort(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config, manifest = _real_config(), _gold_manifest()
    output = tmp_path / "formal-teacher"
    batch_calls = 0

    def fake_batch(*args: Any, **kwargs: Any) -> EpisodeBatchManifest:
        nonlocal batch_calls
        batch_calls += 1
        output.mkdir()
        _publish_manifest(
            output,
            manifest,
            payload=canonical_bytes(manifest.to_document()) + b"\n",
        )
        return manifest

    monkeypatch.setattr(
        s4_collect,
        "prepare_release",
        lambda *args, **kwargs: SimpleNamespace(
            identity=SimpleNamespace(release_id=config.release_id)
        ),
    )
    monkeypatch.setattr(s4_collect, "run_episode_batch", fake_batch)
    monkeypatch.setattr(
        learning_data,
        "read_episode_bundle",
        lambda *args, **kwargs: pytest.fail("cold reader reached before manifest confirmation"),
    )

    with pytest.raises(LearningDataError, match="canonical"):
        s4_collect.collect(
            config_path=CORE_CONFIG,
            release_root=tmp_path / "release",
            task_store_root=tmp_path / "task-store",
            corpus_manifest_path=tmp_path / "CorpusManifest.json",
            output_root=output,
        )

    assert batch_calls == 1
    assert not (output / "TeacherCohort.json").exists()


def test_collect_cold_read_failure_keeps_published_batch_final_without_cohort(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config, manifest = _real_config(), _gold_manifest()
    output = tmp_path / "formal-teacher"
    reads = 0

    def fake_batch(*args: Any, **kwargs: Any) -> EpisodeBatchManifest:
        output.mkdir()
        _publish_manifest(output, manifest)
        return manifest

    def rejected_view(*args: Any, **kwargs: Any) -> TrainingEpisodeView:
        nonlocal reads
        reads += 1
        raise ValueError("paired Episode rejected")

    monkeypatch.setattr(
        s4_collect,
        "prepare_release",
        lambda *args, **kwargs: SimpleNamespace(
            identity=SimpleNamespace(release_id=config.release_id)
        ),
    )
    monkeypatch.setattr(s4_collect, "run_episode_batch", fake_batch)
    monkeypatch.setattr(learning_data, "read_episode_bundle", rejected_view)

    with pytest.raises(ValueError, match="paired Episode rejected"):
        s4_collect.collect(
            config_path=CORE_CONFIG,
            release_root=tmp_path / "release",
            task_store_root=tmp_path / "task-store",
            corpus_manifest_path=tmp_path / "CorpusManifest.json",
            output_root=output,
        )

    assert reads == 1
    assert (output / "batches" / manifest.batch_id / "EpisodeBatchManifest.json").is_file()
    assert not (output / "TeacherCohort.json").exists()


def test_collect_rejects_existing_output_before_prepare_or_batch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    output = tmp_path / "published-or-aborted"
    output.mkdir()
    monkeypatch.setattr(
        s4_collect,
        "prepare_release",
        lambda *args, **kwargs: pytest.fail("preparation reached for a final output root"),
    )

    with pytest.raises(LearningDataError, match="must be absent"):
        s4_collect.collect(
            config_path=CORE_CONFIG,
            release_root=tmp_path / "release",
            task_store_root=tmp_path / "task-store",
            corpus_manifest_path=tmp_path / "CorpusManifest.json",
            output_root=output,
        )


def test_collect_rejects_scripted_config_before_prepare(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document = _real_config().to_document()
    document["teacher_policy"] = PolicySpec(
        "scripted",
        "scripted",
        "1",
        "scripted:test",
        _real_policy().system_prompt_digest,
        12,
    ).to_document()
    config_path = tmp_path / "scripted.json"
    config_path.write_bytes(canonical_bytes(document))
    monkeypatch.setattr(
        s4_collect,
        "prepare_release",
        lambda *args, **kwargs: pytest.fail("preparation reached for scripted teacher"),
    )

    with pytest.raises(LearningDataError, match="Responses teacher"):
        s4_collect.collect(
            config_path=config_path,
            release_root=tmp_path / "release",
            task_store_root=tmp_path / "task-store",
            corpus_manifest_path=tmp_path / "CorpusManifest.json",
            output_root=tmp_path / "output",
        )


def test_collect_rejects_prepared_release_identity_before_batch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        s4_collect,
        "prepare_release",
        lambda *args, **kwargs: SimpleNamespace(identity=SimpleNamespace(release_id="a" * 64)),
    )
    monkeypatch.setattr(
        s4_collect,
        "run_episode_batch",
        lambda *args, **kwargs: pytest.fail("batch reached with wrong prepared Release"),
    )

    with pytest.raises(LearningDataError, match="prepared release_id"):
        s4_collect.collect(
            config_path=CORE_CONFIG,
            release_root=tmp_path / "release",
            task_store_root=tmp_path / "task-store",
            corpus_manifest_path=tmp_path / "CorpusManifest.json",
            output_root=tmp_path / "output",
        )


def test_collect_cli_exposes_only_invocation_local_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    received: dict[str, Path] = {}

    def fake_collect(**kwargs: Path) -> TeacherCohort:
        received.update(kwargs)
        return select_teacher_cohort(_real_config(), _gold_manifest(), _gold_views())

    monkeypatch.setattr(s4_collect, "collect", fake_collect)
    values = {
        "config_path": CORE_CONFIG,
        "release_root": tmp_path / "release",
        "task_store_root": tmp_path / "task-store",
        "corpus_manifest_path": tmp_path / "CorpusManifest.json",
        "output_root": tmp_path / "output",
    }

    assert (
        s4_collect.main(
            [
                "--config",
                str(values["config_path"]),
                "--release-root",
                str(values["release_root"]),
                "--task-store-root",
                str(values["task_store_root"]),
                "--corpus-manifest",
                str(values["corpus_manifest_path"]),
                "--output",
                str(values["output_root"]),
            ]
        )
        == 0
    )
    assert received == values


SFT_CONFIG = Path(__file__).parents[1] / "configs" / "s4" / "sft_trainer_qwen3_0_6b.yaml"


def _persisted_gold_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Path:
    config, manifest, views = _real_config(), _gold_manifest(), _gold_views()
    root = tmp_path / "published-batch"
    root.mkdir()
    write_teacher_cohort(root, select_teacher_cohort(config, manifest, views))
    _publish_manifest(root, manifest)
    by_id = {view.episode_id: view for view in views}
    monkeypatch.setattr(
        learning_data,
        "read_episode_bundle",
        lambda _root, episode_id: by_id[episode_id],
    )
    return root


def test_sft_rows_match_native_verl_multiturn_contract(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _persisted_gold_root(tmp_path, monkeypatch)
    cohort = select_teacher_cohort(_real_config(), _gold_manifest(), _gold_views())

    rows = build_sft_rows(root, _real_config())

    assert [cast(str, source["episode_id"]) for source in (row["source"] for row in rows)] == [
        *cohort.primary_sft_episode_ids
    ]
    assert all(set(row) == {"messages", "tools", "source"} for row in rows)
    view = _gold_view()
    public_input = view.public_input
    row = rows[0]
    expected_messages: list[JSONObject] = [
        {"role": "system", "content": public_input.system_prompt},
        {
            "role": "user",
            "content": canonical_bytes(
                {
                    "instruction": public_input.instruction,
                    "reset_observation": public_input.reset_observation,
                }
            ).decode(),
        },
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call_hTA6aTfJO5EVVYGDobUOHyCL",
                    "type": "function",
                    "function": {"name": "repository_status", "arguments": {}},
                }
            ],
        },
        {
            "role": "tool",
            "content": (
                '{"data":{"branch":"main","clean":true,"entries":[]},"error":null,"ok":true}'
            ),
        },
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call_KafzjB295RazHoukbhR8ADJX",
                    "type": "function",
                    "function": {
                        "name": "create_commit",
                        "arguments": {"message": "Attempt empty commit"},
                    },
                }
            ],
        },
        {
            "role": "tool",
            "content": (
                '{"data":null,"error":{"code":"NO_STAGED_CHANGE","message":"No staged content'
                ' differs from HEAD."},"ok":false}'
            ),
        },
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call_BOINSTLz15Y0C7zvjimQjIv2",
                    "type": "function",
                    "function": {"name": "repository_status", "arguments": {}},
                },
                {
                    "id": "call_qXOnXNtJ2BJAM6DZBnXQHmRc",
                    "type": "function",
                    "function": {"name": "commit_history", "arguments": {"limit": 5}},
                },
            ],
        },
        {
            "role": "tool",
            "content": (
                '{"data":{"branch":"main","clean":true,"entries":[]},"error":null,"ok":true}'
            ),
        },
        {
            "role": "tool",
            "content": (
                '{"data":{"commits":[{"commit_id":"2b0a7380a1c2f1968c3df5785d8e7d6c55ea0493",'
                '"message":"Initialize repository","parent_id":null}]},"error":null,"ok":true}'
            ),
        },
        {"role": "assistant", "content": '{"commit_refusal_code":"NO_STAGED_CHANGE"}'},
    ]
    expected_tools: list[JSONObject] = [
        {
            "type": "function",
            "function": {
                "name": cast(str, spec["name"]),
                "description": cast(str, spec["description"]),
                "parameters": spec["input_schema"],
            },
        }
        for spec in public_input.tool_specs
    ]
    # messages/tools are Parquet-ready deterministic compact JSON strings that
    # preserve the exact projection key order; source stays the native identity
    # object
    assert row["messages"] == json.dumps(
        expected_messages, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    )
    assert row["tools"] == json.dumps(
        expected_tools, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    )
    decoded = json.loads(cast(str, row["messages"]))
    assert decoded == expected_messages
    assert list(decoded[0]) == ["role", "content"]
    assert list(decoded[2]) == ["role", "content", "tool_calls"]
    assert list(decoded[2]["tool_calls"][0]) == ["id", "type", "function"]
    assert list(decoded[2]["tool_calls"][0]["function"]) == ["name", "arguments"]
    decoded_tools = json.loads(cast(str, row["tools"]))
    assert decoded_tools == expected_tools
    assert list(decoded_tools[0]) == ["type", "function"]
    assert list(decoded_tools[0]["function"]) == ["name", "description", "parameters"]
    teacher_user_content = json.dumps(
        {
            "instruction": public_input.instruction,
            "reset_observation": public_input.reset_observation,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    assert decoded[1]["content"] == teacher_user_content
    assert row["source"] == {
        "cohort_id": cohort.cohort_id,
        "batch_id": cohort.batch_id,
        "episode_id": view.episode_id,
        "request_id": view.request_id,
        "release_id": view.request.release_id,
        "task_pack_id": view.request.task_pack_id,
        "policy_id": view.request.policy_id,
    }


def _mutated_turns(
    view: TrainingEpisodeView,
    mutate: Any,
) -> tuple[JSONObject, ...]:
    turns = json.loads(json.dumps([dict(turn) for turn in view.turns]))
    mutate(turns)
    return tuple(cast(JSONObject, turn) for turn in turns)


def _serve_views(
    monkeypatch: pytest.MonkeyPatch,
    views: tuple[TrainingEpisodeView, ...],
) -> None:
    by_id = {view.episode_id: view for view in views}
    monkeypatch.setattr(
        learning_data,
        "read_episode_bundle",
        lambda _root, episode_id: by_id[episode_id],
    )


def test_sft_rows_use_parsed_arguments_not_raw_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _persisted_gold_root(tmp_path, monkeypatch)
    views = _gold_views()

    def drift(turns: list[JSONObject]) -> None:
        turns[1]["calls"][0]["raw_arguments"] = '{"message":"RAW-DRIFT-SENTINEL"}'

    drifted = replace(views[0], turns=_mutated_turns(views[0], drift))
    _serve_views(monkeypatch, (drifted, *views[1:]))

    rows = build_sft_rows(root, _real_config())

    assistant = json.loads(cast(str, rows[0]["messages"]))[4]
    assert assistant["tool_calls"][0]["function"] == {
        "name": "create_commit",
        "arguments": {"message": "Attempt empty commit"},
    }
    text = canonical_bytes(rows[0]).decode()
    assert "RAW-DRIFT-SENTINEL" not in text
    assert '"raw_arguments"' not in text


def test_sft_rows_reject_undispatched_call_or_uncompleted_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _persisted_gold_root(tmp_path, monkeypatch)
    views = _gold_views()

    def undispatch(turns: list[JSONObject]) -> None:
        turns[0]["calls"][0]["dispatch_status"] = "duplicate_call_id"
        turns[0]["calls"][0]["observation"] = None

    undispatched = replace(views[0], turns=_mutated_turns(views[0], undispatch))
    uncompleted = replace(views[1], completion=None)
    for mutated in (undispatched, uncompleted):
        _serve_views(
            monkeypatch,
            tuple(mutated if view.episode_id == mutated.episode_id else view for view in views),
        )
        with pytest.raises(LearningDataError, match="SOURCE_INELIGIBLE"):
            build_sft_rows(root, _real_config())


def test_sft_rows_reject_nonprimary_episode_through_cohort(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    views = (
        _gold_view(),
        replace(_gold_view(VIEW_FILES[1]), disposition="abstain", reward=None),
        _gold_view(VIEW_FILES[2]),
    )
    config = _real_config()
    manifest = _manifest_for_views(views)
    cohort = select_teacher_cohort(config, manifest, views)
    assert views[1].episode_id not in cohort.primary_sft_episode_ids
    forged = TeacherCohort(
        cohort.config_digest,
        cohort.batch_id,
        cohort.corpus_id,
        cohort.release_id,
        cohort.policy_id,
        (views[0].episode_id, views[1].episode_id, views[2].episode_id),
    )
    root = tmp_path / "published-batch"
    root.mkdir()
    write_teacher_cohort(root, forged)
    _publish_manifest(root, manifest)
    _serve_views(monkeypatch, views)

    with pytest.raises(LearningDataError, match="primary selection differs"):
        build_sft_rows(root, config)


def test_sft_rows_exclude_nonpublic_and_private_material(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = build_sft_rows(_persisted_gold_root(tmp_path, monkeypatch), _real_config())

    for row in rows:
        assert set(row) == {"messages", "tools", "source"}
        assert set(row["source"]) == {
            "cohort_id",
            "batch_id",
            "episode_id",
            "request_id",
            "release_id",
            "task_pack_id",
            "policy_id",
        }
        for tool in json.loads(cast(str, row["tools"])):
            assert set(tool) == {"type", "function"}
            assert set(tool["function"]) == {"name", "description", "parameters"}
        text = canonical_bytes(row).decode()
        for banned in (
            '"raw_arguments"',
            '"raw_call_id"',
            '"raw_tool_name"',
            '"usage"',
            '"output_schema"',
            '"defect"',
            '"blocked_',
            '"abstain_',
            '"parse_status"',
            '"schema_status"',
            '"dispatch_status"',
        ):
            assert banned not in text


def test_sft_rows_are_deterministic_in_cohort_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _persisted_gold_root(tmp_path, monkeypatch)
    config = _real_config()

    first = build_sft_rows(root, config)
    second = build_sft_rows(root, config)

    cohort = select_teacher_cohort(config, _gold_manifest(), _gold_views())
    assert [canonical_bytes(row) for row in first] == [canonical_bytes(row) for row in second]
    assert [row["source"]["episode_id"] for row in first] == list(cohort.primary_sft_episode_ids)
    assert {row["source"]["cohort_id"] for row in first} == {cohort.cohort_id}
    assert {row["source"]["batch_id"] for row in first} == {cohort.batch_id}
    by_id = {view.episode_id: view for view in _gold_views()}
    for row in first:
        view = by_id[cast(str, row["source"]["episode_id"])]
        assert row["source"]["request_id"] == view.request_id
        assert row["source"]["task_pack_id"] == view.request.task_pack_id
        assert row["source"]["policy_id"] == view.request.policy_id
        assert row["source"]["release_id"] == view.request.release_id


def test_sft_config_pins_native_verl_contract() -> None:
    document = yaml.safe_load(SFT_CONFIG.read_text())

    assert set(document) == {"defaults", "data", "model", "optim", "checkpoint", "trainer"}
    assert document["defaults"] == ["/sft_trainer_engine", "_self_"]
    data = document["data"]
    assert set(data) == {
        "train_batch_size",
        "micro_batch_size_per_gpu",
        "max_length",
        "max_token_len_per_gpu",
        "custom_cls",
        "enable_thinking_default",
        "train_files",
        "ignore_input_ids_mismatch",
    }
    assert data["train_batch_size"] == 3
    assert data["micro_batch_size_per_gpu"] == 1
    assert data["max_length"] == 2048
    assert data["max_token_len_per_gpu"] == 2048
    assert data["enable_thinking_default"] is False
    assert data["custom_cls"]["path"] == "pkg://agent_env_foundry.verl_sft_dataset"
    assert data["custom_cls"]["name"] == "FoundryJSONColumnsSFTDataset"
    assert data["train_files"] == "${oc.env:S4_SFT_TRAIN_PARQUET}"
    assert data["ignore_input_ids_mismatch"] is True
    assert document["optim"]["lr"] == 1e-5
    assert document["model"]["path"] == "${oc.env:S4_TARGET_MODEL_SNAPSHOT}"
    assert document["checkpoint"]["save_contents"] == ["model", "optimizer", "extra", "hf_model"]
    trainer = document["trainer"]
    assert set(trainer) == {"default_local_dir", "total_training_steps", "logger", "resume_mode"}
    assert trainer["total_training_steps"] == 1
    assert trainer["logger"] == ["console"]
    assert trainer["resume_mode"] == "disable"
    assert trainer["default_local_dir"] == "${oc.env:S4_SFT_CHECKPOINT_DIR}"
    text = SFT_CONFIG.read_text()
    assert "/home/" not in text
    assert "/tmp/" not in text
