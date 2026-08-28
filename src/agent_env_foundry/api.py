"""Direct S1 Need-to-EnvironmentRelease coordinator."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from agent_env_foundry.agents import AgentRoute, run_research
from agent_env_foundry.builder import (
    BuilderConfig,
    BuilderFailure,
    CandidateBuild,
    repair_builder,
    run_builder,
)
from agent_env_foundry.errors import EnvironmentContractError
from agent_env_foundry.publication import (
    ColdReleaseConfig,
    EnvironmentRelease,
    PublicationError,
    assemble_environment_release,
    cold_verify_environment_release,
    publish_environment_release,
    verify_environment_release,
    write_release_zip,
)
from agent_env_foundry.qualification import (
    QualificationConfig,
    QualificationFailure,
    QualificationResult,
    run_qualification,
)
from agent_env_foundry.research import (
    EvidenceStore,
    NeedRecord,
    NotReleased,
    ResearchBudget,
    ResearchConfig,
    ResearchFailure,
    ResearchReady,
    ResearchTools,
    Unsupported,
)
from agent_env_foundry.semantic_qualification import (
    SemanticQualificationFailure,
    qualify_semantic_capabilities,
)
from agent_env_foundry.semantics_author import (
    SemanticsAuthorFailure,
    repair_semantics_author,
    run_semantics_author,
)
from agent_env_foundry.semantics_authoring import generate_expected_task_semantics

__all__ = [
    "GenerationConfig",
    "GenerationOutcome",
    "Released",
    "generate_environment",
    "outcome_document",
]


@dataclass(frozen=True)
class GenerationConfig:
    """Invocation-local resources for one direct S1 generation run."""

    run_store: Path = Path(".artifacts/foundry-runs")
    release_store: Path = Path(".artifacts/environment-releases")
    route: AgentRoute = field(default_factory=AgentRoute)
    research: ResearchConfig = field(default_factory=ResearchConfig)
    research_budget: ResearchBudget = field(default_factory=ResearchBudget)
    builder: BuilderConfig = field(default_factory=BuilderConfig)
    qualification: QualificationConfig = field(default_factory=QualificationConfig)
    cold: ColdReleaseConfig = field(default_factory=ColdReleaseConfig)

    def __post_init__(self) -> None:
        run_store = Path(self.run_store).resolve()
        release_store = Path(self.release_store).resolve()
        object.__setattr__(self, "run_store", run_store)
        object.__setattr__(self, "release_store", release_store)
        if run_store == release_store:
            raise ValueError("run_store and release_store must be distinct")


@dataclass(frozen=True)
class Released:
    """A cold-qualified immutable release and its audit lineage."""

    release: EnvironmentRelease
    run_root: Path
    research_digest: str
    candidate_digest: str
    qualification_evidence_digest: str
    semantic_qualification_evidence_digest: str
    cold_evidence_digest: str
    archive_digest: str


type GenerationOutcome = Released | NotReleased | Unsupported


def generate_environment(
    need_text: str,
    *,
    config: GenerationConfig | None = None,
) -> GenerationOutcome:
    """Execute the direct S1 pipeline and publish only after a cold replay passes."""
    selected = config or GenerationConfig()
    try:
        need = NeedRecord.from_text(need_text)
    except ValueError as exc:
        return NotReleased(
            code="invalid_need",
            message=str(exc),
            details={"phase": "input", "error_type": type(exc).__name__},
        )

    try:
        run_root = _create_run_root(selected.run_store)
        _write_json(run_root / "need.json", need.to_document())
    except OSError as exc:
        return _infrastructure_failure("run_setup", exc)

    research_root = run_root / "research"
    try:
        tools = ResearchTools(
            store=EvidenceStore(research_root / "evidence"),
            config=selected.research,
            budget=selected.research_budget,
        )
        try:
            research = run_research(need=need, tools=tools, route=selected.route)
        finally:
            tools.close()
    except OSError as exc:
        return _finish(run_root, _infrastructure_failure("research", exc))

    if not isinstance(research, ResearchReady):
        return _finish(run_root, research)
    research.write(research_root / "research-ready.json")

    try:
        candidate = run_builder(
            research.builder_projection,
            run_root / "candidate",
            config=selected.builder,
        )
    except BuilderFailure as exc:
        return _finish(
            run_root,
            NotReleased(exc.code, str(exc), dict(exc.details)),
        )
    except OSError as exc:
        return _finish(run_root, _infrastructure_failure("builder", exc))
    _write_candidate_record(run_root, candidate)

    try:
        expected_task_semantics = generate_expected_task_semantics(
            research.builder_projection,
            route=replace(
                selected.route,
                max_provider_turns=min(selected.route.max_provider_turns, 3),
            ),
        )
    except ResearchFailure as exc:
        return _finish(
            run_root,
            NotReleased(
                exc.code,
                str(exc),
                {"phase": exc.phase, **dict(exc.details)},
            ),
        )

    predicate_source_root: Path | None = None
    predicate_source_digest: str | None = None
    while True:
        qualification_root = (
            run_root / "qualification"
            if candidate.revision == 1
            else run_root / f"qualification-attempt-{candidate.revision:03d}"
        )
        qualification = run_qualification(
            research.builder_projection,
            candidate.workspace,
            candidate.candidate_digest,
            qualification_root,
            expected_task_semantics=expected_task_semantics,
            config=selected.qualification,
            predicate_source_root=predicate_source_root,
            predicate_source_digest=predicate_source_digest,
        )
        if qualification.status == "passed":
            break
        if qualification.candidate_finding is None:
            return _finish(run_root, _qualification_failure(qualification))
        if qualification.workspace_root is None or qualification.predicate_digest is None:
            return _finish(
                run_root,
                NotReleased(
                    "candidate_repair_lineage_missing",
                    "Candidate repair requires the prior fresh Qualification lineage",
                    {"phase": "qualification"},
                ),
            )
        try:
            _write_json(
                run_root / f"candidate-repair-{candidate.revision:03d}.json",
                {
                    "rejected_candidate_digest": candidate.candidate_digest,
                    "finding": qualification.candidate_finding.to_document(),
                },
            )
            predicate_source_root = qualification.workspace_root
            predicate_source_digest = qualification.predicate_digest
            candidate = repair_builder(
                candidate,
                qualification.candidate_finding,
                failed_candidate_digest=qualification.candidate_digest,
                config=selected.builder,
            )
            _write_candidate_record(run_root, candidate)
        except BuilderFailure as exc:
            return _finish(run_root, NotReleased(exc.code, str(exc), dict(exc.details)))
        except OSError as exc:
            return _finish(run_root, _infrastructure_failure("builder_repair", exc))
    if (
        qualification.workspace_root is None
        or qualification.evidence_digest is None
        or qualification.semantics_author_inputs is None
        or qualification.expected_task_semantics_digest is None
        or qualification.public_surface_digest is None
    ):
        return _finish(
            run_root,
            NotReleased(
                "qualification_incomplete",
                "Passing Qualification omitted its replay lineage",
                {"phase": "qualification"},
            ),
        )

    try:
        semantics = run_semantics_author(
            qualification.semantics_author_inputs,
            config=selected.builder,
        )
    except SemanticsAuthorFailure as exc:
        return _finish(
            run_root,
            NotReleased(exc.code, str(exc), dict(exc.details)),
        )
    except (QualificationFailure, BuilderFailure) as exc:
        return _finish(
            run_root,
            NotReleased(exc.code, str(exc), dict(exc.details)),
        )
    except Exception as exc:
        return _finish(
            run_root,
            NotReleased(
                "semantics_author_sdk_failed",
                "Semantics Author SDK execution failed",
                {
                    "phase": "semantics_author",
                    "error_type": type(exc).__name__,
                    "message": str(exc),
                },
            ),
        )
    _write_json(
        run_root / "semantics.json",
        {
            "thread_id": semantics.thread_id,
            "factory": semantics.factory,
            "project_digest": semantics.project_digest,
            "checks": [item.to_document() for item in semantics.checks],
            "expected_task_semantics_digest": qualification.expected_task_semantics_digest,
            "public_surface_digest": qualification.public_surface_digest,
        },
    )
    semantic_qualification = None
    for semantic_attempt in range(2):
        try:
            semantic_qualification = qualify_semantic_capabilities(
                semantics,
                qualification,
                candidate.workspace,
                config=selected.qualification,
                route=selected.route,
                runtime_root=run_root / f"semantic-qualification-attempt-{semantic_attempt + 1}",
            )
            break
        except SemanticQualificationFailure as exc:
            if semantic_attempt > 0 or not _semantics_repairable(exc.code):
                return _finish(
                    run_root,
                    NotReleased(exc.code, str(exc), dict(exc.details)),
                )
            finding = {
                "code": exc.code,
                "message": str(exc),
                "actual": dict(exc.details),
                "expected": (
                    "The generated TaskSemantics contract must agree with the frozen public "
                    "answer/binding contract and the independent native oracle on every "
                    "applicable positive and negative result axis."
                ),
                "repair": (
                    "Change only release-local semantic source/tests; preserve immutable "
                    "inputs and passed capabilities. Do not weaken Host gates or Actor behavior."
                ),
            }
            try:
                semantics = repair_semantics_author(
                    qualification.semantics_author_inputs,
                    semantics,
                    [finding],
                    config=selected.builder,
                )
            except (SemanticsAuthorFailure, QualificationFailure, BuilderFailure) as repair_exc:
                return _finish(
                    run_root,
                    NotReleased(repair_exc.code, str(repair_exc), dict(repair_exc.details)),
                )
            _write_json(
                run_root / f"semantics-repair-{semantic_attempt + 1}.json",
                {
                    "thread_id": semantics.thread_id,
                    "project_digest": semantics.project_digest,
                    "trigger": finding,
                    "checks": [item.to_document() for item in semantics.checks],
                },
            )
    if semantic_qualification is None:
        return _finish(
            run_root,
            NotReleased(
                "semantic_qualification_missing",
                "Semantic Qualification produced no terminal result",
                {"phase": "semantic_qualification"},
            ),
        )
    _write_json(
        run_root / "semantic-qualification.json",
        {
            "semantics_digest": semantic_qualification.semantics_digest,
            "public_episode_digest": semantic_qualification.public_episode_digest,
            "native_evidence_digest": semantic_qualification.native_evidence_digest,
            "evidence_digest": semantic_qualification.evidence_digest,
            "capabilities": [item.to_document() for item in semantic_qualification.capabilities],
        },
    )

    try:
        assembled = assemble_environment_release(
            candidate.workspace,
            qualification,
            research.brief.markdown,
            run_root / "assembled-release",
        )
        staging_archive = run_root / f"{assembled.release_id}.zip"
        archive_digest = write_release_zip(assembled.root, staging_archive)
        cold = cold_verify_environment_release(
            staging_archive,
            run_root / "cold",
            research.builder_projection,
            qualification.workspace_root,
            config=selected.cold,
        )
        if cold.qualification.evidence_digest is None:
            raise PublicationError(
                "cold_qualification",
                "cold_evidence_missing",
                "Cold Qualification omitted its evidence digest",
            )
        published = publish_environment_release(assembled.root, selected.release_store)
        if published.archive is None:
            raise PublicationError(
                "publication", "published_archive_missing", "Publication omitted its ZIP artifact"
            )
        published_archive_digest = _sha256_file(published.archive)
        if published_archive_digest != archive_digest:
            raise PublicationError(
                "publication",
                "published_archive_digest_mismatch",
                "Published archive differs from the exact cold-qualified archive",
                cold_archive_digest=archive_digest,
                published_archive_digest=published_archive_digest,
            )
        verified = verify_environment_release(published.root)
    except (PublicationError, EnvironmentContractError) as exc:
        if isinstance(exc, PublicationError):
            return _finish(run_root, NotReleased(exc.code, str(exc), dict(exc.details)))
        return _finish(
            run_root,
            NotReleased(
                "release_invalid",
                str(exc),
                {"phase": "publication", "error_type": type(exc).__name__},
            ),
        )
    except OSError as exc:
        return _finish(run_root, _infrastructure_failure("publication", exc))

    outcome = Released(
        release=EnvironmentRelease(
            release_id=verified.release_id,
            root=verified.root,
            project_root=verified.project_root,
            payload_digest=verified.payload_digest,
            qualification_digest=verified.qualification_digest,
            archive=published.archive,
        ),
        run_root=run_root,
        research_digest=research.digest,
        candidate_digest=candidate.candidate_digest,
        qualification_evidence_digest=qualification.evidence_digest,
        semantic_qualification_evidence_digest=semantic_qualification.evidence_digest,
        cold_evidence_digest=cold.qualification.evidence_digest,
        archive_digest=archive_digest,
    )
    return _finish(run_root, outcome)


def outcome_document(outcome: GenerationOutcome) -> dict[str, Any]:
    if isinstance(outcome, Released):
        return {
            "status": "released",
            "release_id": outcome.release.release_id,
            "release_root": str(outcome.release.root),
            "archive": str(outcome.release.archive) if outcome.release.archive else None,
            "payload_digest": outcome.release.payload_digest,
            "qualification_digest": outcome.release.qualification_digest,
            "research_digest": outcome.research_digest,
            "candidate_digest": outcome.candidate_digest,
            "qualification_evidence_digest": outcome.qualification_evidence_digest,
            "semantic_qualification_evidence_digest": (
                outcome.semantic_qualification_evidence_digest
            ),
            "cold_evidence_digest": outcome.cold_evidence_digest,
            "archive_digest": outcome.archive_digest,
            "run_root": str(outcome.run_root),
        }
    return {
        "status": "unsupported" if isinstance(outcome, Unsupported) else "not_released",
        "code": outcome.code,
        "message": outcome.message,
        "details": json.loads(json.dumps(outcome.details, default=str)),
    }


def _create_run_root(store: Path) -> Path:
    requested = Path(store)
    if requested.is_symlink():
        raise OSError("run_store must not be a symlink")
    root = requested.resolve()
    root.mkdir(parents=True, exist_ok=True)
    run = root / f"run-{uuid.uuid4().hex}"
    run.mkdir(mode=0o700)
    return run


_REPAIRABLE_SEMANTIC_FAILURES = frozenset(
    {
        "semantic_prompted_binding_rejected",
        "semantic_public_binding_ambiguous",
        "semantic_public_binding_hidden",
        "semantic_answer_not_grounded",
        "semantic_answer_report_missing",
        "semantic_answer_report_invalid",
        "semantic_wrong_answer_accepted",
        "semantic_process_violation_accepted",
        "semantic_noop_accepted",
        "semantic_wrong_target_accepted",
        "semantic_physical_wrong_target_accepted",
        "semantic_fresh_replay_mismatch",
        "semantic_fresh_replay_facts_mismatch",
    }
)


def _semantics_repairable(code: str) -> bool:
    return code in _REPAIRABLE_SEMANTIC_FAILURES


def _write_candidate_record(run_root: Path, candidate: CandidateBuild) -> None:
    document = {
        "revision": candidate.revision,
        "candidate_digest": candidate.candidate_digest,
        "thread_id": candidate.thread_id,
        "turns_used": candidate.turns_used,
        "checks": [item.to_document() for item in candidate.checks],
    }
    _write_json(run_root / "candidate.json", document)
    _write_json(
        run_root / f"candidate-revision-{candidate.revision:03d}.json",
        document,
    )


def _qualification_failure(result: QualificationResult) -> NotReleased:
    code = result.failure_code or f"qualification_{result.status}"
    details = {
        "phase": "qualification",
        "qualification_status": result.status,
        **dict(result.details or {}),
    }
    message = str(details.get("message") or f"Qualification ended as {result.status}")
    return NotReleased(code, message, details)


def _infrastructure_failure(phase: str, exc: OSError) -> NotReleased:
    return NotReleased(
        "infrastructure_failure",
        f"{phase} infrastructure failed",
        {"phase": phase, "error_type": type(exc).__name__, "message": str(exc)},
    )


def _finish(run_root: Path, outcome: GenerationOutcome) -> GenerationOutcome:
    try:
        _write_json(run_root / "outcome.json", outcome_document(outcome))
    except OSError:
        pass
    return outcome


def _write_json(path: Path, document: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            document,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ),
        encoding="utf-8",
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
