# S4 Verified Agent Learning — Product Requirements

## 1. Authority and stage

This task is a candidate specialization of the stable S4 `SFT/RL` stage in
`PROJECT.md` and the accepted decisions in `DECISIONS.md`. It cannot redefine
S1–S3 truth or cite edits made by this candidate as upstream authority.

The task remains planning authority until it is explicitly activated. Its
purpose is to test one concrete learning path, not to build a training platform.

## 2. Product goal and claim boundary

Use current S1–S3 artifacts to train one target model through:

```text
fixed-budget teacher Episodes through S3
-> verified-success SFT data
-> one SFT checkpoint
-> online veRL rollout through the same S3 Host
-> terminal S3 reward
-> one GRPO checkpoint
-> matched evaluation on one post-freeze release-held-out Need
```

Completion requires real checkpoints and S3-verified behavior. A dataset build,
falling loss, one optimizer call or one successful training Task is not enough.

One final held-out Release supports only a bounded conclusion about that frozen
Release and evaluation protocol. It does not establish population-wide transfer
to arbitrary Needs or prove that verification is causally superior to every
unverified-data alternative.

## 3. Frozen inputs

Checkpoint 0 freezes:

- exact EnvironmentRelease, CorpusManifest and TaskPack identities;
- one explicit teacher `PolicySpec` and one executable driver factory/route whose
  resolved provider sampling configuration matches it;
- teacher collection budget, including rollouts per TaskPack and turn limit;
- one exact target model, tokenizer, tool-use chat template, tool-call parser and
  tool-observation representation;
- exact train/dev role assignments keyed by existing Corpus fields;
- exact veRL upstream commit, literal SFT/GRPO entrypoints and resolved training
  configuration;
- SFT, rollout and GRPO budgets and the framework-consumed training seeds.

The upstream pin is the latest stable veRL `v0.9.0` release at
`483b8a009ba3a97563edee3a19887e4862b8094a`. Checkpoint 0 verifies the installed
checkout and required APIs against that exact SHA before consuming it. S4 does
not track the release branch after the freeze.

veRL remains an external unmodified checkout by default. Foundry integration is
an installable overlay; it does not vendor or fork upstream first. A patch is
considered only after a focused extension-point failure and separate review.

Device selection is ordinary framework/runtime configuration. S4 implements one
normal veRL path and adds no CPU/GPU fork, remote runner, scheduler or handoff
protocol.

The target profile must pass veRL v0.9.0's Continuous Token model-family wiring
and chat-template checker. Failure stops CP0; S4 does not add another codec to
support an incompatible target.

## 4. Formal teacher Episode collection

Existing S3 checkpoint/acceptance Episodes prove the S3 contract; they are not
implicitly the S4 training cohort. In particular, scripted-policy Episodes are
test evidence rather than primary imitation targets.

The first S4 data action uses the existing S3 `run_episode_batch` path:

```text
exact CorpusManifest
+ frozen teacher PolicySpec
+ matching fresh PolicyDriver factory/route
+ frozen rollouts_per_task and turn budget
+ fresh isolated instances
-> one honest result per requested slot
-> persistent EpisodeRecord/TrainingEpisodeView bundles
-> existing EpisodeBatchManifest
```

Collection rules:

- no retry-until-success, success backfilling or failed-slot replacement;
- retain verified success, verified failure, abstain and blocked outcomes;
- write to a declared persistent artifact root rather than treating `/tmp` as
  canonical training authority;
- bind the eligible cohort to exact batch, policy and Episode identities;
- never use S2 witnesses, admission routes or protected facts as demonstrations.

No arbitrary Task/structure/sample threshold is invented in this task. The
primary SFT source set is all allowlisted train-role verified successes from the
frozen batch; it is not post-hoc success subsampling. If that set is empty,
Checkpoint 0 stops with concrete evidence.

## 5. S3 truth and reward boundary

S4 preserves the current terminal policy:

| S3 disposition | reward | use |
| --- | ---: | --- |
| `verified_success` | `1.0` | eligible for positive SFT and RL |
| `verified_failure` | `0.0` | excluded from positive SFT; eligible for RL |
| `abstain` | `null` | never trainable |

Tool-call parsing, schema validation, dispatch and observation integrity are not
Task reward. S3 produces the one Task-level reward only after closing/reopening
the same native instance and running the frozen checker over authoritative state,
actual public trace and final answer.

S4 transports that outcome. It cannot add per-call shaping, an LLM judge, a
second verifier or a witness-trace comparison.

For initial GRPO behavior, S4 uses the v0.9.0 V1 `verl.trainer.main_ppo`
entrypoint in sync mode, one TaskPack/prompt group per optimizer step, and one
pin-specific `FoundryFailClosedReplayBuffer` through the documented custom
sampler hook. It rejects any failed/incomplete/non-numeric/all-equal group before
advantage or update and never refills it. Any S3 abstention therefore makes the
whole optimizer step fail closed. The Episode is retained when sealable; no
numeric sentinel, replacement, retry or requeue is introduced.

## 6. Primary SFT cohort and format

A primary SFT sample must be:

```text
member of the frozen teacher batch allowlist
and teacher policy is not scripted
and cold-valid TrainingEpisodeView
and disposition == verified_success
and reward == 1.0
```

Scripted Episodes remain available for S3 regression tests and analysis but do
not enter the primary imitation cohort.

`TrainingEpisodeView` contains structured public turns, not the teacher model's
original token IDs. Offline SFT therefore:

1. maps the structured public conversation into the frozen target model's
   messages/tools format;
2. applies the target tokenizer/chat template deterministically once;
3. trains assistant tool-call and final-answer spans;
4. masks system, user, reset and tool-observation context.

It must not claim equality with unavailable teacher token IDs. Failed and
abstained Episodes cannot become positive SFT targets. The SFT command exports
one HF-compatible model/tokenizer directory that the CP2 rollout `model.path`
loads directly; a trainer-only shard layout is not the handoff.

## 7. Online veRL/S3 path

Implement one model-family integration against the exact veRL pin. First test
the smallest bridge through the existing S3 `PolicyDriver` and
`run_task_episode` ownership. A new incremental S3 session API is not authorized
by this plan.

Only a focused functional failure proving that the existing boundary cannot
preserve exact generated token IDs, masks, S3 lifecycle/reward or correct defect
attribution may stop the checkpoint and trigger a separate design review for the
smallest S3 change.

For a trainable rollout, enable the v0.9.0 Continuous Token path for the one
CP0-validated target model family:

```text
veRL Continuous Token builds the public prompt
-> veRL returns exact model token IDs
-> parsing uses a decoded copy only
-> existing S3 Host validates and executes public tool calls
-> upstream Continuous Token merges public observation messages with mask 0
-> exact model-generated tokens retain mask 1
-> existing S3 close/reopen checker produces 1.0 / 0.0 / null
-> AgentLoop transports the S3 result
```

The adapter cannot call the actor directly, rebuild generated assistant tokens,
inspect trusted state or implement a second environment/checker loop.

## 8. Learning splits

Split identity comes from existing Corpus authority:

```text
corpus_id + release_id + structure_id + task_pack_id
```

S4 assigns train/dev roles in the cohort file using those existing keys; `role`
is not claimed to be a Corpus field. If no dev role is available, the experiment
uses the single frozen training recipe without dev-driven tuning or checkpoint
selection. The final release-held-out role is created only after
code/config/metric freeze.

The current Corpus does not demonstrate same-structure/different-instance pairs,
so instance-held-out is not a completion gate. S4 does not add a
`task_structure_id` field or synthesize a proxy identity.

## 9. Required comparisons and reporting

Use one S3 runtime, prompt/tool template and matched evaluation slot budget for:

```text
base model
SFT checkpoint
SFT -> GRPO checkpoint
```

Report only evidence with an existing producer:

- verified success, verified failure and abstain counts/rates;
- result by existing Release/structure identities when the denominator exists;
- repeated-run reliability under the frozen slot budget;
- public calls, turns, tokens and latency when present;
- GRPO reward variance and all-equal-group rate;
- exact model, tokenizer, data, config, checkpoint and Episode identities;
- raw frozen S3 failure codes when already available, without inventing a new
  cross-TaskKind error taxonomy.

Before the final Release is selected, freeze:

- primary contrast: `SFT->GRPO minus Base`;
- primary metric: mean paired S3 numeric terminal reward over matched slots that
  are trustworthy in both arms;
- abstentions: excluded from the numeric reward estimate but retained and
  reported for every requested slot, with no replacement;
- improvement direction and threshold: strictly greater than `0`;
- statistical unit: TaskPack, with the exact paired TaskPack-clustered 95% CI
  procedure checked in before evaluation;
- checkpoint-selection rule: use the terminal checkpoint at the exact frozen SFT
  and GRPO step budgets; no best-of-run selection;
- all secondary `SFT-Base` / `GRPO-SFT` reports.

`SUPPORTED_ON_FROZEN_RELEASE` is emitted only when the primary point estimate is
positive and the frozen CI lower bound is greater than `0`. Otherwise, including
when the CI cannot be computed under the frozen method, the result is
`NOT_SUPPORTED_ON_FROZEN_RELEASE` with the reason retained. This is a support
decision, not a claim of zero effect.

## 10. Evidence artifacts

Each checkpoint persists only the resolved configuration and receipt consumed by
the next checkpoint beside its real dataset, checkpoint or evaluation output.
Existing S3 manifests and trainer checkpoint/config outputs are reused.

Do not create a generic artifact base class, registry or seven predeclared
manifest types. Paths and credentials are operational metadata; semantic
identity binds exact content and configuration digests.

## 11. Explicitly outside S4

- changes to S1/S2 generation, Task admission or checkers;
- S2 witness demonstrations or protected-state model features;
- per-call reward, shaping or reward models;
- trainer/model/algorithm registries;
- additional model families or RL algorithms;
- HTTP Episode services, queues, schedulers or environment pools;
- CPU/GPU-specific Foundry implementations;
- automatic curriculum or Task evolution;
- silent rollout retry/replacement;
- a normalized failure taxonomy without a stable S3 producer.

## 12. Acceptance criteria

S4 is complete only when:

- the formal collection command completes, the cohort binds its in-process
  validated batch identity, and every sealable cohort Episode cold-reads;
- one target model/template and exact veRL commit are bound to resolved configs;
- primary SFT data contains only eligible real teacher successes;
- one real SFT optimizer update changes trainable parameters, exports an
  HF-compatible checkpoint, cold-loads with the same logical tensor digest and
  is evaluated through S3;
- the veRL model drives the existing S3 Host path with exact token/mask truth;
- every trainable rollout binds one matching S3 Episode and terminal reward;
- abstention causes a recorded zero-update step rather than numeric reward;
- at least one nonzero-signal GRPO update, save/reload and continued rollout run;
- base/SFT/GRPO use matched S3 evaluation slots;
- one post-freeze release-held-out evaluation mechanically yields the bounded
  frozen-rule result;
- all five checkpoints pass alignment/deletion review and separate commits;
- S1–S3 truth and public/trusted boundaries remain unchanged.

## 13. Fatal rejection criteria

Reject completion if:

- scripted or non-allowlisted evidence silently enters primary SFT;
- tool validity or final text alone becomes Task success;
- `abstain` becomes zero, disappears or triggers replacement;
- online model tokens are reconstructed through decode/re-encode;
- offline SFT claims preservation of unavailable teacher token IDs;
- a second Host/checker path or protected-data input is introduced;
- a predesigned S3 session refactor is implemented without focused failure;
- all available GRPO groups are zero-signal but useful RL is claimed;
- final evaluation data enters training, tuning or checkpoint selection;
- one held-out Release is generalized to arbitrary Needs;
- falling loss or code completion substitutes for physical learning evidence.
