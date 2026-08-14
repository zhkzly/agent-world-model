# Repair Plan: precondition effects + conditional design-driven runtime

Lineage: Diagnosis Record research/diagnosis-integration-local-tool-semantics-mismatch.md
Trigger: real e2e failure run_386e4f07c70d4f61be9cafbf82edcc55
  (rejected / local_tool_semantics_mismatch, integration node)

## Product target restated

Natural-language EnvironmentRequest -> evidence-grounded design -> real
isolated runtime executing state transitions -> independent Judge -> immutable
Registry EnvironmentPackage -> safe Observe; released packages later feed
SFT/RL through the fixed Consumer/RPC episode interface.

## Diagnosis recap (one paragraph)

The frozen design contract for preview_lodging demands BOTH "status preserved"
(precondition effect) AND "status='ready'" (transition effect) on the same
success trace — a contradiction no candidate can satisfy. The tool_semantics
prompt forces every rule including preconditions to carry >=1 effect without
defining precondition-effect semantics; the modeling gate accepts the pair;
the framework-rendered design-driven runtime drops all `when` predicates and
applies every transition unconditionally; the integration checker requires
precondition effects to hold on the success trace. Retry from integration
reproduces the failure with zero LLM calls (deterministic).

## Scope classification

Coordinated cross-node (Direct slice only): Designer tool_semantics language
(C1) + Builder design-driven runtime renderer (C2) + Judge-side checker
alignment (C3'). No change to agent skills, graph wiring, package, Registry,
or Consumer. Repair/Expand/Consumer handoffs are preserved but NOT implemented
by this plan.

## C1 — Designer: preconditions are guards, they carry no effects

- design.py tool_semantics prompt: preconditions section documented as
  "guard rules: `when` states the required inputs/state; `effects` MUST be
  the empty array []. Precondition failure is framework-fixed semantics:
  reject the invoke and preserve state — never modeled as per-rule effects."
- design.py _compile_rules: add an effects-min parameter; preconditions compile
  with effects array[0..0] (reject any non-empty precondition effects with
  tool_semantics_invalid at $.preconditions[i].effects).
- `preserve` remains a legal operation elsewhere (world invariants, initial
  rules, postconditions); only the precondition section is restricted.
- Compile-path tests that feed non-empty precondition effects encode the old
  language and are updated to empty effects (deterministic regression updates,
  enumerated in Checks below).

## C2 — Builder: design-driven runtime evaluates `when` before effects

- candidate.py _design_runtime_data: embed per-transition rules as
  {when: [name-based predicates], effects: [...]} instead of a flat effect list.
- _DESIGN_RUNTIME_BODY do_invoke: before applying a transition's effects,
  evaluate its `when` predicates against request arguments and the current
  tool state (pre-invoke snapshot). Name resolution order: tool arguments,
  then the invoked tool's state fields. Predicates support the closed operator
  set already defined in the design language
  (exists/not_exists/eq/ne/lt/le/gt/ge/contains/not_contains) — a generic
  ~30-line evaluator over embedded data, NO hardcoded tool names or values.
- A `when` field that resolves to neither arguments nor the tool's state
  evaluates false (rule not applied); the integration checker is the backstop
  that detects any resulting semantic mismatch. Post_state/tool_result
  references in `when` resolve against the pre-invoke state (documented
  limitation; only transitions[0] is integration-checked today).
- No changes to handshake/reset/snapshot/close, result projection, or the
  materializer contract.

## C3' — Judge/Integration checker: preconditions check predicates only

- runtime.py _run_recipe: keep selecting the first precondition + first
  transition, but check the precondition via `_predicates` only (drop the
  `_effects` call for preconditions). Transitions keep predicates + effects.
- This makes the checker consistent with C1 AND with legacy frozen artifacts
  that still carry preserve-no-op precondition effects (the resume retry path
  reuses committed design heads; we must not require regenerating the design).
- Net checker diff is a few lines removed — this is the same patch-like
  coupling the user asked to simplify, not a new patch on top.

## Why this does NOT break the fixed SFT/RL interface (user question)

The fixed consumer interface is source-of-truth section 12: envpkg v3
world/rule_ir.json + Task Materializer v3 + the RPC episode protocol
(start -> step/result -> close); the framework-owned evaluator computes
reward/termination from rule IR; the training side never sees rule internals
or evaluator data. C1 keeps preconditions first-class: their `when` guards
still ship in world_spec.json/rule_ir.json and remain the stable semantic
input for action-legality decisions. What C1 removes is LLM-authored per-rule
effects on preconditions, replacing them with the framework-fixed semantics
"precondition fails => reject + preserve state". That is MORE stable as a
cross-package interface: rejection behavior becomes deterministic framework
contract instead of per-design content that can contradict transitions.
No ABI, schema key, package file, RPC message, or evaluator path changes.

## Producer -> consumer chain

- Designer (tool_semantics direct node) -> frozen ToolDraft.preconditions
  (contracts.py RuleDraft tuple, unchanged type; now zero effects).
- design.json projection (candidate.py + design.py _rules_for_llm) -> unchanged
  shape; builder/verifier agents see preconditions with empty effects.
- Builder renderer (candidate.py) -> candidate runtime.py -> integration/judge
  candidate process (unchanged protocol).
- runtime.py _run_recipe -> integration + judge; verifier IR unaffected
  (no precondition-effect consumer there; consumers listed in diagnosis).
- Package/Registry/Consumer: unchanged.

## Checks and proofs

Deterministic (pytest, offline):
- Updated/kept design_semantics tests: preconditions with effects=[] compile;
  non-empty precondition effects rejected at the right path.
- New candidate test: render design-driven runtime for a frozen tool contract;
  drive handshake/reset/invoke/snapshot in-process; assert a transition with a
  false `when` is not applied and a true `when` is applied (falsifiable).
- Full suite (281 tests) stays green except the enumerated language-encoding
  updates.

True-boundary proof (smallest real):
- resume run_386e4f07... --from integration (credentials exported):
  integration must pass; then judge/package/registry run for the first time.
- Observe after the terminal.

Explicit non-claims:
- We do NOT claim judge will pass (its task-rule semantics are checked
  against the new conditional runtime for the first time; a failure there is a
  new diagnosis).
- We do NOT implement rejection-path verification, cross-tool `when`
  references, or any Expand/Consumer feature in this plan.

## Files touched (implementation step, after allow)

- agent_world/design.py (prompt text + _compile_rules effects-min)
- agent_world/candidate.py (_design_runtime_data + _DESIGN_RUNTIME_BODY)
- agent_world/runtime.py (_run_recipe precondition check)
- tests/test_design_semantics.py (+ tests/test_direct_runtime.py or new
  renderer test) for the deterministic regressions
- task JSONL: implement.jsonl / check.jsonl allow record
