"""Framework-owned execution of the frozen candidate Materializer/Runtime ABI."""

from __future__ import annotations

import json
import math
import os
import select
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from agent_world.contracts import (
    AssuranceRecipe,
    DifficultySchema,
    ExecutableTaskContract,
    FieldDeclaration,
    RuleDraft,
    SemanticBinding,
    ToolDraft,
    VerifierFamily,
    validate_difficulty_selection,
)

RUNTIME_OPERATIONS = ("handshake", "reset", "invoke", "snapshot", "close")
_TIMEOUT = 20
_AUTHORITY_FIELDS = frozenset(
    {"reward", "termination", "evaluator_goal", "judge", "release", "gate", "verdict"}
)


class CandidateRuntimeError(RuntimeError):
    """Safe code for an untrusted-process contract failure."""

    def __init__(self, code: str, detail: Any = None) -> None:
        super().__init__(code)
        self.code = code
        self.detail = detail


@dataclass(frozen=True, slots=True)
class MaterializationRequest:
    seed: int
    task_type: str
    actor: str
    difficulty_pairs: tuple[tuple[str, str], ...]

    def __post_init__(self) -> None:
        if (
            type(self.seed) is not int
            or not 0 <= self.seed < 2**64
            or not self.task_type
            or not self.actor
        ):
            raise ValueError("materialization_request_invalid")


@dataclass(frozen=True, slots=True)
class PrivateVerifierCase:
    """Same-run Judge-only data. It is never serialized or packaged."""

    commitment_id: str
    task_family_index: int
    tool_index: int
    variation_kind: VerifierFamily
    baseline_recipe_digest: str
    request: MaterializationRequest
    arguments: dict[str, Any]
    idempotency_keys: tuple[str, ...]

    def __post_init__(self) -> None:
        if (
            not self.commitment_id.startswith("verifier-")
            or self.task_family_index < 1
            or self.tool_index < 1
            or not self.baseline_recipe_digest.startswith("sha256:")
            or not self.idempotency_keys
        ):
            raise ValueError("private_verifier_case_invalid")


class CandidateProcess:
    def __init__(
        self,
        root: Path,
        entrypoint: str,
        python_executable: str | Path | None = None,
        *,
        close_protocol: bool = True,
    ) -> None:
        self.root, self.entrypoint = root, entrypoint
        self.python_executable = str(python_executable or sys.executable)
        self.close_protocol = close_protocol
        self.process: subprocess.Popen[str] | None = None

    def __enter__(self) -> CandidateProcess:
        path = self.root / self.entrypoint
        if not path.is_file():
            raise CandidateRuntimeError("candidate_entrypoint_missing")
        try:
            self.process = subprocess.Popen(  # noqa: S603 - deliberately launches candidate code
                [self.python_executable, str(path)],
                cwd=self.root,
                env={"PATH": os.defpath},
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                close_fds=True,
            )  # noqa: S603
        except OSError as exc:
            raise CandidateRuntimeError("candidate_launch_failed") from exc
        return self

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        _exception: BaseException | None,
        _traceback: object,
    ) -> None:
        try:
            self.close()
        except CandidateRuntimeError:
            if exception_type is None:
                raise

    def _stderr_tail(self, max_lines: int = 40) -> str:
        process = self.process
        if process is None or process.stderr is None:
            return ""
        lines: list[str] = []
        while select.select([process.stderr], [], [], 0)[0] and len(lines) < max_lines:
            line = process.stderr.readline()
            if not line:
                break
            lines.append(line)
        return "".join(lines).strip()[-2000:]

    def call(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self.process is None or self.process.stdin is None or self.process.stdout is None:
            raise CandidateRuntimeError("candidate_not_running")
        if self.process.poll() is not None:
            raise CandidateRuntimeError(
                "candidate_exited_early", detail={"stderr": self._stderr_tail()}
            )
        try:
            self.process.stdin.write(json.dumps(payload, separators=(",", ":")) + "\n")
            self.process.stdin.flush()
        except OSError as exc:
            raise CandidateRuntimeError("candidate_stdin_failed") from exc
        if not select.select([self.process.stdout], [], [], _TIMEOUT)[0]:
            raise CandidateRuntimeError(
                "candidate_protocol_timeout", detail={"stderr": self._stderr_tail()}
            )
        raw = self.process.stdout.readline()
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise CandidateRuntimeError(
                "candidate_protocol_invalid_json",
                detail={"op": payload.get("op"), "line": raw[:500], "stderr": self._stderr_tail()},
            ) from exc
        if not isinstance(value, dict):
            raise CandidateRuntimeError(
                "candidate_protocol_invalid_json",
                detail={"op": payload.get("op"), "value_type": type(value).__name__},
            )
        return value

    def call_once(self, payload: dict[str, Any]) -> dict[str, Any]:
        """One-shot request: write, close stdin, then read the single response.

        One-shot candidate processes (the Task Materializer) may rely on
        exit-time stdout flushing; closing stdin after the write gives them
        EOF, so their response is never stuck in a block buffer.
        """

        if self.process is None or self.process.stdin is None or self.process.stdout is None:
            raise CandidateRuntimeError("candidate_not_running")
        if self.process.poll() is not None:
            raise CandidateRuntimeError(
                "candidate_exited_early", detail={"stderr": self._stderr_tail()}
            )
        try:
            self.process.stdin.write(json.dumps(payload, separators=(",", ":")) + chr(10))
            self.process.stdin.flush()
            self.process.stdin.close()
        except OSError as exc:
            raise CandidateRuntimeError("candidate_stdin_failed") from exc
        if not select.select([self.process.stdout], [], [], _TIMEOUT)[0]:
            raise CandidateRuntimeError(
                "candidate_protocol_timeout", detail={"stderr": self._stderr_tail()}
            )
        raw = self.process.stdout.readline()
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise CandidateRuntimeError(
                "candidate_protocol_invalid_json",
                detail={"op": payload.get("op"), "line": raw[:500], "stderr": self._stderr_tail()},
            ) from exc
        if not isinstance(value, dict):
            raise CandidateRuntimeError(
                "candidate_protocol_invalid_json",
                detail={"op": payload.get("op"), "value_type": type(value).__name__},
            )
        return value

    def close(self) -> None:
        process = self.process
        if process is None:
            return
        close_error: CandidateRuntimeError | None = None
        exit_code = 0
        try:
            if process.poll() is None and self.close_protocol:
                try:
                    if self.call({"op": "close"}) != {"status": "ok"}:
                        raise CandidateRuntimeError("candidate_close_rejected")
                except CandidateRuntimeError as exc:
                    close_error = exc
                    process.terminate()
            if process.poll() is None and not self.close_protocol:
                process.terminate()
            exit_code = process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            exit_code = process.wait(timeout=5)
        finally:
            self.process = None
        if self.close_protocol and exit_code != 0 and close_error is None:
            close_error = CandidateRuntimeError(
                "candidate_teardown_failed", detail={"stderr": self._stderr_tail()}
            )
        if close_error is not None:
            raise close_error


def _safe(value: object, code: str) -> None:
    if not isinstance(value, dict) or len(value) > 32:
        raise CandidateRuntimeError(code)
    for key, child in value.items():
        if (
            not isinstance(key, str)
            or key.lower() in _AUTHORITY_FIELDS
            or any(word in key.lower() for word in ("secret", "private", "sealed", "evaluator"))
        ):
            raise CandidateRuntimeError(code)
        if isinstance(child, dict):
            _safe(child, code)
        elif isinstance(child, list):
            if len(child) > 32:
                raise CandidateRuntimeError(code)
            for item in child:
                if isinstance(item, dict):
                    _safe(item, code)
                elif isinstance(item, list):
                    if len(item) > 32 or any(isinstance(value, (dict, list)) for value in item):
                        raise CandidateRuntimeError(code)
                elif item is not None and type(item) not in {bool, int, float, str}:
                    raise CandidateRuntimeError(code)
        elif child is not None and type(child) not in {bool, int, float, str}:
            raise CandidateRuntimeError(code)
        if type(child) is float and not math.isfinite(child):
            raise CandidateRuntimeError(code)


_MISSING = object()


def _category(value: object, category: str) -> bool:
    if category in {"text", "timestamp", "identifier", "enum"}:
        return isinstance(value, str)
    if category == "integer":
        return type(value) is int
    if category == "number":
        return type(value) in {int, float} and not (
            type(value) is float and not math.isfinite(value)
        )
    if category == "boolean":
        return type(value) is bool
    if category == "list":
        return isinstance(value, list) and len(value) <= 32
    return False


def _pointer(value: object, path: str) -> object:
    current = value
    if not path.startswith("/"):
        return _MISSING
    for raw in path[1:].split("/"):
        key = raw.replace("~1", "/").replace("~0", "~")
        if not isinstance(current, dict) or key not in current:
            return _MISSING
        current = current[key]
    return current


def _leaf_paths(value: object, prefix: str = "") -> set[str]:
    if not isinstance(value, dict):
        return {prefix}
    leaves: set[str] = set()
    for key, child in value.items():
        escaped = key.replace("~", "~0").replace("/", "~1")
        leaves.update(_leaf_paths(child, f"{prefix}/{escaped}"))
    return leaves


def schema_shape(schema: tuple[tuple[str, str], ...]) -> dict[str, object]:
    """Inverse of _leaf_paths for a (path, category) schema: the nested dict
    whose leaf paths equal the schema paths, each leaf labelled with its value
    category. A self-describing template for the materializer agent — leaves are
    type labels, not real values, so it is provably shape-correct and cannot be
    copied verbatim into a valid (but semantically broken) output."""
    shape: dict[str, object] = {}
    for path, category in schema:
        if not path.startswith("/"):
            continue
        parts = [raw.replace("~1", "/").replace("~0", "~") for raw in path[1:].split("/")]
        node: dict[str, object] = shape
        for key in parts[:-1]:
            nxt = node.get(key)
            if not isinstance(nxt, dict):
                nxt = {}
                node[key] = nxt
            node = nxt
        node[parts[-1]] = category
    return shape


def _validate_schema(value: object, schema: tuple[tuple[str, str], ...], code: str) -> None:
    if not isinstance(value, dict) or _leaf_paths(value) != {path for path, _ in schema}:
        raise CandidateRuntimeError(code)
    for path, category in schema:
        if not _category(_pointer(value, path), category):
            raise CandidateRuntimeError(code)


def _validate_materialization(value: dict[str, Any], task: ExecutableTaskContract) -> None:
    _validate_schema(
        value["public_goal"], task.public_goal_schema, "materializer_public_goal_invalid"
    )
    _validate_schema(
        value["initial_config"], task.initial_config_schema, "materializer_initial_config_invalid"
    )
    public_paths = tuple(path for path, _ in task.public_goal_schema)
    bound_paths = tuple(binding.public_goal_path for binding in task.evaluator_goal_bindings)
    evaluator_paths = tuple(binding.evaluator_goal_path for binding in task.evaluator_goal_bindings)
    if (
        bound_paths != public_paths
        or evaluator_paths != public_paths
        or len(set(bound_paths)) != len(bound_paths)
    ):
        raise CandidateRuntimeError("evaluator_goal_binding_invalid")
    for binding in task.evaluator_goal_bindings:
        public = _pointer(value["public_goal"], binding.public_goal_path)
        evaluator = public
        if public is _MISSING or evaluator != public:
            raise CandidateRuntimeError("evaluator_goal_binding_invalid")


def materialize(
    root: Path,
    request: MaterializationRequest,
    schema: DifficultySchema,
    python_executable: str | Path | None = None,
) -> dict[str, Any]:
    difficulty = validate_difficulty_selection(schema, request.difficulty_pairs)
    with CandidateProcess(
        root, "materializer.py", python_executable, close_protocol=False
    ) as process:
        value = process.call_once(
            {
                "op": "materialize",
                "seed": request.seed,
                "task_type": request.task_type,
                "actor": request.actor,
                "difficulty": difficulty,
            }
        )
    expected = {
        "seed": request.seed,
        "task_type": request.task_type,
        "actor": request.actor,
        "difficulty": difficulty,
    }
    if (
        tuple(value)
        != ("seed", "task_type", "actor", "difficulty", "public_goal", "initial_config")
        or any(value.get(key) != item for key, item in expected.items())
        or tuple(value["difficulty"].items()) != request.difficulty_pairs
    ):
        raise CandidateRuntimeError("materializer_echo_mismatch")
    _safe(value["public_goal"], "materializer_public_goal_invalid")
    _safe(value["initial_config"], "materializer_initial_config_invalid")
    return value


def _value(field: FieldDeclaration) -> object:
    category, values = field.category, field.values
    if category == "boolean":
        return False
    if category == "integer":
        return 0
    if category == "number":
        return 0.0
    if category == "list":
        return []
    if category == "enum":
        return values[0]
    if category == "identifier":
        return "public-id"
    if category == "timestamp":
        return "1970-01-01T00:00:00Z"
    return "sample-text"


def _resolve(binding: SemanticBinding, trace: dict[str, Any]) -> object:
    value: object = trace
    for key in binding.path:
        if not isinstance(value, dict) or key not in value:
            return _MISSING
        value = value[key]
    return value


def _predicates(
    rule: RuleDraft, bindings: tuple[SemanticBinding, ...], trace: dict[str, Any]
) -> bool:
    for predicate in rule.when:
        if not 1 <= predicate.left_semantic_index <= len(bindings):
            raise CandidateRuntimeError("rule_ir_invalid")
        left = _resolve(bindings[predicate.left_semantic_index - 1], trace)
        if predicate.operator == "exists":
            matched = left is not _MISSING
        elif predicate.operator == "not_exists":
            matched = left is _MISSING
        else:
            right = predicate.right
            if left is _MISSING:
                return False
            if predicate.operator == "eq":
                matched = type(left) is type(right) and left == right
            elif predicate.operator == "ne":
                matched = type(left) is type(right) and left != right
            elif predicate.operator in {"lt", "le", "gt", "ge"}:
                if type(left) is not type(right) or type(left) not in {int, float, str}:
                    raise CandidateRuntimeError("rule_ir_category_mismatch")
                comparable_left = cast(Any, left)
                comparable_right = cast(Any, right)
                matched = {
                    "lt": comparable_left < comparable_right,
                    "le": comparable_left <= comparable_right,
                    "gt": comparable_left > comparable_right,
                    "ge": comparable_left >= comparable_right,
                }[predicate.operator]
            elif predicate.operator in {"contains", "not_contains"}:
                if not isinstance(left, (str, list)) or (
                    isinstance(left, str) and not isinstance(right, str)
                ):
                    raise CandidateRuntimeError("rule_ir_category_mismatch")
                matched = right in left
                if predicate.operator == "not_contains":
                    matched = not matched
            else:
                raise CandidateRuntimeError("rule_ir_invalid")
        if not matched:
            return False
    return True


def _pre_value(
    binding: SemanticBinding, bindings: tuple[SemanticBinding, ...], trace: dict[str, Any]
) -> object:
    for candidate in bindings:
        if (
            candidate.source == "pre_state"
            and candidate.name == binding.name
            and candidate.path[1:] == binding.path[1:]
        ):
            return _resolve(candidate, trace)
    return _MISSING


def _effects(
    rule: RuleDraft, bindings: tuple[SemanticBinding, ...], trace: dict[str, Any]
) -> dict[str, Any] | None:
    """Return None if every effect holds, else a detail dict for the first mismatch."""
    for effect in rule.effects:
        if not 1 <= effect.target_semantic_index <= len(bindings):
            raise CandidateRuntimeError("rule_ir_invalid")
        binding = bindings[effect.target_semantic_index - 1]
        actual = _resolve(binding, trace)
        expected = effect.value
        previous = _pre_value(binding, bindings, trace)
        if actual is _MISSING or expected is _MISSING:
            return {
                "field": binding.name,
                "operation": effect.operation,
                "reason": "effect target value missing in trace",
                "actual_present": actual is not _MISSING,
            }
        if effect.operation == "set":
            matched = type(actual) is type(expected) and actual == expected
        elif effect.operation in {"increment", "decrement"}:
            if (
                type(actual) not in {int, float}
                or type(previous) is not type(actual)
                or type(expected) is not type(actual)
            ):
                raise CandidateRuntimeError("rule_ir_category_mismatch")
            numeric_expected = cast(Any, expected)
            numeric_previous = cast(Any, previous)
            delta = numeric_expected if effect.operation == "increment" else -numeric_expected
            matched = actual == numeric_previous + delta
        elif effect.operation in {"add", "remove"}:
            if not isinstance(actual, list) or not isinstance(previous, list):
                raise CandidateRuntimeError("rule_ir_category_mismatch")
            projected = list(previous)
            if effect.operation == "add":
                projected.append(expected)
            elif expected in projected:
                projected.remove(expected)
            matched = actual == projected
        elif effect.operation == "preserve":
            matched = effect.value is None and actual == previous
        elif effect.operation == "reject":
            return {
                "field": binding.name,
                "operation": "reject",
                "reason": "a reject effect was exercised; the transition should not reach here",
            }
        else:
            raise CandidateRuntimeError("rule_ir_invalid")
        if not matched:
            return {
                "field": binding.name,
                "operation": effect.operation,
                "expected": expected,
                "actual": actual,
                "previous": previous if previous is not _MISSING else None,
            }
    return None


def _rule_matches(
    rule: RuleDraft, bindings: tuple[SemanticBinding, ...], trace: dict[str, Any]
) -> bool:
    return _predicates(rule, bindings, trace) and _effects(rule, bindings, trace) is None


def _snapshot(response: object, tools: tuple[ToolDraft, ...]) -> dict[str, Any]:
    if not isinstance(response, dict) or set(response) != {"state"}:
        raise CandidateRuntimeError(
            "candidate_snapshot_rejected",
            detail={
                "reason": "snapshot response must be exactly {'state': ...}",
                "actual_top_level_keys": (
                    sorted(response) if isinstance(response, dict) else type(response).__name__
                ),
            },
        )
    _safe(response["state"], "candidate_snapshot_rejected")
    state = response["state"]
    if (
        not isinstance(state, dict)
        or set(state) != {"tools"}
        or not isinstance(state["tools"], dict)
    ):
        raise CandidateRuntimeError(
            "candidate_snapshot_projection_mismatch",
            detail={
                "reason": "state must be {'tools': {tool_name: {field: value}}}",
                "actual_state_keys": (
                    sorted(state) if isinstance(state, dict) else type(state).__name__
                ),
            },
        )
    expected = {tool.surface.name: tool.surface.result_fields for tool in tools}
    if set(state["tools"]) != set(expected):
        raise CandidateRuntimeError(
            "candidate_snapshot_projection_mismatch",
            detail={
                "reason": "state.tools keys must equal the declared tool names",
                "expected_tools": sorted(expected),
                "actual_tools": sorted(set(state["tools"])),
            },
        )
    for tool_name, fields in expected.items():
        values = state["tools"][tool_name]
        if not isinstance(values, dict) or set(values) != {field.name for field in fields}:
            raise CandidateRuntimeError(
                "candidate_snapshot_projection_mismatch",
                detail={
                    "reason": "each tool value must be {field_name: value} for every result_field",
                    "tool": tool_name,
                    "expected_fields": sorted({f.name for f in fields}),
                    "actual_fields": (
                        sorted(set(values)) if isinstance(values, dict) else type(values).__name__
                    ),
                },
            )
        bad = {f.name: f.category for f in fields if not _category(values[f.name], f.category)}
        if bad:
            raise CandidateRuntimeError(
                "candidate_snapshot_projection_mismatch",
                detail={
                    "reason": "a result_field value has the wrong category",
                    "tool": tool_name,
                    "wrong_category_fields": bad,
                },
            )
    return state


def _result(response: object, tool: ToolDraft) -> dict[str, Any]:
    if isinstance(response, dict) and response.get("status") == "error":
        raise CandidateRuntimeError(
            "candidate_property_mismatch",
            detail={
                "reason": "candidate invoke raised an exception (reported by the runtime scaffold)",
                "tool": tool.surface.name,
                "candidate_error": response.get("error"),
                "traceback": response.get("traceback"),
            },
        )
    if not isinstance(response, dict) or set(response) != {"status", "result"}:
        raise CandidateRuntimeError(
            "candidate_property_mismatch",
            detail={
                "reason": "invoke response must be exactly {'status': ..., 'result': ...}",
                "tool": tool.surface.name,
                "actual_keys": (
                    sorted(response) if isinstance(response, dict) else type(response).__name__
                ),
            },
        )
    if response["status"] != "ok" or not isinstance(response["result"], dict):
        raise CandidateRuntimeError(
            "candidate_property_mismatch",
            detail={
                "reason": "invoke response status must be 'ok' and result must be an object",
                "tool": tool.surface.name,
                "status": response["status"],
                "result_type": type(response["result"]).__name__,
            },
        )
    result = response["result"]
    fields = tool.surface.result_fields
    expected_fields = {field.name for field in fields}
    if set(result) != expected_fields:
        raise CandidateRuntimeError(
            "candidate_property_mismatch",
            detail={
                "reason": "result keys must equal the declared result_field names",
                "tool": tool.surface.name,
                "expected_fields": sorted(expected_fields),
                "actual_fields": sorted(set(result)),
            },
        )
    bad = {
        f.name: {"expected_category": f.category, "got_type": type(result[f.name]).__name__}
        for f in fields
        if not _category(result[f.name], f.category)
    }
    if bad:
        raise CandidateRuntimeError(
            "candidate_property_mismatch",
            detail={
                "reason": "a result_field value has the wrong category",
                "tool": tool.surface.name,
                "wrong_category_fields": bad,
            },
        )
    _safe(result, "candidate_property_mismatch")
    return result


def _task_bindings(tools: tuple[ToolDraft, ...]) -> tuple[SemanticBinding, ...]:
    values: list[SemanticBinding] = []
    for tool in tools:
        for source, fields in (
            ("argument", tool.surface.argument_fields),
            ("tool_result", tool.surface.result_fields),
            ("pre_state", tool.surface.result_fields),
            ("post_state", tool.surface.result_fields),
            ("reset_state", tool.surface.result_fields),
        ):
            for field in fields:
                values.append(
                    SemanticBinding(
                        len(values) + 1,
                        source,  # type: ignore[arg-type]
                        field.name,
                        (source, str(tool.tool_index), field.name),
                    )
                )
    return tuple(values)


def _guard_arguments(tool: ToolDraft, arguments: dict[str, Any]) -> dict[str, Any]:
    """Adjust generated arguments to satisfy precondition guards on arguments."""

    adjusted = dict(arguments)
    for rule in tool.preconditions:
        for predicate in rule.when:
            binding = tool.bindings[predicate.left_semantic_index - 1]
            if binding.source != "argument":
                continue
            current = adjusted[binding.name]
            if predicate.operator == "eq":
                adjusted[binding.name] = predicate.right
            elif predicate.operator == "ne":
                if type(current) is type(predicate.right) and current == predicate.right:
                    if type(current) is bool:
                        adjusted[binding.name] = not current
                    elif type(current) is int:
                        adjusted[binding.name] = current + 1
                    elif type(current) is float:
                        adjusted[binding.name] = current + 1.0
                    elif type(current) is str:
                        adjusted[binding.name] = current + "-variant"
            elif predicate.operator == "ge":
                if (
                    type(current) in {int, float}
                    and isinstance(predicate.right, (int, float))
                    and current < predicate.right
                ):
                    adjusted[binding.name] = predicate.right
            elif predicate.operator == "gt":
                if (
                    type(current) in {int, float}
                    and isinstance(predicate.right, (int, float))
                    and current <= predicate.right
                ):
                    adjusted[binding.name] = (
                        predicate.right + 1
                        if isinstance(predicate.right, int)
                        else predicate.right + 1.0
                    )
            elif predicate.operator == "le":
                if (
                    type(current) in {int, float}
                    and isinstance(predicate.right, (int, float))
                    and current > predicate.right
                ):
                    adjusted[binding.name] = predicate.right
            elif predicate.operator == "lt":
                if (
                    type(current) in {int, float}
                    and isinstance(predicate.right, (int, float))
                    and current >= predicate.right
                ):
                    adjusted[binding.name] = (
                        predicate.right - 1
                        if isinstance(predicate.right, int)
                        else predicate.right - 1.0
                    )
    return adjusted


def _run_recipe(
    root: Path,
    request: MaterializationRequest,
    recipe: AssuranceRecipe,
    tools: tuple[ToolDraft, ...],
    config: dict[str, Any],
    python_executable: str | Path | None,
    keys: tuple[str, ...],
    varied_arguments: dict[str, Any] | None = None,
) -> dict[str, Any]:
    task_trace: dict[str, dict[str, Any]] = {
        "argument": {},
        "tool_result": {},
        "pre_state": {},
        "post_state": {},
        "reset_state": {},
    }
    covered = False
    with CandidateProcess(root, "runtime.py", python_executable) as process:
        if process.call({"op": "handshake"}) != {"operations": list(RUNTIME_OPERATIONS)}:
            raise CandidateRuntimeError("candidate_protocol_mismatch")
        if process.call(
            {"op": "reset", "seed": request.seed, "actor": request.actor, "initial_config": config}
        ) != {"status": "ok"}:
            raise CandidateRuntimeError("candidate_reset_rejected")
        reset_state = _snapshot(process.call({"op": "snapshot"}), tools)
        task_trace["reset_state"] = {
            str(tool.tool_index): reset_state["tools"][tool.surface.name] for tool in tools
        }
        for action_index in recipe.action_tool_indexes:
            tool = tools[action_index - 1]
            arguments = {field.name: _value(field) for field in tool.surface.argument_fields}
            if action_index == recipe.tool_index and varied_arguments is not None:
                arguments = dict(varied_arguments)
            else:
                arguments = _guard_arguments(tool, arguments)
            if set(arguments) != {field.name for field in tool.surface.argument_fields} or any(
                not _category(arguments[field.name], field.category)
                for field in tool.surface.argument_fields
            ):
                raise CandidateRuntimeError("candidate_argument_schema_mismatch")
            pre_state = _snapshot(process.call({"op": "snapshot"}), tools)
            selected_keys = (
                keys if action_index == recipe.tool_index else (f"prefix-{action_index}",)
            )
            result: dict[str, Any] | None = None
            for key in selected_keys:
                payload = {
                    "op": "invoke",
                    "tool_id": tool.surface.name,
                    "arguments": arguments,
                    "idempotency_key": key,
                }
                first, second = process.call(payload), process.call(payload)
                if first != second:
                    raise CandidateRuntimeError("candidate_idempotency_failed")
                result = _result(first, tool)
            assert result is not None
            post_state = _snapshot(process.call({"op": "snapshot"}), tools)
            index = str(tool.tool_index)
            task_trace["argument"][index] = arguments
            task_trace["tool_result"][index] = result
            task_trace["pre_state"][index] = pre_state["tools"][tool.surface.name]
            task_trace["post_state"][index] = post_state["tools"][tool.surface.name]
            # Reference-composition semantics: every precondition guard must hold
            # on the success trace, and the observed post_state must equal the
            # deterministic composition of every transition whose when holds.
            for rule in tool.preconditions:
                if not _predicates(rule, tool.bindings, task_trace):
                    raise CandidateRuntimeError(
                        "local_tool_semantics_mismatch",
                        detail={
                            "failed": "precondition_guards",
                            "tool": tool.surface.name,
                            "rationale": rule.rationale,
                        },
                    )
            pre = dict(task_trace["pre_state"][index])
            composed = dict(pre)
            fired = False
            for rule in tool.transitions:
                view = {
                    "argument": {index: arguments},
                    "tool_result": {index: composed},
                    "pre_state": {index: pre},
                    "post_state": {index: composed},
                    "reset_state": {index: task_trace["reset_state"][index]},
                }
                if not _predicates(rule, tool.bindings, view):
                    continue
                fired = True
                for effect in rule.effects:
                    target = tool.bindings[effect.target_semantic_index - 1]
                    field = target.name
                    if effect.operation == "reject":
                        raise CandidateRuntimeError(
                            "local_tool_semantics_mismatch",
                            detail={
                                "failed": "composition",
                                "reason": "reject effect fired on the success trace",
                                "tool": tool.surface.name,
                                "rationale": rule.rationale,
                            },
                        )
                    if effect.operation == "preserve":
                        continue
                    if effect.operation == "set":
                        composed[field] = effect.value
                    elif effect.operation in {"increment", "decrement"}:
                        delta = (
                            effect.value if effect.operation == "increment" else -effect.value
                        )
                        composed[field] = composed[field] + delta
                    elif effect.operation == "add":
                        composed[field] = composed[field] + [effect.value]
                    elif effect.operation == "remove":
                        composed[field] = [item for item in composed[field] if item != effect.value]
            if not fired:
                raise CandidateRuntimeError(
                    "local_tool_semantics_mismatch",
                    detail={
                        "failed": "composition",
                        "reason": "no transition rule fired on the success trace",
                        "tool": tool.surface.name,
                    },
                )
            actual = task_trace["post_state"][index]
            if composed != actual:
                raise CandidateRuntimeError(
                    "local_tool_semantics_mismatch",
                    detail={
                        "failed": "composition",
                        "tool": tool.surface.name,
                        "expected_post_state": composed,
                        "actual_post_state": actual,
                    },
                )
            if action_index == recipe.tool_index:
                covered = True
                break
    if not covered:
        raise CandidateRuntimeError("assurance_recipe_coverage_invalid")
    return task_trace


def _request(
    recipe: AssuranceRecipe,
    task_type: str,
    seed: int | None = None,
    difficulty: tuple[tuple[str, str], ...] | None = None,
) -> MaterializationRequest:
    return MaterializationRequest(
        seed if seed is not None else recipe.task_family_index * 1000 + recipe.tool_index,
        task_type,
        recipe.actor,
        difficulty or recipe.primary_difficulty,
    )


def _task_for(
    tasks: tuple[ExecutableTaskContract, ...], family_index: int
) -> ExecutableTaskContract:
    try:
        task = tasks[family_index - 1]
    except IndexError as exc:
        raise CandidateRuntimeError("task_contract_missing") from exc
    if task.task_family_index != family_index:
        raise CandidateRuntimeError("task_contract_order_invalid")
    return task


def _task_outcome(
    task: ExecutableTaskContract,
    tools: tuple[ToolDraft, ...],
    trace: dict[str, Any],
) -> tuple[int, bool]:
    bindings = _task_bindings(tools)
    requirement = task.task_requirement
    # Initial rules describe the RESET state (reset_state view): matching them
    # against post-action fields is the wrong-view failure the reset-view
    # bindings prevent. Success/failure/terminal are WHEN-ONLY patterns.
    if any(not _rule_matches(rule, bindings, trace) for rule in requirement.initial_rules):
        mismatched = [
            rule.rationale
            for rule in requirement.initial_rules
            if not _rule_matches(rule, bindings, trace)
        ]
        raise CandidateRuntimeError(
            "task_initial_rule_failed",
            detail={"failed": "initial_rules", "mismatched_rationales": mismatched[:4]},
        )
    success = any(_predicates(rule, bindings, trace) for rule in requirement.success_rules)
    failure = any(_predicates(rule, bindings, trace) for rule in requirement.failure_rules)
    terminal = any(_predicates(rule, bindings, trace) for rule in requirement.terminal_rules)
    if success and failure:
        raise CandidateRuntimeError("task_rule_ambiguous")
    reward: int
    if failure:
        reward = task.reward_spec.failure
    elif success:
        reward = task.reward_spec.success
    else:
        reward = task.reward_spec.otherwise
    terminated = terminal or success or failure
    return reward, terminated


def _binding(recipe: AssuranceRecipe) -> dict[str, object]:
    return {
        "task_family_index": recipe.task_family_index,
        "tool_index": recipe.tool_index,
        "recipe_digest": recipe.recipe_digest,
    }


def integrate(
    root: Path,
    recipes: tuple[AssuranceRecipe, ...],
    tasks: tuple[ExecutableTaskContract, ...],
    schemas: tuple[DifficultySchema, ...],
    tools: tuple[ToolDraft, ...],
    python_executable: str | Path | None = None,
) -> dict[str, Any]:
    coverage: list[dict[str, object]] = []
    try:
        for recipe in recipes:
            schema = schemas[recipe.task_family_index - 1]
            task = _task_for(tasks, recipe.task_family_index)
            first = materialize(
                root, _request(recipe, schema.task_family_id), schema, python_executable
            )
            _validate_materialization(first, task)
            alternate = materialize(
                root,
                _request(
                    recipe,
                    schema.task_family_id,
                    difficulty=recipe.alternate_difficulty,
                ),
                schema,
                python_executable,
            )
            if (
                first["public_goal"] == alternate["public_goal"]
                and first["initial_config"] == alternate["initial_config"]
            ):
                raise CandidateRuntimeError("difficulty_has_no_semantic_effect")
            _validate_materialization(alternate, task)
            _run_recipe(
                root,
                _request(recipe, schema.task_family_id),
                recipe,
                tools,
                first["initial_config"],
                python_executable,
                ("integration",),
            )
            _run_recipe(
                root,
                _request(recipe, schema.task_family_id),
                recipe,
                tools,
                first["initial_config"],
                python_executable,
                ("integration-restart",),
            )
            coverage.append(
                {
                    "task_family_index": recipe.task_family_index,
                    "tool_index": recipe.tool_index,
                    "recipe_digest": recipe.recipe_digest,
                }
            )
    except (CandidateRuntimeError, ValueError) as exc:
        return {
            "status": "failed",
            "code": str(exc),
            "detail": getattr(exc, "detail", None),
        }
    return {"status": "passed", "code": "ok", "baseline_coverage": coverage}


def judge(
    root: Path,
    recipes: tuple[AssuranceRecipe, ...],
    tasks: tuple[ExecutableTaskContract, ...],
    schemas: tuple[DifficultySchema, ...],
    tools: tuple[ToolDraft, ...],
    private_cases: tuple[PrivateVerifierCase, ...] = (),
    python_executable: str | Path | None = None,
) -> tuple[dict[str, Any], ...]:
    outcomes: list[dict[str, Any]] = []
    for recipe in recipes:
        binding = _binding(recipe)
        try:
            task = _task_for(tasks, recipe.task_family_index)
            schema = schemas[recipe.task_family_index - 1]
            materialized = materialize(
                root,
                _request(recipe, schema.task_family_id),
                schema,
                python_executable,
            )
            _validate_materialization(materialized, task)
        except (CandidateRuntimeError, ValueError) as exc:
            outcomes.append(
                {
                    "gate_id": (
                        f"task_materialization:{recipe.task_family_index}:{recipe.tool_index}"
                    ),
                    "status": "failed",
                    "code": str(exc),
                    "binding": binding,
                }
            )
            outcomes.append(
                {
                    "gate_id": f"task_reachability:{recipe.task_family_index}:{recipe.tool_index}",
                    "status": "failed",
                    "code": "task_materialization_required",
                    "binding": binding,
                }
            )
            continue
        outcomes.append(
            {
                "gate_id": f"task_materialization:{recipe.task_family_index}:{recipe.tool_index}",
                "status": "passed",
                "code": "ok",
                "binding": binding,
            }
        )
        try:
            trace = _run_recipe(
                root,
                _request(recipe, schema.task_family_id),
                recipe,
                tools,
                materialized["initial_config"],
                python_executable,
                ("judge",),
            )
            reward, terminated = _task_outcome(task, tools, trace)
            if reward != 1 or not terminated:
                raise CandidateRuntimeError(
                    "task_not_terminal_success_reward_plus_one",
                    detail={"reward": reward, "terminated": terminated},
                )
        except (CandidateRuntimeError, ValueError) as exc:
            outcomes.append(
                {
                    "gate_id": f"task_reachability:{recipe.task_family_index}:{recipe.tool_index}",
                    "status": "failed",
                    "code": str(exc),
                    "binding": binding,
                    "detail": getattr(exc, "detail", None),
                }
            )
        else:
            outcomes.append(
                {
                    "gate_id": f"task_reachability:{recipe.task_family_index}:{recipe.tool_index}",
                    "status": "passed",
                    "code": "terminal_success_reward_plus_one",
                    "binding": binding,
                }
            )
    for case in private_cases:
        binding = {
            "task_family_index": case.task_family_index,
            "tool_index": case.tool_index,
            "recipe_digest": case.baseline_recipe_digest,
        }
        try:
            recipe = next(
                item
                for item in recipes
                if item.task_family_index == case.task_family_index
                and item.tool_index == case.tool_index
                and item.recipe_digest == case.baseline_recipe_digest
            )
            materialized = materialize(
                root, case.request, schemas[case.task_family_index - 1], python_executable
            )
            task = _task_for(tasks, case.task_family_index)
            _validate_materialization(materialized, task)
            trace = _run_recipe(
                root,
                case.request,
                recipe,
                tools,
                materialized["initial_config"],
                python_executable,
                case.idempotency_keys,
                case.arguments,
            )
            reward, terminated = _task_outcome(task, tools, trace)
            if reward != 1 or not terminated:
                raise CandidateRuntimeError(
                    "task_not_terminal_success_reward_plus_one",
                    detail={"reward": reward, "terminated": terminated},
                )
        except (CandidateRuntimeError, ValueError, StopIteration) as exc:
            outcomes.append(
                {
                    "gate_id": case.commitment_id,
                    "status": "failed",
                    "code": str(exc),
                    "binding": binding,
                    "detail": getattr(exc, "detail", None),
                }
            )
        else:
            outcomes.append(
                {
                    "gate_id": case.commitment_id,
                    "status": "passed",
                    "code": "terminal_success_reward_plus_one",
                    "binding": binding,
                }
            )
    return tuple(outcomes)
