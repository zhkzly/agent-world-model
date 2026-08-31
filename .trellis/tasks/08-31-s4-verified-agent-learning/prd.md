# S4 Verified SFT/GRPO Core — Product Requirements

## 1. Authority and current-stage goal

`PROJECT.md` defines the stable S4 stage only as `SFT/RL`. S1–S3 already own and
have completed executable environments, admitted Tasks, verified Episodes and
terminal `1.0 / 0.0 / null` truth.

This candidate task specializes the current S4 implementation slice:

```text
existing Corpus
-> formal teacher Episodes through existing S3
-> one verified-success SFT dataset/checkpoint
-> one veRL AgentLoop through existing S3 Host
-> one terminal-reward GRPO update/checkpoint/reload
```

The deliverable is a real, reproducible training path. It is not a demo or MVP,
but it also does not claim that the trained checkpoint improves held-out Agent
behavior. A learning-utility experiment is a later task when the user requests
it; this task does not predesign that experiment.

## 2. Frozen implementation inputs

Checkpoint 0 freezes:

- exact EnvironmentRelease, CorpusManifest and TaskPack identities/roots;
- one teacher `PolicySpec` and executable fresh-driver factory/route;
- teacher provider sampling configuration, rollouts per TaskPack and turn limit;
- one target model, tokenizer, chat template and tool-call parser;
- latest stable veRL `v0.9.0` at exact tag commit
  `483b8a009ba3a97563edee3a19887e4862b8094a`;
- persistent artifact roots for Episodes, datasets and checkpoints.

Device/backend selection remains normal veRL/PyTorch configuration. Foundry adds
no CPU/GPU fork, remote runner, hardware abstraction or scheduler.

CP0 freezes the exact target/tokenizer/template/parser identity. CP1 validates
the SFT template/mask path and CP2 validates v0.9.0 Continuous Token; neither
compatibility implementation is pulled into CP0.

## 3. Formal teacher trajectory collection

Existing scripted/checkpoint Episodes prove S3 behavior but are not implicitly
the primary SFT cohort.

The collection command invokes existing `run_episode_batch` with:

```text
exact prepared Release and Corpus
+ frozen teacher PolicySpec
+ matching fresh PolicyDriver factory
+ frozen rollouts_per_task
+ absent persistent output root
```

Rules:

- one fresh driver and native instance per slot;
- no retry-until-success, success backfill or slot replacement;
- retain success, failure, abstain and blocked slots;
- validate the returned/written manifest before the command exits;
- cold-read every sealable Episode bundle;
- write one cohort file binding batch, policy/driver route and Episode IDs;
- exclude scripted drivers from primary SFT;
- never use S2 witnesses, admission paths, checker internals or protected facts.

Primary SFT source data is all allowlisted real-teacher `verified_success` views.
No arbitrary sample floor or post-hoc success subsampling is introduced. An
empty source set returns `DATA_INSUFFICIENT` and stops.

If collection aborts before a complete manifest is published, the identical
frozen request may be rerun into a new absent root. A published manifest is
terminal and cannot be retried or repaired.

## 4. SFT contract

`TrainingEpisodeView` contains public structured turns, not original teacher
token IDs or private reasoning. The mapper produces the selected target model's
veRL multi-turn `messages/tools` rows from:

```text
system prompt + instruction + reset observation + ToolSpecs
+ ordered assistant tool calls with parsed_arguments
+ ordered public ToolObservations
+ terminal public answer
```

The pinned veRL SFT dataset applies the target chat template once. Assistant
tool-call/final-answer spans are trainable; system/user/reset/tool-observation
context is masked out.

The SFT command uses `verl.trainer.sft_trainer` and exports
`checkpoint.save_contents=[model,optimizer,extra,hf_model]`. Completion requires:

- at least one real optimizer step;
- a changed logical trainable-tensor digest from the parent model;
- an HF-compatible model/tokenizer export;
- cold-load with the same saved logical tensor digest;
- a finite forward/loss diagnostic after cold-load.

Loss alone is not completion and no held-out improvement claim is made.

## 5. S3/veRL online contract

Use one installable v0.9.0 `AgentLoop` adapter. First attempt the current
synchronous S3 `PolicyDriver` boundary unchanged:

```text
AgentLoop.run
-> run_task_episode in a worker thread
-> synchronous bridge PolicyDriver
-> LLMServerClient.generate on the owning event loop
-> v0.9 Continuous Token prompt/assistant/observation merging
-> DriverDecision through the existing S3 Host
-> existing close/reopen checker and RewardOutcome
```

Each rollout uses a fresh driver whose `PolicySpec` matches the request. Decoded
text is parsing-only; exact model IDs are never replaced. Continuous Token keeps
model spans mask `1` and public environment/tool-observation spans mask `0`.

The adapter persists one rollout-binding receipt keyed by `episode_id`, binding
the exact response IDs/mask, TaskPack group and S3 reward.

No incremental S3 session is pre-authorized. If the proof-first bridge cannot
preserve IDs/masks, lifecycle, reward or error ownership, CP2 stops and requires
a separately reviewed plan revision.

## 6. GRPO and abstention contract

Use v0.9.0 `verl.trainer.main_ppo` with:

```text
trainer.use_v1=true
trainer.v1.trainer_mode=sync
data.train_batch_size=1 prompt group
data.gen_batch_size=1 prompt group
actor_rollout_ref.rollout.n=G
trainer.v1.sampler.sync_refill_failed_groups=false
algorithm.filter_groups.enable=false
```

Stock v0.9 sync ReplayBuffer may sample/pad failed groups. S4 therefore adds one
pin-specific `FoundryFailClosedReplayBuffer` through the documented custom
sampler hook. It rejects before materialization when:

- any sibling/parent group is failed or incomplete;
- the group does not contain exactly `G` matching Episodes;
- any member lacks numeric S3 reward or rollout-binding evidence;
- the group is all-equal and has no GRPO signal.

It never refills, filters survivors, retries or replaces a group. An S3 abstain
therefore leaves the whole optimizer step and parameter digest unchanged.

GRPO completion requires one real nonzero-signal group to produce:

```text
advantages -> backward/update -> changed parameter digest
-> checkpoint save -> cold reload -> fresh continued S3 rollout
```

If no nonzero-signal group exists under the frozen collection budget, return
`NO_GRPO_SIGNAL`; do not add shaping or weaken S3 truth.

## 7. Minimal implementation surface

Production additions are limited to:

```text
src/agent_env_foundry/learning_data.py
  cohort allowlist + TrainingEpisodeView to messages/tools

src/agent_env_foundry/verl_agent_loop.py
  PolicyDriver AgentLoop + FoundryFailClosedReplayBuffer

scripts/s4_collect.py
one SFT config
one GRPO config
focused tests
```

Do not add a custom trainer, token codec, experiment runner, evaluation framework,
split manager, artifact superclass, Registry, service, queue, scheduler or
curriculum. Reuse native S3 manifests and veRL configs/checkpoints.

## 8. Explicitly deferred

The following are not part of this task and receive no implementation or schema:

- Base/SFT/GRPO improvement experiments;
- train/dev/held-out split frameworks;
- a new post-freeze Release;
- statistical estimands, confidence intervals or significance rules;
- `SUPPORTED/NOT_SUPPORTED` learning-utility labels;
- experiment dashboards or generalized reports;
- unverified-data, RL-only or additional-model baselines.

These may be planned later from the actual trained artifacts and user need.

## 9. Acceptance criteria

The current task is complete only when:

- a formal teacher batch and cold-valid primary cohort exist;
- SFT data uses only eligible public verified-success trajectories;
- one real SFT update produces a cold-loadable HF checkpoint;
- v0.9 Continuous Token drives the unchanged S3 PolicyDriver/Host path;
- exact model/environment masks and Episode reward bindings are proven;
- any abstain/incomplete/all-equal group fails closed before update;
- one nonzero-signal GRPO update changes parameters;
- the GRPO checkpoint saves, cold-loads and continues a fresh S3 rollout;
- all four checkpoints pass behavioral RED, mutation, full checks, alignment and
  deletion review, independent review and separate commits;
- S1–S3 truth and public/trusted boundaries remain unchanged.

## 10. Fatal rejection criteria

Reject completion if:

- scripted/non-allowlisted evidence enters primary SFT;
- SFT claims unavailable teacher token identity;
- online generated tokens are decode/re-encoded;
- tool validity/final text becomes Task success;
- `abstain` becomes zero, padding, filtering, refill or replacement;
- a second Host/checker or predesigned S3 session appears;
- veRL-native training/checkpoint/device behavior is reimplemented;
- all-equal groups are shaped into signal;
- code completion or loss substitutes for real checkpoint/update evidence;
- held-out/statistical experiment code is added to this task.
