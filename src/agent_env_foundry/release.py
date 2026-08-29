"""Clean-break EnvironmentRelease v2 parsing and digest verification."""

from __future__ import annotations

import hashlib
import json
import stat
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any

import rfc8785

from agent_env_foundry.errors import EnvironmentContractError
from agent_env_foundry.jsonvalue import is_json_object
from agent_env_foundry.project_identity import ProjectFileRecord, project_digest
from agent_env_foundry.schema import (
    SchemaError,
    require_object_root,
    validate_schema_document,
)

if TYPE_CHECKING:
    from agent_env_foundry.preparation import PreparedReleaseIdentity

__all__ = [
    "DESCRIPTOR_FORMAT_V2",
    "PayloadRecord",
    "ReleaseDescriptorV2",
    "ValidatedReleaseV2",
    "compute_project_digest",
    "compute_payload_digest",
    "parse_descriptor_v2",
    "parse_manifest",
    "verify_release_v2",
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
_V2_PAYLOAD_ROOTS = frozenset({"actor", "semantics", "dist", "docs", "licenses"})


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


def verify_release_v2(release_root: Path) -> ValidatedReleaseV2:
    """Verify one immutable two-project release without preparing either runtime."""

    root = Path(release_root)
    if not root.is_dir() or root.is_symlink():
        raise EnvironmentContractError(f"v2 release root {root} must be a non-symlink directory")
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
    if descriptor.qualification != PurePosixPath("qualification.json"):
        raise EnvironmentContractError("v2 qualification must be qualification.json")

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


# --------------------------------------------------------------------- helpers


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
