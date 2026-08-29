"""Codex-authored release-local TaskSemantics project with Host-owned checks."""

from __future__ import annotations

import ast
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

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
from agent_env_foundry.preparation import _ChildTransport, _probe_origin
from agent_env_foundry.project_identity import (
    ProjectIdentityError,
    compute_authored_project_digest,
    project_files,
)
from agent_env_foundry.release import canonical_bytes
from agent_env_foundry.semantics import (
    CapabilitySpec,
    capability_from_document,
    start_case_from_document,
    validate_catalog,
    validate_start_cases,
)
from agent_env_foundry.semantics_inputs import (
    EXPECTED_TASK_SEMANTICS_NAME,
    PUBLIC_SURFACE_NAME,
    PreparedSemanticsAuthorWorkspace,
)
from agent_env_foundry.semantics_wire import validate_semantics_wire_items

SEMANTICS_FACTORY = "generated_task_semantics.release:make_semantics"


class SemanticsAuthorFailure(RuntimeError):
    def __init__(self, phase: str, code: str, message: str, **details: Any) -> None:
        super().__init__(message)
        self.phase = phase
        self.code = code
        self.details = {"phase": phase, **details}


@dataclass(frozen=True)
class SemanticsBuild:
    root: Path
    thread_id: str
    codex_home: Path
    factory: str
    project_digest: str
    checks: tuple[CommandResult, ...]


def run_semantics_author(
    prepared: PreparedSemanticsAuthorWorkspace,
    *,
    config: BuilderConfig | None = None,
) -> SemanticsBuild:
    """Let Codex write semantic code; Host owns every mechanical check and verdict."""
    selected = config or BuilderConfig(
        uv_cache_dir=Path("/tmp/agent-env-foundry-semantics-author-uv-cache")
    )
    prepared.verify_inputs()
    _initialize_project(prepared.root, selected)
    skill = (Path(__file__).parent / "runtime_skills/task-semantics-codegen/SKILL.md").read_text(
        encoding="utf-8"
    )
    prompt = (
        "Write the TaskSemantics project described by the immutable Host inputs. "
        "Implement release-specific native decoding and semantic records in the fixed "
        "generated_task_semantics.release:make_semantics factory. Framework checks, not "
        "your response, decide acceptance."
    )
    codex_home = prepared.root.parent / "semantics-codex-home"
    _require_fresh_codex_home(codex_home)
    with Codex(_codex_config(prepared.root, codex_home, selected)) as codex:
        thread = codex.thread_start(
            approval_mode=ApprovalMode.deny_all,
            base_instructions=skill,
            cwd=str(prepared.root),
            model=selected.model,
            sandbox=Sandbox.full_access,
        )
        return _drive_semantics_thread(
            prepared,
            thread,
            codex_home,
            selected,
            prompt,
            previous_failed_digest=None,
        )


def repair_semantics_author(
    prepared: PreparedSemanticsAuthorWorkspace,
    build: SemanticsBuild,
    findings: tuple[AuthorFinding, ...],
    *,
    config: BuilderConfig,
) -> SemanticsBuild:
    """Resume the exact Semantics Author thread with physical CP3C findings."""
    prepared.verify_inputs()
    if (
        build.root.resolve() != prepared.root.resolve()
        or build.factory != SEMANTICS_FACTORY
        or not build.thread_id
        or build.codex_home.is_symlink()
        or not build.codex_home.is_dir()
        or not findings
        or any(not isinstance(item, AuthorFinding) for item in findings)
        or len({item.code for item in findings}) != len(findings)
    ):
        raise SemanticsAuthorFailure(
            "semantics_author",
            "semantics_author_resume_invalid",
            "Semantics Author resume identity is unavailable",
        )
    actual_digest = compute_semantics_project_digest(prepared.root)
    if actual_digest != build.project_digest:
        raise SemanticsAuthorFailure(
            "semantics_author",
            "semantics_author_digest_mismatch",
            "TaskSemantics project bytes changed before factual repair",
            expected=build.project_digest,
            actual=actual_digest,
        )
    skill = (Path(__file__).parent / "runtime_skills/task-semantics-codegen/SKILL.md").read_text(
        encoding="utf-8"
    )
    prompt = (
        "PHYSICAL SEMANTIC QUALIFICATION REJECTED\n"
        "Fix semantic source/tests only; preserve immutable Host inputs and passed capabilities.\n"
        "ALL_FINDINGS\n"
        + json.dumps(
            [item.to_document() for item in findings],
            ensure_ascii=False,
            sort_keys=True,
        )
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
        return _drive_semantics_thread(
            prepared,
            thread,
            build.codex_home,
            config,
            prompt,
            previous_failed_digest=build.project_digest,
        )


def _drive_semantics_thread(
    prepared: PreparedSemanticsAuthorWorkspace,
    thread: Any,
    codex_home: Path,
    config: BuilderConfig,
    prompt: str,
    *,
    previous_failed_digest: str | None,
) -> SemanticsBuild:
    last_checks: tuple[CommandResult, ...] = ()
    for turn_index in range(config.max_turns):
        try:
            thread.run(prompt)
        except Exception as exc:
            if turn_index + 1 == config.max_turns:
                raise SemanticsAuthorFailure(
                    "infrastructure",
                    "semantics_provider_turn_failed",
                    "Semantics Author provider turn failed",
                    original_code=type(exc).__name__,
                    original_message=str(exc),
                ) from exc
            continue
        prepared.verify_inputs()
        last_checks = run_semantics_checks(prepared, config)
        digest = compute_semantics_project_digest(prepared.root)
        if last_checks and all(check.passed for check in last_checks):
            return SemanticsBuild(
                prepared.root,
                thread.id,
                codex_home,
                SEMANTICS_FACTORY,
                digest,
                last_checks,
            )
        if previous_failed_digest == digest:
            raise SemanticsAuthorFailure(
                "semantics_author",
                "semantics_author_stalled",
                "Semantics Author changed no project bytes after factual feedback",
                project_digest=digest,
                failures=[check.to_document() for check in last_checks if not check.passed],
            )
        previous_failed_digest = digest
        prompt = _feedback(last_checks)
    raise SemanticsAuthorFailure(
        "semantics_author",
        "semantics_author_turns_exhausted",
        "Semantics Author exhausted its bounded repair turns",
        failures=[check.to_document() for check in last_checks if not check.passed],
    )


def _codex_config(root: Path, codex_home: Path, config: BuilderConfig) -> CodexConfig:
    return CodexConfig(
        cwd=str(root),
        env=_isolated_codex_env(codex_home, config.uv_cache_dir),
        config_overrides=_codex_provider_overrides(),
    )


def _require_fresh_codex_home(path: Path) -> None:
    if path.is_symlink() or (path.exists() and (not path.is_dir() or any(path.iterdir()))):
        raise SemanticsAuthorFailure(
            "semantics_author",
            "semantics_codex_home_not_fresh",
            "Semantics Author Codex home must be fresh",
        )
    path.mkdir(exist_ok=True)


def run_semantics_checks(
    prepared: PreparedSemanticsAuthorWorkspace,
    config: BuilderConfig,
) -> tuple[CommandResult, ...]:
    prepared.verify_inputs()
    source_check = _source_check(prepared.root)
    if not source_check.passed:
        return (source_check,)
    results: list[CommandResult] = [source_check]
    commands = (
        ("lock", ("uv", "lock")),
        ("sync", ("uv", "sync", "--frozen", "--all-groups", "--link-mode", "copy")),
    )
    for phase, command in commands:
        result = _run(command, cwd=prepared.root, phase=phase, config=config)
        results.append(result)
        if not result.passed:
            return tuple(results)
    import_check = _import_separation_check(prepared, config)
    results.append(import_check)
    if not import_check.passed:
        return tuple(results)
    build_result = _run(
        ("uv", "build"),
        cwd=prepared.root,
        phase="build",
        config=config,
    )
    results.append(build_result)
    if not build_result.passed:
        return tuple(results)
    tests = prepared.root / "tests"
    test_command = (str(prepared.root / ".venv/bin/python"), "-m", "pytest", "-q")
    if not tests.is_dir():
        results.append(CommandResult("tests", test_command, 2, "", "tests missing"))
        return tuple(results)
    test_result = _run(test_command, cwd=prepared.root, phase="tests", config=config)
    results.append(test_result)
    if not test_result.passed:
        return tuple(results)
    results.append(_contract_check(prepared, config))
    prepared.verify_inputs()
    return tuple(results)


def compute_semantics_project_digest(root: Path) -> str:
    try:
        return compute_authored_project_digest(root, "semantics")
    except ProjectIdentityError as exc:
        raise SemanticsAuthorFailure(
            "semantics_identity",
            exc.code,
            str(exc),
            path=exc.path,
        ) from exc


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
            "generated-task-semantics",
            "--python",
            "3.12",
            str(root),
        ),
        cwd=root.parent,
        phase="workspace_init",
        config=config,
    )
    if not initialized.passed:
        raise SemanticsAuthorFailure(
            "workspace_init",
            "semantics_uv_init_failed",
            "uv init failed for the Semantics Author workspace",
            command=initialized.to_document(),
        )


def _project_files(root: Path) -> tuple[Path, ...]:
    try:
        return project_files(root, "semantics")
    except ProjectIdentityError as exc:
        raise SemanticsAuthorFailure(
            "semantics_identity",
            exc.code,
            str(exc),
            path=exc.path,
        ) from exc


def _source_check(root: Path) -> CommandResult:
    actor_module = ACTOR_FACTORY.partition(":")[0].split(".", 1)[0]
    violations: list[dict[str, str]] = []
    source_root = root / "src/generated_task_semantics"
    if not (source_root / "release.py").is_file():
        violations.append({"path": "src/generated_task_semantics/release.py", "reason": "missing"})
    for path in source_root.rglob("*.py") if source_root.is_dir() else ():
        relative = path.relative_to(root).as_posix()
        text = path.read_text(encoding="utf-8")
        if "candidate-view" in text:
            violations.append({"path": relative, "reason": "candidate_view_runtime_access"})
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
        for forbidden in {
            "agent_env_foundry",
            "generated_qualification_verifier",
            actor_module,
        } - {""}:
            if forbidden in imports:
                violations.append({"path": relative, "reason": f"forbidden_import:{forbidden}"})
    return CommandResult(
        "source_contract",
        ("host", "scan-semantics-source"),
        1 if violations else 0,
        "" if violations else "source contract passed",
        json.dumps(violations, ensure_ascii=False, sort_keys=True) if violations else "",
    )


def _contract_check(
    prepared: PreparedSemanticsAuthorWorkspace,
    config: BuilderConfig,
) -> CommandResult:
    python = prepared.root / ".venv/bin/python"
    transport: _ChildTransport | None = None
    try:
        transport = _ChildTransport(
            python,
            Path(__file__).parent / "_semantics_runner.py",
            (SEMANTICS_FACTORY,),
            cwd=prepared.root,
            timeout=config.command_timeout_seconds,
            role="semantics",
        )
        public = _read_json(prepared.root / PUBLIC_SURFACE_NAME)
        start_limit = 4
        raw_cases = transport.call("start_cases", {"seed": 0, "limit": start_limit})
        repeated_cases = transport.call("start_cases", {"seed": 0, "limit": start_limit})
        raw_capabilities = transport.call("capabilities", {})
        findings: list[str] = []
        if not isinstance(raw_cases, list):
            raise ValueError("start_cases must return an array")
        if not raw_cases:
            findings.append("$.start_cases: must return a non-empty array")
        if canonical_bytes(raw_cases) != canonical_bytes(repeated_cases):
            findings.append("$.start_cases: results differ for the same seed and limit")
        if not isinstance(raw_capabilities, list):
            raise ValueError("capabilities must return an array")
        findings.extend(
            f"$.start_cases{item.removeprefix('$')}"
            for item in validate_semantics_wire_items("start_case", raw_cases)
        )
        findings.extend(
            f"$.capabilities{item.removeprefix('$')}"
            for item in validate_semantics_wire_items("capability", raw_capabilities)
        )
        cases = []
        for index, item in enumerate(raw_cases):
            try:
                cases.append(start_case_from_document(item))
            except Exception as exc:
                findings.append(f"$.start_cases[{index}]: {type(exc).__name__}: {exc}")
        specs = []
        for index, item in enumerate(raw_capabilities):
            try:
                specs.append(capability_from_document(item))
            except Exception as exc:
                findings.append(f"$.capabilities[{index}]: {type(exc).__name__}: {exc}")
        if findings:
            raise ValueError(json.dumps({"findings": findings}, ensure_ascii=False, sort_keys=True))
        validate_start_cases(
            tuple(cases),
            start_schema=cast(dict[str, Any], public["start_schema"]),
            limit=start_limit,
        )
        catalog = validate_catalog(tuple(specs))
        _align_expected_catalog(
            _read_json(prepared.root / EXPECTED_TASK_SEMANTICS_NAME),
            catalog,
        )
    except Exception as exc:
        return CommandResult(
            "semantics_contract",
            (str(python), SEMANTICS_FACTORY),
            1,
            "",
            f"{type(exc).__name__}: {exc}",
        )
    finally:
        if transport is not None:
            transport.close(operation="close")
    return CommandResult(
        "semantics_contract",
        (str(python), SEMANTICS_FACTORY),
        0,
        "TaskSemantics factory and frozen catalog passed",
        "",
    )


def _import_separation_check(
    prepared: PreparedSemanticsAuthorWorkspace,
    config: BuilderConfig,
) -> CommandResult:
    actor_module = ACTOR_FACTORY.partition(":")[0].split(".", 1)[0]
    modules = tuple(
        module
        for module in (
            actor_module,
            "generated_qualification_verifier",
            "agent_env_foundry",
        )
        if module
    )
    python = prepared.root / ".venv/bin/python"
    try:
        own_origin = _probe_origin(
            python,
            prepared.root,
            "generated_task_semantics",
            config.command_timeout_seconds,
        )
        leaked = {
            module: _probe_origin(
                python,
                prepared.root,
                module,
                config.command_timeout_seconds,
            )
            for module in modules
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


def _align_expected_catalog(
    expected: dict[str, Any],
    actual: dict[str, CapabilitySpec],
) -> None:
    expected_capabilities = {item["capability_id"]: item for item in expected["capabilities"]}
    if set(actual) != set(expected_capabilities):
        raise ValueError(
            f"capability IDs differ: expected {sorted(expected_capabilities)}, got {sorted(actual)}"
        )
    capability_findings: list[dict[str, Any]] = []
    for capability_id, expected_item in expected_capabilities.items():
        spec = actual[capability_id]
        comparisons = {
            "requirement_ids": sorted(spec.requirement_ids),
            "workflow_ids": sorted(spec.workflow_ids),
            "actor_role": spec.actor_role,
            "task_kind": spec.task_kind,
            "intent_label": spec.intent_label,
            "answer_fields": sorted(
                (
                    {
                        "field_id": field.field_id,
                        "public_label": field.public_label,
                    }
                    for field in spec.answer_fields
                ),
                key=lambda field: field["field_id"],
            ),
        }
        mismatches = {
            field: {"expected": expected_item[field], "actual": value}
            for field, value in comparisons.items()
            if value != expected_item[field]
        }
        if mismatches:
            capability_findings.append({"capability_id": capability_id, "mismatches": mismatches})
    if capability_findings:
        raise ValueError(
            json.dumps(
                {"capability_findings": capability_findings},
                ensure_ascii=False,
                sort_keys=True,
            )
        )

    actual_rules = {
        rule.rule_id: rule for spec in actual.values() for rule in spec.composition_rules
    }
    expected_rules = {item["rule_id"]: item for item in expected["composition_rules"]}
    if set(actual_rules) != set(expected_rules):
        raise ValueError("composition rule IDs differ from frozen semantics")
    for rule_id, item in expected_rules.items():
        rule = actual_rules[rule_id]
        if (
            rule.workflow_id != item["workflow_id"]
            or sorted(rule.capability_ids) != item["capability_ids"]
            or rule.max_occurrences != item["max_occurrences"]
        ):
            raise ValueError(f"composition rule {rule_id!r} differs from frozen semantics")
        for capability_id in item["capability_ids"]:
            if rule_id not in {
                attached.rule_id for attached in actual[capability_id].composition_rules
            }:
                raise ValueError(
                    f"composition rule {rule_id!r} is not attached to {capability_id!r}"
                )

    actual_conditions: dict[str, Any] = {}
    for spec in actual.values():
        for condition in spec.conditions:
            previous = actual_conditions.setdefault(condition.condition_id, condition)
            if previous != condition:
                raise ValueError(
                    f"condition {condition.condition_id!r} has inconsistent declarations"
                )
    expected_conditions = {item["condition_id"]: item for item in expected["conditions"]}
    if set(actual_conditions) != set(expected_conditions):
        raise ValueError("condition IDs differ from frozen semantics")
    condition_findings: list[dict[str, Any]] = []
    for condition_id, item in expected_conditions.items():
        condition = actual_conditions[condition_id]
        report_field_id = condition.report_field.field_id if condition.report_field else ""
        visibility = (
            "reset"
            if condition.public_source.kind == "reset"
            else "public_tool"
            if condition.public_source.kind == "tool_output"
            else condition.public_source.kind
        )
        expected_values = {
            "public_label": item["public_label"],
            "visibility": item["visibility"],
            "binding_scope": item["binding_scope"],
            "true_capability_ids": item["true_capability_ids"],
            "false_capability_ids": item["false_capability_ids"],
            "report_field_id": item["report_field_id"],
        }
        actual_values = {
            "public_label": condition.public_label,
            "visibility": visibility,
            "binding_scope": condition.binding_scope,
            "true_capability_ids": sorted(condition.true_capability_ids),
            "false_capability_ids": sorted(condition.false_capability_ids),
            "report_field_id": report_field_id,
        }
        mismatches = {
            field: {"expected": expected_values[field], "actual": actual_values[field]}
            for field in expected_values
            if expected_values[field] != actual_values[field]
        }
        if mismatches:
            condition_findings.append({"condition_id": condition_id, "mismatches": mismatches})
    if condition_findings:
        raise ValueError(
            json.dumps(
                {"condition_findings": condition_findings},
                ensure_ascii=False,
                sort_keys=True,
            )
        )


def _feedback(checks: tuple[CommandResult, ...]) -> str:
    failures = [check.to_document() for check in checks if not check.passed]
    return (
        "The deterministic Framework rejected the current TaskSemantics project. "
        "Repair semantic code/dependencies/tests only; do not edit immutable Host inputs. "
        "Fix every complete factual failure in this turn:\n"
        + json.dumps(failures, ensure_ascii=False, sort_keys=True)
    )


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SemanticsAuthorFailure(
            "semantics_input",
            "semantics_input_invalid",
            f"Cannot read immutable input {path.name}",
            original_message=str(exc),
        ) from exc
    if not isinstance(value, dict):
        raise SemanticsAuthorFailure(
            "semantics_input",
            "semantics_input_invalid",
            f"Immutable input {path.name} must be an object",
        )
    return cast(dict[str, Any], value)
