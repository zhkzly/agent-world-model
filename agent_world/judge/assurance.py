"""Pure framework inspections used by the independent static and supply gates."""

from __future__ import annotations

import ast
import json
import re
import stat
import tomllib
from dataclasses import dataclass
from email import policy
from email.parser import BytesParser
from pathlib import Path, PurePosixPath
from typing import Any, Literal

from packaging.markers import default_environment
from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name
from packaging.version import InvalidVersion, Version

from agent_world.builder.workspace import CandidateWorkspaceError, CandidateWorkspaceValidator
from agent_world.contracts import (
    ArtifactRef,
    CandidateManifest,
    PackageFile,
    sha256_digest,
)
from agent_world.contracts.lineage import ImplementationLineage
from agent_world.contracts.supply_chain import (
    MAX_PUBLIC_TESTS,
    CandidateLicenseFileEvidence,
    InstalledComponentEvidence,
    LicenseMetadataEvidence,
    LockedComponentEvidence,
    LockedWheelEvidence,
    StaticFileEvidence,
    SupplyChainEvidence,
)

APPROVED_REGISTRY_URLS = ("https://pypi.org/simple", "https://pypi.org/simple/")

_TEXT_SUFFIXES = frozenset(
    {".cfg", ".ini", ".json", ".md", ".py", ".rst", ".toml", ".txt", ".yaml", ".yml"}
)
_TEXT_NAMES = frozenset({"LICENSE", "LICENSE-APACHE", "LICENSE-MIT", "NOTICE", "README"})
_FORBIDDEN_PATTERNS = (
    re.compile(rb"\bunittest\.mock\b", re.IGNORECASE),
    re.compile(rb"\bMagicMock\b"),
    re.compile(rb"\bfixture[_ -]?registry\b", re.IGNORECASE),
    re.compile(rb"\bmock[_ -]?(?:backend|runtime|environment)\b", re.IGNORECASE),
    re.compile(rb"\b(?:evaluator_goal|sealed_case|verifier_ir)\b", re.IGNORECASE),
)
_SECRET_PATTERNS = (
    re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(rb"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(
        rb"(?i)\b(?:api[_-]?key|access[_-]?token|client[_-]?secret|password)\b"
        rb"\s*[:=]\s*['\"][^'\"\r\n]{12,}['\"]"
    ),
    re.compile(rb"(?i)\bBearer\s+[A-Za-z0-9._~-]{24,}"),
)
_UNKNOWN_LICENSE_VALUES = frozenset({"", "unknown", "none", "n/a", "na", "unspecified"})
type LicenseMetadataSource = Literal[
    "pyproject-license-expression",
    "pyproject-license-file",
    "pyproject-license-text",
    "core-metadata-license-expression",
    "core-metadata-license-field",
    "missing",
]


@dataclass(frozen=True, slots=True)
class StaticSourceInspection:
    files: tuple[StaticFileEvidence, ...]
    forbidden_pattern_scan_passed: bool
    secret_scan_passed: bool
    strict_data_parse_passed: bool
    python_compile_passed: bool
    component_import_violations: tuple[str, ...]
    failure_codes: tuple[str, ...]


def inspect_static_sources(root: Path, manifest: CandidateManifest) -> StaticSourceInspection:
    """Parse and compile manifest-bound bytes without importing candidate code."""

    failures: set[str] = set()
    file_evidence: list[StaticFileEvidence] = []
    forbidden_ok = True
    secret_ok = True
    data_ok = True
    python_ok = True
    component_import_violations: set[str] = set()
    python_trees: dict[str, ast.Module] = {}
    declared_by_path = {item.path: item for item in manifest.files}

    for declared in sorted(manifest.files, key=lambda item: item.path):
        path = _manifest_path(root, declared)
        data = path.read_bytes()
        suffix = path.suffix.lower()
        is_text = suffix in _TEXT_SUFFIXES or path.name in _TEXT_NAMES or path.name == "uv.lock"
        media_kind: Literal["python", "json", "toml", "text", "other"] = (
            "python"
            if suffix == ".py"
            else "json"
            if suffix == ".json"
            else "toml"
            if suffix == ".toml" or path.name == "uv.lock"
            else "text"
            if is_text
            else "other"
        )
        utf8_valid: bool | None = None
        ast_valid: bool | None = None
        compile_valid: bool | None = None
        parse_valid: bool | None = None
        scan_passed = True
        item_failures: set[str] = set()

        text: str | None = None
        if is_text:
            try:
                text = data.decode("utf-8", errors="strict")
                utf8_valid = True
            except UnicodeDecodeError:
                utf8_valid = False
                item_failures.add("static_utf8_invalid")
                failures.add("static_utf8_invalid")

            if any(pattern.search(data) is not None for pattern in _FORBIDDEN_PATTERNS):
                forbidden_ok = False
                scan_passed = False
                item_failures.add("static_forbidden_pattern")
                failures.add("static_forbidden_pattern")
            if any(pattern.search(data) is not None for pattern in _SECRET_PATTERNS):
                secret_ok = False
                scan_passed = False
                item_failures.add("static_secret_pattern")
                failures.add("static_secret_pattern")

        if media_kind == "python":
            if text is None:
                ast_valid = False
                compile_valid = False
                python_ok = False
            else:
                try:
                    tree = ast.parse(text, filename=declared.path, mode="exec")
                    python_trees[declared.path] = tree
                    ast_valid = True
                    compile(tree, declared.path, "exec", dont_inherit=True, optimize=0)
                    compile_valid = True
                except SyntaxError:
                    ast_valid = False
                    compile_valid = False
                    python_ok = False
                    item_failures.add("static_python_compile_invalid")
                    failures.add("static_python_compile_invalid")
        elif media_kind in {"json", "toml"}:
            if text is None:
                parse_valid = False
                data_ok = False
            else:
                try:
                    if media_kind == "json":
                        _strict_json_loads(text)
                    else:
                        tomllib.loads(text)
                    parse_valid = True
                except (ValueError, tomllib.TOMLDecodeError):
                    parse_valid = False
                    data_ok = False
                    code = "static_json_invalid" if media_kind == "json" else "static_toml_invalid"
                    item_failures.add(code)
                    failures.add(code)

        file_evidence.append(
            StaticFileEvidence(
                path=declared.path,
                role=declared.role,
                content_hash=sha256_digest(data),
                size_bytes=len(data),
                media_kind=media_kind,
                utf8_valid=utf8_valid,
                ast_valid=ast_valid,
                compile_valid=compile_valid,
                parse_valid=parse_valid,
                scan_passed=scan_passed,
                failure_codes=tuple(sorted(item_failures)),
            )
        )

    violations_by_source = _component_import_violations(
        declared_by_path=declared_by_path,
        python_trees=python_trees,
    )
    if violations_by_source:
        failures.add("static_component_import_boundary_violation")
        component_import_violations.update(
            violation
            for violations in violations_by_source.values()
            for violation in violations
        )
        file_evidence = [
            (
                evidence.model_copy(
                    update={
                        "failure_codes": tuple(
                            sorted(
                                {
                                    *evidence.failure_codes,
                                    "static_component_import_boundary_violation",
                                }
                            )
                        )
                    }
                )
                if evidence.path in violations_by_source
                else evidence
            )
            for evidence in file_evidence
        ]

    return StaticSourceInspection(
        files=tuple(file_evidence),
        forbidden_pattern_scan_passed=forbidden_ok,
        secret_scan_passed=secret_ok,
        strict_data_parse_passed=data_ok,
        python_compile_passed=python_ok,
        component_import_violations=tuple(sorted(component_import_violations)),
        failure_codes=tuple(sorted(failures)),
    )


_COMPONENT_IMPORT_ROLES: dict[str, frozenset[str]] = {
    "runtime": frozenset({"runtime"}),
    "task_materializer": frozenset({"runtime", "task_materializer"}),
    "public_verifier": frozenset({"runtime", "task_materializer", "public_verifier"}),
}


def _component_import_violations(
    *,
    declared_by_path: dict[str, PackageFile],
    python_trees: dict[str, ast.Module],
) -> dict[str, tuple[str, ...]]:
    """Reject declared cross-role imports that cannot exist in the isolated file view."""

    module_paths = {
        module: path
        for path in python_trees
        if (module := _module_name_for_path(path)) is not None
    }
    violations: dict[str, tuple[str, ...]] = {}
    for source_path, tree in python_trees.items():
        source = declared_by_path[source_path]
        allowed_roles = _COMPONENT_IMPORT_ROLES.get(source.role)
        if allowed_roles is None:
            continue
        source_module = _module_name_for_path(source_path)
        if source_module is None:
            continue
        imported_paths = {
            target_path
            for imported_module in _declared_import_modules(tree, source_path, source_module)
            if (target_path := _declared_module_path(imported_module, module_paths)) is not None
        }
        source_violations = tuple(
            f"{source_path}->{target_path}"
            for target_path in sorted(imported_paths)
            if declared_by_path[target_path].role not in allowed_roles
        )
        if source_violations:
            violations[source_path] = source_violations
    return violations


def _module_name_for_path(path: str) -> str | None:
    pure = PurePosixPath(path)
    if pure.suffix != ".py":
        return None
    parts = list(pure.with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts) if parts else None


def _declared_import_modules(
    tree: ast.Module,
    source_path: str,
    source_module: str,
) -> set[str]:
    imported: set[str] = set()
    is_package = PurePosixPath(source_path).name == "__init__.py"
    package_parts = source_module.split(".") if is_package else source_module.split(".")[:-1]
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
            continue
        if not isinstance(node, ast.ImportFrom):
            continue
        if node.level:
            keep = len(package_parts) - node.level + 1
            if keep < 0:
                continue
            base_parts = package_parts[:keep]
        else:
            base_parts = []
        if node.module:
            base_parts.extend(node.module.split("."))
        base = ".".join(base_parts)
        if base:
            imported.add(base)
        for alias in node.names:
            if alias.name != "*":
                imported.add(".".join((*base_parts, alias.name)))
    return imported


def _declared_module_path(module: str, module_paths: dict[str, str]) -> str | None:
    parts = module.split(".")
    for size in range(len(parts), 0, -1):
        if (path := module_paths.get(".".join(parts[:size]))) is not None:
            return path
    return None


def inspect_supply_chain(
    *,
    evidence_id: str,
    candidate_ref: ArtifactRef,
    root: Path,
    manifest: CandidateManifest,
    implementation_lineage_ref: ArtifactRef,
    implementation_lineage: ImplementationLineage | None,
    installed_tree_hash: str,
) -> SupplyChainEvidence:
    """Bind the exact lock, clean install, physical metadata, and license inventory."""

    failures: set[str] = set()
    pyproject_bytes = _manifest_path(root, _file_by_path(manifest, "pyproject.toml")).read_bytes()
    lock_bytes = _manifest_path(root, _file_by_path(manifest, "uv.lock")).read_bytes()
    pyproject_hash = sha256_digest(pyproject_bytes)
    lock_hash = sha256_digest(lock_bytes)
    lineage_hash = (
        implementation_lineage.dependency_lock_hash if implementation_lineage is not None else None
    )
    if implementation_lineage is None:
        failures.add("supply_implementation_lineage_invalid")
    if lineage_hash != lock_hash:
        failures.add("supply_lineage_lock_mismatch")

    license_files = _candidate_license_inventory(root, manifest, failures)
    project: dict[str, Any] = {}
    lock: dict[str, Any] = {}
    project_name: str | None = None
    project_version: str | None = None
    dependency_policy_passed = False
    locked_components: tuple[LockedComponentEvidence, ...] = ()
    root_license: LicenseMetadataEvidence | None = None

    try:
        parsed_project = tomllib.loads(pyproject_bytes.decode("utf-8", errors="strict"))
        parsed_lock = tomllib.loads(lock_bytes.decode("utf-8", errors="strict"))
        if not isinstance(parsed_project, dict) or not isinstance(parsed_lock, dict):
            raise ValueError("uv project documents must be TOML tables")
        project = parsed_project
        lock = parsed_lock
        raw_project = project.get("project")
        if not isinstance(raw_project, dict):
            raise ValueError("pyproject requires a project table")
        raw_name = raw_project.get("name")
        raw_version = raw_project.get("version")
        if not isinstance(raw_name, str) or not raw_name.strip():
            raise ValueError("project name is missing")
        if not isinstance(raw_version, str) or not raw_version.strip():
            raise ValueError("project version is missing")
        Version(raw_version)
        project_name = raw_name
        project_version = raw_version
        CandidateWorkspaceValidator._validate_dependency_policy(  # noqa: SLF001
            pyproject=project,
            lock=lock,
            project_name=project_name,
        )
        dependency_policy_passed = True
        locked_components = _locked_components(lock, failures)
        _validate_virtual_root(
            locked_components,
            project_name=project_name,
            project_version=project_version,
            failures=failures,
        )
        root_license = _root_license_metadata(
            raw_project,
            project_name=project_name,
            project_version=project_version,
            pyproject_hash=pyproject_hash,
            license_files=license_files,
        )
        if root_license.status == "unknown":
            failures.add("supply_root_license_unknown")
    except (
        CandidateWorkspaceError,
        InvalidVersion,
        UnicodeDecodeError,
        ValueError,
        tomllib.TOMLDecodeError,
    ):
        failures.add("supply_project_lock_invalid")

    installed_components = _installed_components(root, failures)
    license_complete = root_license is not None and root_license.status == "declared"
    if any(item.license.status == "unknown" for item in installed_components):
        failures.add("supply_dependency_license_unknown")
        license_complete = False

    lock_install_closed = False
    if project_name is not None and project_version is not None and project:
        lock_install_closed = _validate_install_closure(
            project=project,
            locked_components=locked_components,
            installed_components=installed_components,
            failures=failures,
        )

    status: Literal["pass", "fail"] = (
        "pass"
        if lineage_hash == lock_hash
        and bool(license_files)
        and root_license is not None
        and root_license.status == "declared"
        and dependency_policy_passed
        and lock_install_closed
        and license_complete
        and not failures
        else "fail"
    )
    return SupplyChainEvidence(
        evidence_id=evidence_id,
        candidate_ref=candidate_ref,
        implementation_lineage_ref=implementation_lineage_ref,
        candidate_source_tree_digest=manifest.candidate_source_tree_digest,
        status=status,
        pyproject_hash=pyproject_hash,
        uv_lock_hash=lock_hash,
        lineage_dependency_lock_hash=lineage_hash,
        installed_tree_hash=_as_content_hash(installed_tree_hash),
        root_project_name=project_name,
        root_project_version=project_version,
        root_license=root_license,
        candidate_license_files=license_files,
        locked_components=locked_components,
        installed_components=installed_components,
        approved_registry_urls=APPROVED_REGISTRY_URLS,
        lock_install_closed=lock_install_closed,
        dependency_policy_passed=dependency_policy_passed,
        license_metadata_complete=license_complete,
        failure_codes=tuple(sorted(failures)),
    )


def _strict_json_loads(text: str) -> Any:
    def reject_constant(value: str) -> None:
        raise ValueError(f"non-finite JSON number is prohibited: {value}")

    def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON object key: {key}")
            result[key] = value
        return result

    return json.loads(text, parse_constant=reject_constant, object_pairs_hook=unique_object)


def _manifest_path(root: Path, declared: PackageFile) -> Path:
    path = root.joinpath(*PurePosixPath(declared.path).parts)
    observed = path.lstat()
    if path.is_symlink() or not stat.S_ISREG(observed.st_mode) or observed.st_nlink != 1:
        raise ValueError(f"manifest path is not an independent regular file: {declared.path}")
    data = path.read_bytes()
    if len(data) != declared.size_bytes or sha256_digest(data) != declared.content_hash:
        raise ValueError(f"manifest-bound bytes changed: {declared.path}")
    return path


def _file_by_path(manifest: CandidateManifest, path: str) -> PackageFile:
    matches = tuple(item for item in manifest.files if item.path == path)
    if len(matches) != 1:
        raise ValueError(f"candidate manifest requires exactly one {path}")
    return matches[0]


def _candidate_license_inventory(
    root: Path,
    manifest: CandidateManifest,
    failures: set[str],
) -> tuple[CandidateLicenseFileEvidence, ...]:
    result: list[CandidateLicenseFileEvidence] = []
    for declared in sorted(
        (item for item in manifest.files if item.role == "license"),
        key=lambda item: item.path,
    ):
        try:
            data = _manifest_path(root, declared).read_bytes()
            if not data.strip():
                raise ValueError("license file is empty")
            result.append(
                CandidateLicenseFileEvidence(
                    path=declared.path,
                    content_hash=sha256_digest(data),
                    size_bytes=len(data),
                )
            )
        except (OSError, ValueError):
            failures.add("supply_license_file_invalid")
    if not result:
        failures.add("supply_license_file_missing")
    return tuple(result)


def _locked_components(
    lock: dict[str, Any], failures: set[str]
) -> tuple[LockedComponentEvidence, ...]:
    packages = lock.get("package")
    if not isinstance(packages, list):
        failures.add("supply_lock_packages_invalid")
        return ()
    result: list[LockedComponentEvidence] = []
    for raw in packages:
        try:
            if not isinstance(raw, dict):
                raise ValueError("lock package is not a table")
            name = raw.get("name")
            version = raw.get("version")
            source = raw.get("source")
            if (
                not isinstance(name, str)
                or not isinstance(version, str)
                or not isinstance(source, dict)
            ):
                raise ValueError("lock package identity is incomplete")
            Version(version)
            normalized = canonicalize_name(name)
            dependencies = _locked_dependency_names(raw.get("dependencies", []))
            if source == {"virtual": "."}:
                result.append(
                    LockedComponentEvidence(
                        name=name,
                        normalized_name=normalized,
                        version=version,
                        source_kind="virtual-root",
                        dependency_names=dependencies,
                    )
                )
                continue
            registry = source.get("registry")
            wheels_raw = raw.get("wheels")
            if not isinstance(registry, str) or not isinstance(wheels_raw, list):
                raise ValueError("registry lock package has no wheel provenance")
            wheels = tuple(
                LockedWheelEvidence(
                    url=_required_str(item, "url"),
                    content_hash=_required_str(item, "hash"),
                    size_bytes=_required_int(item, "size"),
                )
                for item in wheels_raw
                if isinstance(item, dict)
            )
            if len(wheels) != len(wheels_raw) or not wheels:
                raise ValueError("registry lock package wheel records are invalid")
            result.append(
                LockedComponentEvidence(
                    name=name,
                    normalized_name=normalized,
                    version=version,
                    source_kind="registry",
                    registry_url=registry,
                    wheels=wheels,
                    dependency_names=dependencies,
                )
            )
        except (InvalidVersion, ValueError):
            failures.add("supply_locked_component_invalid")
    identities = {(item.normalized_name, item.version, item.source_kind) for item in result}
    if len(identities) != len(result):
        failures.add("supply_locked_component_duplicate")
    return tuple(sorted(result, key=lambda item: (item.normalized_name, item.version)))


def _locked_dependency_names(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ValueError("lock dependencies must be an array")
    names: set[str] = set()
    for item in value:
        name = (
            item if isinstance(item, str) else item.get("name") if isinstance(item, dict) else None
        )
        if not isinstance(name, str) or not name:
            raise ValueError("lock dependency has no name")
        names.add(canonicalize_name(name))
    return tuple(sorted(names))


def _validate_virtual_root(
    components: tuple[LockedComponentEvidence, ...],
    *,
    project_name: str,
    project_version: str,
    failures: set[str],
) -> None:
    roots = tuple(item for item in components if item.source_kind == "virtual-root")
    if len(roots) != 1:
        failures.add("supply_virtual_root_invalid")
        return
    root = roots[0]
    if root.normalized_name != canonicalize_name(project_name) or root.version != project_version:
        failures.add("supply_virtual_root_mismatch")


def _root_license_metadata(
    project: dict[str, Any],
    *,
    project_name: str,
    project_version: str,
    pyproject_hash: str,
    license_files: tuple[CandidateLicenseFileEvidence, ...],
) -> LicenseMetadataEvidence:
    value = project.get("license")
    source: LicenseMetadataSource = "missing"
    declared: str | None = None
    if isinstance(value, str) and _known_license(value):
        source = "pyproject-license-expression"
        declared = value.strip()
    elif isinstance(value, dict) and set(value) == {"file"}:
        path = value.get("file")
        if isinstance(path, str) and any(item.path == path for item in license_files):
            source = "pyproject-license-file"
            declared = path
    elif isinstance(value, dict) and set(value) == {"text"}:
        text = value.get("text")
        if isinstance(text, str) and _known_license(text):
            source = "pyproject-license-text"
            declared = text.strip()
    return LicenseMetadataEvidence(
        subject_name=project_name,
        subject_version=project_version,
        status="declared" if declared is not None else "unknown",
        metadata_source=source,
        declared_value=declared,
        metadata_path="pyproject.toml",
        metadata_hash=pyproject_hash,
    )


def _installed_components(root: Path, failures: set[str]) -> tuple[InstalledComponentEvidence, ...]:
    result: list[InstalledComponentEvidence] = []
    seen: set[str] = set()
    metadata_paths = sorted(
        (root / ".venv").rglob("*.dist-info/METADATA"),
        key=lambda item: item.relative_to(root).as_posix(),
    )
    for path in metadata_paths:
        try:
            observed = path.lstat()
            if path.is_symlink() or not stat.S_ISREG(observed.st_mode):
                raise ValueError("installed METADATA is not a regular file")
            data = path.read_bytes()
            message = BytesParser(policy=policy.default).parsebytes(data)
            name = _single_header(message.get_all("Name"), "Name")
            version = _single_header(message.get_all("Version"), "Version")
            Version(version)
            normalized = canonicalize_name(name)
            if normalized in seen:
                failures.add("supply_installed_component_duplicate")
            seen.add(normalized)
            metadata_path = path.relative_to(root).as_posix()
            metadata_hash = sha256_digest(data)
            expression = _optional_single_header(message.get_all("License-Expression"))
            license_field = _optional_single_header(message.get_all("License"))
            if expression is not None and _known_license(expression):
                license_source: LicenseMetadataSource = "core-metadata-license-expression"
                license_value: str | None = expression.strip()
            elif license_field is not None and _known_license(license_field):
                license_source = "core-metadata-license-field"
                license_value = license_field.strip()
            else:
                license_source = "missing"
                license_value = None
            license_evidence = LicenseMetadataEvidence(
                subject_name=name,
                subject_version=version,
                status="declared" if license_value is not None else "unknown",
                metadata_source=license_source,
                declared_value=license_value,
                metadata_path=metadata_path,
                metadata_hash=metadata_hash,
            )
            requires_dist = tuple(
                item.strip() for item in (message.get_all("Requires-Dist") or []) if item.strip()
            )
            result.append(
                InstalledComponentEvidence(
                    name=name,
                    normalized_name=normalized,
                    version=version,
                    metadata_path=metadata_path,
                    metadata_hash=metadata_hash,
                    requires_dist=requires_dist,
                    license=license_evidence,
                )
            )
        except (InvalidVersion, UnicodeError, ValueError):
            failures.add("supply_installed_metadata_invalid")
    return tuple(sorted(result, key=lambda item: (item.normalized_name, item.version)))


def _validate_install_closure(
    *,
    project: dict[str, Any],
    locked_components: tuple[LockedComponentEvidence, ...],
    installed_components: tuple[InstalledComponentEvidence, ...],
    failures: set[str],
) -> bool:
    closure_failed = False
    locked = {
        (item.normalized_name, item.version): item
        for item in locked_components
        if item.source_kind == "registry"
    }
    installed = {item.normalized_name: item for item in installed_components}
    if len(installed) != len(installed_components):
        failures.add("supply_install_name_ambiguous")
        return False
    for item in installed_components:
        if (item.normalized_name, item.version) not in locked:
            failures.add("supply_installed_not_locked")
            closure_failed = True

    raw_project = project.get("project")
    if not isinstance(raw_project, dict):
        failures.add("supply_project_dependencies_invalid")
        return False
    root_requirements = raw_project.get("dependencies", [])
    if not isinstance(root_requirements, list) or not all(
        isinstance(item, str) for item in root_requirements
    ):
        failures.add("supply_project_dependencies_invalid")
        return False

    reached: set[str] = set()
    expanded_extras: dict[str, set[str]] = {}
    pending: list[tuple[str, frozenset[str]]] = [(item, frozenset()) for item in root_requirements]
    while pending:
        raw, parent_extras = pending.pop()
        try:
            requirement = Requirement(raw)
        except InvalidRequirement:
            failures.add("supply_requirement_invalid")
            closure_failed = True
            continue
        if not _requirement_applies(requirement, parent_extras):
            continue
        normalized = canonicalize_name(requirement.name)
        installed_item = installed.get(normalized)
        if installed_item is None:
            failures.add("supply_required_component_missing")
            closure_failed = True
            continue
        try:
            if (
                requirement.specifier
                and Version(installed_item.version) not in requirement.specifier
            ):
                failures.add("supply_installed_version_mismatch")
                closure_failed = True
        except InvalidVersion:
            failures.add("supply_installed_version_mismatch")
            closure_failed = True
        if (normalized, installed_item.version) not in locked:
            failures.add("supply_installed_not_locked")
            closure_failed = True
        reached.add(normalized)
        requested_extras = set(requirement.extras)
        previous = expanded_extras.setdefault(normalized, set())
        if requested_extras <= previous and previous:
            continue
        previous.update(requested_extras)
        child_extras = frozenset(previous)
        pending.extend((item, child_extras) for item in installed_item.requires_dist)

    if reached != set(installed):
        failures.add("supply_installed_closure_mismatch")
        closure_failed = True
    return not closure_failed


def _requirement_applies(requirement: Requirement, extras: frozenset[str]) -> bool:
    if requirement.marker is None:
        return True
    environment = {key: str(value) for key, value in default_environment().items()}
    values = extras or frozenset({""})
    return any(requirement.marker.evaluate({**environment, "extra": extra}) for extra in values)


def _single_header(values: list[str] | None, name: str) -> str:
    if values is None or len(values) != 1 or not values[0].strip():
        raise ValueError(f"installed METADATA requires exactly one {name}")
    return values[0].strip()


def _optional_single_header(values: list[str] | None) -> str | None:
    if not values:
        return None
    if len(values) != 1:
        return None
    value = values[0].strip()
    return value or None


def _known_license(value: str) -> bool:
    return value.strip().casefold() not in _UNKNOWN_LICENSE_VALUES


def _required_str(value: dict[str, Any], key: str) -> str:
    result = value.get(key)
    if not isinstance(result, str) or not result:
        raise ValueError(f"locked wheel {key} is invalid")
    return result


def _required_int(value: dict[str, Any], key: str) -> int:
    result = value.get(key)
    if isinstance(result, bool) or not isinstance(result, int) or result <= 0:
        raise ValueError(f"locked wheel {key} is invalid")
    return result


def _as_content_hash(value: str) -> str:
    return value if value.startswith("sha256:") else f"sha256:{value}"


__all__ = [
    "APPROVED_REGISTRY_URLS",
    "MAX_PUBLIC_TESTS",
    "StaticSourceInspection",
    "inspect_static_sources",
    "inspect_supply_chain",
]
