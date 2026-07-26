# World Rules E2E Diagnostic Fidelity — Design

## Decision

Treat the current `world_rules` failure as a feedback-fidelity defect first,
not as evidence that the Engineer should be retried or that the WorldSpec
should be rewritten. Repair the exact diagnostic boundaries proven to be on
the `WorldRules -> _compile_world_semantic_source` path, prove them with
constructed node-level inputs, then run one isolated real `test-node` target.

The task remains one E2E stage at a time. A fresh result may expose a prompt,
Skill, code, or feedback problem, but it does not authorize an unrelated
pipeline change.

## Confirmed Evidence

- The captured scope is `generate-job:ba03ff3dce4e303593c64e2d` and its
  target coordinate is `design/world_rules`.
- Its safe telemetry span is `designer | world_rules | design.world_rules |
  attempt 1 | failed | validation_failed | 176.7s`.
- Its frontier has one blocker:
  `framework_diagnostic_incomplete` at `semantic_output`; it lacks a
  source-facing repair identity.
- `validate_world_rules` calls `_compile_world_semantic_source`. The latter
  presently reaches seven validators with 26 direct `raise ValueError`
  sites: state shape (3), initial-state rules (3), tool-plan inventory (5),
  tool schema (2), tool-surface schemas (1), tool inventory (3), and world
  skeleton (9).
- `one_shot.run_structured_agent` intentionally keeps a bare-`ValueError`
  catch-all. It turns truly untyped framework errors into a safe,
  non-actionable `framework_diagnostic_incomplete`; this catch-all is not the
  edit target.

The handoff's claimed A/B=14 and C=12 split does not reconcile with the
verified 26-site inventory. Each site must therefore be classified from its
actual provenance rather than copied from that aggregate.

One confirmed local cause is evidence of a defect *class*, not permission to
fix only the first symptom. The unit test establishes the causal mechanism;
the subsequent inventory identifies all same-owner/same-boundary instances.
Every instance gets its own source path and direct proof before the compiler or
E2E layer is retested.

## Current WorldRules Audit Before the Fresh Run

A subsequent isolated, real `grok-4.5` `world_rules` invocation completed and
returned two typed `initial_state_rule_id_prefix` issues. This is not a provider
hang or an opaque fallback: its safe code, source path, condition, and expected
category were sufficient to locate the ownership boundary.

The all-layer audit of the actual production path found a coherent defect
cluster, rather than a single malformed output to patch around:

| Owner | Finding | Resulting repair |
|---|---|---|
| Prompt | The active `WorldRulesLeaf` projection omitted the exact section/family split and said nothing about framework ownership of optional `rule_id`. | State the reset-versus-cross-tool split, exact families, and that IDs must be omitted. |
| Skill | The tool-free Engineer Skill had detailed ToolSemantics guidance but no durable WorldRules ownership rules. | Add the same compact semantic/ownership guidance to the owning Skill. |
| Code / contract | The two WorldRules source compilers did not pass a deterministic ID prefix, so a model-supplied mechanical ID reached the later validator. | Canonicalize supplied IDs away and derive `rule:state:<ordinal>` / `rule:world:<ordinal>` in code. |
| Feedback | The current returned diagnostic was actionable. The bad ID is nevertheless framework-owned, so it must not become an Agent correction brief. | Mark prefix/duplicate checks non-actionable and retain typed observability. |

The same-boundary inventory is complete for this finding: the current
production prompt, generic prompt/envelope/correction projection, the
Engineer Skill, all three legacy WorldRules prompt builders, both WorldRules
sequence compilers, and persistence of `design.world_rules_source` were
reviewed. The generic base prompt, JSON envelope transport, and correction
brief are not defective for this mechanics-only condition. ToolSemantics
already derives its rule IDs and is outside this specific missing-prefix pair.

## Four-Way Diagnosis Gate

Before changing anything, classify the exact failure in this order:

| Owner | Evidence | Repair boundary |
|---|---|---|
| Feedback | A proposal-semantic failure reaches a generic code or lacks safe code/path/condition/category. | Add or repair typed diagnostics, frontier/scene projection, then re-run the same node. |
| Code / contract | A constructed valid input deterministically violates a framework-owned rule, or a source-to-compiled boundary has wrong ownership/closure. | Correct or refactor the deterministic boundary and its direct regression. |
| Prompt | The typed contract and Skill clearly state a requirement, but the prompt projection omits context or mechanically necessary frozen information. | Change only that node's prompt projection and prove the prompt/input contract; do not relax validation. |
| Skill | The contract is correct, feedback is actionable, and the role lacks durable guidance for producing the required semantic artifact. | Update only the owning role Skill, then test the same node. |

A refactor is acceptable whenever the evidence proves a structural code or
ownership problem. Existing structure is not a reason to retain an incorrect
boundary. Conversely, no code patch is justified merely because an E2E run
failed.

## Diagnostic Boundary Design

### Targeted sources

The direct `world_rules` compiler path will use
`StructuredValidationError(ValidationDiagnostic(...))` for every known
semantic or compiler invariant condition that can arise from these seven
validators. A validator aggregates all safe field-level issues for its local
source artifact before raising once.

Every issue must have:

- a stable framework-authored code;
- a source-facing path locating the faulty field or element;
- a static message, `violated_condition`, and `expected_category`;
- no Agent-supplied ids, field names, values, raw Pydantic context, provider
  output, secret, or endpoint data.

The code/condition/category registry remains
`_DESIGNER_SEMANTIC_CONTRACTS` in `control/validation.py`, so all safe
projections remain derived from one source of truth.

### Actionability ownership

Each of the 26 sites will be assigned one of two outcomes using its actual
input provenance:

1. **Proposal-owned** — an Agent can change the source semantic artifact
   without changing frozen framework inputs. It produces an actionable typed
   issue and can participate in the existing Scheduler-authorized correction.
2. **Framework invariant** — the condition can occur only if framework
   composition, frozen input, or compiler identity has drifted after earlier
   validation. It produces a distinct typed issue with `retryable=False`; it
   is observable but never becomes an Agent repair instruction.

The distinction is based on data ownership, not on whether the exception is
currently a `ValueError`. The prior catch-all stays as the safety net for any
future untyped framework defect.

The current call graph resolves the direct-site inventory more precisely than
the handoff's aggregate: `world_rules_definition.allowed_mutation_roots` is
only `/initial_state_rules` and `/invariants`. Of the three explicit checks in
`_validate_initial_state_rules_draft`, only rule **family** is
proposal-owned. Prefix and duplicate identity checks are framework invariants:
the compiler now discards an Agent-supplied optional `rule_id` and derives the
stable identity from the frozen section plus ordinal. The other 23 consume
frozen Architecture/ToolSemantics output or framework-composed values and are
also framework invariants. They retain an observable typed identity but are
`retryable=False`; routing any of these checks back to WorldRules would ask the
Agent to change data it cannot own.

Transitive failures from called contracts are a separate inventory. They will
be added only if a direct constructed test proves that they cross this node
without a safe diagnostic; they are not silently folded into the 26-site
claim.

### Scope boundaries

- Do not modify unrelated Judge/Builder paths or the known generic fallback
  sites.
- Do not add a retry, change repair budgets, weaken any validator, or alter
  the immutable prompt merely to get another sample.
- Do not turn a framework-invariant error into an actionable semantic repair.
- Do not persist rejected provider payloads to make a test case; use a typed,
  constructed equivalent input.

## Test Design

`tests/agent_world/test_designer_world_composition.py` already provides
`portable_counter_contracts` and a complete
`WorldSemanticSourceIRDraft` construction pattern. Tests will begin from that
valid baseline and poison only one field/condition.

For every migrated site, direct tests assert:

1. the expected `ValidationDiagnostic.validation_phase`, code and exact path;
2. proposal-owned issues are actionable, framework-invariant issues are not;
3. code/message/condition/category do not contain the poisoned Agent value;
4. the valid control input continues to compile.

An integration regression calls `_compile_world_semantic_source` with a full,
otherwise-valid `WorldSemanticSourceIRDraft`, proving that a poisoned target
cannot fall into `one_shot`'s generic fallback. A narrow structural guard may
inspect only the seven target validators to ensure no direct `raise
ValueError` remains there. Existing tests proving that an unrelated bare
`ValueError` remains non-actionable must stay unchanged.

Only after the deterministic suite is green will the real test-node be run.
The test-node remains diagnostic-only and non-releasable.

For this audit, the deterministic gate includes a complete
`compile_world_rules` integration input that deliberately supplies arbitrary
Agent IDs and proves both the persisted source canonicalization and the
derived executable IDs. It also covers wrong section family as the remaining
Agent-actionable WorldRules source failure.

## Fresh Isolated Confirmation

The one permitted fresh `test-node` execution completed in its own marked,
non-releasable state copy. Safe observability for
`design.world_rules.world_rules` reports `head_status=committed`,
`validation_status=passed`, `frontier_progress=resolved`, no failure code,
and an empty frontier. The enclosing scene is also `committed` with no stuck
coordinate. This proves this repaired node only; it does not claim Builder,
Judge, Registry, or the remaining pipeline are complete, and no downstream
coordinate was dispatched.

## E2E Feedback Loop

```text
safe telemetry + frontier + scene
        -> four-way ownership decision
        -> one node / one validator / one constructed regression
        -> focused tests pass
        -> one fresh test-node execution of that coordinate
        -> inspect safe terminal evidence
        -> next single-owner decision, or stop
```

If the fresh node is still `failed` with a typed proposal issue, decide from
the exact issue whether the next change belongs to prompt, Skill, or code. If
it is `error`, use the infrastructure/transport lane instead of changing
WorldSpec. If it returns generic feedback again, repair feedback before any
retry. If there is no strict frontier progress or the pattern oscillates, stop
and record the causal diagnosis rather than patching or sampling again.

## Operational Safety

No real run occurs until deterministic validation passes. Before a live
test-node run, verify the required isolation precondition; its absence is an
external infrastructure blocker, not a reason to weaken Judge/isolation.
Only safe telemetry columns and frontier projections are read into task notes.
No commit or push is part of this task without a separate user instruction.
