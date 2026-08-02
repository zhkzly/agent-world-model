"""Closed Judge evidence for static and dependency-chain assurance.

Candidates never author these contracts.  The framework derives them from the
manifest-bound source tree, the clean uv installation, and physical metadata.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, model_validator

from .base import ArtifactRef, ContentHash, Identifier, NonEmptyStr, V2Contract

MAX_PUBLIC_TESTS = 32


class StaticDiagnosticLocation(V2Contract):
    """One safe source coordinate for a framework-owned static-policy finding."""

    line: Annotated[int, Field(ge=1)]
    category: Literal[
        "framework_private_identifier",
        "fixture_registry",
        "test_double",
    ]


class StaticFileEvidence(V2Contract):
    path: NonEmptyStr
    role: Identifier
    content_hash: ContentHash
    size_bytes: Annotated[int, Field(ge=0)]
    media_kind: Literal["python", "json", "toml", "text", "other"]
    utf8_valid: bool | None = None
    ast_valid: bool | None = None
    compile_valid: bool | None = None
    parse_valid: bool | None = None
    scan_passed: bool
    failure_codes: tuple[Identifier, ...] = ()
    diagnostic_locations: tuple[StaticDiagnosticLocation, ...] = ()

    @model_validator(mode="after")
    def success_has_no_failure_codes(self) -> StaticFileEvidence:
        checks = (
            self.utf8_valid,
            self.ast_valid,
            self.compile_valid,
            self.parse_valid,
            self.scan_passed,
        )
        if self.failure_codes and all(item is not False for item in checks):
            raise ValueError("static file failure codes require a failed check")
        if self.diagnostic_locations and "static_forbidden_pattern" not in self.failure_codes:
            raise ValueError("static diagnostic locations require a forbidden-pattern failure")
        return self


class PublicTestExecution(V2Contract):
    path: NonEmptyStr
    public_test_ref: ArtifactRef
    argv: Annotated[tuple[NonEmptyStr, ...], Field(min_length=2, max_length=4)]
    exit_code: int | None
    duration_ms: Annotated[int, Field(ge=0)]
    stdout_hash: ContentHash
    stderr_hash: ContentHash
    stdout_truncated: bool
    stderr_truncated: bool
    network_policy: Literal["disabled"] = "disabled"
    workspace_policy: Literal["read-only"] = "read-only"
    passed: bool
    failure_class: Identifier | None = None

    @model_validator(mode="after")
    def passing_execution_is_clean(self) -> PublicTestExecution:
        if self.passed and (
            self.exit_code != 0
            or self.stdout_truncated
            or self.stderr_truncated
            or self.failure_class is not None
        ):
            raise ValueError("passing public test evidence must describe a clean execution")
        return self


class StaticAssuranceEvidence(V2Contract):
    evidence_id: Identifier
    candidate_ref: ArtifactRef
    candidate_source_tree_digest: ContentHash
    status: Literal["pass", "fail"]
    files: Annotated[tuple[StaticFileEvidence, ...], Field(min_length=1)]
    public_tests: tuple[PublicTestExecution, ...] = ()
    forbidden_pattern_scan_passed: bool
    secret_scan_passed: bool
    strict_data_parse_passed: bool
    python_compile_passed: bool
    failure_codes: tuple[Identifier, ...] = ()
    # These are source-path relationships only.  They deliberately retain no
    # Candidate text, but make a component-visibility failure independently
    # actionable for an authorized Builder correction.
    component_import_violations: tuple[NonEmptyStr, ...] = ()

    @model_validator(mode="after")
    def status_matches_checks(self) -> StaticAssuranceEvidence:
        passed = (
            self.forbidden_pattern_scan_passed
            and self.secret_scan_passed
            and self.strict_data_parse_passed
            and self.python_compile_passed
            and bool(self.public_tests)
            and all(item.passed for item in self.public_tests)
            and not self.failure_codes
        )
        if (self.status == "pass") != passed:
            raise ValueError("static assurance status does not match framework observations")
        return self


class LockedWheelEvidence(V2Contract):
    url: NonEmptyStr
    content_hash: ContentHash
    size_bytes: Annotated[int, Field(gt=0)]


class LockedComponentEvidence(V2Contract):
    name: NonEmptyStr
    normalized_name: Identifier
    version: NonEmptyStr
    source_kind: Literal["virtual-root", "registry"]
    registry_url: NonEmptyStr | None = None
    wheels: tuple[LockedWheelEvidence, ...] = ()
    dependency_names: tuple[Identifier, ...] = ()

    @model_validator(mode="after")
    def source_has_required_provenance(self) -> LockedComponentEvidence:
        if self.source_kind == "virtual-root":
            if self.registry_url is not None or self.wheels:
                raise ValueError("virtual root cannot declare registry wheels")
        elif self.registry_url is None or not self.wheels:
            raise ValueError("registry component requires registry URL and locked wheels")
        return self


class LicenseMetadataEvidence(V2Contract):
    subject_name: NonEmptyStr
    subject_version: NonEmptyStr
    status: Literal["declared", "unknown"]
    metadata_source: Literal[
        "pyproject-license-expression",
        "pyproject-license-file",
        "pyproject-license-text",
        "core-metadata-license-expression",
        "core-metadata-license-field",
        "missing",
    ]
    declared_value: NonEmptyStr | None = None
    metadata_path: NonEmptyStr
    metadata_hash: ContentHash

    @model_validator(mode="after")
    def unknown_never_invents_a_value(self) -> LicenseMetadataEvidence:
        if self.status == "declared" and self.declared_value is None:
            raise ValueError("declared license metadata requires an explicit value")
        if self.status == "unknown" and self.declared_value is not None:
            raise ValueError("unknown license metadata cannot invent a value")
        return self


class InstalledComponentEvidence(V2Contract):
    name: NonEmptyStr
    normalized_name: Identifier
    version: NonEmptyStr
    metadata_path: NonEmptyStr
    metadata_hash: ContentHash
    requires_dist: tuple[NonEmptyStr, ...] = ()
    license: LicenseMetadataEvidence


class CandidateLicenseFileEvidence(V2Contract):
    path: NonEmptyStr
    content_hash: ContentHash
    size_bytes: Annotated[int, Field(gt=0)]


class SupplyChainEvidence(V2Contract):
    evidence_id: Identifier
    candidate_ref: ArtifactRef
    implementation_lineage_ref: ArtifactRef
    candidate_source_tree_digest: ContentHash
    status: Literal["pass", "fail"]
    pyproject_hash: ContentHash
    uv_lock_hash: ContentHash
    lineage_dependency_lock_hash: ContentHash | None = None
    installed_tree_hash: ContentHash
    root_project_name: NonEmptyStr | None = None
    root_project_version: NonEmptyStr | None = None
    root_license: LicenseMetadataEvidence | None = None
    candidate_license_files: tuple[CandidateLicenseFileEvidence, ...] = ()
    locked_components: tuple[LockedComponentEvidence, ...] = ()
    installed_components: tuple[InstalledComponentEvidence, ...] = ()
    approved_registry_urls: tuple[NonEmptyStr, ...]
    lock_install_closed: bool
    dependency_policy_passed: bool
    license_metadata_complete: bool
    install_network_policy: Literal["disabled"] = "disabled"
    failure_codes: tuple[Identifier, ...] = ()

    @model_validator(mode="after")
    def status_matches_supply_chain(self) -> SupplyChainEvidence:
        passed = (
            self.lineage_dependency_lock_hash == self.uv_lock_hash
            and bool(self.candidate_license_files)
            and self.root_license is not None
            and self.root_license.status == "declared"
            and all(item.license.status == "declared" for item in self.installed_components)
            and self.lock_install_closed
            and self.dependency_policy_passed
            and self.license_metadata_complete
            and not self.failure_codes
        )
        if (self.status == "pass") != passed:
            raise ValueError("supply-chain status does not match framework observations")
        return self


__all__ = [
    "CandidateLicenseFileEvidence",
    "InstalledComponentEvidence",
    "LicenseMetadataEvidence",
    "LockedComponentEvidence",
    "LockedWheelEvidence",
    "MAX_PUBLIC_TESTS",
    "PublicTestExecution",
    "StaticAssuranceEvidence",
    "StaticDiagnosticLocation",
    "StaticFileEvidence",
    "SupplyChainEvidence",
]
