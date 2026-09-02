"""Shared canonical artifact helpers for the sole EnvironmentRelease/3 path."""

from __future__ import annotations

import hashlib
import json
import stat
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

import rfc8785

from agent_env_foundry.errors import EnvironmentContractError
from agent_env_foundry.jsonvalue import is_json_object
from agent_env_foundry.project_identity import ProjectFileRecord, project_digest
from agent_env_foundry.schema import SchemaError, require_object_root, validate_schema_document

DESCRIPTOR_NAME = "release.json"
CANONICALIZATION = "rfc8785"
HASH_ALGORITHM = "sha256"
RECORD_KEYS = frozenset({"path", "type", "mode", "digest"})


@dataclass(frozen=True, slots=True)
class PayloadRecord:
    path: PurePosixPath
    type: str
    mode: int
    digest: str


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
    return sha256_hex(canonical_bytes(manifest_document))


def safe_member_path(value: Any, *, field: str) -> PurePosixPath:
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


def _write_verified_release_zip(
    release_root: Path,
    destination: Path,
    *,
    role: str,
) -> Path:
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


__all__ = [
    "CANONICALIZATION",
    "DESCRIPTOR_NAME",
    "HASH_ALGORITHM",
    "PayloadRecord",
    "canonical_bytes",
    "compute_payload_digest",
    "compute_project_digest",
    "parse_manifest",
    "safe_member_path",
    "sha256_hex",
]
