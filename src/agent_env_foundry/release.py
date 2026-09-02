"""Clean-break EnvironmentRelease v2 parsing and digest verification."""

from __future__ import annotations

import hashlib
import json
import shutil
import stat
import zipfile
from dataclasses import dataclass, replace
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any, cast

import rfc8785

from agent_env_foundry.environment import JSONObject, ToolSpec
from agent_env_foundry.errors import EnvironmentContractError
from agent_env_foundry.jsonvalue import is_json_object
from agent_env_foundry.project_identity import (
    ProjectFileRecord,
    compute_authored_project_digest,
    copy_authored_project,
    project_digest,
)
from agent_env_foundry.schema import (
    SchemaError,
    require_object_root,
    validate_schema_document,
)

if TYPE_CHECKING:
    from agent_env_foundry.preparation import PreparedReleaseIdentity
    from agent_env_foundry.qualification_contracts import (
        PublicSurfaceManifest,
        QualificationCore,
        QualificationReceipt,
        QualifiedCatalogManifest,
        QualifiedStartCasesManifest,
        RequirementCoverageManifest,
    )
    from agent_env_foundry.semantics import CapabilitySpec, StartCase

__all__ = [
    "DESCRIPTOR_FORMAT_V2",
    "PayloadRecord",
    "ReleaseDescriptorV2",
    "ValidatedReleaseV2",
    "compute_project_digest",
    "compute_payload_digest",
    "parse_descriptor_v2",
    "parse_manifest",
    "publish_release_v2",
    "verify_release_v2",
    "write_release_zip_v2",
]

DESCRIPTOR_NAME = "release.json"
DESCRIPTOR_FORMAT_V2 = "environment-release/2"
CANONICALIZATION = "rfc8785"
HASH_ALGORITHM = "sha256"

RECORD_KEYS = frozenset({"path", "type", "mode", "digest"})
DESCRIPTOR_KEYS_V2 = frozenset(
    {
        "format",
        "canonicalization",
        "hash",
        "payload_manifest",
        "payload_digest",
        "qualification",
        "qualification_digest",
        "actor_project",
        "actor_project_digest",
        "actor_factory",
        "semantics_project",
        "semantics_project_digest",
        "semantics_factory",
        "start_schema",
        "reset_observation_schema",
    }
)
_V2_PAYLOAD_ROOTS = frozenset({"actor", "semantics", "qualification", "dist", "docs", "licenses"})


@dataclass(frozen=True)
class ReleaseDescriptorV2:
    format: str
    canonicalization: str
    hash: str
    payload_manifest: PurePosixPath
    payload_digest: str
    qualification: PurePosixPath
    qualification_digest: str
    actor_project: PurePosixPath
    actor_project_digest: str
    actor_factory: str
    semantics_project: PurePosixPath
    semantics_project_digest: str
    semantics_factory: str
    start_schema: PurePosixPath
    reset_observation_schema: PurePosixPath


@dataclass(frozen=True)
class PayloadRecord:
    path: PurePosixPath
    type: str
    mode: int
    digest: str


@dataclass(frozen=True)
class ValidatedReleaseV2:
    root: Path
    descriptor: ReleaseDescriptorV2
    records: tuple[PayloadRecord, ...]
    start_schema: dict[str, Any]
    reset_observation_schema: dict[str, Any]
    release_id: str
    sealed_tool_specs: tuple[ToolSpec, ...] | None = None
    sealed_capabilities: tuple[CapabilitySpec, ...] | None = None
    sealed_start_cases: tuple[StartCase, ...] | None = None
    sealed_start_seed: int | None = None
    sealed_start_limit: int | None = None
    sealed_task_goals: JSONObject | None = None

    @property
    def identity(self) -> PreparedReleaseIdentity:
        from agent_env_foundry.preparation import PreparedReleaseIdentity

        return PreparedReleaseIdentity(
            self.descriptor.format,
            self.release_id,
            self.descriptor.actor_project_digest,
            self.descriptor.semantics_project_digest,
        )


def canonical_bytes(document: Any) -> bytes:
    try:
        return rfc8785.dumps(document)
    except (TypeError, ValueError) as exc:
        raise EnvironmentContractError(
            f"document cannot be canonically serialized as JSON: {exc}"
        ) from exc


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def compute_payload_digest(manifest_document: Any) -> str:
    """Payload digest: SHA-256 of the RFC 8785 canonical manifest document."""
    return sha256_hex(canonical_bytes(manifest_document))


def safe_member_path(value: Any, *, field: str) -> PurePosixPath:
    """Validate a release-relative member path; reject escapes and absolutes."""
    if not isinstance(value, str) or not value:
        raise EnvironmentContractError(f"{field} must be a non-empty relative path string")
    if "\\" in value:
        raise EnvironmentContractError(f"{field} must not contain backslashes: {value!r}")
    path = PurePosixPath(value)
    if value.startswith("/") or path.is_absolute():
        raise EnvironmentContractError(f"{field} must be relative, got {value!r}")
    if any(part == ".." for part in path.parts):
        raise EnvironmentContractError(
            f"{field} must stay inside the release directory, got {value!r}"
        )
    if path == PurePosixPath("."):
        raise EnvironmentContractError(f"{field} must name a member, got {value!r}")
    return path


def parse_descriptor_v2(document: Any) -> ReleaseDescriptorV2:
    """Strictly decode the clean-break EnvironmentRelease v2 descriptor."""

    if not is_json_object(document):
        raise EnvironmentContractError("v2 release.json must be a JSON object")
    if document.get("format") != DESCRIPTOR_FORMAT_V2:
        raise EnvironmentContractError(f"prepared release format must be {DESCRIPTOR_FORMAT_V2!r}")
    if set(document) != DESCRIPTOR_KEYS_V2:
        raise EnvironmentContractError(
            f"v2 release.json must contain exactly {sorted(DESCRIPTOR_KEYS_V2)}, "
            f"got {sorted(document)}"
        )
    if document["canonicalization"] != CANONICALIZATION:
        raise EnvironmentContractError("v2 release canonicalization must be rfc8785")
    if document["hash"] != HASH_ALGORITHM:
        raise EnvironmentContractError("v2 release hash must be sha256")
    actor_project = safe_member_path(document["actor_project"], field="actor_project")
    semantics_project = safe_member_path(document["semantics_project"], field="semantics_project")
    if actor_project != PurePosixPath("actor") or semantics_project != PurePosixPath("semantics"):
        raise EnvironmentContractError("v2 actor and semantics projects must use fixed roots")
    return ReleaseDescriptorV2(
        format=document["format"],
        canonicalization=document["canonicalization"],
        hash=document["hash"],
        payload_manifest=safe_member_path(document["payload_manifest"], field="payload_manifest"),
        payload_digest=_hex_digest(document["payload_digest"], field="payload_digest"),
        qualification=safe_member_path(document["qualification"], field="qualification"),
        qualification_digest=_hex_digest(
            document["qualification_digest"], field="qualification_digest"
        ),
        actor_project=actor_project,
        actor_project_digest=_hex_digest(
            document["actor_project_digest"], field="actor_project_digest"
        ),
        actor_factory=_entrypoint_reference(document["actor_factory"], "actor_factory"),
        semantics_project=semantics_project,
        semantics_project_digest=_hex_digest(
            document["semantics_project_digest"], field="semantics_project_digest"
        ),
        semantics_factory=_entrypoint_reference(document["semantics_factory"], "semantics_factory"),
        start_schema=safe_member_path(document["start_schema"], field="start_schema"),
        reset_observation_schema=safe_member_path(
            document["reset_observation_schema"], field="reset_observation_schema"
        ),
    )


def parse_manifest(document: Any) -> list[PayloadRecord]:
    if not is_json_object(document) or set(document) != {"files"}:
        raise EnvironmentContractError(
            "payload manifest must be a JSON object with exactly a 'files' array"
        )
    entries = document["files"]
    if not isinstance(entries, list):
        raise EnvironmentContractError("payload manifest 'files' must be an array")
    records: list[PayloadRecord] = []
    seen: set[PurePosixPath] = set()
    for position, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise EnvironmentContractError(f"manifest record {position} must be an object")
        keys = set(entry)
        if keys != RECORD_KEYS:
            raise EnvironmentContractError(
                f"manifest record {position} for {entry.get('path')!r} must have exactly "
                f"{sorted(RECORD_KEYS)}, got {sorted(keys)}"
            )
        if entry["type"] != "file":
            raise EnvironmentContractError(
                f"manifest record {position} must describe a regular file, "
                f"got type {entry['type']!r}"
            )
        mode = entry["mode"]
        if not isinstance(mode, int) or isinstance(mode, bool) or not 0 <= mode <= 0o777:
            raise EnvironmentContractError(
                f"manifest record {position} has invalid normalized mode {mode!r}"
            )
        path = safe_member_path(entry["path"], field=f"manifest record {position} path")
        if path in seen:
            raise EnvironmentContractError(f"manifest lists duplicate path {str(path)!r}")
        seen.add(path)
        records.append(
            PayloadRecord(
                path=path,
                type=entry["type"],
                mode=mode,
                digest=_hex_digest(entry["digest"], field=f"manifest record {position} digest"),
            )
        )
    paths = [record.path for record in records]
    if paths != sorted(paths):
        raise EnvironmentContractError("manifest records must be sorted by path")
    return records


def compute_project_digest(
    records: list[PayloadRecord] | tuple[PayloadRecord, ...],
    project_root: PurePosixPath,
) -> str:
    """Digest one project from its release-bound relative file records."""

    selected = [record for record in records if record.path.is_relative_to(project_root)]
    if not selected:
        raise EnvironmentContractError(f"project {project_root} has no bound files")
    try:
        return project_digest(
            tuple(
                ProjectFileRecord(
                    str(record.path.relative_to(project_root)),
                    record.mode,
                    record.digest,
                )
                for record in selected
            ),
            require_locked_project=True,
        )
    except ValueError as exc:
        raise EnvironmentContractError(
            f"project {project_root} identity is invalid: {exc}"
        ) from exc


def publish_release_v2(
    destination: Path,
    *,
    core: QualificationCore,
    receipt: QualificationReceipt,
    actor_project: Path,
    semantics_project: Path,
    verifier_project: Path,
    expected_semantics_payload: bytes,
    public_surface: PublicSurfaceManifest,
    qualified_catalog: QualifiedCatalogManifest,
    requirement_coverage: RequirementCoverageManifest,
    qualified_start_cases: QualifiedStartCasesManifest,
    evidence_root: Path,
) -> ValidatedReleaseV2:
    """Copy frozen C3 bytes once and derive the final v2 Release ID."""

    from agent_env_foundry.qualification_contracts import QualificationContractError
    from agent_env_foundry.qualification_v2 import verify_qualification_evidence

    root = Path(destination)
    if root.exists() or root.is_symlink():
        raise EnvironmentContractError("v2 publication destination must be new")
    try:
        expected_document = json.loads(expected_semantics_payload)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise EnvironmentContractError("Expected Semantics is not canonical JSON") from exc
    if expected_semantics_payload != canonical_bytes(expected_document):
        raise EnvironmentContractError("Expected Semantics bytes are not canonical JSON")
    if sha256_hex(expected_semantics_payload) != core.expected_semantics_digest:
        raise EnvironmentContractError("Expected Semantics differs from the Qualification Core")
    declared = (
        (Path(actor_project), "actor", core.actor_project_digest),
        (Path(semantics_project), "semantics", core.semantics_project_digest),
        (Path(verifier_project), "verifier", core.verifier_project_digest),
    )
    for source, role, expected_digest in declared:
        actual = compute_authored_project_digest(
            source,
            cast(Any, role),
            require_locked_project=True,
        )
        if actual != expected_digest:
            raise EnvironmentContractError(f"frozen {role} project differs from its Core")
    if public_surface.manifest_digest != core.public_surface_manifest_digest:
        raise EnvironmentContractError("Public Surface differs from the Qualification Core")
    try:
        qualified_start_cases.validate_against(public_surface)
        receipt.validate_core(core)
    except QualificationContractError as exc:
        raise EnvironmentContractError(str(exc)) from exc
    required_capability_ids = tuple(item.capability_id for item in qualified_catalog.capabilities)
    evidence_manifest = verify_qualification_evidence(
        core,
        Path(evidence_root),
        required_capability_ids=required_capability_ids,
    )
    evidence_digest = sha256_hex(canonical_bytes(evidence_manifest))
    declared_digests = {
        "qualified_catalog_digest": qualified_catalog.catalog_digest,
        "requirement_coverage_digest": requirement_coverage.coverage_digest,
        "qualified_start_cases_digest": qualified_start_cases.start_cases_digest,
        "evidence_manifest_digest": evidence_digest,
    }
    for field, actual in declared_digests.items():
        if getattr(receipt, field) != actual:
            raise EnvironmentContractError(f"Qualification receipt {field} mismatch")

    try:
        copy_authored_project(Path(actor_project), root / "actor", "actor")
        copy_authored_project(Path(semantics_project), root / "semantics", "semantics")
        copy_authored_project(
            Path(verifier_project),
            root / "qualification/verifier",
            "verifier",
        )
        shutil.copytree(Path(evidence_root), root / "qualification/evidence")
        documents: tuple[tuple[str, Any], ...] = (
            ("qualification/core.json", core.to_document()),
            ("qualification/expected-task-semantics.json", expected_document),
            ("qualification/public-surface.json", public_surface.to_document()),
            ("qualification/qualified-catalog.json", qualified_catalog.to_document()),
            ("qualification/requirement-coverage.json", requirement_coverage.to_document()),
            (
                "qualification/qualified-start-cases.json",
                qualified_start_cases.to_document(),
            ),
            ("docs/schemas/start.json", public_surface.start_schema),
            ("docs/schemas/reset.json", public_surface.reset_observation_schema),
        )
        for relative, document in documents:
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(canonical_bytes(document))
            path.chmod(0o644)
        receipt_path = root / "qualification/receipt.json"
        receipt_path.write_bytes(canonical_bytes(receipt.to_document()))
        receipt_path.chmod(0o644)

        records = _publication_records(
            root,
            excluded={
                PurePosixPath(DESCRIPTOR_NAME),
                PurePosixPath("payload-manifest.json"),
                PurePosixPath("qualification/receipt.json"),
            },
        )
        manifest_document = {
            "files": [
                {
                    "path": record.path.as_posix(),
                    "type": record.type,
                    "mode": record.mode,
                    "digest": record.digest,
                }
                for record in records
            ]
        }
        manifest_path = root / "payload-manifest.json"
        manifest_path.write_bytes(canonical_bytes(manifest_document))
        manifest_path.chmod(0o644)
        descriptor_document = {
            "format": DESCRIPTOR_FORMAT_V2,
            "canonicalization": CANONICALIZATION,
            "hash": HASH_ALGORITHM,
            "payload_manifest": "payload-manifest.json",
            "payload_digest": compute_payload_digest(manifest_document),
            "qualification": "qualification/receipt.json",
            "qualification_digest": sha256_hex(receipt_path.read_bytes()),
            "actor_project": "actor",
            "actor_project_digest": core.actor_project_digest,
            "actor_factory": core.actor_factory,
            "semantics_project": "semantics",
            "semantics_project_digest": core.semantics_project_digest,
            "semantics_factory": core.semantics_factory,
            "start_schema": "docs/schemas/start.json",
            "reset_observation_schema": "docs/schemas/reset.json",
        }
        descriptor_path = root / DESCRIPTOR_NAME
        descriptor_path.write_bytes(canonical_bytes(descriptor_document))
        descriptor_path.chmod(0o644)
        return verify_release_v2(root)
    except Exception:
        shutil.rmtree(root, ignore_errors=True)
        raise


def _verify_release_layout_v2(release_root: Path) -> ValidatedReleaseV2:
    """Verify one immutable two-project release without preparing either runtime."""

    requested_root = Path(release_root)
    if not requested_root.is_dir() or requested_root.is_symlink():
        raise EnvironmentContractError(
            f"v2 release root {requested_root} must be a non-symlink directory"
        )
    root = requested_root.resolve()
    descriptor_path = _regular_file_within(
        root, PurePosixPath(DESCRIPTOR_NAME), role=DESCRIPTOR_NAME
    )
    descriptor_bytes = descriptor_path.read_bytes()
    descriptor_document = _read_json(descriptor_path, role=DESCRIPTOR_NAME)
    if descriptor_bytes != canonical_bytes(descriptor_document):
        raise EnvironmentContractError(
            "v2 release descriptor bytes are not canonical RFC 8785 JSON"
        )
    descriptor = parse_descriptor_v2(descriptor_document)
    if descriptor.payload_manifest != PurePosixPath("payload-manifest.json"):
        raise EnvironmentContractError("v2 payload manifest must be payload-manifest.json")
    manifest_path = _regular_file_within(
        root, descriptor.payload_manifest, role="v2 payload manifest"
    )
    manifest_bytes = manifest_path.read_bytes()
    manifest_document = _read_json(manifest_path, role="v2 payload manifest")
    if manifest_bytes != canonical_bytes(manifest_document):
        raise EnvironmentContractError("v2 payload manifest bytes are not canonical RFC 8785 JSON")
    actual_payload_digest = compute_payload_digest(manifest_document)
    if actual_payload_digest != descriptor.payload_digest:
        raise EnvironmentContractError("v2 payload digest mismatch")
    records = tuple(parse_manifest(manifest_document))
    by_path = {record.path: record for record in records}
    protected = {
        PurePosixPath(DESCRIPTOR_NAME),
        descriptor.payload_manifest,
        descriptor.qualification,
    }
    if protected & set(by_path):
        raise EnvironmentContractError("v2 payload manifest creates a circular metadata identity")
    if any(
        not record.path.parts or record.path.parts[0] not in _V2_PAYLOAD_ROOTS for record in records
    ):
        raise EnvironmentContractError("v2 payload member lies outside the closed layout")

    actual = {
        PurePosixPath(path.relative_to(root).as_posix())
        for path in root.rglob("*")
        if path.is_file() or path.is_symlink()
    } - protected
    listed = set(by_path)
    if actual != listed:
        raise EnvironmentContractError(
            "v2 payload closure differs from manifest: "
            f"unlisted={sorted(map(str, actual - listed))}, "
            f"missing={sorted(map(str, listed - actual))}"
        )
    for record in records:
        _verify_payload_record(root, record)

    qualification_path = _regular_file_within(
        root, descriptor.qualification, role="v2 qualification"
    )
    qualification_bytes = qualification_path.read_bytes()
    if sha256_hex(qualification_bytes) != descriptor.qualification_digest:
        raise EnvironmentContractError("v2 qualification digest mismatch")
    qualification_document = _read_json(qualification_path, role="v2 qualification")
    if qualification_bytes != canonical_bytes(qualification_document):
        raise EnvironmentContractError("v2 qualification bytes are not canonical RFC 8785 JSON")

    _regular_directory_within(root, descriptor.actor_project, role="actor project")
    _regular_directory_within(root, descriptor.semantics_project, role="semantics project")
    actor_digest = compute_project_digest(records, descriptor.actor_project)
    semantics_digest = compute_project_digest(records, descriptor.semantics_project)
    if actor_digest != descriptor.actor_project_digest:
        raise EnvironmentContractError("actor project digest mismatch")
    if semantics_digest != descriptor.semantics_project_digest:
        raise EnvironmentContractError("semantics project digest mismatch")

    start_schema = _load_bound_schema(
        root, by_path, descriptor.start_schema, role="start_schema", object_root_required=True
    )
    reset_schema = _load_bound_schema(
        root,
        by_path,
        descriptor.reset_observation_schema,
        role="reset_observation_schema",
        object_root_required=False,
    )
    return ValidatedReleaseV2(
        root=root,
        descriptor=descriptor,
        records=records,
        start_schema=start_schema,
        reset_observation_schema=reset_schema,
        release_id=sha256_hex(descriptor_bytes),
    )


def verify_release_v2(release_root: Path) -> ValidatedReleaseV2:
    """Admit only a closed v2 release carrying a strict physical receipt."""

    release = _verify_release_layout_v2(release_root)
    if release.descriptor.qualification != PurePosixPath("qualification/receipt.json"):
        raise EnvironmentContractError(
            "v2 product admission requires qualification/receipt.json as a strict "
            "Qualification receipt"
        )
    from agent_env_foundry.qualification_contracts import (
        QualificationContractError,
        QualificationCore,
        public_surface_manifest_from_document,
        qualification_core_from_document,
        qualification_receipt_from_document,
        qualified_catalog_manifest_from_document,
        qualified_start_cases_manifest_from_document,
        requirement_coverage_manifest_from_document,
    )

    receipt_path = _regular_file_within(
        release.root,
        release.descriptor.qualification,
        role="strict Qualification receipt",
    )
    try:
        receipt = qualification_receipt_from_document(
            _read_json(receipt_path, role="strict Qualification receipt")
        )
    except QualificationContractError as exc:
        raise EnvironmentContractError(f"strict Qualification receipt is invalid: {exc}") from exc
    if (
        receipt.actor_project_digest != release.descriptor.actor_project_digest
        or receipt.semantics_project_digest != release.descriptor.semantics_project_digest
    ):
        raise EnvironmentContractError(
            "strict Qualification receipt project digests differ from the release descriptor"
        )
    by_path = {record.path: record for record in release.records}
    core_document = _load_bound_json_document(
        release.root,
        by_path,
        PurePosixPath("qualification/core.json"),
        role="Qualification Core",
    )
    expected_path = _bound_file(
        release.root,
        by_path,
        PurePosixPath("qualification/expected-task-semantics.json"),
        role="Expected TaskSemantics",
    )
    expected_bytes = expected_path.read_bytes()
    expected_document = _read_json(expected_path, role="Expected TaskSemantics")
    if expected_bytes != canonical_bytes(expected_document):
        raise EnvironmentContractError("Expected TaskSemantics bytes are not canonical")
    surface = public_surface_manifest_from_document(
        _load_bound_json_document(
            release.root,
            by_path,
            PurePosixPath("qualification/public-surface.json"),
            role="Public Surface",
        )
    )
    catalog = qualified_catalog_manifest_from_document(
        _load_bound_json_document(
            release.root,
            by_path,
            PurePosixPath("qualification/qualified-catalog.json"),
            role="qualified catalog",
        )
    )
    coverage = requirement_coverage_manifest_from_document(
        _load_bound_json_document(
            release.root,
            by_path,
            PurePosixPath("qualification/requirement-coverage.json"),
            role="Requirement coverage",
        )
    )
    starts = qualified_start_cases_manifest_from_document(
        _load_bound_json_document(
            release.root,
            by_path,
            PurePosixPath("qualification/qualified-start-cases.json"),
            role="qualified StartCases",
        )
    )
    verifier_root = PurePosixPath("qualification/verifier")
    _regular_directory_within(release.root, verifier_root, role="Qualification verifier")
    verifier_digest = compute_project_digest(release.records, verifier_root)
    reconstructed_core = QualificationCore(
        expected_semantics_digest=sha256_hex(expected_bytes),
        actor_project_digest=release.descriptor.actor_project_digest,
        actor_factory=release.descriptor.actor_factory,
        semantics_project_digest=release.descriptor.semantics_project_digest,
        semantics_factory=release.descriptor.semantics_factory,
        verifier_project_digest=verifier_digest,
        verifier_factory="generated_qualification_verifier.release:make_verifier",
        public_surface_manifest_digest=surface.manifest_digest,
    )
    try:
        stored_core = qualification_core_from_document(core_document)
        if stored_core != reconstructed_core:
            raise EnvironmentContractError(
                "archived Qualification Core differs from recomputed payload bytes"
            )
        receipt.validate_core(reconstructed_core)
        starts.validate_against(surface)
    except QualificationContractError as exc:
        raise EnvironmentContractError(f"strict Qualification receipt is invalid: {exc}") from exc
    bound_digests = {
        "qualified_catalog_digest": catalog.catalog_digest,
        "requirement_coverage_digest": coverage.coverage_digest,
        "qualified_start_cases_digest": starts.start_cases_digest,
    }
    for field, actual in bound_digests.items():
        if getattr(receipt, field) != actual:
            raise EnvironmentContractError(f"strict Qualification receipt {field} mismatch")
    if release.start_schema != surface.start_schema or (
        release.reset_observation_schema != surface.reset_observation_schema
    ):
        raise EnvironmentContractError("descriptor schemas differ from the sealed Public Surface")
    required_capability_ids = tuple(item.capability_id for item in catalog.capabilities)
    if not isinstance(expected_document, dict) or not isinstance(
        expected_document.get("capabilities"), list
    ):
        raise EnvironmentContractError("Expected TaskSemantics capabilities are invalid")
    task_goals: JSONObject = {}
    for item in expected_document["capabilities"]:
        if (
            not isinstance(item, dict)
            or not isinstance(item.get("capability_id"), str)
            or not isinstance(item.get("qualification_goal"), str)
            or not item["qualification_goal"].strip()
        ):
            raise EnvironmentContractError("Expected public task goal is invalid")
        task_goals[item["capability_id"]] = item["qualification_goal"]
    if set(task_goals) != set(required_capability_ids):
        raise EnvironmentContractError("Expected public task goals differ from sealed catalog")
    from agent_env_foundry.qualification_v2 import verify_qualification_evidence

    evidence = verify_qualification_evidence(
        reconstructed_core,
        release.root / "qualification/evidence",
        required_capability_ids=required_capability_ids,
    )
    if receipt.evidence_manifest_digest != sha256_hex(canonical_bytes(evidence)):
        raise EnvironmentContractError("strict Qualification receipt evidence digest mismatch")
    _validate_requirement_coverage(
        expected_document,
        coverage,
        evidence,
        starts.start_cases_digest,
    )
    return replace(
        release,
        sealed_tool_specs=surface.tool_specs,
        sealed_capabilities=catalog.capabilities,
        sealed_start_cases=starts.cases,
        sealed_start_seed=starts.seed,
        sealed_start_limit=starts.requested_limit,
        sealed_task_goals=task_goals,
    )


def write_release_zip_v2(release_root: Path, destination: Path) -> Path:
    """Write one deterministic ZIP from an already admitted release directory."""

    release = verify_release_v2(release_root)
    return _write_verified_release_zip(
        release.root,
        destination,
        role="v2 release ZIP",
    )


def _write_verified_release_zip(
    release_root: Path,
    destination: Path,
    *,
    role: str,
) -> Path:
    """Write exact already-verified release bytes without choosing admission."""

    output = Path(destination)
    if output.exists() or output.is_symlink():
        raise EnvironmentContractError(f"{role} destination must be new")
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(
            output,
            "w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=9,
        ) as archive:
            for path in sorted(
                release_root.rglob("*"),
                key=lambda item: item.relative_to(release_root).as_posix(),
            ):
                relative = path.relative_to(release_root).as_posix()
                if path.is_dir():
                    info = zipfile.ZipInfo(
                        f"{relative}/",
                        date_time=(1980, 1, 1, 0, 0, 0),
                    )
                    info.create_system = 3
                    info.external_attr = (stat.S_IFDIR | stat.S_IMODE(path.stat().st_mode)) << 16
                    info.compress_type = zipfile.ZIP_STORED
                    archive.writestr(info, b"")
                    continue
                if not path.is_file():
                    continue
                info = zipfile.ZipInfo(relative, date_time=(1980, 1, 1, 0, 0, 0))
                info.create_system = 3
                info.external_attr = (stat.S_IFREG | stat.S_IMODE(path.stat().st_mode)) << 16
                info.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(info, path.read_bytes(), compresslevel=9)
    except Exception:
        output.unlink(missing_ok=True)
        raise
    return output


# --------------------------------------------------------------------- helpers


def _publication_records(
    root: Path,
    *,
    excluded: set[PurePosixPath],
) -> tuple[PayloadRecord, ...]:
    return _publication_records_for_roots(
        root,
        excluded=excluded,
        allowed_roots=_V2_PAYLOAD_ROOTS,
    )


def _publication_records_for_roots(
    root: Path,
    *,
    excluded: set[PurePosixPath],
    allowed_roots: frozenset[str],
) -> tuple[PayloadRecord, ...]:
    records: list[PayloadRecord] = []
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        relative = PurePosixPath(path.relative_to(root).as_posix())
        if relative in excluded:
            continue
        if path.is_symlink():
            raise EnvironmentContractError(f"publication member {relative} is a symlink")
        if not path.is_file():
            continue
        if not relative.parts or relative.parts[0] not in allowed_roots:
            raise EnvironmentContractError(
                f"publication member {relative} lies outside the closed layout"
            )
        records.append(
            PayloadRecord(
                relative,
                "file",
                stat.S_IMODE(path.stat().st_mode),
                sha256_hex(path.read_bytes()),
            )
        )
    return tuple(records)


def _bound_file(
    root: Path,
    by_path: dict[PurePosixPath, PayloadRecord],
    relative: PurePosixPath,
    *,
    role: str,
) -> Path:
    record = by_path.get(relative)
    if record is None:
        raise EnvironmentContractError(f"{role} file {relative} is not payload-bound")
    path = _regular_file_within(root, relative, role=role)
    actual = sha256_hex(path.read_bytes())
    if actual != record.digest:
        raise EnvironmentContractError(f"{role} file {relative} digest mismatch")
    return path


def _load_bound_json_document(
    root: Path,
    by_path: dict[PurePosixPath, PayloadRecord],
    relative: PurePosixPath,
    *,
    role: str,
) -> Any:
    path = _bound_file(root, by_path, relative, role=role)
    payload = path.read_bytes()
    document = _read_json(path, role=role)
    if payload != canonical_bytes(document):
        raise EnvironmentContractError(f"{role} bytes are not canonical JSON")
    return document


def _validate_requirement_coverage(
    expected: Any,
    coverage: Any,
    evidence: JSONObject,
    start_cases_digest: str,
) -> None:
    if (
        not isinstance(expected, dict)
        or expected.get("format") != "expected-task-semantics/1"
        or not isinstance(expected.get("requirements"), list)
        or not isinstance(expected.get("capabilities"), list)
    ):
        raise EnvironmentContractError("Expected TaskSemantics coverage source is invalid")
    requirements = {
        item.get("requirement_id"): item
        for item in expected["requirements"]
        if isinstance(item, dict) and isinstance(item.get("requirement_id"), str)
    }
    if len(requirements) != len(expected["requirements"]):
        raise EnvironmentContractError("Expected TaskSemantics Requirement IDs are invalid")
    capabilities = {
        item.get("capability_id"): item
        for item in expected["capabilities"]
        if isinstance(item, dict) and isinstance(item.get("capability_id"), str)
    }
    if len(capabilities) != len(expected["capabilities"]):
        raise EnvironmentContractError("Expected TaskSemantics capability IDs are invalid")
    entries = {item.requirement_id: item for item in coverage.entries}
    if set(entries) != set(requirements):
        raise EnvironmentContractError(
            "Requirement coverage does not disposition every Expected Requirement"
        )
    raw_cases = evidence.get("cases")
    if not isinstance(raw_cases, list):
        raise EnvironmentContractError("Qualification evidence cases are invalid")
    evidence_ids = {
        item["digest"]
        for item in raw_cases
        if isinstance(item, dict) and isinstance(item.get("digest"), str)
    }
    evidence_ids.add(start_cases_digest)
    positive_by_capability = {
        item["capability_id"]: item["digest"]
        for item in raw_cases
        if isinstance(item, dict)
        and item.get("category") == "positive"
        and isinstance(item.get("capability_id"), str)
        and isinstance(item.get("digest"), str)
    }
    for requirement_id, requirement in requirements.items():
        entry = entries[requirement_id]
        disposition = requirement.get("disposition")
        expected_capabilities = tuple(
            sorted(
                capability_id
                for capability_id, capability in capabilities.items()
                if isinstance(capability_id, str)
                and requirement_id in capability.get("requirement_ids", [])
            )
        )
        if entry.disposition != disposition:
            raise EnvironmentContractError(
                f"Requirement coverage disposition mismatch for {requirement_id}"
            )
        if disposition == "Taskable":
            if entry.capability_ids != expected_capabilities or any(
                positive_by_capability.get(item) not in entry.evidence_ids
                for item in expected_capabilities
            ):
                raise EnvironmentContractError(
                    f"Taskable Requirement coverage mismatch for {requirement_id}"
                )
        elif entry.capability_ids:
            raise EnvironmentContractError(
                f"non-Taskable Requirement {requirement_id} declares capabilities"
            )
        if any(item not in evidence_ids for item in entry.evidence_ids):
            raise EnvironmentContractError(
                f"Requirement coverage cites unknown evidence for {requirement_id}"
            )


def _hex_digest(value: Any, *, field: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(char not in "0123456789abcdef" for char in value.lower())
        or value != value.lower()
    ):
        raise EnvironmentContractError(
            f"{field} must be a lowercase 64-character sha256 hex digest"
        )
    return value


def _entrypoint_reference(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise EnvironmentContractError(f"{field} must be a 'module:factory' string")
    if value.count(":") != 1:
        raise EnvironmentContractError(
            f"{field} must contain exactly one ':' separating module and factory, got {value!r}"
        )
    module_name, _, attribute = value.partition(":")
    if not module_name or not attribute:
        raise EnvironmentContractError(f"{field} has an empty part: {value!r}")
    return value


def _read_json(path: Path, *, role: str) -> Any:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise EnvironmentContractError(f"cannot read {role} at {path}: {exc}") from exc
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise EnvironmentContractError(f"{role} at {path} is not valid JSON: {exc}") from exc


def _regular_file_within(root: Path, relative: PurePosixPath, *, role: str) -> Path:
    path = root / relative
    if path.is_symlink():
        raise EnvironmentContractError(f"{role} at {relative} is a symlink; rejected")
    resolved = path.resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise EnvironmentContractError(f"{role} at {relative} escapes the release root; rejected")
    if not resolved.is_file():
        raise EnvironmentContractError(f"{role} at {relative} is not a regular file")
    return path


def _regular_directory_within(root: Path, relative: PurePosixPath, *, role: str) -> Path:
    path = root / relative
    if path.is_symlink():
        raise EnvironmentContractError(f"{role} at {relative} is a symlink; rejected")
    resolved = path.resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise EnvironmentContractError(f"{role} at {relative} escapes the release root; rejected")
    if not resolved.is_dir():
        raise EnvironmentContractError(f"{role} at {relative} is not a directory")
    return path


def _verify_payload_record(root: Path, record: PayloadRecord) -> Path:
    path = _regular_file_within(root, record.path, role=f"payload member {record.path}")
    actual_digest = sha256_hex(path.read_bytes())
    if actual_digest != record.digest:
        raise EnvironmentContractError(
            f"payload member {record.path} content digest mismatch: manifest declares "
            f"{record.digest}, file verifies to {actual_digest}"
        )
    actual_mode = stat.S_IMODE(path.stat().st_mode)
    if actual_mode != record.mode:
        raise EnvironmentContractError(
            f"payload member {record.path} mode mismatch: manifest declares "
            f"{oct(record.mode)}, file has {oct(actual_mode)}"
        )
    return path


def _load_bound_schema(
    root: Path,
    by_path: dict[PurePosixPath, PayloadRecord],
    relative: PurePosixPath,
    *,
    role: str,
    object_root_required: bool,
) -> dict[str, Any]:
    record = by_path.get(relative)
    if record is None:
        raise EnvironmentContractError(
            f"{role} file {relative} is not listed in the payload manifest (unlisted member)"
        )
    path = _regular_file_within(root, relative, role=role)
    content = path.read_bytes()
    if sha256_hex(content) != record.digest:
        raise EnvironmentContractError(
            f"{role} file {relative} content digest mismatch: manifest declares "
            f"{record.digest}, file verifies to {sha256_hex(content)}"
        )
    document: dict[str, Any] = _read_json(path, role=f"{role} file {relative}")
    try:
        if object_root_required:
            require_object_root(document, role=role)
        else:
            validate_schema_document(document, role=role)
    except SchemaError as exc:
        raise EnvironmentContractError(
            f"{role} file {relative} violates the release schema rules: {exc}"
        ) from exc
    return document
