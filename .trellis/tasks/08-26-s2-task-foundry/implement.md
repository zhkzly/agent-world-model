# S2 Goal-First Task Foundry — Implementation Plan

## 1. Execution rules

- Implement vertical evidence paths, not speculative schemas.
- Framework owns deterministic mechanics; generated code owns domain semantics.
- Fix the first incorrect owner and delete downstream compensating checks.
- No v1 compatibility, fallback, dual reader, or feature flag.
- A green unit suite is necessary but never substitutes for real execution.

## 2. Checkpoint A — Simplified contracts

### Work

- Keep exact public AnswerField source kinds and full ToolObservation pointers.
- Remove `reportable_field_ids` and singleton report profiles.
- Allow condition branches to use their own necessary answer schemas.
- Reduce Native Auditor result to required effects, collateral, and diagnostics.
- Remove final answer from the Native Auditor request.

### Validation

- old `tool_output` is rejected;
- source pointers resolve against sealed schemas;
- public surface is visible to the Expected Semantics turn;
- Native Auditor cannot emit public report/process/answer authority;
- branch-specific answer contracts freeze successfully.

## 3. Checkpoint B — S1 positive qualification

### Work

- Run one representative positive public episode per capability.
- Compare TaskSemantics and Native Auditor only on effects/collateral.
- Match every reported AnswerField to a real public source occurrence.
- Seal only positive capability evidence and requirement coverage.
- Remove S1 Task-level negatives, replay matrix, result mutation records, and
  full cold historical replay.

### Validation

- every capability has one positive case;
- a source/report mismatch rejects Qualification;
- a native effects/collateral disagreement rejects Qualification;
- an answer/process disagreement is owned only by TaskSemantics/Host;
- environments without state changes, multi-binding queries, or disjoint
  workflows remain valid when their Need permits them.

### Real vertical

Fresh-author and publish the filesystem/Git release, then relocate it and open
one Consumer session. Repeat later with SQLite using unchanged Framework code.

## 4. Checkpoint C — Minimal Task admission

### Atom

- compile one full answer schema per capability/binding;
- freeze checker before instruction;
- run two fresh public witnesses;
- execute no-op, applicable wrong-target, and constructible wrong-answer;
- seal AtomTaskPack.

### ForEach

- freeze complete eligible selection;
- run two fresh witnesses;
- run no-op and one representative omitted-member challenge;
- seal ForEachTaskPack.

### If

- freeze qualified condition and selected branch;
- preserve the selected branch answer schema;
- run two fresh witnesses confirming condition and selected branch;
- reuse the admitted Atom branch TaskPack.

### All

- require an explicit CompositionRule;
- run two witnesses, no-op, and one representative missing child.

### Validation

- no protected checker/native/verifier data reaches the public Agent;
- fresh materializations resolve the same logical Task;
- exact final answers match public occurrences;
- applicable minimal negatives fail for their intended reason;
- no mandatory alternative route, reverse order, collateral manufacture,
  AgentChoice perturbation, or result-object mutation remains.

## 5. Checkpoint D — Assessment and paper experiments

### Work

- assess admitted TaskPacks with an independent acting policy;
- select a CorpusManifest without changing Task truth;
- run Git, SQLite, and a post-freeze held-out Need;
- report yield, Goal distribution, success rate, cost, and downstream SFT/RL utility;
- optionally run robustness experiments over sampled Tasks.

### Important boundary

Targets such as corpus size, Goal diversity, multiple StartCases, alternative
routes, mutations, or perturbations are reported experiment outcomes. They are
not EnvironmentRelease or individual TaskPack admission gates.

## 6. Validation commands

```bash
UV_CACHE_DIR=/tmp/foundry-s2-uv-cache uv lock --check
.venv/bin/ruff check src tests
.venv/bin/ruff format --check src tests
.venv/bin/mypy src
.venv/bin/python -m pytest -q
git diff --check
```

New deterministic enforcement requires RED/GREEN and mutation-licensed tests.
Real provider/process claims require retained run artifacts.

## 7. Rollback ownership

```text
Need/Research
Environment Builder
Expected Semantics
TaskSemantics Author
Native Auditor Author
Qualification Framework
Publication/preparation
Task compiler
public runner
Task checker/admission
assessment/corpus
Infrastructure
```

Rollback the first incorrect owner. Do not widen a later validator to absorb an
upstream semantic defect.

## 8. Completion

This task completes only after:

- simplified deterministic gates are green;
- a fresh Git release passes real positive Qualification and cold use;
- Atom, ForEach, and If TaskPacks pass minimal admission across the real releases;
- no environment is required to manufacture a Goal kind absent from its qualified semantics;
- SQLite repeats with unchanged Framework code;
- held-out and downstream experiments are reported separately.
