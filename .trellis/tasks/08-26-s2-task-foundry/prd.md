# S2 Direct Good-Task Sampling Foundry

## Product goal

Given one immutable qualified `EnvironmentRelease`, sample a useful collection
of high-quality Tasks that downstream tool-calling Agents can actually execute
and that deterministic environment truth can grade.

```text
EnvironmentRelease
-> Direct Candidate Task sampling
-> Good Task admission
-> TaskPack
-> TaskAssessment
-> CorpusManifest
```

S2 does not generate environments, scalar rewards, trajectories, token masks or
training updates. Those belong to S1, S3 and S4 respectively.

## Inputs from S1

S2 consumes only exact admitted Release authority:

- immutable Release identity and cold preparation;
- public `reset/tools/invoke/close`, schemas and structured observations;
- qualified CapabilitySpecs, Conditions and CompositionRules;
- deterministic StartCases and binding enumeration;
- protected read-only facts and atomic outcome/answer/process evaluation.

S2 may request a narrowly demonstrated S1 correction when a candidate lacks a
public operand, replayable Start or reliable truth route. It must not demand a
universal ontology, State IR, generic snapshot format, Task generator or reward
field from S1.

## Required sampling method

The production sampler is Direct Goal-first enumeration:

```text
qualified Capability
x supported StartCase
x eligible public Binding
x supported Goal/selector/condition shape
-> frozen Candidate Task
```

Current shapes are:

- `Atom`: one qualified capability and one selected binding;
- `ForEach`: a qualified complete public selection;
- `If`: a qualified public condition and its selected capability branch;
- `All`: only when a real S1 CompositionRule licenses the capabilities.

Framework code never contains Git/SQLite/booking branches. Unsupported shapes
produce no candidate rather than fabricated Tasks.

Graph and Programmatic are optional experiments only. They may be proposed
after measured Direct coverage is insufficient, run under matched budgets and
be removed when they add no useful non-redundant admitted Tasks.

## Good Task admission

### Intrinsic hard gates

Every admitted TaskPack must be:

1. **Publicly solvable** — at least two fresh real executions of the exact final
   instruction succeed using public information and tools only.
2. **Reliably verifiable** — deterministic checks reject applicable no-op,
   wrong-target, partial, collateral and wrong/stale-answer cases while allowing
   another valid path when one is known.
3. **Well-posed** — all load-bearing constraints are public and unambiguous,
   without leaking a tool recipe, protected field or answer key.
4. **Non-trivial** — mutation/process Tasks fail at Start/no-op; query answers
   must be grounded in real public observations.
5. **Replayable and isolated** — Start and logical binding reconstruct across
   fresh instances; dynamic IDs are rediscovered; episodes do not share state.
6. **Purposeful** — one coherent Need/workflow-anchored objective without
   arbitrary tool stitching or decorative witness calls.

Witnesses prove that a solution exists; they never define the only accepted
trajectory. Verification evaluates the frozen goal, state, collateral effects,
process constraints and structured answer.

### Corpus-level quality

Task validity and corpus selection are separate. Corpus selection reports:

- unique semantic/execution structures;
- capability, Goal, Start and condition distribution;
- redundancy and parameter-only variants;
- model-relative success, failure attribution, calls, tokens, latency and cost;
- declared training purpose and sampling budget.

Task count or distribution targets never waive an intrinsic hard gate.

## Required causal order

```text
1. cold-prepare exact Release
2. enumerate Direct candidates
3. compute structure identity and deduplicate/select
4. freeze checker and final instruction
5. solve exact instruction on two fresh instances
6. close/reopen when persistence is claimed
7. execute applicable physical challenges
8. seal TaskPack
9. run fresh model-relative TaskAssessment
10. select CorpusManifest
```

Task correction restarts from candidate compilation. Checker correction reruns
all applicable challenges. Assessment never changes Task truth.

## S2 to S3 handoff

S2 publishes strict current-format TaskPacks. The S3 host receives the exact
Release/Task/Start/checker identities. The acting policy receives only:

```text
canonical instruction
fresh public reset observation
ToolSpecs
ToolObservations
final-answer schema
```

It never receives protected bindings, semantic keys, expected branch, checker,
witness trace or answer key.

## Acceptance criteria

- Direct production API compiles, structurally deduplicates, admits and persists
  TaskPacks plus typed rejected candidates.
- Candidate structure identity ignores paraphrase/entity swaps but preserves
  genuine Goal/condition/selector/answer differences.
- Exact final instructions succeed twice on fresh public-only runs.
- Acting-time argument provenance closes over instruction/reset/schema/prior
  observations without protected values.
- Applicable physical challenges and declared reload evidence pass.
- Current TaskPacks cold-read after relocation into a non-leaking PublicTaskView.
- TaskAssessment/CorpusManifest remain identity-separated from Task truth.
- Git, SQLite and one post-freeze held-out release use the same Framework.
- Fixed-budget reports show attempts, accepted unique structures, rejection
  owners, redundancy, distribution and cost.
- Deterministic tests, mutation licenses, Ruff, format, Mypy, lock and diff
  checks pass; real execution artifacts are retained outside source authority.

## Forbidden

- mandatory Graph or Programmatic product stages;
- TaskIntent/WitnessSet, dual readers, compatibility switches or v1 ABI;
- a universal Task/State/Rule ontology or unrestricted per-Task verifier code;
- native writes, hidden setup calls or protected acting operands;
- witness-trace equality as Task truth;
- fake result mutation, manufactured success or domain-specific Framework code;
- claiming corpus quality from count, text variety or tool length alone;
- implementing S3 scalar reward or S4 training inside S2.
