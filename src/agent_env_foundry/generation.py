"""Direct S1 coordinator from one natural-language Need to one cold Release."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import partial
from pathlib import Path

from agent_env_foundry.agents import AgentRoute, run_research
from agent_env_foundry.author_finding import AuthorFinding
from agent_env_foundry.builder import ACTOR_FACTORY, BuilderConfig, CandidateBuild, run_builder
from agent_env_foundry.environment import JSONObject
from agent_env_foundry.preparation import (
    OpenPreparedRelease,
    PreparationExecutionError,
    PreparationSettings,
    ProjectMaterializationInput,
    prepare_release,
    read_actor_tool_catalog,
)
from agent_env_foundry.qualification_contracts import PublicSurfaceManifest
from agent_env_foundry.qualification_runner import QualificationBudget, run_v2_qualification
from agent_env_foundry.qualification_v2 import FrozenCoreInputs, derive_qualification_core
from agent_env_foundry.release import (
    ValidatedReleaseV2,
    publish_release_v2,
    write_release_zip_v2,
)
from agent_env_foundry.research import (
    EvidenceStore,
    NeedRecord,
    NotReleased,
    ResearchBudget,
    ResearchConfig,
    ResearchReady,
    ResearchTools,
    Unsupported,
)
from agent_env_foundry.semantics import SemanticsContractError
from agent_env_foundry.semantics_author import (
    SEMANTICS_FACTORY,
    SemanticsBuild,
    repair_semantics_author,
    run_semantics_author,
)
from agent_env_foundry.semantics_authoring import (
    ExpectedTaskSemantics,
    generate_expected_task_semantics,
)
from agent_env_foundry.semantics_inputs import (
    PreparedSemanticsAuthorWorkspace,
    prepare_semantics_author_workspace,
)
from agent_env_foundry.tree_manifest import tree_manifest
from agent_env_foundry.verifier_author import (
    VERIFIER_FACTORY,
    VerifierBuild,
    repair_verifier_author,
    run_verifier_author,
)
from agent_env_foundry.verifier_inputs import (
    PreparedVerifierAuthorWorkspace,
    prepare_verifier_author_workspace,
)

__all__ = ["GenerationConfig", "Released", "generate_environment_v2"]

_ACTOR_FORBIDDEN = (
    "generated_task_semantics",
    "generated_qualification_verifier",
    "agent_env_foundry",
)
_SEMANTICS_FORBIDDEN = (
    "generated_environment",
    "generated_qualification_verifier",
    "agent_env_foundry",
)
_VERIFIER_FORBIDDEN = (
    "generated_environment",
    "generated_task_semantics",
    "agent_env_foundry",
)
_OWNER = {
    "research": "Research",
    "environment_builder": "EnvironmentBuilder",
    "public_surface": "EnvironmentBuilder",
    "expected_semantics": "ExpectedSemantics",
    "prepare_semantics_author": "TaskSemanticsAuthor",
    "prepare_verifier_author": "QualificationVerifierAuthor",
    "semantics_author": "TaskSemanticsAuthor",
    "semantics_repair": "TaskSemanticsAuthor",
    "verifier_author": "QualificationVerifierAuthor",
    "verifier_repair": "QualificationVerifierAuthor",
    "derive_core": "Qualification",
    "qualification": "Qualification",
    "publication": "Publication",
    "write_zip": "Publication",
    "cold_prepare": "Publication",
}


@dataclass(frozen=True)
class GenerationConfig:
    route: AgentRoute = field(default_factory=AgentRoute)
    research: ResearchConfig = field(default_factory=ResearchConfig)
    research_budget: ResearchBudget = field(default_factory=ResearchBudget)
    builder: BuilderConfig = field(default_factory=BuilderConfig)
    author: BuilderConfig = field(
        default_factory=lambda: BuilderConfig(
            max_turns=4,
            uv_cache_dir=Path("/tmp/agent-env-foundry-author-uv-cache"),
        )
    )
    qualification: QualificationBudget = field(default_factory=QualificationBudget)
    preparation: PreparationSettings = field(
        default_factory=lambda: PreparationSettings(
            Path("/tmp/agent-env-foundry-generation-uv-cache")
        )
    )
    physical_author_repairs: int = 2

    def __post_init__(self) -> None:
        if self.physical_author_repairs < 0:
            raise ValueError("physical_author_repairs must be non-negative")


@dataclass(frozen=True)
class Released:
    release_id: str
    release_root: Path
    archive: Path
    research_digest: str
    prepared: OpenPreparedRelease
    events: tuple[JSONObject, ...]


class _StageFailure(RuntimeError):
    def __init__(self, stage: str, cause: Exception) -> None:
        super().__init__(str(cause))
        self.stage = stage
        self.cause = cause


def _run_stage[T](
    stage: str,
    events: list[JSONObject],
    sink: Callable[[JSONObject], None] | None,
    operation: Callable[[], T],
) -> T:
    started = time.monotonic_ns()
    try:
        result = operation()
    except Exception as exc:
        event: JSONObject = {
            "stage": stage,
            "status": "failed",
            "elapsed_ms": (time.monotonic_ns() - started) // 1_000_000,
            "error_type": type(exc).__name__,
        }
        events.append(event)
        if sink is not None:
            sink(event)
        raise _StageFailure(stage, exc) from exc
    event = {
        "stage": stage,
        "status": "passed",
        "elapsed_ms": (time.monotonic_ns() - started) // 1_000_000,
    }
    events.append(event)
    if sink is not None:
        sink(event)
    return result


def _terminal_failure(stage: str, exc: Exception, events: list[JSONObject]) -> NotReleased:
    raw_details = getattr(exc, "details", {})
    details = dict(raw_details) if isinstance(raw_details, dict) else {"details": raw_details}
    phase = getattr(exc, "phase", None)
    if isinstance(phase, str) and "phase" not in details:
        details["phase"] = phase
    details.update(
        {
            "owner": _OWNER[stage],
            "original_type": type(exc).__name__,
            "events": list(events),
        }
    )
    code = getattr(exc, "code", f"{stage}_failed")
    if not isinstance(code, str) or not code:
        code = f"{stage}_failed"
    return NotReleased(code, str(exc), details)


def _with_research_owner(
    outcome: NotReleased | Unsupported, events: list[JSONObject]
) -> NotReleased | Unsupported:
    owner = (
        "Infrastructure"
        if outcome.code in {"missing_openai_api_key", "responses_request_failed"}
        else "Research"
    )
    details = {**outcome.details, "owner": owner, "events": list(events)}
    return type(outcome)(outcome.code, outcome.message, details)


def _read_json(path: Path, role: str) -> JSONObject:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"{role} is not readable canonical JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{role} must be a JSON object")
    return value


def _freeze_public_surface(
    actor_root: Path,
    actor_digest: str,
    runtime_root: Path,
    settings: PreparationSettings,
) -> PublicSurfaceManifest:
    docs = actor_root / "docs"
    schemas = docs / "schemas"
    tools = read_actor_tool_catalog(
        ProjectMaterializationInput(
            actor_root,
            actor_digest,
            "generated_environment",
            _ACTOR_FORBIDDEN,
            "actor",
        ),
        runtime_root,
        factory=ACTOR_FACTORY,
        settings=settings,
    )
    return PublicSurfaceManifest(
        _read_json(schemas / "start.json", "actor start schema"),
        _read_json(schemas / "reset.json", "actor reset schema"),
        tools,
        tree_manifest(docs).digest,
    )


def _frozen_inputs(
    actor: CandidateBuild,
    surface: PublicSurfaceManifest,
    expected: ExpectedTaskSemantics,
    semantics_inputs: PreparedSemanticsAuthorWorkspace,
    verifier_inputs: PreparedVerifierAuthorWorkspace,
    semantics: SemanticsBuild,
    verifier: VerifierBuild,
) -> FrozenCoreInputs:
    return FrozenCoreInputs(
        expected.canonical_payload,
        expected.digest,
        surface,
        semantics_inputs,
        verifier_inputs,
        ProjectMaterializationInput(
            actor.workspace,
            actor.candidate_digest,
            "generated_environment",
            _ACTOR_FORBIDDEN,
            "actor",
        ),
        ACTOR_FACTORY,
        ProjectMaterializationInput(
            semantics.root,
            semantics.project_digest,
            "generated_task_semantics",
            _SEMANTICS_FORBIDDEN,
            "semantics",
        ),
        SEMANTICS_FACTORY,
        ProjectMaterializationInput(
            verifier.root,
            verifier.project_digest,
            "generated_qualification_verifier",
            _VERIFIER_FORBIDDEN,
            "verifier",
        ),
        VERIFIER_FACTORY,
    )


def _author_defect(error: Exception) -> str | None:
    if isinstance(error, PreparationExecutionError) and error.kind in {
        "SemanticsDefect",
        "VerifierDefect",
    }:
        return error.kind
    if isinstance(error, SemanticsContractError):
        return "SemanticsDefect"
    return None


def _physical_finding(error: Exception) -> AuthorFinding:
    details = error.details if isinstance(error, PreparationExecutionError) else {}
    kind = error.kind if isinstance(error, PreparationExecutionError) else "SemanticsDefect"
    code = error.code if isinstance(error, PreparationExecutionError) else "semantics_wire_invalid"
    actual = {
        "kind": kind,
        "code": code,
        "message": str(error),
        "details": details,
    }
    safe_actual = json.loads(json.dumps(actual, ensure_ascii=False, default=str))
    return AuthorFinding(
        "native_physical_check",
        code,
        "generated code must execute the reported Qualification operation",
        {"status": "completed_without_runtime_error"},
        safe_actual,
        json.loads(json.dumps(details, ensure_ascii=False, default=str)),
    )


def _new_root(path: Path, role: str) -> Path:
    root = Path(path)
    if root.is_symlink() or (root.exists() and (not root.is_dir() or any(root.iterdir()))):
        raise ValueError(f"{role} must be absent or an empty non-symlink directory")
    root.mkdir(parents=True, exist_ok=True)
    return root.resolve()


def generate_environment_v2(
    need_text: str,
    work_root: Path,
    output_root: Path,
    *,
    config: GenerationConfig,
    event_sink: Callable[[JSONObject], None] | None = None,
) -> Released | NotReleased | Unsupported:
    """Run the accepted S1 stages once; no generated role decides admission."""

    events: list[JSONObject] = []
    try:
        need = NeedRecord.from_text(need_text)
        work = _new_root(work_root, "generation work root")
        output = _new_root(output_root, "generation output root")
    except ValueError as exc:
        return NotReleased(
            "invalid_need" if not need_text.strip() else "generation_root_invalid",
            str(exc),
            {"owner": "Research" if not need_text.strip() else "Infrastructure"},
        )

    tools = ResearchTools(
        store=EvidenceStore(work / "research/evidence"),
        config=config.research,
        budget=config.research_budget,
    )
    try:
        research = _run_stage(
            "research",
            events,
            event_sink,
            lambda: run_research(need=need, tools=tools, route=config.route),
        )
    except _StageFailure as failure:
        return _terminal_failure(failure.stage, failure.cause, events)
    finally:
        tools.close()
    if isinstance(research, (NotReleased, Unsupported)):
        return _with_research_owner(research, events)
    if not isinstance(research, ResearchReady):
        return NotReleased(
            "research_result_invalid",
            "Research returned an unsupported result type",
            {"owner": "Research", "events": list(events)},
        )

    try:
        research.write(work / "research/ResearchReady.json")
        actor = _run_stage(
            "environment_builder",
            events,
            event_sink,
            lambda: run_builder(research.builder_projection, work / "actor", config=config.builder),
        )
        surface = _run_stage(
            "public_surface",
            events,
            event_sink,
            lambda: _freeze_public_surface(
                actor.workspace,
                actor.candidate_digest,
                work / "public-surface-runtime",
                config.preparation,
            ),
        )
        expected = _run_stage(
            "expected_semantics",
            events,
            event_sink,
            lambda: generate_expected_task_semantics(
                research.builder_projection,
                public_surface=surface,
                route=config.route,
            ),
        )
        semantics_inputs = _run_stage(
            "prepare_semantics_author",
            events,
            event_sink,
            lambda: prepare_semantics_author_workspace(
                work / "semantics-author",
                actor_root=actor.workspace,
                actor_digest=actor.candidate_digest,
                expected_semantics_payload=expected.canonical_payload,
                expected_semantics_digest=expected.digest,
                public_surface=surface,
            ),
        )
        verifier_inputs = _run_stage(
            "prepare_verifier_author",
            events,
            event_sink,
            lambda: prepare_verifier_author_workspace(
                work / "verifier-author",
                actor_root=actor.workspace,
                actor_digest=actor.candidate_digest,
                expected_semantics_payload=expected.canonical_payload,
                expected_semantics_digest=expected.digest,
                public_surface=surface,
            ),
        )
        semantics = _run_stage(
            "semantics_author",
            events,
            event_sink,
            lambda: run_semantics_author(semantics_inputs, config=config.author),
        )
        verifier = _run_stage(
            "verifier_author",
            events,
            event_sink,
            lambda: run_verifier_author(verifier_inputs, config=config.author),
        )
        repair_count = 0
        while True:
            frozen = _frozen_inputs(
                actor,
                surface,
                expected,
                semantics_inputs,
                verifier_inputs,
                semantics,
                verifier,
            )
            core = _run_stage(
                "derive_core",
                events,
                event_sink,
                partial(derive_qualification_core, frozen),
            )
            try:
                qualification = _run_stage(
                    "qualification",
                    events,
                    event_sink,
                    partial(
                        run_v2_qualification,
                        frozen,
                        core,
                        work / "qualification",
                        work / f"qualification-cache-{repair_count}",
                        route=config.route,
                        budget=config.qualification,
                        settings=config.preparation,
                    ),
                )
                break
            except _StageFailure as failure:
                error = failure.cause
                defect = _author_defect(error)
                if defect is None or repair_count >= config.physical_author_repairs:
                    raise
                finding = (_physical_finding(error),)
                if defect == "SemanticsDefect":
                    current = semantics
                    semantics = _run_stage(
                        "semantics_repair",
                        events,
                        event_sink,
                        partial(
                            repair_semantics_author,
                            semantics_inputs,
                            current,
                            finding,
                            config=config.author,
                        ),
                    )
                else:
                    current_verifier = verifier
                    verifier = _run_stage(
                        "verifier_repair",
                        events,
                        event_sink,
                        partial(
                            repair_verifier_author,
                            verifier_inputs,
                            current_verifier,
                            finding,
                            config=config.author,
                        ),
                    )
                repair_count += 1
        release: ValidatedReleaseV2 = _run_stage(
            "publication",
            events,
            event_sink,
            lambda: publish_release_v2(
                output / "EnvironmentRelease",
                core=core,
                receipt=qualification.receipt,
                actor_project=actor.workspace,
                semantics_project=semantics.root,
                verifier_project=verifier.root,
                expected_semantics_payload=expected.canonical_payload,
                public_surface=surface,
                qualified_catalog=qualification.qualified_catalog,
                requirement_coverage=qualification.requirement_coverage,
                qualified_start_cases=qualification.qualified_start_cases,
                evidence_root=qualification.evidence_root,
            ),
        )
        archive = _run_stage(
            "write_zip",
            events,
            event_sink,
            lambda: write_release_zip_v2(release.root, output / "EnvironmentRelease.zip"),
        )
        prepared = _run_stage(
            "cold_prepare",
            events,
            event_sink,
            lambda: prepare_release(
                archive,
                work / "cold-cache",
                settings=config.preparation,
            ),
        )
    except _StageFailure as failure:
        return _terminal_failure(failure.stage, failure.cause, events)

    return Released(
        release.release_id,
        release.root,
        archive,
        research.digest,
        prepared,
        tuple(events),
    )
