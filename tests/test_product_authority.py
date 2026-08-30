from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
S2_TASK = ROOT / ".trellis/tasks/08-26-s2-task-foundry"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_active_s2_authority_keeps_graph_and_programmatic_optional() -> None:
    documents = (
        ROOT / "PROJECT.md",
        ROOT / ".trellis/tasks/08-26-foundry-paper-product/prd.md",
        S2_TASK / "prd.md",
        S2_TASK / "design.md",
        S2_TASK / "implement.md",
        S2_TASK / "checklist.md",
    )
    combined = "\n".join(_text(path) for path in documents)
    forbidden = (
        "Graph and Programmatic samplers are required",
        "Graph and Programmatic mechanisms are required",
        "S2 requires at least two complementary proposal mechanisms",
        "Checkpoint C — Graph sampler",
        "Checkpoint D — Programmatic sampler",
        "direct + Graph + Programmatic grounded proposals",
    )
    assert all(value not in combined for value in forbidden)
    assert "Graph and Programmatic are optional" in _text(ROOT / "PROJECT.md")
    assert "Optional sampler experiments" in _text(S2_TASK / "implement.md")


def test_active_task_and_context_select_only_the_direct_product_path() -> None:
    task = json.loads(_text(S2_TASK / "task.json"))
    assert task["meta"]["candidate_samplers"] == ["direct"]
    checkpoint = task["meta"]["implementation_checkpoint"]
    assert checkpoint.startswith("direct_")
    assert "graph" not in checkpoint.lower()
    assert "programmatic" not in checkpoint.lower()
    context = _text(S2_TASK / "implement.jsonl") + _text(S2_TASK / "check.jsonl")
    assert "direct/Graph/Programmatic" not in context
    assert "Graph/Programmatic" not in context


def test_abandoned_parallel_b_modules_are_deleted() -> None:
    for relative in (
        "src/agent_env_foundry/requirement_obligations.py",
        "src/agent_env_foundry/task_specification.py",
        "src/agent_env_foundry/task_binding.py",
        ".trellis/spec/backend/s2-task-specification.md",
    ):
        assert not (ROOT / relative).exists(), relative
