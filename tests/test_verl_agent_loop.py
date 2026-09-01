from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

pytest.importorskip("verl")

import numpy as np
import torch
from omegaconf import OmegaConf
from transformers import AutoTokenizer
from verl.experimental.agent_loop.agent_loop import DictConfigWrap
from verl.trainer.ppo.core_algos import compute_grpo_outcome_advantage
from verl.workers.rollout.replica import TokenOutput

import agent_env_foundry.verl_agent_loop as adapter
from agent_env_foundry.episodes import RewardOutcome
from agent_env_foundry.public_agent import capture_public_episode
from agent_env_foundry.verl_agent_loop import FoundryFailClosedReplayBuffer, FoundryS3AgentLoop

_TOKENIZER_ROOT = Path("/tmp/foundry-s4-qwen3-tokenizer")
_VERL_COMMIT = "483b8a009ba3a97563edee3a19887e4862b8094a"
_RELEASE_ID = "1" * 64
_TASK_PACK_ID = "2" * 64
_EPISODE_ID = "3" * 64
_REQUEST_ID = "4" * 64


class _Actor:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def tools(self) -> tuple[dict[str, Any], ...]:
        return (
            {
                "name": "inspect_item",
                "description": "Inspect one public item.",
                "input_schema": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {"item": {"type": "string"}},
                    "required": ["item"],
                },
                "output_schema": {
                    "type": "object",
                    "additionalProperties": False,
                    "properties": {"value": {"type": "string"}},
                    "required": ["value"],
                },
            },
        )

    def invoke(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((tool_name, arguments))
        return {"ok": True, "data": {"value": arguments["item"]}, "error": None}


class _Server:
    def __init__(self, outputs: list[list[int] | Exception]) -> None:
        self.outputs = outputs
        self.prompts: list[list[int]] = []

    async def generate(
        self, request_id: str, *, prompt_ids: list[int], **_kwargs: Any
    ) -> TokenOutput:
        assert request_id == "group-1:0"
        self.prompts.append(list(prompt_ids))
        output = self.outputs.pop(0)
        if isinstance(output, Exception):
            raise output
        return TokenOutput(token_ids=output)


def _target_model() -> dict[str, str]:
    return {
        "model_id": "Qwen/Qwen3-0.6B",
        "revision": "c1899de289a04d12100db370d81485cdf75e47ca",
        "tokenizer_id": "Qwen/Qwen3-0.6B",
        "tokenizer_revision": "c1899de289a04d12100db370d81485cdf75e47ca",
        "chat_template_source": "tokenizer_config.json",
        "continuous_token_model_family": "qwen",
        "tool_parser": "hermes",
    }


def _make_loop(server: _Server) -> tuple[FoundryS3AgentLoop, Any]:
    tokenizer = AutoTokenizer.from_pretrained(_TOKENIZER_ROOT, local_files_only=True)
    trainer = OmegaConf.create(
        {
            "actor_rollout_ref": {
                "rollout": {"prompt_length": 4096, "response_length": 4096},
                "model": {"path": str(_TOKENIZER_ROOT), "tokenizer_path": str(_TOKENIZER_ROOT)},
            }
        }
    )
    data = OmegaConf.create(
        {
            "continuous_token": {"enable": True, "model_family": "qwen"},
            "apply_chat_template_kwargs": {"enable_thinking": False},
            "mm_processor_kwargs": {},
        }
    )
    loop = FoundryS3AgentLoop(
        trainer_config=DictConfigWrap(trainer),
        server_manager=server,
        tokenizer=tokenizer,
        processor=None,
        dataset_cls=object,
        data_config=DictConfigWrap(data),
        policy_model_id="s4-sft-checkpoint:test",
        max_provider_turns=3,
        target_model=_target_model(),
        verl_commit=_VERL_COMMIT,
    )
    return loop, tokenizer


def _success_ids(tokenizer: Any) -> tuple[list[int], list[int]]:
    call_ids = tokenizer.encode(
        '<tool_call>{"name":"inspect_item","arguments":{"item":"public-1"}}</tool_call>',
        add_special_tokens=False,
    )
    final_ids = (
        tokenizer.encode('{"value":"', add_special_tokens=False)
        + [0, 0]
        + tokenizer.encode('"}', add_special_tokens=False)
    )
    return call_ids, final_ids


def _install_s3(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    actor: _Actor,
    *,
    forced_view: tuple[str, float | None] | None = None,
) -> tuple[list[str], list[Any]]:
    events: list[str] = []
    drivers: list[Any] = []

    def fake_prepare(_release: Path, _cache: Path) -> Any:
        return SimpleNamespace(identity=SimpleNamespace(release_id=_RELEASE_ID))

    def fake_run(
        _prepared: Any,
        _task_pack_path: Path,
        expected_task_pack_id: str,
        *,
        policy_driver: Any,
        rollout_index: int,
        instance_root: Path,
    ) -> Any:
        events.append("run")
        drivers.append(policy_driver)
        assert expected_task_pack_id == _TASK_PACK_ID
        assert rollout_index == 1
        assert instance_root.parent == tmp_path / "instances"
        capture = capture_public_episode(
            actor=actor,
            instruction="Inspect public-1 and return its value.",
            reset_observation={"items": ["public-1"]},
            answer_schema={
                "type": "object",
                "additionalProperties": False,
                "properties": {"value": {"type": "string"}},
                "required": ["value"],
            },
            policy_driver=policy_driver,
        )
        if capture.defect is not None:
            reward = RewardOutcome("abstain", None, capture.defect.owner, capture.defect.code)
        elif capture.completion is not None and capture.completion.terminal_kind == "completed":
            reward = RewardOutcome("verified_success", 1.0, None, None)
        else:
            reward = RewardOutcome("verified_failure", 0.0, None, None)
        return SimpleNamespace(
            episode_id=_EPISODE_ID,
            request=SimpleNamespace(
                request_id=_REQUEST_ID,
                release_id=_RELEASE_ID,
                task_pack_id=_TASK_PACK_ID,
                policy_id=policy_driver.policy_spec.policy_id,
                rollout_index=rollout_index,
            ),
            capture=capture,
            reward=reward,
        )

    def fake_write(_root: Path, record: Any) -> Any:
        events.append("write")
        disposition, reward = forced_view or (
            record.reward.disposition,
            record.reward.reward,
        )
        return SimpleNamespace(
            episode_id=_EPISODE_ID,
            request_id=_REQUEST_ID,
            request=SimpleNamespace(release_id=_RELEASE_ID, task_pack_id=_TASK_PACK_ID),
            disposition=disposition,
            reward=reward,
        )

    monkeypatch.setattr(adapter, "prepare_release", fake_prepare)
    monkeypatch.setattr(adapter, "run_task_episode", fake_run)
    monkeypatch.setattr(adapter, "write_episode_bundle", fake_write)
    return events, drivers


def _run(loop: FoundryS3AgentLoop, tmp_path: Path) -> Any:
    return asyncio.run(
        loop.run(
            {"temperature": 0.0},
            uid="group-1",
            session_id=0,
            release_path=str(tmp_path / "release"),
            release_cache_root=str(tmp_path / "cache"),
            expected_release_id=_RELEASE_ID,
            task_pack_path=str(tmp_path / "TaskPack.json"),
            task_pack_id=_TASK_PACK_ID,
            instance_root=str(tmp_path / "instances"),
            episode_output_root=str(tmp_path / "episodes"),
        )
    )


def _make_sampler() -> FoundryFailClosedReplayBuffer:
    return FoundryFailClosedReplayBuffer(
        trainer_mode="sync",
        trainer_config=OmegaConf.create({}),
        max_off_policy_threshold=8,
        max_off_policy_strategy="drop",
        sampler_kwargs=OmegaConf.create({}),
        refill_fn=lambda _count: pytest.fail("abstained groups must not refill"),
    )


def _gate(buffer: FoundryFailClosedReplayBuffer) -> set[str]:
    return buffer._sampleable_terminal_keys("train", (set(), set(), set(), {}))


def test_failure_root_stops_before_stock_padding() -> None:
    buffer = _make_sampler()
    buffer.failure_keys["train"].add("group-1")
    buffer.partitions["train"]["group-1_0_0"] = {"status": "success"}

    with pytest.raises(RuntimeError, match="S3_ABSTAIN"):
        _gate(buffer)

    buffer.failure_keys["train"].clear()
    buffer.finished_keys["train"].add("group-1")
    assert _gate(buffer) == {"group-1"}
    assert buffer.refill_fn is None


def test_native_grpo_owns_numeric_group_math() -> None:
    def advantages(rewards: list[float]) -> torch.Tensor:
        values = torch.tensor(rewards, dtype=torch.float32).unsqueeze(-1)
        result, _returns = compute_grpo_outcome_advantage(
            values,
            torch.ones_like(values),
            np.array(["group-1"] * len(rewards)),
        )
        return result.squeeze(-1)

    contrasted = advantages([1.0, 0.0])
    assert contrasted[0] > 0
    assert contrasted[1] < 0
    assert torch.equal(advantages([1.0, 1.0]), torch.zeros(2))
    assert torch.equal(advantages([0.0, 0.0]), torch.zeros(2))


def test_grpo_configs_pin_only_native_training_and_foundry_abstain_guard() -> None:
    config = OmegaConf.to_container(
        OmegaConf.load("configs/s4/grpo_qwen3_0_6b.yaml"), resolve=False
    )
    assert isinstance(config, dict)
    assert config["defaults"] == ["/ppo_trainer", "_self_"]
    assert config["data"] == {
        "train_files": "${oc.env:S4_GRPO_TRAIN_PARQUET}",
        "val_files": None,
        "train_batch_size": 1,
        "gen_batch_size": 1,
        "max_prompt_length": 2048,
        "max_response_length": 2048,
        "truncation": "error",
        "continuous_token": {"enable": True, "model_family": "qwen"},
        "apply_chat_template_kwargs": {"enable_thinking": False},
    }
    actor_rollout_ref = config["actor_rollout_ref"]
    assert actor_rollout_ref["model"] == {
        "path": "${oc.env:S4_SFT_HF_MODEL}",
        "tokenizer_path": "${oc.env:S4_SFT_HF_MODEL}",
    }
    assert actor_rollout_ref["actor"] == {
        "ppo_mini_batch_size": 2,
        "ppo_micro_batch_size_per_gpu": 1,
        "ppo_max_token_len_per_gpu": 6144,
        "checkpoint": {"save_contents": ["model", "optimizer", "extra", "hf_model"]},
    }
    rollout = actor_rollout_ref["rollout"]
    assert rollout["name"] == "vllm"
    assert rollout["mode"] == "async"
    assert rollout["n"] == 2
    assert rollout["load_format"] == "auto"
    assert rollout["tensor_model_parallel_size"] == 1
    assert rollout["log_prob_micro_batch_size_per_gpu"] == 1
    assert rollout["multi_turn"] == {"enable": True, "format": "hermes"}
    assert rollout["agent"] == {
        "num_workers": 1,
        "default_agent_loop": "foundry_s3",
        "agent_loop_config_path": "configs/s4/grpo_agent_loop_qwen3_0_6b.yaml",
    }
    assert config["algorithm"] == {
        "adv_estimator": "grpo",
        "filter_groups": {"enable": False},
        "use_kl_in_reward": False,
    }
    assert config["reward"] == {"num_workers": 1, "reward_model": {"enable": False}}
    assert config["trainer"] == {
        "use_v1": True,
        "v1": {
            "trainer_mode": "sync",
            "sampler": {
                "sync_refill_failed_groups": False,
                "custom_sampler": {
                    "path": "pkg://agent_env_foundry.verl_agent_loop",
                    "name": "FoundryFailClosedReplayBuffer",
                },
            },
        },
        "nnodes": 1,
        "n_gpus_per_node": 1,
        "total_epochs": 1,
        "total_training_steps": 1,
        "project_name": "agent-env-foundry-s4",
        "experiment_name": "qwen3-0.6b-grpo-core",
        "logger": ["console"],
        "val_before_train": False,
        "test_freq": -1,
        "save_freq": 1,
        "default_local_dir": "${oc.env:S4_GRPO_CHECKPOINT_DIR}",
        "resume_mode": "disable",
        "device": "cuda",
    }

    agent_loops = OmegaConf.to_container(
        OmegaConf.load("configs/s4/grpo_agent_loop_qwen3_0_6b.yaml"), resolve=False
    )
    assert agent_loops == [
        {
            "name": "foundry_s3",
            "_target_": "agent_env_foundry.verl_agent_loop.FoundryS3AgentLoop",
            "policy_model_id": "${oc.env:S4_SFT_POLICY_ID}",
            "max_provider_turns": 12,
            "target_model": _target_model(),
            "verl_commit": _VERL_COMMIT,
        }
    ]


def test_generated_token_ids_survive_non_round_trip_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tokenizer = AutoTokenizer.from_pretrained(_TOKENIZER_ROOT, local_files_only=True)
    call_ids, final_ids = _success_ids(tokenizer)
    final_text = tokenizer.decode(final_ids)
    assert json.loads(final_text) == {"value": "!!"}
    assert tokenizer.encode(final_text, add_special_tokens=False) != final_ids

    server = _Server([call_ids, final_ids])
    loop, _ = _make_loop(server)
    actor = _Actor()
    events, drivers = _install_s3(monkeypatch, tmp_path, actor)
    output = _run(loop, tmp_path)

    assert [
        token for token, mask in zip(output.response_ids, output.response_mask, strict=True) if mask
    ] == (call_ids + final_ids)
    assert 0 in output.response_mask
    assert actor.calls == [("inspect_item", {"item": "public-1"})]
    assert len(drivers) == 1
    assert drivers[0].policy_spec.driver_id == "verl-agent-loop"
    assert events == ["run", "write"]
    initial_prompt = tokenizer.decode(server.prompts[0])
    assert "Inspect public-1" in initial_prompt
    assert "checker_documents" not in initial_prompt
    assert "native_instance_id" not in initial_prompt
    receipt_path = tmp_path / "episodes" / "rollout-receipts" / f"{_EPISODE_ID}.json"
    receipt = json.loads(receipt_path.read_bytes())
    assert receipt["response_ids"] == output.response_ids
    assert receipt["response_mask"] == output.response_mask
    assert receipt["group_id"] == "group-1"
    assert receipt["episode_id"] == _EPISODE_ID
    assert receipt["reward"] == 1.0


def test_provider_failure_is_s3_abstain_not_policy_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    server = _Server([RuntimeError("backend unavailable")])
    loop, _ = _make_loop(server)
    actor = _Actor()
    events, _drivers = _install_s3(monkeypatch, tmp_path, actor)

    with pytest.raises(RuntimeError, match="S3_ABSTAIN"):
        _run(loop, tmp_path)

    assert actor.calls == []
    assert events == ["run", "write"]
    receipt = json.loads(
        (tmp_path / "episodes" / "rollout-receipts" / f"{_EPISODE_ID}.json").read_bytes()
    )
    assert receipt["disposition"] == "abstain"
    assert receipt["reward"] is None


def test_receipt_rejects_reward_that_differs_from_cold_episode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tokenizer = AutoTokenizer.from_pretrained(_TOKENIZER_ROOT, local_files_only=True)
    call_ids, final_ids = _success_ids(tokenizer)
    loop, _ = _make_loop(_Server([call_ids, final_ids]))
    _install_s3(
        monkeypatch,
        tmp_path,
        _Actor(),
        forced_view=("verified_failure", 0.0),
    )

    with pytest.raises(ValueError, match="finalized S3 reward identity"):
        _run(loop, tmp_path)
    assert not (tmp_path / "episodes" / "rollout-receipts").exists()
