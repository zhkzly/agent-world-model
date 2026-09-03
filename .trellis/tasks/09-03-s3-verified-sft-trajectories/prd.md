# S3 Verified SFT Trajectories

## Goal

Consume the exact completed S1/S2 artifacts and collect real, immutable policy
Episodes that are sufficient for a later S4 adapter to create multi-turn SFT
data:

```text
20 EnvironmentRelease/3 artifacts + 69 checker-free TaskPacks
-> 8 fresh Luna rollouts per TaskPack
-> complete public action/observation/final-answer trajectories
-> post-reopen common Goal evaluation
-> reward 1.0 / 0.0 / null
-> EpisodeRecord/3 + TrainingEpisodeView/2 + EpisodeBatchManifest/2
```

The product outcome is verified trajectory data, not an interface-only demo.

## Frozen Inputs

- S1 campaign:
  `486dd2349f1eccb2f2ee096447a7c2325e811ecd92b6189722a69ed49a09ad7d`.
- S2 campaign:
  `4453f83c7126724c6e695dd3ee402c270d30e652dcf8d2a1425a0a94aefb08b8`.
- S2 CorpusManifest:
  `7ce6f07703acf6a60f4c67ff784f18bfac75821f1c47ba979fc7a553288f186e`.
- Exactly 69 current `TaskPack/1` artifacts across 20 Release IDs.
- Teacher route: `gpt-5.6-luna` through
  `http://127.0.0.1:8317/v1`, using the frozen public policy prompt.
- Exactly 8 logical rollout slots per TaskPack: 552 total.
- Release-level worker limit 8, based on the successful S2 route evidence.

## Requirements

### R1. Current authority only

S3 cold-loads the current multi-Release CorpusManifest, every referenced
TaskPack and the matching S1 Release. IDs, paths and Release bindings must agree
before acting. Old checker-bound TaskPack/Episode formats and the old
`s3-episode-runtime` implementation are unsupported; no compatibility reader,
adapter or feature flag may be added.

### R2. One real fresh policy Episode per slot

Each `(task_pack_id, policy_id, rollout_index)` freezes one `EpisodeRequest` and
uses a new native environment instance. The acting policy sees only:

```text
system prompt
Task instruction
fresh reset observation
public ToolSpecs
prior public ToolObservations
type-only final-answer schema
```

It never sees the S2 sampling/reference/filter trajectories, protected state,
Goal truth, expected answer or evaluator internals. The existing Host-owned
Responses tool loop remains the sole policy loop.

### R3. Complete observable trajectory

Retain every public policy turn, attempted function call, raw and parsed
arguments, dispatch status, real ToolObservation, public terminal and final
answer. Retain provider usage in trusted evidence. Provider-private reasoning
or hidden chain-of-thought is neither requested nor fabricated; any actually
public assistant text is retained exactly.

### R4. Physical final verification

After policy termination, close and reopen the same native instance without
reset. Read protected task-neutral state and run the same common
`Atom/All/If/ForEach` evaluator used by S2 against the frozen Task Goal, actual
public trace, final answer and real before/after state. Do not compare against
an S2 solution trace and do not generate a Checker.

### R5. Reward and abstention

```text
trustworthy Episode and Goal satisfied       -> verified_success / 1.0
trustworthy Episode but Task not satisfied   -> verified_failure / 0.0
untrustworthy provider/truth/runtime path     -> abstain / null
```

A malformed call, missing answer, refusal or turn-budget exhaustion is a real
policy failure only when environment and evaluation truth remain trustworthy.
Infrastructure/trust failure must never become reward zero. One logical slot is
not secretly replaced by retry-until-success.

### R6. Trusted and training projections

`EpisodeRecord/3` binds request, policy, complete public capture including typed
provider/runtime failure details, protected
before/post-reopen state, common evaluation and reward. Its derived
`TrainingEpisodeView/2` contains only the public input, ordered observable
interaction, completion and reward plus exact source IDs. It excludes
protected facts, Goal truth, expected answers, S2 evidence and evaluator data.

`EpisodeBatchManifest/2` covers all 552 requested slots across all 20 Releases
and reports success, failure, abstention, tool-call, turn, token and trajectory
length statistics. Every artifact must cold-read after relocation.

### R7. SFT handoff, not training

S3 remains tokenizer-neutral. A later S4 adapter selects only cold
`verified_success` views for positive SFT, maps them losslessly to
`system/user/assistant-tool/tool/assistant-final` messages and lets the pinned
trainer own chat-template rendering, tokenization and assistant-only loss
masks. S3 does not emit Parquet, token IDs, masks, checkpoints or optimizer
state.

## Acceptance Criteria

- [ ] One production API consumes the exact 69-member multi-Release corpus and
      creates all 552 logical rollout results without domain-specific branches.
- [ ] Every policy slot uses a fresh reset and records a complete public
      trajectory, including failed policy attempts.
- [ ] Every sealable Episode is evaluated after close/reopen by the current
      common Goal evaluator; old Checker code and trace matching are absent.
- [ ] Physical examples produce real `1.0`, `0.0` and typed `null` outcomes
      without changing Task truth.
- [ ] Every TaskPack has at least one verified-success Episode for the primary
      SFT cohort, or SFT readiness fails explicitly without extra hidden retries.
- [ ] Successes cover all supported Goal/outcome categories present in the
      corpus and all 20 Release IDs.
- [ ] EpisodeRecord/View pairs and the batch manifest pass local and relocated
      cold reads with recomputed identities.
- [ ] Public/SFT projections leak zero Goal truth, protected state, expected
      answer, reference/filter evidence or evaluator internals.
- [ ] A consumer probe reconstructs lossless multi-turn messages and tools from
      a cold success view without reading trusted Episode data.
- [ ] The final campaign reports exact IDs, terminal counts, success rate,
      per-Task coverage, turns, calls, tokens, lengths, concurrency and elapsed
      time; partial or green-only runs are not completion.

## Out of Scope

- More Environment generation or expansion from 20 to 50 Releases.
- Task generation, repair, re-admission or corpus reselection.
- Per-Task Checker, generated verifier, Tool Graph or S2 trace matching.
- SFT curation policy, Parquet conversion, tokenizer/template integration,
  training, checkpoints, GRPO or learning-improvement claims.
- Service, Registry, scheduler, generic driver/plugin or sandbox frameworks.

## Open Questions

None. The user approved the eight-rollout Luna trajectory direction; technical
details above are resolved by current code and stable project boundaries.
