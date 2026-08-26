"""Test support: build mechanical release directories for loader tests.

Everything produced here is a *mechanical contract fixture*: it exercises the
release/loader boundary only. It is not a domain environment, not a qualified
``EnvironmentRelease``, and must never be presented as product-completion
evidence (PRD F8 / implement.md Slice 1 checkpoint rule).
"""

from __future__ import annotations

import hashlib
import json
import stat
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import rfc8785

DESCRIPTOR_FORMAT = "environment-release/1"

# Defaults describe the mechanical fixture environment in tests/fixtures.
DEFAULT_START_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"seed": {"type": "integer", "minimum": 0}},
    "additionalProperties": False,
}
DEFAULT_RESET_OBSERVATION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "kind": {"const": "mechanical"},
        "token": {"type": "integer"},
        "started": {"type": "boolean"},
        "seed": {"type": ["integer", "null"]},
    },
    "required": ["kind", "token", "started", "seed"],
    "additionalProperties": False,
}

START_SCHEMA_PATH = "docs/schemas/start.json"
RESET_OBSERVATION_SCHEMA_PATH = "docs/schemas/reset-observation.json"
MANIFEST_PATH = "payload-manifest.json"


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def record_for(root: Path, rel: str, *, digest: str | None = None) -> dict[str, Any]:
    """One payload-manifest record for an already-written file."""
    path = root / rel
    content = path.read_bytes()
    return {
        "path": rel,
        "type": "file",
        "mode": stat.S_IMODE(path.stat().st_mode),
        "digest": digest or sha256_hex(content),
    }


def build_release(
    root: Path,
    *,
    factory: str = "fx_contract_ok:make_environment",
    descriptor_patch: dict[str, Any] | None = None,
    descriptor_drop: Iterable[str] = (),
    declared_payload_digest: str | None = None,
    start_schema: Any = DEFAULT_START_SCHEMA,
    reset_observation_schema: Any = DEFAULT_RESET_OBSERVATION_SCHEMA,
    manifest_records: list[dict[str, Any]] | None = None,
) -> Path:
    """Write a minimal mechanical release directory and return its root."""
    (root / "docs/schemas").mkdir(parents=True, exist_ok=True)
    (root / START_SCHEMA_PATH).write_text(json.dumps(start_schema, indent=2))
    (root / RESET_OBSERVATION_SCHEMA_PATH).write_text(
        json.dumps(reset_observation_schema, indent=2)
    )

    if manifest_records is None:
        manifest_records = sorted(
            [
                record_for(root, START_SCHEMA_PATH),
                record_for(root, RESET_OBSERVATION_SCHEMA_PATH),
            ],
            key=lambda record: record["path"],
        )
    manifest = {"files": manifest_records}
    (root / MANIFEST_PATH).write_text(json.dumps(manifest, indent=2))

    descriptor: dict[str, Any] = {
        "format": DESCRIPTOR_FORMAT,
        "canonicalization": "rfc8785",
        "hash": "sha256",
        "payload_manifest": MANIFEST_PATH,
        "payload_digest": declared_payload_digest or sha256_hex(rfc8785.dumps(manifest)),
        "environment_factory": factory,
        "start_schema": START_SCHEMA_PATH,
        "reset_observation_schema": RESET_OBSERVATION_SCHEMA_PATH,
    }
    if descriptor_patch:
        descriptor.update(descriptor_patch)
    for key in descriptor_drop:
        descriptor.pop(key, None)
    (root / "release.json").write_text(json.dumps(descriptor, indent=2))
    return root
