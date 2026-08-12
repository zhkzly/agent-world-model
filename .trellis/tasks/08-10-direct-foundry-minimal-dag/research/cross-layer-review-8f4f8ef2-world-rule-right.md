# Research: cross-layer-review-8f4f8ef2-world-rule-right

- Query: Determine whether plan `8f4f8ef20126864a40cc9f400496d7e4a96824c8489ed433c68a7af53caa3ab1`, revision 1/2, makes the smallest correct repair to the inverted predicate-right `isinstance` condition and supplies a sufficient failed-`WorkRecord` regression.
- Scope: internal, read-only cross-layer critic; only the existing predicate-right acceptance condition and its WorldRules failed-`WorkRecord` regression.
- Date: 2026-08-11

## Decision

Decision: block

- Plan digest: `8f4f8ef20126864a40cc9f400496d7e4a96824c8489ed433c68a7af53caa3ab1` (SHA-256 recomputed from `world-rule-predicate-right-plan.md`).
- Plan lineage / revision: `world-rule-predicate-right`, revision 1/2; first review of this digest.
- Scope classification: local validation-boundary correction and its existing Direct-node failure-record regression. No Prompt, node, graph, child, live-proof, or other-validator change is reviewed or authorized.
- Trigger / evidence: static diagnosis `diagnosis-world-rule-predicate-right.md` and the final whole-diff block. No relevant real execution or Observe scene exists; none is inferred.
- Affected trust boundary: framework compilation of the closed `PredicateDraft.right` object before a Direct `world_rules` proposal may become a committed rule, and conversion of rejected output into the existing safe terminal record.

## Findings

### Single blocking finding — the proposed one-token inversion is not a closed-object or safe-failure repair

The current condition at `agent_world/design.py:345-378` accepts non-dictionaries through `not isinstance(right, dict)`, then reaches `dict(right)`. The plan proposes changing only that operand to `isinstance(right, dict)` (`world-rule-predicate-right-plan.md:9-18`). The resulting first branch is effectively:

```text
isinstance(right, dict) OR exact-literal-shape(right)
```

It therefore accepts every dictionary before either exact shape is checked. For example, `{}` or `{"kind": "unknown"}` passes the first branch and is committed as `PredicateDraft.right` at `agent_world/design.py:378`. That does not satisfy the required closed union of literal object and semantic-reference object (`node-contracts.md:285-307`).

It also does not safely reject every non-object. When `right` is `None` or an integer, evaluation proceeds to `set(right)` and can raise raw `TypeError`; when it is `["kind", "value"]`, the set comparison can succeed and then `right.get(...)` can raise raw `AttributeError`. `GraphRunner.execute` only persists terminals raised as `NodeExecutionError` (`agent_world/graph.py:487-539`), whereas `DesignError` is that safe subtype (`agent_world/design.py:75-96`). Thus the proposed one-token edit can still bypass the intended validation/Finding/failed-`WorkRecord` path.

The action required from the plan writer is bounded: revise the one existing condition so the literal branch is guarded by both object type and its exact literal shape, while retaining the existing semantic-reference branch. Do not add a helper, schema, Prompt, node, retry, or control-plane mechanism. Name the actual shared helper (`_compile_rules`, not `_rules`) so the change target is unambiguous.

## Product target and impact chain

The preserved target is: turn an arbitrary natural-language `EnvironmentRequest` into an evidence-grounded executable environment, independently verify it in an isolated boundary, publish an immutable Registry `EnvironmentPackage`, and expose only safe facts through Observe. This bounded correction advances only the honest rejection of malformed Direct WorldRules output; it is not a release or E2E claim.

```text
Direct WorldRules proposal
  -> existing predicate-right closed-shape compiler
  -> DesignError(world_rules_invalid, exact right path)
  -> GraphRunner.execute
  -> validation + Finding + failed WorldRules WorkRecord
  -> honest Design terminal; no committed WorldRules artifact
```

`world_rules` is a Direct LLM node whose only intended output is the closed WorldRules source draft (`design.md:304-317`; `direct-rewrite-execution-map.zh.md:71-76`). The source of truth requires WorldRules to be compiled under the closed Rule ADT rather than accepted as arbitrary model structure (`docs/agent-world-environment-generation.zh.md:601-607`). `GraphRunner.fail` already supplies the framework-owned validation, Finding, and failed `WorkRecord` once the compiler raises `DesignError` (`agent_world/graph.py:699-784`). The plan must restore that pre-existing path, not alter its owner or persistence contracts.

## Owner and consumer compatibility

| Owner / consumer | Compatibility fact required by a revised plan |
| --- | --- |
| Designer / WorldRules compiler | It remains the sole framework compiler of the Direct LLM's RuleDraft proposal; accepted `right` values must be exactly one of the two frozen object shapes. |
| GraphRunner | No change is needed if malformed values consistently become `DesignError`; its existing `NodeExecutionError` handling persists the terminal evidence and failed work record. |
| Finding / WorkRecord / Observe | Their schema, owner, route-free status, and safe code remain unchanged. The regression must demonstrate the existing records, not create a new failure representation. |

## Smallest permitted revision and proof

Before implementation, revise the plan and obtain a new digest/review. Its focused regression must use the existing Direct WorldRules transaction and prove all of the following for this one predicate-right condition:

1. Both allowed shapes still compile: exact literal and exact frozen semantic reference.
2. A malformed object is rejected rather than accepted, including a shape such as `{}` or an unknown/missing `kind` form.
3. Representative non-objects that exercise the type guard, including `None` and a sequence such as `["kind", "value"]`, yield `DesignError` rather than any raw `ValueError`, `TypeError`, or `AttributeError`.
4. Two rejected WorldRules proposals take the existing one local correction and then persist the existing failed validation, route-free Finding, and failed `WorkRecord` with `world_rules_invalid`; no WorldRules output commits.

This remains a deterministic local boundary proof. No live Direct, Repair, Expand, Consumer, Candidate, Judge, Registry, or other-node proof is permitted by this review.

## Files found

| Path | Relevance |
| --- | --- |
| `AGENTS.md` | Source-of-truth precedence and independent critic gate. |
| `docs/agent-world-environment-generation.zh.md` | Canonical closed-Rule ADT and Direct compiler ownership. |
| `docs/direct-rewrite-execution-map.zh.md` | Direct WorldRules executor/authority map. |
| `.trellis/tasks/08-10-direct-foundry-minimal-dag/{prd,design,implement,node-contracts}.md` | Current Direct node, closed PredicateDraft, provenance, and non-scope contracts. |
| `research/direct-final-whole-diff-check.md` | Static release-blocking finding. |
| `research/diagnosis-world-rule-predicate-right.md` | Static causal diagnosis; no Observe scene. |
| `research/world-rule-predicate-right-plan.md` | Reviewed plan revision and verified digest. |
| `agent_world/design.py` | Predicate compiler, `DesignError`, and Direct WorldRules transaction. |
| `agent_world/graph.py` | Existing safe failure persistence. |
| `tests/test_design_semantics.py` | Intended focused Direct-transaction regression surface. |

## Related specs and references

- Closed PredicateDraft union and framework compilation: `node-contracts.md:282-307`.
- WorldRules ownership and bounded source output: `design.md:304-317`; `direct-rewrite-execution-map.zh.md:71-76`.
- Safe failed-work requirement: `node-contracts.md:35-74`; `agent_world/graph.py:496-539`, `:699-784`.
- External references / versions: none consulted; this is an internal deterministic validation contract.

## Caveats / Not Found

- No code or test was run; the review is static and read-only.
- This `block` identifies only the proposed condition's failure to close the predicate-right object contract and its resulting insufficient failure-record regression. It makes no finding about any other validator, Prompt, node, child, or live path.
- The next permitted gate is one revised plan (revision 2/2) that addresses the single finding, followed by a fresh independent critic review. No implementation is authorized by this record.
