"""Record privacy-preserving aggregate feedback for optional Evolve campaigns.

The recorder deliberately consumes an immutable Registry Suite identity rather
than an Artifact reference.  Evidence references remain private audit edges in
the Artifact DAG; they are not part of the projection shown to a Researcher.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from agent_world.artifact_store import ArtifactWriter
from agent_world.contracts import (
    CAPABILITY_FEEDBACK_ARTIFACT_ID_PREFIX,
    CAPABILITY_FEEDBACK_ARTIFACT_TYPE,
    CAPABILITY_FEEDBACK_PRODUCER,
    ArtifactRef,
    CapabilityAggregateSignal,
    CapabilityFeedback,
)
from agent_world.registry import EnvironmentRegistry


class CapabilityFeedbackError(RuntimeError):
    """Base error for feedback admission and persistence failures."""


class CapabilityFeedbackIntegrityError(CapabilityFeedbackError):
    """The caller's Suite commitment does not match Registry truth."""


@dataclass(frozen=True, slots=True)
class RecordedCapabilityFeedback:
    feedback: CapabilityFeedback
    feedback_ref: ArtifactRef


class FeedbackRecorder:
    """Persist aggregate consumer signals under one least-privilege writer."""

    def __init__(
        self,
        *,
        registry: EnvironmentRegistry,
        artifact_store: ArtifactWriter,
    ) -> None:
        self._require_narrow_writer(artifact_store)
        self.registry = registry
        self.artifacts = artifact_store

    def record(
        self,
        *,
        suite_snapshot_id: str,
        suite_snapshot_digest: str,
        signals: Sequence[CapabilityAggregateSignal],
        evidence_refs: Sequence[ArtifactRef] = (),
        created_at: datetime | None = None,
    ) -> RecordedCapabilityFeedback:
        """Verify the immutable Suite and commit one content-addressed aggregate."""

        snapshot = self.registry.load_suite_snapshot(suite_snapshot_id)
        if snapshot.snapshot_digest != suite_snapshot_digest:
            raise CapabilityFeedbackIntegrityError(
                "CapabilityFeedback Suite digest differs from Registry snapshot"
            )
        feedback = CapabilityFeedback.create(
            created_at=created_at or datetime.now(UTC),
            suite_snapshot_id=snapshot.snapshot_id,
            suite_snapshot_digest=snapshot.snapshot_digest,
            signals=tuple(signals),
            evidence_refs=tuple(evidence_refs),
        )
        feedback_ref = self.artifacts.put_json(
            artifact_id=feedback.feedback_id,
            artifact_type=CAPABILITY_FEEDBACK_ARTIFACT_TYPE,
            value=feedback,
            dependencies=feedback.evidence_refs,
        )
        return RecordedCapabilityFeedback(feedback=feedback, feedback_ref=feedback_ref)

    @staticmethod
    def _require_narrow_writer(writer: ArtifactWriter) -> None:
        capability = writer.capability
        if capability.producer != CAPABILITY_FEEDBACK_PRODUCER:
            raise ValueError(
                f"FeedbackRecorder writer producer must be {CAPABILITY_FEEDBACK_PRODUCER}"
            )
        if capability.allowed_artifact_types != (CAPABILITY_FEEDBACK_ARTIFACT_TYPE,):
            raise ValueError(
                "FeedbackRecorder requires an ArtifactWriter restricted to exactly "
                "consumer.capability_feedback"
            )
        if capability.allowed_artifact_type_prefixes:
            raise ValueError("FeedbackRecorder writer cannot authorize artifact type prefixes")
        if capability.allowed_event_types or capability.allowed_event_type_prefixes:
            raise ValueError("FeedbackRecorder writer cannot authorize unrelated events")
        if capability.allowed_artifact_id_prefixes not in (
            (),
            (CAPABILITY_FEEDBACK_ARTIFACT_ID_PREFIX,),
        ):
            raise ValueError("FeedbackRecorder writer has an incompatible artifact id scope")


__all__ = [
    "CAPABILITY_FEEDBACK_ARTIFACT_ID_PREFIX",
    "CAPABILITY_FEEDBACK_ARTIFACT_TYPE",
    "CAPABILITY_FEEDBACK_PRODUCER",
    "CapabilityFeedbackError",
    "CapabilityFeedbackIntegrityError",
    "FeedbackRecorder",
    "RecordedCapabilityFeedback",
]
