# S3 Verified Episode Runtime — Product Requirements

> **Planning status:** candidate proposal only. The parent and this child task
> remain `planning`. These artifacts grant no implementation authority until
> the latest planning summary receives explicit user approval and
> `task.py start` succeeds.

## 1. Product goal

Given one exact qualified `EnvironmentRelease v2`, one admitted S2
`TaskPack`, and one target acting policy, execute a real isolated tool-use
episode and publish trustworthy immutable evidence containing:

```text
complete public policy trajectory
+ post-reopen frozen Task verification
+ deterministic base Reward or typed abstention
+ causal failure ownership, provider usage and latency
```

S3 turns admitted Task truth into target-policy behavior evidence. It does not
decide which Tasks are valid, repair or re-admit them, select another corpus, or
optimize a model.

```text
S1 EnvironmentRelease
-> S2 TaskPack / CorpusManifest
-> S3 EpisodeRecord / TrainingEpisodeView / EpisodeBatchManifest
-> S4 SFT/RL and held-out learning evidence
```

## 2. Exact stage boundary

### Inputs owned upstream

S3 consumes only current cold-verified authority:

- one exact `EnvironmentRelease v2` and its prepared actor/trusted runtimes;
- one exact admitted S2 `TaskPack`, or one exact single-release
  `CorpusManifest` whose entries resolve to current TaskPacks;
- a target `PolicySpec` and bounded public execution configuration.

S3 may narrowly refactor existing S2 execution primitives only when the shared
path cannot preserve failed policy trajectories, physical verification or the
strict public projection. It must not change Task meaning, TaskPack bytes or
identity, checker truth, admission gates, witnesses, assessment policy, or
corpus membership.

If Release, Corpus or TaskPack authority cannot be cold-verified before a valid
public input is frozen, no policy Episode exists. The direct API returns a typed
authority failure. A valid batch may retain a blocked corpus/rollout slot, but it
must not fabricate an `EpisodeRequest`, public trajectory or
`TrainingEpisodeView`.

After a logical EpisodeRequest is validly frozen, reset/preflight/environment or
semantics may still fail before PublicEpisodeInput exists. That also creates no
EpisodeRecord/View; batch records a request-bound blocked result. Thus blocked
results may bind either a corpus slot only or an already valid request ID,
without inventing an empty capture.

### Outputs owned by S3

S3 publishes:

- an immutable trusted `EpisodeRecord` for every valid public-input attempt,
  including verified success, verified policy failure and typed abstention;
- an exact non-leaking `TrainingEpisodeView` derived from that trusted record;
- one `EpisodeBatchManifest` binding an exact CorpusManifest, policy, every
  rollout result and honest aggregates;
- complete public calls, reported provider usage, latency, lifecycle evidence,
  verification and causal ownership.

### Explicitly outside S3

- Task generation, repair, re-admission, challenge generation or corpus
  reselection;
- automatic retry or retry scheduling;
- another Agent/Responses loop, a driver registry or generic plugin framework;
- SFT/chat-template formatting, tokenization, token masks, logprobs, advantage
  calculation, veRL integration, optimizer steps or checkpoints;
- monetary pricing/cost calculation;
- service, queue, Registry, database or workflow-engine infrastructure;
- LLM-as-Judge reward or hidden reasoning storage.

## 3. S2 witness/assessment versus S3 Episode

S2 witnesses answer: **does at least one public solution exist?**

S2 TaskAssessment answers: **how does a calibration policy perform for corpus
selection?**

S3 answers: **what did this target policy actually do on this exact admitted
Task, and what deterministic outcome follows?**

S3 preserves success and failure trajectories and never compares them with an
S2 witness. TaskAssessment reliability, witness identity, admission challenges
and corpus selection cannot alter Episode reward.

The required shared-path refactor may make new failed TaskAssessment trials
retain their real partial calls, observations, provider turns and reported
usage. It must preserve the current successful S2 public-run, witness,
`ReloadEvidence/1` and TaskPack formats, key sets and identity preimages so
existing current artifacts remain readable; fresh physical IDs may naturally
differ. It cannot change Task truth.

## 4. Required causal order

```text
1. cold-verify Release, Corpus if present, and exact TaskPack bytes
2. reconstruct current Atom/ForEach/If static runtime/checker authority
3. derive one frozen logical EpisodeRequest
4. open one fresh native instance and reset once with the trusted StartCase
5. inspect/preflight fresh binding, condition and checker preimage
6. snapshot actor tools and freeze the exact PublicEpisodeInput
7. run one Host-owned policy/tool loop through public surfaces only
8. preserve every public turn, attempted call, observation and terminal
9. inspect, close and reopen the same native instance without reset
10. inspect and execute the frozen checker after reopen
11. map trusted evidence to 1.0, 0.0 or typed null
12. persist and immediately cold-read the Episode bundle
13. bind the result or blocked slot into the EpisodeBatchManifest
```

Checker reconstruction and public-projection validation happen before the first
policy call; PublicEpisodeInput cannot exist before reset/preflight. Reward is
computed only after trustworthy post-reopen verification.

One rollout performs exactly one policy attempt. S3 has no retry-until-success,
hidden SDK retry or conditional retry slot.

## 5. Public policy boundary and Host ownership

The policy receives exactly the model-visible public input:

- canonical public system-prompt text;
- canonical instruction;
- fresh reset observation;
- exact model-facing public ToolSpecs;
- prior public ToolObservations;
- final-answer schema.

It never receives:

- TaskPack admission or witnesses;
- StartCase input as a separate hint;
- semantic keys, protected bindings or public descriptors as hidden operands;
- expected If branch or embedded branch admission evidence;
- native facts, checker request/result/digest or checker failure codes;
- TaskAssessment, corpus-selection facts or challenge feedback.

There is one Host-owned interaction loop. A `PolicyDriver` is single-Episode
and single-use: it produces exactly one provider/policy decision per Host call,
may retain only opaque in-memory continuation state, and is closed in a Host
`finally` path. No driver state crosses rollout or batch boundaries. The Host
alone owns:

- turn budgets and terminal classification;
- tool and final-answer schema validation;
- dispatch and ToolObservation validation;
- ordered call/observation recording;
- flat checker `TraceEvent` projection.

The Host constructs PublicEpisodeInput internally. Its prompt text must hash to
the driver's PolicySpec, its sole turn budget comes from that PolicySpec, and
its model-facing ToolSpecs and dispatch catalog are one snapshot from the same
`actor.tools()` call. Callers cannot pass an independently trusted public input
or budget.

`ResponsesPolicyDriver` is the only production adapter in S3. A scripted
driver is test-only conformance evidence. Neither receives actor reset,
inspection, checker or direct tool invocation authority.

## 6. Complete public trajectories

S3 retains public action history when the policy:

- requests an unknown tool;
- emits missing, malformed, non-JSON or schema-invalid arguments;
- returns a refusal through a healthy provider response;
- reaches its Host provider-turn budget;
- returns a missing, malformed or schema-invalid final answer;
- performs valid state changes but fails the user-facing protocol.

Every attempted function call retains exact raw public call-ID/name/argument
material, optional normalized ID/name and parsed arguments,
parse/schema/dispatch status and an optional public observation. Only validated
dispatched calls enter the flat checker trace.

Provider-private reasoning items, hidden chain-of-thought and unrelated provider
metadata are neither required nor persisted. Public terminal material needed to
explain a malformed call, refusal or invalid answer is retained.

A healthy policy terminal is a valid failed Episode and is still verified after
close/reopen. Provider, infrastructure, environment or trusted-runtime defects
retain the public prefix and abstain when enough authority exists to seal an
Episode.

## 7. Physical lifecycle and frozen verification

Every valid public-input attempt records the lifecycle events actually achieved
in causal order. The complete path remains:

```text
acting open -> reset once -> preflight -> public capture terminal -> pre-close inspect
-> acting close -> reopened open -> post-reopen inspect -> checker
-> reopened close
```

S3 always records a new request-bound `EpisodeAttemptEvidence` with an explicit
`capture_terminal` event, so provider/infrastructure defects are not
mislabelled as the legacy `episode_complete`. The current `ReloadEvidence/1`
shape, validation and identity preimage remain an unchanged compatibility
projection only when the public protocol completed and the full canonical
lifecycle finished; successful S2 wrappers continue to require that projection.

If close, reopen, inspection, checker or cleanup fails, S3 stores the achieved
lifecycle events plus the defect phase. `reload_evidence=None` alone is never
sufficient evidence. An incomplete lifecycle can only abstain; it cannot be
called verified failure.

For each Episode S3 must:

- match Release, TaskPack and Task identities;
- reconstruct fresh logical bindings rather than reuse witness IDs;
- recompute the current checker preimage before acting;
- evaluate actual trace, final answer and post-reopen facts;
- store the exact canonical task-kind checker request and result as trusted
  evidence;
- bind verification, lifecycle and reward consistently.

For If, the private loader validates and extracts the exact embedded current
AtomTaskPack branch from the verified If admission. It does not recompile an
Atom universe, load arbitrary verifier code or introduce a dependency registry.

S3 evaluates the actual Episode only. It does not rerun S2 admission challenges.

## 8. Base Reward and causal ownership

S3 supports one reward policy:

```text
binary-task-success/1
```

| Condition | disposition | reward |
| --- | --- | --- |
| healthy public protocol completed and frozen checker satisfied | `verified_success` | `1.0` |
| trustworthy lifecycle/checker, but policy failed or Task not satisfied | `verified_failure` | `0.0` |
| provider, infrastructure or trusted truth/evidence defect | `abstain` | `null` |

Policy failure has lower precedence than a trust defect. Examples:

```text
policy terminal + checker satisfied                 -> verified_failure / 0.0
completed + checker satisfied + any trust defect    -> abstain / null
provider failure after a satisfying mutation        -> abstain / null
policy failure without trustworthy reopen/checker   -> abstain / null
missing answer after a correct state mutation       -> verified_failure / 0.0
```

Closed abstain owners are:

| owner | Deterministic boundary |
| --- | --- |
| `provider` | a valid request crossed the provider boundary and received an explicit remote 429, 5xx, provider outage/timeout code or declared service failure |
| `infrastructure` | credential/auth/route configuration, client initialization, DNS/TLS/proxy/socket transport, dependency, process or I/O failure |
| `environment` | actor reset/tools/invoke/observation, native persistence or environment close behavior is invalid |
| `task_artifact` | post-freeze TaskPack/Corpus identity, release binding or checker preimage drifts |
| `semantics` | trusted inspect, binding or condition semantics are invalid |
| `verifier` | the frozen checker execution or result contract is invalid |
| `evidence` | Host lifecycle, identity, projection, canonical write or cold-read sealing is incomplete/corrupt |

A healthy provider response containing model refusal, malformed calls, wrong
arguments or a wrong answer remains policy behavior. A valid checker returning
`satisfied=false` is not a verifier defect.

Remote 400/422 request rejection is treated as a Host/adapter evidence defect,
not blamed on the provider. 401/403 and route/model configuration rejection are
infrastructure. An unexpected Responses envelope remains unattributed unless
the current raw provider contract proves provider nonconformance or the Host
adapter proves its own evidence defect.

Bare or unknown exceptions must not be guessed into an owner. They remain an
internal unattributed blocking failure with no training view or completion
claim; the affected run stops and the checkpoint cannot pass until attribution
is repaired.

## 9. Core contracts and artifacts

### `PolicySpec`

A non-secret identity over the actual model/checkpoint, driver kind/version,
public prompt digest, explicit normalized non-secret route ID and provider-turn
limit. S3 has no generic generation/config bag; any additional applied
identity-bearing parameter must be added as an explicit named contract field.

Credentials, raw auth headers, temporary paths and arbitrary plugin
configuration are forbidden. Route ID is not an opaque caller-supplied digest
and cannot be derived from URL userinfo/query secrets. The Responses adapter
must prove its actual request matches the frozen PolicySpec.

### `EpisodeRequest`

Frozen logical rollout identity:

```text
release_id
task_pack_id
task_id
policy_id
rollout_index (positive, 1-based)
```

It contains no attempt/retry index, Task truth, answer, native value, path,
witness, assessment or corpus-selection identity. Physical attempt identity is
bound separately in the Episode evidence.

### `EpisodeRecord`

Trusted immutable artifact containing:

- request and PolicySpec;
- exact public input and Host-recorded public turns;
- public completion and at most one primary typed defect;
- reported provider usage and latency;
- request-bound native instance and lifecycle evidence;
- optional legacy `ReloadEvidence/1` only for a protocol-completed full
  lifecycle, plus authoritative S3 EpisodeAttemptEvidence for every Episode;
- exact frozen checker request/result when available;
- one validated `RewardOutcome` whose abstain owner/code match that defect.

The Episode ID hashes the complete canonical record except its own ID. Moving an
artifact or changing an output path does not change identity. Changing any
trajectory, lifecycle, checker, policy, request or reward content changes the ID
or makes cold-read fail.

### `TrainingEpisodeView`

Exact S4-facing projection derived from the trusted EpisodeRecord. It contains:

- Episode/Request/Release/TaskPack/Task/Policy IDs and rollout index;
- exact public system prompt, instruction, reset observation, model-facing
  ToolSpecs and final-answer schema;
- ordered public turns, calls, raw public terminal material, observations and
  final answer;
- nullable PolicyCompletion kind/code so budget/refusal/invalid-final terminals
  remain reconstructable even without raw terminal material or a final answer;
- disposition and reward.

It excludes provider usage/latency, native/lifecycle facts, checker
request/result/failure codes, defect owner/code/phase, Start input, semantic
keys, protected bindings, expected branch, S2 witnesses/admission/assessment
and hidden reasoning.

An abstained Episode may have a TrainingEpisodeView with `reward=null`, but an
input-authority blocked slot has none.

Episode bundles are written only under a new output root and immediately
cold-verified as a pair. A write/view/cold-read failure leaves that run invalid:
no TrainingEpisodeView or final EpisodeBatchManifest is claimed, and the same
unpersisted record cannot certify its own publication failure.

### `EpisodeBatchManifest`

Introduced only by the batch runtime. It binds:

- one exact expected CorpusManifest ID;
- one exact prepared Release ID and one PolicySpec;
- the positive rollout count and frozen valid EpisodeRequests;
- every Episode ID and every pre-Episode blocked rollout slot;
- aggregates derived only from retained records: dispositions, blocked counts,
  attempted/dispatched calls, provider turns, reported input/output tokens,
  missing-usage count, latency and abstain-owner counts.

There is no monetary cost claim, duplicate run artifact or explicit-TaskPack-set
batch source.

## 10. Batch execution

The production batch API accepts one CorpusManifest path plus mandatory
expected `corpus_id`, one task store, one prepared Release, one frozen
PolicySpec, one factory for fresh single-use PolicyDrivers, and a positive
rollout count.

Before the first policy call it:

- cold-verifies the CorpusManifest and every referenced current TaskPack;
- rejects an invalid CorpusManifest entirely;
- rejects a multi-release corpus as typed unsupported input;
- ensures every valid entry matches the one prepared Release;
- freezes every valid logical EpisodeRequest;
- records corpus entries that cannot form a valid request as blocked slots.

Execution is serial. Each rollout produces exactly one success, failure,
abstention or blocked result. There is no policy or infrastructure retry and
provider SDK retries remain disabled.

If an Episode bundle cannot be written and cold-read, the whole batch run aborts
and publishes no final EpisodeBatchManifest. The every-slot invariant applies
only to a successfully published batch; unexecuted remainder is not fabricated
as blocked work.

Policy failure never changes Task validity. Task/Environment/Semantics/Verifier
authority defects stop the affected authority and account honestly for
remaining blocked slots.

## 11. S4 handoff

S3 supports:

1. paired cold verification of EpisodeRecord and TrainingEpisodeView while
   returning only the non-leaking view to an S4-facing caller;
2. one decision-only PolicyDriver boundary that a later S4 adapter may
   implement without direct tool or trusted access.

S3 implements no S4 consumer, veRL adapter, trainer schema or optimization code.
A scripted second driver and test-only cold reader prove conformance.

## 12. Acceptance criteria

S3 completes only when the frozen runtime:

- consumes relocated current Release, TaskPack and single-release Corpus
  artifacts;
- runs Atom, ForEach and If through one shared runtime across the complete
  authority set;
- preserves full public trajectories for success and healthy policy failure;
- records physical `verified_success`, `verified_failure` and typed
  `abstain` Episodes without owner conflation;
- verifies after real close/reopen of the same native instance;
- preserves partial lifecycle evidence for interrupted abstentions;
- cold-reads paired immutable EpisodeRecord/TrainingEpisodeView bundles after
  relocation and rejects every identity/projection mutation;
- executes fixed Git, SQLite and inherited maintenance authority without domain
  branches;
- runs one real Responses full batch and one scripted second-driver identity
  through the same Host loop;
- executes one exact CorpusManifest per successfully published batch and
  retains every rollout or blocked slot;
- proves no S2 witness/admission/checker data enters policy or training input;
- leaves TaskPack/Corpus identities unchanged and training implementation to S4;
- passes deterministic tests, named mutation licences, physical evidence, live
  provider evidence where required and independent checkpoint review.

Checkpoints are acceptance gates, not demos or MVP milestones. CP1–CP5 may close
the single-Task runtime slice; only CP1–CP7 together complete S3.

## 13. Fatal rejection criteria

Reject the design or implementation if it:

- rewards model text through an LLM Judge;
- drops failed calls/turns or labels provider/trust defects as policy failure;
- evaluates in-memory state without the declared close/reopen path;
- fabricates legacy ReloadEvidence from a policy/provider/infrastructure
  terminal or an incomplete lifecycle;
- creates a new Task/checker/admission path or changes TaskPack format;
- passes protected Task/checker fields or raw checker codes to the policy/view;
- requires trajectory matching with an S2 witness;
- retries until success or silently drops abstained/blocked outcomes;
- stores hidden reasoning;
- introduces a second loop, service, queue, registry, database, universal
  trajectory/state/reward ontology, veRL adapter or trainer-specific framework.
