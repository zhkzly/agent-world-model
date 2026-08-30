# S2 Goal-First Task Foundry

## Goal

Build the paper-grade production path:

```text
Need
-> real executable EnvironmentRelease
-> Goal-first Tasks grounded in that release
-> public Agent tool execution
-> protected checker truth
-> TaskPack
-> separate assessment/corpus
-> later SFT/RL consumption
```

Semantic completion requires real processes and state transitions. Mocks,
dictionary worlds, hand-written successful traces, green unit tests, or model
self-approval are not completion evidence.

There is no EnvironmentRelease v1 compatibility path.

## Stage ownership

### S1 EnvironmentRelease

S1 owns:

- a real uv actor project exposing `reset`, `tools`, `invoke`, and `close`;
- public schemas and exact ToolSpecs;
- release-local TaskSemantics;
- one independent native-state auditor;
- one real positive public execution for every qualified capability;
- immutable publication, relocation, and cold preparation.

S1 does not prove every future Task, alternative route, difficulty level, or
corpus yield.

### S2 Task Foundry

S2 consumes only a sealed EnvironmentRelease and owns:

- logical Task binding and Goal compilation;
- checker freeze before instruction exposure;
- public solvability;
- minimal applicable negative checks;
- TaskPack identity;
- separate TaskAssessment and CorpusManifest.

S2 does not invent environment truth or scalar training reward.

### Paper evaluation and S3

Corpus size/structure targets, route diversity, perturbation studies, mutation
benchmarks, difficulty, and downstream SFT/RL value are experiment metrics.
They do not authorize or block an individual EnvironmentRelease or TaskPack.

## Author and Framework ownership

Three isolated authored artifacts remain:

1. Environment Builder writes actor code.
2. TaskSemantics Author writes protected release-local checker code.
3. Native Auditor writes an independent read-only native effects/collateral reader.

The Native Auditor returns only:

```text
required_effects_ok
collateral_ok
failure_codes
```

It does not duplicate final-answer, report-value, process, Task, or reward
evaluation. Framework owns schemas, identities, execution, source matching,
receipts, publication, TaskPack admission, and final verdicts.

## Answer contract

Each capability declares only final-answer values needed by its own user
objective. Examples:

- query: the requested public values;
- successful mutation: the user-relevant result such as a commit reference;
- refusal: the stable refusal code.

State integrity, persistence, process completion, and collateral constraints
are checker evidence, not padded final-answer fields.

Every AnswerField declares exactly one public source:

```text
task_literal(value)
task_descriptor(pointer)
reset(pointer)
tool_observation(tool_name, pointer rooted at {ok,data,error})
tool_schema_constant(tool_name, input_pointer, value)
```

Qualification proves every reported non-null value matches a real public
occurrence. Different condition branches may use different answer schemas.

## S1 qualification

For every capability, Framework finds one eligible representative binding and
runs the public qualification goal once on a fresh materialization. Admission
requires:

- TaskSemantics accepts the real execution;
- Native Auditor agrees on required effects and collateral only;
- AnswerFields match real public source occurrences;
- `task_kind` matches the physical semantic state transition;
- actor, TaskSemantics, and auditor remain read-only outside their roles.

Wrong-answer, wrong-target, partial, alternative-route, AgentChoice, and
checker-mutation experiments are not repeated in S1.

## S2 Good Task contract

A TaskPack requires:

- one sealed release and qualified StartCase;
- one frozen logical selection and checker;
- one final instruction rendered after checker freeze;
- two successful fresh public witnesses with independent materializations;
- exact public argument provenance;
- the minimal applicable negative evidence for its Goal.

Minimal negatives:

| Goal | Required Task-level negatives |
|---|---|
| Atom | no-op; wrong target if available; wrong answer if constructible |
| ForEach | no-op; one representative omitted member |
| If | condition-selected branch must be satisfied |
| All | no-op; one representative missing child |

Collateral is still evaluated by TaskSemantics on every witness; S2 does not
run an extra unrelated Task solely to manufacture collateral damage.

## Goal contract

The bounded GoalProgram contains only:

```text
AtomGoal
AllGoal
IfGoal
ForEachGoal
```

Task diversity comes from Goal/process/evidence structure and qualified logical
selection, not answer-field singleton profiles, parameter swaps, or paraphrases.

## Acceptance criteria

- no v1 parser, adapter, reader, publisher, or fallback;
- one real cold-published EnvironmentRelease for Git and SQLite with unchanged Framework code;
- every qualified capability has real positive execution and source evidence;
- public Consumer can reset and invoke the relocated release;
- Atom/ForEach/If compiler and TaskPack paths use only admitted release views, and
  no individual environment must manufacture a Goal kind absent from its qualified semantics;
- two fresh public witnesses pass for admitted Tasks;
- minimal applicable Task negatives fail for the intended reason;
- deterministic tests, Ruff, formatting, Mypy, lock check, and diff check pass;
- paper experiments report corpus yield and downstream utility separately.

## Forbidden

- compatibility readers or `allow_unqualified` paths;
- self-authored manifests, receipts, verdicts, Tasks, or rewards;
- exact duplicate public-answer evaluation in the Native Auditor;
- S1 copies of Task-level challenge matrices;
- mandatory alternative routes or per-occurrence AgentChoice perturbation;
- result-object boolean flipping presented as executable mutation evidence;
- domain branches in Framework;
- product release decisions based on corpus-count targets.
