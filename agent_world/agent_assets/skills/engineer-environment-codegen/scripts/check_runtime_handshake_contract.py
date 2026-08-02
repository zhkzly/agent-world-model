#!/usr/bin/env python3
"""Check one Candidate Runtime handshake against its frozen WorldSpec surface.

This is a build-time Code-Agent diagnostic. It starts the Candidate command
selected by the Engineer and compares only the framework-owned public tool
projection; it neither evaluates domain transitions nor claims Integration,
Judge, or release success.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast


@dataclass(frozen=True)
class Finding:
    """A stable, Candidate-actionable handshake difference."""

    code: str
    path: str
    expected: str
    actual: str

    def render(self) -> str:
        return (
            f"ERROR {self.code} path={self.path} expected={self.expected!r} actual={self.actual!r}"
        )


class HandshakeContractError(ValueError):
    """Expected local preflight failure without raw Candidate process output."""

    def __init__(self, finding: Finding) -> None:
        super().__init__(finding.code)
        self.finding = finding


def _finding(code: str, path: str, expected: str, actual: object) -> HandshakeContractError:
    return HandshakeContractError(Finding(code, path, expected, _safe_actual(actual)))


def _safe_actual(value: object) -> str:
    if isinstance(value, str):
        return value if len(value) <= 96 else "string"
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int | float):
        return "number"
    if isinstance(value, list):
        return f"array[{len(value)}]"
    if isinstance(value, Mapping):
        return "object"
    return type(value).__name__


def _load_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise _finding(
            "world_spec_unreadable",
            path.as_posix(),
            "readable frozen JSON object",
            type(exc).__name__,
        ) from exc
    if not isinstance(value, dict):
        raise _finding("world_spec_not_object", path.as_posix(), "JSON object", value)
    return value


def _canonical(value: object, *, path: str) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise _finding(
            "schema_not_json",
            path,
            "canonical JSON value",
            type(value).__name__,
        ) from exc


def _first_difference(expected: object, actual: object, *, path: str) -> str | None:
    """Return one value-free, reproducible nested difference coordinate."""

    if type(expected) is not type(actual):
        return path
    if isinstance(expected, Mapping):
        expected_mapping = cast(Mapping[str, object], expected)
        actual_mapping = cast(Mapping[str, object], actual)
        expected_keys = set(expected_mapping)
        actual_keys = set(actual_mapping)
        for key in sorted(expected_keys - actual_keys):
            return f"{path}/{key}"
        for key in sorted(actual_keys - expected_keys):
            return f"{path}/{key}"
        for key in sorted(expected_keys):
            difference = _first_difference(
                expected_mapping[key],
                actual_mapping[key],
                path=f"{path}/{key}",
            )
            if difference is not None:
                return difference
        return None
    if isinstance(expected, list):
        expected_list = cast(list[object], expected)
        actual_list = cast(list[object], actual)
        if len(expected_list) != len(actual_list):
            return f"{path}/length"
        for index, (expected_item, actual_item) in enumerate(
            zip(expected_list, actual_list, strict=True)
        ):
            difference = _first_difference(expected_item, actual_item, path=f"{path}/{index}")
            if difference is not None:
                return difference
        return None
    return None if expected == actual else path


def _expected_tools(workspace: Path) -> dict[str, dict[str, object]]:
    world_spec = _load_object(workspace / "inputs" / "world-spec.json")
    raw_tools = world_spec.get("tools")
    if not isinstance(raw_tools, list):
        raise _finding(
            "world_spec_tools_invalid",
            "inputs/world-spec.json:/tools",
            "array of tool records",
            raw_tools,
        )
    expected: dict[str, dict[str, object]] = {}
    for index, raw_tool in enumerate(raw_tools):
        path = f"inputs/world-spec.json:/tools/{index}"
        if not isinstance(raw_tool, Mapping) or not isinstance(raw_tool.get("surface"), Mapping):
            raise _finding(
                "world_spec_surface_invalid", path, "tool record with surface object", raw_tool
            )
        surface = raw_tool["surface"]
        tool_id = surface.get("tool_id")
        if not isinstance(tool_id, str) or not tool_id or tool_id in expected:
            raise _finding(
                "world_spec_tool_id_invalid",
                f"{path}/surface/tool_id",
                "unique non-empty string",
                tool_id,
            )
        contract: dict[str, object] = {}
        for field in (
            "namespace",
            "name",
            "input_schema",
            "output_schema",
            "observation_schema",
        ):
            if field not in surface:
                raise _finding(
                    "world_spec_surface_field_missing",
                    f"{path}/surface/{field}",
                    "present",
                    "missing",
                )
            contract[field] = surface[field]
            _canonical(surface[field], path=f"{path}/surface/{field}")
        expected[tool_id] = contract
    return expected


def _candidate_import_root(workspace: Path, import_root: str) -> Path:
    candidate = (workspace / "candidate").resolve()
    relative = Path(import_root)
    resolved = (workspace / relative).resolve()
    if (
        relative.is_absolute()
        or ".." in relative.parts
        or not resolved.is_dir()
        or candidate not in (resolved, *resolved.parents)
    ):
        raise _finding(
            "candidate_import_root_invalid",
            "--import-root",
            "existing workspace-relative directory inside candidate/",
            import_root,
        )
    return resolved


def _runtime_command(workspace: Path, raw_argv: Sequence[str]) -> tuple[str, ...]:
    if not raw_argv:
        raise _finding("runtime_argv_missing", "--runtime-argv", "non-empty command", "empty")
    command = list(raw_argv)
    executable = Path(command[0])
    if not executable.is_absolute() and len(executable.parts) > 1:
        if ".." in executable.parts:
            raise _finding(
                "runtime_argv_invalid",
                "--runtime-argv/0",
                "candidate-relative executable",
                command[0],
            )
        command[0] = str((workspace / "candidate" / executable).resolve())
    return tuple(command)


def _handshake_response(
    *,
    workspace: Path,
    import_root: Path,
    command: Sequence[str],
    timeout_seconds: float,
) -> object:
    environment = dict(os.environ)
    with tempfile.TemporaryDirectory(
        prefix="candidate-handshake-state-", dir=workspace
    ) as state_dir:
        environment["AGENT_WORLD_STATE_DIR"] = state_dir
        try:
            completed = subprocess.run(  # noqa: S603 - Agent chooses its local Candidate command
                command,
                cwd=import_root,
                input=json.dumps(
                    {
                        "abi_version": "agent-world.runtime.v2",
                        "request_id": "candidate-contract-map",
                        "operation": "handshake",
                        "payload": {},
                    },
                    separators=(",", ":"),
                )
                + "\n",
                text=True,
                capture_output=True,
                timeout=timeout_seconds,
                env=environment,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise _finding(
                "runtime_handshake_timeout",
                "handshake",
                f"one response within {timeout_seconds:g} seconds",
                "timeout",
            ) from exc
        except OSError as exc:
            raise _finding(
                "runtime_handshake_launch_failed",
                "--runtime-argv",
                "launchable Candidate Runtime command",
                type(exc).__name__,
            ) from exc
    if completed.returncode != 0:
        raise _finding(
            "runtime_handshake_command_failed",
            "handshake",
            "zero-exit Runtime handshake command",
            f"exit_code={completed.returncode}",
        )
    lines = [line for line in completed.stdout.splitlines() if line.strip()]
    if len(lines) != 1:
        raise _finding(
            "runtime_handshake_response_count",
            "handshake/stdout",
            "exactly one JSONL response",
            f"nonempty_lines={len(lines)}",
        )
    try:
        return json.loads(lines[0])
    except json.JSONDecodeError as exc:
        raise _finding(
            "runtime_handshake_response_json_invalid",
            "handshake/stdout",
            "one JSON response object",
            "invalid_json",
        ) from exc


def check_runtime_handshake(
    *,
    workspace: Path,
    import_root: str,
    runtime_argv: Sequence[str],
    timeout_seconds: float,
) -> tuple[Finding, ...]:
    expected = _expected_tools(workspace)
    response = _handshake_response(
        workspace=workspace,
        import_root=_candidate_import_root(workspace, import_root),
        command=_runtime_command(workspace, runtime_argv),
        timeout_seconds=timeout_seconds,
    )
    if not isinstance(response, Mapping) or response.get("ok") is not True:
        raise _finding("runtime_handshake_not_ok", "handshake", "response with ok=true", response)
    result = response.get("result")
    if not isinstance(result, Mapping):
        raise _finding("runtime_handshake_result_invalid", "handshake/result", "object", result)
    observed_tools = result.get("tools")
    if not isinstance(observed_tools, list):
        raise _finding(
            "runtime_handshake_tools_invalid", "handshake/result/tools", "array", observed_tools
        )
    observed: dict[str, list[Mapping[str, object]]] = {}
    findings: list[Finding] = []
    for index, item in enumerate(observed_tools):
        if not isinstance(item, Mapping):
            findings.append(
                Finding("runtime_tool_invalid", f"tools/{index}", "object", _safe_actual(item))
            )
            continue
        tool_id = item.get("tool_id")
        if not isinstance(tool_id, str) or not tool_id:
            findings.append(
                Finding(
                    "runtime_tool_id_invalid",
                    f"tools/{index}/tool_id",
                    "non-empty string",
                    _safe_actual(tool_id),
                )
            )
            continue
        observed.setdefault(tool_id, []).append(item)
    for tool_id in sorted(set(expected) - set(observed)):
        findings.append(
            Finding(
                "runtime_tool_missing",
                f"tools[{tool_id}]",
                "one declared WorldSpec tool",
                "missing",
            )
        )
    for tool_id in sorted(set(observed) - set(expected)):
        findings.append(
            Finding(
                "runtime_tool_unexpected", f"tools[{tool_id}]", "no extra handshake tool", "present"
            )
        )
    for tool_id in sorted(set(expected) & set(observed)):
        entries = observed[tool_id]
        if len(entries) != 1:
            findings.append(
                Finding(
                    "runtime_tool_duplicate",
                    f"tools[{tool_id}]",
                    "exactly one entry",
                    str(len(entries)),
                )
            )
            continue
        for field, expected_value in expected[tool_id].items():
            actual_value = entries[0].get(field)
            if _canonical(expected_value, path=f"tools[{tool_id}].{field}") == _canonical(
                actual_value,
                path=f"handshake/tools[{tool_id}].{field}",
            ):
                continue
            difference = _first_difference(
                expected_value,
                actual_value,
                path=f"tools[{tool_id}].{field}",
            )
            findings.append(
                Finding(
                    "runtime_tool_surface_mismatch",
                    difference or f"tools[{tool_id}].{field}",
                    "canonical projection from inputs/world-spec.json",
                    "different or missing Candidate handshake value",
                )
            )
    return tuple(findings)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, default=Path("."))
    parser.add_argument("--import-root", required=True)
    parser.add_argument("--timeout-seconds", type=float, default=15.0)
    parser.add_argument("--runtime-argv", nargs=argparse.REMAINDER, required=True)
    args = parser.parse_args(argv)
    if args.timeout_seconds <= 0:
        parser.error("--timeout-seconds must be positive")
    workspace = args.workspace.resolve()
    try:
        findings = check_runtime_handshake(
            workspace=workspace,
            import_root=args.import_root,
            runtime_argv=args.runtime_argv,
            timeout_seconds=args.timeout_seconds,
        )
    except HandshakeContractError as exc:
        print(exc.finding.render())
        print("FAILED candidate-runtime-handshake-contract findings=1")
        return 1
    if findings:
        for finding in findings:
            print(finding.render())
        print(f"FAILED candidate-runtime-handshake-contract findings={len(findings)}")
        return 1
    print(f"OK candidate-runtime-handshake-contract tools={len(_expected_tools(workspace))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
