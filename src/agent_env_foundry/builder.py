"""Real Codex SDK Builder for one accepted S1 BuilderProjection."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

import rfc8785
from openai_codex import ApprovalMode, Codex, CodexConfig

from agent_env_foundry.errors import EnvironmentContractError
from agent_env_foundry.release import verify_release
from agent_env_foundry.research import BuilderProjection

__all__ = [
    "BuilderConfig",
    "BuilderFailure",
    "CandidateBuild",
    "CandidateRepairFinding",
    "CommandResult",
    "PreparedBuilderWorkspace",
    "candidate_files",
    "compute_candidate_digest",
    "prepare_builder_workspace",
    "repair_builder",
    "run_builder",
    "run_candidate_checks",
]

PROJECTION_NAME = "BUILDER_PROJECTION.json"
CONTRACT_NAME = "ENVIRONMENT_CONTRACT.md"
_CODEX_PROVIDER_ID = "foundry_runtime"
_EXCLUDED_PARTS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "dist",
}
_EXCLUDED_NAMES = {PROJECTION_NAME, CONTRACT_NAME}
_AMBIENT_PYTHON_ENV = ("VIRTUAL_ENV", "PYTHONPATH", "PYTHONHOME")
_CANDIDATE_REPAIR_FINDING_ORIGIN = object()
_CANDIDATE_REPAIR_CLAUSES = {
    "candidate_runtime_failed": "public_environment_runtime",
    "candidate_reload_failed": "factory_reattachment",
}


class BuilderFailure(RuntimeError):
    def __init__(self, phase: str, code: str, message: str, **details: Any) -> None:
        super().__init__(message)
        self.phase = phase
        self.code = code
        self.details = {"phase": phase, **details}


@dataclass(frozen=True)
class CandidateRepairFinding:
    failure_code: str
    contract_clause: str
    operation: str | None
    arguments: dict[str, Any] | None
    observation: Any
    runtime_error: str | None
    _origin: object = field(repr=False, compare=False)

    def to_document(self) -> dict[str, Any]:
        return {
            "failure_code": self.failure_code,
            "contract_clause": self.contract_clause,
            "operation": self.operation,
            "arguments": self.arguments,
            "observation": self.observation,
            "runtime_error": self.runtime_error,
        }


def _candidate_repair_finding(
    *,
    failure_code: str,
    contract_clause: str,
    operation: str | None = None,
    arguments: dict[str, Any] | None = None,
    observation: Any = None,
    runtime_error: str | None = None,
) -> CandidateRepairFinding:
    if _CANDIDATE_REPAIR_CLAUSES.get(failure_code) != contract_clause:
        raise BuilderFailure(
            "builder_repair",
            "candidate_repair_finding_invalid",
            "Candidate repair finding is not a closed Host-owned failure",
        )
    if operation is not None and (not isinstance(operation, str) or not operation):
        raise BuilderFailure(
            "builder_repair",
            "candidate_repair_finding_invalid",
            "Candidate repair operation must be non-empty",
        )
    safe_observation: Any = None
    if observation is not None:
        error = observation.get("error") if isinstance(observation, dict) else None
        code = error.get("code") if isinstance(error, dict) else None
        if (
            not isinstance(observation, dict)
            or observation.get("ok") is not False
            or observation.get("data") is not None
            or not isinstance(code, str)
            or not code
        ):
            raise BuilderFailure(
                "builder_repair",
                "candidate_repair_finding_invalid",
                "Candidate repair observation must be a canonical failed public call",
            )
        safe_observation = {"ok": False, "data": None, "error": {"code": code}}
    try:
        rfc8785.dumps({"arguments": arguments, "observation": safe_observation})
    except (TypeError, ValueError) as exc:
        raise BuilderFailure(
            "builder_repair",
            "candidate_repair_finding_invalid",
            "Candidate repair finding must contain only JSON facts",
        ) from exc
    if runtime_error is not None and (
        not isinstance(runtime_error, str)
        or not runtime_error
        or len(runtime_error) > 100
        or not runtime_error.replace("_", "").isalnum()
    ):
        raise BuilderFailure(
            "builder_repair",
            "candidate_repair_finding_invalid",
            "Candidate repair runtime error must be text",
        )
    return CandidateRepairFinding(
        failure_code,
        contract_clause,
        operation,
        arguments,
        safe_observation,
        runtime_error,
        _CANDIDATE_REPAIR_FINDING_ORIGIN,
    )


@dataclass(frozen=True)
class BuilderConfig:
    model: str = "gpt-5.6-luna"
    max_turns: int = 3
    uv_cache_dir: Path = Path("/tmp/agent-env-foundry-builder-uv-cache")
    command_timeout_seconds: float = 300.0

    def __post_init__(self) -> None:
        if self.max_turns <= 0:
            raise ValueError("max_turns must be positive")
        if self.command_timeout_seconds <= 0:
            raise ValueError("command_timeout_seconds must be positive")


@dataclass(frozen=True)
class CommandResult:
    phase: str
    command: tuple[str, ...]
    exit_code: int
    stdout: str
    stderr: str

    @property
    def passed(self) -> bool:
        return self.exit_code == 0

    def to_document(self) -> dict[str, Any]:
        return {
            "phase": self.phase,
            "command": list(self.command),
            "exit_code": self.exit_code,
            "stdout": self.stdout,
            "stderr": self.stderr,
        }


@dataclass(frozen=True)
class PreparedBuilderWorkspace:
    root: Path
    projection_digest: str
    contract_digest: str

    def verify_inputs(self) -> None:
        expected = {
            PROJECTION_NAME: self.projection_digest,
            CONTRACT_NAME: self.contract_digest,
        }
        for name, digest in expected.items():
            path = self.root / name
            actual = _file_digest(path) if path.is_file() and not path.is_symlink() else None
            if actual != digest:
                raise BuilderFailure(
                    "builder_input",
                    "builder_input_modified",
                    f"Builder input {name} changed after workspace preparation",
                    path=name,
                    expected_digest=digest,
                    actual_digest=actual,
                )


@dataclass(frozen=True)
class CandidateBuild:
    workspace: Path
    thread_id: str
    candidate_digest: str
    final_response: str
    checks: tuple[CommandResult, ...]
    codex_home: Path | None = None
    projection_digest: str | None = None
    contract_digest: str | None = None
    turns_used: int = 0
    revision: int = 1
    seen_digests: tuple[str, ...] = ()


def _file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _run(
    command: tuple[str, ...],
    *,
    cwd: Path,
    phase: str,
    config: BuilderConfig,
    extra_env: dict[str, str] | None = None,
) -> CommandResult:
    env = dict(os.environ)
    for ambient in _AMBIENT_PYTHON_ENV:
        env.pop(ambient, None)
    env["UV_CACHE_DIR"] = str(config.uv_cache_dir)
    if extra_env:
        env.update(extra_env)
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            env=env,
            text=True,
            capture_output=True,
            timeout=config.command_timeout_seconds,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return CommandResult(
            phase,
            command,
            124 if isinstance(exc, subprocess.TimeoutExpired) else 127,
            "",
            f"{type(exc).__name__}: {exc}",
        )
    return CommandResult(phase, command, result.returncode, result.stdout, result.stderr)


def prepare_builder_workspace(
    root: Path,
    projection: BuilderProjection,
    *,
    uv_cache_dir: Path,
) -> PreparedBuilderWorkspace:
    requested_workspace = Path(root)
    if requested_workspace.is_symlink():
        raise BuilderFailure("workspace", "workspace_symlink", "Builder workspace is a symlink")
    workspace = requested_workspace.resolve()
    if workspace.exists() and any(workspace.iterdir()):
        raise BuilderFailure(
            "workspace",
            "workspace_not_empty",
            "Builder workspace must be empty",
            path=str(workspace),
        )
    workspace.parent.mkdir(parents=True, exist_ok=True)
    resolved_uv_cache = Path(uv_cache_dir).resolve()
    resolved_uv_cache.mkdir(parents=True, exist_ok=True)
    config = BuilderConfig(uv_cache_dir=resolved_uv_cache)
    initialized = _run(
        (
            "uv",
            "init",
            "--package",
            "--no-workspace",
            "--vcs",
            "none",
            "--name",
            "generated-environment",
            "--python",
            "3.12",
            str(workspace),
        ),
        cwd=workspace.parent,
        phase="workspace_init",
        config=config,
    )
    if not initialized.passed:
        raise BuilderFailure(
            initialized.phase,
            "uv_init_failed",
            "uv init failed for the Builder workspace",
            command=initialized.to_document(),
        )

    placeholder = workspace / "src/generated_environment/__init__.py"
    if placeholder.exists():
        placeholder.unlink()

    projection_path = workspace / PROJECTION_NAME
    projection_path.write_bytes(rfc8785.dumps(projection.to_document()))
    contract_source = (
        Path(__file__).parent / "runtime_skills/environment-codegen/ENVIRONMENT_CONTRACT.md"
    )
    contract_path = workspace / CONTRACT_NAME
    shutil.copyfile(contract_source, contract_path)
    projection_path.chmod(0o444)
    contract_path.chmod(0o444)
    return PreparedBuilderWorkspace(
        root=workspace,
        projection_digest=_file_digest(projection_path),
        contract_digest=_file_digest(contract_path),
    )


def _candidate_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for path in root.rglob("*"):
        relative = path.relative_to(root)
        if any(part in _EXCLUDED_PARTS for part in relative.parts):
            continue
        if path.is_symlink():
            raise BuilderFailure(
                "candidate_identity",
                "candidate_symlink_forbidden",
                "Candidate identity does not accept symlinks",
                path=relative.as_posix(),
            )
        if not path.is_file():
            continue
        if path.name in _EXCLUDED_NAMES:
            continue
        files.append(path)
    return sorted(files, key=lambda item: item.relative_to(root).as_posix())


def candidate_files(root: Path) -> tuple[Path, ...]:
    """Return the exact project members bound by ``compute_candidate_digest``."""
    return tuple(_candidate_files(Path(root)))


def compute_candidate_digest(root: Path) -> str:
    records = []
    for path in _candidate_files(Path(root)):
        records.append(
            {
                "path": path.relative_to(root).as_posix(),
                "mode": stat.S_IMODE(path.stat().st_mode),
                "digest": _file_digest(path),
            }
        )
    return hashlib.sha256(rfc8785.dumps(cast(Any, {"files": records}))).hexdigest()


def run_candidate_checks(root: Path, config: BuilderConfig) -> tuple[CommandResult, ...]:
    tests_command = (str(root / ".venv" / "bin" / "python"), "-m", "pytest", "-q")
    commands: list[tuple[str, tuple[str, ...]]] = [
        ("lock", ("uv", "lock")),
        ("sync", ("uv", "sync", "--frozen", "--all-groups")),
        ("build", ("uv", "build")),
    ]
    results: list[CommandResult] = []
    for phase, command in commands:
        result = _run(command, cwd=root, phase=phase, config=config)
        results.append(result)
        if not result.passed:
            return tuple(results)
    if not (root / "tests").is_dir():
        results.append(CommandResult("tests", tests_command, 2, "", "tests missing"))
        return tuple(results)
    tests_result = _run(tests_command, cwd=root, phase="tests", config=config)
    results.append(tests_result)
    if not tests_result.passed:
        return tuple(results)
    release_result = _verify_release_contract(root)
    results.append(release_result)
    if not release_result.passed:
        return tuple(results)
    return (*results, _smoke_environment_load(root, config))


def _verify_release_contract(root: Path) -> CommandResult:
    """Loader-contract check on the candidate's own release.json/manifest bytes."""
    command = ("verify_release", str(root))
    try:
        verify_release(root)
    except EnvironmentContractError as exc:
        return CommandResult("release_contract", command, 1, "", str(exc))
    return CommandResult("release_contract", command, 0, "", "")


def _smoke_environment_load(root: Path, config: BuilderConfig) -> CommandResult:
    candidate_python = root / ".venv/bin/python"
    host_source = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(
        prefix="agent-env-foundry-loader-deps-",
        dir=root.parent,
    ) as temporary:
        dependencies = Path(temporary) / "site"
        install = _run(
            (
                "uv",
                "pip",
                "install",
                "--python",
                str(candidate_python),
                "--target",
                str(dependencies),
                "rfc8785",
                "jsonschema",
            ),
            cwd=root.parent,
            phase="environment_load",
            config=config,
        )
        if not install.passed:
            return install
        return _run(
            (str(candidate_python), "-m", "agent_env_foundry._smoke", str(root.resolve())),
            cwd=root.parent,
            phase="environment_load",
            config=config,
            extra_env={"PYTHONPATH": os.pathsep.join((str(host_source), str(dependencies)))},
        )


def _feedback(checks: tuple[CommandResult, ...]) -> str:
    failed = [item.to_document() for item in checks if not item.passed]
    return (
        "The deterministic host checks rejected the current candidate. Repair the same "
        "workspace without editing BUILDER_PROJECTION.json or ENVIRONMENT_CONTRACT.md. "
        "Complete factual failures:\n" + json.dumps(failed, ensure_ascii=False, sort_keys=True)
    )


def _codex_provider_overrides() -> tuple[str, ...]:
    base_url = os.environ.get("OPENAI_BASE_URL", "").strip().rstrip("/")
    if not base_url:
        raise BuilderFailure(
            "builder_provider",
            "provider_base_url_missing",
            "Builder requires an explicit OPENAI_BASE_URL for its clean Codex runtime",
            env_var="OPENAI_BASE_URL",
        )
    if not os.environ.get("OPENAI_API_KEY"):
        raise BuilderFailure(
            "builder_provider",
            "provider_api_key_missing",
            "Builder requires OPENAI_API_KEY for its configured Codex provider",
            env_var="OPENAI_API_KEY",
        )
    provider = _CODEX_PROVIDER_ID
    return (
        f'model_provider="{provider}"',
        f'model_providers.{provider}.name="Foundry runtime"',
        f"model_providers.{provider}.base_url={json.dumps(base_url)}",
        f'model_providers.{provider}.env_key="OPENAI_API_KEY"',
        f'model_providers.{provider}.wire_api="responses"',
        f"model_providers.{provider}.supports_websockets=true",
        "project_root_markers=[]",
        "features.plugins=false",
        "features.multi_agent=false",
        "features.skill_search=false",
    )


def _isolated_codex_env(codex_home: str | Path, uv_cache_dir: Path) -> dict[str, str]:
    """Keep product Codex roles outside the developer's HOME-scoped guidance."""
    home = Path(codex_home)
    execution_home = home / "home"
    if execution_home.is_symlink() or (execution_home.exists() and not execution_home.is_dir()):
        raise BuilderFailure(
            "builder",
            "codex_execution_home_invalid",
            "Product Codex execution HOME must be a real directory",
            path=str(execution_home),
        )
    execution_home.mkdir(exist_ok=True)
    return {
        "CODEX_HOME": str(home),
        "HOME": str(execution_home),
        "UV_CACHE_DIR": str(uv_cache_dir),
    }


def _builder_skill() -> str:
    return (Path(__file__).parent / "runtime_skills/environment-codegen/SKILL.md").read_text(
        encoding="utf-8"
    )


def _builder_codex_config(
    root: Path,
    codex_home: Path,
    config: BuilderConfig,
) -> CodexConfig:
    return CodexConfig(
        cwd=str(root),
        env=_isolated_codex_env(codex_home, config.uv_cache_dir),
        config_overrides=(
            *_codex_provider_overrides(),
            *_codex_workspace_permission_overrides("foundry_builder", root),
        ),
    )


def _codex_workspace_permission_overrides(profile: str, root: Path) -> tuple[str, ...]:
    if not profile.replace("_", "").isalnum():
        raise ValueError("Codex permission profile name is invalid")
    workspace = Path(root).resolve()
    parent = workspace.parent
    filesystem = (
        "{"
        + ",".join(
            (
                f'{json.dumps(str(parent))}="deny"',
                f'{json.dumps(str(workspace))}="write"',
            )
        )
        + "}"
    )
    return (
        f'default_permissions="{profile}"',
        f'permissions.{profile}.extends=":workspace"',
        f"permissions.{profile}.filesystem={filesystem}",
        f"permissions.{profile}.network.enabled=true",
    )


def _require_fresh_builder_codex_home(path: Path) -> None:
    if path.is_symlink() or path.exists():
        raise BuilderFailure(
            "builder",
            "builder_codex_home_not_fresh",
            "Builder Codex home must be absent before a new lineage",
            path=str(path),
        )
    path.mkdir()


def _drive_builder_thread(
    prepared: PreparedBuilderWorkspace,
    thread: Any,
    codex_home: Path,
    config: BuilderConfig,
    prompt: str,
    *,
    turns_used: int,
    revision: int,
    seen_digests: tuple[str, ...],
) -> CandidateBuild:
    remaining = config.max_turns - turns_used
    if remaining <= 0:
        raise BuilderFailure(
            "builder",
            "builder_turns_exhausted",
            "Builder lineage exhausted its total turn budget",
            turns_used=turns_used,
            max_turns=config.max_turns,
        )
    observed = list(seen_digests)
    previous_digest = observed[-1] if observed else None
    last_response = ""
    last_checks: tuple[CommandResult, ...] = ()
    for _ in range(remaining):
        try:
            result = thread.run(prompt)
        except Exception as exc:
            raise BuilderFailure(
                "infrastructure",
                "builder_provider_turn_failed",
                "Builder provider turn failed",
                original_code=type(exc).__name__,
                original_message=str(exc),
            ) from exc
        turns_used += 1
        last_response = result.final_response or ""
        prepared.verify_inputs()
        last_checks = run_candidate_checks(prepared.root, config)
        digest = compute_candidate_digest(prepared.root)
        if digest in observed:
            code = "builder_stalled" if digest == previous_digest else "builder_revision_cycle"
            failure_phase = next(
                (item.phase for item in last_checks if not item.passed),
                "builder",
            )
            raise BuilderFailure(
                failure_phase,
                code,
                "Builder produced no new candidate revision after factual feedback",
                candidate_digest=digest,
                seen_digests=observed,
            )
        observed.append(digest)
        if last_checks and all(item.passed for item in last_checks):
            return CandidateBuild(
                prepared.root,
                thread.id,
                digest,
                last_response,
                last_checks,
                codex_home,
                prepared.projection_digest,
                prepared.contract_digest,
                turns_used,
                revision,
                tuple(observed),
            )
        previous_digest = digest
        prompt = _feedback(last_checks)
    raise BuilderFailure(
        "builder",
        "builder_turns_exhausted",
        "Builder lineage exhausted its total turn budget",
        turns_used=turns_used,
        max_turns=config.max_turns,
        final_response=last_response,
        checks=[item.to_document() for item in last_checks],
    )


def _qualification_feedback(build: CandidateBuild, finding: CandidateRepairFinding) -> str:
    return (
        "ACTOR QUALIFICATION REJECTED\n"
        "Repair the general environment implementation and its diagnostic tests in the same "
        "workspace. Preserve BUILDER_PROJECTION.json and ENVIRONMENT_CONTRACT.md. Do not "
        "special-case one observed value; fresh Qualification will rerun all Requirements, "
        "starts, instances, negatives, and cold checks.\n"
        "REJECTED_CANDIDATE_DIGEST\n"
        f"{build.candidate_digest}\n"
        "SAFE_HOST_FINDING\n"
        + json.dumps(finding.to_document(), ensure_ascii=False, sort_keys=True)
    )


def run_builder(
    projection: BuilderProjection,
    root: Path,
    *,
    config: BuilderConfig | None = None,
) -> CandidateBuild:
    selected = config or BuilderConfig()
    prepared = prepare_builder_workspace(
        root,
        projection,
        uv_cache_dir=selected.uv_cache_dir,
    )
    prompt = (
        "Build the complete environment project described by BUILDER_PROJECTION.json and "
        "ENVIRONMENT_CONTRACT.md. Own all implementation decisions. Run and repair the "
        "project's real uv commands and diagnostic tests before reporting completion."
    )
    codex_home = prepared.root.parent / f"{prepared.root.name}-codex-home"
    _require_fresh_builder_codex_home(codex_home)
    with Codex(_builder_codex_config(prepared.root, codex_home, selected)) as codex:
        thread = codex.thread_start(
            approval_mode=ApprovalMode.deny_all,
            base_instructions=_builder_skill(),
            cwd=str(prepared.root),
            model=selected.model,
        )
        return _drive_builder_thread(
            prepared,
            thread,
            codex_home,
            selected,
            prompt,
            turns_used=0,
            revision=1,
            seen_digests=(),
        )


def repair_builder(
    build: CandidateBuild,
    finding: CandidateRepairFinding,
    *,
    failed_candidate_digest: str,
    config: BuilderConfig,
) -> CandidateBuild:
    """Resume the exact Builder thread after a Host-owned Candidate finding."""
    if finding._origin is not _CANDIDATE_REPAIR_FINDING_ORIGIN:
        raise BuilderFailure(
            "builder_repair",
            "candidate_repair_finding_invalid",
            "Builder repair requires a Host-origin finding",
        )
    if failed_candidate_digest != build.candidate_digest:
        raise BuilderFailure(
            "builder_repair",
            "candidate_repair_digest_mismatch",
            "Qualification failure binds a different Candidate revision",
            build_digest=build.candidate_digest,
            failed_digest=failed_candidate_digest,
        )
    if compute_candidate_digest(build.workspace) != build.candidate_digest:
        raise BuilderFailure(
            "builder_repair",
            "candidate_changed_before_repair",
            "Candidate workspace changed outside the Builder lineage",
        )
    if (
        build.codex_home is None
        or build.projection_digest is None
        or build.contract_digest is None
        or build.codex_home.is_symlink()
        or not build.codex_home.is_dir()
    ):
        raise BuilderFailure(
            "builder_repair",
            "builder_resume_invalid",
            "Builder resume identity is unavailable",
        )
    prepared = PreparedBuilderWorkspace(
        build.workspace,
        build.projection_digest,
        build.contract_digest,
    )
    prepared.verify_inputs()
    if build.turns_used >= config.max_turns:
        raise BuilderFailure(
            "builder",
            "builder_turns_exhausted",
            "Builder lineage exhausted its total turn budget",
            turns_used=build.turns_used,
            max_turns=config.max_turns,
        )
    try:
        with Codex(_builder_codex_config(build.workspace, build.codex_home, config)) as codex:
            thread = codex.thread_resume(
                build.thread_id,
                approval_mode=ApprovalMode.deny_all,
                base_instructions=_builder_skill(),
                cwd=str(build.workspace),
                model=config.model,
            )
            if thread.id != build.thread_id:
                raise BuilderFailure(
                    "builder_repair",
                    "builder_resume_invalid",
                    "Resumed Builder thread identity changed",
                )
            return _drive_builder_thread(
                prepared,
                thread,
                build.codex_home,
                config,
                _qualification_feedback(build, finding),
                turns_used=build.turns_used,
                revision=build.revision + 1,
                seen_digests=build.seen_digests or (build.candidate_digest,),
            )
    except BuilderFailure:
        raise
    except Exception as exc:
        raise BuilderFailure(
            "infrastructure",
            "builder_resume_failed",
            "Builder thread could not be resumed",
            original_code=type(exc).__name__,
            original_message=str(exc),
        ) from exc
