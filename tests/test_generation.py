"""Focused orchestration tests; real Git/SQLite runs own S1 success evidence."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from tests.v2_release_factory import build_v2_release

from agent_env_foundry.builder import BuilderFailure
from agent_env_foundry.preparation import (
    PreparationExecutionError,
    PreparationSettings,
    ProjectMaterializationInput,
    read_actor_tool_catalog,
)
from agent_env_foundry.project_identity import compute_authored_project_digest
from agent_env_foundry.research import NotReleased
from agent_env_foundry.semantics import SemanticsContractError


class _ResearchReady:
    builder_projection = object()
    digest = "1" * 64

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}", encoding="utf-8")


class _Tools:
    closed = False

    def close(self) -> None:
        self.closed = True


def test_generation_reserves_a_post_mechanical_semantic_repair_turn() -> None:
    import agent_env_foundry.generation as subject

    assert subject.GenerationConfig().author.max_turns == 4


def _install_success_stages(monkeypatch: pytest.MonkeyPatch) -> tuple[Any, list[str]]:
    import agent_env_foundry.generation as subject

    calls: list[str] = []

    def stage(name: str, result: Any):
        def run(*args: Any, **kwargs: Any) -> Any:
            calls.append(name)
            return result

        return run

    actor = SimpleNamespace(workspace=Path("actor"), candidate_digest="2" * 64)
    surface = SimpleNamespace(manifest_digest="3" * 64)
    expected = SimpleNamespace(canonical_payload=b"{}", digest="4" * 64)
    semantics_inputs = SimpleNamespace(root=Path("semantics-inputs"))
    verifier_inputs = SimpleNamespace(root=Path("verifier-inputs"))
    semantics = SimpleNamespace(
        root=Path("semantics"), project_digest="5" * 64, factory="semantics:factory"
    )
    verifier = SimpleNamespace(
        root=Path("verifier"), project_digest="6" * 64, factory="verifier:factory"
    )
    core = object()
    qualification = SimpleNamespace(
        receipt=object(),
        qualified_catalog=object(),
        requirement_coverage=object(),
        qualified_start_cases=object(),
        evidence_root=Path("evidence"),
    )
    release = SimpleNamespace(release_id="7" * 64, root=Path("release"))
    prepared = object()

    monkeypatch.setattr(subject, "ResearchReady", _ResearchReady)
    monkeypatch.setattr(subject, "ResearchTools", lambda **kwargs: _Tools())
    monkeypatch.setattr(subject, "run_research", stage("research", _ResearchReady()))
    monkeypatch.setattr(subject, "run_builder", stage("environment_builder", actor))
    monkeypatch.setattr(subject, "_freeze_public_surface", stage("public_surface", surface))
    monkeypatch.setattr(
        subject, "generate_expected_task_semantics", stage("expected_semantics", expected)
    )
    monkeypatch.setattr(
        subject,
        "prepare_semantics_author_workspace",
        stage("prepare_semantics_author", semantics_inputs),
    )
    monkeypatch.setattr(
        subject,
        "prepare_verifier_author_workspace",
        stage("prepare_verifier_author", verifier_inputs),
    )
    monkeypatch.setattr(subject, "run_semantics_author", stage("semantics_author", semantics))
    monkeypatch.setattr(subject, "run_verifier_author", stage("verifier_author", verifier))
    monkeypatch.setattr(subject, "derive_qualification_core", stage("derive_core", core))
    monkeypatch.setattr(subject, "run_v2_qualification", stage("qualification", qualification))
    monkeypatch.setattr(subject, "publish_release_v2", stage("publication", release))
    monkeypatch.setattr(subject, "write_release_zip_v2", stage("write_zip", Path("release.zip")))
    monkeypatch.setattr(subject, "prepare_release", stage("cold_prepare", prepared))
    return prepared, calls


def test_generate_environment_uses_existing_s1_stages_in_order(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import agent_env_foundry.generation as subject

    prepared, calls = _install_success_stages(monkeypatch)
    result = subject.generate_environment_v2(
        "Build a resettable environment.",
        work_root=tmp_path / "work",
        output_root=tmp_path / "output",
        config=subject.GenerationConfig(),
    )

    assert isinstance(result, subject.Released)
    assert result.prepared is prepared
    assert result.release_id == "7" * 64
    assert calls == [
        "research",
        "environment_builder",
        "public_surface",
        "expected_semantics",
        "prepare_semantics_author",
        "prepare_verifier_author",
        "semantics_author",
        "verifier_author",
        "derive_core",
        "qualification",
        "publication",
        "write_zip",
        "cold_prepare",
    ]


def test_research_nonrelease_stops_before_builder(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import agent_env_foundry.generation as subject

    monkeypatch.setattr(subject, "ResearchTools", lambda **kwargs: _Tools())
    monkeypatch.setattr(
        subject,
        "run_research",
        lambda **kwargs: NotReleased("research_gap", "not closed", {"phase": "brief"}),
    )
    monkeypatch.setattr(
        subject,
        "run_builder",
        lambda *args, **kwargs: pytest.fail("Builder must not run after Research failure"),
    )

    result = subject.generate_environment_v2(
        "Build a resettable environment.",
        work_root=tmp_path / "work",
        output_root=tmp_path / "output",
        config=subject.GenerationConfig(),
    )

    assert isinstance(result, NotReleased)
    assert result.code == "research_gap"
    assert result.details["owner"] == "Research"


def test_research_provider_failure_is_infrastructure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import agent_env_foundry.generation as subject

    monkeypatch.setattr(subject, "ResearchTools", lambda **kwargs: _Tools())
    monkeypatch.setattr(
        subject,
        "run_research",
        lambda **kwargs: NotReleased(
            "responses_request_failed",
            "stream disconnected",
            {"phase": "reviewer", "original_code": "APIStatusError"},
        ),
    )

    result = subject.generate_environment_v2(
        "Build a resettable environment.",
        work_root=tmp_path / "work",
        output_root=tmp_path / "output",
        config=subject.GenerationConfig(),
    )

    assert isinstance(result, NotReleased)
    assert result.details["owner"] == "Infrastructure"


def test_builder_failure_preserves_owner_and_stops_later_stages(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    import agent_env_foundry.generation as subject

    monkeypatch.setattr(subject, "ResearchReady", _ResearchReady)
    monkeypatch.setattr(subject, "ResearchTools", lambda **kwargs: _Tools())
    monkeypatch.setattr(subject, "run_research", lambda **kwargs: _ResearchReady())

    def fail_builder(*args: Any, **kwargs: Any) -> None:
        raise BuilderFailure("build", "builder_failed", "actor did not pass")

    monkeypatch.setattr(subject, "run_builder", fail_builder)
    monkeypatch.setattr(
        subject,
        "_freeze_public_surface",
        lambda *args, **kwargs: pytest.fail("later stages must not run"),
    )

    result = subject.generate_environment_v2(
        "Build a resettable environment.",
        work_root=tmp_path / "work",
        output_root=tmp_path / "output",
        config=subject.GenerationConfig(),
    )

    assert isinstance(result, NotReleased)
    assert result.code == "builder_failed"
    assert result.details["owner"] == "EnvironmentBuilder"
    assert result.details["phase"] == "build"


@pytest.mark.parametrize(
    ("failure", "expected_code"),
    (
        (
            PreparationExecutionError(
                "SemanticsDefect",
                "child_call_failed",
                "enumerate_bindings failed",
                operation="enumerate_bindings",
                error={"type": "NameError", "message": "cid is not defined"},
            ),
            "child_call_failed",
        ),
        (SemanticsContractError("facets must be a JSON object"), "semantics_wire_invalid"),
    ),
)
def test_semantics_defect_resumes_original_author_before_requalification(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    failure: Exception,
    expected_code: str,
) -> None:
    import agent_env_foundry.generation as subject

    _prepared, _calls = _install_success_stages(monkeypatch)
    qualification = SimpleNamespace(
        receipt=object(),
        qualified_catalog=object(),
        requirement_coverage=object(),
        qualified_start_cases=object(),
        evidence_root=Path("evidence"),
    )
    attempts = 0

    def qualify(*args: Any, **kwargs: Any) -> Any:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise failure
        return qualification

    observed: dict[str, Any] = {}

    def repair(_inputs: Any, build: Any, findings: Any, *, config: Any) -> Any:
        observed["build"] = build
        observed["finding"] = findings[0]
        observed["config"] = config
        return SimpleNamespace(
            root=Path("semantics-repaired"),
            project_digest="8" * 64,
            factory="semantics:factory",
        )

    monkeypatch.setattr(subject, "run_v2_qualification", qualify)
    monkeypatch.setattr(subject, "repair_semantics_author", repair)

    result = subject.generate_environment_v2(
        "Build a resettable environment.",
        work_root=tmp_path / "work",
        output_root=tmp_path / "output",
        config=subject.GenerationConfig(),
    )

    assert isinstance(result, subject.Released)
    assert attempts == 2
    assert observed["finding"].source == "native_physical_check"
    assert observed["finding"].code == expected_code
    assert [event["stage"] for event in result.events].count("qualification") == 2
    assert any(event["stage"] == "semantics_repair" for event in result.events)


def test_actor_catalog_is_read_in_its_locked_runtime(tmp_path: Path) -> None:
    fixture = build_v2_release(tmp_path / "fixture")
    actor = fixture / "actor"
    digest = compute_authored_project_digest(actor, "actor", require_locked_project=True)
    settings = PreparationSettings(tmp_path / "uv-cache", 120.0)

    tools = read_actor_tool_catalog(
        ProjectMaterializationInput(
            actor,
            digest,
            "shared_actor",
            ("shared_semantics", "generated_qualification_verifier", "agent_env_foundry"),
            "actor",
        ),
        tmp_path / "runtime",
        factory="shared_actor:make_environment",
        settings=settings,
    )

    assert [tool["name"] for tool in tools] == ["increment"]
