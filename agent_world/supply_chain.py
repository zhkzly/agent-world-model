"""Framework-owned offline wheel admission for untrusted candidate trees."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

_PYPI_REGISTRY = "https://pypi.org/simple"
_WHEEL_HOST = "files.pythonhosted.org"
_PROJECT_KEYS = {"name", "version", "requires-python", "dependencies"}
_LOCK_TOP_LEVEL_KEYS = {"version", "revision", "requires-python", "package"}
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.!+~-]*$")


class SupplyChainError(ValueError):
    """A closed failure from framework-owned dependency admission."""


@dataclass(frozen=True, slots=True)
class LockedWheel:
    """One exact lock-selected wheel admitted from the trusted store."""

    filename: str
    digest: str
    size: int


@dataclass(frozen=True, slots=True)
class AdmittedLockEntry:
    """One canonical distribution in the complete active lock closure."""

    name: str
    version: str
    wheels: tuple[LockedWheel, ...]


@dataclass(frozen=True, slots=True)
class AdmittedLockClosure:
    """The finite, framework-committed dependency set installed for a candidate."""

    entries: tuple[AdmittedLockEntry, ...]

    @property
    def distributions(self) -> frozenset[tuple[str, str]]:
        return frozenset((entry.name, entry.version) for entry in self.entries)


@dataclass(frozen=True, slots=True)
class PreparedCandidate:
    """Fresh interpreter plus the exact framework-admitted dependency closure."""

    python: Path
    admitted_lock_closure: AdmittedLockClosure


def admitted_lock_closure_value(closure: AdmittedLockClosure) -> dict[str, object]:
    """Return the one canonical, package-safe projection of an admitted closure."""

    return {
        "entries": [
            {
                "name": entry.name,
                "version": entry.version,
                "wheels": [
                    {"filename": wheel.filename, "digest": wheel.digest, "size": wheel.size}
                    for wheel in entry.wheels
                ],
            }
            for entry in closure.entries
        ]
    }


def compile_sbom(root: Path) -> dict[str, object]:
    """Compile the portable, license-unknown SBOM from admitted local metadata.

    This intentionally reuses the same closed lock admission as installation.
    It does not resolve, download, or infer any license fact from candidate
    metadata or a filename.
    """

    project, _ = _read_candidate_metadata(root)
    closure = validate_candidate_dependencies(root)
    return {
        "schema_version": "sbom@1",
        "root": {
            "name": _normalized_name(project["name"]),
            "version": project["version"],
            "license_state": "unknown",
        },
        "dependencies": [
            {
                "name": entry.name,
                "version": entry.version,
                "license_state": "unknown",
                "wheels": [
                    {
                        "filename": wheel.filename,
                        "digest": wheel.digest,
                        "size": wheel.size,
                    }
                    for wheel in entry.wheels
                ],
            }
            for entry in closure.entries
        ],
        "admitted_lock_closure": admitted_lock_closure_value(closure),
    }


def compile_sbom_from_metadata(pyproject: bytes, lock: bytes) -> dict[str, object]:
    """Recompile an SBOM from package-contained metadata, never ambient files."""

    with tempfile.TemporaryDirectory(prefix="foundry-sbom-") as temporary:
        root = Path(temporary)
        (root / "pyproject.toml").write_bytes(pyproject)
        (root / "uv.lock").write_bytes(lock)
        return compile_sbom(root)


def validate_candidate_dependencies(root: Path) -> AdmittedLockClosure:
    """Derive one complete, unambiguous registry-wheel closure before ``uv``."""

    project, lock = _read_candidate_metadata(root)
    dependencies = _project_dependencies(project)
    packages, root_dependencies = _lock_packages(lock, project)
    if root_dependencies != dependencies:
        raise SupplyChainError("candidate_dependency_lock_mismatch")

    selected: dict[str, dict[str, Any]] = {}
    pending = list(dependencies)
    while pending:
        name = pending.pop()
        if name in selected:
            continue
        package = packages.get(name)
        if package is None:
            raise SupplyChainError("candidate_dependency_unlocked")
        selected[name] = package
        pending.extend(_package_dependency_names(package))

    # A lock containing inactive packages/groups/extras would require the
    # framework to choose a resolver shape. C5 admits exactly one closure.
    if set(selected) != set(packages):
        raise SupplyChainError("candidate_dependency_closure_ambiguous")
    entries = tuple(
        AdmittedLockEntry(name, selected[name]["version"], _package_wheels(selected[name]))
        for name in sorted(selected)
    )
    return AdmittedLockClosure(entries)


def _read_candidate_metadata(root: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    pyproject = root / "pyproject.toml"
    lock = root / "uv.lock"
    if (root / "uv.toml").exists():
        raise SupplyChainError("candidate_dependency_source_forbidden")
    try:
        project = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        lock_data = tomllib.loads(lock.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise SupplyChainError("candidate_dependency_metadata_missing") from exc
    if not isinstance(project, dict) or set(project) != {"project"}:
        raise SupplyChainError("candidate_dependency_source_forbidden")
    project_data = project.get("project")
    if not isinstance(project_data, dict) or set(project_data).difference(_PROJECT_KEYS):
        raise SupplyChainError("candidate_dependency_metadata_invalid")
    if not isinstance(project_data.get("name"), str) or not isinstance(
        project_data.get("version"), str
    ):
        raise SupplyChainError("candidate_dependency_metadata_invalid")
    if not isinstance(lock_data, dict) or set(lock_data).difference(_LOCK_TOP_LEVEL_KEYS):
        raise SupplyChainError("candidate_dependency_source_forbidden")
    if not isinstance(lock_data.get("version"), int):
        raise SupplyChainError("candidate_dependency_metadata_invalid")
    return project_data, lock_data


def _project_dependencies(project: dict[str, Any]) -> tuple[str, ...]:
    values = project.get("dependencies", [])
    if not isinstance(values, list):
        raise SupplyChainError("candidate_dependency_metadata_invalid")
    names: list[str] = []
    for requirement in values:
        if not isinstance(requirement, str):
            raise SupplyChainError("candidate_dependency_metadata_invalid")
        match = re.fullmatch(
            r"([A-Za-z0-9][A-Za-z0-9_.-]*)==([A-Za-z0-9][A-Za-z0-9_.!+~-]*)",
            requirement,
        )
        if match is None:
            raise SupplyChainError("candidate_dependency_source_forbidden")
        names.append(_normalized_name(match.group(1)))
    if len(set(names)) != len(names):
        raise SupplyChainError("candidate_dependency_closure_ambiguous")
    return tuple(names)


def _lock_packages(
    lock: dict[str, Any], project: dict[str, Any]
) -> tuple[dict[str, dict[str, Any]], tuple[str, ...]]:
    values = lock.get("package", [])
    if not isinstance(values, list):
        raise SupplyChainError("candidate_dependency_metadata_invalid")
    packages: dict[str, dict[str, Any]] = {}
    root_dependencies: tuple[str, ...] | None = None
    root_name = _normalized_name(project["name"])
    root_version = project["version"]
    for package in values:
        if not isinstance(package, dict):
            raise SupplyChainError("candidate_dependency_metadata_invalid")
        name = package.get("name")
        version = package.get("version")
        source = package.get("source")
        if (
            not isinstance(name, str)
            or not isinstance(version, str)
            or not isinstance(source, dict)
        ):
            raise SupplyChainError("candidate_dependency_metadata_invalid")
        normalized = _normalized_name(name)
        if normalized == root_name and version == root_version:
            if set(package).difference({"name", "version", "source", "dependencies"}) or source != {
                "virtual": "."
            }:
                raise SupplyChainError("candidate_dependency_source_forbidden")
            if root_dependencies is not None:
                raise SupplyChainError("candidate_dependency_closure_ambiguous")
            root_dependencies = _dependency_names(package.get("dependencies", []))
            continue
        if set(package).difference({"name", "version", "source", "dependencies", "wheels"}):
            raise SupplyChainError("candidate_dependency_source_forbidden")
        if (
            normalized in packages
            or source != {"registry": _PYPI_REGISTRY}
            or not _NAME.fullmatch(name)
            or not _VERSION.fullmatch(version)
        ):
            raise SupplyChainError("candidate_dependency_closure_ambiguous")
        packages[normalized] = package
    if root_dependencies is None and not packages and not project.get("dependencies", []):
        root_dependencies = ()
    if root_dependencies is None:
        raise SupplyChainError("candidate_dependency_lock_mismatch")
    return packages, root_dependencies


def _dependency_names(values: object) -> tuple[str, ...]:
    if not isinstance(values, list):
        raise SupplyChainError("candidate_dependency_metadata_invalid")
    names: list[str] = []
    for dependency in values:
        if not isinstance(dependency, dict) or set(dependency) != {"name"}:
            raise SupplyChainError("candidate_dependency_source_forbidden")
        name = dependency.get("name")
        if not isinstance(name, str) or not _NAME.fullmatch(name):
            raise SupplyChainError("candidate_dependency_metadata_invalid")
        names.append(_normalized_name(name))
    if len(set(names)) != len(names):
        raise SupplyChainError("candidate_dependency_closure_ambiguous")
    return tuple(names)


def _package_dependency_names(package: dict[str, Any]) -> tuple[str, ...]:
    return _dependency_names(package.get("dependencies", []))


def _package_wheels(package: dict[str, Any]) -> tuple[LockedWheel, ...]:
    values = package.get("wheels")
    if not isinstance(values, list) or not values:
        raise SupplyChainError("candidate_dependency_unlocked")
    name = _normalized_name(package["name"])
    version = package["version"]
    wheels: list[LockedWheel] = []
    for value in values:
        if not isinstance(value, dict) or set(value) != {"url", "hash", "size"}:
            raise SupplyChainError("candidate_dependency_source_forbidden")
        url = value.get("url")
        digest = value.get("hash")
        size = value.get("size")
        parsed = urlparse(url) if isinstance(url, str) else None
        filename = Path(parsed.path).name if parsed is not None else ""
        parts = filename.split("-")
        if (
            parsed is None
            or parsed.scheme != "https"
            or parsed.netloc != _WHEEL_HOST
            or parsed.query
            or parsed.fragment
            or not filename.endswith(".whl")
            or len(parts) < 5
            or _normalized_name(parts[0]) != name
            or parts[1] != version
            or not isinstance(digest, str)
            or not re.fullmatch(r"sha256:[0-9a-f]{64}", digest)
            or not isinstance(size, int)
            or size < 1
        ):
            raise SupplyChainError("candidate_dependency_source_forbidden")
        wheels.append(LockedWheel(filename, digest, size))
    if len({(wheel.filename, wheel.digest) for wheel in wheels}) != len(wheels):
        raise SupplyChainError("candidate_dependency_closure_ambiguous")
    return tuple(sorted(wheels, key=lambda wheel: (wheel.filename, wheel.digest)))


def _normalized_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _digest(path: Path) -> str:
    return f"sha256:{sha256(path.read_bytes()).hexdigest()}"


def _digest_tree(root: Path) -> str:
    files = [
        (path.relative_to(root).as_posix(), _digest(path))
        for path in sorted(root.rglob("*"))
        if path.is_file() and not path.is_symlink()
    ]
    encoded = "\n".join(f"{name}\0{digest}" for name, digest in files).encode()
    return f"sha256:{sha256(encoded).hexdigest()}"


def _admit_wheels(store: Path | None, closure: AdmittedLockClosure, destination: Path) -> None:
    destination.mkdir()
    if not closure.entries:
        return
    if store is None or not store.is_dir():
        raise SupplyChainError("candidate_trusted_wheel_missing")
    for entry in closure.entries:
        for wheel in entry.wheels:
            source = store / wheel.filename
            if (
                not source.is_file()
                or source.is_symlink()
                or source.stat().st_size != wheel.size
                or _digest(source) != wheel.digest
            ):
                raise SupplyChainError("candidate_trusted_wheel_mismatch")
            target = destination / wheel.filename
            if target.exists() or target.is_symlink():
                raise SupplyChainError("candidate_dependency_closure_ambiguous")
            shutil.copyfile(source, target)
            if target.stat().st_size != wheel.size or _digest(target) != wheel.digest:
                raise SupplyChainError("candidate_trusted_wheel_mismatch")


def _requirements(closure: AdmittedLockClosure) -> str:
    lines: list[str] = []
    for entry in closure.entries:
        hashes = " ".join(f"--hash={wheel.digest}" for wheel in entry.wheels)
        lines.append(f"{entry.name}=={entry.version} {hashes}\n")
    return "".join(lines)


def _minimal_environment() -> dict[str, str]:
    return {"PATH": os.defpath}


def offline_uv_argv(
    framework_python: str,
    environment: Path,
    cache: Path,
    config: Path,
    wheel_dir: Path,
    requirements: Path,
    uv: str,
) -> tuple[list[str], list[str], dict[str, str]]:
    """Return the only C5 installer argv lists and their scrubbed environment."""

    venv = [
        uv,
        "venv",
        "--no-project",
        "--python",
        framework_python,
        "--no-python-downloads",
        "--config-file",
        str(config),
        str(environment),
    ]
    sync = [
        uv,
        "pip",
        "sync",
        "--python",
        str(environment / "bin" / "python"),
        "--offline",
        "--no-build",
        "--strict",
        "--allow-empty-requirements",
        "--require-hashes",
        "--no-index",
        "--find-links",
        str(wheel_dir),
        "--config-file",
        str(config),
        "--cache-dir",
        str(cache),
        str(requirements),
    ]
    return venv, sync, _minimal_environment()


def _installed_distributions(python: Path, env: dict[str, str]) -> list[tuple[str, str]]:
    script = (
        "import importlib.metadata,json; "
        "print(json.dumps(sorted((d.metadata['Name'], d.version) "
        "for d in importlib.metadata.distributions())))"
    )
    try:
        result = subprocess.run(  # noqa: S603 - framework-created venv interpreter
            [str(python), "-c", script],
            env=env,
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
        raw = json.loads(result.stdout)
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise SupplyChainError("candidate_install_inventory_failed") from exc
    if not isinstance(raw, list) or not all(
        isinstance(item, list) and len(item) == 2 and all(isinstance(part, str) for part in item)
        for item in raw
    ):
        raise SupplyChainError("candidate_install_inventory_failed")
    return [(_normalized_name(name), version) for name, version in raw]


@contextmanager
def prepare_candidate(
    root: Path, trusted_wheel_store: Path | None = None
) -> Iterator[PreparedCandidate]:
    """Create a fresh, dependency-only venv from the admitted wheel closure."""

    root = root.resolve()
    closure = validate_candidate_dependencies(root)
    with tempfile.TemporaryDirectory(prefix="foundry-uv-") as temporary:
        base = Path(temporary)
        work = base / "work"
        environment = base / "venv"
        cache = base / "cache"
        config = base / "empty.toml"
        wheel_dir = base / "verified-wheels"
        requirements = base / "requirements.txt"
        work.mkdir()
        config.write_text("", encoding="utf-8")
        requirements.write_text(_requirements(closure), encoding="utf-8")
        _admit_wheels(trusted_wheel_store, closure, wheel_dir)

        uv_path = shutil.which("uv")
        if uv_path is None:
            raise SupplyChainError("uv_missing")
        uv = str(Path(uv_path).resolve())
        env = _minimal_environment()
        try:
            version = subprocess.run(  # noqa: S603 - resolved framework executable
                [uv, "--version"], env=env, capture_output=True, text=True, check=True, timeout=10
            ).stdout.strip()
        except (OSError, subprocess.SubprocessError) as exc:
            raise SupplyChainError("uv_version_unavailable") from exc
        if version.split()[:2] != ["uv", "0.11.29"]:
            raise SupplyChainError("uv_version_unverified")

        source_before = _digest_tree(root)
        lock_before = _digest(root / "uv.lock")
        requirements_before = _digest(requirements)
        store_before = _digest_tree(wheel_dir)
        venv_argv, sync_argv, command_env = offline_uv_argv(
            str(Path(sys.executable).resolve()),
            environment,
            cache,
            config,
            wheel_dir,
            requirements,
            uv,
        )
        for argv in (venv_argv, sync_argv):
            try:
                result = subprocess.run(  # noqa: S603 - reviewed fixed argv, no shell
                    argv,
                    cwd=work,
                    env=command_env,
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=180,
                )
            except (OSError, subprocess.SubprocessError) as exc:
                raise SupplyChainError("candidate_install_failed") from exc
            if result.returncode != 0:
                raise SupplyChainError("candidate_install_failed")

        if (
            source_before != _digest_tree(root)
            or lock_before != _digest(root / "uv.lock")
            or requirements_before != _digest(requirements)
            or store_before != _digest_tree(wheel_dir)
        ):
            raise SupplyChainError("candidate_install_input_mutated")
        python = environment / "bin" / "python"
        if not python.is_file():
            raise SupplyChainError("candidate_python_missing")
        installed = _installed_distributions(python, command_env)
        installed_set = frozenset(installed)
        if len(installed_set) != len(installed) or installed_set != closure.distributions:
            raise SupplyChainError("candidate_install_distribution_mismatch")
        yield PreparedCandidate(python, closure)
