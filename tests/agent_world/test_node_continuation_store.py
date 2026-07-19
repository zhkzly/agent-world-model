from __future__ import annotations

import os
from pathlib import Path

import pytest

from agent_world.contracts import sha256_digest
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


def test_private_continuation_restores_only_exact_model_schema_and_commitment(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    store = NodeContinuationStore(tmp_path / "continuations")
    record = NodeContinuationRecord.capture(
        work_id="work:hotel:tool-semantics",
        attempt_id="attempt:1",
        session=_session(workspace),
        model="gpt-5.4-mini",
        output_schema_digest=sha256_digest(b"tool-semantics-schema"),
        previous_candidate={"tools": [{"tool_id": "reserve_hotel"}]},
        allowed_mutation_roots=("/tools",),
    )
    store.save(record)

    loaded = store.load_exact(
        record.continuation_id,
        work_id=record.work_id,
        session_commitment=record.session_commitment,
        model=record.model,
        output_schema_digest=record.output_schema_digest,
    )
    assert loaded == record
    assert loaded is not None
    assert loaded.restore_session() == _session(workspace)
    assert (
        store.load_exact(
            record.continuation_id,
            work_id=record.work_id,
            session_commitment=record.session_commitment,
            model="different-model",
            output_schema_digest=record.output_schema_digest,
        )
        is None
    )
    assert (os.stat(store.root).st_mode & 0o777) == 0o700
    assert all((os.stat(path).st_mode & 0o777) == 0o600 for path in store.root.iterdir())


def test_private_continuation_rejects_secret_material_and_conflicting_identity(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    store = NodeContinuationStore(tmp_path / "continuations")
    record = NodeContinuationRecord.capture(
        work_id="work:hotel:tool-semantics",
        attempt_id="attempt:1",
        session=_session(workspace),
        model="gpt-5.4-mini",
        output_schema_digest=sha256_digest(b"schema"),
        previous_candidate={"authorization": "Bearer very-sensitive-runtime-token-123456"},
        allowed_mutation_roots=("/tools",),
    )
    with pytest.raises(ResearchSafetyError, match="credential-like"):
        store.save(record)

    safe = record.model_copy(
        update={
            "previous_candidate": {"tools": []},
            "candidate_commitment": sha256_digest(b'{"tools":[]}'),
        }
    )
    store.save(safe)
    conflict = safe.model_copy(update={"created_at": safe.created_at.replace(year=2025)})
    with pytest.raises(ContinuationStoreError, match="other state"):
        store.save(conflict)
