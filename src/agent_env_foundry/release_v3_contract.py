"""Pure EnvironmentRelease/3 descriptor and payload-path contract."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

from agent_env_foundry.errors import EnvironmentContractError
from agent_env_foundry.jsonvalue import is_json_object
from agent_env_foundry.release import (
    CANONICALIZATION,
    HASH_ALGORITHM,
    _entrypoint_reference,
    _hex_digest,
    canonical_bytes,
    safe_member_path,
    sha256_hex,
)

DESCRIPTOR_FORMAT_V3 = "environment-release/3"

_DESCRIPTOR_KEYS_V3 = frozenset(
    {
        "format",
        "canonicalization",
        "hash",
        "payload_manifest",
        "payload_digest",
        "conformance",
        "conformance_digest",
        "actor_project",
        "actor_project_digest",
        "actor_factory",
        "state_reader_factory",
        "start_schema",
        "reset_observation_schema",
        "state_schema",
    }
)
_ROOT_FILES_V3 = frozenset({"payload-manifest.json", "release.json"})
_PAYLOAD_ROOTS_V3 = frozenset({"actor", "conformance", "docs", "dist", "licenses"})
_FIXED_PATHS_V3 = {
    "payload_manifest": PurePosixPath("payload-manifest.json"),
    "conformance": PurePosixPath("conformance/receipt.json"),
    "actor_project": PurePosixPath("actor"),
    "start_schema": PurePosixPath("docs/schemas/start.json"),
    "reset_observation_schema": PurePosixPath("docs/schemas/reset.json"),
    "state_schema": PurePosixPath("docs/schemas/state.json"),
}


@dataclass(frozen=True, slots=True)
class ReleaseDescriptorV3:
    format: str
    canonicalization: str
    hash: str
    payload_manifest: PurePosixPath
    payload_digest: str
    conformance: PurePosixPath
    conformance_digest: str
    actor_project: PurePosixPath
    actor_project_digest: str
    actor_factory: str
    state_reader_factory: str
    start_schema: PurePosixPath
    reset_observation_schema: PurePosixPath
    state_schema: PurePosixPath


def parse_descriptor_v3(document: Any) -> ReleaseDescriptorV3:
    if not is_json_object(document):
        raise EnvironmentContractError("v3 release.json must be a JSON object")
    if document.get("format") != DESCRIPTOR_FORMAT_V3:
        raise EnvironmentContractError(f"v3 release format must be {DESCRIPTOR_FORMAT_V3!r}")
    if set(document) != _DESCRIPTOR_KEYS_V3:
        raise EnvironmentContractError(
            f"v3 release.json must contain exactly {sorted(_DESCRIPTOR_KEYS_V3)}, "
            f"got {sorted(document)}"
        )
    if document["canonicalization"] != CANONICALIZATION:
        raise EnvironmentContractError("v3 release canonicalization must be rfc8785")
    if document["hash"] != HASH_ALGORITHM:
        raise EnvironmentContractError("v3 release hash must be sha256")

    paths = {field: safe_member_path(document[field], field=field) for field in _FIXED_PATHS_V3}
    for field, expected in _FIXED_PATHS_V3.items():
        if paths[field] != expected:
            raise EnvironmentContractError(f"v3 {field} must be {expected.as_posix()!r}")

    return ReleaseDescriptorV3(
        format=DESCRIPTOR_FORMAT_V3,
        canonicalization=CANONICALIZATION,
        hash=HASH_ALGORITHM,
        payload_manifest=paths["payload_manifest"],
        payload_digest=_hex_digest(document["payload_digest"], field="payload_digest"),
        conformance=paths["conformance"],
        conformance_digest=_hex_digest(document["conformance_digest"], field="conformance_digest"),
        actor_project=paths["actor_project"],
        actor_project_digest=_hex_digest(
            document["actor_project_digest"], field="actor_project_digest"
        ),
        actor_factory=_entrypoint_reference(document["actor_factory"], "actor_factory"),
        state_reader_factory=_entrypoint_reference(
            document["state_reader_factory"], "state_reader_factory"
        ),
        start_schema=paths["start_schema"],
        reset_observation_schema=paths["reset_observation_schema"],
        state_schema=paths["state_schema"],
    )


def descriptor_release_id_v3(document: Any) -> str:
    parse_descriptor_v3(document)
    return sha256_hex(canonical_bytes(document))


def validate_payload_paths_v3(paths: tuple[str, ...]) -> tuple[PurePosixPath, ...]:
    resolved: list[PurePosixPath] = []
    seen: set[PurePosixPath] = set()
    for position, value in enumerate(paths):
        path = safe_member_path(value, field=f"payload path {position}")
        root = path.parts[0]
        if path.as_posix() not in _ROOT_FILES_V3 and root not in _PAYLOAD_ROOTS_V3:
            raise EnvironmentContractError(
                f"v3 payload path has prohibited root: {path.as_posix()}"
            )
        if path in seen:
            raise EnvironmentContractError(f"v3 payload path is duplicated: {path.as_posix()}")
        seen.add(path)
        resolved.append(path)
    return tuple(resolved)


__all__ = [
    "DESCRIPTOR_FORMAT_V3",
    "ReleaseDescriptorV3",
    "descriptor_release_id_v3",
    "parse_descriptor_v3",
    "validate_payload_paths_v3",
]
