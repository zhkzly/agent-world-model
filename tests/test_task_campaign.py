from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType


def _module() -> ModuleType:
    path = Path(__file__).resolve().parents[1] / "scripts/run_task_campaign.py"
    spec = importlib.util.spec_from_file_location("run_task_campaign", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_task_campaign_identity_excludes_runtime_scheduling_and_has_no_target() -> None:
    module = _module()

    config = module._campaign_config("s1-campaign", "source-commit", 15)

    assert config == {
        "format": "task-sampling-campaign-config/1",
        "s1_campaign_id": "s1-campaign",
        "source_commit": "source-commit",
        "candidate_budget_per_release": 15,
        "target_count": None,
        "proposal_model": "gpt-5.6-luna",
        "checker_model": "gpt-5.6-luna",
        "base_url": "http://127.0.0.1:8317/v1",
    }
    assert "workers" not in config and "max_new" not in config


def test_task_campaign_serial_warmup_selects_next_release() -> None:
    module = _module()
    sources = (
        {"need_id": "need-1", "release_id": "1" * 64},
        {"need_id": "need-2", "release_id": "2" * 64},
        {"need_id": "need-3", "release_id": "3" * 64},
    )
    records = {"need-1": {"need_id": "need-1", "terminal": "sampled"}}

    assert module._select_sources(sources, records, max_new=1) == (sources[1],)
    assert module._select_sources(sources, records, max_new=None) == sources


def test_task_campaign_summary_reports_honest_yield_cost_and_failures() -> None:
    module = _module()
    records = [
        {
            "need_id": "need-1",
            "domain": "alpha",
            "family": "workflow",
            "terminal": "sampled",
            "elapsed_ms": 1000,
            "candidate_count": 15,
            "accepted_count": 4,
            "rejected_count": 11,
            "duplicate_count": 2,
            "task_packs": [
                {
                    "release_id": "1" * 64,
                    "task_pack_id": "a" * 64,
                    "structure_id": "b" * 64,
                    "path": "needs/need-1/packs/a",
                }
            ],
            "stage_elapsed_ms": {"proposal": 100, "checker": 700},
            "tokens": {"input": 1000, "output": 200, "total": 1200},
            "tool_calls": 30,
            "rejection_codes": {"duplicate_task_structure": 2, "fresh_solution_rejected": 9},
        },
        {
            "need_id": "need-2",
            "domain": "beta",
            "family": "policy",
            "terminal": "worker_failed",
            "elapsed_ms": 500,
            "code": "provider_failed",
        },
    ]

    summary = module._summary("campaign", "s1", records)
    corpus = module._corpus_manifest("campaign", records)

    assert summary["environment_count"] == 2
    assert summary["terminal_counts"] == {"sampled": 1, "worker_failed": 1}
    assert summary["candidate_count"] == 15
    assert summary["accepted_task_count"] == 4
    assert summary["acceptance_yield"] == 4 / 15
    assert summary["duplicate_count"] == 2
    assert summary["stage_elapsed_ms"]["checker"] == 700
    assert summary["tokens"]["total"] == 1200
    assert summary["rejection_codes"]["fresh_solution_rejected"] == 9
    assert corpus["task_pack_count"] == 1
    assert corpus["members"][0]["task_pack_id"] == "a" * 64
    assert corpus["manifest_id"]
