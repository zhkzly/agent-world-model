from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from agent_world.contracts import ArtifactRef, sha256_digest
from agent_world.control import (
    DirectJobAlreadyRunningError,
    DirectJobHeadConflictError,
    DirectJobStore,
    new_direct_job_head,
)


def _ref(name: str, artifact_type: str) -> ArtifactRef:
    digest = sha256_digest(name.encode("utf-8"))
    return ArtifactRef(
        artifact_id=name,
        revision_id=digest,
        artifact_type=artifact_type,
        content_hash=digest,
        media_type="application/json",
        size_bytes=0,
    )


def test_direct_job_store_is_single_writer_restart_safe_and_identity_immutable(
    tmp_path: Path,
) -> None:
    store = DirectJobStore(tmp_path / "direct-jobs")
    request_id = "request:durable-one"
    request_ref = _ref("request-artifact:one", "control.environment_request")
    job_ref = _ref("generate-job:one", "control.environment_job")
    snapshot_one = _ref("run:one:state:one", "control.job_run_snapshot")
    snapshot_two = _ref("run:one:state:two", "control.job_run_snapshot")
    result_ref = _ref("run:one:result", "control.generate_result")
    fingerprint = sha256_digest(b"canonical-request-one")

    with store.exclusive(request_id) as lock:
        first = new_direct_job_head(
            request_id=request_id,
            request_fingerprint=fingerprint,
            request_ref=request_ref,
            job_ref=job_ref,
            run_id="run:direct-one",
            snapshot_ref=snapshot_one,
            snapshot_revision=1,
            status="running",
        )
        assert store.compare_and_swap(lock, expected_head=None, next_head=first) == first
        with pytest.raises(DirectJobAlreadyRunningError):
            with DirectJobStore(tmp_path / "direct-jobs").exclusive(request_id):
                pass

        changed_identity = new_direct_job_head(
            request_id=request_id,
            request_fingerprint=sha256_digest(b"different-request"),
            request_ref=request_ref,
            job_ref=job_ref,
            run_id="run:direct-one",
            snapshot_ref=snapshot_two,
            snapshot_revision=2,
            status="released",
        )
        with pytest.raises(DirectJobHeadConflictError, match="identity cannot change"):
            store.compare_and_swap(
                lock,
                expected_head=first,
                next_head=changed_identity,
            )

        released = new_direct_job_head(
            request_id=request_id,
            request_fingerprint=fingerprint,
            request_ref=request_ref,
            job_ref=job_ref,
            run_id="run:direct-one",
            snapshot_ref=snapshot_two,
            snapshot_revision=2,
            status="released",
        )
        assert store.compare_and_swap(lock, expected_head=first, next_head=released) == released
        completed = released.model_copy(
            update={"result_ref": result_ref, "updated_at": datetime.now(UTC)}
        )
        assert (
            store.compare_and_swap(lock, expected_head=released, next_head=completed) == completed
        )

    reopened = DirectJobStore(tmp_path / "direct-jobs")
    assert reopened.read_head(request_id) == completed
    with reopened.exclusive(request_id) as lock:
        with pytest.raises(DirectJobHeadConflictError, match="completed.*immutable"):
            reopened.compare_and_swap(
                lock,
                expected_head=completed,
                next_head=completed.model_copy(update={"updated_at": datetime.now(UTC)}),
            )


def test_failed_direct_head_requires_explicit_restart_and_preserves_prior_result(
    tmp_path: Path,
) -> None:
    store = DirectJobStore(tmp_path / "direct-jobs")
    request_id = "request:resumable"
    request_ref = _ref("request-artifact:resumable", "control.environment_request")
    job_ref = _ref("generate-job:resumable", "control.environment_job")
    fingerprint = sha256_digest(b"canonical-resumable-request")
    first_snapshot = _ref("run:first:state", "control.job_run_snapshot")
    failed_snapshot = _ref("run:first:failed", "control.job_run_snapshot")
    failed_result = _ref("run:first:result", "control.generate_result")
    resumed_snapshot = _ref("run:second:state", "control.job_run_snapshot")

    with store.exclusive(request_id) as lock:
        running = new_direct_job_head(
            request_id=request_id,
            request_fingerprint=fingerprint,
            request_ref=request_ref,
            job_ref=job_ref,
            run_id="run:first",
            snapshot_ref=first_snapshot,
            snapshot_revision=1,
            status="running",
        )
        store.compare_and_swap(lock, expected_head=None, next_head=running)
        failed = new_direct_job_head(
            request_id=request_id,
            request_fingerprint=fingerprint,
            request_ref=request_ref,
            job_ref=job_ref,
            run_id="run:first",
            snapshot_ref=failed_snapshot,
            snapshot_revision=2,
            status="failed",
        )
        store.compare_and_swap(lock, expected_head=running, next_head=failed)
        completed = failed.model_copy(
            update={"result_ref": failed_result, "updated_at": datetime.now(UTC)}
        )
        store.compare_and_swap(lock, expected_head=failed, next_head=completed)
        resumed = new_direct_job_head(
            request_id=request_id,
            request_fingerprint=fingerprint,
            request_ref=request_ref,
            job_ref=job_ref,
            run_id="run:second",
            snapshot_ref=resumed_snapshot,
            snapshot_revision=1,
            status="running",
            previous_result_ref=failed_result,
        )

        with pytest.raises(DirectJobHeadConflictError, match="identity cannot change"):
            store.compare_and_swap(lock, expected_head=completed, next_head=resumed)
        assert store.compare_and_swap(
            lock,
            expected_head=completed,
            next_head=resumed,
            allow_terminal_restart=True,
        ) == resumed
