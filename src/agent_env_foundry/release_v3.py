"""Internal EnvironmentRelease/3 publication and verification vertical."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from agent_env_foundry.conformance_v3 import (
    ConformanceContractError,
    EnvironmentConformanceReceipt,
    conformance_receipt_from_document,
)
from agent_env_foundry.environment import JSONObject
from agent_env_foundry.errors import EnvironmentContractError
from agent_env_foundry.project_identity import (
    compute_authored_project_digest,
    copy_authored_project,
)
from agent_env_foundry.release import (
    DESCRIPTOR_NAME,
    PayloadRecord,
    _load_bound_json_document,
    _load_bound_schema,
    _publication_records_for_roots,
    _read_json,
    _regular_directory_within,
    _regular_file_within,
    _verify_payload_record,
    _write_verified_release_zip,
    canonical_bytes,
    compute_payload_digest,
    compute_project_digest,
    parse_manifest,
    sha256_hex,
)
from agent_env_foundry.release_v3_contract import (
    DESCRIPTOR_FORMAT_V3,
    ReleaseDescriptorV3,
    parse_descriptor_v3,
    validate_payload_paths_v3,
)

_PAYLOAD_ROOTS_V3 = frozenset({"actor", "conformance", "docs", "dist", "licenses"})
_EVIDENCE_PATH = PurePosixPath("conformance/evidence/report.json")


@dataclass(frozen=True, slots=True)
class ValidatedReleaseV3:
    root: Path
    descriptor: ReleaseDescriptorV3
    records: tuple[PayloadRecord, ...]
    start_schema: JSONObject
    reset_observation_schema: JSONObject
    state_schema: JSONObject
    receipt: EnvironmentConformanceReceipt
    release_id: str


def publish_release_v3_internal(
    destination: Path,
    *,
    actor_project: Path,
    receipt: EnvironmentConformanceReceipt,
    evidence: JSONObject,
    start_schema: JSONObject,
    reset_observation_schema: JSONObject,
    state_schema: JSONObject,
) -> ValidatedReleaseV3:
    root = Path(destination)
    if root.exists() or root.is_symlink():
        raise EnvironmentContractError("v3 publication destination must be new")
    actual_actor_digest = compute_authored_project_digest(
        Path(actor_project), "actor", require_locked_project=True
    )
    expected = {
        "actor_project_digest": actual_actor_digest,
        "start_schema_digest": sha256_hex(canonical_bytes(start_schema)),
        "reset_observation_schema_digest": sha256_hex(canonical_bytes(reset_observation_schema)),
        "state_schema_digest": sha256_hex(canonical_bytes(state_schema)),
        "evidence_digest": sha256_hex(canonical_bytes(evidence)),
    }
    for field, value in expected.items():
        if getattr(receipt, field) != value:
            raise EnvironmentContractError(f"v3 conformance receipt {field} mismatch")
    try:
        copy_authored_project(Path(actor_project), root / "actor", "actor")
        documents = (
            (_EVIDENCE_PATH, evidence),
            (PurePosixPath("docs/schemas/start.json"), start_schema),
            (PurePosixPath("docs/schemas/reset.json"), reset_observation_schema),
            (PurePosixPath("docs/schemas/state.json"), state_schema),
        )
        for relative, document in documents:
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(canonical_bytes(document))
            path.chmod(0o644)
        receipt_path = root / "conformance/receipt.json"
        receipt_path.parent.mkdir(parents=True, exist_ok=True)
        receipt_path.write_bytes(canonical_bytes(receipt.to_document()))
        receipt_path.chmod(0o644)

        records = _publication_records_for_roots(
            root,
            excluded={
                PurePosixPath(DESCRIPTOR_NAME),
                PurePosixPath("payload-manifest.json"),
                PurePosixPath("conformance/receipt.json"),
            },
            allowed_roots=_PAYLOAD_ROOTS_V3,
        )
        validate_payload_paths_v3(tuple(item.path.as_posix() for item in records))
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
            "format": DESCRIPTOR_FORMAT_V3,
            "canonicalization": "rfc8785",
            "hash": "sha256",
            "payload_manifest": "payload-manifest.json",
            "payload_digest": compute_payload_digest(manifest_document),
            "conformance": "conformance/receipt.json",
            "conformance_digest": sha256_hex(receipt_path.read_bytes()),
            "actor_project": "actor",
            "actor_project_digest": receipt.actor_project_digest,
            "actor_factory": receipt.actor_factory,
            "state_reader_factory": receipt.state_reader_factory,
            "start_schema": "docs/schemas/start.json",
            "reset_observation_schema": "docs/schemas/reset.json",
            "state_schema": "docs/schemas/state.json",
        }
        descriptor_path = root / DESCRIPTOR_NAME
        descriptor_path.write_bytes(canonical_bytes(descriptor_document))
        descriptor_path.chmod(0o644)
        return verify_release_v3_internal(root)
    except Exception:
        shutil.rmtree(root, ignore_errors=True)
        raise


def verify_release_v3_internal(release_root: Path) -> ValidatedReleaseV3:
    requested = Path(release_root)
    if not requested.is_dir() or requested.is_symlink():
        raise EnvironmentContractError("v3 release root must be a real directory")
    root = requested.resolve()
    descriptor_path = _regular_file_within(
        root, PurePosixPath(DESCRIPTOR_NAME), role="v3 release descriptor"
    )
    descriptor_bytes = descriptor_path.read_bytes()
    descriptor_document = _read_json(descriptor_path, role="v3 release descriptor")
    if descriptor_bytes != canonical_bytes(descriptor_document):
        raise EnvironmentContractError("v3 release descriptor bytes are not canonical")
    descriptor = parse_descriptor_v3(descriptor_document)
    manifest_path = _regular_file_within(
        root, descriptor.payload_manifest, role="v3 payload manifest"
    )
    manifest_document = _read_json(manifest_path, role="v3 payload manifest")
    if manifest_path.read_bytes() != canonical_bytes(manifest_document):
        raise EnvironmentContractError("v3 payload manifest bytes are not canonical")
    if compute_payload_digest(manifest_document) != descriptor.payload_digest:
        raise EnvironmentContractError("v3 payload digest mismatch")
    records = tuple(parse_manifest(manifest_document))
    validate_payload_paths_v3(tuple(item.path.as_posix() for item in records))
    by_path = {item.path: item for item in records}
    protected = {
        PurePosixPath(DESCRIPTOR_NAME),
        descriptor.payload_manifest,
        descriptor.conformance,
    }
    if protected & set(by_path):
        raise EnvironmentContractError("v3 payload manifest creates circular metadata identity")
    actual = {
        PurePosixPath(path.relative_to(root).as_posix())
        for path in root.rglob("*")
        if path.is_file() or path.is_symlink()
    } - protected
    if actual != set(by_path):
        raise EnvironmentContractError("v3 payload closure differs from manifest")
    for record in records:
        _verify_payload_record(root, record)

    receipt_path = _regular_file_within(root, descriptor.conformance, role="v3 conformance")
    receipt_bytes = receipt_path.read_bytes()
    if sha256_hex(receipt_bytes) != descriptor.conformance_digest:
        raise EnvironmentContractError("v3 conformance digest mismatch")
    if receipt_bytes != canonical_bytes(_read_json(receipt_path, role="v3 conformance")):
        raise EnvironmentContractError("v3 conformance bytes are not canonical")
    try:
        receipt = conformance_receipt_from_document(_read_json(receipt_path, role="v3 conformance"))
    except ConformanceContractError as exc:
        raise EnvironmentContractError(f"v3 conformance receipt is invalid: {exc}") from exc
    if (
        receipt.actor_project_digest != descriptor.actor_project_digest
        or receipt.actor_factory != descriptor.actor_factory
        or receipt.state_reader_factory != descriptor.state_reader_factory
    ):
        raise EnvironmentContractError("v3 conformance actor authority mismatch")

    _regular_directory_within(root, descriptor.actor_project, role="v3 actor project")
    if compute_project_digest(records, descriptor.actor_project) != descriptor.actor_project_digest:
        raise EnvironmentContractError("v3 actor project digest mismatch")
    start = _load_bound_schema(
        root, by_path, descriptor.start_schema, role="start_schema", object_root_required=True
    )
    reset = _load_bound_schema(
        root,
        by_path,
        descriptor.reset_observation_schema,
        role="reset_observation_schema",
        object_root_required=False,
    )
    state = _load_bound_schema(
        root, by_path, descriptor.state_schema, role="state_schema", object_root_required=False
    )
    schema_digests = {
        "start_schema_digest": sha256_hex(canonical_bytes(start)),
        "reset_observation_schema_digest": sha256_hex(canonical_bytes(reset)),
        "state_schema_digest": sha256_hex(canonical_bytes(state)),
    }
    if any(getattr(receipt, field) != value for field, value in schema_digests.items()):
        raise EnvironmentContractError("v3 conformance schema digest mismatch")
    evidence = _load_bound_json_document(
        root, by_path, _EVIDENCE_PATH, role="v3 conformance evidence"
    )
    if receipt.evidence_digest != sha256_hex(canonical_bytes(evidence)):
        raise EnvironmentContractError("v3 conformance evidence digest mismatch")
    return ValidatedReleaseV3(
        root,
        descriptor,
        records,
        start,
        reset,
        state,
        receipt,
        sha256_hex(descriptor_bytes),
    )


def write_release_zip_v3_internal(release_root: Path, destination: Path) -> Path:
    """Write one deterministic archive from verified EnvironmentRelease/3 bytes."""

    release = verify_release_v3_internal(release_root)
    return _write_verified_release_zip(
        release.root,
        destination,
        role="v3 release ZIP",
    )


__all__ = [
    "ValidatedReleaseV3",
    "publish_release_v3_internal",
    "verify_release_v3_internal",
    "write_release_zip_v3_internal",
]
