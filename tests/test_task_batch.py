from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

import agent_env_foundry.batch_foundry as batch_module
from agent_env_foundry.release import canonical_bytes
from agent_env_foundry.semantics import StartCase
from agent_env_foundry.task_foundry import AtomTask, TaskFoundryError


class _CanonicalPack:
    def __init__(self, marker: str = "accepted") -> None:
        self._preimage = {"format": "test-task-pack/1", "marker": marker}

    @property
    def task_pack_id(self) -> str:
        return hashlib.sha256(canonical_bytes(self._preimage)).hexdigest()

    def to_document(self) -> dict[str, object]:
        return {**self._preimage, "task_pack_id": self.task_pack_id}


def _atom(
    semantic_key: str,
    descriptor: str,
    *,
    field: str = "value",
    regime: str = "base",
) -> AtomTask:
    answer_schema = {
        "type": "object",
        "properties": {field: {"type": "string"}},
        "required": [field],
        "additionalProperties": False,
    }
    start = StartCase(regime, {"regime": regime}, (regime,))
    preimage = {
        "release_id": "a" * 64,
        "start_case_id": start.case_id,
        "capability_id": "cap-1",
        "semantic_key": semantic_key,
        "answer_schema": answer_schema,
    }
    instruction = f"Complete {descriptor}."
    return AtomTask(
        "a" * 64,
        start,
        "cap-1",
        semantic_key,
        {"item": descriptor},
        hashlib.sha256(canonical_bytes(preimage)).hexdigest(),
        instruction,
        hashlib.sha256(instruction.encode()).hexdigest(),
        answer_schema,
    )


def test_structure_id_ignores_parameters_but_keeps_report_and_regime_semantics() -> None:
    first, second = sorted(
        (_atom("item:one", "one"), _atom("item:two", "two")),
        key=lambda task: task.task_id,
    )

    assert batch_module.task_structure_id("atom", first) == batch_module.task_structure_id(
        "atom", second
    )
    assert batch_module.task_structure_id("atom", first) != batch_module.task_structure_id(
        "atom", _atom("item:one", "one", field="other")
    )
    assert batch_module.task_structure_id("atom", first) != batch_module.task_structure_id(
        "atom", _atom("item:one", "one", regime="other")
    )


def test_batch_tries_another_parameterization_after_candidate_rejection(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    first, second = sorted(
        (_atom("item:one", "one"), _atom("item:two", "two")),
        key=lambda task: task.task_id,
    )
    candidates = tuple(batch_module._candidate("atom", task) for task in (first, second))
    attempts: list[str] = []

    pack = _CanonicalPack("second-parameterization")

    monkeypatch.setattr(
        batch_module,
        "_compile_candidates",
        lambda *_args: (candidates, (first, second)),
    )

    def admit(*_args: object, **_kwargs: object) -> _CanonicalPack:
        candidate = next(item for item in _args if isinstance(item, batch_module._Candidate))
        attempts.append(candidate.task_id)
        if candidate.task_id == first.task_id:
            raise TaskFoundryError("public_witness_failed", "first parameterization failed")
        return pack

    monkeypatch.setattr(batch_module, "_admit_candidate", admit)
    report = batch_module.run_task_foundry_batch(
        SimpleNamespace(identity=SimpleNamespace(release_id="a" * 64)),
        tmp_path / "work",
        tmp_path / "output",
        target_structures=1,
        candidate_attempt_limit=1,
    )

    assert attempts == [first.task_id, second.task_id]
    assert report.target_reached is True
    assert len(report.admitted) == 1
    assert len(report.rejected) == 1
    assert report.rejected[0].code == "public_witness_failed"
    assert report.rejected[0].attempt_index == 1


def test_batch_retries_retryable_failure_with_a_fresh_attempt_root(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    task = _atom("item:one", "one")
    candidate = batch_module._candidate("atom", task)
    roots: list[Path] = []

    monkeypatch.setattr(
        batch_module,
        "_compile_candidates",
        lambda *_args: ((candidate,), (task,)),
    )

    pack = _CanonicalPack("second-attempt")

    def admit(*args: object, **_kwargs: object) -> _CanonicalPack:
        root = next(
            item for item in args if isinstance(item, Path) and item.name.startswith("attempt-")
        )
        roots.append(root)
        if len(roots) == 1:
            raise TaskFoundryError("public_witness_failed", "transient policy failure")
        return pack

    monkeypatch.setattr(batch_module, "_admit_candidate", admit)
    report = batch_module.run_task_foundry_batch(
        SimpleNamespace(identity=SimpleNamespace(release_id="a" * 64)),
        tmp_path / "work",
        tmp_path / "output",
        target_structures=1,
        candidate_attempt_limit=2,
    )

    assert [root.name for root in roots] == ["attempt-1", "attempt-2"]
    assert report.target_reached is True
    assert report.candidate_attempt_limit == 2
    assert report.to_document()["format"] == "task-foundry-batch/2"
    assert [item.attempt_index for item in report.rejected] == [1]


def test_batch_failure_taxonomy_distinguishes_policy_and_framework_owners() -> None:
    assert batch_module._task_failure_kind("public_witness_failed") == "NoPublicWitness"
    assert batch_module._task_failure_kind("foreach_partial_not_discriminated") == (
        "ChallengePolicyFailure"
    )
    assert batch_module._task_failure_kind("checker_mutant_survived") == "RejectedTaskPack"


def test_batch_does_not_retry_non_policy_framework_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    task = _atom("item:one", "one")
    candidate = batch_module._candidate("atom", task)
    attempts = 0
    monkeypatch.setattr(
        batch_module,
        "_compile_candidates",
        lambda *_args: ((candidate,), (task,)),
    )

    def reject(*_args: object, **_kwargs: object) -> None:
        nonlocal attempts
        attempts += 1
        raise TaskFoundryError(
            "invalid_task_contract",
            "deterministic challenge construction failed",
        )

    monkeypatch.setattr(batch_module, "_admit_candidate", reject)
    report = batch_module.run_task_foundry_batch(
        SimpleNamespace(identity=SimpleNamespace(release_id="a" * 64)),
        tmp_path / "work",
        tmp_path / "output",
        target_structures=1,
        candidate_attempt_limit=3,
    )

    assert attempts == 1
    assert report.target_reached is False
    assert report.rejected[0].failure_kind == "RejectedTaskPack"


def test_batch_persists_canonical_pack_and_report(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    task = _atom("item:one", "one")
    candidate = batch_module._candidate("atom", task)

    monkeypatch.setattr(
        batch_module,
        "_compile_candidates",
        lambda *_args: ((candidate,), (task,)),
    )
    pack = _CanonicalPack()
    monkeypatch.setattr(batch_module, "_admit_candidate", lambda *_args, **_kwargs: pack)

    report = batch_module.run_task_foundry_batch(
        SimpleNamespace(identity=SimpleNamespace(release_id="a" * 64)),
        tmp_path / "work",
        tmp_path / "output",
        target_structures=1,
    )

    pack_path = tmp_path / "output" / "taskpacks" / pack.task_pack_id / "AtomTaskPack.json"
    report_path = tmp_path / "output" / "runs" / f"{report.run_id}.json"
    assert pack_path.read_bytes() == canonical_bytes(pack.to_document())
    assert report_path.read_bytes() == canonical_bytes(report.to_document())


def test_batch_rejects_task_pack_with_forged_identity_before_recording_admission(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    task = _atom("item:one", "one")
    candidate = batch_module._candidate("atom", task)

    class ForgedPack:
        task_pack_id = "c" * 64

        def to_document(self) -> dict[str, object]:
            return {"format": "test-task-pack/1", "task_pack_id": self.task_pack_id}

    monkeypatch.setattr(
        batch_module,
        "_compile_candidates",
        lambda *_args: ((candidate,), (task,)),
    )
    monkeypatch.setattr(
        batch_module,
        "_admit_candidate",
        lambda *_args, **_kwargs: ForgedPack(),
    )

    with pytest.raises(TaskFoundryError) as raised:
        batch_module.run_task_foundry_batch(
            SimpleNamespace(identity=SimpleNamespace(release_id="a" * 64)),
            tmp_path / "work",
            tmp_path / "output",
            target_structures=1,
        )

    assert raised.value.code == "task_pack_artifact_preimage_mismatch"
    assert not (tmp_path / "output" / "runs").exists()


def test_task_pack_cold_verifier_recomputes_identity_from_disk(tmp_path: Path) -> None:
    pack = _CanonicalPack()
    path = tmp_path / "TaskPack.json"
    path.write_bytes(canonical_bytes(pack.to_document()))

    batch_module.verify_task_pack_artifact(path, pack.task_pack_id)
    tampered = {**pack.to_document(), "marker": "tampered"}
    path.write_bytes(canonical_bytes(tampered))

    with pytest.raises(TaskFoundryError) as raised:
        batch_module.verify_task_pack_artifact(path, pack.task_pack_id)

    assert raised.value.code == "task_pack_artifact_preimage_mismatch"


def test_task_pack_reader_projects_only_the_public_acting_view(tmp_path: Path) -> None:
    task = _atom("item:secret-key", "public-item")
    preimage = {
        "format": "atom-task-pack/4",
        "task": task.to_document(),
        "admission": {"task_id": task.task_id},
    }
    task_pack_id = hashlib.sha256(canonical_bytes(preimage)).hexdigest()
    path = tmp_path / "AtomTaskPack.json"
    path.write_bytes(canonical_bytes({**preimage, "task_pack_id": task_pack_id}))

    loaded = batch_module.read_task_pack_artifact(path, task_pack_id)

    assert set(loaded.public.to_document()) == {
        "format",
        "task_pack_id",
        "task_id",
        "release_id",
        "goal_kind",
        "instruction",
        "answer_schema",
    }
    assert "semantic_key" not in loaded.public.to_document()
    assert "public_descriptor" not in loaded.public.to_document()
    assert loaded.start_case == task.start_case.to_document()
    assert loaded.checker_digest == task.checker_digest


def test_batch_reports_dependency_packs_and_progress_events(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    task = _atom("item:one", "one")
    candidate = batch_module._candidate("atom", task)
    events: list[dict[str, object]] = []

    monkeypatch.setattr(
        batch_module,
        "_compile_candidates",
        lambda *_args: ((candidate,), (task,)),
    )

    pack = _CanonicalPack("dependency-parent")

    def admit(*args: object, **_kwargs: object) -> _CanonicalPack:
        dependencies = args[-1]
        assert isinstance(dependencies, dict)
        dependencies[task.task_id] = batch_module.AdmittedTaskRecord(
            "atom",
            task.task_id,
            candidate.structure_id,
            "e" * 64,
            "taskpacks/dependency/AtomTaskPack.json",
        )
        return pack

    monkeypatch.setattr(batch_module, "_admit_candidate", admit)
    report = batch_module.run_task_foundry_batch(
        SimpleNamespace(identity=SimpleNamespace(release_id="a" * 64)),
        tmp_path / "work",
        tmp_path / "output",
        target_structures=1,
        event_sink=events.append,  # type: ignore[arg-type]
    )

    assert [item["event"] for item in events] == [
        "candidate_started",
        "candidate_admitted",
    ]
    assert [item.task_pack_id for item in report.dependencies] == ["e" * 64]
