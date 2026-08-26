"""Release descriptor and payload-manifest parsing with digest verification.

This is the loader-facing half of the release contract (S1 Slice 1): it parses
``release.json`` and ``payload-manifest.json`` strictly, verifies the payload
digest plus every listed member's bytes and normalized mode, and loads
digest-bound schema members without letting any path escape the release root.

Release identity, assembly, Qualification binding and cold publication belong
to Slice 5; nothing here writes, publishes, or claims a qualified release.
"""

from __future__ import annotations

import hashlib
import json
import stat
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import rfc8785

from agent_env_foundry.errors import EnvironmentContractError
from agent_env_foundry.jsonvalue import is_json_object
from agent_env_foundry.schema import (
    SchemaError,
    require_object_root,
    validate_schema_document,
)

__all__ = [
    "DESCRIPTOR_FORMAT",
    "PayloadRecord",
    "ReleaseDescriptor",
    "ValidatedReleaseContract",
    "compute_payload_digest",
    "parse_descriptor",
    "parse_manifest",
    "verify_release",
]

DESCRIPTOR_NAME = "release.json"
DESCRIPTOR_FORMAT = "environment-release/1"
CANONICALIZATION = "rfc8785"
HASH_ALGORITHM = "sha256"

DESCRIPTOR_KEYS = frozenset(
    {
        "format",
        "canonicalization",
        "hash",
        "payload_manifest",
        "payload_digest",
        "environment_factory",
        "start_schema",
        "reset_observation_schema",
    }
)
RECORD_KEYS = frozenset({"path", "type", "mode", "digest"})


@dataclass(frozen=True)
class ReleaseDescriptor:
    format: str
    canonicalization: str
    hash: str
    payload_manifest: PurePosixPath
    payload_digest: str
    environment_factory: str
    start_schema: PurePosixPath
    reset_observation_schema: PurePosixPath


@dataclass(frozen=True)
class PayloadRecord:
    path: PurePosixPath
    type: str
    mode: int
    digest: str


@dataclass(frozen=True)
class ValidatedReleaseContract:
    """Loader-facing release metadata; not a qualified EnvironmentRelease."""

    descriptor: ReleaseDescriptor
    start_schema: dict[str, Any]
    reset_observation_schema: dict[str, Any]


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


def parse_descriptor(document: Any) -> ReleaseDescriptor:
    """Strictly parse ``release.json``; unknown fields are rejected, not normalized."""
    if not is_json_object(document):
        raise EnvironmentContractError("release.json must be a JSON object")
    keys = set(document)
    missing = sorted(DESCRIPTOR_KEYS - keys)
    if missing:
        raise EnvironmentContractError(f"release.json is missing required fields: {missing}")
    unknown = sorted(keys - DESCRIPTOR_KEYS)
    if unknown:
        raise EnvironmentContractError(
            f"release.json contains fields outside the release contract: {unknown}; "
            "rejected, not normalized"
        )
    if document["format"] != DESCRIPTOR_FORMAT:
        raise EnvironmentContractError(
            f"unsupported release format {document['format']!r}; expected {DESCRIPTOR_FORMAT!r}"
        )
    if document["canonicalization"] != CANONICALIZATION:
        raise EnvironmentContractError(
            f"unsupported canonicalization {document['canonicalization']!r}"
        )
    if document["hash"] != HASH_ALGORITHM:
        raise EnvironmentContractError(f"unsupported hash algorithm {document['hash']!r}")
    return ReleaseDescriptor(
        format=document["format"],
        canonicalization=document["canonicalization"],
        hash=document["hash"],
        payload_manifest=safe_member_path(document["payload_manifest"], field="payload_manifest"),
        payload_digest=_hex_digest(document["payload_digest"], field="payload_digest"),
        environment_factory=_factory_reference(document["environment_factory"]),
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


def verify_release(release_root: Path) -> ValidatedReleaseContract:
    """Validate loader-facing release bytes without assigning a release ID."""
    root = Path(release_root)
    if not root.is_dir():
        raise EnvironmentContractError(f"release root {root} is not a directory")
    if (root / DESCRIPTOR_NAME).is_symlink():
        raise EnvironmentContractError(f"{DESCRIPTOR_NAME} must not be a symlink")

    descriptor_document = _read_json(root / DESCRIPTOR_NAME, role=DESCRIPTOR_NAME)
    descriptor = parse_descriptor(descriptor_document)

    manifest_document = _read_json(
        _regular_file_within(root, descriptor.payload_manifest, role="payload manifest"),
        role="payload manifest",
    )
    actual_digest = compute_payload_digest(manifest_document)
    if actual_digest != descriptor.payload_digest:
        raise EnvironmentContractError(
            "payload digest mismatch: release.json declares "
            f"{descriptor.payload_digest}, manifest verifies to {actual_digest}"
        )

    records = parse_manifest(manifest_document)
    by_path = {record.path: record for record in records}
    # Non-circular identity DAG: the manifest must not bind itself or the
    # descriptor it is summarized by.
    for protected in (PurePosixPath(DESCRIPTOR_NAME), descriptor.payload_manifest):
        if protected in by_path:
            raise EnvironmentContractError(
                f"payload manifest must not list {protected}; identity would be circular"
            )

    for record in records:
        _verify_payload_record(root, record)

    start_schema = _load_bound_schema(
        root, by_path, descriptor.start_schema, role="start_schema", object_root_required=True
    )
    reset_observation_schema = _load_bound_schema(
        root,
        by_path,
        descriptor.reset_observation_schema,
        role="reset_observation_schema",
        object_root_required=False,
    )
    return ValidatedReleaseContract(
        descriptor=descriptor,
        start_schema=start_schema,
        reset_observation_schema=reset_observation_schema,
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


def _factory_reference(value: Any) -> str:
    if not isinstance(value, str) or not value:
        raise EnvironmentContractError("environment_factory must be a 'module:factory' string")
    if value.count(":") != 1:
        raise EnvironmentContractError(
            f"environment_factory must contain exactly one ':' separating module and "
            f"factory, got {value!r}"
        )
    module_name, _, attribute = value.partition(":")
    if not module_name or not attribute:
        raise EnvironmentContractError(f"environment_factory has an empty part: {value!r}")
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
