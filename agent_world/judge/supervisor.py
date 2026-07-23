from __future__ import annotations

import asyncio
import functools
import hashlib
import json
import os
import re
import resource
import shutil
import signal
import stat
import sys
import tempfile
import time
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Literal

from agent_world.contracts import PackageFile, candidate_source_tree_digest, sha256_digest
from agent_world.judge.protocol import (
    DEFAULT_PROTOCOL_LIMITS,
    RUNTIME_ABI_VERSION,
    JsonValue,
    ProtocolLimits,
    ProtocolViolation,
    RuntimeOperation,
    RuntimeResponse,
    decode_response,
    encode_request,
    make_request,
)
from agent_world.observability.subprocess_scene import (
    RuntimeSubprocessScene,
    runtime_subprocess_scene,
)

_SANDBOX_TMP = PurePosixPath("/") / "tmp"
_SANDBOX_HOME = _SANDBOX_TMP / "home"
_SANDBOX_UV_CACHE = _SANDBOX_TMP / "uv-cache"
_PRODUCTION_BWRAP = Path("/usr/bin/bwrap")
_PRODUCTION_SYSTEM_ROOTS = (Path("/usr"),)
_PRODUCTION_PYTHON = Path(sys.executable).resolve()
_PRODUCTION_PYTHON_ROOT = _PRODUCTION_PYTHON.parents[1]
_SANDBOX_PYTHON_ROOT = "/opt/agent-world/python"
_SANDBOX_PYTHON = f"{_SANDBOX_PYTHON_ROOT}/bin/{_PRODUCTION_PYTHON.name}"
_SANDBOX_UV_CACHE_SOURCE = "/opt/agent-world/uv-cache"
_APPROVED_INTERPRETERS = frozenset({".venv/bin/python", ".venv/bin/python3", "python", "python3"})
_TASK_MATERIALIZER_RUNNER_DESTINATION = "/opt/agent-world/bin/task-materializer-runner.py"


@functools.lru_cache(maxsize=1)
def _trusted_temp_root() -> str:
    """Select a host temp root with native permission semantics.

    WSL frequently inherits Windows ``TEMP``/``TMP`` paths whose mounted file
    systems cannot preserve the executable bits used by source-closure checks.
    Security-sensitive Judge work therefore ignores ambient temp variables on
    POSIX unless an explicit Agent World root is configured.
    """

    configured = os.environ.get("AGENT_WORLD_TEMP_ROOT")
    requested = Path(
        configured
        if configured is not None
        else (tempfile.gettempdir() if os.name == "nt" else "/tmp")  # noqa: S108
    ).expanduser()
    try:
        resolved = requested.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise JudgeInfrastructureError(
            "trusted_temp_root_invalid",
            "Agent World temporary root cannot be resolved",
        ) from exc
    if not resolved.is_dir() or not os.access(resolved, os.W_OK | os.X_OK):
        raise JudgeInfrastructureError(
            "trusted_temp_root_unusable",
            "Agent World temporary root must be a writable directory",
        )
    return str(resolved)


_TASK_MATERIALIZER_RUNNER_SOURCE = r"""from __future__ import annotations

import importlib
import inspect
import json
import os
import sys


def fail(message: str, exit_code: int = 65) -> None:
    payload = {
        "protocol": "agent-world.task-materializer-runner.v3",
        "ok": False,
        "error": message,
    }
    sys.stdout.write(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n")
    sys.stdout.flush()
    raise SystemExit(exit_code)


try:
    request = json.load(sys.stdin)
except BaseException:
    fail("framework request was not valid JSON", 70)

if not isinstance(request, dict) or set(request) != {"protocol", "entrypoint", "calls"}:
    fail("framework request envelope was invalid", 70)
if request["protocol"] != "agent-world.task-materializer-runner.v3":
    fail("framework runner protocol was invalid", 70)
entrypoint = request["entrypoint"]
calls = request["calls"]
if not isinstance(entrypoint, str) or entrypoint.count(":") != 1 or not isinstance(calls, list):
    fail("framework runner request types were invalid", 70)
module_name, function_name = entrypoint.split(":", 1)
if function_name != "materialize":
    fail("candidate entrypoint must name materialize")

workspace = os.environ.get("AGENT_WORLD_WORKSPACE", "/workspace")
for candidate_path in (os.path.join(workspace, "src"), workspace):
    if candidate_path not in sys.path:
        sys.path.insert(0, candidate_path)

try:
    module = importlib.import_module(module_name)
    function = getattr(module, function_name)
except BaseException as exc:
    fail(f"candidate entrypoint import failed ({type(exc).__name__})")
if not callable(function):
    fail("candidate materialize entrypoint is not callable")

try:
    signature = inspect.signature(function)
except BaseException as exc:
    fail(f"candidate materialize signature cannot be inspected ({type(exc).__name__})")
parameters = tuple(signature.parameters.values())
if tuple(item.name for item in parameters) != ("seed", "task_type", "actor", "difficulty"):
    fail("candidate materialize signature must be (seed, task_type, actor, difficulty)")
if any(
    item.kind is not inspect.Parameter.POSITIONAL_OR_KEYWORD
    or item.default is not inspect.Parameter.empty
    for item in parameters
):
    fail("candidate materialize parameters must be required positional-or-keyword parameters")

results = []
for call in calls:
    if not isinstance(call, dict) or set(call) != {"seed", "task_type", "actor", "difficulty"}:
        fail("framework task-materializer call envelope was invalid", 70)
    seed = call["seed"]
    task_type = call["task_type"]
    actor = call["actor"]
    difficulty = call["difficulty"]
    if (
        isinstance(seed, bool)
        or not isinstance(seed, int)
        or not 0 <= seed <= 2**64 - 1
        or not isinstance(task_type, str)
        or not task_type
        or not isinstance(actor, str)
        or not actor
        or not isinstance(difficulty, dict)
    ):
        fail("framework task-materializer call values were invalid", 70)
    try:
        results.append(function(seed, task_type, actor, difficulty))
    except BaseException as exc:
        fail(f"candidate materialize call failed ({type(exc).__name__})")

try:
    encoded = json.dumps(
        {
            "protocol": "agent-world.task-materializer-runner.v3",
            "ok": True,
            "materializations": results,
        },
        allow_nan=False,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
except BaseException as exc:
    fail(f"candidate materialize output is not strict JSON ({type(exc).__name__})")
sys.stdout.write(encoded + "\n")
sys.stdout.flush()
"""

class JudgeInfrastructureError(RuntimeError):
    def __init__(
        self, code: str, message: str, *, details: Mapping[str, Any] | None = None
    ) -> None:
        super().__init__(message)
        self.code = code
        self.details = dict(details or {})

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": str(self), "details": self.details}


class IsolationUnavailable(JudgeInfrastructureError):
    pass


class CandidateBuildError(JudgeInfrastructureError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        record: InstallRecord | None = None,
        details: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(code, message, details=details)
        self.record = record


class RuntimeRequestTimeout(JudgeInfrastructureError):
    pass


class RuntimeProcessCrashed(JudgeInfrastructureError):
    pass


@dataclass(frozen=True, slots=True)
class ResourceLimits:
    cpu_seconds: int = 60
    address_space_bytes: int = 1024 * 1024 * 1024
    file_size_bytes: int = 128 * 1024 * 1024
    open_files: int = 256
    processes: int = 64

    def __post_init__(self) -> None:
        for name, value in (
            ("cpu_seconds", self.cpu_seconds),
            ("address_space_bytes", self.address_space_bytes),
            ("file_size_bytes", self.file_size_bytes),
            ("open_files", self.open_files),
            ("processes", self.processes),
        ):
            if value <= 0:
                raise ValueError(f"{name} must be positive")


@dataclass(frozen=True, slots=True)
class LaunchContract:
    argv: tuple[str, ...]
    cwd: str = "."
    env: Mapping[str, str] = field(default_factory=dict)
    abi_version: str = RUNTIME_ABI_VERSION
    allowed_interpreters: tuple[str, ...] = (
        ".venv/bin/python",
        ".venv/bin/python3",
        "python",
        "python3",
    )

    def validate(self, project_root: Path) -> ValidatedLaunch:
        root = Path(project_root).resolve(strict=True)
        if not root.is_dir():
            raise JudgeInfrastructureError(
                "invalid_candidate_root", "candidate project root must be a directory"
            )
        if self.abi_version != RUNTIME_ABI_VERSION:
            raise JudgeInfrastructureError(
                "launch_abi_mismatch",
                f"launch contract ABI must be {RUNTIME_ABI_VERSION}",
            )
        if not self.argv:
            raise JudgeInfrastructureError(
                "empty_launch_command", "launch command must not be empty"
            )
        if len(self.argv) > 256:
            raise JudgeInfrastructureError(
                "launch_command_too_large", "launch command has too many arguments"
            )
        total_chars = 0
        for argument in self.argv:
            if not isinstance(argument, str) or not argument or "\x00" in argument:
                raise JudgeInfrastructureError(
                    "invalid_launch_argument",
                    "launch arguments must be non-empty strings without NUL",
                )
            if len(argument) > 8192:
                raise JudgeInfrastructureError(
                    "invalid_launch_argument", "launch argument exceeds 8192 characters"
                )
            total_chars += len(argument)
        if total_chars > 64 * 1024:
            raise JudgeInfrastructureError(
                "launch_command_too_large", "launch command exceeds 64 KiB"
            )

        configured_interpreters = set(self.allowed_interpreters)
        if (
            not configured_interpreters
            or len(configured_interpreters) != len(self.allowed_interpreters)
            or not configured_interpreters.issubset(_APPROVED_INTERPRETERS)
        ):
            raise JudgeInfrastructureError(
                "invalid_interpreter_allowlist",
                "launch interpreter allowlist must be a unique non-empty subset "
                "of the framework allowlist",
            )

        cwd = _resolve_relative_directory(root, self.cwd, field_name="launch cwd")
        executable = self.argv[0]
        _validate_launch_executable(
            executable,
            root=root,
            cwd=cwd,
            allowed_interpreters=set(self.allowed_interpreters),
        )
        env = _validate_runtime_env(self.env)
        return ValidatedLaunch(
            argv=self.argv,
            cwd_relative=cwd.relative_to(root).as_posix() or ".",
            env=env,
        )


@dataclass(frozen=True, slots=True)
class ValidatedLaunch:
    argv: tuple[str, ...]
    cwd_relative: str
    env: Mapping[str, str]


@dataclass(frozen=True, slots=True)
class IsolationPolicy:
    bubblewrap_path: Path = _PRODUCTION_BWRAP
    purpose: Literal["runtime", "build"] = "runtime"
    workspace_read_only: bool = True
    probe_timeout_seconds: float = 5.0
    system_roots: tuple[Path, ...] = _PRODUCTION_SYSTEM_ROOTS
    python_runtime_root: Path = _PRODUCTION_PYTHON_ROOT

    def validate(self) -> None:
        if os.name != "posix":
            raise IsolationUnavailable(
                "unsupported_platform", "production Judge isolation requires POSIX bubblewrap"
            )
        bwrap = self.bubblewrap_path
        if bwrap != _PRODUCTION_BWRAP:
            raise IsolationUnavailable(
                "unapproved_bubblewrap",
                f"production Judge requires bubblewrap at {_PRODUCTION_BWRAP}",
            )
        if not bwrap.is_absolute() or not bwrap.is_file() or not os.access(bwrap, os.X_OK):
            raise IsolationUnavailable(
                "bubblewrap_unavailable",
                f"required bubblewrap executable is unavailable: {bwrap}",
            )
        if self.system_roots != _PRODUCTION_SYSTEM_ROOTS:
            raise IsolationUnavailable(
                "unapproved_system_roots",
                "production Judge exposes only the read-only /usr system root",
            )
        if self.python_runtime_root != _PRODUCTION_PYTHON_ROOT:
            raise IsolationUnavailable(
                "unapproved_python_runtime",
                "production Judge must use the framework-pinned Python runtime",
            )
        if (
            sys.version_info[:2] != (3, 12)
            or not self.python_runtime_root.is_dir()
            or not _PRODUCTION_PYTHON.is_file()
        ):
            raise IsolationUnavailable(
                "python_runtime_unavailable",
                "production Judge requires a complete framework Python 3.12 runtime",
            )
        if not all(root.is_absolute() and root.is_dir() for root in self.system_roots):
            raise IsolationUnavailable(
                "invalid_system_root", "required read-only system root is unavailable"
            )
        if not isinstance(self.workspace_read_only, bool):
            raise IsolationUnavailable(
                "invalid_isolation_policy", "isolation policy flags must be boolean"
            )
        if not self.workspace_read_only:
            raise IsolationUnavailable(
                "writable_judge_workspace_rejected",
                "production Judge and clean-build candidate workspaces are always read-only",
            )
        if self.probe_timeout_seconds <= 0:
            raise ValueError("probe_timeout_seconds must be positive")

    async def ensure_available(self) -> None:
        """Prove namespace creation works; finding bwrap on PATH is insufficient."""

        self.validate()
        with tempfile.TemporaryDirectory(
            prefix="agent-world-bwrap-probe-",
            dir=_trusted_temp_root(),
        ) as workspace_text:
            workspace = Path(workspace_text)
            state_dir = workspace / "state"
            state_dir.mkdir(mode=0o700)
            command = self.wrap_command(
                workspace=workspace,
                cwd_relative=".",
                argv=("/usr/bin/true",),
                state_dir=state_dir,
                writable_workspace=False,
                visible_workspace_paths=(),
            )
            process = await asyncio.create_subprocess_exec(
                *command,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=_scrubbed_host_env(),
                start_new_session=True,
            )
            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(), timeout=self.probe_timeout_seconds
                )
            except TimeoutError as exc:
                await _terminate_process_group(process)
                raise IsolationUnavailable(
                    "bubblewrap_probe_timeout", "bubblewrap isolation probe timed out"
                ) from exc
            except BaseException:
                await _terminate_process_group(process)
                raise
            if process.returncode != 0:
                raise IsolationUnavailable(
                    "bubblewrap_probe_failed",
                    "bubblewrap is installed but cannot create the required isolation namespaces",
                    details={
                        "exit_code": process.returncode,
                        "stdout": _decode_limited(stdout, 16 * 1024),
                        "stderr": _decode_limited(stderr, 16 * 1024),
                    },
                )

    def wrap_command(
        self,
        *,
        workspace: Path,
        cwd_relative: str,
        argv: Sequence[str],
        state_dir: Path,
        writable_workspace: bool = False,
        visible_workspace_paths: Sequence[str] | None = None,
        extra_env: Mapping[str, str] | None = None,
        extra_read_only_binds: Mapping[Path, str] | None = None,
        extra_ephemeral_overlay_binds: Mapping[Path, str] | None = None,
        extra_writable_directory_binds: Mapping[Path, str] | None = None,
        process_limit: int | None = None,
    ) -> tuple[str, ...]:
        self.validate()
        workspace = Path(workspace).resolve(strict=True)
        state_dir = Path(state_dir).resolve(strict=True)
        if not workspace.is_dir() or not state_dir.is_dir():
            raise IsolationUnavailable(
                "invalid_isolation_mount", "workspace and state mounts must be directories"
            )
        cwd_host = _resolve_relative_directory(workspace, cwd_relative, field_name="sandbox cwd")
        cwd_inside = "/workspace"
        relative = cwd_host.relative_to(workspace).as_posix()
        if relative != ".":
            cwd_inside = f"/workspace/{relative}"

        command: list[str] = [
            str(self.bubblewrap_path),
            "--die-with-parent",
            "--new-session",
            "--unshare-all",
            "--unshare-user",
        ]
        command.extend(["--disable-userns", "--clearenv"])
        for root in self.system_roots:
            command.extend(["--ro-bind", str(root), str(root)])
        command.extend(
            [
                "--symlink",
                "usr/bin",
                "/bin",
                "--symlink",
                "usr/sbin",
                "/sbin",
                "--symlink",
                "usr/lib",
                "/lib",
                "--symlink",
                "usr/lib64",
                "/lib64",
                "--dir",
                "/etc",
            ]
        )
        for host_path in _minimal_etc_mounts():
            command.extend(["--ro-bind", str(host_path), str(host_path)])
        command.extend(
            [
                "--proc",
                "/proc",
                "--dev",
                "/dev",
                "--tmpfs",
                str(_SANDBOX_TMP),
                "--dir",
                str(_SANDBOX_HOME),
                "--dir",
                "/run",
                "--dir",
                "/opt",
                "--dir",
                "/opt/agent-world",
                "--dir",
                "/opt/agent-world/bin",
                "--dir",
                _SANDBOX_PYTHON_ROOT,
            ]
        )
        command.extend(
            [
                "--ro-bind",
                str(self.python_runtime_root),
                _SANDBOX_PYTHON_ROOT,
            ]
        )
        if writable_workspace:
            raise IsolationUnavailable(
                "writable_candidate_workspace_rejected",
                "candidate source cannot be exposed as a writable build/runtime workspace",
            )
        if visible_workspace_paths is None:
            raise IsolationUnavailable(
                "workspace_visibility_required",
                "read-only candidate execution requires an explicit workspace file allowlist",
            )
        mounts, directories, venv = _validate_workspace_file_view(
            workspace,
            cwd_relative=relative,
            visible_paths=visible_workspace_paths,
        )
        command.extend(["--tmpfs", "/workspace"])
        for directory in directories:
            command.extend(["--dir", f"/workspace/{directory}"])
        if venv is not None:
            command.extend(["--ro-bind", str(venv), "/workspace/.venv"])
        for source, destination in mounts:
            command.extend(["--ro-bind", str(source), f"/workspace/{destination}"])
        if extra_writable_directory_binds:
            command.extend(["--dir", "/workspace/.venv"])
        command.extend(["--remount-ro", "/workspace"])
        command.extend(["--bind", str(state_dir), "/state"])

        for host_path, destination in (extra_writable_directory_binds or {}).items():
            source = Path(host_path).resolve(strict=True)
            if self.purpose != "build" or source.is_symlink() or not source.is_dir():
                raise IsolationUnavailable(
                    "invalid_isolation_bind",
                    "writable directory binds are restricted to real build directories",
                )
            if destination != "/workspace/.venv":
                raise IsolationUnavailable(
                    "invalid_isolation_bind",
                    f"unsafe writable build bind destination: {destination}",
                )
            command.extend(["--bind", str(source), destination])

        for host_path, destination in (extra_read_only_binds or {}).items():
            source = Path(host_path).resolve(strict=True)
            if not source.is_file():
                raise IsolationUnavailable(
                    "invalid_isolation_bind", f"read-only bind source is not a file: {source}"
                )
            if (
                not destination.startswith("/opt/agent-world/bin/")
                or ".." in PurePosixPath(destination).parts
            ):
                raise IsolationUnavailable(
                    "invalid_isolation_bind", f"unsafe isolation bind destination: {destination}"
                )
            command.extend(["--ro-bind", str(source), destination])

        allowed_directories = {_SANDBOX_UV_CACHE_SOURCE}
        for host_path, destination in (extra_ephemeral_overlay_binds or {}).items():
            source = Path(host_path).resolve(strict=True)
            if source.is_symlink() or not source.is_dir():
                raise IsolationUnavailable(
                    "invalid_isolation_bind",
                    f"read-only bind source is not a real directory: {source}",
                )
            if destination not in allowed_directories:
                raise IsolationUnavailable(
                    "invalid_isolation_bind",
                    f"unsafe isolation directory bind destination: {destination}",
                )
            command.extend(["--overlay-src", str(source), "--tmp-overlay", destination])

        child_env = {
            "PATH": "/workspace/.venv/bin:/opt/agent-world/bin:/usr/local/bin:/usr/bin:/bin",
            "HOME": str(_SANDBOX_HOME),
            "TMPDIR": str(_SANDBOX_TMP),
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONUNBUFFERED": "1",
            "AGENT_WORLD_WORKSPACE": "/workspace",
            "AGENT_WORLD_STATE_DIR": "/state",
            "UV_PYTHON": _SANDBOX_PYTHON,
            "UV_PYTHON_DOWNLOADS": "never",
        }
        child_env.update(_validate_runtime_env(extra_env or {}))
        for name, value in sorted(child_env.items()):
            command.extend(["--setenv", name, value])
        sandbox_argv = tuple(argv)
        if process_limit is not None:
            if process_limit < 1:
                raise ValueError("sandbox process_limit must be positive")
            sandbox_argv = (
                "/usr/bin/prlimit",
                f"--nproc={process_limit}:{process_limit}",
                "--",
                *sandbox_argv,
            )
        command.extend(["--chdir", cwd_inside, "--", *sandbox_argv])
        return tuple(command)


@dataclass(frozen=True, slots=True)
class InstallRecord:
    success: bool
    command: tuple[str, ...]
    cwd_ref: str
    exit_code: int | None
    stdout: str
    stderr: str
    stdout_truncated: bool
    stderr_truncated: bool
    duration_ms: int
    source_tree_hash: str
    candidate_source_tree_digest: str | None
    installed_tree_hash: str
    network_policy: Literal["disabled"]
    failure_class: str = ""


@dataclass(slots=True)
class CleanCandidate:
    root: Path
    source_tree_hash: str
    candidate_source_tree_digest: str | None
    installed_tree_hash: str
    install: InstallRecord
    _cleaned: bool = False

    def cleanup(self) -> None:
        if self._cleaned:
            return
        shutil.rmtree(self.root, ignore_errors=True)
        self._cleaned = True

    def __enter__(self) -> CleanCandidate:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.cleanup()


@dataclass(slots=True)
class CleanCandidateBuilder:
    build_isolation: IsolationPolicy = field(
        default_factory=lambda: IsolationPolicy(purpose="build")
    )
    uv_path: Path | None = None
    uv_cache_dir: Path | None = None
    timeout_seconds: float = 300.0
    max_output_bytes: int = 2 * 1024 * 1024
    max_source_files: int = 20_000
    max_source_bytes: int = 1024 * 1024 * 1024
    resource_limits: ResourceLimits = field(
        default_factory=lambda: ResourceLimits(
            cpu_seconds=300,
            address_space_bytes=4 * 1024 * 1024 * 1024,
            file_size_bytes=2 * 1024 * 1024 * 1024,
            open_files=512,
            processes=128,
        )
    )

    def __post_init__(self) -> None:
        if self.build_isolation.purpose != "build":
            raise ValueError("CleanCandidateBuilder requires a build-purpose isolation policy")
        if not self.build_isolation.workspace_read_only:
            raise ValueError("clean builds require a read-only candidate source view")
        for name, value in (
            ("timeout_seconds", self.timeout_seconds),
            ("max_output_bytes", self.max_output_bytes),
            ("max_source_files", self.max_source_files),
            ("max_source_bytes", self.max_source_bytes),
        ):
            if value <= 0:
                raise ValueError(f"{name} must be positive")
        if self.uv_cache_dir is not None and (
            self.uv_cache_dir.is_symlink() or not self.uv_cache_dir.is_dir()
        ):
            raise ValueError("uv_cache_dir must be a real directory")

    async def build(
        self,
        source_dir: Path,
        *,
        expected_source_files: tuple[PackageFile, ...] | None = None,
        expected_source_tree_digest: str | None = None,
    ) -> CleanCandidate:
        """Copy and install a candidate without importing it into the Judge."""

        if (expected_source_files is None) != (expected_source_tree_digest is None):
            raise ValueError(
                "expected source files and candidate source-tree digest must be supplied together"
            )

        await self.build_isolation.ensure_available()
        source = await _run_blocking(_resolve_candidate_source, source_dir)
        uv_path = await _run_blocking(_resolve_uv_executable, self.uv_path)

        clean_root = Path(
            tempfile.mkdtemp(
                prefix="agent-world-clean-candidate-",
                dir=_trusted_temp_root(),
            )
        )
        os.chmod(clean_root, 0o700)
        state_dir = Path(
            tempfile.mkdtemp(
                prefix="agent-world-clean-build-state-",
                dir=_trusted_temp_root(),
            )
        )
        os.chmod(state_dir, 0o700)
        dependency_environment = Path(
            tempfile.mkdtemp(
                prefix="agent-world-clean-build-venv-",
                dir=_trusted_temp_root(),
            )
        )
        os.chmod(dependency_environment, 0o700)
        try:
            source_hash = await _run_blocking(
                _prepare_clean_source,
                source,
                clean_root,
                max_files=self.max_source_files,
                max_bytes=self.max_source_bytes,
            )
            (clean_root / ".venv").mkdir(mode=0o700)
            source_hash = await _run_blocking(_hash_tree, clean_root)
            visible_source_paths = await _run_blocking(_source_file_view, clean_root)
            source_manifest_digest: str | None = None
            if expected_source_files is not None and expected_source_tree_digest is not None:
                source_manifest_digest = await _run_blocking(
                    _validate_declared_source_tree,
                    clean_root,
                    expected_source_files,
                    expected_source_tree_digest,
                )
            inner_command = [
                "/opt/agent-world/bin/uv",
                "sync",
                "--frozen",
                "--no-dev",
                "--offline",
                "--no-build",
                "--no-editable",
                "--no-config",
                "--no-install-project",
                "--no-install-workspace",
                "--no-install-local",
            ]
            cache_inside = (
                _SANDBOX_UV_CACHE_SOURCE
                if self.uv_cache_dir is not None
                else str(_SANDBOX_UV_CACHE)
            )
            wrapped = self.build_isolation.wrap_command(
                workspace=clean_root,
                cwd_relative=".",
                argv=inner_command,
                state_dir=state_dir,
                writable_workspace=False,
                visible_workspace_paths=visible_source_paths,
                extra_env={
                    "UV_PROJECT_ENVIRONMENT": "/workspace/.venv",
                    "UV_CACHE_DIR": cache_inside,
                    "UV_LINK_MODE": "copy",
                    "UV_NO_PROGRESS": "1",
                },
                extra_read_only_binds={uv_path: "/opt/agent-world/bin/uv"},
                extra_ephemeral_overlay_binds=(
                    {self.uv_cache_dir: _SANDBOX_UV_CACHE_SOURCE}
                    if self.uv_cache_dir is not None
                    else None
                ),
                extra_writable_directory_binds={
                    dependency_environment: "/workspace/.venv"
                },
                process_limit=self.resource_limits.processes,
            )
            started = time.monotonic()
            outcome = await _run_captured_process(
                wrapped,
                timeout_seconds=self.timeout_seconds,
                max_output_bytes=self.max_output_bytes,
                limits=self.resource_limits,
                failure_prefix="uv_sync",
            )
            duration_ms = int((time.monotonic() - started) * 1000)
            if outcome.exit_code != 0 and outcome.stderr.lstrip().startswith("bwrap:"):
                raise IsolationUnavailable(
                    "bubblewrap_launch_failed",
                    "Bubblewrap failed before the candidate build process started",
                    details={
                        "exit_code": outcome.exit_code,
                        "stderr_hash": sha256_digest(outcome.stderr.encode("utf-8")),
                        "failure_class": outcome.failure_class,
                    },
                )
            if outcome.exit_code != 0:
                record = InstallRecord(
                    success=False,
                    command=tuple(inner_command),
                    cwd_ref=".",
                    exit_code=outcome.exit_code,
                    stdout=outcome.stdout,
                    stderr=outcome.stderr,
                    stdout_truncated=outcome.stdout_truncated,
                    stderr_truncated=outcome.stderr_truncated,
                    duration_ms=duration_ms,
                    source_tree_hash=source_hash,
                    candidate_source_tree_digest=source_manifest_digest,
                    installed_tree_hash="",
                    network_policy="disabled",
                    failure_class=outcome.failure_class or "uv_sync_failed",
                )
                raise CandidateBuildError(
                    record.failure_class,
                    "candidate failed dependency-only frozen `uv sync` installation",
                    record=record,
                )
            if await _run_blocking(_hash_tree, clean_root) != source_hash:
                raise CandidateBuildError(
                    "candidate_source_mutated",
                    "dependency installation changed the read-only candidate source tree",
                )
            if expected_source_files is not None and expected_source_tree_digest is not None:
                post_install_digest = await _run_blocking(
                    _validate_declared_source_tree,
                    clean_root,
                    expected_source_files,
                    expected_source_tree_digest,
                )
                if post_install_digest != source_manifest_digest:
                    raise CandidateBuildError(
                        "candidate_source_digest_changed",
                        "candidate source-tree digest changed during dependency installation",
                    )
            (clean_root / ".venv").rmdir()
            await _run_blocking(
                shutil.copytree,
                dependency_environment,
                clean_root / ".venv",
                symlinks=True,
            )
            installed_hash = await _run_blocking(_validate_and_hash_installed, clean_root)
            record = InstallRecord(
                success=True,
                command=tuple(inner_command),
                cwd_ref=".",
                exit_code=outcome.exit_code,
                stdout=outcome.stdout,
                stderr=outcome.stderr,
                stdout_truncated=outcome.stdout_truncated,
                stderr_truncated=outcome.stderr_truncated,
                duration_ms=duration_ms,
                source_tree_hash=source_hash,
                candidate_source_tree_digest=source_manifest_digest,
                installed_tree_hash=installed_hash,
                network_policy="disabled",
            )
            return CleanCandidate(
                root=clean_root,
                source_tree_hash=source_hash,
                candidate_source_tree_digest=source_manifest_digest,
                installed_tree_hash=installed_hash,
                install=record,
            )
        except BaseException:
            await _run_blocking(shutil.rmtree, clean_root, ignore_errors=True)
            raise
        finally:
            await _run_blocking(shutil.rmtree, state_dir, ignore_errors=True)
            await _run_blocking(shutil.rmtree, dependency_environment, ignore_errors=True)

    @asynccontextmanager
    async def materialize(
        self,
        source_dir: Path,
        *,
        expected_source_files: tuple[PackageFile, ...] | None = None,
        expected_source_tree_digest: str | None = None,
    ) -> AsyncIterator[CleanCandidate]:
        candidate = await self.build(
            source_dir,
            expected_source_files=expected_source_files,
            expected_source_tree_digest=expected_source_tree_digest,
        )
        try:
            yield candidate
        finally:
            await _run_blocking(candidate.cleanup)


@dataclass(frozen=True, slots=True)
class SandboxProcessResult:
    """Bounded subprocess result; stdout/stderr remain ephemeral Judge memory."""

    argv: tuple[str, ...]
    exit_code: int | None
    stdout: str
    stderr: str
    stdout_truncated: bool
    stderr_truncated: bool
    duration_ms: int
    failure_class: str = ""

    @property
    def succeeded(self) -> bool:
        return (
            self.exit_code == 0
            and not self.failure_class
            and not self.stdout_truncated
            and not self.stderr_truncated
        )


@dataclass(slots=True)
class CandidateSandboxRunner:
    """Run finite candidate commands without importing candidate code in Judge."""

    isolation: IsolationPolicy = field(default_factory=IsolationPolicy)
    timeout_seconds: float = 60.0
    max_output_bytes: int = 1024 * 1024
    max_input_bytes: int = 1024 * 1024
    resource_limits: ResourceLimits = field(default_factory=ResourceLimits)

    def __post_init__(self) -> None:
        for name, value in (
            ("timeout_seconds", self.timeout_seconds),
            ("max_output_bytes", self.max_output_bytes),
            ("max_input_bytes", self.max_input_bytes),
        ):
            if value <= 0:
                raise ValueError(f"{name} must be positive")

    async def run(
        self,
        project_root: Path,
        *,
        argv: Sequence[str],
        visible_workspace_paths: Sequence[str],
        cwd: str = ".",
        stdin_bytes: bytes | None = None,
        timeout_seconds: float | None = None,
        max_output_bytes: int | None = None,
        extra_read_only_binds: Mapping[Path, str] | None = None,
        failure_prefix: str = "candidate_command",
    ) -> SandboxProcessResult:
        if isinstance(visible_workspace_paths, (str, bytes)):
            raise JudgeInfrastructureError(
                "invalid_workspace_visibility",
                "candidate command visibility must be an explicit sequence of file paths",
            )
        await self.isolation.ensure_available()
        launch = LaunchContract(argv=tuple(argv), cwd=cwd).validate(project_root)
        if stdin_bytes is not None and len(stdin_bytes) > self.max_input_bytes:
            raise JudgeInfrastructureError(
                "sandbox_input_limit_exceeded",
                "framework-owned sandbox input exceeds its configured limit",
            )
        effective_timeout = min(timeout_seconds or self.timeout_seconds, self.timeout_seconds)
        effective_output_limit = min(
            max_output_bytes or self.max_output_bytes,
            self.max_output_bytes,
        )
        if effective_timeout <= 0 or effective_output_limit <= 0:
            raise ValueError("sandbox timeout and output limit must be positive")

        with tempfile.TemporaryDirectory(
            prefix="agent-world-command-state-",
            dir=_trusted_temp_root(),
        ) as state_text:
            state_dir = Path(state_text)
            os.chmod(state_dir, 0o700)
            wrapped = self.isolation.wrap_command(
                workspace=project_root,
                cwd_relative=launch.cwd_relative,
                argv=launch.argv,
                state_dir=state_dir,
                writable_workspace=False,
                visible_workspace_paths=visible_workspace_paths,
                extra_env=launch.env,
                extra_read_only_binds=extra_read_only_binds,
                process_limit=self.resource_limits.processes,
            )
            started = time.monotonic()
            try:
                outcome = await _run_captured_process(
                    wrapped,
                    timeout_seconds=effective_timeout,
                    max_output_bytes=effective_output_limit,
                    limits=self.resource_limits,
                    failure_prefix=failure_prefix,
                    stdin_bytes=stdin_bytes,
                )
            except OSError as exc:
                raise JudgeInfrastructureError(
                    "sandbox_process_spawn_failed",
                    "Judge could not spawn the required isolated subprocess",
                    details={"error_type": type(exc).__name__},
                ) from exc
            duration_ms = int((time.monotonic() - started) * 1000)
        return SandboxProcessResult(
            argv=launch.argv,
            exit_code=outcome.exit_code,
            stdout=outcome.stdout,
            stderr=outcome.stderr,
            stdout_truncated=outcome.stdout_truncated,
            stderr_truncated=outcome.stderr_truncated,
            duration_ms=duration_ms,
            failure_class=outcome.failure_class,
        )

    async def run_task_materializer(
        self,
        project_root: Path,
        *,
        entrypoint: str,
        calls: Sequence[Mapping[str, JsonValue]],
        visible_workspace_paths: Sequence[str],
    ) -> SandboxProcessResult:
        if isinstance(visible_workspace_paths, (str, bytes)) or not visible_workspace_paths:
            raise JudgeInfrastructureError(
                "workspace_visibility_required",
                "task materializers require a non-empty role file allowlist",
            )
        request = {
            "protocol": "agent-world.task-materializer-runner.v3",
            "entrypoint": entrypoint,
            "calls": [dict(item) for item in calls],
        }
        try:
            stdin_bytes = json.dumps(
                request,
                allow_nan=False,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise JudgeInfrastructureError(
                "task_materializer_runner_input_serialization_failed",
                "framework could not serialize task-materializer inputs",
            ) from exc

        with tempfile.TemporaryDirectory(
            prefix="agent-world-task-materializer-",
            dir=_trusted_temp_root(),
        ) as runner_text:
            runner_path = Path(runner_text) / "task-materializer-runner.py"
            runner_path.write_text(_TASK_MATERIALIZER_RUNNER_SOURCE, encoding="utf-8")
            runner_path.chmod(0o400)
            return await self.run(
                project_root,
                argv=(".venv/bin/python", _TASK_MATERIALIZER_RUNNER_DESTINATION),
                visible_workspace_paths=visible_workspace_paths,
                stdin_bytes=stdin_bytes,
                extra_read_only_binds={runner_path: _TASK_MATERIALIZER_RUNNER_DESTINATION},
                failure_prefix="task_materializer",
            )


class RuntimeSupervisor:
    """Own an untrusted ABI v2 runtime process without importing candidate code."""

    def __init__(
        self,
        project_root: Path,
        launch: LaunchContract,
        *,
        visible_workspace_paths: Sequence[str],
        isolation: IsolationPolicy | None = None,
        protocol_limits: ProtocolLimits = DEFAULT_PROTOCOL_LIMITS,
        resource_limits: ResourceLimits | None = None,
        request_timeout_seconds: float = 10.0,
        shutdown_grace_seconds: float = 2.0,
        max_stderr_bytes: int = 256 * 1024,
        on_subprocess_scene: Callable[[RuntimeSubprocessScene], None] | None = None,
        known_secret_canaries: Sequence[str | bytes] = (),
    ) -> None:
        self.project_root = Path(project_root).resolve(strict=True)
        self.launch = launch
        if isinstance(visible_workspace_paths, (str, bytes)) or not visible_workspace_paths:
            raise ValueError("RuntimeSupervisor requires a non-empty role file allowlist")
        self.visible_workspace_paths = tuple(visible_workspace_paths)
        self.isolation = isolation or IsolationPolicy()
        self.protocol_limits = protocol_limits
        self.resource_limits = resource_limits or ResourceLimits()
        self.request_timeout_seconds = request_timeout_seconds
        self.shutdown_grace_seconds = shutdown_grace_seconds
        self.max_stderr_bytes = max_stderr_bytes
        self._on_subprocess_scene = on_subprocess_scene
        self._known_secret_canaries = tuple(known_secret_canaries)
        if request_timeout_seconds <= 0 or shutdown_grace_seconds <= 0 or max_stderr_bytes <= 0:
            raise ValueError("supervisor timeouts and output limits must be positive")

        self._validated_launch: ValidatedLaunch | None = None
        self._process: asyncio.subprocess.Process | None = None
        self._stderr_task: asyncio.Task[tuple[bytes, bool]] | None = None
        self._stderr_bytes = b""
        self._stderr_truncated = False
        self._request_lock = asyncio.Lock()
        self._state_temp: tempfile.TemporaryDirectory[str] | None = None
        self._handshake: RuntimeResponse | None = None
        self._closed = False

    @property
    def pid(self) -> int | None:
        return self._process.pid if self._process is not None else None

    @property
    def handshake_response(self) -> RuntimeResponse | None:
        return self._handshake

    @property
    def stderr(self) -> str:
        suffix = "\n<stderr truncated>" if self._stderr_truncated else ""
        return self._stderr_bytes.decode("utf-8", errors="replace") + suffix

    async def start(self) -> RuntimeResponse:
        if self._closed:
            raise JudgeInfrastructureError(
                "supervisor_closed", "closed RuntimeSupervisor cannot be restarted"
            )
        if self._process is not None:
            raise JudgeInfrastructureError(
                "runtime_already_started", "runtime process is already started"
            )
        await self.isolation.ensure_available()
        self._validated_launch = self.launch.validate(self.project_root)
        self._state_temp = tempfile.TemporaryDirectory(
            prefix="agent-world-runtime-state-",
            dir=_trusted_temp_root(),
        )
        state_dir = Path(self._state_temp.name)
        os.chmod(state_dir, 0o700)
        wrapped = self.isolation.wrap_command(
            workspace=self.project_root,
            cwd_relative=self._validated_launch.cwd_relative,
            argv=self._validated_launch.argv,
            state_dir=state_dir,
            writable_workspace=False,
            visible_workspace_paths=self.visible_workspace_paths,
            extra_env=self._validated_launch.env,
            process_limit=self.resource_limits.processes,
        )
        try:
            self._process = await asyncio.create_subprocess_exec(
                *wrapped,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=_scrubbed_host_env(),
                start_new_session=True,
                preexec_fn=_rlimit_preexec(self.resource_limits),
                limit=self.protocol_limits.max_message_bytes + 1,
            )
            assert self._process.stderr is not None
            self._stderr_task = asyncio.create_task(
                _read_stream_limited(self._process.stderr, self.max_stderr_bytes),
                name=f"runtime-stderr-{self._process.pid}",
            )
            self._handshake = await self.handshake()
            return self._handshake
        except BaseException:
            await self.terminate()
            raise

    async def handshake(self) -> RuntimeResponse:
        return await self.request(RuntimeOperation.HANDSHAKE, {})

    async def reset(
        self,
        *,
        seed: int | str,
        actor: str,
        config: Mapping[str, JsonValue],
    ) -> RuntimeResponse:
        return await self.request(
            RuntimeOperation.RESET,
            {"seed": seed, "actor": actor, "config": dict(config)},
        )

    async def invoke(
        self,
        *,
        tool: str,
        args: Mapping[str, JsonValue],
        idempotency_key: str,
    ) -> RuntimeResponse:
        return await self.request(
            RuntimeOperation.INVOKE,
            {"tool": tool, "args": dict(args), "idempotency_key": idempotency_key},
        )

    async def snapshot(self) -> RuntimeResponse:
        return await self.request(RuntimeOperation.SNAPSHOT, {})

    async def request(
        self,
        operation: RuntimeOperation | str,
        payload: Mapping[str, JsonValue],
        *,
        timeout_seconds: float | None = None,
    ) -> RuntimeResponse:
        process = self._require_running()
        request = make_request(operation, payload, limits=self.protocol_limits)
        timeout = self.request_timeout_seconds if timeout_seconds is None else timeout_seconds
        if timeout <= 0:
            raise ValueError("request timeout must be positive")
        try:
            async with asyncio.timeout(timeout):
                async with self._request_lock:
                    if process.returncode is not None:
                        await self._refresh_stderr(wait_for_eof=True)
                        raise self._crashed_error(
                            "runtime exited before request",
                            operation=request.operation,
                        )
                    assert process.stdin is not None
                    assert process.stdout is not None
                    process.stdin.write(encode_request(request, limits=self.protocol_limits))
                    await process.stdin.drain()
                    try:
                        raw = await process.stdout.readline()
                    except ValueError as exc:
                        raise ProtocolViolation(
                            "response_too_large",
                            (
                                "runtime response exceeds "
                                f"{self.protocol_limits.max_message_bytes} bytes"
                            ),
                            request_id=request.request_id,
                        ) from exc
                    if not raw:
                        await process.wait()
                        await self._refresh_stderr(wait_for_eof=True)
                        raise self._crashed_error(
                            "runtime exited without a response",
                            operation=request.operation,
                        )
                    return decode_response(
                        raw,
                        expected_request=request,
                        limits=self.protocol_limits,
                    )
        except TimeoutError as exc:
            await self.terminate()
            raise RuntimeRequestTimeout(
                "runtime_request_timeout",
                f"runtime {request.operation.value} request timed out",
                details={"request_id": request.request_id, "timeout_seconds": timeout},
            ) from exc
        except (ProtocolViolation, RuntimeProcessCrashed):
            await self.terminate()
            raise
        except asyncio.CancelledError:
            await self.terminate()
            raise
        except (BrokenPipeError, ConnectionResetError) as exc:
            await self._refresh_stderr()
            error = self._crashed_error(
                "runtime communication channel closed",
                operation=request.operation,
            )
            await self.terminate()
            raise error from exc

    async def close(self) -> RuntimeResponse | None:
        if self._closed:
            return None
        response: RuntimeResponse | None = None
        try:
            if self._process is not None and self._process.returncode is None:
                response = await self.request(RuntimeOperation.CLOSE, {})
            return response
        finally:
            try:
                await self.terminate()
            finally:
                self._closed = True

    async def terminate(self) -> None:
        process = self._process
        if process is not None:
            await _terminate_process_group(process, grace_seconds=self.shutdown_grace_seconds)
        await self._refresh_stderr(wait_for_eof=True)
        if self._stderr_task is not None and not self._stderr_task.done():
            self._stderr_task.cancel()
            await asyncio.gather(self._stderr_task, return_exceptions=True)
        self._stderr_task = None
        if process is not None and process.stdin is not None:
            process.stdin.close()
        self._process = None
        if self._state_temp is not None:
            self._state_temp.cleanup()
            self._state_temp = None

    async def __aenter__(self) -> RuntimeSupervisor:
        await self.start()
        return self

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None:
        try:
            await self.close()
        except Exception:
            await self.terminate()
            if exc is None:
                raise

    def _require_running(self) -> asyncio.subprocess.Process:
        if self._closed:
            raise JudgeInfrastructureError("supervisor_closed", "RuntimeSupervisor is closed")
        if self._process is None:
            raise JudgeInfrastructureError(
                "runtime_not_started", "runtime process has not been started"
            )
        return self._process

    async def _refresh_stderr(self, *, wait_for_eof: bool = False) -> None:
        if self._stderr_task is None:
            return
        if wait_for_eof and not self._stderr_task.done():
            try:
                await asyncio.wait_for(asyncio.shield(self._stderr_task), timeout=0.5)
            except TimeoutError:
                pass
        if self._stderr_task.done():
            try:
                self._stderr_bytes, self._stderr_truncated = self._stderr_task.result()
            except asyncio.CancelledError:
                pass

    def _crashed_error(
        self,
        message: str,
        *,
        operation: RuntimeOperation | str | None = None,
    ) -> RuntimeProcessCrashed:
        error = RuntimeProcessCrashed(
            "runtime_process_crashed",
            message,
            details={
                "exit_code": self._process.returncode if self._process is not None else None,
                "stderr": self.stderr,
            },
        )
        callback = self._on_subprocess_scene
        if callback is not None:
            operation_name = (
                operation.value if isinstance(operation, RuntimeOperation) else operation
            )
            try:
                callback(
                    runtime_subprocess_scene(
                        operation=operation_name or "unknown",
                        exit_code=error.details.get("exit_code"),
                        stderr=error.details.get("stderr"),
                        launch_argv=self.launch.argv,
                        known_secret_canaries=self._known_secret_canaries,
                    )
                )
            except Exception:
                # Observability is strictly a side effect: Runtime failure routing
                # must remain correct when its projection cannot be recorded.
                return error
        return error


@dataclass(frozen=True, slots=True)
class _CapturedOutcome:
    exit_code: int | None
    stdout: str
    stderr: str
    stdout_truncated: bool
    stderr_truncated: bool
    failure_class: str = ""


async def _run_blocking[T](function: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    """Finish a filesystem operation before propagating task cancellation."""

    task = asyncio.create_task(asyncio.to_thread(function, *args, **kwargs))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        await asyncio.gather(task, return_exceptions=True)
        raise


async def _run_captured_process(
    argv: Sequence[str],
    *,
    timeout_seconds: float,
    max_output_bytes: int,
    limits: ResourceLimits,
    failure_prefix: str,
    stdin_bytes: bytes | None = None,
) -> _CapturedOutcome:
    process = await asyncio.create_subprocess_exec(
        *argv,
        stdin=(asyncio.subprocess.PIPE if stdin_bytes is not None else asyncio.subprocess.DEVNULL),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=_scrubbed_host_env(),
        start_new_session=True,
        preexec_fn=_rlimit_preexec(limits),
    )
    assert process.stdout is not None
    assert process.stderr is not None
    stdout_task = asyncio.create_task(_read_stream_limited(process.stdout, max_output_bytes))
    stderr_task = asyncio.create_task(_read_stream_limited(process.stderr, max_output_bytes))
    stdin_task: asyncio.Task[None] | None = None
    if stdin_bytes is not None:
        stdin_writer = process.stdin
        assert stdin_writer is not None

        async def write_stdin() -> None:
            stdin_writer.write(stdin_bytes)
            await stdin_writer.drain()
            stdin_writer.close()
            await stdin_writer.wait_closed()

        stdin_task = asyncio.create_task(write_stdin())
    try:
        try:
            async with asyncio.timeout(timeout_seconds):
                if stdin_task is not None:
                    await stdin_task
                await process.wait()
            failure_class = "" if process.returncode == 0 else f"{failure_prefix}_failed"
        except TimeoutError:
            await _terminate_process_group(process)
            failure_class = f"{failure_prefix}_timeout"
            if stdin_task is not None and not stdin_task.done():
                stdin_task.cancel()
                await asyncio.gather(stdin_task, return_exceptions=True)
        stdout_result, stderr_result = await asyncio.gather(stdout_task, stderr_task)
        return _CapturedOutcome(
            exit_code=process.returncode,
            stdout=stdout_result[0].decode("utf-8", errors="replace"),
            stderr=stderr_result[0].decode("utf-8", errors="replace"),
            stdout_truncated=stdout_result[1],
            stderr_truncated=stderr_result[1],
            failure_class=failure_class,
        )
    except BaseException:
        await _terminate_process_group(process)
        for task in (stdout_task, stderr_task, stdin_task):
            if task is None:
                continue
            if not task.done():
                task.cancel()
        await asyncio.gather(
            *(task for task in (stdout_task, stderr_task, stdin_task) if task is not None),
            return_exceptions=True,
        )
        raise


async def _read_stream_limited(stream: asyncio.StreamReader, limit: int) -> tuple[bytes, bool]:
    captured = bytearray()
    truncated = False
    while True:
        chunk = await stream.read(64 * 1024)
        if not chunk:
            break
        remaining = limit - len(captured)
        if remaining > 0:
            captured.extend(chunk[:remaining])
        if len(chunk) > max(0, remaining):
            truncated = True
    return bytes(captured), truncated


async def _terminate_process_group(
    process: asyncio.subprocess.Process, *, grace_seconds: float = 2.0
) -> None:
    if process.returncode is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        await asyncio.wait_for(process.wait(), timeout=grace_seconds)
        return
    except TimeoutError:
        pass
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    await process.wait()


def _rlimit_preexec(limits: ResourceLimits):
    def apply_limits() -> None:
        resource.setrlimit(resource.RLIMIT_CPU, (limits.cpu_seconds, limits.cpu_seconds))
        resource.setrlimit(
            resource.RLIMIT_AS, (limits.address_space_bytes, limits.address_space_bytes)
        )
        resource.setrlimit(resource.RLIMIT_FSIZE, (limits.file_size_bytes, limits.file_size_bytes))
        resource.setrlimit(resource.RLIMIT_NOFILE, (limits.open_files, limits.open_files))
        # RLIMIT_NPROC is applied by trusted ``prlimit`` *inside* the new user/PID
        # namespaces. Applying it to the host-side bwrap launcher can make Linux
        # reject namespace creation based on unrelated host UID process counts.

    return apply_limits


_ENV_NAME_RE = re.compile(r"^[A-Z_][A-Z0-9_]{0,127}$")
_SECRET_ENV_FRAGMENTS = (
    "SECRET",
    "TOKEN",
    "PASSWORD",
    "PASSWD",
    "API_KEY",
    "CREDENTIAL",
    "COOKIE",
    "AUTH",
)
_RESERVED_CHILD_ENV = frozenset(
    {
        "PATH",
        "HOME",
        "TMPDIR",
        "AGENT_WORLD_WORKSPACE",
        "AGENT_WORLD_STATE_DIR",
        "PYTHONPATH",
        "VIRTUAL_ENV",
        "LD_PRELOAD",
        "LD_LIBRARY_PATH",
    }
)


def _validate_runtime_env(value: Mapping[str, str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for name, raw in value.items():
        if not isinstance(name, str) or not _ENV_NAME_RE.fullmatch(name):
            raise JudgeInfrastructureError(
                "invalid_runtime_environment", f"invalid runtime environment name: {name!r}"
            )
        if name in _RESERVED_CHILD_ENV:
            raise JudgeInfrastructureError(
                "reserved_runtime_environment",
                f"runtime cannot override reserved environment variable {name}",
            )
        if any(fragment in name for fragment in _SECRET_ENV_FRAGMENTS):
            raise JudgeInfrastructureError(
                "secret_environment_rejected",
                f"runtime environment cannot contain secret-bearing variable {name}",
            )
        if not isinstance(raw, str) or "\x00" in raw or len(raw) > 8192:
            raise JudgeInfrastructureError(
                "invalid_runtime_environment",
                f"invalid value for runtime environment variable {name}",
            )
        result[name] = raw
    return result


def _scrubbed_host_env() -> dict[str, str]:
    return {
        "PATH": "/usr/bin:/bin",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
    }


def _resolve_relative_directory(root: Path, value: str, *, field_name: str) -> Path:
    if not isinstance(value, str) or not value or "\\" in value:
        raise JudgeInfrastructureError(
            "invalid_relative_path", f"{field_name} must be a non-empty POSIX path"
        )
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts:
        raise JudgeInfrastructureError(
            "path_escape_rejected", f"{field_name} must stay inside the candidate root"
        )
    resolved = (root / Path(*path.parts)).resolve(strict=True)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise JudgeInfrastructureError(
            "path_escape_rejected", f"{field_name} resolves outside the candidate root"
        ) from exc
    if not resolved.is_dir():
        raise JudgeInfrastructureError("invalid_relative_path", f"{field_name} is not a directory")
    return resolved


def _validate_workspace_file_view(
    root: Path,
    *,
    cwd_relative: str,
    visible_paths: Sequence[str],
) -> tuple[tuple[tuple[Path, str], ...], tuple[str, ...], Path | None]:
    """Validate and compile one exact, role-scoped candidate workspace view."""

    if isinstance(visible_paths, (str, bytes)):
        raise IsolationUnavailable(
            "invalid_workspace_visibility",
            "workspace visibility must be a sequence of package-relative file paths",
        )
    root = root.resolve(strict=True)
    mounts: list[tuple[Path, str]] = []
    seen: set[str] = set()
    directories: set[str] = set()

    cwd = PurePosixPath(cwd_relative)
    if cwd_relative != ".":
        _validate_real_directory_chain(root, cwd, label="sandbox cwd")
        for index in range(1, len(cwd.parts) + 1):
            directories.add(PurePosixPath(*cwd.parts[:index]).as_posix())

    for raw_path in visible_paths:
        if (
            not isinstance(raw_path, str)
            or not raw_path
            or "\x00" in raw_path
            or "\\" in raw_path
            or len(raw_path) > 4096
        ):
            raise IsolationUnavailable(
                "invalid_workspace_visibility",
                "visible workspace paths must be bounded non-empty POSIX strings",
            )
        relative = PurePosixPath(raw_path)
        canonical = relative.as_posix()
        if (
            relative.is_absolute()
            or canonical in {"", ".", ".."}
            or ".." in relative.parts
            or canonical != raw_path
            or not relative.parts
            or relative.parts[0] == ".venv"
        ):
            raise IsolationUnavailable(
                "workspace_visibility_escape",
                f"visible workspace path is not a canonical candidate file: {raw_path!r}",
            )
        if canonical in seen:
            raise IsolationUnavailable(
                "duplicate_workspace_visibility",
                f"visible workspace path is duplicated: {canonical}",
            )
        seen.add(canonical)
        source = _validate_real_file_chain(root, relative)
        mounts.append((source, canonical))
        for index in range(1, len(relative.parts)):
            directories.add(PurePosixPath(*relative.parts[:index]).as_posix())

    venv_candidate = root / ".venv"
    venv: Path | None = venv_candidate
    try:
        venv_stat = venv_candidate.lstat()
    except OSError as exc:
        venv = None
        if mounts:
            raise IsolationUnavailable(
                "candidate_venv_missing",
                "role-scoped candidate execution requires the clean .venv dependency tree",
            ) from exc
    if venv is not None:
        if stat.S_ISLNK(venv_stat.st_mode) or not stat.S_ISDIR(venv_stat.st_mode):
            raise IsolationUnavailable(
                "candidate_venv_invalid",
                "candidate .venv must be a real directory",
            )
        directories.add(".venv")

    return (
        tuple(sorted(mounts, key=lambda item: item[1])),
        tuple(sorted(directories, key=lambda item: (item.count("/"), item))),
        venv,
    )


def _validate_real_directory_chain(root: Path, relative: PurePosixPath, *, label: str) -> Path:
    current = root
    for part in relative.parts:
        current = current / part
        try:
            current_stat = current.lstat()
        except OSError as exc:
            raise IsolationUnavailable(
                "workspace_visibility_missing",
                f"{label} is absent from the candidate workspace: {relative.as_posix()}",
            ) from exc
        if stat.S_ISLNK(current_stat.st_mode) or not stat.S_ISDIR(current_stat.st_mode):
            raise IsolationUnavailable(
                "workspace_visibility_unsafe_parent",
                f"{label} traverses a symlink or non-directory: {relative.as_posix()}",
            )
    return current


def _validate_real_file_chain(root: Path, relative: PurePosixPath) -> Path:
    if len(relative.parts) > 1:
        _validate_real_directory_chain(
            root,
            PurePosixPath(*relative.parts[:-1]),
            label="visible workspace file parent",
        )
    source = root.joinpath(*relative.parts)
    try:
        source_stat = source.lstat()
    except OSError as exc:
        raise IsolationUnavailable(
            "workspace_visibility_missing",
            f"visible workspace file is absent: {relative.as_posix()}",
        ) from exc
    if stat.S_ISLNK(source_stat.st_mode) or not stat.S_ISREG(source_stat.st_mode):
        raise IsolationUnavailable(
            "workspace_visibility_not_regular",
            f"visible workspace path is not a real regular file: {relative.as_posix()}",
        )
    return source


def _validate_launch_executable(
    executable: str,
    *,
    root: Path,
    cwd: Path,
    allowed_interpreters: set[str],
) -> None:
    if "\\" in executable or "\x00" in executable:
        raise JudgeInfrastructureError(
            "invalid_launch_executable", "launch executable must use a safe POSIX path"
        )
    path = PurePosixPath(executable)
    if path.is_absolute() or ".." in path.parts:
        raise JudgeInfrastructureError(
            "launch_path_escape",
            "launch executable must be relative to cwd or an allowed interpreter",
        )
    if "/" not in executable:
        if executable not in allowed_interpreters:
            raise JudgeInfrastructureError(
                "launch_executable_not_allowed", f"bare executable is not allowed: {executable}"
            )
        return
    lexical = cwd / Path(*path.parts)
    normalized = path.as_posix()
    if lexical.is_symlink() and normalized in allowed_interpreters:
        _validate_pinned_venv_interpreter_link(lexical, root=root)
        return
    if not lexical.exists():
        raise JudgeInfrastructureError(
            "launch_executable_missing", f"launch executable does not exist: {executable}"
        )
    resolved = lexical.resolve(strict=True)
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        if normalized not in allowed_interpreters or not any(
            _is_relative_to(resolved, system_root.resolve())
            for system_root in (Path("/usr/bin"), Path("/usr/local/bin"))
            if system_root.exists()
        ):
            raise JudgeInfrastructureError(
                "launch_path_escape",
                "launch executable symlink escapes to an unapproved interpreter",
            ) from exc
    if not resolved.is_file() or not os.access(resolved, os.X_OK):
        raise JudgeInfrastructureError(
            "launch_executable_not_executable", f"launch executable is not executable: {executable}"
        )


def _minimal_etc_mounts() -> list[Path]:
    candidates = [
        Path("/etc/ld.so.cache"),
        Path("/etc/passwd"),
        Path("/etc/group"),
        Path("/etc/nsswitch.conf"),
        Path("/etc/ssl"),
        Path("/etc/ca-certificates"),
    ]
    return [path for path in candidates if path.exists()]


_COPY_IGNORED_NAMES = frozenset({".git", ".venv", "__pycache__", ".pytest_cache", ".ruff_cache"})


def _resolve_candidate_source(source_dir: Path) -> Path:
    try:
        source = Path(source_dir).resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise CandidateBuildError(
            "invalid_candidate_source",
            "candidate source does not resolve to an existing directory",
        ) from exc
    if not source.is_dir():
        raise CandidateBuildError(
            "invalid_candidate_source", "candidate source must be a directory"
        )
    return source


def _resolve_uv_executable(configured_path: Path | None) -> Path:
    raw_path: Path | str | None = (
        configured_path if configured_path is not None else shutil.which("uv")
    )
    if raw_path is None:
        raise CandidateBuildError(
            "uv_unavailable", "CleanCandidateBuilder requires an executable uv binary"
        )
    uv_path = Path(raw_path)
    if not uv_path.is_absolute():
        raise CandidateBuildError("uv_unavailable", "uv executable path must be absolute")
    try:
        uv_path = uv_path.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise CandidateBuildError(
            "uv_unavailable", "uv executable path cannot be resolved"
        ) from exc
    if not uv_path.is_file() or not os.access(uv_path, os.X_OK):
        raise CandidateBuildError(
            "uv_unavailable", "CleanCandidateBuilder requires an executable uv binary"
        )
    return uv_path


def _prepare_clean_source(
    source: Path,
    destination: Path,
    *,
    max_files: int,
    max_bytes: int,
) -> str:
    _copy_clean_source(source, destination, max_files=max_files, max_bytes=max_bytes)
    for required in ("pyproject.toml", "uv.lock"):
        path = destination / required
        try:
            is_regular = stat.S_ISREG(path.lstat().st_mode)
        except OSError:
            is_regular = False
        if not is_regular:
            raise CandidateBuildError(
                "missing_locked_project",
                f"candidate must contain a regular {required} file",
            )
    return _hash_tree(destination)


def _validate_and_hash_installed(root: Path) -> str:
    _validate_installed_tree(root)
    return _hash_tree(root)


def _source_file_view(root: Path) -> tuple[str, ...]:
    """Return every copied source file for an explicit read-only build view."""

    visible: list[str] = []
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix()
        observed = path.lstat()
        if stat.S_ISDIR(observed.st_mode):
            continue
        if not stat.S_ISREG(observed.st_mode) or path.is_symlink():
            raise CandidateBuildError(
                "candidate_source_view_rejected",
                f"candidate build view contains a non-regular entry: {relative}",
            )
        visible.append(relative)
    if not visible:
        raise CandidateBuildError("candidate_source_empty", "candidate source tree is empty")
    return tuple(visible)


def _validate_declared_source_tree(
    root: Path,
    files: tuple[PackageFile, ...],
    expected_digest: str,
) -> str:
    """Re-read manifest-declared bytes and bind them to the canonical source digest."""

    declared_digest = candidate_source_tree_digest(files)
    if declared_digest != expected_digest:
        raise CandidateBuildError(
            "candidate_source_manifest_digest",
            "declared candidate files do not match the expected source-tree digest",
        )
    for declared in files:
        path = root.joinpath(*PurePosixPath(declared.path).parts)
        try:
            observed = path.lstat()
        except OSError as exc:
            raise CandidateBuildError(
                "candidate_source_file_missing",
                f"manifest-declared source file is missing: {declared.path}",
            ) from exc
        if (
            path.is_symlink()
            or not stat.S_ISREG(observed.st_mode)
            or observed.st_nlink != 1
        ):
            raise CandidateBuildError(
                "candidate_source_file_unsafe",
                f"manifest-declared source is not an independent regular file: {declared.path}",
            )
        content = path.read_bytes()
        if (
            len(content) != declared.size_bytes
            or sha256_digest(content) != declared.content_hash
            or bool(observed.st_mode & 0o111) != declared.executable
        ):
            raise CandidateBuildError(
                "candidate_source_file_changed",
                f"manifest-declared source bytes or mode changed: {declared.path}",
                details={
                    "path": declared.path,
                    "expected_size_bytes": declared.size_bytes,
                    "observed_size_bytes": len(content),
                    "expected_content_hash": declared.content_hash,
                    "observed_content_hash": sha256_digest(content),
                    "expected_executable": declared.executable,
                    "observed_executable": bool(observed.st_mode & 0o111),
                },
            )
    return declared_digest


def _copy_clean_source(source: Path, destination: Path, *, max_files: int, max_bytes: int) -> None:
    file_count = 0
    byte_count = 0

    def copy_directory(source_dir: Path, destination_dir: Path) -> None:
        nonlocal file_count, byte_count
        for entry in sorted(os.scandir(source_dir), key=lambda item: item.name):
            if entry.name in _COPY_IGNORED_NAMES or entry.name.endswith((".pyc", ".pyo")):
                continue
            source_path = Path(entry.path)
            destination_path = destination_dir / entry.name
            if entry.is_symlink():
                raise CandidateBuildError(
                    "candidate_symlink_rejected",
                    f"candidate source contains symlink: {source_path.relative_to(source)}",
                )
            entry_stat = entry.stat(follow_symlinks=False)
            if stat.S_ISDIR(entry_stat.st_mode):
                destination_path.mkdir(mode=0o755)
                copy_directory(source_path, destination_path)
                continue
            if not stat.S_ISREG(entry_stat.st_mode):
                raise CandidateBuildError(
                    "candidate_special_file_rejected",
                    f"candidate source contains special file: {source_path.relative_to(source)}",
                )
            if entry_stat.st_nlink != 1:
                raise CandidateBuildError(
                    "candidate_hardlink_rejected",
                    "candidate source contains a hard-linked file: "
                    f"{source_path.relative_to(source)}",
                )
            file_count += 1
            byte_count += entry_stat.st_size
            if file_count > max_files or byte_count > max_bytes:
                raise CandidateBuildError(
                    "candidate_source_too_large",
                    "candidate source exceeds configured file or byte limit",
                    details={"files": file_count, "bytes": byte_count},
                )
            with (
                source_path.open("rb") as source_handle,
                destination_path.open("xb") as destination_handle,
            ):
                shutil.copyfileobj(source_handle, destination_handle, length=1024 * 1024)
            mode = 0o755 if entry_stat.st_mode & stat.S_IXUSR else 0o644
            os.chmod(destination_path, mode)

    copy_directory(source, destination)


def _validate_installed_tree(root: Path) -> None:
    for path in root.rglob("*"):
        relative = path.relative_to(root)
        path_stat = path.lstat()
        if stat.S_ISLNK(path_stat.st_mode):
            if not relative.parts or relative.parts[0] != ".venv":
                raise CandidateBuildError(
                    "installed_symlink_rejected",
                    f"install created symlink outside .venv: {relative}",
                )
            target = os.readlink(path)
            target_path = PurePosixPath(target)
            if target_path.is_absolute():
                if not _is_exact_pinned_python_link(path, root=root, target=target):
                    raise CandidateBuildError(
                        "installed_symlink_escape",
                        f"installed symlink escapes approved roots: {relative}",
                    )
                continue
            lexical_target = Path(os.path.normpath(path.parent / target))
            try:
                lexical_target.relative_to(root)
            except ValueError as exc:
                raise CandidateBuildError(
                    "installed_symlink_escape",
                    f"installed symlink escapes approved roots: {relative}",
                ) from exc
            if not (lexical_target.exists() or lexical_target.is_symlink()):
                raise CandidateBuildError(
                    "installed_symlink_dangling",
                    f"install created a dangling relative symlink: {relative}",
                )
        elif not (stat.S_ISDIR(path_stat.st_mode) or stat.S_ISREG(path_stat.st_mode)):
            raise CandidateBuildError(
                "installed_special_file_rejected", f"install created special file: {relative}"
            )


def _hash_tree(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix()
        path_stat = path.lstat()
        if stat.S_ISDIR(path_stat.st_mode):
            digest.update(f"D\0{relative}\0".encode())
            continue
        if stat.S_ISLNK(path_stat.st_mode):
            digest.update(f"L\0{relative}\0{os.readlink(path)}\0".encode())
            continue
        if not stat.S_ISREG(path_stat.st_mode):
            raise CandidateBuildError(
                "tree_hash_special_file", f"cannot hash special file: {relative}"
            )
        digest.update(
            f"F\0{relative}\0{path_stat.st_mode & 0o777:o}\0{path_stat.st_size}\0".encode()
        )
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        digest.update(b"\0")
    return digest.hexdigest()


def _is_exact_pinned_python_link(path: Path, *, root: Path, target: str) -> bool:
    """Accept only uv's interpreter links to the framework-owned sandbox Python."""

    try:
        relative = path.relative_to(root)
    except ValueError:
        return False
    return (
        relative.parent == Path(".venv/bin")
        and relative.name in {"python", "python3", _PRODUCTION_PYTHON.name}
        and target == _SANDBOX_PYTHON
    )


def _validate_pinned_venv_interpreter_link(path: Path, *, root: Path) -> None:
    """Validate a possibly chained uv interpreter link without resolving `/opt` on the host."""

    current = path
    seen: set[Path] = set()
    while current.is_symlink():
        if current in seen:
            raise JudgeInfrastructureError(
                "launch_symlink_cycle", "launch interpreter contains a symlink cycle"
            )
        seen.add(current)
        target = os.readlink(current)
        if PurePosixPath(target).is_absolute():
            if _is_exact_pinned_python_link(current, root=root, target=target):
                return
            raise JudgeInfrastructureError(
                "launch_path_escape",
                "launch interpreter does not target the framework-pinned sandbox Python",
            )
        current = Path(os.path.normpath(current.parent / target))
        try:
            current.relative_to(root)
        except ValueError as exc:
            raise JudgeInfrastructureError(
                "launch_path_escape", "launch interpreter symlink escapes the candidate root"
            ) from exc
    if not current.is_file() or not os.access(current, os.X_OK):
        raise JudgeInfrastructureError(
            "launch_executable_not_executable", "launch interpreter chain is not executable"
        )


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _decode_limited(value: bytes, limit: int) -> str:
    suffix = b"\n<truncated>" if len(value) > limit else b""
    return (value[:limit] + suffix).decode("utf-8", errors="replace")
