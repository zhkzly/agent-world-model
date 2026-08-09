from __future__ import annotations

import ast
from pathlib import Path

PACKAGE_ROOT = Path(__file__).parents[1] / "agent_world"
RETIRED_DIRECTORIES = {
    "builder",
    "consumer",
    "control",
    "designer",
    "graph",
    "invocation",
    "judge",
    "observability",
    "registry",
    "research",
}
RETIRED_MODULE_PREFIXES = {
    "agent_world.agent_output_authority",
    "agent_world.agent_profiles",
    "agent_world.app",
    "agent_world.artifact_store",
    "agent_world.controller",
    "agent_world.diagnostic_state",
    "agent_world.doctor",
    "agent_world.expansion_runner",
    "agent_world.judge_budgeting",
    "agent_world.task_materialization",
}
RETIRED_IMPORT_DIRECTORIES = RETIRED_DIRECTORIES - {"invocation"}


def _import_targets(module_path: Path) -> set[str]:
    tree = ast.parse(module_path.read_text(encoding="utf-8"), filename=str(module_path))
    targets: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            targets.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            targets.add(node.module)
    return targets


def test_public_package_has_no_legacy_runtime_directories() -> None:
    assert PACKAGE_ROOT.exists()
    assert not RETIRED_DIRECTORIES.intersection(
        child.name for child in PACKAGE_ROOT.iterdir() if child.is_dir()
    )


def test_public_package_has_no_legacy_runtime_imports() -> None:
    imports = {
        target
        for module_path in PACKAGE_ROOT.rglob("*.py")
        for target in _import_targets(module_path)
    }

    forbidden = {
        target
        for target in imports
        if target in RETIRED_MODULE_PREFIXES
        or any(
            target == f"agent_world.{name}" or target.startswith(f"agent_world.{name}.")
            for name in RETIRED_IMPORT_DIRECTORIES
        )
    }

    assert forbidden == set()
