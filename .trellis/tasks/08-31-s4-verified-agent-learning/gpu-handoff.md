# S4 GPU Physical Acceptance Handoff

## 1. Honest status

Code/config authority: commit `1ba3a19` or a later descendant on branch
`s4-verified-agent-learning`.

Pinned veRL authority:

```text
tag: v0.9.0
commit: 483b8a009ba3a97563edee3a19887e4862b8094a
```

CPU/config implementation is accepted. No GPU SFT, model-backed S3 rollout,
GRPO optimizer update, checkpoint cold-load or reloaded-weight rollout has run.
Do not mark the S4 task complete until Sections 6–8 pass in order.

Foundry does not implement a trainer, optimizer or checkpoint manager. veRL
owns numeric GRPO grouping/advantage/loss/update/checkpointing. Foundry only:

- maps cold verified Episodes to lossless SFT rows;
- connects veRL AgentLoop generations to the existing S3 Host;
- persists Episode/rollout receipts;
- raises after persisting an S3 `null` reward;
- rejects the resulting V1 failure root before stock survivor padding.

## 2. Server prerequisites

Clone this branch and run every command from the repository root.

Prepare one training environment containing:

- GPU-enabled PyTorch compatible with the server;
- one veRL rollout backend (`vllm` for the checked-in config, or override it);
- pandas/pyarrow for Parquet materialization;
- editable installs of the exact veRL checkout and this repository.

Verify the source before every physical command:

```bash
git -C "$VERL_ROOT" rev-parse HEAD
git -C "$VERL_ROOT" status --porcelain
python -c 'import pathlib, verl, agent_env_foundry; print(pathlib.Path(verl.__file__).resolve()); print(pathlib.Path(agent_env_foundry.__file__).resolve())'
```

Required result: the full veRL SHA above, empty status, and import paths inside
`$VERL_ROOT` and this Foundry checkout. Stop on drift; do not add a compatibility
fallback.

The checked-in proof config uses one GPU and Qwen3-0.6B. If changing GPU count
or rollout backend, use ordinary veRL overrides; keep `rollout.n=2`, V1 sync,
the Foundry AgentLoop and the failure-root sampler unchanged.

## 3. Inputs that Git does not publish

The CP0 artifact root is operational data and is not part of the branch. Copy
the existing authoritative directory to the server; do not recollect or retry
the teacher cohort:

```text
.artifacts/cp0-formal-teacher-no-listener-20260831
batch:  6a92bd643f29c8623c477b02c7f486d65756ca657e036c2c7e81fded432d8df0
cohort: 09cecd906974dcb102aa95f762848b003f049fe7091e97d302a3ac23697fb579
```

Also prepare the exact model snapshot:

```text
model/tokenizer: Qwen/Qwen3-0.6B
revision: c1899de289a04d12100db370d81485cdf75e47ca
chat template: tokenizer_config.json
tool parser: hermes
```

## 4. Materialize SFT Parquet

Use the copied CP0 root and the checked-in semantic config. This is a one-off
materialization step, not a new product artifact framework:

```python
from pathlib import Path
import pandas as pd
from agent_env_foundry.learning_data import build_sft_rows, read_s4_core_config

repo = Path("/absolute/path/to/foundry-s4-verified-agent-learning")
cohort_root = Path("/absolute/path/to/cp0-formal-teacher-no-listener-20260831")
output = Path("/absolute/path/to/s4-sft-train.parquet")
config = read_s4_core_config(repo / "configs/s4/core.json")
pd.DataFrame(build_sft_rows(cohort_root, config)).to_parquet(output, index=False)
```

Expected row count: `3`. Do not rewrite the CP0 cohort or Episode bundles.

## 5. Construct one GRPO prompt row

The stock veRL `RLHFDataset` forwards arbitrary Parquet columns to the custom
AgentLoop, so no Foundry data builder is required. One row is repeated twice by
native `rollout.n=2`.

Required row shape (all paths must be visible to Ray workers):

```json
{
  "prompt": [{"role": "user", "content": "Execute the bound S3 task."}],
  "data_source": "s3",
  "reward_model": {"ground_truth": null},
  "release_path": "/absolute/path/to/EnvironmentRelease",
  "release_cache_root": "/absolute/path/to/release-cache",
  "expected_release_id": "<64-hex release id>",
  "task_pack_path": "/absolute/path/to/current TaskPack JSON",
  "task_pack_id": "<64-hex task-pack id>",
  "instance_root": "/absolute/path/to/absent-or-dedicated instance root",
  "episode_output_root": "/absolute/path/to/dedicated S4 rollout output root",
  "extra_info": {"index": 0}
}
```

Write one such row to `$S4_GRPO_TRAIN_PARQUET`. Choose an admitted TaskPack from
the exact CP0 Corpus/Release authority; do not use a witness or scripted Episode.

## 6. Physical gate A — native SFT

Set invocation-local paths:

```bash
export S4_TARGET_MODEL_SNAPSHOT=/absolute/path/to/Qwen3-0.6B-c1899de
export S4_SFT_TRAIN_PARQUET=/absolute/path/to/s4-sft-train.parquet
export S4_SFT_CHECKPOINT_DIR=/absolute/path/to/absent-sft-checkpoint-root
```

Run the native trainer (adjust `NPROC` only for the server):

```bash
torchrun --standalone --nproc_per_node="$NPROC" -m verl.trainer.sft_trainer \
  --config-dir "$PWD/configs/s4" \
  --config-name sft_trainer_qwen3_0_6b
```

Accept only with execution evidence for all of:

- at least one optimizer step;
- finite loss/forward diagnostic;
- logical trainable-tensor digest differs from the base snapshot;
- checkpoint contains model, optimizer, extra and HF model export;
- HF export cold-loads and reproduces its saved logical tensor digest.

Use the HF export path as `$S4_SFT_HF_MODEL`. Set
`S4_SFT_POLICY_ID=sft:<logical-tensor-sha256>`; never use a machine path as the
semantic policy ID.

## 7. Physical gate B — model-backed S3 rollout

The first rollout phase of the native GRPO command below exercises the committed
AgentLoop/S3 path. Before accepting any optimizer result, cold-read its emitted:

```text
episodes/<episode_id>/EpisodeRecord.json
episodes/<episode_id>/TrainingEpisodeView.json
rollout-receipts/<episode_id>.json
```

Require:

- two fresh session IDs under one veRL `uid`;
- all tool actions came through the existing S3 Host;
- close/reopen/checker completed for every sealable Episode;
- receipt response IDs/mask equal the AgentLoop output;
- numeric reward is exactly S3 `0.0/1.0`, or S3 `null` is persisted and the
  whole V1 root fails before padding/update.

Do not claim CP2 physical completion from CPU tests alone.

## 8. Physical gate C — native GRPO/checkpoint/reload

Set paths from Sections 5–7:

```bash
export S4_GRPO_TRAIN_PARQUET=/absolute/path/to/s4-grpo-train.parquet
export S4_SFT_HF_MODEL=/absolute/path/to/sft-hf-export
export S4_SFT_POLICY_ID=sft:<logical-tensor-sha256>
export S4_GRPO_CHECKPOINT_DIR=/absolute/path/to/absent-grpo-checkpoint-root
```

Run from the repository root so the relative AgentLoop config resolves:

```bash
python -m verl.trainer.main_ppo \
  --config-dir "$PWD/configs/s4" \
  --config-name grpo_qwen3_0_6b
```

The checked-in config already selects native V1 sync GRPO, `rollout.n=2`, one
GPU, vLLM, one optimizer step, save frequency 1, HF checkpoint contents, the
Foundry AgentLoop and the thin failure-root guard.

Accept only when a numeric contrasting group produces:

- native GRPO advantages;
- backward/optimizer execution;
- logical actor tensor digest different from the SFT parent;
- checkpoint save with model/optimizer/extra/HF export;
- HF cold-load with the saved digest;
- one fresh S3 rollout using the reloaded model path.

For an S3 `null` group, require command failure before materialization/update and
an unchanged parent tensor digest. Normal numeric `[1,1]` or `[0,0]` behavior is
owned by veRL and has zero relative advantage; Foundry does not reject or reshape
it. Such a group cannot prove the changed-parameter acceptance claim.

## 9. Adjustable server settings

Safe ordinary veRL overrides include:

```text
trainer.n_gpus_per_node
actor_rollout_ref.rollout.name                # vllm or installed supported backend
actor_rollout_ref.rollout.tensor_model_parallel_size
actor_rollout_ref.rollout.gpu_memory_utilization
actor_rollout_ref.actor.ppo_micro_batch_size_per_gpu
actor_rollout_ref.actor.ppo_max_token_len_per_gpu
```

When increasing GPU count, keep the native effective batch-size divisibility
valid (`train_batch_size * rollout.n`) or adjust the standard batch config. Do
not modify S3 reward, `rollout.n=2`, the custom AgentLoop, or failure-root guard
to make a run pass.

## 10. Completion and reporting

Record exact commands, resolved config, source SHAs, input artifact IDs,
parameter digests, checkpoint paths and Episode/receipt IDs. After all three
physical gates pass, update the active task evidence and only then mark/archive
S4 complete. This handoff does not authorize a learning-utility experiment or
claim that the trained model improves held-out behavior.
