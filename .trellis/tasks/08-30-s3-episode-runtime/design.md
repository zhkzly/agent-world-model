# S3 Verified Episode Runtime — Technical Design

## 1. Design judgment

S3 should be a thin trusted execution/evaluation layer over current S2
artifacts, not another foundry.

The current repository already contains most hard mechanics:

| Existing component | Reuse in S3 |
| --- | --- |
| `prepare_release` / actor+trusted child runtimes | exact Release isolation |
| `read_task_pack_artifact` | cold TaskPack verification and public/trusted split |
| `run_public_episode` | Responses function-tool policy adapter |
| `run_public_attempt` / `ReloadEvidence` | physical open-reset-act-close-reopen-check lifecycle |
| Atom/ForEach/If runtime evaluators | frozen Task-kind verification |
| provenance code | public operand evidence |
| `TaskAssessment` | source of shared execution/cost patterns, not S3 truth |

S3 adds only what these components do not currently provide:

1. retain complete trajectories when the policy fails;
2. run an arbitrary target policy identity instead of the research-specific
   hard-coded route;
3. map frozen verification to one base Reward/abstention contract;
4. persist cold-readable Episode artifacts and batch manifests for S4;
5. expose one restricted policy-driving boundary usable by Responses now and an
   S4 rollout adapter later.

## 2. One runtime, two drivers

```text
                         trusted Host
                             |
         +-------------------+-------------------+
         |                                       |
  ResponsesPolicyDriver                    future S4 driver
         |                                       |
         +---------- restricted PublicEpisodePort+
                             |
                    actor reset/tools/invoke
                             |
                      close -> reopen
                             |
                   frozen Task verification
                             |
                    EpisodeRecord + reward
```

There is no driver registry. S3 defines one small `PolicyDriver` protocol and
ships one production implementation, `ResponsesPolicyDriver`. Tests may use a
scripted driver. S4 may later implement the same protocol without changing the
Host's trust boundary.

## 3. Minimal public policy port

The policy driver must never receive `OpenPreparedSession`, `TrustedTaskView` or
checker callbacks. It receives a restricted object:

```python
class PublicEpisodePort(Protocol):
    @property
    def input(self) -> PublicEpisodeInput: ...

    def invoke(self, tool_name: str, arguments: JSONObject) -> ToolObservation: ...
```

`PublicEpisodeInput` contains:

```python
@dataclass(frozen=True, slots=True)
class PublicEpisodeInput:
    instruction: str
    reset_observation: JSONValue
    tool_specs: tuple[ToolSpec, ...]
    answer_schema: JSONObject
    system_prompt_digest: str
```

The Host records each invocation before returning the public observation. The
policy cannot inspect native state, reset again or evaluate the checker.

The driver returns a typed terminal outcome:

```python
@dataclass(frozen=True, slots=True)
class PolicyCompletion:
    turns: tuple[PolicyTurn, ...]
    final_answer: JSONObject | None
    terminal_kind: Literal[
        "completed",
        "policy_failure",
        "infrastructure_failure",
    ]
    terminal_code: str | None
    usage: tuple[JSONObject | None, ...]
```

Environment/trusted defects are raised by the Host and routed to abstention.
Policy protocol defects are represented in `PolicyCompletion` so prior actions
are not discarded.

## 4. Required refactor of current public execution

Current `run_public_episode` returns only after a valid final answer and raises
`NoPublicWitness` for policy-level failures. That behavior is correct for S2
witness admission but insufficient for S3 because partial trajectories vanish.

Refactor without creating a second loop:

```text
capture_public_episode(...) -> PolicyCompletion

run_public_episode(...)     # retained S2 convenience wrapper
  -> capture_public_episode(...)
  -> require terminal_kind == completed
  -> otherwise raise the existing typed S2 failure
```

`capture_public_episode` records:

- provider turn index;
- normalized function-call items, including invalid/unknown calls where safely
  parseable;
- Host dispatch result or the policy protocol error;
- public ToolObservation;
- final structured answer when valid;
- usage per provider turn.

It excludes provider-private reasoning items. Function-call ordering and turn
grouping are retained; the existing `TraceEvent` remains the checker-facing
projection.

## 5. Required refactor of physical lifecycle

Current `run_public_attempt` assumes the policy runner returns normally before
post-reopen evaluation. S3 needs the same physical lifecycle for completed and
policy-failed episodes.

Extract one lower-level context:

```python
run_episode_attempt(
    prepared,
    instance_root,
    task_runtime,
    policy_driver,
) -> AttemptOutcome
```

The exact lifecycle remains:

```text
open acting session
-> reset once
-> trusted before inspect
-> checker/binding preflight
-> policy execution through PublicEpisodePort
-> trusted pre-close inspect
-> close
-> reopen same native instance without reset
-> trusted post-reopen inspect
-> frozen checker evaluation
-> close
```

The existing successful S2 wrappers call this core and require a successful
policy completion plus satisfied checker. S3 accepts either satisfied or failed
checker results and publishes an EpisodeRecord. No duplicate lifecycle remains.

Infrastructure failure after one or more tool calls is still recorded as an
abstained attempt when enough evidence can be sealed; it never becomes reward
zero.

## 6. Runtime Task adapter

S3 must not deserialize arbitrary verifier code. It supports only current
admitted TaskPack formats and explicit goal-kind dispatch:

```python
type RuntimeTask = AtomTask | ForEachTask | IfTask
```

A single module provides:

```python
load_runtime_task(trusted_view: TrustedTaskView) -> RuntimeTask

prepare_task_evaluation(
    session,
    task,
    before_facts,
) -> FrozenEvaluationContext

evaluate_task_episode(
    session,
    task,
    context,
    before_facts,
    post_reopen_facts,
    trace,
    final_answer,
) -> JSONObject
```

The adapter reuses the same task-kind-specific binding and evaluation logic used
by S2. It performs before-policy checks:

- exact release match;
- current Task format and identity;
- fresh logical binding reconstruction;
- checker preimage/digest equality;
- initial state validity.

`All` is added automatically only after S2 publishes a current admitted All
TaskPack format. S3 does not invent composition support.

## 7. Policy identity

The current `AgentRoute` is intentionally fixed to one research route/model and
cannot identify arbitrary S3 target policies. Keep it for S1 research where it
is authoritative, but remove it from generic Task episode identity.

Introduce:

```python
@dataclass(frozen=True, slots=True)
class PolicySpec:
    policy_name: str
    model_id: str
    driver_id: str
    driver_version: str
    route_digest: str
    system_prompt_digest: str
    max_provider_turns: int
    generation_config: JSONObject
```

Rules:

- no credentials or raw auth headers;
- include only generation parameters actually applied;
- route digest may bind a non-secret normalized route document;
- model/checkpoint changes produce a new policy identity;
- batch retry policy is not hidden in the driver.

## 8. Episode objects and identities

### `EpisodeRequest`

Frozen before any policy call:

```python
@dataclass(frozen=True, slots=True)
class EpisodeRequest:
    release_id: str
    task_pack_id: str
    task_id: str
    policy_id: str
    rollout_index: int
    attempt_index: int
```

`request_id` is its canonical digest.

### `PolicyTurn`

One provider/policy decision turn:

```python
@dataclass(frozen=True, slots=True)
class PolicyTurn:
    turn_index: int
    calls: tuple[EpisodeToolCall, ...]
    final_answer: JSONObject | None
    failure_code: str | None
    usage: JSONObject | None
```

`EpisodeToolCall` binds call ID, tool name, arguments, dispatch status and public
observation. It preserves turn grouping while `TraceEvent` remains a derived
flat verifier input.

### `EpisodeVerification`

Do not invent a universal state ontology. Store:

```text
checker_digest
task-kind-specific canonical checker request
exact checker result document
common status: satisfied / failed
common failure codes
```

The task-kind-specific request may contain protected facts/bindings and exists
only in the trusted EpisodeRecord.

### `EpisodeRecord`

```python
@dataclass(frozen=True, slots=True)
class EpisodeRecord:
    request: EpisodeRequest
    policy: PolicySpec
    public_input: PublicEpisodeInput
    completion: PolicyCompletion
    reload_evidence: ReloadEvidence | None
    verification: EpisodeVerification | None
    disposition: Literal["verified_success", "verified_failure", "abstain"]
    reward: float | None
    abstain_owner: str | None
    abstain_code: str | None
    latency_ms: int
```

The Episode ID hashes the complete canonical record except its own ID. Paths,
credentials and temporary directories are excluded.

### `TrainingEpisodeView`

Exact allowed keys:

```text
episode_id
request_id
release_id
task_pack_id
task_id
policy_id
instruction
reset_observation
tool_specs
policy_turns
final_answer
verified_status
failure_codes
reward
disposition
```

It excludes native facts, Start input, semantic key, protected binding, expected
branch, checker request/result, TaskPack witnesses/admission and S2 assessment.

## 9. Reward mapper

One deterministic function:

```python
def map_base_reward(
    *,
    completion: PolicyCompletion,
    verification: EpisodeVerification | None,
    defect: EpisodeDefect | None,
) -> RewardOutcome:
    ...
```

Rules:

```text
defect owned by infrastructure/environment/task/semantics/verifier/evidence
  -> abstain / null

no trust defect and completion is protocol-complete and checker satisfied
  -> verified_success / 1.0

otherwise, with valid post-reopen verification
  -> verified_failure / 0.0
```

A state effect achieved before provider/TLS failure remains abstained because
the policy outcome cannot be causally separated from infrastructure failure.
A malformed tool call, wrong answer or turn-budget exhaustion produced by a
healthy provider remains policy failure and reward zero.

## 10. Artifact layout

No Registry or database:

```text
<output>/
  episodes/<episode_id>/EpisodeRecord.json
  views/<episode_id>/TrainingEpisodeView.json
  batches/<batch_id>/EpisodeBatchManifest.json
  runs/<batch_run_id>.json
```

Every write follows:

```text
validate in-memory preimage
-> write canonical bytes to a new path
-> immediate cold-read
-> recompute identity and projection
```

Collision or unsupported current format fails closed.

## 11. Batch runner

```python
run_episode_batch(
    prepared: OpenPreparedRelease,
    task_store_root: Path,
    corpus_manifest_path: Path,
    output_root: Path,
    *,
    policy: PolicyDriver,
    rollouts_per_task: int,
    infrastructure_retry_limit: int = 1,
) -> EpisodeBatchManifest
```

The batch runner:

1. cold-reads the CorpusManifest and exact TaskPacks;
2. creates the complete ordered `EpisodeRequest` set before the first rollout;
3. executes serially in the initial implementation;
4. retains every policy success/failure and infrastructure attempt;
5. never retries a policy failure as the same rollout;
6. fails closed on Task/Release/Semantics/Verifier authority defects;
7. aggregates reward counts, abstention owners, tool calls, tokens and latency.

The batch manifest does not choose another corpus and cannot modify Task or
Episode identity.

## 12. S2 integration rule

S3 may change existing S2 code only for shared causal needs:

- `public_agent.py`: expose complete policy outcomes;
- `task_execution.py`: evaluate policy failures after close/reopen;
- TaskPack readers: export strict runtime deserialization;
- `assessment.py`: reuse the shared public execution/lifecycle rather than keep
  divergent mechanics;
- current TaskPack formats only when an unavoidable new identity field is
  required. Prefer no TaskPack format change.

Changes forbidden as “S3 cleanup”:

- changing Task instructions, selectors, checkers or admission evidence;
- weakening two-witness or challenge gates;
- adding hidden setup or witness hints;
- making TaskAssessment determine Episode reward.

## 13. Failure ownership

```text
PolicyFailure          healthy policy execution did not complete/satisfy Task -> reward 0
InfrastructureFailure  provider/process/dependency unavailable -> abstain
EnvironmentDefect      actor/reset/tool/observation/persistence wrong -> abstain, block release
TaskArtifactDefect     TaskPack/corpus/identity/checker preimage invalid -> fail before acting
SemanticsDefect        binding/inspection/evaluator contract wrong -> abstain, reopen S1/S2
VerifierDefect         checker crashes/contradicts current frozen contract -> abstain
EvidenceDefect         lifecycle/projection/persistence incomplete -> abstain
```

Do not call all failures “hard Tasks”. Do not retry until success.

## 14. Anti-overdesign constraints

Do not add:

- a new Agent orchestration framework;
- a second Responses loop;
- event sourcing beyond the canonical Episode artifact;
- a server, broker, worker queue, database or registry;
- generic plugin discovery;
- a universal Task/state/reward DSL;
- partial-reward weights before real training evidence requires them;
- logprobs/token masks/trainer schemas inside S3;
- hidden reasoning storage.

A new component requires one named S3/S4 handoff or trust claim that the current
components cannot satisfy, plus a failing test or real counterexample.
