# S2 Good Task Sampler — Technical Design

## 1. Design target

Implement one production path over current `EnvironmentRelease/3`:

```text
coverage target
-> generic execution-first Sampling Agent
-> TaskDraft over actual public steps
-> Host Goal/evidence freeze
-> fresh reference replay + common evaluator
-> 2-of-5 fresh public-Agent filter
-> TaskPack / CorpusManifest / campaign report
```

There is no Tool Graph, random walk, generated Checker, TaskSemantics project,
solution program or verifier program. Corpus selection is a post-admission
batch operation, not a third generation stage.

Implementation starts from `s1-s2-authority-realignment` at the final S1/S2
baseline. Historical commits are source-reading references only; no old module
is cherry-picked wholesale.

## 2. Existing assets and deletion boundary

### Reuse

- `ValidatedReleaseV3` / `prepare_release_v3_internal` and isolated
  `open(...)` / `read_state(...)`;
- Need/Development Brief projection and public ToolSpecs;
- structured `ToolObservation`, schema validation and canonical bytes;
- the current `task_proposal` Responses function-tool loop and physical
  before/after capture;
- `public_agent` execution, capture and provider attribution;
- public argument-provenance and TaskPack identity patterns.

### Replace or delete

- replace the proposal terminal schema with `TaskDraft`; non-empty trace is no
  longer sufficient;
- remove `checker_brief`, checker factory/project/digest/result fields;
- delete `checker_author.py`, `_checker_runner.py`, checker-codegen runtime
  skill, checker packaging/runtime and checker-only tests;
- replace sequential first-N proposal sampling with coverage-target scheduling,
  bounded concurrency and deterministic fan-in;
- replace checker/trace-only identity with Goal/effect/answer structure.

## 3. Stage boundary

S1 supplies one immutable Release. S2 may use:

```text
public: Need/Brief, reset, tools, invoke
trusted Host only: read_state
```

S2 does not consume diagnostic scenarios as task proposals. Qualification
establishes that the Release is usable; it does not enumerate the TaskSpace.

## 4. Minimal contracts

### 4.1 SamplingTarget

```text
required_goal_shape
required_focus_tool_names
required_outcome_class
prior_structure_summaries
```

The three required fields are structural obligations selected from simple
counters. Every focus tool must occur in the final objective, not only in
exploration. The Agent may return typed unsupported but may not substitute an
easier shape or outcome. The target contains no path, edge or
environment-specific rule.

### 4.2 Public references

```text
TaskLiteral(value)
ResetValue(pointer)
ObservationValue(step_id, pointer)
```

Every load-bearing call argument, condition and collection selector must close
over these sources. Protected state can validate outcomes but cannot supply an
acting operand.

### 4.3 TaskDraft

```text
goal_shape: Atom | All | If | ForEach
instruction
objective_step_ids
answer_projection over public value sources
condition_source, when If
member_source, member key and per-member objective refs, when ForEach
```

The Sampling Agent authors only this public semantic selection over events it
actually observed. It cannot provide an answer schema, protected paths,
expected state, reward, checker prose or executable code.

Unnamed target selection must resolve to a unique public value under the
frozen reset. ForEach deliberately resolves a complete public set. A draft
that permits several unrelated target choices is unsupported in this contract;
the proposal's accidental choice cannot silently become Task truth. Every free
literal affecting final state or answer must instead appear exactly in the
instruction.

### 4.4 AnswerProjection

An answer is a canonical JSON tree whose leaves/subtrees are composed from
`TaskLiteral`, `ResetValue` or `ObservationValue`. References may copy an
entire public object/array or assemble an object/array of references. They
cannot execute arithmetic, invent labels or synthesize claims such as
`operation_succeeded=true` when no cited public field contains that fact.

Host resolves the projection to the expected answer and derives a type-only
transport schema from the referenced ToolSpec/reset schemas. Semantic values,
patterns and constants remain trusted evaluator data; they are never exposed
as answer-schema `const` hints. Empty arrays retain their referenced source
item schema rather than guessing from the observed empty value.

### 4.5 Goal and sampling evidence

Host resolves the draft into typed Goal data:

```text
AtomGoal(outcome)
AllGoal(children >= 2)
IfGoal(public condition, selected branch goal)
ForEachGoal(public initial members, body goals)
```

Each resolved outcome binds the relevant public calls, source references,
answer values/schema and actual protected before/after change set. The sampled
public solution is retained separately from Goal meaning.

### 4.6 Candidate and TaskPack

A Candidate binds:

```text
release_id
builder_projection_digest
reset_start
Goal
instruction
final_answer_schema
sampling_evidence_digest
structure_id
```

Each of five filter runs records an independent instance, reset, public trace,
before/after state, final answer, provenance, evaluator result, provider usage
and failure owner. All five outcomes are retained.

The public Task view exposes only task/release identity, instruction and final
answer schema. Goal, expected outcome and sampling solution are trusted data.

## 5. Sampling algorithm

### 5.1 Select a coverage target

For each Release, counters track admitted/attempted Goal shapes, selected
objective tool names and outcome classes. Deterministic tie-breaking selects an
underused required cell and one or more required focus tools. No candidate tool
chain is computed.

### 5.2 Execute the Sampling Agent

Open a fresh instance and send the Agent the public inputs plus SamplingTarget.
The Host owns the loop and dispatches every schema-valid function call. The
Agent may inspect, mutate, branch and iterate using ToolObservations. Invalid
calls return structured public errors; infrastructure and environment failures
retain their original owners.

The Agent terminates with either typed unsupported or a `TaskDraft`. A draft is
accepted for materialization only if its objective references successful or
stable-refusal events in the captured trace. Merely making a public call cannot
create a Candidate.

### 5.3 Materialize Goal truth

Host:

1. resolves every step and public source reference;
2. validates argument provenance against Task/reset/prior observations;
3. checks the requested Goal shape/outcome/focus tools exactly;
4. checks unique selection, or a complete ForEach set with one objective
   execution for every initial member key;
5. resolves AnswerProjection and derives its type-only transport schema;
6. compares protected before/after state and captures expected changes;
7. rejects initial satisfaction, hidden operands, answer leakage, decorative
   objective calls and duplicate structures.

The Host does not infer a business objective from arbitrary state differences;
the Agent selects the objective steps, while the Host proves that every claim
is supported by the real run.

### 5.4 Fresh reference replay

From a new reset, Framework resolves the frozen public argument sources and
replays the retained solution. The common evaluator must reproduce the Goal's
outcome, answer and permitted state changes. Failure is terminal for that
sampling attempt. There is no in-place Goal, instruction or verifier repair.

## 6. Four Goal shapes

### Atom

One coherent query, transition or stable business refusal selected from the
real trace. Query/refusal outcomes require unchanged protected state;
transition outcomes require the expected change set and no unexplained change.

### All

Two or more selected child outcomes must serve one public instruction and all
hold after execution. Calls made only for discovery remain evidence, not Goal
children. Adjacent or same-domain calls do not establish coherence.

### If

The draft references one public scalar condition observed before the branch
action. A collection pointer cannot masquerade as a condition. The actual value
selects the frozen required branch. If the condition or branch cannot be
represented from public evidence, the draft is unsupported.

### ForEach

The draft references one complete public collection observed before mutation,
one member-key pointer and the action argument sourced from each member. At
least two initial members are required. Objective refs must form a bijection
with the frozen member-key set; evaluation permits no missing, duplicate or
extra member.

## 7. Common evaluator

One ordinary Framework evaluator receives `(goal, actual_run_context)`.

- the actual canonical before state must equal the frozen reference before
  state for the same Release/reset;
- the actual canonical final state must equal the frozen reference final state;
  whole-state equality is the primary collateral guard, while leaf diffs are
  diagnostic output only;
- the actual structured final answer must equal the Host-resolved
  AnswerProjection;
- Atom checks public outcome/answer, required unchanged state for query/refusal,
  and expected/no-outside changes for transitions.
- All recursively checks every child and compatible aggregate effects.
- If resolves the actual public condition and checks the selected branch.
- ForEach resolves the frozen initial member set and checks every member.
- Every required Goal component must be visited; incomplete evaluation fails
  rather than returning a partial PASS.

The evaluator contains no release, environment or tool names. It does not
compare the complete action sequence, so read-only exploration or a different
valid public route can pass when it reaches the same canonical state/answer and
satisfies the Goal-shape obligations. A route with extra mutation is correctly
different state and fails.

## 8. Filtering and diversity

For each frozen Candidate, run five independent Responses policies on five
fresh instances. Exactly five valid semantic outcomes are required and at
least two must pass. Runs may be serial or concurrent under a route-specific
provider limit; concurrency is scheduling only. The local 8317 route defaults
to one until an explicit concurrency probe proves a larger safe value.

After admission, deterministic selection balances:

```text
Goal shape
selected objective tool set
outcome class
public binding depth
condition/member structure
effect and answer shape
```

Prior accepted structure summaries are shown to later Sampling Agents to avoid
semantic repetition. Wording and entity-ID variation do not count as new
structure. No Graph artifact exists.

## 9. Cross-environment evidence and known limits

Four real Release/3 processes were exercised during planning: inventory,
support SLA, Git release workspace and laboratory chain of custody. Coherent
public multi-step executions succeeded in every environment. A no-Graph
simulation then ran ForEach, If, All and Atom respectively through Sampling,
fresh replay and five independent public solvers. After generic contract
corrections, all four Candidates produced 5/5 state-and-answer-equivalent
solver runs.

The probes also establish required boundaries:

- schema-name edges are neither sound nor complete;
- temporal state dependencies need Agent reasoning, not Framework graph rules;
- selected dynamic targets must be uniquely public or complete-set bound;
- an executable cycle whose final business state cancels is not automatically
  a meaningful Task;
- raw list-index diffs are evidence bytes, not semantic entity identity.
- an LLM-authored answer schema caused 5/5 Git terminal-format failures while
  the same Task passed 5/5 with a Host-derived type-only schema;
- unconstrained “choose a new version” wording froze an arbitrary proposal
  value and was correctly rejected;
- local two-way provider concurrency produced no valid semantic results while
  serial execution succeeded, so scheduling cannot define admission.

These findings justify execution-first semantic selection plus deterministic
Host verification. They do not authorize environment-specific fixes.

## 10. Parallelism, failures and S3 boundary

Sampling attempts and five-run filters use fresh isolated instances and may
run concurrently. Deterministic fan-in owns deduplication and TaskPack sealing;
worker count never changes semantic identity.

Failures retain the first causal owner:

```text
SamplingUnsupported
SamplingExecution
DraftRejected
EvaluatorDefect
PolicyRejected
EnvironmentDefect
InfrastructureFailure
DuplicateStructure
```

S2 emits no scalar reward, token mask, logprob or training trajectory. A later
clean-break S3 adapter opens the exact Release and Task public view, collects an
episode and calls the same trusted evaluator. Existing checker-bound S3 code is
not claimed compatible and is not modified here.

## 11. Evaluator assurance without per-Task pressure

Test the common evaluator once using real-derived cross-domain examples and
focused mutations: wrong answer, no-op transition, unexplained state change,
missing All child, wrong If branch, and missing/duplicate/extra ForEach member.
These are Framework regression tests, never regenerated per TaskPack.

The final 20-release report separates sampling yield, Task validity,
model-relative recoverability, diversity and infrastructure failures. Resume
claims cite immutable TaskPack and campaign IDs, never prose or green tests.
