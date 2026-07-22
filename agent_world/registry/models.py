"""Durable Registry projections and release metadata.

These are Registry-internal v2 records.  They intentionally contain references
and redacted gate summaries, never sealed cases, model transcripts, credentials,
or candidate workspace paths.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, field_validator, model_validator

from agent_world.contracts import (
    ArtifactRef,
    BudgetUsage,
    ContentHash,
    GateResult,
    Identifier,
    NonEmptyStr,
    PackageLineage,
    ReleaseProfile,
    V2Contract,
)

ReleaseStatus = Literal["released", "quarantined", "superseded"]
ReservationStatus = Literal["active", "consumed", "cancelled", "expired"]


def _validate_version(value: str) -> str:
    allowed = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789._:+-")
    if len(value) > 160 or not value[0].isalnum() or not set(value) <= allowed:
        raise ValueError("version is not safe as a Registry path component")
    return value


class PackageCoordinate(V2Contract):
    package_id: Identifier
    version: NonEmptyStr
    package_digest: ContentHash

    @field_validator("version")
    @classmethod
    def validate_version(cls, value: str) -> str:
        return _validate_version(value)


class PackageVersionReservation(V2Contract):
    """Durable exclusive claim over one package_id/version coordinate."""

    reservation_id: Identifier
    package_id: Identifier
    version: NonEmptyStr
    owner_ref: ArtifactRef
    status: ReservationStatus
    framework_actor: Identifier
    created_at: AwareDatetime
    updated_at: AwareDatetime
    expires_at: AwareDatetime
    terminal_at: AwareDatetime | None = None
    manifest_ref: ArtifactRef | None = None
    package_digest: ContentHash | None = None
    release_id: Identifier | None = None

    @field_validator("version")
    @classmethod
    def validate_version(cls, value: str) -> str:
        return _validate_version(value)

    @model_validator(mode="after")
    def validate_lifecycle(self) -> PackageVersionReservation:
        if self.expires_at <= self.created_at:
            raise ValueError("reservation expires_at must be after created_at")
        if self.updated_at < self.created_at:
            raise ValueError("reservation updated_at cannot precede created_at")
        publication = (self.manifest_ref, self.package_digest, self.release_id)
        if self.status == "active":
            if self.terminal_at is not None or any(value is not None for value in publication):
                raise ValueError("active reservation cannot contain terminal publication fields")
        elif self.status == "consumed":
            if self.terminal_at is None or any(value is None for value in publication):
                raise ValueError("consumed reservation requires complete publication fields")
        elif self.terminal_at is None or any(value is not None for value in publication):
            raise ValueError(
                "cancelled/expired reservation requires terminal_at and forbids publication fields"
            )
        if self.terminal_at is not None and self.updated_at != self.terminal_at:
            raise ValueError("terminal reservation updated_at must equal terminal_at")
        return self


class PublicationDossier(V2Contract):
    """Registry-authored physical publication receipt; excluded from its own digest."""

    coordinate: PackageCoordinate
    reservation_id: Identifier
    reservation_owner_ref: ArtifactRef
    manifest_ref: ArtifactRef
    judge_report_ref: ArtifactRef
    integration_report_ref: ArtifactRef
    release_dossier_ref: ArtifactRef
    telemetry_summary_ref: ArtifactRef
    candidate_ref: ArtifactRef
    release_profile: ReleaseProfile
    passed_hard_gates: tuple[Identifier, ...]
    file_count: Annotated[int, Field(ge=1)]
    payload_size_bytes: Annotated[int, Field(ge=0)]
    scan_policy: Literal["agent-world.registry.v2"] = "agent-world.registry.v2"
    published_at: AwareDatetime


class ReleaseRecord(V2Contract):
    release_id: Identifier
    coordinate: PackageCoordinate
    reservation_id: Identifier
    reservation_owner_ref: ArtifactRef
    status: ReleaseStatus
    package_relpath: NonEmptyStr
    manifest_ref: ArtifactRef
    judge_report_ref: ArtifactRef
    integration_report_ref: ArtifactRef
    release_dossier_ref: ArtifactRef
    telemetry_summary_ref: ArtifactRef
    candidate_ref: ArtifactRef
    design_ref: ArtifactRef
    public_verifier_ref: ArtifactRef
    release_profile: ReleaseProfile
    lineage: PackageLineage
    world_boundary_hash: ContentHash
    world_spec_hash: ContentHash
    gate_results: tuple[GateResult, ...]
    judge_budget_usage: BudgetUsage
    file_count: Annotated[int, Field(ge=1)]
    payload_size_bytes: Annotated[int, Field(ge=0)]
    dossier_hash: ContentHash
    published_at: AwareDatetime
    status_changed_at: AwareDatetime
    superseded_by: PackageCoordinate | None = None

    @model_validator(mode="after")
    def validate_status(self) -> ReleaseRecord:
        if self.status == "superseded" and self.superseded_by is None:
            raise ValueError("superseded release requires superseded_by")
        if self.status != "superseded" and self.superseded_by is not None:
            raise ValueError("superseded_by is only valid for superseded releases")
        digest = self.coordinate.package_digest.removeprefix("sha256:")
        expected_id = f"release_{digest}"
        expected_path = f"packages/{self.coordinate.package_id}/{self.coordinate.version}/{digest}"
        if self.release_id != expected_id or self.package_relpath != expected_path:
            raise ValueError("release id/path does not match its content-addressed coordinate")
        return self


class PreparedRelease(V2Contract):
    staging_token: Identifier
    staging_relpath: NonEmptyStr
    coordinate: PackageCoordinate
    reservation_id: Identifier
    reservation_owner_ref: ArtifactRef
    manifest_ref: ArtifactRef
    judge_report_ref: ArtifactRef
    integration_report_ref: ArtifactRef
    release_dossier_ref: ArtifactRef
    telemetry_summary_ref: ArtifactRef
    release_profile: ReleaseProfile
    passed_hard_gates: tuple[Identifier, ...]
    file_count: Annotated[int, Field(ge=1)]
    payload_size_bytes: Annotated[int, Field(ge=0)]
    framework_actor: Identifier
    prepared_at: AwareDatetime

    @model_validator(mode="after")
    def validate_staging_path(self) -> PreparedRelease:
        if self.staging_relpath != f".staging/{self.staging_token}":
            raise ValueError("prepared staging path must derive from its token")
        return self


class RegistryIndex(V2Contract):
    revision: Annotated[int, Field(ge=0)] = 0
    releases: tuple[ReleaseRecord, ...] = ()
    reservations: tuple[PackageVersionReservation, ...] = ()

    @model_validator(mode="after")
    def validate_authority_index(self) -> RegistryIndex:
        keys = [(item.coordinate.package_id, item.coordinate.version) for item in self.releases]
        if len(set(keys)) != len(keys):
            raise ValueError("Registry may contain only one digest per package_id/version")
        reservation_ids = [item.reservation_id for item in self.reservations]
        if len(set(reservation_ids)) != len(reservation_ids):
            raise ValueError("Registry reservation ids must be unique")
        active_keys = [
            (item.package_id, item.version) for item in self.reservations if item.status == "active"
        ]
        if len(set(active_keys)) != len(active_keys):
            raise ValueError("Registry may contain only one active reservation per coordinate")
        release_by_key = {
            (item.coordinate.package_id, item.coordinate.version): item for item in self.releases
        }
        reservation_by_id = {item.reservation_id: item for item in self.reservations}
        for key in active_keys:
            if key in release_by_key:
                raise ValueError("released coordinates cannot retain an active reservation")
        for release in self.releases:
            reservation = reservation_by_id.get(release.reservation_id)
            if reservation is None or reservation.status != "consumed":
                raise ValueError("every release must bind one consumed reservation")
            if (
                reservation.owner_ref != release.reservation_owner_ref
                or reservation.package_id != release.coordinate.package_id
                or reservation.version != release.coordinate.version
                or reservation.manifest_ref != release.manifest_ref
                or reservation.package_digest != release.coordinate.package_digest
                or reservation.release_id != release.release_id
            ):
                raise ValueError("release does not match its consumed reservation")
        for reservation in self.reservations:
            if reservation.status != "consumed":
                continue
            matching_release = release_by_key.get((reservation.package_id, reservation.version))
            if (
                matching_release is None
                or matching_release.reservation_id != reservation.reservation_id
            ):
                raise ValueError("consumed reservation requires its exact release")
        return self


class RegistryEvent(V2Contract):
    event_id: Identifier
    event_type: Literal["release_published", "release_quarantined", "release_superseded"]
    coordinate: PackageCoordinate
    previous_status: ReleaseStatus | None
    new_status: ReleaseStatus
    occurred_at: AwareDatetime
    actor: Identifier
    reason_code: Identifier | None = None
    superseded_by: PackageCoordinate | None = None


class EnvironmentPoolSnapshot(V2Contract):
    snapshot_id: Identifier
    registry_revision: Annotated[int, Field(ge=0)]
    created_at: AwareDatetime
    releases: tuple[ReleaseRecord, ...]

    @model_validator(mode="after")
    def unique_releases(self) -> EnvironmentPoolSnapshot:
        release_ids = [item.release_id for item in self.releases]
        if len(set(release_ids)) != len(release_ids):
            raise ValueError("pool snapshot contains duplicate releases")
        return self


__all__ = [
    "EnvironmentPoolSnapshot",
    "PackageCoordinate",
    "PackageVersionReservation",
    "PreparedRelease",
    "RegistryEvent",
    "RegistryIndex",
    "PublicationDossier",
    "ReleaseRecord",
    "ReleaseStatus",
    "ReservationStatus",
]
