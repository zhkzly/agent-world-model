# S4 Verified SFT/GRPO Core — Technical Design

## 1. Design judgment

The current stage connects completed S1–S3 truth to one real training path. It
does not yet evaluate whether that path improves unseen-Release behavior.

```text
existing S3 batch/runtime
-> formal teacher trajectories
-> veRL-native SFT
-> thin Foundry AgentLoop
-> veRL-native GRPO/checkpointing
```

The implementation is configuration-first. Foundry code exists only where veRL
cannot know the project-specific Episode/S3 Host contract.

The exact veRL source is an external operational checkout. It is cloned at tag
`v0.9.0`, verified at SHA `483b8a009ba3a97563edee3a19887e4862b8094a`,
and installed editable in an isolated training environment. Foundry does not
vendor it, add a submodule, put its backend dependencies in the root lockfile or
wrap environment installation in another runtime.

## 2. Minimal file surface

```text
src/agent_env_foundry/learning_data.py
  select formal primary cohort
  map public TrainingEpisodeView to lossless messages/tools JSON columns

src/agent_env_foundry/verl_sft_dataset.py
  decode those two columns after the pinned upstream parquet read

src/agent_env_foundry/verl_agent_loop.py
  bridge veRL generation to current synchronous PolicyDriver
  bind online token/mask evidence to S3 Episode
  reject failed/incomplete/non-numeric/zero-signal V1 groups

scripts/s4_collect.py
  configure and invoke current run_episode_batch

tests/test_learning_data.py
tests/test_verl_agent_loop.py

one SFT config
one GRPO config
```

There is no `s4_evaluate.py`, split module, experiment package, custom trainer,
codec, artifact framework, Registry or service.

## 3. Cohort command

`scripts/s4_collect.py` is a thin owner for one missing literal command. It:

1. reads the exact checked-in semantic S4 config;
2. accepts invocation-local Release/TaskStore/Corpus locators and prepares the
   declared identities;
3. builds a fresh teacher driver per requested slot;
4. calls existing `run_episode_batch` once;
5. verifies returned/written manifest identity before exit;
6. cold-reads every sealable paired Episode bundle;
7. writes one cohort file with exact batch/policy/driver/Episode identities.

Artifact paths are operational command arguments, not semantic config identity;
the checked-in config contains IDs, policy/model revisions and budgets only.

The cohort selector lives in `learning_data.py` from CP0, so CP1 has no backwards
dependency. Scripted drivers are analysis/regression only. Every published slot
is terminal.

## 4. SFT data and command

The mapper emits native v0.9 multi-turn rows:

```text
messages:
  system/user reset and Task context
  assistant tool calls using parsed_arguments
  tool observations
  assistant terminal answer
tools:
  public ToolSpecs in the selected target schema
source:
  Episode / TaskPack / Release identities
```

The mapper does not tokenize and does not create a loss mask. It stores
`messages` and `tools` as deterministic compact JSON text because Arrow struct
inference null-unions heterogeneous argument and JSON-Schema keys even within a
single row. `FoundryJSONColumnsSFTDataset` subclasses the pinned
`MultiTurnSFTDataset`, calls the upstream read, rejects non-text or non-exact
compact-JSON cells, decodes only those two columns, and changes nothing else. The pinned
dataset still owns target-template application and assistant-only mask; the CP1
compatibility test checks exact decoded values and produced masks through that
real class.

The only training implementation is the resolved config for:

```text
torchrun ... -m verl.trainer.sft_trainer
checkpoint.save_contents=[model,optimizer,extra,hf_model]
```

The physical gate compares logical trainable-tensor digests before/after the
optimizer step and after HF cold-load. No SFT runner is added to Foundry.

## 5. Proof-first PolicyDriver bridge

Current S3 already owns reset, Host call validation/dispatch, close/reopen,
checker and Reward. The adapter uses it unchanged:

```text
AgentLoop event loop
-> asyncio.to_thread(run_task_episode)
-> fresh synchronous bridge PolicyDriver
-> run_coroutine_threadsafe(LLMServerClient.generate)
-> DriverDecision returned to existing Host
```

The driver receives only `PublicEpisodeInput` and prior public results. Each
rollout driver has the exact frozen `PolicySpec`; S3 continues to reject reuse or
identity drift.

If this bridge cannot preserve token truth, lifecycle, reward or failure owner,
the checkpoint stops. A new S3 session API is not authorized here.

## 6. Continuous Token use

The target profile must pass v0.9 Continuous Token wiring and chat-template
checks. The adapter uses upstream helpers:

```text
ct_build_initial_tokens
ct_merge_assistant_token
ct_merge_non_assistant_msg
```

Exact generated assistant IDs remain mask `1`. S3 public tool-observation
messages are merged with mask `0`. Decoding is used only to construct a
`DriverDecision`; decoded/re-rendered tokens never replace generated IDs.

This removes the need for a Foundry token codec or model-family registry.

## 7. Rollout-binding evidence

`TrainingEpisodeView` intentionally has no online model token IDs. The adapter
therefore writes one adjacent rollout receipt keyed by `episode_id` containing:

```text
release_id / task_pack_id / policy_id / group ID
response_ids or content-addressed token blob
response_mask or content-addressed mask blob
S3 disposition and reward
exact v0.9/model/template/config identities
```

The GRPO sampler consumes that receipt before materialization. This is one
current producer/consumer pair, not a generic artifact layer.

## 8. V1 fail-closed sampler

Use v0.9 V1 sync trainer with one prompt group per optimizer step. Stock sync
ReplayBuffer permits failed groups to remain sampleable and may pad missing
trajectories, which conflicts with S3 `abstain=null`.

`FoundryFailClosedReplayBuffer` is the only trainer-side extension. It subclasses
the exact-pin sync `ReplayBuffer` and overrides `_sampleable_terminal_keys`, which
runs after TransferQueue metadata sync and before materialization. It verifies:

- root status is `finished`, never `failure`;
- exactly frozen `G` sibling rows exist;
- every sibling binds a cold S3 Episode and rollout receipt;
- all rewards are numeric `0.0/1.0` and match S3;
- the group has nonzero variance.

Any violation raises a typed failure. With one group per step, no advantage,
backward or actor update runs. The class never refills, retries, pads, filters or
requeues a group.

It is configured through the upstream `trainer.v1.sampler.custom_sampler` hook
and remains inside `verl_agent_loop.py`; no sampler framework is created.

## 9. Runtime configuration

```text
veRL tag: v0.9.0
commit: 483b8a009ba3a97563edee3a19887e4862b8094a
trainer.use_v1: true
trainer.v1.trainer_mode: sync
data.train_batch_size: 1
data.gen_batch_size: 1
actor_rollout_ref.rollout.n: G
trainer.v1.sampler.sync_refill_failed_groups: false
algorithm.filter_groups.enable: false
```

The exact model, rollout backend, device and distributed settings are ordinary
resolved veRL config. Foundry does not wrap them.

## 10. Deletion rules

Delete or reject:

- any custom trainer or checkpoint manager;
- custom prompt/token/mask codec code duplicated from Continuous Token;
- any SFT dataset override beyond strict post-read JSON decoding;
- model, algorithm, device, sampler or artifact registries;
- incremental S3 session/service/queue/pool;
- retry, refill, survivor filtering or reward shaping;
- train/dev/held-out split machinery;
- comparison, CI, significance or learning-utility report code;
- future model families, algorithms or experiment baselines.

The current task ends with a real reloadable GRPO checkpoint and continued S3
rollout. Later utility evaluation starts from those artifacts under a new plan.
