# S2 Implementation-Readiness Audit

Date: 2026-08-28

Branch: `s2-task-foundry`

Status: planning evidence, not product-execution evidence

## Verdict

`IMPLEMENTABLE AFTER ACTIVATION`

The revised PRD/design/implementation plan now specifies enough code ownership,
data contracts, execution order, failure ownership and real acceptance evidence
to guide production implementation without falling back to the old
Graph/Programmatic-first design.

The design remains conditional on S1 v2 publishing independently qualified
release-local TaskSemantics. It does not claim that S2 can recover reliable Task
truth from arbitrary opaque tools/state after the fact.

## Blocking ambiguities found and corrected

1. **Final instruction after witness.** Corrected to checker freeze -> canonical
   instruction freeze -> witness receives that exact string.
2. **Task identity mixed with model trials.** Corrected to TaskDefinition /
   TaskPack / TaskAssessment / CorpusManifest separation.
3. **Six-node GoalProgram overdesign.** `Select` and `Report` were removed as
   standalone nodes; selectors/reporting are Blueprint attributes. Core Goal AST
   is Atom/All/If/ForEach.
4. **Unqualified natural composition.** CapabilitySpec now requires workflow IDs
   and qualified public ConditionSpecs.
5. **Custom WitnessRecipe/value-expression DSL.** Removed. TaskPack stores two
   concrete successful public traces and provenance reports.
6. **Codex SDK versus acting Agent ambiguity.** Codex SDK is restricted to actor
   project and TaskSemantics project code generation. Witness/assessment uses a
   Host-owned Responses function-tool loop. Deterministic framework code owns all
   compilation and verdicts.
7. **Prompt-only requirements.** Every prompt responsibility now has a matching
   schema, Host check, physical execution gate or explicit non-authority status.
8. **Model-relative difficulty in structural diversity.** Removed from
   TaskFingerprint and placed in TaskAssessment.
9. **One happy path could satisfy completion.** Added per-release and held-out
   Task-yield/structure/start floors that cannot be met by paraphrases or
   parameter-only variants.

## Framework implementation responsibilities

Framework code must directly implement:

```text
release v2 identity and prepare/open isolation
TaskSemantics contract validation
StartCase/materialization
qualified selector and Goal enumeration
checker compilation/interpreter
canonical instruction rendering/audits
Responses tool dispatch and trace journal
public/protected operand provenance
fresh witness gates
challenge and checker mutation verdicts
TaskDefinition/TaskPack identities
TaskAssessment and CorpusManifest separation
semantic deduplication/corpus selection
```

A worker that responds by adding prompts without these code paths has not
implemented the plan.

## Codex SDK responsibilities

Exactly two persistent code-generation roles are required:

```text
Environment Builder
  frozen BuilderProjection + actor contract
  -> complete actor uv project

TaskSemantics Author
  Host-frozen expected semantic relations + read-only candidate view
  -> complete protected semantics uv project
```

Both operate in separate fresh workspaces/threads. Host-owned checks and
physical negatives authorize publication. No additional Critic/Reviewer/Arbiter
Agent organization is justified.

## Responses Agent responsibilities

The Host-owned Responses loop performs public policy execution only:

```text
canonical instruction + reset context + ToolSpecs + ToolObservations
-> tool calls + final structured answer
```

It receives no checker/native/protected data. The same runner is reused for
constructive witness and independent TaskAssessment with different route/policy
identities.

## Good Task quality mapping

| Quality | Concrete gate |
| --- | --- |
| Public solvability | two successful fresh executions of exact final instruction; load-bearing argument provenance |
| Reliable verification | S1 atomic physical negatives + frozen checker + S2 challenge/mutation kill |
| Well-posedness | qualified labels, deterministic renderer, slot/cardinality/leakage audit |
| Non-triviality | checker false on before==after; query answer-leak check |
| Reproducibility | deterministic reset-only StartCases and semantic-key alignment |
| Need/natural grounding | Requirement IDs + shared qualified workflow IDs + qualified ConditionSpecs |
| Path openness | final facts/answer/process checked; reference-trace equality absent |
| No collateral | atomic evaluator + scope-aware composition + collateral challenge |
| Structural diversity | capability/workflow/Goal/selector/start/answer/process fingerprint |
| Difficulty/utility | separate independent TaskAssessment and matched-budget downstream test |

## Remaining research risks, not planning ambiguity

1. Generated TaskSemantics may still contain correlated semantic mistakes. The
   physical-negative and held-out gates test but cannot mathematically eliminate
   this risk.
2. Reset-only start diversity may limit Task yield. The correct outcome is an S1
   limitation or method failure, not hidden setup.
3. A bounded public policy may fail to find witnesses for valid Tasks. This is
   reported as planner yield, not semantic impossibility.
4. Structural diversity may not improve training. Matched-budget downstream
   evaluation is therefore a fatal gate.

## Anti-overdesign rule

Do not add a new semantic object, Agent role, plugin, graph subsystem, DSL,
protocol or service unless a real SQLite/Git/held-out failing case cannot be
expressed by:

```text
qualified capability atom
+ SelectorSpec
+ four-node GoalProgram
+ frozen checker
+ exact canonical instruction
+ public episode traces
```

## Readiness conclusion

The plan can now guide implementation. The first code checkpoint is contracts and
failing tests, followed by S1 v2 preparation and extension of existing
Qualification. Starting with a hand-coded sample Task, fake release, prompt-only
semantic author or Graph demo would violate the plan rather than implement it.
