# S4 Verified Agent Learning — Technical Design

## 1. Design judgment

The project criterion is semantic completion of the full causal chain:

```text
real Need
-> real executable EnvironmentRelease
-> admitted good Tasks
-> verified acting-policy Episodes
-> measured learning utility
```

S1–S3 are complete authority for the first four links. S4 must consume them
without reopening their implementation and answer the last question with one
real SFT→GRPO path. veRL is a means to that evidence, not a new product layer.

The smallest valid S4 path is:

```text
existing Corpus
-> fixed-budget teacher batch through existing S3
-> target-template SFT data and checkpoint
-> pinned veRL policy through existing S3 PolicyDriver/Host
-> terminal-reward GRPO checkpoint
-> frozen single-Release held-out comparison
```

## 2. Current-stage boundaries

S4 may invoke current S3 public APIs and persist their outputs. It may not:

- generate or re-admit Tasks;
- repair S1/S2 data or weaken Task gates;
- add another Host, checker or reward authority;
- treat acceptance fixtures as an automatically valid training cohort;
- build a generic learning platform in anticipation of later experiments.

If the formal collection has insufficient usable evidence, S4 returns the exact
shortfall. It does not silently move back into S1/S2 work.

## 3. Minimal implementation surface

Add code only when a checkpoint has a current producer and consumer:

```text
src/agent_env_foundry/learning_data.py
  CP0 cohort allowlist and CP1 target-format SFT rows

src/agent_env_foundry/verl_agent_loop.py
  exact-pin compatibility check, PolicyDriver bridge, one AgentLoop and one
  v0.9.0 fail-closed sync ReplayBuffer subclass

tests/test_learning_data.py
tests/test_verl_agent_loop.py
tests/test_s4_evaluate.py

one SFT config
one GRPO config
scripts/s4_collect.py
scripts/s4_evaluate.py
```

The veRL-facing Python code remains inside the installable package. Do not add a
parallel `integrations/verl` Python package, `learning_artifacts.py`, split
framework, registry or codec hierarchy.

The exact file list may shrink when an upstream command or current S3 API already
provides the behavior. It may not grow for unproven future consumers.

## 4. Formal cohort materialization

Checkpoint 0 adds the literal `scripts/s4_collect.py` command. It prepares the
declared Release, builds one fresh teacher `PolicyDriver` per slot from the
frozen route, and invokes existing `run_episode_batch`. No new collection runtime
is introduced.

The batch request freezes:

```text
CorpusManifest identity
teacher PolicySpec
matching driver factory/route and provider sampling config
rollouts_per_task
turn budget
slot order
persistent output root
```

The command receives the in-memory `EpisodeBatchManifest`, validates its written
bytes before exit, cold-reads every sealable Episode bundle and writes one cohort
file binding the batch, PolicySpec, driver route and exact Episode IDs. Later
commands consume the cohort and cold-read those bundles; S4 does not add a new
public S3 batch-manifest reader.

If collection aborts before publishing a complete manifest, the operator may run
the identical frozen request into a new absent output root. That is recovery from
an unpublished run, not retry-until-success. Once a manifest is published, its
slots are terminal and cannot be replaced.

Primary SFT eligibility is decided from trusted batch/record provenance before
the model sees data. The actual sample is constructed only from the paired
public `TrainingEpisodeView`.

Scripted drivers are excluded from the primary SFT cohort. They remain useful
only for deterministic S3 and adapter regression tests.

## 5. SFT representation

`TrainingEpisodeView` contains public structured action/observation/final-answer
turns. It does not contain private reasoning or original teacher token IDs.

For one selected target model:

```text
PublicEpisodeInput
+ ordered assistant tool calls
+ ordered public ToolObservations
+ terminal public answer
-> one messages/tools row
-> frozen target tokenizer/template applies once
-> assistant-only training mask
```

Use the pinned veRL multi-turn SFT dataset contract directly. Do not emit a
second custom token stream when veRL already owns template application and mask
construction. The selected target must also pass v0.9.0's Continuous Token
model-family wiring and chat-template checker before CP1 proceeds.

Focused fixtures prove:

- system/user/reset/tool context is not a loss target;
- assistant tool-call and final-answer spans are targets;
- source ordering and JSON arguments survive exactly;
- protected/checker/witness fields cannot enter the row;
- duplicate or non-allowlisted Episode IDs fail;
- the same input produces byte-identical data/config identity.

Offline SFT makes no claim about preserving unavailable teacher token IDs.
The SFT config explicitly exports an HF-compatible model/tokenizer directory;
CP2 loads that exact directory as its `model.path`. Logical trainable-tensor
digests prove one real update and cold-load equality.

## 6. Proof-first S3/veRL bridge

Current S3 already exposes a synchronous `PolicyDriver` boundary and owns the
complete reset→Host→close/reopen→checker lifecycle. The first integration must
attempt to use it unchanged.

The focused design candidate is:

```text
FoundryAgentLoop.run (veRL event loop)
-> asyncio.to_thread(run_task_episode)
-> synchronous model PolicyDriver in that worker thread
-> run_coroutine_threadsafe(LLMServerClient.generate, owner event loop)
-> v0.9.0 Continuous Token helpers retain/merge exact assistant IDs and public
   non-assistant observation messages
-> DriverDecision returned to the existing S3 Host
```

The proof must establish:

1. exact generated token IDs and masks are recoverable without re-rendering;
2. public observations return through the existing DriverDecision/Host ledger;
3. S3 lifecycle and terminal reward remain unchanged;
4. model-server faults retain correct ownership and do not create false policy
   failures or false S3 provider Episodes;
5. driver/session close remains deterministic under thread offload.

Every rollout receives a fresh bridge driver and its `PolicySpec` must equal the
batch/request policy exactly, matching existing S3 enforcement. Runtime dataset
rows contain operational Release/TaskStore locators plus exact
`release_id/corpus_id/task_pack_id`; locators are not semantic identity.

The bridge writes one concrete rollout-binding receipt keyed by `episode_id` and
containing the exact `response_ids`, `response_mask`, group identity and S3 reward
or their content-addressed blobs. CP3 consumes this receipt rather than guessing
token evidence from `TrainingEpisodeView`.

Throughput or aesthetic concerns are not functional failure. If any required
property fails, the checkpoint stops with that focused test. This task does not
pre-authorize `open_interactive_episode`, an async S3 rewrite or direct actor
access; any S3 seam requires a separate reviewed revision.

## 7. Online token and reward contract

For each rollout, veRL owns:

```text
prompt_ids
response_ids
response_mask
log probabilities
group-relative advantage
optimizer/checkpoint state
```

S3 owns:

```text
public tool validation and dispatch
ordered public trace
fresh native instance
close/reopen lifecycle
terminal checker
RewardOutcome
EpisodeRecord/TrainingEpisodeView
```

Model-generated chunks are merged through v0.9.0 Continuous Token exactly with
mask `1`. Decoding is only a parsing copy. Tool-observation and Host-added
environment messages are merged through the same upstream builder with mask
`0`.
The invariant is:

```text
len(response_ids) == len(response_mask)
```

The adapter returns the existing S3 terminal reward. It never computes Task
success from tool validity, final text, calls, latency or a second judge.

## 8. GRPO group and abstention behavior

The initial trainer is v0.9.0 `verl.trainer.main_ppo` with
`trainer.use_v1=true`, `trainer.v1.trainer_mode=sync`, one TaskPack/prompt group
per optimizer step and no refill/resampling. One pin-specific
`FoundryFailClosedReplayBuffer` subclasses the documented V1 sync ReplayBuffer
and overrides the exact-pin `_sampleable_terminal_keys` decision after metadata
sync. It raises before materialization when the root group is failed, incomplete,
non-numeric or all-equal. It never filters survivors into a smaller group.

One group binds one exact TaskPack and logical rollout request. Members use fresh
isolated native instances and rediscover dynamic identifiers publicly.

Before any optimizer step, every member must have:

- exact group/TaskPack identity;
- a cold-valid Episode bundle;
- numeric S3 reward (`1.0` or `0.0`);
- at least one model-generated token;
- consistent response IDs and masks.

Any `abstain` is persisted when sealable and raises a typed failure that aborts
the whole current optimizer step before advantage/backward/update. The initial
path uses no in-band sentinel, group-local filter, retry, replacement, requeue or
scheduler.

An all-equal numeric group has zero relative signal. It is reported and cannot
satisfy the required nonzero GRPO update.

## 9. Cohort roles and evaluation

The single cohort file assigns S4 train/dev roles using existing Corpus keys:

```text
corpus_id
release_id
structure_id
task_pack_id -> S4 role
```

`role` is an S4 assignment, not an existing Corpus field. There is no independent
split artifact, new `task_structure_id`, instance-held-out or initial
structure-held-out completion path.

Base and SFT behavior are measured through the same accepted S3/veRL path before
GRPO. Final evaluation freezes:

- code/config/checkpoint identities;
- primary contrast/metric, denominator and improvement direction;
- statistical unit, exact confidence-interval method and mechanical
  `SUPPORTED_ON_FROZEN_RELEASE` decision rule;
- evaluation slot budget and framework-consumed sampling config;
- terminal-checkpoint-at-frozen-step rule, with no best-of-run selection.

Only after that freeze does the parent Foundry operator (the user or supervising
main session, outside S4 production code) run the already accepted S1, S2 and S3
workflows and deliver exact Release, Corpus, TaskPack and artifact-root
identities. `scripts/s4_evaluate.py` validates them against the freeze before any
model call. S4 does not implement the S1–S3 orchestrator.

The result is limited to the frozen held-out Release. Report existing S3
dispositions and raw codes, not an S4-invented cross-TaskKind taxonomy.

## 10. Runtime and configuration

S4 uses the normal hardware/runtime support of the pinned training stack. The
resolved run records model, tokenizer, Python, PyTorch, veRL, rollout backend and
device configuration because they affect reproducibility.

veRL remains an external checkout of latest stable v0.9.0 at the exact frozen
SHA. Foundry does not
vendor or fork it first, and the optional adapter module is not imported by the
core package on ordinary S1–S3 paths. Commit/API mismatch fails closed. An
upstream patch requires a focused extension-point failure and separate review;
general upstream cleanup is outside S4.

Foundry adds no device abstraction, CPU fallback, remote-execution protocol or
hardware scheduler. The same code/config surface is used wherever the user runs
the framework-supported job.

## 11. Evidence and identity

Reuse existing S3 manifests and native veRL configuration/checkpoint outputs.
The only additional adjacent-stage evidence is: CP0 cohort, CP1 HF checkpoint
receipt, CP2 rollout-binding evidence, CP3 checkpoint receipt and CP4 final
report. Later receipts point backward; earlier artifacts are never mutated to
reference future checkpoints.

No generic manifest superclass or artifact registry is introduced. Add a named
receipt only when a real next-stage command consumes it.

## 12. Deletion and stop rules

Delete or do not introduce:

- a predesigned incremental S3 session;
- a second policy/evaluation driver;
- custom token emission duplicated from pinned veRL;
- scripted trajectories in primary SFT;
- trainer/model/algorithm registries;
- reward shaping, reward models or LLM judges;
- normalized failure categories without an existing producer;
- services, queues, pools, schedulers or curriculum;
- additional model families and RL algorithms.

At each checkpoint, stop before the next one when its physical evidence is not
available or its claim would require changing S1–S3 truth. A valid negative or
insufficient-data result is part of the project evidence, not permission to
weaken the system.
