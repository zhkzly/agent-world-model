from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

import agent_env_foundry.batch_foundry as batch_module
from agent_env_foundry.release import canonical_bytes
from agent_env_foundry.semantics import StartCase
from agent_env_foundry.task_foundry import AtomTask, TaskFoundryError


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

    class Pack:
        task_pack_id = "b" * 64

        def to_document(self) -> dict[str, object]:
            return {"format": "atom-task-pack/1", "task_pack_id": self.task_pack_id}

    monkeypatch.setattr(
        batch_module,
        "_compile_candidates",
        lambda *_args: (candidates, (first, second)),
    )

    def admit(*_args: object, **_kwargs: object) -> Pack:
        candidate = next(item for item in _args if isinstance(item, batch_module._Candidate))
        attempts.append(candidate.task_id)
        if candidate.task_id == first.task_id:
            raise TaskFoundryError("public_witness_failed", "first parameterization failed")
        return Pack()

    monkeypatch.setattr(batch_module, "_admit_candidate", admit)
    report = batch_module.run_task_foundry_batch(
        SimpleNamespace(identity=SimpleNamespace(release_id="a" * 64)),
        tmp_path / "work",
        tmp_path / "output",
        target_structures=1,
    )

    assert attempts == [first.task_id, second.task_id]
    assert report.target_reached is True
    assert len(report.admitted) == 1
    assert len(report.rejected) == 1
    assert report.rejected[0].code == "public_witness_failed"


def test_batch_persists_canonical_pack_and_report(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    task = _atom("item:one", "one")
    candidate = batch_module._candidate("atom", task)

    class Pack:
        task_pack_id = "c" * 64

        def to_document(self) -> dict[str, object]:
            return {"format": "atom-task-pack/1", "task_pack_id": self.task_pack_id}

    monkeypatch.setattr(
        batch_module,
        "_compile_candidates",
        lambda *_args: ((candidate,), (task,)),
    )
    monkeypatch.setattr(batch_module, "_admit_candidate", lambda *_args, **_kwargs: Pack())

    report = batch_module.run_task_foundry_batch(
        SimpleNamespace(identity=SimpleNamespace(release_id="a" * 64)),
        tmp_path / "work",
        tmp_path / "output",
        target_structures=1,
    )

    pack_path = tmp_path / "output" / "taskpacks" / ("c" * 64) / "AtomTaskPack.json"
    report_path = tmp_path / "output" / "runs" / f"{report.run_id}.json"
    assert pack_path.read_bytes() == canonical_bytes(Pack().to_document())
    assert report_path.read_bytes() == canonical_bytes(report.to_document())


def test_batch_reports_dependency_packs_and_progress_events(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    task = _atom("item:one", "one")
    candidate = batch_module._candidate("atom", task)
    events: list[dict[str, object]] = []

    class Pack:
        task_pack_id = "d" * 64

        def to_document(self) -> dict[str, object]:
            return {"format": "atom-task-pack/1", "task_pack_id": self.task_pack_id}

    monkeypatch.setattr(
        batch_module,
        "_compile_candidates",
        lambda *_args: ((candidate,), (task,)),
    )

    def admit(*args: object, **_kwargs: object) -> Pack:
        dependencies = args[-1]
        assert isinstance(dependencies, dict)
        dependencies[task.task_id] = batch_module.AdmittedTaskRecord(
            "atom",
            task.task_id,
            candidate.structure_id,
            "e" * 64,
            "taskpacks/dependency/AtomTaskPack.json",
        )
        return Pack()

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
