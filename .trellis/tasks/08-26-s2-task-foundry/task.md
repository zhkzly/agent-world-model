# S2 Clean-Break Execution Contract

## Initial Contract (frozen)

Goal: implement one v2-only Need → executable environment → qualified release → verified TaskPack pipeline.
Invariant 1: production code accepts and emits EnvironmentRelease v2 only; no legacy parser, adapter, reader, publisher, or fallback survives.
Invariant 2: Framework owns identities/execution/verdicts; generated code never self-authorizes.
Invariant 3: semantic completion requires real state transitions and physical evidence, never mocks or green tests alone.
Not doing: do not implement S3 reward or training inside S2.
Gold reference: contrasting real Git and SQLite releases plus a held-out Need.

## Current product authority

User correction: S2's purpose is to sample Good Tasks. The current required
method is Direct Goal-first candidate enumeration followed by physical
admission, TaskPack persistence, assessment and corpus selection.

Graph and Programmatic are optional experiments only after a measured Direct
coverage gap. The later mandatory-sampler and parallel
RequirementObligation/TaskSpecification/V0 plan was unauthorized drift and has
been deleted from active authority/code.

## Retained implementation baseline

Commit `189be1b` remains the Direct execution baseline:

- only v2 release paths are supported;
- S1 source authority and positive capability Qualification are implemented;
- Native Auditor checks native effects/collateral without duplicating S2 Task
  challenges;
- Atom/ForEach/If Direct compilation and minimal physical admission exist;
- production batch, TaskAssessment and CorpusManifest identities are separate;
- fake result mutation and compatibility machinery remain deleted.

## Physical reload correction

The shared Host lifecycle is retained:

```text
open acting session -> reset once -> public episode -> inspect -> close
-> reopen the same native instance in a distinct session without reset
-> inspect -> trusted checker -> close
```

`ReloadEvidence/1` binds Release, Task, attempt, native instance, distinct
sessions, ordered lifecycle events, fact digests and post-reopen checker result.
Atom/ForEach/If witnesses and TaskAssessment use this path. Challenge migration
remains subject to the Direct admission audit.

Deterministic evidence at the retained checkpoint:

- full tests, Ruff, formatting, Mypy, lock and diff checks passed;
- same-session reuse, lifecycle reordering/second reset, another native instance
  and missing post-reopen checker were rejected;
- focused mutants for lifecycle and witness bindings were killed;
- real SQLite mutation, Git query and SQLite ForEach/If attempts passed after
  physical reopen; one public-policy failure remained honestly recorded.

## Current authority restoration

Smallest observed gap: active documents and three later commits promoted
optional Graph/Programmatic mechanisms and an isolated semantic-contract path,
while the actual production API continued to run Direct Atom/ForEach/If.

Selected correction:

- retain Direct batch/assessment/corpus and physical reload/provenance;
- delete the isolated B1-B3 modules/tests/spec;
- rewrite PROJECT, parent/S2 task documents, checklist, DECISIONS and JSONL
  context around the one actual Direct path;
- make optional sampler experiments conditional on measured coverage and
  matched-budget incremental value;
- prove old B symbols and mandatory-sampler authority are absent.

Rejected alternatives:

- keeping the parallel path as future-proofing;
- feature flags or adapters between paths;
- archiving invalid active documents inside the branch;
- continuing to Graph before Direct batch/cold-product closure.

Evidence that reverses optional-sampler status: a future preregistered
matched-budget experiment demonstrating additional non-redundant admitted Good
Tasks at acceptable truth error and cost. That authorizes an experiment, not a
new source of Task truth.

## Current implementation order

1. Restore active authority and one Direct production path.
2. Audit structural fingerprint/dedup and batch persistence.
3. Close intrinsic Good-Task physical admission on the Direct path.
4. Implement All only after a real qualified CompositionRule exists.
5. Audit TaskAssessment and CorpusManifest over admitted TaskPacks.
6. Freeze and run cross-environment/held-out S3-shaped handoff.

## Generated evidence boundary

Run artifacts under `.artifacts/` and `/tmp` are non-authoritative generated
evidence. Source documents and product claims cite exact IDs only after the
corresponding command has completed successfully. Git history is the archive
for deleted experimental plans/code.

## Authority-restoration execution evidence

After deleting the parallel B1-B3 path, the current Direct production entry was
cold-executed without compatibility or domain changes:

- Git batch run
  `591f330b7838c353e5c1bf7a3cd0278a85b1d5d78580130e4ff6dc730a395f5d`:
  20 candidates, 16 structures, 1 admitted TaskPack, 0 rejected attempts;
- SQLite batch run
  `1469aba810189de0833920869c32192f39e13c8de1bb7ecf541a46cbfca161b2`:
  12 candidates, 8 structures, 1 admitted TaskPack, 0 rejected attempts.

The target of one structure was a cutover regression only and is not an S2
scale/completion claim. Full deterministic validation remained GREEN after the
deletion. The next product audit is structural dedup/batch evidence followed by
remaining Direct Good-Task admission and strict cold TaskPack/PublicTaskView.

## Structural batch checkpoint evidence

The Direct structure audit compiled both exact releases without an acting
policy: Git produced 20 candidates in 16 structures and SQLite produced 12
candidates in 8 structures. Concrete entity substitutions grouped together;
Goal kind, Start regime, If condition/branch, ForEach cardinality and answer
contract remained distinct.

TaskPack persistence now validates the in-memory preimage before admission,
writes canonical bytes and immediately cold-reads/recomputes the identity. The
assessment path reuses the same verifier. A focused identity-bypass mutant was
killed.

Fresh fixed-budget production batches after that change:

- Git run
  `69d66e7235c36c7535bb97aa909e682dd6f560f1f854ce12bf3b536fd9c741a2`:
  20 candidates, 16 structures, 3 admitted (Atom, ForEach, ForEach), 2 recorded
  `public_witness_failed` attempts;
- SQLite run
  `dc71c2d7ed93a539604092f95bfa89037a4459d389ffb5a083e711c3fc1648fa`:
  12 candidates, 8 structures, 3 admitted (Atom, ForEach, Atom), 3 recorded
  failures (`public_witness_failed` and two `challenge_baseline_failed`).

Checkpoint 2 is closed. These runs prove honest structure grouping, attempt
retention and cold TaskPack identity; they do not by themselves close all
Good-Task challenge classes or S2 completion.

## Good-Task admission reload and axis evidence

Action-bearing negatives now reuse the same physical lifecycle as positive
witnesses. Atom wrong-target/wrong-answer and ForEach partial challenges close
the actor, reopen the same native instance in a distinct session, evaluate
post-reopen facts and seal `ReloadEvidence`. Non-applicable wrong-answer no
longer spends an unnecessary model call. Current clean-break pack formats are
Atom v3, ForEach v2 and If v2; no old reader was added.

Two focused reload-evidence mutants and two no-op/collateral-axis mutants were
killed. Fresh physical runs after the lifecycle change succeeded on both
releases. The subsequent stricter axis run produced:

- Git run
  `707fad6476d4daf62049c9936d1270bc4907331049ad9bf9ff844f9227a1b0eb`:
  20 candidates, 16 structures, 3 admitted (Atom, ForEach, ForEach), 2 honest
  `public_witness_failed` records;
- SQLite run
  `5bbb5ec08542a5c420271664189e124d973b2fd40e02f5707aa46820051d8b52`:
  12 candidates, 8 structures, 3 admitted (Atom, ForEach, Atom), and one If
  rejected as `admission_plan_noop_axis_invalid`.

The rejected If exposed an upstream S1 TaskSemantics defect: for
`CAP-SUBMIT-DISPUTE`, identical before/after facts returned
`collateral_ok=false` and `PROHIBITED_COLLATERAL`. S2 now rejects this instead
of treating aggregate `satisfied=false` as sufficient negative evidence.
Checkpoint 3 therefore remains open until S1 Qualification rejects such
axis-conflated semantics, a corrected SQLite release is published, and real
mutation/condition TaskPacks pass the unchanged S2 gates.
