# veRL v0.9.0 contract evidence for S4

## Frozen upstream

```text
latest stable release at plan freeze: v0.9.0
tag commit: 483b8a009ba3a97563edee3a19887e4862b8094a
```

Evidence: [official release](https://github.com/verl-project/verl/releases/tag/v0.9.0)
and [signed tag commit](https://github.com/verl-project/verl/commit/483b8a009ba3a97563edee3a19887e4862b8094a).

S4 verifies the installed checkout against the full SHA and fails closed on API
drift. It does not track `release/v0.9.0` or moving `main`.

The checkout is operational rather than a Foundry product dependency: clone tag
`v0.9.0` at an invocation-local path, require the full `HEAD` above, and install
that tree editable inside the isolated training environment with
`pip install --no-deps -e <verl-root>`. The root Foundry lock remains free of the
backend-specific PyTorch/vLLM/SGLang dependency graph, and no vendored copy or
submodule is introduced.

## AgentLoop and token contracts

- `AgentLoopOutput` still carries prompt/response IDs, response mask and
  trajectory-level reward: [exact source](https://github.com/verl-project/verl/blob/483b8a009ba3a97563edee3a19887e4862b8094a/verl/experimental/agent_loop/agent_loop.py#L85-L146).
- v0.9.0 adds Continuous Token helpers that build initial tokens and merge exact
  assistant IDs with re-rendered non-assistant/tool messages while maintaining
  response metadata: [exact source](https://github.com/verl-project/verl/blob/483b8a009ba3a97563edee3a19887e4862b8094a/verl/experimental/agent_loop/agent_loop.py#L191-L345).
- V1 AgentLoop marks a prompt group `failure` after all sibling sessions settle
  when any session raises: [exact source](https://github.com/verl-project/verl/blob/483b8a009ba3a97563edee3a19887e4862b8094a/verl/trainer/ppo/v1/agent_loop_tq.py#L97-L136).

The target model selected in CP0 must be supported by the frozen Continuous
Token model-family wiring and pass the upstream chat-template checker. S4 uses
the upstream builder rather than implementing another token-concatenation codec.

## SFT handoff

The SFT command uses the pinned `verl.trainer.sft_trainer` module with
multi-turn `messages`/`tools` input. It explicitly sets
`checkpoint.save_contents=[model,optimizer,extra,hf_model]` so CP2 receives an
HF-compatible model/tokenizer path, while preserving native optimizer state.

Evidence: [SFT entrypoint](https://github.com/verl-project/verl/blob/483b8a009ba3a97563edee3a19887e4862b8094a/verl/trainer/sft_trainer.py),
[SFT config](https://github.com/verl-project/verl/blob/483b8a009ba3a97563edee3a19887e4862b8094a/verl/trainer/config/sft_trainer_engine.yaml),
and [checkpoint contract](https://github.com/verl-project/verl/blob/483b8a009ba3a97563edee3a19887e4862b8094a/docs/advance/checkpoint.rst).

## V1 trainer and fail-closed decision

v0.9.0 enables the unified V1 trainer by default. S4 uses:

```text
entrypoint: python -m verl.trainer.main_ppo
trainer.use_v1: true
trainer.v1.trainer_mode: sync
data.train_batch_size: 1 prompt group
data.gen_batch_size: 1 prompt group
actor_rollout_ref.rollout.n: 2
trainer.v1.sampler.sync_refill_failed_groups: false
algorithm.filter_groups.enable: false
```

The stock sync replay buffer intentionally leaves failed groups sampleable and
may pad missing trajectories. That is incompatible with S3 `abstain=null` and a
complete GRPO sibling group: [exact replay-buffer contract](https://github.com/verl-project/verl/blob/483b8a009ba3a97563edee3a19887e4862b8094a/verl/trainer/ppo/v1/replay_buffer.py#L75-L115)
and [sampling behavior](https://github.com/verl-project/verl/blob/483b8a009ba3a97563edee3a19887e4862b8094a/verl/trainer/ppo/v1/replay_buffer.py#L271-L443).

S4 therefore supplies exactly one pin-specific upstream extension:
`FoundryFailClosedReplayBuffer`, configured through the documented
`trainer.v1.sampler.custom_sampler` hook. It subclasses the v0.9.0 sync
`ReplayBuffer` and overrides the exact-pin `_sampleable_terminal_keys` decision,
which runs after TransferQueue metadata synchronization and before
materialization. It raises only when the metadata snapshot contains a prompt
root with status `failure`, then delegates the native decision unchanged for
every numeric group. It never reads numeric rewards, refills, retries, replaces
or silently filters a group. The exception occurs before advantage, backward
and actor update.

The custom-sampler hook is part of the exact V1 source:
[trainer construction](https://github.com/verl-project/verl/blob/483b8a009ba3a97563edee3a19887e4862b8094a/verl/trainer/ppo/v1/trainer_base.py#L132-L176)
and [config surface](https://github.com/verl-project/verl/blob/483b8a009ba3a97563edee3a19887e4862b8094a/verl/trainer/config/ppo_trainer.yaml#L205-L253).

This is one current trust-boundary consumer, not a sampler framework. A version
or trainer-mode change requires a new compatibility review.

## Pinned V1 reward-loop correction

The v0.9 AgentLoop worker calls `_compute_score` whenever its output reward is
`None` and reward-loop handles are non-null. `RewardLoopManager` returns handles
by default when the reward model is disabled (`reward.num_workers` defaults to
8); setting that count to zero produces an empty non-null list and fails at
`random.choice`, so it is not a disable switch.

The smaller correction is earlier: after writing the cold Episode and receipt,
the Foundry AgentLoop raises on `null` rather than returning an output. Numeric
`0.0/1.0` continues through `AgentLoopOutput.reward_score`, so `_compute_score`
is not entered. The custom sampler only rejects the resulting failure root to
prevent stock survivor padding; it does not read receipts or numeric tensors.

The custom AgentLoop constructor arguments cannot be embedded in the PPO config:
v0.9 `AgentLoopWorker` resolves `rollout.agent.agent_loop_config_path`, then
`OmegaConf.load`s a standalone list and instantiates its selected entry. CP3
therefore checks in one small exact-pin AgentLoop list config alongside the one
GRPO trainer config; this is upstream-required wiring, not a Foundry registry.
