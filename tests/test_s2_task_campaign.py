from __future__ import annotations

import importlib.util
from collections import Counter
from pathlib import Path
from types import ModuleType


def _campaign_module() -> ModuleType:
    path = Path(__file__).resolve().parents[1] / "scripts/run_s2_task_campaign.py"
    spec = importlib.util.spec_from_file_location("run_s2_task_campaign", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_scheduler_balances_shapes_outcomes_and_tools_without_a_chain() -> None:
    module = _campaign_module()
    records: list[dict[str, object]] = []
    targets = []
    for attempt_index in range(1, 13):
        target = module._select_target(
            release_id="a" * 64,
            tool_names=("inspect", "mutate", "list"),
            seed=17,
            attempt_index=attempt_index,
            prior_records=records,
        )
        targets.append(target)
        records.append(
            {
                "target": target.to_document(),
                "terminal": "SamplingUnsupported",
                "structure_id": None,
            }
        )

    assert (
        max(Counter(t.required_goal_shape for t in targets).values())
        - min(Counter(t.required_goal_shape for t in targets).values())
        <= 1
    )
    assert (
        max(Counter(t.required_outcome for t in targets).values())
        - min(Counter(t.required_outcome for t in targets).values())
        <= 1
    )
    assert (
        max(Counter(t.required_focus_tools[0] for t in targets).values())
        - min(Counter(t.required_focus_tools[0] for t in targets).values())
        <= 1
    )
    assert all(len(t.required_focus_tools) == 1 for t in targets)
    assert all("chain" not in str(t.to_document()).lower() for t in targets)


def test_scheduler_is_resume_deterministic_and_carries_prior_structure_ids() -> None:
    module = _campaign_module()
    prior = [
        {
            "target": {
                "format": "sampling-target/1",
                "required_goal_shape": "atom",
                "required_focus_tools": ["inspect"],
                "required_outcome": "query",
                "prior_structure_ids": [],
            },
            "terminal": "admitted",
            "structure_id": "b" * 64,
        }
    ]

    first = module._select_target(
        release_id="a" * 64,
        tool_names=("inspect", "mutate"),
        seed=23,
        attempt_index=2,
        prior_records=prior,
    )
    second = module._select_target(
        release_id="a" * 64,
        tool_names=("inspect", "mutate"),
        seed=23,
        attempt_index=2,
        prior_records=list(reversed(prior)),
    )

    assert first == second
    assert first.prior_structure_ids == ("b" * 64,)


def test_corpus_fan_in_is_order_independent_and_deduplicates_structure() -> None:
    module = _campaign_module()
    members = [
        {
            "need_id": "need-2",
            "release_id": "2" * 64,
            "task_pack_id": "c" * 64,
            "structure_id": "f" * 64,
            "path": "needs/need-2/attempts/002/TaskPack",
        },
        {
            "need_id": "need-1",
            "release_id": "1" * 64,
            "task_pack_id": "a" * 64,
            "structure_id": "e" * 64,
            "path": "needs/need-1/attempts/001/TaskPack",
        },
        {
            "need_id": "need-1",
            "release_id": "1" * 64,
            "task_pack_id": "b" * 64,
            "structure_id": "e" * 64,
            "path": "needs/need-1/attempts/002/TaskPack",
        },
    ]

    forward = module._corpus_manifest("d" * 64, members)
    reverse = module._corpus_manifest("d" * 64, list(reversed(members)))

    assert forward == reverse
    assert forward["task_pack_count"] == 2
    assert [item["task_pack_id"] for item in forward["members"]] == ["a" * 64, "c" * 64]
    assert forward["manifest_id"]


def test_campaign_summary_keeps_sampling_filter_and_infrastructure_counts_separate() -> None:
    module = _campaign_module()
    records = [
        {
            "need_id": "need-1",
            "domain": "alpha",
            "release_id": "1" * 64,
            "terminal": "completed",
            "attempt_count": 3,
            "attempt_terminal_counts": {
                "admitted": 1,
                "SamplingUnsupported": 1,
                "InfrastructureFailure": 1,
            },
            "sampled_count": 1,
            "candidate_count": 1,
            "admitted_count": 1,
            "unique_structure_count": 1,
            "sampling_tool_calls": 5,
            "filter_tool_calls": 7,
            "sampling_provider_turns": 3,
            "filter_provider_turns": 8,
            "input_tokens": 100,
            "output_tokens": 20,
            "elapsed_ms": 400,
            "goal_attempts": {"atom": 1, "all": 1, "if": 1},
            "goal_admitted": {"atom": 1},
            "outcome_attempts": {"query": 1, "transition": 1, "refusal": 1},
            "outcome_admitted": {"transition": 1},
            "focus_tools_attempted": ["inspect", "mutate"],
            "objective_tools_admitted": ["mutate"],
            "five_run_vectors": [[True, True, False, False, False]],
            "task_pack_ids": ["a" * 64],
        },
        {
            "need_id": "need-2",
            "domain": "beta",
            "release_id": "2" * 64,
            "terminal": "completed",
            "attempt_count": 2,
            "attempt_terminal_counts": {"PolicyRejected": 2},
            "sampled_count": 2,
            "candidate_count": 2,
            "admitted_count": 0,
            "unique_structure_count": 0,
            "sampling_tool_calls": 4,
            "filter_tool_calls": 10,
            "sampling_provider_turns": 4,
            "filter_provider_turns": 10,
            "input_tokens": 80,
            "output_tokens": 15,
            "elapsed_ms": 600,
            "goal_attempts": {"foreach": 2},
            "goal_admitted": {},
            "outcome_attempts": {"transition": 2},
            "outcome_admitted": {},
            "focus_tools_attempted": ["release"],
            "objective_tools_admitted": [],
            "five_run_vectors": [[True, False, False, False, False]] * 2,
            "task_pack_ids": [],
        },
    ]

    summary = module._campaign_summary(
        "d" * 64,
        "e" * 64,
        records,
        corpus_manifest_id="f" * 64,
    )

    assert summary["release_terminal_coverage"] == {"completed": 2}
    assert summary["attempt_terminal_counts"] == {
        "InfrastructureFailure": 1,
        "PolicyRejected": 2,
        "SamplingUnsupported": 1,
        "admitted": 1,
    }
    assert summary["sampled_count"] == 3
    assert summary["candidate_count"] == 3
    assert summary["admitted_task_count"] == 1
    assert summary["public_tool_calls"] == {"sampling": 9, "filter": 17, "total": 26}
    assert summary["tokens"] == {"input": 180, "output": 35, "total": 215}
    assert summary["checker_generation"] == {"provider_turns": 0, "tokens": 0}
    assert summary["summary_id"]


def test_campaign_identity_excludes_worker_scheduling() -> None:
    module = _campaign_module()

    config = module._campaign_config(
        s1_campaign_id="a" * 64,
        source_commit="b" * 40,
        seed=17,
        attempt_budget=15,
    )

    assert config["attempt_budget_per_release"] == 15
    assert config["model"] == "gpt-5.6-luna"
    assert "workers" not in config
