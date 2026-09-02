"""Codex-authored, task-specific checker with Host-owned identity and execution."""

from __future__ import annotations

import ast
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from openai_codex import ApprovalMode, Codex, CodexConfig, Sandbox

from agent_env_foundry.builder import (
    BuilderConfig,
    CommandResult,
    _codex_provider_overrides,
    _isolated_codex_env,
    _run,
)
from agent_env_foundry.environment import JSONObject
from agent_env_foundry.physical_runtime import (
    PreparationSettings,
    ProjectMaterializationInput,
    _ChildTransport,
    materialize_project,
)
from agent_env_foundry.project_identity import (
    ProjectIdentityError,
    compute_authored_project_digest,
)
from agent_env_foundry.release import canonical_bytes
from agent_env_foundry.task_contract import (
    CHECKER_FACTORY,
    CandidateTaskContract,
    TaskCheckRequest,
    TaskCheckResult,
    TaskContract,
    TaskProposalEvidence,
    make_task_check_request,
    seal_task_contract,
    task_check_result_from_document,
)

CANDIDATE_INPUT = "CANDIDATE_TASK_CONTRACT.json"
PROPOSAL_INPUT = "PROPOSAL_EVIDENCE.json"
CHECKER_CONTRACT_INPUT = "TASK_CHECKER_CONTRACT.md"
_INPUT_NAMES = frozenset({CANDIDATE_INPUT, PROPOSAL_INPUT, CHECKER_CONTRACT_INPUT})
_FORBIDDEN_IMPORTS = frozenset(
    {
        "agent_env_foundry",
        "generated_environment",
        "generated_qualification_verifier",
        "generated_task_semantics",
        "httpx",
        "openai",
        "os",
        "pathlib",
        "requests",
        "socket",
        "subprocess",
    }
)


class CheckerAuthorInputError(ValueError):
    pass


class CheckerAuthorFailure(RuntimeError):
    def __init__(self, phase: str, code: str, message: str, **details: Any) -> None:
        super().__init__(message)
        self.phase = phase
        self.code = code
        self.details = {"phase": phase, **details}


@dataclass(frozen=True, slots=True)
class PreparedCheckerWorkspace:
    root: Path
    candidate: CandidateTaskContract
    proposal_evidence: TaskProposalEvidence
    input_digests: dict[str, str]

    def verify_inputs(self) -> None:
        if set(self.input_digests) != _INPUT_NAMES:
            raise CheckerAuthorInputError("checker frozen input set is incomplete")
        for name, expected in self.input_digests.items():
            path = self.root / name
            if path.is_symlink() or not path.is_file():
                raise CheckerAuthorInputError(f"checker input {name} changed or disappeared")
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
            if actual != expected or path.stat().st_mode & 0o222:
                raise CheckerAuthorInputError(f"checker input {name} changed after staging")


@dataclass(frozen=True, slots=True)
class CheckerBuild:
    root: Path
    thread_id: str
    codex_home: Path
    project_digest: str
    task_contract: TaskContract
    checks: tuple[CommandResult, ...]


def prepare_checker_author_workspace(
    destination: Path,
    *,
    candidate: CandidateTaskContract,
    proposal_evidence: TaskProposalEvidence,
) -> PreparedCheckerWorkspace:
    if not isinstance(candidate, CandidateTaskContract) or not isinstance(
        proposal_evidence, TaskProposalEvidence
    ):
        raise CheckerAuthorInputError("checker author requires typed candidate and evidence")
    if (
        candidate.release_id != proposal_evidence.release_id
        or candidate.reset_start != proposal_evidence.reset_start
        or candidate.proposal_evidence_digest != proposal_evidence.evidence_id
    ):
        raise CheckerAuthorInputError("candidate and proposal evidence identity differ")
    try:
        make_task_check_request(
            seal_task_contract(candidate, checker_project_digest="0" * 64),
            before_state=proposal_evidence.before_state,
            after_state=proposal_evidence.after_state,
            public_trace=proposal_evidence.public_trace,
            final_answer=proposal_evidence.proposed_final_answer,
        )
    except Exception as exc:
        raise CheckerAuthorInputError(f"proposal evidence violates candidate: {exc}") from exc
    root = Path(destination).resolve()
    if root.is_symlink() or (root.exists() and (not root.is_dir() or any(root.iterdir()))):
        raise CheckerAuthorInputError("checker workspace must be absent or empty")
    root.mkdir(parents=True, exist_ok=True)
    payloads = {
        CANDIDATE_INPUT: canonical_bytes(candidate.to_document()),
        PROPOSAL_INPUT: canonical_bytes(proposal_evidence.to_document()),
        CHECKER_CONTRACT_INPUT: (
            Path(__file__).parent / "runtime_skills/task-checker-codegen/TASK_CHECKER_CONTRACT.md"
        ).read_bytes(),
    }
    digests: dict[str, str] = {}
    for name, payload in payloads.items():
        path = root / name
        path.write_bytes(payload)
        path.chmod(0o444)
        digests[name] = hashlib.sha256(payload).hexdigest()
    prepared = PreparedCheckerWorkspace(root, candidate, proposal_evidence, digests)
    prepared.verify_inputs()
    return prepared


def compute_checker_project_digest(root: Path) -> str:
    try:
        return compute_authored_project_digest(root, "checker", require_locked_project=True)
    except ProjectIdentityError as exc:
        raise CheckerAuthorFailure(
            "checker_identity",
            exc.code,
            str(exc),
            path=exc.path,
        ) from exc


def run_checker_checks(
    prepared: PreparedCheckerWorkspace,
    config: BuilderConfig,
) -> tuple[CommandResult, ...]:
    prepared.verify_inputs()
    source = _source_check(prepared.root)
    if not source.passed:
        return (source,)
    results: list[CommandResult] = [source]
    for phase, command in (
        ("lock", ("uv", "lock")),
        ("sync", ("uv", "sync", "--frozen", "--all-groups", "--link-mode", "copy")),
        ("build", ("uv", "build")),
    ):
        result = _run(command, cwd=prepared.root, phase=phase, config=config)
        results.append(result)
        if not result.passed:
            return tuple(results)
    tests = prepared.root / "tests"
    test_command = (str(prepared.root / ".venv/bin/python"), "-m", "pytest", "-q")
    if not tests.is_dir():
        results.append(CommandResult("tests", test_command, 2, "", "tests missing"))
        return tuple(results)
    tests_result = _run(test_command, cwd=prepared.root, phase="tests", config=config)
    results.append(tests_result)
    if not tests_result.passed:
        return tuple(results)
    results.append(_checker_contract_check(prepared, config))
    prepared.verify_inputs()
    return tuple(results)


def execute_checker_project(
    prepared: PreparedCheckerWorkspace,
    *,
    checker_project_digest: str,
    runtime_root: Path,
    settings: PreparationSettings,
) -> tuple[TaskContract, TaskCheckResult]:
    prepared.verify_inputs()
    task = seal_task_contract(
        prepared.candidate,
        checker_project_digest=checker_project_digest,
    )
    evidence = prepared.proposal_evidence
    request = make_task_check_request(
        task,
        before_state=evidence.before_state,
        after_state=evidence.after_state,
        public_trace=evidence.public_trace,
        final_answer=evidence.proposed_final_answer,
    )
    result = execute_task_checker(
        prepared.root,
        task=task,
        request=request,
        runtime_root=runtime_root,
        settings=settings,
    )
    return task, result


def execute_task_checker(
    checker_project_root: Path,
    *,
    task: TaskContract,
    request: TaskCheckRequest,
    runtime_root: Path,
    settings: PreparationSettings,
) -> TaskCheckResult:
    """Execute one frozen checker over any Host-constructed Task request."""

    if not isinstance(task, TaskContract) or not isinstance(request, TaskCheckRequest):
        raise TypeError("checker execution requires typed TaskContract and TaskCheckRequest")
    if request.task_id != task.task_id:
        raise CheckerAuthorFailure(
            "checker_contract",
            "checker_request_task_mismatch",
            "checker request belongs to another Task",
        )
    project_root = Path(checker_project_root)
    actual = compute_checker_project_digest(project_root)
    if actual != task.checker_project_digest:
        raise CheckerAuthorFailure(
            "checker_identity",
            "checker_digest_mismatch",
            "checker project bytes differ from the TaskContract identity",
            expected=task.checker_project_digest,
            actual=actual,
        )
    runtime = materialize_project(
        ProjectMaterializationInput(
            project_root,
            task.checker_project_digest,
            "generated_task_checker",
            (
                "agent_env_foundry",
                "generated_environment",
                "generated_task_semantics",
                "generated_qualification_verifier",
            ),
            "checker",
        ),
        Path(runtime_root),
        settings=settings,
    )
    before_digest = compute_checker_project_digest(runtime.project_root)
    transport = _ChildTransport(
        runtime.python,
        Path(__file__).parent / "_checker_runner.py",
        (CHECKER_FACTORY,),
        cwd=runtime.project_root,
        timeout=settings.command_timeout_seconds,
        role="checker",
    )
    try:
        first = task_check_result_from_document(transport.call("check", request.to_document()))
        second = task_check_result_from_document(transport.call("check", request.to_document()))
    finally:
        transport.close(operation="close")
    if first != second:
        raise CheckerAuthorFailure(
            "checker_contract",
            "checker_nondeterministic",
            "same checker request produced different results",
        )
    after_digest = compute_checker_project_digest(runtime.project_root)
    if before_digest != after_digest:
        raise CheckerAuthorFailure(
            "checker_contract",
            "checker_source_mutation",
            "checker execution changed its frozen project bytes",
        )
    return first


def run_checker_author(
    prepared: PreparedCheckerWorkspace,
    *,
    config: BuilderConfig | None = None,
) -> CheckerBuild:
    selected = config or BuilderConfig(
        uv_cache_dir=Path("/tmp/agent-env-foundry-checker-author-uv-cache")
    )
    prepared.verify_inputs()
    _initialize_project(prepared.root, selected)
    codex_home = prepared.root.parent / "checker-codex-home"
    _fresh_directory(codex_home, role="checker Codex home")
    skill = (Path(__file__).parent / "runtime_skills/task-checker-codegen/SKILL.md").read_text(
        encoding="utf-8"
    )
    prompt = (
        "Implement the one task checker described by the three immutable input files. "
        "Write generated_task_checker.release:check_task and meaningful tests. Run all "
        "project checks. The Host, not your response, decides acceptance."
    )
    with Codex(_codex_config(prepared.root, codex_home, selected)) as codex:
        thread = codex.thread_start(
            approval_mode=ApprovalMode.deny_all,
            base_instructions=skill,
            cwd=str(prepared.root),
            model=selected.model,
            sandbox=Sandbox.full_access,
        )
        return _drive_checker(
            prepared,
            thread,
            codex_home,
            selected,
            prompt,
            previous_failed_digest=None,
        )


def repair_checker_author(
    prepared: PreparedCheckerWorkspace,
    build: CheckerBuild,
    findings: tuple[JSONObject, ...],
    *,
    config: BuilderConfig,
) -> CheckerBuild:
    prepared.verify_inputs()
    if (
        build.root.resolve() != prepared.root.resolve()
        or not build.thread_id
        or not build.codex_home.is_dir()
        or build.project_digest != compute_checker_project_digest(prepared.root)
        or not findings
    ):
        raise CheckerAuthorFailure(
            "checker_repair",
            "checker_repair_identity_invalid",
            "checker repair must resume the exact frozen candidate project",
        )
    skill = (Path(__file__).parent / "runtime_skills/task-checker-codegen/SKILL.md").read_text(
        encoding="utf-8"
    )
    prompt = (
        "PHYSICAL CHECKER CHALLENGE REJECTED THIS CANDIDATE. Repair checker source/tests "
        "without editing immutable inputs. Complete findings:\n"
        + json.dumps(list(findings), ensure_ascii=False, sort_keys=True)
    )
    with Codex(_codex_config(prepared.root, build.codex_home, config)) as codex:
        thread = codex.thread_resume(
            build.thread_id,
            approval_mode=ApprovalMode.deny_all,
            base_instructions=skill,
            cwd=str(prepared.root),
            model=config.model,
            sandbox=Sandbox.full_access,
        )
        return _drive_checker(
            prepared,
            thread,
            build.codex_home,
            config,
            prompt,
            previous_failed_digest=build.project_digest,
        )


def _drive_checker(
    prepared: PreparedCheckerWorkspace,
    thread: Any,
    codex_home: Path,
    config: BuilderConfig,
    prompt: str,
    *,
    previous_failed_digest: str | None,
) -> CheckerBuild:
    last_checks: tuple[CommandResult, ...] = ()
    for turn_index in range(config.max_turns):
        try:
            thread.run(prompt)
        except Exception as exc:
            if turn_index + 1 == config.max_turns:
                raise CheckerAuthorFailure(
                    "infrastructure",
                    "checker_provider_turn_failed",
                    "Checker Author provider turn failed",
                    original_code=type(exc).__name__,
                    original_message=str(exc),
                ) from exc
            continue
        prepared.verify_inputs()
        last_checks = run_checker_checks(prepared, config)
        current_digest = _current_project_digest(prepared.root)
        if last_checks and all(item.passed for item in last_checks):
            digest = compute_checker_project_digest(prepared.root)
            task, _positive = execute_checker_project(
                prepared,
                checker_project_digest=digest,
                runtime_root=prepared.root.parent / ".checker-author-runtime" / digest,
                settings=PreparationSettings(
                    config.uv_cache_dir,
                    config.command_timeout_seconds,
                ),
            )
            return CheckerBuild(
                prepared.root,
                thread.id,
                codex_home,
                digest,
                task,
                last_checks,
            )
        if current_digest == previous_failed_digest:
            raise CheckerAuthorFailure(
                "checker_author",
                "checker_author_stalled",
                "Checker Author changed no project bytes after factual feedback",
                failures=[item.to_document() for item in last_checks if not item.passed],
            )
        previous_failed_digest = current_digest
        prompt = _feedback(last_checks)
    raise CheckerAuthorFailure(
        "checker_author",
        "checker_author_turns_exhausted",
        "Checker Author exhausted its bounded repair turns",
        failures=[item.to_document() for item in last_checks if not item.passed],
    )


def _source_check(root: Path) -> CommandResult:
    violations: list[dict[str, Any]] = []
    source_root = root / "src/generated_task_checker"
    if not (source_root / "release.py").is_file():
        violations.append({"path": "src/generated_task_checker/release.py", "reason": "missing"})
    for path in sorted(source_root.rglob("*.py")) if source_root.is_dir() else ():
        relative = path.relative_to(root).as_posix()
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative)
        except (OSError, SyntaxError) as exc:
            violations.append({"path": relative, "reason": f"invalid_source:{exc}"})
            continue
        imports = {
            alias.name.partition(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        imports.update(
            node.module.partition(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        )
        for name in sorted(imports & _FORBIDDEN_IMPORTS):
            violations.append({"path": relative, "reason": f"forbidden_import:{name}"})
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id
                in {
                    "eval",
                    "exec",
                    "open",
                }
            ):
                violations.append({"path": relative, "reason": f"forbidden_call:{node.func.id}"})
    return CommandResult(
        "source_contract",
        ("host", "scan-checker-source"),
        1 if violations else 0,
        "" if violations else "checker source contract passed",
        json.dumps(violations, ensure_ascii=False, sort_keys=True) if violations else "",
    )


def _checker_contract_check(
    prepared: PreparedCheckerWorkspace,
    config: BuilderConfig,
) -> CommandResult:
    try:
        digest = compute_checker_project_digest(prepared.root)
        task, result = execute_checker_project(
            prepared,
            checker_project_digest=digest,
            runtime_root=prepared.root.parent / ".checker-contract-runtime" / digest,
            settings=PreparationSettings(
                config.uv_cache_dir,
                config.command_timeout_seconds,
            ),
        )
        if not result.passed:
            raise ValueError(f"checker rejected proposal evidence: {list(result.reason_codes)}")
    except Exception as exc:
        return CommandResult(
            "checker_contract",
            ("host", "execute-checker-contract"),
            1,
            "",
            json.dumps(
                {
                    "error_type": type(exc).__name__,
                    "code": getattr(exc, "code", "checker_contract_invalid"),
                    "message": str(exc),
                    "details": getattr(exc, "details", {}),
                },
                ensure_ascii=False,
                sort_keys=True,
                default=str,
            ),
        )
    return CommandResult(
        "checker_contract",
        ("host", "execute-checker-contract"),
        0,
        json.dumps(
            {"task_id": task.task_id, "result": result.to_document()},
            ensure_ascii=False,
            sort_keys=True,
        ),
        "",
    )


def _initialize_project(root: Path, config: BuilderConfig) -> None:
    if not (root / "pyproject.toml").exists():
        result = _run(
            (
                "uv",
                "init",
                "--package",
                "--no-workspace",
                "--vcs",
                "none",
                "--name",
                "generated-task-checker",
                "--python",
                "3.12",
                str(root),
            ),
            cwd=root.parent,
            phase="workspace_init",
            config=config,
        )
        if not result.passed:
            raise CheckerAuthorFailure(
                "workspace_init",
                "checker_uv_init_failed",
                "uv init failed for Checker Author workspace",
                command=result.to_document(),
            )
    result = _run(
        ("uv", "add", "--dev", "pytest>=8.3,<10"),
        cwd=root,
        phase="workspace_test_scaffold",
        config=config,
    )
    if not result.passed:
        raise CheckerAuthorFailure(
            "workspace_init",
            "checker_test_scaffold_failed",
            "Framework could not install checker test dependency",
            command=result.to_document(),
        )
    (root / "tests").mkdir(exist_ok=True)


def _current_project_digest(root: Path) -> str:
    try:
        return compute_authored_project_digest(root, "checker", require_locked_project=False)
    except ProjectIdentityError as exc:
        raise CheckerAuthorFailure("checker_identity", exc.code, str(exc), path=exc.path) from exc


def _fresh_directory(path: Path, *, role: str) -> None:
    if path.is_symlink() or (path.exists() and (not path.is_dir() or any(path.iterdir()))):
        raise CheckerAuthorFailure(
            "checker_author", "checker_workspace_not_fresh", f"{role} must be fresh"
        )
    path.mkdir(parents=True, exist_ok=True)


def _codex_config(root: Path, codex_home: Path, config: BuilderConfig) -> CodexConfig:
    return CodexConfig(
        cwd=str(root),
        env=_isolated_codex_env(str(codex_home), config.uv_cache_dir),
        config_overrides=_codex_provider_overrides(),
    )


def _feedback(checks: tuple[CommandResult, ...]) -> str:
    failures = [item.to_document() for item in checks if not item.passed]
    return (
        "The deterministic Host rejected the checker. Repair source/tests only; preserve "
        "all immutable inputs. Complete failures:\n"
        + json.dumps(failures, ensure_ascii=False, sort_keys=True)
    )


__all__ = [
    "CANDIDATE_INPUT",
    "CHECKER_CONTRACT_INPUT",
    "PROPOSAL_INPUT",
    "CheckerAuthorFailure",
    "CheckerAuthorInputError",
    "CheckerBuild",
    "PreparedCheckerWorkspace",
    "compute_checker_project_digest",
    "execute_checker_project",
    "execute_task_checker",
    "prepare_checker_author_workspace",
    "repair_checker_author",
    "run_checker_author",
    "run_checker_checks",
]
