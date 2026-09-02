"""Real Codex SDK Builder for one accepted S1 BuilderProjection."""

from __future__ import annotations

import ast
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import rfc8785
from openai_codex import ApprovalMode, Codex, CodexConfig, Sandbox

from agent_env_foundry.diagnostic_scenarios import DIAGNOSTIC_SCENARIOS_PATH
from agent_env_foundry.physical_runtime import (
    PreparationSettings,
)
from agent_env_foundry.project_identity import (
    ProjectIdentityError,
    compute_authored_project_digest,
    project_files,
)
from agent_env_foundry.research import BuilderProjection
from agent_env_foundry.schema import SchemaError, require_object_root, validate_schema_document

__all__ = [
    "ACTOR_FACTORY",
    "BuilderConfig",
    "BuilderFailure",
    "CandidateBuild",
    "CommandResult",
    "DIAGNOSTIC_SCENARIOS_PATH",
    "PreparedBuilderWorkspace",
    "RESET_OBSERVATION_SCHEMA_PATH",
    "STATE_READER_FACTORY",
    "STATE_SCHEMA_PATH",
    "START_SCHEMA_PATH",
    "candidate_files",
    "compute_candidate_digest",
    "prepare_builder_workspace",
    "run_builder",
    "run_candidate_checks",
]

PROJECTION_NAME = "BUILDER_PROJECTION.json"
CONTRACT_NAME = "ENVIRONMENT_CONTRACT.md"
ACTOR_FACTORY = "generated_environment.release:make_environment"
STATE_READER_FACTORY = "generated_environment.release:read_state"
START_SCHEMA_PATH = Path("docs/schemas/start.json")
RESET_OBSERVATION_SCHEMA_PATH = Path("docs/schemas/reset.json")
STATE_SCHEMA_PATH = Path("docs/schemas/state.json")
_CODEX_PROVIDER_ID = "foundry_runtime"
_AMBIENT_PYTHON_ENV = ("VIRTUAL_ENV", "PYTHONPATH", "PYTHONHOME")
_BUILDER_PREFLIGHT_PHASES = (
    "lock",
    "sync",
    "build",
    "tests",
    "public_contract",
    "source_determinism",
)
_AMBIENT_ENTROPY_CALLS = frozenset(
    {
        "datetime.date.today",
        "datetime.datetime.now",
        "datetime.datetime.today",
        "datetime.datetime.utcnow",
        "os.urandom",
        "random.choice",
        "random.choices",
        "random.getrandbits",
        "random.randint",
        "random.random",
        "random.randrange",
        "random.shuffle",
        "random.uniform",
        "secrets.choice",
        "secrets.randbelow",
        "secrets.token_bytes",
        "secrets.token_hex",
        "secrets.token_urlsafe",
        "time.time",
        "time.time_ns",
        "uuid.uuid1",
        "uuid.uuid4",
    }
)


class BuilderFailure(RuntimeError):
    def __init__(self, phase: str, code: str, message: str, **details: Any) -> None:
        super().__init__(message)
        self.phase = phase
        self.code = code
        self.details = {"phase": phase, **details}


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


def _file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _run(
    command: tuple[str, ...],
    *,
    cwd: Path,
    phase: str,
    config: BuilderConfig,
    extra_env: dict[str, str] | None = None,
    input_text: str | None = None,
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
            input=input_text,
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
    try:
        return list(project_files(root, "actor"))
    except ProjectIdentityError as exc:
        code = (
            "candidate_symlink_forbidden" if exc.code == "project_symlink_forbidden" else exc.code
        )
        raise BuilderFailure(
            "candidate_identity",
            code,
            str(exc),
            path=exc.path,
        ) from exc


def candidate_files(root: Path) -> tuple[Path, ...]:
    """Return the exact project members bound by ``compute_candidate_digest``."""
    return tuple(_candidate_files(Path(root)))


def compute_candidate_digest(root: Path) -> str:
    try:
        return compute_authored_project_digest(Path(root), "actor")
    except ProjectIdentityError as exc:
        code = (
            "candidate_symlink_forbidden" if exc.code == "project_symlink_forbidden" else exc.code
        )
        raise BuilderFailure(
            "candidate_identity",
            code,
            str(exc),
            path=exc.path,
        ) from exc


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
    results.append(_public_contract_check(root))
    if not results[-1].passed:
        return tuple(results)
    results.append(_source_determinism_check(root))
    if not results[-1].passed:
        return tuple(results)
    results.append(_live_actor_contract_check(root, config, tuple(results)))
    return tuple(results)


def _public_contract_check(root: Path) -> CommandResult:
    failures: list[dict[str, str]] = []
    for relative, object_root_required in (
        (START_SCHEMA_PATH, True),
        (RESET_OBSERVATION_SCHEMA_PATH, False),
        (STATE_SCHEMA_PATH, False),
    ):
        path = root / relative
        if path.is_symlink() or not path.is_file():
            failures.append(
                {
                    "path": relative.as_posix(),
                    "reason": "missing_regular_file",
                }
            )
            continue
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
            if object_root_required:
                require_object_root(document, role=relative.as_posix())
            else:
                validate_schema_document(document, role=relative.as_posix())
        except (OSError, json.JSONDecodeError, SchemaError) as exc:
            failures.append(
                {
                    "path": relative.as_posix(),
                    "reason": f"{type(exc).__name__}: {exc}",
                }
            )
    diagnostic_path = root / DIAGNOSTIC_SCENARIOS_PATH
    if diagnostic_path.is_symlink() or not diagnostic_path.is_file():
        failures.append(
            {
                "path": DIAGNOSTIC_SCENARIOS_PATH.as_posix(),
                "reason": "missing_regular_file",
            }
        )
    else:
        try:
            diagnostic_document = json.loads(diagnostic_path.read_text(encoding="utf-8"))
            if not isinstance(diagnostic_document, dict):
                raise ValueError("diagnostic document must be a JSON object")
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            failures.append(
                {
                    "path": DIAGNOSTIC_SCENARIOS_PATH.as_posix(),
                    "reason": f"{type(exc).__name__}: {exc}",
                }
            )
    return CommandResult(
        "public_contract",
        ("host", "validate-public-contract"),
        1 if failures else 0,
        "" if failures else "public contract passed",
        json.dumps(failures, ensure_ascii=False, sort_keys=True) if failures else "",
    )


def _source_determinism_check(root: Path) -> CommandResult:
    """Reject ambient entropy that cannot be replayed from release state."""

    failures: list[dict[str, Any]] = []
    for path in sorted((root / "src").rglob("*.py")):
        relative = path.relative_to(root).as_posix()
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative)
        except (OSError, SyntaxError) as exc:
            failures.append(
                {
                    "path": relative,
                    "line": getattr(exc, "lineno", None),
                    "call": "invalid_python_source",
                    "message": str(exc),
                }
            )
            continue
        bindings: dict[str, str] = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    local = alias.asname or alias.name.partition(".")[0]
                    bindings[local] = alias.name if alias.asname else local
            elif isinstance(node, ast.ImportFrom) and node.module:
                for alias in node.names:
                    if alias.name != "*":
                        bindings[alias.asname or alias.name] = f"{node.module}.{alias.name}"
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            reference = _call_reference(node.func, bindings)
            unseeded_random = reference == "random.Random" and not node.args and not node.keywords
            if reference not in _AMBIENT_ENTROPY_CALLS and not unseeded_random:
                continue
            failures.append(
                {
                    "path": relative,
                    "line": node.lineno,
                    "call": reference,
                    "message": (
                        "actor state and observations must derive time/IDs/randomness from "
                        "resettable instance state"
                    ),
                }
            )
    return CommandResult(
        "source_determinism",
        ("host", "scan-actor-determinism"),
        1 if failures else 0,
        "" if failures else "actor source contains no ambient entropy calls",
        json.dumps(failures, ensure_ascii=False, sort_keys=True) if failures else "",
    )


def _call_reference(node: ast.expr, bindings: dict[str, str]) -> str:
    parts: list[str] = []
    current = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if not isinstance(current, ast.Name):
        return ""
    root = bindings.get(current.id, current.id)
    return ".".join((root, *reversed(parts)))


def _live_actor_contract_check(
    root: Path,
    config: BuilderConfig,
    prior_checks: tuple[CommandResult, ...] | None = None,
) -> CommandResult:
    """Run complete task-neutral conformance while Codex can still repair."""

    try:
        digest = compute_candidate_digest(root)
        checks = prior_checks or tuple(
            CommandResult(phase, ("host", f"preflight-{phase}"), 0, "passed", "")
            for phase in _BUILDER_PREFLIGHT_PHASES
        )
        placeholder = CommandResult(
            "live_contract",
            ("host", "validate-live-actor-contract"),
            0,
            "preflight placeholder",
            "",
        )
        candidate = CandidateBuild(
            root,
            "builder-live-preflight",
            digest,
            "",
            (*checks, placeholder),
        )
        from agent_env_foundry.environment_conformance_v3 import (
            run_environment_conformance_v3_internal,
        )

        conformed = run_environment_conformance_v3_internal(
            candidate,
            root.parent / ".builder-conformance-runtimes" / digest,
            settings=PreparationSettings(
                config.uv_cache_dir,
                config.command_timeout_seconds,
            ),
        )
    except Exception as exc:
        details = getattr(exc, "details", {})
        failure = {
            "error_type": type(exc).__name__,
            "code": getattr(exc, "code", "live_actor_contract_failed"),
            "message": str(exc),
            "details": details if isinstance(details, dict) else {"value": details},
        }
        return CommandResult(
            "live_contract",
            ("host", "validate-live-actor-contract"),
            1,
            "",
            json.dumps(failure, ensure_ascii=False, sort_keys=True, default=str),
        )
    return CommandResult(
        "live_contract",
        ("host", "validate-live-actor-contract"),
        0,
        json.dumps(
            {"tool_names": [item["name"] for item in conformed.tool_specs]},
            ensure_ascii=False,
            sort_keys=True,
        ),
        "",
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
    skill = (Path(__file__).parent / "runtime_skills/environment-codegen/SKILL.md").read_text(
        encoding="utf-8"
    )
    previous_failed_digest: str | None = None
    prompt = (
        "Build the complete environment project described by BUILDER_PROJECTION.json and "
        "ENVIRONMENT_CONTRACT.md. Own all implementation decisions. Run and repair the "
        "project's real uv commands and diagnostic tests before reporting completion."
    )
    provider_overrides = _codex_provider_overrides()
    with tempfile.TemporaryDirectory(
        dir=prepared.root.parent,
        prefix="agent-env-foundry-codex-home-",
        ignore_cleanup_errors=True,
    ) as codex_home:
        sdk_env = _isolated_codex_env(codex_home, selected.uv_cache_dir)
        with Codex(
            CodexConfig(
                cwd=str(prepared.root),
                env=sdk_env,
                config_overrides=provider_overrides,
            )
        ) as codex:
            thread = codex.thread_start(
                approval_mode=ApprovalMode.deny_all,
                base_instructions=skill,
                cwd=str(prepared.root),
                model=selected.model,
                sandbox=Sandbox.full_access,
            )
            last_response = ""
            last_checks: tuple[CommandResult, ...] = ()
            for _turn in range(selected.max_turns):
                result = thread.run(prompt)
                last_response = result.final_response or ""
                prepared.verify_inputs()
                last_checks = run_candidate_checks(prepared.root, selected)
                digest = compute_candidate_digest(prepared.root)
                if last_checks and all(item.passed for item in last_checks):
                    return CandidateBuild(
                        prepared.root,
                        thread.id,
                        digest,
                        last_response,
                        last_checks,
                    )
                if previous_failed_digest == digest:
                    failed = next(item for item in last_checks if not item.passed)
                    raise BuilderFailure(
                        failed.phase,
                        "builder_stalled",
                        "Builder produced no byte change after factual failure feedback",
                        candidate_digest=digest,
                        failure=failed.to_document(),
                    )
                previous_failed_digest = digest
                prompt = _feedback(last_checks)
    raise BuilderFailure(
        "builder",
        "builder_turns_exhausted",
        "Builder exhausted its repair turns without passing deterministic checks",
        final_response=last_response,
        checks=[item.to_document() for item in last_checks],
    )
