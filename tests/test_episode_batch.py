from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import pytest

import agent_env_foundry.episode_batch as batch
import test_episode_runtime as fixtures
from agent_env_foundry.assessment import (
    AssessmentError,
    CorpusManifest,
    CorpusPolicy,
    CorpusSelectionCandidate,
)
from agent_env_foundry.environment import JSONObject
from agent_env_foundry.episodes import EpisodeDefect, PolicySpec
from agent_env_foundry.public_agent import DriverDecision
from agent_env_foundry.release import canonical_bytes
from agent_env_foundry.task_foundry import TaskFoundryError


def _sha(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


class Prepared(fixtures.Prepared):
    """Existing fake semantics with fresh acting/reopened identities per Episode."""

    def open(self, path: Path):
        position = len(self.paths)
        self.paths.append(path)
        label = "acting" if position % 2 == 0 else "reopened"
        session_id = hashlib.sha256(f"{label}:{position}".encode()).hexdigest()
        self.events.append(f"{label}:open")
        return fixtures.Session(
            session_id,
            self.state,
            self.events,
            label,
            self.members,
            self.mode,
        )


def _corpus(
    tmp_path: Path,
    entries: list[tuple[str, str, str]],
) -> tuple[Path, CorpusManifest]:
    candidates = tuple(
        CorpusSelectionCandidate(
            task_pack_id,
            _sha({"assessment": position}),
            fixtures.RELEASE_ID,
            cast(Any, goal_kind),
            _sha({"structure": position}),
            0.5,
        )
        for position, (task_pack_id, goal_kind, _path) in enumerate(entries)
    )
    corpus = CorpusManifest(
        CorpusPolicy("rl", 0.0, None),
        7,
        candidates,
        _sha({"selection": [item.task_pack_id for item in candidates]}),
    )
    path = tmp_path / "CorpusManifest.json"
    path.write_bytes(canonical_bytes(corpus.to_document()))
    store = tmp_path / "store" / "batch" / "taskpacks"
    names = {
        "atom": "AtomTaskPack.json",
        "foreach": "ForEachTaskPack.json",
        "if": "IfTaskPack.json",
    }
    for task_pack_id, goal_kind, source in entries:
        if not source:
            continue
        target = store / task_pack_id / names[goal_kind]
        target.parent.mkdir(parents=True)
        shutil.copyfile(source, target)
    return path, corpus


def _driver(decisions: list[DriverDecision]) -> fixtures.Driver:
    return fixtures.Driver(decisions)


def _source(tmp_path: Path, kind: str, *, label: str | None = None):
    root = tmp_path / (label or kind)
    root.mkdir()
    return fixtures._write_pack(root, cast(Any, kind))


def test_exact_batch_prefreezes_then_retains_every_outcome_and_aggregate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sources = [_source(tmp_path, kind) for kind in ("atom", "foreach", "if")]
    missing_id = "9" * 64
    entries = [
        (sources[0][1], "atom", str(sources[0][0])),
        (sources[1][1], "foreach", str(sources[1][0])),
        (sources[2][1], "if", str(sources[2][0])),
        (missing_id, "atom", ""),
    ]
    corpus_path, corpus = _corpus(tmp_path, entries)
    success = fixtures._completed(1, "{}")
    success[0] = replace(success[0], usage={"input_tokens": 3, "output_tokens": 2})
    decisions = [
        success,
        [DriverDecision()],
        [
            DriverDecision(
                defect=EpisodeDefect("provider", "provider_outage", "policy_driver_decision")
            )
        ],
    ]
    drivers: list[fixtures.Driver] = []
    loaded: list[str] = []
    original_load = batch._load_task_authority

    def tracked_load(prepared, path, task_pack_id):
        loaded.append(task_pack_id)
        return original_load(prepared, path, task_pack_id)

    monkeypatch.setattr(batch, "_load_task_authority", tracked_load)

    def factory() -> fixtures.Driver:
        assert loaded == [item[0] for item in entries]
        driver = _driver(decisions[len(drivers)])
        drivers.append(driver)
        return driver

    policy_spec = _driver(fixtures._completed(1, "{}")).policy_spec
    output = tmp_path / "output"
    manifest = batch.run_episode_batch(
        Prepared(members=2),  # type: ignore[arg-type]
        tmp_path / "store",
        corpus_path,
        corpus.corpus_id,
        output,
        policy_spec=policy_spec,
        policy_driver_factory=factory,
        rollouts_per_task=1,
    )

    assert [item["task_pack_id"] for item in manifest.results] == [item[0] for item in entries]
    assert [item["episode_id"] is not None for item in manifest.results] == [
        True,
        True,
        True,
        False,
    ]
    assert manifest.results[3] == {
        "task_pack_id": missing_id,
        "rollout_index": 1,
        "request_id": None,
        "episode_id": None,
        "blocked_owner": "task_artifact",
        "blocked_code": "task_pack_artifact_unreadable",
        "blocked_phase": "task_authority",
    }
    assert manifest.aggregates == {
        "total_slots": 4,
        "episode_count": 3,
        "blocked_count": 1,
        "verified_success": 1,
        "verified_failure": 1,
        "abstain": 1,
        "attempted_calls": 1,
        "dispatched_calls": 1,
        "provider_turns": 4,
        "input_tokens": 3,
        "output_tokens": 2,
        "missing_usage_turns": 3,
        "policy_elapsed_ms": cast(int, manifest.aggregates["policy_elapsed_ms"]),
        "abstain_owner_counts": {"provider": 1},
        "blocked_owner_counts": {"task_artifact": 1},
    }
    assert len(drivers) == 3
    assert all(driver.close_count == 1 for driver in drivers)
    assert all(item["request_id"] is not None for item in manifest.results[:3])
    document = cast(
        JSONObject,
        json.loads(
            (output / "batches" / manifest.batch_id / "EpisodeBatchManifest.json").read_bytes()
        ),
    )
    assert document == manifest.to_document()
    assert set(document) == {
        "format",
        "corpus_id",
        "release_id",
        "policy_id",
        "rollouts_per_task",
        "results",
        "aggregates",
        "batch_id",
    }


def test_rollouts_use_fresh_drivers_once_without_retry(tmp_path: Path) -> None:
    source, pack_id, _task = _source(tmp_path, "atom", label="source")
    corpus_path, corpus = _corpus(tmp_path, [(pack_id, "atom", str(source))])
    drivers: list[fixtures.Driver] = []

    def factory() -> fixtures.Driver:
        driver = _driver(fixtures._completed(1, "{}"))
        drivers.append(driver)
        return driver

    policy_spec: PolicySpec = _driver(fixtures._completed(1, "{}")).policy_spec
    manifest = batch.run_episode_batch(
        Prepared(),  # type: ignore[arg-type]
        tmp_path / "store",
        corpus_path,
        corpus.corpus_id,
        tmp_path / "output",
        policy_spec=policy_spec,
        policy_driver_factory=factory,
        rollouts_per_task=2,
    )

    assert len(drivers) == 2
    assert drivers[0] is not drivers[1]
    assert all(driver.close_count == 1 for driver in drivers)
    assert [item["rollout_index"] for item in manifest.results] == [1, 2]
    assert manifest.aggregates["verified_success"] == 2


def test_reused_and_mismatched_drivers_are_request_bound_evidence_blocks(
    tmp_path: Path,
) -> None:
    source, pack_id, _task = _source(tmp_path, "atom", label="source")
    corpus_path, corpus = _corpus(tmp_path, [(pack_id, "atom", str(source))])
    shared = _driver(fixtures._completed(1, "{}"))
    manifest = batch.run_episode_batch(
        Prepared(),  # type: ignore[arg-type]
        tmp_path / "store",
        corpus_path,
        corpus.corpus_id,
        tmp_path / "reuse-output",
        policy_spec=shared.policy_spec,
        policy_driver_factory=lambda: shared,
        rollouts_per_task=2,
    )
    assert manifest.results[0]["episode_id"] is not None
    assert manifest.results[1]["request_id"] is not None
    assert manifest.results[1]["blocked_code"] == "policy_driver_reused"

    wrong = _driver(fixtures._completed(1, "{}"))
    wrong._spec = replace(wrong.policy_spec, model_id="another-policy")
    mismatched = batch.run_episode_batch(
        Prepared(),  # type: ignore[arg-type]
        tmp_path / "store",
        corpus_path,
        corpus.corpus_id,
        tmp_path / "mismatch-output",
        policy_spec=shared.policy_spec,
        policy_driver_factory=lambda: wrong,
        rollouts_per_task=1,
    )
    assert mismatched.results[0]["episode_id"] is None
    assert mismatched.results[0]["request_id"] is not None
    assert mismatched.results[0]["blocked_owner"] == "evidence"
    assert mismatched.results[0]["blocked_code"] == "policy_spec_mismatch"
    assert wrong.close_count == 1


def test_pre_input_failure_keeps_request_and_current_owner(tmp_path: Path) -> None:
    source, pack_id, _task = _source(tmp_path, "atom", label="source")
    corpus_path, corpus = _corpus(tmp_path, [(pack_id, "atom", str(source))])
    driver = _driver(fixtures._completed(1, "{}"))

    manifest = batch.run_episode_batch(
        Prepared(mode="preflight"),  # type: ignore[arg-type]
        tmp_path / "store",
        corpus_path,
        corpus.corpus_id,
        tmp_path / "output",
        policy_spec=driver.policy_spec,
        policy_driver_factory=lambda: driver,
        rollouts_per_task=1,
    )

    assert manifest.results[0]["request_id"] is not None
    assert manifest.results[0]["episode_id"] is None
    assert manifest.results[0]["blocked_owner"] == "semantics"
    assert manifest.results[0]["blocked_code"] == "preflight_failed"


def test_trusted_pre_input_failure_stops_the_task_without_retry(tmp_path: Path) -> None:
    source, pack_id, _task = _source(tmp_path, "atom", label="source")
    corpus_path, corpus = _corpus(tmp_path, [(pack_id, "atom", str(source))])
    drivers: list[fixtures.Driver] = []

    def factory() -> fixtures.Driver:
        driver = _driver(fixtures._completed(1, "{}"))
        drivers.append(driver)
        return driver

    policy_spec = _driver(fixtures._completed(1, "{}")).policy_spec
    manifest = batch.run_episode_batch(
        Prepared(mode="preflight"),  # type: ignore[arg-type]
        tmp_path / "store",
        corpus_path,
        corpus.corpus_id,
        tmp_path / "output",
        policy_spec=policy_spec,
        policy_driver_factory=factory,
        rollouts_per_task=2,
    )

    assert len(drivers) == 1
    assert drivers[0].close_count == 1
    assert [item["blocked_owner"] for item in manifest.results] == [
        "semantics",
        "semantics",
    ]
    assert [item["blocked_code"] for item in manifest.results] == [
        "preflight_failed",
        "preflight_failed",
    ]
    assert manifest.results[1]["blocked_phase"] == "affected_task_authority"


def test_unattributed_pre_input_failure_aborts_without_manifest(tmp_path: Path) -> None:
    source, pack_id, _task = _source(tmp_path, "atom", label="source")
    corpus_path, corpus = _corpus(tmp_path, [(pack_id, "atom", str(source))])
    policy_spec = _driver(fixtures._completed(1, "{}")).policy_spec
    output = tmp_path / "output"

    def fail_factory() -> fixtures.Driver:
        raise RuntimeError("unattributed factory failure")

    with pytest.raises(RuntimeError, match="unattributed factory failure"):
        batch.run_episode_batch(
            Prepared(),  # type: ignore[arg-type]
            tmp_path / "store",
            corpus_path,
            corpus.corpus_id,
            output,
            policy_spec=policy_spec,
            policy_driver_factory=fail_factory,
            rollouts_per_task=1,
        )
    assert not (output / "batches").exists()


def test_episode_publication_failure_aborts_without_manifest_or_fake_remainder(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, pack_id, _task = _source(tmp_path, "atom", label="source")
    corpus_path, corpus = _corpus(tmp_path, [(pack_id, "atom", str(source))])
    drivers: list[fixtures.Driver] = []

    def factory() -> fixtures.Driver:
        driver = _driver(fixtures._completed(1, "{}"))
        drivers.append(driver)
        return driver

    def fail_write(_root: Path, _record: Any):
        raise OSError("injected publication failure")

    monkeypatch.setattr(batch, "write_episode_bundle", fail_write)
    policy_spec = _driver(fixtures._completed(1, "{}")).policy_spec
    output = tmp_path / "output"
    with pytest.raises(OSError, match="publication failure"):
        batch.run_episode_batch(
            Prepared(),  # type: ignore[arg-type]
            tmp_path / "store",
            corpus_path,
            corpus.corpus_id,
            output,
            policy_spec=policy_spec,
            policy_driver_factory=factory,
            rollouts_per_task=2,
        )
    assert len(drivers) == 1
    assert not (output / "batches").exists()


def test_batch_rejects_invalid_corpus_release_and_existing_root_before_driver(
    tmp_path: Path,
) -> None:
    source, pack_id, _task = _source(tmp_path, "atom", label="source")
    corpus_path, corpus = _corpus(tmp_path, [(pack_id, "atom", str(source))])
    policy_spec = _driver(fixtures._completed(1, "{}")).policy_spec
    calls = 0

    def factory() -> fixtures.Driver:
        nonlocal calls
        calls += 1
        return _driver(fixtures._completed(1, "{}"))

    with pytest.raises(AssessmentError):
        batch.run_episode_batch(
            Prepared(),  # type: ignore[arg-type]
            tmp_path / "store",
            corpus_path,
            "8" * 64,
            tmp_path / "wrong-id-output",
            policy_spec=policy_spec,
            policy_driver_factory=factory,
            rollouts_per_task=1,
        )
    assert not (tmp_path / "wrong-id-output").exists()

    multi = CorpusManifest(
        corpus.policy,
        corpus.seed,
        (
            corpus.entries[0],
            replace(
                corpus.entries[0],
                task_pack_id="7" * 64,
                assessment_id="6" * 64,
                release_id="b" * 64,
            ),
        ),
        corpus.selection_evidence_digest,
    )
    multi_path = tmp_path / "multi-release.json"
    multi_path.write_bytes(canonical_bytes(multi.to_document()))
    with pytest.raises(TaskFoundryError, match="exactly one Corpus release"):
        batch.run_episode_batch(
            Prepared(),  # type: ignore[arg-type]
            tmp_path / "store",
            multi_path,
            multi.corpus_id,
            tmp_path / "multi-output",
            policy_spec=policy_spec,
            policy_driver_factory=factory,
            rollouts_per_task=1,
        )
    assert not (tmp_path / "multi-output").exists()

    changed = CorpusManifest(
        corpus.policy,
        corpus.seed,
        (replace(corpus.entries[0], release_id="b" * 64),),
        corpus.selection_evidence_digest,
    )
    changed_path = tmp_path / "other-release.json"
    changed_path.write_bytes(canonical_bytes(changed.to_document()))
    with pytest.raises(TaskFoundryError, match="another prepared release"):
        batch.run_episode_batch(
            Prepared(),  # type: ignore[arg-type]
            tmp_path / "store",
            changed_path,
            changed.corpus_id,
            tmp_path / "release-output",
            policy_spec=policy_spec,
            policy_driver_factory=factory,
            rollouts_per_task=1,
        )
    assert not (tmp_path / "release-output").exists()

    existing = tmp_path / "existing"
    existing.mkdir()
    with pytest.raises(ValueError, match="absent"):
        batch.run_episode_batch(
            Prepared(),  # type: ignore[arg-type]
            tmp_path / "store",
            corpus_path,
            corpus.corpus_id,
            existing,
            policy_spec=policy_spec,
            policy_driver_factory=factory,
            rollouts_per_task=1,
        )
    assert calls == 0


def test_cold_reconciliation_rejects_dropped_slot_and_changed_aggregate(
    tmp_path: Path,
) -> None:
    source, pack_id, _task = _source(tmp_path, "atom", label="source")
    corpus_path, corpus = _corpus(tmp_path, [(pack_id, "atom", str(source))])
    policy_spec = _driver(fixtures._completed(1, "{}")).policy_spec
    output = tmp_path / "output"
    manifest = batch.run_episode_batch(
        Prepared(),  # type: ignore[arg-type]
        tmp_path / "store",
        corpus_path,
        corpus.corpus_id,
        output,
        policy_spec=policy_spec,
        policy_driver_factory=lambda: _driver(fixtures._completed(1, "{}")),
        rollouts_per_task=2,
    )
    path = output / "batches" / manifest.batch_id / "EpisodeBatchManifest.json"
    original = cast(dict[str, Any], json.loads(path.read_bytes()))
    for mutation in ("drop", "aggregate"):
        changed = json.loads(json.dumps(original))
        if mutation == "drop":
            changed["results"].pop()
            changed["aggregates"]["total_slots"] -= 1
            changed["aggregates"]["episode_count"] -= 1
            changed["aggregates"]["verified_success"] -= 1
        else:
            changed["aggregates"]["input_tokens"] += 1
        path.write_bytes(canonical_bytes(changed))
        with pytest.raises(ValueError):
            batch._cold_check_manifest(output, manifest)
        path.write_bytes(canonical_bytes(original))
