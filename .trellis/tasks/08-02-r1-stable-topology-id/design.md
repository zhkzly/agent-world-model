# Design — R1 stable definition identity across re-derivation

## Confirmed mechanism (ground truth, not theory)

1. Active-commit gate `require_active_commit` (work_store.py:731-737) compares
   ONLY: `head.work_id`, `head.definition_digest`, `head.acceptance_digest`,
   `head.input_fingerprint`.
2. `input_fingerprint = work_input_fingerprint(refs)` (work.py:132-137) =
   `sha256(sorted(ref.revision_id for ref in refs))`. It hashes ONLY the input
   artifact revision ids — NOT `graph_digest`, NOT `topology_id`.
   → **`topology_id` divergence cannot orphan a parent.** It only triggers
     `test_descendant_target_ambiguous` when two retained manifests carry the
     same coordinate.
3. Therefore the ONLY thing that orphans a committed parent is a differing
   `definition_digest` (or `acceptance_digest`). Both are content digests of the
   WorkDefinition (work.py:618-663).
4. `DiagnosticFinalNodeRunner._final_graph` (test_node.py:6546) →
   `complete_generation_work_graph(...)` regenerates every final definition from
   live compiler functions, so `repair_policy` (config-derived) and
   `*_revision_id` (`leaf_code_revision` over current source) differ from the
   committed production definitions → new `definition_digest` → orphan.

## Fix (reconcile against committed definitions)

After compiling the fresh final graph (`base_final_graph` and any
budget-overridden `final_graph`), **replace each definition whose coordinate
already has a committed head in the same scope with the exact committed
WorkDefinition** recovered from that head's commit, then re-compile the graph
from the reconciled definition set. Only coordinates that are genuinely new, or
that the diagnostic explicitly overrides (proposal-budget target,
refresh-current-implementation, profile change), keep the freshly-compiled
definition.

### Where
- New helper (test_node.py, near `_final_graph`): given `app`, `scope_id`, and a
  compiled `GenerationWorkGraph`, return a new graph whose definitions are, per
  coordinate: the committed head's stored definition if one exists and the
  freshly-compiled definition is a benign passthrough (same coordinate,
  compatible acceptance contract); else the fresh definition.
- Recover the committed definition via the head's commit: `head.commit_ref` →
  `WorkCommit` → the stored `control.work_definition` artifact whose
  `content_hash == commit.definition_digest` (mirror the existing recovery in
  `work_store._require_commit_definition` / `test_node._definition_for_binding`,
  which already recover a definition by exact `definition_digest`).
- Apply reconciliation to `base_final_graph` (test_node.py:6283) so the
  passthrough path (no budget override) freezes a manifest whose shared nodes
  reproduce the committed `definition_digest`s. The budget-override branches
  (6336/6346) intentionally change ONE agent target's envelope — reconcile all
  OTHER nodes, leave the overridden target fresh.

### Overlay preservation (R1.3)
- Budget override target: excluded from reconciliation (its divergence is the
  intended overlay).
- `refresh_current_implementation` / profile change: these deliberately record
  current revisions; they are handled by the descendant runner, not the final
  freeze — leave their explicit paths untouched. Reconciliation only reuses a
  committed definition when the fresh one is a benign passthrough for that exact
  coordinate.

## Boundaries / invariants preserved
- Do NOT modify `work_store.py` active-commit logic (R1.4).
- Do NOT modify `complete_generation_work_graph` (shared production compiler);
  reconcile at the diagnostic call site only, so production freeze is unchanged.
- The reconciled graph must still `GenerationWorkGraph.compile(...)` cleanly and
  round-trip to a manifest; the committed definitions came from a compiled
  production graph for the same scope, so structural compatibility holds.

## Tradeoffs / risks
- Risk: a committed definition and the fresh compile could differ structurally
  (not just repair/revision) if the framework topology genuinely changed. Then
  reusing the committed one is still correct for advancing THIS closure (the
  parents were committed under it), and unit test AC1 pins the expected reuse.
- Risk: recovering by `definition_digest` requires the definition artifact to be
  retained in the clone. It is — the commit retains it (proven: production
  manifest binds all committed parents byte-exactly).

## Test strategy
- AC1 unit: build/reuse a committed-closure fixture (or the real clone in a
  guarded integration test); assert reconciled final graph's candidate_build /
  release_assurance / runtime_integration `definition_digest` == committed head
  digest; assert a budget-override target differs.
- AC2 real: dispatch release_assurance from the clone without forcing the
  production revision; expect no `parent_commit_inactive` / no
  `target_ambiguous` for the passthrough.
- AC3: `pytest tests/agent_world/test_test_node.py -q` stays ≥61 pass.
