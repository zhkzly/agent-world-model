# R1 repair plan — close the per-tool semantic handoff

## Trigger and predecessor

This revises blocked digest `8dbbac0d...` after
`cross-layer-review-8dbbac0d-tool-semantics.md`. The real terminal and
Diagnosis Record remain unchanged. The repair is one coordinated Direct
Design-to-Judge contract correction, not a retry or later-child feature.

## Goal

Make `tool_semantics[tool]` produce the smallest retained, executable per-tool
behavior contract required by CandidateBuild, independent Judge, package Rule
IR and the future Expand ToolSemantics genotype. Framework derives frozen tool
surface facts; the model no longer echoes argument/result arrays or emits a
discarded success sample.

## Closed source and compiled contracts

Add narrow immutable values in `agent_world/contracts.py`:

```text
SemanticBinding:
  index: positive one-based int
  source: "argument" | "tool_result" | "pre_state" | "post_state"
  name: frozen tool argument/result-field name

PredicateDraft:
  left_semantic_index: int
  operator: "eq" | "ne" | "lt" | "le" | "gt" | "ge" |
            "contains" | "not_contains" | "exists" | "not_exists"
  right: {"kind":"literal","value": JSON scalar/list} |
         {"kind":"semantic_ref","semantic_index": int}

EffectDraft:
  target_semantic_index: int
  operation: "set" | "increment" | "decrement" | "add" | "remove" |
             "preserve" | "reject"
  value: JSON scalar/list | {"kind":"semantic_ref","semantic_index":int} | null

RuleDraft:
  when: tuple[PredicateDraft]
  effects: nonempty tuple[EffectDraft]
  error_kind: bounded snake identifier | null
  rationale: bounded nonempty text
  citation_indexes: unique tuple[positive int]

ToolDraft:
  existing framework-derived name/description/arguments/result_fields
  tool_index: exact one-based frozen tool index
  bindings: tuple[SemanticBinding]
  preconditions: tuple[RuleDraft]
  transitions: nonempty tuple[RuleDraft]
  postconditions: tuple[RuleDraft]
  errors: tuple[RuleDraft]
  local_rules_digest: canonical SHA-256 over index/bindings/four rule sections
```

These values are only the existing RuleDraft source contract and its compiled
per-tool closure. Do not add a reusable rule framework, plugin interface,
registry, DSL loader or node subclass.

## Framework-owned binding catalog

For each frozen WorldArchitecture tool, `agent_world/design.py` deterministically
builds one local catalog in this exact order:

1. each argument as `argument`;
2. each result field as `tool_result`;
3. each result field as `pre_state`;
4. each result field as `post_state`.

Each entry binds its exact tool-local name and receives the next one-based
index. This is the minimum catalog constructible from the already-frozen tool
surface; WorldArchitecture model output does not change. Candidate private
snapshot state uses the closed namespace
`state.tools[tool_name][result_field]`, so pre/post bindings are executable
without inventing another state-schema model turn.

## DesignGraph producer change

1. Add `evidence` to the existing `tool_semantics` input ports and one
   `research_synthesis.evidence -> tool_semantics.evidence` edge. Pass only the
   relevant bounded claims/source indexes alongside `tool_index`, exact tool,
   binding catalog and optional shared contract.
2. Replace the current four-key echo output with exactly:

   ```text
   {tool_index, preconditions, transitions, postconditions, errors}
   ```

   The Prompt/output contract states every field, enum and bound: 0–6 rules in
   optional sections, 1–6 transitions, 0–6 predicates per rule, 1–6 effects,
   rationale <=300 characters and 0–8 unique citation indexes.
3. The node-local compiler validates exact tool index, all binding and citation
   references, closed right/value alternatives, finite JSON values, operator
   and operation enums, section-specific reject/error use, and at least one
   non-`preserve` transition effect. Framework then attaches frozen surface,
   bindings and canonical digest to `ToolDraft` and commits it.
4. Reuse small private parse/evaluate helpers inside `design.py`/`runtime.py`;
   do not add generic schema generation or a third graph. Keep one correction.

## Existing consumer closure

1. `world_rules` receives compiled local rules. Its existing output remains the
   additional-global-invariant section, but the compiler rejects an invariant
   canonically identical to any retained local rule. It does not redefine or
   replace tool transitions.
2. `task_requirement` receives the same frozen `ToolDraft`s under its existing
   closed scenario contract. Because that model output has no local-rule
   fields, extra transition/error keys are rejected; framework retains the
   exact local-rule digest in the resulting Design dependency closure.
3. `modeling_gate` and `DesignContract` retain the expanded immutable tools.
   `compile_implementation_contract` adds one fixed `tool_semantics` section
   containing the exact bindings/rules/digests plus the required private
   snapshot namespace. BuildPlan, CandidateBuild and VerifierIntent therefore
   see the same frozen semantics without a new input path.
4. Update only the existing `engineer-environment-codegen` Runtime Skill to
   require implementation of that fixed semantic section and snapshot
   namespace. It gains no Judge/release authority and no new tool.
5. The existing Runtime protocol records one safe private pre-snapshot,
   invocation result and post-snapshot trace for the selected public step.
   A narrow framework evaluator resolves only the declared bindings and checks
   applicable precondition/transition/postcondition effects. Judge adds one
   required `local_tool_semantics` gate and requires at least one transition
   plus one precondition or error rule to be exercised. It does not route,
   repair or interpret free-form rationale.
6. Package `world/world_spec.json` carries each tool's local-rules digest;
   `world/rule_ir.json` carries canonical bindings/local rules plus global
   invariants and the aggregate local-rules digest. Registry cold-read
   canonical-parses this closed shape, recomputes all local/aggregate digests,
   and rejects a missing or mismatched closure before publication.
7. Future Expand compatibility is only the stable local-rules digest/value:
   changing retained semantics changes it; reformatting framework-derived
   surface data does not. No Campaign/operator code is added. Consumer remains
   package-only and unchanged.

## Files

Product changes are limited to:

- `agent_world/contracts.py`
- `agent_world/design.py`
- `agent_world/graph.py`
- `agent_world/candidate.py`
- `agent_world/runtime.py`
- `agent_world/runtime_skills/engineer-environment-codegen/SKILL.md`
- focused existing tests in `tests/test_graph_contracts.py`,
  `tests/test_direct_runtime.py`, and `tests/test_direct_release.py`

Do not add a module, graph, model route, retry, profile, permission layer,
callback, automatic Repair, Expand or Consumer implementation.

## Deterministic acceptance

- Producer tests capture the real model payload/output contract and reject:
  missing/empty transitions, wrong tool index, unresolved binding/citation,
  unknown predicate/effect enum, invalid value alternative, no-op transition,
  and the old architecture-echo object.
- Closure tests prove exact local rules/digest survive Design -> implementation
  contract -> Builder/Verifier projections -> Judge gate -> package Rule IR;
  missing/tampered local rules or digest fail Registry cold-read.
- Separation tests prove WorldRules duplicate rejection, TaskRequirement closed
  output rejection of local-rule redefinition, and semantic digest change only
  when retained local semantics change.
- Existing graph, supply-chain, Runtime, provenance, secret and legacy-firewall
  checks remain green; code-size review rejects helper/abstraction growth not
  needed by the exact contract.

## True-boundary proof order

1. One fresh real Luna `tool_semantics` shard must pass the revised compiler;
   read its Observe terminal and claim only that shard.
2. Continue one fresh CandidateBuild through offline install and isolated
   Judge. The trace must pass the required `local_tool_semantics` gate while
   exercising one retained transition and one retained precondition or error.
3. Only then rerun a fresh full Direct request to Registry cold-read and terminal
   Observe. Any new failure begins a new diagnosis; no blind retry.

## Non-goals and non-claims

No general Rule engine, arbitrary expression language, new state-schema turn,
third graph, scheduler, dynamic routing, extra model attempt, model switch,
automatic Repair, Campaign, multi-parent logic, Consumer, trainer or
compatibility path. This plan does not claim Candidate, Judge, Registry or E2E
success before their real proofs.
