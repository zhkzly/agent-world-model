# S3 Verified Episode Runtime

## 1. Scope / Trigger

Use this contract when executing current checker-free `TaskPack/1` artifacts as
policy Episodes or handing their public trajectories to S4. S3 consumes exact
S1/S2 authority and owns capture, post-reopen evaluation, reward and immutable
Episode artifacts. It does not generate Tasks or train models.

## 2. Signatures

```python
run_task_episode(
    prepared: OpenPreparedReleaseV3,
    task_pack: TaskPackArtifact,
    request: EpisodeRequest,
    *,
    instance_directory: Path,
    policy_driver: PolicyDriver,
) -> EpisodeRecord

write_episode_bundle(output_root: Path, record: EpisodeRecord) -> Path
read_episode_bundle(output_root: Path, episode_id: str) -> TrainingEpisodeView
read_episode_record(output_root: Path, episode_id: str) -> EpisodeRecord

run_episode_campaign(
    *,
    s1_campaign_root: Path,
    s2_campaign_root: Path,
    output_root: Path,
    source_commit: str,
    expected_s1_campaign_id: str,
    expected_corpus_manifest_id: str,
    route: AgentRoute,
    rollouts_per_task: int,
    workers: int,
) -> EpisodeCampaignResult
```

Current persisted formats are `episode-record/3`,
`training-episode-view/2`, `episode-slot-result/1` and
`episode-batch-manifest/2`.

## 3. Contracts

```text
cold Release + cold TaskPack
-> fresh instance and one reset
-> existing Host-owned public policy loop
-> complete calls/observations/final answer
-> close and reopen the same instance without reset
-> common Goal evaluator over real state, trace and answer
-> 1.0 / 0.0 / null
-> paired trusted/public Episode artifact
```

- Policy input is exactly system prompt, instruction, reset observation,
  ToolSpecs, prior ToolObservations and type-only answer schema.
- S2 sampling/reference/filter evidence, Goal truth, expected answer and
  protected state never reach the policy or `TrainingEpisodeView`.
- `EpisodeRecord/3` binds request, PolicySpec, materialization, complete capture
  including provider error details, protected before/post-reopen state,
  evaluation and reward.
- `TrainingEpisodeView/2` is derived from the trusted Record. It keeps ordered
  public turns/calls/observations/final answer and reward, but omits usage and
  all trusted truth.
- The evaluator checks exact reset, before/after state, answer schema/value and
  recursive Atom/All/If/ForEach Goal. It does not compare with an S2 path.
- The batch is multi-Release. Each result carries its own Release/TaskPack/Task
  request binding; there is no top-level single-Release assumption.
- Eight logical rollouts per TaskPack are fixed before execution. Release-level
  concurrency changes scheduling only, never request or Episode identity.

## 4. Validation & Error Matrix

| Condition | Result |
|---|---|
| trustworthy completion and evaluator pass | `verified_success / 1.0` |
| trustworthy policy/evaluator failure | `verified_failure / 0.0` |
| provider, environment or truth-path defect | `abstain / null` |
| authority failure before sealable Episode | blocked slot with owner/code/phase/details |
| wrong/missing Release or TaskPack binding | reject before policy use |
| state changes across close/reopen | abstain; never policy zero |
| record/view mutation under old ID | paired cold-read rejection |
| old `/1` or `/2` trusted Episode format | unsupported; no adapter |
| missing or duplicate request slot | final batch rejection |

Provider/private reasoning is neither requested nor fabricated. Public terminal
text and all public function calls are retained. A provider exception must keep
its status/original code/message in trusted capture details.

## 5. Good / Base / Bad Cases

- Good: real state and final answer satisfy the frozen Goal after reopen, giving
  `1.0` and an SFT-visible complete public trajectory.
- Base: a valid policy attempt reaches the wrong answer or misses a Goal; its
  trace is retained with `0.0` and excluded from positive SFT.
- Good failure: an HTTP/provider defect retains the public prefix and exact
  machine details with `null`.
- Bad: trust tool `ok`, final text, an LLM Judge, S2 reliability, or a reference
  trace as Episode success.

## 6. Tests Required

- Physical success, wrong-answer and provider-defect Episodes through one real
  Release process.
- Reward mutations independently kill `1.0`, `0.0` and `null` swaps.
- Record/View exact-shape, identity, canonical-byte, symlink, partial and
  relocation tests.
- Corpus/Release/TaskPack cross-binding and 1..N request-grid tests.
- Resume tests reject changed terminal slots and missing/duplicate fan-in.
- Public traversal proves zero protected/S2/evaluator leakage.
- A real campaign must cold-read every pair and reconstruct successful
  `messages + tools` without trusted data.

## 7. Wrong vs Correct

Wrong:

```text
Luna says done -> save as SFT success
```

Correct:

```text
Luna trajectory -> real close/reopen -> common evaluator -> reward
-> SFT later selects only cold reward=1 views
```

Wrong:

```text
copy old checker-bound S3 or refill failures until every rollout succeeds
```

Correct:

```text
one current TaskPack path, one attempt per fixed slot, every outcome retained
```
