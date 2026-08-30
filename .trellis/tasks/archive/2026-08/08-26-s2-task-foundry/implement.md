# S2 Direct Good-Task Sampling Foundry — Implementation Plan

## 1. Execution rules

- Implement one Direct product claim at a time.
- Models may execute public Tasks; they never define Task truth or admission.
- Every new enforcement starts RED on real or real-derived evidence and kills a
  focused mutant before acceptance.
- Green unit tests never replace real Release, state transition, fresh witness,
  reload, challenge or cold artifact evidence.
- No backward compatibility, dual product path, hidden setup or domain branch.
- Graph/Programmatic are not active checkpoints.
- Main session performs alignment/overdesign review unless the user explicitly
  requests another reviewer.

## 2. Baseline and rollback point

The Direct production path at `189be1b` is the implementation baseline. Later A
commits adding shared physical reload/ReloadEvidence remain retained.

The abandoned B1-B3 obligation/TaskSpecification parallel path is deleted. Git
history is the rollback/audit record; no compatibility code or archive copy is
kept in the active branch.

## 3. Checkpoint 1 — Authority and single-path restoration

### Product claim

Active documents, Trellis context and production code describe exactly one
required Direct sampling path.

### Work

- remove mandatory Graph/Programmatic language from PROJECT, parent and S2
  authority;
- delete the isolated obligation/TaskSpecification/binding modules and tests;
- restore the current release/semantics contract consumed by Direct sampling;
- keep shared physical reload/provenance changes;
- prove `run_task_foundry_batch` and `run_task_foundry_product` are the actual
  production entry points;
- remove stale B GREEN and sampler metadata from task/context files.

### RED acceptance

- active authority containing a mandatory Graph/Programmatic phrase fails;
- task metadata listing required non-Direct samplers fails;
- any abandoned parallel B module still present fails;
- production batch imports a second candidate/admission path fails.

### Real exit

Full deterministic gates pass, old B symbols have zero live references and one
current Git/SQLite release can enter the Direct batch without a compatibility
switch.

## 4. Checkpoint 2 — Structural dedup and production batch audit

### Product claim

Direct sampling reports honest unique Task structures and persists admitted and
rejected candidates through one production API.

### Work

- audit `task_structure_id` against real Atom/ForEach/If examples;
- prove entity/parameter substitutions and paraphrases deduplicate;
- prove Goal/selector/condition/answer/Start differences remain distinct;
- audit balanced selection and candidate-attempt budgets;
- preserve every typed failure instead of retrying to success;
- cold-verify every persisted TaskPack identity.

### RED acceptance

- parameter-only variants satisfying a new structure target fail;
- a genuine condition/selector/answer difference collapsing to one structure
  fails;
- a batch target admitting an invalid Task or hiding a rejected attempt fails;
- artifact collision/tampering fails closed.

### Real exit

Run fixed-budget Git and SQLite batches and report candidate count, unique
structures, admitted TaskPacks, typed rejection classes and cost. No arbitrary
Task floor is a product gate.

## 5. Checkpoint 3 — Good-Task admission closure

### Product claim

Every TaskPack accepted by the Direct batch satisfies the intrinsic Good-Task
gates with physical evidence.

### Work

- audit two-fresh-witness enforcement for Atom/ForEach/If;
- verify full public argument provenance;
- retain close/reopen evidence for persistence;
- audit applicable no-op, wrong-target, partial, collateral and wrong-answer
  challenges;
- reject initially satisfied or publicly ungrounded Tasks;
- accept another valid path when found without requiring exhaustive search;
- migrate any remaining challenge that still verifies only in-process state.

### RED acceptance

Each applicable class has one real-derived bad execution accepted by the old
gate and rejected by the corrected gate. Boolean result flipping is not
physical evidence.

### Real exit

Seal real query, mutation/refusal, collection and condition TaskPacks across Git
and SQLite where the releases support them. Unsupported shapes abstain.

## 6. Checkpoint 4 — AllGoal only when licensed

### Product claim

Direct sampling can compose capabilities only when a real qualified
CompositionRule exists.

### Work

- first obtain a release whose business Need and Qualification support one
  CompositionRule;
- then implement All compilation, fresh binding, witness and physical
  challenges through the same admission/TaskPack path;
- do nothing when no conformance release supports All.

### RED acceptance

- arbitrary successful tool adjacency cannot authorize All;
- an All candidate omitting a rule capability or exceeding occurrences fails;
- unrelated collateral effects remain rejected.

### Real exit

One real All TaskPack, or a documented unsupported result if no accepted
CompositionRule exists. Coverage targets cannot manufacture one.

## 7. Checkpoint 5 — TaskAssessment and CorpusManifest

### Product claim

Assessment and corpus selection describe a training distribution without
changing individual Task truth.

### Work

- run fresh policy trials distinct from admission witnesses;
- preserve failure ownership, calls, tokens, latency and cost;
- verify TaskAssessment identity binds exact TaskPack and policy;
- verify CorpusManifest binds exact TaskPack/Assessment pairs;
- deduplicate structures and balance declared buckets deterministically;
- report model-relative difficulty without labelling Task/Verifier/Environment/
  Infrastructure defects as hard.

### RED acceptance

- assessment retry-until-success fails;
- one policy with uniform success cannot claim discrimination;
- corpus policy cannot validate or invalidate a TaskPack;
- paraphrase/entity variants cannot satisfy structural diversity alone.

### Real exit

Produce cold-readable Git/SQLite CorpusManifests with honest reliability,
distribution, redundancy and cost reports.

## 8. Checkpoint 6 — Held-out transfer and S3-shaped handoff

### Product claim

The frozen Direct Framework transfers to a Need selected after freeze and emits
TaskPacks consumable by the later episode/reward runtime.

### Work

- freeze Direct code, prompts, sampling/admission rules and budgets;
- select one held-out Need afterward and run S1 publication plus complete S2;
- relocate/cold-read Release, TaskPacks and Corpus;
- expose only PublicTaskView to the acting policy;
- exercise the public tool loop and deterministic verified facts;
- report typed low yield/abstention without domain patches.

### RED acceptance

- preselecting/tuning the held-out Need fails contamination checks;
- TaskPack identity or PublicTaskView leakage fails before acting;
- domain-specific Framework changes or weaker held-out gates fail transfer;
- S3 reward/logprob/training fields in S2 output fail the boundary.

### Real exit

Held-out execution yields valid TaskPacks or justified abstention, with the same
metrics and gates used for conformance releases.

## 9. Optional sampler experiments

Graph, Programmatic, backward planning or other search methods require a new
explicit experiment task after Direct fixed-budget evidence demonstrates a
named gap. The experiment must use the same admission path and matched budget.
No incremental useful Task gain means deletion. Optional experiments never
block Checkpoints 1–6.

## 10. Required validation

```bash
UV_CACHE_DIR=/tmp/foundry-s2-uv-cache uv lock --check
.venv/bin/ruff check src tests
.venv/bin/ruff format --check src tests
.venv/bin/mypy src
.venv/bin/python -m pytest -q
git diff --check
```

At every checkpoint also retain real run IDs/facts, run focused mutation
licenses, grep deleted symbols/domain branches and report production/test LOC
added and removed.

## 11. Completion

S2 completes only when Checkpoints 1–6 satisfy their real exits. Optional
sampler experiments and S3/S4 training are not completion gates.
