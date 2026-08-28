"""Mechanical EnvironmentRelease v2 bytes for contract tests only.

This fixture is not a qualified release and cannot authorize product completion.
"""

from __future__ import annotations

import hashlib
import json
import stat
import zipfile
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


def build_v2_release(
    root: Path,
    *,
    behavior: str = "alpha",
    mutate_semantics: bool = False,
    raise_after_mutation: bool = False,
    leak_actor_into_semantics: bool = False,
    leak_semantics_into_actor: bool = False,
    broken_semantics_startup: bool = False,
) -> Path:
    fixtures = Path(__file__).parent / "fixtures"
    actor_init = (
        (fixtures / "fx_v2_actor.py")
        .read_text(encoding="utf-8")
        .replace('BEHAVIOR = "__BEHAVIOR__"', f"BEHAVIOR = {behavior!r}")
    )
    semantics_init = (
        (fixtures / "fx_v2_semantics.py")
        .read_text(encoding="utf-8")
        .replace('BEHAVIOR = "__BEHAVIOR__"', f"BEHAVIOR = {behavior!r}")
        .replace("MUTATE = False", f"MUTATE = {mutate_semantics!r}")
        .replace("RAISE_AFTER_MUTATION = False", f"RAISE_AFTER_MUTATION = {raise_after_mutation!r}")
        .replace("BROKEN_STARTUP = False", f"BROKEN_STARTUP = {broken_semantics_startup!r}")
    )
    projects = (
        ("actor", "shared-actor", "shared_actor", actor_init),
        ("semantics", "shared-semantics", "shared_semantics", semantics_init),
    )
    for project, distribution, module, source in projects:
        _write(
            root / project / "pyproject.toml",
            f'''[project]
name = "{distribution}"
version = "0.1.0"
requires-python = ">=3.12,<3.13"
dependencies = []

[build-system]
requires = ["uv_build>=0.11.29,<0.12.0"]
build-backend = "uv_build"
''',
        )
        _write(
            root / project / "uv.lock",
            f'''version = 1
revision = 3
requires-python = ">=3.12, <3.13"

[[package]]
name = "{distribution}"
version = "0.1.0"
source = {{ editable = "." }}
''',
        )
        _write(root / project / f"src/{module}/__init__.py", source)
    if leak_actor_into_semantics:
        _write(
            root / "semantics/src/shared_actor/__init__.py",
            "LEAKED_ACTOR = True\n",
        )
    if leak_semantics_into_actor:
        _write(
            root / "actor/src/shared_semantics/__init__.py",
            "LEAKED_SEMANTICS = True\n",
        )

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
        "actor_factory": "shared_actor:make_environment",
        "semantics_project": "semantics",
        "semantics_project_digest": _project_digest(records, "semantics"),
        "semantics_factory": "shared_semantics:make_semantics",
        "start_schema": "docs/schemas/start.json",
        "reset_observation_schema": "docs/schemas/reset.json",
    }
    (root / "release.json").write_bytes(rfc8785.dumps(descriptor))
    return root


def write_v2_zip(root: Path, destination: Path) -> Path:
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
            if not path.is_file():
                continue
            info = zipfile.ZipInfo(path.relative_to(root).as_posix())
            info.create_system = 3
            info.external_attr = (stat.S_IFREG | stat.S_IMODE(path.stat().st_mode)) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, path.read_bytes())
    return destination
