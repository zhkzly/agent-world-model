#!/usr/bin/env python3
"""Render the compact, frozen CandidateBuild acceptance map.

The map contains only inputs already mounted for a CandidateBuild Agent.  It
does not read a Candidate, run candidate code, or claim Validator, Integration,
Judge, or release success.  Its job is to make cross-file requirements visible
early enough for the Code Agent to turn them into its own local checks.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Finding:
    """One stable, agent-actionable frozen-input problem."""

    code: str
    path: str
    expected: str
    actual: str

    def render(self) -> str:
        return (
            f"ERROR {self.code} path={self.path} expected={self.expected!r} actual={self.actual!r}"
        )


def _load_object(path: Path, findings: list[Finding]) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        findings.append(Finding("json_unreadable", path.as_posix(), "JSON object", str(exc)))
        return {}
    if not isinstance(value, dict):
        findings.append(
            Finding("json_not_object", path.as_posix(), "JSON object", type(value).__name__)
        )
        return {}
    return value


def _string(
    value: object,
    *,
    path: str,
    findings: list[Finding],
    required: bool = True,
) -> str | None:
    if isinstance(value, str) and value:
        return value
    if required:
        findings.append(Finding("contract_field_invalid", path, "non-empty string", repr(value)))
    return None


def _positive_int(value: object, *, path: str, findings: list[Finding]) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    findings.append(Finding("contract_field_invalid", path, "positive integer", repr(value)))
    return None


def _string_list(value: object, *, path: str, findings: list[Finding]) -> tuple[str, ...]:
    if (
        not isinstance(value, list)
        or not value
        or any(not isinstance(item, str) or not item for item in value)
    ):
        findings.append(
            Finding("contract_field_invalid", path, "non-empty string array", repr(value))
        )
        return ()
    return tuple(value)


def _object_list(
    value: object, *, path: str, findings: list[Finding]
) -> tuple[dict[str, Any], ...]:
    if (
        not isinstance(value, list)
        or not value
        or any(not isinstance(item, dict) for item in value)
    ):
        findings.append(
            Finding("contract_field_invalid", path, "non-empty object array", repr(value))
        )
        return ()
    return tuple(value)


def contract_map(workspace: Path) -> tuple[tuple[str, ...], tuple[Finding, ...]]:
    """Return a concise input-only map and any malformed-input findings."""

    findings: list[Finding] = []
    inputs = workspace / "inputs"
    curriculum = _load_object(inputs / "curriculum.json", findings)
    contract = _load_object(inputs / "implementation-contract.json", findings)
    world_spec = _load_object(inputs / "world-spec.json", findings)
    if findings:
        return (), tuple(findings)

    python_requires = _string(
        contract.get("python_requires"),
        path="inputs/implementation-contract.json:/python_requires",
        findings=findings,
    )
    root_files = _string_list(
        contract.get("required_root_files"),
        path="inputs/implementation-contract.json:/required_root_files",
        findings=findings,
    )
    runtime = contract.get("runtime")
    if not isinstance(runtime, dict):
        findings.append(
            Finding(
                "contract_field_invalid",
                "inputs/implementation-contract.json:/runtime",
                "object",
                repr(runtime),
            )
        )
        runtime = {}
    abi = _string(
        runtime.get("abi_version"),
        path="inputs/implementation-contract.json:/runtime/abi_version",
        findings=findings,
    )
    operations = _object_list(
        runtime.get("operations"),
        path="inputs/implementation-contract.json:/runtime/operations",
        findings=findings,
    )
    operation_names: list[str] = []
    for index, item in enumerate(operations):
        name = _string(
            item.get("operation"),
            path=f"inputs/implementation-contract.json:/runtime/operations/{index}/operation",
            findings=findings,
        )
        if name is not None:
            operation_names.append(name)

    materializer = contract.get("task_materializer")
    if not isinstance(materializer, dict):
        findings.append(
            Finding(
                "contract_field_invalid",
                "inputs/implementation-contract.json:/task_materializer",
                "object",
                repr(materializer),
            )
        )
        materializer = {}
    output_fields = _string_list(
        materializer.get("candidate_output_fields"),
        path="inputs/implementation-contract.json:/task_materializer/candidate_output_fields",
        findings=findings,
    )
    materializer_task_types = _string_list(
        materializer.get("task_types"),
        path="inputs/implementation-contract.json:/task_materializer/task_types",
        findings=findings,
    )
    minimum_initials = _positive_int(
        curriculum.get("minimum_distinct_initial_states"),
        path="inputs/curriculum.json:/minimum_distinct_initial_states",
        findings=findings,
    )
    minimum_materializations = _positive_int(
        curriculum.get("minimum_distinct_tasks_per_type"),
        path="inputs/curriculum.json:/minimum_distinct_tasks_per_type",
        findings=findings,
    )
    dimensions = _object_list(
        curriculum.get("difficulty_dimensions"),
        path="inputs/curriculum.json:/difficulty_dimensions",
        findings=findings,
    )
    levels_by_dimension: dict[str, tuple[str, ...]] = {}
    for index, item in enumerate(dimensions):
        dimension = _string(
            item.get("dimension"),
            path=f"inputs/curriculum.json:/difficulty_dimensions/{index}/dimension",
            findings=findings,
        )
        levels = _string_list(
            item.get("levels"),
            path=f"inputs/curriculum.json:/difficulty_dimensions/{index}/levels",
            findings=findings,
        )
        if dimension is not None and levels:
            levels_by_dimension[dimension] = levels

    task_types = _object_list(
        curriculum.get("task_types"),
        path="inputs/curriculum.json:/task_types",
        findings=findings,
    )
    task_lines: list[str] = []
    for index, item in enumerate(task_types):
        task_type = _string(
            item.get("task_type"),
            path=f"inputs/curriculum.json:/task_types/{index}/task_type",
            findings=findings,
        )
        actors = _string_list(
            item.get("allowed_actor_ids"),
            path=f"inputs/curriculum.json:/task_types/{index}/allowed_actor_ids",
            findings=findings,
        )
        task_dimensions = _string_list(
            item.get("difficulty_dimensions"),
            path=f"inputs/curriculum.json:/task_types/{index}/difficulty_dimensions",
            findings=findings,
        )
        if task_type is None or not actors or not task_dimensions:
            continue
        unknown_dimensions = sorted(set(task_dimensions) - set(levels_by_dimension))
        if unknown_dimensions:
            findings.append(
                Finding(
                    "task_difficulty_dimension_unknown",
                    f"inputs/curriculum.json:/task_types/{index}/difficulty_dimensions",
                    "declared curriculum difficulty dimension",
                    ",".join(unknown_dimensions),
                )
            )
            continue
        difficulty = "; ".join(
            f"{dimension}=[{','.join(levels_by_dimension[dimension])}]"
            for dimension in task_dimensions
        )
        task_lines.append(
            f"  - task_type={task_type} actors=[{','.join(actors)}] difficulty={difficulty}"
        )

    world_tools = _object_list(
        world_spec.get("tools"),
        path="inputs/world-spec.json:/tools",
        findings=findings,
    )
    tool_ids: list[str] = []
    for index, tool in enumerate(world_tools):
        surface = tool.get("surface")
        if not isinstance(surface, dict):
            findings.append(
                Finding(
                    "contract_field_invalid",
                    f"inputs/world-spec.json:/tools/{index}/surface",
                    "ToolSurface object",
                    repr(surface),
                )
            )
            continue
        tool_id = _string(
            surface.get("tool_id"),
            path=f"inputs/world-spec.json:/tools/{index}/surface/tool_id",
            findings=findings,
        )
        if tool_id is not None:
            tool_ids.append(tool_id)

    if findings:
        return (), tuple(findings)
    if set(materializer_task_types) != {
        line.split("task_type=", 1)[1].split(" ", 1)[0] for line in task_lines
    }:
        findings.append(
            Finding(
                "task_type_closure_mismatch",
                "inputs/implementation-contract.json:/task_materializer/task_types",
                "same task-type set as inputs/curriculum.json:/task_types",
                ",".join(materializer_task_types),
            )
        )
        return (), tuple(findings)

    assert python_requires is not None
    assert abi is not None
    assert minimum_initials is not None
    assert minimum_materializations is not None
    base_count = max(2, minimum_initials, minimum_materializations)
    lines = (
        "CANDIDATE-CONTRACT-MAP v1",
        (
            "source=frozen-inputs only; this is not Candidate validation, Integration, "
            "Judge, or release evidence"
        ),
        (
            "project "
            f"python_requires={python_requires} root_files=[{','.join(root_files)}]"
        ),
        f"runtime abi={abi} operations=[{','.join(operation_names)}] tools=[{','.join(tool_ids)}]",
        f"materializer output_fields=[{','.join(output_fields)}]",
        "task-materializer campaign:",
        *task_lines,
        (
            "  - per task/actor run at least "
            f"{base_count} base seeds; assert exact call echo, JSON-safe deterministic output, "
            f"distinct initial_config>={minimum_initials}, and distinct full "
            f"materializations>={minimum_materializations}"
        ),
        (
            "  - for every listed difficulty dimension, call lowest and highest levels with "
            "the same seed; assert public_goal or initial_config changes"
        ),
        "  - rerun the same campaign after the final relevant source or metadata edit",
    )
    return lines, ()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, default=Path("."))
    args = parser.parse_args(argv)
    lines, findings = contract_map(args.workspace.resolve())
    if findings:
        for finding in findings:
            print(finding.render())
        print(f"FAILED candidate-contract-map findings={len(findings)}")
        return 1
    print("\n".join(lines))
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised as a standalone Skill script
    raise SystemExit(main())
