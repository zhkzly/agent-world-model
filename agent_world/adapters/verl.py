"""verl-facing metadata facade.

This module intentionally has no dependency on the real ``verl`` package.
"""

from agent_world.adapters.grpo import (
    VerlAdapterExport,
    build_prompt_dataset,
    build_reward_bridge_config,
    consume_runtime_contract,
    export_grpo_adapter_metadata,
)

__all__ = [
    "VerlAdapterExport",
    "build_prompt_dataset",
    "build_reward_bridge_config",
    "consume_runtime_contract",
    "export_grpo_adapter_metadata",
]
