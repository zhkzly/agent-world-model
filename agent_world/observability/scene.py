"""Bounded, agent-facing Tier A scene contracts and their pure reducer.

The scene is deliberately a projection of already durable WorkGraph facts.  It
does not own scheduling, repair, or release authority, and ``fold`` only sees
cold inputs that a later read-side command can reconstruct.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, model_validator

from agent_world.contracts import (
    ContentHash,
    NonEmptyStr,
    V2Contract,
    canonical_json_bytes,
    sha256_digest,
)

MAX_TOP_ISSUES = 8
MAX_UNRESOLVED_ISSUES = 32
MAX_COORDINATE_POINTERS = 16
MAX_MISSING_COORDINATES = 32
MAX_WATERMARK_COORDINATES = 64
MAX_FRONTIER_SAMPLES = 4
MAX_ROOT_INDEX_ENTRIES = 64

type HeadStatus = Literal[
    "running",
    "repair_authorized",
    "committed",
    "failed",
    "needs_human",
    "interrupted",
]
# Mirrors ``agent_world.control.work.ValidationStatus``.  ``error`` is the
# authoritative marker of an infrastructure/transport terminal (a leaf that
# could not produce a valid proposal, e.g. a compatible-gateway response that
# was not JSON) as opposed to ``failed`` (a real proposal whose semantics were
# deterministically rejected).  The scene must route these two lanes apart so a
# transport failure never presents the frozen WorldSpec as the repair subject.
type ValidationStatus = Literal["passed", "failed", "inconclusive", "error"]
type PipelineStage = Literal[
    "Research",
    "Designer",
    "Builder",
    "Integration",
    "Judge",
    "Registry",
]
type FrontierProgress = Literal["strict_progress", "resolved", "no_progress", "unknown"]
type RepairAuthority = Literal[
    "authorized",
    "in_progress",
    "eligible",
    "none",
    "needs_human",
]
type RepairTarget = Literal[
    "generated_candidate_code",
    "design_worldspec",
    "proposal_semantics",
    "infrastructure_transport",
    "needs_human",
]
type StuckReason = Literal[
    "thrashing",
    "no_repair_authority",
    "subprocess_crash",
    "budget_exhausted",
    "blocked_by_parent",
    "needs_human",
]
type SceneStatus = Literal[
    "running",
    "repair_authorized",
    "committed",
    "failed",
    "needs_human",
    "interrupted",
]
type NextActionHint = Literal[
    "inspect_subprocess",
    "inspect_infrastructure",
    "repair_candidate_code",
    "revise_proposal",
    "review_design_worldspec",
    "request_human_review",
    "wait_for_running_work",
]


class TopIssue(V2Contract):
    """One bounded, secret-screened diagnostic suitable for an agent read."""

    code: Annotated[NonEmptyStr, Field(max_length=160)]
    path: Annotated[tuple[str | int, ...], Field(min_length=1, max_length=16)]
    violated_condition: Annotated[NonEmptyStr, Field(max_length=512)]
    expected_category: Annotated[NonEmptyStr, Field(max_length=512)]
    severity: Literal["warning", "blocker"]

    @model_validator(mode="after")
    def validate_path(self) -> TopIssue:
        for part in self.path:
            if isinstance(part, str) and (not part or len(part) > 160):
                raise ValueError("scene issue path strings must contain 1..160 characters")
            if isinstance(part, int) and part < 0:
                raise ValueError("scene issue path indices cannot be negative")
        return self


class FrontierDiff(V2Contract):
    """Set-size projection of the current and preceding unresolved frontier."""

    previous_size: Annotated[int, Field(ge=0)]
    current_size: Annotated[int, Field(ge=0)]
    delta: int

    @model_validator(mode="after")
    def validate_delta(self) -> FrontierDiff:
        if self.delta != self.current_size - self.previous_size:
            raise ValueError("frontier delta must equal current_size minus previous_size")
        return self


class CoordinatePointer(V2Contract):
    """A bounded map-layer pointer to one on-disk coordinate scene."""

    coordinate_key: ContentHash
    coordinate_label: Annotated[NonEmptyStr, Field(max_length=512)]
    head_status: HeadStatus
    json_path: Annotated[NonEmptyStr, Field(max_length=512)]
    markdown_path: Annotated[NonEmptyStr, Field(max_length=512)]


class CoordinateWatermark(V2Contract):
    """One durable-head version included in a materialized scene."""

    coordinate_key: ContentHash
    revision: Annotated[int, Field(ge=1)]
    status: HeadStatus
    attempt_ref_revision: ContentHash


class SceneWatermark(V2Contract):
    """Bounded per-coordinate freshness proof plus an all-head aggregate hash."""

    coordinates: Annotated[
        tuple[CoordinateWatermark, ...], Field(max_length=MAX_WATERMARK_COORDINATES)
    ]
    coordinate_overflow_count: Annotated[int, Field(ge=0)] = 0
    aggregate_digest: ContentHash
    graph_digest: ContentHash
    projected_from_run_id: Annotated[NonEmptyStr, Field(max_length=512)] | None = None
    projected_at: AwareDatetime

    @model_validator(mode="after")
    def validate_unique_coordinates(self) -> SceneWatermark:
        keys = tuple(item.coordinate_key for item in self.coordinates)
        if len(set(keys)) != len(keys):
            raise ValueError("scene watermark coordinates must be unique")
        return self


class CoordinateScene(V2Contract):
    """The bounded current scene for one physical WorkCoordinate."""

    scope_id: Annotated[NonEmptyStr, Field(max_length=512)]
    coordinate_key: ContentHash
    coordinate_label: Annotated[NonEmptyStr, Field(max_length=512)]
    head_status: HeadStatus
    attempt_ordinal: Annotated[int, Field(ge=1)]
    failure_code: Annotated[NonEmptyStr, Field(max_length=512)] | None = None
    validation_status: ValidationStatus | None = None
    frontier_ordinal: Annotated[int, Field(ge=0)]
    pipeline_stage: PipelineStage
    unresolved_issue_ids: Annotated[
        tuple[ContentHash, ...], Field(max_length=MAX_UNRESOLVED_ISSUES)
    ] = ()
    unresolved_issue_overflow_count: Annotated[int, Field(ge=0)] = 0
    unresolved_issue_digest: ContentHash
    previous_issue_digest: ContentHash | None = None
    frontier_diff: FrontierDiff
    frontier_progress: FrontierProgress
    repair_authority: RepairAuthority
    candidate_file: Annotated[NonEmptyStr, Field(max_length=512)] | None = None
    contract_pointer: Annotated[NonEmptyStr, Field(max_length=512)] | None = None
    repair_target: RepairTarget | None = None
    top_issues: Annotated[tuple[TopIssue, ...], Field(max_length=MAX_TOP_ISSUES)] = ()
    subprocess_pointer: Annotated[NonEmptyStr, Field(max_length=512)] | None = None
    input_fingerprint: ContentHash
    attempt_ref_id: Annotated[NonEmptyStr, Field(max_length=512)]

    @model_validator(mode="after")
    def validate_scene_bounds(self) -> CoordinateScene:
        if len(set(self.unresolved_issue_ids)) != len(self.unresolved_issue_ids):
            raise ValueError("scene unresolved issue identities must be unique")
        if self.head_status == "committed" and self.repair_target is not None:
            raise ValueError("committed coordinate scenes cannot advertise a repair target")
        if self.repair_target == "generated_candidate_code" and self.candidate_file is None:
            raise ValueError("candidate-code repair target requires a concrete candidate file")
        return self


class FrontierRecord(V2Contract):
    """One compact, append-only per-attempt frontier sample."""

    coordinate_key: ContentHash
    attempt_ref_revision: ContentHash
    attempt_ref_id: Annotated[NonEmptyStr, Field(max_length=512)]
    attempt_ordinal: Annotated[int, Field(ge=1)]
    frontier_ordinal: Annotated[int, Field(ge=0)]
    unresolved_issue_digest: ContentHash
    unresolved_issue_count: Annotated[int, Field(ge=0)]
    issue_samples: Annotated[tuple[TopIssue, ...], Field(max_length=MAX_FRONTIER_SAMPLES)] = ()


class RunSceneIndex(V2Contract):
    """The map-layer index that agents read before expanding one coordinate."""

    scope_id: Annotated[NonEmptyStr, Field(max_length=512)]
    overall_status: SceneStatus
    stuck_coordinate: CoordinatePointer | None = None
    stuck_reason: StuckReason | None = None
    missing_coordinates: Annotated[
        tuple[CoordinatePointer, ...], Field(max_length=MAX_MISSING_COORDINATES)
    ] = ()
    missing_coordinates_overflow_count: Annotated[int, Field(ge=0)] = 0
    frontier_size: Annotated[int, Field(ge=0)]
    frontier_delta: int
    next_action_hint: NextActionHint | None = None
    coordinate_pointers: Annotated[
        tuple[CoordinatePointer, ...], Field(max_length=MAX_COORDINATE_POINTERS)
    ] = ()
    additional_stuck_count: Annotated[int, Field(ge=0)] = 0
    watermark: SceneWatermark

    @model_validator(mode="after")
    def validate_stuck_shape(self) -> RunSceneIndex:
        if self.stuck_reason is not None and self.stuck_coordinate is None:
            raise ValueError("a stuck reason requires a stuck coordinate")
        if len({item.coordinate_key for item in self.coordinate_pointers}) != len(
            self.coordinate_pointers
        ):
            raise ValueError("scene coordinate pointers must be unique")
        return self


class ScopeIndexEntry(V2Contract):
    """One bounded root-index entry for a stable scope partition."""

    scope_id: Annotated[NonEmptyStr, Field(max_length=512)]
    overall_status: SceneStatus
    updated_at: AwareDatetime
    stuck_coordinate_key: ContentHash | None = None


class ObservabilityIndex(V2Contract):
    """Cross-scope pointer index; it is a cache just like each scene file."""

    entries: Annotated[tuple[ScopeIndexEntry, ...], Field(max_length=MAX_ROOT_INDEX_ENTRIES)] = ()
    overflow_count: Annotated[int, Field(ge=0)] = 0

    @model_validator(mode="after")
    def validate_unique_scopes(self) -> ObservabilityIndex:
        scopes = tuple(item.scope_id for item in self.entries)
        if len(set(scopes)) != len(scopes):
            raise ValueError("observability root index scopes must be unique")
        return self


@dataclass(frozen=True, slots=True)
class SceneIssue:
    """Cold, already secret-screened issue input to the shared reducer."""

    normalized_identity: str
    code: str
    path: tuple[str | int, ...]
    violated_condition: str
    expected_category: str
    severity: Literal["warning", "blocker"]
    actionable: bool
    gate_id: str | None = None
    candidate_file: str | None = None
    multi_file_gate: bool = False


@dataclass(frozen=True, slots=True)
class SceneHead:
    """Cold durable facts for one coordinate; no live scheduler snapshots enter here."""

    scope_id: str
    coordinate_key: str
    coordinate_label: str
    head_status: HeadStatus
    revision: int
    attempt_ref_revision: str
    attempt_ref_id: str
    attempt_ordinal: int
    failure_code: str | None
    frontier_ordinal: int
    pipeline_stage: PipelineStage
    repair_authority: RepairAuthority
    input_fingerprint: str
    issues: tuple[SceneIssue, ...]
    previous_issue_ids: tuple[str, ...]
    run_id: str | None
    graph_digest: str
    updated_at: datetime
    subprocess_available: bool = False
    # The terminal ValidationReport.status for this head, when one exists.
    # ``error`` denotes an infrastructure/transport terminal; ``failed`` denotes
    # a deterministically rejected real proposal.  ``None`` when the head has no
    # settled validation report yet (running / freshly scheduled).
    validation_status: ValidationStatus | None = None
    # True when this head's terminal report routes its repair to an ancestor
    # coordinate (a ``control.parent_repair_route`` was committed).  A rejected
    # proposal WITHOUT such a route is repairable where it was produced, so it
    # must not be presented as a frozen-design defect.
    routes_repair_to_parent: bool = False


@dataclass(frozen=True, slots=True)
class SceneTierBEvent:
    """The small cold subset of a Tier B event relevant to scene folding."""

    event_type: str
    coordinate_key: str | None = None


@dataclass(frozen=True, slots=True)
class Scene:
    """All deterministic Tier A outputs of one shared fold."""

    index: RunSceneIndex
    coordinates: tuple[CoordinateScene, ...]
    frontier_records: tuple[FrontierRecord, ...]


def fold(heads: Sequence[SceneHead], tier_b_events: Sequence[SceneTierBEvent]) -> Scene:
    """Fold only cold durable heads and Tier B facts into one bounded scene.

    This signature is intentionally shared by the eager runtime projection and
    the future cold-start read-side rebuild.  Do not add WorkScheduler or
    WorkReadiness snapshots here: those objects do not survive process restart.
    """

    if not heads:
        raise ValueError("scene fold requires at least one durable WorkControlHead")
    scope_ids = {item.scope_id for item in heads}
    if len(scope_ids) != 1:
        raise ValueError("one scene fold cannot mix scope partitions")
    graph_digests = {item.graph_digest for item in heads}
    if len(graph_digests) != 1:
        raise ValueError("one scene fold requires one graph digest")

    event_coordinates = {
        item.coordinate_key
        for item in tier_b_events
        if item.event_type == "runtime_subprocess_scene" and item.coordinate_key is not None
    }
    ordered_heads = tuple(sorted(heads, key=lambda item: item.coordinate_key))
    coordinates = tuple(
        _coordinate_scene(
            head,
            subprocess_available=(
                head.subprocess_available or head.coordinate_key in event_coordinates
            ),
        )
        for head in ordered_heads
    )
    records = tuple(
        FrontierRecord(
            coordinate_key=coordinate.coordinate_key,
            attempt_ref_revision=head.attempt_ref_revision,
            attempt_ref_id=coordinate.attempt_ref_id,
            attempt_ordinal=coordinate.attempt_ordinal,
            frontier_ordinal=coordinate.frontier_ordinal,
            unresolved_issue_digest=coordinate.unresolved_issue_digest,
            unresolved_issue_count=(
                len(head.issues)
                if coordinate.unresolved_issue_overflow_count
                else len(coordinate.unresolved_issue_ids)
            ),
            issue_samples=coordinate.top_issues[:MAX_FRONTIER_SAMPLES],
        )
        for head, coordinate in zip(ordered_heads, coordinates, strict=True)
    )
    stuck_scenes = tuple(
        sorted(
            (item for item in coordinates if item.head_status != "committed"),
            key=_stuck_sort_key,
        )
    )
    stuck = stuck_scenes[0] if stuck_scenes else None
    # The bounded map must retain the most actionable coordinate first.  A
    # coordinate-key sort is deterministic but can otherwise hide the actual
    # thrashing/crashed coordinate behind unrelated running work in a wide graph.
    pointer_scenes = (
        *stuck_scenes,
        *(item for item in coordinates if item.head_status == "committed"),
    )
    pointers = tuple(_pointer(item) for item in pointer_scenes)
    missing = stuck_scenes
    watermark_items = tuple(
        CoordinateWatermark(
            coordinate_key=head.coordinate_key,
            revision=head.revision,
            status=head.head_status,
            attempt_ref_revision=head.attempt_ref_revision,
        )
        for head in ordered_heads[:MAX_WATERMARK_COORDINATES]
    )
    aggregate_digest = sha256_digest(
        canonical_json_bytes(
            tuple(
                {
                    "coordinate_key": head.coordinate_key,
                    "revision": head.revision,
                    "status": head.head_status,
                    "attempt_ref_revision": head.attempt_ref_revision,
                }
                for head in ordered_heads
            )
        )
    )
    latest = max(ordered_heads, key=lambda item: (item.updated_at, item.coordinate_key))
    index = RunSceneIndex(
        scope_id=ordered_heads[0].scope_id,
        overall_status=_overall_status(coordinates),
        stuck_coordinate=(_pointer(stuck) if stuck is not None else None),
        stuck_reason=(_stuck_reason(stuck) if stuck is not None else None),
        missing_coordinates=tuple(_pointer(item) for item in missing[:MAX_MISSING_COORDINATES]),
        missing_coordinates_overflow_count=max(0, len(missing) - MAX_MISSING_COORDINATES),
        frontier_size=sum(len(head.issues) for head in ordered_heads),
        frontier_delta=sum(item.frontier_diff.delta for item in coordinates),
        next_action_hint=(_next_action(stuck) if stuck is not None else None),
        coordinate_pointers=tuple(pointers[:MAX_COORDINATE_POINTERS]),
        additional_stuck_count=max(0, len(stuck_scenes) - MAX_COORDINATE_POINTERS),
        watermark=SceneWatermark(
            coordinates=watermark_items,
            coordinate_overflow_count=max(0, len(ordered_heads) - MAX_WATERMARK_COORDINATES),
            aggregate_digest=aggregate_digest,
            graph_digest=ordered_heads[0].graph_digest,
            projected_from_run_id=latest.run_id,
            projected_at=latest.updated_at,
        ),
    )
    return Scene(index=index, coordinates=coordinates, frontier_records=records)


def _coordinate_scene(head: SceneHead, *, subprocess_available: bool) -> CoordinateScene:
    issue_ids = tuple(sorted(item.normalized_identity for item in head.issues))
    prior_ids = tuple(sorted(set(head.previous_issue_ids)))
    shown_issue_ids = issue_ids[:MAX_UNRESOLVED_ISSUES]
    ordered_issues = tuple(
        sorted(
            head.issues,
            key=lambda item: (
                not item.actionable,
                item.severity != "blocker",
                item.code,
                item.normalized_identity,
            ),
        )
    )
    visible_issues = ordered_issues[:MAX_TOP_ISSUES]
    top_issues = tuple(
        TopIssue(
            code=item.code,
            path=item.path,
            violated_condition=item.violated_condition,
            expected_category=item.expected_category,
            severity=item.severity,
        )
        for item in visible_issues
    )
    multi_file_gate = any(item.multi_file_gate for item in ordered_issues)
    candidate_issue = (
        None
        if multi_file_gate
        else next((item for item in visible_issues if item.candidate_file), None)
    )
    candidate_file = candidate_issue.candidate_file if candidate_issue is not None else None
    repair_target = _repair_target(
        head,
        candidate_issue,
        multi_file_gate=multi_file_gate,
    )
    issue_digest = _issue_digest(issue_ids)
    previous_digest = _issue_digest(prior_ids) if prior_ids else None
    frontier_diff = FrontierDiff(
        previous_size=len(prior_ids),
        current_size=len(issue_ids),
        delta=len(issue_ids) - len(prior_ids),
    )
    contract_pointer = (
        f"observe contract {head.scope_id} {head.coordinate_key}"
        if repair_target is not None
        else None
    )
    return CoordinateScene(
        scope_id=head.scope_id,
        coordinate_key=head.coordinate_key,
        coordinate_label=head.coordinate_label,
        head_status=head.head_status,
        attempt_ordinal=head.attempt_ordinal,
        failure_code=head.failure_code,
        validation_status=head.validation_status,
        frontier_ordinal=head.frontier_ordinal,
        pipeline_stage=head.pipeline_stage,
        unresolved_issue_ids=shown_issue_ids,
        unresolved_issue_overflow_count=max(0, len(issue_ids) - MAX_UNRESOLVED_ISSUES),
        unresolved_issue_digest=issue_digest,
        previous_issue_digest=previous_digest,
        frontier_diff=frontier_diff,
        frontier_progress=_frontier_progress(issue_ids, prior_ids, head.head_status),
        repair_authority=head.repair_authority,
        candidate_file=candidate_file,
        contract_pointer=contract_pointer,
        repair_target=repair_target,
        top_issues=top_issues,
        subprocess_pointer=(
            f"subprocess/{_coordinate_file_name(head.coordinate_key)}.json"
            if subprocess_available
            else None
        ),
        input_fingerprint=head.input_fingerprint,
        attempt_ref_id=head.attempt_ref_id,
    )


def _repair_target(
    head: SceneHead,
    issue: SceneIssue | None,
    *,
    multi_file_gate: bool,
) -> RepairTarget | None:
    if head.head_status == "committed":
        return None
    # An infrastructure/transport terminal (ValidationReport.status == "error")
    # is not evidence of a design defect: the leaf never produced a proposal to
    # judge.  It must never route to design_worldspec, or a transient bad-JSON
    # transport failure would tell the agent to edit the frozen WorldSpec and
    # thrash.  This check precedes the Designer branch precisely because the
    # same coordinate can emit both lanes across attempts.
    if head.validation_status == "error" and head.issues:
        return "infrastructure_transport"
    if multi_file_gate:
        return "needs_human"
    if head.pipeline_stage == "Designer" and head.issues:
        # A rejected proposal is only a frozen-design defect when the leaf
        # actually routed its repair upstream.  Without that route the failure
        # lives in the output this coordinate just produced -- e.g. a
        # ToolSemantics batch referencing an error code it never declared -- and
        # the honest instruction is to revise that proposal, not to edit the
        # frozen WorldSpec.  Conflating the two is what turned a self-repairable
        # semantic defect into repeated frozen-design edits.
        if head.routes_repair_to_parent:
            return "design_worldspec"
        return "proposal_semantics"
    if issue is not None and issue.candidate_file is not None:
        return "generated_candidate_code"
    if head.issues or head.head_status == "needs_human":
        return "needs_human"
    return None


def _frontier_progress(
    issue_ids: tuple[str, ...],
    previous_issue_ids: tuple[str, ...],
    status: HeadStatus,
) -> FrontierProgress:
    if status == "committed":
        return "resolved"
    if not issue_ids:
        return "unknown"
    if not previous_issue_ids:
        return "unknown"
    if set(issue_ids) < set(previous_issue_ids):
        return "strict_progress"
    return "no_progress"


def _issue_digest(issue_ids: tuple[str, ...]) -> str:
    return sha256_digest(canonical_json_bytes(issue_ids))


def _coordinate_file_name(coordinate_key: str) -> str:
    return coordinate_key.removeprefix("sha256:")


def _pointer(scene: CoordinateScene) -> CoordinatePointer:
    filename = _coordinate_file_name(scene.coordinate_key)
    return CoordinatePointer(
        coordinate_key=scene.coordinate_key,
        coordinate_label=scene.coordinate_label,
        head_status=scene.head_status,
        json_path=f"coordinates/{filename}.json",
        markdown_path=f"coordinates/{filename}.md",
    )


def _overall_status(coordinates: tuple[CoordinateScene, ...]) -> SceneStatus:
    priorities: tuple[SceneStatus, ...] = (
        "needs_human",
        "failed",
        "interrupted",
        "repair_authorized",
        "running",
        "committed",
    )
    statuses = {item.head_status for item in coordinates}
    return next(item for item in priorities if item in statuses)


def _stuck_sort_key(scene: CoordinateScene) -> tuple[int, int, str]:
    reason = _stuck_reason(scene)
    reason_priority = {
        "thrashing": 0,
        "subprocess_crash": 1,
        "budget_exhausted": 2,
        "needs_human": 3,
        "no_repair_authority": 4,
        "blocked_by_parent": 5,
        None: 6,
    }[reason]
    status_priority = {
        "failed": 0,
        "needs_human": 1,
        "interrupted": 2,
        "repair_authorized": 3,
        "running": 4,
        "committed": 5,
    }[scene.head_status]
    return (reason_priority, status_priority, scene.coordinate_key)


def _stuck_reason(scene: CoordinateScene) -> StuckReason | None:
    if scene.head_status == "needs_human":
        return "needs_human"
    if scene.failure_code == "budget_exhausted":
        return "budget_exhausted"
    if scene.subprocess_pointer is not None:
        return "subprocess_crash"
    if scene.frontier_progress == "no_progress" and scene.attempt_ordinal > 1:
        return "thrashing"
    if scene.failure_code is not None and scene.failure_code.startswith("causal_"):
        return "blocked_by_parent"
    if scene.head_status in {"failed", "interrupted"} and scene.repair_authority == "none":
        return "no_repair_authority"
    return None


def _next_action(scene: CoordinateScene) -> NextActionHint | None:
    reason = _stuck_reason(scene)
    if reason == "subprocess_crash":
        return "inspect_subprocess"
    # A transport/infra terminal must be inspected as infrastructure even when
    # the attempt count would otherwise read as thrashing: the loop is caused by
    # mis-routing, not by an unrepairable design.  This precedes the thrashing
    # branch so it is not swallowed into request_human_review.
    if scene.repair_target == "infrastructure_transport":
        return "inspect_infrastructure"
    if scene.repair_target == "generated_candidate_code":
        return "repair_candidate_code"
    if scene.repair_target == "proposal_semantics":
        return "revise_proposal"
    if scene.repair_target == "design_worldspec":
        return "review_design_worldspec"
    if scene.repair_target == "needs_human" or reason in {
        "thrashing",
        "needs_human",
        "no_repair_authority",
    }:
        return "request_human_review"
    if scene.head_status in {"running", "repair_authorized"}:
        return "wait_for_running_work"
    return None


__all__ = [
    "CoordinatePointer",
    "CoordinateScene",
    "CoordinateWatermark",
    "FrontierDiff",
    "FrontierRecord",
    "MAX_COORDINATE_POINTERS",
    "MAX_FRONTIER_SAMPLES",
    "MAX_MISSING_COORDINATES",
    "MAX_ROOT_INDEX_ENTRIES",
    "MAX_TOP_ISSUES",
    "MAX_UNRESOLVED_ISSUES",
    "MAX_WATERMARK_COORDINATES",
    "ObservabilityIndex",
    "PipelineStage",
    "RunSceneIndex",
    "Scene",
    "SceneHead",
    "SceneIssue",
    "SceneTierBEvent",
    "SceneWatermark",
    "ScopeIndexEntry",
    "TopIssue",
    "fold",
]
