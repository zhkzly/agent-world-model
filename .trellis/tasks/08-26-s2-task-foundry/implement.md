# S2 Good-Task Sampling Foundry — Implementation Plan

## 1. Execution rules

- This plan is documentation-only until the user reviews it.
- Implement one vertical claim at a time; do not restore old branches wholesale.
- Framework owns deterministic contracts, identity, execution and verdicts.
- Models may propose Tasks/programs and solve public Tasks; they never define
  truth, reward or admission.
- Every new enforcement starts RED on a real or real-derived artifact, kills an
  injected mutant, then turns GREEN.
- A green unit suite never substitutes for a real release, process, state
  transition, reload, challenge or public Agent execution.
- No subagent/reviewer is started unless the user explicitly requests it.

## 2. Baseline and rollback point

Start from commit `189be1b`.

Retain its verified physical foundations and treat its TaskPacks as diagnostic
checkpoints. They are not Good Task gold data. In particular, retain the real
SQLite counterexample:

```text
instruction claims close/reopen persistence
witness performs same-process reads only
checker accepts
```

The first new acceptance must reject that exact artifact. Do not edit the old
artifact to make the test pass.

## 3. Checkpoint A — Strict TaskPack handoff and physical reload

### Product claim

S2 can cold-read one exact current TaskPack, expose a non-leaking PublicTaskView
and physically verify persistence across process close/reopen.

### Work

- add exact Atom/ForEach/If TaskPack decoders with no legacy fallback;
- recompute Task, admission and pack identities from canonical bytes;
- define one minimal PublicTaskView: instruction and final-answer schema;
- keep StartRecipe/checker/semantic keys/expected branches trusted-only;
- extract one reusable single-attempt lifecycle:

```text
open -> reset -> public episode -> close
-> reopen same instance -> trusted inspect/evaluate -> close
```

- use that lifecycle for admission and assessment rather than duplicating it.

### RED acceptance

- the current SQLite “reopen” TaskPack is rejected because no reopen evidence is
  bound;
- tampered Task/pack IDs fail cold read;
- PublicTaskView contains no semantic key, expected branch, checker, witness,
  Start reset input or protected binding;
- after-state collected before reopen cannot satisfy a declared reload claim.

### Real exit

Regenerate one SQLite state-change Task. Two witnesses must show different
materialization IDs and explicit close/reopen evidence over the same per-witness
native instance. Git query Tasks must remain valid without domain branches.

### Expected files

`task_foundry.py`, `foreach_foundry.py`, `if_foundry.py`, a small TaskPack reader
module if needed, `assessment.py`, and focused tests. Do not add a service or
Registry.

## 4. Checkpoint B — TaskSpecification, coverage and V0

### Product claim

Task meaning freezes before witness search and covers every applicable declared
Requirement obligation in both directions.

### Work

- introduce one bounded TaskSpecification document;
- freeze its parameterized semantic section from qualified
  Requirements/Capabilities and a Candidate proposal;
- after Start, append only concrete public-provenance values to its binding
  section without changing semantic fields;
- record predicate-to-anchor and obligation-to-predicate/irrelevance mappings;
- deterministically enumerate stable obligation IDs from every declared
  precondition/outcome/refusal/collateral item and require complete accounting;
- require an executable public applicability predicate for every irrelevance
  disposition; free-text rationale cannot remove an obligation;
- fail closed on unanchored predicates, omitted obligations or unjustified
  irrelevance;
- compile V0 as an evaluation plan over existing qualified TaskSemantics, not
  arbitrary per-Task Python;
- audit the bound instruction for public constraint/operand closure, hidden
  predicate leakage, answer leakage and solver-route leakage; a fresh
  public-view critic may reject ambiguity/purposefulness but cannot authorize a
  deterministic failure;
- make the current direct Capability compiler emit proposals into this path.

### RED acceptance

Use a real-derived cancellation-style fixture with three obligations:

```text
cancel reservation
restore capacity
issue refund
```

A candidate/checker that encodes only the first two must be rejected even when
its witness and existing predicates pass. Also reject a checker predicate with
no public anchor, an instruction that omits one load-bearing frozen constraint,
and an instruction that exposes a dynamic answer or prescribed reference route.

### Real exit

Compile one Git and one SQLite Task through direct proposal -> specification ->
V0 -> freeze. The frozen digest must be identical across recompilation and must
not depend on witness bytes.

### Anti-overdesign

Do not create a world ontology, Rule IR, generic expression language or fourth
Codex-authored verifier project. Add only fields exercised by the two real
Tasks and the omitted-obligation counterexample.

## 5. Checkpoint C — Graph sampler

### Product claim

Graph sampling proposes Need-anchored Tasks from real public value-flow and
state-enablement evidence rather than LLM-imagined tool edges.

### Work

- use disposable reset instances and the existing public tool runner;
- retain executed nodes, observations and public argument provenance;
- create edges only after the later call actually executes with values derived
  from earlier public observations/schema constants;
- admit value-flow edges only with exact observation-pointer to argument-pointer
  provenance;
- admit state-enablement edges only when the same later tool/arguments fails
  before and succeeds after the earlier action on equivalent fresh starts, with
  the enabling effect confirmed by qualified TaskSemantics;
- sample bounded paths/subgraphs under a fixed calls/tokens/time budget;
- map each proposal to accepted Requirement anchors;
- discard the graph after proposal/evidence persistence.

### RED acceptance

- an LLM-only edge with no executed later call cannot propose a Task;
- a later argument copied from protected/native state is rejected;
- two unrelated successful tools cannot be stitched without one coherent
  Requirement objective;
- a successful executed path with an omitted Requirement obligation still fails
  Checkpoint B.

### Real exit

Produce proposals on both Git and SQLite, including one multi-step value-flow or
state-enablement candidate where the release supports it. Report zero-yield
honestly when it does not.

### Non-goals

No persistent graph package, learned universal dependency model, GraphTask ABI
or claim of exhaustive tool-space coverage.

## 6. Checkpoint D — Programmatic sampler

### Product claim

A public-only bounded solution program can propose different grounded Task
structures, while its successful route remains constructive evidence rather
than the only accepted solution.

### Work

- give the planner only Requirement/public schemas/reset observations;
- return a bounded run-local JSON program containing only call, public-pointer
  if, bounded public-array for_each and finish operations;
- execute on a disposable instance and provide complete factual repair feedback
  only for public execution/shape failures;
- fresh replay the repaired program;
- convert Requirement + executed evidence into the common proposal;
- discard source program from acting-time PublicTaskView.

### RED acceptance

- hidden literal/native ID use fails provenance;
- a program that executes but solves another Requirement is rejected;
- a program whose successful answer cannot be recomputed from public evidence is
  rejected;
- verifier output is never returned as planner guidance;
- alternate public execution satisfying the same frozen Task is accepted.

### Real exit

Run one real Git and SQLite Programmatic proposal under the same published
budget as Graph. Record attempts, repair turns, executions, yield and failure
ownership.

### Non-goals

No ProgrammaticTask product type, arbitrary Python from untrusted data or
solution-program equality checker.

## 7. Checkpoint E — Applicability-planned Good Task challenges

### Product claim

Every admitted Task rejects constructible close counterexamples without running
an exhaustive or decorative challenge matrix.

### Work

- derive and freeze challenge applicability before witness search;
- implement physical initial/no-op, wrong entity, wrong/stale answer,
  partial/omitted obligation, near-miss, collateral and process/reload cases;
- prune retained constructive witness evidence to calls that support a public
  operand, branch, required effect or declared process milestone, without making
  trace minimality an acceptance rule for future acting policies;
- compare qualified TaskSemantics truth across fresh/reloaded instances;
- execute a distinct valid route when one is actually found;
- record deterministic non-applicability reasons;
- restart TaskSpecification on semantic correction and V0 on verifier correction.

### RED acceptance

Each applicable category must have one real-derived mutant that the unmodified
checker would accept and the strengthened admission rejects. Mutating result
booleans or hand-writing an impossible native state is not physical evidence.

### Real exit

Seal at least one query, state-change/refusal, collection and condition/composed
Task across the conformance releases when their semantics support those shapes.
No environment is forced to manufacture an unsupported Goal.

### Anti-overdesign

Do not test every member, order, parameter or route. One discriminating physical
case per applicable semantic failure class is the production gate; broader
sampling belongs to robustness experiments.

## 8. Checkpoint F — Unified TaskPack and sampler batch

### Product claim

All samplers feed one identity/admission path and a fixed-budget batch reports
honest yield and rejection causes.

### Work

- seal TaskSpecification, StartRecipe, V0 and AdmissionEvidence into one current
  TaskPackManifest;
- remove any current in-memory-only identity assumption;
- run direct, Graph and Programmatic proposals under declared budgets;
- deduplicate by semantic/execution structure, not text or entity ID;
- persist accepted packs and typed rejected-proposal/admission records;
- never stop merely because three structures were admitted unless that is an
  explicitly labelled smoke run.

### RED acceptance

- same semantics with paraphrase/entity swap deduplicates structurally;
- different objective/quantifier/constraint/information dependency remains
  distinct;
- sampler lineage changes evidence identity but not Task truth;
- batch target cannot override Good Task failure.

### Real exit

Run complete fixed-budget batches on Git and SQLite and report proposal count,
execution count, TaskPack yield, unique structures, rejection classes and cost.

## 9. Checkpoint G — Difficulty and CorpusManifest

### Product claim

Corpus selection produces a declared training distribution rather than a list
of easy duplicates.

### Work

- run at least two policy lineages/checkpoints with repeated fresh trials;
- preserve complete success/failure attribution and cost;
- classify difficulty from empirical success and failure patterns, not tool
  count;
- select by Goal/capability/state/constraint/information dependency and declared
  SFT/RL purpose;
- report redundancy, easy/intermediate/hard/defect-suspect partitions;
- keep assessment/corpus identity outside TaskPack truth.

### RED acceptance

- one policy at 100% cannot establish discrimination;
- Task/Verifier/Environment/Infrastructure failures cannot be labelled “hard”;
- parameter/paraphrase variants cannot satisfy structure diversity alone;
- a corpus threshold cannot retroactively invalidate or validate a TaskPack.

### Real exit

Generate a conformance CorpusManifest with exact TaskPack/Assessment pairs and
publish all selection evidence. Do not claim learning value yet.

## 10. Checkpoint H — Held-out transfer and S3-shaped handoff

### Product claim

The frozen S2 Framework transfers without domain edits and its output is
consumable by a future Agentic RL episode runner.

### Work

- freeze Framework code, prompts, sampler budgets and acceptance rules;
- select one held-out Need afterward;
- run S1 publication and the complete S2 pipeline;
- cold-read TaskPack/Corpus from relocated bytes;
- exercise PublicTaskView through the public tool loop;
- serialize a neutral OpenAI-style message trace as a compatibility probe only.

### RED acceptance

- selecting or tuning the held-out Need before Framework/prompt/budget freeze is
  rejected as contaminated evidence;
- a TaskPack that cannot cold-read after relocation fails before acting;
- PublicTaskView or the neutral trace containing semantic keys, expected branch,
  checker/witness/protected facts is rejected;
- held-out execution requiring a Framework domain branch or weaker Good Task
  gate fails transfer rather than being patched locally;
- S3-only reward, logprob or training fields appearing in S2 output are rejected.

### S2 boundary

The probe may demonstrate:

```text
system/user/tool schemas
assistant tool calls
tool observations
assistant final answer
verified Task facts
```

S2 does not implement rollout logprobs, response masks, token rewards,
advantages, reward mapping or training. Those become the S3/S4 plan after S2
completion.

### Real exit

Held-out execution must produce valid TaskPacks or typed justified low yield,
with no domain branch or weakened gate. Report the same metrics as conformance
runs.

## 11. Required validation at every checkpoint

```bash
UV_CACHE_DIR=/tmp/foundry-s2-uv-cache uv lock --check
.venv/bin/ruff check src tests
.venv/bin/ruff format --check src tests
.venv/bin/mypy src
.venv/bin/python -m pytest -q
git diff --check
```

Additionally:

- run focused RED/GREEN tests and one mutation license for each independent
  binding/enforcement edge;
- retain real run IDs, TaskPack IDs, process/state before-after facts and typed
  failures;
- grep for deleted legacy symbols and domain branches;
- report source/test LOC added/deleted at each checkpoint;
- main session performs the alignment/overdesign review unless the user
  explicitly requests another reviewer.

## 12. Completion

S2 completes only when Checkpoints A–H satisfy their real exits. A checkpoint
may be committed independently. Failure at a later checkpoint does not justify
restoring legacy ABI, adding compatibility, weakening an earlier Good Task gate
or claiming S3 has begun.
