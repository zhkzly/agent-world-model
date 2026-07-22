from __future__ import annotations

import os
from pathlib import Path

import pytest

from agent_world.contracts import ArtifactRef, sha256_digest
from agent_world.control.continuation_store import (
    ContinuationStoreError,
    NodeContinuationRecord,
    NodeContinuationStore,
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
