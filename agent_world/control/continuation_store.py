"""Private durable continuation state for one WorkAttempt.

Opaque backend sessions and the last shape-valid candidate are deliberately not
Artifact DAG members and never enter release packages or public telemetry.  A
public WorkAttempt stores only ``session_commitment``; this private store can
resume only when every binding digest still matches.
"""

from __future__ import annotations

import hashlib
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import AwareDatetime, JsonValue, model_validator

from agent_world.contracts import (
    ArtifactRef,
    ContentHash,
    Identifier,
    NonEmptyStr,
    V2Contract,
    canonical_json_bytes,
    sha256_digest,
)
from agent_world.invocation.contracts import InvocationSession
from agent_world.research.security import assert_secret_free

_MAX_PRIVATE_CANDIDATE_BYTES = 4 * 1024 * 1024


class ContinuationStoreError(RuntimeError):
    """Private continuation state is unsafe, conflicting, or corrupted."""


class NodeContinuationRecord(V2Contract):
    continuation_id: Identifier
    work_id: Identifier
    attempt_id: Identifier
    # ``session`` is an opaque same-thread continuation.  ``workspace_recovery``
    # intentionally carries no thread id: it authorizes a fresh Provider
    # session to inspect an untrusted private Builder draft after a closed
    # infrastructure terminal, never an old-thread resume.
    continuation_kind: Literal["session", "workspace_recovery"] = "session"
    thread_id: NonEmptyStr | None = None
    lineage_id: Identifier
    workspace: NonEmptyStr
    profile_digest: ContentHash
    codex_config_digest: ContentHash
    model: NonEmptyStr
    output_schema_digest: ContentHash
    definition_digest: ContentHash
    proposal_policy_digest: ContentHash
    input_fingerprint: ContentHash
    previous_candidate: JsonValue | None = None
    candidate_commitment: ContentHash | None = None
    allowed_mutation_roots: tuple[NonEmptyStr, ...] = ()
    source_report_ref: ArtifactRef
    source_evaluation_ref: ArtifactRef
    repair_action_ref: ArtifactRef
    previous_execution_ref: ArtifactRef
    session_commitment: ContentHash
    record_commitment: ContentHash
    created_at: AwareDatetime

    @model_validator(mode="after")
    def validate_private_binding(self) -> NodeContinuationRecord:
        if not Path(self.workspace).is_absolute():
            raise ValueError("continuation workspace must be absolute")
        if self.continuation_kind == "session" and self.thread_id is None:
            raise ValueError("session continuation requires a private thread id")
        if self.continuation_kind == "workspace_recovery":
            if self.thread_id is not None:
                raise ValueError("workspace recovery must not retain a private thread id")
            if self.previous_candidate is not None:
                raise ValueError("workspace recovery cannot adopt a parsed candidate")
        if len(set(self.allowed_mutation_roots)) != len(self.allowed_mutation_roots):
            raise ValueError("continuation mutation roots must be unique")
        candidate_bytes = canonical_json_bytes(self.previous_candidate)
        if len(candidate_bytes) > _MAX_PRIVATE_CANDIDATE_BYTES:
            raise ValueError("private continuation candidate exceeds 4 MiB")
        expected_candidate = (
            sha256_digest(candidate_bytes) if self.previous_candidate is not None else None
        )
        if self.candidate_commitment != expected_candidate:
            raise ValueError("continuation candidate commitment mismatch")
        expected_session = self.compute_session_commitment(
            thread_id=self.thread_id,
            continuation_kind=self.continuation_kind,
            lineage_id=self.lineage_id,
            workspace=self.workspace,
            profile_digest=self.profile_digest,
            codex_config_digest=self.codex_config_digest,
            model=self.model,
            output_schema_digest=self.output_schema_digest,
        )
        if self.session_commitment != expected_session:
            raise ValueError("continuation session commitment mismatch")
        expected_record = self.compute_record_commitment(
            work_id=self.work_id,
            attempt_id=self.attempt_id,
            continuation_kind=self.continuation_kind,
            definition_digest=self.definition_digest,
            proposal_policy_digest=self.proposal_policy_digest,
            input_fingerprint=self.input_fingerprint,
            session_commitment=self.session_commitment,
            candidate_commitment=self.candidate_commitment,
            allowed_mutation_roots=self.allowed_mutation_roots,
            source_report_ref=self.source_report_ref,
            source_evaluation_ref=self.source_evaluation_ref,
            repair_action_ref=self.repair_action_ref,
            previous_execution_ref=self.previous_execution_ref,
        )
        if self.record_commitment != expected_record:
            raise ValueError("continuation record commitment mismatch")
        expected_id = self.continuation_id_for(expected_record)
        if self.continuation_id != expected_id:
            raise ValueError("continuation id is not derived from its record commitment")
        expected_types = (
            (self.source_report_ref.artifact_type, "control.validation_report"),
            (self.source_evaluation_ref.artifact_type, "control.feedback_evaluation"),
            (self.repair_action_ref.artifact_type, "control.repair_action"),
            (self.previous_execution_ref.artifact_type, "control.proposal_execution"),
        )
        if any(actual != expected for actual, expected in expected_types):
            raise ValueError("continuation authority ref has the wrong Artifact type")
        return self

    @staticmethod
    def compute_session_commitment(
        *,
        thread_id: str | None,
        continuation_kind: Literal["session", "workspace_recovery"] = "session",
        lineage_id: str,
        workspace: str,
        profile_digest: str,
        codex_config_digest: str,
        model: str,
        output_schema_digest: str,
    ) -> ContentHash:
        if continuation_kind == "session":
            if thread_id is None:
                raise ValueError("session continuation requires a thread id")
            # Preserve the existing commitment shape for persisted private
            # session records. A clean workspace-recovery record has its own
            # tagged shape below.
            payload: dict[str, str] = {
                "thread_id": thread_id,
                "lineage_id": lineage_id,
                "workspace": workspace,
                "profile_digest": profile_digest,
                "codex_config_digest": codex_config_digest,
                "model": model,
                "output_schema_digest": output_schema_digest,
            }
        else:
            if thread_id is not None:
                raise ValueError("workspace recovery cannot commit a thread id")
            payload = {
                "continuation_kind": "workspace_recovery",
                "lineage_id": lineage_id,
                "workspace": workspace,
                "profile_digest": profile_digest,
                "codex_config_digest": codex_config_digest,
                "model": model,
                "output_schema_digest": output_schema_digest,
            }
        return sha256_digest(canonical_json_bytes(payload))

    @staticmethod
    def compute_record_commitment(
        *,
        work_id: str,
        attempt_id: str,
        continuation_kind: Literal["session", "workspace_recovery"] = "session",
        definition_digest: str,
        proposal_policy_digest: str,
        input_fingerprint: str,
        session_commitment: str,
        candidate_commitment: str | None,
        allowed_mutation_roots: tuple[str, ...],
        source_report_ref: ArtifactRef,
        source_evaluation_ref: ArtifactRef,
        repair_action_ref: ArtifactRef,
        previous_execution_ref: ArtifactRef,
    ) -> ContentHash:
        payload: dict[str, object] = {
            "work_id": work_id,
            "attempt_id": attempt_id,
            "definition_digest": definition_digest,
            "proposal_policy_digest": proposal_policy_digest,
            "input_fingerprint": input_fingerprint,
            "session_commitment": session_commitment,
            "candidate_commitment": candidate_commitment,
            "allowed_mutation_roots": allowed_mutation_roots,
            "source_report_ref": source_report_ref.model_dump(mode="json"),
            "source_evaluation_ref": source_evaluation_ref.model_dump(mode="json"),
            "repair_action_ref": repair_action_ref.model_dump(mode="json"),
            "previous_execution_ref": previous_execution_ref.model_dump(mode="json"),
        }
        if continuation_kind == "workspace_recovery":
            payload["continuation_kind"] = continuation_kind
        return sha256_digest(canonical_json_bytes(payload))

    @staticmethod
    def continuation_id_for(record_commitment: str) -> Identifier:
        return f"continuation:{record_commitment.removeprefix('sha256:')[:24]}"

    @classmethod
    def capture(
        cls,
        *,
        work_id: Identifier,
        attempt_id: Identifier,
        session: InvocationSession,
        model: str,
        output_schema_digest: ContentHash,
        definition_digest: ContentHash,
        proposal_policy_digest: ContentHash,
        input_fingerprint: ContentHash,
        previous_candidate: JsonValue | None,
        allowed_mutation_roots: tuple[str, ...],
        source_report_ref: ArtifactRef,
        source_evaluation_ref: ArtifactRef,
        repair_action_ref: ArtifactRef,
        previous_execution_ref: ArtifactRef,
    ) -> NodeContinuationRecord:
        candidate_commitment = (
            sha256_digest(canonical_json_bytes(previous_candidate))
            if previous_candidate is not None
            else None
        )
        profile_digest = cls._normalize_digest(session.profile_hash)
        config_digest = cls._normalize_digest(session.codex_config_sha256)
        workspace = str(session.workspace.resolve())
        session_commitment = cls.compute_session_commitment(
            thread_id=session.thread_id,
            lineage_id=session.lineage_id,
            workspace=workspace,
            profile_digest=profile_digest,
            codex_config_digest=config_digest,
            model=model,
            output_schema_digest=output_schema_digest,
        )
        record_commitment = cls.compute_record_commitment(
            work_id=work_id,
            attempt_id=attempt_id,
            definition_digest=definition_digest,
            proposal_policy_digest=proposal_policy_digest,
            input_fingerprint=input_fingerprint,
            session_commitment=session_commitment,
            candidate_commitment=candidate_commitment,
            allowed_mutation_roots=allowed_mutation_roots,
            source_report_ref=source_report_ref,
            source_evaluation_ref=source_evaluation_ref,
            repair_action_ref=repair_action_ref,
            previous_execution_ref=previous_execution_ref,
        )
        return cls(
            continuation_id=cls.continuation_id_for(record_commitment),
            work_id=work_id,
            attempt_id=attempt_id,
            thread_id=session.thread_id,
            lineage_id=session.lineage_id,
            workspace=workspace,
            profile_digest=profile_digest,
            codex_config_digest=config_digest,
            model=model,
            output_schema_digest=output_schema_digest,
            definition_digest=definition_digest,
            proposal_policy_digest=proposal_policy_digest,
            input_fingerprint=input_fingerprint,
            previous_candidate=previous_candidate,
            candidate_commitment=candidate_commitment,
            allowed_mutation_roots=allowed_mutation_roots,
            source_report_ref=source_report_ref,
            source_evaluation_ref=source_evaluation_ref,
            repair_action_ref=repair_action_ref,
            previous_execution_ref=previous_execution_ref,
            session_commitment=session_commitment,
            record_commitment=record_commitment,
            created_at=datetime.now(UTC),
        )

    @classmethod
    def capture_workspace_recovery(
        cls,
        *,
        work_id: Identifier,
        attempt_id: Identifier,
        lineage_id: Identifier,
        workspace: Path,
        profile_digest: str,
        codex_config_digest: str,
        model: str,
        output_schema_digest: ContentHash,
        definition_digest: ContentHash,
        proposal_policy_digest: ContentHash,
        input_fingerprint: ContentHash,
        allowed_mutation_roots: tuple[str, ...],
        source_report_ref: ArtifactRef,
        source_evaluation_ref: ArtifactRef,
        repair_action_ref: ArtifactRef,
        previous_execution_ref: ArtifactRef,
    ) -> NodeContinuationRecord:
        """Capture a verified private draft without retaining its Provider thread."""

        normalized_workspace = str(workspace.expanduser().resolve())
        normalized_profile = cls._normalize_digest(profile_digest)
        normalized_config = cls._normalize_digest(codex_config_digest)
        session_commitment = cls.compute_session_commitment(
            thread_id=None,
            continuation_kind="workspace_recovery",
            lineage_id=lineage_id,
            workspace=normalized_workspace,
            profile_digest=normalized_profile,
            codex_config_digest=normalized_config,
            model=model,
            output_schema_digest=output_schema_digest,
        )
        record_commitment = cls.compute_record_commitment(
            work_id=work_id,
            attempt_id=attempt_id,
            continuation_kind="workspace_recovery",
            definition_digest=definition_digest,
            proposal_policy_digest=proposal_policy_digest,
            input_fingerprint=input_fingerprint,
            session_commitment=session_commitment,
            candidate_commitment=None,
            allowed_mutation_roots=allowed_mutation_roots,
            source_report_ref=source_report_ref,
            source_evaluation_ref=source_evaluation_ref,
            repair_action_ref=repair_action_ref,
            previous_execution_ref=previous_execution_ref,
        )
        return cls(
            continuation_id=cls.continuation_id_for(record_commitment),
            work_id=work_id,
            attempt_id=attempt_id,
            continuation_kind="workspace_recovery",
            thread_id=None,
            lineage_id=lineage_id,
            workspace=normalized_workspace,
            profile_digest=normalized_profile,
            codex_config_digest=normalized_config,
            model=model,
            output_schema_digest=output_schema_digest,
            definition_digest=definition_digest,
            proposal_policy_digest=proposal_policy_digest,
            input_fingerprint=input_fingerprint,
            previous_candidate=None,
            candidate_commitment=None,
            allowed_mutation_roots=allowed_mutation_roots,
            source_report_ref=source_report_ref,
            source_evaluation_ref=source_evaluation_ref,
            repair_action_ref=repair_action_ref,
            previous_execution_ref=previous_execution_ref,
            session_commitment=session_commitment,
            record_commitment=record_commitment,
            created_at=datetime.now(UTC),
        )

    def restore_session(self) -> InvocationSession:
        if self.continuation_kind != "session" or self.thread_id is None:
            raise ContinuationStoreError(
                "workspace recovery records cannot resume a Provider thread"
            )
        return InvocationSession(
            thread_id=self.thread_id,
            lineage_id=self.lineage_id,
            workspace=Path(self.workspace),
            profile_hash=self.profile_digest.removeprefix("sha256:"),
            codex_config_sha256=self.codex_config_digest.removeprefix("sha256:"),
        )

    def workspace_for_recovery(self) -> Path:
        """Return the private workspace only for an authorized fresh-session draft recovery."""

        if self.continuation_kind != "workspace_recovery":
            raise ContinuationStoreError("session records cannot be used as workspace recovery")
        return Path(self.workspace)

    @staticmethod
    def _normalize_digest(value: str) -> ContentHash:
        return value if value.startswith("sha256:") else f"sha256:{value}"


class SemanticRepairSeedRecord(V2Contract):
    """Private parsed-candidate seed for one fresh semantic repair turn.

    Unlike :class:`NodeContinuationRecord`, this record deliberately carries no
    provider thread, workspace, or SDK configuration. It lets a stateless
    structured model receive the last *parsed* candidate as data only after a
    Scheduler-authorized local correction, without pretending that Direct LLM
    calls have same-session continuation semantics.
    """

    seed_id: Identifier
    work_id: Identifier
    attempt_id: Identifier
    model: NonEmptyStr
    profile_digest: ContentHash
    output_schema_digest: ContentHash
    definition_digest: ContentHash
    proposal_policy_digest: ContentHash
    input_fingerprint: ContentHash
    previous_candidate: JsonValue
    candidate_commitment: ContentHash
    allowed_mutation_roots: tuple[NonEmptyStr, ...] = ()
    source_report_ref: ArtifactRef
    source_evaluation_ref: ArtifactRef
    repair_action_ref: ArtifactRef
    previous_execution_ref: ArtifactRef
    record_commitment: ContentHash
    created_at: AwareDatetime

    @model_validator(mode="after")
    def validate_private_binding(self) -> SemanticRepairSeedRecord:
        if len(set(self.allowed_mutation_roots)) != len(self.allowed_mutation_roots):
            raise ValueError("semantic repair seed mutation roots must be unique")
        candidate_bytes = canonical_json_bytes(self.previous_candidate)
        if len(candidate_bytes) > _MAX_PRIVATE_CANDIDATE_BYTES:
            raise ValueError("private semantic repair candidate exceeds 4 MiB")
        if self.candidate_commitment != sha256_digest(candidate_bytes):
            raise ValueError("semantic repair candidate commitment mismatch")
        expected_record = self.compute_record_commitment(
            work_id=self.work_id,
            attempt_id=self.attempt_id,
            model=self.model,
            profile_digest=self.profile_digest,
            output_schema_digest=self.output_schema_digest,
            definition_digest=self.definition_digest,
            proposal_policy_digest=self.proposal_policy_digest,
            input_fingerprint=self.input_fingerprint,
            candidate_commitment=self.candidate_commitment,
            allowed_mutation_roots=self.allowed_mutation_roots,
            source_report_ref=self.source_report_ref,
            source_evaluation_ref=self.source_evaluation_ref,
            repair_action_ref=self.repair_action_ref,
            previous_execution_ref=self.previous_execution_ref,
        )
        if self.record_commitment != expected_record:
            raise ValueError("semantic repair seed record commitment mismatch")
        if self.seed_id != self.seed_id_for(expected_record):
            raise ValueError("semantic repair seed id is not derived from its record commitment")
        expected_types = (
            (self.source_report_ref.artifact_type, "control.validation_report"),
            (self.source_evaluation_ref.artifact_type, "control.feedback_evaluation"),
            (self.repair_action_ref.artifact_type, "control.repair_action"),
            (self.previous_execution_ref.artifact_type, "control.proposal_execution"),
        )
        if any(actual != expected for actual, expected in expected_types):
            raise ValueError("semantic repair seed authority ref has the wrong Artifact type")
        return self

    @staticmethod
    def compute_record_commitment(
        *,
        work_id: str,
        attempt_id: str,
        model: str,
        profile_digest: str,
        output_schema_digest: str,
        definition_digest: str,
        proposal_policy_digest: str,
        input_fingerprint: str,
        candidate_commitment: str,
        allowed_mutation_roots: tuple[str, ...],
        source_report_ref: ArtifactRef,
        source_evaluation_ref: ArtifactRef,
        repair_action_ref: ArtifactRef,
        previous_execution_ref: ArtifactRef,
    ) -> ContentHash:
        return sha256_digest(
            canonical_json_bytes(
                {
                    "work_id": work_id,
                    "attempt_id": attempt_id,
                    "model": model,
                    "profile_digest": profile_digest,
                    "output_schema_digest": output_schema_digest,
                    "definition_digest": definition_digest,
                    "proposal_policy_digest": proposal_policy_digest,
                    "input_fingerprint": input_fingerprint,
                    "candidate_commitment": candidate_commitment,
                    "allowed_mutation_roots": allowed_mutation_roots,
                    "source_report_ref": source_report_ref.model_dump(mode="json"),
                    "source_evaluation_ref": source_evaluation_ref.model_dump(mode="json"),
                    "repair_action_ref": repair_action_ref.model_dump(mode="json"),
                    "previous_execution_ref": previous_execution_ref.model_dump(mode="json"),
                }
            )
        )

    @staticmethod
    def seed_id_for(record_commitment: str) -> Identifier:
        return f"semantic-repair-seed:{record_commitment.removeprefix('sha256:')[:24]}"

    @classmethod
    def capture(
        cls,
        *,
        work_id: Identifier,
        attempt_id: Identifier,
        model: str,
        profile_digest: ContentHash,
        output_schema_digest: ContentHash,
        definition_digest: ContentHash,
        proposal_policy_digest: ContentHash,
        input_fingerprint: ContentHash,
        previous_candidate: JsonValue,
        allowed_mutation_roots: tuple[NonEmptyStr, ...],
        source_report_ref: ArtifactRef,
        source_evaluation_ref: ArtifactRef,
        repair_action_ref: ArtifactRef,
        previous_execution_ref: ArtifactRef,
    ) -> SemanticRepairSeedRecord:
        candidate_commitment = sha256_digest(canonical_json_bytes(previous_candidate))
        normalized_profile = cls._normalize_digest(profile_digest)
        record_commitment = cls.compute_record_commitment(
            work_id=work_id,
            attempt_id=attempt_id,
            model=model,
            profile_digest=normalized_profile,
            output_schema_digest=output_schema_digest,
            definition_digest=definition_digest,
            proposal_policy_digest=proposal_policy_digest,
            input_fingerprint=input_fingerprint,
            candidate_commitment=candidate_commitment,
            allowed_mutation_roots=allowed_mutation_roots,
            source_report_ref=source_report_ref,
            source_evaluation_ref=source_evaluation_ref,
            repair_action_ref=repair_action_ref,
            previous_execution_ref=previous_execution_ref,
        )
        return cls(
            seed_id=cls.seed_id_for(record_commitment),
            work_id=work_id,
            attempt_id=attempt_id,
            model=model,
            profile_digest=normalized_profile,
            output_schema_digest=output_schema_digest,
            definition_digest=definition_digest,
            proposal_policy_digest=proposal_policy_digest,
            input_fingerprint=input_fingerprint,
            previous_candidate=previous_candidate,
            candidate_commitment=candidate_commitment,
            allowed_mutation_roots=allowed_mutation_roots,
            source_report_ref=source_report_ref,
            source_evaluation_ref=source_evaluation_ref,
            repair_action_ref=repair_action_ref,
            previous_execution_ref=previous_execution_ref,
            record_commitment=record_commitment,
            created_at=datetime.now(UTC),
        )

    @staticmethod
    def _normalize_digest(value: str) -> ContentHash:
        return value if value.startswith("sha256:") else f"sha256:{value}"


class DiagnosticSemanticRepairSeedRecord(V2Contract):
    """Private parsed candidate held between a diagnostic failure and opt-in repair.

    A normal Scheduler authorizes a local correction while the leaf still owns
    the parsed candidate, so :class:`SemanticRepairSeedRecord` can bind all
    authority facts in one transaction.  A ``test-descendant-node`` clone
    deliberately settles its first physical attempt before a user explicitly
    asks to exercise the repair path.  This record retains only that parsed
    JSON plus immutable source bindings in the diagnostic-private store.  It
    is not an Artifact, scene field, telemetry payload, or runtime-Agent input
    until a later exact ``RepairAction`` promotes it into a normal seed.
    """

    pending_id: Identifier
    work_id: Identifier
    attempt_id: Identifier
    model: NonEmptyStr
    profile_digest: ContentHash
    output_schema_digest: ContentHash
    definition_digest: ContentHash
    proposal_policy_digest: ContentHash
    input_fingerprint: ContentHash
    previous_candidate: JsonValue
    candidate_commitment: ContentHash
    source_output_commitment: ContentHash
    previous_execution_ref: ArtifactRef
    record_commitment: ContentHash
    created_at: AwareDatetime

    @model_validator(mode="after")
    def validate_private_binding(self) -> DiagnosticSemanticRepairSeedRecord:
        candidate_bytes = canonical_json_bytes(self.previous_candidate)
        if len(candidate_bytes) > _MAX_PRIVATE_CANDIDATE_BYTES:
            raise ValueError("private diagnostic semantic repair candidate exceeds 4 MiB")
        if self.candidate_commitment != sha256_digest(candidate_bytes):
            raise ValueError("diagnostic semantic repair candidate commitment mismatch")
        if self.previous_execution_ref.artifact_type != "control.proposal_execution":
            raise ValueError("diagnostic semantic repair source must be a proposal execution")
        expected_record = self.compute_record_commitment(
            work_id=self.work_id,
            attempt_id=self.attempt_id,
            model=self.model,
            profile_digest=self.profile_digest,
            output_schema_digest=self.output_schema_digest,
            definition_digest=self.definition_digest,
            proposal_policy_digest=self.proposal_policy_digest,
            input_fingerprint=self.input_fingerprint,
            candidate_commitment=self.candidate_commitment,
            source_output_commitment=self.source_output_commitment,
            previous_execution_ref=self.previous_execution_ref,
        )
        if self.record_commitment != expected_record:
            raise ValueError("diagnostic semantic repair record commitment mismatch")
        if self.pending_id != self.pending_id_for(expected_record):
            raise ValueError("diagnostic semantic repair id is not derived from its commitment")
        return self

    @staticmethod
    def compute_record_commitment(
        *,
        work_id: str,
        attempt_id: str,
        model: str,
        profile_digest: str,
        output_schema_digest: str,
        definition_digest: str,
        proposal_policy_digest: str,
        input_fingerprint: str,
        candidate_commitment: str,
        source_output_commitment: str,
        previous_execution_ref: ArtifactRef,
    ) -> ContentHash:
        return sha256_digest(
            canonical_json_bytes(
                {
                    "work_id": work_id,
                    "attempt_id": attempt_id,
                    "model": model,
                    "profile_digest": profile_digest,
                    "output_schema_digest": output_schema_digest,
                    "definition_digest": definition_digest,
                    "proposal_policy_digest": proposal_policy_digest,
                    "input_fingerprint": input_fingerprint,
                    "candidate_commitment": candidate_commitment,
                    "source_output_commitment": source_output_commitment,
                    "previous_execution_ref": previous_execution_ref.model_dump(mode="json"),
                }
            )
        )

    @staticmethod
    def pending_id_for(record_commitment: str) -> Identifier:
        return (
            f"diagnostic-semantic-repair-pending:{record_commitment.removeprefix('sha256:')[:24]}"
        )

    @classmethod
    def capture(
        cls,
        *,
        work_id: Identifier,
        attempt_id: Identifier,
        model: str,
        profile_digest: ContentHash,
        output_schema_digest: ContentHash,
        definition_digest: ContentHash,
        proposal_policy_digest: ContentHash,
        input_fingerprint: ContentHash,
        previous_candidate: JsonValue,
        source_output_commitment: ContentHash,
        previous_execution_ref: ArtifactRef,
    ) -> DiagnosticSemanticRepairSeedRecord:
        candidate_commitment = sha256_digest(canonical_json_bytes(previous_candidate))
        normalized_profile = SemanticRepairSeedRecord._normalize_digest(profile_digest)
        record_commitment = cls.compute_record_commitment(
            work_id=work_id,
            attempt_id=attempt_id,
            model=model,
            profile_digest=normalized_profile,
            output_schema_digest=output_schema_digest,
            definition_digest=definition_digest,
            proposal_policy_digest=proposal_policy_digest,
            input_fingerprint=input_fingerprint,
            candidate_commitment=candidate_commitment,
            source_output_commitment=source_output_commitment,
            previous_execution_ref=previous_execution_ref,
        )
        return cls(
            pending_id=cls.pending_id_for(record_commitment),
            work_id=work_id,
            attempt_id=attempt_id,
            model=model,
            profile_digest=normalized_profile,
            output_schema_digest=output_schema_digest,
            definition_digest=definition_digest,
            proposal_policy_digest=proposal_policy_digest,
            input_fingerprint=input_fingerprint,
            previous_candidate=previous_candidate,
            candidate_commitment=candidate_commitment,
            source_output_commitment=source_output_commitment,
            previous_execution_ref=previous_execution_ref,
            record_commitment=record_commitment,
            created_at=datetime.now(UTC),
        )


class DiagnosticWorkspaceRecoveryRecord(V2Contract):
    """Private Builder-draft offer retained by one settled diagnostic failure.

    A diagnostic node deliberately reaches a terminal ``WorkHead`` before an
    operator can explicitly authorize its one infrastructure retry.  A normal
    :class:`NodeContinuationRecord` cannot exist at that point because it must
    bind the later ``RepairAction``.  This pending record holds only the
    already-verified workspace identity and Agent provenance until that exact
    action exists.  It carries neither candidate bytes nor a Provider thread
    id, and is never an Artifact, scene field, telemetry payload, or runtime
    Agent input.
    """

    pending_id: Identifier
    work_id: Identifier
    attempt_id: Identifier
    lineage_id: Identifier
    workspace: NonEmptyStr
    profile_digest: ContentHash
    codex_config_digest: ContentHash
    model: NonEmptyStr
    output_schema_digest: ContentHash
    definition_digest: ContentHash
    proposal_policy_digest: ContentHash
    input_fingerprint: ContentHash
    previous_execution_ref: ArtifactRef
    record_commitment: ContentHash
    created_at: AwareDatetime

    @model_validator(mode="after")
    def validate_private_binding(self) -> DiagnosticWorkspaceRecoveryRecord:
        if not Path(self.workspace).is_absolute():
            raise ValueError("diagnostic workspace recovery must use an absolute workspace")
        if self.previous_execution_ref.artifact_type != "control.proposal_execution":
            raise ValueError("diagnostic workspace recovery source must be a proposal execution")
        expected = self.compute_record_commitment(
            work_id=self.work_id,
            attempt_id=self.attempt_id,
            lineage_id=self.lineage_id,
            workspace=self.workspace,
            profile_digest=self.profile_digest,
            codex_config_digest=self.codex_config_digest,
            model=self.model,
            output_schema_digest=self.output_schema_digest,
            definition_digest=self.definition_digest,
            proposal_policy_digest=self.proposal_policy_digest,
            input_fingerprint=self.input_fingerprint,
            previous_execution_ref=self.previous_execution_ref,
        )
        if self.record_commitment != expected:
            raise ValueError("diagnostic workspace recovery record commitment mismatch")
        if self.pending_id != self.pending_id_for(expected):
            raise ValueError("diagnostic workspace recovery id is not derived from commitment")
        return self

    @staticmethod
    def compute_record_commitment(
        *,
        work_id: str,
        attempt_id: str,
        lineage_id: str,
        workspace: str,
        profile_digest: str,
        codex_config_digest: str,
        model: str,
        output_schema_digest: str,
        definition_digest: str,
        proposal_policy_digest: str,
        input_fingerprint: str,
        previous_execution_ref: ArtifactRef,
    ) -> ContentHash:
        return sha256_digest(
            canonical_json_bytes(
                {
                    "work_id": work_id,
                    "attempt_id": attempt_id,
                    "lineage_id": lineage_id,
                    "workspace": workspace,
                    "profile_digest": profile_digest,
                    "codex_config_digest": codex_config_digest,
                    "model": model,
                    "output_schema_digest": output_schema_digest,
                    "definition_digest": definition_digest,
                    "proposal_policy_digest": proposal_policy_digest,
                    "input_fingerprint": input_fingerprint,
                    "previous_execution_ref": previous_execution_ref.model_dump(mode="json"),
                }
            )
        )

    @staticmethod
    def pending_id_for(record_commitment: str) -> Identifier:
        return (
            "diagnostic-workspace-recovery-pending:"
            f"{record_commitment.removeprefix('sha256:')[:24]}"
        )

    @classmethod
    def capture(
        cls,
        *,
        work_id: Identifier,
        attempt_id: Identifier,
        lineage_id: Identifier,
        workspace: Path,
        profile_digest: str,
        codex_config_digest: str,
        model: str,
        output_schema_digest: ContentHash,
        definition_digest: ContentHash,
        proposal_policy_digest: ContentHash,
        input_fingerprint: ContentHash,
        previous_execution_ref: ArtifactRef,
    ) -> DiagnosticWorkspaceRecoveryRecord:
        normalized_workspace = str(workspace.expanduser().resolve())
        normalized_profile = NodeContinuationRecord._normalize_digest(profile_digest)
        normalized_config = NodeContinuationRecord._normalize_digest(codex_config_digest)
        record_commitment = cls.compute_record_commitment(
            work_id=work_id,
            attempt_id=attempt_id,
            lineage_id=lineage_id,
            workspace=normalized_workspace,
            profile_digest=normalized_profile,
            codex_config_digest=normalized_config,
            model=model,
            output_schema_digest=output_schema_digest,
            definition_digest=definition_digest,
            proposal_policy_digest=proposal_policy_digest,
            input_fingerprint=input_fingerprint,
            previous_execution_ref=previous_execution_ref,
        )
        return cls(
            pending_id=cls.pending_id_for(record_commitment),
            work_id=work_id,
            attempt_id=attempt_id,
            lineage_id=lineage_id,
            workspace=normalized_workspace,
            profile_digest=normalized_profile,
            codex_config_digest=normalized_config,
            model=model,
            output_schema_digest=output_schema_digest,
            definition_digest=definition_digest,
            proposal_policy_digest=proposal_policy_digest,
            input_fingerprint=input_fingerprint,
            previous_execution_ref=previous_execution_ref,
            record_commitment=record_commitment,
            created_at=datetime.now(UTC),
        )


class SemanticRepairSeedStore:
    """Permission-restricted storage for stateless semantic repair seeds."""

    def __init__(self, root: str | os.PathLike[str]) -> None:
        requested = Path(root).expanduser()
        if requested.exists() and requested.is_symlink():
            raise ContinuationStoreError("semantic repair seed root cannot be a symlink")
        requested.mkdir(mode=0o700, parents=True, exist_ok=True)
        if requested.is_symlink() or not requested.is_dir():
            raise ContinuationStoreError("semantic repair seed root must be a real directory")
        os.chmod(requested, 0o700)
        self.root = requested.resolve(strict=True)
        self.pending_root = self._ensure_private_directory(self.root / "diagnostic-pending")

    def save(
        self,
        record: SemanticRepairSeedRecord,
        *,
        known_secret_values: tuple[str, ...] = (),
    ) -> SemanticRepairSeedRecord:
        record = SemanticRepairSeedRecord.model_validate(record.model_dump(mode="python"))
        content = record.stable_json_bytes()
        self._save_content(
            destination=self._path(record.seed_id),
            content=content,
            known_secret_values=known_secret_values,
            context="private semantic repair seed",
        )
        return record

    def save_diagnostic_pending(
        self,
        record: DiagnosticSemanticRepairSeedRecord,
        *,
        known_secret_values: tuple[str, ...] = (),
    ) -> DiagnosticSemanticRepairSeedRecord:
        """Persist a parsed diagnostic candidate before repair authority exists."""

        record = DiagnosticSemanticRepairSeedRecord.model_validate(record.model_dump(mode="python"))
        content = record.stable_json_bytes()
        self._save_content(
            destination=self._pending_path(record.pending_id),
            content=content,
            known_secret_values=known_secret_values,
            context="private diagnostic semantic repair seed",
        )
        return record

    def _save_content(
        self,
        *,
        destination: Path,
        content: bytes,
        known_secret_values: tuple[str, ...],
        context: str,
    ) -> None:
        assert_secret_free(
            content,
            known_secret_values=known_secret_values,
            context=context,
        )
        temporary = destination.parent / f".{uuid.uuid4().hex}.tmp"
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        try:
            with os.fdopen(descriptor, "wb", closefd=True) as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(temporary, destination, follow_symlinks=False)
            except FileExistsError:
                if destination.read_bytes() != content:
                    raise ContinuationStoreError(
                        "semantic repair seed id already binds other state"
                    ) from None
            directory = os.open(destination.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            temporary.unlink(missing_ok=True)

    def load_commitment(
        self,
        record_commitment: ContentHash,
    ) -> SemanticRepairSeedRecord | None:
        path = self._path(SemanticRepairSeedRecord.seed_id_for(record_commitment))
        try:
            record = self._read(path)
        except FileNotFoundError:
            return None
        if record.record_commitment != record_commitment:
            raise ContinuationStoreError(
                "semantic repair seed commitment does not match its record"
            )
        return record

    def find_repair_binding(
        self,
        *,
        work_id: Identifier,
        attempt_id: Identifier,
        definition_digest: ContentHash,
        proposal_policy_digest: ContentHash,
        input_fingerprint: ContentHash,
        source_report_ref: ArtifactRef,
        source_evaluation_ref: ArtifactRef,
        repair_action_ref: ArtifactRef,
        previous_execution_ref: ArtifactRef,
    ) -> SemanticRepairSeedRecord | None:
        """Recover one seed saved before its public WorkAttempt binding CAS."""

        matches: list[SemanticRepairSeedRecord] = []
        for path in sorted(self.root.glob("*.json")):
            if path.is_symlink() or not path.is_file():
                raise ContinuationStoreError("semantic repair seed store contains an unsafe entry")
            record = self._read(path)
            if (
                record.work_id == work_id
                and record.attempt_id == attempt_id
                and record.definition_digest == definition_digest
                and record.proposal_policy_digest == proposal_policy_digest
                and record.input_fingerprint == input_fingerprint
                and record.source_report_ref == source_report_ref
                and record.source_evaluation_ref == source_evaluation_ref
                and record.repair_action_ref == repair_action_ref
                and record.previous_execution_ref == previous_execution_ref
            ):
                matches.append(record)
        if len(matches) > 1:
            raise ContinuationStoreError("repair authority binds conflicting semantic repair seeds")
        return matches[0] if matches else None

    def find_diagnostic_pending(
        self,
        *,
        work_id: Identifier,
        attempt_id: Identifier,
        definition_digest: ContentHash,
        proposal_policy_digest: ContentHash,
        input_fingerprint: ContentHash,
        previous_execution_ref: ArtifactRef,
    ) -> DiagnosticSemanticRepairSeedRecord | None:
        """Return the one private candidate captured by an exact diagnostic attempt."""

        matches: list[DiagnosticSemanticRepairSeedRecord] = []
        for path in sorted(self.pending_root.glob("*.json")):
            if path.is_symlink() or not path.is_file():
                raise ContinuationStoreError(
                    "diagnostic semantic repair store contains an unsafe entry"
                )
            record = self._read_pending(path)
            if (
                record.work_id == work_id
                and record.attempt_id == attempt_id
                and record.definition_digest == definition_digest
                and record.proposal_policy_digest == proposal_policy_digest
                and record.input_fingerprint == input_fingerprint
                and record.previous_execution_ref == previous_execution_ref
            ):
                matches.append(record)
        if len(matches) > 1:
            raise ContinuationStoreError(
                "diagnostic attempt binds conflicting semantic repair candidates"
            )
        return matches[0] if matches else None

    def _read(self, path: Path) -> SemanticRepairSeedRecord:
        flags = os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(path, flags)
        except OSError as exc:
            if isinstance(exc, FileNotFoundError):
                raise
            raise ContinuationStoreError("cannot safely read semantic repair seed") from exc
        with os.fdopen(descriptor, "rb", closefd=True) as stream:
            raw = stream.read()
        try:
            return SemanticRepairSeedRecord.model_validate_json(raw)
        except Exception as exc:
            raise ContinuationStoreError("invalid private semantic repair seed") from exc

    def _read_pending(self, path: Path) -> DiagnosticSemanticRepairSeedRecord:
        flags = os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(path, flags)
        except OSError as exc:
            if isinstance(exc, FileNotFoundError):
                raise
            raise ContinuationStoreError(
                "cannot safely read diagnostic semantic repair seed"
            ) from exc
        with os.fdopen(descriptor, "rb", closefd=True) as stream:
            raw = stream.read()
        try:
            return DiagnosticSemanticRepairSeedRecord.model_validate_json(raw)
        except Exception as exc:
            raise ContinuationStoreError("invalid diagnostic semantic repair seed") from exc

    def _path(self, seed_id: str) -> Path:
        key = hashlib.sha256(seed_id.encode("utf-8")).hexdigest()
        return self.root / f"{key}.json"

    def _pending_path(self, pending_id: str) -> Path:
        key = hashlib.sha256(pending_id.encode("utf-8")).hexdigest()
        return self.pending_root / f"{key}.json"

    @staticmethod
    def _ensure_private_directory(path: Path) -> Path:
        if path.exists() and path.is_symlink():
            raise ContinuationStoreError("diagnostic semantic repair root cannot be a symlink")
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
        if path.is_symlink() or not path.is_dir():
            raise ContinuationStoreError("diagnostic semantic repair root must be a real directory")
        os.chmod(path, 0o700)
        return path.resolve(strict=True)


class DiagnosticWorkspaceRecoveryStore:
    """Permission-restricted pending private Builder workspace offers.

    This is intentionally distinct from both opaque Provider continuation
    records and parsed semantic-repair seeds.  It exists only in a marked
    diagnostic state root between a closed transient terminal and an explicit
    same-node retry authorization.
    """

    def __init__(self, root: str | os.PathLike[str]) -> None:
        requested = Path(root).expanduser()
        if requested.exists() and requested.is_symlink():
            raise ContinuationStoreError("diagnostic workspace recovery root cannot be a symlink")
        requested.mkdir(mode=0o700, parents=True, exist_ok=True)
        if requested.is_symlink() or not requested.is_dir():
            raise ContinuationStoreError(
                "diagnostic workspace recovery root must be a real directory"
            )
        os.chmod(requested, 0o700)
        self.root = requested.resolve(strict=True)

    def save(
        self,
        record: DiagnosticWorkspaceRecoveryRecord,
        *,
        known_secret_values: tuple[str, ...] = (),
    ) -> DiagnosticWorkspaceRecoveryRecord:
        record = DiagnosticWorkspaceRecoveryRecord.model_validate(record.model_dump(mode="python"))
        content = record.stable_json_bytes()
        assert_secret_free(
            content,
            known_secret_values=known_secret_values,
            context="private diagnostic workspace recovery",
        )
        destination = self._path(record.pending_id)
        temporary = self.root / f".{uuid.uuid4().hex}.tmp"
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        try:
            with os.fdopen(descriptor, "wb", closefd=True) as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(temporary, destination, follow_symlinks=False)
            except FileExistsError:
                if destination.read_bytes() != content:
                    raise ContinuationStoreError(
                        "diagnostic workspace recovery id already binds other state"
                    ) from None
            directory = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            temporary.unlink(missing_ok=True)
        return record

    def find_diagnostic_pending(
        self,
        *,
        work_id: Identifier,
        attempt_id: Identifier,
        definition_digest: ContentHash,
        proposal_policy_digest: ContentHash,
        input_fingerprint: ContentHash,
        previous_execution_ref: ArtifactRef,
    ) -> DiagnosticWorkspaceRecoveryRecord | None:
        """Return the one draft offer bound to an exact failed Agent execution."""

        matches: list[DiagnosticWorkspaceRecoveryRecord] = []
        for path in sorted(self.root.glob("*.json")):
            if path.is_symlink() or not path.is_file():
                raise ContinuationStoreError(
                    "diagnostic workspace recovery store contains an unsafe entry"
                )
            record = self._read(path)
            if (
                record.work_id == work_id
                and record.attempt_id == attempt_id
                and record.definition_digest == definition_digest
                and record.proposal_policy_digest == proposal_policy_digest
                and record.input_fingerprint == input_fingerprint
                and record.previous_execution_ref == previous_execution_ref
            ):
                matches.append(record)
        if len(matches) > 1:
            raise ContinuationStoreError(
                "diagnostic attempt binds conflicting workspace recovery offers"
            )
        return matches[0] if matches else None

    def _read(self, path: Path) -> DiagnosticWorkspaceRecoveryRecord:
        flags = os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(path, flags)
        except OSError as exc:
            if isinstance(exc, FileNotFoundError):
                raise
            raise ContinuationStoreError(
                "cannot safely read diagnostic workspace recovery"
            ) from exc
        with os.fdopen(descriptor, "rb", closefd=True) as stream:
            raw = stream.read()
        try:
            return DiagnosticWorkspaceRecoveryRecord.model_validate_json(raw)
        except Exception as exc:
            raise ContinuationStoreError("invalid diagnostic workspace recovery") from exc

    def _path(self, pending_id: str) -> Path:
        key = hashlib.sha256(pending_id.encode("utf-8")).hexdigest()
        return self.root / f"{key}.json"


class NodeContinuationStore:
    """Permission-restricted immutable store for opaque continuation records."""

    def __init__(self, root: str | os.PathLike[str]) -> None:
        requested = Path(root).expanduser()
        if requested.exists() and requested.is_symlink():
            raise ContinuationStoreError("continuation root cannot be a symlink")
        requested.mkdir(mode=0o700, parents=True, exist_ok=True)
        if requested.is_symlink() or not requested.is_dir():
            raise ContinuationStoreError("continuation root must be a real directory")
        os.chmod(requested, 0o700)
        self.root = requested.resolve(strict=True)

    def save(
        self,
        record: NodeContinuationRecord,
        *,
        known_secret_values: tuple[str, ...] = (),
    ) -> NodeContinuationRecord:
        record = NodeContinuationRecord.model_validate(record.model_dump(mode="python"))
        content = record.stable_json_bytes()
        assert_secret_free(
            content,
            known_secret_values=known_secret_values,
            context="private continuation state",
        )
        destination = self._path(record.continuation_id)
        temporary = self.root / f".{uuid.uuid4().hex}.tmp"
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        try:
            with os.fdopen(descriptor, "wb", closefd=True) as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(temporary, destination, follow_symlinks=False)
            except FileExistsError:
                if destination.read_bytes() != content:
                    raise ContinuationStoreError(
                        "continuation id already binds other state"
                    ) from None
            directory = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            temporary.unlink(missing_ok=True)
        return record

    def load_exact(
        self,
        *,
        expected: NodeContinuationRecord,
        workspace_root: Path,
    ) -> NodeContinuationRecord | None:
        expected = NodeContinuationRecord.model_validate(expected.model_dump(mode="python"))
        path = self._path(expected.continuation_id)
        flags = os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(path, flags)
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise ContinuationStoreError("cannot safely read continuation state") from exc
        with os.fdopen(descriptor, "rb", closefd=True) as stream:
            raw = stream.read()
        try:
            record = NodeContinuationRecord.model_validate_json(raw)
        except Exception as exc:
            raise ContinuationStoreError("invalid private continuation state") from exc
        if record != expected:
            raise ContinuationStoreError("continuation state does not match exact authority")
        root = workspace_root.expanduser().resolve(strict=True)
        workspace = Path(record.workspace)
        try:
            resolved = workspace.resolve(strict=True)
            resolved.relative_to(root)
        except (FileNotFoundError, ValueError, OSError) as exc:
            raise ContinuationStoreError(
                "continuation workspace is outside its authorized root"
            ) from exc
        if workspace.is_symlink() or not resolved.is_dir():
            raise ContinuationStoreError("continuation workspace is not a safe directory")
        return record

    def load_commitment(
        self,
        record_commitment: ContentHash,
        *,
        workspace_root: Path,
    ) -> NodeContinuationRecord | None:
        """Load the immutable record named by a public WorkAttempt commitment."""

        continuation_id = NodeContinuationRecord.continuation_id_for(record_commitment)
        path = self._path(continuation_id)
        flags = os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(path, flags)
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise ContinuationStoreError("cannot safely read continuation state") from exc
        with os.fdopen(descriptor, "rb", closefd=True) as stream:
            raw = stream.read()
        try:
            record = NodeContinuationRecord.model_validate_json(raw)
        except Exception as exc:
            raise ContinuationStoreError("invalid private continuation state") from exc
        if record.record_commitment != record_commitment:
            raise ContinuationStoreError("continuation commitment does not match its record")
        root = workspace_root.expanduser().resolve(strict=True)
        workspace = Path(record.workspace)
        try:
            resolved = workspace.resolve(strict=True)
            resolved.relative_to(root)
        except (FileNotFoundError, ValueError, OSError) as exc:
            raise ContinuationStoreError(
                "continuation workspace is outside its authorized root"
            ) from exc
        if workspace.is_symlink() or not resolved.is_dir():
            raise ContinuationStoreError("continuation workspace is not a safe directory")
        return record

    def find_repair_binding(
        self,
        *,
        work_id: Identifier,
        attempt_id: Identifier,
        definition_digest: ContentHash,
        proposal_policy_digest: ContentHash,
        input_fingerprint: ContentHash,
        source_report_ref: ArtifactRef,
        source_evaluation_ref: ArtifactRef,
        repair_action_ref: ArtifactRef,
        previous_execution_ref: ArtifactRef,
        workspace_root: Path,
    ) -> NodeContinuationRecord | None:
        """Recover a record saved before its public head binding CAS."""

        matches: list[NodeContinuationRecord] = []
        for path in sorted(self.root.glob("*.json")):
            if path.is_symlink() or not path.is_file():
                raise ContinuationStoreError("continuation store contains an unsafe entry")
            flags = os.O_RDONLY | os.O_CLOEXEC | getattr(os, "O_NOFOLLOW", 0)
            try:
                descriptor = os.open(path, flags)
            except OSError as exc:
                raise ContinuationStoreError("cannot safely read continuation state") from exc
            with os.fdopen(descriptor, "rb", closefd=True) as stream:
                raw = stream.read()
            try:
                record = NodeContinuationRecord.model_validate_json(raw)
            except Exception as exc:
                raise ContinuationStoreError("invalid private continuation state") from exc
            if (
                record.work_id == work_id
                and record.attempt_id == attempt_id
                and record.definition_digest == definition_digest
                and record.proposal_policy_digest == proposal_policy_digest
                and record.input_fingerprint == input_fingerprint
                and record.source_report_ref == source_report_ref
                and record.source_evaluation_ref == source_evaluation_ref
                and record.repair_action_ref == repair_action_ref
                and record.previous_execution_ref == previous_execution_ref
            ):
                matches.append(record)
        if len(matches) > 1:
            raise ContinuationStoreError("repair authority binds conflicting continuation records")
        if not matches:
            return None
        record = matches[0]
        return self.load_exact(expected=record, workspace_root=workspace_root)

    def _path(self, continuation_id: str) -> Path:
        key = hashlib.sha256(continuation_id.encode("utf-8")).hexdigest()
        return self.root / f"{key}.json"


__all__ = [
    "ContinuationStoreError",
    "DiagnosticSemanticRepairSeedRecord",
    "DiagnosticWorkspaceRecoveryRecord",
    "DiagnosticWorkspaceRecoveryStore",
    "NodeContinuationRecord",
    "NodeContinuationStore",
    "SemanticRepairSeedRecord",
    "SemanticRepairSeedStore",
]
