# S3 Verified Episode Runtime — Product Requirements

## 1. Product goal

Given one exact qualified `EnvironmentRelease v2`, one admitted S2 `TaskPack`,
and one target acting policy, execute a real isolated tool-use episode and
publish a trustworthy immutable record containing:

```text
public policy trajectory
+ frozen Task verification
+ deterministic base Reward or abstention
+ complete failure attribution and execution cost
```

S3 turns an admitted Task into policy behavior evidence. It does not decide
which Tasks are valid and it does not optimize a model.

```text
S1 EnvironmentRelease
-> S2 TaskPack / CorpusManifest
-> S3 EpisodeRecord / EpisodeBatchManifest
-> S4 SFT/RL and held-out learning evidence
```

## 2. Exact stage boundary

### Inputs owned upstream

S3 consumes only cold-verified current artifacts:

- `EnvironmentRelease v2` and its prepared actor/trusted runtimes;
- S2 `TaskPack` with frozen instruction, StartCase and checker identity;
- optional `CorpusManifest` selecting exact TaskPack/Assessment pairs;
- a target policy identity and bounded execution configuration.

S3 may require a narrowly justified correction to shared S2 execution code when
an actual episode cannot preserve failed trajectories, public projection or
frozen verification. It may not modify Task meaning, lower admission gates or
regenerate a Task.

### Outputs owned by S3

S3 publishes:

- immutable `EpisodeRecord` artifacts for every completed rollout attempt;
- a strict non-leaking training/public trajectory projection;
- an `EpisodeBatchManifest` binding the requested corpus, policy and every
  attempt/result;
- aggregate success, failure, abstention, usage and latency evidence.

### Explicitly outside S3

- Candidate Task generation, Task admission and corpus selection;
- new Task checkers, challenge generation or Task correction;
- SFT formatting tied to a specific trainer, tokenization, token masks,
  log-probability collection, optimizer steps or checkpoints;
- LLM-as-Judge reward;
- service, queue, Registry, database or workflow-engine infrastructure.

## 3. S2 witness/assessment versus S3 episode

S2 witnesses answer: **does at least one public solution exist?**
S2 TaskAssessment answers: **how does a calibration policy perform for corpus
selection?**

S3 answers: **what did this target policy actually do on this exact admitted
Task, and what deterministic outcome/reward follows?**

S3 therefore preserves both success and failure episodes. It never compares the
policy trajectory with the S2 witness trajectory.

## 4. Required causal order

```text
1. cold-verify Release, TaskPack and optional CorpusManifest
2. derive one frozen EpisodeRequest
3. reconstruct the current Task kind and checker identity from Release + TaskPack
4. open one fresh native instance and reset with the trusted StartCase
5. create an exact public projection
6. let the target policy act through public tools only
7. preserve every public turn, tool call, observation, final answer or policy failure
8. close and reopen the same native instance without reset
9. execute the frozen Task checker on post-reopen truth
10. map verified outcome to base Reward or typed abstention
11. persist and immediately cold-read the EpisodeRecord
12. add the attempt to the EpisodeBatchManifest
```

Checker reconstruction and public projection validation happen before the first
policy call. Reward is computed only after post-reopen verification.

## 5. Public policy boundary

The acting policy may receive only:

```text
canonical instruction
fresh reset observation
current ToolSpecs
prior public ToolObservations
final-answer schema
public policy-system prompt
```

It must not receive:

```text
TaskPack admission/witnesses
StartCase input as a separate hint
semantic keys or protected bindings
expected If branch
native facts
checker digest or checker result
failure/challenge feedback
answer key or reference route
```

The Host owns tool-schema validation, dispatch, observation validation, trace
capture and policy-turn budgets.

## 6. Episode execution contract

### Complete trajectories, including failures

S3 must retain the public action history even when the policy:

- emits an unknown tool;
- emits malformed or schema-invalid arguments;
- reaches its provider-turn budget;
- returns a missing or schema-invalid final answer;
- performs valid state changes but does not complete the user-facing protocol.

A policy-level terminal failure is a valid failed Episode, not an exception that
discards prior actions. Infrastructure or trusted-runtime defects remain typed
abstentions.

### No hidden reasoning artifact

S3 stores only model-visible/actionable outputs required to reproduce tool use:

- ordered function calls and arguments;
- corresponding public observations;
- final structured answer or public terminal failure;
- per-turn usage metadata.

Provider-private reasoning items or hidden chain-of-thought are neither required
nor persisted.

### One shared execution path

There is one Host-owned public interaction and close/reopen lifecycle. The
existing S2 witness and TaskAssessment paths must reuse the same lower-level
mechanics after any required refactor. S3 must not create a second Responses
loop or a second verifier path.

## 7. Frozen verification

For each Episode, S3 must:

- verify the Task belongs to the exact prepared Release;
- recompute the current Task/checker preimage before acting;
- rediscover logical bindings from the fresh Start rather than reuse witness IDs;
- evaluate the actual trace, final answer and post-reopen facts;
- preserve the exact task-kind-specific checker request and result as trusted
  evidence;
- reject checker digest drift, missing bindings, TaskPack tampering and
  public/trusted projection leakage before reward.

S3 does not rerun S2's complete challenge matrix for every rollout. S2 admission
already established Task validity. S3 evaluates the actual Episode only.

## 8. Base Reward and abstention

S3 initially supports one fixed reward policy:

```text
binary-task-success/1
```

| Episode condition | disposition | reward |
| --- | --- | --- |
| public protocol completed and frozen checker satisfied | `verified_success` | `1.0` |
| environment/truth route valid, but policy failed or checker not satisfied | `verified_failure` | `0.0` |
| infrastructure, Environment, Task artifact, Semantics, Verifier or evidence integrity defect | `abstain` | `null` |

Examples that receive `0.0`:

- wrong tool/arguments caused by the policy;
- provider-turn budget exhausted without infrastructure failure;
- wrong target, partial completion, collateral damage or wrong answer;
- final answer missing after otherwise valid state changes.

Examples that abstain:

- provider/TLS outage;
- actor crash or invalid ToolObservation;
- TaskPack/checker identity mismatch;
- trusted inspection/evaluator crash or mutation;
- incomplete close/reopen evidence.

S4 may later add declared auxiliary shaping, but it cannot relabel a failed
frozen Task as success or turn abstained evidence into a training reward.

## 9. Core artifacts

### `PolicySpec`

Non-secret policy identity and actual public execution configuration. It binds:

- policy/model/checkpoint identifier;
- driver kind/version;
- public system-prompt digest;
- non-secret route digest;
- generation parameters actually used;
- provider-turn limit.

The existing research-specific hard-coded `AgentRoute` is not sufficient for
S3 target-policy evaluation and must not remain the Task episode identity.
Credentials are never serialized.

### `EpisodeRequest`

Frozen before execution:

```text
release_id
task_pack_id
task_id
policy_id
rollout_index
attempt_index
```

It contains no Task truth, answer or native value.

### `EpisodeRecord`

Trusted immutable artifact containing:

```text
request and policy identity
exact public episode input
ordered policy turns / trace / observations
final answer or policy terminal failure
usage and latency
native-instance and close/reopen evidence
frozen checker request/result
verified status and failure codes
base reward/disposition
```

### `TrainingEpisodeView`

Strict projection for S4 data construction. It contains the public trajectory,
IDs and reward label, but excludes protected facts, bindings, expected branch,
checker internals, S2 witnesses and admission challenges.

### `EpisodeBatchManifest`

Binds one exact CorpusManifest or explicit TaskPack set, one PolicySpec, the
frozen rollout count, every attempt/Episode ID and aggregate counts/cost. It
cannot change TaskPack or Episode truth.

## 10. Batch and retry policy

- Requests are enumerated deterministically from the exact corpus entries and
  rollout count.
- Policy failure is never retried as the same rollout; additional rollouts are
  separate requests.
- Infrastructure failure may use one frozen bounded retry policy, and every
  abstained attempt remains in the batch record.
- Task/Release/Semantics/Verifier trust defects fail closed and block further
  episodes for the affected authority; they are not converted to model failure.
- Initial implementation is serial. Parallel scheduling requires a measured
  throughput bottleneck and is not part of S3 correctness.

## 11. S4 handoff

S3 must support both:

1. offline cold-reading of `TrainingEpisodeView` for SFT/evaluation dataset
   construction;
2. one minimal public `PolicyDriver` boundary so a later S4 rollout engine can
   drive the same Host tool/evaluation path without gaining trusted access.

S3 does not implement trainer-specific chat templates or on-policy optimization.

## 12. Acceptance criteria

S3 is complete only when the frozen runtime:

- consumes relocated current Release, TaskPack and Corpus artifacts;
- runs Atom, ForEach and If TaskPacks through one shared runtime;
- preserves full partial trajectories for real policy-level failure paths;
- records at least one physical `verified_success`, one physical
  `verified_failure` and one injected/reproduced `abstain` without conflating
  their owners;
- verifies after real close/reopen of the same native instance;
- cold-reads EpisodeRecord and TrainingEpisodeView with exact identity/projection
  checks;
- executes Git, SQLite and post-freeze held-out releases without domain branches;
- proves S2 witnesses/admission data never enter policy input;
- exposes one direct batch API and one Responses policy driver, with no service
  or Registry;
- leaves TaskPack identities unchanged and leaves training implementation to S4;
- passes deterministic quality, focused mutation and real execution evidence.

## 13. Fatal rejection criteria

Reject the S3 design/implementation if it:

- rewards model text through an LLM Judge instead of frozen truth;
- drops failed trajectories or labels provider outages as policy failure;
- evaluates in-memory state without the declared close/reopen lifecycle;
- creates a new Task/checker/admission path;
- passes protected TaskPack fields to the policy or training projection;
- requires one trajectory to match an S2 witness;
- stores hidden reasoning as a training requirement;
- introduces a service, queue, plugin registry, universal trajectory ontology or
  trainer-specific data framework without a demonstrated blocker.
