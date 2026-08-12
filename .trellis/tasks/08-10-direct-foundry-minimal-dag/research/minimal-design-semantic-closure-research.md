# Research: minimal Design semantic closure

- Query: What is the smallest coherent typed Design contract for the existing WorldArchitecture -> optional SharedToolSemantics -> ToolSemantics -> WorldRules -> CurriculumPlan -> TaskRequirement -> ModelingGate path that remains honest about the canonical product goal, gives every model-produced semantic field a consumer, and does not introduce future-product machinery?
- Scope: internal
- Date: 2026-08-11

## Findings

### Decision and boundary

The smallest coherent contract is **not** the current one-tool, one-scenario
projection with a decorative `shared_tools.groups` payload.  It is a compact,
typed `EnvironmentDesign` containing one canonical world model, a derived
coupling plan, one committed local semantic shard per tool, zero or more
committed shared-group contracts, typed global rules, and an ordered
parameterized task curriculum with one committed task contract per family.

This is the smallest closure because each item has a present consumer:

```text
typed source draft
  -> framework compiler + immutable Design artifact
  -> Builder-visible Design + implementation contract
  -> candidate source / framework-owned runtime-Judge inputs where expressible
  -> world_spec / rule_ir / curriculum package metadata
  -> Registry cold reparse and exact cross-binding
  -> future Expand parent-world handoff
```

The Design compiler, not the Direct model, owns IDs, schemas, JSON Schema
keywords, rule IDs, task coordinates, seeds, reward/termination reduction,
verifier partitioning, gates, release, and the coupling plan.  This preserves
the source-of-truth authority boundary: `WorldSpec`/`ToolContractSet` is the
single typed semantic centre for Runtime, tasks, verifier, and future change;
parallel prompts must not invent separate worlds
([docs/agent-world-environment-generation.zh.md:165-181]).

The current code instead accepts a narrow tool-name/string surface in
`_direct_architecture` ([agent_world/design.py:925-1008]), commits arbitrary
`groups` ([agent_world/design.py:1014-1046]), and only uses that value as an
uncompiled later prompt input ([agent_world/design.py:1335-1379]).  The prior
independent audit correctly identifies that as a producer/consumer gap
([.trellis/tasks/08-10-direct-foundry-minimal-dag/research/direct-r2-independent-check.md:102-122]).

### Minimal typed inputs and outputs

The following is the semantic minimum.  `RuleDraft` means the closed source ADT
already specified by the task contract: bounded predicates over frozen semantic
catalog indexes, bounded effects, public error kind or null, rationale, and
citation indexes.  Its executable part is only predicates/effects/error; the
rationale is evidence/audit text, never an executable rule.

| Node | Exact minimal input projection | Model output that is allowed | Framework compiled/persisted output | Required next consumers |
| --- | --- | --- | --- | --- |
| `WorldArchitecture` | request need; relevant evidence claims/citation catalog; coverage gaps | `boundary{name,purpose,system_of_record,authority,actors}`; 1..16 entities with compact typed `FieldDeclarationDraft`; 1..8 tools with actor scope plus typed argument/result fields; known divergences + citation indexes | `WorldArchitecture`/`WorldArchitectureRef`; `SemanticCatalog`; framework-derived `ToolCouplingPlan`; compiled world/tool schemas; `known_divergences` | coupling derivation, every later Design node, ModelingGate, Builder Design projection, package world spec, Expand parent handoff |
| `SharedToolSemantics[group]` **only when the derived group contains >=2 tools** | exact ordered member tool indexes; derived shared-state summary; relevant citations; group identity from `ToolCouplingPlan` | exact echo of ordered indexes; `domains` for atomicity/concurrency/idempotency/ordering/compensation, each referring only to group members; nonempty error-policy coverage; semantics + citation indexes | `SharedToolContract{group_id, ordered_tool_indexes, domains, error_policy, digest}`; compiler validates exact group membership and required-domain/error coverage | only the group’s `ToolSemantics` shards; Design/implementation projection; world `rule_ir`; package/cold read; future Expand |
| `ToolSemantics[tool]` | exactly one frozen tool surface and its binding catalog; its committed shared contract if any; evidence/citations | exact `tool_index`; bounded local preconditions, nonempty transitions, postconditions, errors as `RuleDraft` | `ToolDraft` with framework rule IDs/bindings and `local_rules_digest`; `ToolSemanticGroupClosure` validates every shard against its group contract | WorldRules, TaskRequirement, ModelingGate; Builder/implementation contract; Integration/Judge local-rule proof; package rule IR/cold read; Expand |
| `WorldRules` | compiled architecture/cross-tool semantic catalog; local tool closure; unresolved coverage and citations | `initial_rules: tuple[RuleDraft]`, `invariants: tuple[RuleDraft]`; both may be empty only when no such relation exists | `WorldRuleSet` with global semantic bindings and digest; compiler rejects a local duplicate, tautology, schema restatement, or rule not expressible by the closed ADT | Curriculum/Task inputs, ModelingGate, Builder Design projection, package rule IR/cold read, Expand |
| `CurriculumPlan` | compiled actor/tool/capability catalog; world-rule closure; CoverageMap | ordered `task_families` (1..8): stable name, objective, actor index, nonempty tool indexes, 1..6 dimensions with 2..5 ordered levels, sampling intent, citations | `TaskCurriculum`; one framework ID/coordinate and `DifficultySchema` per family, with exact ordered key list/digest | exact per-family TaskRequirement work, ModelingGate, materializer protocol/package metadata, future Expand |
| `TaskRequirement[family]` | one frozen family coordinate and exact difficulty schema; semantic catalog; local/global rule closure | exact family index; public-goal field references; initial, nonempty success, failure, terminal `RuleDraft` tuples | one `TaskRequirement` per family, binding that schema digest; framework-derived public/initial-config schemas, instruction template, evaluator-goal binding, reward, termination and verification requirements | ModelingGate; Builder Design/implementation contract; materializer/runtime/Judge inputs; curriculum/materializer package metadata; Expand |
| `ModelingGate` | evidence + all exact committed architecture/group/tool/world-rule/curriculum/task refs | no model output | canonical `EnvironmentDesign` holding all compiled products, their digests/refs, coverage/fidelity/assurance state, and a selected local assurance plan only if one can be proved | CandidateGraph, lineage/provenance, Package and Registry |

The group and family counts are derived after Architecture and Curriculum,
respectively.  They are physical shards of the same named node family, not new
node kinds.  The canonical flow requires no shared node for a singleton-only
coupling plan; it requires one ToolSemantics shard per tool and one
TaskRequirement shard per committed family
([docs/agent-world-environment-generation.zh.md:596-643]).

### Indispensable fields versus honestly deferred detail

The following fields are indispensable; omitting any of them makes a package
unable to state which world it executes, which tool behavior it promises, or
which semantic delta a future Expand proposal makes.

| Area | Must be canonical and durable now | May be framework-derived or explicitly deferred |
| --- | --- | --- |
| World identity/state | boundary identity/authority/system-of-record; actors; entities, compact field meaning/type/presence/reference relationships; tool namespace, actor visibility and typed argument/result fields; known divergence with evidence | JSON Schema spellings, IDs, `required`, closed-shape mechanics, schema root assembly and binding indexes are compiler output |
| Tool behavior | per-tool precondition/transition/postcondition/error `RuleDraft`; binding catalog; shared-group membership and all required shared semantics/error policy | a generic transaction engine, generic conflict resolver, or a new universal state-machine language; only the closed ADT is allowed |
| Cross-tool/world behavior | initial-state and genuinely cross-entity/cross-tool RuleDrafts, with citations; empty only when there is no expressible extra relation | rules that the closed ADT cannot express: record as a cited `known_limit`/unverified obligation, not as free text pretending to execute |
| Task parameterization | ordered family name/objective, actor/tool scope, ordered difficulty dimensions/levels/sampling intent; one task rule set and bound schema per family | seeds, task IDs, generated initial configurations, public/sealed case partition, reward/termination objects and evaluator templates; these are framework-derived from the frozen source rules |
| Fidelity/assurance | evidence refs, known divergences, semantic digests, exact assurance status of every non-executed contract | reality-equivalence, complete production semantics, shared transaction/concurrency enforcement, all global-rule enforcement, coverage completeness, or a successful live end-to-end run |

In particular, detail is not “deferred” merely because it has been removed
from the model response.  It must either (a) be deterministically derived from
the compiled input, or (b) appear as a package-visible known limit with the
appropriate release-profile consequence.  A discarded model string or
unvalidated `groups` array is neither.

### Compilation, persistence, and consumers

1. **Architecture compiler.** Validate the closed source shape, names,
   references, and citations; assign stable catalog indexes and derive the
   coupling plan from namespace/shared fields.  Persist a typed architecture
   artifact plus its exact compiler projection.  A model cannot select groups.

2. **Group and tool closure.** For each derived multi-tool group, compile a
   `SharedToolContract`; for every tool compile its local RuleDrafts using its
   frozen binding catalog.  Then deterministically prove each group has exactly
   its expected shard members and no shared clause points outside the group.
   Persist group and tool artifacts separately, retaining their refs in
   `EnvironmentDesign`.  The tool-local proof already has a real runtime
   consumer: `evaluate_local_tool_semantics` executes the selected precondition
   and transition from the compiled `ToolDraft`
   ([agent_world/runtime.py:449-467]).

3. **World rule compiler.** Compile global RuleDrafts against the architecture
   catalog (not a free string list), reject duplicates/tautologies, and retain
   the typed IR/digest.  The existing `DesignContract.invariants: tuple[str,
   ...]` cannot be its persisted form ([agent_world/contracts.py:542-555]).

4. **Curriculum/task compiler.** Freeze family order and a difficulty schema
   per family before dispatching a task shard.  Each task artifact references
   the exact schema digest.  The existing task protocol already makes schema
   order observable during materialization ([agent_world/runtime.py:470-520]);
   it needs a per-family rather than first/only-task projection.

5. **ModelingGate.** Construct the sole `EnvironmentDesign` from exact refs and
   reject any absent group closure, tool closure, world-rule IR, curriculum
   coordinate, or task-family contract.  `LocalRuleAssurancePlan` remains a
   deliberately narrow selection, not evidence that every source rule runs.
   Current code makes this selection only for the first tool/first public step
   ([agent_world/design.py:1716-1834]); that first-item assumption is not a
   valid general Design contract.

6. **Candidate/Judge/package.** `CandidateExecutor._projection` and
   `compile_implementation_contract` must contain the entire compiled world,
   group/shared obligations, world-rule IR, curriculum and task-family map;
   the Builder receives them in its sole Design input, never verifier material.
   Package `world_spec.json`, `rule_ir.json`, and curriculum metadata must carry
   the same structures and refs, and Registry cold read must recompute digests
   and equality.  The present package carries local tool IR and a string
   invariant list only ([agent_world/candidate.py:1931-1970]) and cold read only
   knows that narrower shape ([agent_world/candidate.py:2358-2438]).

This makes every Direct-model semantic output affect a deterministic compiler,
a Builder-visible required input, and durable/package-verified provenance.  It
does not permit CandidateBuild to alter these facts, and it does not give a
model release or routing authority.

### Minimum assurance and non-claims

The smallest safe assurance taxonomy is:

- `compiled`: source shape, indexes, citations, group coverage, rule closure,
  difficulty schema and cross-artifact digest bindings are framework checked.
- `locally_executed`: only a designated, applicable local precondition and
  transition have current Integration/Judge trace evidence.  The present
  evaluator supplies exactly this narrow evidence
  ([agent_world/runtime.py:581-710]).
- `builder_required_unverified`: shared clauses, non-selected local rules,
  global initial/invariant rules, and task rules are mandatory Builder inputs
  and package facts, but no proof in this narrow repair says candidate code
  enforces them.
- `known_limit`: a source behavior that cannot be represented by the closed
  Rule ADT or cannot be checked under the current release profile; it is not a
  passing semantic claim.

The package fidelity/assurance material must name those non-claims rather than
silently present all Design facts as executed.  In particular, this repair
does **not** claim atomic execution, concurrency safety, idempotency, ordering,
compensation, shared error behavior, global invariant enforcement, complete
task reachability, reality equivalence, full coverage, or a live Registry
success unless a later, separately authorized proof implements and runs those
checks.  A release profile that requires any of those properties must fail
closed on `builder_required_unverified`/`known_limit`; merely serializing them
is not proof.

### Existing graph shape and smallest implementation impact

The two fixed Python graph declarations and their small transaction runner can
remain.  No dynamic graph engine, scheduler, generic rule engine, Repair,
Expand, Consumer, telemetry or permission subsystem is required.  This is
consistent with the execution map’s explicit two-graph boundary
([docs/direct-rewrite-execution-map.zh.md:30-60]).

The *logical node families* remain the same.  Their node contracts and the
Design executor cannot remain byte-for-byte unchanged: optional per-group and
per-family physical work must be represented by the existing shard-key/commit
mechanism, and the `shared_tools` port must become conditionally absent when
there are no groups rather than a mandatory fake empty model call.  That is a
contract/cardinality correction, not new graph machinery.

Smallest scoped files for the next plan:

- `agent_world/contracts.py`: replace lossy `DesignContract`/task/world-rule
  representations with compact typed compiled records for architecture,
  shared groups, world rules, curriculum and task families.  Preserve existing
  `RuleDraft`, `ToolDraft`, `DifficultySchema`, and `LocalRuleAssurancePlan`
  where they still apply.
- `agent_world/design.py`: implement the closed compilers and their exact
  projections; derive groups; skip absent shared work; shard per group/tool/
  family; build `EnvironmentDesign` only from all closures.
- `agent_world/graph.py`: retain two declarations/runner, updating only
  Design-node port/cardinality assertions/conditional edge handling required
  by those exact contracts.
- `agent_world/candidate.py`: extend the single Builder projection and
  implementation contract; serialize/cold-verify exact world/group/rule/
  curriculum/task structures and assurance states.
- `agent_world/runtime.py`: no generic evaluator rewrite.  Only change it if
  needed to take the selected family/tool from the new typed Design, and retain
  the explicit narrow local-rule evidence boundary.
- focused tests in `tests/test_graph_contracts.py`, Design/compiler tests,
  package cold-read/rejection tests, and existing runtime tests.  No live call
  is part of this plan.

Minimum tests/proofs:

1. architecture compilation rejects schema/control fields and produces a
   stable catalog/coupling plan;
2. zero multi-tool group results in **no** shared model transaction/artifact;
3. a multi-tool group has exact member/order/domain/error-policy coverage and
   fails for missing/extra/cross-group references;
4. every tool shard consumes exactly its group contract and group closure
   rejects a missing/mismatched shard;
5. world-rule strings/free-form/duplicate local rules are rejected; typed rules
   persist identically into rule IR;
6. two task families produce ordered, schema-bound distinct task artifacts;
   a changed schema invalidates only its task contract plus downstream Design;
7. Builder input, package bytes and Registry cold read contain the exact
   compiled structures/digests; omission or mutation fails cold verification;
8. the existing Integration/Judge proof still proves only the designated local
   rule and the fidelity metadata explicitly reports every unverified class.

### Anti-overdesign constraints

- Do not invent a third graph, node subclass hierarchy, YAML/JSON graph DSL,
  plugin registry, dynamic scheduler, callback bus, or generic schema/rule
  engine.
- Do not turn every field/rule into a model call.  Architecture remains one
  bounded transaction, shared semantics one transaction per derived multi-tool
  group, tool semantics one per tool, and task semantics one per frozen family.
- Do not add Repair/Expand/Consumer implementations.  The only future-facing
  work is retaining the typed immutable handoff those paths will consume.
- Do not add a second Builder/Judge, give candidate code verifier data, or
  convert unverified semantics into a model/Judge release verdict.
- Do not retain a free-form, uncompiled, prompt-only semantic payload merely
  to preserve a node.  If a source field cannot compile, persist, feed the
  Builder, package, and cold-read verify, it must be removed from the model
  contract or treated as a fail-closed known limit.
- Do not claim a static test, schema validity, model JSON, package-shaped zip,
  or this research audit proves the canonical natural-language-need to
  independently verified publishable EnvironmentPackage goal.

## Files found

- `docs/agent-world-environment-generation.zh.md` — canonical product and
  Direct world-modeling authority.
- `docs/direct-rewrite-execution-map.zh.md` — derived two-graph/executor map.
- `.trellis/tasks/08-10-direct-foundry-minimal-dag/node-contracts.md` — active
  binding source contracts for the Direct nodes.
- `agent_world/contracts.py` — current compact, lossy compiled Design types.
- `agent_world/design.py` — current Direct projections/compilers and Modeling
  Gate implementation.
- `agent_world/graph.py` — two fixed graph declarations and Design edges.
- `agent_world/candidate.py` — Builder projection, package metadata and cold
  verification consumers.
- `agent_world/runtime.py` — current local-rule execution assurance consumer.
- `.trellis/tasks/08-10-direct-foundry-minimal-dag/research/direct-r2-independent-check.md`
  — prior independent block record and actual consumer map.

## External references

None. Per dispatch constraint, no network, model, Agent SDK, candidate E2E, or
live call was used.

## Related specs

- `docs/agent-world-environment-generation.zh.md` §§3.2–3.5, 6, 11.1, 12.1,
  15.1–15.2.
- `docs/direct-rewrite-execution-map.zh.md` §§"Complete v1 共享的两个领域图"
  and "Direct 正常路径".
- `.trellis/tasks/08-10-direct-foundry-minimal-dag/node-contracts.md` §4.

## Caveats / Not Found

- This is a read-only design-contract audit.  It does not authorize a repair
  plan, implementation, node retry, test execution, or a real proof.
- Current local RuleDraft bindings are tool-local.  A typed global WorldRule IR
  needs a bounded architecture-level catalog projection; this should be added
  as a specific compiler record, not generalized into a rule-engine platform.
- The current candidate/Judge path selects the first tool and first task only;
  its evidence cannot establish all semantics above.  Keeping that proof is
  acceptable only with the stated `locally_executed` non-claim boundary.
