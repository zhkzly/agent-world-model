# S3 Verified Episode Runtime — Implementation Plan

## 1. Planning and execution rules

This document is a candidate execution plan, not implementation authority.
The task remains `planning` until:

1. PRD, design, this plan, checklist and context manifests converge;
2. activation input readiness is closed;
3. the final planning summary receives explicit user approval;
4. `task.py start` succeeds.

Execution rules after activation:

- complete one checkpoint at a time;
- implement only mechanisms consumed by the current checkpoint;
- preserve exact S2 TaskPack truth and the current successful S2 artifact
  formats/identity preimages;
- keep one Host-owned policy/tool loop and one exact S3 Task lifecycle;
- models choose public actions; Host validates, dispatches, records and verifies;
- every non-success has one named causal owner;
- deterministic tests, physical evidence, live-provider evidence and relocation
  evidence are distinct;
- a checkpoint is an acceptance gate, never a demo or MVP milestone;
- no later checkpoint starts until the current checkpoint is explicitly
  `ACCEPTED`.

### Deletion-first rework result

CP1R and CP2R are accepted in separate commits `758d734` and `d59b177`. A
retained field, helper, validation, exception or projection must be required by
the original Episode/Policy/Reward request or the current S2/S3 execution path.
Tests written solely around an introduced abstraction do not count as
consumers, and later-checkpoint usefulness is not a retention reason.

The rework removed the non-JSON freeze/thaw internals, producer-less PolicySpec
surface, duplicate ToolSpec snapshot/validation, parallel trace ledger and
duplicate driver defenses/details. It did not move packages or add directories.
The pruned CP3-CP6 plan below follows the smaller implementation.

No checkpoint may add task generation, automatic retry, a second Agent loop,
veRL/trainer code, a service, Registry, queue, database or optional framework.

## 2. Baseline, authority readiness and rollback

### Product-code baseline

```text
c180112fb7d684707aecafd6d538dca50b38f983
```

Changes after this commit on the S3 branch are planning/session records only.
At activation, record the base HEAD plus canonical digests of the accepted
planning artifacts; do not silently use later edited documents as authority.

Rollback is Git history. No compatibility adapter, feature flag or duplicate
old/new episode path is allowed.

### Upstream input readiness

Paths below are operational locators only and never identity fields.

| Authority | Exact IDs / current coverage | Current readiness |
| --- | --- | --- |
| Git | Release `14331ac6e82e0ac79382d5c5e964c62f6cc9ece506f726299d0645594fbafe80`; Corpus `4fddce70a03b716de69041397b941c4e752e7bf969b8de27d387777ebaaa8344`; Atom + two ForEach packs | READY: retained Release located, exact regeneration command recovered, current readers passed. |
| SQLite | Release `64fa07e1a144536df2ae3ff9b0cf30175e8b0f913f1e34d8731b8377a80ebb87`; Corpus `a750a8127058f8afc9e2f1c038d1a3c3ef39a9205d2e9b83aee69a221802ae68`; Atom + ForEach + If packs | READY: Release, selected packs and embedded-If dependency passed current readers. |
| inherited maintenance | Release `7e2c0718a7de84b07261b729cbe12da86e313c75e4aa107d60ede4c2c34e407a`; Corpus `31eb42b31e621c4ba75892f5866222f80055ccca00a0a018788a4f17d32eb14e`; Atom + ForEach packs | READY: Release, Corpus and all selected packs passed current readers. |

Activation readiness requires:

- exact Release IDs recomputed with current `verify_release_v2`;
- exact Corpus identities recomputed with `read_identity_artifact`;
- every selected TaskPack cold-read with its expected identity;
- every corpus entry matched to the one Release used by that batch;
- current Task kind coverage and If embedded-branch availability recorded;
- reproducible reconstruction commands/inputs retained without making temporary
  paths authoritative.

The exact receipt and Git regeneration provenance are recorded in
`research/input-readiness.md`. Any later locator loss or ID mismatch returns
the task to planning; no substitute authority is allowed.

## 3. Checkpoint closure protocol

CP1–CP5 close only after all of the following:

1. **Scope/authority audit**
   - reread `PROJECT.md`, `DECISIONS.md`, current task artifacts and relevant
     specs;
   - identify the exact existing mechanism being reused;
   - prove no later-checkpoint component is being introduced.
2. **Named RED evidence**
   - add the checkpoint's listed failing cases;
   - run them before implementation and record that they fail for the intended
     reason, not import/setup noise.
3. **Implementation**
   - change only the named checkpoint scope;
   - preserve unrelated user changes and successful S2 projections.
4. **Named mutation licence**
   - state one concrete semantic corruption;
   - name the test that kills it and the exact command/result;
   - reject tautological result-object flipping.
5. **Validation**
   - focused checkpoint tests;
   - locked lint, format and type checking;
   - full deterministic suite;
   - `git diff --check`.
6. **Required non-deterministic evidence**
   - run only the physical/live/cold evidence owned by this checkpoint;
   - retain exact Release/TaskPack/Corpus/Policy/Episode IDs.
7. **Independent review**
   - review scope, trust flow, leakage, code reuse, cross-layer identities and
     plan drift at the exact source snapshot (HEAD plus diff digest);
   - critical findings are verified against code before acceptance.
8. **Verdict**
   - `ACCEPTED` or `REWORK`;
   - rework remains inside the same checkpoint.

CP6 introduces no new production RED or component. It reruns the frozen full
matrix. Any failure returns to the owning checkpoint, requires rework/review,
and restarts downstream evidence.

## 4. Evidence classes

| Evidence class | Valid claim | Invalid claim |
| --- | --- | --- |
| Deterministic | schema, identity, capture mechanics, failure/reward matrix, killed mutants | real provider behavior or physical persistence |
| Physical | real Release code, public tools, native persistence, close/reopen/checker; scripted policy allowed | model solvability or provider quality |
| Live provider | actual Responses request, continuation, model/tool behavior and reported usage | reward or physical lifecycle by itself |
| Cold/relocation | canonical writes, path independence, identity/projection verification | execution behavior by itself |

A naturally occurring live failure is useful evidence but never a deterministic
checkpoint gate.

## 5. Checkpoint 1 — Minimal Episode/Policy/Reward contract kernel

### Product claim

Identity, public capture and base reward ownership are explicit before the
shared execution code changes, without prebuilding persistence or batch
machinery.

### Framework work

Add one `episodes.py` module containing only:

```text
PolicySpec
EpisodeRequest
PublicEpisodeInput
EpisodeToolCall
PolicyTurn
PolicyCompletion
PublicEpisodeCapture
EpisodeDefect + closed DefectOwner
RewardOutcome
```

Required invariants:

- PolicySpec binds applied, non-secret policy facts and rejects credentials,
  auth headers, paths and arbitrary plugin fields;
- EpisodeRequest has release/task-pack/task/policy IDs plus positive 1-based
  `rollout_index`, with no retry/attempt index;
- public input contains exact prompt text, instruction, reset observation,
  model-facing ToolSpecs and answer schema;
- invalid calls retain raw call-ID/name/argument material plus optional
  normalized IDs/names and parsed values;
- Host turns own calls/observations/usage exactly once;
- completion contains only `completed` or `policy_failure`;
- PublicEpisodeCapture contains at least one completion or defect; both are
  allowed when valid completion is followed by Host close/usage failure;
- defects use one flat `(owner, code, phase)` value with provider and
  infrastructure distinct;
- RewardOutcome allows only:

```text
verified_success / 1.0 / no abstain owner
verified_failure / 0.0 / no abstain owner
abstain         / null / required owner+code
```

- every JSON value is deeply snapshotted; caller alias mutation cannot change
  an object's identity or serialization.

Do not add `EpisodeVerification`, `EpisodeRecord`,
`TrainingEpisodeView`, `EpisodeBatchManifest`, persistence, Task runtime or
retry types.

### Files

```text
src/agent_env_foundry/episodes.py
tests/test_episode_models.py
```

### RED and mutation evidence

- credential/auth/path field in PolicySpec;
- route identity derived from URL credentials/query secrets, or identical
  non-secret routes producing different policy IDs under credential rotation;
- generic generation/config bag or undeclared identity-bearing driver option;
- request index zero/negative/non-integer;
- any attempt/retry field in EpisodeRequest;
- provider omitted from the owner set or collapsed into infrastructure;
- completion containing infrastructure status;
- valid completion followed by driver-close/usage defect cannot discard either
  the completion or the one primary defect;
- reward `1.0` for failure, `0.0` for abstention, or null without owner/code;
- original nested JSON mutation changing a constructed value;
- output path, TaskAssessment or S2 witness entering an identity preimage.

Named mutation licence: change one closed reward/owner combination or retain a
mutable input alias; `tests/test_episode_models.py` must kill it.

### Validation

```bash
UV_CACHE_DIR=/tmp/foundry-s3-uv-cache uv run --frozen pytest -q tests/test_episode_models.py
```

### Stop conditions

- a CP2/CP3 consumer cannot be named for a type;
- a generic failure hierarchy or universal trajectory ontology appears;
- EpisodeRecord/View/Batch scaffolding is introduced;
- target identity still depends on fixed research `AgentRoute`.

---

## 6. Checkpoint 2 — One Host-owned public loop and Responses adapter

### Product claim

One trusted Host loop preserves complete public decisions for successful and
healthy failed policies; Responses is only a one-turn adapter.

### Framework work

Refactor the existing `run_public_episode` implementation into:

```python
capture_public_episode(
    *,
    actor: Environment,
    instruction: str,
    reset_observation: JSONValue,
    answer_schema: JSONObject,
    policy_driver: PolicyDriver,
) -> PublicEpisodeCapture
```

The Host:

- snapshots `actor.tools()` once, builds model-facing specs and dispatch catalog
  from the same value, and freezes PublicEpisodeInput before driver start;
- verifies prompt text digest and driver PolicySpec, and takes the sole turn
  budget from that PolicySpec;
- requests one decision per turn;
- validates call metadata, JSON and schema;
- dispatches validated calls and validates observations;
- records raw invalid calls and public terminal material;
- derives the flat checker trace;
- distinguishes policy, provider and local infrastructure terminals.

`PolicyDriver` exposes PolicySpec and one decision method. The production
`ResponsesPolicyDriver`:

- applies exactly the PolicySpec model, prompt, route, turn-independent request
  fields and any explicit identity-bearing options accepted by CP1;
- keeps opaque provider continuation state only in memory;
- is single-Episode/single-use and rejects a second start;
- is closed by the Host in `finally` for every terminal path;
- performs one `responses.create` call per Host request;
- cannot invoke tools, reset, inspect, check, retry or run a loop;
- filters hidden/private reasoning items from persisted output.

Retain `run_public_episode` as the successful S2 wrapper:

```text
capture_public_episode
-> require healthy completed protocol
-> project exact existing PublicEpisodeRun
-> otherwise raise the existing S2 failure semantics
```

Provider boundary:

- explicit remote 429/5xx/outage/timeout/service failure after a valid request:
  `provider`;
- credential/auth/route/client/DNS/TLS/proxy/socket/dependency/process/I/O:
  `infrastructure`;
- remote 400/422 request rejection caused by the Host request: `evidence`;
- unexpected envelope without proved remote/Host ownership: unattributed block;
- healthy refusal/malformed call/wrong answer/budget exhaustion:
  policy failure;
- unattributed exception: block, do not guess or emit training evidence.

### Files

```text
src/agent_env_foundry/public_agent.py
src/agent_env_foundry/episodes.py
tests/test_public_agent.py
tests/test_policy_capture.py
```

### RED tests

Deterministic client responses must preserve the full earlier prefix for:

- unknown tool after a successful call;
- missing/malformed/non-string call ID or name with exact raw values retained;
- non-JSON, non-object and schema-invalid arguments;
- multiple calls where an earlier call succeeded and a later call failed;
- missing/malformed/schema-invalid final answer after mutation;
- healthy refusal;
- Host turn-budget exhaustion;
- explicit provider 429/5xx/service defect after a call;
- remote 400/422 and unexpected envelope are not mislabeled provider defects;
- local infrastructure defect after a call;
- driver close/usage sealing defect after a valid final answer retains the
  completion and adds the primary defect.

Also prove:

- invalid calls do not enter `TraceEvent`;
- turn grouping and flat trace agree;
- raw Responses fixtures map every public call/terminal item exactly into a
  decision, and Host ledger rejects duplicate IDs/result mismatches;
- usage exists only on Host turns;
- actual Responses request matches PolicySpec;
- mismatched prompt digest, independent turn budget or driver PolicySpec fails
  before the first provider call;
- actor ToolSpecs are snapshotted once and the model/dispatch catalogs cannot
  diverge;
- successful S2 `PublicEpisodeRun` format/key set and projection behavior are
  unchanged;
- provider-private reasoning does not persist;
- driver continuation/client state cannot cross two Episode captures.

Named mutation licence: restore the old raise-before-return behavior after one
successful call; the partial-capture tests must kill it.

### Real exit

Run one live current Responses route:

```text
decision -> real public tool observation -> continuation -> final answer
```

The live success proves adapter integration only. Deterministic failure cases,
not a naturally occurring model failure, close CP2.

### Stop conditions

- driver receives `invoke` or direct actor/session access;
- a second Responses/Agent loop exists;
- provider and infrastructure collapse;
- policy failures become empty captures;
- hidden reasoning becomes an artifact.

---

## 7. Checkpoint 3 — Exact single-Task Episode runtime

### Product claim

One direct API consumes an exact current TaskPack, runs Atom/ForEach/If through
the existing physical lifecycle and returns one in-memory EpisodeRecord with a
truthful `1.0`, `0.0` or typed null. There is no standalone generic lifecycle
framework before this concrete consumer.

### Framework work

Implement:

```python
run_task_episode(
    prepared,
    task_pack_path,
    expected_task_pack_id,
    *,
    policy_driver,
    rollout_index,
    instance_root,
) -> EpisodeRecord
```

Before acting:

- cold-read exact TaskPack bytes and IDs;
- match the prepared Release;
- decode only Atom v4, ForEach v3 and If v3 current formats;
- for If, validate and use the embedded branch AtomTaskPack without candidate
  recompilation;
- freeze PolicySpec and logical EpisodeRequest, requiring request.policy_id to
  equal the fresh driver's PolicySpec ID;
- open/reset, reconstruct fresh logical binding/context and recompute checker
  preimage/digest;
- snapshot actor tools, construct PublicEpisodeInput and validate the exact
  public projection;
- only then make the first policy call.

After acting:

- continue completed, policy-failed and sealable defected captures through
  pre-close inspect, close, same-instance reopen without reset, post-reopen
  inspect, the exact task-kind checker and final close;
- retain only the achieved lifecycle facts and one primary defect; do not add a
  reusable `AttemptOutcome` framework or per-owner exception hierarchy;
- execute and retain the exact existing Atom/Condition checker request documents
  after reopen, grouped directly by Task kind without a new checker type;
- bind request, PolicySpec, capture, elapsed latency, minimal request-bound
  lifecycle facts, exact checker request/result and RewardOutcome into
  EpisodeRecord;
- derive Episode ID from the entire canonical record.

The existing `run_public_attempt` and `ReloadEvidence/1` remain the exact S2
success projection. The runtime may extract only the smallest private
task-kind helpers needed to avoid duplicating current checker construction.
TaskAssessment is not changed by S3.

Input-authority behavior:

- invalid Release/Corpus/TaskPack authority before request: typed direct failure
  or corpus-slot blocked result, no EpisodeRecord/View;
- reset/preflight/environment/semantics failure after request but before public
  input: request-bound blocked result, no empty capture/Record/View;
- unattributed exception: block, no completion claim.

### Files

```text
src/agent_env_foundry/episode_runtime.py
src/agent_env_foundry/episodes.py
src/agent_env_foundry/task_execution.py
src/agent_env_foundry/task_foundry.py
src/agent_env_foundry/foreach_foundry.py
src/agent_env_foundry/if_foundry.py
tests/test_task_execution.py
tests/test_episode_runtime.py
```

Only files proved necessary by a failing current-kind path may change; the list
is an upper bound, not a requirement to touch every file.

### RED and reward/authority tests

- after a real public mutation, policy budget or invalid final answer still
  reaches same-instance reopen and the frozen checker;
- reset/preflight failure before PublicEpisodeInput creates no EpisodeRecord;
- observable reopen/inspect/checker/cleanup failure retains achieved events and
  abstains; swallowed child-close failures are not fabricated;
- another native instance, second reset, same session or checker-before-reopen
  is rejected;
- a failed/incomplete S3 path cannot fabricate legacy `episode_complete` or
  `ReloadEvidence/1`;

```text
completed + satisfied                           -> success / 1.0
completed + checker failed                      -> failure / 0.0
policy terminal + checker failed                -> failure / 0.0
policy terminal + checker satisfied             -> failure / 0.0
correct mutation + missing answer               -> failure / 0.0
wrong target/partial/collateral                  -> failure / 0.0
provider defect after satisfying mutation       -> abstain / null
infrastructure defect after satisfying mutation -> abstain / null
completed+satisfied + any trust defect           -> abstain / null
policy failure + incomplete reopen/checker       -> abstain / null
environment/semantics/verifier/evidence defect   -> abstain / null
pre-input Task/checker authority defect          -> no Episode / typed failure
unattributed exception                           -> block / no training view
```

Also prove:

- exact If embedded branch is required and validated;
- malformed nested admission fails before policy call;
- candidate recompilation is impossible;
- TaskAssessment/witness data cannot enter reward;
- output path and native directory are absent from identity;
- changing any call, lifecycle, checker, policy, request or outcome under an old
  ID fails validation.

Named mutation licences: reorder close/reopen/checker, and flip one
checker/reward/defect-precedence branch. The corresponding lifecycle and reward
tests must independently kill them.

### Physical exit

Across the exact authority set:

- execute Atom, ForEach and If after real close/reopen;
- produce a real-persistent verified success;
- produce a real-persistent checker/policy failure;
- carry one controlled provider/infrastructure abstention through the real
  lifecycle with exact owner separation.

All three Task kinds are required across the total set, not necessarily in
every release.

### Stop conditions

- a generic AttemptOutcome, public callback framework or TaskAssessment repair
  appears without another current consumer;
- TaskPack format changes or compatibility readers appear;
- candidate compilation or an arbitrary verifier is used;
- raw checker data leaks to policy;
- model judge or reward shaping enters;
- provider and infrastructure owners conflate.

---

## 8. Checkpoint 4 — Canonical Episode bundle and non-leaking view

### Product claim

Episode truth survives canonical persistence and relocation, while downstream
receives the exact public trajectory/reward projection and no trusted checker
material.

### Framework work

Persist one paired bundle only under a required-new output root:

```text
episodes/<episode_id>/
  EpisodeRecord.json
  TrainingEpisodeView.json
```

Implement one authoritative paired reader. An S4-facing helper may return only
the view, but must verify the trusted record and exact projection internally.

Cold verification checks:

- canonical bytes/current format;
- request/policy/task/release/attempt/lifecycle/checker cross-bindings;
- Host turns versus checker trace;
- checker result versus reload digest and RewardOutcome;
- exact nested TrainingEpisodeView schema;
- exact public prompt/instruction/reset/model-facing ToolSpecs/answer schema;
- nullable PolicyCompletion kind/code for terminals without raw output/final
  answer;
- no provider usage/latency, native facts, lifecycle, checker data/codes,
  defect details, Start input, protected bindings, S2 evidence or hidden
  reasoning in the view.

Publication failure produces no valid bundle/view. It is a run-level evidence
failure and cannot be self-certified by mutating the same EpisodeRecord being
published. Strict readers reject any partial directory.

### Files

```text
src/agent_env_foundry/episodes.py
src/agent_env_foundry/episode_runtime.py
tests/test_episode_artifacts.py
```

### RED tests

- mutate a raw or normalized call ID/name/argument/observation;
- mutate raw terminal/final answer/usage/latency;
- replace policy/request/TaskPack/Release identity;
- mutate lifecycle event/fact/checker request/result/reward;
- copy one Episode bundle under another request/ID;
- add a trusted field or raw checker failure code to the view;
- omit prompt text, model-facing ToolSpecs, answer schema or PolicyCompletion
  kind/code;
- make view reward/disposition/trajectory differ from the record;
- relocate and attempt path-dependent identity;
- mutate original nested JSON after object construction;
- fail after record write, after view write or during paired cold-read; the
  partial directory must be rejected and no TrainingView claimed;
- collide with an existing output directory.

Named mutation licence: add one checker-derived field to the view or allow a
view-only reader to bypass the trusted record; projection tests must kill it.

### Cold/physical exit

Persist and relocate one success, one failure and one abstention bundle.
Cold-read each through the paired reader and reconstruct the exact public input
and trajectory from only the returned TrainingEpisodeView.

No production dummy/S4 consumer is added.

### Stop conditions

- view is trusted independently of EpisodeRecord;
- full TaskPack/Episode JSON is handed downstream;
- a Registry/database is introduced;
- native instance directories become permanent identity.

---

## 9. Checkpoint 5 — Exact serial Corpus batch

### Product claim

One direct batch API executes an exact single-release CorpusManifest under one
target policy. A successfully published batch retains one honest result for
every rollout slot; a publication failure aborts without a final manifest.

### Framework work

Implement:

```python
run_episode_batch(
    prepared,
    task_store_root,
    corpus_manifest_path,
    expected_corpus_id,
    output_root,
    *,
    policy_spec,
    policy_driver_factory,
    rollouts_per_task,
) -> EpisodeBatchManifest
```

Before acting:

- cold-verify exact expected CorpusManifest;
- typed-reject multi-release corpora;
- resolve every TaskPack and release binding;
- freeze all valid requests in deterministic corpus/rollout order;
- retain invalid/missing TaskPack entries as blocked rollout slots without
  fabricating request/public/Episode data.
- retain post-request pre-public-input failures as request-bound blocked slots
  without fabricating capture/Episode data.

Execution:

- serial only;
- create, PolicySpec-check and close one fresh driver per rollout;
- one attempt per rollout;
- no SDK/Host retry parameter or retry slots;
- persist every success, failure, abstention and blocked slot;
- abort without a final EpisodeBatchManifest if any Episode bundle fails
  write/cold-read; do not fabricate the unexecuted remainder as blocked;
- stop affected Task/Release authority on trusted defects;
- never change corpus membership or Task validity.

Persist only:

```text
batches/<batch_id>/EpisodeBatchManifest.json
```

Aggregates are derived from retained records: dispositions, blocked counts,
attempted/dispatched calls, provider turns, reported input/output tokens,
missing-usage count, latency and abstain-owner counts. Do not claim monetary
cost.

### Files

```text
src/agent_env_foundry/episode_batch.py
src/agent_env_foundry/episodes.py
tests/test_episode_batch.py
```

### RED tests

- wrong expected corpus ID or noncanonical manifest;
- multi-release corpus silently accepted/skipped;
- corpus entry resolved to another TaskPack/Release;
- duplicate logical request/rollout index;
- invalid TaskPack fabricated into an EpisodeRequest;
- policy failure retried or overwritten;
- dropped success/failure/abstain/blocked result;
- authority defect counted as model failure;
- aggregate mismatch, including missing usage silently treated as zero;
- Episode publication failure still emits a final manifest or fake blocked
  remainder;
- reused/colliding output root;
- duplicate run artifact emitted;
- driver instance or continuation state reused across rollouts.

Named mutation licence: drop one failed/blocked result or alter one aggregate;
manifest reconciliation tests must kill it.

### Physical exit

Run fixed rollout counts over exact Git and SQLite single-release corpora.
Report all IDs, dispositions, blocked slots, calls, provider turns, reported
tokens, missing-usage count and latency.

### Stop conditions

- parallel scheduler/queue or automatic retry appears;
- explicit TaskPack-set batch source appears;
- batch changes Task validity/corpus membership;
- only successful Episodes persist;
- a multi-release scheduler is invented.

---

## 10. Checkpoint 6 — Frozen S3 stage acceptance

### Product claim

The CP1–CP5 runtime transfers across exact conformance and inherited maintenance
authority and exposes the S4 boundary without implementing S4.

### Freeze rule

Pin the accepted CP5 source snapshot (HEAD plus diff digest) before the CP6 run.
CP6 adds no production component, schema or helper.

If CP6 finds a defect:

1. identify the owning earlier checkpoint;
2. mark it `REWORK`;
3. fix/review there;
4. rerun every affected downstream checkpoint;
5. freeze a new source snapshot before repeating CP6.

### Required evidence

- exact Git, SQLite and inherited maintenance Release/Corpus/TaskPack IDs;
- Atom, ForEach and If across the total authority set;
- one real Responses policy through the full production batch path;
- one scripted second PolicyDriver identity through the same Host loop;
- real-persistent verified success and verified failure;
- controlled typed provider/infrastructure abstention with no owner conflation;
- complete and partial lifecycle evidence;
- relocated paired Episode bundles;
- exact non-leaking S4-facing view;
- unchanged TaskPack and Corpus identities;
- no Framework domain branches.

The scripted second driver proves boundary generality only. The view consumer is
test-only. Internal success counts are not called training utility.

### Fatal outcomes

- new production code is required only for CP6;
- target policy sees protected fields;
- failed trajectories cannot be reconstructed;
- provider/infrastructure/policy failures are inseparable;
- S3 changes/re-admits Task truth;
- runtime is hard-coded to one model/route/domain;
- S4 requires bypassing trusted projection;
- trainer/veRL/service/Registry code appears.

---

## 11. Locked validation

At activation, create/sync the locked development environment once if absent:

```bash
UV_CACHE_DIR=/tmp/foundry-s3-uv-cache uv sync --frozen --group dev
```

At every CP1–CP5 verdict:

```bash
UV_CACHE_DIR=/tmp/foundry-s3-uv-cache uv lock --check
UV_CACHE_DIR=/tmp/foundry-s3-uv-cache uv run --frozen ruff check src tests
UV_CACHE_DIR=/tmp/foundry-s3-uv-cache uv run --frozen ruff format --check src tests
UV_CACHE_DIR=/tmp/foundry-s3-uv-cache uv run --frozen mypy src
UV_CACHE_DIR=/tmp/foundry-s3-uv-cache uv run --frozen python -m pytest -q
git diff --check
```

Focused tests are additive; they never replace the full suite.

Retain per checkpoint:

- named RED and killed mutant;
- exact reviewed source snapshot and diff scope;
- exact input/output artifact IDs;
- non-secret PolicySpec and actual Responses configuration;
- typed defects and lifecycle evidence;
- independent review findings and final verdict.

## 12. Completion

CP1 closes contracts only. CP1–CP4 may close the single-Task runtime slice.
Only CP1–CP6 together complete S3.

An Episode dataclass, green tests, one successful Responses run, a scripted
physical path or a binary reward function alone is never S3 completion.
