# S3 Verified Episode Runtime — Technical Design

## 1. Design judgment

S3 is one thin trusted execution/evaluation layer over current S1/S2 authority,
not another foundry and not an S4 trainer.

Deletion-first correction: CP1 and CP2 are reopened before any lifecycle work.
Only mechanisms used by the original Episode/Policy/Reward request or the
current shared public path survive. Later sections describing CP3-CP7 shapes
are candidate outcomes, not authority to retain or prebuild a field, helper,
exception, runtime carrier or package layout. The correction deliberately
keeps current paths stable; flat-directory cleanup is considered only after
code deletion exposes a real remaining cohesion boundary.

The repository already owns most physical mechanics:

| Existing component | S3 reuse |
| --- | --- |
| `prepare_release` / isolated actor and trusted runtimes | exact Release execution |
| `read_task_pack_artifact` | canonical TaskPack verification and public/trusted split |
| `run_public_episode` | the one Responses loop to refactor, never duplicate |
| `run_public_attempt` / `ReloadEvidence/1` | physical reset/close/reopen/check path |
| Atom/ForEach/If evaluators | frozen Task truth |
| `TaskAssessment` | shared capture/lifecycle consumer, never reward authority |
| `CorpusManifest` | exact batch membership |

Concrete gaps in current code are:

1. policy failures raise and discard the accumulated public prefix;
2. a public failure prevents pre-close inspection, reopen and checker execution;
3. `AgentRoute` is fixed to one research model/route;
4. the cold TaskPack reader does not construct current runtime Task values and
   drops the If admission that contains the exact branch AtomTaskPack;
5. no immutable Episode, reward or non-leaking training projection exists;
6. no direct exact-Corpus episode batch exists.

Each new component below exists for one of those gaps. Types appear only at
their named checkpoint; S3 does not prebuild future batch/trainer machinery.

## 2. Authority and dependency order

```text
CP1 contract kernel
  -> CP2 Host policy loop and Responses decision adapter
  -> CP3 shared physical lifecycle and partial evidence
  -> CP4 strict Task runtime, verification, reward and EpisodeRecord
  -> CP5 canonical Episode bundle and TrainingEpisodeView
  -> CP6 exact Corpus batch and EpisodeBatchManifest
  -> CP7 frozen acceptance only
```

CP3 is callback-driven and does not depend on the CP4 cold Task loader. CP4
supplies current Atom/ForEach/If callbacks to the already accepted lifecycle.
This removes the previous circular dependency where CP3 accepted an undefined
`task_runtime`.

## 3. CP1 contract kernel

CP1 owns only stable leaf/cross-checkpoint contracts. In addition to the four
identity/outcome values below, it freezes the public capture values described
in Section 5 because CP2 consumes them directly. It does not create any
verification, persistence or batch aggregate.

### `PolicySpec`

```python
@dataclass(frozen=True, slots=True)
class PolicySpec:
    model_id: str
    driver_id: str
    driver_version: str
    route_id: str
    system_prompt_digest: str
    max_provider_turns: int
```

Rules:

- credentials, auth headers and temporary paths are impossible fields;
- route_id is an explicit normalized non-secret identifier, never a caller
  digest over URL userinfo, query tokens or auth material;
- there is no generic generation/config bag in CP1; if CP2 proves another
  applied parameter is identity-bearing, implementation returns to CP1 and
  adds one explicit named field before CP2 can pass;
- human labels do not change identity unless they are the declared model
  identifier;
- the Responses adapter proves its actual request matches the spec.

### `EpisodeRequest`

```python
@dataclass(frozen=True, slots=True)
class EpisodeRequest:
    release_id: str
    task_pack_id: str
    task_id: str
    policy_id: str
    rollout_index: int
```

`request_id` is the canonical digest. `rollout_index` is positive and
1-based. There is no retry/attempt index in the logical request.

### `EpisodeDefect`

One flat value:

```python
@dataclass(frozen=True, slots=True)
class EpisodeDefect:
    owner: DefectOwner
    code: str
    phase: str
```

`DefectOwner` is closed over `provider`, `infrastructure`,
`environment`, `task_artifact`, `semantics`, `verifier` and
`evidence`. There is no subclass/exception hierarchy per owner.

### `RewardOutcome`

```python
@dataclass(frozen=True, slots=True)
class RewardOutcome:
    disposition: Literal["verified_success", "verified_failure", "abstain"]
    reward: float | None
    abstain_owner: DefectOwner | None
    abstain_code: str | None
```

Python typing does not use float Literals here. The constructor runtime-validates
that reward is exactly `1.0`, `0.0` or `None` and enforces the complete truth
table. It cannot by itself decide reward; CP4's pure mapper does that from
capture, verification and defect.

### JSON snapshots

Every contract:

- snapshots input JSON rather than retaining caller aliases;
- exposes ordinary structural JSON values to current consumers;
- returns fresh JSON documents from serialization;
- rejects non-JSON, noncanonical or unexpected-key content.

Alias-mutation tests are required. Persistent Episode immutability is enforced
later by canonical artifact identity and cold readers, not by a private
freeze/thaw container framework in these in-memory leaf values.

## 4. One Host-owned policy loop

The previous `PublicEpisodePort.invoke()` design is removed. Tool authority
never crosses into a driver.

```text
                         trusted Host
                              |
            turn budget / validation / ledger / dispatch
                              |
                  PolicyDriver.next_decision(...)
                         /              \
          ResponsesPolicyDriver      scripted test driver
                              |
                       public decision only
```

The minimal driver protocol is stateful but decision-only:

```python
class PolicyDriver(Protocol):
    @property
    def policy_spec(self) -> PolicySpec: ...

    def start(self, public_input: PublicEpisodeInput) -> None: ...

    def next_decision(
        self,
        prior_public_results: tuple[tuple[str, JSONObject], ...],
    ) -> DriverDecision: ...

    def close(self) -> None: ...
```

The exact method names may follow existing code style, but the authority is
fixed:

- one Host call requests one provider/policy decision;
- the driver may retain opaque in-memory continuation state;
- one driver instance belongs to exactly one Episode and rejects reuse;
- the Host closes it in `finally` on success, policy failure or defect;
- continuation state is not persisted or treated as public reasoning;
- the driver cannot reset, invoke, inspect, check, retry or loop;
- the Host owns budgets, validation, dispatch, recording and termination.

The Host entry accepts the actor, instruction, reset observation, answer schema
and one fresh driver—not a separately authoritative PublicEpisodeInput. It:

- snapshots `actor.tools()` once and uses that one validated catalog for both
  model-facing ToolSpecs and dispatch;
- constructs the exact public prompt/input internally;
- verifies the prompt digest and driver PolicySpec identity;
- takes the only turn budget from PolicySpec.

For Responses, the adapter maps one `responses.create` result into a
`DriverDecision` and retains only provider continuation objects needed for the
next API call. The Host remains the only Agent loop.

## 5. Public input and authoritative capture

### `PublicEpisodeInput`

```text
system_prompt              exact public text
instruction                canonical Task instruction
reset_observation          fresh public reset output
tool_specs                 exact model-facing public ToolSpecs
answer_schema              exact final-answer schema
```

The Host constructs this value before the first decision. Any public
tool-description guidance is included here so the persisted input equals what
the model saw; it is not hidden inside the Responses adapter.

### Decision and ledger values

These snapshotted ledger values are part of the CP1 contract kernel. CP2 adds the
driver protocol and the Host loop that produces them; it does not redesign
their persisted shape.

`DriverDecision` is an ephemeral provider-adapter result. The Host converts it
into public records:

```python
@dataclass(frozen=True, slots=True)
class EpisodeToolCall:
    raw_call_id: JSONValue | None
    raw_tool_name: JSONValue | None
    call_id: str | None
    tool_name: str | None
    raw_arguments: JSONValue | str | None
    parsed_arguments: JSONObject | None
    parse_status: str
    schema_status: str
    dispatch_status: str
    observation: JSONObject | None

@dataclass(frozen=True, slots=True)
class PolicyTurn:
    turn_index: int
    calls: tuple[EpisodeToolCall, ...]
    raw_public_terminal: JSONValue | str | None
    usage: JSONObject | None

@dataclass(frozen=True, slots=True)
class PolicyCompletion:
    terminal_kind: Literal["completed", "policy_failure"]
    final_answer: JSONObject | None
    terminal_code: str | None

@dataclass(frozen=True, slots=True)
class PublicEpisodeCapture:
    public_input: PublicEpisodeInput
    turns: tuple[PolicyTurn, ...]
    completion: PolicyCompletion | None
    defect: EpisodeDefect | None
```

Exact field types may be specialized during CP1/CP2 RED tests, but these
authorities are invariant:

- calls/observations/usage exist once in Host turns;
- completion contains only public terminal classification and final answer;
- at least one completion or defect is present; both are allowed when a valid
  public completion is followed by Host close/usage/evidence failure;
- the flat checker `TraceEvent` is derived only from validated dispatched
  calls;
- invalid calls and raw invalid terminal material remain in the public turns.

The Host rejects duplicate call IDs and any mismatch between dispatched calls,
returned call results and its ledger. Separate Responses-adapter mapping tests
prove every public call/terminal item in a raw provider fixture becomes the
corresponding DriverDecision; the generic Host does not pretend it can inspect
provider-private state. Hidden reasoning output items are not copied.

## 6. Provider versus infrastructure

The current catch-all conversion of every Responses request exception to
`InfrastructureFailure` is removed.

Deterministic classification uses observable boundaries:

- `provider`: a valid request crossed the provider API boundary and returned an
  explicit remote 429, 5xx, provider outage/timeout code or declared service
  failure;
- `infrastructure`: credential/auth/route configuration, client initialization,
  DNS/TLS/proxy/socket transport, dependency, process or I/O failure;
- `evidence`: remote 400/422 request rejection caused by the Host request, or a
  proved Host capture/adapter contract defect.

A healthy Responses envelope containing refusal, malformed calls or a wrong
answer is policy behavior. Host turn-budget exhaustion is policy failure.
401/403 and route/model configuration rejection are infrastructure, never
provider quality.
An unexpected envelope remains unattributed until raw current-contract evidence
assigns it to provider nonconformance or the Host adapter.

An exception without sufficient causal evidence is not guessed into either
owner. It becomes an internal unattributed blocker: no TrainingEpisodeView,
the run stops, and checkpoint acceptance fails until classification is repaired.

## 7. Shared physical attempt lifecycle

The existing successful lifecycle is generalized, not replaced:

```python
run_episode_attempt(
    prepared,
    instance_root,
    *,
    task_id,
    start_input,
    preflight,
    execute_policy,
    evaluate_after_reopen,
) -> AttemptOutcome
```

The concrete signature may retain the current context-manager style. Required
behavior is:

```text
acting open
-> reset once
-> before inspect / preflight
-> snapshot tools / freeze PublicEpisodeInput
-> Host public-capture terminal (completion, policy failure or typed defect)
-> pre-close inspect
-> acting close
-> reopened open on same native instance
-> post-reopen inspect
-> supplied frozen evaluator
-> reopened close
```

`AttemptOutcome` owns:

- an optional `PublicEpisodeCapture` because reset/preflight may fail before
  public input exists;
- every lifecycle event actually achieved in causal order;
- native and acting/reopened session identities when available;
- pre-close/post-reopen fact digests when available;
- checker result digest when available;
- one optional lifecycle defect; the Episode's primary defect is
  `capture.defect` when present, otherwise this lifecycle defect;
- authoritative request-bound S3 lifecycle evidence with an explicit
  `capture_terminal` event;
- unchanged `ReloadEvidence/1` only as a compatibility projection when the
  public protocol completed and the canonical lifecycle finished.

S3 adds a request-bound attempt envelope containing `request_id`; it does not
change the existing S2 reload document/preimage.

Cleanup may continue after a provider/policy defect, so lifecycle evidence may
extend past the primary defect. A later cleanup failure makes the lifecycle
incomplete but does not create a general multi-defect event model; the Episode
already abstains and records the achieved terminal phase.
Only protocol-completed exact canonical sequences project to
`ReloadEvidence/1`. A fully closed/reopened policy/provider/infrastructure
terminal remains complete S3 attempt evidence but never receives the misleading
legacy `episode_complete` event.

The S2 `run_public_attempt` wrapper and Atom/ForEach/If witness projections
remain exact for successful paths. New failed TaskAssessment trials use the
shared capture/lifecycle and retain partial public activity and usage without
changing Task truth.

## 8. Strict current TaskPack runtime

S3 supports only:

```text
atom-task-pack/4
foreach-task-pack/3
if-task-pack/3
```

The private loader consumes the complete output of canonical TaskPack
verification and uses exact-key current decoders:

```python
type LoadedRuntimeTask = LoadedAtom | LoadedForEach | LoadedIf
```

- `LoadedAtom` contains the exact AtomTask;
- `LoadedForEach` contains the exact ForEachTask;
- `LoadedIf` contains the exact IfTask plus the validated embedded branch
  AtomTask extracted from `admission.branch_task_pack`.

For If, the loader recomputes nested AtomTaskPack identity/current shape,
checker preimages and If-to-Atom release/start/capability/semantic bindings. It
then discards admission witnesses from the runtime value.

The loader never:

- recompiles candidates or an Atom universe;
- changes TaskPack bytes or format;
- loads arbitrary Python verifier code;
- invents a dependency registry or universal Task DSL.

Current task-kind evaluator logic remains authoritative. Only the smallest
private helpers needed for the shared preflight/post-reopen callback are
extracted from Atom/ForEach/If modules.

## 9. Verification, reward and EpisodeRecord

### `EpisodeVerification`

```text
checker_digest
exact canonical task-kind checker request or request set
exact canonical checker result or result set
derived satisfied/failed status
trusted checker failure codes
```

It stores no universal state ontology. The exact request/result remain trusted
and never enter the training view.

### Reward mapper

```python
def map_base_reward(
    *,
    capture: PublicEpisodeCapture,
    verification: EpisodeVerification | None,
    attempt_evidence: EpisodeAttemptEvidence,
) -> RewardOutcome:
    ...
```

Precedence:

```text
any provider/infrastructure/trust defect
  -> abstain / null

no defect + trustworthy complete lifecycle/checker
+ completed protocol + checker satisfied
  -> verified_success / 1.0

no defect + trustworthy complete lifecycle/checker
+ any policy failure or checker not satisfied
  -> verified_failure / 0.0
```

A valid checker returning failed is not a verifier defect. A policy terminal
with satisfying state is still reward zero. A provider defect after satisfying
mutation is still null.

### `EpisodeRecord`

Introduced at CP4 after capture, lifecycle and verification shapes are real:

```python
@dataclass(frozen=True, slots=True)
class EpisodeRecord:
    request: EpisodeRequest
    policy: PolicySpec
    capture: PublicEpisodeCapture
    attempt_evidence: EpisodeAttemptEvidence
    verification: EpisodeVerification | None
    outcome: RewardOutcome
    latency_ms: int
```

`EpisodeAttemptEvidence` binds `request_id`, physical native/session
identities, achieved lifecycle events, available fact/checker digests and
optional protocol-completed `ReloadEvidence/1` compatibility projection, and
owns the lifecycle defect when the capture itself does not already own the
primary defect.

The Episode ID hashes the complete canonical record except its own ID. All
duplicate projections are derived or cross-validated:

- request policy ID equals PolicySpec identity;
- Host turns equal flat checker trace projection;
- any legacy reload checker digest equals the verification result digest;
- RewardOutcome matches completion/attempt defect/verification;
- paths, credentials, S2 witnesses and assessment/corpus-selection identity are
  absent.

A valid public input plus a later typed defect may produce an abstained
EpisodeRecord. A cold authority failure before valid public input produces no
EpisodeRecord.

A valid logical request may exist before reset/preflight constructs public
input. If that early physical/trusted step fails, AttemptOutcome has
`capture=None`; direct execution returns the typed failure and batch records a
request-bound blocked result, never an empty Episode capture.

## 10. Canonical Episode bundle

One bundle, no Registry/database:

```text
<output>/
  episodes/<episode_id>/
    EpisodeRecord.json
    TrainingEpisodeView.json
  batches/<batch_id>/
    EpisodeBatchManifest.json
```

Write order under a required-new output root:

```text
validate in-memory record
-> write canonical EpisodeRecord and derived TrainingEpisodeView
-> cold-read both and recompute identities/projection
```

Collision, partial write, view derivation or cold-read failure leaves the new
run invalid and no TrainingEpisodeView/final batch claim. The unpersisted
EpisodeRecord cannot recursively record that its own publication failed. Strict
readers reject any partial directory.

The primary reader verifies the pair:

```python
read_episode_bundle(root, episode_id) -> EpisodeBundle
```

An S4-facing helper may return only `TrainingEpisodeView`, but it must
internally resolve and verify the trusted record. A separately trusted view is
not accepted.

The exact training projection includes:

```text
episode/request/release/task-pack/task/policy IDs
rollout index
system prompt text
instruction
reset observation
model-facing ToolSpecs
answer schema
ordered public turns/calls/raw terminal material/observations/final answer
nullable PolicyCompletion terminal kind/code
disposition and reward
```

It excludes usage/latency, native/lifecycle evidence, checker data/codes,
defect attribution, S2 evidence and hidden reasoning.

Relocation changes no identity. Any call, observation, terminal, lifecycle,
checker, policy, request or reward mutation under an old claimed ID fails.

## 11. Exact single-release Corpus batch

```python
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

Before the first policy call the runner:

1. cold-verifies the expected CorpusManifest;
2. rejects a multi-release corpus as typed unsupported input;
3. resolves every referenced current TaskPack;
4. verifies each valid entry belongs to `prepared.identity.release_id`;
5. freezes every valid EpisodeRequest in deterministic corpus/rollout order;
6. records entries that cannot form a valid request as immutable blocked slots.

An invalid CorpusManifest itself produces no batch artifact. A valid corpus with
an invalid/missing TaskPack may produce blocked slots and stops that affected
TaskPack authority.

The runner is serial and retry-free. It creates one fresh single-use driver per
rollout, verifies that driver's PolicySpec equals the frozen batch PolicySpec,
and closes it before the next rollout. One rollout yields one retained result.
Provider SDK retries are zero. Policy failure is never repaired or retried.
If any Episode bundle fails write/cold-read, the batch aborts and writes no final
EpisodeBatchManifest; remaining slots are not fabricated as blocked outcomes.

`EpisodeBatchManifest` appears first in CP6 and binds:

- expected corpus/release/policy identity;
- rollout count and ordered requests;
- every Episode ID and blocked slot;
- aggregates recomputed from retained results: disposition, blocked count,
  attempted/dispatched calls, provider turns, reported input/output tokens,
  missing-usage count, latency and abstain-owner counts.

It does not reselect Tasks, load an explicit TaskPack set, calculate monetary
cost, schedule parallel work or emit a duplicate run artifact.

## 12. S2 integration and compatibility

Allowed shared changes:

- `public_agent.py`: split the existing loop into Host control plus one-turn
  Responses adaptation while retaining the successful S2 wrapper;
- `task_execution.py`: support typed terminals/partial evidence while
  preserving complete `ReloadEvidence/1`;
- TaskPack reader/private loader: retain the already verified full pack long
  enough to build current runtime truth;
- Atom/ForEach/If modules: expose only concrete shared preflight/evaluation
  helpers;
- `assessment.py`: retain partial failed-trial capture through the shared path.

Forbidden as S3 cleanup:

- changing Task instructions, selectors, checker truth or admission evidence;
- changing TaskPack bytes/formats or successful witness/reload projections;
- weakening two-witness/challenge gates;
- recompiling candidates during Episode execution;
- making Assessment reliability affect Episode reward.

If a TaskPack format blocker is discovered, implementation stops and returns to
planning/S2 authority. It is not an escape hatch inside S3.

## 13. Evidence classes

The plan uses four non-interchangeable evidence classes:

| Evidence | Proves | Does not prove |
| --- | --- | --- |
| deterministic fake/scripted tests and killed mutants | schemas, identities, capture mechanics, owner/reward matrix | provider behavior or physical persistence |
| physical Release/tool/native-state execution | real mutation, persistence, close/reopen/checker; scripted policy allowed | public model solvability/provider quality |
| live provider execution | actual Responses request/continuation/usage path | reward/lifecycle correctness by itself |
| cold relocation | canonical persistence, path independence and reader projection | live execution by itself |

A natural live failure is never a deterministic gate. A scripted policy with a
real environment is physical evidence, not a demo, but it does not prove model
solvability.

## 14. Anti-overdesign constraints

Do not add:

- another Agent/Responses loop or driver-side tool invocation;
- a service, broker, queue, database, Registry or event-sourcing system;
- a universal Task/state/reward/failure ontology;
- per-owner class hierarchies;
- a generic Task runtime or public prepare/evaluate adapter framework;
- automatic retry/attempt slots;
- an explicit-TaskPack-set batch source or multi-release scheduler;
- partial-reward weights, cost pricing, logprobs, token masks, chat templates,
  veRL/trainer types or hidden reasoning storage;
- a production second driver or S4 consumer.

Every new type/function must name its immediate checkpoint consumer and the
identity, trust or S4 handoff claim it protects. CP7 adds no production
component; it only evaluates the frozen CP1–CP6 runtime.
