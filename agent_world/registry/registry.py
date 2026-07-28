"""Immutable envpkg v3 publication and Registry projections."""

from __future__ import annotations

import fcntl
import hashlib
import math
import os
import re
import shutil
import stat
import unicodedata
import uuid
from collections.abc import Iterable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Literal

from agent_world.artifact_store import ArtifactReadView, ArtifactStore
from agent_world.contracts import (
    FRAMEWORK_PACKAGE_LAYOUT,
    ArtifactRef,
    CandidateManifest,
    EnvironmentDesign,
    EnvironmentJob,
    EnvironmentPackageManifest,
    EnvironmentSuiteSnapshot,
    FrameworkPackagePayload,
    GateResult,
    GenerationContext,
    ImplementationLineage,
    IntegrationReport,
    JudgeReport,
    PackageFile,
    ReachabilityPublicEvidence,
    ReleaseProfile,
    SuitePackageSelection,
    SuiteSelectionRequest,
    canonical_json_bytes,
    sha256_digest,
)
from agent_world.control import (
    ClaimVector,
    JobRunSnapshot,
    ReleaseDossier,
    ResearchCheckpointReuseEvidence,
    TelemetryReleaseSummary,
    WorkAttempt,
    WorkCommit,
    WorkControlStore,
    WorkGraphEpoch,
    WorkGraphManifest,
    WorkGraphNodeBinding,
    WorkReadinessSnapshot,
)

from .models import (
    EnvironmentPoolSnapshot,
    PackageCoordinate,
    PackageVersionReservation,
    PreparedRelease,
    PublicationDossier,
    RegistryEvent,
    RegistryIndex,
    ReleaseRecord,
    ReleaseStatus,
)
from .semantic_gate import (
    PackageSemanticError,
    SemanticParent,
    load_portable_package_contracts,
    validate_package_identity,
    validate_package_release_bindings,
)

MANIFEST_ARTIFACT_TYPE = "environment_package_manifest"
JUDGE_REPORT_ARTIFACT_TYPE = "judge_report"
INTEGRATION_REPORT_ARTIFACT_TYPE = "judge.integration_report"
RELEASE_DOSSIER_ARTIFACT_TYPE = "release.dossier"
# Kept only so the retired, unreachable audit reader can deserialize historic
# bad-case artifacts until the legacy method is deleted with its fixtures.
CLAIM_VECTOR_ARTIFACT_TYPE = "release.claim_vector"
TELEMETRY_SUMMARY_ARTIFACT_TYPE = "release.telemetry_summary"
_MANIFEST_NAME = "manifest.json"
_DOSSIER_NAME = "release-dossier.json"
_PACKAGE_COMPONENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:+-]{0,159}$")
_IDENTIFIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$")
_FORBIDDEN_COMPONENTS = frozenset(
    {
        ".git",
        ".venv",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        "__pycache__",
        "node_modules",
    }
)
_FORBIDDEN_NAME_TOKENS = frozenset(
    {
        "auth",
        "credential",
        "credentials",
        "expected",
        "oracle",
        "sealed",
        "secret",
        "secrets",
        "transcript",
        "transcripts",
    }
)
_CONTENT_PATTERNS: tuple[tuple[str, re.Pattern[bytes]], ...] = (
    ("private-key", re.compile(rb"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----", re.IGNORECASE)),
    ("aws-access-key", re.compile(rb"\bAKIA[0-9A-Z]{16}\b")),
    ("openai-key", re.compile(rb"\bsk-[A-Za-z0-9_-]{20,}\b")),
    ("github-token", re.compile(rb"\bgh[pousr]_[A-Za-z0-9]{20,}\b")),
    ("jina-key", re.compile(rb"\bjina_[A-Za-z0-9_-]{20,}\b", re.IGNORECASE)),
    (
        "private-evaluation-data",
        re.compile(
            rb"[\"'](?:expected_answer|expected_state|case_label|sealed_cases|"
            rb"agent_transcript|raw_prompt|raw_response)[\"']\s*:",
            re.IGNORECASE,
        ),
    ),
)
_CREDENTIAL_ASSIGNMENT = re.compile(
    rb"(?:api[_-]?key|access[_-]?token|client[_-]?secret|password)"
    rb"\s*[=:]\s*[\"']?([A-Za-z0-9_./+~=-]{16,})",
    re.IGNORECASE,
)
_BEARER_CREDENTIAL = re.compile(rb"\bbearer\s+([A-Za-z0-9._~+/=-]{16,})", re.IGNORECASE)
_CREDENTIAL_PLACEHOLDERS = (
    b"example",
    b"placeholder",
    b"replace",
    b"sample",
    b"test",
    b"your",
    b"xxxxx",
)
_DEFAULT_RESERVATION_TTL_SECONDS = 2 * 60 * 60
_MAX_RESERVATION_TTL_SECONDS = 7 * 24 * 60 * 60
_FRAMEWORK_PRODUCERS = frozenset({"framework"})
_JUDGE_PRODUCERS = frozenset({"environment-judge"})
_REACHABILITY_EVIDENCE_ARTIFACT_TYPE = "judge.reachability_public_evidence"
_REQUIRED_INTEGRATION_GATES = frozenset(
    {
        "schema",
        "supply_chain",
        "static_assurance",
        "public_self_check",
        "runtime_protocol",
        "task_materialization",
        "clean_deployment",
    }
)
_REQUIRED_RELEASE_CLAIMS = frozenset(
    {
        "design.valid",
        "build.valid",
        "runtime.executable",
        "integration.ready",
        "verifier.valid",
        "release_judge.valid",
        "observability.release_ready",
    }
)


@dataclass(frozen=True, slots=True)
class ResolvedEnvironmentPackage:
    """A verified local path to one currently released Suite member."""

    selection: SuitePackageSelection
    record: ReleaseRecord
    manifest: EnvironmentPackageManifest
    package_root: Path


class RegistryError(RuntimeError):
    """Base class for Registry publication failures."""


class ReleaseRejectedError(RegistryError):
    pass


class ReleaseConflictError(RegistryError):
    pass


class ReleaseNotFoundError(RegistryError):
    pass


class RegistryIntegrityError(RegistryError):
    pass


class UnsafePackageError(ReleaseRejectedError):
    pass


class PreparedReleaseNotFoundError(RegistryError):
    pass


class ReservationConflictError(RegistryError):
    pass


class ReservationExpiredError(RegistryError):
    pass


class ReservationNotFoundError(RegistryError):
    pass


class ParentNotEligibleError(RegistryError):
    pass


class _ContentScanner:
    def __init__(self, canaries: tuple[bytes, ...], path: str) -> None:
        self._canaries = canaries
        self._path = path
        self._tail = b""
        self._overlap = max((len(item) for item in canaries), default=0)
        self._overlap = max(self._overlap, 4096) - 1

    def update(self, chunk: bytes) -> None:
        window = self._tail + chunk
        for canary in self._canaries:
            if canary in window:
                raise UnsafePackageError(f"known secret canary detected in {self._path}")
        for label, pattern in _CONTENT_PATTERNS:
            if pattern.search(window):
                raise UnsafePackageError(f"{label} material detected in {self._path}")
        for pattern, label in (
            (_CREDENTIAL_ASSIGNMENT, "credential-assignment"),
            (_BEARER_CREDENTIAL, "bearer-authorization"),
        ):
            for match in pattern.finditer(window):
                candidate = match.group(1).lower()
                if _is_probable_credential(candidate):
                    raise UnsafePackageError(f"{label} material detected in {self._path}")
        self._tail = window[-self._overlap :]


def _is_probable_credential(candidate: bytes) -> bool:
    return (
        not any(part in candidate for part in _CREDENTIAL_PLACEHOLDERS)
        and any(48 <= value <= 57 for value in candidate)
        and any(65 <= value <= 90 or 97 <= value <= 122 for value in candidate)
    )


class EnvironmentRegistry:
    """The sole package/version/status truth for released envpkg v3 artifacts."""

    def __init__(
        self,
        root: str | os.PathLike[str],
        artifact_store: ArtifactStore,
        *,
        work_store: WorkControlStore | None = None,
        known_secret_canaries: Sequence[str | bytes] = (),
        reservation_ttl_seconds: float = _DEFAULT_RESERVATION_TTL_SECONDS,
    ) -> None:
        requested = Path(root).expanduser()
        if requested.exists() and requested.is_symlink():
            raise RegistryIntegrityError("Registry root cannot be a symlink")
        requested.mkdir(parents=True, exist_ok=True)
        if requested.is_symlink() or not requested.is_dir():
            raise RegistryIntegrityError("Registry root must be a real directory")
        self._root = requested.resolve(strict=True)
        self._artifact_store = artifact_store
        # The Registry does not recreate readiness from a dossier's self-report.
        # It reads the same durable Work heads that the Scheduler uses.  The
        # conventional state-root location keeps standalone deployments usable;
        # Controller construction passes its exact store explicitly.
        self._work_store = work_store or WorkControlStore(self._root.parent / "work-control")
        self._framework_producers = _FRAMEWORK_PRODUCERS
        self._judge_producers = _JUDGE_PRODUCERS
        self._reservation_ttl_seconds = self._validate_reservation_ttl(reservation_ttl_seconds)
        canaries: set[bytes] = set()
        for raw in known_secret_canaries:
            value = raw.encode("utf-8") if isinstance(raw, str) else raw
            if not isinstance(value, bytes) or len(value) < 4 or len(value) > 8192:
                raise ValueError("secret canaries must contain 4..8192 bytes")
            canaries.add(value)
        self._secret_canaries = tuple(sorted(canaries))
        for name in (
            "packages",
            ".staging",
            "prepared",
            "snapshots",
            "suite-snapshots",
            ".tmp",
        ):
            self._ensure_directory(self._safe_path(name))
        with self._registry_lock(exclusive=True):
            if not self._index_path.exists():
                self._write_index(RegistryIndex())

    @property
    def root(self) -> Path:
        return self._root

    def reserve_package_version(
        self,
        package_id: str,
        version: str,
        owner_ref: ArtifactRef,
        *,
        ttl_seconds: float | None = None,
        framework_actor: str = "framework",
    ) -> PackageVersionReservation:
        """Exclusively reserve one coordinate for an exact framework-owned job revision.

        An unexpired retry by the same owner returns the same record.  A retry after
        that owner's successful publication returns the consumed record.  Expired or
        cancelled reservations are terminal; the owner may then acquire a new token.
        """

        self._validate_package_component(package_id, "package_id")
        self._validate_package_component(version, "version")
        self._validate_actor(framework_actor)
        self._require_framework_owner(owner_ref)
        ttl = self._validate_reservation_ttl(
            self._reservation_ttl_seconds if ttl_seconds is None else ttl_seconds
        )
        now = datetime.now(UTC)
        with self._registry_lock(exclusive=True):
            index = self._load_index()
            reservations, expired = self._expire_reservations(index.reservations, now)
            existing_release = self._find_record(index, package_id, version)
            if existing_release is not None:
                consumed = self._find_reservation(
                    reservations,
                    existing_release.reservation_id,
                )
                if consumed is not None and consumed.owner_ref == owner_ref:
                    self._persist_reservation_projection(index, reservations, expired)
                    return consumed
                self._persist_reservation_projection(index, reservations, expired)
                raise ReservationConflictError(
                    f"Registry coordinate is already published: {package_id}@{version}"
                )

            active = self._find_active_reservation(reservations, package_id, version)
            if active is not None:
                self._persist_reservation_projection(index, reservations, expired)
                if active.owner_ref == owner_ref:
                    return active
                raise ReservationConflictError(
                    f"Registry coordinate is reserved by another owner: {package_id}@{version}"
                )

            if self._existing_digest_directories(package_id, version):
                self._persist_reservation_projection(index, reservations, expired)
                raise ReservationConflictError(
                    "Registry coordinate has an unindexed publish tree; recover the original "
                    f"reservation before reusing {package_id}@{version}"
                )

            reservation = PackageVersionReservation(
                reservation_id=f"reservation_{uuid.uuid4().hex}",
                package_id=package_id,
                version=version,
                owner_ref=owner_ref,
                status="active",
                framework_actor=framework_actor,
                created_at=now,
                updated_at=now,
                expires_at=now + timedelta(seconds=ttl),
            )
            self._write_index(
                RegistryIndex(
                    revision=index.revision + 1,
                    releases=index.releases,
                    reservations=self._sorted_reservations((*reservations, reservation)),
                )
            )
            return reservation

    def inspect_reservation(self, reservation_id: str) -> PackageVersionReservation:
        """Return durable reservation state, materializing expiry if required."""

        self._validate_identifier(reservation_id, "reservation_id")
        now = datetime.now(UTC)
        with self._registry_lock(exclusive=True):
            index = self._load_index()
            reservations, expired = self._expire_reservations(index.reservations, now)
            reservation = self._find_reservation(reservations, reservation_id)
            if reservation is None:
                raise ReservationNotFoundError(f"Registry reservation not found: {reservation_id}")
            self._persist_reservation_projection(index, reservations, expired)
            return reservation

    def release_reservation(
        self,
        reservation_id: str,
        owner_ref: ArtifactRef,
        *,
        framework_actor: str = "framework",
    ) -> PackageVersionReservation:
        """Relinquish an active reservation; terminal retries are idempotent."""

        self._validate_identifier(reservation_id, "reservation_id")
        self._validate_actor(framework_actor)
        self._require_framework_owner(owner_ref)
        now = datetime.now(UTC)
        with self._registry_lock(exclusive=True):
            index = self._load_index()
            reservations, expired = self._expire_reservations(index.reservations, now)
            current = self._find_reservation(reservations, reservation_id)
            if current is None:
                raise ReservationNotFoundError(f"Registry reservation not found: {reservation_id}")
            if current.owner_ref != owner_ref:
                self._persist_reservation_projection(index, reservations, expired)
                raise ReservationConflictError("reservation belongs to a different owner")
            if current.status == "consumed":
                self._persist_reservation_projection(index, reservations, expired)
                raise ReservationConflictError("published reservation cannot be released")
            if current.status in {"cancelled", "expired"}:
                self._persist_reservation_projection(index, reservations, expired)
                return current
            cancelled = current.model_copy(
                update={
                    "status": "cancelled",
                    "updated_at": now,
                    "terminal_at": now,
                }
            )
            updated = tuple(
                cancelled if item.reservation_id == reservation_id else item
                for item in reservations
            )
            self._write_index(
                RegistryIndex(
                    revision=index.revision + 1,
                    releases=index.releases,
                    reservations=self._sorted_reservations(updated),
                )
            )
            return cancelled

    def prepare(
        self,
        *,
        candidate_workspace: str | os.PathLike[str],
        manifest_ref: ArtifactRef,
        judge_report_ref: ArtifactRef,
        release_profile: ReleaseProfile,
        reservation: PackageVersionReservation,
        framework_payloads: Sequence[FrameworkPackagePayload],
        framework_actor: str = "framework",
    ) -> PreparedRelease:
        """Build a staging tree bound to one still-active version reservation."""

        self._validate_actor(framework_actor)
        manifest, report, passed_gates = self._load_release_evidence(
            manifest_ref,
            judge_report_ref,
            release_profile,
            reservation_owner_ref=reservation.owner_ref,
        )
        self._validate_package_component(manifest.package_id, "package_id")
        self._validate_package_component(manifest.version, "version")
        self._validate_manifest_files(manifest.files)
        self._require_framework_owner(reservation.owner_ref)
        self._require_active_reservation(
            reservation,
            package_id=manifest.package_id,
            version=manifest.version,
        )
        workspace = self._candidate_root(candidate_workspace)

        package_digest = self._package_digest(manifest)
        coordinate = PackageCoordinate(
            package_id=manifest.package_id,
            version=manifest.version,
            package_digest=package_digest,
        )
        token = f"prep_{uuid.uuid4().hex}"
        staging = self._safe_path(".staging", token)
        staging.mkdir(mode=0o700)
        marker = self._prepared_path(token)
        try:
            self._copy_and_validate_payload(
                workspace,
                staging,
                manifest.files,
                framework_payloads=framework_payloads,
            )
            self._atomic_create(
                staging / _MANIFEST_NAME,
                manifest.stable_json_bytes(),
                mode=0o400,
            )
            self._verify_staging(staging, manifest, include_dossier=False)
            prepared = PreparedRelease(
                staging_token=token,
                staging_relpath=f".staging/{token}",
                coordinate=coordinate,
                reservation_id=reservation.reservation_id,
                reservation_owner_ref=reservation.owner_ref,
                manifest_ref=manifest_ref,
                judge_report_ref=judge_report_ref,
                integration_report_ref=manifest.integration_report_ref,
                release_dossier_ref=manifest.release_dossier_ref,
                telemetry_summary_ref=manifest.telemetry_summary_ref,
                release_profile=release_profile,
                passed_hard_gates=passed_gates,
                file_count=len(manifest.files),
                payload_size_bytes=sum(item.size_bytes for item in manifest.files),
                framework_actor=framework_actor,
                prepared_at=datetime.now(UTC),
            )
            # Recheck under the Registry lock after potentially expensive file scans.
            # Cancellation or expiry racing preparation must win before the marker exists.
            with self._registry_lock(exclusive=True):
                index = self._load_index()
                reservations, expired = self._expire_reservations(
                    index.reservations,
                    datetime.now(UTC),
                )
                current = self._find_reservation(reservations, reservation.reservation_id)
                self._persist_reservation_projection(index, reservations, expired)
                self._assert_active_reservation(
                    current,
                    reservation,
                    package_id=manifest.package_id,
                    version=manifest.version,
                )
                if current != reservation:
                    raise ReservationConflictError(
                        "supplied reservation no longer matches its durable state"
                    )
                self._validate_package_semantics(
                    staging,
                    manifest,
                    report=report,
                    index=index,
                    require_released_parents=True,
                    integrity_error=False,
                )
                self._atomic_create(marker, prepared.stable_json_bytes(), mode=0o400)
            return prepared
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            marker.unlink(missing_ok=True)
            raise

    def publish(self, prepared: PreparedRelease) -> ReleaseRecord:
        """Publish and consume the bound reservation in one RegistryIndex commit.

        Expiry prevents starting publication.  The sole exception is recovery of an
        exact final package tree already moved by an earlier publish attempt before
        its atomic index commit; no new owner can reserve that unindexed coordinate.
        """

        with self._registry_lock(exclusive=True):
            self._validate_actor(prepared.framework_actor)
            index = self._load_index()
            reservations, expired = self._expire_reservations(
                index.reservations,
                datetime.now(UTC),
            )
            reservation = self._find_reservation(reservations, prepared.reservation_id)
            if reservation is None:
                self._persist_reservation_projection(index, reservations, expired)
                raise ReservationNotFoundError(
                    f"Registry reservation not found: {prepared.reservation_id}"
                )
            if reservation.owner_ref != prepared.reservation_owner_ref:
                self._persist_reservation_projection(index, reservations, expired)
                raise ReservationConflictError("prepared release has the wrong reservation owner")

            existing = self._find_record(
                index,
                prepared.coordinate.package_id,
                prepared.coordinate.version,
            )
            if reservation.status == "consumed":
                self._persist_reservation_projection(index, reservations, expired)
                if not self._prepared_matches_release(prepared, reservation, existing):
                    raise ReservationConflictError(
                        "consumed reservation does not match this prepared release"
                    )
                assert existing is not None
                self._verify_release_record(existing)
                self._discard_prepared(prepared)
                return existing
            final_path = self._package_path(prepared.coordinate)
            recovering_unindexed_publish = reservation.status == "expired" and final_path.exists()
            if reservation.status == "expired" and not recovering_unindexed_publish:
                self._persist_reservation_projection(index, reservations, expired)
                raise ReservationExpiredError(
                    f"Registry reservation expired: {reservation.reservation_id}"
                )
            if reservation.status != "active" and not recovering_unindexed_publish:
                self._persist_reservation_projection(index, reservations, expired)
                raise ReservationConflictError(
                    f"Registry reservation is not active: {reservation.status}"
                )
            if (
                reservation.package_id != prepared.coordinate.package_id
                or reservation.version != prepared.coordinate.version
            ):
                self._persist_reservation_projection(index, reservations, expired)
                raise ReservationConflictError(
                    "prepared release coordinate does not match its reservation"
                )
            if existing is not None:
                self._persist_reservation_projection(index, reservations, expired)
                raise RegistryIntegrityError("published coordinate retained an active reservation")

            persisted = self._load_prepared(prepared.staging_token)
            if persisted != prepared:
                raise RegistryIntegrityError("prepared release does not match its durable marker")
            manifest, report, passed_gates = self._load_release_evidence(
                prepared.manifest_ref,
                prepared.judge_report_ref,
                prepared.release_profile,
                reservation_owner_ref=prepared.reservation_owner_ref,
            )
            if tuple(passed_gates) != prepared.passed_hard_gates:
                raise RegistryIntegrityError("prepared hard gates changed")
            if self._package_digest(manifest) != prepared.coordinate.package_digest:
                raise RegistryIntegrityError("prepared package digest changed")
            if (
                prepared.coordinate.package_id != manifest.package_id
                or prepared.coordinate.version != manifest.version
                or prepared.file_count != len(manifest.files)
                or prepared.payload_size_bytes != sum(item.size_bytes for item in manifest.files)
            ):
                raise RegistryIntegrityError("prepared release metadata does not match manifest")

            semantic_root = final_path if final_path.exists() else self._staging_path(prepared)
            self._validate_package_semantics(
                semantic_root,
                manifest,
                report=report,
                index=index,
                require_released_parents=True,
                integrity_error=True,
            )

            sibling_digests = self._existing_digest_directories(
                prepared.coordinate.package_id,
                prepared.coordinate.version,
            )
            if sibling_digests and final_path.name not in sibling_digests:
                self._discard_prepared(prepared)
                raise ReleaseConflictError(
                    f"unindexed content already exists for {manifest.package_id}@{manifest.version}"
                )

            if final_path.exists():
                record = self._recover_unindexed_release(
                    final_path,
                    manifest,
                    report,
                    prepared,
                )
                self._discard_prepared(prepared)
            else:
                staging = self._staging_path(prepared)
                dossier = self._load_or_create_staging_dossier(
                    staging,
                    manifest,
                    prepared,
                )
                dossier_bytes = dossier.stable_json_bytes()
                self._verify_staging(staging, manifest, include_dossier=True, dossier=dossier)
                self._freeze_tree(staging, manifest.files)
                self._ensure_directory(final_path.parent)
                if final_path.exists():
                    raise RegistryIntegrityError(
                        "package path appeared while Registry lock was held"
                    )
                os.rename(staging, final_path)
                os.chmod(final_path, 0o500, follow_symlinks=False)
                self._fsync_directory(final_path.parent)
                record = self._build_release_record(
                    manifest=manifest,
                    report=report,
                    prepared=prepared,
                    dossier_hash=sha256_digest(dossier_bytes),
                    published_at=dossier.published_at,
                )

            consumed_at = datetime.now(UTC)
            consumed = reservation.model_copy(
                update={
                    "status": "consumed",
                    "updated_at": consumed_at,
                    "terminal_at": consumed_at,
                    "manifest_ref": prepared.manifest_ref,
                    "package_digest": prepared.coordinate.package_digest,
                    "release_id": record.release_id,
                }
            )
            updated_reservations = tuple(
                consumed if item.reservation_id == consumed.reservation_id else item
                for item in reservations
            )
            updated = RegistryIndex(
                revision=index.revision + 1,
                releases=self._sorted_records((*index.releases, record)),
                reservations=self._sorted_reservations(updated_reservations),
            )
            self._write_index(updated)
            self._append_event(
                event_type="release_published",
                coordinate=record.coordinate,
                previous_status=None,
                new_status="released",
                actor=prepared.framework_actor,
            )
            self._prepared_path(prepared.staging_token).unlink(missing_ok=True)
            return record

    def inspect(
        self,
        package_id: str,
        version: str,
        *,
        package_digest: str | None = None,
    ) -> ReleaseRecord:
        """Return one exact release after rechecking its immutable package tree."""

        self._validate_package_component(package_id, "package_id")
        self._validate_package_component(version, "version")
        with self._registry_lock(exclusive=False):
            record = self._find_record(self._load_index(), package_id, version)
            if record is None:
                raise ReleaseNotFoundError(f"release not found: {package_id}@{version}")
            if package_digest is not None and record.coordinate.package_digest != package_digest:
                raise ReleaseNotFoundError(f"release digest not found: {package_id}@{version}")
            self._verify_release_record(record)
            return record

    def require_released_manifest(self, manifest_ref: ArtifactRef) -> ReleaseRecord:
        """Resolve one exact manifest only when its current Registry status is released."""

        if manifest_ref.artifact_type != MANIFEST_ARTIFACT_TYPE:
            raise ParentNotEligibleError(f"parent artifact_type must be {MANIFEST_ARTIFACT_TYPE}")
        self._artifact_store.get_revision(manifest_ref)
        with self._registry_lock(exclusive=False):
            matches = tuple(
                item for item in self._load_index().releases if item.manifest_ref == manifest_ref
            )
            if not matches:
                raise ReleaseNotFoundError(
                    f"released package manifest is not registered: {manifest_ref.artifact_id}"
                )
            if len(matches) != 1:
                raise RegistryIntegrityError("manifest ref resolves to multiple Registry releases")
            record = matches[0]
            self._verify_release_record(record)
            if record.status != "released":
                raise ParentNotEligibleError(
                    f"package manifest is not currently released: {record.status}"
                )
            return record

    def require_snapshot_parent(
        self,
        snapshot_id: str,
        manifest_ref: ArtifactRef,
    ) -> ReleaseRecord:
        """Require frozen released membership and current released eligibility."""

        snapshot = self.load_pool_snapshot(snapshot_id)
        frozen_matches = tuple(
            item for item in snapshot.releases if item.manifest_ref == manifest_ref
        )
        if not frozen_matches:
            raise ParentNotEligibleError(
                "parent manifest is not a member of the frozen Pool snapshot"
            )
        if len(frozen_matches) != 1:
            raise RegistryIntegrityError("snapshot contains duplicate manifest refs")
        frozen = frozen_matches[0]
        if frozen.status != "released":
            raise ParentNotEligibleError("parent was not released in the frozen Pool snapshot")
        current = self.require_released_manifest(manifest_ref)
        if (
            current.release_id != frozen.release_id
            or current.coordinate != frozen.coordinate
            or current.manifest_ref != frozen.manifest_ref
        ):
            raise RegistryIntegrityError("current release differs from frozen parent identity")
        return current

    def list(
        self,
        *,
        package_id: str | None = None,
        statuses: Iterable[ReleaseStatus] | None = None,
    ) -> tuple[ReleaseRecord, ...]:
        """List the Registry projection without mutating or reclassifying releases."""

        if package_id is not None:
            self._validate_package_component(package_id, "package_id")
        selected_statuses = frozenset(statuses) if statuses is not None else None
        if selected_statuses is not None and not selected_statuses <= {
            "released",
            "quarantined",
            "superseded",
        }:
            raise ValueError("unknown release status")
        with self._registry_lock(exclusive=False):
            records = (
                item
                for item in self._load_index().releases
                if (package_id is None or item.coordinate.package_id == package_id)
                and (selected_statuses is None or item.status in selected_statuses)
            )
            return self._sorted_records(records)

    def pool_snapshot(
        self,
        *,
        package_ids: Iterable[str] | None = None,
        statuses: Iterable[ReleaseStatus] = ("released",),
    ) -> EnvironmentPoolSnapshot:
        """Persist an immutable, exact Registry view for one Expansion campaign."""

        selected_ids = frozenset(package_ids) if package_ids is not None else None
        if selected_ids is not None:
            for package_id in selected_ids:
                self._validate_package_component(package_id, "package_id")
        selected_statuses = frozenset(statuses)
        if not selected_statuses <= {"released", "quarantined", "superseded"}:
            raise ValueError("unknown release status")
        with self._registry_lock(exclusive=True):
            index = self._load_index()
            records = self._sorted_records(
                item
                for item in index.releases
                if item.status in selected_statuses
                and (selected_ids is None or item.coordinate.package_id in selected_ids)
            )
            for record in records:
                self._verify_release_record(record)
            created_at = datetime.now(UTC)
            snapshot_id = self._snapshot_id(index.revision, created_at, records)
            snapshot = EnvironmentPoolSnapshot(
                snapshot_id=snapshot_id,
                registry_revision=index.revision,
                created_at=created_at,
                releases=records,
            )
            self._atomic_create(
                self._safe_path("snapshots", f"{snapshot_id}.json"),
                snapshot.stable_json_bytes(),
                mode=0o400,
            )
            return snapshot

    def load_pool_snapshot(self, snapshot_id: str) -> EnvironmentPoolSnapshot:
        self._validate_identifier(snapshot_id, "snapshot_id")
        path = self._safe_path("snapshots", f"{snapshot_id}.json")
        raw = self._read_file(path, f"pool snapshot not found: {snapshot_id}")
        try:
            snapshot = EnvironmentPoolSnapshot.model_validate_json(raw)
        except Exception as exc:
            raise RegistryIntegrityError(f"invalid pool snapshot: {snapshot_id}") from exc
        if snapshot.snapshot_id != snapshot_id:
            raise RegistryIntegrityError("pool snapshot identity mismatch")
        expected_id = self._snapshot_id(
            snapshot.registry_revision,
            snapshot.created_at,
            snapshot.releases,
        )
        if expected_id != snapshot_id:
            raise RegistryIntegrityError("pool snapshot content hash mismatch")
        for record in snapshot.releases:
            self._verify_release_record(record)
        return snapshot

    def create_suite_snapshot(
        self,
        selections: Sequence[SuiteSelectionRequest],
    ) -> EnvironmentSuiteSnapshot:
        """Atomically freeze exact, physically verified releases for consumption."""

        if not selections:
            raise ValueError("Suite snapshot requires at least one package selection")
        keys = [(item.package_id, item.version) for item in selections]
        if len(set(keys)) != len(keys):
            raise ValueError("Suite package selections must be unique")
        for selection in selections:
            self._validate_package_component(selection.package_id, "package_id")
            self._validate_package_component(selection.version, "version")

        with self._registry_lock(exclusive=True):
            index = self._load_index()
            packages: list[SuitePackageSelection] = []
            for selection in selections:
                record = self._find_record(index, selection.package_id, selection.version)
                if record is None:
                    raise ReleaseNotFoundError(
                        f"release not found: {selection.package_id}@{selection.version}"
                    )
                if record.status != "released":
                    raise ParentNotEligibleError(
                        "only currently released packages may enter a Suite snapshot"
                    )
                self._verify_release_record(record)
                manifest = self._artifact_store.get_json(
                    record.manifest_ref,
                    EnvironmentPackageManifest,
                )
                packages.append(
                    SuitePackageSelection(
                        package_id=selection.package_id,
                        version=selection.version,
                        weight=selection.weight,
                        curriculum_policy=selection.curriculum_policy,
                        package_digest=record.coordinate.package_digest,
                        manifest_hash=manifest.content_digest(),
                    )
                )
            snapshot = EnvironmentSuiteSnapshot.create(
                created_at=datetime.now(UTC),
                packages=tuple(packages),
            )
            self._atomic_create(
                self._suite_snapshot_path(snapshot.snapshot_id),
                snapshot.stable_json_bytes(),
                mode=0o400,
            )
            return snapshot

    def load_suite_snapshot(self, snapshot_id: str) -> EnvironmentSuiteSnapshot:
        """Read an immutable Suite and re-verify every referenced package tree."""

        self._validate_identifier(snapshot_id, "snapshot_id")
        with self._registry_lock(exclusive=False):
            snapshot = self._read_suite_snapshot(snapshot_id)
            index = self._load_index()
            for selection in snapshot.packages:
                self._verify_suite_selection(index, selection)
            return snapshot

    def resolve_suite_package(
        self,
        snapshot_id: str,
        package_id: str,
        version: str,
    ) -> ResolvedEnvironmentPackage:
        """Resolve one Suite member only while it remains safe for new consumption."""

        self._validate_identifier(snapshot_id, "snapshot_id")
        self._validate_package_component(package_id, "package_id")
        self._validate_package_component(version, "version")
        with self._registry_lock(exclusive=False):
            snapshot = self._read_suite_snapshot(snapshot_id)
            matches = tuple(
                item
                for item in snapshot.packages
                if item.package_id == package_id and item.version == version
            )
            if len(matches) != 1:
                raise ReleaseNotFoundError(f"Suite package not found: {package_id}@{version}")
            selection = matches[0]
            index = self._load_index()
            record, manifest = self._verify_suite_selection(index, selection)
            if record.status != "released":
                raise ParentNotEligibleError(
                    f"Suite package is not currently released: {record.status}"
                )
            return ResolvedEnvironmentPackage(
                selection=selection,
                record=record,
                manifest=manifest,
                package_root=self._package_path(record.coordinate),
            )

    def _read_suite_snapshot(self, snapshot_id: str) -> EnvironmentSuiteSnapshot:
        raw = self._read_file(
            self._suite_snapshot_path(snapshot_id),
            f"Suite snapshot not found: {snapshot_id}",
        )
        try:
            snapshot = EnvironmentSuiteSnapshot.model_validate_json(raw)
        except Exception as exc:
            raise RegistryIntegrityError(f"invalid Suite snapshot: {snapshot_id}") from exc
        if snapshot.snapshot_id != snapshot_id or snapshot.stable_json_bytes() != raw:
            raise RegistryIntegrityError("Suite snapshot identity or canonical bytes changed")
        return snapshot

    def _verify_suite_selection(
        self,
        index: RegistryIndex,
        selection: SuitePackageSelection,
    ) -> tuple[ReleaseRecord, EnvironmentPackageManifest]:
        record = self._find_record(index, selection.package_id, selection.version)
        if record is None:
            raise RegistryIntegrityError(
                f"Suite release disappeared: {selection.package_id}@{selection.version}"
            )
        if record.coordinate.package_digest != selection.package_digest:
            raise RegistryIntegrityError("Suite package digest differs from Registry release")
        self._verify_release_record(record)
        manifest = self._artifact_store.get_json(
            record.manifest_ref,
            EnvironmentPackageManifest,
        )
        if manifest.content_digest() != selection.manifest_hash:
            raise RegistryIntegrityError("Suite manifest hash differs from Registry release")
        return record, manifest

    def _suite_snapshot_path(self, snapshot_id: str) -> Path:
        return self._safe_path("suite-snapshots", f"{snapshot_id}.json")

    def _load_release_evidence(
        self,
        manifest_ref: ArtifactRef,
        judge_report_ref: ArtifactRef,
        release_profile: ReleaseProfile,
        *,
        reservation_owner_ref: ArtifactRef,
    ) -> tuple[EnvironmentPackageManifest, JudgeReport, tuple[str, ...]]:
        """Revalidate the acyclic pre-package dossier before physical publish.

        This method intentionally overrides the retired ClaimVector-based
        implementation above while the clean-break migration deletes its old
        helpers.  The executable Registry path now accepts only a final graph
        epoch and pre-package WorkCommit closure; a package cannot cite its own
        readiness to manufacture release eligibility.
        """

        if manifest_ref.artifact_type != MANIFEST_ARTIFACT_TYPE:
            raise ReleaseRejectedError(f"manifest artifact_type must be {MANIFEST_ARTIFACT_TYPE}")
        if judge_report_ref.artifact_type != JUDGE_REPORT_ARTIFACT_TYPE:
            raise ReleaseRejectedError(
                f"JudgeReport artifact_type must be {JUDGE_REPORT_ARTIFACT_TYPE}"
            )
        read_view = self._artifact_store.open_read_view()
        self._assert_produced_by(
            manifest_ref,
            self._framework_producers,
            "framework",
            read_view=read_view,
        )
        self._assert_produced_by(
            judge_report_ref,
            self._judge_producers,
            "Judge",
            read_view=read_view,
        )
        manifest = read_view.get_json(manifest_ref, EnvironmentPackageManifest)
        report = read_view.get_json(judge_report_ref, JudgeReport)
        dossier_ref = manifest.release_dossier_ref
        if dossier_ref.artifact_type != RELEASE_DOSSIER_ARTIFACT_TYPE:
            raise ReleaseRejectedError("manifest ReleaseDossier has the wrong artifact type")
        self._assert_produced_by(
            dossier_ref,
            self._framework_producers,
            "framework",
            read_view=read_view,
        )
        dossier = read_view.get_json(dossier_ref, ReleaseDossier)
        integration = read_view.get_json(
            manifest.integration_report_ref,
            IntegrationReport,
        )
        telemetry = read_view.get_json(
            manifest.telemetry_summary_ref,
            TelemetryReleaseSummary,
        )
        epoch = read_view.get_json(dossier.final_epoch_ref, WorkGraphEpoch)
        graph_manifest = read_view.get_json(
            dossier.final_manifest_ref,
            WorkGraphManifest,
        )
        if (
            manifest.judge_report_ref != judge_report_ref
            or dossier.final_epoch_ref.artifact_type != "control.work_graph_epoch"
            or epoch.epoch_kind != "final"
            or epoch.context_ref != dossier.context_ref
            or epoch.manifest_ref != dossier.final_manifest_ref
            or graph_manifest.mode != "production"
            or not graph_manifest.releasable
            or graph_manifest.external_root_refs != (dossier.context_ref,)
        ):
            raise ReleaseRejectedError("ReleaseDossier does not bind one final generation graph")
        expected_dossier_refs = {
            "design_ref": manifest.design_ref,
            "candidate_ref": manifest.candidate_ref,
            "candidate_manifest_ref": manifest.candidate_manifest_ref,
            "build_record_ref": manifest.build_record_ref,
            "implementation_lineage_ref": manifest.implementation_lineage_ref,
            "integration_report_ref": manifest.integration_report_ref,
            "judge_report_ref": judge_report_ref,
            "telemetry_summary_ref": manifest.telemetry_summary_ref,
        }
        if any(getattr(dossier, name) != ref for name, ref in expected_dossier_refs.items()):
            raise ReleaseRejectedError(
                "ReleaseDossier and package manifest bind different revisions"
            )
        if dossier.release_profile != release_profile:
            raise ReleaseRejectedError("ReleaseDossier and Registry release policy differ")
        # ``build.public_verifier`` is the public candidate self-check while
        # ``judge.verifier_ir_projection`` is the independent Judge contract.
        # They must never be collapsed to one reference.  What publication
        # needs is proof that the exact JudgeReport consumed the IR named by the
        # dossier; the manifest separately binds its public self-check.
        if dossier.verifier_ref not in read_view.dependencies(judge_report_ref):
            raise ReleaseRejectedError("JudgeReport does not bind the ReleaseDossier Verifier IR")
        if not dossier.prepackage_commit_refs:
            raise ReleaseRejectedError("ReleaseDossier has no pre-package WorkCommit closure")
        for commit_ref in dossier.prepackage_commit_refs:
            commit = read_view.get_json(commit_ref, WorkCommit)
            if commit.diagnostic_only or not commit.releasable:
                raise ReleaseRejectedError(
                    "diagnostic WorkCommit cannot establish release evidence"
                )
        dossier_dependencies = set(read_view.dependencies(dossier_ref))
        required_dossier_dependencies = {
            dossier.context_ref,
            dossier.final_epoch_ref,
            dossier.final_manifest_ref,
            *dossier.prepackage_commit_refs,
            dossier.design_ref,
            dossier.candidate_ref,
            dossier.candidate_manifest_ref,
            dossier.build_record_ref,
            dossier.implementation_lineage_ref,
            dossier.verifier_ref,
            dossier.integration_report_ref,
            dossier.judge_report_ref,
            dossier.telemetry_summary_ref,
        }
        if not required_dossier_dependencies <= dossier_dependencies:
            raise ReleaseRejectedError("ReleaseDossier dependency closure is incomplete")
        self._require_active_release_commit_closure(
            graph_manifest=graph_manifest,
            dossier=dossier,
            manifest_ref=manifest_ref,
            read_view=read_view,
        )
        if (
            report.candidate_ref != manifest.candidate_ref
            or report.candidate_source_tree_digest != manifest.candidate_source_tree_digest
            or report.verdict != "pass"
            or any(item.hard and item.status != "pass" for item in report.gate_results)
            or any(item.blocks_release for item in report.findings)
        ):
            raise ReleaseRejectedError("JudgeReport is not a passing exact-candidate release proof")
        if (
            integration.status != "ready"
            or integration.candidate_ref != manifest.candidate_ref
            or integration.candidate_source_tree_digest != manifest.candidate_source_tree_digest
            or any(item.status != "pass" for item in integration.gate_results)
            or any(item.blocks_release for item in integration.findings)
        ):
            raise ReleaseRejectedError("IntegrationReport is not ready for the exact Candidate")
        if (
            telemetry.cut_stage != "pre_publish"
            or telemetry.trace_id != telemetry.run_id
            or telemetry.invocation_count < 1
        ):
            raise ReleaseRejectedError("telemetry is not a valid pre-publish commitment")
        gates = {item.gate_id: item for item in report.gate_results}
        required = tuple(sorted(release_profile.required_hard_gates))
        if not required or any(
            gate_id not in gates or not gates[gate_id].hard or gates[gate_id].status != "pass"
            for gate_id in required
        ):
            raise ReleaseRejectedError("required hard gate did not pass")
        self._validate_reachability_release_evidence(report, gates)
        manifest_dependencies = set(read_view.dependencies(manifest_ref))
        required_manifest_dependencies = {
            manifest.design_ref,
            manifest.world_spec_ref,
            manifest.candidate_ref,
            manifest.candidate_manifest_ref,
            manifest.build_record_ref,
            manifest.implementation_lineage_ref,
            manifest.judge_report_ref,
            manifest.integration_report_ref,
            manifest.release_dossier_ref,
            manifest.telemetry_summary_ref,
            manifest.public_verifier_ref,
            manifest.task_materializer.output_schema_ref,
            manifest.task_materializer.curriculum_ref,
        }
        if not required_manifest_dependencies <= manifest_dependencies:
            raise ReleaseRejectedError("package manifest dependency closure is incomplete")
        if reservation_owner_ref not in read_view.dependencies(dossier.context_ref):
            # The context itself binds its Job; accept an exact Job root only.
            context = read_view.get_json(dossier.context_ref, GenerationContext)
            if context.job_ref != reservation_owner_ref:
                raise ReleaseRejectedError(
                    "ReleaseDossier context does not bind the reservation owner"
                )
        return manifest, report, required

    def _require_active_release_commit_closure(
        self,
        *,
        graph_manifest: WorkGraphManifest,
        dossier: ReleaseDossier,
        manifest_ref: ArtifactRef,
        read_view: ArtifactReadView,
    ) -> None:
        """Prove dossier evidence is live Scheduler authority, not a hand-built DAG.

        A ``ReleaseDossier`` is deliberately immutable and pre-package, so it
        cannot by itself tell whether an upstream repair superseded one of its
        WorkCommits.  The Registry must therefore reread the exact mutable
        heads, validate their definition identity against the frozen final graph,
        and additionally require the Package commit that occurs after dossier
        assembly.  This is the causal cut that prevents either a stale dossier or
        a Design-only graph from manufacturing a release candidate.
        """

        bindings: dict[tuple[str, str], WorkGraphNodeBinding] = {
            (binding.coordinate.component, binding.coordinate.stage): binding
            for binding in graph_manifest.node_bindings
        }
        expected_outputs: dict[tuple[str, str], tuple[ArtifactRef, ...]] = {
            ("design", "modeling_boundary"): (dossier.design_ref,),
            (
                "build",
                "candidate_build",
            ): (
                dossier.candidate_ref,
                dossier.candidate_manifest_ref,
                dossier.build_record_ref,
                dossier.implementation_lineage_ref,
            ),
            ("verifier", "verifier_intent"): (dossier.verifier_ref,),
            ("integration", "runtime_integration"): (dossier.integration_report_ref,),
            ("judge", "release_assurance"): (dossier.judge_report_ref,),
            ("release", "observability_closure"): (dossier.telemetry_summary_ref,),
        }
        commit_by_coordinate: dict[tuple[str, str], ArtifactRef] = {}
        for commit_ref in dossier.prepackage_commit_refs:
            self._assert_produced_by(
                commit_ref,
                self._framework_producers,
                "framework",
                read_view=read_view,
            )
            commit = read_view.get_json(commit_ref, WorkCommit)
            commit_key = (commit.coordinate.component, commit.coordinate.stage)
            if commit_key in commit_by_coordinate:
                raise ReleaseRejectedError("ReleaseDossier repeats a WorkCommit coordinate")
            commit_by_coordinate[commit_key] = commit_ref

        if set(commit_by_coordinate) != set(expected_outputs):
            raise ReleaseRejectedError("ReleaseDossier WorkCommit coordinates are not canonical")
        for key, expected_refs in expected_outputs.items():
            binding = bindings.get(key)
            if binding is None:
                raise ReleaseRejectedError("final WorkGraph omits a required release coordinate")
            commit_ref = commit_by_coordinate[key]
            commit = read_view.get_json(commit_ref, WorkCommit)
            if (
                commit.coordinate != binding.coordinate
                or commit.work_id != binding.work_id
                or commit.definition_digest != binding.definition_digest
                or commit.diagnostic_only
                or not commit.releasable
                or not set(expected_refs) <= set(commit.consumer_refs)
            ):
                raise ReleaseRejectedError(
                    "ReleaseDossier WorkCommit does not prove its frozen final-graph output"
                )
            self._require_active_head_commit(
                binding,
                commit,
                commit_ref,
                read_view=read_view,
            )

        package_binding = bindings.get(("release", "package"))
        if package_binding is None:
            raise ReleaseRejectedError("final WorkGraph omits the Package coordinate")
        package_head = self._work_store.read_head(package_binding.coordinate)
        if (
            package_head is None
            or package_head.status != "committed"
            or package_head.commit_ref is None
        ):
            raise ReleaseRejectedError("Package has not committed before Registry publication")
        package_commit = read_view.get_json(package_head.commit_ref, WorkCommit)
        if (
            package_commit.coordinate != package_binding.coordinate
            or package_commit.work_id != package_binding.work_id
            or package_commit.definition_digest != package_binding.definition_digest
            or package_commit.diagnostic_only
            or not package_commit.releasable
            or manifest_ref not in package_commit.consumer_refs
        ):
            raise ReleaseRejectedError("Package WorkCommit does not bind the exact manifest")
        self._require_active_head_commit(
            package_binding,
            package_commit,
            package_head.commit_ref,
            read_view=read_view,
        )

    def _require_active_head_commit(
        self,
        binding: WorkGraphNodeBinding,
        commit: WorkCommit,
        commit_ref: ArtifactRef,
        *,
        read_view: ArtifactReadView,
    ) -> None:
        """Check one frozen binding against the Scheduler's current durable head."""

        head = self._work_store.read_head(binding.coordinate)
        if (
            head is None
            or head.status != "committed"
            or head.commit_ref != commit_ref
            or head.definition_digest != binding.definition_digest
            or head.acceptance_digest != commit.acceptance_digest
            or head.evaluation_ref != commit.feedback_evaluation_ref
        ):
            raise ReleaseRejectedError("ReleaseDossier WorkCommit is not active in WorkControl")
        attempt = read_view.get_json(head.attempt_ref, WorkAttempt)
        if (
            attempt.attempt_id != commit.attempt_id
            or attempt.work_id != binding.work_id
            or attempt.coordinate != binding.coordinate
            or attempt.definition_digest != binding.definition_digest
            or attempt.input_refs != commit.input_refs
            or attempt.feedback_evaluation_ref != commit.feedback_evaluation_ref
        ):
            raise ReleaseRejectedError("active WorkHead and WorkCommit attempt closure differ")

    @staticmethod
    def _snapshot_id(
        registry_revision: int,
        created_at: datetime,
        records: tuple[ReleaseRecord, ...],
    ) -> str:
        body = {
            "registry_revision": registry_revision,
            "created_at": created_at.isoformat(),
            "releases": [item.model_dump(mode="json", exclude_none=False) for item in records],
        }
        digest = sha256_digest(canonical_json_bytes(body)).removeprefix("sha256:")
        return f"snapshot_{digest}"

    def quarantine(
        self,
        package_id: str,
        version: str,
        *,
        reason_code: str,
        actor: str = "framework",
    ) -> ReleaseRecord:
        """Mark a release quarantined without changing any package byte."""

        return self._change_status(
            package_id=package_id,
            version=version,
            new_status="quarantined",
            reason_code=reason_code,
            actor=actor,
            superseded_by=None,
        )

    def supersede(
        self,
        package_id: str,
        version: str,
        *,
        superseded_by: PackageCoordinate,
        reason_code: str,
        actor: str = "framework",
    ) -> ReleaseRecord:
        """Mark an old immutable version superseded by another released coordinate."""

        return self._change_status(
            package_id=package_id,
            version=version,
            new_status="superseded",
            reason_code=reason_code,
            actor=actor,
            superseded_by=superseded_by,
        )

    def _change_status(
        self,
        *,
        package_id: str,
        version: str,
        new_status: ReleaseStatus,
        reason_code: str,
        actor: str,
        superseded_by: PackageCoordinate | None,
    ) -> ReleaseRecord:
        self._validate_package_component(package_id, "package_id")
        self._validate_package_component(version, "version")
        self._validate_identifier(reason_code, "reason_code")
        self._validate_actor(actor)
        with self._registry_lock(exclusive=True):
            index = self._load_index()
            current = self._find_record(index, package_id, version)
            if current is None:
                raise ReleaseNotFoundError(f"release not found: {package_id}@{version}")
            self._verify_release_record(current)
            if current.status == new_status:
                if new_status != "superseded" or current.superseded_by == superseded_by:
                    return current
                raise ReleaseConflictError("release was superseded by a different coordinate")
            if current.status == "superseded":
                raise ReleaseConflictError("a superseded release cannot change status")
            if new_status == "superseded":
                if superseded_by is None or superseded_by == current.coordinate:
                    raise ReleaseRejectedError("supersede requires a different replacement release")
                replacement = self._find_record(
                    index,
                    superseded_by.package_id,
                    superseded_by.version,
                )
                if replacement is None or replacement.coordinate != superseded_by:
                    raise ReleaseNotFoundError("superseding release is not registered")
                if replacement.status != "released":
                    raise ReleaseRejectedError("superseding release must currently be released")
            now = datetime.now(UTC)
            replacement_data = current.model_dump(mode="python")
            replacement_data.update(
                {
                    "status": new_status,
                    "status_changed_at": now,
                    "superseded_by": superseded_by,
                }
            )
            updated_record = ReleaseRecord.model_validate(replacement_data)
            records = tuple(
                updated_record if item.release_id == current.release_id else item
                for item in index.releases
            )
            self._write_index(
                RegistryIndex(
                    revision=index.revision + 1,
                    releases=self._sorted_records(records),
                    reservations=index.reservations,
                )
            )
            event_type: Literal["release_quarantined", "release_superseded"] = (
                "release_quarantined" if new_status == "quarantined" else "release_superseded"
            )
            self._append_event(
                event_type=event_type,
                coordinate=current.coordinate,
                previous_status=current.status,
                new_status=new_status,
                actor=actor,
                reason_code=reason_code,
                superseded_by=superseded_by,
            )
            return updated_record

    def _load_legacy_claim_vector_evidence(
        self,
        manifest_ref: ArtifactRef,
        judge_report_ref: ArtifactRef,
        release_profile: ReleaseProfile,
        *,
        reservation_owner_ref: ArtifactRef,
    ) -> tuple[EnvironmentPackageManifest, JudgeReport, tuple[str, ...]]:
        if manifest_ref.artifact_type != MANIFEST_ARTIFACT_TYPE:
            raise ReleaseRejectedError(f"manifest artifact_type must be {MANIFEST_ARTIFACT_TYPE}")
        if judge_report_ref.artifact_type != JUDGE_REPORT_ARTIFACT_TYPE:
            raise ReleaseRejectedError(
                f"JudgeReport artifact_type must be {JUDGE_REPORT_ARTIFACT_TYPE}"
            )
        self._assert_produced_by(manifest_ref, self._framework_producers, "framework")
        self._assert_produced_by(judge_report_ref, self._judge_producers, "Judge")
        manifest = self._artifact_store.get_json(manifest_ref, EnvironmentPackageManifest)
        report = self._artifact_store.get_json(judge_report_ref, JudgeReport)
        integration_ref = manifest.integration_report_ref
        claim_vector_ref = manifest.release_dossier_ref
        telemetry_ref = manifest.telemetry_summary_ref
        if integration_ref.artifact_type != INTEGRATION_REPORT_ARTIFACT_TYPE:
            raise ReleaseRejectedError("manifest IntegrationReport has the wrong artifact type")
        if claim_vector_ref.artifact_type != CLAIM_VECTOR_ARTIFACT_TYPE:
            raise ReleaseRejectedError("manifest ClaimVector has the wrong artifact type")
        if telemetry_ref.artifact_type != TELEMETRY_SUMMARY_ARTIFACT_TYPE:
            raise ReleaseRejectedError("manifest telemetry summary has the wrong artifact type")
        self._assert_produced_by(integration_ref, self._judge_producers, "Integration")
        self._assert_produced_by(claim_vector_ref, self._framework_producers, "framework")
        self._assert_produced_by(telemetry_ref, self._framework_producers, "framework")
        integration = self._artifact_store.get_json(integration_ref, IntegrationReport)
        claim_vector = self._artifact_store.get_json(claim_vector_ref, ClaimVector)
        telemetry = self._artifact_store.get_json(telemetry_ref, TelemetryReleaseSummary)
        if manifest.judge_report_ref != judge_report_ref:
            raise ReleaseRejectedError("manifest does not reference the supplied JudgeReport")
        if manifest.candidate_ref != report.candidate_ref:
            raise ReleaseRejectedError("manifest and JudgeReport reference different candidates")
        if report.candidate_source_tree_digest != manifest.candidate_source_tree_digest:
            raise ReleaseRejectedError(
                "JudgeReport and envpkg bind different candidate source trees"
            )
        if report.verdict != "pass":
            raise ReleaseRejectedError(f"Judge verdict is not pass: {report.verdict}")
        if any(item.hard and item.status != "pass" for item in report.gate_results):
            raise ReleaseRejectedError("JudgeReport contains a non-passing hard gate")
        if any(item.blocks_release for item in report.findings):
            raise ReleaseRejectedError("JudgeReport contains a release-blocking Finding")
        if (
            integration.status != "ready"
            or integration.candidate_ref != manifest.candidate_ref
            or integration.candidate_source_tree_digest != manifest.candidate_source_tree_digest
        ):
            raise ReleaseRejectedError(
                "IntegrationReport is not ready for the exact manifest source tree"
            )
        integration_gate_ids = tuple(item.gate_id for item in integration.gate_results)
        if (
            len(set(integration_gate_ids)) != len(integration_gate_ids)
            or set(integration_gate_ids) != _REQUIRED_INTEGRATION_GATES
        ):
            raise ReleaseRejectedError("IntegrationReport gate closure is not canonical")
        if any(item.status != "pass" for item in integration.gate_results):
            raise ReleaseRejectedError("IntegrationReport contains a non-passing gate")
        if any(item.blocks_release for item in integration.findings):
            raise ReleaseRejectedError("IntegrationReport contains a release-blocking Finding")
        claims = {item.claim_id: item for item in claim_vector.claims}
        if (
            claim_vector.maturity != "release_candidate"
            or claim_vector.blocking_claim_ids
            or claim_vector.design_ref != manifest.design_ref
            or claim_vector.candidate_ref != manifest.candidate_ref
            or claim_vector.integration_ref != integration_ref
            or claim_vector.release_judge_ref != judge_report_ref
            or claim_vector.telemetry_ref != telemetry_ref
            or set(claims) != _REQUIRED_RELEASE_CLAIMS
            or any(claims[claim_id].status != "passed" for claim_id in _REQUIRED_RELEASE_CLAIMS)
        ):
            raise ReleaseRejectedError("ClaimVector is not an exact RELEASE_CANDIDATE proof")
        if claims["design.valid"].subject_ref != manifest.design_ref or any(
            claims[claim_id].subject_ref != manifest.candidate_ref
            for claim_id in _REQUIRED_RELEASE_CLAIMS - {"design.valid"}
        ):
            raise ReleaseRejectedError("ClaimVector claim subjects do not bind the manifest")
        expected_effects = {
            "design.valid": "block_integration",
            "build.valid": "block_integration",
            "runtime.executable": "block_integration",
            "integration.ready": "block_release",
            "verifier.valid": "block_release",
            "release_judge.valid": "block_release",
            "observability.release_ready": "block_release",
        }
        if any(
            claim_item.producer != "framework" or claim_item.effect != expected_effects[claim_id]
            for claim_id, claim_item in claims.items()
        ):
            raise ReleaseRejectedError("ClaimVector producer/effect semantics are invalid")
        verifier_ref = claim_vector.verifier_ref
        if verifier_ref is None:
            raise ReleaseRejectedError("release ClaimVector omits its Verifier")
        design_evidence_refs = claims["design.valid"].evidence_refs
        modeling_refs = tuple(
            ref for ref in design_evidence_refs if ref.artifact_type == "control.modeling_gate"
        )
        work_manifest_refs = tuple(
            ref
            for ref in design_evidence_refs
            if ref.artifact_type == "control.work_graph_manifest"
        )
        readiness_refs = tuple(
            ref for ref in design_evidence_refs if ref.artifact_type == "control.work_readiness"
        )
        if (
            len(modeling_refs) != 1
            or len(work_manifest_refs) != 1
            or len(readiness_refs) != 1
            or len(design_evidence_refs) != 3
        ):
            raise ReleaseRejectedError(
                "design.valid must cite Modeling Gate, WorkGraph manifest and readiness"
            )
        modeling_gate = self._artifact_store.get_json(modeling_refs[0], GateResult)
        work_manifest = self._artifact_store.get_json(
            work_manifest_refs[0],
            WorkGraphManifest,
        )
        readiness = self._artifact_store.get_json(
            readiness_refs[0],
            WorkReadinessSnapshot,
        )
        if (
            modeling_gate.status != "pass"
            or not modeling_gate.hard
            or modeling_gate.subject_ref != manifest.design_ref
            or work_manifest.mode != "production"
            or not work_manifest.releasable
            or readiness.manifest_ref != work_manifest_refs[0]
            or readiness.graph_digest != work_manifest.graph_digest
            or readiness.status != "ready"
            or not readiness.release_candidate_ready
        ):
            raise ReleaseRejectedError("design.valid production WorkGraph is not exact and ready")
        expected_evidence = {
            "design.valid": design_evidence_refs,
            "build.valid": (manifest.build_record_ref, manifest.candidate_manifest_ref),
            "runtime.executable": (integration_ref,),
            "integration.ready": (integration_ref,),
            "verifier.valid": (verifier_ref,),
            "release_judge.valid": (judge_report_ref,),
            "observability.release_ready": (telemetry_ref,),
        }
        if any(
            set(claims[claim_id].evidence_refs) != set(refs)
            for claim_id, refs in expected_evidence.items()
        ):
            raise ReleaseRejectedError("ClaimVector evidence semantics are invalid")
        judge_verifier_refs = {
            ref
            for ref in self._artifact_store.dependencies(judge_report_ref)
            if ref.artifact_type == "judge.verifier_ir_projection"
        }
        if judge_verifier_refs != {verifier_ref}:
            raise ReleaseRejectedError("ClaimVector Verifier is not uniquely bound by Judge")
        if (
            telemetry.cut_stage != "pre_publish"
            or not telemetry.provisional
            or telemetry.open_span_count != 1
            or telemetry.trace_id != telemetry.run_id
            or telemetry.invocation_count < 1
            or set(telemetry.required_node_attempts)
            != {"request", "design", "verifier", "build", "integration", "judge"}
            or any(value < 1 for value in telemetry.required_node_attempts.values())
            or set(telemetry.required_operation_attempts)
            not in (
                {"research.search", "research.fetch", "research.extract"},
                {"research.checkpoint_reuse"},
            )
            or any(value < 1 for value in telemetry.required_operation_attempts.values())
            or set(telemetry.required_metric_observations)
            != {
                "invocation.tokens.total",
                "research.search.calls",
                "research.fetch.calls",
                "research.documents.extracted",
            }
            or any(value < 1 for value in telemetry.required_metric_observations.values())
        ):
            raise ReleaseRejectedError("telemetry summary is not a complete release trace")
        research_provenance_dependencies: set[ArtifactRef] = set()
        if set(telemetry.required_operation_attempts) == {"research.checkpoint_reuse"}:
            if len(telemetry.research_provenance_refs) != 1:
                raise ReleaseRejectedError(
                    "checkpoint reuse requires one research provenance artifact"
                )
            provenance_ref = telemetry.research_provenance_refs[0]
            self._assert_produced_by(
                provenance_ref,
                self._framework_producers,
                "framework",
            )
            provenance = self._artifact_store.get_json(
                provenance_ref,
                ResearchCheckpointReuseEvidence,
            )
            job = self._artifact_store.get_json(reservation_owner_ref, EnvironmentJob)
            final_design = self._artifact_store.get_json(
                manifest.design_ref,
                EnvironmentDesign,
            )
            provenance_dependencies = set(self._artifact_store.dependencies(provenance_ref))
            expected_provenance_dependencies = {
                reservation_owner_ref,
                provenance.request_ref,
                provenance.checkpoint_ref,
                provenance.evidence_graph_ref,
                manifest.design_ref,
                modeling_refs[0],
            }
            if (
                provenance.run_id != telemetry.run_id
                or provenance.job_ref != reservation_owner_ref
                or job.kind != "generate"
                or job.request_ref != provenance.request_ref
                or provenance.final_design_ref != manifest.design_ref
                or provenance.evidence_graph_ref != final_design.evidence_graph_ref
                or provenance.modeling_gate_ref != modeling_refs[0]
                or provenance_dependencies != expected_provenance_dependencies
            ):
                raise ReleaseRejectedError(
                    "research checkpoint provenance does not bind the final design"
                )
            if provenance.checkpoint_ref.artifact_type == "control.job_run_snapshot":
                snapshot = self._artifact_store.get_json(
                    provenance.checkpoint_ref,
                    JobRunSnapshot,
                )
                checkpoint_valid = (
                    snapshot.job_ref == reservation_owner_ref
                    and provenance.evidence_graph_ref in snapshot.latest_artifact_refs
                )
            else:
                checkpoint_valid = False
            if not checkpoint_valid:
                raise ReleaseRejectedError(
                    "research provenance checkpoint does not bind its EvidenceGraph"
                )
            research_provenance_dependencies.add(provenance_ref)
        elif telemetry.research_provenance_refs:
            raise ReleaseRejectedError("executed research cannot cite checkpoint reuse provenance")
        telemetry_dependencies = set(self._artifact_store.dependencies(telemetry_ref))
        required_telemetry_dependencies = {
            reservation_owner_ref,
            manifest.candidate_ref,
            judge_report_ref,
            *research_provenance_dependencies,
        }
        if telemetry_dependencies != required_telemetry_dependencies:
            raise ReleaseRejectedError(
                "telemetry summary is not bound to the exact job, candidate and JudgeReport"
            )

        gates: dict[str, GateResult] = {}
        for gate in report.gate_results:
            if gate.gate_id in gates:
                raise ReleaseRejectedError(f"duplicate gate result: {gate.gate_id}")
            gates[gate.gate_id] = gate
        required = release_profile.required_hard_gates
        if not required or len(set(required)) != len(required):
            raise ReleaseRejectedError("release profile must define unique required hard gates")
        for gate_id in required:
            result = gates.get(gate_id)
            if result is None or not result.hard or result.status != "pass":
                raise ReleaseRejectedError(f"required hard gate did not pass: {gate_id}")

        manifest_dependencies = set(self._artifact_store.dependencies(manifest_ref))
        direct_manifest_refs = {
            manifest.design_ref,
            manifest.world_spec_ref,
            manifest.candidate_ref,
            manifest.candidate_manifest_ref,
            manifest.build_record_ref,
            manifest.implementation_lineage_ref,
            manifest.judge_report_ref,
            manifest.integration_report_ref,
            manifest.release_dossier_ref,
            manifest.telemetry_summary_ref,
            manifest.public_verifier_ref,
            manifest.task_materializer.output_schema_ref,
            manifest.task_materializer.curriculum_ref,
        }
        if not direct_manifest_refs <= manifest_dependencies:
            missing = sorted(
                item.artifact_id for item in direct_manifest_refs - manifest_dependencies
            )
            raise ReleaseRejectedError(f"manifest dependency edges are incomplete: {missing}")
        report_dependencies = set(self._artifact_store.dependencies(judge_report_ref))
        if report.candidate_ref not in report_dependencies:
            raise ReleaseRejectedError("JudgeReport must depend on the exact candidate revision")
        declared_evidence = set(report.evaluation_evidence_refs)
        referenced_evidence = {
            evidence_ref for gate in report.gate_results for evidence_ref in gate.evidence_refs
        } | {evidence_ref for finding in report.findings for evidence_ref in finding.evidence_refs}
        if not referenced_evidence <= declared_evidence:
            missing = sorted(item.artifact_id for item in referenced_evidence - declared_evidence)
            raise ReleaseRejectedError(
                f"JudgeReport omits Gate/Finding evidence from its declared closure: {missing}"
            )
        if not declared_evidence <= report_dependencies:
            missing = sorted(item.artifact_id for item in declared_evidence - report_dependencies)
            raise ReleaseRejectedError(
                f"JudgeReport dependency edges omit declared evaluation evidence: {missing}"
            )
        for gate in report.gate_results:
            if gate.subject_ref != report.candidate_ref:
                raise ReleaseRejectedError(
                    f"Judge gate does not bind the exact candidate: {gate.gate_id}"
                )
        for evidence_ref in declared_evidence:
            self._assert_produced_by(evidence_ref, self._judge_producers, "Judge evidence")
        integration_dependencies = set(self._artifact_store.dependencies(integration_ref))
        declared_integration_evidence = set(integration.evidence_refs)
        referenced_integration_evidence = {
            evidence_ref for gate in integration.gate_results for evidence_ref in gate.evidence_refs
        } | {
            evidence_ref
            for finding in integration.findings
            for evidence_ref in finding.evidence_refs
        }
        if (
            integration.candidate_ref not in integration_dependencies
            or not referenced_integration_evidence <= declared_integration_evidence
            or not declared_integration_evidence <= integration_dependencies
        ):
            raise ReleaseRejectedError("IntegrationReport evidence closure is incomplete")
        for gate in integration.gate_results:
            if gate.subject_ref != integration.candidate_ref:
                raise ReleaseRejectedError("Integration gate does not bind the exact candidate")
        for evidence_ref in declared_integration_evidence:
            self._assert_produced_by(evidence_ref, self._judge_producers, "Integration evidence")
        claim_dependencies = set(self._artifact_store.dependencies(claim_vector_ref))
        required_claim_dependencies = {
            manifest.design_ref,
            manifest.candidate_ref,
            integration_ref,
            judge_report_ref,
            telemetry_ref,
            claim_vector.verifier_ref,
            *(
                ref
                for assurance_claim in claim_vector.claims
                for ref in (
                    *assurance_claim.evidence_refs,
                    *assurance_claim.dependency_refs,
                )
            ),
        }
        required_claim_dependencies.discard(None)
        if not required_claim_dependencies <= claim_dependencies:
            raise ReleaseRejectedError("ClaimVector artifact dependency closure is incomplete")
        telemetry_dependencies = set(self._artifact_store.dependencies(telemetry_ref))
        if not {manifest.candidate_ref, judge_report_ref} <= telemetry_dependencies:
            raise ReleaseRejectedError("telemetry summary is not bound to candidate and Judge")
        self._validate_reachability_release_evidence(report, gates)
        for ref in direct_manifest_refs:
            self._artifact_store.get_revision(ref)
        return manifest, report, tuple(sorted(required))

    def _validate_reachability_release_evidence(
        self,
        report: JudgeReport,
        gates: dict[str, GateResult],
    ) -> None:
        """Re-parse the one publishable reachability claim before release.

        A signed generic Judge blob is not enough for this hard claim.  The
        Registry accepts only the closed aggregate contract and never infers
        that a finite release sample certifies unseen future episodes.
        """

        gate = gates.get("task_reachability")
        if gate is None or not gate.hard or gate.status != "pass":
            raise ReleaseRejectedError("task_reachability hard gate did not pass")
        if len(gate.evidence_refs) != 1:
            raise ReleaseRejectedError(
                "task_reachability must reference exactly one public evidence artifact"
            )
        evidence_ref = gate.evidence_refs[0]
        if evidence_ref.artifact_type != _REACHABILITY_EVIDENCE_ARTIFACT_TYPE:
            raise ReleaseRejectedError(
                "task_reachability must use typed public reachability evidence"
            )
        try:
            evidence = self._artifact_store.get_json(
                evidence_ref,
                ReachabilityPublicEvidence,
            )
        except Exception as exc:
            raise ReleaseRejectedError("task_reachability public evidence is invalid") from exc
        if evidence.candidate_ref != report.candidate_ref:
            raise ReleaseRejectedError(
                "task_reachability evidence does not bind the exact candidate"
            )
        if (
            evidence.failed_instances != 0
            or evidence.certified_instances != evidence.materialized_instances
        ):
            raise ReleaseRejectedError(
                "task_reachability evidence contains an uncertified release sample"
            )
        if report.candidate_ref not in set(self._artifact_store.dependencies(evidence_ref)):
            raise ReleaseRejectedError(
                "task_reachability evidence lacks a dependency on the exact candidate"
            )

    def _assert_produced_by(
        self,
        ref: ArtifactRef,
        allowed_producers: frozenset[str],
        authority: str,
        *,
        read_view: ArtifactReadView | None = None,
    ) -> None:
        reader = self._artifact_store if read_view is None else read_view
        revision = reader.get_revision(ref)
        if revision.producer not in allowed_producers:
            raise ReleaseRejectedError(
                f"artifact lacks signed {authority} producer provenance: {ref.artifact_id}"
            )

    def _candidate_root(self, value: str | os.PathLike[str]) -> Path:
        requested = Path(value).expanduser()
        if requested.is_symlink():
            raise UnsafePackageError("candidate workspace cannot be a symlink")
        try:
            root = requested.resolve(strict=True)
        except FileNotFoundError as exc:
            raise UnsafePackageError("candidate workspace does not exist") from exc
        if not root.is_dir():
            raise UnsafePackageError("candidate workspace must be a directory")
        if root == self._root or self._root in root.parents:
            raise UnsafePackageError("candidate workspace cannot be inside the Registry")
        return root

    def _copy_and_validate_payload(
        self,
        source_root: Path,
        staging_root: Path,
        files: tuple[PackageFile, ...],
        *,
        framework_payloads: Sequence[FrameworkPackagePayload],
    ) -> None:
        declared_by_path = {item.path: item for item in files}
        payload_by_path = {item.path: item for item in framework_payloads}
        if len(payload_by_path) != len(framework_payloads):
            raise UnsafePackageError("framework package payload paths must be unique")
        expected_framework_paths = {path for path, _role in FRAMEWORK_PACKAGE_LAYOUT}
        if set(payload_by_path) != expected_framework_paths:
            raise UnsafePackageError(
                "framework package payload closure differs from manifest; "
                f"missing={sorted(expected_framework_paths - set(payload_by_path))}, "
                f"extra={sorted(set(payload_by_path) - expected_framework_paths)}"
            )
        candidate_files = tuple(item for item in files if item.path not in payload_by_path)
        self._assert_tree_matches(source_root, candidate_files, framework_files=())
        for declared in sorted(candidate_files, key=lambda item: item.path):
            source = source_root.joinpath(*PurePosixPath(declared.path).parts)
            target = staging_root.joinpath(*PurePosixPath(declared.path).parts)
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            self._copy_verified_file(source, target, declared)
        for path, payload in sorted(payload_by_path.items()):
            framework_declared = declared_by_path.get(path)
            if framework_declared is None or payload.descriptor() != framework_declared:
                raise UnsafePackageError(
                    f"framework package payload differs from manifest declaration: {path}"
                )
            if framework_declared.executable:
                raise UnsafePackageError(
                    f"framework data payload cannot be executable: {framework_declared.path}"
                )
            scanner = _ContentScanner(self._secret_canaries, framework_declared.path)
            scanner.update(payload.content)
            target = staging_root.joinpath(*PurePosixPath(framework_declared.path).parts)
            self._atomic_create(target, payload.content, mode=0o400)
        self._assert_tree_matches(source_root, candidate_files, framework_files=())
        self._verify_payload(staging_root, files, framework_files=())

    def _copy_verified_file(self, source: Path, target: Path, declared: PackageFile) -> None:
        source_flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        try:
            source_fd = os.open(source, source_flags)
        except OSError as exc:
            raise UnsafePackageError(f"cannot safely open declared file: {declared.path}") from exc
        target_flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        try:
            target_fd = os.open(target, target_flags, 0o600)
        except Exception:
            os.close(source_fd)
            raise
        digest = hashlib.sha256()
        size = 0
        scanner = _ContentScanner(self._secret_canaries, declared.path)
        try:
            source_stat = os.fstat(source_fd)
            if not stat.S_ISREG(source_stat.st_mode):
                raise UnsafePackageError(f"declared path is not a regular file: {declared.path}")
            executable = bool(source_stat.st_mode & 0o111)
            if executable != declared.executable:
                raise UnsafePackageError(f"executable mode mismatch: {declared.path}")
            while chunk := os.read(source_fd, 1024 * 1024):
                digest.update(chunk)
                scanner.update(chunk)
                size += len(chunk)
                self._write_all(target_fd, chunk)
            os.fsync(target_fd)
        finally:
            os.close(source_fd)
            os.close(target_fd)
        observed_hash = f"sha256:{digest.hexdigest()}"
        if size != declared.size_bytes or observed_hash != declared.content_hash:
            raise UnsafePackageError(f"hash or size mismatch: {declared.path}")
        os.chmod(target, 0o500 if declared.executable else 0o400, follow_symlinks=False)

    def _verify_payload(
        self,
        root: Path,
        files: tuple[PackageFile, ...],
        *,
        framework_files: tuple[str, ...],
    ) -> None:
        self._assert_tree_matches(root, files, framework_files=framework_files)
        for declared in files:
            path = root.joinpath(*PurePosixPath(declared.path).parts)
            flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
            try:
                descriptor = os.open(path, flags)
            except OSError as exc:
                raise RegistryIntegrityError(
                    f"cannot safely open package file: {declared.path}"
                ) from exc
            digest = hashlib.sha256()
            size = 0
            scanner = _ContentScanner(self._secret_canaries, declared.path)
            try:
                observed = os.fstat(descriptor)
                if not stat.S_ISREG(observed.st_mode):
                    raise RegistryIntegrityError(f"package path is not regular: {declared.path}")
                if bool(observed.st_mode & 0o111) != declared.executable:
                    raise RegistryIntegrityError(
                        f"package executable mode changed: {declared.path}"
                    )
                while chunk := os.read(descriptor, 1024 * 1024):
                    digest.update(chunk)
                    scanner.update(chunk)
                    size += len(chunk)
            finally:
                os.close(descriptor)
            if (
                size != declared.size_bytes
                or f"sha256:{digest.hexdigest()}" != declared.content_hash
            ):
                raise RegistryIntegrityError(f"package file changed: {declared.path}")

    def _verify_staging(
        self,
        root: Path,
        manifest: EnvironmentPackageManifest,
        *,
        include_dossier: bool,
        dossier: PublicationDossier | None = None,
    ) -> None:
        if root.is_symlink() or not root.is_dir():
            raise RegistryIntegrityError("staging tree is missing or unsafe")
        framework_files = (_MANIFEST_NAME, _DOSSIER_NAME) if include_dossier else (_MANIFEST_NAME,)
        self._verify_payload(root, manifest.files, framework_files=framework_files)
        manifest_bytes = self._read_file(root / _MANIFEST_NAME, "staging manifest missing")
        if manifest_bytes != manifest.stable_json_bytes():
            raise RegistryIntegrityError("staging manifest is not canonical or changed")
        if include_dossier:
            if dossier is None:
                raise RegistryIntegrityError("release dossier was not supplied")
            dossier_bytes = self._read_file(root / _DOSSIER_NAME, "release dossier missing")
            if dossier_bytes != dossier.stable_json_bytes():
                raise RegistryIntegrityError("release dossier is not canonical or changed")

    def _assert_tree_matches(
        self,
        root: Path,
        files: tuple[PackageFile, ...],
        *,
        framework_files: tuple[str, ...],
    ) -> None:
        actual_files, actual_directories = self._collect_tree(root)
        expected_files = {item.path for item in files} | set(framework_files)
        if actual_files != expected_files:
            missing = sorted(expected_files - actual_files)
            extra = sorted(actual_files - expected_files)
            raise UnsafePackageError(
                f"package file declaration mismatch; missing={missing}, extra={extra}"
            )
        expected_directories: set[str] = set()
        for path in expected_files:
            parent = PurePosixPath(path).parent
            while str(parent) != ".":
                expected_directories.add(parent.as_posix())
                parent = parent.parent
        undeclared_directories = actual_directories - expected_directories
        if undeclared_directories:
            raise UnsafePackageError(
                f"package contains undeclared directories: {sorted(undeclared_directories)}"
            )

    def _collect_tree(self, root: Path) -> tuple[set[str], set[str]]:
        files: set[str] = set()
        directories: set[str] = set()

        def visit(directory: Path, relative: PurePosixPath) -> None:
            try:
                entries = sorted(os.scandir(directory), key=lambda item: item.name)
            except OSError as exc:
                raise UnsafePackageError(f"cannot scan package directory: {relative}") from exc
            for entry in entries:
                child_relative = relative / entry.name
                child_name = child_relative.as_posix()
                self._assert_allowed_payload_path(child_name)
                if entry.is_symlink():
                    raise UnsafePackageError(f"symlink is prohibited: {child_name}")
                if entry.is_dir(follow_symlinks=False):
                    directories.add(child_name)
                    visit(Path(entry.path), child_relative)
                elif entry.is_file(follow_symlinks=False):
                    files.add(child_name)
                else:
                    raise UnsafePackageError(
                        f"non-regular package entry is prohibited: {child_name}"
                    )

        visit(root, PurePosixPath())
        return files, directories

    def _validate_manifest_files(self, files: tuple[PackageFile, ...]) -> None:
        canonical_names: set[str] = set()
        for declared in files:
            path = PurePosixPath(declared.path)
            if path.as_posix() != declared.path or path.is_absolute() or ".." in path.parts:
                raise UnsafePackageError(f"non-canonical package path: {declared.path}")
            if declared.path in {_MANIFEST_NAME, _DOSSIER_NAME} or declared.role == "manifest":
                raise UnsafePackageError("manifest and release dossier are framework-owned files")
            self._assert_allowed_payload_path(declared.path)
            canonical = unicodedata.normalize("NFC", declared.path).casefold()
            if canonical in canonical_names:
                raise UnsafePackageError(f"case/Unicode-colliding package path: {declared.path}")
            canonical_names.add(canonical)

    @staticmethod
    def _assert_allowed_payload_path(path: str) -> None:
        pure = PurePosixPath(path)
        for component in pure.parts:
            lowered = component.casefold()
            if lowered in _FORBIDDEN_COMPONENTS or lowered == ".env" or lowered.startswith(".env."):
                raise UnsafePackageError(f"forbidden package path: {path}")
            tokens = {item for item in re.split(r"[^a-z0-9]+", lowered) if item}
            if tokens & _FORBIDDEN_NAME_TOKENS:
                raise UnsafePackageError(f"private/sensitive package path is prohibited: {path}")
            if "verifier" in tokens and ("private" in tokens or "hidden" in tokens):
                raise UnsafePackageError(f"private verifier path is prohibited: {path}")
            if lowered in {"id_rsa", "id_ed25519"}:
                raise UnsafePackageError(f"credential path is prohibited: {path}")

    def _build_release_record(
        self,
        *,
        manifest: EnvironmentPackageManifest,
        report: JudgeReport,
        prepared: PreparedRelease,
        dossier_hash: str,
        published_at: datetime,
    ) -> ReleaseRecord:
        digest_hex = prepared.coordinate.package_digest.removeprefix("sha256:")
        return ReleaseRecord(
            release_id=f"release_{digest_hex}",
            coordinate=prepared.coordinate,
            reservation_id=prepared.reservation_id,
            reservation_owner_ref=prepared.reservation_owner_ref,
            status="released",
            package_relpath=self._package_relpath(prepared.coordinate),
            manifest_ref=prepared.manifest_ref,
            judge_report_ref=prepared.judge_report_ref,
            integration_report_ref=prepared.integration_report_ref,
            release_dossier_ref=prepared.release_dossier_ref,
            telemetry_summary_ref=prepared.telemetry_summary_ref,
            candidate_ref=manifest.candidate_ref,
            design_ref=manifest.design_ref,
            public_verifier_ref=manifest.public_verifier_ref,
            release_profile=prepared.release_profile,
            lineage=manifest.lineage,
            world_boundary_hash=manifest.world_boundary_hash,
            world_spec_hash=manifest.world_spec_hash,
            gate_results=report.gate_results,
            judge_budget_usage=report.budget_usage,
            file_count=prepared.file_count,
            payload_size_bytes=prepared.payload_size_bytes,
            dossier_hash=dossier_hash,
            published_at=published_at,
            status_changed_at=published_at,
        )

    def _load_or_create_staging_dossier(
        self,
        staging: Path,
        manifest: EnvironmentPackageManifest,
        prepared: PreparedRelease,
    ) -> PublicationDossier:
        path = staging / _DOSSIER_NAME
        if path.exists() or path.is_symlink():
            dossier_bytes = self._read_file(path, "staging release dossier missing")
            try:
                dossier = PublicationDossier.model_validate_json(dossier_bytes)
            except Exception as exc:
                raise RegistryIntegrityError("staging release dossier is invalid") from exc
            expected = PublicationDossier(
                coordinate=prepared.coordinate,
                reservation_id=prepared.reservation_id,
                reservation_owner_ref=prepared.reservation_owner_ref,
                manifest_ref=prepared.manifest_ref,
                judge_report_ref=prepared.judge_report_ref,
                integration_report_ref=prepared.integration_report_ref,
                release_dossier_ref=prepared.release_dossier_ref,
                telemetry_summary_ref=prepared.telemetry_summary_ref,
                candidate_ref=manifest.candidate_ref,
                release_profile=prepared.release_profile,
                passed_hard_gates=prepared.passed_hard_gates,
                file_count=prepared.file_count,
                payload_size_bytes=prepared.payload_size_bytes,
                published_at=dossier.published_at,
            )
            if dossier != expected:
                raise RegistryIntegrityError("staging release dossier does not match preparation")
            return dossier
        self._verify_staging(staging, manifest, include_dossier=False)
        dossier = PublicationDossier(
            coordinate=prepared.coordinate,
            reservation_id=prepared.reservation_id,
            reservation_owner_ref=prepared.reservation_owner_ref,
            manifest_ref=prepared.manifest_ref,
            judge_report_ref=prepared.judge_report_ref,
            integration_report_ref=prepared.integration_report_ref,
            release_dossier_ref=prepared.release_dossier_ref,
            telemetry_summary_ref=prepared.telemetry_summary_ref,
            candidate_ref=manifest.candidate_ref,
            release_profile=prepared.release_profile,
            passed_hard_gates=prepared.passed_hard_gates,
            file_count=prepared.file_count,
            payload_size_bytes=prepared.payload_size_bytes,
            published_at=datetime.now(UTC),
        )
        self._atomic_create(path, dossier.stable_json_bytes(), mode=0o400)
        return dossier

    def _recover_unindexed_release(
        self,
        path: Path,
        manifest: EnvironmentPackageManifest,
        report: JudgeReport,
        prepared: PreparedRelease,
    ) -> ReleaseRecord:
        dossier_bytes = self._read_file(path / _DOSSIER_NAME, "unindexed release dossier missing")
        try:
            dossier = PublicationDossier.model_validate_json(dossier_bytes)
        except Exception as exc:
            raise RegistryIntegrityError("unindexed release dossier is invalid") from exc
        expected = PublicationDossier(
            coordinate=prepared.coordinate,
            reservation_id=prepared.reservation_id,
            reservation_owner_ref=prepared.reservation_owner_ref,
            manifest_ref=prepared.manifest_ref,
            judge_report_ref=prepared.judge_report_ref,
            integration_report_ref=prepared.integration_report_ref,
            release_dossier_ref=prepared.release_dossier_ref,
            telemetry_summary_ref=prepared.telemetry_summary_ref,
            candidate_ref=manifest.candidate_ref,
            release_profile=prepared.release_profile,
            passed_hard_gates=prepared.passed_hard_gates,
            file_count=prepared.file_count,
            payload_size_bytes=prepared.payload_size_bytes,
            published_at=dossier.published_at,
        )
        if dossier != expected:
            raise RegistryIntegrityError(
                "unindexed release dossier does not match prepared release"
            )
        self._verify_staging(path, manifest, include_dossier=True, dossier=dossier)
        return self._build_release_record(
            manifest=manifest,
            report=report,
            prepared=prepared,
            dossier_hash=sha256_digest(dossier_bytes),
            published_at=dossier.published_at,
        )

    def _verify_release_record(self, record: ReleaseRecord) -> None:
        expected_relpath = self._package_relpath(record.coordinate)
        if record.package_relpath != expected_relpath:
            raise RegistryIntegrityError(f"release path projection mismatch: {record.release_id}")
        try:
            path = self._package_path(record.coordinate)
            path.resolve(strict=True).relative_to(self._root)
        except (FileNotFoundError, ValueError) as exc:
            raise RegistryIntegrityError(
                f"release package is missing: {record.release_id}"
            ) from exc
        if path.is_symlink() or not path.is_dir():
            raise RegistryIntegrityError(f"release package path is unsafe: {record.release_id}")
        try:
            manifest, report, passed_gates = self._load_release_evidence(
                record.manifest_ref,
                record.judge_report_ref,
                record.release_profile,
                reservation_owner_ref=record.reservation_owner_ref,
            )
        except Exception as exc:
            raise RegistryIntegrityError(
                f"release Judge evidence closure is invalid: {record.release_id}"
            ) from exc
        if passed_gates != tuple(sorted(record.release_profile.required_hard_gates)):
            raise RegistryIntegrityError(f"release hard-gate closure changed: {record.release_id}")
        if self._package_digest(manifest) != record.coordinate.package_digest:
            raise RegistryIntegrityError(f"release digest mismatch: {record.release_id}")
        dossier_bytes = self._read_file(path / _DOSSIER_NAME, "release dossier missing")
        if sha256_digest(dossier_bytes) != record.dossier_hash:
            raise RegistryIntegrityError(f"release dossier changed: {record.release_id}")
        try:
            dossier = PublicationDossier.model_validate_json(dossier_bytes)
        except Exception as exc:
            raise RegistryIntegrityError(
                f"release dossier is invalid: {record.release_id}"
            ) from exc
        expected_dossier = PublicationDossier(
            coordinate=record.coordinate,
            reservation_id=record.reservation_id,
            reservation_owner_ref=record.reservation_owner_ref,
            manifest_ref=record.manifest_ref,
            judge_report_ref=record.judge_report_ref,
            integration_report_ref=record.integration_report_ref,
            release_dossier_ref=record.release_dossier_ref,
            telemetry_summary_ref=record.telemetry_summary_ref,
            candidate_ref=record.candidate_ref,
            release_profile=record.release_profile,
            passed_hard_gates=tuple(sorted(record.release_profile.required_hard_gates)),
            file_count=record.file_count,
            payload_size_bytes=record.payload_size_bytes,
            published_at=record.published_at,
        )
        if dossier != expected_dossier:
            raise RegistryIntegrityError(f"release dossier mismatch: {record.release_id}")
        if (
            report.verdict != "pass"
            or report.candidate_ref != record.candidate_ref
            or report.gate_results != record.gate_results
            or report.budget_usage != record.judge_budget_usage
        ):
            raise RegistryIntegrityError(f"release Judge evidence changed: {record.release_id}")
        if (
            manifest.candidate_ref != record.candidate_ref
            or manifest.design_ref != record.design_ref
            or manifest.integration_report_ref != record.integration_report_ref
            or manifest.release_dossier_ref != record.release_dossier_ref
            or manifest.telemetry_summary_ref != record.telemetry_summary_ref
            or manifest.public_verifier_ref != record.public_verifier_ref
            or manifest.lineage != record.lineage
            or manifest.world_boundary_hash != record.world_boundary_hash
            or manifest.world_spec_hash != record.world_spec_hash
            or len(manifest.files) != record.file_count
            or sum(item.size_bytes for item in manifest.files) != record.payload_size_bytes
        ):
            raise RegistryIntegrityError(
                f"release manifest projection changed: {record.release_id}"
            )
        try:
            self._verify_staging(path, manifest, include_dossier=True, dossier=dossier)
        except UnsafePackageError as exc:
            raise RegistryIntegrityError(f"release tree is unsafe: {record.release_id}") from exc
        self._validate_package_semantics(
            path,
            manifest,
            report=report,
            index=self._load_index(),
            require_released_parents=False,
            integrity_error=True,
        )

    def _validate_package_semantics(
        self,
        root: Path,
        manifest: EnvironmentPackageManifest,
        *,
        report: JudgeReport,
        index: RegistryIndex,
        require_released_parents: bool,
        integrity_error: bool,
    ) -> None:
        """Make ``released`` imply a parseable, identity-closed physical envpkg."""

        try:
            contracts = load_portable_package_contracts(
                root,
                manifest,
                read_file=self._read_file,
            )
            design = self._artifact_store.get_json(
                manifest.design_ref,
                EnvironmentDesign,
            )
            candidate_manifest = self._artifact_store.get_json(
                manifest.candidate_manifest_ref,
                CandidateManifest,
            )
            implementation_lineage = self._artifact_store.get_json(
                manifest.implementation_lineage_ref,
                ImplementationLineage,
            )
            validate_package_release_bindings(
                manifest,
                contracts,
                design=design,
                candidate_manifest=candidate_manifest,
                implementation_lineage=implementation_lineage,
                report=report,
            )
            parents = self._resolve_semantic_parents(
                manifest,
                index=index,
                require_released=require_released_parents,
            )
            validate_package_identity(manifest, contracts, parents=parents)
        except PackageSemanticError as exc:
            message = f"envpkg semantic closure failed: {exc}"
            if integrity_error:
                raise RegistryIntegrityError(message) from exc
            raise ReleaseRejectedError(message) from exc
        except Exception as exc:
            message = "envpkg semantic closure failed: typed artifact input is invalid"
            if integrity_error:
                raise RegistryIntegrityError(message) from exc
            raise ReleaseRejectedError(message) from exc

    def _resolve_semantic_parents(
        self,
        manifest: EnvironmentPackageManifest,
        *,
        index: RegistryIndex,
        require_released: bool,
    ) -> tuple[SemanticParent, ...]:
        refs = manifest.lineage.semantic.semantic_parent_refs
        revisions = [item.revision_id for item in refs]
        if len(set(revisions)) != len(revisions):
            raise PackageSemanticError("SemanticLineage parent refs must be unique")
        parents: list[SemanticParent] = []
        for parent_ref in refs:
            if parent_ref.artifact_type != MANIFEST_ARTIFACT_TYPE:
                raise PackageSemanticError(
                    "SemanticLineage parents must be exact environment package manifests"
                )
            matches = tuple(
                record for record in index.releases if record.manifest_ref == parent_ref
            )
            if len(matches) != 1:
                raise PackageSemanticError(
                    "SemanticLineage parent must resolve to exactly one Registry release"
                )
            record = matches[0]
            if require_released and record.status != "released":
                raise PackageSemanticError(
                    f"SemanticLineage parent is not currently released: {record.status}"
                )
            parent_manifest = self._artifact_store.get_json(
                parent_ref,
                EnvironmentPackageManifest,
            )
            if (
                record.coordinate.package_id != parent_manifest.package_id
                or record.coordinate.version != parent_manifest.version
                or record.world_spec_hash != parent_manifest.world_spec_hash
                or record.world_boundary_hash != parent_manifest.world_boundary_hash
            ):
                raise RegistryIntegrityError(
                    "Registry semantic parent projection differs from its manifest"
                )
            parent_root = self._package_path(record.coordinate)
            parent_contracts = load_portable_package_contracts(
                parent_root,
                parent_manifest,
                read_file=self._read_file,
            )
            parents.append(
                SemanticParent(
                    manifest=parent_manifest,
                    contracts=parent_contracts,
                )
            )
        return tuple(parents)

    @staticmethod
    def _package_digest(manifest: EnvironmentPackageManifest) -> str:
        body = {
            "format": "envpkg-v3",
            "manifest_hash": manifest.content_digest(),
            "files": [
                item.model_dump(mode="json", exclude_none=False)
                for item in sorted(manifest.files, key=lambda entry: entry.path)
            ],
        }
        return sha256_digest(canonical_json_bytes(body))

    def _load_prepared(self, token: str) -> PreparedRelease:
        self._validate_identifier(token, "staging_token")
        raw = self._read_file(self._prepared_path(token), f"prepared release not found: {token}")
        try:
            return PreparedRelease.model_validate_json(raw)
        except Exception as exc:
            raise RegistryIntegrityError(f"invalid prepared release marker: {token}") from exc

    def _discard_prepared(self, prepared: PreparedRelease) -> None:
        expected = f".staging/{prepared.staging_token}"
        if prepared.staging_relpath != expected:
            raise RegistryIntegrityError("prepared staging path is invalid")
        staging = self._safe_path(".staging", prepared.staging_token)
        if staging.exists():
            if staging.is_symlink() or not staging.is_dir():
                raise RegistryIntegrityError("prepared staging tree is unsafe")
            for directory, directory_names, _ in os.walk(
                staging,
                topdown=True,
                followlinks=False,
            ):
                os.chmod(directory, 0o700, follow_symlinks=False)
                for name in directory_names:
                    child = Path(directory) / name
                    if child.is_symlink():
                        raise RegistryIntegrityError("prepared staging tree contains a symlink")
            shutil.rmtree(staging)
        self._prepared_path(prepared.staging_token).unlink(missing_ok=True)

    def _staging_path(self, prepared: PreparedRelease) -> Path:
        expected = f".staging/{prepared.staging_token}"
        if prepared.staging_relpath != expected:
            raise RegistryIntegrityError("prepared staging path is invalid")
        path = self._safe_path(".staging", prepared.staging_token)
        if path.is_symlink() or not path.is_dir():
            raise PreparedReleaseNotFoundError(f"staging tree not found: {prepared.staging_token}")
        return path

    def _require_framework_owner(self, owner_ref: ArtifactRef) -> None:
        revision = self._artifact_store.get_revision(owner_ref)
        if revision.producer not in self._framework_producers:
            raise ReservationConflictError(
                f"reservation owner lacks signed framework provenance: {owner_ref.artifact_id}"
            )

    def _require_active_reservation(
        self,
        supplied: PackageVersionReservation,
        *,
        package_id: str,
        version: str,
    ) -> PackageVersionReservation:
        now = datetime.now(UTC)
        with self._registry_lock(exclusive=True):
            index = self._load_index()
            reservations, expired = self._expire_reservations(index.reservations, now)
            current = self._find_reservation(reservations, supplied.reservation_id)
            self._persist_reservation_projection(index, reservations, expired)
            self._assert_active_reservation(
                current,
                supplied,
                package_id=package_id,
                version=version,
            )
            assert current is not None
            return current

    @staticmethod
    def _assert_active_reservation(
        current: PackageVersionReservation | None,
        supplied: PackageVersionReservation,
        *,
        package_id: str,
        version: str,
    ) -> None:
        if current is None:
            raise ReservationNotFoundError(
                f"Registry reservation not found: {supplied.reservation_id}"
            )
        if current.owner_ref != supplied.owner_ref:
            raise ReservationConflictError("reservation belongs to a different owner")
        if current.status == "expired":
            raise ReservationExpiredError(f"Registry reservation expired: {current.reservation_id}")
        if current.status != "active":
            raise ReservationConflictError(f"Registry reservation is not active: {current.status}")
        if current.package_id != package_id or current.version != version:
            raise ReservationConflictError("manifest coordinate does not match its reservation")
        if current != supplied:
            raise ReservationConflictError(
                "supplied reservation no longer matches its durable state"
            )

    @staticmethod
    def _find_reservation(
        reservations: Sequence[PackageVersionReservation],
        reservation_id: str,
    ) -> PackageVersionReservation | None:
        return next(
            (item for item in reservations if item.reservation_id == reservation_id),
            None,
        )

    @staticmethod
    def _find_active_reservation(
        reservations: Sequence[PackageVersionReservation],
        package_id: str,
        version: str,
    ) -> PackageVersionReservation | None:
        return next(
            (
                item
                for item in reservations
                if item.status == "active"
                and item.package_id == package_id
                and item.version == version
            ),
            None,
        )

    @staticmethod
    def _expire_reservations(
        reservations: Sequence[PackageVersionReservation],
        now: datetime,
    ) -> tuple[tuple[PackageVersionReservation, ...], bool]:
        changed = False
        values: list[PackageVersionReservation] = []
        for reservation in reservations:
            if reservation.status == "active" and reservation.expires_at <= now:
                changed = True
                values.append(
                    reservation.model_copy(
                        update={
                            "status": "expired",
                            "updated_at": now,
                            "terminal_at": now,
                        }
                    )
                )
            else:
                values.append(reservation)
        return tuple(values), changed

    def _persist_reservation_projection(
        self,
        index: RegistryIndex,
        reservations: Sequence[PackageVersionReservation],
        changed: bool,
    ) -> None:
        if not changed:
            return
        self._write_index(
            RegistryIndex(
                revision=index.revision + 1,
                releases=index.releases,
                reservations=self._sorted_reservations(reservations),
            )
        )

    @staticmethod
    def _prepared_matches_release(
        prepared: PreparedRelease,
        reservation: PackageVersionReservation,
        release: ReleaseRecord | None,
    ) -> bool:
        return bool(
            release is not None
            and reservation.status == "consumed"
            and release.reservation_id == prepared.reservation_id
            and release.reservation_owner_ref == prepared.reservation_owner_ref
            and release.coordinate == prepared.coordinate
            and release.manifest_ref == prepared.manifest_ref
            and release.judge_report_ref == prepared.judge_report_ref
            and release.integration_report_ref == prepared.integration_report_ref
            and release.release_dossier_ref == prepared.release_dossier_ref
            and release.telemetry_summary_ref == prepared.telemetry_summary_ref
            and release.release_profile == prepared.release_profile
            and release.file_count == prepared.file_count
            and release.payload_size_bytes == prepared.payload_size_bytes
            and reservation.manifest_ref == prepared.manifest_ref
            and reservation.package_digest == prepared.coordinate.package_digest
            and reservation.release_id == release.release_id
        )

    @staticmethod
    def _find_record(index: RegistryIndex, package_id: str, version: str) -> ReleaseRecord | None:
        return next(
            (
                item
                for item in index.releases
                if item.coordinate.package_id == package_id and item.coordinate.version == version
            ),
            None,
        )

    @staticmethod
    def _sorted_records(records: Iterable[ReleaseRecord]) -> tuple[ReleaseRecord, ...]:
        return tuple(
            sorted(
                records,
                key=lambda item: (
                    item.coordinate.package_id,
                    item.coordinate.version,
                    item.coordinate.package_digest,
                ),
            )
        )

    @staticmethod
    def _sorted_reservations(
        reservations: Iterable[PackageVersionReservation],
    ) -> tuple[PackageVersionReservation, ...]:
        return tuple(
            sorted(
                reservations,
                key=lambda item: (
                    item.package_id,
                    item.version,
                    item.created_at,
                    item.reservation_id,
                ),
            )
        )

    @property
    def _index_path(self) -> Path:
        return self._safe_path("index.json")

    def _load_index(self) -> RegistryIndex:
        raw = self._read_file(self._index_path, "Registry index is missing")
        try:
            return RegistryIndex.model_validate_json(raw)
        except Exception as exc:
            raise RegistryIntegrityError("Registry index is invalid") from exc

    def _write_index(self, index: RegistryIndex) -> None:
        self._atomic_replace(self._index_path, index.stable_json_bytes(), mode=0o600)

    def _append_event(
        self,
        *,
        event_type: Literal[
            "release_published",
            "release_quarantined",
            "release_superseded",
        ],
        coordinate: PackageCoordinate,
        previous_status: ReleaseStatus | None,
        new_status: ReleaseStatus,
        actor: str,
        reason_code: str | None = None,
        superseded_by: PackageCoordinate | None = None,
    ) -> RegistryEvent:
        occurred_at = datetime.now(UTC)
        body = {
            "event_type": event_type,
            "coordinate": coordinate.model_dump(mode="json"),
            "previous_status": previous_status,
            "new_status": new_status,
            "occurred_at": occurred_at.isoformat(),
            "actor": actor,
            "reason_code": reason_code,
            "superseded_by": (
                superseded_by.model_dump(mode="json") if superseded_by is not None else None
            ),
        }
        event_id = f"event_{sha256_digest(canonical_json_bytes(body)).removeprefix('sha256:')}"
        event = RegistryEvent(
            event_id=event_id,
            event_type=event_type,
            coordinate=coordinate,
            previous_status=previous_status,
            new_status=new_status,
            occurred_at=occurred_at,
            actor=actor,
            reason_code=reason_code,
            superseded_by=superseded_by,
        )
        path = self._safe_path("events.jsonl")
        flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags, 0o600)
        try:
            self._write_all(descriptor, event.stable_json_bytes() + b"\n")
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        return event

    def _package_path(self, coordinate: PackageCoordinate) -> Path:
        digest = coordinate.package_digest.removeprefix("sha256:")
        return self._safe_path(
            "packages",
            coordinate.package_id,
            coordinate.version,
            digest,
        )

    @staticmethod
    def _package_relpath(coordinate: PackageCoordinate) -> str:
        digest = coordinate.package_digest.removeprefix("sha256:")
        return f"packages/{coordinate.package_id}/{coordinate.version}/{digest}"

    def _existing_digest_directories(self, package_id: str, version: str) -> set[str]:
        directory = self._safe_path("packages", package_id, version)
        if not directory.exists():
            return set()
        if directory.is_symlink() or not directory.is_dir():
            raise RegistryIntegrityError("package version path is unsafe")
        result: set[str] = set()
        for child in directory.iterdir():
            if (
                child.is_symlink()
                or not child.is_dir()
                or re.fullmatch(r"[0-9a-f]{64}", child.name) is None
            ):
                raise RegistryIntegrityError(f"unexpected package version entry: {child.name}")
            result.add(child.name)
        return result

    def _prepared_path(self, token: str) -> Path:
        return self._safe_path("prepared", f"{token}.json")

    def _validate_actor(self, actor: str) -> None:
        self._validate_identifier(actor, "actor")
        if actor not in self._framework_producers:
            raise ReleaseRejectedError(f"actor is not framework-authorized: {actor}")

    @staticmethod
    def _validate_identifier(value: str, label: str) -> None:
        if _IDENTIFIER.fullmatch(value) is None:
            raise ValueError(f"invalid {label}: {value!r}")

    @staticmethod
    def _validate_package_component(value: str, label: str) -> None:
        if _PACKAGE_COMPONENT.fullmatch(value) is None or value in {".", ".."}:
            raise UnsafePackageError(f"invalid {label} for Registry path: {value!r}")

    @staticmethod
    def _validate_reservation_ttl(value: float) -> float:
        if isinstance(value, bool):
            raise ValueError("reservation TTL must be a positive number of seconds")
        try:
            ttl = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError("reservation TTL must be a positive number of seconds") from exc
        if not math.isfinite(ttl) or not 0 < ttl <= _MAX_RESERVATION_TTL_SECONDS:
            raise ValueError(
                "reservation TTL must be greater than zero and no more than seven days"
            )
        return ttl

    @contextmanager
    def _registry_lock(self, *, exclusive: bool) -> Iterator[None]:
        path = self._safe_path(".registry.lock")
        flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags, 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
            yield
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)

    def _safe_path(self, *parts: str) -> Path:
        if not parts or any(
            part in {"", ".", ".."} or "/" in part or "\\" in part for part in parts
        ):
            raise RegistryIntegrityError("unsafe Registry path component")
        path = self._root.joinpath(*parts)
        current = self._root
        for part in parts:
            current = current / part
            if current.exists() or current.is_symlink():
                if current.is_symlink():
                    raise RegistryIntegrityError(f"Registry path contains a symlink: {current}")
        try:
            path.resolve(strict=False).relative_to(self._root)
        except ValueError as exc:
            raise RegistryIntegrityError("Registry path escapes its root") from exc
        return path

    def _ensure_directory(self, path: Path) -> None:
        try:
            relative = path.relative_to(self._root)
        except ValueError as exc:
            raise RegistryIntegrityError("Registry directory escapes root") from exc
        current = self._root
        for part in relative.parts:
            current = current / part
            if current.exists() or current.is_symlink():
                if current.is_symlink() or not current.is_dir():
                    raise RegistryIntegrityError(f"unsafe Registry directory: {current}")
            else:
                current.mkdir(mode=0o700)

    def _atomic_create(self, target: Path, content: bytes, *, mode: int) -> bool:
        self._ensure_directory(target.parent)
        temporary = self._safe_path(".tmp", f"{uuid.uuid4().hex}.tmp")
        self._exclusive_write(temporary, content, mode)
        try:
            try:
                os.link(temporary, target, follow_symlinks=False)
                created = True
            except FileExistsError:
                existing = self._read_file(target, f"existing file disappeared: {target.name}")
                if existing != content:
                    raise RegistryIntegrityError(
                        f"immutable Registry file already has different content: {target.name}"
                    ) from None
                created = False
            self._fsync_directory(target.parent)
            return created
        finally:
            temporary.unlink(missing_ok=True)

    def _atomic_replace(self, target: Path, content: bytes, *, mode: int) -> None:
        self._ensure_directory(target.parent)
        temporary = self._safe_path(".tmp", f"{uuid.uuid4().hex}.tmp")
        self._exclusive_write(temporary, content, mode)
        try:
            os.replace(temporary, target)
            self._fsync_directory(target.parent)
        finally:
            temporary.unlink(missing_ok=True)

    @staticmethod
    def _exclusive_write(path: Path, content: bytes, mode: int) -> None:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags, 0o600)
        try:
            EnvironmentRegistry._write_all(descriptor, content)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        os.chmod(path, mode, follow_symlinks=False)

    @staticmethod
    def _write_all(descriptor: int, content: bytes) -> None:
        view = memoryview(content)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise RegistryIntegrityError("short write while persisting Registry data")
            view = view[written:]

    @staticmethod
    def _read_file(path: Path, missing_message: str) -> bytes:
        if path.is_symlink():
            raise RegistryIntegrityError(f"refusing to read Registry symlink: {path}")
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(path, flags)
        except FileNotFoundError as exc:
            if "prepared release" in missing_message:
                raise PreparedReleaseNotFoundError(missing_message) from exc
            raise RegistryIntegrityError(missing_message) from exc
        except OSError as exc:
            raise RegistryIntegrityError(f"cannot safely open Registry file: {path}") from exc
        try:
            chunks: list[bytes] = []
            while chunk := os.read(descriptor, 1024 * 1024):
                chunks.append(chunk)
            return b"".join(chunks)
        finally:
            os.close(descriptor)

    @staticmethod
    def _fsync_directory(path: Path) -> None:
        descriptor = os.open(path, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    @staticmethod
    def _freeze_tree(root: Path, files: tuple[PackageFile, ...]) -> None:
        executable = {item.path: item.executable for item in files}
        for directory, directory_names, file_names in os.walk(
            root, topdown=False, followlinks=False
        ):
            base = Path(directory)
            for name in file_names:
                path = base / name
                relative = path.relative_to(root).as_posix()
                mode = 0o500 if executable.get(relative, False) else 0o400
                os.chmod(path, mode, follow_symlinks=False)
            for name in directory_names:
                os.chmod(base / name, 0o500, follow_symlinks=False)
            if base != root:
                os.chmod(base, 0o500, follow_symlinks=False)


__all__ = [
    "EnvironmentRegistry",
    "JUDGE_REPORT_ARTIFACT_TYPE",
    "MANIFEST_ARTIFACT_TYPE",
    "ParentNotEligibleError",
    "PreparedReleaseNotFoundError",
    "RegistryError",
    "RegistryIntegrityError",
    "ReservationConflictError",
    "ReservationExpiredError",
    "ReservationNotFoundError",
    "ReleaseConflictError",
    "ReleaseNotFoundError",
    "ReleaseRejectedError",
    "UnsafePackageError",
]
