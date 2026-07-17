"""Portable envpkg v3 release contracts and deterministic framework payloads.

The package compiler in this module has no release authority.  It projects exact
Design, Build and Judge facts into portable, closed documents; Registry reparses
and cross-binds those physical bytes before a release can exist.
"""

from __future__ import annotations

import json
import re
import tomllib
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Annotated, Literal

from pydantic import AwareDatetime, Field, field_validator, model_validator

from .base import (
    ArtifactRef,
    ContentHash,
    Identifier,
    NonEmptyStr,
    V2Contract,
    canonical_json_bytes,
    sha256_digest,
)
from .design import EnvironmentDesign, RewardSpec
from .jobs import BudgetUsage
from .judging import IntegrationReport, JudgeReport
from .lineage import ImplementationLineage, PackageLineage, SemanticLineage
from .runtime import (
    CURRICULUM_PACKAGE_PATH,
    RULE_IR_PACKAGE_PATH,
    TASK_MATERIALIZER_PROTOCOL_PACKAGE_PATH,
    WORLD_SPEC_PACKAGE_PATH,
    PublicSelfCheckDescriptor,
    RuntimeLaunch,
    TaskMaterializerDescriptor,
)
from .world import FidelityStatement

ENVPKG_METADATA_PACKAGE_PATH: Literal["envpkg.toml"] = "envpkg.toml"
PROVENANCE_PACKAGE_PATH: Literal["evidence/provenance.json"] = (
    "evidence/provenance.json"
)
ASSURANCE_PACKAGE_PATH: Literal["evidence/assurance.json"] = "evidence/assurance.json"
FIDELITY_PACKAGE_PATH: Literal["evidence/fidelity.json"] = "evidence/fidelity.json"
SBOM_PACKAGE_PATH: Literal["sbom/sbom.json"] = "sbom/sbom.json"
PYPROJECT_PACKAGE_PATH: Literal["pyproject.toml"] = "pyproject.toml"
UV_LOCK_PACKAGE_PATH: Literal["uv.lock"] = "uv.lock"

type FrameworkPackageRole = Literal[
    "package_metadata",
    "world_spec",
    "materializer_protocol",
    "curriculum",
    "rule_ir",
    "provenance",
    "assurance",
    "fidelity",
    "sbom",
]

FRAMEWORK_PACKAGE_LAYOUT: tuple[tuple[str, FrameworkPackageRole], ...] = (
    (ENVPKG_METADATA_PACKAGE_PATH, "package_metadata"),
    (WORLD_SPEC_PACKAGE_PATH, "world_spec"),
    (TASK_MATERIALIZER_PROTOCOL_PACKAGE_PATH, "materializer_protocol"),
    (CURRICULUM_PACKAGE_PATH, "curriculum"),
    (RULE_IR_PACKAGE_PATH, "rule_ir"),
    (PROVENANCE_PACKAGE_PATH, "provenance"),
    (ASSURANCE_PACKAGE_PATH, "assurance"),
    (FIDELITY_PACKAGE_PATH, "fidelity"),
    (SBOM_PACKAGE_PATH, "sbom"),
)
_FRAMEWORK_ROLE_BY_PATH: dict[str, str] = dict(FRAMEWORK_PACKAGE_LAYOUT)
_FRAMEWORK_PATH_BY_ROLE: dict[str, str] = {
    role: path for path, role in FRAMEWORK_PACKAGE_LAYOUT
}
_FRAMEWORK_ROLES = frozenset(_FRAMEWORK_PATH_BY_ROLE)

_CANDIDATE_SOURCE_ROLES = frozenset(
    {
        "runtime",
        "task_materializer",
        "public_verifier",
        "dependency_lock",
        "documentation",
        "public_test",
        "configuration",
        "license",
    }
)


@dataclass(frozen=True, slots=True)
class FrameworkPackagePayload:
    """One framework-owned physical envpkg file ready for staging."""

    path: str
    role: FrameworkPackageRole
    content: bytes

    def descriptor(self) -> PackageFile:
        return PackageFile(
            path=self.path,
            content_hash=sha256_digest(self.content),
            size_bytes=len(self.content),
            role=self.role,
        )


class TrustedEvaluatorSpec(V2Contract):
    """Portable data consumed by the framework-owned closed Rule interpreter."""

    protocol: Literal["agent-world.trusted-evaluator.v2"] = (
        "agent-world.trusted-evaluator.v2"
    )
    world_spec_hash: ContentHash
    curriculum_hash: ContentHash
    reward: RewardSpec
    task_goal_source: Literal["task_goal"] = "task_goal"
    authoritative_outputs: tuple[
        Literal["reward", "terminated", "succeeded", "failed"], ...
    ] = ("reward", "terminated", "succeeded", "failed")
    runtime_reward_policy: Literal["ignore_diagnostic_values"] = "ignore_diagnostic_values"

    @classmethod
    def from_design(cls, design: EnvironmentDesign) -> TrustedEvaluatorSpec:
        return cls(
            world_spec_hash=design.world_spec.content_digest(),
            curriculum_hash=design.curriculum.content_digest(),
            reward=design.reward,
        )


class TrustedEvaluatorDescriptor(V2Contract):
    """Package-relative inputs sufficient to re-run trusted evaluation."""

    protocol: Literal["agent-world.trusted-evaluator.v2"] = (
        "agent-world.trusted-evaluator.v2"
    )
    rule_ir_path: Literal["world/rule_ir.json"] = "world/rule_ir.json"
    world_spec_path: Literal["world/world_spec.json"] = "world/world_spec.json"
    curriculum_path: Literal["tasks/curriculum.json"] = "tasks/curriculum.json"
    materializer_protocol_path: Literal["tasks/materializer_protocol.json"] = (
        "tasks/materializer_protocol.json"
    )
    interpreter: Literal["agent_world.closed_rule_ir.v2"] = "agent_world.closed_rule_ir.v2"
    task_goal_field: Literal["evaluator_goal"] = "evaluator_goal"
    reward_authority: Literal["trusted_evaluator"] = "trusted_evaluator"


class PackageFile(V2Contract):
    path: NonEmptyStr
    content_hash: ContentHash
    size_bytes: Annotated[int, Field(ge=0)]
    role: Literal[
        "runtime",
        "task_materializer",
        "public_verifier",
        "manifest",
        "dependency_lock",
        "documentation",
        "public_test",
        "configuration",
        "license",
        "package_metadata",
        "world_spec",
        "materializer_protocol",
        "curriculum",
        "rule_ir",
        "provenance",
        "assurance",
        "fidelity",
        "sbom",
    ]
    executable: bool = False

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        path = PurePosixPath(value)
        if path.is_absolute() or value in {"", ".", ".."} or ".." in path.parts or "\\" in value:
            raise ValueError("package file path must be a package-relative POSIX path")
        return value


def candidate_source_tree_digest(files: tuple[PackageFile, ...]) -> ContentHash:
    """Digest the complete candidate-authored source tree declared by a package."""

    candidate_files = tuple(
        sorted(
            (item for item in files if item.role in _CANDIDATE_SOURCE_ROLES),
            key=lambda item: item.path,
        )
    )
    if not candidate_files:
        raise ValueError("candidate source tree must contain at least one candidate file")
    paths = tuple(item.path for item in candidate_files)
    if len(set(paths)) != len(paths):
        raise ValueError("candidate source tree paths must be unique")
    return sha256_digest(
        canonical_json_bytes(
            [item.model_dump(mode="json", exclude_none=False) for item in candidate_files]
        )
    )


type ProvenanceInputRole = Literal[
    "job",
    "request",
    "design",
    "world_spec",
    "evidence_graph",
    "coverage_map",
    "candidate",
    "candidate_manifest",
    "build_record",
    "judge_report",
    "integration_report",
    "claim_vector",
    "telemetry_summary",
    "implementation_lineage",
    "implementation_contract",
    "source_snapshot",
    "parent_workspace",
    "public_verifier",
    "materializer_protocol",
    "curriculum",
    "semantic_parent",
    "semantic_clue",
    "semantic_evidence",
]


class ProvenanceInputCommitment(V2Contract):
    role: ProvenanceInputRole
    ref: ArtifactRef


class PackageProvenance(V2Contract):
    format: Literal["agent-world.provenance.v1"] = "agent-world.provenance.v1"
    package_id: Identifier
    version: NonEmptyStr
    world_spec_hash: ContentHash
    candidate_source_tree_digest: ContentHash
    dependency_lock_hash: ContentHash
    semantic_lineage: SemanticLineage
    implementation_lineage: ImplementationLineage
    input_refs: Annotated[tuple[ProvenanceInputCommitment, ...], Field(min_length=1)]

    @model_validator(mode="after")
    def validate_input_closure(self) -> PackageProvenance:
        identities = [(item.role, item.ref.revision_id) for item in self.input_refs]
        if len(set(identities)) != len(identities):
            raise ValueError("provenance input role/revision commitments must be unique")
        required = {
            "design",
            "world_spec",
            "evidence_graph",
            "coverage_map",
            "candidate",
            "candidate_manifest",
            "build_record",
            "judge_report",
            "integration_report",
            "claim_vector",
            "telemetry_summary",
            "implementation_lineage",
            "implementation_contract",
            "public_verifier",
            "materializer_protocol",
            "curriculum",
        }
        roles = {item.role for item in self.input_refs}
        if not required <= roles:
            raise ValueError(f"provenance input closure is incomplete: {sorted(required - roles)}")
        if self.implementation_lineage.dependency_lock_hash != self.dependency_lock_hash:
            raise ValueError("provenance dependency lock differs from implementation lineage")
        return self


class AssuranceGateCommitment(V2Contract):
    gate_id: Identifier
    status: Literal["pass", "fail", "inconclusive", "error"]
    hard: bool
    subject_ref: ArtifactRef
    evidence_refs: Annotated[tuple[ArtifactRef, ...], Field(min_length=1)]
    observed_metrics: dict[Identifier, float] = Field(default_factory=dict)
    duration_seconds: Annotated[float, Field(ge=0)]


class PackageAssurance(V2Contract):
    format: Literal["agent-world.assurance.v1"] = "agent-world.assurance.v1"
    disclosure: Literal["commitments_only_no_private_cases"] = (
        "commitments_only_no_private_cases"
    )
    package_id: Identifier
    version: NonEmptyStr
    report_ref: ArtifactRef
    integration_report_ref: ArtifactRef
    claim_vector_ref: ArtifactRef
    telemetry_summary_ref: ArtifactRef
    report_id: Identifier
    report_revision: Annotated[int, Field(ge=1)]
    candidate_ref: ArtifactRef
    candidate_source_tree_digest: ContentHash
    verdict: Literal["pass", "fail", "inconclusive", "error"]
    gates: Annotated[tuple[AssuranceGateCommitment, ...], Field(min_length=1)]
    evaluation_evidence_refs: Annotated[tuple[ArtifactRef, ...], Field(min_length=1)]
    finding_count: Annotated[int, Field(ge=0)]
    findings_commitment: ContentHash
    actual_budget_usage: BudgetUsage

    @model_validator(mode="after")
    def validate_gate_closure(self) -> PackageAssurance:
        gate_ids = tuple(item.gate_id for item in self.gates)
        if len(set(gate_ids)) != len(gate_ids):
            raise ValueError("assurance gate commitments must be unique")
        declared = set(self.evaluation_evidence_refs)
        referenced = {ref for gate in self.gates for ref in gate.evidence_refs}
        if not referenced <= declared:
            raise ValueError("assurance gates reference evidence outside the report closure")
        return self


class PackageFidelity(V2Contract):
    format: Literal["agent-world.fidelity.v1"] = "agent-world.fidelity.v1"
    assurance_scope: Literal["design_declarations_not_reality_equivalence"] = (
        "design_declarations_not_reality_equivalence"
    )
    reality_equivalence_claimed: Literal[False] = False
    package_id: Identifier
    version: NonEmptyStr
    world_spec_hash: ContentHash
    statements: Annotated[tuple[FidelityStatement, ...], Field(min_length=1)]
    known_divergences: tuple[NonEmptyStr, ...] = ()
    known_limits: tuple[NonEmptyStr, ...] = ()
    evidence_refs: Annotated[tuple[ArtifactRef, ...], Field(min_length=1)]


class SbomLicenseMetadata(V2Contract):
    """License knowledge; ``verified`` is only legal with Judge evidence refs."""

    status: Literal["unknown", "verified"]
    expression: NonEmptyStr | None = None
    evidence_refs: tuple[ArtifactRef, ...] = ()

    @model_validator(mode="after")
    def validate_assurance(self) -> SbomLicenseMetadata:
        if self.status == "unknown":
            if self.expression is not None or self.evidence_refs:
                raise ValueError("unknown license metadata cannot claim an expression or evidence")
        elif self.expression is None or not self.evidence_refs:
            raise ValueError("verified license metadata requires expression and Judge evidence")
        return self


class SbomInputFile(V2Contract):
    path: Literal["pyproject.toml", "uv.lock"]
    role: Literal["configuration", "dependency_lock"]
    content_hash: ContentHash
    size_bytes: Annotated[int, Field(ge=1)]


class CandidateLicenseFile(V2Contract):
    """Hash inventory only; presence never implies a parsed or verified license."""

    path: NonEmptyStr
    content_hash: ContentHash
    size_bytes: Annotated[int, Field(ge=0)]

    @field_validator("path")
    @classmethod
    def validate_relative_path(cls, value: str) -> str:
        PackageFile.validate_path(value)
        return value


class SbomLockedWheel(V2Contract):
    url: NonEmptyStr
    content_hash: ContentHash
    size_bytes: Annotated[int, Field(gt=0)]


class SbomVirtualRoot(V2Contract):
    name: NonEmptyStr
    version: NonEmptyStr
    requires_python: NonEmptyStr
    lock_requires_python: NonEmptyStr
    source: Literal["virtual:."] = "virtual:."
    declared_dependencies: tuple[NonEmptyStr, ...] = ()
    license: SbomLicenseMetadata = Field(
        default_factory=lambda: SbomLicenseMetadata(status="unknown")
    )


class SbomRegistryDependency(V2Contract):
    name: NonEmptyStr
    version: NonEmptyStr
    registry: NonEmptyStr
    wheels: Annotated[tuple[SbomLockedWheel, ...], Field(min_length=1)]
    license: SbomLicenseMetadata = Field(
        default_factory=lambda: SbomLicenseMetadata(status="unknown")
    )


class EnvironmentSbom(V2Contract):
    format: Literal["agent-world.sbom.v1"] = "agent-world.sbom.v1"
    package_id: Identifier
    version: NonEmptyStr
    lock_format_version: Annotated[int, Field(ge=1)]
    input_files: Annotated[tuple[SbomInputFile, ...], Field(min_length=2, max_length=2)]
    virtual_root: SbomVirtualRoot
    registry_dependencies: tuple[SbomRegistryDependency, ...] = ()
    candidate_license_files: tuple[CandidateLicenseFile, ...] = ()

    @model_validator(mode="after")
    def validate_inventory(self) -> EnvironmentSbom:
        paths = tuple(item.path for item in self.input_files)
        if set(paths) != {PYPROJECT_PACKAGE_PATH, UV_LOCK_PACKAGE_PATH}:
            raise ValueError("SBOM must bind exact pyproject.toml and uv.lock inputs")
        dependency_keys = tuple(
            (item.name, item.version, item.registry) for item in self.registry_dependencies
        )
        if len(set(dependency_keys)) != len(dependency_keys):
            raise ValueError("SBOM registry dependency identities must be unique")
        license_paths = tuple(item.path for item in self.candidate_license_files)
        if len(set(license_paths)) != len(license_paths):
            raise ValueError("SBOM candidate license file paths must be unique")
        return self


class EnvPackageMetadata(V2Contract):
    """Canonical flat TOML bootstrap; deliberately excludes any manifest hash."""

    format: Literal["envpkg-v3"] = "envpkg-v3"
    metadata_protocol: Literal["agent-world.envpkg.metadata.v1"] = (
        "agent-world.envpkg.metadata.v1"
    )
    package_id: Identifier
    version: NonEmptyStr
    runtime_protocol: Literal["agent-world.runtime.v2"] = "agent-world.runtime.v2"
    runtime_launch_hash: ContentHash
    runtime_argv: Annotated[tuple[NonEmptyStr, ...], Field(min_length=1)]
    runtime_workdir: NonEmptyStr
    runtime_paths: Annotated[tuple[NonEmptyStr, ...], Field(min_length=1)]
    task_materializer_protocol: Literal["python-callable-v3"] = "python-callable-v3"
    task_materializer_descriptor_hash: ContentHash
    task_materializer_entrypoint: NonEmptyStr
    task_materializer_path: NonEmptyStr
    trusted_evaluator_protocol: Literal["agent-world.trusted-evaluator.v2"] = (
        "agent-world.trusted-evaluator.v2"
    )
    trusted_evaluator_path: Literal["world/rule_ir.json"] = "world/rule_ir.json"
    public_self_check_protocol: Literal["python-module-v2"] = "python-module-v2"
    public_self_check_descriptor_hash: ContentHash
    public_self_check_path: NonEmptyStr
    world_spec_path: Literal["world/world_spec.json"] = "world/world_spec.json"
    world_spec_hash: ContentHash
    world_boundary_hash: ContentHash
    candidate_source_tree_digest: ContentHash
    dependency_lock_path: Literal["uv.lock"] = "uv.lock"
    dependency_lock_hash: ContentHash
    judge_report_revision_id: ContentHash
    judge_report_content_hash: ContentHash
    integration_report_revision_id: ContentHash
    integration_report_content_hash: ContentHash
    claim_vector_revision_id: ContentHash
    claim_vector_content_hash: ContentHash
    telemetry_summary_revision_id: ContentHash
    telemetry_summary_content_hash: ContentHash
    provenance_path: Literal["evidence/provenance.json"] = PROVENANCE_PACKAGE_PATH
    provenance_hash: ContentHash
    assurance_path: Literal["evidence/assurance.json"] = ASSURANCE_PACKAGE_PATH
    assurance_hash: ContentHash
    fidelity_path: Literal["evidence/fidelity.json"] = FIDELITY_PACKAGE_PATH
    fidelity_hash: ContentHash
    sbom_path: Literal["sbom/sbom.json"] = SBOM_PACKAGE_PATH
    sbom_hash: ContentHash

    @field_validator(
        "runtime_workdir",
        "task_materializer_path",
        "public_self_check_path",
    )
    @classmethod
    def validate_relative_paths(cls, value: str) -> str:
        if value == ".":
            return value
        PackageFile.validate_path(value)
        return value

    @field_validator("runtime_paths")
    @classmethod
    def validate_runtime_paths(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        for value in values:
            PackageFile.validate_path(value)
        if len(set(values)) != len(values):
            raise ValueError("runtime paths must be unique")
        return values

    @field_validator("runtime_argv")
    @classmethod
    def reject_absolute_argv(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        absolute_windows = re.compile(r"^[A-Za-z]:[\\/]")
        if any(
            value.startswith(("/", "file://")) or absolute_windows.match(value) is not None
            for value in values
        ):
            raise ValueError("envpkg metadata cannot contain an absolute runtime argv path")
        return values

    def stable_toml_bytes(self) -> bytes:
        return _canonical_envpkg_toml(self)


class EnvironmentPackageManifest(V2Contract):
    format: Literal["envpkg-v3"] = "envpkg-v3"
    package_id: Identifier
    version: NonEmptyStr
    created_at: AwareDatetime
    world_boundary_hash: ContentHash
    world_spec_hash: ContentHash
    candidate_source_tree_digest: ContentHash
    design_ref: ArtifactRef
    world_spec_ref: ArtifactRef
    candidate_ref: ArtifactRef
    candidate_manifest_ref: ArtifactRef
    build_record_ref: ArtifactRef
    implementation_lineage_ref: ArtifactRef
    judge_report_ref: ArtifactRef
    integration_report_ref: ArtifactRef
    claim_vector_ref: ArtifactRef
    telemetry_summary_ref: ArtifactRef
    runtime: RuntimeLaunch
    task_materializer: TaskMaterializerDescriptor
    trusted_evaluator: TrustedEvaluatorDescriptor
    public_self_check: PublicSelfCheckDescriptor
    public_verifier_ref: ArtifactRef
    metadata_path: Literal["envpkg.toml"] = ENVPKG_METADATA_PACKAGE_PATH
    provenance_path: Literal["evidence/provenance.json"] = PROVENANCE_PACKAGE_PATH
    assurance_path: Literal["evidence/assurance.json"] = ASSURANCE_PACKAGE_PATH
    fidelity_path: Literal["evidence/fidelity.json"] = FIDELITY_PACKAGE_PATH
    sbom_path: Literal["sbom/sbom.json"] = SBOM_PACKAGE_PATH
    files: Annotated[tuple[PackageFile, ...], Field(min_length=1)]
    lineage: PackageLineage
    known_limits: tuple[NonEmptyStr, ...] = ()

    @model_validator(mode="after")
    def validate_manifest_closure(self) -> EnvironmentPackageManifest:
        paths = [item.path for item in self.files]
        if len(set(paths)) != len(paths):
            raise ValueError("package file paths must be unique")
        if candidate_source_tree_digest(self.files) != self.candidate_source_tree_digest:
            raise ValueError(
                "packaged candidate source tree differs from candidate_source_tree_digest"
            )
        declared = {item.path: item for item in self.files}
        for path, framework_role in FRAMEWORK_PACKAGE_LAYOUT:
            item = declared.get(path)
            if item is None or item.role != framework_role:
                raise ValueError(f"{path} must be packaged with role {framework_role}")
            if item.executable:
                raise ValueError(f"framework package payload cannot be executable: {path}")
        for item in self.files:
            if item.role in _FRAMEWORK_ROLES and _FRAMEWORK_PATH_BY_ROLE[item.role] != item.path:
                raise ValueError(
                    f"framework role {item.role} is fixed to {_FRAMEWORK_PATH_BY_ROLE[item.role]}"
                )
        required_candidate = {
            PYPROJECT_PACKAGE_PATH: "configuration",
            UV_LOCK_PACKAGE_PATH: "dependency_lock",
            self.task_materializer.entry_path: "task_materializer",
            self.public_self_check.entry_path: "public_verifier",
        }
        for path, candidate_role in required_candidate.items():
            if declared.get(path) is None or declared[path].role != candidate_role:
                raise ValueError(f"{path} must be packaged with role {candidate_role}")
        required_framework = {
            self.task_materializer.output_schema_path: "materializer_protocol",
            self.task_materializer.curriculum_path: "curriculum",
            self.trusted_evaluator.world_spec_path: "world_spec",
            self.trusted_evaluator.rule_ir_path: "rule_ir",
            self.metadata_path: "package_metadata",
            self.provenance_path: "provenance",
            self.assurance_path: "assurance",
            self.fidelity_path: "fidelity",
            self.sbom_path: "sbom",
        }
        for path, required_framework_role in required_framework.items():
            if declared.get(path) is None or declared[path].role != required_framework_role:
                raise ValueError(f"{path} must be packaged with role {required_framework_role}")
        if declared[self.trusted_evaluator.world_spec_path].content_hash != self.world_spec_hash:
            raise ValueError("packaged WorldSpec hash differs from manifest world_spec_hash")
        for path, ref in (
            (self.task_materializer.output_schema_path, self.task_materializer.output_schema_ref),
            (self.task_materializer.curriculum_path, self.task_materializer.curriculum_ref),
            (self.public_self_check.entry_path, self.public_verifier_ref),
        ):
            if declared[path].content_hash != ref.content_hash:
                raise ValueError(f"packaged file {path} differs from its ArtifactRef content")
        if (
            declared[UV_LOCK_PACKAGE_PATH].content_hash
            != self.lineage.implementation.dependency_lock_hash
        ):
            raise ValueError("physical uv.lock differs from implementation lineage")
        return self


class CandidateManifest(V2Contract):
    """Builder-authored draft without Judge evidence or release authority."""

    format: Literal["envpkg-v3-candidate"] = "envpkg-v3-candidate"
    candidate_id: Identifier
    design_ref: ArtifactRef
    candidate_source_tree_digest: ContentHash
    runtime: RuntimeLaunch
    task_materializer: TaskMaterializerDescriptor
    public_self_check: PublicSelfCheckDescriptor
    public_verifier_ref: ArtifactRef
    public_test_refs: tuple[ArtifactRef, ...] = ()
    files: Annotated[tuple[PackageFile, ...], Field(min_length=1)]
    implementation_lineage_ref: ArtifactRef
    known_limits: tuple[NonEmptyStr, ...] = ()

    @model_validator(mode="after")
    def unique_paths(self) -> CandidateManifest:
        paths = [item.path for item in self.files]
        if len(set(paths)) != len(paths):
            raise ValueError("candidate package file paths must be unique")
        if candidate_source_tree_digest(self.files) != self.candidate_source_tree_digest:
            raise ValueError("candidate files differ from candidate_source_tree_digest")
        roles = {item.path: item.role for item in self.files}
        required = {
            PYPROJECT_PACKAGE_PATH: "configuration",
            UV_LOCK_PACKAGE_PATH: "dependency_lock",
            self.task_materializer.entry_path: "task_materializer",
            self.public_self_check.entry_path: "public_verifier",
        }
        for path, role in required.items():
            if roles.get(path) != role:
                raise ValueError(f"{path} must be packaged with role {role}")
        declared = {item.path: item for item in self.files}
        if (
            declared[self.public_self_check.entry_path].content_hash
            != self.public_verifier_ref.content_hash
        ):
            raise ValueError(
                f"candidate file {self.public_self_check.entry_path} differs from its ArtifactRef"
            )
        return self


def parse_envpkg_metadata_toml(raw: bytes) -> EnvPackageMetadata:
    """Parse the intentionally small canonical TOML subset used by envpkg v3."""

    try:
        text = raw.decode("utf-8", errors="strict")
        value = tomllib.loads(text)
        for field in ("runtime_argv", "runtime_paths"):
            if isinstance(value.get(field), list):
                value[field] = tuple(value[field])
        metadata = EnvPackageMetadata.model_validate(value)
    except Exception as exc:
        raise ValueError("envpkg.toml is not a valid closed metadata contract") from exc
    if metadata.stable_toml_bytes() != raw:
        raise ValueError("envpkg.toml must use the canonical flat TOML representation")
    return metadata


def compile_package_provenance(
    design: EnvironmentDesign,
    *,
    package_id: str,
    version: str,
    lineage: PackageLineage,
    design_ref: ArtifactRef,
    world_spec_ref: ArtifactRef,
    candidate_ref: ArtifactRef,
    candidate_manifest_ref: ArtifactRef,
    build_record_ref: ArtifactRef,
    implementation_lineage_ref: ArtifactRef,
    judge_report_ref: ArtifactRef,
    integration_report_ref: ArtifactRef,
    claim_vector_ref: ArtifactRef,
    telemetry_summary_ref: ArtifactRef,
    public_verifier_ref: ArtifactRef,
    materializer_protocol_ref: ArtifactRef,
    curriculum_ref: ArtifactRef,
    candidate_source_digest: str,
) -> PackageProvenance:
    fixed = (
        ProvenanceInputCommitment(role="job", ref=design.job_ref),
        ProvenanceInputCommitment(role="request", ref=design.request_ref),
        ProvenanceInputCommitment(role="design", ref=design_ref),
        ProvenanceInputCommitment(role="world_spec", ref=world_spec_ref),
        ProvenanceInputCommitment(role="evidence_graph", ref=design.evidence_graph_ref),
        ProvenanceInputCommitment(role="coverage_map", ref=design.coverage_map_ref),
        ProvenanceInputCommitment(role="candidate", ref=candidate_ref),
        ProvenanceInputCommitment(role="candidate_manifest", ref=candidate_manifest_ref),
        ProvenanceInputCommitment(role="build_record", ref=build_record_ref),
        ProvenanceInputCommitment(role="judge_report", ref=judge_report_ref),
        ProvenanceInputCommitment(role="integration_report", ref=integration_report_ref),
        ProvenanceInputCommitment(role="claim_vector", ref=claim_vector_ref),
        ProvenanceInputCommitment(role="telemetry_summary", ref=telemetry_summary_ref),
        ProvenanceInputCommitment(
            role="implementation_lineage",
            ref=implementation_lineage_ref,
        ),
        ProvenanceInputCommitment(
            role="implementation_contract",
            ref=lineage.implementation.implementation_contract_ref,
        ),
        ProvenanceInputCommitment(role="public_verifier", ref=public_verifier_ref),
        ProvenanceInputCommitment(
            role="materializer_protocol",
            ref=materializer_protocol_ref,
        ),
        ProvenanceInputCommitment(role="curriculum", ref=curriculum_ref),
    )
    repeated = (
        *(
            ProvenanceInputCommitment(role="source_snapshot", ref=ref)
            for ref in lineage.implementation.source_snapshot_refs
        ),
        *(
            ProvenanceInputCommitment(role="parent_workspace", ref=ref)
            for ref in lineage.implementation.parent_workspace_refs
        ),
        *(
            ProvenanceInputCommitment(role="semantic_parent", ref=ref)
            for ref in lineage.semantic.semantic_parent_refs
        ),
        *(
            ProvenanceInputCommitment(role="semantic_clue", ref=ref)
            for ref in lineage.semantic.clue_refs
        ),
        *(
            ProvenanceInputCommitment(role="semantic_evidence", ref=ref)
            for ref in lineage.semantic.evidence_refs
        ),
    )
    inputs = tuple(
        sorted(
            (*fixed, *repeated),
            key=lambda item: (item.role, item.ref.artifact_id, item.ref.revision_id),
        )
    )
    return PackageProvenance(
        package_id=package_id,
        version=version,
        world_spec_hash=design.world_spec.content_digest(),
        candidate_source_tree_digest=candidate_source_digest,
        dependency_lock_hash=lineage.implementation.dependency_lock_hash,
        semantic_lineage=lineage.semantic,
        implementation_lineage=lineage.implementation,
        input_refs=inputs,
    )


def compile_package_assurance(
    report: JudgeReport,
    *,
    package_id: str,
    version: str,
    report_ref: ArtifactRef,
    integration_report_ref: ArtifactRef,
    claim_vector_ref: ArtifactRef,
    telemetry_summary_ref: ArtifactRef,
) -> PackageAssurance:
    if report.candidate_source_tree_digest is None:
        raise ValueError("assurance cannot fabricate an unbound candidate source commitment")
    gates = tuple(
        AssuranceGateCommitment(
            gate_id=gate.gate_id,
            status=gate.status,
            hard=gate.hard,
            subject_ref=gate.subject_ref,
            evidence_refs=tuple(
                sorted(gate.evidence_refs, key=lambda ref: (ref.artifact_id, ref.revision_id))
            ),
            observed_metrics=dict(sorted(gate.observed_metrics.items())),
            duration_seconds=gate.duration_seconds,
        )
        for gate in sorted(report.gate_results, key=lambda item: item.gate_id)
    )
    return PackageAssurance(
        package_id=package_id,
        version=version,
        report_ref=report_ref,
        integration_report_ref=integration_report_ref,
        claim_vector_ref=claim_vector_ref,
        telemetry_summary_ref=telemetry_summary_ref,
        report_id=report.report_id,
        report_revision=report.revision,
        candidate_ref=report.candidate_ref,
        candidate_source_tree_digest=report.candidate_source_tree_digest,
        verdict=report.verdict,
        gates=gates,
        evaluation_evidence_refs=tuple(
            sorted(
                report.evaluation_evidence_refs,
                key=lambda ref: (ref.artifact_id, ref.revision_id),
            )
        ),
        finding_count=len(report.findings),
        findings_commitment=sha256_digest(
            canonical_json_bytes(
                [item.model_dump(mode="json", exclude_none=False) for item in report.findings]
            )
        ),
        actual_budget_usage=report.budget_usage,
    )


def compile_package_fidelity(
    design: EnvironmentDesign,
    *,
    package_id: str,
    version: str,
    known_limits: tuple[str, ...],
) -> PackageFidelity:
    divergences = tuple(
        dict.fromkeys(
            statement.known_divergence
            for statement in design.world_spec.fidelity
            if statement.known_divergence is not None
        )
    )
    limits = tuple(dict.fromkeys((*known_limits, *design.unresolved_questions)))
    evidence_refs = tuple(
        dict.fromkeys((design.evidence_graph_ref, design.coverage_map_ref))
    )
    return PackageFidelity(
        package_id=package_id,
        version=version,
        world_spec_hash=design.world_spec.content_digest(),
        statements=design.world_spec.fidelity,
        known_divergences=divergences,
        known_limits=limits,
        evidence_refs=evidence_refs,
    )


def compile_environment_sbom(
    *,
    package_id: str,
    version: str,
    files: tuple[PackageFile, ...],
    pyproject_bytes: bytes,
    uv_lock_bytes: bytes,
) -> EnvironmentSbom:
    """Compile exact uv inputs; phase 1 deliberately emits only unknown licenses."""

    declared = {item.path: item for item in files}
    if len(declared) != len(files):
        raise ValueError("candidate files must be unique before SBOM compilation")
    pyproject_file = declared.get(PYPROJECT_PACKAGE_PATH)
    lock_file = declared.get(UV_LOCK_PACKAGE_PATH)
    if pyproject_file is None or pyproject_file.role != "configuration":
        raise ValueError("SBOM requires pyproject.toml with role configuration")
    if lock_file is None or lock_file.role != "dependency_lock":
        raise ValueError("SBOM requires uv.lock with role dependency_lock")
    for descriptor, content in (
        (pyproject_file, pyproject_bytes),
        (lock_file, uv_lock_bytes),
    ):
        if (
            descriptor.content_hash != sha256_digest(content)
            or descriptor.size_bytes != len(content)
        ):
            raise ValueError(
                f"SBOM input bytes differ from candidate descriptor: {descriptor.path}"
            )
    try:
        pyproject = tomllib.loads(pyproject_bytes.decode("utf-8", errors="strict"))
        lock = tomllib.loads(uv_lock_bytes.decode("utf-8", errors="strict"))
    except Exception as exc:
        raise ValueError("SBOM inputs must be strict UTF-8 TOML") from exc
    project = pyproject.get("project")
    packages = lock.get("package")
    lock_version = lock.get("version")
    lock_requires_python = lock.get("requires-python")
    if not isinstance(project, dict) or not isinstance(packages, list):
        raise ValueError("SBOM inputs lack project or lock package tables")
    if isinstance(lock_version, bool) or not isinstance(lock_version, int) or lock_version < 1:
        raise ValueError("SBOM requires a positive uv lock format version")
    root_name = project.get("name")
    root_version = project.get("version")
    root_requires_python = project.get("requires-python")
    dependencies = project.get("dependencies", [])
    if (
        not isinstance(root_name, str)
        or not root_name
        or not isinstance(root_version, str)
        or not root_version
        or not isinstance(root_requires_python, str)
        or not root_requires_python
        or not isinstance(lock_requires_python, str)
        or not lock_requires_python
    ):
        raise ValueError("SBOM root project and lock require name/version/Python strings")
    if not isinstance(dependencies, list) or not all(
        isinstance(item, str) for item in dependencies
    ):
        raise ValueError("SBOM project.dependencies must be a string array")

    virtual_roots: list[dict[str, object]] = []
    registry_dependencies: list[SbomRegistryDependency] = []
    for raw_package in packages:
        if not isinstance(raw_package, dict):
            raise ValueError("SBOM uv.lock package entries must be tables")
        name = raw_package.get("name")
        package_version = raw_package.get("version")
        source = raw_package.get("source")
        if (
            not isinstance(name, str)
            or not isinstance(package_version, str)
            or not isinstance(source, dict)
        ):
            raise ValueError("SBOM lock package requires name, version and source")
        if source == {"virtual": "."}:
            virtual_roots.append(raw_package)
            continue
        registry = source.get("registry")
        if set(source) != {"registry"} or not isinstance(registry, str):
            raise ValueError(f"SBOM dependency {name} is not an exact registry dependency")
        raw_wheels = raw_package.get("wheels")
        if not isinstance(raw_wheels, list) or not raw_wheels:
            raise ValueError(f"SBOM dependency {name} has no locked wheel inventory")
        wheels: list[SbomLockedWheel] = []
        for raw_wheel in raw_wheels:
            if not isinstance(raw_wheel, dict):
                raise ValueError(f"SBOM dependency {name} wheel must be a table")
            url = raw_wheel.get("url")
            digest = raw_wheel.get("hash")
            size = raw_wheel.get("size")
            if (
                not isinstance(url, str)
                or not isinstance(digest, str)
                or re.fullmatch(r"sha256:[0-9a-f]{64}", digest) is None
                or isinstance(size, bool)
                or not isinstance(size, int)
                or size <= 0
            ):
                raise ValueError(f"SBOM dependency {name} wheel lacks URL/hash/size")
            wheels.append(
                SbomLockedWheel(url=url, content_hash=digest, size_bytes=size)
            )
        registry_dependencies.append(
            SbomRegistryDependency(
                name=name,
                version=package_version,
                registry=registry,
                wheels=tuple(sorted(wheels, key=lambda item: item.url)),
                license=SbomLicenseMetadata(status="unknown"),
            )
        )
    if len(virtual_roots) != 1:
        raise ValueError("SBOM requires exactly one virtual uv root")
    root = virtual_roots[0]
    if root.get("name") != root_name or root.get("version") != root_version:
        raise ValueError("SBOM virtual lock root differs from pyproject identity")

    input_files = (
        SbomInputFile(
            path=PYPROJECT_PACKAGE_PATH,
            role="configuration",
            content_hash=pyproject_file.content_hash,
            size_bytes=pyproject_file.size_bytes,
        ),
        SbomInputFile(
            path=UV_LOCK_PACKAGE_PATH,
            role="dependency_lock",
            content_hash=lock_file.content_hash,
            size_bytes=lock_file.size_bytes,
        ),
    )
    license_files = tuple(
        CandidateLicenseFile(
            path=item.path,
            content_hash=item.content_hash,
            size_bytes=item.size_bytes,
        )
        for item in sorted(files, key=lambda value: value.path)
        if item.role == "license"
    )
    return EnvironmentSbom(
        package_id=package_id,
        version=version,
        lock_format_version=lock_version,
        input_files=input_files,
        virtual_root=SbomVirtualRoot(
            name=root_name,
            version=root_version,
            requires_python=root_requires_python,
            lock_requires_python=lock_requires_python,
            declared_dependencies=tuple(dependencies),
            license=SbomLicenseMetadata(status="unknown"),
        ),
        registry_dependencies=tuple(
            sorted(
                registry_dependencies,
                key=lambda item: (item.name, item.version, item.registry),
            )
        ),
        candidate_license_files=license_files,
    )


def compile_framework_package_payloads(
    design: EnvironmentDesign,
    *,
    package_id: str,
    version: str,
    candidate_manifest: CandidateManifest,
    judge_report: JudgeReport,
    integration_report: IntegrationReport,
    lineage: PackageLineage,
    design_ref: ArtifactRef,
    world_spec_ref: ArtifactRef,
    candidate_ref: ArtifactRef,
    candidate_manifest_ref: ArtifactRef,
    build_record_ref: ArtifactRef,
    implementation_lineage_ref: ArtifactRef,
    judge_report_ref: ArtifactRef,
    integration_report_ref: ArtifactRef,
    claim_vector_ref: ArtifactRef,
    telemetry_summary_ref: ArtifactRef,
    pyproject_bytes: bytes,
    uv_lock_bytes: bytes,
) -> tuple[FrameworkPackagePayload, ...]:
    """Compile every framework-owned file from exact typed release inputs."""

    _validate_compiler_bindings(
        design,
        candidate_manifest=candidate_manifest,
        judge_report=judge_report,
        integration_report=integration_report,
        lineage=lineage,
        design_ref=design_ref,
        world_spec_ref=world_spec_ref,
        candidate_ref=candidate_ref,
        candidate_manifest_ref=candidate_manifest_ref,
        implementation_lineage_ref=implementation_lineage_ref,
        judge_report_ref=judge_report_ref,
        integration_report_ref=integration_report_ref,
        uv_lock_bytes=uv_lock_bytes,
    )
    evaluator = TrustedEvaluatorSpec.from_design(design)
    from agent_world.task_materialization import compile_task_materializer_output_schema

    provenance = compile_package_provenance(
        design,
        package_id=package_id,
        version=version,
        lineage=lineage,
        design_ref=design_ref,
        world_spec_ref=world_spec_ref,
        candidate_ref=candidate_ref,
        candidate_manifest_ref=candidate_manifest_ref,
        build_record_ref=build_record_ref,
        implementation_lineage_ref=implementation_lineage_ref,
        judge_report_ref=judge_report_ref,
        integration_report_ref=integration_report_ref,
        claim_vector_ref=claim_vector_ref,
        telemetry_summary_ref=telemetry_summary_ref,
        public_verifier_ref=candidate_manifest.public_verifier_ref,
        materializer_protocol_ref=candidate_manifest.task_materializer.output_schema_ref,
        curriculum_ref=candidate_manifest.task_materializer.curriculum_ref,
        candidate_source_digest=candidate_manifest.candidate_source_tree_digest,
    )
    assurance = compile_package_assurance(
        judge_report,
        package_id=package_id,
        version=version,
        report_ref=judge_report_ref,
        integration_report_ref=integration_report_ref,
        claim_vector_ref=claim_vector_ref,
        telemetry_summary_ref=telemetry_summary_ref,
    )
    fidelity = compile_package_fidelity(
        design,
        package_id=package_id,
        version=version,
        known_limits=candidate_manifest.known_limits,
    )
    sbom = compile_environment_sbom(
        package_id=package_id,
        version=version,
        files=candidate_manifest.files,
        pyproject_bytes=pyproject_bytes,
        uv_lock_bytes=uv_lock_bytes,
    )
    provenance_bytes = provenance.stable_json_bytes()
    assurance_bytes = assurance.stable_json_bytes()
    fidelity_bytes = fidelity.stable_json_bytes()
    sbom_bytes = sbom.stable_json_bytes()
    runtime_paths = tuple(
        item.path
        for item in sorted(candidate_manifest.files, key=lambda value: value.path)
        if item.role == "runtime"
    )
    metadata = EnvPackageMetadata(
        package_id=package_id,
        version=version,
        runtime_launch_hash=candidate_manifest.runtime.content_digest(),
        runtime_argv=candidate_manifest.runtime.argv,
        runtime_workdir=candidate_manifest.runtime.workdir,
        runtime_paths=runtime_paths,
        task_materializer_descriptor_hash=candidate_manifest.task_materializer.content_digest(),
        task_materializer_entrypoint=candidate_manifest.task_materializer.entrypoint,
        task_materializer_path=candidate_manifest.task_materializer.entry_path,
        public_self_check_descriptor_hash=candidate_manifest.public_self_check.content_digest(),
        public_self_check_path=candidate_manifest.public_self_check.entry_path,
        world_spec_hash=design.world_spec.content_digest(),
        world_boundary_hash=design.world_spec.boundary.content_digest(),
        candidate_source_tree_digest=candidate_manifest.candidate_source_tree_digest,
        dependency_lock_hash=lineage.implementation.dependency_lock_hash,
        judge_report_revision_id=judge_report_ref.revision_id,
        judge_report_content_hash=judge_report_ref.content_hash,
        integration_report_revision_id=integration_report_ref.revision_id,
        integration_report_content_hash=integration_report_ref.content_hash,
        claim_vector_revision_id=claim_vector_ref.revision_id,
        claim_vector_content_hash=claim_vector_ref.content_hash,
        telemetry_summary_revision_id=telemetry_summary_ref.revision_id,
        telemetry_summary_content_hash=telemetry_summary_ref.content_hash,
        provenance_hash=sha256_digest(provenance_bytes),
        assurance_hash=sha256_digest(assurance_bytes),
        fidelity_hash=sha256_digest(fidelity_bytes),
        sbom_hash=sha256_digest(sbom_bytes),
    )
    payload_by_path = {
        ENVPKG_METADATA_PACKAGE_PATH: FrameworkPackagePayload(
            ENVPKG_METADATA_PACKAGE_PATH,
            "package_metadata",
            metadata.stable_toml_bytes(),
        ),
        WORLD_SPEC_PACKAGE_PATH: FrameworkPackagePayload(
            WORLD_SPEC_PACKAGE_PATH,
            "world_spec",
            design.world_spec.stable_json_bytes(),
        ),
        TASK_MATERIALIZER_PROTOCOL_PACKAGE_PATH: FrameworkPackagePayload(
            TASK_MATERIALIZER_PROTOCOL_PACKAGE_PATH,
            "materializer_protocol",
            canonical_json_bytes(compile_task_materializer_output_schema(design.curriculum)),
        ),
        CURRICULUM_PACKAGE_PATH: FrameworkPackagePayload(
            CURRICULUM_PACKAGE_PATH,
            "curriculum",
            design.curriculum.stable_json_bytes(),
        ),
        RULE_IR_PACKAGE_PATH: FrameworkPackagePayload(
            RULE_IR_PACKAGE_PATH,
            "rule_ir",
            evaluator.stable_json_bytes(),
        ),
        PROVENANCE_PACKAGE_PATH: FrameworkPackagePayload(
            PROVENANCE_PACKAGE_PATH,
            "provenance",
            provenance_bytes,
        ),
        ASSURANCE_PACKAGE_PATH: FrameworkPackagePayload(
            ASSURANCE_PACKAGE_PATH,
            "assurance",
            assurance_bytes,
        ),
        FIDELITY_PACKAGE_PATH: FrameworkPackagePayload(
            FIDELITY_PACKAGE_PATH,
            "fidelity",
            fidelity_bytes,
        ),
        SBOM_PACKAGE_PATH: FrameworkPackagePayload(
            SBOM_PACKAGE_PATH,
            "sbom",
            sbom_bytes,
        ),
    }
    return tuple(payload_by_path[path] for path, _role in FRAMEWORK_PACKAGE_LAYOUT)


def _validate_compiler_bindings(
    design: EnvironmentDesign,
    *,
    candidate_manifest: CandidateManifest,
    judge_report: JudgeReport,
    integration_report: IntegrationReport,
    lineage: PackageLineage,
    design_ref: ArtifactRef,
    world_spec_ref: ArtifactRef,
    candidate_ref: ArtifactRef,
    candidate_manifest_ref: ArtifactRef,
    implementation_lineage_ref: ArtifactRef,
    judge_report_ref: ArtifactRef,
    integration_report_ref: ArtifactRef,
    uv_lock_bytes: bytes,
) -> None:
    if design_ref.content_hash != design.content_digest():
        raise ValueError("design_ref does not bind the supplied EnvironmentDesign")
    if world_spec_ref.content_hash != design.world_spec.content_digest():
        raise ValueError("world_spec_ref does not bind the supplied WorldSpec")
    if candidate_manifest.design_ref != design_ref:
        raise ValueError("CandidateManifest and compiler bind different designs")
    if candidate_manifest_ref.content_hash != candidate_manifest.content_digest():
        raise ValueError("candidate_manifest_ref does not bind the supplied CandidateManifest")
    if candidate_manifest.implementation_lineage_ref != implementation_lineage_ref:
        raise ValueError("CandidateManifest and compiler bind different implementation lineage")
    if implementation_lineage_ref.content_hash != lineage.implementation.content_digest():
        raise ValueError("implementation_lineage_ref does not bind PackageLineage")
    if judge_report_ref.content_hash != judge_report.content_digest():
        raise ValueError("judge_report_ref does not bind the supplied JudgeReport")
    if integration_report_ref.content_hash != integration_report.content_digest():
        raise ValueError("integration_report_ref does not bind the supplied IntegrationReport")
    if integration_report.status != "ready":
        raise ValueError("framework payloads require a ready IntegrationReport")
    if integration_report.candidate_ref != candidate_ref:
        raise ValueError("IntegrationReport and compiler bind different candidates")
    if (
        integration_report.candidate_source_tree_digest
        != candidate_manifest.candidate_source_tree_digest
    ):
        raise ValueError("IntegrationReport and CandidateManifest bind different source trees")
    if judge_report.candidate_ref != candidate_ref:
        raise ValueError("JudgeReport and compiler bind different candidates")
    if judge_report.verdict != "pass" or judge_report.candidate_source_tree_digest is None:
        raise ValueError("framework payloads require a source-bound passing JudgeReport")
    if judge_report.candidate_source_tree_digest != candidate_manifest.candidate_source_tree_digest:
        raise ValueError("JudgeReport and CandidateManifest bind different source trees")
    if lineage.implementation.dependency_lock_hash != sha256_digest(uv_lock_bytes):
        raise ValueError("uv.lock bytes differ from implementation lineage")


_ENVPKG_TOML_FIELDS = (
    "schema_version",
    "format",
    "metadata_protocol",
    "package_id",
    "version",
    "runtime_protocol",
    "runtime_launch_hash",
    "runtime_argv",
    "runtime_workdir",
    "runtime_paths",
    "task_materializer_protocol",
    "task_materializer_descriptor_hash",
    "task_materializer_entrypoint",
    "task_materializer_path",
    "trusted_evaluator_protocol",
    "trusted_evaluator_path",
    "public_self_check_protocol",
    "public_self_check_descriptor_hash",
    "public_self_check_path",
    "world_spec_path",
    "world_spec_hash",
    "world_boundary_hash",
    "candidate_source_tree_digest",
    "dependency_lock_path",
    "dependency_lock_hash",
    "judge_report_revision_id",
    "judge_report_content_hash",
    "integration_report_revision_id",
    "integration_report_content_hash",
    "claim_vector_revision_id",
    "claim_vector_content_hash",
    "telemetry_summary_revision_id",
    "telemetry_summary_content_hash",
    "provenance_path",
    "provenance_hash",
    "assurance_path",
    "assurance_hash",
    "fidelity_path",
    "fidelity_hash",
    "sbom_path",
    "sbom_hash",
)


def _canonical_envpkg_toml(metadata: EnvPackageMetadata) -> bytes:
    values = metadata.model_dump(mode="python", exclude_none=False)
    lines: list[str] = []
    for key in _ENVPKG_TOML_FIELDS:
        value = values[key]
        if isinstance(value, str):
            encoded = json.dumps(value, ensure_ascii=False, allow_nan=False)
        elif isinstance(value, tuple | list):
            encoded = "[" + ",".join(
                json.dumps(item, ensure_ascii=False, allow_nan=False) for item in value
            ) + "]"
        else:
            raise TypeError(f"unsupported canonical envpkg TOML field: {key}")
        lines.append(f"{key} = {encoded}\n")
    return "".join(lines).encode("utf-8")


__all__ = [
    "ASSURANCE_PACKAGE_PATH",
    "AssuranceGateCommitment",
    "CandidateLicenseFile",
    "CandidateManifest",
    "ENVPKG_METADATA_PACKAGE_PATH",
    "EnvironmentPackageManifest",
    "EnvironmentSbom",
    "EnvPackageMetadata",
    "FIDELITY_PACKAGE_PATH",
    "FRAMEWORK_PACKAGE_LAYOUT",
    "FrameworkPackagePayload",
    "FrameworkPackageRole",
    "PROVENANCE_PACKAGE_PATH",
    "PackageAssurance",
    "PackageFidelity",
    "PackageFile",
    "PackageProvenance",
    "ProvenanceInputCommitment",
    "PYPROJECT_PACKAGE_PATH",
    "SBOM_PACKAGE_PATH",
    "SbomInputFile",
    "SbomLicenseMetadata",
    "SbomLockedWheel",
    "SbomRegistryDependency",
    "SbomVirtualRoot",
    "TrustedEvaluatorDescriptor",
    "TrustedEvaluatorSpec",
    "UV_LOCK_PACKAGE_PATH",
    "candidate_source_tree_digest",
    "compile_environment_sbom",
    "compile_framework_package_payloads",
    "compile_package_assurance",
    "compile_package_fidelity",
    "compile_package_provenance",
    "parse_envpkg_metadata_toml",
]
