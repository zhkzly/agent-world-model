"""Builder output contracts; candidates remain untrusted until Judge approval."""

from __future__ import annotations

import re
from pathlib import PurePosixPath
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator

from .base import ArtifactRef, Identifier, NonEmptyStr, V2Contract
from .task import (
    EVALUATOR_GOAL_PROJECTOR_VERSION,
    TASK_INSTRUCTION_RENDERER_VERSION,
)

WORLD_SPEC_PACKAGE_PATH = "world/world_spec.json"
RULE_IR_PACKAGE_PATH = "world/rule_ir.json"
TASK_MATERIALIZER_PROTOCOL_PACKAGE_PATH = "tasks/materializer_protocol.json"
CURRICULUM_PACKAGE_PATH = "tasks/curriculum.json"


def _relative_package_path(value: str) -> str:
    path = PurePosixPath(value)
    if path.is_absolute() or value in {"", ".", ".."} or ".." in path.parts:
        raise ValueError("path must be a non-empty package-relative POSIX path")
    if "\\" in value:
        raise ValueError("package paths must use POSIX separators")
    return value


def _python_module_for_path(value: str) -> str:
    path = PurePosixPath(_relative_package_path(value))
    if path.suffix != ".py":
        raise ValueError("Python entry path must end in .py")
    parts = list(path.with_suffix("").parts)
    if parts and parts[0] == "src":
        parts.pop(0)
    if parts and parts[-1] == "__main__":
        parts.pop()
    if not parts or any(re.fullmatch(r"[A-Za-z_]\w*", part) is None for part in parts):
        raise ValueError("Python entry path does not map to an importable module")
    return ".".join(parts)


class RuntimeLaunch(V2Contract):
    protocol: Literal["agent-world.runtime.v2"] = "agent-world.runtime.v2"
    transport: Literal["stdio-jsonl"] = "stdio-jsonl"
    argv: Annotated[tuple[NonEmptyStr, ...], Field(min_length=1)]
    workdir: NonEmptyStr = "."
    declared_environment_names: tuple[Identifier, ...] = ()
    startup_timeout_seconds: Annotated[float, Field(gt=0)] = 30
    request_timeout_seconds: Annotated[float, Field(gt=0)] = 30
    shutdown_timeout_seconds: Annotated[float, Field(gt=0)] = 10
    supported_operations: tuple[
        Literal["handshake", "reset", "invoke", "snapshot", "close"], ...
    ] = ("handshake", "reset", "invoke", "snapshot", "close")
    reward_authority: Literal["trusted_evaluator"] = "trusted_evaluator"
    runtime_reward_fields: Literal["diagnostic_only"] = "diagnostic_only"

    @field_validator("workdir")
    @classmethod
    def validate_workdir(cls, value: str) -> str:
        if value == ".":
            return value
        return _relative_package_path(value)

    @model_validator(mode="after")
    def validate_operations(self) -> RuntimeLaunch:
        required = ("handshake", "reset", "invoke", "snapshot", "close")
        if self.supported_operations != required:
            raise ValueError(f"runtime v2 operations are fixed to {required}")
        return self


class TaskMaterializerDescriptor(V2Contract):
    entrypoint: NonEmptyStr
    entry_path: NonEmptyStr
    protocol: Literal["python-callable-v3"] = "python-callable-v3"
    callable_name: Literal["materialize"] = "materialize"
    task_schema_version: Literal["task-materialization-v3"] = "task-materialization-v3"
    instruction_renderer: Literal["objective-public-goal-v1"] = (
        TASK_INSTRUCTION_RENDERER_VERSION
    )
    evaluator_goal_projector: Literal["identity-bindings-v1"] = (
        EVALUATOR_GOAL_PROJECTOR_VERSION
    )
    seed_type: Literal["uint64"] = "uint64"
    output_schema_ref: ArtifactRef
    curriculum_ref: ArtifactRef
    output_schema_path: Literal["tasks/materializer_protocol.json"] = (
        "tasks/materializer_protocol.json"
    )
    curriculum_path: Literal["tasks/curriculum.json"] = "tasks/curriculum.json"

    @field_validator("entry_path")
    @classmethod
    def validate_entry_path(cls, value: str) -> str:
        _python_module_for_path(value)
        return value

    @model_validator(mode="after")
    def validate_callable(self) -> TaskMaterializerDescriptor:
        pattern = r"^[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*:materialize$"
        if re.fullmatch(pattern, self.entrypoint) is None:
            raise ValueError("task materializer entrypoint must be package.module:materialize")
        module, _separator, function = self.entrypoint.partition(":")
        if function != self.callable_name or module != _python_module_for_path(self.entry_path):
            raise ValueError("task materializer entrypoint must match entry_path and callable_name")
        return self


class PublicSelfCheckDescriptor(V2Contract):
    """Framework-executed public diagnostic command shipped in envpkg v3."""

    protocol: Literal["python-module-v2"] = "python-module-v2"
    argv: Annotated[tuple[NonEmptyStr, ...], Field(min_length=3, max_length=3)]
    entry_path: NonEmptyStr
    timeout_seconds: Annotated[float, Field(gt=0, le=300)] = 60
    max_output_bytes: Annotated[int, Field(ge=1024, le=8 * 1024 * 1024)] = 1024 * 1024

    @field_validator("entry_path")
    @classmethod
    def validate_entry_path(cls, value: str) -> str:
        _python_module_for_path(value)
        return value

    @model_validator(mode="after")
    def validate_command(self) -> PublicSelfCheckDescriptor:
        if self.argv[0] not in {".venv/bin/python", ".venv/bin/python3"}:
            raise ValueError("public self-check must use the clean uv environment interpreter")
        if self.argv[1] != "-m" or self.argv[2] != _python_module_for_path(self.entry_path):
            raise ValueError("public self-check argv must be `python -m <entry_path module>`")
        return self


class EnvironmentCandidate(V2Contract):
    candidate_id: Identifier
    revision: Annotated[int, Field(ge=1)]
    design_ref: ArtifactRef
    implementation_contract_ref: ArtifactRef
    source_workspace_snapshot_ref: ArtifactRef
    build_artifact_ref: ArtifactRef
    runtime: RuntimeLaunch
    task_materializer: TaskMaterializerDescriptor
    public_self_check: PublicSelfCheckDescriptor
    public_verifier_ref: ArtifactRef
    candidate_manifest_ref: ArtifactRef
    implementation_lineage_ref: ArtifactRef


__all__ = [
    "EnvironmentCandidate",
    "CURRICULUM_PACKAGE_PATH",
    "PublicSelfCheckDescriptor",
    "RULE_IR_PACKAGE_PATH",
    "RuntimeLaunch",
    "TASK_MATERIALIZER_PROTOCOL_PACKAGE_PATH",
    "TaskMaterializerDescriptor",
    "WORLD_SPEC_PACKAGE_PATH",
]
