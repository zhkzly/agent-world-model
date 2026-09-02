from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from agent_env_foundry.environment_semantic_qualification import SemanticQualificationFailure
from agent_env_foundry.preparation_v3 import PreparationExecutionErrorV3
from agent_env_foundry.research import BuilderProjection


class _ResearchReady:
    builder_projection = BuilderProjection(
        frozen_need={"original_need": "test", "clauses": []},
        selected_world={"scope": "test"},
        requirements=({"id": "REQ-001"},),
        initial_world_relations=(),
        cited_evidence=(),
    )
    digest = "1" * 64

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}", encoding="utf-8")


class _Tools:
    def close(self) -> None:
        return


def _install_success(monkeypatch: pytest.MonkeyPatch) -> tuple[object, list[str]]:
    import agent_env_foundry.generation_v3 as subject

    calls: list[str] = []

    def stage(name: str, result: Any):
        def run(*args: Any, **kwargs: Any) -> Any:
            calls.append(name)
            return result

        return run

    actor = SimpleNamespace(
        workspace=Path("actor"),
        candidate_digest="2" * 64,
        acceptance={"verdict": "passed"},
    )
    conformed = SimpleNamespace(
        receipt=object(),
        evidence={},
        start_schema={},
        reset_observation_schema={},
        state_schema={},
    )
    release = SimpleNamespace(release_id="3" * 64, root=Path("release"))
    prepared = object()
    monkeypatch.setattr(subject, "ResearchReady", _ResearchReady)
    monkeypatch.setattr(subject, "ResearchTools", lambda **kwargs: _Tools())
    monkeypatch.setattr(subject, "run_research", stage("research", _ResearchReady()))

    def build(*args: Any, **kwargs: Any) -> Any:
        calls.append("environment_builder")
        assert callable(kwargs["acceptance_check"])
        return actor

    monkeypatch.setattr(subject, "run_builder", build)
    monkeypatch.setattr(
        subject,
        "run_environment_conformance_v3_internal",
        stage("environment_conformance", conformed),
    )
    monkeypatch.setattr(
        subject,
        "_bind_accepted_semantics",
        stage("environment_semantic_qualification", conformed),
    )
    monkeypatch.setattr(
        subject,
        "publish_release_v3_internal",
        stage("publication", release),
    )
    monkeypatch.setattr(
        subject,
        "write_release_zip_v3_internal",
        stage("write_zip", Path("release.zip")),
    )
    monkeypatch.setattr(
        subject,
        "prepare_release_v3_internal",
        stage("cold_prepare", prepared),
    )
    return prepared, calls


def test_internal_v3_generation_has_only_environment_stages(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import agent_env_foundry.generation_v3 as subject

    prepared, calls = _install_success(monkeypatch)
    result = subject.generate_environment_v3_internal(
        "Build a resettable environment.",
        tmp_path / "work",
        tmp_path / "output",
        config=subject.GenerationConfigV3(),
    )

    assert isinstance(result, subject.ReleasedV3)
    assert result.prepared is prepared
    assert calls == [
        "research",
        "environment_builder",
        "environment_conformance",
        "environment_semantic_qualification",
        "publication",
        "write_zip",
        "cold_prepare",
    ]


def test_internal_v3_conformance_failure_stops_before_publication(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import agent_env_foundry.generation_v3 as subject

    monkeypatch.setattr(subject, "ResearchReady", _ResearchReady)
    monkeypatch.setattr(subject, "ResearchTools", lambda **kwargs: _Tools())
    monkeypatch.setattr(subject, "run_research", lambda **kwargs: _ResearchReady())
    monkeypatch.setattr(subject, "run_builder", lambda *args, **kwargs: object())
    monkeypatch.setattr(
        subject,
        "run_environment_conformance_v3_internal",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            PreparationExecutionErrorV3(
                "EnvironmentDefect",
                "state_reopen_drift",
                "state drifted",
            )
        ),
    )
    monkeypatch.setattr(
        subject,
        "publish_release_v3_internal",
        lambda *args, **kwargs: pytest.fail("publication must not run"),
    )

    result = subject.generate_environment_v3_internal(
        "Build a resettable environment.",
        tmp_path / "work",
        tmp_path / "output",
        config=subject.GenerationConfigV3(),
    )
    assert result.code == "state_reopen_drift"
    assert result.details["owner"] == "EnvironmentConformance"


def test_semantic_reviewer_failure_is_not_attributed_to_builder(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import agent_env_foundry.generation_v3 as subject

    monkeypatch.setattr(subject, "ResearchReady", _ResearchReady)
    monkeypatch.setattr(subject, "ResearchTools", lambda **kwargs: _Tools())
    monkeypatch.setattr(subject, "run_research", lambda **kwargs: _ResearchReady())
    monkeypatch.setattr(
        subject,
        "run_builder",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            SemanticQualificationFailure(
                "InfrastructureFailure",
                "semantic_review_provider_failed",
                "review provider failed",
            )
        ),
    )
    monkeypatch.setattr(
        subject,
        "publish_release_v3_internal",
        lambda *args, **kwargs: pytest.fail("publication must not run"),
    )

    result = subject.generate_environment_v3_internal(
        "Build a resettable environment.",
        tmp_path / "work",
        tmp_path / "output",
        config=subject.GenerationConfigV3(),
    )

    assert result.code == "semantic_review_provider_failed"
    assert result.details["owner"] == "EnvironmentSemanticQualification"


def test_internal_v3_generation_imports_no_task_authority() -> None:
    import agent_env_foundry.generation_v3 as subject

    source = Path(subject.__file__).read_text(encoding="utf-8")
    for token in (
        "TaskSemantics",
        "NativeAuditor",
        "qualification_v2",
        "semantics_author",
        "verifier_author",
        "TrustedProxy",
    ):
        assert token not in source


def test_internal_v3_import_graph_does_not_load_task_authority() -> None:
    probe = subprocess.run(
        (
            sys.executable,
            "-I",
            "-B",
            "-c",
            "import sys,agent_env_foundry.generation_v3;"
            "print('\\n'.join(sorted(n for n in sys.modules "
            "if n in ('agent_env_foundry.semantics_author',"
            "'agent_env_foundry.qualification_v2',"
            "'agent_env_foundry.verifier_author',"
            "'agent_env_foundry.task_foundry'))))",
        ),
        check=False,
        capture_output=True,
        text=True,
    )
    assert probe.returncode == 0, probe.stderr
    assert probe.stdout == "\n"
