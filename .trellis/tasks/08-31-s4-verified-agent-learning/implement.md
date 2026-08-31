# S4 Verified Agent Learning — Implementation Plan

## 1. Execution rules

S4 begins only after this candidate plan is reviewed and explicitly activated.
Checkpoints execute in order. A later checkpoint may not be implemented to make
an earlier exit appear reachable.

Every checkpoint follows the same gate:

1. write a reachable behavioral RED against an existing boundary;
2. implement only the current checkpoint consumer;
3. run focused tests and a semantic mutation that proves the test can fail;
4. run the full deterministic suite, Ruff and mypy;
5. execute the checkpoint's real command and retain its physical output;
6. review alignment with `PROJECT.md`, accepted decisions and the S4 claim;
7. delete producer-less or next-checkpoint abstractions;
8. obtain independent review and commit the checkpoint separately.

For a brand-new callable, add only its importable typed interface scaffold in the
same working change, then run the named RED through that callable. A
`ModuleNotFoundError`, `NotImplementedError` or missing symbol is not RED; the
failure must be the stated behavioral assertion.

Normal framework device configuration is used. There is one implementation
path, not a local/remote or CPU/GPU product split. If a physical command has not
run, its claim remains unverified; that does not authorize a fake substitute.

Common deterministic checks:

```bash
uv run python -m pytest
uv run ruff check src tests
uv run mypy src
git diff --check
```

## 2. Checkpoint 0 — Freeze and materialize the real S4 cohort

### Stage claim

Current admitted Corpus entries can be executed through the completed S3 runtime
under one frozen teacher policy and budget, yielding an honest, persistent cohort
for the declared S4 experiment.

This checkpoint consumes S1–S3; it does not add an S1/S2 producer or modify S3
truth.

### Inputs to freeze

```text
EnvironmentRelease roots and IDs
CorpusManifest roots and IDs
Corpus entry release_id / structure_id / task_pack_id
teacher PolicySpec
matching fresh PolicyDriver factory/route and provider sampling config
rollouts_per_task and provider-turn budget
slot ordering
target model/tokenizer/chat-template/tool-parser/observation-format revision
latest stable veRL v0.9.0 exact SHA 483b8a009ba3a97563edee3a19887e4862b8094a
literal pinned `torchrun ... -m verl.trainer.sft_trainer` command with
checkpoint.save_contents=[model,optimizer,extra,hf_model]
verl.trainer.main_ppo V1 sync entrypoint + FoundryFailClosedReplayBuffer
SFT/rollout/GRPO budgets and framework-consumed training seeds
S4 train/dev roles keyed by existing Corpus identities
persistent collection output root
```

Do not add instance-held-out or `task_structure_id`. Do not invent Task or
sample-count floors. Freeze a declared experiment budget, then report what the
real collection can support.

### Work

- add one checked-in S4 experiment config for the selected identities/budgets;
- introduce `src/agent_env_foundry/learning_data.py` with the CP0 cohort selector,
  `tests/test_learning_data.py`, and the single literal command
  `uv run python scripts/s4_collect.py --config <config> --output <absent-root>`;
- make that command prepare the declared Release and construct a fresh executable
  teacher driver per slot whose `PolicySpec` matches the frozen spec;
- run the existing S3 batch once per frozen request without retry/backfill;
- validate the returned manifest and written manifest bytes in the collection
  process, then cold-read every sealable Episode bundle;
- write one exact cohort allowlist binding batch, PolicySpec, driver route and
  Episode IDs; later commands do not require a new S3 batch-manifest reader;
- classify scripted Episodes as regression evidence, never primary SFT data;
- select primary SFT candidates only from non-scripted verified successes;
- require the exact target profile to pass v0.9.0 Continuous Token
  model-family/chat-template compatibility;
- record exact target/veRL resolved configuration for later commands.

The cohort allowlist is the direct input to Checkpoint 1. Later stages consume
the adjacent checkpoint/rollout receipts that carry its provenance rather than
depending on CP0 independently.

If the command aborts before a complete manifest is published, the identical
frozen request may run again into a new absent output root. Once a manifest is
published, its slots are terminal; this recovery rule cannot chase success.

### Behavioral RED

The first named RED is:

```text
tests/test_learning_data.py::test_primary_cohort_rejects_scripted_policy
```

It reaches the typed cohort selector with a cold-valid scripted success and must
fail the naive “all successes are SFT” behavior. Then add the remaining cases:

- an Episode from another batch or PolicySpec enters the cohort;
- a scripted driver enters the primary SFT role;
- duplicate Episode IDs are accepted;
- a failed, abstained, unsealed or non-cold-valid Episode enters primary SFT;
- a requested collection slot disappears because it did not succeed;
- a Corpus role refers to an unknown `(release_id, structure_id, task_pack_id)`;
- final held-out Release/TaskPack identities appear in the freeze.

Missing-module import noise is not a valid RED. The test must reach an existing
S3/cohort boundary and fail on the named behavior.

### Physical exit

```text
frozen config + executable driver factory
-> scripts/s4_collect.py
-> existing run_episode_batch
-> one result for every requested slot
-> in-process validated manifest bytes
-> cold-valid sealable Episode bundles
-> exact primary/analysis cohort allowlist
```

The exit reports real disposition, policy and structure coverage. Primary SFT
source data is all allowlisted train-role verified successes without post-hoc
success subsampling. An empty source set returns `DATA_INSUFFICIENT`; that is a
valid stop result.

### Alignment and deletion review

- prove no S1/S2 generation or S3 truth changed;
- prove existing acceptance fixtures were not silently promoted to authority;
- delete any generic readiness class, artifact registry or hardware abstraction;
- verify every new config field is consumed by Checkpoint 0 or the next command.

### Commit

```text
s4(cp0): freeze and collect the verified learning cohort
```

## 3. Checkpoint 1 — Verified-success SFT data and candidate checkpoint

### Stage claim

The formal teacher cohort can be converted into one target model's real
multi-turn tool-use SFT input and train a reloadable candidate checkpoint without
protected-data leakage.

This checkpoint does not yet claim improved Agent behavior; that requires the
matched S3 evaluation in Checkpoint 2.

### Work

Extend the CP0 module with the smallest dataset mapper:

```text
src/agent_env_foundry/learning_data.py
tests/test_learning_data.py
```

For every allowlisted source view:

- emit the selected target model's messages/tools representation;
- preserve public instruction, reset observation, ToolSpecs, the validated
  `parsed_arguments` object for each tool call, ToolObservations and terminal
  answer in order;
- let the pinned veRL SFT dataset/tokenizer apply the frozen template once;
- train assistant tool-call/final-answer spans only;
- bind each row to source Episode, TaskPack, structure and Release IDs;
- reject scripted, failed, abstained, duplicate or non-cold-valid sources;
- freeze the literal pinned SFT command and configure an HF-compatible
  model/tokenizer export consumed directly by CP2 `model.path`;
- store the resolved dataset/training config beside the dataset/checkpoint.

Use one real SFT configuration. Do not create a trainer, model or codec registry.

### Behavioral RED

The first named RED is:

```text
tests/test_learning_data.py::test_sft_row_masks_tool_observation
```

It reaches the existing CP0 module and fails when a naive target mask trains a
tool observation. Then add:

- tool-observation or prompt context receives assistant loss mask;
- assistant tool-call/final-answer span is masked out;
- tool arguments, observations or final answer are reordered/dropped;
- protected/checker/witness data enters a row;
- non-allowlisted or scripted Episode enters the dataset;
- the same source/config produces different dataset bytes;
- source IDs or target tokenizer/template revision are absent from provenance.

Do not test equality with teacher token IDs: S3 never stored them.

### Deterministic validation

```bash
uv run python -m pytest tests/test_learning_data.py
uv run python -m pytest
uv run ruff check src tests
uv run mypy src
```

Decode representative real rows and compare them with their source
`TrainingEpisodeView`. Mutate an observation mask, assistant mask and cohort
allowlist check; each mutant must be caught.

### Physical exit

Run the normal pinned SFT command with the frozen target/config:

```text
formal dataset
-> global optimizer step > 0
-> at least one predeclared trainable-tensor digest differs from the parent
-> HF-compatible model/tokenizer export
-> cold load with the same logical tensor digest as the saved export
-> finite forward/loss on a frozen dev row when present, otherwise a train-role
   diagnostic row with dev-driven tuning disabled
```

Record actual samples/tokens, parent and trained tensor digests, resolved config
and checkpoint identity. Loss is a training diagnostic, not update or
learning-utility evidence.

### Stop conditions

- the target template cannot represent current public tool calls faithfully;
- assistant and environment spans cannot be separated;
- trainable parameters do not change or the HF handoff cannot save/cold-load;
- primary data is empty or violates the frozen batch requirement.

### Alignment and deletion review

- verify the data is public S3 projection only;
- verify no second tokenizer/render path or trainer abstraction was added;
- delete generic dataset/artifact layers with only one format consumer;
- confirm no CP2 bridge or CP3 GRPO implementation appeared early.

### Commit

```text
s4(cp1): train one verified-trajectory SFT candidate
```

## 4. Checkpoint 2 — Pinned veRL bridge and matched Base/SFT evaluation

### Stage claim

The base model and SFT candidate can both act through one veRL-owned token path
and the unchanged S3 `PolicyDriver`/Host/lifecycle path, producing exact online
token/mask evidence and matched S3 outcomes.

### Work

Add one installable veRL adapter module and focused tests, normally:

```text
src/agent_env_foundry/verl_agent_loop.py
tests/test_verl_agent_loop.py
```

First verify the exact upstream SHA and required `AgentLoopOutput`,
`LLMServerClient`, Continuous Token and V1 custom-sampler contracts. Then attempt
the proof-first bridge:

```text
AgentLoop.run
-> run_task_episode in a worker thread
-> synchronous PolicyDriver
-> model generation scheduled on the veRL event loop
-> existing S3 Host and close/reopen checker
```

Retain generated token IDs exactly. Decode only for call/final parsing. Use the
v0.9.0 Continuous Token helpers for the CP0-frozen model family to build the
initial prompt, merge exact assistant IDs, and merge Host/tool observation
messages with mask `0`. Every rollout constructs a fresh bridge driver whose
`PolicySpec` exactly matches the request.

Each runtime row provides operational Release/TaskStore roots plus exact
`release_id`, `corpus_id` and `task_pack_id`. The adapter persists one concrete
rollout-binding receipt keyed by `episode_id`, retaining exact
`response_ids/response_mask`, group identity and matching S3 reward (inline or as
content-addressed blobs). CP3 cold-validates this receipt.

Do not add an incremental S3 session. If the focused proof fails on exact IDs,
masks, lifecycle, reward or fault attribution, stop and revise the design with
that test as evidence; do not implement a speculative seam inside this
checkpoint.

### Behavioral RED

After adding only the importable adapter interface scaffold, the first named RED
is:

```text
tests/test_verl_agent_loop.py::test_generated_token_ids_survive_non_round_trip_text
```

The fake token output deliberately does not round-trip through decoded text, so
the failure reaches token preservation rather than module import. Then add:

- generated assistant IDs are replaced by decode/re-encode output;
- environment observation token receives mask `1`;
- assistant tool-call/final-answer token receives mask `0`;
- direct actor invocation bypasses Host validation;
- reward is computed before or differently from the S3 Episode;
- protected/checker/witness data enters model input;
- model-server failure becomes a healthy policy failure or misowned Episode;
- one rollout reuses another rollout's native instance;
- Base and SFT evaluation use different templates, slots or budgets.

### Deterministic validation

- fake token output tests must preserve non-round-trippable token IDs;
- injected tool observation must have an all-zero environment mask;
- injected S3 `1.0`, `0.0` and `null` must transport distinctly;
- existing S3 success/failure/abstain and close/reopen tests remain unchanged;
- semantic mutants for token replacement, reward recomputation and Host bypass
  must fail.

Run the common full checks after focused tests.

### Physical exit

First load the exact CP1 HF export through the frozen rollout `model.path`.
Using the same frozen evaluation slots and normal framework runtime:

```text
base checkpoint -> S3 Episodes
SFT candidate   -> S3 Episodes
```

Both runs must cold-persist all requested success/failure/abstain slots. Report
verified success, public efficiency metrics and exact identities without silent
retry.

Run at least one same-TaskPack multi-rollout group to measure whether valid
numeric rewards contain nonzero GRPO signal. This is measurement, not a promise
of positive variance.

### Stop conditions

- the proof-first bridge cannot preserve the required contract;
- Base/SFT cannot use the same S3 and template path;
- the SFT candidate cannot produce valid model-owned tokens/tool calls;
- all available frozen groups are zero-signal;
- abstention or truth defects make reward evidence untrustworthy.

### Alignment and deletion review

- prove there is still one S3 Host/checker/reward path;
- prove no S3 refactor, second evaluator, service or model registry was added;
- remove performance-only bridge complexity;
- decide only now whether the SFT candidate is accepted for GRPO.

### Commit

```text
s4(cp2): bridge pinned verl rollouts to s3 truth
```

## 5. Checkpoint 3 — Terminal-reward GRPO and reloadable checkpoint

### Stage claim

One real nonzero-signal group of fresh S3 Episodes drives a genuine veRL GRPO
update, and the resulting checkpoint reloads and continues acting through the
same path.

### Work

Freeze one GRPO configuration:

```text
parent: accepted SFT checkpoint
trainer entrypoint: pinned v0.9.0 verl.trainer.main_ppo V1 sync
trainer.use_v1: true
trainer.v1.trainer_mode: sync
trainer.v1.sampler.custom_sampler: FoundryFailClosedReplayBuffer
trainer.v1.sampler.sync_refill_failed_groups: false
data.train_batch_size / data.gen_batch_size: 1 prompt group
algorithm: GRPO
group key: exact TaskPack/rollout request
groups per optimizer step: 1
reward: transported S3 terminal 1.0/0.0 only
actor_rollout_ref.rollout.n: frozen group size G
failed/incomplete/all-equal group refill/resample: disabled
no shaping/reward model/curriculum/retry/replacement
```

Before advantage/backward, the pin-specific sampler verifies the root status,
exact `G` siblings, matching cold Episode/token/mask evidence, numeric rewards
and nonzero variance. If any member abstains or the group is incomplete, persist
what S3 can seal, raise a typed error and leave the whole optimizer step and
parameter digest unchanged.

Do not add a group-local sentinel, filter, requeue or scheduler.

### Behavioral RED

The first named RED is:

```text
tests/test_verl_agent_loop.py::test_abstain_aborts_main_ppo_step_without_parameter_change
```

It reaches the CP2 adapter/trainer boundary with one sealable abstention and
compares before/after parameter digests. Then add:

- `null` reaches advantage as zero;
- an abstained or mismatched Episode reaches backward/update;
- two TaskPacks share a group identity;
- all-equal reward is treated as useful signal;
- response masks are ignored;
- checkpoint omits parent/data/config/veRL identity;
- post-update rollout uses stale weights;
- failed slots are silently replaced.

Semantic mutations must demonstrate that abstain-zero, reward mismatch and stale
weight bugs are detected before the real run.

### Physical exit

```text
fresh same-TaskPack rollout group with nonzero reward variance
-> GRPO advantages
-> backward and optimizer step
-> changed parameter/checkpoint digest
-> checkpoint save
-> cold reload
-> another fresh S3 rollout with reloaded weights
```

Then run only the frozen bounded training budget. Record requested and retained
slots, zero-signal groups, abstention failures, optimizer steps and checkpoint
identity.

### Stop conditions

- no nonzero-signal group exists under the frozen budget;
- abstention enters optimization or prevents trustworthy evidence;
- weights/checkpoints do not synchronize or reload;
- progress requires changing S3 reward truth or adding shaping.

### Alignment and deletion review

- confirm S3 remains reward authority;
- confirm only GRPO and one model family exist;
- delete scheduler, recovery, generic trainer and auxiliary reward code;
- accept a valid no-update/negative outcome rather than weaken truth.

### Commit

```text
s4(cp3): run terminal-reward grpo checkpoint
```

## 6. Checkpoint 4 — Frozen release-held-out learning utility

### Stage claim

Under one predeclared protocol, Base, SFT and SFT→GRPO behavior can be compared
on one Need/EnvironmentRelease never used for training, tuning or checkpoint
selection.

### Freeze before receiving the final Release

```text
code and integration commits
model/tokenizer/veRL/checkpoint identities
SFT and GRPO configs
primary contrast: SFT->GRPO minus Base
primary metric: paired numeric S3 terminal reward on slots trustworthy in both arms
abstain handling: retain/report every slot, exclude null from numeric estimate,
                  never replace
improvement threshold: > 0
statistical unit: TaskPack
exact paired TaskPack-clustered 95% CI implementation
decision rule: SUPPORTED only when estimate > 0 and CI lower bound > 0
checkpoint selection: terminal checkpoint at each exact frozen step budget;
                      no best-of-run selection
evaluation slot budget and framework-consumed sampling config
```

After this freeze, the parent Foundry operator (the user or supervising main
session, outside S4 production code) runs the already accepted S1, S2 and S3
workflows and delivers exact Release, Corpus, TaskPack and artifact-root
identities. S4 only consumes them; it does not add an orchestration path or edit
the Tasks/checkers.

Add only `scripts/s4_evaluate.py` and `tests/test_s4_evaluate.py` for the frozen
preflight, matched invocation and report calculation.

### Behavioral RED

After the importable evaluation preflight scaffold exists, the first named RED
is:

```text
tests/test_s4_evaluate.py::test_final_release_leakage_fails_before_model_call
```

Then add:

- final Release/TaskPack appears in training or tuning history;
- checkpoint selection reads final outcomes;
- evaluation slots/budgets differ across Base/SFT/GRPO;
- failed or abstained slots disappear from requested-slot accounting, or null is
  coerced into the paired numeric reward estimate;
- success is recomputed outside S3;
- a missing metric is fabricated from final text/trace;
- one Release result is generalized to arbitrary Needs;
- identities/config cannot reconstruct a reported result.

### Physical exit

Run all three checkpoints over the same frozen S3 slot list:

```text
Base
SFT
SFT -> GRPO
```

Publish one cold-reproducible utility report containing:

- verified success/failure/abstain counts and rates;
- the predeclared primary estimate and confidence interval;
- results by existing structure identity when denominators exist;
- public calls/turns/tokens/latency when recorded;
- GRPO variance/zero-signal information;
- exact source, checkpoint and config identities;
- existing raw S3 failure codes only, without a new taxonomy.

Completion is one of:

```text
SUPPORTED_ON_FROZEN_RELEASE
NOT_SUPPORTED_ON_FROZEN_RELEASE
```

The frozen rule emits `SUPPORTED_ON_FROZEN_RELEASE` only when the point estimate
and CI lower bound are both greater than zero. Every other mechanically valid
result, including an uncomputable CI, emits `NOT_SUPPORTED_ON_FROZEN_RELEASE`
with its reason. Neither label is a claim about all future Needs or proof of zero
effect.

### Alignment and deletion review

- verify the experiment answers the project learning-utility question rather
  than merely proving veRL can run;
- verify no final-data leakage, S1–S3 modification or hidden retry occurred;
- delete report fields without existing producers;
- confirm no later research baseline became a completion requirement.

### Commit

```text
s4(cp4): report frozen release learning utility
```

## 7. Task completion

The task completes only after Checkpoints 0–4 pass their physical exits,
independent reviews and separate commits. Code that has not yet been exercised by
its required framework command remains implemented but unverified; it cannot be
used to claim SFT, GRPO or learning success.

Additional models, algorithms, unverified-data baselines, curriculum, services,
distributed environment scheduling and generalized cross-Need claims require
separate evidence and tasks.
