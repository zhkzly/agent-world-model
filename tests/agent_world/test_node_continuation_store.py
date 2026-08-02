from __future__ import annotations

import os
from pathlib import Path

import pytest

from agent_world.contracts import ArtifactRef, sha256_digest
from agent_world.control.continuation_store import (
    ContinuationStoreError,
    DiagnosticSemanticRepairSeedRecord,
    NodeContinuationRecord,
    NodeContinuationStore,
    SemanticRepairSeedRecord,
    SemanticRepairSeedStore,
)
from agent_world.invocation.contracts import InvocationSession
from agent_world.research.security import ResearchSafetyError


def _session(workspace: Path) -> InvocationSession:
    return InvocationSession(
        thread_id="thread-hotel-1",
        lineage_id="job:hotel.tool-semantics.batch:1",
        workspace=workspace.resolve(),
        profile_hash="1" * 64,
        codex_config_sha256="2" * 64,
    )


def _ref(label: str, artifact_type: str) -> ArtifactRef:
    return ArtifactRef(
        artifact_id=f"artifact:{label}",
        revision_id=sha256_digest(f"revision:{label}".encode()),
        artifact_type=artifact_type,
        content_hash=sha256_digest(f"content:{label}".encode()),
        media_type="application/json",
        size_bytes=1,
    )


def _capture(workspace: Path, *, previous_candidate):
    return NodeContinuationRecord.capture(
        work_id="work:hotel:tool-semantics",
        attempt_id="attempt:1",
        session=_session(workspace),
        model="gpt-5.4-mini",
        output_schema_digest=sha256_digest(b"tool-semantics-schema"),
        definition_digest=sha256_digest(b"definition"),
        proposal_policy_digest=sha256_digest(b"proposal-policy"),
        input_fingerprint=sha256_digest(b"inputs"),
        previous_candidate=previous_candidate,
        allowed_mutation_roots=("/tools",),
        source_report_ref=_ref("report", "control.validation_report"),
        source_evaluation_ref=_ref("evaluation", "control.feedback_evaluation"),
        repair_action_ref=_ref("action", "control.repair_action"),
        previous_execution_ref=_ref("execution", "control.proposal_execution"),
    )


def _seed_capture(*, previous_candidate):
    return SemanticRepairSeedRecord.capture(
        work_id="work:hotel:tool-semantics",
        attempt_id="attempt:1",
        model="gpt-5.4-mini",
        profile_digest=sha256_digest(b"challenger-profile"),
        output_schema_digest=sha256_digest(b"tool-semantics-schema"),
        definition_digest=sha256_digest(b"definition"),
        proposal_policy_digest=sha256_digest(b"proposal-policy"),
        input_fingerprint=sha256_digest(b"inputs"),
        previous_candidate=previous_candidate,
        allowed_mutation_roots=("/tools",),
        source_report_ref=_ref("report", "control.validation_report"),
        source_evaluation_ref=_ref("evaluation", "control.feedback_evaluation"),
        repair_action_ref=_ref("action", "control.repair_action"),
        previous_execution_ref=_ref("execution", "control.proposal_execution"),
    )


def _diagnostic_seed_capture(*, previous_candidate):
    return DiagnosticSemanticRepairSeedRecord.capture(
        work_id="work:hotel:tool-semantics",
        attempt_id="attempt:1",
        model="gpt-5.4-mini",
        profile_digest=sha256_digest(b"challenger-profile"),
        output_schema_digest=sha256_digest(b"tool-semantics-schema"),
        definition_digest=sha256_digest(b"definition"),
        proposal_policy_digest=sha256_digest(b"proposal-policy"),
        input_fingerprint=sha256_digest(b"inputs"),
        previous_candidate=previous_candidate,
        source_output_commitment=sha256_digest(b"direct-output"),
        previous_execution_ref=_ref("execution", "control.proposal_execution"),
    )


def test_private_continuation_restores_only_exact_model_schema_and_commitment(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    store = NodeContinuationStore(tmp_path / "continuations")
    record = _capture(workspace, previous_candidate={"tools": [{"tool_id": "reserve_hotel"}]})
    store.save(record)

    loaded = store.load_exact(
        expected=record,
        workspace_root=tmp_path,
    )
    assert loaded == record
    assert loaded is not None
    assert loaded.restore_session() == _session(workspace)
    mismatched = record.model_copy(update={"attempt_id": "attempt:2"})
    with pytest.raises(ValueError, match="record commitment"):
        store.load_exact(expected=mismatched, workspace_root=tmp_path)
    assert (os.stat(store.root).st_mode & 0o777) == 0o700
    assert all((os.stat(path).st_mode & 0o777) == 0o600 for path in store.root.iterdir())


def test_continuation_metadata_inspection_does_not_authorize_workspace(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "source-runs" / "workspace"
    workspace.mkdir(parents=True)
    store = NodeContinuationStore(tmp_path / "continuations")
    record = _capture(workspace, previous_candidate={"tools": []})
    store.save(record)

    # Clone orchestration may recover the commitment-bound path, but execution
    # still requires a separate exact-root containment check.
    assert store.inspect_commitment(record.record_commitment) == record
    unrelated_root = tmp_path / "unrelated-runs"
    unrelated_root.mkdir()
    with pytest.raises(ContinuationStoreError, match="outside its authorized root"):
        store.load_commitment(
            record.record_commitment,
            workspace_root=unrelated_root,
        )


def test_private_workspace_recovery_keeps_draft_without_provider_thread(tmp_path: Path) -> None:
    """A draft recovery is private state for a fresh session, not a session restore."""

    workspace = tmp_path / "builder" / "attempt-1" / ".agent-runtime" / "workspace"
    workspace.mkdir(parents=True)
    (workspace / "candidate.py").write_text("def build(): pass\n", encoding="utf-8")
    store = NodeContinuationStore(tmp_path / "continuations")
    record = NodeContinuationRecord.capture_workspace_recovery(
        work_id="work:hotel:candidate-build",
        attempt_id="attempt:1",
        lineage_id="implementation:hotel",
        workspace=workspace,
        profile_digest=sha256_digest(b"builder-profile"),
        codex_config_digest=sha256_digest(b"builder-config"),
        model="grok-4.5",
        output_schema_digest=sha256_digest(b"candidate-completion-schema"),
        definition_digest=sha256_digest(b"candidate-definition"),
        proposal_policy_digest=sha256_digest(b"candidate-proposal-policy"),
        input_fingerprint=sha256_digest(b"candidate-inputs"),
        allowed_mutation_roots=("/candidate",),
        source_report_ref=_ref("report", "control.validation_report"),
        source_evaluation_ref=_ref("evaluation", "control.feedback_evaluation"),
        repair_action_ref=_ref("action", "control.repair_action"),
        previous_execution_ref=_ref("execution", "control.proposal_execution"),
    )
    store.save(record)

    loaded = store.load_commitment(record.record_commitment, workspace_root=tmp_path)
    assert loaded == record
    assert loaded is not None
    assert loaded.continuation_kind == "workspace_recovery"
    assert loaded.thread_id is None
    assert loaded.workspace_for_recovery() == workspace.resolve()
    with pytest.raises(ContinuationStoreError, match="cannot resume a Provider thread"):
        loaded.restore_session()
    with pytest.raises(ValueError, match="workspace recovery must not retain"):
        NodeContinuationRecord.model_validate(
            {**loaded.model_dump(mode="python"), "thread_id": "private-thread"}
        )


def test_private_continuation_rejects_secret_material_and_conflicting_identity(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    store = NodeContinuationStore(tmp_path / "continuations")
    record = _capture(
        workspace,
        previous_candidate={"authorization": "Bearer very-sensitive-runtime-token-123456"},
    )
    with pytest.raises(ResearchSafetyError, match="credential-like"):
        store.save(record)

    safe = _capture(workspace, previous_candidate={"tools": []})
    store.save(safe)
    conflict = safe.model_copy(update={"created_at": safe.created_at.replace(year=2025)})
    with pytest.raises(ContinuationStoreError, match="other state"):
        store.save(conflict)


def test_private_continuation_recovers_orphan_by_exact_repair_authority(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    store = NodeContinuationStore(tmp_path / "continuations")
    record = _capture(workspace, previous_candidate={"tools": []})
    store.save(record)

    recovered = store.find_repair_binding(
        work_id=record.work_id,
        attempt_id=record.attempt_id,
        definition_digest=record.definition_digest,
        proposal_policy_digest=record.proposal_policy_digest,
        input_fingerprint=record.input_fingerprint,
        source_report_ref=record.source_report_ref,
        source_evaluation_ref=record.source_evaluation_ref,
        repair_action_ref=record.repair_action_ref,
        previous_execution_ref=record.previous_execution_ref,
        workspace_root=tmp_path,
    )
    assert recovered == record
    assert (
        store.find_repair_binding(
            work_id=record.work_id,
            attempt_id="attempt:other",
            definition_digest=record.definition_digest,
            proposal_policy_digest=record.proposal_policy_digest,
            input_fingerprint=record.input_fingerprint,
            source_report_ref=record.source_report_ref,
            source_evaluation_ref=record.source_evaluation_ref,
            repair_action_ref=record.repair_action_ref,
            previous_execution_ref=record.previous_execution_ref,
            workspace_root=tmp_path,
        )
        is None
    )


def test_private_stateless_semantic_seed_requires_exact_repair_authority(
    tmp_path: Path,
) -> None:
    """A Direct repair retains parsed JSON, never a workspace or thread handle."""

    store = SemanticRepairSeedStore(tmp_path / "semantic-repair-seeds")
    record = _seed_capture(previous_candidate={"tools": [{"tool_id": "reserve_hotel"}]})
    store.save(record)

    assert store.load_commitment(record.record_commitment) == record
    assert (
        store.find_repair_binding(
            work_id=record.work_id,
            attempt_id=record.attempt_id,
            definition_digest=record.definition_digest,
            proposal_policy_digest=record.proposal_policy_digest,
            input_fingerprint=record.input_fingerprint,
            source_report_ref=record.source_report_ref,
            source_evaluation_ref=record.source_evaluation_ref,
            repair_action_ref=record.repair_action_ref,
            previous_execution_ref=record.previous_execution_ref,
        )
        == record
    )
    assert (
        store.find_repair_binding(
            work_id=record.work_id,
            attempt_id="attempt:other",
            definition_digest=record.definition_digest,
            proposal_policy_digest=record.proposal_policy_digest,
            input_fingerprint=record.input_fingerprint,
            source_report_ref=record.source_report_ref,
            source_evaluation_ref=record.source_evaluation_ref,
            repair_action_ref=record.repair_action_ref,
            previous_execution_ref=record.previous_execution_ref,
        )
        is None
    )
    assert (os.stat(store.root).st_mode & 0o777) == 0o700
    assert (os.stat(store.pending_root).st_mode & 0o777) == 0o700
    assert all((os.stat(path).st_mode & 0o777) == 0o600 for path in store.root.glob("*.json"))

    unsafe = _seed_capture(
        previous_candidate={"authorization": "Bearer very-sensitive-runtime-token-123456"}
    )
    with pytest.raises(ResearchSafetyError, match="credential-like"):
        store.save(unsafe)


def test_private_diagnostic_seed_is_not_an_artifact_until_exact_repair_binds_it(
    tmp_path: Path,
) -> None:
    store = SemanticRepairSeedStore(tmp_path / "semantic-repair-seeds")
    record = _diagnostic_seed_capture(previous_candidate={"tools": [{"tool_id": "reserve_hotel"}]})

    store.save_diagnostic_pending(record)

    assert (
        store.find_diagnostic_pending(
            work_id=record.work_id,
            attempt_id=record.attempt_id,
            definition_digest=record.definition_digest,
            proposal_policy_digest=record.proposal_policy_digest,
            input_fingerprint=record.input_fingerprint,
            previous_execution_ref=record.previous_execution_ref,
        )
        == record
    )
    assert (
        store.find_diagnostic_pending(
            work_id=record.work_id,
            attempt_id="attempt:other",
            definition_digest=record.definition_digest,
            proposal_policy_digest=record.proposal_policy_digest,
            input_fingerprint=record.input_fingerprint,
            previous_execution_ref=record.previous_execution_ref,
        )
        is None
    )
    assert (os.stat(store.pending_root).st_mode & 0o777) == 0o700
    assert all((os.stat(path).st_mode & 0o777) == 0o600 for path in store.pending_root.iterdir())

    unsafe = _diagnostic_seed_capture(
        previous_candidate={"authorization": "Bearer very-sensitive-runtime-token-123456"}
    )
    with pytest.raises(ResearchSafetyError, match="credential-like"):
        store.save_diagnostic_pending(unsafe)
