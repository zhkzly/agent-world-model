# S2 TaskAssessment and CorpusManifest

## Scope

This layer starts only after the active S2 PRD's intrinsic Good Task gates and
TaskPack admission. It measures acting policies and selects a corpus; it never
changes Task meaning, checker truth, admission evidence, EnvironmentRelease
qualification, or scalar training reward.

## TaskAssessment

Each assessment binds:

```text
TaskPack ID
EnvironmentRelease ID
Goal kind
model + route + public Agent prompt policy
ordered fresh trial results
```

Every trial opens a fresh materialization and runs the exact admitted public
instruction through the ordinary public tool loop. Checker failure and
`NoPublicWitness` are recorded as model-relative failures. Environment,
infrastructure, binding, condition or checker drift remains a typed upstream
error and must not be counted as model difficulty.

Admission witnesses are not assessment trials. Assessment reports empirical
reliability, provider turns, tokens, latency, failure codes and a structured
difficulty summary. These values do not enter TaskPack identity.

One policy lineage with uniform success cannot establish useful difficulty or
discrimination. Paper-ready S2 evidence uses at least two declared policy
lineages/checkpoints under matched trial budgets and keeps Task/Verifier/
Environment/Infrastructure defects out of the difficulty label.

## CorpusManifest

Corpus selection consumes exact `(TaskPack ID, TaskAssessment ID)` pairs. It:

- applies an explicit purpose and reliability policy;
- removes duplicate structures within one release;
- balances release/Goal buckets deterministically under a seed;
- binds all candidates in selection evidence;
- may select a subset without rejecting the omitted TaskPacks.

Corpus size, Goal distribution and reliability threshold are experiment policy,
not EnvironmentRelease or TaskPack admission gates. A manifest may not point to
an unadmitted TaskPack or to an assessment belonging to another TaskPack.

## Forbidden

- reusing admission witnesses as independent assessment;
- retrying failed trials until only successes remain;
- weakening a checker based on assessment yield;
- copying assessment or corpus identity into TaskPack identity;
- domain-specific selection branches;
- treating a corpus target count as proof of Task validity.

## Scenario: Cold Task handoff and assessed corpus

### 1. Scope / Trigger

Use this scenario whenever TaskPacks, Assessments or CorpusManifests cross a
process/root boundary or are exposed to an S3 acting policy.

### 2. Signatures

```python
verify_task_pack_artifact(path, task_pack_id) -> JSONObject
read_task_pack_artifact(path, task_pack_id) -> TrustedTaskView
read_identity_artifact(path, expected_identity=None) -> JSONObject
```

Current TaskPack formats are `atom-task-pack/4`, `foreach-task-pack/3` and
`if-task-pack/3`.

### 3. Contracts

`TrustedTaskView` retains the exact StartCase, checker digest and full Task
document. Its `PublicTaskView` contains exactly:

```text
format, task_pack_id, task_id, release_id, goal_kind, instruction, answer_schema
```

The acting policy obtains reset observation and ToolSpecs freshly from the
prepared release. It never receives StartCase input, checker, semantic key,
public descriptor as a separate oracle, protected binding, admission evidence
or witness trace.

Assessment, Corpus and Product documents are canonical current-format identity
artifacts. Persistence cold-reads and recomputes their preimages immediately.

### 4. Validation & Error Matrix

| Condition | Error |
| --- | --- |
| TaskPack bytes noncanonical/tampered | `task_pack_artifact_*` |
| unsupported pack/task shape | `task_pack_reader_*` |
| instruction differs from its digest | `task_pack_reader_instruction_mismatch` |
| Assessment/Corpus/Product preimage drift | `AssessmentError` identity preimage mismatch |
| Public projection gains a trusted field | public-view regression/mutation failure |

### 5. Good / Base / Bad Cases

- Good: relocate Release and S2 output, cold-read every identity, then run the
  exact public instruction on a fresh instance and satisfy the protected Host checker.
- Base: a failed Assessment trial remains in reliability/failure codes while
  TaskPack truth is unchanged.
- Bad: deserialize the whole TaskPack and pass it to the acting model.

### 6. Tests Required

- TaskPack tamper/collision/current-format and instruction-digest rejection.
- PublicTaskView exact-key assertion plus a leakage mutant.
- Assessment/Corpus/Product preimage mutation and relocation cold-read.
- One real S3-shaped fresh public episode from a relocated TaskPack.

### 7. Wrong vs Correct

Wrong:

```python
acting_input = json.loads(task_pack_bytes)  # leaks checker and witnesses
```

Correct:

```python
trusted = read_task_pack_artifact(path, expected_id)
acting_input = trusted.public.to_document()
```
