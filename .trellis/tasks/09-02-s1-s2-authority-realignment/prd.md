# S1 Environment Release / S2 Task Truth Authority Realignment

## Goal

Restore a paper-grade product boundary in which S1 can publish a real,
replayable executable environment without first requiring independently
LLM-authored Task truth programs to agree, while S2 owns per-Task semantics,
solvability, checker/reward truth and Task admission under one sealed semantic
authority.

## Background and confirmed evidence

- `PROJECT.md:25-47` currently gives S1 both executable-environment ownership
  and protected TaskSemantics/Capability/Condition/evaluation ownership.
- `PROJECT.md:148-155` requires Codex to author three S1 projects: actor,
  TaskSemantics and a mutually blind Native Auditor.
- The direct coordinator implements that exact sequence at
  `src/agent_env_foundry/generation.py:435-516`; only after both generated
  readers and physical Qualification pass can publication run.
- The stopped `bb0645b2...` campaign retained eight terminal Needs and zero
  Releases. Research, actor Builder and public-surface freeze repeatedly
  passed. Six terminals were logical Qualification failures, one Semantics
  Author stalled on an exact static source error, and one was a provider
  failure.
- Three of the first six terminal Needs were peer-reader disagreements over
  required effects or collateral. A clinic booking case completed the public
  process, required effect and answer, but TaskSemantics and Native Auditor
  disagreed only on collateral.
- The frozen Expected Semantics expresses phrases such as "unrelated state
  remains unchanged" and branch/refusal goals, but does not seal an executable
  state projection, allowed-change set, forbidden-change set, branch-specific
  answer source or category-specific noop predicate. Two independent code
  authors can therefore implement different valid interpretations.
- Automatically repairing one or both readers from their disagreement is not
  safe: no third truth authority identifies which reader is wrong, and repeated
  feedback can make peer readers converge on the observed case rather than on
  external truth.
- OpenViking history independently records the same pattern in earlier
  canaries and warns that independently generated Witness/Judge or peer-reader
  agreement is internal closure, not an external semantic oracle. Those
  memories are advisory; the current eight frozen records are the deciding
  evidence.

## Approved product decision

The user explicitly approved revising stable `PROJECT.md` on 2026-09-02. The
approved authority is as follows.

### S1 owns environment truth, not Task truth

S1 owns:

- Need research and the Development Brief;
- one standalone uv-managed actor project;
- public `reset / tools / invoke / close` behavior;
- real persistent native state, reload, isolation and controlled replay;
- exact ToolSpecs and observed schema conformance;
- reset/start reconstruction sufficient for later task discovery;
- a protected, task-neutral state/readback boundary sufficient for S2 to
  evaluate real before/after facts;
- immutable EnvironmentRelease bytes, dependency lock, cold preparation and
  relocation.

S1 does not own:

- CapabilitySpecs as a Task distribution;
- qualification goals or answer fields;
- positive/noop Task cases;
- TaskSemantics or task-specific Native Auditor projects;
- Task checker, reward, witness or corpus admission.

An environment fails S1 only for an environment-owned defect: invalid or
non-executable tools, schema/output mismatch, reset/replay failure, broken
persistence/isolation, invalid task-neutral readback, dependency/publication or
cold-relocation failure.

### S2 owns one semantic authority per admitted Task

S2 owns:

- candidate Task discovery from Need-bound affordances and real executions;
- one sealed GoalContract describing variables, preconditions, required,
  allowed and forbidden effects, process evidence and branch-specific answer
  sources;
- fresh Start materialization and real before/after truth;
- deterministic checker compilation from that sealed contract and truth;
- public instruction rendering after checker freeze;
- fresh public solvability witnesses, replay and discriminating negatives;
- per-Task admission, assessment and corpus selection.

Independent Agents may propose or challenge a GoalContract, but cannot create a
second peer truth authority. A failed candidate Task is rejected without
invalidating its EnvironmentRelease.

## Requirements

1. **Stable authority update** — update `PROJECT.md` only after explicit user
   approval; all design/spec/task artifacts must agree with the new S1/S2
   ownership.
2. **Clean break** — remove the S1 publication dependency on Expected
   TaskSemantics, TaskSemantics Author, Native Auditor and task-case
   Qualification. Do not add compatibility readers, feature flags or dual
   release paths.
3. **Environment-level qualification** — define executable, domain-neutral S1
   checks that prove real actor behavior, state persistence, reset/replay,
   schema conformance, task-neutral readback and cold publication without
   preselecting Tasks.
4. **S1→S2 handoff** — freeze the exact public actor surface plus the minimal
   protected task-neutral truth/readback contract required by S2; do not leak
   protected operands to an acting policy.
5. **Single Task semantic authority** — S2 must seal one GoalContract before
   witness execution and derive checker/reward truth from it plus real state,
   rather than comparing two independently generated truth programs.
6. **Per-Task failure scope** — Task proposal, witness, checker challenge or
   assessment failure rejects that Task only; it cannot revoke an otherwise
   valid EnvironmentRelease.
7. **Real evidence** — acceptance requires real cross-domain uv projects,
   persistent state, cold releases, fresh public tool execution and physical
   Task verification. Mocks and green unit tests are not product evidence.
8. **Deletion-first implementation** — remove obsolete S1 task-semantics
   authority and tests before adding replacement S2 truth mechanics; no generic
   workflow engine, verifier DSL or domain branches.

## Acceptance criteria

- [ ] Stable product intent explicitly states the approved S1/S2 authority
      boundary with no contradictory current spec.
- [ ] A fresh filesystem/Git and a fresh SQLite/stateful Need each produce a
      cold, relocated EnvironmentRelease without Task generation or task-specific
      verifier agreement in S1.
- [ ] Each Release exposes real public tools and a protected task-neutral
      readback that reconstructs fresh before/after truth without leaking it to
      the acting policy.
- [ ] S2 can derive at least one candidate from each contrasting Release, seal
      one GoalContract, compile its checker, prove public solvability and reject
      a relevant physical negative.
- [ ] Deliberately malformed or unsolved Task candidates are rejected while
      the source EnvironmentRelease remains valid and reusable.
- [ ] Two peer-generated semantic programs are absent from the release
      admission authority; independent review/challenge cannot mutate or define
      Task truth.
- [ ] Old S1 TaskSemantics/Native-Auditor production references and
      compatibility paths are zero; remaining historical artifacts are clearly
      non-authoritative.
- [ ] Full deterministic checks, mutation evidence and post-code independent
      review pass, followed by one held-out cross-domain Need without domain
      edits.

## Out of scope

- S3 episode runtime, S4 training or learning-gain claims.
- Graph/Programmatic sampler experiments until the corrected Direct path is
  physically complete.
- A universal state JSON, general verifier DSL, workflow engine, Registry
  redesign or backward compatibility with superseded release formats.
- Loosening logical gates merely to raise batch yield.
