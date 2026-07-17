from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError
from v3_fixture import build_release_graph

from agent_world.artifact_store import ArtifactStore
from agent_world.consumer import (
    CapabilityFeedbackIntegrityError,
    FeedbackRecorder,
)
from agent_world.contracts import (
    ArtifactRef,
    CapabilityCountSignal,
    CapabilityCoverageGapSignal,
    CapabilityFailureSignal,
    CapabilityFeedback,
    CapabilityRateSignal,
    CapabilityRewardSignal,
    CapabilityStepsSignal,
    CapabilitySuccessSignal,
    SuiteSelectionRequest,
    sha256_digest,
)
from agent_world.designer.expansion_source import project_capability_feedback_for_source
from agent_world.registry import EnvironmentRegistry


def _signals() -> tuple[
    CapabilitySuccessSignal,
    CapabilityFailureSignal,
    CapabilityRateSignal,
    CapabilityRewardSignal,
    CapabilityStepsSignal,
    CapabilityCountSignal,
    CapabilityCoverageGapSignal,
]:
    return (
        CapabilitySuccessSignal(
            capability_dimension="inventory.reconciliation",
            sample_count=20,
            confidence=0.9,
            count=13,
        ),
        CapabilityFailureSignal(
            capability_dimension="inventory.reconciliation",
            sample_count=20,
            confidence=0.9,
            count=7,
        ),
        CapabilityRateSignal(
            capability_dimension="inventory.reconciliation",
            sample_count=20,
            confidence=0.9,
            metric="success",
            value=0.65,
        ),
        CapabilityRewardSignal(
            capability_dimension="inventory.reconciliation",
            sample_count=20,
            confidence=0.9,
            statistic="mean",
            value=0.72,
        ),
        CapabilityStepsSignal(
            capability_dimension="inventory.reconciliation",
            sample_count=20,
            confidence=0.9,
            statistic="p95",
            value=11.0,
        ),
        CapabilityCountSignal(
            capability_dimension="inventory.reconciliation",
            sample_count=20,
            confidence=0.9,
            metric="tool_calls",
            count=84,
        ),
        CapabilityCoverageGapSignal(
            capability_dimension="inventory.reconciliation",
            sample_count=20,
            confidence=0.9,
            gap="low_success",
            severity=0.35,
        ),
    )


def _private_audit_ref() -> ArtifactRef:
    digest = sha256_digest(b"private aggregate audit evidence")
    return ArtifactRef(
        artifact_id="sealed-case-audit:private",
        revision_id=digest,
        artifact_type="consumer.private_rollout_audit",
        content_hash=digest,
        media_type="application/json",
        size_bytes=32,
    )


def _released_suite(
    root: Path,
) -> tuple[ArtifactStore, EnvironmentRegistry, str, str]:
    state_root = root / "state"
    store = ArtifactStore(state_root / "artifacts")
    graph = build_release_graph(state_root, store)
    registry = EnvironmentRegistry(state_root / "registry", store)
    reservation = registry.reserve_package_version(
        graph.package_id,
        graph.version,
        graph.owner_ref,
    )
    prepared = registry.prepare(
        candidate_workspace=graph.workspace,
        manifest_ref=graph.manifest_ref,
        judge_report_ref=graph.report_ref,
        release_profile=graph.release_profile,
        reservation=reservation,
        framework_payloads=graph.framework_payloads,
    )
    release = registry.publish(prepared)
    snapshot = registry.create_suite_snapshot(
        (
            SuiteSelectionRequest(
                package_id=release.coordinate.package_id,
                version=release.coordinate.version,
            ),
        )
    )
    return store, registry, snapshot.snapshot_id, snapshot.snapshot_digest


def test_capability_feedback_is_a_closed_content_addressed_aggregate() -> None:
    feedback = CapabilityFeedback.create(
        created_at=datetime(2026, 7, 14, tzinfo=UTC),
        suite_snapshot_id="suite_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        suite_snapshot_digest="sha256:" + "a" * 64,
        signals=_signals(),
        evidence_refs=(_private_audit_ref(),),
    )

    assert feedback.feedback_id.startswith("feedback:")
    assert len(feedback.signals) == 7
    assert not hasattr(feedback, "capability_dimensions")
    assert not hasattr(feedback, "suite_snapshot_ref")

    payload = feedback.model_dump(mode="json")
    payload["oracle"] = {"expected_action": "do-not-leak"}
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        CapabilityFeedback.model_validate(payload)

    signal_payload = _signals()[2].model_dump(mode="json")
    signal_payload["hidden_task_id"] = "task:private"
    signal_payload["expected_action"] = "inventory.commit"
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        CapabilityRateSignal.model_validate(signal_payload)


def test_source_projection_exposes_only_typed_priority_signals() -> None:
    feedback = CapabilityFeedback.create(
        created_at=datetime(2026, 7, 14, tzinfo=UTC),
        suite_snapshot_id="suite_bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
        suite_snapshot_digest="sha256:" + "b" * 64,
        signals=_signals(),
        evidence_refs=(_private_audit_ref(),),
    )

    projection = project_capability_feedback_for_source(feedback)

    assert set(projection) == {"feedback_id", "suite_snapshot_digest", "signals"}
    assert projection["feedback_id"] == feedback.feedback_id
    assert projection["suite_snapshot_digest"] == feedback.suite_snapshot_digest
    assert projection["signals"] == [
        signal.model_dump(mode="json", exclude={"schema_version"}, exclude_none=False)
        for signal in feedback.signals
    ]
    serialized = str(projection).casefold()
    for forbidden in (
        "evidence_refs",
        "suite_snapshot_id",
        "sealed-case-audit",
        "oracle",
        "verifier",
        "expected_action",
        "hidden_task",
    ):
        assert forbidden not in serialized


def test_feedback_recorder_rejects_suite_digest_mismatch_and_persists_audit_edges(
    tmp_path: Path,
) -> None:
    store, registry, snapshot_id, snapshot_digest = _released_suite(tmp_path)
    audit_writer = store.issue_writer(
        producer="rollout-consumer",
        allowed_artifact_types=("consumer.rollout_aggregate",),
    )
    audit_ref = audit_writer.put_json(
        artifact_id="rollout-aggregate:inventory",
        artifact_type="consumer.rollout_aggregate",
        value={"episodes": 20, "successes": 13, "failures": 7},
    )
    feedback_writer = store.issue_writer(
        producer="consumer-feedback-recorder",
        allowed_artifact_types=("consumer.capability_feedback",),
        allowed_artifact_id_prefixes=("feedback:",),
    )
    recorder = FeedbackRecorder(registry=registry, artifact_store=feedback_writer)

    with pytest.raises(CapabilityFeedbackIntegrityError, match="differs from Registry"):
        recorder.record(
            suite_snapshot_id=snapshot_id,
            suite_snapshot_digest="sha256:" + "0" * 64,
            signals=_signals(),
            evidence_refs=(audit_ref,),
        )
    assert not store.list_revisions("feedback:" + "0" * 64)

    recorded = recorder.record(
        suite_snapshot_id=snapshot_id,
        suite_snapshot_digest=snapshot_digest,
        signals=_signals(),
        evidence_refs=(audit_ref,),
        created_at=datetime(2026, 7, 14, tzinfo=UTC),
    )

    assert recorded.feedback.suite_snapshot_id == snapshot_id
    assert recorded.feedback.suite_snapshot_digest == snapshot_digest
    assert store.get_json(recorded.feedback_ref, CapabilityFeedback) == recorded.feedback
    assert store.dependencies(recorded.feedback_ref) == (audit_ref,)


def test_feedback_recorder_requires_a_single_purpose_writer(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    broad_writer = store.issue_writer(
        producer="consumer-feedback-recorder",
        allowed_artifact_types=("consumer.capability_feedback",),
        allowed_artifact_type_prefixes=("consumer.",),
    )
    registry = EnvironmentRegistry(tmp_path / "registry", store)

    with pytest.raises(ValueError, match="artifact type prefixes"):
        FeedbackRecorder(registry=registry, artifact_store=broad_writer)
