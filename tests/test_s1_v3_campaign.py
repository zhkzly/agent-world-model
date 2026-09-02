from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest


def _campaign_module() -> ModuleType:
    path = Path(__file__).resolve().parents[1] / "scripts/run_batch_campaign.py"
    spec = importlib.util.spec_from_file_location("run_batch_campaign", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_official_s1_v3_campaign_suite_has_twenty_unique_needs() -> None:
    module = _campaign_module()
    suite = module._read_suite(
        Path(__file__).resolve().parents[1] / "experiments/batch-environment-task/needs.json"
    )

    assert len(suite) == 20
    assert len({item["id"] for item in suite}) == 20
    assert {item["family"] for item in suite} >= {
        "transactional-policy",
        "approval-workflow",
        "resource-scheduling",
        "repository-filesystem",
    }


def test_s1_v3_campaign_summary_separates_release_and_failure_metrics() -> None:
    module = _campaign_module()
    records = [
        {
            "need_id": "need-a",
            "domain": "alpha",
            "terminal": "released",
            "elapsed_ms": 100,
            "tool_count": 4,
            "source_nonblank_loc": 120,
            "test_functions": 3,
            "release_archive_bytes": 2000,
            "stage_events": [
                {"stage": "research", "status": "passed", "elapsed_ms": 70},
                {"stage": "environment_builder", "status": "passed", "elapsed_ms": 30},
            ],
        },
        {
            "need_id": "need-b",
            "domain": "beta",
            "terminal": "not_released",
            "elapsed_ms": 300,
        },
    ]

    summary = module._summary("campaign", "suite", records)

    assert summary["need_count"] == 2
    assert summary["terminal_counts"] == {"released": 1, "not_released": 1}
    assert summary["release_rate"] == 0.5
    assert summary["elapsed_ms"]["total"] == 400
    assert summary["total_tools"] == 4
    assert summary["total_source_nonblank_loc"] == 120
    assert summary["total_test_functions"] == 3
    assert summary["stage_elapsed"]["research"]["mean_ms"] == 70
    assert summary["summary_id"]


def test_campaign_identity_is_independent_of_runtime_concurrency() -> None:
    module = _campaign_module()

    config = module._campaign_config("suite-digest", "source-commit")

    assert config == {
        "format": "s1-v3-campaign-config/2",
        "suite_digest": "suite-digest",
        "source_commit": "source-commit",
        "environment_model": "gpt-5.6-luna",
        "semantic_reviewer_model": "gpt-5.6-luna",
        "base_url": "http://127.0.0.1:8317/v1",
    }
    assert "workers" not in config


def test_serial_warmup_selects_only_next_unreleased_need() -> None:
    module = _campaign_module()
    needs = tuple(
        {"id": f"need-{index}", "domain": "d", "family": "f", "need": "n"} for index in range(1, 5)
    )
    records = {"need-1": {"need_id": "need-1", "terminal": "released"}}

    selected = module._select_needs_for_run(needs, records, max_new=1)

    assert [item["id"] for item in selected] == ["need-2"]
    assert module._select_needs_for_run(needs, records, max_new=None) == needs


def test_s1_v3_campaign_preserves_unexpected_worker_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _campaign_module()

    def fail_generation(*args: object, **kwargs: object) -> object:
        raise RuntimeError("unexpected physical failure")

    monkeypatch.setattr(module, "generate_environment_v3_internal", fail_generation)
    record = module._run_need(
        {
            "id": "need-a",
            "domain": "alpha",
            "family": "transactional-policy",
            "need": "Create one environment.",
        },
        tmp_path,
        "suite",
        "campaign",
    )

    assert record["terminal"] == "worker_failed"
    assert record["code"] == "RuntimeError"
    assert (tmp_path / "records/need-a.json").is_file()
    assert (tmp_path / "needs/need-a/attempts/attempt-001/terminal.json").is_file()
