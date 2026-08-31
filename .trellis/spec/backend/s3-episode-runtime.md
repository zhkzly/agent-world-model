# S3 Verified Episode Runtime

## 1. Scope / Trigger

Use this contract when turning one exact current S2 TaskPack or one exact
single-release CorpusManifest into acting-policy Episodes and the public reward
view handed to S4.

S3 consumes immutable S1/S2 authority. It never generates, repairs, re-admits
or reselects Tasks, and it contains no trainer, retry scheduler, service,
Registry or domain branch.

## 2. Signatures

```python
capture_public_episode(
    *,
    actor: Environment,
    instruction: str,
    reset_observation: JSONValue,
    answer_schema: JSONObject,
    policy_driver: PolicyDriver,
) -> PublicEpisodeCapture

run_task_episode(
    prepared: OpenPreparedRelease,
    task_pack_path: Path,
    expected_task_pack_id: str,
    *,
    policy_driver: PolicyDriver,
    rollout_index: int,
    instance_root: Path,
) -> EpisodeRecord

write_episode_bundle(output_root: Path, record: EpisodeRecord) -> TrainingEpisodeView
read_episode_bundle(output_root: Path, episode_id: str) -> TrainingEpisodeView

run_episode_batch(
    prepared: OpenPreparedRelease,
    task_store_root: Path,
    corpus_manifest_path: Path,
    expected_corpus_id: str,
    output_root: Path,
    *,
    policy_spec: PolicySpec,
    policy_driver_factory: Callable[[], PolicyDriver],
    rollouts_per_task: int,
) -> EpisodeBatchManifest
```

Current TaskPack formats are exactly `atom-task-pack/4`,
`foreach-task-pack/3` and `if-task-pack/3`.

## 3. Contracts

### Policy and public capture

- `PolicySpec` contains model, driver kind/version, normalized non-secret route,
  prompt digest and the one positive Host turn limit. It contains no credential,
  path, retry or generic config bag.
- One `PolicyDriver` belongs to one Episode. It receives public input and prior
  public observations, makes one decision per Host call and is closed by the
  Host. It cannot reset, invoke, inspect or check.
- The Host snapshots ToolSpecs once, validates and dispatches calls, records raw
  invalid material and derives checker TraceEvents only from dispatched calls.
- Provider-private reasoning is never stored.

### Exact Task lifecycle and reward

The concrete S3 lifecycle is:

```text
acting_open -> reset -> capture_terminal -> pre_close_inspect -> acting_close
-> reopened_open -> post_reopen_inspect -> checker_evaluated -> reopened_close
```

- Reopen uses the same native directory, a distinct session and no reset.
- Atom/ForEach/If use the existing AtomCheckRequest and ConditionCheckRequest
  documents. The checker trace, final answer and facts must agree with the one
  public capture.
- `ReloadEvidence/1` remains the exact legacy S2 projection and uses
  `episode_complete`, not `capture_terminal`. It exists only for a completed,
  defect-free, full lifecycle.
- Reward is closed:

```text
completed + checker satisfied + no defect -> verified_success / 1.0
healthy policy terminal or checker failed -> verified_failure / 0.0
provider/infrastructure/trust defect       -> abstain / null
```

Any defect takes precedence over satisfying state. TaskAssessment, witnesses
and corpus reliability never affect reward.

### Record and TrainingEpisodeView

`EpisodeRecord` identity binds request, policy, complete capture, Host policy
elapsed time, native/session lifecycle, fact digests, exact checker documents,
optional ReloadEvidence and RewardOutcome. Paths are absent.

Bundles are paired:

```text
episodes/<episode_id>/EpisodeRecord.json
episodes/<episode_id>/TrainingEpisodeView.json
```

The paired reader reconstructs and validates the Record first, derives the
expected view, requires exact equality with the canonical view file and returns
only the derived `TrainingEpisodeView`. There is no independent view reader or
view identity.

The view contains IDs, full EpisodeRequest, exact public input, public turns
without usage, completion and disposition/reward. It excludes PolicySpec
details, defects/owners, usage, elapsed time, native/lifecycle/facts, checker
data, ReloadEvidence, S2 evidence and hidden reasoning.

### Exact Corpus batch

- A batch accepts one expected canonical `corpus-manifest/1` whose entries all
  use the prepared Release.
- TaskPacks resolve only at
  `<task_store_root>/batch/taskpacks/<task_pack_id>/<current filename>`.
- All valid requests and authority-blocked slots freeze in Corpus order and
  1-based rollout order before the first driver factory call.
- Execution is serial, one fresh driver and one attempt per valid request. There
  is no retry.
- Invalid TaskPack authority creates no request; pre-input failures after a
  request create request-bound blocked slots. Unattributed failures abort.
- Every returned Episode is paired-written and cold-read. Publication failure
  aborts without a final manifest or fabricated remainder.
- Aggregates are recomputed from persisted Records and blocked slots. Missing
  usage is explicit; monetary cost is not claimed.

## 4. Validation & Error Matrix

| Condition | Required result |
| --- | --- |
| noncanonical/wrong TaskPack before request | typed Task authority failure; no Episode |
| malformed embedded If branch | reject before policy call |
| reset/preflight fails after request, before public input | no Episode; request-bound blocked batch slot |
| healthy refusal/malformed call/missing answer/turn budget | complete policy-failure capture; checker runs; reward `0.0` |
| explicit provider or infrastructure defect after public input | retain capture and lifecycle; reward `null` with exact owner |
| unattributed driver/runtime exception | abort; do not guess owner or publish training evidence |
| reopen/checker evidence incomplete | typed abstain; never verified failure |
| checker trace/final answer/facts differ from capture | Record rejection |
| view differs from derived Record projection | paired-reader rejection |
| partial/symlink/noncanonical bundle | paired-reader rejection |
| duplicate Episode directory | collision; existing bytes unchanged |
| multi-release Corpus or prepared-Release mismatch | whole batch rejected before output/provider use |
| missing/invalid TaskPack in valid Corpus | every affected rollout blocked with no fabricated request |
| reused/mismatched driver | request-bound evidence block; no policy call |
| same-Task trusted pre-input defect | remaining frozen rollouts blocked; no repeat attempt |
| Episode publication/cold-read failure | abort batch; no final manifest/fake remainder |

## 5. Good / Base / Bad Cases

- Good: a completed Atom mutates real state, closes/reopens, passes the frozen
  checker, persists/relocates and returns view reward `1.0`.
- Good: a policy mutates state then omits its answer; the full trajectory and
  checker evidence survive and reward is `0.0`.
- Good: a provider defect after public activity yields a relocated paired view
  with `reward=null`, while owner details stay only in the Record.
- Base: one exact Corpus serially retains success, failure, abstain and blocked
  slots with reconciled aggregates.
- Bad: retry a failed policy, trust a view without its Record, derive reward from
  TaskAssessment, copy checker codes into the view, or add a domain-specific
  Task branch.

## 6. Tests Required

- Contract tests for structural JSON snapshots, policy/request identity and the
  complete RewardOutcome truth table.
- Host tests for raw malformed calls, one ToolSpec snapshot, owner separation,
  single-use/close and Responses continuation.
- Runtime tests for all three Task kinds, lifecycle order, no second reset,
  checker/capture/facts binding, 1/0/null and pre-input no-Record behavior.
- Artifact tests for exact view keys, structural leakage exclusion, fresh-ID
  malformed checker rejection, tamper, partial, symlink, collision and
  relocation.
- Batch tests for prefreeze-before-factory, fresh drivers, no retry, every slot,
  owner/stop behavior, publication abort and cold aggregate reconciliation.
- Mutation licences must kill reward precedence, lifecycle order, If embedded
  authority, view leakage/Record bypass, dropped slots and aggregate changes.
- Stage evidence must include exact Git, SQLite and held-out maintenance
  authorities plus one live Responses batch and one scripted second driver.

## 7. Wrong vs Correct

Wrong:

```python
view = json.loads((bundle / "TrainingEpisodeView.json").read_text())
train(view)  # trusts a projection with no Record verification
```

Correct:

```python
view = read_episode_bundle(output_root, expected_episode_id)
# Reader cold-validates EpisodeRecord and exact projection before returning.
```

Wrong:

```python
while not success:
    record = run_task_episode(...)  # retry-until-success changes the rollout
```

Correct:

```python
record = run_task_episode(...)  # exactly one attempt; failure is retained
```
