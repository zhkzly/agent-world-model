"""Fail-closed tests for the direct S1 coordinator.

Fakes in this module exercise routing and attribution only.  They are never
allowed to produce a ``Released`` outcome; the positive path is a live S1
proof using real Research, Builder, Qualification, and cold publication.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

import agent_env_foundry.api as api_module
from agent_env_foundry.api import GenerationConfig, generate_environment
from agent_env_foundry.builder import BuilderFailure, CandidateBuild
from agent_env_foundry.publication import EnvironmentRelease, PublicationError
from agent_env_foundry.qualification import QualificationResult
from agent_env_foundry.research import (
    DevelopmentBrief,
    EvidenceIndex,
    EvidenceReview,
    NotReleased,
    ResearchFailure,
    ResearchReady,
    finalize_research,
)


def _config(tmp_path: Path) -> GenerationConfig:
    return GenerationConfig(
        run_store=tmp_path / "runs",
        release_store=tmp_path / "releases",
    )


def test_generation_config_resolves_storage_roots(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)

    config = GenerationConfig(run_store=Path("runs"), release_store=Path("releases"))

    assert config.run_store == tmp_path / "runs"
    assert config.release_store == tmp_path / "releases"


def _research_ready() -> ResearchReady:
    brief = DevelopmentBrief.for_test(
        markdown="# Accepted mechanical Brief\n",
        evidence_index=EvidenceIndex(entries=()),
        requirement_ids=("REQ-001",),
    )
    review = EvidenceReview(
        clause_findings=(
            {
                "clause_id": "NEED-001",
                "judgment": "supported",
                "rationale": "Mechanical coordinator fixture.",
                "evidence_refs": [],
            },
        ),
        requirement_findings=(
            {
                "requirement_id": "REQ-001",
                "judgment": "supported",
                "rationale": "Mechanical coordinator fixture.",
                "evidence_refs": [],
            },
        ),
        scope_assessment={
            "judgment": "supported",
            "rationale": "Mechanical coordinator fixture.",
        },
        residual_limitations=(),
        unsupported_findings=(),
    )
    ready = finalize_research(brief=brief, review=review)
    assert isinstance(ready, ResearchReady)
    return ready


def test_research_rejection_stops_before_builder_and_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rejected = NotReleased("research_failed", "Research failed", {"phase": "research"})
    monkeypatch.setattr(api_module, "run_research", lambda **_kwargs: rejected)
    monkeypatch.setattr(
        api_module,
        "run_builder",
        lambda *_args, **_kwargs: pytest.fail("Builder must not run"),
    )

    outcome = generate_environment("Create a real resettable world.", config=_config(tmp_path))

    assert outcome == rejected
    assert not (tmp_path / "releases").exists()


def test_builder_failure_is_attributed_and_stops_qualification(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(api_module, "run_research", lambda **_kwargs: _research_ready())

    def fail_builder(*_args: object, **_kwargs: object) -> CandidateBuild:
        raise BuilderFailure(
            "candidate_test",
            "candidate_tests_failed",
            "Candidate-owned tests failed",
            exit_code=1,
        )

    monkeypatch.setattr(api_module, "run_builder", fail_builder)
    monkeypatch.setattr(
        api_module,
        "run_qualification",
        lambda *_args, **_kwargs: pytest.fail("Qualification must not run"),
    )

    outcome = generate_environment("Create a real resettable world.", config=_config(tmp_path))

    assert isinstance(outcome, NotReleased)
    assert outcome.code == "candidate_tests_failed"
    assert outcome.details["phase"] == "candidate_test"
    assert not (tmp_path / "releases").exists()


def test_builder_filesystem_failure_is_typed_infrastructure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(api_module, "run_research", lambda **_kwargs: _research_ready())
    monkeypatch.setattr(
        api_module,
        "run_builder",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            FileNotFoundError("candidate workspace disappeared")
        ),
    )

    outcome = generate_environment("Create a real resettable world.", config=_config(tmp_path))

    assert isinstance(outcome, NotReleased)
    assert outcome.code == "infrastructure_failure"
    assert outcome.details["phase"] == "builder"
    assert not (tmp_path / "releases").exists()


def test_qualification_failure_cannot_reach_assembly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ready = _research_ready()
    candidate_root = tmp_path / "candidate"
    candidate_root.mkdir()
    candidate = CandidateBuild(candidate_root, "thread", "a" * 64, "done", ())
    monkeypatch.setattr(api_module, "run_research", lambda **_kwargs: ready)
    monkeypatch.setattr(api_module, "run_builder", lambda *_args, **_kwargs: candidate)
    monkeypatch.setattr(
        api_module,
        "generate_expected_task_semantics",
        lambda *_args, **_kwargs: object(),
    )
    monkeypatch.setattr(
        api_module,
        "run_qualification",
        lambda *_args, **_kwargs: QualificationResult(
            status="candidate_defect",
            candidate_digest=candidate.candidate_digest,
            expected_relations_digest="b" * 64,
            failure_code="candidate_runtime_failed",
            details={"message": "public/native mismatch"},
        ),
    )
    monkeypatch.setattr(
        api_module,
        "assemble_environment_release",
        lambda *_args, **_kwargs: pytest.fail("Assembly must not run"),
    )

    outcome = generate_environment("Create a real resettable world.", config=_config(tmp_path))

    assert isinstance(outcome, NotReleased)
    assert outcome.code == "candidate_runtime_failed"
    assert outcome.details["qualification_status"] == "candidate_defect"
    assert not (tmp_path / "releases").exists()


def test_expected_semantics_failure_stops_before_qualification(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ready = _research_ready()
    candidate_root = tmp_path / "candidate"
    candidate_root.mkdir()
    candidate = CandidateBuild(candidate_root, "thread", "a" * 64, "done", ())
    monkeypatch.setattr(api_module, "run_research", lambda **_kwargs: ready)
    monkeypatch.setattr(api_module, "run_builder", lambda *_args, **_kwargs: candidate)
    monkeypatch.setattr(
        api_module,
        "generate_expected_task_semantics",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            ResearchFailure(
                phase="expected_semantics",
                code="expected_semantics_invalid",
                message="Requirement coverage mismatch",
                details={"findings": ["REQ-001 omitted"]},
            )
        ),
    )
    monkeypatch.setattr(
        api_module,
        "run_qualification",
        lambda *_args, **_kwargs: pytest.fail("Qualification must not run"),
    )

    outcome = generate_environment("Create a real resettable world.", config=_config(tmp_path))

    assert isinstance(outcome, NotReleased)
    assert outcome.code == "expected_semantics_invalid"
    assert outcome.details["phase"] == "expected_semantics"
    assert outcome.details["findings"] == ["REQ-001 omitted"]


def test_semantics_author_failure_stops_before_assembly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ready = _research_ready()
    candidate_root = tmp_path / "candidate"
    candidate_root.mkdir()
    candidate = CandidateBuild(candidate_root, "thread", "a" * 64, "done", ())
    qualification = QualificationResult(
        status="passed",
        candidate_digest=candidate.candidate_digest,
        expected_relations_digest="b" * 64,
        evidence_digest="c" * 64,
        probe_bundle_digest="d" * 64,
        negative_evidence_count=1,
        workspace_root=tmp_path / "qualification",
        semantics_author_inputs=object(),
        expected_task_semantics_digest="e" * 64,
        public_surface_digest="f" * 64,
    )
    monkeypatch.setattr(api_module, "run_research", lambda **_kwargs: ready)
    monkeypatch.setattr(api_module, "run_builder", lambda *_args, **_kwargs: candidate)
    monkeypatch.setattr(
        api_module,
        "generate_expected_task_semantics",
        lambda *_args, **_kwargs: object(),
    )
    monkeypatch.setattr(api_module, "run_qualification", lambda *_args, **_kwargs: qualification)
    monkeypatch.setattr(
        api_module,
        "run_semantics_author",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            api_module.SemanticsAuthorFailure(
                "semantics_author",
                "semantics_source_forbidden",
                "actor import is forbidden",
            )
        ),
    )
    monkeypatch.setattr(
        api_module,
        "assemble_environment_release",
        lambda *_args, **_kwargs: pytest.fail("Assembly must not run"),
    )

    outcome = generate_environment("Create a real resettable world.", config=_config(tmp_path))

    assert isinstance(outcome, NotReleased)
    assert outcome.code == "semantics_source_forbidden"
    assert outcome.details["phase"] == "semantics_author"


def test_cold_failure_blocks_immutable_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ready = _research_ready()
    candidate_root = tmp_path / "candidate"
    candidate_root.mkdir()
    candidate = CandidateBuild(candidate_root, "thread", "a" * 64, "done", ())
    qualification_root = tmp_path / "qualification"
    qualification_root.mkdir()
    qualification = QualificationResult(
        status="passed",
        candidate_digest=candidate.candidate_digest,
        expected_relations_digest="b" * 64,
        evidence_digest="c" * 64,
        probe_bundle_digest="d" * 64,
        negative_evidence_count=1,
        workspace_root=qualification_root,
        semantics_author_inputs=object(),
        expected_task_semantics_digest="3" * 64,
        public_surface_digest="4" * 64,
    )
    assembled_root = tmp_path / "assembled-fixture"
    assembled_root.mkdir()
    assembled = EnvironmentRelease(
        release_id="e" * 64,
        root=assembled_root,
        project_root=assembled_root / "project",
        payload_digest="f" * 64,
        qualification_digest="1" * 64,
    )
    monkeypatch.setattr(api_module, "run_research", lambda **_kwargs: ready)
    monkeypatch.setattr(api_module, "run_builder", lambda *_args, **_kwargs: candidate)
    monkeypatch.setattr(
        api_module,
        "generate_expected_task_semantics",
        lambda *_args, **_kwargs: object(),
    )
    monkeypatch.setattr(api_module, "run_qualification", lambda *_args, **_kwargs: qualification)
    monkeypatch.setattr(
        api_module,
        "run_semantics_author",
        lambda *_args, **_kwargs: SimpleNamespace(
            thread_id="semantics-thread",
            factory="generated_task_semantics.release:make_semantics",
            project_digest="5" * 64,
            checks=(),
        ),
    )
    monkeypatch.setattr(
        api_module,
        "qualify_semantic_capabilities",
        lambda *_args, **_kwargs: SimpleNamespace(
            semantics_digest="5" * 64,
            public_episode_digest="6" * 64,
            native_evidence_digest="8" * 64,
            evidence_digest="7" * 64,
            capabilities=(),
        ),
    )
    monkeypatch.setattr(api_module, "assemble_environment_release", lambda *_args: assembled)

    def write_archive(_root: Path, destination: Path) -> str:
        destination.write_bytes(b"mechanical archive")
        return "2" * 64

    monkeypatch.setattr(api_module, "write_release_zip", write_archive)
    monkeypatch.setattr(
        api_module,
        "cold_verify_environment_release",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            PublicationError(
                "cold_qualification",
                "cold_qualification_failed",
                "Cold replay failed",
            )
        ),
    )
    monkeypatch.setattr(
        api_module,
        "publish_environment_release",
        lambda *_args, **_kwargs: pytest.fail("Publication must not run"),
    )

    outcome = generate_environment("Create a real resettable world.", config=_config(tmp_path))

    assert isinstance(outcome, NotReleased)
    assert outcome.code == "cold_qualification_failed"
    assert outcome.details["phase"] == "cold_qualification"
    assert not (tmp_path / "releases").exists()


def test_semantic_qualification_failure_blocks_release_assembly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ready = _research_ready()
    candidate_root = tmp_path / "candidate"
    candidate_root.mkdir()
    candidate = CandidateBuild(candidate_root, "thread", "a" * 64, "done", ())
    qualification_root = tmp_path / "qualification"
    qualification_root.mkdir()
    qualification = QualificationResult(
        status="passed",
        candidate_digest=candidate.candidate_digest,
        expected_relations_digest="b" * 64,
        evidence_digest="c" * 64,
        probe_bundle_digest="d" * 64,
        negative_evidence_count=1,
        workspace_root=qualification_root,
        semantics_author_inputs=object(),
        expected_task_semantics_digest="3" * 64,
        public_surface_digest="4" * 64,
    )
    semantics = SimpleNamespace(
        root=tmp_path / "semantics",
        codex_home=tmp_path / "semantics-home",
        thread_id="semantics-thread",
        factory="generated_task_semantics.release:make_semantics",
        project_digest="5" * 64,
        checks=(),
    )
    monkeypatch.setattr(api_module, "run_research", lambda **_kwargs: ready)
    monkeypatch.setattr(api_module, "run_builder", lambda *_args, **_kwargs: candidate)
    monkeypatch.setattr(
        api_module,
        "generate_expected_task_semantics",
        lambda *_args, **_kwargs: object(),
    )
    monkeypatch.setattr(api_module, "run_qualification", lambda *_args, **_kwargs: qualification)
    monkeypatch.setattr(api_module, "run_semantics_author", lambda *_args, **_kwargs: semantics)
    qualification_calls = 0

    def rejected_semantics(*_args: object, **_kwargs: object) -> object:
        nonlocal qualification_calls
        qualification_calls += 1
        raise api_module.SemanticQualificationFailure(
            "semantic_noop_accepted",
            "Evaluator accepted a no-op",
        )

    repair_calls = 0

    def repair(*_args: object, **_kwargs: object) -> object:
        nonlocal repair_calls
        repair_calls += 1
        return semantics

    monkeypatch.setattr(api_module, "qualify_semantic_capabilities", rejected_semantics)
    monkeypatch.setattr(api_module, "repair_semantics_author", repair)
    monkeypatch.setattr(
        api_module,
        "assemble_environment_release",
        lambda *_args, **_kwargs: pytest.fail("Assembly must not run"),
    )

    outcome = generate_environment("Create a real resettable world.", config=_config(tmp_path))

    assert isinstance(outcome, NotReleased)
    assert outcome.code == "semantic_noop_accepted"
    assert outcome.details["phase"] == "semantic_qualification"
    assert qualification_calls == 2
    assert repair_calls == 1


def test_native_oracle_disagreement_is_not_routed_to_semantics_self_repair() -> None:
    assert api_module._semantics_repairable("semantic_noop_accepted")
    assert not api_module._semantics_repairable("semantic_native_disagreement")
