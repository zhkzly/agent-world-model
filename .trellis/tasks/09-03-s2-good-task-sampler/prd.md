# S2 Good Task Sampler

## Goal

Consume the frozen 20/20 `EnvironmentRelease/3` campaign and produce a real,
diverse, resume-grade corpus of executable Good Tasks through one production
path:

```text
execution-first Sampling Agent
-> Host Goal/evidence freeze and fresh replay
-> common Good-Task filtering
```

Task sampling must work for a previously unseen Release without adding Python
branches, an environment-specific sampler, generated verifier code or a Tool
Graph. A demo, mock, green unit suite or candidate count is not completion.

## Confirmed baseline and correction

- S1 is complete: 20 immutable qualified releases, 206 public tools, real
  persistent state, ZIPs and cold verification.
- S1 hands S2 the released environment surface: Need/Development Brief,
  `reset`, `tools`, `invoke` and a Host-only task-neutral state reader. S1
  diagnostic scenarios are qualification evidence, not Task templates or a
  supposedly complete TaskSpace.
- The existing Responses proposal loop is reusable. In live probes it
  autonomously completed coherent Git and laboratory workflows using only the
  public interface.
- The current `propose_task_direct` acceptance is invalid: it requires only a
  non-empty public trace and then asks Codex to generate a per-Task Checker.
  A Candidate must instead bind a coherent objective to successful executed
  steps, pass Host replay/evaluation, and use no generated Checker.
- Static Tool Graphs are rejected. Across four real releases, exact-name schema
  matching produced many false edges while missing real temporal dependencies
  and field aliases. Graphs and random walks are not part of this task.
- The previous per-Task/per-environment pressure/checker path and the later
  over-broad deletion are both superseded. Old Direct campaign artifacts remain
  a comparison baseline only.

## Inputs and outputs

### Input

One exact cold-prepared `EnvironmentRelease/3` providing:

```text
release identity
Need / Development Brief projection
reset / tools / invoke / close
public ToolSpecs and structured ToolObservations
task-neutral protected read_state available only to Host evaluation
```

### Output

```text
Accepted TaskPack
Rejected sampling/filter attempt with typed ownership
CorpusManifest over accepted unique TaskPacks
20-release campaign report
```

## Stage 1 — Execution-first Task sampling

### S1. Simple coverage target

Framework selects a `SamplingTarget` from small counters, not a graph:

```text
required Goal shape: Atom / All / If / ForEach
one or more required focus tools
required outcome class: query / transition / refusal
prior accepted structure summaries to avoid
```

The target is a structural obligation, never a tool sequence or semantic truth.
Every focus tool must participate in the selected objective, not merely in
exploration. If the target is unnatural or unreachable, the Sampling Agent
returns unsupported and the attempt is retained. It may not silently emit an
easier shape or outcome. Framework never fabricates a chain to fill a cell.

### S2. One generic Sampling Agent acts first

On a fresh isolated materialization, the Sampling Agent sees only:

```text
Need / Development Brief
SamplingTarget
reset observation
ToolSpecs
its own ToolObservations
```

It autonomously explores the public tools and physically completes one
coherent, Need-relevant objective. It may make read-only discovery calls before
the objective. It cannot inspect protected state, write native storage, define
Task truth or decide admission.

After a successful trajectory it emits one structured `TaskDraft` containing:

```text
goal_shape
natural public instruction
objective_step_ids that actually occurred
answer projection composed only from public source references
public operand/condition/member source references
```

It emits no answer schema, Checker brief, expected protected state, reward,
Python predicate or solution code. Framework resolves the answer projection
against captured ToolObservations and derives the public answer schema from the
referenced source schemas. The projection may copy or assemble JSON values but
may not invent derived booleans, labels, arithmetic or facts.

### S3. Host freezes truth from actual execution

Host captures reset, the complete public trace, argument provenance and
protected before/after state. It rejects the draft unless:

- every objective and answer reference resolves to the captured execution;
- objective calls have the required success/refusal outcomes;
- every load-bearing operand comes from the Task, reset or a prior public
  ToolObservation;
- any unnamed selected target is uniquely determined by its recorded public
  selector; open-ended “choose any” targets are unsupported rather than bound
  to the proposal's arbitrary choice;
- every free ID, version, message, quantity or other Task literal affecting
  truth is written exactly in the instruction;
- If conditions resolve to a public scalar observed before the objective;
- ForEach membership is a complete public initial set with a member key, and
  objective executions cover every initial key exactly once;
- the Task is not already satisfied at reset and the instruction does not leak
  the answer or solution path;
- the selected steps form one coherent objective rather than decorative calls.

Host then materializes canonical `AtomGoal`, `AllGoal`, `IfGoal` or
`ForEachGoal` data. Exact expected public answers, their type-only transport
schema and protected state changes come from the real run. Semantic constants
remain evaluator truth and are not exposed through `const`-filled answer
schemas. Environment-specific names, IDs and state paths are data in the Goal
evidence, never Framework code branches.

### S4. Fresh replay precedes Candidate creation

Framework replays the recorded public solution from a fresh reset, resolving
arguments only through the frozen public sources. The common evaluator must
pass on the replayed public trace, before/after state and answer. A failed,
unstable, ambiguous or unbound replay produces a typed sampling rejection, not
a Candidate and not a repair loop.

An emitted Candidate therefore has constructive public existence evidence.
The retained solution proves at least one route, but is protected evidence and
is never the only accepted trajectory.

## Goal shapes

- `AtomGoal`: one coherent query, transition or stable business refusal.
- `AllGoal`: all related objective children from one coherent user intent must
  hold; shared wording or adjacent calls are insufficient.
- `IfGoal`: an actually public scalar condition selects the required branch;
  unsupported branches are not invented.
- `ForEachGoal`: a public complete initial member set is processed in full;
  missing, duplicate or extra membership fails.

No release is forced to support a shape. Natural-language words such as “if”
or “all” do not establish the shape.

## Stage 2 — Common Good-Task filtering

### F1. One evaluator, no generated Checker

Framework implements one domain-free recursive evaluator:

```text
evaluate(AtomGoal, context)
evaluate(AllGoal, context)
evaluate(IfGoal, context)
evaluate(ForEachGoal, context)
```

The evaluator checks frozen public outcomes, exact answer sources, expected
state changes, forbidden outside changes and public provenance. It does not
compare the acting Agent's entire trace with the sampling trace; an alternative
public route passes when it reaches the same frozen outcome without forbidden
effects.

Unsupported semantics fail closed. Adding a Release or Task cannot add
evaluator source, build a wheel or invoke a generated repair loop.

### F2. Five complete fresh public runs

After Candidate freeze, run exactly five valid independent public Agent
attempts on five fresh materializations. Each sees the final instruction,
Framework-derived type-only answer schema, reset observation, ToolSpecs and
only its own ToolObservations.

The common evaluator grades every run. At least two of five must pass. All five
semantic outcomes must finish and be retained; Infrastructure failures are
retried within a separate budget and never counted as semantic failures.
Execution may be serial or concurrent according to the actual provider route;
simultaneity is not a semantic requirement.

The sampling replay proves existence. The 2-of-5 filter measures whether an
independent public Agent can recover the Task from its final presentation and
filters one-off or underspecified proposals.

### F3. No per-Task pressure suite

Individual admission does not generate wrong-target, partial, collateral,
reverse-order or mutation policies. The common evaluator is tested once with
reusable real-derived regressions and focused mutations. Optional research
audits remain outside Task admission.

## Good Task definition

Every accepted Task is:

1. **Publicly solvable:** one public sampling solution and at least two fresh
   public solutions pass.
2. **Reliably verifiable:** one common evaluator checks real state, observation
   and answer evidence without generated code.
3. **Well-posed:** all load-bearing operands and conditions are public and
   deterministic for the frozen reset, while the answer and route are hidden.
4. **Non-trivial:** the Goal is not already true and requires meaningful
   querying, state change, branching, iteration or stable refusal reasoning.
5. **Stable:** fresh instances reproduce the Start and Goal semantics without
   shared episode state.
6. **Purposeful:** selected objective steps serve one Need-related user intent;
   exploratory calls do not become required merely because they occurred.

Model-relative difficulty is measured after these hard gates. Tool count or
path length alone is not quality.

## Diversity and reporting without a Graph

- Schedule underused Goal shapes, public tools and outcome classes through
  counters; never prescribe a chain.
- Deduplicate by Goal shape, selected objective tools, public binding depth,
  effect/answer structure and condition/member structure, not wording or
  concrete IDs.
- Keep attempted, sampled, replayed and admitted counts separate.
- Report unsupported cells honestly instead of weakening gates.
- Run the frozen implementation over all 20 releases and report tool coverage,
  Goal distribution, 2-of-5 vectors, redundancy, latency, tokens and calls.
- Map every resume-ready number to exact retained TaskPack and campaign IDs.

## Forbidden

- any Tool Graph, dependency-graph authority or random-walk product path;
- S1 diagnostics treated as Task templates or complete TaskSpace;
- generated per-Task or per-environment Checker, TaskSemantics or verifier;
- `checker_brief`, Checker Author, checker wheel or checker repair loop;
- generated `pi_code` or `V_code` as a required product path;
- per-Task generated pressure/adversarial policies;
- Candidate admission from a merely non-empty trace;
- repairing or rewording a failed frozen Candidate into success;
- protected operands, hidden setup, native writes or witness-trace equality;
- domain branches, canned Tasks, dictionary worlds, fake providers or legacy
  compatibility paths;
- claiming diversity from wording, raw count, graph edges or tool length.

## Acceptance criteria

- [ ] The existing public Responses tool-loop is reused, but no production
      reference to Checker Author/checker projects or `checker_brief` remains.
- [ ] No Tool Graph, random walk or S1 diagnostic-to-Task extraction exists in
      the production sampler.
- [ ] One generic Sampling Agent can sample a new exact Release without source
      changes; SamplingTarget contains only required shape/tool/outcome
      obligations and no tool chain.
- [ ] A Candidate cannot exist without successful objective steps, closed
      public provenance, Host-frozen Goal evidence and a passing fresh replay.
- [ ] Atom/All/If/ForEach are typed data checked by one common evaluator;
      unsupported or ambiguous goals fail closed.
- [ ] Framework, not the Sampling Agent, derives the final-answer transport
      schema from a fully grounded public answer projection.
- [ ] Five valid fresh attempts complete independently and at least two pass
      before TaskPack admission.
- [ ] No individual Task generates a Checker or pressure suite.
- [ ] Serial and parallel scheduling over frozen attempts produce identical
      accepted structure sets and identities.
- [ ] TaskPacks cold-read into a non-leaking public view and trusted
      Goal/evidence view sufficient for a later clean-break S3 adapter.
- [ ] One frozen campaign reaches terminal records for all 20 releases and
      emits honest coverage, yield, rejection, cost and difficulty statistics.
