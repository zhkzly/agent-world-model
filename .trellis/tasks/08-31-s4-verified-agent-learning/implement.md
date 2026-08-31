# S4 Verified SFT/GRPO Core — Implementation Plan

## 1. Execution discipline

The task remains planning authority until explicitly activated. Checkpoints run
in order and land in separate commits.

Each checkpoint requires:

1. an importable minimal interface scaffold where needed;
2. a named behavioral RED that reaches the callable rather than failing import;
3. the smallest current implementation;
4. focused tests plus semantic mutation evidence;
5. full deterministic tests, Ruff, mypy and `git diff --check`;
6. the real S3/veRL physical exit;
7. project-purpose, stage-boundary and deletion review;
8. independent review before commit.

Normal veRL device/backend configuration is used. A command that has not run is
unverified; it is not replaced by a fake or CPU/GPU-specific Foundry path.

```bash
uv run python -m pytest
uv run ruff check src tests
uv run mypy src
git diff --check
```

## 2. Checkpoint 0 — Formal teacher cohort

### Claim

Existing admitted Corpus entries can produce an honest S4 teacher cohort through
the completed S3 runtime, without retrying for success or changing upstream
truth.

### Freeze

```text
Release/Corpus/TaskPack roots and IDs
teacher PolicySpec + executable fresh-driver route/provider config
rollouts_per_task + turn limit
target model/tokenizer/template/tool parser
veRL v0.9.0 exact SHA 483b8a009ba3a97563edee3a19887e4862b8094a
literal SFT and GRPO configs/commands
persistent output roots
```

The target must pass v0.9 Continuous Token model-family and chat-template
compatibility before CP0 exits.

### Work

Introduce:

```text
src/agent_env_foundry/learning_data.py   # cohort selector first
tests/test_learning_data.py
scripts/s4_collect.py
```

The literal command is:

```bash
uv run python scripts/s4_collect.py --config <config> --output <absent-root>
```

It prepares the declared Release, constructs a fresh matching teacher driver per
slot, calls existing `run_episode_batch`, validates the manifest before exit,
cold-reads sealable bundles and writes the cohort file.

Primary SFT = all allowlisted non-scripted `verified_success` views. Retain every
published failure/abstain/blocked slot as evidence; do not backfill it.

An unpublished aborted batch may be rerun identically in a new root. A published
manifest is terminal.

### Behavioral RED

First test:

```text
tests/test_learning_data.py::test_primary_cohort_rejects_scripted_policy
```

Then cover:

- batch/PolicySpec/driver-route mismatch;
- duplicate Episode ID;
- failed/abstained/non-cold-valid primary source;
- missing requested slot;
- acceptance fixture silently promoted to primary authority.

Mutations must prove the scripted and disposition filters are load-bearing.

### Physical exit

```text
frozen request
-> S3 EpisodeBatchManifest with one result per slot
-> cold-valid sealable Episode bundles
-> exact primary/analysis cohort
```

If the primary set is empty, return `DATA_INSUFFICIENT` and stop.

### Alignment/deletion gate

- no S1/S2 generation or S3 truth changes;
- no batch reader/framework, split manager or artifact base class;
- no SFT/AgentLoop/GRPO code introduced early;
- every config field has a CP0 or direct CP1 consumer.

### Commit

```text
s4(cp0): collect the formal teacher cohort
```

## 3. Checkpoint 1 — veRL-native SFT checkpoint

### Claim

The formal public teacher trajectories can drive one real v0.9 multi-turn SFT
update and produce an HF-compatible checkpoint for the online path.

### Work

Extend `learning_data.py` to emit only `messages`, `tools` and source identities.
Use each call's validated `parsed_arguments`, ordered ToolObservation and terminal
answer. Do not tokenize or create a custom loss mask.

The resolved command is the pinned configuration of:

```bash
torchrun ... -m verl.trainer.sft_trainer \
  data.train_files=<dataset> \
  data.messages_key=messages \
  data.tools_key=tools \
  model.path=<base-model> \
  checkpoint.save_contents='[model,optimizer,extra,hf_model]'
```

veRL `MultiTurnSFTDataset` owns target-template application and assistant-only
masking.

### Behavioral RED

First test:

```text
tests/test_learning_data.py::test_sft_row_masks_tool_observation
```

Then cover:

- assistant call/final answer masked out;
- prompt/tool observation trained;
- parsed arguments, observation or answer reordered/dropped;
- protected/checker/witness data included;
- non-allowlisted source included;
- nondeterministic row bytes or missing source identity.

Mask, allowlist and protected-data mutants must fail.

### Physical exit

```text
dataset
-> optimizer step > 0
-> changed logical trainable-tensor digest
-> HF-compatible model/tokenizer export
-> cold-load with identical saved logical tensor digest
-> finite post-load forward/loss diagnostic
```

Loss is diagnostic only. This checkpoint makes no improvement claim.

### Stop conditions

- target/template cannot represent current public tool calls;
- assistant/environment spans cannot be separated by pinned veRL;
- trainable parameters do not change;
- HF handoff cannot save or cold-load.

### Alignment/deletion gate

- public TrainingEpisodeView fields only;
- one target format, no custom dataset class/codec/trainer;
- no CP2 AgentLoop or CP3 GRPO implementation early;
- checkpoint is directly loadable as CP2 `model.path`.

### Commit

```text
s4(cp1): train the verified-trajectory sft checkpoint
```

## 4. Checkpoint 2 — Continuous Token AgentLoop over S3

### Claim

The SFT checkpoint can generate multi-turn tool actions through v0.9 Continuous
Token while the unchanged S3 PolicyDriver/Host owns every environment action and
terminal reward.

### Work

Introduce:

```text
src/agent_env_foundry/verl_agent_loop.py
tests/test_verl_agent_loop.py
```

Implement the proof-first thread bridge:

```text
AgentLoop.run
-> asyncio.to_thread(run_task_episode)
-> fresh synchronous bridge PolicyDriver
-> run_coroutine_threadsafe(LLMServerClient.generate)
-> ct_build_initial_tokens / ct_merge_assistant_token /
   ct_merge_non_assistant_msg
-> DriverDecision through existing Host
```

Use CP1 HF export as `model.path`. Dataset rows provide operational Release and
TaskStore roots plus exact release/corpus/task IDs.

Persist one rollout-binding receipt keyed by `episode_id`, binding exact response
IDs/mask, group identity and S3 reward.

No incremental S3 session is authorized. A focused bridge failure stops the
checkpoint for separate replanning.

### Behavioral RED

First test:

```text
tests/test_verl_agent_loop.py::test_generated_token_ids_survive_non_round_trip_text
```

Then cover:

- tool observation receives mask `1`;
- assistant token receives mask `0`;
- direct actor call bypasses Host;
- reward differs from EpisodeRecord or occurs before S3 finalization;
- model-server failure becomes healthy policy failure;
- driver reuse/PolicySpec drift;
- protected data enters prompt;
- rollout receipt mismatches Episode ID/reward.

Token replacement, Host bypass and reward recomputation mutants must fail.

### Physical exit

Using the real SFT checkpoint and normal veRL runtime:

```text
same TaskPack + G fresh isolated rollouts
-> exact Continuous Token IDs/masks
-> cold S3 Episode for every sealable member
-> matching rollout-binding receipt
-> observed numeric reward group or honest abstain/failure
```

Measure group reward variance only to determine whether CP3 has a valid GRPO
input. No Base comparison or utility experiment is performed.

### Stop conditions

- token/mask/lifecycle/reward ownership cannot be proven;
- target is incompatible with Continuous Token/tool parsing;
- all available frozen groups have no numeric nonzero signal;
- progress requires an S3 rewrite or second verifier.

### Alignment/deletion gate

- one current S3 Host/checker/reward path;
- one AgentLoop and target model;
- no S3 seam, service, codec or evaluator;
- no experiment/split/report code.

### Commit

```text
s4(cp2): bridge continuous-token rollouts to s3 truth
```

## 5. Checkpoint 3 — Fail-closed V1 GRPO checkpoint

### Claim

One complete nonzero-signal S3 group can drive a real v0.9 V1-sync GRPO update,
save/reload the checkpoint and continue a fresh S3 rollout.

### Config

```text
entrypoint: python -m verl.trainer.main_ppo
trainer.use_v1: true
trainer.v1.trainer_mode: sync
trainer.v1.sampler.custom_sampler: FoundryFailClosedReplayBuffer
trainer.v1.sampler.sync_refill_failed_groups: false
data.train_batch_size: 1
data.gen_batch_size: 1
actor_rollout_ref.rollout.n: G
algorithm.adv_estimator: grpo
algorithm.filter_groups.enable: false
reward: S3 terminal 1.0/0.0 only
```

Add `FoundryFailClosedReplayBuffer` inside `verl_agent_loop.py`. At the exact-pin
`_sampleable_terminal_keys` gate, reject failed/incomplete/non-numeric/all-equal
groups before materialization. Never pad, refill, retry, filter survivors or
replace siblings.

### Behavioral RED

First test:

```text
tests/test_verl_agent_loop.py::test_abstain_aborts_v1_step_without_parameter_change
```

Then cover:

- failed root with surviving child is sampled;
- group cardinality differs from `G`;
- null/mismatched Episode reward reaches advantage;
- all-equal group updates;
- two TaskPacks share a group;
- response masks ignored;
- post-update rollout uses stale weights.

Abstain padding, sibling filtering and stale-weight mutants must fail.

### Physical exit

```text
complete nonzero-signal group
-> advantages
-> backward/actor update
-> changed parameter digest
-> checkpoint save
-> cold reload
-> fresh continued S3 rollout using reloaded weights
```

Also inject one sealable abstain and prove the command fails before update with an
unchanged parameter digest.

### Stop conditions

- no complete nonzero-signal group exists;
- stock/custom sampler behavior cannot guarantee whole-step fail closed;
- checkpoint/rollout weights do not save, load or synchronize;
- only shaping, retry or S3 truth changes could make progress.

### Alignment/deletion gate

- no custom trainer/checkpoint/device layer;
- exactly one pin-specific sampler subclass and no sampler registry;
- no retry/refill/filtering/shaping;
- no utility experiment or held-out code.

### Commit

```text
s4(cp3): run the fail-closed grpo checkpoint
```

## 6. Task completion

Completion means the config-first SFT/GRPO training core is physically real and
reloadable. It does not mean learning utility is proven.

Any future Base comparison, held-out Release, statistical analysis or paper
claim begins as a separate explicitly requested task using the checkpoints and
Episode evidence produced here.
