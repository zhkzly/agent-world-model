"""Codex-authored audit-only Qualification Verifier with Host-owned checks."""

from __future__ import annotations

import ast
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from openai_codex import ApprovalMode, Codex, CodexConfig, Sandbox

from agent_env_foundry.author_finding import AuthorFinding
from agent_env_foundry.builder import (
    ACTOR_FACTORY,
    BuilderConfig,
    CommandResult,
    _codex_provider_overrides,
    _isolated_codex_env,
    _run,
)
from agent_env_foundry.preparation import _probe_origin
from agent_env_foundry.project_identity import (
    ProjectIdentityError,
    compute_authored_project_digest,
    project_files,
)
from agent_env_foundry.qualification_contracts import (
    NativeVerificationRequest,
    NativeVerificationResult,
    native_verification_result_from_document,
)
from agent_env_foundry.tree_manifest import tree_manifest
from agent_env_foundry.verifier_inputs import (
    ACTOR_VIEW_NAME,
    PreparedVerifierAuthorWorkspace,
)

VERIFIER_FACTORY = "generated_qualification_verifier.release:make_verifier"
_PROHIBITED_OUTPUT_TOKENS = frozenset({"digest", "evidence", "manifest", "receipt", "verdict"})


class VerifierAuthorFailure(RuntimeError):
    def __init__(self, phase: str, code: str, message: str, **details: Any) -> None:
        super().__init__(message)
        self.phase = phase
        self.code = code
        self.details = {"phase": phase, **details}


@dataclass(frozen=True)
class VerifierBuild:
    root: Path
    thread_id: str
    codex_home: Path
    factory: str
    project_digest: str
    checks: tuple[CommandResult, ...]


VerifierAuthorFinding = AuthorFinding


def run_verifier_author(
    prepared: PreparedVerifierAuthorWorkspace,
    *,
    config: BuilderConfig | None = None,
) -> VerifierBuild:
    """Let Codex author verifier bytes; Host checks and identities decide acceptance."""

    selected = config or BuilderConfig(
        uv_cache_dir=Path("/tmp/agent-env-foundry-verifier-author-uv-cache")
    )
    prepared.verify_inputs()
    _initialize_project(prepared.root, selected)
    skill = (
        Path(__file__).parent / "runtime_skills/qualification-verifier-codegen/SKILL.md"
    ).read_text(encoding="utf-8")
    prompt = (
        "Write the standalone Qualification Verifier project described by the immutable "
        "Host inputs. Implement independent native before/after evaluation in the fixed "
        "generated_qualification_verifier.release:make_verifier factory. Framework checks "
        "decide acceptance."
    )
    codex_home = prepared.root.parent / "verifier-codex-home"
    _require_fresh_codex_home(codex_home)
    with Codex(_codex_config(prepared.root, codex_home, selected)) as codex:
        thread = codex.thread_start(
            approval_mode=ApprovalMode.deny_all,
            base_instructions=skill,
            cwd=str(prepared.root),
            model=selected.model,
            sandbox=Sandbox.full_access,
        )
        return _drive_verifier_thread(
            prepared,
            thread,
            codex_home,
            selected,
            prompt,
            previous_failed_digest=None,
        )


def repair_verifier_author(
    prepared: PreparedVerifierAuthorWorkspace,
    build: VerifierBuild,
    findings: tuple[AuthorFinding, ...],
    *,
    config: BuilderConfig,
) -> VerifierBuild:
    """Resume the same verifier thread with Host-owned factual findings only."""

    prepared.verify_inputs()
    if (
        build.root.resolve() != prepared.root.resolve()
        or build.factory != VERIFIER_FACTORY
        or not build.thread_id
        or build.codex_home.is_symlink()
        or not build.codex_home.is_dir()
        or not findings
        or any(not isinstance(item, AuthorFinding) for item in findings)
        or len({item.code for item in findings}) != len(findings)
    ):
        raise VerifierAuthorFailure(
            "verifier_repair",
            "verifier_repair_identity_mismatch",
            "Verifier repair build does not belong to this workspace",
        )
    actual_digest = compute_verifier_project_digest(prepared.root)
    if actual_digest != build.project_digest:
        raise VerifierAuthorFailure(
            "verifier_repair",
            "verifier_repair_digest_mismatch",
            "Verifier project bytes changed before factual repair",
            expected=build.project_digest,
            actual=actual_digest,
        )
    prompt = (
        "The deterministic Framework rejected the verifier project. Repair verifier "
        "source/dependencies/tests only and fix every factual finding:\n"
        + json.dumps(
            [item.to_document() for item in findings],
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    with Codex(_codex_config(prepared.root, build.codex_home, config)) as codex:
        thread = codex.thread_resume(build.thread_id)
        if thread is None:
            raise VerifierAuthorFailure(
                "verifier_repair",
                "verifier_thread_missing",
                "Verifier Author thread cannot be resumed",
            )
        return _drive_verifier_thread(
            prepared,
            thread,
            build.codex_home,
            config,
            prompt,
            previous_failed_digest=build.project_digest,
        )


def _drive_verifier_thread(
    prepared: PreparedVerifierAuthorWorkspace,
    thread: Any,
    codex_home: Path,
    config: BuilderConfig,
    prompt: str,
    *,
    previous_failed_digest: str | None,
) -> VerifierBuild:
    last_checks: tuple[CommandResult, ...] = ()
    for turn_index in range(config.max_turns):
        try:
            thread.run(prompt)
        except Exception as exc:
            if turn_index + 1 == config.max_turns:
                raise VerifierAuthorFailure(
                    "infrastructure",
                    "verifier_provider_turn_failed",
                    "Verifier Author provider turn failed",
                    original_code=type(exc).__name__,
                    original_message=str(exc),
                ) from exc
            continue
        prepared.verify_inputs()
        last_checks = run_verifier_checks(prepared, config)
        digest = compute_verifier_project_digest(prepared.root)
        if last_checks and all(check.passed for check in last_checks):
            return VerifierBuild(
                prepared.root,
                thread.id,
                codex_home,
                VERIFIER_FACTORY,
                digest,
                last_checks,
            )
        if previous_failed_digest == digest:
            raise VerifierAuthorFailure(
                "verifier_author",
                "verifier_author_stalled",
                "Verifier Author changed no project bytes after factual feedback",
                project_digest=digest,
                failures=[check.to_document() for check in last_checks if not check.passed],
            )
        previous_failed_digest = digest
        prompt = _feedback(last_checks)
    raise VerifierAuthorFailure(
        "verifier_author",
        "verifier_author_turns_exhausted",
        "Verifier Author exhausted its bounded repair turns",
        failures=[check.to_document() for check in last_checks if not check.passed],
    )


def run_verifier_checks(
    prepared: PreparedVerifierAuthorWorkspace,
    config: BuilderConfig,
) -> tuple[CommandResult, ...]:
    prepared.verify_inputs()
    source_check = _source_check(prepared.root)
    if not source_check.passed:
        return (source_check,)
    results: list[CommandResult] = [source_check]
    for phase, command in (
        ("lock", ("uv", "lock")),
        ("sync", ("uv", "sync", "--frozen", "--all-groups", "--link-mode", "copy")),
    ):
        result = _run(command, cwd=prepared.root, phase=phase, config=config)
        results.append(result)
        if not result.passed:
            return tuple(results)
    import_check = _import_separation_check(prepared, config)
    results.append(import_check)
    if not import_check.passed:
        return tuple(results)
    build = _run(("uv", "build"), cwd=prepared.root, phase="build", config=config)
    results.append(build)
    if not build.passed:
        return tuple(results)
    tests = prepared.root / "tests"
    test_command = (str(prepared.root / ".venv/bin/python"), "-m", "pytest", "-q")
    if not tests.is_dir():
        results.append(CommandResult("tests", test_command, 2, "", "tests missing"))
        return tuple(results)
    tested = _run(test_command, cwd=prepared.root, phase="tests", config=config)
    results.append(tested)
    if not tested.passed:
        return tuple(results)
    factory = _factory_check(prepared, config)
    results.append(factory)
    if not factory.passed:
        return tuple(results)
    results.append(_source_check(prepared.root, phase="post_source_contract"))
    prepared.verify_inputs()
    return tuple(results)


def invoke_verifier_transition(
    root: Path,
    request: NativeVerificationRequest,
    *,
    expected_verifier_project_digest: str,
    config: BuilderConfig,
) -> NativeVerificationResult:
    """Run one typed verifier call and prove both native trees stayed unchanged."""

    verifier_path = Path(root)
    if verifier_path.is_symlink():
        raise VerifierAuthorFailure(
            "verifier_transition",
            "verifier_project_symlink",
            "Qualification Verifier project root must not be a symlink",
        )
    verifier_root = verifier_path.resolve()
    actual_verifier_digest = compute_verifier_project_digest(verifier_root)
    if actual_verifier_digest != expected_verifier_project_digest:
        raise VerifierAuthorFailure(
            "verifier_transition",
            "verifier_project_digest_mismatch",
            "Qualification Verifier project differs from the accepted project identity",
            expected=expected_verifier_project_digest,
            actual=actual_verifier_digest,
        )
    verifier_manifest = tree_manifest(verifier_root)
    before_root = request.before_instance_directory.resolve()
    after_root = request.after_instance_directory.resolve()
    if before_root == after_root:
        raise VerifierAuthorFailure(
            "verifier_transition",
            "verifier_instance_alias",
            "Native before/after paths resolve to the same instance directory",
        )
    before_manifest = tree_manifest(before_root)
    after_manifest = tree_manifest(after_root)
    document = request.to_document()
    document["before_instance_directory"] = str(before_root)
    document["after_instance_directory"] = str(after_root)
    script = (
        "import json,sys;"
        "from generated_qualification_verifier.release import make_verifier;"
        "request=json.load(sys.stdin);"
        "json.dump(make_verifier().verify_transition(request),sys.stdout,sort_keys=True)"
    )
    executed = _run(
        (
            str(verifier_root / ".venv/bin/python"),
            "-I",
            "-B",
            "-c",
            script,
        ),
        cwd=verifier_root,
        phase="verifier_transition",
        config=config,
        input_text=json.dumps(document, ensure_ascii=False, sort_keys=True),
    )
    changed = {
        role: {"before": expected, "after": actual}
        for role, expected, actual in (
            ("verifier_project", verifier_manifest.digest, tree_manifest(verifier_root).digest),
            ("before_instance", before_manifest.digest, tree_manifest(before_root).digest),
            ("after_instance", after_manifest.digest, tree_manifest(after_root).digest),
        )
        if expected != actual
    }
    if changed:
        raise VerifierAuthorFailure(
            "verifier_transition",
            "verifier_instance_mutation",
            "Qualification Verifier changed a native instance tree",
            changed=changed,
        )
    if not executed.passed:
        raise VerifierAuthorFailure(
            "verifier_transition",
            "verifier_transition_failed",
            "Qualification Verifier process failed",
            command=executed.to_document(),
        )
    try:
        payload = json.loads(executed.stdout)
        result = native_verification_result_from_document(payload)
    except Exception as exc:
        raise VerifierAuthorFailure(
            "verifier_transition",
            "verifier_result_invalid",
            "Qualification Verifier returned an invalid NativeVerificationResult",
            original_code=type(exc).__name__,
            original_message=str(exc),
        ) from exc
    return result


def compute_verifier_project_digest(root: Path) -> str:
    try:
        return compute_authored_project_digest(root, "verifier")
    except ProjectIdentityError as exc:
        raise VerifierAuthorFailure(
            "verifier_identity",
            exc.code,
            str(exc),
            path=exc.path,
        ) from exc


def _codex_config(root: Path, codex_home: Path, config: BuilderConfig) -> CodexConfig:
    return CodexConfig(
        cwd=str(root),
        env=_isolated_codex_env(codex_home, config.uv_cache_dir),
        config_overrides=_codex_provider_overrides(),
    )


def _require_fresh_codex_home(path: Path) -> None:
    if path.is_symlink() or (path.exists() and (not path.is_dir() or any(path.iterdir()))):
        raise VerifierAuthorFailure(
            "verifier_author",
            "verifier_codex_home_not_fresh",
            "Verifier Author Codex home must be fresh",
        )
    path.mkdir(exist_ok=True)


def _initialize_project(root: Path, config: BuilderConfig) -> None:
    if (root / "pyproject.toml").exists():
        return
    initialized = _run(
        (
            "uv",
            "init",
            "--package",
            "--no-workspace",
            "--vcs",
            "none",
            "--name",
            "generated-qualification-verifier",
            "--python",
            "3.12",
            str(root),
        ),
        cwd=root.parent,
        phase="workspace_init",
        config=config,
    )
    if not initialized.passed:
        raise VerifierAuthorFailure(
            "workspace_init",
            "verifier_uv_init_failed",
            "uv init failed for the Verifier Author workspace",
            command=initialized.to_document(),
        )


def _project_files(root: Path) -> tuple[Path, ...]:
    try:
        return project_files(root, "verifier")
    except ProjectIdentityError as exc:
        raise VerifierAuthorFailure(
            "verifier_identity",
            exc.code,
            str(exc),
            path=exc.path,
        ) from exc


def _source_check(root: Path, *, phase: str = "source_contract") -> CommandResult:
    actor_module = ACTOR_FACTORY.partition(":")[0].split(".", 1)[0]
    violations: list[dict[str, str]] = []
    for path in _project_files(root):
        relative = path.relative_to(root).as_posix()
        lowered_parts = {
            token
            for part in path.relative_to(root).parts
            for token in part.casefold().replace("-", "_").replace(".", "_").split("_")
        }
        prohibited = sorted(lowered_parts & _PROHIBITED_OUTPUT_TOKENS)
        if prohibited:
            violations.append(
                {
                    "path": relative,
                    "reason": f"prohibited_output_artifact:{','.join(prohibited)}",
                }
            )
    source_root = root / "src/generated_qualification_verifier"
    release_source = source_root / "release.py"
    if not release_source.is_file():
        violations.append(
            {"path": "src/generated_qualification_verifier/release.py", "reason": "missing"}
        )
    for path in source_root.rglob("*.py") if source_root.is_dir() else ():
        relative = path.relative_to(root).as_posix()
        text = path.read_text(encoding="utf-8")
        if ACTOR_VIEW_NAME in text:
            violations.append({"path": relative, "reason": "actor_view_runtime_access"})
        try:
            tree = ast.parse(text, filename=relative)
        except SyntaxError as exc:
            violations.append({"path": relative, "reason": f"syntax:{exc.lineno}:{exc.offset}"})
            continue
        imports = {
            alias.name.split(".", 1)[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        imports.update(
            node.module.split(".", 1)[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        )
        for forbidden in {"agent_env_foundry", "generated_task_semantics", actor_module} - {""}:
            if forbidden in imports:
                violations.append({"path": relative, "reason": f"forbidden_import:{forbidden}"})
    return CommandResult(
        phase,
        ("host", "scan-verifier-source"),
        1 if violations else 0,
        "" if violations else "source contract passed",
        json.dumps(violations, ensure_ascii=False, sort_keys=True) if violations else "",
    )


def _import_separation_check(
    prepared: PreparedVerifierAuthorWorkspace,
    config: BuilderConfig,
) -> CommandResult:
    actor_module = ACTOR_FACTORY.partition(":")[0].split(".", 1)[0]
    forbidden_modules = tuple(
        module
        for module in (actor_module, "generated_task_semantics", "agent_env_foundry")
        if module
    )
    python = prepared.root / ".venv/bin/python"
    try:
        own_origin = _probe_origin(
            python,
            prepared.root,
            "generated_qualification_verifier",
            config.command_timeout_seconds,
        )
        leaked = {
            module: _probe_origin(
                python,
                prepared.root,
                module,
                config.command_timeout_seconds,
            )
            for module in forbidden_modules
        }
    except Exception as exc:
        return CommandResult(
            "import_separation",
            (str(python), "-I", "import-probe"),
            1,
            "",
            f"{type(exc).__name__}: {exc}",
        )
    expected_source = (prepared.root / "src").resolve()
    visible = {name: str(origin) for name, origin in leaked.items() if origin is not None}
    if own_origin is None or not own_origin.resolve().is_relative_to(expected_source) or visible:
        return CommandResult(
            "import_separation",
            (str(python), "-I", "import-probe"),
            1,
            "",
            f"own_origin={own_origin}; forbidden_origins={visible}",
        )
    return CommandResult(
        "import_separation",
        (str(python), "-I", "import-probe"),
        0,
        f"own_origin={own_origin}",
        "",
    )


def _factory_check(
    prepared: PreparedVerifierAuthorWorkspace,
    config: BuilderConfig,
) -> CommandResult:
    python = prepared.root / ".venv/bin/python"
    script = (
        "import importlib,sys;"
        "module_name,attribute=sys.argv[1].split(':',1);"
        "factory=getattr(importlib.import_module(module_name),attribute);"
        "verifier=factory();"
        "assert callable(getattr(verifier,'verify_transition',None))"
    )
    return _run(
        (str(python), "-I", "-B", "-c", script, VERIFIER_FACTORY),
        cwd=prepared.root,
        phase="verifier_contract",
        config=config,
    )


def _feedback(checks: tuple[CommandResult, ...]) -> str:
    failures = [check.to_document() for check in checks if not check.passed]
    return (
        "The deterministic Framework rejected the current verifier project. "
        "Repair verifier code/dependencies/tests only; do not edit immutable inputs. "
        "Fix every complete factual failure in this turn:\n"
        + json.dumps(failures, ensure_ascii=False, sort_keys=True)
    )


__all__ = [
    "VERIFIER_FACTORY",
    "VerifierAuthorFailure",
    "VerifierAuthorFinding",
    "VerifierBuild",
    "compute_verifier_project_digest",
    "invoke_verifier_transition",
    "repair_verifier_author",
    "run_verifier_author",
    "run_verifier_checks",
]
