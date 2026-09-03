# S2 Good Task Sampler — Implementation Plan

## 1. Execution contract

- Create `s2-good-task-sampler` from the current
  `s1-s2-authority-realignment` head. Bring only this approved task; do not
  merge the legacy `s2-task-foundry` implementation history.
- The frozen 20/20 `EnvironmentRelease/3` campaign is immutable input.
- Reuse the real Responses function-tool loop. The Sampling Agent performs
  environment-specific semantic exploration; Framework owns execution,
  evidence, Goal materialization, replay, evaluation and identity.
- No Tool Graph, random walk, S1 diagnostic-to-Task extraction, generated
  Checker, TaskSemantics project, solution/verifier program or per-Task pressure
  suite.
- One common evaluator handles every release and Goal. No compatibility reader,
  feature flag or dual S2 product path.
- Product code must remain domain-free and materially smaller than the removed
  Checker/TaskSemantics stack.

Gold inputs:

```text
S1 campaign 486dd2349f1eccb2f2ee096447a7c2325e811ecd92b6189722a69ed49a09ad7d
20 verified Release IDs / 206 ToolSpecs
Direct/checker baseline campaign 91ffc87386c7109fb9a736a41c8dc7320844d63293b60eba419b623518896273
planning live probes: Git release and laboratory chain-of-custody
```

Before product code, update `PROJECT.md` on the new branch to the approved
execution-first/no-Graph/no-Checker S2 authority. Do not modify S1 or S3.

## 2. Checkpoint A — TaskDraft, Goal data and common evaluator

### Claim

Actual public steps can be selected as Atom/All/If/ForEach data and checked by
one domain-free evaluator without executable Task-specific code.

### Work

- add compact required `SamplingTarget`, public source references,
  `AnswerProjection` and `TaskDraft`;
- add canonical Atom/All/If/ForEach Goal records and exact identity;
- implement one evaluator over Goal, trace, answer, provenance and protected
  before/after state;
- fail closed on unresolved, ambiguous or incomplete Goal components;
- let Framework derive the type-only answer transport schema from referenced
  public source schemas; the Agent cannot author it;
- support unique public target selection, scalar prior If conditions and
  member-key-complete ForEach sets; do not add an arbitrary predicate DSL.

### RED/exit evidence

- real-derived inventory, Git and laboratory records decode and evaluate;
- no-op, wrong answer, outside state change, missing All child, wrong If branch
  and missing/duplicate/extra ForEach member fail through the same API;
- ambiguous “choose any” selection fails while a unique public selector passes;
- a free version/ID/message not frozen in the instruction fails;
- an Agent-authored answer schema has no product input path;
- a collection-valued If condition and incomplete/duplicate ForEach member
  mapping fail;
- evaluator mutants are killed;
- no domain/tool/environment identifier occurs in evaluator branches.

### Rollback point

The new contracts/evaluator stay unreachable until Checkpoint C. Deleting the
checkpoint commit restores the exact base without changing S1.

## 3. Checkpoint B — Execution-first Sampling Agent

### Claim

The existing generic public tool-loop can produce a TaskDraft only after
physically completing a coherent objective in an arbitrary Release.

### Work

- replace the proposal terminal schema with TaskDraft/unsupported output;
- pass one simple SamplingTarget: required shape, focus tools/outcome and
  prior structure summaries;
- retain the current Host-owned public dispatch, schema validation, full trace,
  provider usage and protected before/after capture;
- require every focus tool to participate in the objective and require
  objective/AnswerProjection references to resolve to real events;
- reject a non-empty trace with no completed objective;
- keep exploratory calls as evidence but not automatic Goal requirements;
- batch all deterministic draft findings into actionable feedback only for
  malformed output; a semantically failed attempt is not repaired in place.

### RED/exit evidence

- a trace containing only a successful list/inspect call cannot create a
  Candidate by itself;
- inventory, support, Git and laboratory live probes produce ForEach, If, All
  and Atom TaskDrafts through the same code and prompt;
- a weak/failed model reduces yield but cannot create false evidence;
- hidden operands, nonexistent step IDs, ungrounded answer projections and
  off-target Goal/tool/outcome drafts fail;
- no Tool Graph or release-specific branch exists;
- prompt/TaskDraft mutants are killed.

## 4. Checkpoint C — Host Goal freeze, replay and Checker deletion

### Claim

One accepted TaskDraft becomes a Candidate only after Host materialization and
a passing fresh reference replay; the generated-Checker path is absent.

### Work

- resolve public operand/condition/member provenance;
- resolve expected answer from AnswerProjection, derive its type-only schema,
  and capture protected state effects from the actual run;
- enforce unique target or complete-set selection, initial non-satisfaction,
  instruction non-leakage and coherent objective closure;
- replay the retained public solution on a fresh instance and call the common
  evaluator;
- create Candidate/structure identity from Goal/effect/answer structure;
- atomically delete checker fields, author, runner, runtime skill, project
  packaging/runtime and checker-only tests;
- leave no old TaskPack reader or adapter.

### RED/exit evidence

- replay instability, unresolved provenance, extra state effects and Goal/
  answer contradictions prevent Candidate creation;
- a valid alternate public route can pass without witness-trace equality;
- `rg` reports zero production references to `checker_brief`, checker
  author/factory/project/wheel or TaskSemantics;
- old checker TaskPack fails closed;
- one real Candidate from Git and one from laboratory cold-decode;
- the four planning canaries reproduce their reference state/answer without a
  generated answer schema;
- materialization/replay mutants are killed.

### Rollback point

Commit A/B before this atomic cutover. If cutover checks fail, revert only this
commit; do not add compatibility or a feature flag.

## 5. Checkpoint D — Five-run filtering and TaskPack

### Claim

Every admitted Task has constructive sampling evidence and is independently
recoverable from its final public presentation.

### Work

- run exactly five valid independent public policy attempts on fresh instances;
- select serial/concurrent execution through a route-specific provider limit;
  default local 8317 execution to one until a concurrency probe passes;
- evaluate each run through the common evaluator and retain all outcomes;
- retry Infrastructure failures separately; never count them as policy runs;
- require at least two passes and all five valid outcomes;
- never repair/reword a frozen Candidate in place;
- seal/cold-read TaskPack with Candidate, sampling evidence, five run records,
  threshold result and structure ID;
- expose a non-leaking PublicTaskView and separate trusted Goal projection;
- do not modify or claim compatibility with existing checker-bound S3.

### RED/exit evidence

- 1/5 rejects and 2/5 admits;
- fewer than five valid semantic outcomes never admits;
- provider concurrency failure abstains and can retry serially without becoming
  a policy failure;
- instances and model histories are independent;
- identity drift and public-view leakage fail closed;
- relocated TaskPack cold-read passes;
- filter/pack mutants are killed.

## 6. Checkpoint E — Coverage scheduling and 20-release campaign

### Claim

Simple counters can steer a generic Sampling Agent toward a diverse, measurable
corpus across all 20 Releases without a Graph or domain edits.

### Work

- schedule required underused Goal shapes, focus tools and outcome classes with
  deterministic tie-breaking; an off-target result is rejected, not counted in
  the requested cell;
- send prior accepted structure summaries to discourage semantic repetition;
- deduplicate by Goal/tool/binding/effect/answer structure, not wording/IDs;
- add resumable campaign CLI with seed, per-release attempt budget, model route
  and worker limit;
- write terminal attempt records before deterministic partial/final fan-in;
- freeze code, prompt and config and run the exact 20-release campaign;
- compare honestly with the retained Direct/checker baseline.

### Required report

```text
20 Release terminal coverage
public tools attempted and present in admitted Tasks
Atom/All/If/ForEach attempted, unsupported, sampled and admitted
query/transition/refusal distribution
Candidate, replay and unique-structure counts
five-run vectors and policy success rate
typed rejection and infrastructure counts
wall time, tokens and public tool calls
per-Task cost and removed Checker-generation cost
exact TaskPack/CorpusManifest/campaign IDs
```

### Exit evidence

- all 20 Releases reach terminal campaign records without source changes;
- every accepted Task has a successful sampling execution, passing fresh replay
  and at least two passing independent runs;
- unsupported Goal cells remain reported rather than fabricated;
- resume rebuild and serial/parallel fan-in preserve identities;
- every resume-ready number maps to immutable retained evidence.

## 7. Validation

Run fail-fast from the implementation worktree:

```bash
uv sync --frozen --all-groups
uv run ruff check src tests scripts
uv run ruff format --check src tests scripts
uv run mypy src
uv run pytest -q
git diff --check
```

Focused mutation licences target TaskDraft validation, common evaluation,
Candidate replay, the 2-of-5 threshold and TaskPack cold-read. Real canaries use
the exact frozen releases; fake providers may test protocol control flow only
and never count as Task evidence.

## 8. Completion

This task completes only after Checkpoints A–E and the real 20-release campaign.
It does not complete after contracts, one environment, one TaskPack, green
tests or a partial campaign. S3/S4 remain separate.
