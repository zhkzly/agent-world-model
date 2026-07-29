"""Builder-private contracts for compiling one frozen EnvironmentDesign.

The completion contract deliberately contains only package-relative paths and
launch metadata.  Content hashes, ArtifactRefs, lineage, candidate manifests,
Judge evidence, and release decisions are authored by framework code after the
workspace has been inspected.
"""

from __future__ import annotations

import copy
import re
import unicodedata
from pathlib import PurePosixPath
from typing import Annotated, Literal, cast

from pydantic import AwareDatetime, Field, JsonValue, field_validator, model_validator
from pydantic_core import PydanticCustomError

from agent_world.agent_output_authority import (
    AgentOutputAuthority,
    SemanticAdvisoryOutput,
    WorkspaceProposalOutput,
    register_agent_output_contract,
)
from agent_world.contracts import (
    ArtifactRef,
    ContentHash,
    Identifier,
    NonEmptyStr,
    PackageFile,
    V2Contract,
)
from agent_world.contracts.supply_chain import MAX_PUBLIC_TESTS

RUNTIME_ABI_V2 = "agent-world.runtime.v2"
RUNTIME_OPERATIONS = ("handshake", "reset", "invoke", "snapshot", "close")

type CandidateFileRole = Literal[
    "runtime",
    "task_materializer",
    "public_verifier",
    "dependency_lock",
    "documentation",
    "public_test",
    "configuration",
    "license",
]


class _PythonEntryPathError(ValueError):
    """One safe, typed failure while deriving a Python module from a path."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class _PythonLaunchError(ValueError):
    """One safe, typed failure in a candidate Python launch declaration."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


_PYTHON_ENTRY_PATH_MESSAGES = {
    "python_entry_path_invalid": (
        "Python entry path must be a normalized package-relative POSIX `.py` path"
    ),
    "python_entry_path_not_importable": "Python entry path must map to an importable Python module",
}
_PYTHON_LAUNCH_MESSAGES = {
    "python_launch_interpreter_invalid": (
        "Python launch argv must start with the clean uv environment interpreter"
    ),
    "python_launch_argument_invalid": "Python launch argv contains an unsafe argument",
    "python_launch_entrypoint_mismatch": (
        "Python launch argv must run the declared entry path with `python -m package.module`"
    ),
}


def validate_relative_path(value: str, *, allow_dot: bool = False) -> str:
    """Validate a portable path without consulting the host filesystem."""

    if (
        not value
        or "\\" in value
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise ValueError("path must be a non-empty package-relative POSIX path")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError("path must not be absolute or contain '..'")
    if value == ".":
        if allow_dot:
            return value
        raise ValueError("'.' is not a file path")
    if any(part in {"", "."} for part in path.parts):
        raise ValueError("path must be normalized")
    if path.as_posix() != value:
        raise ValueError("path must be normalized POSIX text")
    return value


def _module_name_for_path(value: str) -> str:
    try:
        path = PurePosixPath(validate_relative_path(value))
    except ValueError as exc:
        raise _PythonEntryPathError("python_entry_path_invalid") from exc
    if path.suffix != ".py":
        raise _PythonEntryPathError("python_entry_path_invalid")
    parts = list(path.with_suffix("").parts)
    if parts and parts[0] == "src":
        parts.pop(0)
    if parts and parts[-1] == "__main__":
        parts.pop()
    if not parts or any(re.fullmatch(r"[A-Za-z_]\w*", part) is None for part in parts):
        raise _PythonEntryPathError("python_entry_path_not_importable")
    return ".".join(parts)


def _validate_candidate_relative_path(value: str) -> str:
    """Expose path-format failures as safe CandidateCompletion diagnostics."""

    try:
        return validate_relative_path(value)
    except ValueError as exc:
        raise PydanticCustomError(
            "candidate_path_invalid",
            "candidate paths must be normalized package-relative POSIX paths",
        ) from exc


def _validate_python_entry_path(value: str) -> str:
    """Require both a portable source path and an importable Python module."""

    try:
        _module_name_for_path(value)
    except _PythonEntryPathError as exc:
        raise PydanticCustomError(exc.code, _PYTHON_ENTRY_PATH_MESSAGES[exc.code]) from exc
    return value


def _validate_python_argv(argv: tuple[str, ...], entry_path: str) -> None:
    if argv[0] not in {".venv/bin/python", ".venv/bin/python3"}:
        raise _PythonLaunchError("python_launch_interpreter_invalid")
    if any("\x00" in item or "\\" in item or len(item) > 512 for item in argv):
        raise _PythonLaunchError("python_launch_argument_invalid")
    if any(PurePosixPath(item).is_absolute() or ".." in PurePosixPath(item).parts for item in argv):
        raise _PythonLaunchError("python_launch_argument_invalid")
    expected_module = _module_name_for_path(entry_path)
    if len(argv) < 3 or argv[1] != "-m" or argv[2] != expected_module:
        raise _PythonLaunchError("python_launch_entrypoint_mismatch")


def _validate_python_launch(argv: tuple[str, ...], entry_path: str) -> None:
    """Convert launch mechanics into field-addressable structured diagnostics."""

    try:
        _validate_python_argv(argv, entry_path)
    except _PythonLaunchError as exc:
        raise PydanticCustomError(exc.code, _PYTHON_LAUNCH_MESSAGES[exc.code]) from exc


class RuntimeOperationContract(V2Contract):
    operation: Literal["handshake", "reset", "invoke", "snapshot", "close"]
    request_payload: dict[str, JsonValue]
    result_requirements: Annotated[tuple[NonEmptyStr, ...], Field(min_length=1)]


class RuntimeWireContract(V2Contract):
    """Framework-authored wire contract; candidate code cannot weaken it."""

    abi_version: Literal["agent-world.runtime.v2"] = "agent-world.runtime.v2"
    transport: Literal["stdio-jsonl"] = "stdio-jsonl"
    request_envelope_keys: tuple[Identifier, ...] = (
        "abi_version",
        "request_id",
        "operation",
        "payload",
    )
    response_required_keys: tuple[Identifier, ...] = (
        "abi_version",
        "request_id",
        "operation",
        "ok",
    )
    response_optional_keys: tuple[Identifier, ...] = ("result", "error")
    operations: Annotated[tuple[RuntimeOperationContract, ...], Field(min_length=5)]
    one_request_one_response: bool = True
    stdout_is_protocol_only: bool = True

    @model_validator(mode="after")
    def validate_operations(self) -> RuntimeWireContract:
        operations = tuple(item.operation for item in self.operations)
        if operations != RUNTIME_OPERATIONS:
            raise ValueError(f"runtime operations must be exactly {RUNTIME_OPERATIONS}")
        return self


class ToolBindingRequirement(V2Contract):
    tool_id: Identifier
    tool_contract_hash: ContentHash


class TaskMaterializerContract(V2Contract):
    protocol: Literal["python-callable-v3"] = "python-callable-v3"
    callable_name: Literal["materialize"] = "materialize"
    callable_signature: Literal[
        "materialize(seed: int, task_type: str, actor: str, difficulty: object) "
        "-> task-materialization-v3"
    ] = (
        "materialize(seed: int, task_type: str, actor: str, difficulty: object) "
        "-> task-materialization-v3"
    )
    task_schema_version: Literal["task-materialization-v3"] = "task-materialization-v3"
    seed_type: Literal["uint64"] = "uint64"
    task_types: Annotated[tuple[Identifier, ...], Field(min_length=1)]
    minimum_distinct_initial_states: Annotated[int, Field(ge=2)]
    minimum_distinct_tasks_per_type: Annotated[int, Field(ge=2)]
    candidate_output_fields: tuple[
        Literal[
            "schema_version",
            "task_schema_version",
            "seed",
            "task_type",
            "actor",
            "difficulty",
            "public_goal",
            "initial_config",
        ],
        ...,
    ] = (
        "schema_version",
        "task_schema_version",
        "seed",
        "task_type",
        "actor",
        "difficulty",
        "public_goal",
        "initial_config",
    )
    framework_renders_public_instruction: Literal[True] = True
    same_seed_difficulty_contrast_required: Literal[True] = True

    @model_validator(mode="after")
    def validate_fixed_boundary(self) -> TaskMaterializerContract:
        expected_fields = (
            "schema_version",
            "task_schema_version",
            "seed",
            "task_type",
            "actor",
            "difficulty",
            "public_goal",
            "initial_config",
        )
        if self.candidate_output_fields != expected_fields:
            raise ValueError("Task Materializer v3 candidate output fields are fixed")
        if len(set(self.task_types)) != len(self.task_types):
            raise ValueError("Task Materializer task types must be unique")
        return self


class ImplementationContract(V2Contract):
    """Deterministic framework instruction compiled from EnvironmentDesign."""

    contract_id: Identifier
    design_ref: ArtifactRef
    world_spec_hash: ContentHash
    state_schema_hash: ContentHash
    curriculum_hash: ContentHash
    project_format: Literal["python-uv"] = "python-uv"
    project_root: Literal["candidate"] = "candidate"
    required_root_files: tuple[Literal["pyproject.toml", "uv.lock", "LICENSE"], ...] = (
        "pyproject.toml",
        "uv.lock",
        "LICENSE",
    )
    python_requires: Literal[">=3.12,<3.13"] = ">=3.12,<3.13"
    root_project_mode: Literal["virtual-read-only-source-tree"] = "virtual-read-only-source-tree"
    dependency_install_mode: Literal["offline-wheel-only"] = "offline-wheel-only"
    source_builds: Literal["prohibited"] = "prohibited"
    install_network: Literal["disabled"] = "disabled"
    required_license_role: Literal["license"] = "license"
    runtime: RuntimeWireContract
    tools: Annotated[tuple[ToolBindingRequirement, ...], Field(min_length=1)]
    task_materializer: TaskMaterializerContract
    public_artifacts: tuple[
        Literal["task_materializer", "public_verifier", "public_tests"],
        ...,
    ] = ("task_materializer", "public_verifier", "public_tests")

    @model_validator(mode="after")
    def validate_contract(self) -> ImplementationContract:
        if self.required_root_files != ("pyproject.toml", "uv.lock", "LICENSE"):
            raise ValueError("Python uv candidates require pyproject.toml, uv.lock, and LICENSE")
        tool_ids = [item.tool_id for item in self.tools]
        if len(set(tool_ids)) != len(tool_ids):
            raise ValueError("tool bindings must be unique")
        if self.public_artifacts != ("task_materializer", "public_verifier", "public_tests"):
            raise ValueError("Builder public artifacts are fixed for envpkg v3")
        return self


class ImplementationPlanDraft(SemanticAdvisoryOutput, V2Contract):
    """Text-first Engineer preparation for one later CandidateBuild turn.

    This is deliberately advisory: it can improve a later Agent's working
    plan, but cannot declare candidate files, alter frozen semantics, or carry
    scheduler/release authority.
    """

    implementation_strategy: Annotated[NonEmptyStr, Field(max_length=12_000)]


class ImplementationPlan(V2Contract):
    """Framework-bound advisory plan for one exact Design/contract closure."""

    plan_id: Identifier
    design_ref: ArtifactRef
    implementation_contract_ref: ArtifactRef
    world_spec_hash: ContentHash
    curriculum_hash: ContentHash
    implementation_strategy: Annotated[NonEmptyStr, Field(max_length=12_000)]

    @model_validator(mode="after")
    def validate_bindings(self) -> ImplementationPlan:
        if self.design_ref.artifact_type not in {
            "design.environment_design",
            "expansion.environment_design",
        }:
            raise ValueError("implementation plan must bind one EnvironmentDesign")
        if self.implementation_contract_ref.artifact_type != "build.implementation_contract":
            raise ValueError("implementation plan must bind one ImplementationContract")
        return self


register_agent_output_contract(
    ImplementationPlanDraft,
    authority=AgentOutputAuthority.SEMANTIC_ADVISORY,
)


class CandidateFileDeclaration(V2Contract):
    """Agent declaration of one relative file; hashes and modes are framework-owned."""

    path: NonEmptyStr
    role: CandidateFileRole

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        return _validate_candidate_relative_path(value)


class CandidateRuntimeDeclaration(V2Contract):
    protocol: Literal["agent-world.runtime.v2"] = "agent-world.runtime.v2"
    transport: Literal["stdio-jsonl"] = "stdio-jsonl"
    argv: Annotated[tuple[NonEmptyStr, ...], Field(min_length=2, max_length=32)]
    workdir: Literal["."] = "."
    entry_path: NonEmptyStr
    startup_timeout_seconds: Annotated[float, Field(gt=0, le=300)] = 30
    request_timeout_seconds: Annotated[float, Field(gt=0, le=300)] = 30
    shutdown_timeout_seconds: Annotated[float, Field(gt=0, le=60)] = 10

    @field_validator("entry_path")
    @classmethod
    def validate_entry_path(cls, value: str) -> str:
        return _validate_python_entry_path(value)

    @model_validator(mode="after")
    def validate_launch(self) -> CandidateRuntimeDeclaration:
        _validate_python_launch(self.argv, self.entry_path)
        return self


class CandidateTaskMaterializerDeclaration(V2Contract):
    protocol: Literal["python-callable-v3"] = "python-callable-v3"
    entrypoint: NonEmptyStr
    entry_path: NonEmptyStr

    @field_validator("entrypoint")
    @classmethod
    def validate_entrypoint(cls, value: str) -> str:
        pattern = r"^[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*:materialize$"
        if re.fullmatch(pattern, value) is None:
            raise PydanticCustomError(
                "task_materializer_entrypoint_format",
                "task materializer entrypoint must be package.module:materialize",
            )
        return value

    @field_validator("entry_path")
    @classmethod
    def validate_entry_path(cls, value: str) -> str:
        return _validate_python_entry_path(value)

    @model_validator(mode="after")
    def validate_module_matches_path(self) -> CandidateTaskMaterializerDeclaration:
        module, _separator, _function = self.entrypoint.partition(":")
        expected_module = _module_name_for_path(self.entry_path)
        if module != expected_module:
            raise PydanticCustomError(
                "task_materializer_binding_mismatch",
                "task materializer entrypoint module does not match entry_path",
            )
        return self


class CandidatePublicSelfCheckDeclaration(V2Contract):
    argv: Annotated[tuple[NonEmptyStr, ...], Field(min_length=3, max_length=3)]
    entry_path: NonEmptyStr

    @field_validator("entry_path")
    @classmethod
    def validate_entry_path(cls, value: str) -> str:
        return _validate_python_entry_path(value)

    @model_validator(mode="after")
    def validate_launch(self) -> CandidatePublicSelfCheckDeclaration:
        _validate_python_launch(self.argv, self.entry_path)
        return self


def normalize_candidate_completion_output(value: JsonValue) -> JsonValue:
    """Canonicalize only uniquely witnessed, framework-owned declaration syntax.

    The Engineer writes physical files below the workspace's outer ``candidate/``
    directory, while every completion path is relative to that directory.  A model
    can therefore consistently add one outer prefix to every ``files[*].path`` even
    when the real import package is also named ``candidate``.  Strip that outer
    namespace only when the complete declaration closure proves the mapping; never
    inspect or mutate the filesystem here.  Physical closure remains the independent
    responsibility of :class:`CandidateWorkspaceValidator`.

    File executable mode is likewise a physical property of the final
    workspace, which the framework derives while it validates and packages the
    candidate. Drop a legacy Agent-supplied ``files[*].executable`` spelling:
    it cannot alter the resulting manifest and must not become a second source
    of truth for a file mode.

    The callable name ``materialize`` is fixed by the implementation contract.
    Its module is uniquely derived from one lexically importable ``entry_path``;
    normalize any ``*:materialize`` spelling to that canonical representation
    without asking an Agent to make a semantic choice. An arbitrary callable
    remains invalid. Component declarations and file roles also repeat one fixed
    relationship. Normalize that relationship only when every referenced path is
    unique and no path claims conflicting component roles.
    """

    if not isinstance(value, dict):
        return value
    proposal = copy.deepcopy(value)
    if proposal.get("status") != "completed" or proposal.get("project_root") != "candidate":
        return proposal

    files = proposal.get("files")
    if isinstance(files, list):
        for declaration in files:
            if isinstance(declaration, dict):
                # Mode belongs to the physical regular file, not an Agent
                # declaration. This exact legacy field is safe to discard
                # before strict structured-output validation.
                declaration.pop("executable", None)
    if isinstance(files, list) and files:
        declarations = tuple(item for item in files if isinstance(item, dict))
        raw_paths = tuple(item.get("path") for item in declarations)
        prefix = "candidate/"
        can_strip_file_namespace = len(declarations) == len(files) and all(
            isinstance(path, str) and path.startswith(prefix) for path in raw_paths
        )
        if can_strip_file_namespace:
            stripped_paths = tuple(str(path)[len(prefix) :] for path in raw_paths)
            required_roots = {"pyproject.toml", "uv.lock", "LICENSE"}
            can_strip_file_namespace = (
                all(stripped_paths)
                and len(set(stripped_paths)) == len(stripped_paths)
                and required_roots.issubset(stripped_paths)
            )
        if can_strip_file_namespace:
            roles_by_path = {
                stripped: declaration.get("role")
                for stripped, declaration in zip(stripped_paths, declarations, strict=True)
            }

            def resolve_declared_path(raw: object, role: str) -> str | None:
                if not isinstance(raw, str):
                    return None
                raw_match = roles_by_path.get(raw) == role
                stripped = raw[len(prefix) :] if raw.startswith(prefix) else raw
                stripped_match = stripped != raw and roles_by_path.get(stripped) == role
                if raw_match:
                    return raw
                if not stripped_match:
                    return None
                return stripped

            components = (
                ("runtime", "runtime"),
                ("task_materializer", "task_materializer"),
                ("public_self_check", "public_verifier"),
            )
            resolved_components: dict[str, str] = {}
            for field, role in components:
                declaration = proposal.get(field)
                if not isinstance(declaration, dict):
                    break
                resolved = resolve_declared_path(declaration.get("entry_path"), role)
                if resolved is None:
                    break
                resolved_components[field] = resolved
            else:
                public_tests = proposal.get("public_test_paths")
                if isinstance(public_tests, list):
                    resolved_tests = tuple(
                        resolve_declared_path(path, "public_test") for path in public_tests
                    )
                    if all(path is not None for path in resolved_tests):
                        for declaration, stripped in zip(
                            declarations,
                            stripped_paths,
                            strict=True,
                        ):
                            declaration["path"] = stripped
                        for field, resolved in resolved_components.items():
                            component = proposal[field]
                            assert isinstance(component, dict)
                            component["entry_path"] = resolved
                        proposal["public_test_paths"] = list(resolved_tests)

    files = proposal.get("files")
    if isinstance(files, list) and all(isinstance(item, dict) for item in files):
        file_declarations = cast(list[dict[str, JsonValue]], files)
        by_path: dict[str, dict[str, JsonValue]] = {}
        for declaration in file_declarations:
            path = declaration.get("path")
            if not isinstance(path, str) or path in by_path:
                break
            by_path[path] = declaration
        else:
            role_claims: list[tuple[str, str]] = [
                ("pyproject.toml", "configuration"),
                ("uv.lock", "dependency_lock"),
                ("LICENSE", "license"),
            ]
            components = (
                ("runtime", "runtime"),
                ("task_materializer", "task_materializer"),
                ("public_self_check", "public_verifier"),
            )
            claims_complete = True
            for field, role in components:
                component = proposal.get(field)
                entry_path = component.get("entry_path") if isinstance(component, dict) else None
                if not isinstance(entry_path, str):
                    claims_complete = False
                    break
                role_claims.append((entry_path, role))
            public_tests = proposal.get("public_test_paths")
            if not isinstance(public_tests, list) or any(
                not isinstance(path, str) for path in public_tests
            ):
                claims_complete = False
            else:
                role_claims.extend((cast(str, path), "public_test") for path in public_tests)

            roles_by_claimed_path: dict[str, set[str]] = {}
            for path, role in role_claims:
                roles_by_claimed_path.setdefault(path, set()).add(role)
            if (
                claims_complete
                and all(len(roles) == 1 for roles in roles_by_claimed_path.values())
                and all(path in by_path for path in roles_by_claimed_path)
            ):
                for path, roles in roles_by_claimed_path.items():
                    by_path[path]["role"] = next(iter(roles))

    task_materializer = proposal.get("task_materializer")
    if isinstance(task_materializer, dict):
        entrypoint = task_materializer.get("entrypoint")
        materialize_callable = entrypoint == "materialize" or (
            isinstance(entrypoint, str) and entrypoint.endswith(":materialize")
        )
        entry_path = task_materializer.get("entry_path")
        declared_task_paths = (
            {
                item.get("path")
                for item in files
                if isinstance(item, dict) and item.get("role") == "task_materializer"
            }
            if isinstance(files, list)
            else set()
        )
        if (
            materialize_callable
            and isinstance(entry_path, str)
            and entry_path in declared_task_paths
        ):
            try:
                module = _module_name_for_path(entry_path)
            except ValueError:
                pass
            else:
                task_materializer["entrypoint"] = f"{module}:materialize"
    return proposal


class CandidateCompletion(WorkspaceProposalOutput, V2Contract):
    """The only structured object an Engineer may claim after a turn."""

    status: Literal["completed", "blocked"]
    blocking_reason: NonEmptyStr | None = None
    project_root: Literal["candidate"] | None = None
    root_project_mode: Literal["virtual-read-only-source-tree"] | None = None
    dependency_install_mode: Literal["offline-wheel-only"] | None = None
    runtime: CandidateRuntimeDeclaration | None = None
    task_materializer: CandidateTaskMaterializerDeclaration | None = None
    public_self_check: CandidatePublicSelfCheckDeclaration | None = None
    public_test_paths: Annotated[
        tuple[NonEmptyStr, ...],
        Field(max_length=MAX_PUBLIC_TESTS),
    ] = ()
    files: tuple[CandidateFileDeclaration, ...] = ()

    @field_validator("public_test_paths")
    @classmethod
    def validate_public_test_paths(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(_validate_candidate_relative_path(value) for value in values)

    @model_validator(mode="after")
    def validate_status_and_declarations(self) -> CandidateCompletion:
        if self.status == "blocked":
            if self.blocking_reason is None:
                raise PydanticCustomError(
                    "completion_blocking_reason_missing",
                    "blocked completion requires blocking_reason",
                )
            if (
                any(
                    value is not None
                    for value in (
                        self.project_root,
                        self.root_project_mode,
                        self.dependency_install_mode,
                        self.runtime,
                        self.task_materializer,
                        self.public_self_check,
                    )
                )
                or self.public_test_paths
                or self.files
            ):
                raise PydanticCustomError(
                    "completion_blocked_claims_outputs",
                    "blocked completion cannot claim candidate outputs",
                )
            return self

        if self.blocking_reason is not None:
            raise PydanticCustomError(
                "completion_completed_has_blocker",
                "completed output cannot include blocking_reason",
            )
        required = {
            "project_root": self.project_root,
            "root_project_mode": self.root_project_mode,
            "dependency_install_mode": self.dependency_install_mode,
            "runtime": self.runtime,
            "task_materializer": self.task_materializer,
            "public_self_check": self.public_self_check,
        }
        missing = sorted(key for key, value in required.items() if value is None)
        if missing:
            raise PydanticCustomError(
                "completion_missing_declarations",
                "completed output is missing required declarations",
            )
        if not self.public_test_paths:
            raise PydanticCustomError(
                "completion_public_tests_missing",
                "completed output requires at least one public test",
            )
        if not self.files:
            raise PydanticCustomError(
                "completion_files_missing",
                "completed output requires declared files",
            )

        runtime = self.runtime
        task_materializer = self.task_materializer
        public_self_check = self.public_self_check
        if runtime is None or task_materializer is None or public_self_check is None:
            raise AssertionError("completed declaration validation lost a required output")

        by_path = {item.path: item for item in self.files}
        if len(by_path) != len(self.files):
            raise PydanticCustomError(
                "completion_file_declarations_duplicate",
                "candidate file declarations must be unique",
            )
        required_roles = {
            "pyproject.toml": "configuration",
            "uv.lock": "dependency_lock",
            "LICENSE": "license",
            runtime.entry_path: "runtime",
            task_materializer.entry_path: "task_materializer",
            public_self_check.entry_path: "public_verifier",
        }
        for path, role in required_roles.items():
            declaration = by_path.get(str(path))
            if declaration is None or declaration.role != role:
                raise PydanticCustomError(
                    "completion_required_role_missing",
                    "a required component path is missing its fixed file role",
                )
        for path in self.public_test_paths:
            declaration = by_path.get(path)
            if declaration is None or declaration.role != "public_test":
                raise PydanticCustomError(
                    "completion_public_test_role_invalid",
                    "every public test path must be declared with role public_test",
                )
        return self


register_agent_output_contract(
    CandidateCompletion,
    authority=AgentOutputAuthority.WORKSPACE_PROPOSAL,
)


class BuildRecord(V2Contract):
    """Public build evidence without Agent transcript or workspace paths."""

    build_id: Identifier
    candidate_id: Identifier
    candidate_revision: Annotated[int, Field(ge=1)]
    implementation_contract_ref: ArtifactRef
    source_snapshot_ref: ArtifactRef
    completion_hash: ContentHash
    files: Annotated[tuple[PackageFile, ...], Field(min_length=1)]
    validations: Annotated[tuple[Identifier, ...], Field(min_length=1)]
    agent_turn_number: Annotated[int, Field(ge=1)]
    public_self_check_argv: Annotated[tuple[NonEmptyStr, ...], Field(min_length=3)]


class BuilderWorkspaceProgress(V2Contract):
    """Content-free heartbeat proving whether a long codegen workspace changed."""

    run_id: Identifier
    attempt_id: Identifier
    lineage_id: NonEmptyStr
    observed_at: AwareDatetime
    status: Literal["turn_started", "changed", "steady", "turn_terminal", "unavailable"]
    file_count: Annotated[int, Field(ge=0)]
    total_bytes: Annotated[int, Field(ge=0)]
    metadata_digest: ContentHash | None = None
    error_code: Identifier | None = None

    @model_validator(mode="after")
    def validate_progress_shape(self) -> BuilderWorkspaceProgress:
        if self.status == "unavailable" and self.error_code is None:
            raise ValueError("unavailable workspace progress requires an error code")
        if self.status != "unavailable" and self.error_code is not None:
            raise ValueError("workspace progress error code is only valid when unavailable")
        if self.status != "unavailable" and self.metadata_digest is None:
            raise ValueError("available workspace progress requires a metadata digest")
        return self


class RepairDisclosure(V2Contract):
    """Minimal Engineer-visible projection of a framework Finding."""

    disclosure_id: Identifier
    category: Identifier
    severity: Literal["info", "low", "medium", "high", "critical"]
    disclosure: Literal["public", "repair", "sealed_summary"]
    summary: NonEmptyStr
    suggested_repair: NonEmptyStr | None = None

    @field_validator("summary", "suggested_repair")
    @classmethod
    def reject_private_evaluation_details(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = re.sub(r"[\s-]+", "_", unicodedata.normalize("NFKC", value).casefold())
        forbidden = (
            "case_id",
            "case_label",
            "evaluator_goal",
            "expected_answer",
            "expected_output",
            "expected_path",
            "expected_state",
            "evaluation_witness",
            "oracle",
            "private_goal",
            "sealed_case",
            "sealed_data",
            "verifier_ir",
        )
        if any(term in normalized for term in forbidden):
            raise ValueError("repair disclosure contains private evaluation vocabulary")
        return value

    @model_validator(mode="after")
    def protect_sealed_summary(self) -> RepairDisclosure:
        if self.disclosure == "sealed_summary" and self.suggested_repair is not None:
            raise ValueError("sealed summaries cannot include a suggested repair payload")
        return self


__all__ = [
    "BuildRecord",
    "BuilderWorkspaceProgress",
    "CandidateCompletion",
    "CandidateFileDeclaration",
    "CandidateFileRole",
    "CandidatePublicSelfCheckDeclaration",
    "CandidateRuntimeDeclaration",
    "CandidateTaskMaterializerDeclaration",
    "ImplementationContract",
    "ImplementationPlan",
    "ImplementationPlanDraft",
    "RUNTIME_ABI_V2",
    "RUNTIME_OPERATIONS",
    "RepairDisclosure",
    "RuntimeOperationContract",
    "RuntimeWireContract",
    "TaskMaterializerContract",
    "ToolBindingRequirement",
    "normalize_candidate_completion_output",
    "validate_relative_path",
]
