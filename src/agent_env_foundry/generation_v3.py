"""Internal S1 v3 coordinator: Need to one cold executable environment."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from agent_env_foundry.agents import AgentRoute, run_research
from agent_env_foundry.builder import BuilderConfig, CandidateBuild, CommandResult, run_builder
from agent_env_foundry.environment import JSONObject
from agent_env_foundry.environment_conformance_v3 import (
    ConformedEnvironmentV3,
    bind_environment_semantics_v3,
    run_environment_conformance_v3_internal,
)
from agent_env_foundry.environment_semantic_qualification import (
    SemanticQualificationFailure,
    review_environment_semantics,
    semantic_qualification_from_document,
)
from agent_env_foundry.preparation_v3 import (
    OpenPreparedReleaseV3,
    PreparationSettingsV3,
    prepare_release_v3_internal,
)
from agent_env_foundry.release import canonical_bytes
from agent_env_foundry.release_v3 import (
    publish_release_v3_internal,
    write_release_zip_v3_internal,
)
from agent_env_foundry.research import (
    BuilderProjection,
    EvidenceStore,
    NeedRecord,
    NotReleased,
    ResearchBudget,
    ResearchConfig,
    ResearchReady,
    ResearchTools,
    Unsupported,
)

_OWNER = {
    "research": "Research",
    "environment_builder": "EnvironmentBuilder",
    "environment_semantic_qualification": "EnvironmentSemanticQualification",
    "environment_conformance": "EnvironmentConformance",
    "publication": "Publication",
    "write_zip": "Publication",
    "cold_prepare": "Publication",
}


@dataclass(frozen=True)
class GenerationConfigV3:
    route: AgentRoute = field(default_factory=AgentRoute)
    research: ResearchConfig = field(default_factory=ResearchConfig)
    research_budget: ResearchBudget = field(default_factory=ResearchBudget)
    builder: BuilderConfig = field(default_factory=BuilderConfig)
    preparation: PreparationSettingsV3 = field(
        default_factory=lambda: PreparationSettingsV3(
            Path("/tmp/agent-env-foundry-generation-v3-uv-cache")
        )
    )


@dataclass(frozen=True)
class ReleasedV3:
    release_id: str
    release_root: Path
    archive: Path
    research_digest: str
    prepared: OpenPreparedReleaseV3
    events: tuple[JSONObject, ...]


class _StageFailureV3(RuntimeError):
    def __init__(self, stage: str, cause: Exception) -> None:
        super().__init__(str(cause))
        self.stage = stage
        self.cause = cause


def generate_environment_v3_internal(
    need_text: str,
    work_root: Path,
    output_root: Path,
    *,
    config: GenerationConfigV3,
    event_sink: Callable[[JSONObject], None] | None = None,
) -> ReleasedV3 | NotReleased | Unsupported:
    """Run the environment-only S1 order; no Task role participates."""

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
    except _StageFailureV3 as failure:
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
            lambda: run_builder(
                research.builder_projection,
                work / "actor",
                config=config.builder,
                acceptance_check=lambda candidate: _semantic_acceptance_check(
                    candidate,
                    projection=research.builder_projection,
                    runtime_root=work / "semantic-qualification-runtime",
                    config=config,
                ),
            ),
        )
        physical = _run_stage(
            "environment_conformance",
            events,
            event_sink,
            lambda: run_environment_conformance_v3_internal(
                actor,
                work / "conformance-runtime",
                settings=config.preparation,
            ),
        )
        conformed = _run_stage(
            "environment_semantic_qualification",
            events,
            event_sink,
            lambda: _bind_accepted_semantics(
                actor,
                physical,
                projection=research.builder_projection,
            ),
        )
        release = _run_stage(
            "publication",
            events,
            event_sink,
            lambda: publish_release_v3_internal(
                output / "EnvironmentRelease",
                actor_project=actor.workspace,
                receipt=conformed.receipt,
                evidence=conformed.evidence,
                start_schema=conformed.start_schema,
                reset_observation_schema=conformed.reset_observation_schema,
                state_schema=conformed.state_schema,
            ),
        )
        archive = _run_stage(
            "write_zip",
            events,
            event_sink,
            lambda: write_release_zip_v3_internal(
                release.root,
                output / "EnvironmentRelease.zip",
            ),
        )
        prepared = _run_stage(
            "cold_prepare",
            events,
            event_sink,
            lambda: prepare_release_v3_internal(
                archive,
                work / "cold-cache",
                settings=config.preparation,
            ),
        )
    except _StageFailureV3 as failure:
        return _terminal_failure(failure.stage, failure.cause, events)

    return ReleasedV3(
        release.release_id,
        release.root,
        archive,
        research.digest,
        prepared,
        tuple(events),
    )


def _semantic_acceptance_check(
    candidate: CandidateBuild,
    *,
    projection: BuilderProjection,
    runtime_root: Path,
    config: GenerationConfigV3,
) -> CommandResult:
    physical = run_environment_conformance_v3_internal(
        candidate,
        runtime_root / candidate.candidate_digest,
        settings=config.preparation,
    )
    qualification = review_environment_semantics(
        projection,
        actor_project_digest=candidate.candidate_digest,
        tool_specs=physical.tool_specs,
        diagnostic_evidence=physical.diagnostic_evidence,
        route=config.route,
    )
    if qualification.passed:
        return CommandResult(
            "semantic_qualification",
            ("host", "review-need-semantics"),
            0,
            canonical_bytes(qualification.to_document()).decode("utf-8"),
            "",
        )
    return CommandResult(
        "semantic_qualification",
        ("host", "review-need-semantics"),
        1,
        "",
        canonical_bytes(
            {
                "code": "need_semantics_not_satisfied",
                "message": (
                    "Independent review found that actual Host evidence does not satisfy "
                    "every frozen Requirement. Repair code and/or diagnostic coverage; do not "
                    "edit the frozen projection."
                ),
                "findings": [
                    item.to_document()
                    for item in qualification.findings
                    if item.verdict == "not_satisfied"
                ],
            }
        ).decode("utf-8"),
    )


def _bind_accepted_semantics(
    candidate: CandidateBuild,
    physical: ConformedEnvironmentV3,
    *,
    projection: BuilderProjection,
) -> ConformedEnvironmentV3:
    if candidate.acceptance is None:
        raise SemanticQualificationFailure(
            "QualifierDefect",
            "semantic_qualification_missing",
            "Builder completed without an accepted semantic qualification",
        )
    try:
        qualification = semantic_qualification_from_document(candidate.acceptance)
        return bind_environment_semantics_v3(
            physical,
            projection=projection,
            qualification=qualification,
        )
    except ValueError as exc:
        raise SemanticQualificationFailure(
            "QualifierDefect",
            "semantic_qualification_binding_invalid",
            str(exc),
        ) from exc


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
        raise _StageFailureV3(stage, exc) from exc
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
    details.update(
        {
            "owner": (
                "EnvironmentSemanticQualification"
                if isinstance(exc, SemanticQualificationFailure)
                else _OWNER[stage]
            ),
            "original_type": type(exc).__name__,
            "events": list(events),
        }
    )
    code = getattr(exc, "code", f"{stage}_failed")
    if not isinstance(code, str) or not code:
        code = f"{stage}_failed"
    return NotReleased(code, str(exc), details)


def _with_research_owner(
    outcome: NotReleased | Unsupported,
    events: list[JSONObject],
) -> NotReleased | Unsupported:
    owner = (
        "Infrastructure"
        if outcome.code in {"missing_openai_api_key", "responses_request_failed"}
        else "Research"
    )
    details = {**outcome.details, "owner": owner, "events": list(events)}
    return type(outcome)(outcome.code, outcome.message, details)


def _new_root(path: Path, role: str) -> Path:
    root = Path(path)
    if root.is_symlink() or (root.exists() and (not root.is_dir() or any(root.iterdir()))):
        raise ValueError(f"{role} must be absent or an empty non-symlink directory")
    root.mkdir(parents=True, exist_ok=True)
    return root.resolve()


__all__ = ["GenerationConfigV3", "ReleasedV3", "generate_environment_v3_internal"]
