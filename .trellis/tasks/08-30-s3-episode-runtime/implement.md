# S3 Verified Episode Runtime — Implementation Plan

## 1. Execution rules

- Preserve S2 TaskPack truth and identities unless a concrete runtime blocker
  proves a format change unavoidable.
- Implement one shared public-policy/lifecycle path; refactor existing S2 callers
  onto it rather than add a parallel S3 loop.
- Models choose actions. Framework validates, dispatches, records and verifies.
- Every success/failure/abstention claim requires a named causal owner.
- Green unit tests never replace real Release, public tool, close/reopen, frozen
  checker and cold artifact evidence.
- Do not implement S4 training, a service layer or optional infrastructure.

## 2. Baseline and rollback

Base commit:

```text
c180112fb7d684707aecafd6d538dca50b38f983
```

The retained S2 product baseline includes exact Release v2 preparation,
PublicTaskView/TrustedTaskView, public Responses execution, close/reopen
ReloadEvidence, Atom/ForEach/If evaluators, TaskAssessment and CorpusManifest.

Rollback is Git history. No compatibility adapters or duplicate old/new episode
paths are allowed.

## 3. Checkpoint 1 — Freeze S3 contracts and ownership

### Product claim

S3 has an explicit identity/projection/reward contract before execution code is
changed.

### Framework work

Add immutable typed objects for:

```text
PolicySpec
EpisodeRequest
PublicEpisodeInput
EpisodeToolCall
PolicyTurn
PolicyCompletion
EpisodeVerification
RewardOutcome
EpisodeRecord
TrainingEpisodeView
EpisodeBatchManifest
all typed non-success owners
```

Rules:

- `PolicySpec` contains no credential and is not the current research-only
  hard-coded `AgentRoute`;
- `EpisodeRequest` freezes before the first policy call;
- `EpisodeRecord` separates public trajectory and trusted verification;
- `TrainingEpisodeView` has an exact allowed-key set;
- only `1.0`, `0.0` and `null` are valid base rewards;
- reward/disposition/abstain owner combinations are closed and validated;
- temporary paths, secrets and S2 witness IDs do not enter identity preimages.

### Files

```text
src/agent_env_foundry/episodes.py
tests/test_episode_models.py
```

Do not create a package hierarchy, registry or persistence backend.

### RED tests

- credential/base auth serialized in PolicySpec;
- reward `1.0` with failed checker;
- reward `0.0` with infrastructure owner;
- `null` reward without abstain owner/code;
- trusted field in TrainingEpisodeView;
- rollout/attempt indices zero, missing or duplicated;
- Episode ID changed by output path but not by trace/result mutation;
- TaskAssessment or S2 witness identity copied into Episode identity.

### Validation

```bash
uv run pytest -q tests/test_episode_models.py
uv run mypy src
uv run ruff check src tests
```

### Stop conditions

- an object has no direct S3 or S4 consumer;
- a universal state/reward ontology is introduced;
- target-policy identity still depends on the fixed S1 research route.

---

## 4. Checkpoint 2 — Preserve complete public policy outcomes

### Product claim

A healthy provider policy failure yields a complete failed trajectory instead of
throwing away prior tool actions.

### Framework work

Refactor `public_agent.py` into one core:

```python
capture_public_episode(port, policy_driver) -> PolicyCompletion
```

and retain the S2 wrapper:

```python
run_public_episode(...)
  -> capture_public_episode(...)
  -> require protocol completion
```

Implement one minimal `PolicyDriver` protocol and one production
`ResponsesPolicyDriver`.

Record:

- ordered provider/policy turns;
- function call IDs, names and raw parsed arguments;
- Host schema/dispatch outcome;
- public observations;
- final answer or public policy terminal code;
- per-turn usage.

Do not persist provider-private reasoning items.

### Files

```text
src/agent_env_foundry/public_agent.py
src/agent_env_foundry/episodes.py
tests/test_public_agent.py
tests/test_policy_completion.py
```

### RED tests

Use deterministic client responses to prove retained partial history for:

- unknown tool after one successful tool call;
- schema-invalid arguments;
- malformed function call;
- missing/schema-invalid final answer after a state change;
- provider-turn budget exhaustion;
- healthy policy refusal;
- provider exception after a tool call, attributed to infrastructure rather than
  policy.

Also prove:

- S2 `run_public_episode` still fails admission on non-completion;
- only function calls/final public answer are retained, not reasoning items;
- turn grouping and flat `TraceEvent` projection agree.

### Real exit

Run one current Responses route preflight that performs:

```text
function_call -> real tool observation -> continuation -> final answer
```

and retain one real policy-level failed completion if naturally available. A fake
client proves mechanics only.

### Stop conditions

- a second Responses loop is added;
- policy failures are converted to empty traces;
- infrastructure faults become reward-zero candidates;
- raw hidden reasoning becomes required artifact content.

---

## 5. Checkpoint 3 — Shared physical attempt lifecycle for success and failure

### Product claim

Completed and policy-failed episodes are both evaluated after closing and
reopening the same native instance.

### Framework work

Refactor `task_execution.py` to expose one lower-level episode lifecycle used by
S2 and S3:

```python
run_episode_attempt(
    prepared,
    instance_root,
    *,
    task_runtime,
    policy_driver,
) -> AttemptOutcome
```

Required order:

```text
open -> reset once -> inspect/preflight -> policy execute -> inspect -> close
-> reopen same native instance without reset -> inspect -> checker -> close
```

The lifecycle must complete post-reopen verification for policy-level terminal
failures. It may abstain when infrastructure/environment failure prevents
trustworthy closure.

Keep `run_public_attempt` only as a thin successful-S2 compatibility wrapper over
this same core, or replace its callers directly. No duplicate lifecycle.

### Files

```text
src/agent_env_foundry/task_execution.py
src/agent_env_foundry/task_foundry.py
src/agent_env_foundry/foreach_foundry.py
src/agent_env_foundry/if_foundry.py
src/agent_env_foundry/assessment.py
tests/test_task_execution.py
```

### RED tests

- policy reaches budget after mutating state: post-reopen facts and checker still
  recorded, reward later zero;
- invalid final answer after correct state transition: same behavior;
- second reset during reopen;
- another native instance substituted;
- same session reused for reopen;
- checker omitted or executed before reopen;
- provider outage after mutation: abstention owner preserved;
- S2 witness wrappers accept only completed+satisfied outcomes.

### Physical exit

Use current real SQLite and Git releases to run:

- one successful episode;
- one scripted public policy failure after a real tool mutation;
- one real close/reopen verifier evaluation for each.

The scripted driver is allowed to prove runtime failure handling; it is not
public-solvability evidence.

### Stop conditions

- in-memory state is used as final truth;
- S2 and S3 use different reopen/checker paths;
- Task checker details leak back into the same acting episode.

---

## 6. Checkpoint 4 — Strict TaskPack runtime and base Reward/abstention

### Product claim

One direct API runs any current admitted TaskPack kind and maps its frozen truth
to `1.0`, `0.0` or `null` without changing Task meaning.

### Framework work

Implement strict current-format runtime deserialization and dispatch:

```python
load_runtime_task(trusted_view) -> AtomTask | ForEachTask | IfTask

run_task_episode(
    prepared,
    task_pack_path,
    task_pack_id,
    policy_driver,
    instance_root,
    request,
) -> EpisodeRecord
```

Before acting:

- cold-read TaskPack;
- match Release/Task IDs;
- reconstruct fresh logical binding/context;
- recompute current checker preimage/digest;
- validate exact PublicTaskView projection;
- freeze EpisodeRequest and public input.

After acting:

- evaluate task-kind-specific frozen checker post-reopen;
- preserve exact canonical checker request/result;
- map base reward by the fixed policy;
- never compare with S2 witness traces;
- never rerun Task admission challenges.

### Files

```text
src/agent_env_foundry/episode_runtime.py
src/agent_env_foundry/batch_foundry.py
src/agent_env_foundry/task_foundry.py
src/agent_env_foundry/foreach_foundry.py
src/agent_env_foundry/if_foundry.py
tests/test_episode_runtime.py
```

### Required reward tests

```text
completed + satisfied             -> verified_success / 1.0
completed + checker failed        -> verified_failure / 0.0
policy terminal + checker failed  -> verified_failure / 0.0
correct mutation + missing answer -> verified_failure / 0.0
wrong target/partial/collateral   -> verified_failure / 0.0
provider/TLS error                -> abstain / null
actor observation defect          -> abstain / null
Task/checker identity drift        -> fail before policy call
semantics/checker crash            -> abstain / null
reload evidence incomplete         -> abstain / null
```

### Real exit

Across current Atom, ForEach and If TaskPacks, produce at least:

- one physical success;
- one physical checker failure;
- one infrastructure abstention using a controlled failing provider route;
- exact causal attribution for each.

### Stop conditions

- TaskAssessment reliability enters reward;
- a model judge decides success;
- reward shaping weights appear before base policy evidence;
- a task-specific arbitrary Python verifier is loaded from TaskPack.

---

## 7. Checkpoint 5 — Episode persistence and non-leaking S4 view

### Product claim

Episode truth survives persistence/relocation, while S4 receives only public
trajectory plus reward labels.

### Framework work

Persist:

```text
episodes/<episode_id>/EpisodeRecord.json
views/<episode_id>/TrainingEpisodeView.json
```

Implement:

```python
verify_episode_artifact(path, episode_id) -> JSONObject
read_episode_artifact(path, episode_id) -> TrustedEpisodeView
read_training_episode_view(path, episode_id) -> TrainingEpisodeView
```

Cold readers must verify:

- canonical bytes and exact current format;
- request/policy/task/release identity bindings;
- public input digest;
- turn/trace/final-answer consistency;
- checker result/reward consistency;
- exact public/training projection key set;
- no protected facts, semantic keys, Start input, expected branch, checker
  details, S2 witnesses or admission challenges in the training view.

### Files

```text
src/agent_env_foundry/episodes.py
src/agent_env_foundry/episode_runtime.py
tests/test_episode_artifacts.py
```

### RED tests

- change one tool argument, observation, final answer, reward or checker result;
- replace policy ID or TaskPack ID;
- copy an Episode into another request;
- add a protected field to TrainingEpisodeView;
- make TrainingEpisodeView reward differ from trusted record;
- relocate artifacts and attempt path-dependent identity.

### Physical exit

Relocate one success, one failure and one abstention Episode. Cold-read all
identities and use only TrainingEpisodeView to reconstruct the public
instruction/tool trajectory needed by a dummy S4 consumer.

### Stop conditions

- full TaskPack/Episode trusted JSON is handed to S4 as the training view;
- a database/registry is added for artifact lookup;
- native instance directories are required as permanent Episode identity.

---

## 8. Checkpoint 6 — Deterministic corpus batch execution

### Product claim

One direct batch API executes an exact CorpusManifest under a target policy and
retains every rollout outcome honestly.

### Framework work

Implement:

```python
run_episode_batch(
    prepared,
    task_store_root,
    corpus_manifest_path,
    output_root,
    *,
    policy_driver,
    rollouts_per_task,
    infrastructure_retry_limit=1,
) -> EpisodeBatchManifest
```

The runner must:

- cold-verify CorpusManifest and TaskPack paths;
- freeze all EpisodeRequests before the first policy call;
- execute serially initially;
- persist every policy success/failure;
- persist every infrastructure abstention/retry attempt;
- never retry policy failure as the same rollout;
- stop the affected authority on Task/Environment/Semantics/Verifier defects;
- report reward distribution, failure/abstain owners, calls, tokens and latency;
- not reselect Tasks or alter CorpusManifest.

### Files

```text
src/agent_env_foundry/episode_batch.py
src/agent_env_foundry/episodes.py
tests/test_episode_batch.py
```

### RED tests

- hidden retry-until-success;
- dropped failed rollout;
- corpus entry resolved to another TaskPack;
- duplicate request index;
- policy failure retried as infrastructure;
- task/verifier defect counted as model failure;
- aggregate counts/cost disagree with Episode records;
- output root reused/collided.

### Real exit

Run fixed rollouts over one Git and one SQLite corpus. Report exact success,
failure, abstain, tool call, token and latency counts. Batch size is an
experiment parameter, not a correctness gate.

### Stop conditions

- parallel scheduler/queue added before a measured bottleneck;
- batch policy modifies Task validity or corpus membership;
- only successful episodes are persisted.

---

## 9. Checkpoint 7 — Held-out transfer and S4-shaped handoff

### Product claim

The frozen S3 runtime transfers across current conformance and held-out releases
and exposes a usable policy/training boundary without implementing S4.

### Work

- freeze S3 contracts, prompt, reward map and batch rules;
- run current Git, SQLite and post-freeze equipment-maintenance artifacts without
  domain changes;
- execute Atom/ForEach/If where present;
- run at least one real Responses policy through the full batch path;
- exercise a second policy identity or scripted public driver to prove the
  runtime is not bound to the S2 witness model;
- cold-read TrainingEpisodeViews;
- implement one tiny S4-shaped consumer that groups successful/failed/non-trainable
  episodes without tokenization or optimization;
- confirm TaskPack and Corpus identities are unchanged.

### Required evidence

```text
real verified_success
real or physical verified_failure
controlled infrastructure abstention
close/reopen evidence
cold artifact relocation
exact public/training projection
cross-policy identity separation
cross-environment no-domain-branch execution
```

### Fatal outcomes

- target policy receives protected fields;
- failed trajectories cannot be reconstructed;
- provider failure and model failure are inseparable;
- S3 requires modifying Task truth or re-admitting Tasks;
- S4 cannot drive/read the public trajectory without bypassing trust;
- runtime is hard-coded to one model/route or one environment domain.

### Stop conditions

- trainer/chat-template/logprob/token-mask code enters S3;
- a new Agent framework is introduced instead of the small PolicyDriver boundary;
- internal success counts are called training utility.

---

## 10. Required validation

At every checkpoint:

```bash
UV_CACHE_DIR=/tmp/foundry-s3-uv-cache uv lock --check
.venv/bin/ruff check src tests
.venv/bin/ruff format --check src tests
.venv/bin/mypy src
.venv/bin/python -m pytest -q
git diff --check
```

Also retain:

- focused mutation licences for projection, reward and identity;
- exact real Release/TaskPack/Corpus/Episode IDs;
- provider route/version and non-secret PolicySpec;
- production/test LOC added and removed;
- typed failures rather than repaired-away attempts.

## 11. Completion

S3 completes only after Checkpoints 1–7 meet their real exits. A successful
Responses demo, an Episode dataclass, a binary reward function or green tests
alone are not completion.
