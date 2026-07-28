"""Read-side observability queries backed by durable Work and Tier B facts.

The reader intentionally has no scheduler, repair, or release capability.  It
can replace a disposable Tier A cache, but all decisions remain owned by the
existing WorkControlRuntime and generated Candidate code.
"""

from __future__ import annotations

import io
import json
import tarfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from agent_world.artifact_store import ArtifactStore, ArtifactWriter
from agent_world.builder.models import BuildRecord
from agent_world.contracts import (
    ArtifactRef,
    EnvironmentCandidate,
    EnvironmentDesign,
    canonical_json_bytes,
    sha256_digest,
)
from agent_world.control.telemetry import TelemetryStore
from agent_world.control.work import (
    ArtifactSlotContract,
    ValidationReport,
    WorkAttempt,
    WorkCoordinate,
    WorkDefinition,
)
from agent_world.control.work_store import WorkControlHead, WorkControlStore

from .paths import ObservabilityError, ObservabilityRoot
from .projector import SceneProjector
from .scene import CoordinateScene, FrontierRecord, RunSceneIndex, Scene
from .subprocess_scene import (
    RuntimeSubprocessScene,
    runtime_subprocess_scene_from_payload,
    safe_dynamic_text,
)

MAX_CANDIDATE_SOURCE_OUTPUT_BYTES = 256 * 1024
MAX_FRONTIER_DIFF_ISSUES = 32
MAX_COMPARE_STATUS_DIFFERENCES = 32
_TERMINAL_ATTEMPT_STATUSES = frozenset(
    {
        "succeeded",
        "failed",
        "interrupted",
        "cancelled",
        "budget_exhausted",
        "needs_human",
    }
)


@dataclass(frozen=True, slots=True)
class SceneRead:
    """The cache-validation outcome for one map-layer read."""

    scene: RunSceneIndex
    cache_status: Literal["hit", "rebuilt", "rebuilt_after_stale_watermark"]

    @property
    def stale_before_rebuild(self) -> bool:
        return self.cache_status == "rebuilt_after_stale_watermark"


class ObservabilityReader:
    """Capability-limited reader for the agent-facing `observe` commands."""

    def __init__(
        self,
        *,
        root: ObservabilityRoot,
        artifacts: ArtifactStore | ArtifactWriter,
        heads: WorkControlStore,
        telemetry: TelemetryStore,
        known_secret_canaries: Sequence[str | bytes] = (),
        tier_a_keep_last_scopes: int = 64,
    ) -> None:
        if isinstance(tier_a_keep_last_scopes, bool) or tier_a_keep_last_scopes < 1:
            raise ValueError("Tier A retention must keep at least one scope")
        self.root = root
        self.artifacts = artifacts
        self.heads = heads
        self.telemetry = telemetry
        self.known_secret_canaries = tuple(known_secret_canaries)
        self.tier_a_keep_last_scopes = tier_a_keep_last_scopes
        self._projector = SceneProjector(
            root=root,
            artifacts=artifacts,
            heads=heads,
            telemetry=telemetry,
            known_secret_canaries=known_secret_canaries,
        )

    def latest_scope_id(self) -> str:
        """Resolve `--latest` from durable head timestamps, never cache names."""

        return self._read("latest scope", self._latest_scope_id)

    def scene(self, scope_id: str, *, force_rebuild: bool = False) -> SceneRead:
        """Read a current map, rebuilding only when its watermark is invalid."""

        return self._read(
            "scene",
            lambda: self._scene(scope_id, force_rebuild=force_rebuild),
        )

    def scene_payload(self, scope_id: str, *, force_rebuild: bool = False) -> dict[str, object]:
        """Return CLI JSON, never emitting an unvalidated action hint."""

        result = self.scene(scope_id, force_rebuild=force_rebuild)
        payload = result.scene.model_dump(mode="json")
        payload["cache_status"] = result.cache_status
        if result.stale_before_rebuild:
            # The cache's old coordinate-level action is intentionally never
            # surfaced.  `observe rebuild` can be run explicitly to request a
            # fresh action hint after the reader has reconstructed Tier A.
            payload["next_action_hint"] = None
            payload["stale_cache_hint_suppressed"] = True
        return payload

    def coordinate(self, scope_id: str, coordinate: str) -> CoordinateScene:
        """Return one validated coordinate scene, self-healing a missing leaf."""

        return self._read(
            "coordinate",
            lambda: self._coordinate(scope_id, coordinate),
        )

    def subprocess(self, scope_id: str, coordinate: str) -> dict[str, object]:
        """Return one correlated Runtime crash scene from Tier B evidence."""

        return self._read(
            "subprocess",
            lambda: self._subprocess(scope_id, coordinate),
        )

    def candidate(self, scope_id: str, coordinate: str) -> dict[str, object]:
        """Read exactly one declared generated file from an in-memory tar blob."""

        return self._read(
            "candidate",
            lambda: self._candidate(scope_id, coordinate),
        )

    def contract(self, scope_id: str, coordinate: str) -> dict[str, object]:
        """Render a safe Candidate contract or its exact WorkDefinition fallback."""

        return self._read(
            "contract",
            lambda: self._contract(scope_id, coordinate),
        )

    def frontier_diff(
        self,
        scope_id: str,
        coordinate: str,
        *,
        from_attempt_ordinal: int | None = None,
        to_attempt_ordinal: int | None = None,
    ) -> dict[str, object]:
        """Compare two retained unresolved frontiers for one exact coordinate."""

        return self._read(
            "frontier diff",
            lambda: self._frontier_diff(
                scope_id,
                coordinate,
                from_attempt_ordinal=from_attempt_ordinal,
                to_attempt_ordinal=to_attempt_ordinal,
            ),
        )

    def compare(
        self,
        *,
        baseline_scope_id: str,
        candidate_scope_id: str,
    ) -> dict[str, object]:
        """Compare durable coordinate status facts across two scope partitions."""

        return self._read(
            "scope comparison",
            lambda: self._compare(
                baseline_scope_id=baseline_scope_id,
                candidate_scope_id=candidate_scope_id,
            ),
        )

    def replay(self, scope_id: str, coordinate: str) -> dict[str, object]:
        """Reconstruct compact terminal attempt history from Tier B telemetry."""

        return self._read("attempt replay", lambda: self._replay(scope_id, coordinate))

    def _latest_scope_id(self) -> str:
        scope_id = self.heads.latest_scope_id()
        if scope_id is None:
            raise ObservabilityError(
                "no durable WorkAttempt heads exist",
                code="observability_scope_not_found",
            )
        return scope_id

    def _scene(self, scope_id: str, *, force_rebuild: bool) -> SceneRead:
        safe_scope = self._projector.safe_scope_id(scope_id)
        cached = None if force_rebuild else self.root.read_scene(safe_scope)
        if cached is not None and self._projector.watermark_matches(scope_id, cached):
            return SceneRead(scene=cached, cache_status="hit")

        rebuilt = self._rebuild_scene(scope_id)
        return SceneRead(
            scene=rebuilt.index,
            cache_status=(
                "rebuilt_after_stale_watermark"
                if cached is not None
                else "rebuilt"
            ),
        )

    def _coordinate(self, scope_id: str, coordinate: str) -> CoordinateScene:
        self._scene(scope_id, force_rebuild=False)
        head = self._head_for_coordinate(scope_id, coordinate)
        safe_scope = self._projector.safe_scope_id(scope_id)
        cached = self.root.read_coordinate(safe_scope, head.coordinate.coordinate_key)
        if (
            cached is not None
            and cached.head_status == head.status
            and cached.attempt_ref_id == self._safe(head.attempt_ref.artifact_id)
        ):
            return cached

        # A valid map can still coexist with a missing coordinate file if the
        # process died between individual cache writes.  Re-fold from durable
        # facts rather than infer a terrain view from the map alone.
        rebuilt = self._rebuild_scene(scope_id)
        for item in rebuilt.coordinates:
            if item.coordinate_key == head.coordinate.coordinate_key:
                return item
        raise ObservabilityError(
            "durable coordinate is absent from rebuilt scene",
            code="observability_coordinate_unavailable",
        )

    def _frontier_diff(
        self,
        scope_id: str,
        coordinate: str,
        *,
        from_attempt_ordinal: int | None,
        to_attempt_ordinal: int | None,
    ) -> dict[str, object]:
        if (from_attempt_ordinal is None) != (to_attempt_ordinal is None):
            raise ObservabilityError(
                "frontier diff requires both --from and --to together",
                code="observability_frontier_selector_invalid",
            )
        if (
            from_attempt_ordinal is not None
            and (from_attempt_ordinal < 1 or to_attempt_ordinal is None or to_attempt_ordinal < 1)
        ):
            raise ObservabilityError(
                "frontier attempt ordinals must be positive",
                code="observability_frontier_selector_invalid",
            )
        head = self._head_for_coordinate(scope_id, coordinate)
        safe_scope = self._projector.safe_scope_id(scope_id)
        records = self.root.read_frontier(safe_scope, head.coordinate.coordinate_key)
        if not records:
            raise ObservabilityError(
                "no retained frontier history exists for this coordinate",
                code="observability_frontier_not_found",
            )
        ordered = tuple(
            sorted(
                records,
                key=lambda item: (item.attempt_ordinal, item.attempt_ref_revision),
            )
        )
        if from_attempt_ordinal is None:
            if len(ordered) < 2:
                raise ObservabilityError(
                    "frontier diff requires at least two retained attempts",
                    code="observability_frontier_not_found",
                )
            from_record, to_record = ordered[-2:]
        else:
            assert to_attempt_ordinal is not None
            from_record = self._frontier_record_for_ordinal(records, from_attempt_ordinal)
            to_record = self._frontier_record_for_ordinal(records, to_attempt_ordinal)
        if from_record.attempt_ordinal >= to_record.attempt_ordinal:
            raise ObservabilityError(
                "frontier diff requires an earlier --from attempt",
                code="observability_frontier_selector_invalid",
            )

        from_issue_ids = self._frontier_issue_ids(
            from_record,
            expected_coordinate_key=head.coordinate.coordinate_key,
        )
        to_issue_ids = self._frontier_issue_ids(
            to_record,
            expected_coordinate_key=head.coordinate.coordinate_key,
        )
        added = to_issue_ids - from_issue_ids
        removed = from_issue_ids - to_issue_ids
        retained = from_issue_ids & to_issue_ids
        return {
            "scope_id": safe_scope,
            "coordinate_key": head.coordinate.coordinate_key,
            "from": self._frontier_record_payload(from_record),
            "to": self._frontier_record_payload(to_record),
            "issues": {
                "added": self._bounded_issue_ids(added),
                "removed": self._bounded_issue_ids(removed),
                "retained": self._bounded_issue_ids(retained),
            },
            "frontier_ordinal_delta": (
                to_record.frontier_ordinal - from_record.frontier_ordinal
            ),
        }

    def _compare(
        self,
        *,
        baseline_scope_id: str,
        candidate_scope_id: str,
    ) -> dict[str, object]:
        baseline = self._rebuild_scene(baseline_scope_id)
        candidate = self._rebuild_scene(candidate_scope_id)
        baseline_by_label = self._coordinates_by_label(baseline.coordinates)
        candidate_by_label = self._coordinates_by_label(candidate.coordinates)
        differences: list[dict[str, object]] = []
        for label in sorted(set(baseline_by_label) | set(candidate_by_label)):
            baseline_coordinate = baseline_by_label.get(label)
            candidate_coordinate = candidate_by_label.get(label)
            if (
                baseline_coordinate is not None
                and candidate_coordinate is not None
                and baseline_coordinate.head_status == candidate_coordinate.head_status
            ):
                continue
            differences.append(
                self._status_difference_payload(
                    label,
                    baseline_coordinate,
                    candidate_coordinate,
                )
            )
        return {
            "baseline_scope_id": baseline.index.scope_id,
            "candidate_scope_id": candidate.index.scope_id,
            "first_diverging_coordinate": differences[0] if differences else None,
            "status_differences": differences[:MAX_COMPARE_STATUS_DIFFERENCES],
            "status_difference_overflow_count": max(
                0,
                len(differences) - MAX_COMPARE_STATUS_DIFFERENCES,
            ),
        }

    def _replay(self, scope_id: str, coordinate: str) -> dict[str, object]:
        head = self._head_for_coordinate(scope_id, coordinate)
        current = self.artifacts.get_json(head.attempt_ref, WorkAttempt)
        attempts, trace_ids = self._attempt_lineage(current)
        by_hash = {
            sha256_digest(item.attempt_id.encode("utf-8")): item
            for item in attempts
        }
        rows: list[tuple[int, int, dict[str, object]]] = []
        seen: set[str] = set()
        for trace_id in trace_ids:
            trace = self.telemetry.inspect_trace(trace_id)
            for event in trace["events"]:
                if event.get("event_type") != "work.attempt_terminal":
                    continue
                try:
                    payload = json.loads(str(event.get("payload_json", "{}")))
                except (TypeError, ValueError):
                    continue
                if not isinstance(payload, dict):
                    continue
                attempt_hash = payload.get("attempt_id_hash")
                event_coordinate_key = payload.get("coordinate_key")
                ordinal = payload.get("attempt_ordinal")
                status = payload.get("attempt_status")
                frontier_ordinal = payload.get("frontier_ordinal")
                if not isinstance(attempt_hash, str):
                    continue
                attempt = by_hash.get(attempt_hash)
                if (
                    attempt is None
                    or event_coordinate_key != head.coordinate.coordinate_key
                    or not isinstance(ordinal, int)
                    or ordinal != attempt.ordinal
                    or status not in _TERMINAL_ATTEMPT_STATUSES
                    or status != attempt.status
                    or (frontier_ordinal is not None and not isinstance(frontier_ordinal, int))
                    or attempt_hash in seen
                ):
                    continue
                recorded_at = event.get("recorded_at_ns")
                rows.append(
                    (
                        ordinal,
                        recorded_at if isinstance(recorded_at, int) else 0,
                        {
                            "attempt_id": self._safe(attempt.attempt_id),
                            "status": status,
                            "frontier_ordinal": frontier_ordinal,
                        },
                    )
                )
                seen.add(attempt_hash)
        ordered = [item for _ordinal, _recorded_at, item in sorted(rows)]
        if not ordered:
            raise ObservabilityError(
                "no Tier B terminal attempt events exist for this coordinate",
                code="observability_replay_not_found",
            )
        return {
            "scope_id": self._projector.safe_scope_id(scope_id),
            "coordinate_key": head.coordinate.coordinate_key,
            "attempts": ordered,
            "source": "tier_b_telemetry",
        }

    def _subprocess(self, scope_id: str, coordinate: str) -> dict[str, object]:
        coordinate_scene = self._coordinate(scope_id, coordinate)
        runtime_scene = self._latest_subprocess_scene(scope_id, coordinate_scene.coordinate_key)
        if runtime_scene is None:
            raise ObservabilityError(
                "no correlated Runtime subprocess scene exists for this coordinate",
                code="observability_subprocess_not_found",
            )
        payload: dict[str, object] = {
            "scope_id": self._projector.safe_scope_id(scope_id),
            "coordinate_key": coordinate_scene.coordinate_key,
            "subprocess": runtime_scene.telemetry_payload(),
        }
        self.root.write_subprocess(
            self._projector.safe_scope_id(scope_id),
            coordinate_scene.coordinate_key,
            canonical_json_bytes(payload),
        )
        return payload

    def _candidate(self, scope_id: str, coordinate: str) -> dict[str, object]:
        self._coordinate(scope_id, coordinate)
        head = self._head_for_coordinate(scope_id, coordinate)
        attempt = self.artifacts.get_json(head.attempt_ref, WorkAttempt)
        candidate_ref, candidate = self._candidate_for_attempt(attempt)
        path = self._projector.candidate_file_for_attempt(attempt)
        if path is None:
            raise ObservabilityError(
                "this coordinate has no exact single-file generated Candidate target",
                code="observability_candidate_not_actionable",
            )
        record = self.artifacts.get_json(candidate.build_artifact_ref, BuildRecord)
        declared_files = tuple(item for item in record.files if item.path == path)
        if len(declared_files) != 1:
            raise ObservabilityError(
                "declared Candidate file is unavailable",
                code="observability_candidate_unavailable",
            )
        declared = declared_files[0]
        if (
            record.source_snapshot_ref != candidate.source_workspace_snapshot_ref
            or record.source_snapshot_ref.artifact_type != "build.source_workspace_snapshot"
            or record.source_snapshot_ref.media_type != "application/x-tar"
        ):
            raise ObservabilityError(
                "Candidate source snapshot does not satisfy its frozen contract",
                code="observability_candidate_unavailable",
            )
        source = self._tar_file(record.source_snapshot_ref, path)
        if len(source) != declared.size_bytes or sha256_digest(source) != declared.content_hash:
            raise ObservabilityError(
                "Candidate source file does not match its BuildRecord declaration",
                code="observability_candidate_integrity",
            )
        decoded = source.decode("utf-8", errors="replace")
        safe_source = self._safe(decoded)
        redacted = safe_source != decoded
        truncated = False
        if not redacted and len(source) > MAX_CANDIDATE_SOURCE_OUTPUT_BYTES:
            safe_source = source[:MAX_CANDIDATE_SOURCE_OUTPUT_BYTES].decode(
                "utf-8", errors="replace"
            )
            truncated = True
        return {
            "scope_id": self._projector.safe_scope_id(scope_id),
            "coordinate_key": head.coordinate.coordinate_key,
            "candidate_ref_revision": candidate_ref.revision_id,
            "path": self._safe(path),
            "source": safe_source,
            "source_redacted": redacted,
            "source_truncated": truncated,
            "read_only": True,
        }

    def _contract(self, scope_id: str, coordinate: str) -> dict[str, object]:
        self._coordinate(scope_id, coordinate)
        head = self._head_for_coordinate(scope_id, coordinate)
        attempt = self.artifacts.get_json(head.attempt_ref, WorkAttempt)
        try:
            _candidate_ref, candidate = self._candidate_for_attempt(attempt)
        except ObservabilityError as exc:
            if exc.code != "observability_candidate_unavailable":
                raise
            # Design and research nodes do not yet have an EnvironmentCandidate,
            # but their scene still points an investigating Code Agent here.  A
            # durable WorkDefinition is the safe, read-only contract available
            # at that boundary; do not advertise a Candidate contract that the
            # node cannot possibly own.
            definition = self._work_definition_for_head(head)
            return self._work_definition_contract(scope_id, head, definition)
        if candidate.design_ref.artifact_type not in {
            "design.environment_design",
            "expansion.environment_design",
        }:
            raise ObservabilityError(
                "frozen EnvironmentDesign is unavailable for this coordinate",
                code="observability_contract_unavailable",
            )
        design = self.artifacts.get_json(candidate.design_ref, EnvironmentDesign)
        tools: list[dict[str, object]] = []
        for tool in design.world_spec.tools:
            surface = tool.surface
            tools.append(
                {
                    "tool_id": self._safe(surface.tool_id),
                    "namespace": self._safe(surface.namespace),
                    "name": self._safe(surface.name),
                    "input_schema": self._safe_json(surface.input_schema),
                    "output_schema": self._safe_json(surface.output_schema),
                }
            )
        verification = design.verification
        return {
            "scope_id": self._projector.safe_scope_id(scope_id),
            "coordinate_key": head.coordinate.coordinate_key,
            "read_only_reference": True,
            "do_not_modify": ["world_spec", "gate"],
            "world_spec_tool_surface": tools,
            "verifier_expectation": {
                "required_rule_ids": [
                    self._safe(item) for item in verification.required_rule_ids
                ],
                "required_property_families": [
                    self._safe(item) for item in verification.required_property_families
                ],
                "required_metamorphic_relations": [
                    self._safe(item) for item in verification.required_metamorphic_relations
                ],
                "deployment_checks": [
                    self._safe(item) for item in verification.deployment_checks
                ],
                "minimum_unknown_seed_episodes": verification.minimum_unknown_seed_episodes,
            },
        }

    def _work_definition_for_head(self, head: WorkControlHead) -> WorkDefinition:
        """Recover one exact immutable definition without trusting a cache hint."""

        candidates: list[WorkDefinition] = []
        for ref in self.artifacts.list_revisions():
            if (
                ref.artifact_type != "control.work_definition"
                or ref.content_hash != head.definition_digest
            ):
                continue
            try:
                definition = self.artifacts.get_json(ref, WorkDefinition)
            except ValueError:
                continue
            if (
                definition.work_id == head.work_id
                and definition.coordinate == head.coordinate
                and definition.definition_digest == head.definition_digest
                and definition.acceptance_digest == head.acceptance_digest
            ):
                candidates.append(definition)
        if not candidates or any(item != candidates[0] for item in candidates[1:]):
            raise ObservabilityError(
                "this coordinate lacks one exact durable WorkDefinition",
                code="observability_contract_unavailable",
            )
        return candidates[0]

    def _work_definition_contract(
        self,
        scope_id: str,
        head: WorkControlHead,
        definition: WorkDefinition,
    ) -> dict[str, object]:
        """Project the compact contract a design-stage investigator can use.

        This is deliberately a path map to framework-owned policy, not a copy
        of a rendered runtime Prompt, mounted Runtime Skill, model response,
        repair authority, or budget ledger.  Those remain available only from
        their dedicated safe views when a diagnosis requires them.
        """

        return {
            "scope_id": self._projector.safe_scope_id(scope_id),
            "coordinate_key": head.coordinate.coordinate_key,
            "contract_kind": "work_definition",
            "read_only_reference": True,
            "do_not_modify": ["framework_work_definition", "control_plane"],
            "work": {
                "work_id": self._safe(definition.work_id),
                "required_claim_id": self._safe(definition.required_claim_id),
                "success_maturity": self._safe(definition.success_maturity),
                "dependencies": [
                    self._safe_coordinate(item) for item in definition.dependency_coordinates
                ],
                "allowed_mutation_roots": [
                    self._safe(item) for item in definition.allowed_mutation_roots
                ],
            },
            "proposal": {
                "executor": definition.proposal_policy.executor,
                "operation": self._safe(definition.proposal_policy.operation),
                "replay_mode": definition.proposal_policy.replay_mode,
                "agent_role": definition.proposal_policy.agent_role,
                "capability_profile_id": self._safe_optional(
                    definition.proposal_policy.capability_profile_id
                ),
                "output_contract_id": self._safe_optional(
                    definition.proposal_policy.output_contract_id
                ),
                "implementation_revision_id": self._safe(
                    definition.proposal_policy.implementation_revision_id
                ),
            },
            "validation": {
                "validator_id": self._safe(definition.validation_policy.validator_id),
                "validator_revision_id": self._safe(
                    definition.validation_policy.validator_revision_id
                ),
                "validation_phase": self._safe(definition.validation_policy.validation_phase),
                "frontier_ordinal": definition.validation_policy.frontier_ordinal,
                "effect": definition.validation_policy.effect,
            },
            "input_slots": [self._safe_slot(slot) for slot in definition.input_slots],
            "output_slots": [self._safe_slot(slot) for slot in definition.output_slots],
        }

    def _safe_coordinate(self, coordinate: WorkCoordinate) -> dict[str, object]:
        """Render only the public identity fields of a dependency coordinate."""

        return {
            "component": coordinate.component,
            "stage": self._safe(coordinate.stage),
            "artifact_slot": self._safe(coordinate.artifact_slot),
            "group_id": self._safe_optional(coordinate.group_id),
            "shard_id": self._safe_optional(coordinate.shard_id),
        }

    def _safe_slot(self, slot: ArtifactSlotContract) -> dict[str, object]:
        """Project one immutable Artifact slot without its concrete inputs."""

        return {
            "slot_id": self._safe(slot.slot_id),
            "direction": slot.direction,
            "artifact_types": [self._safe(item) for item in slot.artifact_types],
            "minimum_count": slot.minimum_count,
            "maximum_count": slot.maximum_count,
            "producer_component": slot.producer_component,
            "confidentiality": slot.confidentiality,
        }

    def _rebuild_scene(self, scope_id: str) -> Scene:
        """Rebuild Tier A, then best-effort collect other disposable scopes."""

        scene = self._projector.rebuild(scope_id)
        # Retention belongs to the read-side cache plane.  It must never make
        # a durable diagnosis or a completed WorkAttempt unavailable.
        try:
            self.root.prune_scopes(
                keep_last=self.tier_a_keep_last_scopes,
                preserve_scope_ids=(scene.index.scope_id,),
            )
        except Exception:
            return scene
        return scene

    @staticmethod
    def _frontier_record_for_ordinal(
        records: Sequence[FrontierRecord],
        ordinal: int,
    ) -> FrontierRecord:
        matches = tuple(item for item in records if item.attempt_ordinal == ordinal)
        if len(matches) != 1:
            raise ObservabilityError(
                "frontier attempt ordinal does not resolve to one retained record",
                code="observability_frontier_not_found",
            )
        return matches[0]

    def _frontier_issue_ids(
        self,
        record: FrontierRecord,
        *,
        expected_coordinate_key: str,
    ) -> set[str]:
        refs = tuple(
            ref
            for ref in self.artifacts.list_revisions()
            if (
                ref.artifact_type == "control.work_attempt"
                and ref.revision_id == record.attempt_ref_revision
            )
        )
        if len(refs) != 1:
            raise ObservabilityError(
                "frontier record no longer resolves to one durable WorkAttempt",
                code="observability_frontier_unavailable",
            )
        attempt = self.artifacts.get_json(refs[0], WorkAttempt)
        if (
            attempt.coordinate.coordinate_key != expected_coordinate_key
            or attempt.ordinal != record.attempt_ordinal
            or self._safe(attempt.attempt_id) != record.attempt_ref_id
        ):
            raise ObservabilityError(
                "frontier record conflicts with its durable WorkAttempt",
                code="observability_frontier_unavailable",
            )
        if attempt.validation_report_ref is None:
            if record.unresolved_issue_count:
                raise ObservabilityError(
                    "frontier record lacks its durable validation report",
                    code="observability_frontier_unavailable",
                )
            return set()
        report = self.artifacts.get_json(attempt.validation_report_ref, ValidationReport)
        if report.attempt_id != attempt.attempt_id or report.coordinate != attempt.coordinate:
            raise ObservabilityError(
                "frontier validation report conflicts with its WorkAttempt",
                code="observability_frontier_unavailable",
            )
        issue_ids = set(report.blocking_issue_ids)
        if len(issue_ids) != record.unresolved_issue_count:
            raise ObservabilityError(
                "frontier record differs from durable validation evidence",
                code="observability_frontier_unavailable",
            )
        return issue_ids

    def _frontier_record_payload(self, record: FrontierRecord) -> dict[str, object]:
        return {
            "attempt_id": self._safe(record.attempt_ref_id),
            "attempt_ref_revision": self._safe(record.attempt_ref_revision),
            "attempt_ordinal": record.attempt_ordinal,
            "frontier_ordinal": record.frontier_ordinal,
            "unresolved_issue_digest": self._safe(record.unresolved_issue_digest),
            "unresolved_issue_count": record.unresolved_issue_count,
        }

    def _bounded_issue_ids(self, values: set[str]) -> dict[str, object]:
        ordered = tuple(sorted(values))
        return {
            "issue_ids": [self._safe(item) for item in ordered[:MAX_FRONTIER_DIFF_ISSUES]],
            "count": len(ordered),
            "overflow_count": max(0, len(ordered) - MAX_FRONTIER_DIFF_ISSUES),
        }

    @staticmethod
    def _coordinates_by_label(
        coordinates: Sequence[CoordinateScene],
    ) -> dict[str, CoordinateScene]:
        result: dict[str, CoordinateScene] = {}
        for coordinate in coordinates:
            if coordinate.coordinate_label in result:
                raise ObservabilityError(
                    "scope has ambiguous coordinate labels",
                    code="observability_compare_ambiguous",
                )
            result[coordinate.coordinate_label] = coordinate
        return result

    def _status_difference_payload(
        self,
        label: str,
        baseline: CoordinateScene | None,
        candidate: CoordinateScene | None,
    ) -> dict[str, object]:
        return {
            "coordinate_label": self._safe(label),
            "baseline": {
                "coordinate_key": (
                    self._safe(baseline.coordinate_key) if baseline is not None else None
                ),
                "status": baseline.head_status if baseline is not None else None,
            },
            "candidate": {
                "coordinate_key": (
                    self._safe(candidate.coordinate_key) if candidate is not None else None
                ),
                "status": candidate.head_status if candidate is not None else None,
            },
        }

    def _attempt_lineage(
        self,
        current: WorkAttempt,
    ) -> tuple[tuple[WorkAttempt, ...], tuple[str, ...]]:
        """Walk immutable parent links to find all traces for one coordinate."""

        attempts: list[WorkAttempt] = []
        trace_ids: list[str] = []
        current_id = current.attempt_id
        expected_coordinate = current.coordinate
        seen_ids: set[str] = set()
        while current_id not in seen_ids:
            seen_ids.add(current_id)
            candidates = tuple(
                self.artifacts.get_json(ref, WorkAttempt)
                for ref in self.artifacts.list_revisions(current_id)
                if ref.artifact_type == "control.work_attempt"
            )
            eligible = tuple(
                item
                for item in candidates
                if item.attempt_id == current_id and item.coordinate == expected_coordinate
            )
            if not eligible:
                raise ObservabilityError(
                    "attempt lineage is unavailable from durable Artifacts",
                    code="observability_replay_unavailable",
                )
            selected = max(
                eligible,
                key=lambda item: (
                    item.finished_at is not None,
                    item.finished_at or item.scheduled_at,
                    item.ordinal,
                ),
            )
            attempts.append(selected)
            if selected.telemetry_trace_id is not None:
                trace_ids.append(selected.telemetry_trace_id)
            current_id = selected.parent_attempt_id or ""
            if not current_id:
                break
        return (
            tuple(attempts),
            tuple(dict.fromkeys(trace_ids)),
        )

    def _head_for_coordinate(self, scope_id: str, coordinate: str) -> WorkControlHead:
        heads = self.heads.read_scope_heads(scope_id)
        matches = tuple(
            head
            for head in heads
            if coordinate
            in {
                head.coordinate.coordinate_key,
                f"{head.coordinate.component}.{head.coordinate.stage}.{head.coordinate.artifact_slot}",
            }
        )
        if len(matches) != 1:
            raise ObservabilityError(
                "coordinate does not resolve to one durable WorkAttempt head",
                code="observability_coordinate_not_found",
            )
        return matches[0]

    def _candidate_for_attempt(
        self,
        attempt: WorkAttempt,
    ) -> tuple[ArtifactRef, EnvironmentCandidate]:
        refs = tuple(
            ref
            for ref in attempt.input_refs
            if ref.artifact_type == "build.environment_candidate"
        )
        if len(refs) != 1:
            raise ObservabilityError(
                "coordinate does not bind one exact EnvironmentCandidate",
                code="observability_candidate_unavailable",
            )
        candidate = self.artifacts.get_json(refs[0], EnvironmentCandidate)
        return refs[0], candidate

    def _latest_subprocess_scene(
        self,
        scope_id: str,
        coordinate_key: str,
    ) -> RuntimeSubprocessScene | None:
        candidates: list[tuple[int, RuntimeSubprocessScene]] = []
        for head in self.heads.read_scope_heads(scope_id):
            attempt = self.artifacts.get_json(head.attempt_ref, WorkAttempt)
            if attempt.telemetry_trace_id is None:
                continue
            trace = self.telemetry.inspect_trace(attempt.telemetry_trace_id)
            for row in trace["events"]:
                if row.get("event_type") != "runtime_subprocess_scene":
                    continue
                try:
                    payload = json.loads(str(row.get("payload_json", "{}")))
                except (TypeError, ValueError):
                    continue
                if not isinstance(payload, dict) or payload.get("coordinate_key") != coordinate_key:
                    continue
                scene = runtime_subprocess_scene_from_payload(
                    payload,
                    known_secret_canaries=self.known_secret_canaries,
                )
                if scene is None:
                    continue
                recorded_at = row.get("recorded_at_ns")
                if isinstance(recorded_at, int):
                    candidates.append((recorded_at, scene))
        if not candidates:
            return None
        return max(candidates, key=lambda item: item[0])[1]

    def _tar_file(self, source_snapshot_ref: ArtifactRef, path: str) -> bytes:
        # Tar members are never extracted.  Exact name matching prevents a
        # path traversal payload from becoming a filesystem read primitive.
        try:
            archive_bytes = self.artifacts.get_blob(source_snapshot_ref)
            with tarfile.open(fileobj=io.BytesIO(archive_bytes), mode="r:") as archive:
                matches = tuple(
                    member
                    for member in archive.getmembers()
                    if member.name == path and member.isfile()
                )
                if len(matches) != 1:
                    raise ObservabilityError(
                        "Candidate source tar lacks one exact declared file",
                        code="observability_candidate_unavailable",
                    )
                stream = archive.extractfile(matches[0])
                if stream is None:
                    raise ObservabilityError(
                        "Candidate source tar file cannot be read",
                        code="observability_candidate_unavailable",
                    )
                return stream.read()
        except ObservabilityError:
            raise
        except (OSError, tarfile.TarError) as exc:
            raise ObservabilityError(
                "Candidate source tar is unavailable",
                code="observability_candidate_unavailable",
            ) from exc

    def _safe_json(self, value: object) -> object:
        if value is None or isinstance(value, (bool, int, float)):
            return value
        if isinstance(value, str):
            return self._safe(value)
        if isinstance(value, list):
            return [self._safe_json(item) for item in value]
        if isinstance(value, tuple):
            return [self._safe_json(item) for item in value]
        if isinstance(value, Mapping):
            output: dict[str, object] = {}
            for key, item in value.items():
                safe_key = self._safe(str(key))
                if safe_key in output:
                    raise ObservabilityError(
                        "contract schema cannot be safely rendered",
                        code="observability_contract_unavailable",
                    )
                output[safe_key] = self._safe_json(item)
            return output
        raise ObservabilityError(
            "contract schema contains an unsupported value",
            code="observability_contract_unavailable",
        )

    def _safe(self, value: str) -> str:
        return safe_dynamic_text(
            value,
            known_secret_canaries=self.known_secret_canaries,
        )

    def _safe_optional(self, value: str | None) -> str | None:
        return None if value is None else self._safe(value)

    @staticmethod
    def _read(label: str, operation: Any) -> Any:
        try:
            return operation()
        except ObservabilityError:
            raise
        except Exception as exc:
            raise ObservabilityError(
                f"durable observability {label} data is unavailable",
                code="observability_data_unavailable",
            ) from exc


__all__ = [
    "MAX_CANDIDATE_SOURCE_OUTPUT_BYTES",
    "ObservabilityReader",
    "SceneRead",
]
