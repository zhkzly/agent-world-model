#!/usr/bin/env python3
"""Run a Candidate-owned, frozen-input Task Materializer development campaign.

This helper is intentionally narrower than the framework Judge.  It imports
only the Candidate entrypoint chosen by the Code Agent and verifies callable
echo, JSON safety, deterministic output, diversity, and difficulty contrast
from the public frozen Builder inputs.  It neither starts Runtime nor claims
schema, Integration, Judge, or release success.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import re
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_PYTHON_DOTTED_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*")


@dataclass(frozen=True)
class Finding:
    """A stable, Candidate-actionable local preflight failure."""

    code: str
    path: str
    expected: str
    actual: str

    def render(self) -> str:
        return (
            f"ERROR {self.code} path={self.path} expected={self.expected!r} actual={self.actual!r}"
        )


class CampaignError(ValueError):
    """Expected local preflight failure with no Candidate/provider payload."""

    def __init__(self, code: str, path: str, expected: str, actual: str) -> None:
        super().__init__(code)
        self.finding = Finding(code, path, expected, actual)


@dataclass(frozen=True)
class TaskSpec:
    task_type: str
    actors: tuple[str, ...]
    dimensions: tuple[str, ...]


@dataclass(frozen=True)
class CampaignSpec:
    tasks: tuple[TaskSpec, ...]
    levels_by_dimension: dict[str, tuple[str, ...]]
    minimum_initial_states: int
    minimum_materializations: int

    @property
    def base_seed_count(self) -> int:
        return max(2, self.minimum_initial_states, self.minimum_materializations)


def _load_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CampaignError(
            "json_unreadable", path.as_posix(), "JSON object", type(exc).__name__
        ) from exc
    if not isinstance(value, dict):
        raise CampaignError("json_not_object", path.as_posix(), "JSON object", type(value).__name__)
    return value


def _positive_int(value: object, *, path: str) -> int:
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    raise CampaignError("contract_field_invalid", path, "positive integer", type(value).__name__)


def _string(value: object, *, path: str) -> str:
    if isinstance(value, str) and value:
        return value
    raise CampaignError("contract_field_invalid", path, "non-empty string", type(value).__name__)


def _string_list(value: object, *, path: str) -> tuple[str, ...]:
    if isinstance(value, list) and value and all(isinstance(item, str) and item for item in value):
        return tuple(value)
    raise CampaignError(
        "contract_field_invalid", path, "non-empty string array", type(value).__name__
    )


def _object_list(value: object, *, path: str) -> tuple[dict[str, Any], ...]:
    if isinstance(value, list) and value and all(isinstance(item, dict) for item in value):
        return tuple(value)
    raise CampaignError(
        "contract_field_invalid", path, "non-empty object array", type(value).__name__
    )


def _campaign_spec(workspace: Path) -> CampaignSpec:
    inputs = workspace / "inputs"
    curriculum = _load_object(inputs / "curriculum.json")
    contract = _load_object(inputs / "implementation-contract.json")
    minimum_initial_states = _positive_int(
        curriculum.get("minimum_distinct_initial_states"),
        path="inputs/curriculum.json:/minimum_distinct_initial_states",
    )
    minimum_materializations = _positive_int(
        curriculum.get("minimum_distinct_tasks_per_type"),
        path="inputs/curriculum.json:/minimum_distinct_tasks_per_type",
    )
    dimensions = _object_list(
        curriculum.get("difficulty_dimensions"),
        path="inputs/curriculum.json:/difficulty_dimensions",
    )
    levels_by_dimension: dict[str, tuple[str, ...]] = {}
    for index, item in enumerate(dimensions):
        dimension = _string(
            item.get("dimension"),
            path=f"inputs/curriculum.json:/difficulty_dimensions/{index}/dimension",
        )
        levels_by_dimension[dimension] = _string_list(
            item.get("levels"),
            path=f"inputs/curriculum.json:/difficulty_dimensions/{index}/levels",
        )

    task_requirements = _object_list(
        curriculum.get("task_types"), path="inputs/curriculum.json:/task_types"
    )
    tasks: list[TaskSpec] = []
    for index, requirement in enumerate(task_requirements):
        task_type = _string(
            requirement.get("task_type"),
            path=f"inputs/curriculum.json:/task_types/{index}/task_type",
        )
        actors = _string_list(
            requirement.get("allowed_actor_ids"),
            path=f"inputs/curriculum.json:/task_types/{index}/allowed_actor_ids",
        )
        dimensions_for_task = _string_list(
            requirement.get("difficulty_dimensions"),
            path=f"inputs/curriculum.json:/task_types/{index}/difficulty_dimensions",
        )
        unknown = sorted(set(dimensions_for_task) - set(levels_by_dimension))
        if unknown:
            raise CampaignError(
                "task_difficulty_dimension_unknown",
                f"inputs/curriculum.json:/task_types/{index}/difficulty_dimensions",
                "declared curriculum difficulty dimension",
                ",".join(unknown),
            )
        tasks.append(TaskSpec(task_type, actors, dimensions_for_task))

    materializer = contract.get("task_materializer")
    if not isinstance(materializer, dict):
        raise CampaignError(
            "contract_field_invalid",
            "inputs/implementation-contract.json:/task_materializer",
            "object",
            type(materializer).__name__,
        )
    declared_task_types = _string_list(
        materializer.get("task_types"),
        path="inputs/implementation-contract.json:/task_materializer/task_types",
    )
    task_names = tuple(item.task_type for item in tasks)
    if set(declared_task_types) != set(task_names):
        raise CampaignError(
            "task_type_closure_mismatch",
            "inputs/implementation-contract.json:/task_materializer/task_types",
            "same task-type set as inputs/curriculum.json:/task_types",
            ",".join(declared_task_types),
        )
    return CampaignSpec(
        tasks=tuple(tasks),
        levels_by_dimension=levels_by_dimension,
        minimum_initial_states=minimum_initial_states,
        minimum_materializations=minimum_materializations,
    )


def _import_materializer(
    *, workspace: Path, import_root: str, entrypoint: str
) -> Callable[[int, str, str, dict[str, str]], object]:
    candidate = (workspace / "candidate").resolve()
    relative_root = Path(import_root)
    if relative_root.is_absolute() or ".." in relative_root.parts:
        raise CampaignError(
            "candidate_import_root_invalid",
            "--import-root",
            "workspace-relative path inside candidate/",
            import_root,
        )
    resolved_root = (workspace / relative_root).resolve()
    if not resolved_root.is_dir() or candidate not in (resolved_root, *resolved_root.parents):
        raise CampaignError(
            "candidate_import_root_invalid",
            "--import-root",
            "existing directory inside candidate/",
            import_root,
        )
    module_name, separator, callable_name = entrypoint.partition(":")
    if (
        separator != ":"
        or not _PYTHON_DOTTED_NAME.fullmatch(module_name)
        or not _PYTHON_DOTTED_NAME.fullmatch(callable_name)
    ):
        raise CampaignError(
            "materializer_entrypoint_invalid",
            "--entrypoint",
            "dotted.module:callable",
            entrypoint,
        )
    sys.path.insert(0, str(resolved_root))
    try:
        module = importlib.import_module(module_name)
        materialize = getattr(module, callable_name)
    except (ImportError, AttributeError, OSError, SyntaxError) as exc:
        raise CampaignError(
            "materializer_import_failed",
            f"candidate/{relative_root.as_posix()}:{entrypoint}",
            "importable Materializer callable",
            type(exc).__name__,
        ) from exc
    if not callable(materialize):
        raise CampaignError(
            "materializer_entrypoint_not_callable",
            entrypoint,
            "callable",
            type(materialize).__name__,
        )
    return materialize


def _canonical(value: object, *, path: str) -> str:
    try:
        return json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        )
    except (TypeError, ValueError) as exc:
        raise CampaignError(
            "materializer_json_unsafe", path, "JSON-safe value", type(exc).__name__
        ) from exc


def _seed(label: str) -> int:
    return int.from_bytes(hashlib.sha256(label.encode("utf-8")).digest()[:8], "big")


def _run_call(
    materialize: Callable[[int, str, str, dict[str, str]], object],
    *,
    seed: int,
    task_type: str,
    actor: str,
    difficulty: dict[str, str],
) -> tuple[dict[str, object], str, str]:
    path = f"task:{task_type}/actor:{actor}/seed:{seed}"
    try:
        first = materialize(seed, task_type, actor, dict(difficulty))
        second = materialize(seed, task_type, actor, dict(difficulty))
    except BaseException as exc:
        raise CampaignError(
            "materializer_call_failed",
            path,
            "callable returns one materialization",
            type(exc).__name__,
        ) from exc
    if not isinstance(first, dict):
        raise CampaignError(
            "materializer_output_not_object", path, "JSON object", type(first).__name__
        )
    first_canonical = _canonical(first, path=path)
    second_canonical = _canonical(second, path=path)
    if first_canonical != second_canonical:
        raise CampaignError(
            "materializer_nondeterministic",
            path,
            "same-input canonical output on repeated calls",
            "different canonical output",
        )
    for field, expected in (
        ("seed", seed),
        ("task_type", task_type),
        ("actor", actor),
        ("difficulty", difficulty),
    ):
        if first.get(field) != expected:
            raise CampaignError(
                "materializer_call_echo_mismatch",
                f"{path}/{field}",
                "exact framework-selected call value",
                "different or missing value",
            )
    for field in ("public_goal", "initial_config"):
        if not isinstance(first.get(field), dict):
            raise CampaignError(
                "materializer_output_field_invalid",
                f"{path}/{field}",
                "JSON object",
                type(first.get(field)).__name__,
            )
    initial_canonical = _canonical(first["initial_config"], path=f"{path}/initial_config")
    return first, first_canonical, initial_canonical


def run_campaign(
    *,
    workspace: Path,
    import_root: str,
    entrypoint: str,
) -> tuple[int, int]:
    """Run the frozen-input local campaign and return `(calls, task_types)`."""

    spec = _campaign_spec(workspace)
    materialize = _import_materializer(
        workspace=workspace, import_root=import_root, entrypoint=entrypoint
    )
    total_calls = 0
    for task in spec.tasks:
        for actor in task.actors:
            outputs: set[str] = set()
            initial_configs: set[str] = set()
            for index in range(spec.base_seed_count):
                difficulty = {
                    dimension: spec.levels_by_dimension[dimension][
                        index % len(spec.levels_by_dimension[dimension])
                    ]
                    for dimension in task.dimensions
                }
                _, output, initial = _run_call(
                    materialize,
                    seed=_seed(f"candidate-local:{task.task_type}:{actor}:base:{index}"),
                    task_type=task.task_type,
                    actor=actor,
                    difficulty=difficulty,
                )
                outputs.add(output)
                initial_configs.add(initial)
                total_calls += 1
            if len(initial_configs) < spec.minimum_initial_states:
                raise CampaignError(
                    "materializer_initial_diversity",
                    f"task:{task.task_type}/actor:{actor}/initial_config",
                    f">={spec.minimum_initial_states} distinct canonical values",
                    str(len(initial_configs)),
                )
            if len(outputs) < spec.minimum_materializations:
                raise CampaignError(
                    "materializer_output_diversity",
                    f"task:{task.task_type}/actor:{actor}/materialization",
                    f">={spec.minimum_materializations} distinct canonical values",
                    str(len(outputs)),
                )
            for dimension in task.dimensions:
                levels = spec.levels_by_dimension[dimension]
                shared_seed = _seed(
                    f"candidate-local:{task.task_type}:{actor}:contrast:{dimension}"
                )
                lowest = {item: spec.levels_by_dimension[item][0] for item in task.dimensions}
                highest = dict(lowest)
                highest[dimension] = levels[-1]
                low_output, _, _ = _run_call(
                    materialize,
                    seed=shared_seed,
                    task_type=task.task_type,
                    actor=actor,
                    difficulty=lowest,
                )
                high_output, _, _ = _run_call(
                    materialize,
                    seed=shared_seed,
                    task_type=task.task_type,
                    actor=actor,
                    difficulty=highest,
                )
                total_calls += 2
                if _canonical(
                    low_output["public_goal"], path=f"task:{task.task_type}/public_goal"
                ) == _canonical(
                    high_output["public_goal"], path=f"task:{task.task_type}/public_goal"
                ) and _canonical(
                    low_output["initial_config"], path=f"task:{task.task_type}/initial_config"
                ) == _canonical(
                    high_output["initial_config"], path=f"task:{task.task_type}/initial_config"
                ):
                    raise CampaignError(
                        "materializer_difficulty_no_effect",
                        f"task:{task.task_type}/actor:{actor}/difficulty:{dimension}",
                        "lowest/highest level changes public_goal or initial_config",
                        "both projected values are equal",
                    )
    return total_calls, len(spec.tasks)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, default=Path("."))
    parser.add_argument("--import-root", required=True)
    parser.add_argument("--entrypoint", required=True)
    args = parser.parse_args(argv)
    try:
        calls, task_types = run_campaign(
            workspace=args.workspace.resolve(),
            import_root=args.import_root,
            entrypoint=args.entrypoint,
        )
    except CampaignError as exc:
        print(exc.finding.render())
        print("FAILED candidate-materializer-campaign findings=1")
        return 1
    print(f"OK candidate-materializer-campaign calls={calls} task_types={task_types}")
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised as a standalone Skill script
    raise SystemExit(main())
