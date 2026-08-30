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

## S1 noop Qualification correction and refreshed releases

S1 Qualification now seals one deterministic physical `noop` and one real
positive case per capability. TaskSemantics and the mutually blind Native
Verifier must agree on required-effect/collateral axes; unchanged state must
keep collateral true even when the required effect is absent. Failed public
positive episodes are attributed before AnswerField source evidence, so policy
failure is not misreported as generated-code corruption.

The old evidence/2 releases are fail-closed and no compatibility reader exists.
Fresh releases are:

- SQLite release
  `64fa07e1a144536df2ae3ff9b0cf30175e8b0f913f1e34d8731b8377a80ebb87`:
  4 noop + 4 positive cases, receipt
  `46619aaad44ed5e09b1dc620738b5363b4f1c7fae0458a7fa6cbfb6731936292`;
- Git release
  `14331ac6e82e0ac79382d5c5e964c62f6cc9ece506f726299d0645594fbafe80`:
  6 noop + 6 positive cases, receipt
  `a2db5637233f1825bd806d3824f100e42ac3476f0a00d6ac05f5fc280950b9ac`.

The SQLite Semantics Author and Git Native Verifier remained role-separated.
The former fixed axis independence; the latter learned to resolve a noop target
from the public descriptor when trace is intentionally empty. Framework owned
both verdicts.

Unchanged S2 gates then produced:

- Git run
  `f30da63ad2774cb34553e85cf95e6f0bd5c11227a25eec84dce63eed1a61aef3`:
  20 candidates, 16 structures, 3 admitted, 2 recorded witness failures;
- SQLite run
  `f7ef8e02885b0e4961c65edab3e27742d7e45fed31641c933bc04418939dc2b0`:
  12 candidates, 8 structures, Atom + ForEach + If admitted, one separately
  admitted `CAP-SUBMIT-DISPUTE` branch dependency, and 2 recorded If failures.

This closes the upstream mutation/condition blocker. Checkpoint 3 remains open
only for the final admission audit: freeze an explicit collateral
applicable/non-applicable disposition and independently challenge a complete
ForEach wrong answer where constructible. No CompositionRule exists in either
release, so All remains honestly unsupported rather than fabricated.

## Good-Task admission closure

Atom AdmissionPlan now freezes whether a same-Start state-changing wrong target
can physically challenge collateral. It reuses the existing wrong-target
episode, adding no provider call. A real SQLite query Task rejected the
successful dispute mutation as `PROHIBITED_COLLATERAL` after reopen; run
`d637ff580bb9e1738f25a2f9e385f1e8b722d7428ee3ed86a07ac8da57f82821`.

ForEach AdmissionPlan now freezes a public wrong target (preferring a real
state change) plus one deterministic member-level schema-valid wrong answer.
Nested objects/arrays are mutated recursively at one valid leaf; the complete
answer remains schema-valid. Real run
`d1705505b106bbba1d9a6dbf509eb5cfe4b708a29274237aaf5950798784e9dc`
admitted Atom and ForEach with no rejection. Its ForEach TaskPack proves:

- all three members reject the unrelated state change on collateral;
- the wrong-answer control satisfies all three members;
- changing only member 0's nested amount makes only its answer axis fail;
- partial, wrong-target and wrong-answer each carry distinct post-reopen
  evidence.

Focused collateral, wrong-answer and recursive-answer mutants were killed; all
deterministic gates passed. Checkpoint 3 is closed. Both qualified releases
declare zero CompositionRules, so Checkpoint 4 is closed as typed unsupported;
no All compiler or fabricated composition was added.
