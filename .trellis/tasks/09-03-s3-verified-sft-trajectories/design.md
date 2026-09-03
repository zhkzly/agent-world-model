# S3 Verified SFT Trajectories — Design

## 1. Clean-break boundary

Build S3 from the final `s2-good-task-sampler` branch. Do not merge the old
`s3-episode-runtime`: it consumes generated Checker artifacts, old TaskPack
kinds and a single-Release CorpusManifest.

Reuse only current production primitives:

- `prepare_release_v3_internal` and fresh `OpenPreparedSessionV3` instances;
- `load_task_pack` and its separate public/trusted projections;
- `capture_public_episode` and `ResponsesPolicyDriver`;
- `TraceEvent`, `EvaluationContext` and `evaluate_goal`;
- `PolicySpec`, `EpisodeRequest`, `PublicEpisodeCapture` and `RewardOutcome`.

Remove the stale `checker` defect-owner value from the current leaf contract.
Introduce no alternative execution loop or evaluator.

## 2. End-to-end data flow

```text
S1 campaign records --------------------------┐
                                              v
S2 CorpusManifest -> TaskPack member -> resolve matching Release root
                                      -> cold prepare Release
                                      -> freeze EpisodeRequest
                                      -> open fresh instance / reset / read before state
                                      -> capture_public_episode(Luna)
                                      -> read pre-close state / close
                                      -> reopen same instance / read post-reopen state / close
                                      -> evaluate frozen Goal with actual trace and answer
                                      -> derive RewardOutcome
                                      -> write + cold-read EpisodeRecord/View pair
all 552 terminal slots -> deterministic fan-in -> EpisodeBatchManifest
```

The S1 campaign record is the sole Release-ID-to-root mapping. The S2 member is
the sole TaskPack path and Release binding. S3 never discovers artifacts by
scanning for a convenient match.

## 3. Contracts

### 3.1 Episode request

The existing request identity remains:

```python
EpisodeRequest(
    release_id,
    task_pack_id,
    task_id,
    policy_id,
    rollout_index,
)
```

`rollout_index` is 1 through 8 for each TaskPack. Parallel scheduling cannot
change the request ID.

### 3.2 EpisodeRecord/2

One trusted record contains:

```text
format / episode_id
request / policy
materialization_id
public capture (input, turns, completion or defect, usage)
protected before_state
protected post_reopen_state
common EvaluationResult or typed trust defect
RewardOutcome
```

The Episode ID hashes the complete canonical record except its own ID. Host
paths and credentials never enter the record or identity.

### 3.3 TrainingEpisodeView/2

Derived mechanically from the trusted record:

```text
episode/request/release/task-pack/task/policy IDs and rollout index
system prompt, instruction, reset observation, ToolSpecs, answer schema
ordered public turns and calls
public ToolObservations and terminal/final answer
disposition and nullable reward
```

Usage may remain trusted accounting and is omitted from the training view.
Hidden reasoning is not part of the observable environment protocol.

### 3.4 EpisodeBatchManifest/2

The corpus is multi-Release, so the old top-level `release_id` contract is
deleted. Each result binds:

```text
release_id / task_pack_id / task_id / rollout_index / request_id
episode_id or typed pre-Episode failure
disposition / reward or failure owner+code
```

The manifest also binds the exact S1 campaign, S2 corpus, PolicySpec and
rollout count. Deterministic ordering is `(task_pack_id, rollout_index)`.

## 4. Episode execution

1. Cold-load member, TaskPack and Release and cross-check all identities.
2. Freeze `EpisodeRequest` before opening the actor.
3. Open a new instance, reset exactly once, and capture protected before state.
4. Snapshot public tools and run the existing Host-owned Responses loop.
5. Preserve policy failure or provider defect with its public prefix.
6. Close, reopen the same materialization without reset and read protected
   state. Any unreliable lifecycle/truth step forces abstention.
7. Convert only validated dispatched calls to evaluator `TraceEvent`s.
8. Evaluate the TaskPack's frozen `GoalTruth`; alternate valid action paths are
   allowed.
9. Derive reward by fixed precedence: trust defect, success, then failure.
10. Persist the trusted record and derived public view atomically enough that a
    partial directory is never readable as an Episode.

There is no model feedback or repair loop in S3.

## 5. Complete trajectory and SFT projection

S3 stores the provider-independent public semantics, not tokenizer output:

```text
assistant function call -> tool observation -> ... -> assistant final answer
```

Raw call material is retained for failures; successful SFT eligibility later
requires validated dispatched calls with observations and a completed final
answer. S4 can render the cold view as `messages` plus `tools` without trusted
state. It may select and deduplicate verified successes, but cannot reinterpret
S3 reward.

## 6. Failures and scheduling

- Authority mismatch before a valid request: terminal batch slot, no Episode.
- Failure after public input exists: retain public prefix; abstain when truth is
  untrustworthy.
- Valid policy failure with trustworthy reopen/evaluation: reward `0.0`.
- Provider/infrastructure/truth failure: reward `null`, never `0.0`.
- Each logical rollout is attempted once by S3. Transport behavior is frozen by
  the driver; the campaign does not refill failures under another index.
- Up to eight TaskPack/Release jobs run concurrently. Work inside one Episode
  remains sequential because observations causally determine later calls.

Terminal slot files are written before fan-in so an interrupted campaign can
resume missing slots without changing completed identities.

## 7. Artifact layout

```text
<output>/
  campaign-config.json
  slots/<task_pack_id>/<rollout_index>.json
  episodes/<episode_id>/
    EpisodeRecord.json
    TrainingEpisodeView.json
  EpisodeBatchManifest.json
  summary.json
```

The configuration freezes source commit, exact upstream IDs, PolicySpec,
rollout count and worker limit. Runtime worker count affects scheduling and is
reported; it does not enter EpisodeRequest identity.

## 8. S3/S4 boundary

S3 produces immutable tokenizer-neutral trajectory truth. S4 owns:

```text
select reward=1 successes
-> trajectory-quality/dedup policy
-> messages/tools projection
-> exact target chat template and tokenizer
-> assistant-only loss mask
-> Parquet and training
```

A small consumer probe in S3 tests that a cold view contains sufficient public
information. It is not a second production exporter or veRL adapter.

## 9. Deletion and non-growth rule

Do not copy old `episode_runtime.py`, `episode_batch.py`, old TaskPack readers or
S4 training code. Implement only the current multi-Release runtime, artifact
reader/writer and campaign command. Every new abstraction must have at least two
current call sites or own one persisted boundary.
