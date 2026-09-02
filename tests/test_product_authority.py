from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
S2_TASK = ROOT / ".trellis/tasks/archive/2026-08/08-26-s2-task-foundry"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_archived_s2_authority_keeps_graph_and_programmatic_optional() -> None:
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


def test_archived_task_and_context_select_only_the_direct_product_path() -> None:
    task = json.loads(_text(S2_TASK / "task.json"))
    assert task["status"] == "completed"
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


def test_current_product_authority_separates_s1_environment_from_s2_task_truth() -> None:
    project = _text(ROOT / "PROJECT.md")
    s1 = project.split("## S1 owns the executable environment", 1)[1].split(
        "## S2 owns sampling good Tasks", 1
    )[0]
    s2 = project.split("## S2 owns sampling good Tasks", 1)[1].split(
        "## S3 owns verified policy Episodes", 1
    )[0]

    for prohibited in (
        "CapabilitySpecs",
        "TaskSemantics",
        "task-specific auditors",
        "positive/noop Task cases",
    ):
        assert prohibited in s1
    assert "does not publish CapabilitySpecs" in s1
    assert "one checker project" in s2.casefold()
    assert "failed task candidate never invalidates" in s2.casefold()


def test_current_backend_specs_expose_only_v3_environment_authority() -> None:
    backend = ROOT / ".trellis/spec/backend"
    assert not (backend / "v2-preparation.md").exists()
    assert not (backend / "v2-qualification-publication.md").exists()

    index = _text(backend / "index.md")
    coordinator = _text(backend / "s1-coordinator.md")
    preparation = _text(backend / "v3-preparation.md")
    publication = _text(backend / "v3-conformance-publication.md")
    normalized_coordinator = " ".join(coordinator.split())
    normalized_preparation = " ".join(preparation.split())

    assert "./v3-preparation.md" in index
    assert "./v3-conformance-publication.md" in index
    assert (
        "S1 publishes an executable world; it does not generate or qualify Tasks"
        in normalized_coordinator
    )
    assert (
        "does not generate Tasks or install a release-local semantics/verifier"
        in normalized_preparation
    )
    assert "TaskSemantics" in publication and "rejected as prohibited members" in publication
