"""Untrusted candidate workspace inspection and deterministic snapshots."""

from __future__ import annotations

import io
import os
import re
import stat
import tarfile
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import cast
from urllib.parse import urlsplit

from packaging.requirements import InvalidRequirement, Requirement
from packaging.specifiers import InvalidSpecifier, SpecifierSet

from agent_world.contracts import PackageFile, candidate_source_tree_digest, sha256_digest

from .models import CandidateCompletion, CandidateFileRole

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
_SECRET_PATTERNS = (
    re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(rb"\bsk-[A-Za-z0-9_-]{20,}\b"),
    re.compile(
        rb"(?i)\b(?:api[_-]?key|access[_-]?token|client[_-]?secret|password)\b"
        rb"\s*[:=]\s*['\"][^'\"\r\n]{12,}['\"]"
    ),
    re.compile(rb"(?i)\bBearer\s+[A-Za-z0-9._~-]{24,}"),
)
_APPROVED_REGISTRY_URLS = frozenset({"https://pypi.org/simple", "https://pypi.org/simple/"})
_APPROVED_ARTIFACT_HOST = "files.pythonhosted.org"
_UNKNOWN_LICENSE_VALUES = frozenset({"", "unknown", "none", "n/a", "na", "unspecified"})
_FORBIDDEN_UV_CONFIGURATION_KEYS = frozenset(
    {
        "config-settings",
        "config-settings-package",
        "default-index",
        "extra-index-url",
        "find-links",
        "index",
        "index-strategy",
        "index-url",
        "keyring-provider",
        "no-build-isolation",
        "no-index",
        "sources",
    }
)


@dataclass(frozen=True, slots=True)
class CandidateWorkspaceDiagnostic:
    """Safe, non-content evidence for one candidate-workspace rejection.

    The validator may need raw paths internally to reject an untrusted tree,
    but those paths are not safe control-plane feedback: a model can choose a
    path name and encode arbitrary text in it.  This compact companion keeps
    the *kind* and cardinality of a manifest mismatch so a later authorized
    Engineer correction can inspect its own workspace without receiving raw
    exception text.
    """

    code: str
    count: int | None = None


class CandidateWorkspaceError(RuntimeError):
    """The candidate workspace is unsafe or contradicts its declaration."""

    def __init__(
        self,
        message: str,
        *,
        safe_diagnostic: CandidateWorkspaceDiagnostic | None = None,
    ) -> None:
        super().__init__(message)
        self.safe_diagnostic = safe_diagnostic


@dataclass(frozen=True, slots=True)
class ValidatedCandidateFile:
    path: str
    role: CandidateFileRole
    executable: bool
    data: bytes
    content_hash: str

    def package_file(self) -> PackageFile:
        return PackageFile(
            path=self.path,
            content_hash=self.content_hash,
            size_bytes=len(self.data),
            role=self.role,
            executable=self.executable,
        )


@dataclass(frozen=True, slots=True)
class ValidatedCandidateWorkspace:
    files: tuple[ValidatedCandidateFile, ...]
    project_name: str

    @property
    def package_files(self) -> tuple[PackageFile, ...]:
        return tuple(item.package_file() for item in self.files)

    @property
    def candidate_source_tree_digest(self) -> str:
        return candidate_source_tree_digest(self.package_files)

    def file(self, relative_path: str) -> ValidatedCandidateFile:
        for item in self.files:
            if item.path == relative_path:
                return item
        raise CandidateWorkspaceError(f"declared candidate file is unavailable: {relative_path}")

    def deterministic_tar(self) -> bytes:
        """Return a byte-stable, link-free tar archive of validated files."""

        output = io.BytesIO()
        with tarfile.open(fileobj=output, mode="w", format=tarfile.USTAR_FORMAT) as archive:
            for item in self.files:
                info = tarfile.TarInfo(name=item.path)
                info.size = len(item.data)
                info.mode = 0o755 if item.executable else 0o644
                info.uid = 0
                info.gid = 0
                info.uname = ""
                info.gname = ""
                info.mtime = 0
                info.type = tarfile.REGTYPE
                archive.addfile(info, io.BytesIO(item.data))
        return output.getvalue()


class CandidateWorkspaceValidator:
    """Validate source bytes without importing or executing candidate code."""

    def __init__(
        self,
        *,
        max_files: int = 1_000,
        max_total_bytes: int = 64 * 1024 * 1024,
        max_file_bytes: int = 8 * 1024 * 1024,
    ) -> None:
        if min(max_files, max_total_bytes, max_file_bytes) <= 0:
            raise ValueError("candidate workspace limits must be positive")
        self.max_files = max_files
        self.max_total_bytes = max_total_bytes
        self.max_file_bytes = max_file_bytes

    def validate(
        self,
        root: Path,
        completion: CandidateCompletion,
        *,
        secret_values: tuple[str, ...] = (),
        forbidden_absolute_paths: tuple[Path, ...] = (),
        python_requires: str = ">=3.12,<3.13",
    ) -> ValidatedCandidateWorkspace:
        if completion.status != "completed":
            raise CandidateWorkspaceError("a blocked completion has no candidate workspace")
        requested = Path(root)
        if requested.is_symlink() or not requested.is_dir():
            raise CandidateWorkspaceError("candidate project root must be a real directory")
        resolved_root = requested.resolve(strict=True)
        declarations = {item.path: item for item in completion.files}
        if len(declarations) != len(completion.files):
            raise CandidateWorkspaceError(
                "candidate file declarations are not unique",
                safe_diagnostic=CandidateWorkspaceDiagnostic(
                    "manifest_declaration_duplicate",
                    len(completion.files) - len(declarations),
                ),
            )

        actual: dict[str, tuple[bytes, os.stat_result]] = {}
        total_bytes = 0
        for directory, directory_names, file_names, directory_fd in os.fwalk(
            resolved_root, topdown=True, follow_symlinks=False
        ):
            base = Path(directory)
            directory_names.sort()
            file_names.sort()
            for name in directory_names:
                relative = (base / name).relative_to(resolved_root).as_posix()
                self._validate_observed_path(relative)
                entry_stat = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
                if stat.S_ISLNK(entry_stat.st_mode):
                    raise CandidateWorkspaceError(f"symlink directory is prohibited: {relative}")
                if name.startswith(".") or name in _FORBIDDEN_DIRECTORIES:
                    raise CandidateWorkspaceError(
                        f"build/control directory is prohibited: {relative}"
                    )
                if not stat.S_ISDIR(entry_stat.st_mode):
                    raise CandidateWorkspaceError(
                        f"unsupported filesystem entry in candidate: {relative}"
                    )
            for name in file_names:
                relative = (base / name).relative_to(resolved_root).as_posix()
                self._validate_observed_path(relative)
                file_stat = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
                if stat.S_ISLNK(file_stat.st_mode):
                    raise CandidateWorkspaceError(f"symlink file is prohibited: {relative}")
                if not stat.S_ISREG(file_stat.st_mode):
                    raise CandidateWorkspaceError(
                        f"non-regular candidate file is prohibited: {relative}"
                    )
                if file_stat.st_nlink != 1:
                    raise CandidateWorkspaceError(f"hard-linked file is prohibited: {relative}")
                if name in _FORBIDDEN_FILENAMES:
                    raise CandidateWorkspaceError(
                        f"credential-like filename is prohibited: {relative}"
                    )
                if (
                    Path(name).suffix.lower() not in _ALLOWED_SUFFIXES
                    and name not in _ALLOWED_EXTENSIONLESS
                ):
                    raise CandidateWorkspaceError(f"unsupported candidate file type: {relative}")
                if file_stat.st_size > self.max_file_bytes:
                    raise CandidateWorkspaceError(f"candidate file exceeds size limit: {relative}")
                data = self._read_regular_file(
                    name=name,
                    directory_fd=directory_fd,
                    relative=relative,
                    observed=file_stat,
                )
                total_bytes += len(data)
                if total_bytes > self.max_total_bytes:
                    raise CandidateWorkspaceError("candidate exceeds the total byte limit")
                actual[relative] = (data, file_stat)

        declared_paths = set(declarations)
        actual_paths = set(actual)
        if missing := sorted(declared_paths - actual_paths):
            raise CandidateWorkspaceError(
                f"declared files are missing: {missing}",
                safe_diagnostic=CandidateWorkspaceDiagnostic(
                    "manifest_declared_missing",
                    len(missing),
                ),
            )
        if undeclared := sorted(actual_paths - declared_paths):
            raise CandidateWorkspaceError(
                f"candidate contains undeclared files: {undeclared}",
                safe_diagnostic=CandidateWorkspaceDiagnostic(
                    "manifest_undeclared_files",
                    len(undeclared),
                ),
            )
        if not actual_paths:
            raise CandidateWorkspaceError(
                "candidate project is empty",
                safe_diagnostic=CandidateWorkspaceDiagnostic("manifest_empty", 0),
            )
        if len(actual_paths) > self.max_files:
            raise CandidateWorkspaceError(
                "candidate exceeds the file-count limit",
                safe_diagnostic=CandidateWorkspaceDiagnostic(
                    "manifest_file_limit",
                    len(actual_paths),
                ),
            )

        forbidden_bytes = tuple(
            value.encode("utf-8")
            for value in secret_values
            if value and len(value.encode("utf-8")) >= 8
        )
        path_bytes = tuple(
            str(path.expanduser().resolve()).encode("utf-8") for path in forbidden_absolute_paths
        )
        files: list[ValidatedCandidateFile] = []
        for relative in sorted(actual):
            data, file_stat = actual[relative]
            self._validate_text(relative, data)
            self._scan_sensitive_data(relative, data, forbidden_bytes, path_bytes)
            declaration = declarations[relative]
            executable = bool(file_stat.st_mode & 0o111)
            files.append(
                ValidatedCandidateFile(
                    path=relative,
                    role=cast(CandidateFileRole, declaration.role),
                    executable=executable,
                    data=data,
                    content_hash=sha256_digest(data),
                )
            )

        project_name = self._validate_uv_project(files, python_requires=python_requires)
        self._validate_entry_files(completion, files)
        return ValidatedCandidateWorkspace(files=tuple(files), project_name=project_name)

    @staticmethod
    def _validate_observed_path(relative: str) -> None:
        if len(relative) > 240:
            raise CandidateWorkspaceError("candidate path exceeds 240 characters")
        if any(ord(character) < 32 or ord(character) == 127 for character in relative):
            raise CandidateWorkspaceError("candidate path contains control characters")
        try:
            tarfile.TarInfo(relative).tobuf(
                format=tarfile.USTAR_FORMAT,
                encoding="utf-8",
                errors="strict",
            )
        except (UnicodeError, ValueError) as exc:
            raise CandidateWorkspaceError(
                "candidate path is not representable in the deterministic USTAR snapshot"
            ) from exc

    def _read_regular_file(
        self,
        *,
        name: str,
        directory_fd: int,
        relative: str,
        observed: os.stat_result,
    ) -> bytes:
        flags = os.O_RDONLY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            descriptor = os.open(name, flags, dir_fd=directory_fd)
        except OSError as exc:
            raise CandidateWorkspaceError(
                f"candidate file could not be opened safely: {relative}"
            ) from exc
        try:
            before = os.fstat(descriptor)
            identity_before = self._stat_identity(before)
            if identity_before != self._stat_identity(observed):
                raise CandidateWorkspaceError(
                    f"candidate file changed before inspection: {relative}"
                )
            chunks: list[bytes] = []
            size = 0
            while True:
                chunk = os.read(descriptor, min(1024 * 1024, self.max_file_bytes + 1 - size))
                if not chunk:
                    break
                chunks.append(chunk)
                size += len(chunk)
                if size > self.max_file_bytes:
                    raise CandidateWorkspaceError(f"candidate file exceeds size limit: {relative}")
            after = os.fstat(descriptor)
            if self._stat_identity(after) != identity_before or size != after.st_size:
                raise CandidateWorkspaceError(
                    f"candidate file changed during inspection: {relative}"
                )
            return b"".join(chunks)
        finally:
            os.close(descriptor)

    @staticmethod
    def _stat_identity(value: os.stat_result) -> tuple[int, int, int, int, int, int]:
        return (
            value.st_dev,
            value.st_ino,
            value.st_mode,
            value.st_nlink,
            value.st_size,
            value.st_mtime_ns,
        )

    @staticmethod
    def _validate_text(relative: str, data: bytes) -> None:
        if b"\x00" in data:
            raise CandidateWorkspaceError(f"binary/NUL content is prohibited: {relative}")
        try:
            data.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise CandidateWorkspaceError(
                f"candidate files must be strict UTF-8 text: {relative}"
            ) from exc

    @staticmethod
    def _scan_sensitive_data(
        relative: str,
        data: bytes,
        secret_values: tuple[bytes, ...],
        absolute_paths: tuple[bytes, ...],
    ) -> None:
        if any(secret in data for secret in secret_values):
            raise CandidateWorkspaceError(
                f"candidate contains a materialized credential value: {relative}"
            )
        if any(path and path in data for path in absolute_paths):
            raise CandidateWorkspaceError(
                f"candidate embeds a generation-host absolute path: {relative}"
            )
        if any(pattern.search(data) is not None for pattern in _SECRET_PATTERNS):
            raise CandidateWorkspaceError(
                f"candidate contains credential-like literal content: {relative}"
            )

    @staticmethod
    def _validate_uv_project(files: list[ValidatedCandidateFile], *, python_requires: str) -> str:
        by_path = {item.path: item for item in files}
        if "uv.toml" in by_path:
            raise CandidateWorkspaceError(
                "candidate uv.toml is prohibited; dependency policy is framework-owned"
            )
        try:
            pyproject = tomllib.loads(by_path["pyproject.toml"].data.decode("utf-8"))
            lock = tomllib.loads(by_path["uv.lock"].data.decode("utf-8"))
        except KeyError as exc:
            raise CandidateWorkspaceError(f"required uv project file is missing: {exc}") from exc
        except tomllib.TOMLDecodeError as exc:
            raise CandidateWorkspaceError(f"invalid uv project TOML: {exc}") from exc
        project = pyproject.get("project")
        if not isinstance(project, dict):
            raise CandidateWorkspaceError("pyproject.toml requires a [project] table")
        name = project.get("name")
        requires_python = project.get("requires-python")
        if not isinstance(name, str) or not name.strip():
            raise CandidateWorkspaceError("pyproject project.name must be non-empty")
        CandidateWorkspaceValidator._validate_project_license(project, files=files)
        lock_requires_python = lock.get("requires-python")
        if not isinstance(requires_python, str) or not isinstance(lock_requires_python, str):
            raise CandidateWorkspaceError(
                "pyproject and uv.lock require string requires-python specifiers"
            )
        try:
            expected = SpecifierSet(python_requires)
            project_specifier = SpecifierSet(requires_python)
            lock_specifier = SpecifierSet(lock_requires_python)
        except InvalidSpecifier as exc:
            raise CandidateWorkspaceError(
                "pyproject and uv.lock require valid requires-python specifiers"
            ) from exc
        canonical_uv_lock_specifier = SpecifierSet("==3.12.*")
        if project_specifier != expected or lock_specifier not in {
            expected,
            canonical_uv_lock_specifier,
        }:
            raise CandidateWorkspaceError(
                "pyproject requires-python and uv's canonical lock range must exactly represent "
                f"the implementation contract ({python_requires})",
                safe_diagnostic=CandidateWorkspaceDiagnostic("python_requires_contract_mismatch"),
            )
        if not isinstance(lock.get("version"), int):
            raise CandidateWorkspaceError("uv.lock does not contain a uv lock format version")
        CandidateWorkspaceValidator._validate_dependency_policy(
            pyproject=pyproject,
            lock=lock,
            project_name=name,
        )
        return name

    @staticmethod
    def _validate_project_license(
        project: dict[str, object],
        *,
        files: list[ValidatedCandidateFile],
    ) -> None:
        """Require the same root-license declaration that Integration consumes.

        A non-empty ``LICENSE`` file and PEP 639 ``license-files`` inventory do
        not by themselves declare the root project's license.  Catch that
        mechanical metadata gap while the Code Agent still owns its workspace,
        before an otherwise valid Candidate reaches the independent supply
        gate.
        """

        value = project.get("license")
        declared = False
        if isinstance(value, str):
            declared = value.strip().casefold() not in _UNKNOWN_LICENSE_VALUES
        elif isinstance(value, dict) and set(value) == {"file"}:
            path = value.get("file")
            declared = isinstance(path, str) and any(
                item.path == path and item.role == "license" for item in files
            )
        elif isinstance(value, dict) and set(value) == {"text"}:
            text = value.get("text")
            declared = (
                isinstance(text, str) and text.strip().casefold() not in _UNKNOWN_LICENSE_VALUES
            )
        if not declared:
            raise CandidateWorkspaceError(
                "candidate [project].license must declare a non-unknown expression, "
                "license file, or license text; [project].license-files alone is only "
                "an inventory",
                safe_diagnostic=CandidateWorkspaceDiagnostic("project_license_declaration_missing"),
            )

    @staticmethod
    def _validate_dependency_policy(
        *,
        pyproject: dict[str, object],
        lock: dict[str, object],
        project_name: str,
    ) -> None:
        """Reject dependency sources that bypass the offline wheel trust boundary."""

        if "build-system" in pyproject:
            raise CandidateWorkspaceError(
                "candidate build-system hooks are prohibited; the project is executed "
                "directly from its read-only source tree",
                safe_diagnostic=CandidateWorkspaceDiagnostic("dependency_build_system_prohibited"),
            )
        tool = pyproject.get("tool", {})
        if tool is None:
            tool = {}
        if not isinstance(tool, dict):
            raise CandidateWorkspaceError(
                "pyproject [tool] must be a table",
                safe_diagnostic=CandidateWorkspaceDiagnostic("dependency_uv_configuration_invalid"),
            )
        uv = tool.get("uv", {})
        if uv is None:
            uv = {}
        if not isinstance(uv, dict):
            raise CandidateWorkspaceError(
                "pyproject [tool.uv] must be a table",
                safe_diagnostic=CandidateWorkspaceDiagnostic("dependency_uv_configuration_invalid"),
            )
        forbidden = sorted(_FORBIDDEN_UV_CONFIGURATION_KEYS.intersection(uv))
        if forbidden:
            raise CandidateWorkspaceError(
                f"candidate dependency source configuration is prohibited: {forbidden}",
                safe_diagnostic=CandidateWorkspaceDiagnostic(
                    "dependency_uv_configuration_forbidden"
                ),
            )
        if uv.get("package") is not False:
            raise CandidateWorkspaceError(
                "candidate pyproject must set [tool.uv] package=false for a virtual, "
                "non-installed root",
                safe_diagnostic=CandidateWorkspaceDiagnostic(
                    "dependency_virtual_root_mode_invalid"
                ),
            )

        project = pyproject.get("project")
        assert isinstance(project, dict)
        requirement_groups: list[object] = [project.get("dependencies", [])]
        optional = project.get("optional-dependencies", {})
        if optional is not None:
            if not isinstance(optional, dict):
                raise CandidateWorkspaceError(
                    "project.optional-dependencies must be a table",
                    safe_diagnostic=CandidateWorkspaceDiagnostic("dependency_declaration_invalid"),
                )
            requirement_groups.extend(optional.values())
        dependency_groups = pyproject.get("dependency-groups", {})
        if dependency_groups is not None:
            if not isinstance(dependency_groups, dict):
                raise CandidateWorkspaceError(
                    "dependency-groups must be a table",
                    safe_diagnostic=CandidateWorkspaceDiagnostic("dependency_declaration_invalid"),
                )
            requirement_groups.extend(dependency_groups.values())
        for group in requirement_groups:
            if not isinstance(group, list) or not all(isinstance(item, str) for item in group):
                raise CandidateWorkspaceError(
                    "dependency declarations must be string arrays",
                    safe_diagnostic=CandidateWorkspaceDiagnostic("dependency_declaration_invalid"),
                )
            for raw in group:
                try:
                    requirement = Requirement(raw)
                except InvalidRequirement as exc:
                    raise CandidateWorkspaceError(
                        f"invalid dependency requirement: {raw}",
                        safe_diagnostic=CandidateWorkspaceDiagnostic(
                            "dependency_declaration_invalid"
                        ),
                    ) from exc
                if requirement.url is not None:
                    raise CandidateWorkspaceError(
                        f"direct URL/path dependency is prohibited: {requirement.name}",
                        safe_diagnostic=CandidateWorkspaceDiagnostic(
                            "dependency_direct_source_prohibited"
                        ),
                    )

        packages = lock.get("package")
        if not isinstance(packages, list) or not packages:
            raise CandidateWorkspaceError(
                "uv.lock requires a non-empty package array",
                safe_diagnostic=CandidateWorkspaceDiagnostic(
                    "dependency_lock_package_array_invalid"
                ),
            )
        root_source = {"virtual": "."}
        root_count = 0
        for raw_package in packages:
            if not isinstance(raw_package, dict):
                raise CandidateWorkspaceError(
                    "uv.lock package entries must be tables",
                    safe_diagnostic=CandidateWorkspaceDiagnostic(
                        "dependency_lock_package_array_invalid"
                    ),
                )
            name = raw_package.get("name")
            source = raw_package.get("source")
            if not isinstance(name, str) or not isinstance(source, dict):
                raise CandidateWorkspaceError(
                    "uv.lock package requires name and source tables",
                    safe_diagnostic=CandidateWorkspaceDiagnostic(
                        "dependency_lock_package_array_invalid"
                    ),
                )
            if name == project_name:
                if source != root_source:
                    raise CandidateWorkspaceError(
                        "uv.lock must contain a virtual, non-installed root project; "
                        "editable/path/registry root sources are prohibited",
                        safe_diagnostic=CandidateWorkspaceDiagnostic(
                            "dependency_virtual_root_source_invalid"
                        ),
                    )
                root_count += 1
                continue
            if source == root_source:
                raise CandidateWorkspaceError(
                    "uv.lock virtual root package name must equal pyproject project.name",
                    safe_diagnostic=CandidateWorkspaceDiagnostic(
                        "dependency_virtual_root_name_mismatch"
                    ),
                )
            if source.get("registry") not in _APPROVED_REGISTRY_URLS or set(source) != {"registry"}:
                raise CandidateWorkspaceError(
                    f"dependency {name} must come from the fixed HTTPS PyPI registry; "
                    "path/Git/URL/editable sources are prohibited",
                    safe_diagnostic=CandidateWorkspaceDiagnostic(
                        "dependency_registry_source_invalid"
                    ),
                )
            wheels = raw_package.get("wheels")
            if not isinstance(wheels, list) or not wheels:
                raise CandidateWorkspaceError(
                    f"dependency {name} has no locked wheel; source builds are prohibited",
                    safe_diagnostic=CandidateWorkspaceDiagnostic(
                        "dependency_locked_wheels_missing"
                    ),
                )
            for wheel in wheels:
                CandidateWorkspaceValidator._validate_locked_distribution(
                    wheel,
                    package_name=name,
                    distribution="wheel",
                )
            sdist = raw_package.get("sdist")
            if sdist is not None:
                CandidateWorkspaceValidator._validate_locked_distribution(
                    sdist,
                    package_name=name,
                    distribution="sdist metadata",
                )
        if root_count != 1:
            raise CandidateWorkspaceError(
                "uv.lock must contain exactly one virtual, non-installed root project source",
                safe_diagnostic=CandidateWorkspaceDiagnostic(
                    "dependency_virtual_root_count",
                    root_count,
                ),
            )

    @staticmethod
    def _validate_locked_distribution(
        value: object,
        *,
        package_name: str,
        distribution: str,
    ) -> None:
        if not isinstance(value, dict):
            raise CandidateWorkspaceError(
                f"dependency {package_name} {distribution} record must be a table",
                safe_diagnostic=CandidateWorkspaceDiagnostic(
                    "dependency_locked_distribution_invalid"
                ),
            )
        url = value.get("url")
        digest = value.get("hash")
        size = value.get("size")
        if (
            not isinstance(url, str)
            or not isinstance(digest, str)
            or re.fullmatch(r"sha256:[0-9a-f]{64}", digest) is None
            or isinstance(size, bool)
            or not isinstance(size, int)
            or size <= 0
        ):
            raise CandidateWorkspaceError(
                f"dependency {package_name} {distribution} lacks URL/hash/size provenance",
                safe_diagnostic=CandidateWorkspaceDiagnostic(
                    "dependency_locked_distribution_invalid"
                ),
            )
        parsed = urlsplit(url)
        try:
            port = parsed.port
        except ValueError as exc:
            raise CandidateWorkspaceError(
                f"dependency {package_name} {distribution} URL has an invalid port",
                safe_diagnostic=CandidateWorkspaceDiagnostic(
                    "dependency_locked_distribution_invalid"
                ),
            ) from exc
        if (
            parsed.scheme != "https"
            or parsed.hostname != _APPROVED_ARTIFACT_HOST
            or parsed.username is not None
            or parsed.password is not None
            or port not in {None, 443}
            or not parsed.path.startswith("/packages/")
            or parsed.query
            or parsed.fragment
        ):
            raise CandidateWorkspaceError(
                f"dependency {package_name} {distribution} must use the approved "
                "files.pythonhosted.org HTTPS origin",
                safe_diagnostic=CandidateWorkspaceDiagnostic(
                    "dependency_locked_distribution_invalid"
                ),
            )

    @staticmethod
    def _validate_entry_files(
        completion: CandidateCompletion,
        files: list[ValidatedCandidateFile],
    ) -> None:
        by_path = {item.path: item for item in files}
        assert completion.runtime is not None
        assert completion.task_materializer is not None
        assert completion.public_self_check is not None
        required_python = (
            completion.runtime.entry_path,
            completion.task_materializer.entry_path,
            completion.public_self_check.entry_path,
            *completion.public_test_paths,
        )
        for path in required_python:
            if path not in by_path:
                raise CandidateWorkspaceError(f"declared component file is missing: {path}")
            if Path(path).suffix != ".py":
                raise CandidateWorkspaceError(f"candidate component must be Python source: {path}")


__all__ = [
    "CandidateWorkspaceDiagnostic",
    "CandidateWorkspaceError",
    "CandidateWorkspaceValidator",
    "ValidatedCandidateFile",
    "ValidatedCandidateWorkspace",
]
