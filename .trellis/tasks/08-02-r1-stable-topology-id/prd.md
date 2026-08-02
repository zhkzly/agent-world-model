# R1 stable topology_id (release unblocker)

## Goal

A committed generation closure MUST stay advanceable: dispatching a descendant
(e.g. `judge.release_assurance`) under a re-derived final manifest for the same
scope MUST NOT fail with `parent_commit_inactive`, provided the underlying node
definitions and input closure are unchanged.

## Root cause (CORRECTED by real diagnosis 2026-08-02 — supersedes the original "topology_id suffix" theory)

The original PRD/memory assumed re-derivation mints a fresh per-dispatch
`topology_id` → different `graph_digest` → orphaned commits. **Ground truth
disproves that.** `topology_id`s are already deterministic content-functions.

The real divergence is `definition_digest`. For the SAME coordinate, the
production final manifest (`410a604e`, `topology:direct-final:…`) and the
`test-final-node` re-frozen manifest (`9c82e8ad`, `topology:test-final-node:…`)
bind **different WorkDefinitions**, differing only in:

1. `repair_policy` budgets — production `maximum_infrastructure_retries=3 /
   maximum_model_fallbacks=2 / maximum_total_repair_attempts=13` vs diagnostic
   re-derivation `1 / 1 / 3` (config-derived, tighter single-shot budgets).
2. `*_revision_id` — `leaf_code_revision()` (agent_world/control/code_revision.py:99)
   hashes the CURRENT framework module source. Framework code was edited between
   the original run and now, so re-derivation bakes new revision ids
   (`framework.judge-release-assurance.a2449a4e…` → `…f37b41a5…`;
   `framework.validator-release-assurance.4482837d…` → `…44c0cd1b…`).

`definition_digest = content_digest()` folds in BOTH (repair_policy is in the
full digest; revision ids are in both `definition_digest` and `acceptance_digest`).
The active-commit gate (work_store.py:732-737) requires `head.definition_digest
== definition.definition_digest`, so any divergence orphans the parent.

**Proof the production manifest is already correct:** `release_assurance`'s 3
direct deps (candidate_build / runtime_integration / verifier_bundle) are all
`committed`, `invalidated_by=None`, and their `definition_digest` matches the
production manifest `410a604e` byte-for-byte. Dispatching against the production
revision (`--manifest-revision sha256:410c9d13…`) clears `parent_commit_inactive`
entirely (it then hits a separate, unrelated runtime dispatch error — out of R1
scope).

**Source of divergence:** `DiagnosticFinalNodeRunner._final_graph`
(test_node.py:6546) calls `complete_generation_work_graph(...)`, which
regenerates ALL final definitions from live compiler functions (current revision
ids + config repair budgets) instead of reusing the committed production
definitions already retained in the closure.

## Requirements

- R1.1: `test-final-node` re-derivation MUST reuse the exact committed
  WorkDefinition (its `repair_policy` and `*_revision_id`, hence its
  `definition_digest`) for any coordinate that already has a committed head in
  the same scope closure. Only genuinely new/overridden nodes (e.g. an explicit
  proposal-budget override target) may carry a fresh definition.
- R1.2: With R1.1, the re-frozen final manifest reproduces the committed
  closure's `graph_digest` for the shared nodes, so prior commits stay active
  and no shadow manifest is minted for the passthrough case.
- R1.3: Genuine overlays (budget override, refresh-current-implementation,
  profile change) MUST still differ — their divergence is intentional and
  content-derived, not a passthrough artifact.
- R1.4: Do NOT loosen the active-commit check in work_store.py. The fix makes
  the INPUTS to the rule stable, per the user-approved (b) decision.

## Acceptance Criteria

- [ ] AC1: Unit test — re-deriving the final graph for a committed scope reuses
  the committed definitions; `definition_digest` for candidate_build /
  release_assurance / runtime_integration equals the committed head digest; a
  genuine budget-override target legitimately differs.
- [ ] AC2: Integration (real) — dispatch `release_assurance` from the committed
  closure clone WITHOUT `--manifest-revision` (or against the re-derived
  manifest) and observe NO `parent_commit_inactive` and NO
  `test_descendant_target_ambiguous` from a benign passthrough re-derivation.
- [ ] AC3: `pytest tests/agent_world/test_test_node.py` regresses no
  currently-passing test (baseline 61 pass).

## Notes

- The separate runtime dispatch failure hit after clearing the topology wall
  (`test_descendant_nonterminal_dispatch_failure`, a swallowed WorkRuntimeError)
  is NOT part of R1 — it is a downstream scheduler/execution issue to classify
  on its own.
- Related memory: `descendant-topology-parent-commit-inactive` (root cause now
  corrected here), `task-runtime-resume-topology-recovery-plan`.
