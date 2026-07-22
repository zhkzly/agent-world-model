"""Framework-owned semantic and evidence closure checks for physical envpkg v3 trees."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, cast

from jsonschema import Draft202012Validator, SchemaError  # type: ignore[import-untyped]

from agent_world.contracts import (
    CandidateManifest,
    CurriculumRequirements,
    EnvironmentDesign,
    EnvironmentPackageManifest,
    EnvironmentSbom,
    EnvPackageMetadata,
    ImplementationLineage,
    JudgeReport,
    PackageAssurance,
    PackageFidelity,
    PackageProvenance,
    SbomLicenseMetadata,
    TrustedEvaluatorSpec,
    V2Contract,
    WorldBoundary,
    WorldSpec,
    canonical_json_bytes,
    compile_environment_sbom,
    compile_package_assurance,
    compile_package_fidelity,
    compile_package_provenance,
    parse_envpkg_metadata_toml,
    sha256_digest,
)
from agent_world.task_materialization import compile_task_materializer_output_schema

_INITIAL_PACKAGE_VERSION = "1.0.0"
_BOUNDARY_DIMENSIONS = (
    "primary_domain",
    "actors_and_authority",
    "systems_of_record",
    "core_resources",
    "transition_authorities",
    "tool_namespaces",
    "core_invariants",
)
_FRAMEWORK_ROLES = frozenset(
    {
        "package_metadata",
        "world_spec",
        "materializer_protocol",
        "curriculum",
        "rule_ir",
        "provenance",
        "assurance",
        "fidelity",
        "sbom",
    }
)


class PackageSemanticError(ValueError):
    """A physical envpkg is byte-valid but not a closed portable contract."""


@dataclass(frozen=True, slots=True)
class PortablePackageContracts:
    """Canonical framework contracts parsed from one immutable package tree."""

    metadata: EnvPackageMetadata
    world_spec: WorldSpec
    curriculum: CurriculumRequirements
    evaluator: TrustedEvaluatorSpec
    materializer_protocol_schema: dict[str, Any]
    provenance: PackageProvenance
    assurance: PackageAssurance
    fidelity: PackageFidelity
    sbom: EnvironmentSbom


@dataclass(frozen=True, slots=True)
class SemanticParent:
    """One Registry-resolved semantic parent and its verified physical contracts."""

    manifest: EnvironmentPackageManifest
    contracts: PortablePackageContracts


def load_portable_package_contracts(
    root: Path,
    manifest: EnvironmentPackageManifest,
    *,
    read_file: Callable[[Path, str], bytes],
) -> PortablePackageContracts:
    """Reparse every portable contract and bind it to physical package bytes."""

    descriptor = manifest.trusted_evaluator
    metadata_bytes = _read_declared(
        root,
        manifest.metadata_path,
        "envpkg metadata",
        read_file=read_file,
    )
    world_bytes = _read_declared(
        root,
        descriptor.world_spec_path,
        "WorldSpec",
        read_file=read_file,
    )
    curriculum_bytes = _read_declared(
        root,
        descriptor.curriculum_path,
        "CurriculumRequirements",
        read_file=read_file,
    )
    evaluator_bytes = _read_declared(
        root,
        descriptor.rule_ir_path,
        "TrustedEvaluatorSpec Rule IR",
        read_file=read_file,
    )
    materializer_protocol_bytes = _read_declared(
        root,
        descriptor.materializer_protocol_path,
        "task materialization schema",
        read_file=read_file,
    )
    provenance_bytes = _read_declared(
        root,
        manifest.provenance_path,
        "provenance",
        read_file=read_file,
    )
    assurance_bytes = _read_declared(
        root,
        manifest.assurance_path,
        "assurance",
        read_file=read_file,
    )
    fidelity_bytes = _read_declared(
        root,
        manifest.fidelity_path,
        "fidelity",
        read_file=read_file,
    )
    sbom_bytes = _read_declared(
        root,
        manifest.sbom_path,
        "SBOM",
        read_file=read_file,
    )
    pyproject_bytes = _read_declared(
        root,
        "pyproject.toml",
        "pyproject.toml",
        read_file=read_file,
    )
    uv_lock_bytes = _read_declared(
        root,
        "uv.lock",
        "uv.lock",
        read_file=read_file,
    )
    try:
        metadata = parse_envpkg_metadata_toml(metadata_bytes)
        world_spec = _parse_canonical_contract(world_bytes, WorldSpec, "WorldSpec")
        curriculum = _parse_canonical_contract(
            curriculum_bytes,
            CurriculumRequirements,
            "CurriculumRequirements",
        )
        evaluator = _parse_canonical_contract(
            evaluator_bytes,
            TrustedEvaluatorSpec,
            "TrustedEvaluatorSpec",
        )
        provenance = _parse_canonical_contract(
            provenance_bytes,
            PackageProvenance,
            "PackageProvenance",
        )
        assurance = _parse_canonical_contract(
            assurance_bytes,
            PackageAssurance,
            "PackageAssurance",
        )
        fidelity = _parse_canonical_contract(
            fidelity_bytes,
            PackageFidelity,
            "PackageFidelity",
        )
        sbom = _parse_canonical_contract(sbom_bytes, EnvironmentSbom, "EnvironmentSbom")
        materializer_protocol_value = _strict_json_loads(materializer_protocol_bytes)
    except PackageSemanticError:
        raise
    except Exception as exc:
        raise PackageSemanticError(
            "envpkg contains an unparsable framework-owned portable contract"
        ) from exc

    if not isinstance(materializer_protocol_value, dict):
        raise PackageSemanticError("physical task materialization schema must be a JSON object")
    materializer_protocol_schema = cast(dict[str, Any], materializer_protocol_value)
    try:
        Draft202012Validator.check_schema(materializer_protocol_schema)
    except SchemaError as exc:
        raise PackageSemanticError(
            "physical task materialization schema is not valid JSON Schema"
        ) from exc
    if canonical_json_bytes(materializer_protocol_schema) != materializer_protocol_bytes:
        raise PackageSemanticError("physical task materialization schema must use canonical JSON")

    _validate_core_bindings(
        manifest,
        metadata=metadata,
        world_spec=world_spec,
        curriculum=curriculum,
        evaluator=evaluator,
        materializer_protocol_schema=materializer_protocol_schema,
        provenance=provenance,
        assurance=assurance,
        fidelity=fidelity,
        sbom=sbom,
        provenance_bytes=provenance_bytes,
        assurance_bytes=assurance_bytes,
        fidelity_bytes=fidelity_bytes,
        sbom_bytes=sbom_bytes,
        pyproject_bytes=pyproject_bytes,
        uv_lock_bytes=uv_lock_bytes,
    )
    return PortablePackageContracts(
        metadata=metadata,
        world_spec=world_spec,
        curriculum=curriculum,
        evaluator=evaluator,
        materializer_protocol_schema=materializer_protocol_schema,
        provenance=provenance,
        assurance=assurance,
        fidelity=fidelity,
        sbom=sbom,
    )


def validate_package_release_bindings(
    manifest: EnvironmentPackageManifest,
    contracts: PortablePackageContracts,
    *,
    design: EnvironmentDesign,
    candidate_manifest: CandidateManifest,
    implementation_lineage: ImplementationLineage,
    report: JudgeReport,
) -> None:
    """Recompile evidence documents from signed artifacts and compare exact values."""

    if design.world_spec != contracts.world_spec:
        raise PackageSemanticError("Design artifact differs from the physical WorldSpec")
    if design.curriculum != contracts.curriculum:
        raise PackageSemanticError("Design artifact differs from the physical curriculum")
    if manifest.lineage.implementation != implementation_lineage:
        raise PackageSemanticError(
            "manifest implementation lineage differs from its exact artifact"
        )
    if candidate_manifest.design_ref != manifest.design_ref:
        raise PackageSemanticError("CandidateManifest and manifest bind different designs")
    if candidate_manifest.implementation_lineage_ref != manifest.implementation_lineage_ref:
        raise PackageSemanticError(
            "CandidateManifest and manifest bind different implementation lineage"
        )
    if candidate_manifest.candidate_source_tree_digest != manifest.candidate_source_tree_digest:
        raise PackageSemanticError("CandidateManifest and manifest bind different source trees")
    if candidate_manifest.runtime != manifest.runtime:
        raise PackageSemanticError("CandidateManifest and manifest runtime descriptors differ")
    if candidate_manifest.task_materializer != manifest.task_materializer:
        raise PackageSemanticError(
            "CandidateManifest and manifest task materializer descriptors differ"
        )
    if candidate_manifest.public_self_check != manifest.public_self_check:
        raise PackageSemanticError(
            "CandidateManifest and manifest public self-check descriptors differ"
        )
    if candidate_manifest.public_verifier_ref != manifest.public_verifier_ref:
        raise PackageSemanticError("CandidateManifest and manifest public verifier refs differ")
    candidate_files = tuple(item for item in manifest.files if item.role not in _FRAMEWORK_ROLES)
    if candidate_files != candidate_manifest.files:
        raise PackageSemanticError(
            "physical manifest candidate files differ from CandidateManifest"
        )
    if manifest.known_limits != candidate_manifest.known_limits:
        raise PackageSemanticError("manifest known limits differ from CandidateManifest")

    expected_provenance = compile_package_provenance(
        design,
        package_id=manifest.package_id,
        version=manifest.version,
        lineage=manifest.lineage,
        design_ref=manifest.design_ref,
        world_spec_ref=manifest.world_spec_ref,
        candidate_ref=manifest.candidate_ref,
        candidate_manifest_ref=manifest.candidate_manifest_ref,
        build_record_ref=manifest.build_record_ref,
        implementation_lineage_ref=manifest.implementation_lineage_ref,
        judge_report_ref=manifest.judge_report_ref,
        integration_report_ref=manifest.integration_report_ref,
        release_dossier_ref=manifest.release_dossier_ref,
        telemetry_summary_ref=manifest.telemetry_summary_ref,
        public_verifier_ref=manifest.public_verifier_ref,
        materializer_protocol_ref=manifest.task_materializer.output_schema_ref,
        curriculum_ref=manifest.task_materializer.curriculum_ref,
        candidate_source_digest=manifest.candidate_source_tree_digest,
    )
    if contracts.provenance != expected_provenance:
        raise PackageSemanticError("physical provenance differs from exact release inputs")
    expected_assurance = compile_package_assurance(
        report,
        package_id=manifest.package_id,
        version=manifest.version,
        report_ref=manifest.judge_report_ref,
        integration_report_ref=manifest.integration_report_ref,
        release_dossier_ref=manifest.release_dossier_ref,
        telemetry_summary_ref=manifest.telemetry_summary_ref,
    )
    if contracts.assurance != expected_assurance:
        raise PackageSemanticError("physical assurance differs from the exact JudgeReport")
    expected_fidelity = compile_package_fidelity(
        design,
        package_id=manifest.package_id,
        version=manifest.version,
        known_limits=candidate_manifest.known_limits,
    )
    if contracts.fidelity != expected_fidelity:
        raise PackageSemanticError("physical fidelity differs from Design/Build declarations")
    _validate_verified_license_sources(contracts.sbom, report)


def _validate_core_bindings(
    manifest: EnvironmentPackageManifest,
    *,
    metadata: EnvPackageMetadata,
    world_spec: WorldSpec,
    curriculum: CurriculumRequirements,
    evaluator: TrustedEvaluatorSpec,
    materializer_protocol_schema: dict[str, Any],
    provenance: PackageProvenance,
    assurance: PackageAssurance,
    fidelity: PackageFidelity,
    sbom: EnvironmentSbom,
    provenance_bytes: bytes,
    assurance_bytes: bytes,
    fidelity_bytes: bytes,
    sbom_bytes: bytes,
    pyproject_bytes: bytes,
    uv_lock_bytes: bytes,
) -> None:
    world_hash = world_spec.content_digest()
    curriculum_hash = curriculum.content_digest()
    boundary_hash = world_spec.boundary.content_digest()
    if world_hash != manifest.world_spec_hash:
        raise PackageSemanticError(
            "physical WorldSpec digest differs from manifest world_spec_hash"
        )
    if boundary_hash != manifest.world_boundary_hash:
        raise PackageSemanticError(
            "physical WorldBoundary digest differs from manifest world_boundary_hash"
        )
    if curriculum_hash != manifest.task_materializer.curriculum_ref.content_hash:
        raise PackageSemanticError(
            "physical CurriculumRequirements differs from task materializer curriculum_ref"
        )
    materializer_hash = sha256_digest(canonical_json_bytes(materializer_protocol_schema))
    if materializer_hash != manifest.task_materializer.output_schema_ref.content_hash:
        raise PackageSemanticError(
            "physical task materialization schema differs from output_schema_ref"
        )
    if evaluator.world_spec_hash != world_hash:
        raise PackageSemanticError("TrustedEvaluatorSpec does not bind the physical WorldSpec")
    if evaluator.curriculum_hash != curriculum_hash:
        raise PackageSemanticError(
            "TrustedEvaluatorSpec does not bind the physical CurriculumRequirements"
        )
    compiled_schema = compile_task_materializer_output_schema(curriculum)
    if canonical_json_bytes(materializer_protocol_schema) != canonical_json_bytes(compiled_schema):
        raise PackageSemanticError(
            "physical task materialization schema was not compiled from the physical curriculum"
        )

    runtime_paths = tuple(
        item.path
        for item in sorted(manifest.files, key=lambda value: value.path)
        if item.role == "runtime"
    )
    expected_metadata_fields = {
        "package_id": manifest.package_id,
        "version": manifest.version,
        "runtime_protocol": manifest.runtime.protocol,
        "runtime_launch_hash": manifest.runtime.content_digest(),
        "runtime_argv": manifest.runtime.argv,
        "runtime_workdir": manifest.runtime.workdir,
        "runtime_paths": runtime_paths,
        "task_materializer_protocol": manifest.task_materializer.protocol,
        "task_materializer_descriptor_hash": manifest.task_materializer.content_digest(),
        "task_materializer_entrypoint": manifest.task_materializer.entrypoint,
        "task_materializer_path": manifest.task_materializer.entry_path,
        "trusted_evaluator_protocol": manifest.trusted_evaluator.protocol,
        "trusted_evaluator_path": manifest.trusted_evaluator.rule_ir_path,
        "public_self_check_protocol": manifest.public_self_check.protocol,
        "public_self_check_descriptor_hash": manifest.public_self_check.content_digest(),
        "public_self_check_path": manifest.public_self_check.entry_path,
        "world_spec_path": manifest.trusted_evaluator.world_spec_path,
        "world_spec_hash": manifest.world_spec_hash,
        "world_boundary_hash": manifest.world_boundary_hash,
        "candidate_source_tree_digest": manifest.candidate_source_tree_digest,
        "dependency_lock_hash": manifest.lineage.implementation.dependency_lock_hash,
        "judge_report_revision_id": manifest.judge_report_ref.revision_id,
        "judge_report_content_hash": manifest.judge_report_ref.content_hash,
        "integration_report_revision_id": manifest.integration_report_ref.revision_id,
        "integration_report_content_hash": manifest.integration_report_ref.content_hash,
        "release_dossier_revision_id": manifest.release_dossier_ref.revision_id,
        "release_dossier_content_hash": manifest.release_dossier_ref.content_hash,
        "telemetry_summary_revision_id": manifest.telemetry_summary_ref.revision_id,
        "telemetry_summary_content_hash": manifest.telemetry_summary_ref.content_hash,
        "provenance_hash": sha256_digest(provenance_bytes),
        "assurance_hash": sha256_digest(assurance_bytes),
        "fidelity_hash": sha256_digest(fidelity_bytes),
        "sbom_hash": sha256_digest(sbom_bytes),
    }
    for field, expected in expected_metadata_fields.items():
        if getattr(metadata, field) != expected:
            raise PackageSemanticError(f"envpkg.toml differs from manifest at {field}")

    if (
        provenance.package_id != manifest.package_id
        or provenance.version != manifest.version
        or provenance.world_spec_hash != manifest.world_spec_hash
        or provenance.candidate_source_tree_digest != manifest.candidate_source_tree_digest
        or provenance.dependency_lock_hash != manifest.lineage.implementation.dependency_lock_hash
        or provenance.semantic_lineage != manifest.lineage.semantic
        or provenance.implementation_lineage != manifest.lineage.implementation
    ):
        raise PackageSemanticError("provenance does not bind the manifest release identity")
    if (
        assurance.package_id != manifest.package_id
        or assurance.version != manifest.version
        or assurance.report_ref != manifest.judge_report_ref
        or assurance.integration_report_ref != manifest.integration_report_ref
        or assurance.release_dossier_ref != manifest.release_dossier_ref
        or assurance.telemetry_summary_ref != manifest.telemetry_summary_ref
        or assurance.candidate_ref != manifest.candidate_ref
        or assurance.candidate_source_tree_digest != manifest.candidate_source_tree_digest
    ):
        raise PackageSemanticError("assurance does not bind the manifest release identity")
    if (
        fidelity.package_id != manifest.package_id
        or fidelity.version != manifest.version
        or fidelity.world_spec_hash != manifest.world_spec_hash
        or fidelity.reality_equivalence_claimed
    ):
        raise PackageSemanticError("fidelity does not bind the bounded manifest world")

    expected_sbom = compile_environment_sbom(
        package_id=manifest.package_id,
        version=manifest.version,
        files=manifest.files,
        pyproject_bytes=pyproject_bytes,
        uv_lock_bytes=uv_lock_bytes,
    )
    if _without_verified_licenses(sbom) != expected_sbom:
        raise PackageSemanticError("physical SBOM differs from pyproject.toml/uv.lock")


def _without_verified_licenses(sbom: EnvironmentSbom) -> EnvironmentSbom:
    unknown = SbomLicenseMetadata(status="unknown")
    return sbom.model_copy(
        update={
            "virtual_root": sbom.virtual_root.model_copy(update={"license": unknown}),
            "registry_dependencies": tuple(
                item.model_copy(update={"license": unknown}) for item in sbom.registry_dependencies
            ),
        }
    )


def _validate_verified_license_sources(sbom: EnvironmentSbom, report: JudgeReport) -> None:
    supply_chain_evidence = {
        ref
        for gate in report.gate_results
        if gate.gate_id == "supply_chain" and gate.hard and gate.status == "pass"
        for ref in gate.evidence_refs
    }
    licenses = (
        sbom.virtual_root.license,
        *(item.license for item in sbom.registry_dependencies),
    )
    for license_metadata in licenses:
        if license_metadata.status != "verified":
            continue
        if not set(license_metadata.evidence_refs) <= supply_chain_evidence:
            raise PackageSemanticError(
                "verified license metadata lacks exact passing Judge supply_chain evidence"
            )


def validate_package_identity(
    manifest: EnvironmentPackageManifest,
    contracts: PortablePackageContracts,
    *,
    parents: Sequence[SemanticParent],
) -> None:
    """Prove PackageId/version and lineage against physical current/parent worlds."""

    semantic = manifest.lineage.semantic
    identity = semantic.identity_decision
    world_hash = contracts.world_spec.content_digest()
    boundary_hash = contracts.world_spec.boundary.content_digest()
    if semantic.world_spec_after_hash != world_hash:
        raise PackageSemanticError("SemanticLineage does not bind the physical WorldSpec")
    if identity.boundary_after_hash != boundary_hash:
        raise PackageSemanticError("IdentityDecision does not bind the physical WorldBoundary")
    if semantic.tool_contract_set_after_hash not in _tool_contract_set_hashes(contracts.world_spec):
        raise PackageSemanticError("SemanticLineage does not bind the physical ToolContract set")
    if len(parents) != len(semantic.semantic_parent_refs):
        raise PackageSemanticError("Registry semantic parent closure is incomplete")

    if not parents:
        if identity.target_kind != "new_package":
            raise PackageSemanticError("a parentless release must create a new package")
        if any(
            value is not None
            for value in (
                semantic.world_spec_before_hash,
                semantic.tool_contract_set_before_hash,
                identity.boundary_before_hash,
            )
        ):
            raise PackageSemanticError("a parentless release cannot claim before-state hashes")
        if identity.changed_boundary_dimensions:
            raise PackageSemanticError(
                "a parentless release cannot claim changed prior-boundary dimensions"
            )
        _require_new_package_coordinate(manifest, boundary_hash)
        return

    if any(
        value is None
        for value in (
            semantic.world_spec_before_hash,
            semantic.tool_contract_set_before_hash,
            identity.boundary_before_hash,
        )
    ):
        raise PackageSemanticError("a derived release requires complete before-state hashes")
    matching_parents = tuple(
        parent for parent in parents if _matches_before_state(semantic, parent)
    )
    if not matching_parents:
        raise PackageSemanticError(
            "SemanticLineage before-state hashes do not bind any exact Registry parent"
        )
    primary = matching_parents[0]
    changed_dimensions = _changed_boundary_dimensions(
        primary.contracts.world_spec.boundary,
        contracts.world_spec.boundary,
    )
    if identity.changed_boundary_dimensions != changed_dimensions:
        raise PackageSemanticError(
            "IdentityDecision changed dimensions differ from the physical WorldBoundary delta"
        )

    if identity.target_kind == "package_revision":
        if len(parents) != 1:
            raise PackageSemanticError("package revisions require exactly one semantic parent")
        parent = parents[0].manifest
        if manifest.package_id != parent.package_id:
            raise PackageSemanticError("package revision changed its stable package_id")
        if manifest.version == parent.version:
            raise PackageSemanticError("package revision must use a new immutable version")
        if boundary_hash != parent.world_boundary_hash or changed_dimensions:
            raise PackageSemanticError("package revision changed its WorldBoundary identity")
        return

    _require_new_package_coordinate(manifest, boundary_hash)
    parent_package_ids = {parent.manifest.package_id for parent in parents}
    if manifest.package_id in parent_package_ids:
        raise PackageSemanticError("new package reused a semantic parent's package_id")


def _require_new_package_coordinate(
    manifest: EnvironmentPackageManifest,
    boundary_hash: str,
) -> None:
    expected_id = f"env:{boundary_hash.removeprefix('sha256:')[:32]}"
    if manifest.package_id != expected_id:
        raise PackageSemanticError(
            "new package_id must be derived from the physical WorldBoundary digest"
        )
    if manifest.version != _INITIAL_PACKAGE_VERSION:
        raise PackageSemanticError("new packages must start at immutable version 1.0.0")


def _matches_before_state(semantic: Any, parent: SemanticParent) -> bool:
    return bool(
        semantic.world_spec_before_hash == parent.contracts.world_spec.content_digest()
        and semantic.tool_contract_set_before_hash
        in _tool_contract_set_hashes(parent.contracts.world_spec)
        and semantic.identity_decision.boundary_before_hash
        == parent.contracts.world_spec.boundary.content_digest()
    )


def _tool_contract_set_hashes(world_spec: WorldSpec) -> frozenset[str]:
    as_declared = [item.model_dump(mode="json", exclude_none=False) for item in world_spec.tools]
    sorted_tools = [
        item.model_dump(mode="json", exclude_none=False)
        for item in sorted(world_spec.tools, key=lambda item: item.surface.tool_id)
    ]
    return frozenset(
        (
            sha256_digest(canonical_json_bytes(as_declared)),
            sha256_digest(canonical_json_bytes(sorted_tools)),
        )
    )


def _changed_boundary_dimensions(
    before: WorldBoundary,
    after: WorldBoundary,
) -> tuple[str, ...]:
    return tuple(
        field for field in _BOUNDARY_DIMENSIONS if getattr(before, field) != getattr(after, field)
    )


def _read_declared(
    root: Path,
    relative: str,
    label: str,
    *,
    read_file: Callable[[Path, str], bytes],
) -> bytes:
    path = root.joinpath(*PurePosixPath(relative).parts)
    return read_file(path, f"physical {label} is missing")


def _parse_canonical_contract[TContract: V2Contract](
    raw: bytes,
    contract_type: type[TContract],
    label: str,
) -> TContract:
    try:
        contract = contract_type.model_validate_json(raw)
    except Exception as exc:
        raise PackageSemanticError(f"physical {label} is not a valid closed contract") from exc
    if contract.stable_json_bytes() != raw:
        raise PackageSemanticError(f"physical {label} must use canonical contract JSON")
    return contract


def _strict_json_loads(raw: bytes) -> Any:
    def object_pairs(pairs: Iterable[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise PackageSemanticError(f"duplicate JSON object key: {key}")
            result[key] = value
        return result

    def reject_constant(value: str) -> None:
        raise PackageSemanticError(f"non-finite JSON number is forbidden: {value}")

    try:
        return json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=object_pairs,
            parse_constant=reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise PackageSemanticError("portable contract is not strict UTF-8 JSON") from exc


__all__ = [
    "PackageSemanticError",
    "PortablePackageContracts",
    "SemanticParent",
    "load_portable_package_contracts",
    "validate_package_identity",
    "validate_package_release_bindings",
]
