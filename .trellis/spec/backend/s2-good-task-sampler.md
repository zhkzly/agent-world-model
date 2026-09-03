# S2 Good-Task Sampler

## 1. Scope / Trigger

Use this contract when sampling Tasks from a current `EnvironmentRelease/3`,
admitting a TaskPack, or consuming the S2 corpus in S3. S2 owns executable Task
truth and public recoverability. It does not own environment generation,
Episode reward, training rows, or model updates.

## 2. Signatures

The production path is implemented by these public boundaries:

```python
sample_task_draft(...) -> SampledTaskDraft
materialize_candidate(...) -> CandidateTask
evaluate_goal(goal, context) -> EvaluationResult
filter_candidate(prepared, candidate, ...) -> TaskFilterEvidence
seal_task_pack(root, candidate, filter_evidence) -> TaskPackArtifact
load_task_pack(root) -> TaskPackArtifact
```

The batch command accepts a frozen S1 campaign, output root, model route,
attempt budgets, release-worker limit, and five-run admission threshold. It
writes terminal attempt records before rebuilding its summary and
`CorpusManifest` from those records.

## 3. Contracts

```text
fresh public execution
-> TaskDraft grounded in observed steps
-> Host provenance/state resolution
-> fresh replay through the common Goal evaluator
-> frozen Candidate
-> five fresh public policy runs
-> at least two passes
-> checker-free TaskPack
```

- `SamplingTarget` selects an under-covered Goal shape, focus tool and outcome;
  it never prescribes a tool sequence.
- The Sampling Agent sees Need/brief, target, reset, ToolSpecs and its own
  ToolObservations. It cannot read protected state or decide admission.
- Task truth uses only `AtomGoal`, `AllGoal`, `IfGoal` and `ForEachGoal` plus
  exact public argument/answer provenance and protected before/after facts.
- `PublicTaskView` contains only IDs, instruction and a type-only final-answer
  schema. Sampling evidence, expected answers, Goal truth and protected state
  stay trusted.
- S2 filter trajectories are admission evidence, not S3 Episodes or SFT rows.
- Task identity is independent of worker count, policy assessment and later
  Episode/training artifacts.

## 4. Validation & Error Matrix

| Condition | Terminal result |
|---|---|
| Target cannot be completed publicly | `SamplingUnsupported` |
| Draft/provenance/Goal is invalid or ambiguous | `DraftRejected` |
| Replay does not satisfy the frozen Goal | `DraftRejected` |
| Fewer than two of five valid policy runs pass | `PolicyRejected` |
| Structure identity already admitted | `DuplicateStructure` |
| Provider/transport prevents a semantic run | `InfrastructureFailure` |
| Framework invariant or evaluator path breaks | `FrameworkDefect` |

Infrastructure attempts never count as policy failures. Unsupported semantics
remain explicit and never authorize an easier fabricated Task.

## 5. Good / Base / Bad Cases

- Good: the Agent executes a coherent transition, Host freezes its real effect,
  a fresh replay passes, and at least two independent policies reach the same
  Goal through any valid route.
- Base: a public query or stable business refusal with grounded operands and a
  minimal observation-derived answer can be admitted.
- Bad: a non-empty trace with no completed objective, a repeated condition query
  presented as an `If`, an incomplete `ForEach`, an unmentioned free-text
  literal, or a transport `ok` flag used as answer truth is rejected.

## 6. Tests Required

- Unit mutations for Goal recursion, answer/provenance resolution, forbidden
  collateral changes and the exact two-of-five boundary.
- Physical fresh replay against real Releases before Candidate creation.
- TaskPack local and relocated cold-read with recomputed IDs.
- Public-view leakage checks for expected answer, protected state, sampling and
  filter evidence.
- Full campaign accounting: every Release terminal, every attempt retained,
  summary/manifest rebuilt exactly, and typed failure counts preserved.

## 7. Wrong vs Correct

### Wrong

```text
Tool Graph/random walk -> plausible calls -> generated per-Task Checker -> green
```

This can encode false dependencies, accept fabricated truth, and make each
environment add evaluator code.

### Correct

```text
Agent acts on real public state -> Host freezes observed Goal/evidence
-> common evaluator replay -> five fresh public attempts -> TaskPack
```

Adding a new Release adds data and measured outcomes, never a Framework domain
branch, compatibility reader, generated Checker or task-specific pressure suite.
