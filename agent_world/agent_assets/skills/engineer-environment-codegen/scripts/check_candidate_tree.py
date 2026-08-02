#!/usr/bin/env python3
"""Deterministic preflight for CandidateBuild project mechanics.

This script intentionally checks only framework-owned project and supply-chain
mechanics. It does not evaluate WorldSpec business Rules or claim Integration,
Judge, or release success.
"""

from __future__ import annotations

import argparse
import json
import stat
import tarfile
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_UNKNOWN_LICENSE_VALUES = frozenset({"", "unknown", "none", "n/a", "na", "unspecified"})
_FORBIDDEN_DIRECTORIES = frozenset(
    {
        ".agents",
        ".codex",
        ".git",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".tox",
        ".venv",
        "__pycache__",
        "build",
        "dist",
    }
)
_FORBIDDEN_FILENAMES = frozenset(
    {
        ".env",
        ".env.local",
        "auth.json",
        "candidate_manifest.json",
        "credentials.json",
        "envpkg.toml",
        "id_dsa",
        "id_ecdsa",
        "id_ed25519",
        "id_rsa",
    }
)
_ALLOWED_SUFFIXES = frozenset(
    {
        ".cfg",
        ".csv",
        ".ini",
        ".json",
        ".lock",
        ".md",
        ".py",
        ".rst",
        ".sh",
        ".sql",
        ".toml",
        ".txt",
        ".typed",
        ".yaml",
        ".yml",
    }
)
_ALLOWED_EXTENSIONLESS = frozenset(
    {".gitignore", "LICENSE", "LICENSE-APACHE", "LICENSE-MIT", "NOTICE", "README"}
)


@dataclass(frozen=True)
class Finding:
    code: str
    path: str
    expected: str
    actual: str

    def render(self) -> str:
        return (
            f"ERROR {self.code} path={self.path} expected={self.expected!r} actual={self.actual!r}"
        )


def _load_json(path: Path, findings: list[Finding]) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        findings.append(Finding("json_unreadable", path.as_posix(), "valid JSON object", str(exc)))
        return {}
    if not isinstance(value, dict):
        findings.append(
            Finding("json_not_object", path.as_posix(), "JSON object", type(value).__name__)
        )
        return {}
    return value


def _load_toml(path: Path, findings: list[Finding]) -> dict[str, Any]:
    try:
        value = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
        findings.append(Finding("toml_unreadable", path.as_posix(), "valid TOML", str(exc)))
        return {}
    return value


def _require(
    findings: list[Finding],
    *,
    condition: bool,
    code: str,
    path: str,
    expected: str,
    actual: object,
) -> None:
    if not condition:
        findings.append(Finding(code, path, expected, repr(actual)))


def _scan_tree(candidate: Path, findings: list[Finding]) -> int:
    file_count = 0
    paths = sorted(
        candidate.rglob("*"),
        key=lambda item: item.relative_to(candidate).as_posix(),
    )
    for path in paths:
        relative = path.relative_to(candidate).as_posix()
        if len(relative) > 240 or any(
            ord(character) < 32 or ord(character) == 127 for character in relative
        ):
            findings.append(
                Finding("candidate_path_not_portable", relative, "bounded portable path", "invalid")
            )
            continue
        if path.is_symlink():
            findings.append(
                Finding(
                    "candidate_symlink",
                    relative,
                    "regular file or directory",
                    "symlink",
                )
            )
            continue
        try:
            path_stat = path.stat(follow_symlinks=False)
        except OSError:
            findings.append(
                Finding(
                    "candidate_path_unreadable", relative, "readable project entry", "unreadable"
                )
            )
            continue
        if stat.S_ISDIR(path_stat.st_mode):
            if path.name.startswith(".") or path.name in _FORBIDDEN_DIRECTORIES:
                findings.append(
                    Finding("candidate_derived_path", relative, "no derived/private path", relative)
                )
            continue
        if not stat.S_ISREG(path_stat.st_mode):
            findings.append(
                Finding(
                    "candidate_non_regular_path", relative, "regular source file", "non-regular"
                )
            )
            continue
        if path_stat.st_nlink != 1:
            findings.append(
                Finding("candidate_hardlink", relative, "one source-file link", "hard-linked")
            )
            continue
        if path.name in _FORBIDDEN_FILENAMES:
            findings.append(
                Finding(
                    "candidate_sensitive_filename", relative, "non-credential filename", relative
                )
            )
            continue
        if path.suffix.lower() not in _ALLOWED_SUFFIXES and path.name not in _ALLOWED_EXTENSIONLESS:
            findings.append(
                Finding(
                    "candidate_file_type_not_allowed",
                    relative,
                    "portable Candidate source file type",
                    path.suffix.lower() or "extensionless",
                )
            )
            continue
        try:
            tarfile.TarInfo(relative).tobuf(
                format=tarfile.USTAR_FORMAT,
                encoding="utf-8",
                errors="strict",
            )
        except (UnicodeError, ValueError):
            findings.append(
                Finding(
                    "candidate_path_not_portable", relative, "USTAR-representable path", "invalid"
                )
            )
            continue
        file_count += 1
    return file_count


def _project_license_is_declared(candidate: Path, project: dict[str, Any]) -> bool:
    """Mirror the framework's accepted root-license declaration shapes."""

    value = project.get("license")
    if isinstance(value, str):
        return value.strip().casefold() not in _UNKNOWN_LICENSE_VALUES
    if not isinstance(value, dict) or set(value) not in ({"file"}, {"text"}):
        return False
    if "text" in value:
        text = value["text"]
        return isinstance(text, str) and text.strip().casefold() not in _UNKNOWN_LICENSE_VALUES
    path_value = value["file"]
    if not isinstance(path_value, str):
        return False
    path = Path(path_value)
    return not path.is_absolute() and ".." not in path.parts and (candidate / path).is_file()


def check_workspace(workspace: Path) -> tuple[Finding, ...]:
    findings: list[Finding] = []
    candidate = workspace / "candidate"
    contract_path = workspace / "inputs" / "implementation-contract.json"
    _require(
        findings,
        condition=candidate.is_dir(),
        code="candidate_missing",
        path="candidate",
        expected="project directory",
        actual="missing",
    )
    _require(
        findings,
        condition=contract_path.is_file(),
        code="implementation_contract_missing",
        path="inputs/implementation-contract.json",
        expected="frozen contract file",
        actual="missing",
    )
    if not candidate.is_dir() or not contract_path.is_file():
        return tuple(findings)

    contract = _load_json(contract_path, findings)
    required_roots = tuple(contract.get("required_root_files", ()))
    for name in required_roots:
        if not isinstance(name, str):
            findings.append(
                Finding(
                    "invalid_required_root",
                    "required_root_files",
                    "string entries",
                    repr(name),
                )
            )
            continue
        _require(
            findings,
            condition=(candidate / name).is_file(),
            code="required_root_missing",
            path=f"candidate/{name}",
            expected="regular file",
            actual="missing",
        )

    pyproject_path = candidate / "pyproject.toml"
    lock_path = candidate / "uv.lock"
    pyproject = _load_toml(pyproject_path, findings) if pyproject_path.is_file() else {}
    lock = _load_toml(lock_path, findings) if lock_path.is_file() else {}
    project = pyproject.get("project") if isinstance(pyproject.get("project"), dict) else {}
    tool = pyproject.get("tool") if isinstance(pyproject.get("tool"), dict) else {}
    uv_config = tool.get("uv") if isinstance(tool.get("uv"), dict) else {}

    project_name = project.get("name")
    _require(
        findings,
        condition=isinstance(project_name, str) and bool(project_name.strip()),
        code="project_name_invalid",
        path="candidate/pyproject.toml:[project].name",
        expected="non-empty string",
        actual=project_name,
    )
    _require(
        findings,
        condition=project.get("requires-python") == contract.get("python_requires"),
        code="python_requires_mismatch",
        path="candidate/pyproject.toml:[project].requires-python",
        expected=repr(contract.get("python_requires")),
        actual=project.get("requires-python"),
    )
    _require(
        findings,
        condition="build-system" not in pyproject,
        code="build_system_forbidden",
        path="candidate/pyproject.toml:[build-system]",
        expected="absent",
        actual=pyproject.get("build-system"),
    )
    _require(
        findings,
        condition=uv_config.get("package") is False,
        code="uv_virtual_root_required",
        path="candidate/pyproject.toml:[tool.uv].package",
        expected="false",
        actual=uv_config.get("package"),
    )
    _require(
        findings,
        condition=_project_license_is_declared(candidate, project),
        code="project_license_declaration_missing",
        path="candidate/pyproject.toml:[project].license",
        expected="non-unknown expression, existing file, or non-unknown text",
        actual=project.get("license"),
    )

    packages = lock.get("package") if isinstance(lock.get("package"), list) else []
    virtual_roots = [
        item
        for item in packages
        if isinstance(item, dict)
        and isinstance(item.get("source"), dict)
        and item["source"].get("virtual") == "."
    ]
    _require(
        findings,
        condition=len(virtual_roots) == 1,
        code="lock_virtual_root_count",
        path="candidate/uv.lock:package",
        expected="exactly one virtual='.' package",
        actual=len(virtual_roots),
    )
    if len(virtual_roots) == 1:
        _require(
            findings,
            condition=virtual_roots[0].get("name") == project_name,
            code="lock_virtual_root_name_mismatch",
            path="candidate/uv.lock:package[source.virtual='.'].name",
            expected=repr(project_name),
            actual=virtual_roots[0].get("name"),
        )

    file_count = _scan_tree(candidate, findings)
    _require(
        findings,
        condition=file_count > 0,
        code="candidate_empty",
        path="candidate",
        expected="at least one regular file",
        actual=file_count,
    )
    return tuple(findings)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, default=Path("."))
    args = parser.parse_args(argv)
    workspace = args.workspace.resolve()
    findings = check_workspace(workspace)
    if findings:
        for finding in findings:
            print(finding.render())
        print(f"FAILED candidate-tree-preflight findings={len(findings)}")
        return 1
    file_count = sum(1 for path in (workspace / "candidate").rglob("*") if path.is_file())
    print(f"OK candidate-tree-preflight files={file_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
