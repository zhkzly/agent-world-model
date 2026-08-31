"""External-integration tests for the CP1 strict-JSON-column SFT reader.

These run only where veRL is importable (the dedicated training environment)
and are skipped by the root suite, which stays free of the veRL dependency
graph. They are also directly executable:

    /tmp/foundry-s4-verl-env/bin/python tests/test_verl_sft_dataset_external.py
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Any, cast

import pytest

pytest.importorskip("verl")

import pandas as pd
from omegaconf import DictConfig
from transformers import AutoTokenizer
from verl.trainer.sft_trainer import create_sft_dataset
from verl.utils.dataset.multiturn_sft_dataset import MultiTurnSFTDataset

from agent_env_foundry.learning_data import (
    build_sft_rows,
    read_s4_core_config,
)
from agent_env_foundry.verl_sft_dataset import FoundryJSONColumnsSFTDataset

REPO = Path(__file__).parents[1]
CORE_CONFIG = REPO / "configs" / "s4" / "core.json"
COHORT_ROOT = REPO / ".artifacts" / "cp0-formal-teacher-no-listener-20260831"
TOKENIZER = Path("/tmp/foundry-s4-qwen3-tokenizer")


def _require_physical_cohort() -> None:
    if not COHORT_ROOT.is_dir():
        pytest.skip("physical CP0 cohort root is not present on this machine")


def _cohort_rows() -> list[dict[str, Any]]:
    config = read_s4_core_config(CORE_CONFIG)
    rows = build_sft_rows(COHORT_ROOT, config)
    return [cast(dict[str, Any], row) for row in rows]


def _data_config(**overrides: Any) -> DictConfig:
    values: dict[str, Any] = {
        "messages_key": "messages",
        "tools_key": "tools",
        "pad_mode": "no_padding",
        "truncation": "error",
        "max_length": 2048,
        "ignore_input_ids_mismatch": True,
        "enable_thinking_default": False,
        "custom_cls": {
            "path": "pkg://agent_env_foundry.verl_sft_dataset",
            "name": "FoundryJSONColumnsSFTDataset",
        },
    }
    values.update(overrides)
    return DictConfig(values)


def _dataset(tokenizer: Any, parquet: str, **overrides: Any) -> Any:
    return create_sft_dataset(
        data_paths=parquet,
        data_config=_data_config(**overrides),
        tokenizer=tokenizer,
        processor=None,
    )


def test_json_columns_round_trip_builder_authority() -> None:
    _require_physical_cohort()
    rows = _cohort_rows()
    tokenizer = AutoTokenizer.from_pretrained(str(TOKENIZER))
    with tempfile.TemporaryDirectory() as tmp:
        parquet = str(Path(tmp) / "rows.parquet")
        pd.DataFrame(
            {
                "messages": [row["messages"] for row in rows],
                "tools": [row["tools"] for row in rows],
                "source": [row["source"] for row in rows],
            }
        ).to_parquet(parquet)

        dataset = _dataset(tokenizer, parquet)

        assert isinstance(dataset, FoundryJSONColumnsSFTDataset)
        assert isinstance(dataset, MultiTurnSFTDataset)
        assert len(dataset) == len(rows)
        for index, row in enumerate(rows):
            expected_messages = json.loads(cast(str, row["messages"]))
            expected_tools = json.loads(cast(str, row["tools"]))
            # decoded values equal the builder authority with zero
            # null-union or numeric-coercion drift
            assert dataset.messages[index] == expected_messages
            assert dataset.tools[index] == expected_tools


def test_inherited_masks_and_mismatch_pin() -> None:
    _require_physical_cohort()
    rows = _cohort_rows()
    tokenizer = AutoTokenizer.from_pretrained(str(TOKENIZER))
    with tempfile.TemporaryDirectory() as tmp:
        parquet = str(Path(tmp) / "rows.parquet")
        pd.DataFrame(
            {"messages": [row["messages"] for row in rows], "tools": [row["tools"] for row in rows]}
        ).to_parquet(parquet)
        dataset = _dataset(tokenizer, parquet)

        for index, row in enumerate(rows):
            item = dataset[index]
            ids, mask = item["input_ids"], item["loss_mask"]
            assert len(ids) <= 2048
            trainable = tokenizer.decode(ids[mask == 1], skip_special_tokens=False)
            context = tokenizer.decode(ids[mask == 0], skip_special_tokens=False)
            messages = json.loads(cast(str, row["messages"]))
            for message in messages:
                if message["role"] == "assistant":
                    if message.get("tool_calls"):
                        for call in message["tool_calls"]:
                            assert call["function"]["name"] in trainable
                            assert (
                                json.dumps(call["function"]["arguments"], ensure_ascii=False)
                                in trainable
                            )
                    else:
                        assert message["content"] in trainable
                else:
                    assert message["content"] in context
                    assert message["content"] not in trainable

        strict = _dataset(tokenizer, parquet, ignore_input_ids_mismatch=False)
        with pytest.raises(AssertionError, match="ignore_input_ids_mismatch"):
            strict[0]


def test_rejects_native_struct_cells() -> None:
    _require_physical_cohort()
    rows = _cohort_rows()
    tokenizer = AutoTokenizer.from_pretrained(str(TOKENIZER))
    with tempfile.TemporaryDirectory() as tmp:
        parquet = str(Path(tmp) / "struct.parquet")
        pd.DataFrame(
            {
                "messages": [json.loads(cast(str, row["messages"])) for row in rows],
                "tools": [json.loads(cast(str, row["tools"])) for row in rows],
            }
        ).to_parquet(parquet)

        with pytest.raises(ValueError, match="string cells"):
            _dataset(tokenizer, parquet)


def test_rejects_noncompact_string_cells() -> None:
    _require_physical_cohort()
    rows = _cohort_rows()
    tokenizer = AutoTokenizer.from_pretrained(str(TOKENIZER))
    with tempfile.TemporaryDirectory() as tmp:
        parquet = str(Path(tmp) / "pretty.parquet")
        pretty = [json.dumps(json.loads(cast(str, row["messages"])), indent=2) for row in rows]
        pd.DataFrame({"messages": pretty, "tools": [row["tools"] for row in rows]}).to_parquet(
            parquet
        )

        with pytest.raises(ValueError, match="exact compact"):
            _dataset(tokenizer, parquet)
