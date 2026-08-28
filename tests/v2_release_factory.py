"""Mechanical EnvironmentRelease v2 bytes for contract tests only.

This fixture is not a qualified release and cannot authorize product completion.
"""

from __future__ import annotations

import hashlib
import json
import stat
from pathlib import Path
from typing import Any

import rfc8785

FORMAT = "environment-release/2"
MANIFEST = "payload-manifest.json"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    path.chmod(0o644)


def _record(root: Path, path: Path) -> dict[str, Any]:
    return {
        "path": path.relative_to(root).as_posix(),
        "type": "file",
        "mode": stat.S_IMODE(path.stat().st_mode),
        "digest": _sha(path.read_bytes()),
    }


def _project_digest(records: list[dict[str, Any]], prefix: str) -> str:
    marker = prefix + "/"
    project = {
        "files": [
            {**record, "path": record["path"][len(marker) :]}
            for record in records
            if record["path"].startswith(marker)
        ]
    }
    return _sha(rfc8785.dumps(project))


def build_v2_release(root: Path, *, behavior: str = "alpha") -> Path:
    actor_init = f"""\
def make_environment(instance_directory):
    return {{"kind": "actor", "behavior": {behavior!r}, "instance": str(instance_directory)}}
"""
    semantics_init = f"""\
def make_semantics():
    return {{"kind": "semantics", "behavior": {behavior!r}}}
"""
    for project, source in (("actor", actor_init), ("semantics", semantics_init)):
        _write(
            root / project / "pyproject.toml",
            '[project]\nname="shared-generated-package"\nversion="0.1.0"\n',
        )
        _write(root / project / "uv.lock", "version = 1\n")
        _write(root / project / "src/shared_generated_package/__init__.py", source)

    start_schema = {
        "type": "object",
        "properties": {"seed": {"type": "integer"}},
        "additionalProperties": False,
    }
    reset_schema = {"type": "object", "additionalProperties": True}
    _write(root / "docs/schemas/start.json", json.dumps(start_schema))
    _write(root / "docs/schemas/reset.json", json.dumps(reset_schema))
    _write(root / "docs/ENVIRONMENT.md", "# Mechanical v2 fixture\n")
    qualification = {
        "format": "environment-qualification/2",
        "verdict": "mechanical_fixture_only",
    }
    (root / "qualification.json").write_bytes(rfc8785.dumps(qualification))

    records = sorted(
        (
            _record(root, path)
            for path in root.rglob("*")
            if path.is_file() and path.name != "qualification.json"
        ),
        key=lambda item: item["path"],
    )
    manifest = {"files": records}
    (root / MANIFEST).write_bytes(rfc8785.dumps(manifest))
    descriptor = {
        "format": FORMAT,
        "canonicalization": "rfc8785",
        "hash": "sha256",
        "payload_manifest": MANIFEST,
        "payload_digest": _sha(rfc8785.dumps(manifest)),
        "qualification": "qualification.json",
        "qualification_digest": _sha((root / "qualification.json").read_bytes()),
        "actor_project": "actor",
        "actor_project_digest": _project_digest(records, "actor"),
        "actor_factory": "shared_generated_package:make_environment",
        "semantics_project": "semantics",
        "semantics_project_digest": _project_digest(records, "semantics"),
        "semantics_factory": "shared_generated_package:make_semantics",
        "start_schema": "docs/schemas/start.json",
        "reset_observation_schema": "docs/schemas/reset.json",
    }
    (root / "release.json").write_bytes(rfc8785.dumps(descriptor))
    return root
